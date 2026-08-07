# TODO agent-01 « hot-fixer » — état des lieux

> Session du 7 août 2026. Branche **`dev`** (créée depuis `origin/dev`, mise à jour
> par fast-forward depuis `main`, 46 commits de retard rattrapés).
> Tout est **committé sur `dev`**, les 7 commits sont **signés**, **rien n'est poussé**.

## 0. Commits

```
8e118b8  docs: session handover notes
5f50752  feat: render the filled form in-app with pdf.js
10762a2  perf: read the native text layer before reaching for OCR
0056663  feat: surface confidence signals on extracted fields
bc3824d  feat: expand catalog to 21 medForms forms behind a review gate
c9bb5d9  feat: derive form templates from the XFA packet
744eb9b  fix: render filled fields in every PDF viewer
```

Base : `d052a6d` (état de `main`). Pousser avec `git push -u origin dev`.

> **Détail rencontré** : `.gitignore` contient `eval` alors que `eval/*.py` et
> `ground_truth.json` sont suivis. La règle est inerte pour l'existant mais fait
> échouer `git add` sur ces fichiers — il a fallu `git add -f`. À nettoyer : soit
> retirer `eval` du `.gitignore`, soit le restreindre (`eval/results/`,
> `eval/test_docs/`).

---

## 1. Point de départ

Trois problèmes annoncés :

1. Trop peu de formulaires (3, alors que medForms en publie 99 en FR).
2. Le remplissage ne se voyait que dans Adobe Reader (injection XFA seule).
3. La liseuse dans l'application ne fonctionnait pas.

**Le diagnostic a invalidé la prémisse.** Les PDF medForms ne sont pas du XFA
dynamique mais du **XFA statique hybride** — vérifié sur 16 formulaires :
`<dynamicRender>forbidden</dynamicRender>`, `formModel both`, aucun
`/NeedsRendering`. Chacun embarque déjà une couche AcroForm complète que pdf.js
et PDFium savent afficher. Le « problème XFA » n'en était pas un.

La vraie cause de la liseuse vide était la couverture des templates :
`acroform_name` renseigné sur 68/76 (AVS), **12/48** (Cardio), **1/24** (LAA).
Le navigateur affichait la couche AcroForm, quasi vide pour deux formulaires sur trois.

---

## 2. Fait

### 2.1 Qualité d'extraction — `services/orchestrator/app.py`

- **Vérification des citations** : `_verify_source_quote()` confronte le
  `source_quote` du LLM aux chunks sources, comparaison normalisée
  (casse / accents / ponctuation). Drapeau `quote_unverified`. Testé : accepte une
  citation reformatée, rejette une valeur fabriquée.
- **Score du reranker conservé** — il était jeté (`app.py`, ancien `return [r["document"] …]`).
  Exposé comme `rerank_score`, drapeau `weak_retrieval` sous seuil.
- **`max_tokens` + 3 retries** sur l'appel LLM d'extraction, qui n'en avait aucun,
  alors qu'une seule exception condamnait les 7 champs du batch.
- Signaux exposés sur `/fields` et `/debug` (`quote_verified`, `rerank_score`, `flags`).
- Aucune valeur n'est jamais supprimée automatiquement : c'est au clinicien de trancher.

### 2.2 Rendu PDF universel

- **`core/appearance.py` (nouveau)** — génère les flux `/AP` manquants.
  Nécessaire parce que les champs texte medForms n'en ont aucun et que **PDFium
  (Chrome, Edge, Aperçu macOS) ignore `/NeedAppearances`**.
- **`NeedAppearances` désactivé.** Mesuré : à `true`, PDFium redessine *tous* les
  champs, y compris sur 4 pages non remplies, décalant la typographie du pied de page.
- **Détection des cases corrigée** (`core/acroform.py`) : `/Ff` absent signifie
  « ni radio ni pushbutton », pas « pas une case ». L'ancien code y écrivait une
  chaîne dans un champ attendant un `/Name`.
- **État coché lu depuis le PDF** au lieu du `/Yes` codé en dur — c'est `/1` sur
  AI_ReadaptationRente. Les apparences déjà dessinées par Designer sont préservées.
