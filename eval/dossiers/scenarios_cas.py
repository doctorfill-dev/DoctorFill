"""
Variantes de dossiers qui forcent un chemin du pipeline (#50).

Les 21 dossiers de base sont propres et courts : plusieurs corrections du
pipeline n'y étaient vérifiées que par les tests à modèle simulé. Chaque
variante reprend un formulaire déjà couvert et vise un cas précis :

- dossier-long : trop long pour être transmis en entier, il passe par la
  recherche vectorielle (extraits) et la synthèse hiérarchique ;
- document-illisible : un scan penché sans couche texte et un PDF tronqué ;
  le job doit aboutir sur les autres documents ;
- periodes : trois périodes d'incapacité à des taux différents, attestées de
  la plus récente à la plus ancienne ;
- sans-reponse : patient retraité, sans téléphone, sans e-mail, sans employeur
  ni incapacité de travail : ces champs doivent rester vides.

Le patient d'un dossier « neuchâtelois » demandé dans #50 existe déjà :
AI_ReadaptationRente (Neuchâtel, médecin lausannois). Ce qui manquait, c'était
de vérifier le PDF livré : voir `regression.py`.
"""

from __future__ import annotations

from dataclasses import replace

from .praticiens import BRUNNER
from .render import Patient, Scenario
from .scenarios_autres import SCENARIOS as _AUTRES
from .scenarios_laa import SCENARIOS as _LAA


def _base(form: str) -> Scenario:
    return next(s for s in _LAA + _AUTRES if s.form == form)


# ---------------------------------------------------------------------------
# Dossier long : sept ans de suivi au cabinet avant l'accident
# ---------------------------------------------------------------------------

# (motif, note) : consultations sans rapport avec l'accident, sans incapacité de
# travail ni numéro de fax, pour ne rien changer à la vérité terrain.
_MOTIFS = [
    ("Contrôle de santé",
     "S : pas de plainte. Activité physique régulière, sommeil satisfaisant.\n"
     "O : TA {ta}, FC {fc}/min, poids {poids} kg. Auscultation cardio-pulmonaire normale.\n"
     "A : bilan de santé sans particularité.\n"
     "P : bilan sanguin de routine, prochain contrôle dans un an."),
    ("Rhinopharyngite",
     "S : rhinorrhée, odynophagie et toux sèche depuis trois jours, sans fièvre.\n"
     "O : pharynx érythémateux, tympans calmes, pas d'adénopathie. Température 37,4 °C.\n"
     "A : infection virale des voies aériennes supérieures.\n"
     "P : traitement symptomatique, lavages nasaux, reconsulter si fièvre."),
    ("Vaccination",
     "Vaccin contre la grippe saisonnière administré dans le deltoïde gauche. Lot noté "
     "au carnet. Surveillance de quinze minutes sans réaction. Pas de contre-indication "
     "relevée à l'anamnèse."),
    ("Lésion cutanée",
     "S : grain de beauté du dos remarqué par l'entourage, sans prurit ni saignement.\n"
     "O : naevus de 5 mm, régulier, homogène, bords nets.\n"
     "A : naevus d'aspect bénin.\n"
     "P : photographie au dossier, contrôle dermatologique proposé."),
    ("Gastro-entérite",
     "S : vomissements et diarrhées depuis la veille, contexte familial similaire.\n"
     "O : abdomen souple, bruits hydro-aériques augmentés, pas de signe de "
     "déshydratation.\n"
     "A : gastro-entérite virale probable.\n"
     "P : réhydratation orale, régime adapté, reconsulter si sang dans les selles."),
    ("Conjonctivite",
     "S : œil droit rouge et collé au réveil depuis deux jours.\n"
     "O : hyperhémie conjonctivale, sécrétions mucopurulentes, acuité conservée.\n"
     "A : conjonctivite bactérienne probable.\n"
     "P : collyre antibiotique cinq jours, hygiène des mains."),
    ("Douleurs dorsales",
     "S : douleurs lombaires basses après un week-end de jardinage, sans irradiation.\n"
     "O : contracture paravertébrale, Lasègue négatif, examen neurologique normal.\n"
     "A : lombalgie commune.\n"
     "P : antalgiques simples, mobilisation précoce. Poursuite de l'activité "
     "professionnelle habituelle."),
    ("Bilan sanguin",
     "Discussion des résultats du bilan de routine : formule sanguine, glycémie, "
     "profil lipidique et fonction rénale dans les normes. Pas de mesure à prendre."),
    ("Certificat sportif",
     "Examen en vue d'une inscription à un club de course à pied. Pas d'antécédent "
     "cardiaque familial, ECG de repos normal, épreuve d'effort non indiquée. Aptitude "
     "attestée."),
    ("Piqûre de tique",
     "S : tique retirée la veille au mollet gauche après une promenade en forêt.\n"
     "O : point d'inoculation calme, pas d'érythème migrant.\n"
     "A : piqûre de tique sans signe d'infection.\n"
     "P : surveillance de la peau pendant un mois, consigne de reconsulter."),
    ("Céphalées",
     "S : céphalées frontales en fin de journée, deux à trois fois par semaine, sans "
     "nausée ni trouble visuel. Écrans le soir, sommeil irrégulier.\n"
     "O : examen neurologique normal, TA {ta}, fond d'œil non réalisé.\n"
     "A : céphalées de tension probables.\n"
     "P : hygiène de sommeil, hydratation, contrôle ophtalmologique proposé."),
    ("Rhinite allergique",
     "S : éternuements, prurit nasal et oculaire chaque printemps depuis l'adolescence.\n"
     "O : muqueuse nasale pâle et œdématiée, conjonctives injectées.\n"
     "A : rhinoconjonctivite allergique saisonnière, pollens de graminées probables.\n"
     "P : antihistaminique oral en saison, spray nasal corticoïde, tests cutanés à discuter."),
]


