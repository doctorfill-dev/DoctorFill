# 01 — Analyse des Problèmes

## Résumé des symptômes utilisateurs

- L'application ignore la plupart des diagnostics quand il y en a >10
- Les informations retournées ne sont pas les plus pertinentes
- Pas d'erreur visible côté utilisateur (le formulaire est rempli, mais mal)

---

## Cause Racine #1 — Bottleneck critique : 7 chunks par champ

**Fichier** : `services/orchestrator/app.py`, fonction `extract_field_rag()`

```python
# Ligne ~227 (version actuelle)
context = "\n---\n".join([r["document"] for r in reranked[:7]])
```

**Problème** : Après retrieval (top-20) et reranking, seuls les 7 meilleurs chunks sont passés au LLM.

**Impact** :
- Un diagnostic médical typique occupe 2-3 chunks (400 mots max / chunk)
- Avec 10 diagnostics → besoin de ~30 chunks minimum
- Les diagnostics situés en dehors du top-7 sont complètement ignorés
- **Aucune erreur n'est levée** : le LLM répond avec ce qu'il voit, le reste est perdu silencieusement

---

## Cause Racine #2 — RAG indépendant par champ, sans vue globale

**Fichier** : `services/orchestrator/app.py`, fonction `run_pipeline_task()`

```python
# Chaque champ lance son propre RAG de manière isolée
tasks = [extract_field_rag(field, chroma_col, job_id) for field in form_fields]
results = await asyncio.gather(*tasks)
```

**Problème** : 95 appels RAG+LLM indépendants. Aucune étape ne crée une vision unifiée du patient.

**Impact** :
- Le LLM ne peut pas synthétiser ("liste TOUS les diagnostics") car il ne voit qu'un fragment
- Incohérences entre champs : le même diagnostic peut être mentionné différemment selon le chunk récupéré
- Les informations temporelles (progression de l'incapacité sur plusieurs mois) nécessitent de voir TOUS les documents ensemble

---

## Cause Racine #3 — Fenêtre de contexte artificielle ment bridée

**Fichier** : `services/docker-compose.yml`

```yaml
command: >
  --model Qwen/Qwen2.5-14B-Instruct-AWQ
  --max-model-len 8192          # ← Qwen2.5-14B supporte 128k tokens nativement !
  --gpu-memory-utilization 0.20 # ← Sur 128 GB RAM unifiée = ~25 GB seulement
```

**Problème** : On utilise 0.20 d'utilisation GPU sur un DGX Spark avec 128 GB de RAM unifiée. Le modèle est limité à 8192 tokens alors qu'il supporte 128k.

**Impact** :
- Même si on passe plus de chunks, le LLM ne peut pas les traiter (trop de tokens)
- La synthèse médicale de 10 documents (~50k tokens) est impossible dans cette config
- Ressources largement sous-utilisées (on tourne à ~40 GB sur 128 GB disponibles)

---

## Cause Racine #4 — Chunking trop agressif

**Fichier** : `services/orchestrator/app.py`, fonction `markdown_semantic_chunking()`

```python
MAX_WORDS = 400
OVERLAP_WORDS = 50
```

**Problème** : 400 mots max par chunk. Un rapport d'expertise médicale avec 15 diagnostics ICD-10, dates, sévérités et traitements associés est découpé en 5-8 chunks qui ne se retrouvent jamais tous dans le contexte simultanément.

**Impact** :
- La liste de diagnostics est fragmentée
- Les associations diagnostic ↔ traitement ↔ date sont perdues lors du découpage
- Le reranking classe chaque fragment indépendamment, les fragments "moins bons" sont éliminés

---

## Cause Racine #5 — Aucune étape de synthèse médicale préalable

**Problème** : Le pipeline va directement de OCR → chunks → remplissage champ par champ. Il n'y a aucune étape qui :
- Extrait TOUS les diagnostics de TOUS les documents
- Crée une chronologie médicale unifiée
- Résout les contradictions entre documents (ex: deux rapports avec des dates différentes)
- Identifie le document le plus récent pour chaque information

---

## Tableau de synthèse des problèmes

| # | Problème | Sévérité | Localisation | Impact utilisateur |
|---|---|---|---|---|
| 1 | Top-7 chunks seulement | **Critique** | `app.py` L.227 | Diagnostics manquants |
| 2 | RAG indépendant par champ | **Critique** | `app.py` pipeline | Pas de vue globale |
| 3 | max_model_len = 8192 | **Élevé** | `docker-compose.yml` | Contexte insuffisant |
| 4 | Chunks trop petits (400 mots) | **Élevé** | `app.py` chunking | Fragmentation |
| 5 | Pas de synthèse préalable | **Élevé** | Architecture | Informations perdues |

---

## Ce qui fonctionne bien (à garder)

- OCR avec Marker : excellent, markdown structuré, LRU cache efficace
- Modèles BAAI/bge-m3 + bge-reranker-v2-m3 : très bons pour le médical multilingue
- XFA injection : solide, gestion des checkboxes, conversion de types
- Pipeline asynchrone avec semaphores : bonne architecture de concurrence
- Sécurité (validation PDF, sanitisation, XXE protection) : robuste
