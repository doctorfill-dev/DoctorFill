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
from fastapi.responses import FileResponse
import chromadb
import shutil

from core.extract import extract_xfa_datasets
from core.fill import update_datasets
from core.inject import inject_datasets
from core.checkbox import discover_checkbox_paths, normalize_checkboxes

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

JOBS: Dict[str, Dict[str, Any]] = {}
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "3600"))

# --- [SEC-06] Limite de jobs concurrents
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "20"))

# --- [SEC-05] Limites d'upload
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50 MB
MAX_FILES = int(os.getenv("MAX_FILES", "200"))

# --- [SEC-03] Whitelist des form_id valides (construite au démarrage)
VALID_FORM_IDS: Set[str] = set()


@app.on_event("startup")
async def startup_tasks():
    """Initialisation au démarrage : whitelist form_id + cleanup périodique."""
    # [SEC-03] Scanner les templates disponibles
    template_dir = Path("template")
    if template_dir.exists():
        for f in template_dir.glob("Form_*.json"):
            VALID_FORM_IDS.add(f.stem.replace("Form_", ""))
        logger.info(f"Form IDs valides: {VALID_FORM_IDS}")

    asyncio.create_task(_cleanup_expired_jobs())


async def _cleanup_expired_jobs():
    """Tâche de fond qui purge les jobs terminés et leurs fichiers temporaires."""
    while True:
        await asyncio.sleep(300)
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
            JOBS.pop(jid, None)
        if expired:
            logger.info(f"Cleanup: {len(expired)} job(s) expiré(s) purgé(s)")


# ---------------------------------------------------
# --- UTILS ---

def markdown_semantic_chunking(md_text: str, max_words: int = 400) -> List[str]:
    raw_chunks = re.split(r'(?=\n#{1,3} )', md_text)
    final_chunks = []
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        words = chunk.split()
        if len(words) > max_words:
            for i in range(0, len(words), max_words - 50):
                final_chunks.append(" ".join(words[i:i + max_words]))
        else:
            final_chunks.append(chunk)
    return final_chunks


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


async def fetch_embeddings(client: httpx.AsyncClient, texts: List[str]):
    resp = await client.post(f"{TEI_URL}/embed", json={"texts": texts}, timeout=120.0)
    resp.raise_for_status()
    return resp.json()["embeddings"]


async def fetch_embeddings_batched(client: httpx.AsyncClient, texts: List[str], batch_size: int = 64) -> List:
    """Embed par batches pour éviter les timeouts sur de gros volumes."""
    all_embeddings: List = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embs = await fetch_embeddings(client, batch)
        all_embeddings.extend(embs)
    return all_embeddings


async def fetch_rerank(client: httpx.AsyncClient, query: str, docs: List[str],
                       rerank_sem: asyncio.Semaphore = None):
    """Rerank avec semaphore + retry sur PoolTimeout/ReadError/ConnectError."""
    MAX_RETRIES = 3

    async def _call():
        resp = await client.post(f"{TEI_URL}/rerank", json={"query": query, "documents": docs}, timeout=300.0)
        resp.raise_for_status()
        return resp.json()["results"]

    async def _call_with_retry():
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await _call()
            except (httpx.PoolTimeout, httpx.ReadError, httpx.ConnectError) as e:
                if attempt == MAX_RETRIES:
                    raise
                logger.warning(f"Rerank retry {attempt}/{MAX_RETRIES}: {type(e).__name__}: {e}")
                await asyncio.sleep(2 * attempt)

    if rerank_sem:
        async with rerank_sem:
            return await _call_with_retry()
    else:
        return await _call_with_retry()


