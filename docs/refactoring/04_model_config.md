# 04 — Configuration des Modèles

## Infrastructure DGX Spark (spark-a031)

| Ressource | Valeur |
|---|---|
| GPU | NVIDIA GB10 (architecture Grace Blackwell) |
| RAM unifiée (CPU+GPU partagée) | 128 GB |
| RAM actuellement utilisée | ~51 GB |
| Stockage `/home` | 3.7 TB (197 GB utilisés) |

---

## Consommation actuelle des services

| Service | Modèle | VRAM estimée |
|---|---|---|
| marker_ocr | Surya + Texify | ~3.8 GB |
| tei | BAAI/bge-m3 + bge-reranker-v2-m3 | ~4.5 GB |
| vllm | Qwen2.5-14B-Instruct-AWQ | ~20 GB (0.20 utilization) |
| **Total actuel** | | **~28 GB** |

---

## Configuration vLLM recommandée (après refactoring)

```yaml
# services/docker-compose.yml
vllm:
  command: >
    --model Qwen/Qwen2.5-14B-Instruct-AWQ
    --max-model-len 32768
    --gpu-memory-utilization 0.70
    --max-num-seqs 8
    --enable-chunked-prefill
    --quantization awq
```

**Justification de chaque paramètre** :
- `--max-model-len 32768` : 32k tokens = environ 24 000 mots = ~40 rapports médicaux typiques. Le modèle supporte 128k nativement, mais 32k est un bon compromis mémoire/performance.
- `--gpu-memory-utilization 0.70` : ~90 GB alloués à vLLM. Poids du modèle AWQ ~8 GB + KV cache ~80 GB. Laisse ~38 GB pour le reste du système.
- `--max-num-seqs 8` : 8 séquences en parallèle max (réduit depuis la valeur par défaut pour éviter OOM avec les longues séquences).
- `--enable-chunked-prefill` : essentiel pour les longs contextes, évite les pics mémoire lors du prefill.
- `--quantization awq` : garde la quantization AWQ pour réduire l'empreinte mémoire des poids.

---

## Consommation après refactoring

| Service | VRAM estimée |
|---|---|
| marker_ocr | ~3.8 GB |
| tei | ~4.5 GB |
| vllm (0.70) | ~90 GB |
| **Total** | **~98 GB** |
| **Marge** | **~30 GB** |

---

## Pourquoi garder Qwen2.5-14B-AWQ ?

Le problème n'est pas la qualité du modèle mais l'architecture du pipeline. Qwen2.5-14B-Instruct est excellent pour l'extraction médicale. En lui donnant 32k tokens de contexte au lieu de 8k, on résout le problème principal.

---

## Option de mise à niveau future (si résultats insuffisants)

Si après la refonte les résultats sont encore insuffisants, la prochaine étape serait :

**Qwen2.5-32B-Instruct-AWQ**
- Poids AWQ : ~18 GB
- Avec 0.80 utilization → ~100 GB alloués → KV cache ~82 GB
- Contexte : 32k tokens (idem)
- Commande de téléchargement (sur spark-a031) :
  ```bash
  docker exec df-services-vllm huggingface-cli download Qwen/Qwen2.5-32B-Instruct-AWQ
  ```
- Modifier `VLLM_MODEL_NAME=Qwen/Qwen2.5-32B-Instruct-AWQ` dans `.env`

---

## Modèles TEI (embeddings / reranking) — inchangés

Les modèles BAAI/bge-m3 et BAAI/bge-reranker-v2-m3 sont excellents pour le médical multilingue (FR/DE/IT/EN). Pas de changement recommandé.

---

## Modèle OCR (Marker) — inchangé

Marker avec Surya+Texify est optimal pour les PDFs médicaux (tableaux, en-têtes, listes). Pas de changement recommandé.
