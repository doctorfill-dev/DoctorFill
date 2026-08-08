# TODO agent-01 « hot-fixer » — état des lieux

> Sessions des 7-8 août 2026. Branche **`dev`** (créée depuis `origin/dev`, mise à
> jour par fast-forward depuis `main`, 46 commits de retard rattrapés).
> Tout est **committé et poussé sur `origin/dev`**, tous les commits sont **signés**.
>
> **Version `0.2.0`**, affichée dans l'en-tête de l'application et par `/health`.

## 0. Commits

```
2b22d65  feat: complete all 21 forms — every question written
252f2a9  feat: extend the medForms vocabulary from 3 to 7 publishable forms
f64a1bc  feat: surface frontend and backend versions in the app
79e53b2  docs: session handover notes
5f50752  feat: render the filled form in-app with pdf.js
10762a2  perf: read the native text layer before reaching for OCR
0056663  feat: surface confidence signals on extracted fields
bc3824d  feat: expand catalog to 21 medForms forms behind a review gate
c9bb5d9  feat: derive form templates from the XFA packet
744eb9b  fix: render filled fields in every PDF viewer
```

Base : `d052a6d` (état de `main`). `dev` est en avance de 10 commits sur `main`.

> **Détail** : `TODO-agent-01-hot-fixer.md` a été retrouvé supprimé de l'arbre de
> travail (suppression non commitée, d'origine inconnue) et restauré depuis `HEAD`.
> Le contenu committé n'avait pas été touché.

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

Renommage vérifié par comparaison des jeux de questions avant/après :
**0 question perdue** (90/90, 66/66, 38/38).

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

`annotationMode` est `ENABLE`, **délibérément pas `ENABLE_FORMS`** — voir §4.

### 2.8 Versionnage

Le fichier **`VERSION`** à la racine est la source unique. Vite l'inline au build
(`__APP_VERSION__`), l'orchestrateur lit `APP_VERSION` injecté en argument de build
(le fichier est hors du contexte de build Docker) avec repli sur le fichier pour
une exécution locale.

L'en-tête de l'application affiche **`ui vX` et `api vX`**, et passe en ambre
lorsque les deux diffèrent. Les deux composants se déployant séparément (Cloudflare
Pages / DGX Spark), un numéro unique aurait masqué le seul cas qui compte : l'un
des deux en retard. `/health` renvoie aussi le modèle et le nombre de formulaires
exposés.

Build : `APP_VERSION=$(cat ../VERSION) docker compose build` (runbook mis à jour).

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

### 7.1 Formulaires — **terminé**

Les **21 formulaires sont publiables** : 1430 champs, **toutes les questions
rédigées**, `_reviewed: true` partout.

La rédaction a été menée en deux temps. D'abord le vocabulaire : sur les 461
questions initialement manquantes, 307 réutilisaient 63 noms de champs partagés
entre plusieurs formulaires — le catalogue medForms partage bien plus que ses blocs
d'adresse. Décrire ce vocabulaire une fois a couvert 84 % du travail. Ensuite les
240 restantes, écrites à la main : batterie duplex d'angiologie, score de Glasgow
du MTBI, checklist d'enseignement du diabète, évaluation de capacité de travail LCA.

**Conséquence pour la suite** : tout formulaire ajouté au catalogue héritera
automatiquement d'une large part de ses questions. Mesuré sur les échantillons :
médiane autour de 50 % pour un formulaire inconnu, davantage pour les formulaires
d'assureur qui suivent le modèle Sumex de près.

Ajouter un formulaire :

```bash
cd services/orchestrator
# 1. trouver son code medForms
python -m tools.gen_template <fichier.pdf> --identify
# 2. l'ajouter à tools/catalog_fr.txt, puis générer
python -m tools.gen_catalog --list tools/catalog_fr.txt --write
# 3. compléter les questions restantes, puis basculer _reviewed à true
```

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
- **Les 1430 questions** des 21 formulaires — ~240 écrites à la main, le reste
  produit par le vocabulaire. **Aucune n'a été relue par un clinicien.**
  ⚠️ Deux restent des suppositions : `recipientBlockAddressLeft` et
  `recipientBlockAddressRight` (blocs destinataire de l'en-tête, présents sur
  plusieurs formulaires d'assureur). Le rendu montre un bloc gauche piloté par le
  canton et un bloc droit sans étiquette. **À confirmer.**
- **`catalog_fr.txt`** — la sélection des 21 formulaires est mon choix, pas une
  demande explicite.

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

## 9. Reprendre

```bash
cd ~/code/doctorfill/doctorfill-app
git checkout dev && git pull

# 1. récupérer les PDF vierges — indispensable, ils ne sont pas versionnés
cd services/orchestrator
python -m tools.gen_catalog --list tools/catalog_fr.txt --write
# doit afficher : 1430/1430 (100 %), 0 à rédiger, 0 échec

# 2. déployer le backend, version incluse
cd ../ && APP_VERSION=$(cat ../VERSION) docker compose build && docker compose up -d
curl -s http://localhost:8080/health | python3 -m json.tool

# 3. front
cd ../frontend && npm install && npm run build
```

**Le seul travail restant est une mesure, pas du développement.** Rejouer l'eval
donne le premier chiffre de qualité depuis les correctifs (§7.2), et c'est lui qui
permet de calibrer `MIN_RERANK_SCORE` puis d'arbitrer les évolutions reportées
(§7.3 : modèle MoE, OCR par VLM, ordonnanceur à échéance).

Rappel des deux réserves : le pipeline n'a **jamais tourné de bout en bout** contre
le vrai backend, et les 1430 questions n'ont **pas été relues par un clinicien** —
elles sont cohérentes et vérifiées mécaniquement, mais leur pertinence médicale
reste à confirmer. Le champ `_reviewed` marque « toutes les questions écrites », pas
« validées par un médecin » ; c'est une distinction à garder en tête avant une mise
en production.
