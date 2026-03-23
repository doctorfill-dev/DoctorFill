# DoctorFill — Refactoring : Full-Context Medical Synthesis

> **Document de référence** pour la refonte du pipeline de remplissage de formulaires médicaux.
> Objectif : permettre à une IA de reprendre ce travail à n'importe quel point d'interruption.

## Contexte

**Problème signalé par les utilisateurs** : lorsque plusieurs documents médicaux sont déposés (rapports, expertises, etc.), l'application ne prend pas en compte tous les diagnostics (parfois >10) et retourne des informations incomplètes ou non pertinentes.

## Structure de cette documentation

| Fichier | Contenu |
|---|---|
| `01_problem_analysis.md` | Analyse détaillée des causes racines (avec références au code) |
| `02_proposed_architecture.md` | Nouvelle architecture "Full-Context Medical Synthesis" |
| `03_implementation_plan.md` | Checklist d'implémentation pas-à-pas (état d'avancement inclus) |
| `04_model_config.md` | Configuration des modèles recommandée pour DGX Spark |

## TL;DR de la solution

**Avant** : OCR → chunks (400 mots) → RAG indépendant par champ (top-7) → LLM (8k tokens)

**Après** : OCR → **synthèse médicale globale** (LLM lit tout, produit un JSON structuré) → remplissage hybride (synthèse + RAG top-20, 800 mots/chunk, 32k tokens)

## Infrastructure cible

- Serveur : `cutiips@spark-a031`
- Répertoire : `/home/cutiips/doctorfill/services`
- GPU : NVIDIA GB10 (DGX Spark, 128 GB RAM unifiée)
- Tout fonctionne en local, aucune dépendance externe
