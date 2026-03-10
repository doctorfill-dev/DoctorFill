import os
import logging
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

# --- NOUVELLE API MARKER (v1.0+) ---
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Marker PDF Service (VRAM Optimized)")

# --- Chargement du modèle (Exécuté UNE SEULE FOIS au démarrage)
logger.info("Chargement des modèles de vision dans la VRAM en cours...")
converter = PdfConverter(
    artifact_dict=create_model_dict()  # Auto-détection du GPU (CUDA)
)
logger.info("Modèles chargés avec succès !")

UPLOAD_DIR = "/tmp/pdf_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/extract")
async def extract_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un PDF.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)

    # --- 1) Sauvegarde du PDF reçu
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # --- 2) Extraction via la mémoire VRAM avec la nouvelle API
        rendered = converter(file_path)
        full_text, _, _ = text_from_rendered(rendered)

        return JSONResponse(content={"status": "success", "markdown": full_text})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'exécution Marker : {str(e)}")
    finally:
        # --- 3) Nettoyage de sécurité
        if os.path.exists(file_path):
            os.remove(file_path)


@app.get("/health")
async def health_check():
    return {"status": "Marker API is running & Models are loaded in VRAM"}