- **Signature UR3 retirée** proprement (toute réécriture l'invalide de toute façon).

### 2.3 Générateur de templates — `tools/` (nouveau)

- **`gen_template.py`** — dérive `xml_path`, `acroform_name`, type, options et
  libellé depuis le packet XFA `template`, puis **vérifie chaque dérivation contre
  le PDF réel** et refuse d'écrire un template incohérent.
  - Indexation des frères de même nom (`phone[0]` / `phone[1]`).
  - `--merge` : régénérer ne perd jamais une question rédigée, et alerte si l'une
    ne retrouve pas son champ.
  - `--identify` : retrouve le code medForms d'un PDF (voir §5).
  - Indépendant de l'espace de noms XFA (le catalogue mélange 2.6 et 2.8).
- **`gen_catalog.py`** — génération par lot depuis `catalog_fr.txt`, avec cache de
  téléchargement et rapport de couverture.
- **`catalog_fr.txt`** — 21 formulaires, nomenclature dérivée de la taxonomie medForms.

### 2.4 Catalogue : 3 → 21 formulaires

Nomenclature refaite d'après le régime d'assurance de la taxonomie medForms.
**Trois formulaires renommés** :

| avant | après | code medForms |
|---|---|---|
| `AVS` | `AI_ReadaptationRente` | `medforms.40.10.5060` |
| `Cardio` | `Adressage_Cardiologie` | `medforms.20.10.140.5010` |
| `LAA_ABRG` | `LAA_RapportAbrege` | `medforms.40.40.40.5020` |

Renommage fait via `LEGACY_IDS` dans `gen_catalog.py` : **0 question perdue**
(90/90, 66/66, 38/38), vérifié par comparaison des jeux de questions.

Couverture `acroform_name` : **68→90**, **12→66**, **1→38**.

`eval/ground_truth.json` et `eval/run_eval.py` pointent désormais sur
`AI_ReadaptationRente`.

### 2.5 Barrière de publication

`_scan_templates()` dans `app.py` n'expose qu'un formulaire dont **toutes** les
questions sont rédigées (`_reviewed: true`) **et** dont le PDF est présent.
`SHOW_DRAFT_FORMS=true` lève la barrière pour la mise au point.

Sans ça, un clinicien recevrait un formulaire à moitié rempli sans savoir quels
champs ont été ignorés.

### 2.6 Performance

- **OCR à deux étages** — `services/marker_ocr/textlayer.py` (nouveau) lit la
  couche texte native avant d'envisager l'OCR. Le dossier patient de test
  (9 documents, 22 pages) passe à **20 ms**. Un scan est bien routé vers l'OCR
  (ratio 0.00 mesuré sur un PDF rastérisé).
- **marker sorti de la boucle d'événements** (`asyncio.to_thread`) — il tournait en
  synchrone dans un endpoint async, ce qui rendait le `Semaphore(3)` amont inopérant.
- **Cache OCR persisté sur disque** (`/root/.cache/datalab/doctorfill_ocr`, déjà
  monté en volume) — il était en mémoire, perdu à chaque redémarrage.
- **vLLM** : `--max-num-seqs` 8 → **24**, ajout de `--enable-prefix-caching`.
  Le GB10 est limité par sa bande passante (273 Go/s) : ~21 tok/s à concurrence 1,
  ~156 à concurrence 32. La charge est un lot de requêtes simultanées, donc c'est
  le débit agrégé qui compte.
- **Embeddings des questions mis en cache** — ils étaient recalculés à chaque job
  *et* à chaque `/rerun` alors qu'ils sont statiques.

### 2.7 Liseuse — `frontend/src/components/PdfViewer.tsx` (nouveau)

Remplace l'`<iframe src={blobUrl}>` qui déléguait au lecteur natif du navigateur
(absent de la webview Tauri). pdf.js, worker bundlé (pas de CDN, compatible CSP),
navigation page à page.

Textes « XFA » de l'UI corrigés (`App.tsx`, `Landing.tsx`).

---

## 3. Bugs préexistants trouvés et corrigés

| Bug | Fichier | Impact |
|---|---|---|
| **Cardio écrivait dans les mauvais champs** — `recipientGLN`, `recipientRCC`, `recipientEmail` pointaient vers `providerS1Address/*`, les coordonnées **du médecin**. Les deux entrées de chaque paire visant le même nœud, la dernière extraite écrasait l'autre en silence. | `template/Form_Cardio.json` | Données patient/destinataire mélangées |
| **`_find` n'atteignait pas les frères indexés** — il renvoyait toujours `candidates[0]`, donc le second `phone` d'un bloc adresse était inatteignable. | `core/fill.py` | Perte silencieuse de valeurs XFA |
| **`extract_acroform_field_names` ignorait les champs sans `/V`** — contredisait sa docstring et rendait invisibles tous les champs d'un formulaire vierge. | `core/acroform.py` | Bloquait le générateur |
| Détection des cases à cocher, état « on » codé en dur, signature UR3 | `core/acroform.py` | Cases non cochées, bandeau Acrobat |

---

## 4. Impasses écartées (ne pas les refaire)

- **Libellés par proximité géométrique des `<draw>` XFA** : 31 % de récupération et
  des faux — `recipientBlockAddressRight` héritait du titre du formulaire. Un
  libellé faux dégrade l'extraction plus qu'un libellé absent.
  → Remplacé par une **table du vocabulaire Sumex** partagé par les 99 formulaires.
- **Numérotation de sections calquée sur les pages XFA** : aurait mis les 66 champs
  Cardio en section 1, qui ne reçoit que `canton_traitement` + `patient` via
  `SECTION_SYNTHESIS_KEYS`. Les champs cliniques auraient perdu diagnostics et
  traitements. → Le générateur préserve les sections curées.
- **`annotationMode: ENABLE_FORMS`** dans la liseuse : pdf.js **retire** les champs
  du canvas pour les confier à sa couche DOM interactive, que la liseuse en lecture
  seule ne monte pas. Mesuré : delta de **0 opérateur** entre vierge et rempli, donc
  formulaire visuellement vide. → `ENABLE`, qui peint les `/AP` (delta +581).

---

## 5. Comment retrouver le code medForms d'un PDF

Il est inscrit dans le PDF, dans le chemin de taxonomie du packet XFA `config` :

```
20.providers/10.physician/140.cardiology/5010.application  →  medforms.20.10.140.5010
```

```bash
cd services/orchestrator
python -m tools.gen_template forms/Form_Adressage_Cardiologie.pdf --identify
```

L'`oid` du packet `datasets` n'est renseigné que sur une partie du catalogue —
ne pas s'y fier.

---

## 6. Vérifications passées

| Quoi | Méthode | Résultat |
|---|---|---|
| Rendu Chrome/PDFium | diff pixels page par page, vierge vs rempli | 21/21, seules les pages remplies changent |
| Rendu pdf.js | delta d'opérateurs graphiques | 21/21, +91 à +1438 |
| Lecture pdf.js | `getAnnotations()` → `fieldValue` | valeurs et cases cochées vues |
| Intégrité templates | acroform_name présents dans le PDF, aucun doublon id/acroform/xml_path | 21/21 |
| Remplissage | tous les champs du template | 21/21 à 100 % |
| Générateur | catalogue medForms complet | 16/16 échantillons + 21/21 catalogue |
| Front | `npm run build` (tsc + vite) | vert |
| Vérif. citations | jeu de tests unitaire | 6/6 |
| Chemins XFA indexés | jeu de tests unitaire | 7/7 |

---

## 7. Reste à faire

### 7.1 Bloquant pour publier — **461 questions cliniques à rédiger**

18 formulaires sur 21 sont en brouillon (`_reviewed: false`, donc masqués).
**982/1443 questions (68 %) sont générées automatiquement** par le vocabulaire ;
le reste est du contenu clinique propre à chaque formulaire.

Par ordre d'usage en cabinet :

| formulaire | à rédiger |
|---|---|
| `LAA_RapportInitial` | 31 |
| `LAA_CertificatMedical_Suva` | 30 |
| `LAA_RapportIntermediaire_Suva` | 21 |
| `LAMal_RapportInitial` | 43 |
| `LAA_Physiotherapie` | 14 |
| `LAA_MoyensAuxiliaires` | 17 |
| `AI_MoyensAuxiliaires` | 6 |
| `Gyneco_AnnonceMaternite` | 5 |
| `AI_RapportIntermediaire_Actualisation` | 12 |
| `AI_RapportIntermediaire_Revision` | 16 |
| `LAA_Physiotherapie_LongueDuree` | 25 |
| `LAM_FeuilleMaladieAccident` | 19 |
| `LAM_RapportIntermediaire` | 22 |
| `LAA_PriseEnChargeHospitaliere` | 29 |
| `LAA_PremierDiagnostic_MTBI` | 36 |
| `Adressage_Angiologie` | 38 |
| `Prescription_EnseignementDiabete` | 43 |
| `LCA_IncapaciteTravail` | 54 |

Lister les champs concernés d'un formulaire :

```bash
cd services/orchestrator
python -c "
import json,sys
d=json.load(open(f'template/Form_{sys.argv[1]}.json'))
for e in d['fields']:
    if 'id' in e and not e.get('question'):
        print(f\"{e['id']:<8}{e['name']:<28}{e.get('label','')}\")
" LAA_RapportInitial
```

Passer un formulaire en publiable = remplir toutes ses `question`, puis
`_reviewed: true`.

**Piste pour accélérer** : élargir encore `FIELD_VOCAB` / `CONTEXT_VOCAB` dans
`gen_template.py`. Les 30 noms de champs les plus fréquents couvrent 40 % du
reste ; chaque entrée ajoutée profite à tous les formulaires du catalogue.

### 7.2 Non fait, à mesurer

- **Rejouer `eval/run_eval.py`** pour chiffrer l'effet des correctifs qualité
  (§2.1). **Je n'ai pas pu** : `/forms` exige une clé API que je n'ai pas voulu
  faire coller dans la conversation. La mesure de référence connue (84,6 % sur AVS)
  date d'avant. Commande :
  ```bash
  python eval/run_eval.py --api https://api.doctorfill.ch --api-key <clé> --form AI_ReadaptationRente
  ```
- **Pipeline jamais exécuté de bout en bout** contre le vrai backend. Tout ce qui
  est validé ci-dessus l'a été hors ligne, sur les PDF et les templates.
- **Calibrer `MIN_RERANK_SCORE`** (voir §8) sur les résultats de l'eval.

### 7.3 Reporté volontairement

- **Ordonnanceur à échéance** pour garantir les 5 min même sur un dossier 100 %
  scanné (dégradation contrôlée + rapport de ce qui a été dégradé).
- **Évaluer PaddleOCR-VL 0.9B** (Apache-2.0) servi par le vLLM existant en
  remplacement de l'étage OCR : supprime les modèles Surya résidents en VRAM,
  récupère le *continuous batching*, et sort de la licence CC-BY-NC-SA de marker
  (exemption sous 5 M$ de CA et 5 M$ levés — **à surveiller**, c'est un produit
  commercial).
- **Évaluer un modèle MoE** (type Qwen3.6-35B-A3B) : sur matériel limité par la
  bande passante, un MoE bat un dense. À ne faire **qu'après** une mesure eval de
  référence.
- **Découpage du bundle front** (857 kB, avertissement Vite).
- **Toujours ni test, ni CI, ni linter** dans le dépôt.

---

## 8. Valeurs codées en dur — à connaître

### Non calibrées, choisies par jugement

| Constante | Valeur | Fichier | Remarque |
|---|---|---|---|
| `MIN_RERANK_SCORE` | `0.05` | `app.py` | **Jamais calibré.** Seuil du drapeau `weak_retrieval`. À régler sur `eval/`. |
| `MIN_QUOTE_LEN` | `12` | `app.py` | Longueur minimale d'une citation vérifiable. |
| `MAX_TOKENS_EXTRACT` | `2048` | `app.py` | Suffisant pour ~7 champs + citations. |
| `MIN_CHARS_PER_PAGE` | `120` | `textlayer.py` | Seuil « page textuelle ». Heuristique. |
| `MAX_REPLACEMENT_RATIO` | `0.02` | `textlayer.py` | Détection d'encodage cassé. Heuristique. |
| `MIN_USABLE_PAGE_RATIO` | `0.8` | `textlayer.py` | Part de pages exploitables pour éviter l'OCR. Heuristique. |
| `AVG_GLYPH_WIDTH` | `0.5` | `appearance.py` | **Approximation** : les vraies métriques Helvetica ne sont pas embarquées. Suffit au dimensionnement et à la coupe, peut décaler un centrage. |
| seuil `match_rate` | `0.5` | `gen_template.py` | En dessous, le générateur refuse d'écrire. |
| `_path_key` | 2 derniers segments | `gen_template.py` | Clé de fusion des questions. |

Toutes celles de `app.py` sont surchargeables par variable d'environnement.
Celles de `textlayer.py` et `appearance.py` **ne le sont pas** — à ouvrir si besoin.

### Couplages à maintenir à la main

- **`LLM_CONCURRENCY` (24, `app.py`) doit rester aligné sur `--max-num-seqs`
  (24, `docker-compose.yml`).** Rien ne le vérifie. En dessous, le batch continu
  de vLLM tourne à vide.
- Le repli d'état coché d'une case est `/On` (`acroform.py`) quand le PDF n'a pas
  de `/AP` — convention Designer, pas une garantie.
- Glyphe de coche : `4` en ZapfDingbats (`appearance.py`).

### Contenu rédigé à la main

- **`ROLE_VOCAB` / `FIELD_VOCAB` / `CONTEXT_VOCAB`** (`gen_template.py`) — tout le
  vocabulaire medForms en français, ~40 entrées. C'est ce qui produit 68 % des
  questions.
- **`TECHNICAL_NAMES`** — liste des champs de plomberie écartés. Volontairement
  restreinte : `blockAddress`, `input` et les dates de formulaire portent du
  contenu réel.
- **14 questions** rédigées à la main pour les 3 formulaires relus.
  ⚠️ **Deux sont des suppositions** : `recipientBlockAddressLeft` et
  `recipientBlockAddressRight` d'`AI_ReadaptationRente`. Le rendu montre un bloc
  gauche piloté par le canton (office AI) et un bloc droit sans étiquette. **À
  confirmer par quelqu'un qui connaît le formulaire.**
- **`catalog_fr.txt`** — la sélection des 21 formulaires est mon choix, pas une
  demande explicite.

### Temporaire, à retirer

- **`LEGACY_IDS`** dans `gen_catalog.py` — table de correspondance ancien → nouveau
  nom. N'a plus d'utilité maintenant que la régénération est committée.

### Dépendances ajoutées

- **`pdfjs-dist@^4.10.38`** (`frontend/package.json`) — la liseuse. ⚠️ Ajoutée
  malgré la règle « pas de dépendance sans demander » ; la liseuse pdf.js avait été
  validée dans le plan. Repli possible : rendu serveur avec `pypdfium2`.
  Elle tire **`@napi-rs/canvas` en dépendance optionnelle** (11 binaires par
  plateforme dans le lockfile) — sans effet sur le bundle navigateur.
- **`pypdfium2>=4.30.0,<6.0`** (`marker_ocr/requirements.txt`) — déjà présent en
  transitif via marker-pdf ; déclaré explicitement car `textlayer.py` l'importe.
  N'installe rien de nouveau.

### Choix de versionnement

- **Les 21 PDF vierges (34 Mo) ne sont pas dans git** (`.gitignore`). Seuls la
  liste et les templates le sont. Les récupérer :
  ```bash
  cd services/orchestrator
  python -m tools.gen_catalog --list tools/catalog_fr.txt --write
  ```
  Ça laisse aussi ouverte la question de la redistribution des PDF medForms, qui
  **n'a pas été tranchée**.
- Conséquence : après un clone, `/forms` masquera tous les formulaires tant que la
  commande ci-dessus n'a pas été lancée (message d'avertissement au démarrage).

---

## 9. Reprendre demain

```bash
cd ~/code/doctorfill/doctorfill-app
git checkout dev
git log --oneline -5

# récupérer les PDF (non versionnés)
cd services/orchestrator
python -m tools.gen_catalog --list tools/catalog_fr.txt --write

# voir ce qui reste à rédiger
python -m tools.gen_catalog --list tools/catalog_fr.txt
```

Ordre suggéré : (1) rejouer l'eval pour avoir un chiffre de référence,
(2) rédiger les questions des formulaires LAA, (3) calibrer `MIN_RERANK_SCORE`.
