# Tests et non-régression

Deux questions différentes, deux dispositifs :

| Question | Où | Quand | Bloque le merge |
|---|---|---|---|
| **Le code fait-il toujours ce qu'il doit ?** — chaque champ de chaque formulaire atteint le PDF, les erreurs sont absorbées, les valeurs normalisées | CI GitLab (`.gitlab-ci.yml`), sans GPU, services simulés | chaque MR et chaque push sur `main`/`dev` | oui, une fois « Pipelines must succeed » activé (voir plus bas) |
| **Le modèle trouve-t-il toujours les bonnes valeurs ?** — un changement de prompt, de modèle, de découpage ou de template ne dégrade pas l'extraction | `eval/regression.py` contre le vrai backend (job `eval` sur le DGX) | à la demande, sur les MR qui touchent l'extraction | par la référence `eval/baseline.json` et la revue |

## 1. CI — à chaque MR

```bash
cd services/orchestrator && pip install -r requirements-dev.txt && python -m pytest tests
cd services/marker_ocr   && python -m pytest tests          # pypdfium2 + pikepdf suffisent
```

| Fichier | Ce qui est garanti |
|---|---|
| `test_catalogue.py` | Invariants des 21 templates : IDs, `xml_path` et `acroform_name` uniques, questions toutes rédigées, options alignées sur leurs valeurs d'export, table cantonale cohérente, chaque lot tient dans la fenêtre du modèle, **aucun formulaire ne perd de champs extraits** (`catalogue_coverage.json`) |
| `test_catalogue_fill.py` | Pour les 21 formulaires, un PDF hybride XFA + AcroForm de même structure (`form_factory.py`) : **chaque champ extrait arrive dans les deux couches**, cases, boutons radio, listes et destinataire cantonal compris |
| `test_eval_dossiers.py` | Les 25 dossiers de `eval/dossiers/` passent **par l'API HTTP** (upload → OCR → synthèse → extraction → `/fields` → `/download`), modèle simulé répondant la vérité terrain : 100 % dans `/fields` et dans le PDF livré, dossier long (extraits) et documents illisibles compris. Le garde-fou qualité lui-même est testé (il note 100 % un modèle parfait, détecte une valeur fausse, une valeur inventée et une non-réponse, sort en erreur sur un job en échec) |
| `test_pipeline.py` | Robustesse : document illisible, panne d'embeddings, de rerank ou de synthèse, re-run, purge des fichiers patients, jeton du chat |
| `test_extraction.py` | Appel LLM : contexte trop long, réponse tronquée, IDs absents, réponse vide, schéma refusé, erreurs 4xx/5xx |
| `test_fields.py` | Préparation des champs et normalisation des valeurs |
| `test_fill.py` | Écriture AcroForm/XFA sur un PDF minimal |
| `marker_ocr/tests/test_textlayer.py` | Aiguillage couche texte native / OCR |

Chaque garde-fou a été vérifié par mutation : réintroduire l'ancien bug (case
« On » écrite « 0 », destinataire cantonal appliqué par nom, cases vierges
exclues) fait échouer la CI.

Le job `orchestrator` échoue aussi sous 70 % de couverture de code.

### Rendre la CI bloquante

Sans ces réglages, GitLab autorise la fusion d'une MR rouge.

- **Settings → Repository → Protected branches** : `main` protégée, *Allowed
  to push* : personne ; les changements passent par une MR.
- **Settings → Merge requests** : cocher *Pipelines must succeed*. Les jobs
  `lint`, `orchestrator`, `marker-ocr` et `frontend` doivent alors passer ;
  `eval`, manuel, ne bloque pas.
- Même page, *Merge method* : *Merge commit with semi-linear history* ou
  *Fast-forward merge* : la branche doit être à jour avec `main`, donc la CI a
  tourné sur le résultat de la fusion.

## 2. Qualité d'extraction — contre le vrai modèle

`eval/truth.py` dérive la vérité terrain des scénarios qui ont généré les
dossiers (patient, médecin, incapacités, diagnostics, accident) : **398 champs
sur 25 dossiers**, chacun vérifié présent dans le texte du dossier.

Un dossier par formulaire du catalogue, plus quatre variantes
(`<formulaire>__<cas>`, voir `eval/dossiers/scenarios_cas.py`) qui forcent un
chemin du pipeline :

