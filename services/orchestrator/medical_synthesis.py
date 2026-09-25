"""
medical_synthesis.py — Synthèse médicale globale à partir de tous les documents OCR.

Deux stratégies selon le volume de texte :
- Directe  : tous les documents tiennent dans une seule fenêtre de contexte (<= MAX_DIRECT_TOKENS)
- Hiérarchique : trop de texte → résumé par document puis fusion

Le résultat est un dict Python (issu du JSON LLM) contenant diagnostics, incapacités, etc.
En cas d'échec, retourne None pour que le pipeline continue sur les seuls documents.

Chaque étape a désormais un repli plutôt qu'un point de rupture : la stratégie
directe qui échoue (fenêtre dépassée, JSON tronqué) passe la main à la
hiérarchique, un document trop long pour un résumé est découpé, et une fusion
impossible est remplacée par une fusion déterministe des résumés.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from prompts import (
    SYSTEM_PROMPT_MERGE_SUMMARIES,
    SYSTEM_PROMPT_PER_DOC_SUMMARY,
    SYSTEM_PROMPT_SYNTHESIS,
    build_merge_summaries_prompt,
    build_per_doc_summary_prompt,
    build_synthesis_prompt,
)

logger = logging.getLogger(__name__)

# À garder aligné sur --max-model-len de vLLM (docker-compose).
LLM_MAX_MODEL_LEN = int(os.getenv("LLM_MAX_MODEL_LEN", "32768"))

# Génération réservée à la synthèse. Elle n'avait pas de plafond explicite :
# vLLM lui laissait ce que le prompt n'occupait pas, soit parfois moins de 4k
# tokens pour un JSON exhaustif — tronqué, donc illisible, donc perdu.
SYNTHESIS_MAX_TOKENS = int(os.getenv("SYNTHESIS_MAX_TOKENS", "6144"))
SUMMARY_MAX_TOKENS = int(os.getenv("SUMMARY_MAX_TOKENS", "3072"))

# Seuil en tokens estimés au-delà duquel on passe en mode hiérarchique :
# fenêtre − génération − consignes et squelette JSON du prompt.
MAX_DIRECT_TOKENS = LLM_MAX_MODEL_LEN - SYNTHESIS_MAX_TOKENS - 2500
# Taille maximale d'un morceau de document soumis à un résumé.
MAX_DOC_TOKENS = LLM_MAX_MODEL_LEN - SUMMARY_MAX_TOKENS - 2000

# Timeout LLM pour la synthèse. À ~20 tokens/s sur le GB10, 6k tokens de JSON
# prennent 5 minutes : les 180 s d'origine faisaient échouer les gros dossiers.
SYNTHESIS_TIMEOUT = float(os.getenv("SYNTHESIS_TIMEOUT", "900"))
MAX_SYNTHESIS_RETRIES = 2


class _Unrecoverable(Exception):
    """Erreur qu'un nouvel essai à l'identique reproduirait (fenêtre, troncature)."""


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """
    Estimation prudente : ~3 caractères par token.

    L'ancienne heuristique (4 caractères) sous-estimait le français médical —
    accents, dates, codes — et laissait passer en mode direct des dossiers
    qui dépassaient la fenêtre du modèle.
    """
    return len(text) // 3 + 1


def _extract_json_from_response(text: str) -> dict[str, Any]:
    """
    Extrait le JSON de la réponse du LLM.
    Le LLM peut parfois ajouter du texte autour du JSON malgré les instructions.
    """
    # Cherche le premier '{' et le dernier '}'
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Aucun JSON trouvé dans la réponse : {text[:200]}")
    json_str = text[start : end + 1]
    data = json.loads(json_str)
    if not isinstance(data, dict):
        raise ValueError("La synthèse n'est pas un objet JSON")
    return data


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    vllm_url: str,
    model_name: str,
    max_tokens: int = SYNTHESIS_MAX_TOKENS,
    timeout: float = SYNTHESIS_TIMEOUT,
) -> str:
    """
    Appel vLLM et retourne le contenu texte de la réponse.

    Rejoue une fois les erreurs transitoires. Une fenêtre dépassée ou une
    réponse tronquée sont remontées sans nouvel essai : l'appelant change de
    stratégie.
    """
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.05,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(1, MAX_SYNTHESIS_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
                resp = await client.post(f"{vllm_url}/chat/completions", json=payload)
            if resp.status_code == 400:
                raise _Unrecoverable(f"requête refusée : {resp.text[:200]}")
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise _Unrecoverable("réponse tronquée (max_tokens atteint)")
            return choice["message"]["content"] or ""
        except _Unrecoverable:
            raise
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            if attempt == MAX_SYNTHESIS_RETRIES:
                raise
            logger.warning("Synthèse : nouvel essai après %s: %s", type(exc).__name__, exc)
            await asyncio.sleep(3)
    raise RuntimeError("synthèse sans réponse")


# ---------------------------------------------------------------------------
# Stratégie directe (un seul appel LLM)
# ---------------------------------------------------------------------------


async def _synthesize_direct(
    all_docs_text: str,
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """Synthèse en un seul appel LLM. Utilisée quand le texte tient dans la fenêtre."""
    user_prompt = build_synthesis_prompt(all_docs_text)
    raw = await _call_llm(SYSTEM_PROMPT_SYNTHESIS, user_prompt, vllm_url, model_name)
    return _extract_json_from_response(raw)


# ---------------------------------------------------------------------------
# Stratégie hiérarchique (résumé par doc puis fusion)
# ---------------------------------------------------------------------------


def _split_document(name: str, text: str, max_tokens: int = MAX_DOC_TOKENS) -> list[tuple[str, str]]:
    """
    Découpe un document trop long pour un seul résumé.

    Coupe sur les sauts de paragraphe les plus proches de la limite, pour ne
    pas scinder une ligne de diagnostic en deux.
    """
    if estimate_tokens(text) <= max_tokens:
        return [(name, text)]
    max_chars = max_tokens * 3
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            parts.append(rest)
            break
        cut = rest.rfind("\n\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = rest.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip()
    total = len(parts)
    return [(f"{name} (partie {i}/{total})", part) for i, part in enumerate(parts, start=1)]


async def _summarize_single_doc(
    doc_text: str,
    doc_name: str,
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """Résumé d'un seul document médical."""
    user_prompt = build_per_doc_summary_prompt(doc_text, doc_name)
    raw = await _call_llm(SYSTEM_PROMPT_PER_DOC_SUMMARY, user_prompt, vllm_url, model_name,
                          max_tokens=SUMMARY_MAX_TOKENS)
    return _extract_json_from_response(raw)


