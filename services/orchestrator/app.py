"""
=============================================================================
DOCTORFILL - ORCHESTRATOR HUB
=============================================================================
"""

import os
import re
import secrets
import uuid
import asyncio
import httpx
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Set
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import chromadb
import shutil

from core.extract import extract_xfa_datasets, PDFNoXFAError
from core.fill import update_datasets
from core.inject import inject_datasets
from core.checkbox import discover_checkbox_paths, normalize_checkboxes
from core.acroform import detect_form_type, fill_acroform
from core.fields import batch_fields, collect_form_values, normalize_value, prepare_fields
from core.provenance import SourceIndex, ground_value
import extraction
import stats
from medical_synthesis import run_medical_synthesis
from prompts import (SYSTEM_PROMPT_BATCH_EXTRACT, build_batch_extraction_messages,
                     build_chat_messages, build_synthesis_refine_messages)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- [SEC-21] Désactivation Swagger/ReDoc en production
_disable_docs = os.getenv("DISABLE_DOCS", "false").lower() == "true"
app = FastAPI(
    title="DoctorFill - Orchestrator Hub",
    docs_url=None if _disable_docs else "/docs",
    redoc_url=None if _disable_docs else "/redoc",
    openapi_url=None if _disable_docs else "/openapi.json",
)

# --- [SEC-09] MIDDLEWARE CORS sécurisé
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _raw_origins.strip() == "*" else [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # [SEC-09] credentials=True uniquement si origines explicites (pas wildcard)
    allow_credentials=("*" not in ALLOWED_ORIGINS),
    allow_methods=["GET", "POST"],
    allow_headers=["*", "X-API-Key"]
)

# --- [SEC-22] Clé API pour protéger les endpoints contre les appels non autorisés
API_KEY = os.getenv("API_KEY", "")

from fastapi import Request

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Bypass : health check, CORS preflight, docs
    if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json") or request.method == "OPTIONS":
        return await call_next(request)
    # Si API_KEY est définie, on vérifie le header
    if API_KEY:
        client_key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(client_key, API_KEY):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": "API key invalide."})
    return await call_next(request)

# [SEC-13] Defaults = noms de services Docker (réseau interne)
MARKER_URL = os.getenv("MARKER_URL", "http://marker_ocr:8082")
TEI_URL = os.getenv("TEI_URL", "http://tei:8081")
VLLM_URL = os.getenv("VLLM_URL", "http://vllm:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-AWQ")

chroma_client = chromadb.EphemeralClient()

# --- Dossier de logs de debug (markdown OCR, chunks, résultats LLM)
DEBUG_LOG_DIR = Path(os.getenv("DEBUG_LOG_DIR", "/tmp/doctorfill_debug"))
DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
# Ces journaux contiennent le texte intégral des dossiers patients. Ils étaient
# conservés sans limite ; ils suivent désormais la rétention des jobs, sauf
# demande explicite pour une session de mise au point.
KEEP_DEBUG_LOGS = os.getenv("KEEP_DEBUG_LOGS", "false").lower() == "true"

JOBS: Dict[str, Dict[str, Any]] = {}
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "3600"))

# --- [SEC-06] Limite de jobs concurrents
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "20"))

# --- [SEC-05] Limites d'upload
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50 MB
MAX_FILES = int(os.getenv("MAX_FILES", "200"))

# --- [SEC-03] Whitelist des form_id valides (construite au démarrage)
VALID_FORM_IDS: Set[str] = set()

# Expose aussi les templates générés mais pas encore relus (`_reviewed: false`).
SHOW_DRAFT_FORMS = os.getenv("SHOW_DRAFT_FORMS", "false").lower() == "true"


def _read_version() -> str:
    """
    Version du backend, lue depuis le fichier VERSION à la racine du dépôt.

    Le Dockerfile ne copie que services/orchestrator/, d'où la copie locale du
    fichier ; APP_VERSION permet de l'injecter au build sans y toucher.
    """
    from_env = os.getenv("APP_VERSION", "").strip()
    if from_env:
        return from_env
    for candidate in (Path("VERSION"), Path(__file__).resolve().parents[2] / "VERSION"):
        try:
            content = candidate.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            continue
    return "inconnue"


APP_VERSION = _read_version()

# Identité de build : la version seule ne distingue pas deux images construites
# depuis des commits différents, ce qui est le cas courant entre deux releases.
# Le commit et la date sont injectés au build (voir Dockerfile) ; leur absence
# signale une image construite hors du script de déploiement.
APP_COMMIT = os.getenv("APP_COMMIT", "").strip() or "inconnu"
APP_BUILT_AT = os.getenv("APP_BUILT_AT", "").strip() or "inconnue"


def _build_id() -> str:
    """
    Identifiant de build complet, au format SemVer 2.0 avec métadonnées.

    Exemple : `0.2.0+ed0a9d7.20260808T2231Z`. Le `+…` n'entre pas dans la
    comparaison de versions (spec SemVer), ce qui est exactement le
    comportement voulu : deux builds d'une même version restent compatibles.
    """
    if APP_COMMIT == "inconnu":
        return APP_VERSION
    stamp = APP_BUILT_AT.replace("-", "").replace(":", "")
    return f"{APP_VERSION}+{APP_COMMIT}" + (f".{stamp}" if APP_BUILT_AT != "inconnue" else "")


APP_BUILD_ID = _build_id()

# --- Contrôle qualité de l'extraction
# La confiance est établie par core/provenance : la valeur produite est-elle
# retrouvable dans le texte des documents, et où ? Le seuil de rerank qui tenait
# ce rôle notait la source secondaire du prompt et flaggait 94 champs sur 112,
# dont 76 correctement remplis — voir l'en-tête de core/provenance.py.
#
# Budget de tokens, délais et reprises de l'appel d'extraction : voir extraction.py.

# Extraits retenus par champ après rerank, parmi les candidats de la recherche vectorielle.
RETRIEVAL_CANDIDATES = int(os.getenv("RETRIEVAL_CANDIDATES", "30"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "8"))
# Taille d'un lot d'extraction ; les occurrences d'une structure répétée restent
# groupées jusqu'à MAX_FAMILY_SIZE (voir core/fields.batch_fields).
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "8"))
MAX_FAMILY_SIZE = int(os.getenv("MAX_FAMILY_SIZE", "32"))

# Requêtes LLM en vol. À garder aligné sur --max-num-seqs de vLLM (docker-compose) :
# en dessous, le batch continu de vLLM tourne à vide ; au-dessus, les requêtes
# excédentaires attendent simplement dans sa file.
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "24"))
RERANK_CONCURRENCY = int(os.getenv("RERANK_CONCURRENCY", "5"))
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "3"))

# Exécutions de pipeline menées de front. Mesuré sur le GB10 : une seule
# exécution occupe déjà 17 des 24 emplacements de vLLM, et la puce est limitée
# par sa bande passante mémoire. Au-delà de deux, chaque traitement ralentit
# proportionnellement sans que le débit total progresse — autant faire attendre
# le troisième, avec un temps annoncé, que dégrader tout le monde.
MAX_PARALLEL_JOBS = int(os.getenv("MAX_PARALLEL_JOBS", "2"))

# Ces sémaphores sont *globaux*, pas par job. Créés dans le pipeline, deux jobs
# concurrents ouvraient 2 × LLM_CONCURRENCY requêtes vers un vLLM qui en sert 24,
# et 2 × 3 OCR sur le GPU : chacun croyait respecter une limite que l'autre
# ignorait. asyncio.Semaphore ne se lie plus à une boucle depuis Python 3.10,
# leur création au chargement du module est donc sûre.
_LLM_SEM = asyncio.Semaphore(LLM_CONCURRENCY)
_RERANK_SEM = asyncio.Semaphore(RERANK_CONCURRENCY)
_OCR_SEM = asyncio.Semaphore(OCR_CONCURRENCY)
_PIPELINE_SEM = asyncio.Semaphore(MAX_PARALLEL_JOBS)