def _consultations_anciennes() -> str:
    """Une centaine de consultations de 2019 à 2025, dans l'ordre chronologique."""
    entrees = []
    for i in range(98):
        annee, mois, jour = 2019 + i // 14, 1 + (i % 14) * 11 // 14, 2 + (i * 5) % 26
        motif, note = _MOTIFS[(i * 3) % len(_MOTIFS)]
        note = note.format(ta=f"{112 + i % 14}/{70 + i % 9}", fc=60 + i % 15, poids=58 + i % 4)
        entrees.append(((annee, mois, jour), motif, note))
    entrees.append(((2021, 5, 14), "Entorse de cheville",
                    "S : torsion de la cheville gauche en jouant au badminton la veille au soir.\n"
                    "O : tuméfaction latérale, douleur à la palpation du ligament talo-fibulaire "
                    "antérieur, appui possible, critères d'Ottawa négatifs.\n"
                    "A : entorse bénigne de la cheville gauche.\n"
                    "P : glaçage, bande élastique, reprise sportive progressive dans trois "
                    "semaines. Pas d'arrêt de travail."))
    lignes = []
    for (annee, mois, jour), motif, note in sorted(entrees, key=lambda e: e[0]):
        lignes += [f"## Consultation du {jour:02d}.{mois:02d}.{annee} — {motif}", "", note, ""]
    return "\n".join(lignes)


