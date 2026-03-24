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

from core.extract import extract_xfa_datasets, PDFNoXFAError
from core.fill import update_datasets
from core.inject import inject_datasets
from core.checkbox import discover_checkbox_paths, normalize_checkboxes
from core.acroform import detect_form_type, fill_acroform
from medical_synthesis import run_medical_synthesis
from prompts import SYSTEM_PROMPT_BATCH_EXTRACT, build_batch_extraction_prompt, SECTION_SYNTHESIS_KEYS

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

def markdown_semantic_chunking(md_text: str, max_words: int = 800) -> List[str]:
    raw_chunks = re.split(r'(?=\n#{1,3} )', md_text)
    final_chunks = []
    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        words = chunk.split()
        if len(words) > max_words:
            for i in range(0, len(words), max_words - 100):
                final_chunks.append(" ".join(words[i:i + max_words]))
        else:
            final_chunks.append(chunk)
    return final_chunks


def _normalize_field_value(value: str, field_type: str | None) -> str:
    """Normalise la valeur extraite selon le type du champ déclaré dans le template."""
    if not value or not field_type:
        return value
    if field_type == "sex":
        # Normalise vers M ou F
        v = value.strip().upper()
        if v in ("M", "MASCULIN", "HOMME", "MALE", "H"):
            return "M"
        if v in ("F", "FÉMININ", "FEMININ", "FEMME", "FEMALE"):
            return "F"
        # Cas où le LLM a renvoyé "M (masculin)" ou "F (féminin)"
        if v.startswith("M"):
            return "M"
        if v.startswith("F"):
            return "F"
        return value  # Valeur non reconnue : on laisse passer
    if field_type == "percent":
        # Garde uniquement les chiffres (et éventuellement une virgule/point décimale)
        match = re.search(r'\d+(?:[.,]\d+)?', value.replace("%", ""))
        if match:
            return match.group(0).replace(",", ".")
        return value
    return value


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


def _filter_synthesis_for_section(synthesis: Dict | None, section_id: str) -> str | None:
    """Retourne uniquement les clés de synthèse pertinentes pour la section donnée."""
    if not synthesis:
        return None
    keys = SECTION_SYNTHESIS_KEYS.get(section_id, list(synthesis.keys()))
    filtered = {k: synthesis[k] for k in keys if k in synthesis and synthesis[k]}
    return json.dumps(filtered, ensure_ascii=False) if filtered else None


def _group_fields_into_batches(fields: List[Dict], max_batch_size: int = 7) -> List[List[Dict]]:
    """Groupe les champs par section (préfixe de l'ID), max max_batch_size par batch."""
    from collections import defaultdict
    by_section: Dict[str, List[Dict]] = defaultdict(list)
    for f in fields:
        section = str(f["id"]).split(".")[0]
        by_section[section].append(f)
    batches = []
    for section_fields in by_section.values():
        for i in range(0, len(section_fields), max_batch_size):
            batches.append(section_fields[i:i + max_batch_size])
    return batches


async def extract_fields_batch_vllm(
    client: httpx.AsyncClient,
    fields: List[Dict],
    chunks_context: str,
    synthesis_json: str | None,
    llm_sem: asyncio.Semaphore,
) -> List[Dict]:
    """Extrait plusieurs champs en un seul appel LLM (mode batch)."""
    prompt = build_batch_extraction_prompt(fields, synthesis_json, chunks_context)
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_BATCH_EXTRACT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.05,
        "response_format": {"type": "json_object"},
    }
    try:
        async with llm_sem:
            resp = await client.post(f"{VLLM_URL}/chat/completions", json=payload, timeout=180.0)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        results = []
        for field in fields:
            fid = str(field["id"])
            if fid in data and isinstance(data[fid], dict):
                results.append({"id": field["id"], "result": data[fid]})
            else:
                results.append({"id": field["id"], "error": "field_missing_in_response"})
        return results
    except Exception as e:
        logger.error(f"Erreur batch vLLM ({[f['id'] for f in fields]}): {e}")
        return [{"id": f["id"], "error": "extraction_failed"} for f in fields]


