import os
import hashlib
import asyncio
import logging
import shutil
import tempfile
import time
import json
from pathlib import Path
from functools import partial
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Marker PDF Service (VRAM Optimized)")

# --- Chargement du modèle (une seule fois au démarrage)
logger.info("Chargement des modèles de vision dans la VRAM en cours...")
converter = PdfConverter(
    artifact_dict=create_model_dict()
)
logger.info("Modèles chargés avec succès !")

UPLOAD_DIR = "/tmp/pdf_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Cache OCR par hash SHA-256 du contenu PDF ---
# Clé = sha256(contenu PDF), Valeur = markdown résultat
# Évite de ré-OCR les mêmes documents lors de re-uploads
OCR_CACHE: dict[str, str] = {}
MAX_CACHE_SIZE = int(os.getenv("OCR_CACHE_SIZE", "500"))


def _convert_sync(file_path: str) -> str:
    """Exécution synchrone de Marker (GPU-bound). Appelé via run_in_executor."""
    rendered = converter(file_path)
    full_text, _, _ = text_from_rendered(rendered)
    return full_text


@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    # [SEC-02] Assainir le nom de fichier pour empêcher le path traversal
    original_name = file.filename or "upload.pdf"
    safe_name = Path(original_name).name.replace("\x00", "")

    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")

    # [SEC-14] Utiliser un fichier temporaire unique (évite les race conditions)
    fd, file_path = tempfile.mkstemp(suffix=".pdf", dir=UPLOAD_DIR)
    try:
        content = await file.read()
        with os.fdopen(fd, "wb") as buffer:
            buffer.write(content)

        # --- Cache OCR par hash : skip si déjà traité ---
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash in OCR_CACHE:
            logger.info(f"Cache hit pour {safe_name} (hash={content_hash[:12]}...)")
            return JSONResponse(content={
                "status": "success",
                "markdown": OCR_CACHE[content_hash],
                "cached": True
            })

        # --- Exécution dans un thread pool pour ne pas bloquer l'event loop ---
        # Permet le vrai parallélisme : plusieurs PDFs traités simultanément
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        full_text = await loop.run_in_executor(None, _convert_sync, file_path)
        elapsed = time.perf_counter() - t0
        logger.info(f"OCR terminé pour {safe_name}: {len(full_text)} chars en {elapsed:.1f}s")

        # --- Stocker en cache (FIFO si plein) ---
        if len(OCR_CACHE) >= MAX_CACHE_SIZE:
            oldest_key = next(iter(OCR_CACHE))
            del OCR_CACHE[oldest_key]
        OCR_CACHE[content_hash] = full_text

        return JSONResponse(content={"status": "success", "markdown": full_text, "cached": False})

    except Exception as e:
        # [SEC-10] Log détaillé côté serveur, message générique côté client
        logger.error(f"Erreur extraction PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur lors de l'extraction du PDF.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "marker_ocr"}
