# Architecture globale DoctorFill

## endpoints

## ✅ Composants actifs

- `df-services-vllm` : Inférence LLM (vLLM)
- `df-services-marker_ocr` : Extraction PDF (Marker OCR)
- `df-services-tei` : Embeddings & Reranking (TEI)
- `df-services-orchestrator` : Cerveau du pipeline RAG (FastAPI)

## 🏴‍☠️ Ports réseau

- **8000** : vLLM
- **8080** : Orchestrateur
- **8081** : TEI (Text Embeddings Inference)
- **8082** : Marker OCR

## 💾 Gestion de la VRAM & Sanity Check (NVIDIA DGX Spark)

Capacité totale : **128 Go unifiée (Architecture Grace/Blackwell GB10)**
Commande de monitoring : `nvidia-smi`

**Consommation réelle (Mesurée en prod) :**
- `df-services-marker_ocr` : ~3.8 Go (`3793 MiB`) - *Modèles Vision Surya/Texify chargés.*
- `df-services-tei` : ~4.5 Go (`4522 MiB`) - *Modèles d'Embedding et Reranking chargés.*
- `df-services-vllm` : ~17.7 Go (`17712 MiB`) - *Pre-allocation KV Cache agressif par défaut.*
- `LM Studio (Dev/QA)` : ~0.17 Go (`170 MiB`) - *Outil de test UI local.*

**Total consommé : ~40 Go (~30% de la capacité totale).**
L'infrastructure est très saine et dispose de plus de 100 Go de marge pour la scalabilité des requêtes concurrentes.

*Note : Les modèles sont chargés en VRAM au démarrage des conteneurs (Warm start) pour garantir une latence minimale lors des requêtes.*