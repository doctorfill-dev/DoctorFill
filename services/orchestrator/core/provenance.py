"""
core/provenance.py — Rattache une valeur extraite au texte dont elle provient.

Le signal de confiance dérivait auparavant du score de rerank. Mesuré sur un job
réel (112 champs) : ce score note la pertinence des extraits, qui ne sont que la
source *secondaire* du prompt d'extraction — la synthèse médicale en est la
source principale. Les champs correctement remplis y notaient même plus bas
(médiane 0.0083) que les champs restés vides (0.0165). Aucun seuil ne pouvait
rattraper ça : le signal mesurait une entrée qui ne décide pas du résultat.

On mesure donc sur le résultat : la valeur produite se retrouve-t-elle dans le
texte des documents, et où ? Tout est déterministe — pas de seuil, pas de
modèle, pas de seconde passe LLM. Une valeur est attestée ou elle ne l'est pas.

Le sous-produit compte autant que le verdict : quand un ancrage est trouvé, on
renvoie le document, la page et le texte alentour. Un avertissement qu'on peut
vérifier d'un clic n'est plus un avertissement, c'est un outil.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# --- Verdicts, du plus fort au plus faible -----------------------------------
# La valeur est présente mot pour mot dans la citation, elle-même retrouvée.
VERIFIED = "verified"
# La valeur figure dans un document, mais pas à l'endroit cité.
ATTESTED = "attested"
# La citation est réelle, la valeur en est une reformulation ou une déduction.
INFERRED = "inferred"
# La citation ne se retrouve nulle part : le modèle a pu l'inventer.
UNVERIFIED = "unverified"
# Valeur trop courte pour qu'une recherche textuelle prouve quoi que ce soit
# (« M », « F », « 50 ») : le dire plutôt que de laisser croire à une preuve.
NOT_CHECKABLE = "not_checkable"

# Longueurs minimales, en caractères normalisés, pour qu'une recherche ait un
# sens. Basses volontairement : le LLM cite souvent court (« Nom DOE », « Vaud »),
# et un seuil à 12 déclarait ces citations introuvables sans les avoir cherchées.
# En dessous de SHORT_MATCH_CHARS on exige des frontières de mot, ce qui suffit à
# écarter les correspondances fortuites.
MIN_QUOTE_CHARS = 4
MIN_VALUE_CHARS = 2
SHORT_MATCH_CHARS = 12

# Texte rendu autour d'un ancrage, de part et d'autre.
EXCERPT_MARGIN = 140

# Longueur à partir de laquelle on retente la recherche sans aucun espace.
# La couche texte des PDF coupe des mots au milieu (« complica tion », « traite
# ment », « ar térielle ») : le LLM lit à travers, une comparaison exacte non.
# Assez long pour qu'une correspondance sans frontières de mot reste sûre : à
# cette longueur, une coïncidence sur une suite alphanumérique continue est
# négligeable, y compris sur un dossier de plusieurs centaines de milliers de
# caractères.
SQUASHED_MIN_CHARS = 16

# Découpe d'une citation en propositions, quand elle n'est pas retrouvée entière.
# Le modèle recompose souvent plusieurs fragments réels en une seule « citation ».
_SEGMENT_SPLIT = re.compile(r"[;.]\s+|\n+")

_PAGE_HEADING = re.compile(r"^##\s*Page\s+(\d+)\s*$", re.MULTILINE)

_MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre")

_DATE_PATTERNS = (
    re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$"),   # 15.03.2025
    re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$"),   # 2025-03-15 (inversé)
)


def normalize(text: str) -> str:
    """
    Forme comparable d'un texte : minuscules, sans accents, ponctuation réduite
    à des espaces.

    Réduire la ponctuation plutôt que la supprimer évite de souder deux nombres
    voisins : « 756.1234 » devient « 756 1234 », pas « 7561234 ».
    """
    return _normalize_with_map(text)[0]


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """
    Comme `normalize`, mais conserve pour chaque caractère normalisé son index
    dans le texte d'origine — c'est ce qui permet de restituer un extrait lisible
    à partir d'une correspondance trouvée sur la forme normalisée.
    """
    out: list[str] = []
    origin: list[int] = []
    pending_space = True
    for index, char in enumerate(text):
        decomposed = unicodedata.normalize("NFKD", char.lower())
        for piece in decomposed:
            if unicodedata.combining(piece):
                continue
            if piece.isalnum():
                out.append(piece)
                origin.append(index)
                pending_space = False
            elif not pending_space:
                out.append(" ")
                origin.append(index)
                pending_space = True
    while out and out[-1] == " ":
        out.pop()
        origin.pop()
    return "".join(out), origin


def _date_variants(value: str) -> list[str]:
    """
    Écritures alternatives d'une date.

    Les documents médicaux mêlent « 15.03.2025 », « 15/03/2025 » et « 15 mars
    2025 » ; la normalisation absorbe les deux premières, pas la troisième.
    """
    for pattern in _DATE_PATTERNS:
        match = pattern.match(value.strip())
        if not match:
            continue
        groups = match.groups()
        day, month, year = (groups[2], groups[1], groups[0]) if len(groups[0]) == 4 else groups
        try:
            day_i, month_i = int(day), int(month)
        except ValueError:
            return []
        if not (1 <= month_i <= 12 and 1 <= day_i <= 31):
            return []
        return [
            f"{day_i:02d}.{month_i:02d}.{year}",
            f"{day_i}.{month_i}.{year}",
            f"{day_i} {_MONTHS_FR[month_i - 1]} {year}",
            f"{day_i:02d} {_MONTHS_FR[month_i - 1]} {year}",
        ]
    return []


def _variants(value: str) -> list[str]:
    """Toutes les écritures sous lesquelles une valeur peut apparaître."""
    forms = [value]
    forms.extend(_date_variants(value))
    return forms


class SourceIndex:
    """
    Index de recherche sur le texte des documents d'un job.

    La forme normalisée et sa table de correspondance sont calculées une fois
    par document : elles sont réutilisées pour les 112 champs d'un formulaire.
    """

    def __init__(self, documents: Iterable[dict], derived: Iterable[dict] = ()):
        """
        Args:
            documents: textes sources, `{filename, markdown}`.
            derived: textes produits par le pipeline lui-même — la synthèse
                médicale. Ils sont indexés en dernier et marqués : une valeur
                qui n'y est ancrée que là reste à relire, puisque la synthèse
                est elle-même une production du modèle. Sans eux, une citation
                tirée de la synthèse — la source *principale* du prompt
                d'extraction — passait pour inventée.
        """
        self._docs: list[dict] = []
        for doc in list(documents) + list(derived):
            text = doc.get("markdown") or ""
            if not text:
                continue
            normalized, origin = _normalize_with_map(text)
            self._docs.append({
                "filename": doc.get("filename") or "document",
                "text": text,
                "normalized": normalized,
                "origin": origin,
                # Forme sans espaces, pour rattraper les mots coupés par la
                # couche texte (voir SQUASHED_MIN_CHARS).
                "squashed": normalized.replace(" ", ""),
                "squashed_origin": [o for c, o in zip(normalized, origin) if c != " "],
                "pages": _page_offsets(text),
                "derived": bool(doc.get("derived")),
            })

    def find(self, needle: str, whole_words: bool = False) -> dict | None:
        """
        Localise `needle` dans les documents, sur la forme normalisée.

        Args:
            whole_words: exige des frontières de mot. Indispensable pour les
                valeurs courtes — sans quoi « 50 » se retrouve dans « 1950 ».

        Returns:
            {document, page, excerpt, offset} ou None.
        """
        target = normalize(needle)
        if not target:
            return None
        if whole_words or len(target) < SHORT_MATCH_CHARS:
            pattern = re.compile(rf"\b{re.escape(target)}\b")
        else:
            pattern = None

        squashed_target = target.replace(" ", "")
        retry_squashed = len(squashed_target) >= SQUASHED_MIN_CHARS

        for doc in self._docs:
            origin, text = doc["origin"], doc["text"]
            span = len(target)
            if pattern is not None:
                match = pattern.search(doc["normalized"])
                position = match.start() if match else -1
            else:
                position = doc["normalized"].find(target)
            if position < 0 and retry_squashed:
                position = doc["squashed"].find(squashed_target)
                if position >= 0:
                    origin, span = doc["squashed_origin"], len(squashed_target)
            if position < 0:
                continue
            start = origin[position]
            end = origin[min(position + span, len(origin)) - 1] + 1
            return {
                "document": doc["filename"],
                "page": _page_at(doc["pages"], start),
                "excerpt": _excerpt(text, start, end),
                # Le fragment exact, pour que l'interface le surligne dans
                # l'extrait — sans lui, retrouver la correspondance à l'œil dans
                # 300 caractères de contexte annule le bénéfice.
                "match": _flatten(text[start:end]),
                "offset": start,
                "derived": doc["derived"],
            }
        return None


def _page_offsets(text: str) -> list[tuple[int, int]]:
    """Positions des en-têtes « ## Page N » produits par l'extraction texte."""
    return [(m.start(), int(m.group(1))) for m in _PAGE_HEADING.finditer(text)]


