# Architecture

## Vue d'ensemble

DoctorFill utilise une architecture **microservices containerisée** avec 4 services Docker orchestrés via Docker Compose sur un serveur NVIDIA DGX Spark.

```
                        ┌──────────────────────┐
                        │   Cloudflare Pages    │
                        │   (Frontend React)    │
                        └──────────┬───────────┘
                                   │ HTTPS
                        ┌──────────▼───────────┐
                        │  Cloudflare Tunnel    │
                        │  (doctorfill.ch/api)  │
                        └──────────┬───────────┘
                                   │ HTTP :8080
┌──────────────────────────────────▼──────────────────────────────────┐
│                        NVIDIA DGX Spark                            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                   Docker Compose Stack                       │   │
│  │                                                               │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │            Orchestrator (:8080)                       │   │   │
│  │  │  - FastAPI + ChromaDB éphémère                        │   │   │
│  │  │  - Coordination pipeline RAG                          │   │   │
│  │  │  - Remplissage XFA PDF                                │   │   │
│  │  │  - Gestion des jobs async                             │   │   │
│  │  └───────┬──────────────┬──────────────┬────────────────┘   │   │
│  │          │              │              │                      │   │
│  │  ┌───────▼──────┐ ┌────▼───────┐ ┌───▼──────────┐          │   │
│  │  │  Marker OCR  │ │    TEI     │ │    vLLM      │          │   │
│  │  │   (:8082)    │ │  (:8081)   │ │   (:8000)    │          │   │
│  │  │  ~3.8 Go GPU │ │ ~4.5 Go GPU│ │ ~17.7 Go GPU │          │   │
│  │  └──────────────┘ └────────────┘ └──────────────┘          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  VRAM total : ~40 Go / 128 Go (30% utilisation)                    │
└─────────────────────────────────────────────────────────────────────┘
```

## Services

### 1. Orchestrator (`:8080`)
- **Rôle** : Hub central qui coordonne le pipeline OCR → RAG → remplissage PDF
- **Tech** : FastAPI, ChromaDB (in-memory), httpx
- **Endpoints principaux** :
  - `POST /process-form` — Lance un job de remplissage
  - `GET /status/{job_id}` — Statut et progression
  - `GET /download/{job_id}` — Téléchargement du PDF rempli
  - `GET /debug/{job_id}` — Résultats bruts d'extraction (évaluation)
- **Sécurité** : API Key, CORS, whitelist form_id, limites upload

### 2. Marker OCR (`:8082`)
- **Rôle** : Extraction de texte et layout depuis les PDFs médicaux
- **Tech** : FastAPI + marker-pdf
- **Sortie** : Markdown structuré (headings, tableaux, listes)
- **VRAM** : ~3.8 Go

### 3. TEI — Text Embeddings & Reranking (`:8081`)
- **Rôle** : Vectorisation des chunks + reranking sémantique
- **Modèles** :
  - Embedding : `BAAI/bge-m3`
  - Reranking : `BAAI/bge-reranker-v2-m3`
- **VRAM** : ~4.5 Go

### 4. vLLM (`:8000`)
- **Rôle** : Inférence LLM pour l'extraction de champs
- **Modèle** : `Qwen/Qwen2.5-14B-Instruct-AWQ` (quantifié)
- **Config** : `--gpu-memory-utilization 0.15`, `--max-model-len 8192`
- **VRAM** : ~17.7 Go

## Flux de traitement

```
1. Upload (PDF reports + form_id)
        ↓
2. OCR parallélisé (Semaphore=5)
   → Markdown structuré par fichier
        ↓
3. Chunking (semi-sémantique)
   → Découpage par headings + fallback 400 mots
        ↓
4. Embedding par batch (taille=64)
   → Vecteurs stockés dans ChromaDB éphémère
        ↓
5. Pour chaque champ du template :
   a. Embedding de la question
   b. Retrieval top-20 chunks (ChromaDB)
   c. Reranking → top-7 chunks
   d. LLM extraction (JSON structuré)
        ↓
6. Injection des valeurs dans le XML/XFA du PDF
        ↓
7. PDF rempli disponible en téléchargement
```