# Embeddings des questions d'un template : identiques d'un job à l'autre et d'un
# re-run à l'autre, alors qu'ils étaient recalculés à chaque fois.
_QUESTION_EMB_CACHE: Dict[str, List] = {}


def _scan_templates() -> Set[str]:
    """
    Liste les formulaires publiables.

    Un template généré par tools/gen_template.py porte `_reviewed: false` tant
    que ses questions n'ont pas été relues. Le proposer à un clinicien donnerait
    un formulaire partiellement rempli sans qu'il sache lesquels des champs ont
    été ignorés — on ne l'expose donc qu'une fois relu. SHOW_DRAFT_FORMS lève la
    barrière pour la mise au point.
    """
    available: Set[str] = set()
    template_dir = Path("template")
    if not template_dir.exists():
        return available

    for path in sorted(template_dir.glob("Form_*.json")):
        form_id = path.stem.replace("Form_", "")
        try:
            reviewed = json.loads(path.read_text(encoding="utf-8")).get("_reviewed", True)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"Template illisible, ignoré ({path.name}): {exc}")
            continue
        if not (Path("forms") / f"Form_{form_id}.pdf").exists():
            # Les PDF vierges ne sont pas versionnés (voir .gitignore) : ils sont
            # récupérés par tools/gen_catalog.py. Sans PDF, le job échouerait
            # à l'étape d'injection — autant ne pas proposer le formulaire.
            logger.warning(f"Template {form_id} sans PDF dans forms/ — masqué")
            continue
        if reviewed or SHOW_DRAFT_FORMS:
            available.add(form_id)
        else:
            logger.info(f"Template {form_id} non relu — masqué (SHOW_DRAFT_FORMS=true pour l'afficher)")
    return available


@app.on_event("startup")
async def startup_tasks():
    """Initialisation au démarrage : whitelist form_id + cleanup périodique."""
    # [SEC-03] Scanner les templates disponibles
    VALID_FORM_IDS.update(_scan_templates())
    logger.info(f"Form IDs valides: {sorted(VALID_FORM_IDS)}")

    asyncio.create_task(_cleanup_expired_jobs())


async def _cleanup_expired_jobs():
    """Tâche de fond qui purge les jobs terminés et leurs fichiers temporaires."""
    while True:
        await asyncio.sleep(300)
        try:
            _purge_expired_jobs()
        except Exception as exc:
            # Une exception ici arrêtait la tâche pour de bon : plus aucun job,
            # ni aucun dossier patient sur disque, n'était purgé ensuite.
            logger.error(f"Cleanup: échec de la purge ({type(exc).__name__}: {exc})")


def _purge_expired_jobs() -> None:
    """Purge les jobs terminés depuis plus de JOB_RETENTION_SECONDS et leurs fichiers."""
    now = time.time()
    expired = [
        jid for jid, data in JOBS.items()
        if data.get("status") in ("completed", "failed")
        and now - data.get("completed_at", now) > JOB_RETENTION_SECONDS
    ]
    for jid in expired:
        tmp_dir = Path(f"/tmp/{jid}")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.info(f"Cleanup: fichiers temporaires supprimés pour job {jid}")
        debug_dir = JOBS[jid].get("_debug_dir")
        if debug_dir and not KEEP_DEBUG_LOGS:
            shutil.rmtree(debug_dir, ignore_errors=True)
        try:
            chroma_client.delete_collection(name=f"col_{jid}")
        except Exception:
            pass
        JOBS.pop(jid, None)
    if expired:
        logger.info(f"Cleanup: {len(expired)} job(s) expiré(s) purgé(s)")


# ---------------------------------------------------
# --- UTILS ---

class UserFacingError(Exception):
    """
    Échec dont la cause peut être dite à l'utilisateur sans rien exposer.

    [SEC-10] garde les erreurs internes derrière un message générique ; celles-ci
    décrivent le dossier soumis (« aucun document lisible ») et lui permettent
    d'agir plutôt que de « réessayer » en vain.
    """


def _sanitize_filename(filename: str, index: int) -> str:
    """
    [SEC-01] Assainit un nom de fichier uploadé.
    Empêche le path traversal en ne gardant que le basename.
    """
    if not filename:
        return f"upload_{index}.pdf"
    # Supprimer les null bytes
    safe = filename.replace("\x00", "")
    # Ne garder que le nom de fichier (pas le chemin)
    safe = Path(safe).name
    # Fallback si vide après nettoyage
    if not safe:
        return f"upload_{index}.pdf"
    return safe


_TEI_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