| Dossier | Ce qu'il vérifie |
|---|---|
| `LAA_RapportInitial__dossier-long` | ~21 000 tokens, au-delà du mode dossier intégral : recherche vectorielle et synthèse hiérarchique, faits utiles noyés dans sept ans de suivi |
| `LAA_CertificatMedical_Suva__document-illisible` | un scan penché sans couche texte et un PDF tronqué : le job aboutit et les signale |
| `LCA_IncapaciteTravail__periodes` | trois périodes à 50 %, 100 %, 50 %, attestées de la plus récente à la plus ancienne |
| `LAMal_RapportInitial__sans-reponse` | patient retraité sans téléphone, e-mail, employeur ni incapacité : ces champs restent vides |

Le patient neuchâtelois (destinataire cantonal) est celui d'`AI_ReadaptationRente`.
Une variante n'est pas versionnée : `truth.py` la rend depuis son scénario, et
ses PDF dans `eval/results/pdf/` (fpdf2). Pour la lire :
`python eval/gen_dossiers.py --form LCA_IncapaciteTravail__periodes --markdown-only`.

La précision ne voit pas les champs sans valeur attendue. Deux mesures les
couvrent :

- **valeurs inventées** : `truth.derive_absent` liste les champs que le dossier
  laisse vides (166 : périodes d'incapacité au-delà de celles attestées, fax et
  case postale qu'aucun document ne donne, et ce que le scénario déclare absent).
  Toute valeur y est inventée ;
- **non-réponses** (« non mentionné », « N/A », « ... ») : *écrites*, elles
  partent dans le PDF ; *effacées* par la normalisation, elles disent combien
  de champs « remplis » n'étaient que du bruit. Une baisse du nombre de champs
  remplis s'explique ainsi : non-réponses effacées, ou valeurs perdues.

Le script lit aussi **le PDF livré** (pypdf) : chaque champ de la vérité terrain
doit y porter la valeur de `/fields`, et aucune coordonnée ni remarque la chaîne
technique de la table cantonale (`exaddress#@#…`). C'est au remplissage que la
table écrasait l'adresse du patient neuchâtelois : `/fields` restait juste.

```bash
# Sur main, après validation : fixer la référence (à committer)
python eval/regression.py --api http://localhost:8080 --api-key $KEY --update-baseline

# Sur une branche : comparer à la référence
python eval/regression.py --api http://localhost:8080 --api-key $KEY --report report.md
```

Code de sortie : `0` sans régression, `1` en cas de régression, `2` si un
dossier n'a pas pu être traité. Est une régression : un formulaire qui perd
plus d'un champ juste ou gagne plus d'une valeur inventée par rapport à la
référence (bruit de vLLM toléré), un champ en erreur ou une non-réponse écrite
de plus, une précision globale en baisse de plus de 2 points, ou — sans
référence, car le modèle n'y est pour rien — un champ du PDF différent de
`/fields`.
`--min-accuracy 0.85` ajoute un plancher absolu.

Le rapport liste, par dossier, les champs justes, l'écart à la référence,
les valeurs inventées et les non-réponses, et le détail des champs faux
(attendu / obtenu), des valeurs inventées et des non-réponses écrites.
Il donne aussi la durée de chaque étape (OCR et embeddings, synthèse,
extraction, remplissage, attente), que le backend publie dans `/status` : un
dossier anormalement lent s'explique sans aller lire les journaux du serveur.

### Sur le DGX, depuis GitLab

Le job `eval` (bouton *Run job* dans le pipeline d'une MR) lance le même script
sur un runner portant le tag `dgx`, et garde `report.md` et `results.json` en
artefacts. Variables modifiables au lancement : `EVAL_API`, `EVAL_FORMS`.
Prérequis, une fois :

1. enregistrer un runner GitLab sur le DGX (*Settings → CI/CD → Runners →
   New project runner*), avec le tag `dgx` ;
2. créer la variable `DOCTORFILL_API_KEY`, masquée (*Settings → CI/CD →
   Variables*).

Le job est manuel : un runner auto-hébergé ne doit pas exécuter le code de
n'importe quelle MR automatiquement.