def _laboratoire() -> str:
    """Deux bilans par an, de 2019 à 2025, tous dans les normes."""
    valeurs = [(134, 6.1, 2, 4.9, 4.8, 2.7, 1.8, 54, 68), (136, 5.8, 1, 5.1, 4.9, 2.8, 2.1, 61, 70),
               (131, 7.2, 4, 4.8, 5.0, 2.9, 1.6, 38, 66), (133, 6.4, 1, 5.0, 4.7, 2.6, 2.4, 47, 69),
               (135, 5.9, 2, 5.2, 5.1, 3.0, 1.9, 52, 71), (132, 6.6, 3, 4.9, 4.9, 2.8, 2.0, 44, 67),
               (134, 6.0, 1, 5.0, 4.8, 2.7, 1.7, 58, 70)]
    lignes = []
    for i in range(14):
        annee, (hb, leuco, crp, gly, chol, ldl, tsh, ferr, creat) = 2019 + i // 2, valeurs[i % 7]
        date = f"{6 + i % 9:02d}.{5 if i % 2 == 0 else 11:02d}.{annee}"
        lignes += [
            f"## Bilan du {date}",
            "",
            f"- Hémoglobine : {hb} g/L (norme 120-160)",
            f"- Leucocytes : {leuco} G/L (norme 4,0-10,0)",
            "- Thrombocytes : 254 G/L (norme 150-400)",
            f"- CRP : {crp} mg/L (norme < 5)",
            f"- Glycémie à jeun : {gly} mmol/L (norme 3,9-5,6)",
            f"- Cholestérol total : {chol} mmol/L ; LDL : {ldl} mmol/L ; HDL : 1,6 mmol/L",
            f"- TSH : {tsh} mU/L (norme 0,4-4,0)",
            f"- Ferritine : {ferr} µg/L (norme 15-150)",
            f"- Créatinine : {creat} µmol/L ; DFGe > 90 mL/min/1,73 m²",
            "- Sodium : 140 mmol/L ; potassium : 4,1 mmol/L",
            "",
            "Commentaire : valeurs dans les normes, pas de contrôle rapproché nécessaire.",
            "",
        ]
    return "\n".join(lignes)


# (médicament, posologie, durée) : ordonnances courantes, sans rapport avec l'accident.
_ORDONNANCES = [
    ("Paracétamol 500 mg", "1 à 2 comprimés jusqu'à 4×/jour si douleur", "5 jours"),
    ("Ibuprofène 400 mg", "1 comprimé 3×/jour au repas", "5 jours"),
    ("Cétirizine 10 mg", "1 comprimé le soir", "durée de la saison pollinique"),
    ("Fluticasone spray nasal", "2 pulvérisations par narine le matin", "3 mois"),
    ("Chloramphénicol collyre", "1 goutte 4×/jour dans l'œil atteint", "5 jours"),
    ("Solution de réhydratation orale", "1 sachet après chaque selle liquide", "3 jours"),
    ("Pastilles pour la gorge", "1 pastille toutes les 3 heures", "5 jours"),
    ("Fer (sulfate ferreux) 80 mg", "1 comprimé le matin à jeun", "3 mois"),
]


def _ordonnances() -> str:
    lignes = ["Ordonnances délivrées par le cabinet, de la plus ancienne à la plus récente.", ""]
    for i in range(140):
        annee, mois, jour = 2019 + i // 20, 1 + (i % 20) * 12 // 20, 4 + (i * 3) % 23
        medicament, posologie, duree = _ORDONNANCES[(i * 5) % len(_ORDONNANCES)]
        lignes.append(f"- {jour:02d}.{mois:02d}.{annee} : {medicament} — {posologie}, "
                      f"pendant {duree}. Renouvellement : non.")
    return "\n".join(lignes) + "\n"


_MEDECINE_DU_TRAVAIL = """\
## Examen de médecine du travail — 15.09.2022

Service de santé au travail de la branche de la peinture, Lausanne. Examen
périodique des travailleurs exposés aux solvants et aux poussières de ponçage.

Anamnèse professionnelle : peintre en bâtiment depuis l'apprentissage, travaux
intérieurs et façades. Port du masque FFP2 lors des ponçages, demi-masque à
cartouches A2 pour les peintures solvantées, gants nitrile. Travail en hauteur
sur échafaudage et échelle environ deux jours par semaine.

Plaintes : aucune. Pas de céphalée en fin de journée de travail, pas de toux, pas
de lésion cutanée des mains.

Examen : peau des mains sans eczéma, auscultation pulmonaire normale.
Spirométrie : CVF 3,92 L (104 % du prédit), VEMS 3,31 L (102 %), rapport 84 %.
Audiométrie : seuils normaux sur toutes les fréquences.

Conclusion : apte sans restriction. Rappel des règles d'usage des protections
respiratoires et des échelles (contrôle de l'ancrage, trois points d'appui).
Prochain examen dans deux ans.

## Examen de médecine du travail — 12.09.2024

Même cadre. Pas de changement des tâches. Plaintes : légère irritation oculaire
lors des ponçages de plafond, résolue avec des lunettes de protection.

Spirométrie : CVF 3,88 L (103 %), VEMS 3,29 L (101 %), rapport 85 %.
Audiométrie : seuils normaux.

Conclusion : apte sans restriction. Prochain examen dans deux ans.
"""

