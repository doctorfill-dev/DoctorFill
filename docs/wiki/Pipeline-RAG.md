# Pipeline RAG

## Vue d'ensemble

Le pipeline RAG (Retrieval-Augmented Generation) est le coeur de DoctorFill. Il extrait automatiquement les informations des documents médicaux pour remplir les formulaires.

## Étapes du pipeline

### 1. OCR — Extraction de texte

**Service** : Marker OCR (`:8082`)

- Chaque PDF est envoyé au service Marker OCR
- Sortie : Markdown structuré (headings, tableaux, listes)
- Parallélisation : `asyncio.Semaphore(5)` pour limiter les appels GPU concurrents
- Timeout : 120s par document

### 2. Chunking — Découpage du texte

**Stratégie** : Semi-sémantique

1. **Découpage par headings Markdown** : chaque section `#`, `##`, `###` crée un chunk
2. **Fallback** : si un chunk dépasse 400 mots, il est découpé avec 50 mots de chevauchement

### 3. Embedding — Vectorisation

**Service** : TEI (`:8081`) — Modèle `BAAI/bge-m3`

- Les chunks sont envoyés par batch de 64 pour éviter les timeouts
- Les vecteurs sont stockés dans une collection ChromaDB éphémère (en mémoire)
- Timeout : 120s par batch

### 4. Retrieval — Recherche sémantique

Pour chaque champ du formulaire :

1. **Embedding de la question** : la question du template est vectorisée
2. **Recherche ChromaDB** : `n_results = min(20, nombre_total_de_chunks)`
3. **Reranking** : les 20 résultats sont re-classés par le modèle `BAAI/bge-reranker-v2-m3`
4. **Sélection** : les 7 meilleurs chunks sont conservés

### 5. Extraction LLM

**Service** : vLLM (`:8000`) — Modèle `Qwen/Qwen2.5-14B-Instruct-AWQ`

- Les 7 chunks sélectionnés sont envoyés comme contexte
- Le LLM extrait la valeur selon des règles strictes (prompt système dédié)
- Température : 0.05 (quasi-déterministe)
- Format de réponse : `{"value": "...", "source_quote": "..."}`

### 6. Remplissage PDF

- Les valeurs extraites sont injectées dans le XML/XFA du formulaire PDF
- Le PDF rempli est disponible en téléchargement

## Prompt système

```
Tu es un assistant spécialisé dans l'extraction de données depuis des documents médicaux.
On te fournit des EXTRAITS de rapports et une QUESTION.

RÈGLES STRICTES :
1. Cherche la réponse dans les extraits fournis.
2. Extrais la valeur EXACTE telle qu'elle apparaît dans le texte.
3. Ne réponds "Inconnu" que si l'information est RÉELLEMENT ABSENTE.
4. Réponds UNIQUEMENT en JSON valide.
5. Pour les dates, conserve le format original du document.
6. Pour les noms/prénoms, conserve la casse originale.
```

## Optimisations réalisées

| Paramètre | Avant | Après | Impact |
|-----------|-------|-------|--------|
| MAX_FILES | 10 | 100 | Support de gros dossiers |
| n_results | 5 | min(20, total) | Meilleure couverture |
| reranked | top 3 | top 7 | Plus de contexte au LLM |
| Embedding | 1 appel | Batch de 64 | Pas de timeout |
| OCR | Séquentiel | Parallèle (sem=5) | ~2x plus rapide |
| Température | 0.1 | 0.05 | Réponses plus stables |
| Timeout embed/rerank | 60s | 120s | Pas de timeout sur gros corpus |

## Métriques actuelles

| Métrique | Valeur |
|----------|--------|
| Précision AVS (26 champs) | 84.6% (22/26) |
| Temps de traitement (70 docs) | ~90s |
| Temps de traitement (100 docs) | <5 min (estimé) |

## Problèmes connus

1. **Contamination par bruit** : les documents d'autres patients polluent le retrieval
2. **Confusion d'entités** : patient/médecin/spécialiste mal distingués
3. **Retrieval miss** : certains champs ne trouvent pas leur chunk pertinent

→ Voir issue #21 pour le plan d'amélioration.
