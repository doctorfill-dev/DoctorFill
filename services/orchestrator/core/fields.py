"""
core/fields.py — Préparation des champs d'un template, avant et après le modèle.

Avant l'appel LLM : quels champs soumettre, comment formuler leur question pour
qu'elle soit univoque, et comment les regrouper en lots cohérents.
Après : ramener la réponse du modèle à une valeur que le formulaire accepte.

Tout est déterministe et sans dépendance réseau : c'est la partie du pipeline
qu'on peut tester entièrement hors ligne.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def fold(text: str) -> str:
    """Forme comparable : minuscules, sans accents, espaces réduits."""
    decomposed = unicodedata.normalize("NFKD", str(text).casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.split())


# ---------------------------------------------------------------------------
# Quels champs soumettre au modèle
# ---------------------------------------------------------------------------

def _is_yes_no(labels: Iterable[str]) -> bool:
    folded = [fold(label) for label in labels]
    return any(f.startswith("oui") for f in folded) and any(f.startswith("non") for f in folded)


def is_blank_default(field: dict) -> bool:
    """
    Le `preset` d'un champ n'est-il que l'état vierge du formulaire ?

    `preset` recopie la valeur que le PDF vierge porte déjà. Pour un bloc adresse
    ou un régime d'assurance, c'est une donnée de l'éditeur qui fait autorité.
    Mais une case décochée (« /Off »), une question oui/non positionnée sur
    « non » ou un compteur à 0 ne disent rien : c'est l'état par défaut d'un
    formulaire que personne n'a encore rempli. Les tenir pour acquis écartait de
    l'extraction 79 cases à cocher et une dizaine de questions fermées — des
    champs cliniques (urgence, hospitalisation, rechute…) jamais remplis.
    """
    preset = str(field.get("preset") or "").strip()
    if not preset:
        return False
    state = preset.lstrip("/").strip().casefold()
    kind = field.get("type")
    if kind == "bool":
        return state in {"off", "0", "no", "non", "false"}
    if kind == "int":
        # « /0 » est un état de bouton, pas un nombre : on n'y touche pas.
        return preset == "0"
    if kind == "choice":
        labels = field.get("options") or []
        if not _is_yes_no(labels):
            return False
        values = field.get("option_values") or []
        for index, label in enumerate(labels):
            if fold(label).startswith("non"):
                if state == fold(label):
                    return True
                if index < len(values) and state == str(values[index]).casefold():
                    return True
    return False


def extractable_fields(template: dict) -> list[dict]:
    """
    Champs à soumettre au modèle.

    Écarte les champs `computed` (déduits du formulaire lui-même) et les champs
    `preset` : l'éditeur du formulaire les a déjà renseignés (adresse de l'office
    destinataire, code EAN, données de routage) et ils font autorité. Les
    extraire produisait des documents incohérents — un formulaire AI adressé à
    « Helvetia Santé SA » parce que le dossier mentionnait cette caisse, à
    l'adresse de l'Office AI restée en dessous.

    Exception : un `preset` qui n'est que l'état vierge du champ (voir
    `is_blank_default`) reste à remplir.
    """
    return [f for f in template.get("fields", [])
            if "id" in f
            and str(f.get("question") or "").strip()
            and "computed" not in f
            and (not f.get("preset") or is_blank_default(f))]


# ---------------------------------------------------------------------------
# Questions univoques
# ---------------------------------------------------------------------------

# Conteneurs medForms dont les occurrences successives portent des champs de même
# question. Le libellé nomme ce que chaque occurrence représente ; l'ordre dit au
# modèle comment les répartir.
STRUCT_CONTEXT: dict[str, tuple[str, str]] = {
    "unemployabilityS1Struct": ("période d'incapacité de travail",
                                "de la plus ancienne à la plus récente"),
    "diagnosisS1Struct": ("diagnostic", "du principal au plus secondaire"),
    "treatmentS1Struct": ("traitement", "ordre chronologique"),
    "documentS1Struct": ("document annexé", "ordre des documents"),
    "therapyStruct": ("thérapie", "ordre chronologique"),
    "anamnesisStruct": ("anamnèse", "ordre chronologique"),
}

_INDEX = re.compile(r"\[\d+\]$")


def _segments(xml_path: str | None) -> list[str]:
    return [s for s in str(xml_path or "").split("/") if s]


def _canonical_struct(segment: str) -> str:
    """`bdiagnosisS1Struct[2]` → `diagnosisS1Struct` : même structure, préfixe d'ordre."""
    bare = _INDEX.sub("", segment)
    for known in STRUCT_CONTEXT:
        if bare.endswith(known):
            return known
    return bare


