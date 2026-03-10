"""
=============================================================================
DOCTORFILL - ORCHESTRATOR HUB
=============================================================================

MODIFICATIONS RÉCENTES (10.03.2026) :

[FIX 10.03 - A] : Suppression de l'upload du formulaire vierge par l'utilisateur.
- Problème : Le frontend devait envoyer le PDF vide (form_file) à chaque requête.
- Solution : L'orchestrateur va désormais chercher automatiquement le PDF vierge
  dans le dossier local `forms/` du conteneur en se basant sur le `form_id`.
  (Utilisation de shutil.copy au lieu de form_file.read()).

[FIX 10.03 - B] : Passage en architecture Asynchrone (Background Tasks & Polling).
- Problème : Le traitement synchrone (~40s) risquait de provoquer un timeout 
  HTTP (ex: erreur 524 sur Cloudflare) si le traitement dépassait 100s.
- Solution : La route POST /process-form ne bloque plus. Elle enregistre les
  fichiers temporairement, lance la tâche via `BackgroundTasks` et retourne 
  immédiatement un `job_id`.
  Ajout de deux nouvelles routes :
  - GET /status/{job_id} : Pour suivre la progression en temps réel.
  - GET /download/{job_id} : Pour récupérer le PDF final.
=============================================================================
"""

import os
import re
import uuid
import asyncio
import httpx
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any
# [FIX 10.03 - B] Ajout de BackgroundTasks
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import chromadb
# [FIX 10.03 - A] Ajout de shutil pour la copie locale
import shutil

# Imports core
from core.extract import extract_xfa_datasets
from core.fill import update_datasets
from core.inject import inject_datasets
from core.checkbox import discover_checkbox_paths, normalize_checkboxes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DoctorFill - Orchestrator Hub")

# --- MIDDLEWARE CORS (configurable via variable d'environnement)
# Dév  : ALLOWED_ORIGINS=* (ou ne pas la définir → défaut = "*")
# Prod : ALLOWED_ORIGINS=https://doctorfill.ch,https://www.doctorfill.ch
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _raw_origins.strip() == "*" else [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

MARKER_URL = os.getenv("MARKER_URL", "http://localhost:8082")
TEI_URL = os.getenv("TEI_URL", "http://localhost:8081")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-AWQ")

chroma_client = chromadb.EphemeralClient()

# --- [FIX 10.03 - B] ETAT EN MEMOIRE DES TÂCHES ---
# Dictionnaire global pour stocker la progression de chaque job.
# En production lourde, ceci serait remplacé par Redis ou une BDD.
JOBS: Dict[str, Dict[str, Any]] = {}

# --- CLEANUP AUTOMATIQUE DES FICHIERS TEMPORAIRES ---
# Durée de rétention des jobs terminés (en secondes) avant suppression automatique.
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "3600"))  # 1h par défaut


async def _cleanup_expired_jobs():
    """Tâche de fond qui purge les jobs terminés et leurs fichiers temporaires."""
    while True:
        await asyncio.sleep(300)  # Vérification toutes les 5 minutes
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


@app.on_event("startup")
async def startup_cleanup_task():
    """Lance la tâche de nettoyage périodique au démarrage."""
    asyncio.create_task(_cleanup_expired_jobs())


# ---------------------------------------------------
# --- UTILS ---

def markdown_semantic_chunking(md_text: str, max_words: int = 400) -> List[str]:
    raw_chunks = re.split(r'(?=\n#{1,3} )', md_text)
    final_chunks = []
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk: continue
        words = chunk.split()
        if len(words) > max_words:
            for i in range(0, len(words), max_words - 50):
                final_chunks.append(" ".join(words[i:i + max_words]))
        else:
            final_chunks.append(chunk)
    return final_chunks


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
        return {"id": field["id"], "error": str(e)}


