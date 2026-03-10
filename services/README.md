# Architecture globale DoctorFill

## 🎯 Endpoints

- `:8082/extract` : marker_ocr
- `:8082/health` : marker_ocr
- `:8080/forms` : orchestrator
- `:8080/process-form` : orchestrator
- `:8080/status/{job_id}` : orchestrator
- `:8080/download/{job_id}` : orchestrator
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

## 🆕 Changements récents (10.03.2026)

### Orchestrateur : traitement non-bloquant

L’orchestrateur fonctionne désormais avec une logique de **job asynchrone** :

- `POST /process-form` démarre le traitement et retourne immédiatement un `job_id`
- `GET /status/{job_id}` permet de suivre l’avancement
- `GET /download/{job_id}` permet de récupérer le PDF final

Cette évolution réduit fortement le risque de timeout HTTP sur les traitements longs.

### Chargement automatique des templates PDF

Le frontend n’a plus besoin d’envoyer le formulaire vide à chaque requête.

L’orchestrateur charge directement le template PDF depuis :

```
forms/Form_{form_id}.pdf
```

Cela simplifie les appels côté client et réduit le payload envoyé à l’API.

## 🔄 Flux global

1. Le client envoie les documents source à l’orchestrateur via `POST /process-form`
2. L’orchestrateur stocke temporairement les fichiers et démarre un job en arrière-plan
3. L’orchestrateur appelle :
   - `marker_ocr` pour extraire le contenu PDF
   - `tei` pour les embeddings et le reranking
   - `vllm` pour l’extraction sémantique des champs
4. L’orchestrateur injecte les données dans le PDF XFA
5. Le client récupère le statut puis le PDF final

## 🐳 Commandes Utiles (Docker Compose)

L'ensemble de la stack est géré via Docker Compose pour simplifier le cycle de vie, la mise en réseau, et libérer rapidement la VRAM du DGX. Place-toi dans le dossier `services/` pour exécuter ces commandes :

- **Démarrer tous les services (en tâche de fond) :**
  ```bash
  docker compose up -d
  ```

- **Reconstruire les conteneurs (après modification du code) et démarrer :**
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
  
- **Voir les logs en direct depuis un instant T : **
  ```bash
  docker compose logs -f --tail=0
  ```

- **Vérifier l'état de santé des conteneurs :**
  ```bash
  docker compose ps
  ```
  
- **_Re-build_ un conteneur spécifique (ici orchestrator) :**
  ```bash
  docker compose up -d --build orchestrator
  ```

*Note Réseau : En mode Compose, les conteneurs communiquent via le DNS interne de Docker. Le fichier `.env` de l'Orchestrateur doit pointer vers les noms des services (ex: `http://vllm:8000/v1`) et non `localhost`.*

## 💾 Gestion de la VRAM & Sanity Check (NVIDIA DGX Spark)

Capacité totale : **128 Go unifiée (Architecture Grace/Blackwell GB10)**  
Commande de monitoring : `nvidia-smi`

**Consommation réelle (Mesurée en prod) :**
- `df-services-marker_ocr` : ~3.8 Go (`3793 MiB`) - *Modèles Vision Surya/Texify chargés.*
- `df-services-tei` : ~4.5 Go (`4522 MiB`) - *Modèles d'Embedding et de Reranking chargés.*
- `df-services-vllm` : ~17.7 Go (`17712 MiB`) - *Pré-allocation KV Cache agressive par défaut.*
- `LM Studio (Dev/QA)` : ~0.17 Go (`170 MiB`) - *Outil de test UI local.*

**Total consommé : ~40 Go (~30% de la capacité totale).**  
L'infrastructure est très saine et dispose de plus de 100 Go de marge pour la scalabilité des requêtes concurrentes.

*Note : Les modèles sont chargés en VRAM au démarrage des conteneurs (warm start) pour garantir une latence minimale lors des requêtes.*