def _container(field: dict) -> str:
    """Chemin du conteneur d'un champ, indices et préfixes d'ordre effacés."""
    parts = _segments(field.get("xml_path"))[:-1]
    if not parts:
        return ""
    return "/".join([_INDEX.sub("", p) for p in parts[:-1]] + [_canonical_struct(parts[-1])])


def _struct_of(field: dict) -> str:
    parts = _segments(field.get("xml_path"))
    return _canonical_struct(parts[-2]) if len(parts) >= 2 else ""


# Consignes de format dans une question : utiles au modèle, parasites pour la
# recherche sémantique (« Répondre UNIQUEMENT par … AG, AI, AR, BE… »).
_BRACKETS = re.compile(r"\[[^\]]*\]")
_ANSWER_HINT = re.compile(r"\b(?:Répondre|Reprendre|Répondez)\b.*$", re.IGNORECASE | re.DOTALL)


def retrieval_text(question: str) -> str:
    """Question débarrassée de ses consignes de format, pour l'embedding et le rerank."""
    text = _ANSWER_HINT.sub("", _BRACKETS.sub("", question))
    return " ".join(text.split()) or question


def contextualize(fields: list[dict]) -> list[dict]:
    """
    Rend chaque question univoque au sein du formulaire.

    Le vocabulaire medForms produit la même question pour les occurrences
    successives d'une structure : « Quelle est la date de début de la période
    concernée ? » quatre fois pour quatre périodes d'incapacité, deux fois
    « Quel est le numéro de téléphone du patient ? » pour `phone` et `phone[1]`.
    177 champs du catalogue sont dans ce cas. Le modèle n'avait aucun moyen de
    savoir laquelle il remplissait : il répétait la même valeur partout ou
    laissait tout vide.

    On ajoute à ces questions le contexte que porte le chemin XFA : la structure
    (« période d'incapacité de travail ») et le rang de l'occurrence.

    Returns:
        copies des champs, enrichies de `prompt_question` (pour le modèle) et
        `retrieval_query` (pour la recherche sémantique).
    """
    by_question: dict[str, list[int]] = {}
    for index, field in enumerate(fields):
        by_question.setdefault(fold(field.get("question", "")), []).append(index)

    prepared = [dict(f) for f in fields]
    for indexes in by_question.values():
        base = prepared[indexes[0]]
        if len(indexes) == 1:
            base["prompt_question"] = base.get("question", "")
            base["retrieval_query"] = retrieval_text(base.get("question", ""))
            continue

        # Rang calculé par structure : un `beginDate` de traitement ne partage pas
        # la numérotation des périodes d'incapacité qui ont la même question.
        by_struct: dict[str, list[int]] = {}
        for i in indexes:
            by_struct.setdefault(_container(prepared[i]), []).append(i)

        for members in by_struct.values():
            for rank, i in enumerate(members, start=1):
                field = prepared[i]
                question = field.get("question", "")
                label, order = STRUCT_CONTEXT.get(_struct_of(field), ("", ""))
                total = len(members)
                if label and total > 1:
                    hint = f"{label} n°{rank} sur {total} — {order} ; vide s'il n'y en a pas de n°{rank}"
                elif label:
                    hint = label
                elif total > 1:
                    hint = (f"occurrence n°{rank} sur {total} de cette question — une valeur "
                            f"différente par occurrence ; vide s'il n'y en a pas de n°{rank}")
                else:
                    hint = ""
                field["prompt_question"] = f"{question} (Contexte : {hint}.)" if hint else question
                field["retrieval_query"] = retrieval_text(question) + (f" — {label}" if label else "")
    return prepared


def prepare_fields(template: dict) -> list[dict]:
    """Champs à extraire, prêts pour la recherche et le prompt."""
    return contextualize(extractable_fields(template))


# ---------------------------------------------------------------------------
# Lots d'extraction
# ---------------------------------------------------------------------------

