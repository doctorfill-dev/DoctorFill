import os
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import torch
from sentence_transformers import SentenceTransformer, CrossEncoder

app = FastAPI(title="DoctorFill - Embeddings & Reranking API")

# --- VARIABLES D'ENVIRONNEMENT
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")

# Variables globales pour stocker les modèles en VRAM
embedder = None
reranker = None


@app.on_event("startup")
def load_models():
    global embedder, reranker
    print("⏳ Chargement des modèles en VRAM (Grace ARM64)...")

    # Force l'utilisation du GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # 1. Modèle d'Embedding
    embedder = SentenceTransformer(EMBED_MODEL_NAME, device=device)
    print(f"✅ Embedding ({EMBED_MODEL_NAME}) chargé.")

    # 2. Modèle de Reranking
    reranker = CrossEncoder(RERANK_MODEL_NAME, device=device)
    print(f"✅ Reranker ({RERANK_MODEL_NAME}) chargé.")


# --- SCHEMAS
class EmbedRequest(BaseModel):
    texts: List[str]


class RerankRequest(BaseModel):
    query: str
    documents: List[str]


# --- ROUTES
@app.post("/embed")
def get_embeddings(req: EmbedRequest):
    # normalize_embeddings=True est recommandé pour bge-m3 (Cosine Similarity)
    embeddings = embedder.encode(req.texts, normalize_embeddings=True)
    return {"embeddings": embeddings.tolist()}


@app.post("/rerank")
def get_rerank(req: RerankRequest):
    pairs = [[req.query, doc] for doc in req.documents]
    scores = reranker.predict(pairs)

    # Associer les scores aux documents et trier (score décroissant)
    scored_docs = sorted(zip(req.documents, scores.tolist()), key=lambda x: x[1], reverse=True)

    return {
        "results": [
            {"document": doc, "score": score}
            for doc, score in scored_docs
        ]
    }