_VACCINATIONS = """\
- Diphtérie, tétanos, coqueluche : rappel le 11.04.2019 ; prochain rappel en 2039.
- Rougeole, oreillons, rubéole : deux doses documentées dans l'enfance.
- Hépatite B : schéma complet, anticorps anti-HBs protecteurs (2019).
- Encéphalite à tiques : trois doses (2019-2020), rappel le 06.05.2023.
- Grippe saisonnière : chaque automne depuis 2020.
- COVID-19 : deux doses en 2021, rappel en janvier 2022.
- Papillomavirus : schéma complet à l'adolescence.
"""

_CORRESPONDANCE = """\
## Lettre du Dr méd. Paul Wenger, ophtalmologie FMH, Renens — 18.10.2023

Chère Consœur, cher Confrère,

Votre patiente consulte pour des céphalées en fin de journée. Acuité visuelle
non corrigée 8/10 à droite et 9/10 à gauche ; myopie légère de -0,75 dioptrie aux
deux yeux, sans astigmatisme significatif. Fond d'œil normal, papilles bien
limitées. Je prescris une correction pour le travail sur écran et la conduite de
nuit. Contrôle dans deux ans ou plus tôt en cas de gêne.

Avec mes meilleures salutations confraternelles.

## Lettre du Dr méd. Olivier Rey, dermatologie FMH, Lausanne — 22.06.2022

Chère Consœur, cher Confrère,

J'ai vu votre patiente pour le contrôle du naevus du dos que vous m'avez adressé.
L'examen dermatoscopique de l'ensemble du tégument montre une trentaine de naevi
d'aspect bénin, sans critère de malignité. La lésion dorsale mesure 5 mm, présente
un réseau pigmentaire régulier et ne justifie pas d'exérèse. Je recommande une
protection solaire rigoureuse, compte tenu du travail en extérieur, et un contrôle
dans deux ans. Je reste à disposition au 021 312 18 40.

Avec mes meilleures salutations confraternelles.

## Lettre de la Dre méd. Sophie Gay, ORL FMH, Morges — 09.02.2024

Chère Consœur, cher Confrère,

Votre patiente a consulté pour une sinusite maxillaire droite récidivante, troisième
épisode en un an. La nasofibroscopie montre une déviation septale modérée sans
polype. Le scanner des sinus confirme un épaississement muqueux maxillaire droit
sans niveau liquide. Je propose un traitement local par corticoïde nasal pendant
trois mois et un nouveau contrôle au printemps. Une septoplastie ne se discute
qu'en cas d'échec. Secrétariat : 021 801 44 30.

Avec mes meilleures salutations confraternelles.

## Rapport de physiothérapie, Physio du Flon, Lausanne — 30.06.2021

Prise en charge après entorse bénigne de la cheville gauche du 13.05.2021. Six
séances de proprioception et de renforcement des fibulaires. Récupération complète
de l'amplitude, appui unipodal stable, reprise du badminton sans douleur. Fin du
traitement.
"""


