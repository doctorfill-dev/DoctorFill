# DoctorFill

**Auto-remplissage de formulaires médicaux par IA** — Application qui extrait automatiquement les informations depuis des documents médicaux (rapports, lettres, notes cliniques) pour remplir les formulaires XFA/PDF standards suisses.

## Architecture

```
  Frontend (React)              Backend (Docker Compose — DGX Spark)
┌──────────────────┐     ┌──────────────────────────────────────────┐
│  Cloudflare Pages│────▶│  Orchestrator (:8080) ── FastAPI + RAG  │
│  doctorfill.ch   │     │     ├── Marker OCR (:8082) ── 3.8 Go   │
└──────────────────┘     │     ├── TEI (:8081) ────────── 4.5 Go   │
   Cloudflare Tunnel     │     └── vLLM (:8000) ──────── 17.7 Go  │
   api.doctorfill.ch     └──────────────────────────────────────────┘
```

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| **Frontend** | React 19, Vite 7, Tailwind, shadcn/ui, Tauri 2 | Interface utilisateur (web + desktop) |
| **Orchestrator** | FastAPI, ChromaDB, httpx | Coordination pipeline RAG + remplissage XFA |
| **Marker OCR** | marker-pdf (FastAPI) | Extraction texte/layout depuis PDF → Markdown |
| **TEI** | BAAI/bge-m3, BAAI/bge-reranker-v2-m3 | Embeddings + Reranking sémantique |
| **vLLM** | Qwen/Qwen2.5-14B-Instruct-AWQ | Extraction de champs par LLM |

## Formulaires supportés

| Formulaire | Description | Champs |
|------------|-------------|--------|
| **AVS** | Assurance vieillesse et survivants | ~100 |
| **Cardio** | Formulaire de cardiologie | ~60 |
| **LAA** | Accident (loi fédérale) | ~23 |

## Quickstart

### Backend (DGX Spark)

```bash
cd services
cp .env.example .env    # Configurer les variables
docker compose up -d    # Lancer les 4 services
docker compose ps       # Vérifier la santé
```

> Premier lancement : ~10 min (téléchargement et chargement des modèles en VRAM)

### Frontend

```bash
cd frontend
npm install
npm run dev             # Dev server (http://localhost:5173)
```

### Build production

```bash
cd frontend
npm run build           # Output dans dist/
```

## Documentation

| Ressource | Lien |
|-----------|------|
| Architecture détaillée | [docs/wiki/Architecture.md](docs/wiki/Architecture.md) |
| Déploiement Backend | [docs/wiki/Deploiement-Backend-DGX-Spark.md](docs/wiki/Deploiement-Backend-DGX-Spark.md) |
| Déploiement Frontend | [docs/wiki/Deploiement-Frontend-Cloudflare.md](docs/wiki/Deploiement-Frontend-Cloudflare.md) |
| Pipeline RAG | [docs/wiki/Pipeline-RAG.md](docs/wiki/Pipeline-RAG.md) |
| Templates | [docs/wiki/Templates.md](docs/wiki/Templates.md) |
| Services (détails) | [services/README.md](services/README.md) |

## Structure du projet

```
doctorfill/
├── frontend/                 # Application React + Tauri
│   ├── src/
│   │   ├── App.tsx           # Composant principal (drag & drop, API calls)
│   │   ├── Landing.tsx       # Page d'accueil
│   │   └── components/       # Composants UI (shadcn)
│   └── package.json
├── services/                 # Backend microservices
│   ├── orchestrator/         # Pipeline RAG + remplissage PDF
│   │   ├── app.py            # FastAPI principal
│   │   ├── core/             # Modules (extract, fill, inject, checkbox)
│   │   ├── template/         # Définitions JSON des formulaires
│   │   └── forms/            # Templates PDF vierges
│   ├── marker_ocr/           # Service OCR (marker-pdf)
│   ├── tei/                  # Service Embeddings + Reranking
│   ├── vLLM/                 # Configuration LLM
│   ├── docker-compose.yml    # Orchestration Docker
│   └── .env.example          # Variables d'environnement
├── eval/                     # Framework d'évaluation RAG
│   ├── run_eval.py           # Script d'évaluation
│   ├── generate_docs.py      # Générateur de documents synthétiques
│   └── ground_truth.json     # Vérité terrain (Form_AVS)
└── docs/wiki/                # Documentation wiki
```

## Évaluation RAG

```bash
cd eval
pip install -r requirements.txt

# Générer des documents de test
python generate_docs.py --count 60 --noise 10

# Lancer l'évaluation
python run_eval.py --api http://localhost:8080 --api-key <KEY>
```

Précision actuelle : **84.6%** sur Form_AVS (26 champs) — voir [#21](https://github.com/doctorfill-dev/DoctorFill/issues/21) pour le plan d'amélioration.

## Roadmap

Voir [#18 — Roadmap](https://github.com/doctorfill-dev/DoctorFill/issues/18) et les [milestones](https://github.com/doctorfill-dev/DoctorFill/milestones) pour le planning détaillé.

| Phase | Statut | Échéance |
|-------|--------|----------|
| Phase 0 — Sécurité | ✅ Complété | — |
| Phase 1 — MVP Stable | 🚧 En cours | 25 mars 2026 |
| Phase 2 — RAG Quality | ⏳ Planifié | 8 avril 2026 |
| Phase 3 — Eval & Monitoring | ⏳ Planifié | 22 avril 2026 |