async def _tei_post(client: httpx.AsyncClient, route: str, payload: Dict, timeout: float) -> Dict:
    """
    Appel TEI avec reprises sur erreur transitoire.

    L'embedding n'en avait aucune : un seul hoquet du service pendant l'OCR
    faisait échouer tout le job, après plusieurs minutes de traitement.
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.post(f"{TEI_URL}{route}", json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or attempt == max_retries:
                raise
            err: Exception = e
        except _TEI_TRANSIENT as e:
            if attempt == max_retries:
                raise
            err = e
        logger.warning(f"TEI {route} retry {attempt}/{max_retries}: {type(err).__name__}: {err}")
        await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"TEI {route} sans réponse")


async def fetch_embeddings(client: httpx.AsyncClient, texts: List[str]):
    return (await _tei_post(client, "/embed", {"texts": texts}, timeout=120.0))["embeddings"]


async def fetch_embeddings_batched(client: httpx.AsyncClient, texts: List[str], batch_size: int = 64) -> List:
    """Embed par batches pour éviter les timeouts sur de gros volumes."""
    all_embeddings: List = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embs = await fetch_embeddings(client, batch)
        all_embeddings.extend(embs)
    return all_embeddings


async def fetch_question_embeddings(client: httpx.AsyncClient, form_id: str,
                                    questions: List[str]) -> List:
    """
    Embeddings des questions d'un template, mis en cache par formulaire.

    Les questions sont statiques : les recalculer à chaque job et à chaque re-run
    coûtait un aller-retour TEI pour un résultat identique. La clé inclut le
    contenu des questions pour que toute modification du template invalide le cache.
    """
    signature = f"{form_id}:{hash(tuple(questions))}"
    cached = _QUESTION_EMB_CACHE.get(signature)
    if cached is not None:
        return cached
    embeddings = await fetch_embeddings_batched(client, questions)
    _QUESTION_EMB_CACHE[signature] = embeddings
    return embeddings


async def fetch_rerank(client: httpx.AsyncClient, query: str, docs: List[str],
                       rerank_sem: asyncio.Semaphore = None):
    """Rerank avec semaphore + retry sur erreur transitoire."""
    if rerank_sem:
        async with rerank_sem:
            data = await _tei_post(client, "/rerank", {"query": query, "documents": docs}, timeout=300.0)
    else:
        data = await _tei_post(client, "/rerank", {"query": query, "documents": docs}, timeout=300.0)
    return data["results"]


def _synthesis_as_source(synthesis: Dict | None) -> List[Dict]:
    """
    Expose la synthèse médicale comme source indexable, marquée comme dérivée.

    C'est une source du prompt d'extraction : sans elle dans l'index, toute
    valeur citée depuis la synthèse plutôt que depuis un document brut était
    déclarée non tracée. Le drapeau `derived` évite l'excès inverse — la
    synthèse est une production du modèle, s'y adosser ne vaut pas preuve.
    """
    if not synthesis:
        return []
    return [{
        "filename": "synthèse médicale",
        "markdown": json.dumps(synthesis, ensure_ascii=False, indent=2),
        "derived": True,
    }]


# Réponses choisies plutôt que recopiées : les retrouver dans le texte ne prouve rien.
_NON_LITERAL_TYPES = {"bool", "choice"}


def _annotate_confidence(results: List[Dict], source_index: SourceIndex,
                         field_score_map: Dict[str, float], fields_by_id: Dict[str, Dict]) -> None:
    """
    Normalise chaque valeur extraite et la rattache au texte dont elle provient.

    La normalisation (date au format JJ.MM.AAAA, « non mentionné » → vide, oui/non
    canonique…) a lieu ici plutôt qu'au remplissage : le clinicien voit dans
    l'application exactement ce qui sera écrit dans le formulaire. La valeur
    brute du modèle reste disponible dans `raw_value` quand elle diffère.

    Aucun appel LLM supplémentaire, aucun seuil : la valeur se retrouve dans les
    documents ou elle ne s'y retrouve pas. Le résultat porte le verdict
    (`grounding`), et l'ancrage quand il existe — document, page, extrait — de
    quoi vérifier d'un coup d'œil plutôt que d'avoir à croire le modèle.

    On ne supprime jamais une valeur réelle — c'est au clinicien de trancher.
    """
    for res in results:
        payload = res.get("result")
        if not isinstance(payload, dict):
            continue
        fid = str(res["id"])
        f_def = fields_by_id.get(fid, {})
        score = field_score_map.get(fid)
        payload["rerank_score"] = round(score, 4) if score is not None else None

        raw = str(payload.get("value") or "").strip()
        value = normalize_value(raw, f_def)
        if value != raw:
            payload["raw_value"] = raw
        payload["value"] = value
        if not value:
            payload["source_quote"] = ""
            continue
        payload.update(ground_value(value, str(payload.get("source_quote") or ""), source_index,
                                    literal=f_def.get("type") not in _NON_LITERAL_TYPES))


async def _retrieve(client: httpx.AsyncClient, col, n_chunks: int, form_id: str,
                    fields: List[Dict]) -> tuple[Dict[str, List[str]], Dict[str, float]]:
    """
    Extraits pertinents de chaque champ : recherche vectorielle puis rerank.

    La requête est la question débarrassée de ses consignes de format, enrichie
    du contexte de structure (voir core/fields.contextualize). Un rerank en
    échec ne fait plus échouer le job : le champ garde l'ordre de la recherche
    vectorielle, moins fin mais exploitable.
    """
    if n_chunks == 0 or not fields:
        return {}, {}
    queries = [f.get("retrieval_query") or f["question"] for f in fields]
    q_embs = await fetch_question_embeddings(client, form_id, queries)

    async def _one(query: str, q_emb) -> tuple[List[str], float | None]:
        hits = col.query(query_embeddings=[q_emb],
                         n_results=min(RETRIEVAL_CANDIDATES, n_chunks))["documents"][0]
        try:
            reranked = await fetch_rerank(client, query, hits, rerank_sem=_RERANK_SEM)
        except Exception as exc:
            logger.warning(f"Rerank indisponible, ordre vectoriel conservé : {type(exc).__name__}: {exc}")
            return hits[:RETRIEVAL_TOP_K], None
        top = reranked[:RETRIEVAL_TOP_K]
        # Le meilleur score sert d'indice de pertinence du retrieval pour ce champ.
        best = float(top[0].get("score", 0.0)) if top else 0.0
        return [r["document"] for r in top], best

    retrieved = await asyncio.gather(*[_one(q, e) for q, e in zip(queries, q_embs)])
    chunk_map = {str(f["id"]): cks for f, (cks, _) in zip(fields, retrieved)}
    score_map = {str(f["id"]): s for f, (_, s) in zip(fields, retrieved) if s is not None}
    return chunk_map, score_map


async def _extract_fields(client: httpx.AsyncClient, job_id: str, form_id: str, template: Dict,
                          col, n_chunks: int, synthesis: Dict | None, documents: List[Dict],
                          on_progress) -> List[Dict]:
    """
    Extraction de tous les champs d'un formulaire. Partagée par le pipeline et le re-run.

    Deux modes de contexte :
    - dossier intégral, quand il tient dans la fenêtre du modèle — le cas des
      dossiers usuels. Aucune information ne dépend alors de la qualité du
      retrieval, et vLLM ne calcule qu'une fois le préfixe commun à tous les lots ;
    - extraits choisis par retrieval + rerank, au-delà.

    La synthèse médicale est transmise en entier à chaque lot. Elle était filtrée
    par numéro de section selon une table écrite pour la mise en page du seul
    formulaire AVS : sur les autres formulaires, les champs d'incapacité de
    travail, de diagnostic ou de médecin ne recevaient pas la partie de la
    synthèse qui les concernait.
    """
    fields = prepare_fields(template)
    fields_by_id = {str(f["id"]): f for f in fields}
    batches = batch_fields(fields, max_batch_size=MAX_BATCH_SIZE, max_family_size=MAX_FAMILY_SIZE)
    if not batches:
        return []

    source_index = SourceIndex(documents, _synthesis_as_source(synthesis))
    docs_text = extraction.full_documents_text(documents)
    synthesis_json = json.dumps(synthesis, ensure_ascii=False) if synthesis else None

    # Budget : fenêtre du modèle − génération − marge − parties fixes du prompt.
    fields_tokens = max(
        extraction.estimate_tokens("\n".join(
            (f.get("prompt_question") or f["question"]) + " ".join(f.get("options") or []) + " " * 40
            for f in batch))
        for batch in batches)
    prompt_budget = (extraction.LLM_MAX_MODEL_LEN - extraction.MAX_TOKENS_EXTRACT
                     - extraction.PROMPT_SAFETY_TOKENS
                     - extraction.estimate_tokens(SYSTEM_PROMPT_BATCH_EXTRACT) - fields_tokens)
    docs_budget = prompt_budget - (extraction.estimate_tokens(synthesis_json) if synthesis_json else 0)
    if synthesis_json and docs_budget < 3000:
        logger.warning(f"[{job_id[:8]}] Synthèse trop volumineuse pour le prompt d'extraction — omise")
        synthesis_json, docs_budget = None, prompt_budget

    full_mode = extraction.estimate_tokens(docs_text) <= min(extraction.FULL_CONTEXT_MAX_TOKENS, docs_budget)
    rag_budget = max(1000, min(extraction.RAG_CONTEXT_TOKENS, docs_budget))

    if full_mode:
        field_chunk_map, field_score_map = {}, {}
        logger.info(f"[{job_id[:8]}] {len(fields)} champs, {len(batches)} lots — dossier intégral "
                    f"(~{extraction.estimate_tokens(docs_text)} tokens)")
    else:
        field_chunk_map, field_score_map = await _retrieve(client, col, n_chunks, form_id, fields)
        logger.info(f"[{job_id[:8]}] {len(fields)} champs, {len(batches)} lots — extraits "
                    f"(budget {rag_budget} tokens/lot)")

    def build_messages(batch: List[Dict], scale: float) -> List[Dict]:
        if full_mode and scale >= 1.0:
            return build_batch_extraction_messages(batch, synthesis_json, docs_text, full_documents=True)
        if full_mode:
            # Repli rare : l'estimation a sous-évalué le dossier. On tronque plutôt
            # que d'abandonner le champ.
            limit = int(docs_budget * scale) * 3
            return build_batch_extraction_messages(batch, synthesis_json, docs_text[:limit])
        if not field_chunk_map:
            # Index vide (embeddings indisponibles) : le début du dossier plutôt
            # que rien.
            return build_batch_extraction_messages(batch, synthesis_json,
                                                   docs_text[:int(rag_budget * scale) * 3])
        context = extraction.build_rag_context(batch, field_chunk_map, int(rag_budget * scale))
        return build_batch_extraction_messages(batch, synthesis_json, context)

    done = 0

    async def _run_batch(batch: List[Dict]) -> List[Dict]:
        nonlocal done
        result = await extraction.extract_batch(client, VLLM_URL, VLLM_MODEL, batch,
                                                build_messages, _LLM_SEM)
        _annotate_confidence(result, source_index, field_score_map, fields_by_id)
        done += 1
        on_progress(done, len(batches))
        return result

    batch_results = await asyncio.gather(*[_run_batch(b) for b in batches])
    results = [item for batch in batch_results for item in batch]
    failed = sum(1 for r in results if "error" in r)
    if failed:
        logger.warning(f"[{job_id[:8]}] {failed}/{len(results)} champs en erreur d'extraction")
    return results


_FIELD_ERRORS_WARNING = "champ(s) n'ont pas pu être extraits — à compléter à la main."


def _record_field_errors(job: Dict, results: List[Dict]) -> None:
    """Avertissement sur les champs en erreur, recalculé à chaque passage (re-run compris)."""
    warnings = [w for w in job.setdefault("warnings", []) if not w.endswith(_FIELD_ERRORS_WARNING)]
    failed = sum(1 for r in results if "error" in r)
    if failed:
        warnings.append(f"{failed} {_FIELD_ERRORS_WARNING}")
    job["warnings"] = warnings


def _template_fields_view(template: Dict) -> List[Dict]:
    """Description des champs extraits, pour /fields et le chat."""
    return [
        {"id": f["id"], "label": f.get("label", str(f["id"])),
         "question": f.get("question", ""), "section": str(f["id"]).split(".")[0]}
        for f in prepare_fields(template)
    ]


def _fill_pdf(job_id: str, form_id: str, template: Dict, results: List[Dict],
              tmp_dir: Path, suffix: str = "") -> tuple[Path, str]:
    """
    Écrit les valeurs dans le formulaire PDF. Partagé par le pipeline et le re-run.

    Supporte XFA, AcroForm pur et formulaires hybrides. Le re-run en avait une
    copie qui ignorait les champs calculés et le destinataire cantonal : après
    un re-run, un formulaire AI repartait à l'office AI par défaut du gabarit.

    Returns:
        (chemin du PDF rempli, type de formulaire)
    """
    source_template_path = Path(f"forms/Form_{form_id}.pdf")
    if not source_template_path.exists():
        raise FileNotFoundError(f"Template introuvable pour form_id={form_id}")
    empty_form_path = tmp_dir / f"empty{suffix}.pdf"
    shutil.copy(source_template_path, empty_form_path)

    form_type = detect_form_type(empty_form_path)
    logger.info(f"[{job_id[:8]}] Type de formulaire détecté : {form_type}")

    xfa_values, acro_values = collect_form_values(template, results)
    output_pdf = tmp_dir / f"output{suffix}.pdf"
    if output_pdf.exists():
        output_pdf.unlink()

    if form_type in ("xfa", "hybrid"):
        base_xml = tmp_dir / f"base{suffix}.xml"
        try:
            extract_xfa_datasets(empty_form_path, base_xml)
            checkbox_paths = discover_checkbox_paths(base_xml)
            normalize_checkboxes(xfa_values, checkbox_paths)
            filled_xml = tmp_dir / f"filled{suffix}.xml"
            update_datasets(base_xml, xfa_values, filled_xml, template["fields"])
            inject_datasets(empty_form_path, filled_xml, output_pdf)
        except PDFNoXFAError:
            logger.warning(f"[{job_id[:8]}] XFA introuvable malgré détection hybrid — fallback AcroForm")
            form_type = "acroform"

    if form_type == "acroform" or (form_type == "hybrid" and acro_values):
        # Pour un hybride : repartir du PDF XFA déjà rempli si disponible, sinon template
        acro_source = output_pdf if (form_type == "hybrid" and output_pdf.exists()) else empty_form_path
        fill_acroform(acro_source, acro_values, output_pdf)

    if form_type == "none" or not output_pdf.exists():
        raise ValueError(f"Impossible de remplir le formulaire (type={form_type})")
    return output_pdf, form_type


def _load_template(form_id: str) -> Dict:
    with open(f"template/Form_{form_id}.json", "r", encoding="utf-8") as f:
        return json.load(f)


MAX_OCR_RETRIES = 5


async def _ocr_document(client: httpx.AsyncClient, path: Path) -> str:
    """
    Texte d'un PDF via le service OCR, avec reprises proportionnées à la cause.

    Service injoignable (redémarrage) : jusqu'à 5 tentatives espacées. Délai
    dépassé ou erreur 5xx : une seule reprise — un OCR de dix minutes rejoué
    cinq fois, c'est une heure perdue. Erreur 4xx : le PDF est refusé, inutile
    d'insister.
    """
    content = path.read_bytes()
    last_err: Exception | None = None
    for attempt in range(1, MAX_OCR_RETRIES + 1):
        try:
            resp = await client.post(
                f"{MARKER_URL}/extract",
                files={'file': (path.name, content, 'application/pdf')},
                timeout=httpx.Timeout(600.0, connect=15.0))
            resp.raise_for_status()
            return resp.json().get("markdown", "") or ""
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or attempt >= 2:
                raise
            last_err, delay = e, 5
        except (httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            if isinstance(e, httpx.ConnectTimeout):
                last_err, delay = e, 10 * attempt
            elif attempt >= 2:
                raise
            else:
                last_err, delay = e, 5
        except httpx.NetworkError as e:
            last_err = e
            delay = 10 * attempt if isinstance(e, httpx.ConnectError) else 2 * attempt
        logger.warning(f"OCR retry {attempt}/{MAX_OCR_RETRIES} pour {path.name}: "
                       f"{type(last_err).__name__} (retry in {delay}s)")
        if attempt < MAX_OCR_RETRIES:
            await asyncio.sleep(delay)
    raise last_err or RuntimeError("OCR sans réponse")


async def run_pipeline_task(job_id: str, form_id: str, tmp_dir: Path, report_paths: List[Path]):
    """
    Portier d'exécution : attend un créneau, puis lance le pipeline.

    Au-delà de MAX_PARALLEL_JOBS, on fait patienter plutôt que de ralentir les
    exécutions en cours. Le GB10 est saturé par une seule d'entre elles : lancer
    tout le monde de front ne fait qu'allonger l'attente de chacun, sans rien
    produire de plus vite. Le chronomètre court pendant l'attente — c'est bien le
    temps que l'utilisateur subit.
    """
    _announce_queue(job_id)
    async with _PIPELINE_SEM:
        await _run_pipeline(job_id, form_id, tmp_dir, report_paths)


def _announce_queue(job_id: str) -> None:
    if not _PIPELINE_SEM.locked():
        return
    attente = stats.summary().get("recent_average_seconds")
    repere = f" — environ {attente / 60:.0f} min" if attente else ""
    logger.info(f"[{job_id[:8]}] En file d'attente ({MAX_PARALLEL_JOBS} exécutions en cours)")
    JOBS[job_id].update({
        "status": "processing",
        "message": f"⏳ En file d'attente{repere}…",
        "progress": 2,
    })


async def _run_pipeline(job_id: str, form_id: str, tmp_dir: Path, report_paths: List[Path]):
    """
    Pipeline avec streaming OCR→embed, synthèse médicale globale et semaphores rerank/LLM.
    - STEP 1 : OCR et embedding en parallèle via asyncio.Queue
    - STEP 2 : Synthèse médicale globale (LLM lit tous les documents, produit un JSON structuré)
    - STEP 3 : Extraction des champs (dossier intégral ou RAG, selon sa taille)
    - STEP 4 : Injection XFA / AcroForm
    """
    collection_name = f"col_{job_id}"
    debug_dir = DEBUG_LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:8]}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "markdown").mkdir(exist_ok=True)
    # Connu dès le départ : un job en échec doit lui aussi voir ses journaux purgés.
    JOBS[job_id]["_debug_dir"] = str(debug_dir)
    warnings: List[str] = JOBS[job_id].setdefault("warnings", [])

    timings: Dict[str, float] = {}
    # Résultats OCR bruts (nécessaires pour la synthèse)
    ocr_raw_results: List[Dict[str, str]] = []

    try:
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=10, keepalive_expiry=30)
        async with httpx.AsyncClient(limits=limits) as client:
            total_files = len(report_paths)
            t_pipeline_start = time.perf_counter()

            # ============================================================
            # STEP 1 : OCR + Chunking + Embedding en pipeline streaming
            # ============================================================
            JOBS[job_id].update({"status": "processing",
                                 "message": f"📄 OCR 0/{total_files} documents...", "progress": 5})
            logger.info(f"[{job_id[:8]}] Step 1: OCR+embed pipeline de {total_files} fichiers...")

            t_ocr_start = time.perf_counter()
            ocr_done = 0
            col = chroma_client.get_or_create_collection(name=collection_name)
            chunk_index = 0

            # Queue pour le pipeline OCR → embed ; None marque la fin du flux.
            ocr_queue: asyncio.Queue = asyncio.Queue()

            async def _ocr_one(path: Path) -> None:
                """OCR un PDF et envoie le résultat dans la queue pour embedding."""
                nonlocal ocr_done
                async with _OCR_SEM:
                    try:
                        md_text = await _ocr_document(client, path)
                    except Exception as e:
                        # Un document illisible ne condamne plus tout le dossier : il est
                        # écarté, et l'utilisateur en est averti.
                        logger.error(f"[{job_id[:8]}] OCR abandonné pour {path.name}: "
                                     f"{type(e).__name__}: {e}")
                        warnings.append(f"Document illisible, ignoré : {path.name}")
                        md_text = None
                ocr_done += 1
                JOBS[job_id].update({
                    "message": f"📄 OCR {ocr_done}/{total_files} documents...",
                    "progress": 5 + int(35 * ocr_done / total_files)
                })
                if md_text is None:
                    return
                if not md_text.strip():
                    warnings.append(f"Aucun texte trouvé dans : {path.name}")
                    return
                # Debug : sauvegarder le markdown OCR
                (debug_dir / "markdown" / (path.stem + ".md")).write_text(md_text, encoding="utf-8")
                ocr_raw_results.append({"filename": path.name, "markdown": md_text})
                await ocr_queue.put((path.name, md_text))

            async def _embed_consumer():
                """Consomme la queue OCR, chunk et embed au fil de l'eau."""
                nonlocal chunk_index
                pending_chunks: List[str] = []
                embed_failed = False

                async def _flush():
                    nonlocal chunk_index, pending_chunks, embed_failed
                    if not pending_chunks or embed_failed:
                        pending_chunks = []
                        return
                    try:
                        embeds = await fetch_embeddings_batched(client, pending_chunks)
                    except Exception as e:
                        # L'index ne sert qu'au retrieval des gros dossiers, au chat et au
                        # re-run : son absence dégrade, elle ne justifie pas d'échouer.
                        logger.error(f"[{job_id[:8]}] Embeddings indisponibles : {type(e).__name__}: {e}")
                        warnings.append("Recherche sémantique indisponible : le chat sur le dossier "
                                        "sera limité.")
                        embed_failed, pending_chunks = True, []
                        return
                    ids = [f"{job_id}_{chunk_index + i}" for i in range(len(pending_chunks))]
                    col.add(documents=pending_chunks, embeddings=embeds, ids=ids)
                    chunk_index += len(pending_chunks)
                    logger.info(f"[{job_id[:8]}] Embedded {chunk_index} chunks so far...")
                    pending_chunks = []

                while True:
                    item = await ocr_queue.get()
                    if item is None:
                        break
                    name, md_text = item
                    pending_chunks.extend(extraction.chunk_document(name, md_text))
                    if len(pending_chunks) >= 64:
                        await _flush()
                await _flush()

            # Lancer OCR et embedding en parallèle (pipeline)
            embed_task = asyncio.create_task(_embed_consumer())
            try:
                await asyncio.gather(*[_ocr_one(p) for p in report_paths])
            finally:
                # Toujours clore le flux : sans ce marqueur, le consommateur
                # attendait indéfiniment après une erreur d'OCR.
                await ocr_queue.put(None)
            await embed_task

            # Ordre stable : l'OCR rend les documents dans l'ordre où il les finit.
            ocr_raw_results.sort(key=lambda d: d["filename"])
            if not ocr_raw_results:
                raise UserFacingError(
                    "Aucun texte n'a pu être extrait des documents fournis. "
                    "Vérifiez qu'il s'agit bien de rapports lisibles (PDF non vides, non protégés).")

            t_ocr_end = time.perf_counter()
            timings["ocr_embed_pipeline"] = t_ocr_end - t_ocr_start
            logger.info(f"[{job_id[:8]}] Pipeline OCR+embed terminé: {chunk_index} chunks "
                        f"en {timings['ocr_embed_pipeline']:.1f}s")

            # ============================================================
            # STEP 2 : Synthèse médicale globale
            # ============================================================
            JOBS[job_id].update({
                "status": "processing",
                "message": "🧠 Synthèse médicale de tous les documents...",
                "progress": 42,
            })
            t_synthesis_start = time.perf_counter()
            synthesis = await run_medical_synthesis(ocr_raw_results, VLLM_URL, VLLM_MODEL)
            timings["medical_synthesis"] = time.perf_counter() - t_synthesis_start
            JOBS[job_id]["_source_documents"] = ocr_raw_results

            if synthesis:
                nb_dx = len(synthesis.get("diagnostics") or [])
                nb_it = len(synthesis.get("incapacites_travail") or [])
                logger.info(
                    f"[{job_id[:8]}] Synthèse OK en {timings['medical_synthesis']:.1f}s "
                    f"— {nb_dx} diagnostics, {nb_it} périodes d'incapacité"
                )
                # Debug : sauvegarder la synthèse
                (debug_dir / "medical_synthesis.json").write_text(
                    json.dumps(synthesis, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                logger.warning(f"[{job_id[:8]}] Synthèse échouée — extraction sur les seuls documents")
                warnings.append("Synthèse médicale indisponible : extraction faite sur les seuls documents.")

            # ============================================================
            # STEP 3 : Extraction des champs
            # ============================================================
            t_rag_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing",
                                 "message": "🤖 Analyse LLM et extraction des entités...", "progress": 50})
            template = _load_template(form_id)

            def _progress(done: int, total: int) -> None:
                JOBS[job_id].update({
                    "message": f"🤖 Extraction {done}/{total} sections...",
                    "progress": 50 + int(40 * done / total),
                })

            results = await _extract_fields(client, job_id, form_id, template, col, chunk_index,
                                            synthesis, ocr_raw_results, _progress)
            timings["rag_extraction"] = time.perf_counter() - t_rag_start

            # Stocker les résultats bruts pour le debug/eval + chat
            JOBS[job_id]["_debug_results"] = results
            JOBS[job_id]["_debug_chunks_count"] = chunk_index
            JOBS[job_id]["_debug_synthesis"] = synthesis
            # Stocker les définitions de champs pour l'endpoint /fields
            JOBS[job_id]["_template_fields"] = _template_fields_view(template)

            # Debug : sauvegarder les résultats LLM
            results_debug = []
            for r in results:
                entry = {"field_id": r.get("id")}
                if "result" in r:
                    entry["value"] = r["result"].get("value")
                    entry["raw_value"] = r["result"].get("raw_value")
                    entry["source_quote"] = r["result"].get("source_quote")
                    entry["grounding"] = r["result"].get("grounding")
                if "error" in r:
                    entry["error"] = r["error"]
                results_debug.append(entry)
            (debug_dir / "llm_results.json").write_text(
                json.dumps(results_debug, ensure_ascii=False, indent=2), encoding="utf-8")

            # ============================================================
            # STEP 4 : Injection des valeurs dans le formulaire PDF
            # ============================================================
            t_xfa_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing", "message": "✍️ Injection des données dans le formulaire PDF...",
                            "progress": 90})
            output_pdf, form_type = _fill_pdf(job_id, form_id, template, results, tmp_dir)

            t_xfa_end = time.perf_counter()
            timings["xfa_injection"] = t_xfa_end - t_xfa_start
            timings["total"] = time.perf_counter() - t_pipeline_start

            # Debug : résumé
            ok_count = sum(1 for r in results if "result" in r and r["result"].get("value"))
            err_count = sum(1 for r in results if "error" in r)
            empty_count = sum(1 for r in results if "result" in r and not r["result"].get("value"))
            _record_field_errors(JOBS[job_id], results)
            synthesis_info = "Non disponible (extraction sur les seuls documents)"
            if synthesis:
                nb_dx = len(synthesis.get("diagnostics") or [])
                nb_it = len(synthesis.get("incapacites_travail") or [])
                synthesis_info = f"{nb_dx} diagnostics, {nb_it} périodes d'incapacité"
            summary = (
                f"Job: {job_id}\nForm: {form_id}\nDate: {datetime.now().isoformat()}\n"
                f"Fichiers: {total_files} (lus: {len(ocr_raw_results)})\nChunks: {chunk_index}\n"
                f"Type formulaire: {form_type}\n"
                f"Synthèse médicale: {synthesis_info}\n"
                f"Champs: {len(results)} (OK: {ok_count}, Erreurs: {err_count}, Vides: {empty_count})\n"
                f"Timings: OCR+embed={timings['ocr_embed_pipeline']:.1f}s, "
                f"Synthèse={timings.get('medical_synthesis', 0):.1f}s, "
                f"Extraction={timings['rag_extraction']:.1f}s, Injection={timings['xfa_injection']:.1f}s, "
                f"Total={timings['total']:.1f}s\n"
            )
            (debug_dir / "summary.txt").write_text(summary, encoding="utf-8")
            logger.info(f"[{job_id[:8]}] Pipeline terminé en {timings['total']:.1f}s — "
                        f"{ok_count}/{len(results)} champs remplis — Debug: {debug_dir}")

            # Durée vécue par l'utilisateur : de la soumission au formulaire prêt,
            # transfert et attente comprises. `timings["total"]` ne couvre que le
            # pipeline lui-même et reste au journal de debug.
            elapsed = time.time() - JOBS[job_id].get("started_at", time.time())
            # Seules les exécutions abouties sont comptées : la durée d'un job en
            # échec ne dit rien du coût d'un dossier traité.
            stats.record_run(form_id, total_files, elapsed)

            JOBS[job_id].update({
                "status": "completed",
                "message": f"✅ Formulaire généré en {timings['total']:.0f}s !",
                "progress": 100,
                "file_path": str(output_pdf),
                "completed_at": time.time(),
                "duration_s": round(elapsed, 1),
                "_form_id": form_id,
                "_tmp_dir": str(tmp_dir),
            })

    except UserFacingError as e:
        logger.warning(f"Job {job_id} refusé : {e}")
        JOBS[job_id].update({
            "status": "failed",
            "message": str(e),
            "progress": 0,
            "completed_at": time.time()
        })
    except Exception as e:
        # [SEC-10] Log complet côté serveur, message générique côté client
        logger.error(f"Erreur Job {job_id}: {e}", exc_info=True)
        JOBS[job_id].update({
            "status": "failed",
            "message": "Une erreur est survenue lors du traitement. Veuillez réessayer.",
            "progress": 0,
            "completed_at": time.time()
        })
    finally:
        # Collection kept alive for chat sessions — cleaned up by _cleanup_expired_jobs
        pass


