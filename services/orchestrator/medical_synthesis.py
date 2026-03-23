"""
medical_synthesis.py — Synthèse médicale globale à partir de tous les documents OCR.

Deux stratégies selon le volume de texte :
- Directe  : tous les documents tiennent dans une seule fenêtre de contexte (<= MAX_DIRECT_TOKENS)
- Hiérarchique : trop de texte → résumé par document puis fusion

Le résultat est un dict Python (issu du JSON LLM) contenant diagnostics, incapacités, etc.
En cas d'échec, retourne None pour que le pipeline continue avec le RAG pur.
"""

import json
import logging
import re
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

# Seuil en tokens estimés au-delà duquel on passe en mode hiérarchique.
# 28k laisse ~4k tokens pour le prompt système et la réponse JSON dans une fenêtre de 32k.
MAX_DIRECT_TOKENS = 28_000

# Timeout LLM pour la synthèse (plus long qu'une extraction de champ classique)
SYNTHESIS_TIMEOUT = 180  # secondes


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimation rapide : ~4 caractères = 1 token (heuristique valable pour FR/EN)."""
    return len(text) // 4


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
    return json.loads(json_str)


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    vllm_url: str,
    model_name: str,
    timeout: int = SYNTHESIS_TIMEOUT,
) -> str:
    """Appel vLLM et retourne le contenu texte de la réponse."""
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.05,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{vllm_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


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
    raw = await _call_llm(
        SYSTEM_PROMPT_SYNTHESIS,
        user_prompt,
        vllm_url,
        model_name,
    )
    return _extract_json_from_response(raw)


# ---------------------------------------------------------------------------
# Stratégie hiérarchique (résumé par doc puis fusion)
# ---------------------------------------------------------------------------


async def _summarize_single_doc(
    doc_text: str,
    doc_name: str,
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """Résumé d'un seul document médical."""
    user_prompt = build_per_doc_summary_prompt(doc_text, doc_name)
    raw = await _call_llm(
        SYSTEM_PROMPT_PER_DOC_SUMMARY,
        user_prompt,
        vllm_url,
        model_name,
        timeout=120,
    )
    return _extract_json_from_response(raw)


async def _merge_summaries(
    summaries: list[dict[str, Any]],
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """Fusionne les résumés de chaque document en un dossier unifié."""
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    user_prompt = build_merge_summaries_prompt(summaries_json)
    raw = await _call_llm(
        SYSTEM_PROMPT_MERGE_SUMMARIES,
        user_prompt,
        vllm_url,
        model_name,
        timeout=SYNTHESIS_TIMEOUT,
    )
    return _extract_json_from_response(raw)


async def _synthesize_hierarchical(
    docs: list[tuple[str, str]],  # [(doc_name, doc_text), ...]
    vllm_url: str,
    model_name: str,
) -> dict[str, Any]:
    """
    Synthèse hiérarchique : résumé par document en séquentiel (pour ne pas saturer le GPU),
    puis fusion en un seul appel.
    """
    import asyncio

    summaries = []
    sem = asyncio.Semaphore(3)  # 3 docs en parallèle max

    async def _summarize_with_sem(name: str, text: str) -> dict[str, Any] | None:
        async with sem:
            try:
                return await _summarize_single_doc(text, name, vllm_url, model_name)
            except Exception as exc:
                logger.warning("Échec résumé doc '%s' : %s", name, exc)
                return None

    tasks = [_summarize_with_sem(name, text) for name, text in docs]
    results = await asyncio.gather(*tasks)
    summaries = [r for r in results if r is not None]

    if not summaries:
        raise ValueError("Aucun résumé de document n'a pu être produit")

    if len(summaries) == 1:
        return summaries[0]

    return await _merge_summaries(summaries, vllm_url, model_name)


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
        vllm_url: URL du service vLLM (ex: "http://vllm:8000")
        model_name: nom du modèle vLLM

    Returns:
        dict Python représentant le dossier médical synthétisé,
        ou None si la synthèse a échoué (le pipeline continue avec RAG pur).
    """
    if not ocr_results:
        logger.warning("run_medical_synthesis : aucun document OCR fourni")
        return None

    t0 = time.time()

    try:
        # Construire le texte complet de tous les documents
        docs: list[tuple[str, str]] = []
        for r in ocr_results:
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

        if total_tokens <= MAX_DIRECT_TOKENS:
            result = await _synthesize_direct(all_docs_text, vllm_url, model_name)
            strategy = "directe"
        else:
            result = await _synthesize_hierarchical(docs, vllm_url, model_name)
            strategy = "hiérarchique"

        elapsed = time.time() - t0
        nb_diagnostics = len(result.get("diagnostics", []))
        nb_incapacites = len(result.get("incapacites_travail", []))

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
            "le pipeline continuera avec le RAG pur",
            elapsed,
            exc,
        )
        return None