def _dossier_long() -> Scenario:
    base = _base("LAA_RapportInitial")
    suivi = [
        ("historique-consultations", "Historique des consultations au cabinet (2019-2025)",
         "Patiente suivie au cabinet depuis 2019. Notes antérieures à l'accident, "
         "ordre chronologique.\n\n" + _consultations_anciennes()),
        ("resultats-laboratoire", "Résultats de laboratoire", _laboratoire()),
        ("ordonnances", "Historique des ordonnances", _ordonnances()),
        ("medecine-du-travail", "Rapports de médecine du travail", _MEDECINE_DU_TRAVAIL),
        ("vaccinations", "Carnet de vaccination", _VACCINATIONS),
        ("correspondance", "Correspondance reçue", _CORRESPONDANCE),
    ]
    return replace(base, cas="dossier-long", mode="extraits", documents=suivi + base.documents)


# ---------------------------------------------------------------------------
# Document illisible
# ---------------------------------------------------------------------------

def _document_illisible() -> Scenario:
    base = _base("LAA_CertificatMedical_Suva")
    return replace(base, cas="document-illisible",
                   illisibles=[("radiographie-scannee", "scan-de-travers"),
                               ("courrier-assureur", "corrompu")])


# ---------------------------------------------------------------------------
# Plusieurs périodes d'incapacité, taux différents
# ---------------------------------------------------------------------------

def _periodes() -> Scenario:
    base = _base("LCA_IncapaciteTravail")
    return replace(
        base,
        cas="periodes",
        anamnese=(
            "Épuisement professionnel installé sur dix-huit mois, dans un contexte de "
            "restructuration. Premiers signes de décompensation le 26.01.2026 : arrêt "
            "partiel à 50 %. Aggravation le 23.02.2026, crise anxieuse aiguë sur le lieu "
            "de travail, arrêt complet. Reprise partielle à 50 % le 20.04.2026, dans des "
            "tâches sans conduite d'équipe."),
        consultations=[
            ("20.05.2026",
             "S : reprise à 50 % bien tolérée, fatigue en fin de journée.\n"
             "O : MADRS 17. Pas d'idéation suicidaire.\n"
             "A : amélioration sous traitement, reprise partielle adaptée.\n"
             "P : maintien de l'incapacité à 50 %, réévaluation dans six semaines."),
            ("20.04.2026",
             "S : sommeil amélioré, crises de panique espacées.\n"
             "O : MADRS 21.\n"
             "A : amélioration partielle.\n"
             "P : reprise à 50 % dès ce jour, sans responsabilité hiérarchique."),
            ("23.02.2026",
             "S : crise anxieuse aiguë au travail, sentiment de perte de contrôle.\n"
             "O : tachycardie, tremblements, pleurs. MADRS 32.\n"
             "A : décompensation dépressive et anxieuse.\n"
             "P : arrêt de travail complet, majoration de la sertraline à 100 mg."),
            ("26.01.2026",
             "S : troubles du sommeil, ruminations, irritabilité au travail.\n"
             "O : MADRS 24.\n"
             "A : épisode dépressif débutant sur épuisement professionnel.\n"
             "P : arrêt de travail à 50 %, introduction de sertraline 50 mg."),
        ],
        incapacites=[("26.01.2026", "22.02.2026", "50 %"),
                     ("23.02.2026", "19.04.2026", "100 %"),
                     ("20.04.2026", "", "50 %")],
        incapacites_antichrono=True,
        documents=[
            ("evaluation-capacite-lca", "Évaluation de la capacité de travail",
             "Profession exercée : responsable des ressources humaines, à 100 %, avec "
             "conduite d'équipe de six personnes.\n\n"
             "Début de l'incapacité de travail : 26.01.2026, d'abord partielle, puis "
             "complète lors de l'aggravation de février, puis de nouveau partielle depuis "
             "la reprise d'avril : voir les attestations jointes.\n\n"
             "Limitations fonctionnelles : intolérance au stress et aux conflits, "
             "fatigabilité cognitive, difficulté de concentration au-delà de trente "
             "minutes.\n\n"
             "Une reprise complète dans la fonction d'origine n'est pas exigible avant "
             "l'automne 2026."),
        ],
        evolution="Amélioration progressive sous traitement combiné, MADRS passé de 32 à 17.",
        pronostic="Favorable à moyen terme, reprise complète envisagée à l'automne 2026.",
    )