# ---------------------------------------------------------------
# --- ROUTES ---

@app.get("/health")
async def health_check():
    # /health est le seul endpoint hors authentification : c'est donc lui que le
    # frontend interroge pour afficher la version du backend qu'il pilote.
    return {
        "status": "ok",
        "service": "orchestrator",
        "version": APP_VERSION,
        "build": APP_BUILD_ID,
        "commit": APP_COMMIT,
        "built_at": APP_BUILT_AT,
        "model": VLLM_MODEL,
        "forms": len(VALID_FORM_IDS),
    }


@app.get("/stats")
async def pipeline_stats(form_id: str = ""):
    """
    Repères de durée, calculés sur les exécutions abouties.

    `form_id` restreint au formulaire demandé : un rapport de 112 champs et une
    annonce de maternité de 23 champs n'ont pas le même coût, et une moyenne qui
    les mélange n'aide personne.
    """
    return {
        "global": stats.summary(),
        "form": stats.summary(form_id) if form_id else None,
    }


@app.get("/forms")
async def list_forms():
    # Même filtre que la whitelist de démarrage : un formulaire non relu ne doit
    # pas être proposé, sinon /process-form le refuserait ensuite avec un 400.
    return {"forms": sorted(_scan_templates())}


@app.post("/process-form")
async def process_form(
        background_tasks: BackgroundTasks,
        report_files: List[UploadFile] = File(...),
        form_id: str = Form(...)
):
    """Initie le traitement. Retourne immédiatement un job_id + token."""

    # --- [SEC-03] Validation du form_id (whitelist)
    if form_id not in VALID_FORM_IDS:
        raise HTTPException(status_code=400, detail="Formulaire inconnu.")

    # --- [SEC-06] Limite de jobs concurrents
    active_jobs = sum(1 for j in JOBS.values() if j.get("status") in ("pending", "processing"))
    if active_jobs >= MAX_CONCURRENT_JOBS:
        raise HTTPException(status_code=429, detail="Serveur saturé, réessayez dans quelques minutes.")

    # --- [SEC-05] Validation du nombre de fichiers
    if len(report_files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES} fichiers autorisés.")

    # --- [SEC-07] Job ID complet (128 bits) + token secret
    job_id = uuid.uuid4().hex
    download_token = secrets.token_urlsafe(32)
    tmp_dir = Path(f"/tmp/{job_id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    saved_report_paths = []
    for i, report in enumerate(report_files):
        # --- [SEC-05] Validation taille + magic bytes PDF
        content = await report.read()
        if len(content) > MAX_FILE_SIZE:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_FILE_SIZE // (1024*1024)} MB).")
        if not content.startswith(b"%PDF"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

        # --- [SEC-01] Assainissement du nom de fichier
        safe_name = _sanitize_filename(report.filename, i)
        file_path = tmp_dir / safe_name

        # Vérification supplémentaire : le path résolu reste dans tmp_dir
        if not file_path.resolve().is_relative_to(tmp_dir.resolve()):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

        with open(file_path, "wb") as f:
            f.write(content)
        saved_report_paths.append(file_path)

    JOBS[job_id] = {
        "status": "pending",
        "message": "Initialisation du pipeline...",
        "progress": 0,
        "token": download_token,
        # Origine du chronomètre affiché pendant le traitement.
        "started_at": time.time(),
    }

    background_tasks.add_task(run_pipeline_task, job_id, form_id, tmp_dir, saved_report_paths)

    return {"job_id": job_id, "token": download_token}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Retourne la progression du job (sans le token ni le file_path)."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job introuvable ou expiré.")
    job = JOBS[job_id]
    # Ne pas exposer le token ni le file_path dans le status
    # elapsed_s alimente le chronomètre pendant le traitement ; duration_s est la
    # durée définitive, celle qui entre dans la moyenne.
    started = job.get("started_at")
    return {
        "status": job.get("status"),
        "message": job.get("message"),
        "progress": job.get("progress"),
        "elapsed_s": round(time.time() - started, 1) if started else None,
        "duration_s": job.get("duration_s"),
        # Ce que l'utilisateur doit savoir sans que le job échoue : document
        # illisible écarté, champs à compléter à la main.
        "warnings": job.get("warnings", []),
    }


# ---------------------------------------------------------------
# --- RÉSULTATS DU FORMULAIRE ---

@app.get("/fields/{job_id}")
async def get_fields(job_id: str, token: str = ""):
    """Retourne les champs du formulaire rempli avec leurs valeurs (pour affichage chat)."""
    if job_id not in JOBS or JOBS[job_id].get("status") != "completed":
        raise HTTPException(status_code=404, detail="Session introuvable ou traitement non terminé.")
    expected_token = JOBS[job_id].get("token", "")
    if expected_token and not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Token invalide.")

    template_fields = JOBS[job_id].get("_template_fields", [])
    raw_results = {r["id"]: r for r in JOBS[job_id].get("_debug_results", [])}

    fields_out = []
    for f in template_fields:
        fid = f["id"]
        r = raw_results.get(fid, {})
        payload = r.get("result", {}) if "result" in r else {}
        fields_out.append({
            "id": fid,
            "label": f.get("label", str(fid)),
            "question": f.get("question", ""),
            "section": f.get("section", ""),
            "value": payload.get("value"),
            "source_quote": payload.get("source_quote"),
            # Rattachement au texte source : verdict + où le vérifier.
            "grounding": payload.get("grounding"),
            "source_document": payload.get("source_document"),
            "source_page": payload.get("source_page"),
            "source_excerpt": payload.get("source_excerpt"),
            "source_match": payload.get("source_match"),
            # Réponse du modèle avant normalisation, quand elle diffère.
            "raw_value": payload.get("raw_value"),
            "error": r.get("error"),
        })
    return {"fields": fields_out}


# ---------------------------------------------------------------
# --- CHAT INTERACTIF ---

class ChatRequest(BaseModel):
    job_id: str
    message: str
    token: str = ""
    history: List[Dict[str, Any]] = []


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """Chat interactif sur les documents d'un job déjà traité. Streame la réponse."""
    # Validation
    if len(request.message) > 2000:
        raise HTTPException(status_code=400, detail="Message trop long (max 2000 caractères).")
    if len(request.history) > 40:
        raise HTTPException(status_code=400, detail="Historique trop long (max 20 échanges).")

    job = JOBS.get(request.job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Session introuvable ou traitement non terminé.")
    # Le chat lit le dossier patient : même contrôle que /fields et /download,
    # qui l'exigeaient déjà alors que celui-ci s'en passait.
    expected_token = job.get("token", "")
    if expected_token and not secrets.compare_digest(request.token, expected_token):
        raise HTTPException(status_code=403, detail="Token invalide.")

    synthesis = job.get("_debug_synthesis")
    synthesis_json = json.dumps(synthesis, ensure_ascii=False) if synthesis else None
    collection_name = f"col_{request.job_id}"

    # Construire le contexte des champs remplis (label → valeur)
    fields_context: str | None = None
    template_fields = job.get("_template_fields", [])
    raw_results = {r["id"]: r for r in job.get("_debug_results", [])}
    if template_fields:
        lines = []
        for f in template_fields:
            fid = f["id"]
            r = raw_results.get(fid, {})
            value = r.get("result", {}).get("value") if "result" in r else None
            if value:
                lines.append(f"[{fid}] {f.get('label', fid)} : {value}")
        if lines:
            fields_context = "\n".join(lines)

    # Récupérer les chunks pertinents depuis ChromaDB
    chunks_context: str | None = None
    try:
        col = chroma_client.get_collection(name=collection_name)
        col_count = col.count()
        if col_count > 0:
            async with httpx.AsyncClient(limits=httpx.Limits(max_connections=10)) as client:
                q_emb = (await fetch_embeddings(client, [request.message]))[0]
                hits = col.query(
                    query_embeddings=[q_emb],
                    n_results=min(15, col_count)
                )["documents"][0]
                reranked = await fetch_rerank(client, request.message, hits)
                top_chunks = [r["document"] for r in reranked[:6]]
                chunks_context = "\n---\n".join(top_chunks)
    except Exception as e:
        logger.warning(f"[chat/{request.job_id[:8]}] ChromaDB inaccessible: {e}")

    messages = build_chat_messages(
        synthesis_json=synthesis_json,
        chunks_context=chunks_context,
        fields_context=fields_context,
        history=request.history,
        question=request.message,
    )

    async def _stream():
        payload = {
            "model": VLLM_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                async with client.stream(
                    "POST", f"{VLLM_URL}/chat/completions", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line == "data: [DONE]":
                            yield "data: [DONE]\n\n"
                            return
                        if line.startswith("data: "):
                            yield line + "\n\n"
        except Exception as e:
            logger.error(f"[chat/{request.job_id[:8]}] Erreur streaming vLLM: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------
# --- CONTEXTE GLOBAL (SYNTHÈSE MÉDICALE) ---

class SynthesisUpdateRequest(BaseModel):
    token: str
    synthesis: Dict[str, Any]

class SynthesisRefineRequest(BaseModel):
    token: str
    instruction: str


def _validate_job_token(job_id: str, token: str) -> Dict:
    """Valide job_id + token et retourne le job ou lève HTTPException."""
    job = JOBS.get(job_id)
    if not job or job.get("status") not in ("completed", "processing"):
        raise HTTPException(status_code=404, detail="Session introuvable ou traitement non terminé.")
    expected = job.get("token", "")
    if expected and not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Token invalide.")
    return job


@app.get("/synthesis/{job_id}")
async def get_synthesis(job_id: str, token: str = ""):
    """Retourne la synthèse médicale générée pour ce job (null si non disponible)."""
    job = _validate_job_token(job_id, token)
    synthesis = job.get("_debug_synthesis")
    return {"synthesis": synthesis, "available": synthesis is not None}


@app.post("/synthesis/{job_id}/generate")
async def generate_synthesis(job_id: str, token: str = ""):
    """(Re)génère la synthèse médicale depuis le texte OCR conservé avec le job."""
    job = _validate_job_token(job_id, token)
    # Le texte OCR vit avec le job ; les journaux de debug, purgés avec lui, ne
    # servent plus que de secours pour un job antérieur à ce changement.
    ocr_results = list(job.get("_source_documents") or [])
    if not ocr_results:
        markdown_dir = Path(job.get("_debug_dir", "")) / "markdown"
        for md_file in sorted(markdown_dir.glob("*.md")) if markdown_dir.exists() else []:
            try:
                ocr_results.append({"filename": md_file.name, "markdown": md_file.read_text(encoding="utf-8")})
            except OSError:
                pass

    if not ocr_results:
        raise HTTPException(status_code=404, detail="Texte OCR introuvable (session expirée ou trop ancienne).")

    logger.info(f"[{job_id[:8]}] Régénération synthèse depuis {len(ocr_results)} documents...")
    synthesis = await run_medical_synthesis(ocr_results, VLLM_URL, VLLM_MODEL)
    if synthesis is None:
        raise HTTPException(status_code=502, detail="Le LLM n'a pas pu générer la synthèse. Vérifiez les logs.")

    JOBS[job_id]["_debug_synthesis"] = synthesis
    logger.info(f"[{job_id[:8]}] Synthèse régénérée avec succès.")
    return {"synthesis": synthesis, "available": True}


@app.post("/synthesis/{job_id}/update")
async def update_synthesis(job_id: str, request: SynthesisUpdateRequest):
    """Met à jour la synthèse médicale en mémoire (pour affiner avant re-run)."""
    _validate_job_token(job_id, request.token)
    JOBS[job_id]["_debug_synthesis"] = request.synthesis
    logger.info(f"[{job_id[:8]}] Synthèse mise à jour manuellement.")
    return {"ok": True}


@app.post("/synthesis/{job_id}/refine")
async def refine_synthesis(job_id: str, request: SynthesisRefineRequest):
    """LLM-assisted: propose une synthèse améliorée selon l'instruction. Retourne la suggestion JSON."""
    job = _validate_job_token(job_id, request.token)
    if len(request.instruction) > 1000:
        raise HTTPException(status_code=400, detail="Instruction trop longue (max 1000 caractères).")
    synthesis = job.get("_debug_synthesis")
    if not synthesis:
        raise HTTPException(status_code=404, detail="Synthèse non disponible.")

    synthesis_json = json.dumps(synthesis, ensure_ascii=False, indent=2)
    messages = build_synthesis_refine_messages(synthesis_json, request.instruction)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(f"{VLLM_URL}/chat/completions", json={
            "model": VLLM_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
            "stream": False,
        })
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Extraire le JSON (peut être entouré de ```json ... ```)
    json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    json_str = json_match.group(1) if json_match else raw
    try:
        suggested = json.loads(json_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Le LLM n'a pas retourné un JSON valide.")

    return {"suggestion": suggested, "raw": raw}


async def rerun_pipeline_task(job_id: str):
    """Re-run sous le même portier que le pipeline : il sollicite autant le GPU."""
    _announce_queue(job_id)
    async with _PIPELINE_SEM:
        await _rerun_pipeline(job_id)


async def _rerun_pipeline(job_id: str):
    """Re-run rapide : saute l'OCR/embedding, réutilise le ChromaDB existant avec la synthèse mise à jour."""
    form_id = JOBS[job_id].get("_form_id")
    synthesis = JOBS[job_id].get("_debug_synthesis")
    collection_name = f"col_{job_id}"
    tmp_dir = Path(JOBS[job_id].get("_tmp_dir", f"/tmp/{job_id}"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        JOBS[job_id].update({"status": "processing", "message": "🔄 Re-run : chargement du contexte...", "progress": 5})

        col = chroma_client.get_collection(name=collection_name)
        col_count = col.count()
        documents = JOBS[job_id].get("_source_documents") or []
        if not documents:
            raise ValueError("Contexte du job vide — session expirée, impossible de relancer sans re-OCR.")

        template = _load_template(form_id)
        logger.info(f"[{job_id[:8]}] Re-run: {col_count} chunks en ChromaDB.")

        limits = httpx.Limits(max_connections=50, max_keepalive_connections=10, keepalive_expiry=30)
        async with httpx.AsyncClient(limits=limits) as client:
            JOBS[job_id].update({"message": "🔄 Re-run : extraction...", "progress": 30})

            def _progress(done: int, total: int) -> None:
                JOBS[job_id].update({
                    "message": f"🔄 Re-run : extraction {done}/{total}...",
                    "progress": 30 + int(55 * done / total),
                })

            results = await _extract_fields(client, job_id, form_id, template, col, col_count,
                                            synthesis, documents, _progress)
            JOBS[job_id]["_debug_results"] = results
            JOBS[job_id]["_template_fields"] = _template_fields_view(template)
            _record_field_errors(JOBS[job_id], results)

            JOBS[job_id].update({"message": "✍️ Re-run : injection dans le formulaire...", "progress": 88})
            output_pdf, _ = _fill_pdf(job_id, form_id, template, results, tmp_dir, suffix="_rerun")

        JOBS[job_id].update({
            "status": "completed",
            "message": "✅ Re-run terminé — formulaire mis à jour !",
            "progress": 100,
            "file_path": str(output_pdf),
            "completed_at": time.time(),
        })
        logger.info(f"[{job_id[:8]}] Re-run terminé avec succès.")

    except Exception as e:
        logger.error(f"[{job_id[:8]}] Erreur re-run: {e}", exc_info=True)
        JOBS[job_id].update({
            "status": "failed",
            "message": "Erreur lors du re-run. La session a peut-être expiré.",
            "progress": 0,
            "completed_at": time.time(),
        })


@app.post("/rerun/{job_id}")
async def trigger_rerun(job_id: str, background_tasks: BackgroundTasks, token: str = ""):
    """Relance l'extraction + remplissage avec la synthèse mise à jour. Saute l'OCR."""
    job = _validate_job_token(job_id, token)
    if job.get("status") == "processing":
        raise HTTPException(status_code=409, detail="Un traitement est déjà en cours.")
    if not job.get("_form_id"):
        raise HTTPException(status_code=400, detail="Métadonnées de re-run manquantes (job trop ancien ?).")
    # Marqué tout de suite : sinon un second clic, avant le démarrage de la tâche
    # de fond, lançait un second re-run concurrent sur le même job.
    job.update({"status": "processing", "message": "🔄 Re-run en préparation...", "progress": 2})
    background_tasks.add_task(rerun_pipeline_task, job_id)
    return {"ok": True, "job_id": job_id}


@app.get("/download/{job_id}")
async def download_result(job_id: str, token: str = ""):
    """Télécharge le PDF final. Requiert le token retourné à la création."""
    if job_id not in JOBS or JOBS[job_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Fichier non disponible ou traitement en cours.")

    # --- [SEC-07] Vérification du token de téléchargement
    expected_token = JOBS[job_id].get("token", "")
    if not token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Token invalide.")

    file_path = JOBS[job_id].get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    return FileResponse(file_path, media_type="application/pdf", filename=f"DoctorFill_{job_id[:8]}.pdf")


@app.get("/debug/{job_id}")
async def debug_results(job_id: str, token: str = ""):
    """Retourne les résultats bruts d'extraction LLM pour évaluation/debug."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job introuvable.")

    expected_token = JOBS[job_id].get("token", "")
    if not token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Token invalide.")

    debug_results = JOBS[job_id].get("_debug_results", [])
    debug_synthesis = JOBS[job_id].get("_debug_synthesis")
    return {
        "job_id": job_id,
        "status": JOBS[job_id].get("status"),
        "chunks_count": JOBS[job_id].get("_debug_chunks_count", 0),
        "medical_synthesis": debug_synthesis,
        "extractions": [
            {
                "field_id": r.get("id"),
                "value": r.get("result", {}).get("value") if "result" in r else None,
                "source_quote": r.get("result", {}).get("source_quote") if "result" in r else None,
                "quote_verified": r.get("result", {}).get("quote_verified") if "result" in r else None,
                "raw_value": r.get("result", {}).get("raw_value") if "result" in r else None,
                "rerank_score": r.get("result", {}).get("rerank_score") if "result" in r else None,
                "grounding": r.get("result", {}).get("grounding") if "result" in r else None,
                "source_document": r.get("result", {}).get("source_document") if "result" in r else None,
                "source_page": r.get("result", {}).get("source_page") if "result" in r else None,
                "error": r.get("error"),
            }
            for r in debug_results
        ],
    }
