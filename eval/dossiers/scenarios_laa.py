"""Scénarios des formulaires de l'assurance-accidents (LAA / Suva)."""

from .praticiens import BRUNNER, KELLER, MORAND, VERNET
from .render import Patient, Scenario

SCENARIOS = [
    Scenario(
        form="LAA_RapportInitial",
        titre="Rapport médical initial LAA — fracture du poignet",
        patient=Patient(
            nom="LEUENBERGER", prenom="Nadia", sexe="F", naissance="04.02.1997",
            avs="756.9034.2218.41", rue="Rue de l'Industrie 7", npa="1020",
            ville="Renens", canton="VD", tel="+41 79 887 12 44",
            email="n.leuenberger@exemple-mail.ch", etat_civil="célibataire",
            profession="peintre en bâtiment", employeur="Peinture Rochat SA"),
        medecin=MORAND,
        assureur="Suva, agence de Lausanne",
        police="41-772.915",
        date_rapport="19.02.2026",
        contexte=(
            "Accident professionnel du 17.02.2026 annoncé à la Suva par l'employeur. "
            "Premier rapport médical LAA établi au décours de la prise en charge "
            "initiale."),
        anamnese=(
            "Chute d'une échelle d'environ deux mètres sur un chantier, réception sur la "
            "main droite en hyperextension. Douleur immédiate du poignet, impotence "
            "fonctionnelle totale. Pas de perte de connaissance, pas d'autre point "
            "d'impact."),
        antecedents=[
            "Aucun antécédent chirurgical",
            "Aucun traitement au long cours",
            "Non-fumeuse",
        ],
        diagnostics=[
            ("S52.5", "Fracture de l'extrémité distale du radius droit, déplacée", "17.02.2026"),
            ("S63.5", "Entorse du ligament scapho-lunaire droit", "17.02.2026"),
        ],
        traitements=[
            "Réduction fermée et immobilisation par plâtre antébrachial le 17.02.2026",
            "Dafalgan 1000 mg, 3×/jour",
            "Contrôle radiologique hebdomadaire pendant trois semaines",
        ],
        consultations=[
            ("19.02.2026",
             "S : douleur contrôlée sous antalgie simple, pas de paresthésie.\n"
             "O : plâtre en place, extrémités chaudes, mobilité des doigts conservée, "
             "temps de recoloration < 2 s.\n"
             "A : suites simples à 48 heures.\n"
             "P : contrôle radiologique à J7, arrêt de travail complet."),
            ("17.02.2026",
             "S : douleur 8/10 du poignet droit après chute.\n"
             "O : déformation en dos de fourchette, tuméfaction, pas d'ouverture "
             "cutanée, pas de déficit neurologique.\n"
             "A : fracture de Pouteau-Colles déplacée.\n"
             "P : réduction sous anesthésie locorégionale, plâtre, radiographie de "
             "contrôle satisfaisante."),
        ],
        incapacites=[("17.02.2026", "31.03.2026", "100 %")],
        accident={
            "date": "17.02.2026", "heure": "09h20",
            "lieu": "Chantier, Avenue du Léman 44, 1005 Lausanne",
            "description":
                "L'assurée peignait un plafond depuis une échelle simple. L'échelle a "
                "glissé sur le sol fraîchement lessivé. Chute d'une hauteur d'environ "
                "deux mètres, réception sur la main droite en hyperextension.",
            "temoin": "M. Gilles Rochat, contremaître, présent sur le chantier.",
            "premiers_soins":
                "Immobilisation de fortune sur place, transport par les collègues à la "
                "Permanence de Chauderon, arrivée à 10h05.",
        },
        documents=[
            ("radiographies", "Compte rendu radiologique",
             "Radiographie du poignet droit, face et profil, du 17.02.2026.\n\n"
             "Fracture métaphysaire distale du radius, à 22 mm de l'interligne, avec "
             "bascule postérieure de 25° et raccourcissement radial de 4 mm. Styloïde "
             "ulnaire fracturée à sa base. Espace scapho-lunaire élargi à 3,5 mm.\n\n"
             "Après réduction : bascule postérieure ramenée à 5°, hauteur radiale "
             "restaurée. Contention plâtrée satisfaisante."),
        ],
        pronostic=(
            "Consolidation attendue à six semaines. Reprise du travail de peintre en "
            "bâtiment envisageable vers la mi-avril 2026, après rééducation."),
    ),

    Scenario(
        form="LAA_RapportAbrege",
        titre="Rapport abrégé LAA — entorse de cheville",
        patient=Patient(
            nom="FERREIRA", prenom="Miguel", sexe="M", naissance="19.06.1992",
            avs="756.2245.9917.33", rue="Chemin du Verger 15", npa="1030",
            ville="Bussigny", canton="VD", tel="+41 78 442 60 19",
            email="m.ferreira@exemple-mail.ch", etat_civil="célibataire",
            profession="magasinier", employeur="Distrilog Suisse SA"),
        medecin=MORAND,
        assureur="Suva, agence de Lausanne",
        police="41-903.226",
        date_rapport="12.03.2026",
        contexte=(
            "Accident bagatelle du 09.03.2026, évolution simple, sans intervention ni "
            "hospitalisation. Le rapport abrégé LAA suffit."),
        anamnese=(
            "Torsion de la cheville gauche en descendant d'un quai de chargement. "
            "Mécanisme en inversion. Appui possible d'emblée, boiterie."),
        antecedents=["Entorse de la même cheville en 2018, sans séquelle"],
        diagnostics=[("S93.4", "Entorse de la cheville gauche, stade II", "09.03.2026")],
        traitements=[
            "Attelle stabilisatrice pendant trois semaines",
            "Glace et surélévation les premiers jours",
            "Dafalgan 1000 mg en réserve",
        ],
        consultations=[
            ("12.03.2026",
             "S : douleur 3/10, appui complet possible avec attelle.\n"
             "O : œdème en régression, pas de laxité en tiroir antérieur.\n"
             "A : évolution favorable.\n"
             "P : poursuite de l'attelle une semaine, reprise du travail le 16.03.2026."),
            ("09.03.2026",
             "S : douleur latérale externe après torsion.\n"
             "O : œdème rétromalléolaire externe, appui monopodal possible, critères "
             "d'Ottawa négatifs.\n"
             "A : entorse de stade II, pas d'indication radiologique.\n"
             "P : attelle, antalgie, arrêt de travail de sept jours."),
        ],
        incapacites=[("09.03.2026", "15.03.2026", "100 %")],
        accident={
            "date": "09.03.2026", "heure": "14h45",
            "lieu": "Entrepôt Distrilog, Route de Crissier 12, 1030 Bussigny",
            "description":
                "En descendant du quai de chargement, l'assuré a posé le pied gauche "
                "sur le rebord d'une palette. Torsion en inversion de la cheville, sans "
                "chute.",
            "temoin": "Aucun témoin direct.",
        },
        pronostic="Guérison sans séquelle attendue à trois semaines.",
    ),

    Scenario(
        form="LAA_CertificatMedical_Suva",
        titre="Certificat médical Suva — plaie de la main avec section tendineuse",
        patient=Patient(
            nom="SCHNEIDER", prenom="Lukas", sexe="M", naissance="28.08.1990",
            avs="756.5561.3308.77", rue="Rue Centrale 22", npa="1400",
            ville="Yverdon-les-Bains", canton="VD", tel="+41 79 336 25 08",
            email="l.schneider@exemple-mail.ch", etat_civil="marié",
            profession="menuisier", employeur="Menuiserie Bornand SA"),
        medecin=BRUNNER,
        assureur="Suva, agence d'Yverdon-les-Bains",
        police="41-118.774",
        date_rapport="28.04.2026",
        contexte=(
            "Accident professionnel du 24.03.2026 avec section tendineuse opérée. La "
            "Suva demande un certificat médical détaillé en vue du suivi des prestations."),
        anamnese=(
            "Section de la face palmaire de la main droite par une scie circulaire, à "
            "travers un gant de protection. Prise en charge chirurgicale en urgence le "
            "jour même : suture des fléchisseurs II et III en zone II, exploration "
            "nerveuse sans lésion. Immobilisation par attelle dorsale de Kleinert "
            "pendant six semaines, puis rééducation."),
        antecedents=[
            "Aucun antécédent notable",
            "Droitier",
        ],
        diagnostics=[
            ("S66.0", "Section des tendons fléchisseurs des 2e et 3e doigts, main droite", "24.03.2026"),
            ("S61.0", "Plaie ouverte de la paume droite", "24.03.2026"),
        ],
        traitements=[
            "Ténorraphie primaire des fléchisseurs II et III le 24.03.2026",
            "Attelle de Kleinert du 24.03.2026 au 05.05.2026",
            "Ergothérapie de la main, 3×/semaine depuis le 07.05.2026",
            "Antibioprophylaxie par co-amoxicilline pendant cinq jours",
        ],
        consultations=[
            ("24.04.2026",
             "S : douleurs résiduelles à la mobilisation, pas de signe infectieux.\n"
             "O : cicatrice calme, flexion active II 40°, III 45°, extension complète "
             "passive. Sensibilité conservée.\n"
             "A : suites simples, raideur attendue à ce stade.\n"
             "P : poursuite de l'ergothérapie, arrêt de travail complet maintenu."),
            ("07.04.2026",
             "S : douleur contrôlée sous attelle.\n"
             "O : pas de désunion, pas de rupture secondaire.\n"
             "A : cicatrisation acquise.\n"
             "P : maintien du protocole de Kleinert."),
        ],
        incapacites=[("24.03.2026", "", "100 %")],
        accident={
            "date": "24.03.2026", "heure": "11h05",
            "lieu": "Atelier Menuiserie Bornand, Rue de l'Arsenal 9, 1400 Yverdon-les-Bains",
            "description":
                "L'assuré débitait un panneau à la scie circulaire de table. Le poussoir "
                "a dérapé et la main droite est entrée en contact avec la lame. Le "
                "protecteur de lame était relevé pour la coupe en cours.",
            "temoin": "M. Antoine Bornand, chef d'atelier.",
            "premiers_soins":
                "Compression et surélévation sur place, appel du 144, transport "
                "médicalisé aux urgences de l'Hôpital d'Yverdon à 11h35.",
        },
        documents=[
            ("protocole-operatoire", "Protocole opératoire",
             "Intervention du 24.03.2026, Hôpital d'Yverdon, service de chirurgie de la "
             "main.\n\n"
             "Sous anesthésie locorégionale, garrot pneumatique à 250 mmHg.\n\n"
             "Exploration de la plaie palmaire : section complète du fléchisseur commun "
             "profond II, section partielle (70 %) du fléchisseur commun superficiel "
             "III. Pédicules vasculo-nerveux collatéraux intacts, testés au "
             "microscope.\n\n"
             "Ténorraphie selon Kessler modifié à quatre brins, surjet épitendineux. "
             "Fermeture cutanée par points séparés. Attelle dorsale poignet à 30° de "
             "flexion, MCP à 60°, IP en extension.\n\n"
             "Durée : 95 minutes. Suites immédiates simples."),
            ("bilan-ergotherapie", "Bilan d'ergothérapie",
             "Bilan du 22.04.2026, après quinze séances.\n\n"
             "Mobilité active : II 40° de flexion MCP, III 45°. Déficit d'extension "
             "actif de 10° sur II. Force de préhension à 12 kg à droite contre 46 kg à "
             "gauche (dynamomètre Jamar).\n\n"
             "Sensibilité : test de Weber à 6 mm en pulpaire II et III, contre 4 mm à "
             "gauche.\n\n"
             "Objectifs à trois mois : flexion active complète, force de préhension à "
             "70 % du côté controlatéral. La reprise du métier de menuisier, qui exige "
             "une préhension forte et une manipulation d'outils tranchants, n'est pas "
             "envisageable avant six mois."),
        ],
        evolution=(
            "Évolution conforme au protocole, sans rupture secondaire ni infection. La "
            "raideur digitale reste au premier plan."),
        pronostic=(
            "Reprise de l'activité de menuisier envisagée au plus tôt en octobre 2026. "
            "Une gêne résiduelle à la préhension fine est probable."),
    ),

    Scenario(
        form="LAA_RapportIntermediaire_Suva",
        titre="Rapport intermédiaire Suva — rupture de coiffe des rotateurs",
        patient=Patient(
            nom="ZUFFEREY", prenom="Patrick", sexe="M", naissance="12.05.1979",
            avs="756.6612.4471.29", rue="Route du Simplon 60", npa="1907",
            ville="Saxon", canton="VS", tel="+41 79 604 33 12",
            email="p.zufferey@exemple-mail.ch", etat_civil="marié",
            profession="monteur en échafaudages", employeur="Échafaudages Valais SA"),
        medecin=BRUNNER,
        assureur="Suva, agence de Sion",
        police="41-556.083",
        date_rapport="15.05.2026",
        contexte=(
            "Accident du 08.11.2025 déjà déclaré. Six mois d'évolution, opération "
            "intervenue entre-temps : la Suva sollicite un rapport intermédiaire sur "
            "l'évolution et sur la reprise du travail."),
        anamnese=(
            "Chute d'un échafaudage d'environ 1,50 m avec réception sur le moignon de "
            "l'épaule droite. Douleur immédiate et impotence à l'élévation. IRM du "
            "21.11.2025 : rupture transfixiante du supra-épineux. Réparation "
            "arthroscopique le 14.01.2026, puis rééducation."),
        antecedents=[
            "Tendinopathie de la coiffe droite traitée conservativement en 2019",
            "Hypercholestérolémie sous statine",
        ],
        diagnostics=[
            ("S43.4", "Rupture traumatique de la coiffe des rotateurs, épaule droite", "08.11.2025"),
            ("M75.1", "Tendinopathie du supra-épineux, préexistante", "03.06.2019"),
        ],
        traitements=[
            "Réparation arthroscopique du supra-épineux le 14.01.2026",
            "Attelle d'abduction pendant six semaines",
            "Physiothérapie, 2×/semaine depuis le 26.02.2026",
            "Atorvastatine 20 mg, 1×/jour",
        ],
        consultations=[
            ("12.05.2026",
             "S : douleur nocturne résolue, gêne à l'élévation au-dessus de l'horizontale.\n"
             "O : élévation active 130°, abduction 120°, rotation externe 40°. Force "
             "4/5 en abduction. Pas de signe de re-rupture.\n"
             "A : évolution favorable, récupération incomplète à quatre mois "
             "post-opératoires.\n"
             "P : poursuite de la physiothérapie, incapacité de travail maintenue à "
             "100 % dans le métier d'origine."),
            ("03.03.2026",
             "S : début de la rééducation, douleurs modérées.\n"
             "O : élévation passive 100°, active 60°.\n"
             "A : raideur post-immobilisation.\n"
             "P : intensification de la physiothérapie."),
        ],
        incapacites=[("08.11.2025", "", "100 %")],
        accident={
            "date": "08.11.2025", "heure": "15h30",
            "lieu": "Chantier, Rue des Vergers 3, 1950 Sion",
            "description":
                "Lors du démontage d'un échafaudage, l'assuré a perdu l'équilibre en "
                "reculant sur une plateforme et a chuté d'environ 1,50 m, réception sur "
                "l'épaule droite.",
            "temoin": "M. Sébastien Praz, collègue de chantier.",
        },
        documents=[
            ("irm-epaule", "Rapport d'imagerie",
             "IRM de l'épaule droite du 21.11.2025.\n\n"
             "Rupture transfixiante du tendon du supra-épineux, rétraction de 12 mm, "
             "trophicité musculaire conservée (Goutallier stade 1). Tendon du "
             "sous-épineux continu. Bourse sous-acromiale distendue. Pas de lésion du "
             "long chef du biceps.\n\n"
             "Conclusion : rupture transfixiante récente du supra-épineux, réparable."),
            ("evaluation-reprise", "Évaluation de la reprise du travail",
             "Le métier de monteur en échafaudages impose le port de charges de 20 à "
             "25 kg, le travail bras au-dessus de la tête et l'usage d'échelles.\n\n"
             "État actuel : élévation active limitée à 130°, force 4/5, pas de port de "
             "charge au-dessus de l'horizontale possible.\n\n"
             "Reprise dans le métier d'origine : non exigible actuellement. Réévaluation "
             "à trois mois.\n\n"
             "Activité adaptée — sans port de charge supérieur à 5 kg, sans travail au-"
             "dessus de l'horizontale, sans échelle : exigible à 50 % dès le 01.06.2026."),
        ],
        evolution="Progression régulière depuis la reprise de la physiothérapie.",
        pronostic=(
            "Récupération fonctionnelle attendue à douze mois de l'intervention. Une "
            "reconversion est à envisager si la force ne permet pas le port de charges "
            "lourdes."),
    ),

    Scenario(
        form="LAA_PremierDiagnostic_MTBI",
        titre="Premier diagnostic LAA — traumatisme cranio-cérébral léger",
        patient=Patient(
            nom="HOFMANN", prenom="Céline", sexe="F", naissance="03.10.1988",
            avs="756.7788.1145.60", rue="Avenue de Cour 71", npa="1007",
            ville="Lausanne", canton="VD", tel="+41 76 229 87 54",
            email="c.hofmann@exemple-mail.ch", etat_civil="célibataire",
            profession="cheffe de projet informatique", employeur="Novatec Solutions SA"),
        medecin=MORAND,
        assureur="Zurich Assurances SA",
        police="LAA-887.442.19",
        date_rapport="06.04.2026",
        contexte=(
            "Traumatisme cranio-cérébral léger survenu le 02.04.2026 dans un accident "
            "non professionnel couvert par l'assurance-accidents de l'employeur. Premier "
            "diagnostic à documenter selon le protocole MTBI."),
        anamnese=(
            "Chute à vélo sur la voie publique, casque porté et fendu à l'impact. Perte "
            "de connaissance estimée à moins d'une minute par un témoin. Amnésie "
            "circonstancielle de quelques minutes autour de l'événement. Céphalées, "
            "nausées et photophobie dans les heures suivantes."),
        antecedents=[
            "Aucun antécédent de traumatisme crânien",
            "Migraine occasionnelle sans aura",
            "Pas de traitement anticoagulant",
        ],
        diagnostics=[
            ("S06.0", "Commotion cérébrale (traumatisme cranio-cérébral léger)", "02.04.2026"),
            ("S00.0", "Contusion du cuir chevelu, région pariétale gauche", "02.04.2026"),
        ],
        traitements=[
            "Repos cognitif et physique pendant sept jours",
            "Dafalgan 1000 mg en réserve, éviction des AINS les 48 premières heures",
            "Reprise progressive selon protocole en six paliers",
        ],
        consultations=[
            ("06.04.2026",
             "S : céphalées 4/10, fatigue marquée, difficultés de concentration à la "
             "lecture. Pas de vomissement, pas de trouble visuel.\n"
             "O : Glasgow 15, examen neurologique sans déficit focal, épreuves "
             "cérébelleuses normales. Test d'équilibre BESS : 18 erreurs.\n"
             "A : syndrome post-commotionnel à J4.\n"
             "P : poursuite du repos relatif, arrêt de travail, réévaluation à une "
             "semaine."),
            ("02.04.2026",
             "S : céphalées immédiates, nausées, sensation de flou.\n"
             "O : Glasgow 15 à l'arrivée, pupilles symétriques réactives, pas de "
             "signe de localisation. Plaie superficielle pariétale gauche de 2 cm.\n"
             "A : traumatisme cranio-cérébral léger, critères canadiens ne retenant pas "
             "d'indication au scanner.\n"
             "P : surveillance de six heures aux urgences, consignes écrites remises à "
             "l'accompagnante, sortie le soir même."),
        ],
        incapacites=[("02.04.2026", "17.04.2026", "100 %")],
        accident={
            "date": "02.04.2026", "heure": "18h10",
            "lieu": "Avenue de Rhodanie, à hauteur du no 40, 1007 Lausanne",
            "description":
                "L'assurée circulait à vélo sur la piste cyclable. Une portière de "
                "véhicule stationné s'est ouverte devant elle. Chute sur le côté gauche "
                "avec impact de la tête au sol, casque porté et fendu.",
            "temoin": "Mme Julie Perrin, passante, a appelé les secours.",
            "premiers_soins":
                "Prise en charge par ambulance, transport aux urgences du CHUV, arrivée "
                "à 18h45.",
        },
        documents=[
            ("bilan-neurocognitif", "Bilan neurocognitif de dépistage",
             "Évaluation du 06.04.2026, à J4 du traumatisme.\n\n"
             "Score SCAT5 symptomatique : 14 symptômes rapportés, sévérité totale 38/132. "
             "Symptômes dominants : céphalées, fatigue, difficulté de concentration, "
             "sensibilité à la lumière.\n\n"
             "Orientation, mémoire immédiate et différée : conservées. Concentration "
             "(chiffres à rebours) : 3/4. Équilibre BESS : 18 erreurs, contre une norme "
             "attendue inférieure à 12 pour l'âge.\n\n"
             "Conclusion : syndrome post-commotionnel d'intensité modérée. Pas de "
             "critère de gravité. Reprise progressive du travail selon protocole, à "
             "réévaluer à J14."),
        ],
        evolution=(
            "Régression progressive des symptômes attendue en deux à quatre semaines "
            "dans la majorité des cas."),
        pronostic=(
            "Favorable. Une reprise à 50 % est prévue le 20.04.2026, avec adaptation du "
            "temps d'écran, puis retour à 100 % selon tolérance."),
    ),

    Scenario(
        form="LAA_PriseEnChargeHospitaliere",
        titre="Prise en charge hospitalière LAA — polytraumatisme",
        patient=Patient(
            nom="ROULIN", prenom="Georges", sexe="M", naissance="17.01.1971",
            avs="756.3390.7724.18", rue="Rue du Château 9", npa="1580",
            ville="Avenches", canton="VD", tel="+41 79 415 77 26",
            email="g.roulin@exemple-mail.ch", etat_civil="marié",
            profession="conducteur de travaux", employeur="Constructions Broye SA"),
        medecin=BRUNNER,
        assureur="Suva, agence de Fribourg",
        police="41-224.907",
        date_rapport="11.05.2026",
        contexte=(
            "Hospitalisation en cours depuis le 28.04.2026 à la suite d'un accident "
            "professionnel grave. Demande de garantie de prise en charge hospitalière "
            "adressée à l'assureur-accidents."),
        anamnese=(
            "Écrasement du membre inférieur droit par une charge de coffrage lors d'une "
            "manœuvre de grue. Prise en charge préhospitalière médicalisée, transfert "
            "direct au CHUV en trauma center. Chirurgie en deux temps."),
        antecedents=[
            "Hypertension artérielle traitée depuis 2016",
            "Tabagisme 25 UPA, actif",
            "Hernie inguinale opérée en 2009",
        ],
        diagnostics=[
            ("S82.2", "Fracture ouverte de la diaphyse tibiale droite, Gustilo II", "28.04.2026"),
            ("S82.4", "Fracture de la diaphyse fibulaire droite", "28.04.2026"),
            ("S80.8", "Contusion étendue des parties molles de la jambe droite", "28.04.2026"),
            ("I10", "Hypertension artérielle", "12.05.2016"),
        ],
        traitements=[
            "Fixateur externe le 28.04.2026, en urgence",
            "Ostéosynthèse par clou centromédullaire verrouillé le 05.05.2026",
            "Antibiothérapie par co-amoxicilline pendant sept jours",
            "Anticoagulation prophylactique par énoxaparine 40 mg/jour",
            "Lisinopril 10 mg, 1×/jour",
        ],
        consultations=[
            ("11.05.2026",
             "S : douleurs contrôlées sous antalgie palier 2, pas de fièvre.\n"
             "O : cicatrices calmes, pas d'écoulement, pouls pédieux perçus. Appui "
             "interdit.\n"
             "A : suites post-opératoires simples à J6 du clou.\n"
             "P : poursuite de l'hospitalisation pour rééducation à la marche en "
             "décharge, sortie envisagée vers le 20.05.2026."),
            ("05.05.2026",
             "S : patient stable, apyrétique.\n"
             "O : parties molles compatibles avec une ostéosynthèse définitive.\n"
             "A : indication retenue.\n"
             "P : conversion du fixateur externe en clou centromédullaire."),
        ],
        incapacites=[("28.04.2026", "", "100 %")],
        accident={
            "date": "28.04.2026", "heure": "10h50",
            "lieu": "Chantier Les Terrasses, Route de Berne 14, 1580 Avenches",
            "description":
                "Lors du levage d'un banc de coffrage par la grue, l'élingue a cédé. La "
                "charge, d'environ 400 kg, est retombée sur la jambe droite de l'assuré "
                "qui guidait la manœuvre au sol.",
            "temoin": "M. Ali Demir, grutier, et M. Yves Cottet, chef de chantier.",
            "premiers_soins":
                "Dégagement par les collègues, appel du 144 à 10h53, médicalisation sur "
                "place puis héliportage au CHUV, admission à 11h40.",
        },
        documents=[
            ("sejour-hospitalier", "Résumé du séjour hospitalier",
             "Admission : 28.04.2026 au CHUV, service de chirurgie orthopédique et "
             "traumatologie de l'appareil moteur.\n\n"
             "Passage en salle de déchoquage, bilan lésionnel par scanner corps entier : "
             "pas de lésion crânienne, thoracique ni abdominale. Lésions limitées au "
             "membre inférieur droit.\n\n"
             "28.04.2026 : parage, lavage abondant, fixateur externe tibial. Durée "
             "115 minutes.\n"
             "05.05.2026 : ablation du fixateur, enclouage centromédullaire verrouillé "
             "du tibia droit. Durée 140 minutes.\n\n"
             "Suites : apyrexie constante, pas de complication infectieuse ni "
             "thromboembolique. Rééducation débutée à J2 du clou.\n\n"
             "Durée de séjour prévisionnelle : 22 jours. Sortie envisagée le 20.05.2026 "
             "vers un séjour de réadaptation musculo-squelettique à la Clinique de "
             "Valmont, d'une durée estimée à trois semaines."),
        ],
        pronostic=(
            "Consolidation osseuse attendue à quatre mois. Reprise de l'activité de "
            "conducteur de travaux envisageable vers janvier 2027, sous réserve de "
            "l'évolution."),
    ),

    Scenario(
        form="LAA_MoyensAuxiliaires",
        titre="Demande de moyens auxiliaires LAA",
        patient=Patient(
            nom="PILLET", prenom="Bernard", sexe="M", naissance="09.03.1966",
            avs="756.1178.5540.94", rue="Chemin de la Forêt 27", npa="1618",
            ville="Châtel-Saint-Denis", canton="FR", tel="+41 79 208 51 63",
            email="b.pillet@exemple-mail.ch", etat_civil="marié",
            profession="chauffeur poids lourds", employeur="Transports Fribourgeois SA"),
        medecin=BRUNNER,
        assureur="Suva, agence de Fribourg",
        police="41-661.338",
        date_rapport="02.06.2026",
        contexte=(
            "Séquelles définitives d'un accident professionnel du 12.06.2025. Demande de "
            "prise en charge de moyens auxiliaires par l'assureur-accidents."),
        anamnese=(
            "Chute de la plateforme d'un camion, hauteur 1,80 m, avec fracture-luxation "
            "du calcanéum gauche. Ostéosynthèse le 16.06.2025. Évolution vers une "
            "arthrose sous-talienne post-traumatique, douloureuse à la marche prolongée "
            "et en terrain irrégulier."),
        antecedents=[
            "Diabète de type 2 depuis 2018, sous metformine",
            "Surcharge pondérale, IMC 29",
        ],
        diagnostics=[
            ("S92.0", "Fracture du calcanéum gauche, séquelles", "12.06.2025"),
            ("M19.0", "Arthrose sous-talienne post-traumatique gauche", "20.02.2026"),
            ("E11.9", "Diabète de type 2 sans complication", "04.09.2018"),
        ],
        traitements=[
            "Metformine 1000 mg, 2×/jour",
            "Antalgie par paracétamol à la demande",
            "Physiothérapie d'entretien, 1×/semaine",
        ],
        consultations=[
            ("26.05.2026",
             "S : douleurs à la marche au-delà de 20 minutes, majorées en terrain "
             "irrégulier. Boiterie en fin de journée.\n"
             "O : mobilité sous-talienne quasi nulle, appui talonnier douloureux, "
             "élargissement du talon.\n"
             "A : arthrose sous-talienne constituée, état stabilisé.\n"
             "P : appareillage orthopédique, adaptation du poste de conduite."),
        ],
        incapacites=[("12.06.2025", "31.03.2026", "100 %"),
                     ("01.04.2026", "", "50 %")],
        accident={
            "date": "12.06.2025", "heure": "07h40",
            "lieu": "Dépôt Transports Fribourgeois, Route Industrielle 5, 1630 Bulle",
            "description":
                "En descendant de la plateforme de chargement du camion, l'assuré a "
                "manqué le dernier échelon et est tombé d'environ 1,80 m, réception sur "
                "le talon gauche.",
            "temoin": "Aucun témoin direct, accident constaté par un collègue peu après.",
        },
        documents=[
            ("prescription-moyens-auxiliaires", "Prescription de moyens auxiliaires",
             "Moyens auxiliaires sollicités auprès de l'assureur-accidents :\n\n"
             "1. Paire de chaussures orthopédiques sur mesure, avec semelle à "
             "amortissement talonnier et déroulé facilité. Renouvellement annuel "
             "prévisible.\n"
             "2. Orthèse plantaire moulée gauche, deux paires par an.\n"
             "3. Canne anglaise réglable, pour les déplacements longs.\n\n"
             "Fournisseur : Orthopédie Fribourgeoise SA. Devis du 20.05.2026 : "
             "CHF 3 280.— pour les chaussures, CHF 640.— pour les orthèses.\n\n"
             "Ces moyens sont rendus nécessaires par les seules séquelles de l'accident "
             "du 12.06.2025. Ils conditionnent le maintien d'une activité de conduite à "
             "50 % et l'autonomie de déplacement."),
            ("rapport-orthopediste", "Rapport de l'orthopédiste-technicien",
             "Examen du 20.05.2026.\n\n"
             "Élargissement du talon gauche de 14 mm par rapport au côté droit, "
             "incompatible avec une chaussure du commerce. Appui talonnier "
             "hyperalgique, empreinte podoscopique montrant une surcharge de l'avant-"
             "pied compensatrice.\n\n"
             "Chaussure de série essayée sans succès : conflit latéral persistant après "
             "trois adaptations.\n\n"
             "Conclusion : chaussure orthopédique sur mesure indiquée, avec coque "
             "talonnière élargie et semelle d'amortissement."),
        ],
        evolution="État stabilisé depuis février 2026, sans amélioration attendue.",
        pronostic=(
            "Séquelles définitives. Capacité de travail durablement limitée à 50 % dans "
            "l'activité de chauffeur, sous réserve de l'appareillage."),
    ),

    Scenario(
        form="LAA_Physiotherapie",
        titre="Prescription de physiothérapie LAA",
        patient=Patient(
            nom="GRAF", prenom="Sandra", sexe="F", naissance="25.12.1993",
            avs="756.4405.6612.37", rue="Rue de Bourg 18", npa="1003",
            ville="Lausanne", canton="VD", tel="+41 78 663 09 41",
            email="s.graf@exemple-mail.ch", etat_civil="célibataire",
            profession="coiffeuse", employeur="Salon Élégance Sàrl"),
        medecin=BRUNNER,
        assureur="Helsana Accidents SA",
        police="LAA-330.219.44",
        date_rapport="20.04.2026",
        contexte=(
            "Suites d'une luxation de l'épaule droite survenue lors d'un accident non "
            "professionnel du 14.03.2026. Première prescription de physiothérapie à la "
            "charge de l'assureur-accidents."),
        anamnese=(
            "Luxation antéro-interne de l'épaule droite lors d'une chute à ski, réduite "
            "aux urgences le jour même. Immobilisation par gilet pendant trois semaines. "
            "Raideur et appréhension à l'armé du bras depuis l'ablation du gilet."),
        antecedents=["Aucun antécédent de luxation", "Droitière"],
        diagnostics=[
            ("S43.0", "Luxation antéro-interne de l'épaule droite, réduite", "14.03.2026"),
            ("M25.6", "Raideur de l'épaule droite post-immobilisation", "07.04.2026"),
        ],
        traitements=[
            "Gilet d'immobilisation du 14.03.2026 au 04.04.2026",
            "Antalgie par paracétamol",
            "Physiothérapie prescrite ce jour",
        ],
        consultations=[
            ("20.04.2026",
             "S : douleur 3/10, appréhension à l'abduction-rotation externe.\n"
             "O : élévation active 110°, rotation externe 20°, test d'appréhension "
             "positif. Pas de déficit neurologique.\n"
             "A : raideur post-immobilisation sur luxation réduite, sans lésion "
             "osseuse.\n"
             "P : physiothérapie, reprise du travail à 50 % dès le 27.04.2026."),
        ],
        incapacites=[("14.03.2026", "26.04.2026", "100 %"),
                     ("27.04.2026", "31.05.2026", "50 %")],
        accident={
            "date": "14.03.2026", "heure": "13h15",
            "lieu": "Domaine skiable des Diablerets, piste bleue no 4",
            "description":
                "Chute à ski en fin de virage, réception bras droit en abduction et "
                "rotation externe. Luxation immédiate, réduite aux urgences de "
                "l'Hôpital d'Aigle.",
            "temoin": "Mme Laure Dupasquier, amie présente sur place.",
        },
        documents=[
            ("prescription-physiotherapie", "Prescription de physiothérapie",
             "Prescription du 20.04.2026, à la charge de l'assureur-accidents.\n\n"
             "Nombre de séances : 9 séances.\n"
             "Fréquence : 2 séances par semaine.\n"
             "Durée : 45 minutes par séance.\n\n"
             "Objectifs :\n"
             "- récupération des amplitudes articulaires passives puis actives ;\n"
             "- renforcement des stabilisateurs de la scapula et de la coiffe ;\n"
             "- travail proprioceptif et levée de l'appréhension ;\n"
             "- reprise gestuelle spécifique au métier de coiffeuse, bras en élévation "
             "prolongée.\n\n"
             "Contre-indications : pas de mobilisation forcée en abduction-rotation "
             "externe avant la sixième semaine.\n\n"
             "Réévaluation médicale au terme des neuf séances."),
        ],
        pronostic=(
            "Récupération complète attendue à trois mois. Risque de récidive de luxation "
            "estimé à 20 % à cet âge, justifiant le travail proprioceptif."),
    ),

    Scenario(
        form="LAA_Physiotherapie_LongueDuree",
        titre="Physiothérapie de longue durée LAA — SDRC du membre supérieur",
        patient=Patient(
            nom="TISSOT", prenom="Olivier", sexe="M", naissance="14.04.1977",
            avs="756.9923.3081.55", rue="Rue Neuve 12", npa="2300",
            ville="La Chaux-de-Fonds", canton="NE", tel="+41 79 771 46 30",
            email="o.tissot@exemple-mail.ch", etat_civil="marié",
            profession="horloger régleur", employeur="Manufacture Helvétia Watch SA"),
        medecin=KELLER,
        assureur="Suva, agence de La Chaux-de-Fonds",
        police="41-448.712",
        date_rapport="08.06.2026",
        contexte=(
            "Syndrome douloureux régional complexe consécutif à une fracture du poignet "
            "du 03.10.2025. La physiothérapie dépasse le cadre des séances ordinaires : "
            "demande de prise en charge de longue durée."),
        anamnese=(
            "Fracture du radius distal gauche le 03.10.2025, traitée par plâtre pendant "
            "six semaines. Apparition à l'ablation du plâtre de douleurs "
            "disproportionnées, d'un œdème et de troubles vasomoteurs. Diagnostic de "
            "SDRC de type I posé le 08.12.2025. Trente-six séances de physiothérapie "
            "déjà effectuées, avec amélioration lente mais réelle."),
        antecedents=[
            "Aucun antécédent de SDRC",
            "Gaucher contrarié, écrit de la main droite",
        ],
        diagnostics=[
            ("M89.0", "Syndrome douloureux régional complexe de type I, poignet gauche", "08.12.2025"),
            ("S52.5", "Fracture de l'extrémité distale du radius gauche, consolidée", "03.10.2025"),
        ],
        traitements=[
            "Physiothérapie décontracturante et désensibilisation, 2×/semaine depuis 12.2025",
            "Ergothérapie, 1×/semaine",
            "Prégabaline 75 mg, 2×/jour",
            "Bains écossais quotidiens à domicile",
        ],
        consultations=[
            ("02.06.2026",
             "S : douleurs 4/10 contre 8/10 en décembre, allodynie en régression.\n"
             "O : œdème résiduel discret, coloration cutanée normalisée, flexion-"
             "extension du poignet 45/40° contre 20/15° initialement. Préhension fine "
             "possible sur objets de plus de 5 mm.\n"
             "A : SDRC en amélioration lente, sans stabilisation.\n"
             "P : poursuite de la physiothérapie au-delà des séances ordinaires."),
            ("10.03.2026",
             "S : douleurs persistantes, gêne au sommeil.\n"
             "O : allodynie marquée, œdème modéré.\n"
             "A : SDRC actif.\n"
             "P : intensification de la désensibilisation."),
        ],
        incapacites=[("03.10.2025", "", "100 %")],
        accident={
            "date": "03.10.2025", "heure": "17h55",
            "lieu": "Parking de la Manufacture, Rue du Progrès 110, 2300 La Chaux-de-Fonds",
            "description":
                "En quittant son poste, l'assuré a glissé sur une plaque de verglas et "
                "est tombé en arrière, réception sur la main gauche en hyperextension.",
            "temoin": "M. Raphaël Girard, collègue.",
        },
        documents=[
            ("demande-physiotherapie-longue-duree", "Demande de physiothérapie de longue durée",
             "Séances déjà effectuées : 36 depuis le 15.12.2025.\n"
             "Séances supplémentaires demandées : 36, sur six mois.\n"
             "Fréquence : 2 séances hebdomadaires de 45 minutes.\n\n"
             "Justification :\n\n"
             "Le syndrome douloureux régional complexe évolue favorablement mais "
             "lentement. L'interruption de la prise en charge à ce stade exposerait à "
             "une régression documentée dans la littérature, et à une raideur "
             "définitive du poignet.\n\n"
             "Les progrès sont mesurables : EVA passée de 8/10 à 4/10, amplitudes de "
             "flexion-extension passées de 20/15° à 45/40°, reprise de la préhension "
             "fine. Le métier d'horloger régleur exige une motricité fine bimanuelle de "
             "haute précision : la récupération fonctionnelle conditionne directement la "
             "reprise professionnelle.\n\n"
             "Objectifs des six prochains mois :\n"
             "- amplitudes de flexion-extension à 60/55° ;\n"
             "- disparition de l'allodynie ;\n"
             "- reprise de la manipulation d'outils d'horlogerie ;\n"
             "- reprise professionnelle à 50 % visée pour janvier 2027.\n\n"
             "Une réévaluation médicale est prévue tous les trois mois."),
            ("bilan-ergotherapie", "Bilan d'ergothérapie",
             "Bilan du 28.05.2026.\n\n"
             "Force de préhension : 14 kg à gauche contre 42 kg à droite.\n"
             "Pince pouce-index : 3 kg contre 8 kg.\n"
             "Test de Purdue Pegboard : 6 pièces en 30 s à gauche, contre 14 à droite.\n\n"
             "Allodynie mécanique en régression : le seuil de tolérance au contact est "
             "passé du monofilament 2,83 au 4,31.\n\n"
             "Conclusion : progression réelle, insuffisante à ce jour pour un travail "
             "d'horlogerie de précision."),
        ],
        evolution=(
            "Amélioration lente mais continue sur six mois, sans plateau atteint à ce "
            "jour."),
        pronostic=(
            "Réservé à court terme, favorable à douze mois sous réserve de la poursuite "
            "de la rééducation."),
    ),
]
