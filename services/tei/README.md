# DoctorFill - Microservice : TEI (Text Embeddings & Reranking)

API FastAPI conteneurisée gérant la vectorisation (Embeddings) et le reclassement sémantique (Reranking) pour le pipeline RAG. 

## 🚀 Architecture & Choix techniques

Pour respecter l'architecture matérielle ARM64 (Grace/Blackwell) et éviter les erreurs de format (`exec format error` de l'image officielle HF), ce service utilise une image NVIDIA de base avec `sentence-transformers`.
- **Modèle Embedding :** `BAAI/bge-m3` (Multilingue, dense, ~2.5 Go VRAM)
- **Modèle Reranking :** `BAAI/bge-reranker-v2-m3` (Multilingue, ~1.5 Go VRAM)

## 🛠️ Installation & Démarrage

**1. Build de l'image :**
```bash
docker build -t doctorfill/tei-service:latest .
```

**2. Lancement du conteneur :**
```bash
docker run -d \
  --gpus all \
  -p 8081:8081 \
  --name df-services-tei \
  -e EMBED_MODEL_NAME="BAAI/bge-m3" \
  -e RERANK_MODEL_NAME="BAAI/bge-reranker-v2-m3" \
  doctorfill/tei-service:latest
```

## 🛰️ Endpoints

- `POST /embed` : Reçoit une liste de textes, retourne les vecteurs d'embeddings (Cosine Similarity optimisée).
- `POST /rerank` : Reçoit une requête et des documents, retourne les documents triés par pertinence avec leurs scores.