def batch_fields(fields: list[dict], max_batch_size: int = 8,
                 max_family_size: int = 32) -> list[list[dict]]:
    """
    Regroupe les champs en lots pour l'appel LLM.

    Par section d'abord (préfixe de l'ID), puis en gardant ensemble les
    occurrences d'une même structure répétée : les quatre périodes d'incapacité
    doivent être réparties dans un seul appel, sans quoi deux appels distincts
    attribuent la même période au n°1 et au n°2.
    """
    question_count: dict[str, int] = {}
    for f in fields:
        key = fold(f.get("question", ""))
        question_count[key] = question_count.get(key, 0) + 1

    # section → familles, dans l'ordre d'apparition
    sections: dict[str, dict[str, list[dict]]] = {}
    for f in fields:
        section = str(f["id"]).split(".")[0]
        repeated = question_count[fold(f.get("question", ""))] > 1 and _container(f)
        family = f"family:{_container(f)}" if repeated else f"field:{f['id']}"
        sections.setdefault(section, {}).setdefault(family, []).append(f)

    batches: list[list[dict]] = []
    for families in sections.values():
        current: list[dict] = []
        for members in families.values():
            if len(members) > 1:
                if current:
                    batches.append(current)
                    current = []
                for i in range(0, len(members), max_family_size):
                    batches.append(members[i:i + max_family_size])
                continue
            current.extend(members)
            if len(current) >= max_batch_size:
                batches.append(current)
                current = []
        if current:
            batches.append(current)
    return batches


# ---------------------------------------------------------------------------
# Normalisation des valeurs produites par le modèle
# ---------------------------------------------------------------------------

# Réponses qui disent « je n'ai pas trouvé » au lieu de laisser la chaîne vide.
# Écrites telles quelles, elles remplissaient le formulaire de « Non mentionné ».
_NULL_LIKE = re.compile(
    r"^(?:null|none|nil|nan|n/?a|n\.?c\.?|n\.?d\.?|inconnue?s?|\?+|[-–—_.… ]*"
    r"|(?:aucune |pas d')?information(?:s)?(?: non disponibles?| absentes?| manquantes?)?"
    r"|non (?:mentionn|precis|renseign|specifi|disponible|communiqu|indiqu|document|trouv"
    r"|applicable|connu|fourni|determin|rapport|stipul|detaill)\w*(?:\W.*)?"
    r"|(?:pas|rien) (?:de donnee|d'information|mentionne|precise|trouve|indique)\w*(?:\W.*)?"
    r"|(?:information|donnee)s? (?:non|pas) (?:disponible|mentionne|precise|trouve|fourni)\w*(?:\W.*)?)$"
)
# Exemples de format recopiés à la place d'une valeur.
_PLACEHOLDER = re.compile(r"^<[^<>]*>$|\b(?:jj|dd)\W?mm\W?(?:aaaa|yyyy|aa|yy)\b|x{3,}|^\.\.\.$")


def is_null_like(value: str) -> bool:
    folded = fold(value)
    return not folded or bool(_NULL_LIKE.match(folded)) or bool(_PLACEHOLDER.search(folded))


