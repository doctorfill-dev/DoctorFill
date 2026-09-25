"""
extraction.py — Découpage des documents, contexte du prompt et appel LLM d'extraction.

Trois causes de champs vides ou en erreur y sont traitées :

- **Contexte hors budget.** Les extraits étaient comptés, pas mesurés : 24
  extraits de 800 mots dépassent la fenêtre de 32k tokens de vLLM, qui répond
  400 — et les 7 champs du lot échouaient après trois tentatives identiques.
  Le contexte est désormais construit contre un budget en tokens.
- **Extraits mal répartis.** Les extraits d'un lot étaient concaténés champ par
  champ puis tronqués : les derniers champs du lot n'avaient souvent plus aucun
  extrait. Ils sont maintenant entrelacés par rang.
- **Réponses incomplètes.** Un JSON tronqué, un ID oublié ou une valeur rendue
  en chaîne plutôt qu'en objet perdaient le champ. La réponse est contrainte
  par un schéma JSON, lue avec tolérance, et un lot qui échoue est scindé puis
  rejoué plutôt qu'abandonné.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List

import httpx

from core.fields import coerce_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budget de tokens
# ---------------------------------------------------------------------------

# À garder aligné sur --max-model-len de vLLM (docker-compose).
LLM_MAX_MODEL_LEN = int(os.getenv("LLM_MAX_MODEL_LEN", "32768"))
# Plafond de génération d'un lot. Un lot de 28 champs (quatre périodes
# d'incapacité) produit ~2 000 tokens de JSON ; 2048 tronquait les gros lots.
MAX_TOKENS_EXTRACT = int(os.getenv("MAX_TOKENS_EXTRACT", "4096"))
# Marge pour l'écart entre l'estimation et le tokenizer réel.
PROMPT_SAFETY_TOKENS = 1024
# Dossier transmis en entier au modèle s'il tient sous ce seuil : plus aucune
# information ne dépend de la qualité du retrieval, et le préfixe commun à tous
# les lots n'est calculé qu'une fois par vLLM.
FULL_CONTEXT_MAX_TOKENS = int(os.getenv("FULL_CONTEXT_MAX_TOKENS", "16000"))
# Au-delà : extraits sélectionnés par le retrieval, dans ce budget par lot.
RAG_CONTEXT_TOKENS = int(os.getenv("RAG_CONTEXT_TOKENS", "9000"))
# Délai d'un appel d'extraction. Sous charge (24 requêtes en vol sur le GB10),
# 180 s ne suffisaient pas : le délai expirait, la requête était rejouée, et la
# charge augmentait d'autant.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "600"))
MAX_LLM_RETRIES = int(os.getenv("MAX_LLM_RETRIES", "3"))


def estimate_tokens(text: str) -> int:
    """
    Estimation prudente du nombre de tokens.

    Le français médical (accents, nombres, codes) tourne autour de 3,5
    caractères par token avec le tokenizer Qwen ; on compte 3 pour ne jamais
    sous-estimer — c'est la sous-estimation qui provoque les erreurs 400.
    """
    return len(text) // 3 + 1


# ---------------------------------------------------------------------------
# Découpage des documents
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_PAGE_TITLE = re.compile(r"^page\s+(\d+)$", re.IGNORECASE)

CHUNK_MAX_WORDS = int(os.getenv("CHUNK_MAX_WORDS", "300"))
CHUNK_OVERLAP_WORDS = int(os.getenv("CHUNK_OVERLAP_WORDS", "50"))
CHUNK_MIN_WORDS = int(os.getenv("CHUNK_MIN_WORDS", "40"))


def chunk_document(filename: str, markdown: str, max_words: int = CHUNK_MAX_WORDS,
                   overlap: int = CHUNK_OVERLAP_WORDS, min_words: int = CHUNK_MIN_WORDS) -> List[str]:
    """
    Découpe un document en extraits autonomes.

    Chaque extrait porte en tête sa source — document, page, section. Seul le
    premier extrait d'un document la portait : les suivants arrivaient au
    modèle sans qu'il sache de quel rapport, ni de quelle date, ils venaient.
    Un « Téléphone : 021 … » isolé ne dit pas s'il s'agit du patient ou du
    médecin ; « [Source : 01_fiche.pdf — Médecin traitant] » le dit.

    Les sections trop courtes sont fusionnées avec la suivante (un titre seul
    n'est qu'un embedding parasite), les trop longues découpées avec
    chevauchement, à une taille que le reranker évalue sans la tronquer.
    """
    sections: List[tuple[int | None, str, str]] = []  # (page, titre, texte)
    page: int | None = None
    positions = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(markdown)]
    if not positions or positions[0][0] > 0:
        positions.insert(0, (0, ""))
    for index, (start, title) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(markdown)
        body = markdown[start:end].strip()
        page_match = _PAGE_TITLE.match(title)
        if page_match:
            # « ## Page 3 » passe dans l'en-tête de l'extrait, pas dans son texte.
            page = int(page_match.group(1))
            title = ""
            body = body.split("\n", 1)[1].strip() if "\n" in body else ""
        if body:
            sections.append((page, title, body))

    # Fusion des sections trop courtes avec la suivante, sur la même page.
    merged: List[tuple[int | None, str, str]] = []
    for sec in sections:
        if merged:
            prev_page, prev_title, prev_body = merged[-1]
            if len(prev_body.split()) < min_words and prev_page == sec[0]:
                merged[-1] = (prev_page, prev_title or sec[1], prev_body + "\n\n" + sec[2])
                continue
        merged.append(sec)

    chunks: List[str] = []
    step = max(1, max_words - overlap)
    for sec_page, title, body in merged:
        label = filename
        if sec_page is not None:
            label += f" — page {sec_page}"
        if title:
            label += f" — {title}"
        header = f"[Source : {label}]"
        words = body.split()
        if len(words) <= max_words:
            chunks.append(f"{header}\n{body}")
            continue
        for i in range(0, len(words), step):
            part = words[i:i + max_words]
            chunks.append(f"{header}\n{' '.join(part)}")
            if i + max_words >= len(words):
                break
    return chunks


def full_documents_text(documents: List[Dict[str, str]]) -> str:
    """Texte intégral du dossier, un bloc par document, dans un ordre stable."""
    blocks = []
    for doc in sorted(documents, key=lambda d: d.get("filename", "")):
        text = (doc.get("markdown") or "").strip()
        if text:
            blocks.append(f"=== DOCUMENT : {doc.get('filename', 'document')} ===\n{text}")
    return "\n\n".join(blocks)


def build_rag_context(fields: List[Dict], field_chunks: Dict[str, List[str]],
                      budget_tokens: int) -> str:
    """
    Extraits d'un lot, entrelacés par rang et bornés par un budget en tokens.

    Le meilleur extrait de chaque champ passe avant le second de quiconque :
    aucun champ du lot ne se retrouve sans source parce que ses voisins ont
    consommé le budget.
    """
    lists = [field_chunks.get(str(f["id"]), []) for f in fields]
    seen: set = set()
    selected: List[str] = []
    used = 0
    depth = max((len(lst) for lst in lists), default=0)
    for rank in range(depth):
        for lst in lists:
            if rank >= len(lst) or lst[rank] in seen:
                continue
            cost = estimate_tokens(lst[rank])
            if used + cost > budget_tokens:
                continue
            seen.add(lst[rank])
            selected.append(lst[rank])
            used += cost
    return "\n\n---\n\n".join(selected)


# ---------------------------------------------------------------------------
# Appel LLM
# ---------------------------------------------------------------------------

class ContextOverflow(Exception):
    """Le prompt dépasse la fenêtre du modèle : rejouer tel quel est inutile."""


class TruncatedResponse(Exception):
    """La génération a atteint max_tokens : le JSON est incomplet."""


class SchemaUnsupported(Exception):
    """Le serveur refuse `response_format: json_schema`."""


# Le schéma JSON contraint la génération (vLLM, décodage guidé) : plus d'ID
# oublié ni de clé déformée. Désactivé au premier refus du serveur.
_schema_supported = os.getenv("LLM_JSON_SCHEMA", "true").lower() == "true"


def response_schema(fields: List[Dict]) -> Dict[str, Any]:
    """Schéma de la réponse attendue : un objet par ID, valeur et citation."""
    properties = {}
    for f in fields:
        value: Dict[str, Any] = {"type": "string"}
        options = f.get("options")
        if f.get("type") == "choice" and options:
            # "" reste permis : l'absence d'information prime sur l'obligation de choisir.
            value = {"type": "string", "enum": list(dict.fromkeys(list(options) + [""]))}
        properties[str(f["id"])] = {
            "type": "object",
            "properties": {"value": value, "source_quote": {"type": "string"}},
            "required": ["value", "source_quote"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _load_json_object(content: str) -> Dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(content[start:end + 1])
    if not isinstance(data, dict):
        raise json.JSONDecodeError("réponse JSON non objet", content, 0)
    return data


def _clean_key(key: Any) -> str:
    return str(key).strip().strip("[]•").strip()


def parse_response(content: str, fields: List[Dict]) -> Dict[str, Dict[str, str]]:
    """
    Lit la réponse du modèle, avec tolérance.

    Accepte les écarts courants hors décodage guidé : ID entre crochets, valeur
    rendue en chaîne ou en liste plutôt qu'en objet, réponse enveloppée dans
    une clé unique (« champs », « fields »).

    Returns:
        ID → {"value", "source_quote"}, pour les seuls IDs trouvés.
    """
    data = _load_json_object(content)
    wanted = {str(f["id"]) for f in fields}
    entries = {_clean_key(k): v for k, v in data.items()}
    if not wanted & set(entries) and len(entries) == 1:
        inner = next(iter(entries.values()))
        if isinstance(inner, dict):
            entries = {_clean_key(k): v for k, v in inner.items()}

    parsed: Dict[str, Dict[str, str]] = {}
    for fid in wanted:
        if fid not in entries:
            continue
        raw = entries[fid]
        if isinstance(raw, dict):
            value = raw.get("value", raw.get("valeur", ""))
            quote = raw.get("source_quote", raw.get("citation", ""))
        else:
            value, quote = raw, ""
        parsed[fid] = {"value": coerce_text(value).strip(), "source_quote": coerce_text(quote).strip()}
    return parsed


async def _post_chat(client: httpx.AsyncClient, url: str, payload: Dict[str, Any],
                     llm_sem: asyncio.Semaphore) -> str:
    """Un appel chat/completions, erreurs classées. Retourne le contenu du message."""
    async with llm_sem:
        resp = await client.post(f"{url}/chat/completions", json=payload,
                                 timeout=httpx.Timeout(LLM_TIMEOUT, connect=15.0))
    if resp.status_code == 400:
        detail = resp.text.lower()
        # Libellés selon les versions de vLLM : « maximum context length is… »,
        # « …is longer than the maximum model length of… ».
        if any(k in detail for k in ("context length", "maximum context", "too long",
                                     "maximum model length", "longer than the maximum")):
            raise ContextOverflow(resp.text[:300])
        if "response_format" in payload and payload["response_format"].get("type") == "json_schema" \
                and any(k in detail for k in ("json_schema", "response_format", "guided", "schema")):
            raise SchemaUnsupported(resp.text[:300])
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise TruncatedResponse(f"{len(choice['message'].get('content') or '')} caractères générés")
    return choice["message"]["content"] or ""


_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


async def call_extraction(client: httpx.AsyncClient, url: str, model: str,
                          messages: List[Dict], fields: List[Dict],
                          llm_sem: asyncio.Semaphore) -> Dict[str, Dict[str, str]]:
    """
    Appel d'extraction avec reprises sur les seules erreurs transitoires.

    Réseau, délai, 5xx, 429 : on rejoue. Une erreur 4xx, un prompt trop long ou
    une réponse tronquée se reproduiraient à l'identique : on les remonte tout
    de suite à l'appelant, qui scinde le lot.
    """
    global _schema_supported
    for attempt in range(1, MAX_LLM_RETRIES + 1):
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS_EXTRACT,
        }
        if _schema_supported:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": response_schema(fields)},
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        try:
            content = await _post_chat(client, url, payload, llm_sem)
            return parse_response(content, fields)
        except SchemaUnsupported as exc:
            logger.warning("json_schema refusé par le serveur, repli sur json_object : %s", exc)
            _schema_supported = False
            # Rejoué sans consommer de tentative : le refus ne dit rien de la requête.
            return await call_extraction(client, url, model, messages, fields, llm_sem)
        except (ContextOverflow, TruncatedResponse):
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status < 500 and status != 429:
                raise
            error: Exception = exc
        except (json.JSONDecodeError, *_TRANSIENT) as exc:
            error = exc
        if attempt == MAX_LLM_RETRIES:
            raise error
        logger.warning("LLM retry %d/%d (%s) : %s: %s", attempt, MAX_LLM_RETRIES,
                       [f["id"] for f in fields], type(error).__name__, error)
        await asyncio.sleep(2 * attempt)
    raise RuntimeError("appel d'extraction sans réponse")


PromptBuilder = Callable[[List[Dict], float], List[Dict]]


async def extract_batch(client: httpx.AsyncClient, url: str, model: str,
                        fields: List[Dict], build_messages: PromptBuilder,
                        llm_sem: asyncio.Semaphore, _depth: int = 0, _shrink: int = 0) -> List[Dict]:
    """
    Extrait un lot de champs, sans jamais perdre tout le lot sur une erreur.

    - prompt trop long : rejoué avec un contexte réduit de moitié, trois fois au plus ;
    - réponse tronquée : le lot est scindé en deux, chaque moitié rejouée ;
    - IDs absents de la réponse : redemandés une fois, dans un lot à eux ;
    - autre échec : le lot est scindé une fois avant d'abandonner.

    Args:
        build_messages: (champs, échelle du contexte) → messages. L'échelle
            vaut 1 puis 0.5, 0.25… à chaque dépassement de la fenêtre.

    Returns:
        [{"id", "result": {"value", "source_quote"}}] ou [{"id", "error"}].
    """
    ids = [f["id"] for f in fields]

    async def _split(depth: int) -> List[Dict]:
        half = len(fields) // 2
        parts = await asyncio.gather(
            extract_batch(client, url, model, fields[:half], build_messages, llm_sem, depth, _shrink),
            extract_batch(client, url, model, fields[half:], build_messages, llm_sem, depth, _shrink),
        )
        return parts[0] + parts[1]

    try:
        data = await call_extraction(client, url, model, build_messages(fields, 0.5 ** _shrink),
                                     fields, llm_sem)
    except ContextOverflow as exc:
        if _shrink >= 3:
            logger.error("Extraction abandonnée, contexte irréductible (%s) : %s", ids, exc)
            return [{"id": f["id"], "error": "extraction_failed"} for f in fields]
        logger.warning("Lot %s : fenêtre dépassée, contexte réduit", ids)
        return await extract_batch(client, url, model, fields, build_messages, llm_sem,
                                   _depth, _shrink + 1)
    except TruncatedResponse as exc:
        if len(fields) == 1 or _depth >= 5:
            logger.error("Extraction abandonnée, réponse tronquée (%s) : %s", ids, exc)
            return [{"id": f["id"], "error": "extraction_failed"} for f in fields]
        logger.warning("Lot %s : réponse tronquée, lot scindé", ids)
        return await _split(_depth + 1)
    except Exception as exc:
        logger.error("Erreur batch vLLM (%s) : %s: %s", ids, type(exc).__name__, exc)
        if len(fields) > 1 and _depth == 0:
            return await _split(1)
        return [{"id": f["id"], "error": "extraction_failed"} for f in fields]

    missing = [f for f in fields if str(f["id"]) not in data]
    if missing and _depth == 0:
        # Une fois, y compris quand la réponse ne contient aucun ID ({} valide) :
        # le modèle s'est écarté de la consigne, pas forcément du dossier.
        logger.info("IDs absents de la réponse, redemandés : %s", [f["id"] for f in missing])
        retry = await extract_batch(client, url, model, missing, build_messages, llm_sem, 1, _shrink)
        for r in retry:
            if "result" in r:
                data[str(r["id"])] = r["result"]

    results = []
    for f in fields:
        entry = data.get(str(f["id"]))
        if entry is None:
            results.append({"id": f["id"], "error": "field_missing_in_response"})
        else:
            results.append({"id": f["id"], "result": dict(entry)})
    return results