def _page_at(pages: list[tuple[int, int]], offset: int) -> int | None:
    """Numéro de page couvrant un offset, si le document en porte."""
    page = None
    for start, number in pages:
        if start > offset:
            break
        page = number
    return page


def _flatten(text: str) -> str:
    """Réduit un fragment à une ligne lisible."""
    return re.sub(r"\s+", " ", text).strip()


def _excerpt(text: str, start: int, end: int) -> str:
    """Texte alentour de la correspondance, pour affichage."""
    left = max(0, start - EXCERPT_MARGIN)
    right = min(len(text), end + EXCERPT_MARGIN)
    snippet = _flatten(text[left:right])
    return ("… " if left > 0 else "") + snippet + (" …" if right < len(text) else "")


def _locate_quote(quote: str, index: SourceIndex) -> tuple[dict | None, bool]:
    """
    Localise la citation, entière si possible, sinon par propositions.

    Le modèle recompose fréquemment une « citation » à partir de plusieurs
    fragments réels — les lignes d'un tableau de diagnostics rassemblées en une
    phrase, par exemple. Refuser ces citations en bloc les rangeait avec les
    inventions, ce que le signal a précisément pour but de distinguer.

    Returns:
        (ancrage, partiel). `partiel` signale une citation retrouvée seulement
        par morceaux : elle atteste d'une source réelle, pas d'une reprise
        littérale, et plafonne donc le verdict.
    """
    if len(normalize(quote)) < MIN_QUOTE_CHARS:
        return None, False

    whole = index.find(quote)
    if whole is not None:
        return whole, False

    # La proposition la plus longue est la plus discriminante : c'est celle dont
    # une correspondance fortuite est la moins probable.
    segments = sorted((s.strip() for s in _SEGMENT_SPLIT.split(quote)),
                      key=lambda s: len(normalize(s)), reverse=True)
    for segment in segments:
        if len(normalize(segment)) < MIN_QUOTE_CHARS:
            break
        hit = index.find(segment)
        if hit is not None:
            return hit, True
    return None, False