SYSTEM_PROMPT_EXTRACT = (
    "Tu es un assistant spécialisé dans l'extraction de données depuis des documents médicaux. "
    "On te fournit des EXTRAITS de rapports et une QUESTION.\n\n"
    "RÈGLES STRICTES :\n"
    "1. Cherche la réponse dans les extraits fournis. L'information peut apparaître sous différentes formes "
    "(en-tête, tableau, texte narratif, champ de formulaire, etc.).\n"
    "2. Extrais la valeur EXACTE telle qu'elle apparaît dans le texte.\n"
    "3. Ne réponds \"Inconnu\" que si l'information est RÉELLEMENT ABSENTE de tous les extraits.\n"
    "4. Réponds UNIQUEMENT en JSON valide avec ce format :\n"
    '   {"value": "<réponse extraite>", "source_quote": "<phrase exacte du contexte contenant la réponse>"}\n'
    "5. Pour les dates, conserve le format original du document.\n"
    "6. Pour les noms/prénoms, conserve la casse originale."
)


async def extract_field_vllm(client: httpx.AsyncClient, context: str, field: Dict):
    prompt = f"EXTRAITS DE DOCUMENTS :\n{context}\n\nQUESTION : {field['question']}"
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_EXTRACT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.05,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = await client.post(f"{VLLM_URL}/chat/completions", json=payload, timeout=120.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return {"id": field["id"], "result": json.loads(content)}
    except Exception as e:
        logger.error(f"Erreur vLLM sur {field['id']}: {e}")
        # [SEC-10] Ne pas exposer les détails de l'erreur au client
        return {"id": field["id"], "error": "extraction_failed"}


async def run_pipeline_task(job_id: str, form_id: str, tmp_dir: Path, report_paths: List[Path]):
    """
    Pipeline avec streaming OCR→embed et semaphores rerank/LLM.
    - OCR et embedding se font en parallèle via asyncio.Queue
    - Rerank limité à 5 concurrents (évite PoolTimeout)
    - LLM limité à 10 concurrents (évite saturation KV cache vLLM)
    """
    collection_name = f"col_{job_id}"
    debug_dir = DEBUG_LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:8]}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "markdown").mkdir(exist_ok=True)

    timings: Dict[str, float] = {}

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
            ocr_sem = asyncio.Semaphore(3)
            MAX_OCR_RETRIES = 5
            col = chroma_client.get_or_create_collection(name=collection_name)
            chunk_index = 0
            all_chunks: List[str] = []

            # Queue pour le pipeline OCR → embed
            ocr_queue: asyncio.Queue = asyncio.Queue()
            embed_done = asyncio.Event()

            async def _ocr_one(path: Path) -> tuple:
                """OCR un PDF et envoie le résultat dans la queue pour embedding."""
                nonlocal ocr_done
                async with ocr_sem:
                    with open(path, "rb") as f:
                        content = f.read()
                    last_err = None
                    for attempt in range(1, MAX_OCR_RETRIES + 1):
                        try:
                            resp = await client.post(
                                f"{MARKER_URL}/extract",
                                files={'file': (path.name, content, 'application/pdf')},
                                timeout=600.0)
                            resp.raise_for_status()
                            md_text = resp.json().get("markdown", "")
                            ocr_done += 1
                            JOBS[job_id].update({
                                "message": f"📄 OCR {ocr_done}/{total_files} documents...",
                                "progress": 5 + int(35 * ocr_done / total_files)
                            })
                            # Debug : sauvegarder le markdown OCR
                            md_filename = path.stem + ".md"
                            (debug_dir / "markdown" / md_filename).write_text(md_text, encoding="utf-8")
                            # Envoyer dans la queue pour embedding immédiat
                            await ocr_queue.put((path.name, md_text))
                            return path.name, md_text
                        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                            last_err = e
                            delay = 10 * attempt if isinstance(e, httpx.ConnectError) else 2 * attempt
                            logger.warning(f"[{job_id[:8]}] OCR retry {attempt}/{MAX_OCR_RETRIES} pour {path.name}: {type(e).__name__} (retry in {delay}s)")
                            if attempt < MAX_OCR_RETRIES:
                                await asyncio.sleep(delay)
                    raise last_err

            async def _embed_consumer():
                """Consomme la queue OCR, chunk et embed au fil de l'eau."""
                nonlocal chunk_index
                pending_chunks: List[str] = []

                while True:
                    try:
                        name, md_text = await asyncio.wait_for(ocr_queue.get(), timeout=2.0)
                    except asyncio.TimeoutError:
                        if ocr_queue.empty() and embed_done.is_set():
                            break
                        continue

                    doc_md = f"\n\n--- SOURCE: {name} ---\n\n" + md_text
                    doc_chunks = markdown_semantic_chunking(doc_md)
                    pending_chunks.extend(doc_chunks)
                    all_chunks.extend(doc_chunks)

                    # Embed quand on a accumulé assez de chunks
                    if len(pending_chunks) >= 64 or (embed_done.is_set() and ocr_queue.empty()):
                        if pending_chunks:
                            embeds = await fetch_embeddings_batched(client, pending_chunks)
                            ids = [f"{job_id}_{chunk_index + i}" for i in range(len(pending_chunks))]
                            col.add(documents=pending_chunks, embeddings=embeds, ids=ids)
                            chunk_index += len(pending_chunks)
                            logger.info(f"[{job_id[:8]}] Embedded {chunk_index} chunks so far...")
                            pending_chunks = []

                # Flush les chunks restants
                if pending_chunks:
                    embeds = await fetch_embeddings_batched(client, pending_chunks)
                    ids = [f"{job_id}_{chunk_index + i}" for i in range(len(pending_chunks))]
                    col.add(documents=pending_chunks, embeddings=embeds, ids=ids)
                    chunk_index += len(pending_chunks)

            # Lancer OCR et embedding en parallèle (pipeline)
            embed_task = asyncio.create_task(_embed_consumer())
            await asyncio.gather(*[_ocr_one(p) for p in report_paths])
            embed_done.set()
            await embed_task

            t_ocr_end = time.perf_counter()
            timings["ocr_embed_pipeline"] = t_ocr_end - t_ocr_start
            chunks = all_chunks
            logger.info(f"[{job_id[:8]}] Pipeline OCR+embed terminé: {len(chunks)} chunks en {timings['ocr_embed_pipeline']:.1f}s")

            # ============================================================
            # STEP 2 : RAG — rerank + LLM avec semaphores
            # ============================================================
            t_rag_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing",
                                 "message": "🤖 Analyse LLM et extraction des entités...", "progress": 45})
            with open(f"template/Form_{form_id}.json", "r") as f:
                template = json.load(f)

            fields_with_q = [f for f in template["fields"] if "question" in f]
            logger.info(f"[{job_id[:8]}] Step 2: {len(fields_with_q)} champs à extraire (rerank_sem=5, llm_sem=10)...")

            all_q_embs = await fetch_embeddings_batched(client, [f["question"] for f in fields_with_q])

            rerank_sem = asyncio.Semaphore(5)
            llm_sem = asyncio.Semaphore(10)
            llm_done = 0

            async def _retrieve_and_extract(field: Dict, q_emb) -> Dict:
                """ChromaDB query (instant) → rerank (sem=5) → LLM (sem=10)."""
                nonlocal llm_done
                hits = col.query(query_embeddings=[q_emb], n_results=min(20, len(chunks)))["documents"][0]
                reranked = await fetch_rerank(client, field["question"], hits, rerank_sem=rerank_sem)
                context = "\n---\n".join([r["document"] for r in reranked[:7]])
                async with llm_sem:
                    result = await extract_field_vllm(client, context, field)
                llm_done += 1
                JOBS[job_id].update({
                    "message": f"🤖 Extraction {llm_done}/{len(fields_with_q)} champs...",
                    "progress": 50 + int(40 * llm_done / len(fields_with_q))
                })
                return result

            results = await asyncio.gather(*[
                _retrieve_and_extract(f, emb) for f, emb in zip(fields_with_q, all_q_embs)
            ])
            t_rag_end = time.perf_counter()
            timings["rag_extraction"] = t_rag_end - t_rag_start

            # Stocker les résultats bruts pour le debug/eval
            JOBS[job_id]["_debug_results"] = results
            JOBS[job_id]["_debug_chunks_count"] = len(chunks)

            # Debug : sauvegarder les résultats LLM
            results_debug = []
            for r in results:
                entry = {"field_id": r.get("id")}
                if "result" in r:
                    entry["value"] = r["result"].get("value")
                    entry["source_quote"] = r["result"].get("source_quote")
                if "error" in r:
                    entry["error"] = r["error"]
                results_debug.append(entry)
            (debug_dir / "llm_results.json").write_text(
                json.dumps(results_debug, ensure_ascii=False, indent=2), encoding="utf-8")

            # ============================================================
            # STEP 3 : Mapping & Injection XFA
            # ============================================================
            t_xfa_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing", "message": "✍️ Injection des données dans le PDF XFA...",
                            "progress": 90})
            empty_form_path = tmp_dir / "empty.pdf"

            source_template_path = Path(f"forms/Form_{form_id}.pdf")
            if not source_template_path.exists():
                raise FileNotFoundError(f"Template introuvable pour form_id={form_id}")
            shutil.copy(source_template_path, empty_form_path)

            base_xml = tmp_dir / "base.xml"
            extract_xfa_datasets(empty_form_path, base_xml)

            filled_values = {}
            for res in results:
                if "result" in res and res["result"].get("value"):
                    f_def = next(f for f in template["fields"] if f.get("id") == res["id"])
                    filled_values[f_def["xml_path"]] = res["result"]["value"]

            checkbox_paths = discover_checkbox_paths(base_xml)
            normalize_checkboxes(filled_values, checkbox_paths)

            filled_xml = tmp_dir / "filled.xml"
            update_datasets(base_xml, filled_values, filled_xml, template["fields"])

            output_pdf = tmp_dir / "output.pdf"
            inject_datasets(empty_form_path, filled_xml, output_pdf)

            t_xfa_end = time.perf_counter()
            timings["xfa_injection"] = t_xfa_end - t_xfa_start
            timings["total"] = time.perf_counter() - t_pipeline_start

            # Debug : résumé
            ok_count = sum(1 for r in results if "result" in r and r["result"].get("value") and r["result"]["value"] != "Inconnu")
            err_count = sum(1 for r in results if "error" in r)
            inconnu_count = sum(1 for r in results if "result" in r and r["result"].get("value") == "Inconnu")
            summary = (
                f"Job: {job_id}\nForm: {form_id}\nDate: {datetime.now().isoformat()}\n"
                f"Fichiers: {total_files}\nChunks: {len(chunks)}\n"
                f"Champs: {len(fields_with_q)} (OK: {ok_count}, Erreurs: {err_count}, Inconnu: {inconnu_count})\n"
                f"Timings: OCR+embed={timings['ocr_embed_pipeline']:.1f}s, RAG={timings['rag_extraction']:.1f}s, XFA={timings['xfa_injection']:.1f}s, Total={timings['total']:.1f}s\n"
            )
            (debug_dir / "summary.txt").write_text(summary, encoding="utf-8")
            logger.info(f"[{job_id[:8]}] Pipeline terminé en {timings['total']:.1f}s — Debug: {debug_dir}")

            JOBS[job_id].update({
                "status": "completed",
                "message": f"✅ Formulaire généré en {timings['total']:.0f}s !",
                "progress": 100,
                "file_path": str(output_pdf),
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
        try:
            chroma_client.delete_collection(name=collection_name)
        except Exception:
            pass


# ---------------------------------------------------------------
# --- ROUTES ---

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "orchestrator"}


@app.get("/forms")
async def list_forms():
    template_path = Path("template")
    return {"forms": [f.stem.replace("Form_", "") for f in template_path.glob("Form_*.json")]}


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
    return {
        "status": job.get("status"),
        "message": job.get("message"),
        "progress": job.get("progress"),
    }


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
    return {
        "job_id": job_id,
        "status": JOBS[job_id].get("status"),
        "chunks_count": JOBS[job_id].get("_debug_chunks_count", 0),
        "extractions": [
            {
                "field_id": r.get("id"),
                "value": r.get("result", {}).get("value") if "result" in r else None,
                "source_quote": r.get("result", {}).get("source_quote") if "result" in r else None,
                "error": r.get("error"),
            }
            for r in debug_results
        ],
    }