# --- [FIX 10.03 - B] FONCTION DE TRAVAIL ASYNCHRONE ---
async def run_pipeline_task(job_id: str, form_id: str, tmp_dir: Path, report_paths: List[Path]):
    """
    Exécute le pipeline complet en arrière-plan et met à jour le dictionnaire JOBS.
    Anciennement le cœur de la route POST /process-form.
    """
    collection_name = f"col_{job_id}"
    try:
        async with httpx.AsyncClient() as client:
            # 1. OCR Multi-fichiers
            JOBS[job_id] = {"status": "processing", "message": "📄 Numérisation et OCR des documents patients...",
                            "progress": 10}
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
            JOBS[job_id] = {"status": "processing", "message": "🧠 Vectorisation du contexte médical...", "progress": 40}
            chunks = markdown_semantic_chunking(full_context_md)
            embeds = await fetch_embeddings(client, chunks)
            col = chroma_client.get_or_create_collection(name=collection_name)
            col.add(documents=chunks, embeddings=embeds, ids=[f"{job_id}_{i}" for i in range(len(chunks))])
            await asyncio.sleep(0.1)

            # 3. RAG Loop
            JOBS[job_id] = {"status": "processing", "message": "🤖 Analyse LLM et extraction des entités...",
                            "progress": 60}
            with open(f"template/Form_{form_id}.json", "r") as f:
                template = json.load(f)

            tasks = []
            for field in template["fields"]:
                if "question" not in field: continue
                q_emb = await fetch_embeddings(client, [field["question"]])
                hits = col.query(query_embeddings=q_emb, n_results=5)["documents"][0]
                reranked = await fetch_rerank(client, field["question"], hits)
                context = "\n---\n".join([r["document"] for r in reranked[:3]])
                tasks.append(extract_field_vllm(client, context, field))

            results = await asyncio.gather(*tasks)

            # 4. Mapping & Injection XFA
            JOBS[job_id] = {"status": "processing", "message": "✍️ Injection des données dans le PDF XFA...",
                            "progress": 90}
            empty_form_path = tmp_dir / "empty.pdf"

            # --- [FIX 10.03 - A] : Recherche automatique du template
            source_template_path = Path(f"forms/Form_{form_id}.pdf")
            if not source_template_path.exists():
                raise HTTPException(status_code=404,
                                    detail=f"Template {source_template_path} introuvable sur le serveur.")
            shutil.copy(source_template_path, empty_form_path)
            # Ancienne version supprimée :
            # with open(empty_form_path, "wb") as f:
            #    f.write(await form_file.read())
            # --- Fin [FIX 10.03 - A]

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

            # FINITION
            JOBS[job_id] = {
                "status": "completed",
                "message": "✅ Formulaire généré avec succès !",
                "progress": 100,
                "file_path": str(output_pdf),  # On stocke le chemin pour le téléchargement futur
                "completed_at": time.time()
            }

    except Exception as e:
        logger.error(f"Erreur Job {job_id}: {e}")
        JOBS[job_id] = {"status": "failed", "message": f"❌ Erreur: {str(e)}", "progress": 0, "completed_at": time.time()}
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


# --- [FIX 10.03 - B] Nouvelle version de process-form (Non-bloquante) ---
@app.post("/process-form")
async def process_form(
        background_tasks: BackgroundTasks,  # NOUVEAU
        report_files: List[UploadFile] = File(...),
        # [FIX 10.03 - A]
        # form_file: UploadFile = File(...), # Supprimé : Le fichier est récupéré en local (forms/)
        form_id: str = Form(...)
):
    """
    Initie le traitement. Sauvegarde les fichiers et lance la tâche en arrière-plan.
    Retourne immédiatement le job_id au frontend.
    """
    job_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(f"/tmp/{job_id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Sauvegarde des fichiers reçus sur le disque (obligatoire car UploadFile 
    # se ferme à la fin de cette fonction synchrone).
    saved_report_paths = []
    for report in report_files:
        file_path = tmp_dir / report.filename
        with open(file_path, "wb") as f:
            f.write(await report.read())
        saved_report_paths.append(file_path)

    # Initialisation de l'état
    JOBS[job_id] = {"status": "pending", "message": "Initialisation du pipeline...", "progress": 0}

    # On délègue le gros du travail à la fonction de background
    background_tasks.add_task(run_pipeline_task, job_id, form_id, tmp_dir, saved_report_paths)

    # On libère le client web immédiatement
    return {"job_id": job_id}


# --- [FIX 10.03 - B] Nouvelles routes de Polling ---
@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """
    Route appelée par le frontend toutes les 2 secondes pour connaître l'avancement.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job introuvable ou expiré.")
    return JOBS[job_id]


@app.get("/download/{job_id}")
async def download_result(job_id: str):
    """
    Route appelée par le frontend lorsque le statut passe à 'completed'.
    """
    if job_id not in JOBS or JOBS[job_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Fichier non disponible ou traitement en cours.")

    file_path = JOBS[job_id].get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable sur le disque.")

    return FileResponse(file_path, media_type="application/pdf", filename=f"DoctorFill_{job_id}.pdf")