def ground_value(value: str, quote: str, index: SourceIndex) -> dict[str, Any]:
    """
    Rattache une valeur extraite à son texte source.

    Trois questions, dans cet ordre : la citation existe-t-elle vraiment ? la
    valeur y figure-t-elle ? sinon, figure-t-elle ailleurs dans les documents ?

    Returns:
        {grounding, quote_verified, source_document, source_page, source_excerpt}
    """
    value = (value or "").strip()
    quote = (quote or "").strip()

    quote_hit, quote_partial = _locate_quote(quote, index)

    result: dict[str, Any] = {"quote_verified": quote_hit is not None}

    def _locate(hit: dict | None) -> None:
        if hit:
            result["source_document"] = hit["document"]
            result["source_page"] = hit["page"]
            result["source_excerpt"] = hit["excerpt"]
            result["source_match"] = hit["match"]

    def _grade(strong: str, hit: dict) -> str:
        """Un ancrage dans un texte dérivé ne vaut jamais mieux que « à relire »."""
        return INFERRED if hit.get("derived") else strong

    # Une valeur d'un seul caractère se retrouve partout par accident : on ne peut
    # ni l'attester ni la démentir, et le prétendre serait pire que se taire.
    if len(normalize(value)) < MIN_VALUE_CHARS:
        result["grounding"] = NOT_CHECKABLE if quote_hit else UNVERIFIED
        _locate(quote_hit)
        return result

    # La valeur est-elle portée par une citation reprise littéralement ?
    #
    # Cette voie exige la citation *entière*. Sur une citation seulement
    # retrouvée par morceaux, « la valeur est dans la citation » ne prouve que
    # la cohérence du modèle avec lui-même : c'est ainsi qu'une adresse dont le
    # numéro de rue était inventé passait pour attestée, alors que seul le nom
    # du cabinet existait dans le dossier. On laisse ce cas descendre à la
    # recherche de la valeur elle-même, ci-dessous.
    if quote_hit is not None and not quote_partial:
        quote_norm = normalize(quote)
        if any(re.search(rf"\b{re.escape(normalize(v))}\b", quote_norm) for v in _variants(value)):
            result["grounding"] = _grade(VERIFIED, quote_hit)
            _locate(quote_hit)
            return result

    # Sinon, la valeur figure-t-elle quelque part dans les documents ?
    for variant in _variants(value):
        value_hit = index.find(variant, whole_words=True)
        if value_hit is not None:
            result["grounding"] = _grade(ATTESTED, value_hit)
            _locate(value_hit)
            return result

    # Citation réelle mais valeur introuvable : reformulation ou déduction —
    # le cas normal des champs de texte libre.
    result["grounding"] = INFERRED if quote_hit is not None else UNVERIFIED
    _locate(quote_hit)
    return result
