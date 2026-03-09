# Architecture globale DoctorFill

## 🎯 Endpoints
- `:8082/extract` : marker_ocr
- `:8082/health` : marker_ocr
- `:8080/forms` : orchestrator
- `:8080/process-form` : orchestrator
- `:8081/embed` : tei
- `:8081/rerank` : tei

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

## 🐳 Commandes Utiles (Docker Compose)

L'ensemble de la stack est géré via Docker Compose pour simplifier le cycle de vie, la mise en réseau, et libérer rapidement la VRAM du DGX. Place-toi dans le dossier `services/` pour exécuter ces commandes :

- **Démarrer tous les services (en tâche de fond) :**
  ```bash
  docker compose up -d
  ```
- **Reconstruire l'Orchestrateur (après modification du code) et démarrer :**
  ```bash
  docker compose up -d --build
  ```
- **Couper tous les services et libérer la VRAM (Arrêt d'urgence / Fin de session) :**
  ```bash
  docker compose down
  ```
- **Voir les logs en direct de toute la stack (Ctrl+C pour quitter) :**
  ```bash
  docker compose logs -f
  ```
- **Vérifier l'état de santé des conteneurs :**
  ```bash
  docker compose ps
  ```

*Note Réseau : En mode Compose, les conteneurs communiquent via le DNS interne de Docker. Le fichier `.env` de l'Orchestrateur doit pointer vers les noms des services (ex: `http://vllm:8000/v1`) et non `localhost`.*

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