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

JOBS: Dict[str, Dict[str, Any]] = {}
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "3600"))

# --- [SEC-06] Limite de jobs concurrents
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "20"))

# --- [SEC-05] Limites d'upload
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50 MB
MAX_FILES = int(os.getenv("MAX_FILES", "10"))

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
    resp = await client.post(f"{TEI_URL}/embed", json={"texts": texts}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["embeddings"]


async def fetch_rerank(client: httpx.AsyncClient, query: str, docs: List[str]):
    resp = await client.post(f"{TEI_URL}/rerank", json={"query": query, "documents": docs}, timeout=60.0)
    resp.raise_for_status()
    return resp.json()["results"]


async def extract_field_vllm(client: httpx.AsyncClient, context: str, field: Dict):
    prompt = f"CONTEXTE:\n{context}\n\nQUESTION: {field['question']}"
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": "Assistant médical. Réponds en JSON: {'value': ..., 'source_quote': ...}"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
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
    """Exécute le pipeline complet en arrière-plan."""
    collection_name = f"col_{job_id}"
    try:
        async with httpx.AsyncClient() as client:
            # 1. OCR Multi-fichiers
            JOBS[job_id].update({"status": "processing", "message": "📄 Numérisation et OCR des documents patients...",
                            "progress": 10})
            full_context_md = ""
            logger.info(f"Step 1: OCR de {len(report_paths)} fichiers ...")
            for report_path in report_paths:
                with open(report_path, "rb") as f:
                    file_content = f.read()
                ocr_resp = await client.post(f"{MARKER_URL}/extract",
                                             files={'file': (report_path.name, file_content, 'application/pdf')},
                                             timeout=300.0)
                ocr_resp.raise_for_status()
                full_context_md += f"\n\n--- SOURCE: {report_path.name} ---\n\n" + ocr_resp.json().get("markdown", "")

            # 2. RAG & ChromaDB
            JOBS[job_id].update({"status": "processing", "message": "🧠 Vectorisation du contexte médical...", "progress": 40})
            chunks = markdown_semantic_chunking(full_context_md)
            embeds = await fetch_embeddings(client, chunks)
            col = chroma_client.get_or_create_collection(name=collection_name)
            col.add(documents=chunks, embeddings=embeds, ids=[f"{job_id}_{i}" for i in range(len(chunks))])
            await asyncio.sleep(0.1)

            # 3. RAG Loop
            JOBS[job_id].update({"status": "processing", "message": "🤖 Analyse LLM et extraction des entités...",
                            "progress": 60})
            with open(f"template/Form_{form_id}.json", "r") as f:
                template = json.load(f)

            tasks = []
            for field in template["fields"]:
                if "question" not in field:
                    continue
                q_emb = await fetch_embeddings(client, [field["question"]])
                hits = col.query(query_embeddings=q_emb, n_results=5)["documents"][0]
                reranked = await fetch_rerank(client, field["question"], hits)
                context = "\n---\n".join([r["document"] for r in reranked[:3]])
                tasks.append(extract_field_vllm(client, context, field))

            results = await asyncio.gather(*tasks)

            # 4. Mapping & Injection XFA
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

            JOBS[job_id].update({
                "status": "completed",
                "message": "✅ Formulaire généré avec succès !",
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