def coerce_text(value: Any) -> str:
    """Ramène n'importe quelle valeur JSON à une chaîne."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return "\n".join(t for t in (coerce_text(v).strip() for v in value) if t)
    if isinstance(value, dict):
        for key in ("value", "valeur", "text"):
            if key in value:
                return coerce_text(value[key])
        return "\n".join(f"{k} : {coerce_text(v)}" for k, v in value.items() if coerce_text(v))
    return str(value)


_MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3,
    "avril": 4, "avr": 4, "mai": 5, "juin": 6, "juillet": 7, "juil": 7, "aout": 8,
    "septembre": 9, "sept": 9, "sep": 9, "octobre": 10, "oct": 10, "novembre": 11,
    "nov": 11, "decembre": 12, "dec": 12,
}
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DATE_WORDS = re.compile(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\.?\s+(\d{4})\b")


def _format_date(day: int, month: int, year: int) -> str | None:
    try:
        date(year, month, day)
    except ValueError:
        return None
    return f"{day:02d}.{month:02d}.{year:04d}"


def normalize_date(value: str) -> str:
    """
    Ramène une date au format JJ.MM.AAAA demandé par les formulaires.

    Accepte « 2025-03-15 », « 15/3/2025 », « 15 mars 2025 », et une date seule
    noyée dans du texte (« dès le 15.03.2025 »). Plusieurs dates, ou aucune
    date reconnue : la valeur est rendue telle quelle.
    """
    folded = fold(value)
    found: list[str] = []
    for m in _DATE_ISO.finditer(folded):
        found.append(_format_date(int(m.group(3)), int(m.group(2)), int(m.group(1))) or "")
    without_iso = _DATE_ISO.sub(" ", folded)
    for m in _DATE_NUMERIC.finditer(without_iso):
        year = int(m.group(3))
        if len(m.group(3)) == 2:
            pivot = date.today().year % 100 + 1
            year += 2000 if year <= pivot else 1900
        found.append(_format_date(int(m.group(1)), int(m.group(2)), year) or "")
    for m in _DATE_WORDS.finditer(folded):
        month = _MONTHS.get(m.group(2))
        if month:
            found.append(_format_date(int(m.group(1)), month, int(m.group(3))) or "")
    distinct = {d for d in found if d}
    if len(distinct) == 1 and len(found) == 1:
        return distinct.pop()
    return value


_TRUE_WORDS = {"oui", "yes", "true", "vrai", "1", "on", "x", "coche", "checked", "y", "o"}
_FALSE_WORDS = {"non", "no", "false", "faux", "0", "off", "n", "decoche", "unchecked"}


def normalize_bool(value: str) -> str:
    """« oui », « non », ou "" si la réponse ne tranche pas."""
    folded = fold(value).rstrip(".!")
    if folded in _TRUE_WORDS or re.match(r"oui\b", folded):
        return "oui"
    if folded in _FALSE_WORDS or re.match(r"non\b", folded):
        return "non"
    return ""


def normalize_sex(value: str) -> str:
    folded = fold(value).rstrip(".")
    if folded in {"f", "feminin", "femme", "female", "madame", "mme", "mlle", "fille"} \
            or folded.startswith(("femin", "femme", "madame")):
        return "F"
    if folded in {"m", "masculin", "homme", "male", "h", "monsieur", "mr", "garcon"} \
            or folded.startswith(("mascul", "homme", "monsieur")):
        return "M"
    return value


def normalize_value(raw: Any, field: dict | None) -> str:
    """
    Valeur prête à être écrite, selon le type déclaré dans le template.

    Une réponse qui équivaut à « rien trouvé » devient "" : le champ reste vide,
    ce qui est le seul état honnête.
    """
    value = coerce_text(raw).strip()
    if not value:
        return ""
    field = field or {}
    kind = field.get("type")
    options = field.get("options") or []

    # Une option peut ressembler à une non-réponse (« Inconnue ») : la vérifier d'abord.
    if kind == "choice" and any(fold(o) == fold(value) for o in options):
        return next(o for o in options if fold(o) == fold(value))
    if is_null_like(value):
        return ""

    if kind == "bool":
        return normalize_bool(value)
    if kind == "sex":
        return normalize_sex(value)
    if kind == "date":
        return normalize_date(value)
    if kind == "percent":
        match = re.search(r"\d+(?:[.,]\d+)?", value.replace("%", ""))
        return match.group(0).replace(",", ".") if match else value
    if kind == "int":
        match = re.search(r"\d+", value)
        return match.group(0) if match else value
    return value


def resolve_option(value: str, field: dict) -> str:
    """
    Traduit le libellé choisi par le modèle en valeur d'export du formulaire.

    Les groupes de boutons radio medForms exportent un index (« 0 », « 1 », …)
    et non le libellé affiché ; `option_values` porte la correspondance. On
    accepte aussi la valeur d'export elle-même et un libellé abrégé
    (« oui » pour « oui (= Major RF) ») s'il ne désigne qu'une option.

    Un libellé inconnu est laissé tel quel : le remplissage laissera alors le
    groupe vide plutôt que de cocher au hasard.
    """
    options = field.get("options") or []
    values = field.get("option_values") or []
    if not options:
        return value
    exported = values if len(values) == len(options) else options
    target = fold(value)

    for label, export in zip(options, exported):
        if fold(label) == target:
            return export
    if values:
        for export in values:
            if fold(export) == target:
                return export
    prefixed = [export for label, export in zip(options, exported)
                if re.match(rf"{re.escape(target)}(?:\W|$)", fold(label))]
    if target and len(prefixed) == 1:
        return prefixed[0]
    return value


def bool_item(value: str, field: dict, truthy: bool) -> str:
    """
    Valeur XFA d'une case à cocher : l'état déclaré par le formulaire.

    Les cases medForms n'utilisent pas toutes le même couple : « On/Off » pour
    certaines, « 1/0 » pour d'autres. `options` porte, dans l'ordre, les états
    coché puis décoché lus dans le XFA.
    """
    options = field.get("options") or []
    if len(options) >= 2:
        return options[0] if truthy else options[1]
    return "1" if truthy else "0"


# ---------------------------------------------------------------------------
# Du résultat d'extraction aux valeurs du formulaire
# ---------------------------------------------------------------------------

def computed_values(template: dict) -> list[tuple[dict, str]]:
    """
    Champs dont la valeur se déduit du formulaire lui-même.

    Le bloc adresse du destinataire en est le seul cas aujourd'hui : il est la
    version visible de champs structurés déjà renseignés par l'éditeur, mais
    masqués dans la mise en page. Le demander au modèle produisait des adresses
    inventées — un numéro de rue emprunté au patient, un code postal fabriqué.
    """
    return [(f, f["computed"]) for f in template.get("fields", []) if f.get("computed")]


def canton_recipient(template: dict, results: list[dict]) -> dict[str, str]:
    """
    Destinataire correspondant au canton de traitement extrait.

    Un formulaire AI s'adresse à l'office AI *du canton du patient*. Le gabarit
    porte cette table et l'applique par script — mais le script ne s'exécute
    que dans un lecteur XFA, jamais dans le PDF qu'on livre. Sans ça, un dossier
    neuchâtelois partait à l'office de Berne, l'adresse par défaut du vierge.

    Canton absent ou inconnu : on ne renvoie rien et le formulaire garde ses
    valeurs d'origine — mieux vaut le défaut du gabarit qu'un office arbitraire.

    Returns:
        nom de champ → valeur, à écrire tel quel.
    """
    table = template.get("_recipient_by_canton")
    if not table:
        return {}
    canton_ids = {str(f["id"]) for f in template.get("fields", [])
                  if f.get("name") == "treatmentCanton"}
    for res in results:
        if str(res.get("id")) not in canton_ids:
            continue
        valeur = str((res.get("result") or {}).get("value") or "").strip().upper()
        if valeur in table:
            logger.info("Destinataire dérivé du canton %s", valeur)
            return table[valeur]
        if valeur:
            logger.warning("Canton %r hors de la table du formulaire", valeur)
    return {}


def collect_form_values(template: dict, results: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """
    Valeurs à écrire dans le PDF, par chemin XFA et par nom AcroForm.

    Réunit, dans cet ordre de priorité croissante : les valeurs extraites, les
    champs calculés, puis le destinataire dérivé du canton. Partagé par le
    pipeline et le re-run, qui l'avaient chacun recopié — et le re-run avait
    perdu en route les deux dernières étapes.
    """
    by_id = {str(f["id"]): f for f in template.get("fields", []) if "id" in f}
    xfa_values: dict[str, str] = {}
    acro_values: dict[str, str] = {}

    def _put(f_def: dict, xfa_value: str, acro_value: str) -> None:
        if f_def.get("xml_path"):
            xfa_values[f_def["xml_path"]] = xfa_value
        if f_def.get("acroform_name"):
            acro_values[f_def["acroform_name"]] = acro_value

    for res in results:
        payload = res.get("result")
        if not isinstance(payload, dict):
            continue
        f_def = by_id.get(str(res.get("id")))
        if f_def is None:
            continue
        value = normalize_value(payload.get("value"), f_def)
        if not value:
            continue
        kind = f_def.get("type")
        if kind == "bool":
            truthy = value == "oui"
            _put(f_def, bool_item(value, f_def, truthy), "1" if truthy else "0")
        elif kind == "choice":
            exported = resolve_option(value, f_def)
            _put(f_def, exported, exported)
        else:
            _put(f_def, value, value)

    for f_def, value in computed_values(template):
        _put(f_def, value, value)

    # Le destinataire dépend du canton : il écrase aussi bien les valeurs par
    # défaut du gabarit que ce que le modèle aurait pu produire.
    for nom, value in canton_recipient(template, results).items():
        for f_def in template.get("fields", []):
            if f_def.get("name") == nom:
                _put(f_def, value, value)

    return xfa_values, acro_values
