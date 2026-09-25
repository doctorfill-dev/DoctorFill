# Pipeline RAG

## Vue d'ensemble

Le pipeline extrait les informations des documents médicaux d'un dossier pour
remplir un formulaire medForms (XFA statique hybride, couche AcroForm comprise).
Il est piloté par l'orchestrateur (`services/orchestrator/app.py`) et partagé
par le traitement initial et le re-run (`_extract_fields`, `_fill_pdf`).

```
PDF ──► OCR (texte natif, sinon marker) ──► découpage + embeddings (ChromaDB)
                                         └► synthèse médicale (LLM)
                                                   │
        champs du template ──► questions univoques ──► lots ──► LLM (JSON contraint)
                                                                   │
                           normalisation + provenance ◄────────────┘
                                                   │
                                     remplissage XFA + AcroForm
```

## Étapes

### 1. OCR

**Service** : `marker_ocr` (`:8082`). La couche texte native est lue d'abord
(`textlayer.py`, quelques ms/page) ; l'OCR marker n'est lancé que pour les pages
scannées. Résultats mis en cache par empreinte SHA-256.

Un document illisible **n'interrompt plus le job** : il est écarté et signalé
dans `warnings` (`/status`). Reprises proportionnées à la cause : service
injoignable → 5 tentatives espacées ; délai dépassé ou 5xx → une seule reprise ;
4xx → aucune. Si aucun document n'est lisible, le job échoue avec un message
explicite.

### 2. Découpage et embeddings

`extraction.chunk_document` — sections Markdown fusionnées si trop courtes
(< 40 mots), découpées si trop longues (300 mots, chevauchement 50).
**Chaque extrait porte sa source** : `[Source : 03_consultations.pdf — page 2 — Médecin traitant]`.
Embeddings `BAAI/bge-m3` par lots de 64 (TEI `:8081`, reprises sur erreur
transitoire), stockés dans une collection ChromaDB éphémère par job (réutilisée
par le chat et le re-run).

### 3. Synthèse médicale

`medical_synthesis.py` — JSON structuré (patient, diagnostics, incapacités,
traitements, médecins, dates clés). Directe si le dossier tient dans la fenêtre,
hiérarchique sinon (résumé par document, découpé si besoin, puis fusion).
Replis : directe → hiérarchique ; fusion LLM → fusion déterministe. En cas
d'échec complet, l'extraction continue sur les seuls documents.

### 4. Préparation des champs

`core/fields.py` :

- **Champs soumis** : question rédigée, ni `computed` ni `preset` d'éditeur.
  Un `preset` qui n'est que l'**état vierge** du champ (case « /Off », question
  oui/non sur « non », compteur à 0) reste à remplir.
- **Questions univoques** : les occurrences d'une structure répétée reçoivent
  leur contexte — « (Contexte : période d'incapacité de travail n°2 sur 4 — de la
  plus ancienne à la plus récente ; vide s'il n'y en a pas de n°2) ».
- **Lots** : par section, jusqu'à 8 champs ; les occurrences d'une même
  structure restent dans le même lot (jusqu'à 32) pour être réparties sans doublon.

### 5. Contexte du prompt

Deux modes, choisis par job selon un budget en tokens (`extraction.py`) :

| Mode | Quand | Contexte |
|------|-------|----------|
| Dossier intégral | dossier ≤ `FULL_CONTEXT_MAX_TOKENS` (16k) et place dans la fenêtre | texte complet de tous les documents, identique pour tous les lots (préfixe mis en cache par vLLM) |
| Extraits | au-delà | recherche vectorielle (30 candidats) → rerank `bge-reranker-v2-m3` (top 8) → extraits **entrelacés par rang** entre les champs du lot, dans `RAG_CONTEXT_TOKENS` (9k) |

La synthèse est transmise **en entier** à chaque lot, avant les documents.

### 6. Extraction LLM

**Service** : vLLM (`:8000`) — `Qwen/Qwen2.5-14B-Instruct-AWQ`, fenêtre 32k.

- Réponse contrainte par **schéma JSON** (`response_format: json_schema`) : tous
  les IDs sont présents, les listes de choix sont des `enum`. Repli automatique
  sur `json_object` si le serveur refuse le schéma.
- Température 0, `max_tokens` 4096, délai 600 s.
- Reprises sur les seules erreurs transitoires (réseau, délai, 5xx, 429).
- Fenêtre dépassée → contexte réduit de moitié (3 fois au plus) ;
  réponse tronquée → lot scindé ; IDs absents → redemandés une fois.

### 7. Normalisation et provenance

- Valeurs : « non mentionné », « N/A », « ... », exemples de format → vide ;
  dates → `JJ.MM.AAAA` ; oui/non canoniques ; nombres seuls ; sexe `M`/`F`.
  La réponse brute reste dans `raw_value`.
- Provenance (`core/provenance.py`) : la valeur est-elle retrouvable dans les
  documents, et où ? Verdict `verified` / `attested` / `inferred` / `unverified`
  / `not_checkable`, avec document, page et extrait. Pour une réponse choisie
  (oui/non, option de liste), seule la citation compte.

### 8. Remplissage PDF

`core/fields.collect_form_values` construit les valeurs XFA et AcroForm :
extraits, champs calculés, puis destinataire dérivé du canton.
Cases à cocher : état déclaré par le formulaire (`On`/`Off` ou `1`/`0`).
Listes : libellé choisi → valeur d'export, et libellé affiché dans l'apparence.

## Réglages

| Variable | Défaut | Rôle |
|----------|--------|------|
| `LLM_MAX_MODEL_LEN` | 32768 | À aligner sur `--max-model-len` de vLLM |
| `FULL_CONTEXT_MAX_TOKENS` | 16000 | Seuil du mode dossier intégral |
| `RAG_CONTEXT_TOKENS` | 9000 | Budget d'extraits par lot |
| `MAX_TOKENS_EXTRACT` | 4096 | Génération par lot |
| `LLM_TIMEOUT` / `SYNTHESIS_TIMEOUT` | 600 / 900 s | Délais LLM |
| `MAX_BATCH_SIZE` / `MAX_FAMILY_SIZE` | 8 / 32 | Taille des lots |
| `RETRIEVAL_CANDIDATES` / `RETRIEVAL_TOP_K` | 30 / 8 | Retrieval |
| `KEEP_DEBUG_LOGS` | false | Conserver les journaux de debug au-delà du job |

## Tests

```bash
cd services/orchestrator
pip install -r requirements-dev.txt
python -m pytest tests
```

Sans GPU ni service : OCR, TEI et vLLM sont simulés ; le remplissage est vérifié
sur un vrai PDF AcroForm. Exécutés en CI (`.github/workflows/tests.yml`).

## Métriques

| Métrique | Valeur |
|----------|--------|
| Précision AVS (26 champs, avant les changements de septembre 2026) | 84.6% (22/26) |

À remesurer avec `eval/run_eval.py` et `eval/check_grounding.py` sur les
dossiers de `eval/dossiers/`.
