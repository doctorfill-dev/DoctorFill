# DoctorFill — Wiki

Bienvenue sur le wiki de **DoctorFill**, l'application d'auto-remplissage de formulaires médicaux par IA.

## Navigation

| Page | Description |
|------|-------------|
| [Architecture](Architecture) | Vue d'ensemble de l'architecture microservices |
| [Déploiement Backend (DGX Spark)](Deploiement-Backend-DGX-Spark) | Mise en place du backend sur NVIDIA DGX Spark |
| [Déploiement Frontend (Cloudflare)](Deploiement-Frontend-Cloudflare) | Déploiement du frontend sur Cloudflare Pages + Tunnel |
| [Pipeline RAG](Pipeline-RAG) | Fonctionnement du pipeline RAG (OCR → Embedding → Retrieval → LLM) |
| [Templates](Templates) | Documentation des templates de formulaires (AVS, Cardio, LAA) |

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Frontend | React 19 + Vite 7 + Tailwind CSS + shadcn/ui |
| Desktop | Tauri 2 |
| OCR | Marker PDF (FastAPI) |
| Embeddings | BAAI/bge-m3 via TEI |
| Reranking | BAAI/bge-reranker-v2-m3 via TEI |
| LLM | Qwen2.5-14B-Instruct-AWQ via vLLM |
| Orchestration | FastAPI + ChromaDB (éphémère) |
| Infrastructure | NVIDIA DGX Spark (128 Go VRAM) |
| Hébergement frontend | Cloudflare Pages |
| Tunnel API | Cloudflare Tunnel |