async def _merge_summaries(
    summaries: list[dict[str, Any]],
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """Fusionne les résumés de chaque document en un dossier unifié."""
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    if estimate_tokens(summaries_json) > MAX_DIRECT_TOKENS:
        raise _Unrecoverable("résumés trop volumineux pour une fusion par le modèle")
    user_prompt = build_merge_summaries_prompt(summaries_json)
    raw = await _call_llm(SYSTEM_PROMPT_MERGE_SUMMARIES, user_prompt, vllm_url, model_name)
    return _extract_json_from_response(raw)


def _combine_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Fusion déterministe des résumés par document, sans appel LLM.

    Repli de `_merge_summaries` : moins synthétique (les doublons entre
    documents subsistent), mais aucune information n'est perdue — ce qui
    compte davantage pour remplir un formulaire que l'élégance du résumé.
    """
    combined: dict[str, Any] = {
        "patient": {}, "diagnostics": [], "incapacites_travail": [], "traitements": [],
        "medecins": [], "dates_cles": {}, "pronostic": None, "canton_traitement": None,
    }
    pronostics: list[str] = []
    for summary in summaries:
        source = summary.get("document")
        for key, value in (summary.get("patient") or {}).items():
            if value and not combined["patient"].get(key):
                combined["patient"][key] = value
        for key in ("diagnostics", "incapacites_travail"):
            for entry in summary.get(key) or []:
                if isinstance(entry, dict):
                    entry = {**entry, "document_source": entry.get("document_source") or source}
                combined[key].append(entry)
        for key in ("traitements", "medecins"):
            combined[key].extend(summary.get(key) or [])
        dates = summary.get("dates_cles") or {}
        if isinstance(dates, dict):
            for key, value in dates.items():
                if value and not combined["dates_cles"].get(key):
                    combined["dates_cles"][key] = value
        if summary.get("dates_importantes"):
            combined.setdefault("dates_importantes", []).extend(summary["dates_importantes"])
        if summary.get("pronostic"):
            pronostics.append(str(summary["pronostic"]))
        if summary.get("canton_traitement") and not combined["canton_traitement"]:
            combined["canton_traitement"] = summary["canton_traitement"]
    combined["pronostic"] = "\n".join(pronostics) or None
    return combined


async def _synthesize_hierarchical(
    docs: list[tuple[str, str]],  # [(doc_name, doc_text), ...]
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """
    Synthèse hiérarchique : résumé par document (3 en parallèle pour ne pas
    saturer le GPU), puis fusion en un seul appel.
    """
    parts = [part for name, text in docs for part in _split_document(name, text)]
    sem = asyncio.Semaphore(3)  # 3 docs en parallèle max

    async def _summarize_with_sem(name: str, text: str) -> dict[str, Any] | None:
        async with sem:
            try:
                summary = await _summarize_single_doc(text, name, vllm_url, model_name)
                summary.setdefault("document", name)
                return summary
            except Exception as exc:
                logger.warning("Échec résumé doc '%s' : %s", name, exc)
                return None

    results = await asyncio.gather(*[_summarize_with_sem(name, text) for name, text in parts])
    summaries = [r for r in results if r is not None]

    if not summaries:
        raise ValueError("Aucun résumé de document n'a pu être produit")

    if len(summaries) == 1:
        return summaries[0]

    try:
        return await _merge_summaries(summaries, vllm_url, model_name)
    except Exception as exc:
        logger.warning("Fusion des résumés par le modèle impossible (%s) — fusion déterministe", exc)
        return _combine_summaries(summaries)


# ---------------------------------------------------------------------------
# Point d'entrée public
# ---------------------------------------------------------------------------


async def run_medical_synthesis(
    ocr_results: list[dict[str, str]],  # [{"filename": ..., "markdown": ...}, ...]
    vllm_url: str,
    model_name: str,
) -> dict[str, Any] | None:
    """
    Lance la synthèse médicale à partir des résultats OCR.

    Args:
        ocr_results: liste de dicts {"filename": str, "markdown": str}
        vllm_url: URL du service vLLM, préfixe /v1 inclus (ex: "http://vllm:8000/v1")
        model_name: nom du modèle vLLM

    Returns:
        dict Python représentant le dossier médical synthétisé,
        ou None si la synthèse a échoué (le pipeline continue sur les seuls documents).
    """
    if not ocr_results:
        logger.warning("run_medical_synthesis : aucun document OCR fourni")
        return None

    t0 = time.time()

    try:
        # Ordre stable : même dossier, même prompt — et même préfixe pour vLLM.
        docs: list[tuple[str, str]] = []
        for r in sorted(ocr_results, key=lambda d: d.get("filename", "")):
            name = r.get("filename", "document_inconnu")
            text = r.get("markdown", "")
            if text.strip():
                docs.append((name, text))

        if not docs:
            logger.warning("run_medical_synthesis : tous les documents OCR sont vides")
            return None

        # Estimer le nombre de tokens
        separator = "\n\n" + "=" * 60 + "\n\n"
        all_docs_text = separator.join(
            f"--- DOCUMENT : {name} ---\n\n{text}" for name, text in docs
        )
        total_tokens = estimate_tokens(all_docs_text)

        logger.info(
            "Synthèse médicale : %d documents, ~%d tokens estimés",
            len(docs),
            total_tokens,
        )

        result = None
        strategy = "hiérarchique"
        if total_tokens <= MAX_DIRECT_TOKENS:
            try:
                result = await _synthesize_direct(all_docs_text, vllm_url, model_name)
                strategy = "directe"
            except Exception as exc:
                # Un seul document mal formé ou un JSON tronqué ne justifie pas
                # de renoncer : les résumés par document tiennent plus sûrement.
                logger.warning("Synthèse directe impossible (%s: %s) — passage en hiérarchique",
                               type(exc).__name__, exc)
        if result is None:
            result = await _synthesize_hierarchical(docs, vllm_url, model_name)

        elapsed = time.time() - t0
        nb_diagnostics = len(result.get("diagnostics") or [])
        nb_incapacites = len(result.get("incapacites_travail") or [])

        logger.info(
            "Synthèse médicale terminée (%s) en %.1fs — %d diagnostics, %d périodes d'incapacité",
            strategy,
            elapsed,
            nb_diagnostics,
            nb_incapacites,
        )

        return result

    except Exception as exc:
        elapsed = time.time() - t0
        logger.error(
            "Échec de la synthèse médicale après %.1fs : %s — "
            "le pipeline continuera sur les seuls documents",
            elapsed,
            exc,
        )
        return None