async def run_pipeline_task(job_id: str, form_id: str, tmp_dir: Path, report_paths: List[Path]):
    """
    Pipeline avec streaming OCR→embed, synthèse médicale globale et semaphores rerank/LLM.
    - STEP 1 : OCR et embedding en parallèle via asyncio.Queue
    - STEP 2 : Synthèse médicale globale (LLM lit tous les documents, produit un JSON structuré)
    - STEP 3 : RAG hybride (synthèse + chunks reranked) pour chaque champ
    - STEP 4 : Injection XFA
    """
    collection_name = f"col_{job_id}"
    debug_dir = DEBUG_LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:8]}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "markdown").mkdir(exist_ok=True)

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
                            # Accumuler pour la synthèse médicale
                            ocr_raw_results.append({"filename": path.name, "markdown": md_text})
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
            # STEP 2 : Synthèse médicale globale (nouveau)
            # ============================================================
            JOBS[job_id].update({
                "status": "processing",
                "message": "🧠 Synthèse médicale de tous les documents...",
                "progress": 42,
            })
            t_synthesis_start = time.perf_counter()
            synthesis = await run_medical_synthesis(ocr_raw_results, VLLM_URL, VLLM_MODEL)
            timings["medical_synthesis"] = time.perf_counter() - t_synthesis_start

            synthesis_json: str | None = None
            if synthesis:
                synthesis_json = json.dumps(synthesis, ensure_ascii=False)
                nb_dx = len(synthesis.get("diagnostics", []))
                nb_it = len(synthesis.get("incapacites_travail", []))
                logger.info(
                    f"[{job_id[:8]}] Synthèse OK en {timings['medical_synthesis']:.1f}s "
                    f"— {nb_dx} diagnostics, {nb_it} périodes d'incapacité"
                )
                # Debug : sauvegarder la synthèse
                (debug_dir / "medical_synthesis.json").write_text(
                    json.dumps(synthesis, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                logger.warning(f"[{job_id[:8]}] Synthèse échouée — mode RAG pur activé")

            # ============================================================
            # STEP 3 : RAG hybride — rerank par champ + batch LLM par section
            # Phase A : retrieval + rerank en parallèle (sem=5), top-8 chunks/champ
            # Phase B : batch LLM par section (sem=10), ~7 champs par appel
            # ============================================================
            t_rag_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing",
                                 "message": "🤖 Analyse LLM et extraction des entités...", "progress": 50})
            with open(f"template/Form_{form_id}.json", "r") as f:
                template = json.load(f)

            fields_with_q = [f for f in template["fields"] if "question" in f]
            n_fields = len(fields_with_q)
            logger.info(f"[{job_id[:8]}] Step 3: {n_fields} champs — phase A rerank, phase B batch-LLM...")

            all_q_embs = await fetch_embeddings_batched(client, [f["question"] for f in fields_with_q])

            rerank_sem = asyncio.Semaphore(5)
            llm_sem = asyncio.Semaphore(10)

            # --- Phase A : retrieval + rerank par champ (top-8 chunks) ---
            async def _retrieve_for_field(field: Dict, q_emb) -> List[str]:
                hits = col.query(query_embeddings=[q_emb], n_results=min(30, len(chunks)))["documents"][0]
                reranked = await fetch_rerank(client, field["question"], hits, rerank_sem=rerank_sem)
                return [r["document"] for r in reranked[:12]]

            field_top_chunks: List[List[str]] = await asyncio.gather(*[
                _retrieve_for_field(f, emb) for f, emb in zip(fields_with_q, all_q_embs)
            ])
            field_chunk_map: Dict[str, List[str]] = {
                str(f["id"]): cks for f, cks in zip(fields_with_q, field_top_chunks)
            }

            # --- Phase B : batch LLM par section ---
            batches = _group_fields_into_batches(fields_with_q, max_batch_size=7)
            batches_done = 0

            async def _extract_batch(batch_fields: List[Dict]) -> List[Dict]:
                nonlocal batches_done
                # Fusionner les chunks uniques du batch (max 16 chunks fusionnés)
                seen: set = set()
                merged_chunks: List[str] = []
                for bf in batch_fields:
                    for c in field_chunk_map.get(str(bf["id"]), []):
                        if c not in seen:
                            seen.add(c)
                            merged_chunks.append(c)
                chunks_ctx = "\n---\n".join(merged_chunks[:24])

                # Filtrer la synthèse sur la section de ce batch
                section = str(batch_fields[0]["id"]).split(".")[0]
                filtered_synthesis = _filter_synthesis_for_section(synthesis, section)

                result = await extract_fields_batch_vllm(
                    client, batch_fields, chunks_ctx, filtered_synthesis, llm_sem
                )
                batches_done += 1
                JOBS[job_id].update({
                    "message": f"🤖 Extraction {batches_done}/{len(batches)} sections...",
                    "progress": 50 + int(40 * batches_done / len(batches))
                })
                return result

            batch_results = await asyncio.gather(*[_extract_batch(b) for b in batches])
            results = [item for batch in batch_results for item in batch]
            t_rag_end = time.perf_counter()
            timings["rag_extraction"] = t_rag_end - t_rag_start

            # Stocker les résultats bruts pour le debug/eval
            JOBS[job_id]["_debug_results"] = results
            JOBS[job_id]["_debug_chunks_count"] = len(chunks)
            JOBS[job_id]["_debug_synthesis"] = synthesis

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
            # STEP 4 : Injection des valeurs dans le formulaire PDF
            #          Supporte XFA, AcroForm pur et formulaires hybrides
            # ============================================================
            t_xfa_start = time.perf_counter()
            JOBS[job_id].update({"status": "processing", "message": "✍️ Injection des données dans le formulaire PDF...",
                            "progress": 90})
            empty_form_path = tmp_dir / "empty.pdf"

            source_template_path = Path(f"forms/Form_{form_id}.pdf")
            if not source_template_path.exists():
                raise FileNotFoundError(f"Template introuvable pour form_id={form_id}")
            shutil.copy(source_template_path, empty_form_path)

            # Détecter le type de formulaire
            form_type = detect_form_type(empty_form_path)
            logger.info(f"[{job_id[:8]}] Type de formulaire détecté : {form_type}")

            # Construire les valeurs extraites par champ
            xfa_values: Dict[str, str] = {}    # xml_path → valeur
            acro_values: Dict[str, str] = {}   # acroform_name → valeur

            for res in results:
                if "result" not in res or not res["result"].get("value"):
                    continue
                value = str(res["result"]["value"])
                f_def = next((f for f in template["fields"] if f.get("id") == res["id"]), None)
                if f_def is None:
                    continue
                # Normalisation selon le type déclaré dans le template
                value = _normalize_field_value(value, f_def.get("type"))
                # XFA path
                if f_def.get("xml_path"):
                    xfa_values[f_def["xml_path"]] = value
                # AcroForm name (champ optionnel dans le template JSON)
                if f_def.get("acroform_name"):
                    acro_values[f_def["acroform_name"]] = value

            output_pdf = tmp_dir / "output.pdf"

            if form_type in ("xfa", "hybrid"):
                # --- Injection XFA ---
                base_xml = tmp_dir / "base.xml"
                try:
                    extract_xfa_datasets(empty_form_path, base_xml)
                    checkbox_paths = discover_checkbox_paths(base_xml)
                    normalize_checkboxes(xfa_values, checkbox_paths)
                    filled_xml = tmp_dir / "filled.xml"
                    update_datasets(base_xml, xfa_values, filled_xml, template["fields"])
                    # Pour un hybride, on part du template pour la base XFA
                    inject_datasets(empty_form_path, filled_xml, output_pdf)
                except PDFNoXFAError:
                    logger.warning(f"[{job_id[:8]}] XFA introuvable malgré détection hybrid — fallback AcroForm")
                    form_type = "acroform"

            if form_type == "acroform" or (form_type == "hybrid" and acro_values):
                # --- Injection AcroForm ---
                # Pour un hybride : repartir du PDF XFA déjà rempli si disponible, sinon template
                acro_source = output_pdf if (form_type == "hybrid" and output_pdf.exists()) else empty_form_path
                fill_acroform(acro_source, acro_values, output_pdf)

            if form_type == "none" or not output_pdf.exists():
                raise ValueError(f"Impossible de remplir le formulaire (type={form_type})")

            t_xfa_end = time.perf_counter()
            timings["xfa_injection"] = t_xfa_end - t_xfa_start
            timings["total"] = time.perf_counter() - t_pipeline_start

            # Debug : résumé
            ok_count = sum(1 for r in results if "result" in r and r["result"].get("value"))
            err_count = sum(1 for r in results if "error" in r)
            empty_count = sum(1 for r in results if "result" in r and not r["result"].get("value"))
            synthesis_info = "Non disponible (fallback RAG pur)"
            if synthesis:
                nb_dx = len(synthesis.get("diagnostics", []))
                nb_it = len(synthesis.get("incapacites_travail", []))
                synthesis_info = f"{nb_dx} diagnostics, {nb_it} périodes d'incapacité"
            summary = (
                f"Job: {job_id}\nForm: {form_id}\nDate: {datetime.now().isoformat()}\n"
                f"Fichiers: {total_files}\nChunks: {len(chunks)}\n"
                f"Type formulaire: {form_type}\n"
                f"Synthèse médicale: {synthesis_info}\n"
                f"Champs: {n_fields} (OK: {ok_count}, Erreurs: {err_count}, Vides: {empty_count})\n"
                f"Timings: OCR+embed={timings['ocr_embed_pipeline']:.1f}s, "
                f"Synthèse={timings.get('medical_synthesis', 0):.1f}s, "
                f"RAG={timings['rag_extraction']:.1f}s, Injection={timings['xfa_injection']:.1f}s, "
                f"Total={timings['total']:.1f}s\n"
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
                "error": r.get("error"),
            }
            for r in debug_results
        ],
    }
