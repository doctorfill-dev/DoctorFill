# DoctorFill - Microservice : Orchestrateur Hub

Ce composant est le point d'entrée unique qui coordonne l'OCR, le RAG et le moteur de remplissage de formulaires XFA.

## 🚀 Fonctionnalités Clés

- **Pipeline RAG asynchrone** : Exploite `asyncio` pour envoyer plusieurs requêtes simultanées à vLLM.
- **Moteur de Formulaires XFA** : Extraction, normalisation des checkboxes, et injection de données XML dans des PDF dynamiques.
- **Gestion Hybride** : Supporte les templates manuels (JSON) pour un mapping précis vers les chemins XML (`xml_path`).

## 🏴‍☠️ Endpoints

- `GET /forms` : Retourne la liste des formulaires disponibles (basé sur le dossier `/template`).
- `POST /process-form` :
    - `report_file` (PDF) : Le document source.
    - `form_file` (PDF) : Le formulaire XFA vide.
    - `form_id` (String) : L'ID du formulaire (ex: `AVS`).
    - **Retour** : Le PDF rempli.

## 🛠️ Installation (DGX Blackwell)

**Build :**
```bash
docker build -t doctorfill/orchestrator:latest .
```

**Run (Network Host recommandé pour dev) :**
```bash
docker run -d \
  --name df-services-orchestrator \
  --network host \
  --env-file ../.env \
  doctorfill/orchestrator:latest
```

## 🔬 Monitoring des ressources
L'orchestrateur consomme principalement de la CPU et de la RAM système pour la manipulation XML. Il délègue toute la charge GPU à `vllm` et `tei`.