import os
import logging
import shutil
import tempfile
from pathlib import Path
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
        with os.fdopen(fd, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        rendered = converter(file_path)
        full_text, _, _ = text_from_rendered(rendered)

        return JSONResponse(content={"status": "success", "markdown": full_text})

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
