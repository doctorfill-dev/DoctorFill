# 02 — Architecture Proposée : Full-Context Medical Synthesis

## Principe fondamental

> Au lieu de chercher les informations dans des fragments (RAG), on crée d'abord une **synthèse médicale structurée** de tous les documents, puis on remplit le formulaire à partir de cette synthèse.

---

## Nouveau pipeline en 4 étapes

```
┌─────────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 : OCR (inchangé)                                       │
│  Marker OCR → texte markdown par document                       │
│  Parallèle, 3 concurrent, LRU cache                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 : SYNTHÈSE MÉDICALE GLOBALE (nouveau - clé du système) │
│                                                                 │
│  Si total_tokens < 28 000 :                                     │
│    → LLM lit TOUS les documents d'un coup                       │
│    → Produit un JSON médical structuré                          │
│                                                                 │
│  Si total_tokens >= 28 000 (beaucoup de documents) :            │
│    → Résumé par document (LLM, ~500 tokens/doc)                 │
│    → Fusion des résumés en un seul JSON                         │
│                                                                 │
│  Output JSON : diagnostics[], incapacités[], médecins[],        │
│                traitements[], dates_clés{}, patient{}           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 : EMBEDDING + INDEX (amélioré)                         │
│  Chunks 800 mots (au lieu de 400), overlap 100 mots             │
│  Même pipeline async qu'avant                                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 : REMPLISSAGE HYBRIDE (amélioré)                       │
│                                                                 │
│  Pour chaque champ :                                            │
│    1. Cherche dans la synthèse (source primaire, rapide)        │
│    2. Si non trouvé → RAG fallback (top-20 chunks, reranked)    │
│    3. LLM avec contexte = synthèse + chunks pertinents          │
│       (jusqu'à 28 000 tokens de contexte disponibles)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Structure du JSON de synthèse médicale

```json
{
  "patient": {
    "nom": "...",
    "prenom": "...",
    "date_naissance": "DD.MM.YYYY",
    "numero_avs": "...",
    "adresse": "..."
  },
  "diagnostics": [
    {
      "code_icd": "M54.4",
      "description": "Lumbago avec sciatique",
      "date_diagnostic": "DD.MM.YYYY",
      "document_source": "rapport_neurologie_2024.pdf",
      "medecin": "Dr. Martin",
      "statut": "principal | secondaire | antecedent"
    }
  ],
  "incapacites_travail": [
    {
      "taux": 50,
      "date_debut": "DD.MM.YYYY",
      "date_fin": "DD.MM.YYYY",
      "motif": "...",
      "document_source": "..."
    }
  ],
  "traitements": [
    {
      "type": "medicament | physiotherapie | chirurgie | ...",
      "description": "...",
      "date_debut": "DD.MM.YYYY",
      "date_fin": "DD.MM.YYYY | en cours"
    }
  ],
  "medecins": [
    {
      "nom": "...",
      "specialite": "...",
      "etablissement": "...",
      "role": "traitant | consultant | expert"
    }
  ],
  "dates_cles": {
    "premier_arret": "DD.MM.YYYY",
    "debut_maladie": "DD.MM.YYYY",
    "derniere_consultation": "DD.MM.YYYY"
  },
  "pronostic": "...",
  "canton_traitement": "...",
  "metadata": {
    "nb_documents": 5,
    "documents": ["rapport1.pdf", "..."],
    "date_synthese": "DD.MM.YYYY HH:MM"
  }
}
```

---

## Modifications des paramètres vLLM

```yaml
# docker-compose.yml — AVANT
--max-model-len 8192
--gpu-memory-utilization 0.20

# docker-compose.yml — APRÈS
--max-model-len 32768     # 4x plus de contexte (Qwen2.5-14B supporte 128k)
--gpu-memory-utilization 0.70  # 90 GB sur 128 GB (modèle, KV cache, batching)
```

**Justification** : DGX Spark = 128 GB RAM unifiée. Actuellement on utilise ~40 GB. Passer à 0.70 donne ~90 GB à vLLM, ce qui permet un KV cache bien plus grand et plusieurs synthèses en parallèle.

---

## Modifications du chunking

```python
# AVANT
MAX_WORDS = 400
OVERLAP_WORDS = 50

# APRÈS
MAX_WORDS = 800
OVERLAP_WORDS = 100
```

---

## Modifications du RAG

```python
# AVANT
n_results = min(20, total_chunks)   # retrieval
reranked[:7]                         # context

# APRÈS
n_results = min(30, total_chunks)   # retrieval
reranked[:20]                        # context (avec 32k tokens, on peut se le permettre)
```

---

## Nouveaux fichiers créés

| Fichier | Rôle |
|---|---|
| `services/orchestrator/medical_synthesis.py` | Logique de synthèse médicale (prompt + appel LLM + parse JSON) |
| `services/orchestrator/prompts.py` | Tous les prompts centralisés (synthèse + extraction par champ) |

## Fichiers modifiés

| Fichier | Modifications |
|---|---|
| `services/orchestrator/app.py` | Nouveau pipeline 4 étapes, chunking 800 mots, RAG top-20 |
| `services/docker-compose.yml` | max_model_len 32768, gpu_memory_utilization 0.70 |

---

## Pourquoi ne pas passer à un modèle plus grand ?

Qwen2.5-14B-Instruct-AWQ est déjà excellent pour l'extraction médicale. Le problème n'est pas le modèle — c'est l'architecture du pipeline. Augmenter la fenêtre de contexte (8k → 32k) et ajouter la synthèse préalable résout 95% du problème sans changer de modèle.

Si les résultats restent insuffisants après cette refonte, la prochaine étape serait Qwen2.5-32B-Instruct-AWQ (~35 GB en AWQ, faisable sur le DGX Spark).
