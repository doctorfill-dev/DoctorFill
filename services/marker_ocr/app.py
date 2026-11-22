import asyncio
import os
import hashlib
import logging
import tempfile
import time
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

from ocr_cache import OcrCache, purge_legacy_disk_cache
from textlayer import extract_text_layer, should_skip_ocr

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
# Évite de ré-OCR les mêmes documents lors de re-uploads. En mémoire seulement,
# et pas plus longtemps qu'un job : le texte d'un dossier ne doit pas survivre
# à la rétention annoncée (#32). Voir ocr_cache.py.
OCR_CACHE = OcrCache(
    max_entries=int(os.getenv("OCR_CACHE_SIZE", "500")),
    ttl_seconds=float(os.getenv("OCR_CACHE_TTL_SECONDS", "3600")),
)

# L'ancien cache disque gardait le texte intégral de chaque document sans limite.
_purged = purge_legacy_disk_cache()
if _purged:
    logger.info("Ancien cache OCR sur disque supprimé : %d entrée(s)", _purged)

# Permet de forcer l'OCR complet même quand une couche texte est présente.
FORCE_OCR = os.getenv("FORCE_OCR", "false").lower() == "true"


def _run_marker(file_path: str) -> str:
    """Conversion marker complète. Bloquante : à appeler via un thread."""
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

        # --- Cache par hash : skip si déjà traité ---
        content_hash = hashlib.sha256(content).hexdigest()
        # Les journaux désignent le document par son empreinte, jamais par son
        # nom : un nom de fichier médical contient souvent celui du patient.
        doc = f"doc={content_hash[:12]}"
        cached = OCR_CACHE.get(content_hash)
        if cached is not None:
            logger.info(f"Cache hit ({doc})")
            return JSONResponse(content={**cached, "status": "success", "cached": True})

        t0 = time.perf_counter()

        # --- Étage 1 : couche texte native (~ms/page) ---
        # Ne coûte presque rien et évite l'OCR sur la majorité des PDF médicaux,
        # qui sont exportés d'un DPI et portent déjà leur texte.
        mode = "ocr"
        full_text = ""
        if not FORCE_OCR:
            try:
                text, ratio, pages = extract_text_layer(file_path)
                if should_skip_ocr(ratio, pages):
                    full_text, mode = text, "text_layer"
                else:
                    logger.info(f"{doc}: couche texte insuffisante "
                                f"({ratio:.0%} de {pages} pages) → OCR")
            except Exception as exc:
                logger.warning(f"{doc}: lecture de la couche texte impossible "
                               f"({type(exc).__name__}) → OCR")

        # --- Étage 2 : OCR marker, dans un thread pour ne pas bloquer la boucle ---
        if mode == "ocr":
            full_text = await asyncio.to_thread(_run_marker, file_path)

        elapsed = time.perf_counter() - t0
        logger.info(f"Extraction {mode} ({doc}): {len(full_text)} chars "
                    f"en {elapsed:.2f}s")

        payload = {"markdown": full_text, "mode": mode, "elapsed_s": round(elapsed, 3)}
        OCR_CACHE.put(content_hash, payload)
        return JSONResponse(content={**payload, "status": "success", "cached": False})

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