# ---------------------------------------------------------------------------
# Champs sans réponse : patient retraité, sans téléphone ni e-mail
# ---------------------------------------------------------------------------

def _sans_reponse() -> Scenario:
    return Scenario(
        form="LAMal_RapportInitial",
        cas="sans-reponse",
        titre="Rapport médical initial LAMal — coxarthrose, patient retraité",
        patient=Patient(
            nom="BOVET", prenom="Gérard", sexe="M", naissance="03.06.1951",
            avs="756.3307.5512.86", rue="Chemin de la Cure 3", npa="1066",
            ville="Épalinges", canton="VD", tel="", email="", etat_civil="marié",
            profession="retraité, ancien menuisier", employeur="",
            taux_activite="sans activité lucrative"),
        medecin=BRUNNER,
        assureur="CSS Assurance-maladie SA",
        police="LAMal-8830215",
        date_rapport="02.04.2026",
        contexte=(
            "Coxarthrose droite évoluée. Une prothèse totale de hanche est planifiée. "
            "L'assureur-maladie demande un rapport médical initial pour la garantie de "
            "prise en charge. Patient retraité : la capacité de travail est sans objet. "
            "Aucun numéro de téléphone ni adresse e-mail n'a été communiqué au cabinet ; "
            "le patient est joignable par courrier."),
        anamnese=(
            "Douleurs inguinales droites depuis 2022, d'aggravation progressive. "
            "Périmètre de marche réduit à 500 mètres, boiterie, difficulté à se chausser. "
            "Échec du traitement conservateur : antalgiques, physiothérapie, une "
            "infiltration intra-articulaire en 2025."),
        antecedents=[
            "Hypertension artérielle traitée depuis 2010 (I10)",
            "Appendicectomie en 1968",
        ],
        diagnostics=[
            ("M16.1", "Coxarthrose primaire droite", "10.01.2025"),
            ("I10", "Hypertension artérielle", "15.04.2010"),
        ],
        traitements=[
            "Amlodipine 5 mg, 1×/jour",
            "Paracétamol 1 g, jusqu'à 3×/jour",
            "Physiothérapie, 1×/semaine",
        ],
        consultations=[
            ("26.03.2026",
             "S : douleurs 6/10 à la marche, réveils nocturnes.\n"
             "O : flexion de hanche 80°, rotation interne 5°, Trendelenburg positif.\n"
             "A : coxarthrose évoluée, traitement conservateur épuisé.\n"
             "P : indication à une prothèse totale de hanche, intervention planifiée au "
             "18.05.2026."),
            ("15.01.2026",
             "S : aggravation malgré l'infiltration.\n"
             "O : boiterie d'esquive, périmètre de marche 500 m.\n"
             "A : échec du traitement conservateur.\n"
             "P : bilan radiologique et discussion opératoire."),
        ],
        documents=[
            ("radiographies-hanche", "Compte rendu radiologique",
             "Radiographies du bassin de face et de la hanche droite de profil, du "
             "10.03.2026.\n\n"
             "Pincement complet de l'interligne coxo-fémoral droit, ostéophytose "
             "acétabulaire et céphalique, géodes sous-chondrales.\n\n"
             "Conclusion : coxarthrose droite stade IV de Kellgren-Lawrence."),
            ("planification-operatoire", "Planification opératoire",
             "Intervention prévue le 18.05.2026 à l'Hôpital de Lavaux, Cully.\n\n"
             "Prothèse totale de hanche droite par voie antérieure, non cimentée.\n\n"
             "Durée d'hospitalisation prévue : 5 jours, puis réadaptation ambulatoire.\n\n"
             "Capacité de travail : sans objet, patient retraité sans activité lucrative."),
        ],
        pronostic="Bon. Reprise de la marche sans canne attendue en six à huit semaines.",
        absents=("tel", "email", "employeur", "incapacites"),
    )


SCENARIOS = [_dossier_long(), _document_illisible(), _periodes(), _sans_reponse()]
