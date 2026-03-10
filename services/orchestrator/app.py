import os
import re
import uuid
import asyncio
import httpx
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import chromadb
import shutil # fix du 10.03

# Imports core
from core.extract import extract_xfa_datasets
from core.fill import update_datasets
from core.inject import inject_datasets
from core.checkbox import discover_checkbox_paths, normalize_checkboxes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DoctorFill - Orchestrator Hub")

# --- MIDDLEWARE pour le dév
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # ⚠️ accepte toutes les origines
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

MARKER_URL = os.getenv("MARKER_URL", "http://localhost:8082")
TEI_URL = os.getenv("TEI_URL", "http://localhost:8081")
VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.getenv("VLLM_MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-AWQ")

chroma_client = chromadb.EphemeralClient()


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


# --- ROUTES ---

@app.get("/forms")
async def list_forms():
    template_path = Path("template")
    return {"forms": [f.stem.replace("Form_", "") for f in template_path.glob("Form_*.json")]}


@app.post("/process-form")
async def process_form(
        report_files: List[UploadFile] = File(...),
        # fix du 10.03 : recherche automatique des templates
        # todo : delete commented lines when tested
        # form_file: UploadFile = File(...),
        form_id: str = Form(...)
):
    job_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(f"/tmp/{job_id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    collection_name = f"col_{job_id}"

    try:
        async with httpx.AsyncClient() as client:
            # 1. OCR Multi-fichiers
            full_context_md = ""
            logger.info(f"Step 1: OCR de {len(report_files)} fichiers ...")
            for report in report_files:
                report_content = await report.read()
                ocr_resp = await client.post(f"{MARKER_URL}/extract",
                                             files={'file': (report.filename, report_content, 'application/pdf')},
                                             timeout=300.0)
                ocr_resp.raise_for_status()
                full_context_md += f"\n\n--- SOURCE: {report.filename} ---\n\n" + ocr_resp.json().get("markdown", "")

            # 2. RAG & ChromaDB (Fix: get_or_create pour éviter les conflits)
            chunks = markdown_semantic_chunking(full_context_md)
            embeds = await fetch_embeddings(client, chunks)
            col = chroma_client.get_or_create_collection(name=collection_name)
            col.add(documents=chunks, embeddings=embeds, ids=[f"{job_id}_{i}" for i in range(len(chunks))])
            await asyncio.sleep(0.1)  # Laisser ChromaDB respirer

            # 3. RAG Loop
            with open(f"template/Form_{form_id}.json", "r") as f:
                template = json.load(f)

            tasks = []
            for field in template["fields"]:
                if "question" not in field: continue
                q_emb = await fetch_embeddings(client, [field["question"]])
                hits = col.query(query_embeddings=q_emb, n_results=5)["documents"][0]
                reranked = await fetch_rerank(client, field["question"], hits)
                context = "\n---\n".join([r["document"] for r in reranked[:3]])
                # On prépare la tâche (ne pas oublier de l'await plus tard)
                tasks.append(extract_field_vllm(client, context, field))

            # 4. Inférence asynchrone (Execution réelle)
            results = await asyncio.gather(*tasks)

            # 5. Mapping & Injection XFA
            empty_form_path = tmp_dir / "empty.pdf"

            # --- begin fix du 10.03 : recherche automatique des templates
            source_template_path = Path(f"template/Form_{form_id}.pdf")

            if not source_template_path.exists():
                raise HTTPException(status_code=404,
                                    detail=f"Template {source_template_path} introuvable sur le serveur.")

            shutil.copy(source_template_path, empty_form_path)

            # fix du 10.03 : recherche automatique des templates
            # todo : delete commented lines when tested
            # with open(empty_form_path, "wb") as f:
            #    f.write(await form_file.read())

            # -- end fix du 10.03

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

            return FileResponse(output_pdf, media_type="application/pdf", filename=f"filled_{form_id}.pdf")

    finally:
        # Nettoyage sécurisé
        try:
            chroma_client.delete_collection(name=collection_name)
        except Exception:
            pass