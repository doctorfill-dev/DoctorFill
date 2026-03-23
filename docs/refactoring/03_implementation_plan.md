# 03 — Plan d'Implémentation

> Ce fichier sert de checklist pour suivre l'avancement. Mettre à jour le statut au fur et à mesure.
> Format : ✅ terminé | 🔄 en cours | ⬜ à faire | ❌ bloqué

---

## Phase 1 — Documentation (prerequis)

- ✅ Créer `docs/refactoring/README.md`
- ✅ Créer `docs/refactoring/01_problem_analysis.md`
- ✅ Créer `docs/refactoring/02_proposed_architecture.md`
- ✅ Créer `docs/refactoring/03_implementation_plan.md` (ce fichier)
- ✅ Créer `docs/refactoring/04_model_config.md`

---

## Phase 2 — Configuration infrastructure

### 2.1 Modifier `services/docker-compose.yml`
- ✅ Changer `--max-model-len 8192` → `--max-model-len 32768`
- ✅ Changer `--gpu-memory-utilization 0.20` → `--gpu-memory-utilization 0.70`
- ✅ Ajouter `--max-num-seqs 8` et `--enable-chunked-prefill`

---

## Phase 3 — Nouveaux modules Python

### 3.1 Créer `services/orchestrator/prompts.py`
- ✅ Prompt système pour la synthèse médicale (`SYSTEM_PROMPT_SYNTHESIS`)
- ✅ Prompt utilisateur pour la synthèse (`build_synthesis_prompt(docs_text)`)
- ✅ Prompt pour synthèse par document (`build_per_doc_summary_prompt(doc_text, doc_name)`)
- ✅ Prompt pour fusion des résumés (`build_merge_summaries_prompt(summaries)`)
- ✅ Prompt pour extraction de champ avec synthèse (`build_field_extraction_prompt(field, synthesis_json, chunks)`)
- ✅ Garder le prompt d'extraction actuel comme fallback (`SYSTEM_PROMPT_EXTRACT`)

### 3.2 Créer `services/orchestrator/medical_synthesis.py`
- ✅ Fonction `estimate_tokens(text)` — estimation rapide (len/4)
- ✅ Fonction `_synthesize_direct(all_docs_text, ...)` — appel LLM unique si < 28k tokens
- ✅ Fonction `_summarize_single_doc(doc_text, doc_name, ...)` — résumé d'un document
- ✅ Fonction `_merge_summaries(summaries, ...)` — fusion des résumés
- ✅ Fonction `run_medical_synthesis(ocr_results, vllm_url, model_name)` — orchestration
- ✅ Gestion des erreurs : si la synthèse échoue, retourner `None` (pipeline continue)

---

## Phase 4 — Refactoring `services/orchestrator/app.py`

### 4.1 Chunking
- ✅ Modifier `MAX_WORDS` de 400 à 800
- ✅ Modifier `OVERLAP_WORDS` de 50 à 100

### 4.2 RAG
- ✅ Modifier `n_results` de `min(20, ...)` à `min(30, ...)`
- ✅ Modifier `reranked[:7]` à `reranked[:20]`

### 4.3 Nouveau pipeline
- ✅ Importer `medical_synthesis.run_medical_synthesis` et prompts
- ✅ Dans `run_pipeline_task()` : après l'étape OCR+embed, appeler `run_medical_synthesis()`
- ✅ Passer la synthèse à `extract_field_vllm()` comme paramètre optionnel
- ✅ Dans `extract_field_vllm()` : contexte = synthèse JSON + chunks reranked

### 4.4 Mise à jour des statuts
- ✅ Ajouter un message de statut `"synthesizing"` entre embed et extract
- ✅ Logger le temps de synthèse dans les timings et le summary

### 4.5 Debug endpoint
- ✅ Exposer la synthèse médicale dans `/debug/{job_id}`

---

## Phase 5 — Déploiement sur spark-a031

- ⬜ `git push` des modifications sur la branche courante
- ⬜ SSH sur spark-a031 : `git pull`
- ⬜ `docker compose build orchestrator`
- ⬜ `docker compose down && docker compose up -d`
- ⬜ Vérifier que vLLM démarre bien avec les nouveaux paramètres (peut prendre 5-10 min)
- ⬜ Tester avec un cas simple (1 document)
- ⬜ Tester avec un cas complexe (10+ documents)

---

## Points de vigilance

1. **Temps de synthèse** : avec 32k tokens de contexte, la synthèse peut prendre 30-60 secondes. Le job_timeout global devra peut-être être augmenté (actuellement 120 secondes dans app.py).

2. **Mémoire GPU au démarrage de vLLM** : avec gpu_memory_utilization=0.70, vLLM va pré-allouer ~90 GB de KV cache au démarrage. Le démarrage du conteneur sera plus long (~5 min). C'est normal.

3. **Si la synthèse retourne un JSON invalide** : le code doit détecter cela et tomber sur le RAG pur (fallback). Ne jamais crasher le pipeline entier à cause d'une synthèse ratée.

4. **Ordre des documents** : dans la synthèse, toujours mentionner le `document_source` pour que le LLM sache d'où vient chaque information.

---

## Comment reprendre ce travail après interruption

1. Lire `01_problem_analysis.md` pour comprendre les causes racines
2. Lire `02_proposed_architecture.md` pour comprendre la solution
3. Revenir sur ce fichier et regarder les ✅ / ⬜ pour savoir où en est l'implémentation
4. Reprendre à la première tâche `⬜`
5. Le code source est dans `services/orchestrator/app.py` (pipeline principal) et les nouveaux fichiers `prompts.py` / `medical_synthesis.py`
