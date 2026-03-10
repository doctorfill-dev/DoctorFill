# DoctorFill - Microservice : Orchestrateur Hub

Ce composant est le point d'entrée unique qui coordonne l'OCR, le RAG et le moteur de remplissage de formulaires XFA.

## 🚀 Fonctionnalités Clés

- **Pipeline RAG asynchrone** : Exploite `asyncio` pour envoyer plusieurs requêtes simultanées à vLLM.
- **Moteur de Formulaires XFA** : Extraction, normalisation des checkboxes, et injection de données XML dans des PDF dynamiques.
- **Gestion Hybride** : Supporte les templates manuels (JSON) pour un mapping précis vers les chemins XML (`xml_path`).
- **Architecture non-bloquante** : Traitement des formulaires via tâches en arrière-plan (`BackgroundTasks`) pour éviter les timeouts HTTP.

## 🆕 Changements récents (10.03.2026)

### 🔧 Suppression de l’upload du formulaire vide

Avant :
- Le frontend devait envoyer **le formulaire PDF vide** (`form_file`) avec chaque requête.

Maintenant :
- L’orchestrateur récupère automatiquement le template depuis le dossier local :

```
forms/Form_{form_id}.pdf
```

Cela :
- simplifie l’API
- réduit la taille des requêtes HTTP
- évite les erreurs côté frontend

### ⚡ Passage en architecture asynchrone (Background Tasks)

**Problème initial :**

Le pipeline complet peut prendre **30 à 60 secondes**, ce qui peut provoquer des **timeouts HTTP** (par exemple une erreur **524** derrière un reverse proxy comme Cloudflare).

**Solution :**

- `POST /process-form` **ne bloque plus**
- la requête lance un **job en arrière-plan**
- un `job_id` est retourné immédiatement
- le frontend peut ensuite **poller l’état du traitement** jusqu’à la génération du PDF final

## 🏴‍☠️ Endpoints

### `GET /forms`

Retourne la liste des formulaires disponibles (basé sur le dossier `/template`).

### `POST /process-form`

Initie le traitement d'un formulaire.

**Paramètres :**

- `report_files` (PDF[]) : documents médicaux source
- `form_id` (String) : identifiant du formulaire (ex: `AVS`)

**Retour :**

```json
{
  "job_id": "a3f91c2b"
}
```

### `GET /status/{job_id}`

Retourne l’état courant du traitement.

**Exemple de réponse :**

```json
{
  "status": "processing",
  "message": "🧠 Vectorisation du contexte médical...",
  "progress": 40
}
```

**Statuts possibles :**
- `pending`
- `processing`
- `completed`
- `failed`

### `GET /download/{job_id}`

Permet de télécharger le PDF généré une fois le job terminé.

**Condition :**
- disponible uniquement lorsque le statut est `completed`

## 🔄 Nouveau flux frontend

1. Le frontend envoie les `report_files` et le `form_id` à `POST /process-form`
2. L’API retourne immédiatement un `job_id`
3. Le frontend appelle régulièrement `GET /status/{job_id}`
4. Quand le statut passe à `completed`, le frontend appelle `GET /download/{job_id}`

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

L'orchestrateur consomme principalement de la **CPU** et de la **RAM système** pour :
- la manipulation XML/XFA
- la gestion des fichiers temporaires
- le suivi des jobs en mémoire

Il délègue toute la charge GPU à :
- `vllm`
- `tei`
- `marker_ocr`

## ⚠️ Notes techniques

- L’état des jobs est actuellement stocké **en mémoire** dans un dictionnaire global `JOBS`
- Cette approche est adaptée au **développement** et aux environnements simples
- En production à plus grande échelle, il est recommandé d’utiliser :
  - **Redis**
  - ou une **base de données**
  - ou un vrai système de queue de tâches

- Les fichiers temporaires sont stockés dans :

```
/tmp/{job_id}
```

- Les templates PDF sont attendus dans :

```
forms/
```

- Les définitions JSON des formulaires sont attendues dans :

```
template/
```