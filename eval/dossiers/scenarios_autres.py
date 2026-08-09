"""Scénarios LAMal, assurance militaire, LCA, adressages et prescriptions."""

from .praticiens import BRUNNER, FAVRE, MORAND, ROSSIER, SCHMID, VERNET
from .render import Patient, Scenario

SCENARIOS = [
    Scenario(
        form="LAMal_RapportInitial",
        titre="Rapport médical initial LAMal — gonarthrose et prothèse totale",
        patient=Patient(
            nom="MARTIN", prenom="Josiane", sexe="F", naissance="11.08.1963",
            avs="756.2201.9948.12", rue="Avenue du Général-Guisan 52", npa="1009",
            ville="Pully", canton="VD", tel="+41 79 512 30 88",
            email="j.martin@exemple-mail.ch", etat_civil="veuve",
            profession="aide-soignante", employeur="EMS La Colline",
            taux_activite="70 %"),
        medecin=BRUNNER,
        assureur="Assura-Basis SA",
        police="LAMal-4471928",
        date_rapport="24.03.2026",
        contexte=(
            "Gonarthrose tricompartimentale gauche évoluée. Une prothèse totale de genou "
            "est planifiée. L'assureur-maladie demande un rapport médical initial dans le "
            "cadre de la garantie de prise en charge et de l'appréciation de la capacité "
            "de travail."),
        anamnese=(
            "Gonalgies gauches d'apparition progressive depuis 2019, aggravées ces "
            "dix-huit mois. Périmètre de marche réduit à 300 mètres. Douleurs nocturnes "
            "depuis six mois. Échec du traitement conservateur bien conduit : "
            "physiothérapie, antalgiques, trois infiltrations d'acide hyaluronique."),
        antecedents=[
            "Surcharge pondérale, IMC 31",
            "Hypertension artérielle traitée depuis 2014 (I10)",
            "Méniscectomie interne gauche par arthroscopie en 2011",
            "Tabagisme sevré en 2008, 10 UPA",
        ],
        diagnostics=[
            ("M17.1", "Gonarthrose primaire tricompartimentale gauche, stade IV", "14.11.2024"),
            ("I10", "Hypertension artérielle", "22.05.2014"),
            ("E66.9", "Obésité de grade I", "22.05.2014"),
        ],
        traitements=[
            "Lisinopril 20 mg, 1×/jour",
            "Paracétamol 1 g, 3×/jour",
            "Physiothérapie, 1×/semaine",
            "Trois infiltrations d'acide hyaluronique en 2025, sans bénéfice durable",
        ],
        consultations=[
            ("18.03.2026",
             "S : douleurs 7/10 à la marche, réveils nocturnes trois à quatre fois par "
             "semaine. Difficulté croissante à assurer les transferts de résidents.\n"
             "O : flexion 95°, déficit d'extension 5°, varus de 8°, épanchement "
             "modéré, craquements audibles.\n"
             "A : gonarthrose évoluée, traitement conservateur épuisé.\n"
             "P : indication à une prothèse totale de genou, intervention planifiée au "
             "12.05.2026."),
            ("09.12.2025",
             "S : aggravation malgré la troisième infiltration.\n"
             "O : périmètre de marche 300 m, boiterie d'esquive.\n"
             "A : échec du traitement conservateur.\n"
             "P : bilan préopératoire."),
        ],
        incapacites=[("01.02.2026", "11.05.2026", "50 %"),
                     ("12.05.2026", "31.08.2026", "100 %")],
        documents=[
            ("radiographies-genou", "Compte rendu radiologique",
             "Radiographies du genou gauche en charge, face, profil et défilé fémoro-"
             "patellaire, du 05.03.2026.\n\n"
             "Pincement complet de l'interligne fémoro-tibial interne, avec contact os "
             "contre os. Ostéophytose marginale marquée. Géodes sous-chondrales "
             "tibiales internes. Pincement fémoro-patellaire modéré. Axe mécanique en "
             "varus de 8°.\n\n"
             "Conclusion : gonarthrose tricompartimentale à prédominance interne, stade "
             "IV de Kellgren-Lawrence."),
            ("planification-operatoire", "Planification opératoire",
             "Intervention prévue le 12.05.2026 à la Clinique Cecil, Lausanne.\n\n"
             "Prothèse totale de genou gauche cimentée, à plateau fixe, avec resurfaçage "
             "rotulien. Correction de l'axe mécanique visée à 0°.\n\n"
             "Durée d'hospitalisation prévue : 6 jours, suivis de trois semaines de "
             "réadaptation musculo-squelettique stationnaire.\n\n"
             "Bilan préopératoire du 05.03.2026 sans particularité : hémoglobine "
             "134 g/L, créatinine 71 µmol/L, ECG en rythme sinusal, consultation "
             "d'anesthésie ASA II.\n\n"
             "Capacité de travail : incapacité totale prévisible de trois mois à compter "
             "de l'intervention, puis reprise progressive. L'activité d'aide-soignante, "
             "qui impose des transferts de charge et une station debout prolongée, "
             "nécessitera une réévaluation à six mois."),
        ],
        pronostic=(
            "Bon. Reprise de l'activité à 70 % attendue vers septembre 2026, sous "
            "réserve de l'évolution fonctionnelle."),
    ),

    Scenario(
        form="LAM_FeuilleMaladieAccident",
        titre="Feuille de maladie/accident — assurance militaire",
        patient=Patient(
            nom="BAUMGARTNER", prenom="Yannick", sexe="M", naissance="02.02.2005",
            avs="756.6690.1123.48", rue="Rue des Alpes 4", npa="1700",
            ville="Fribourg", canton="FR", tel="+41 79 850 22 17",
            email="y.baumgartner@exemple-mail.ch", etat_civil="célibataire",
            profession="apprenti électricien, recrue", employeur="École de recrues, Payerne"),
        medecin=MORAND,
        assureur="Assurance militaire (Suva AM), Lucerne",
        police="AM-2026-114872",
        date_rapport="09.04.2026",
        contexte=(
            "Affection survenue pendant le service militaire, à l'école de recrues. "
            "L'annonce à l'assurance militaire est faite au moyen de la feuille de "
            "maladie/accident."),
        anamnese=(
            "Douleur aiguë du genou droit survenue lors d'une marche au pas cadencé avec "
            "sac de 25 kg, au cours de la troisième semaine d'école de recrues. Douleur "
            "antérieure, majorée à la descente et à l'accroupissement. Pas de traumatisme "
            "direct, pas de blocage ni de dérobement."),
        antecedents=[
            "Aucun antécédent de pathologie du genou",
            "Pratique du football en junior jusqu'en 2023",
            "Aptitude au service confirmée au recrutement en 09.2024",
        ],
        diagnostics=[
            ("M76.5", "Tendinopathie rotulienne droite d'effort", "07.04.2026"),
            ("M79.6", "Douleur du membre inférieur droit", "07.04.2026"),
        ],
        traitements=[
            "Repos relatif, dispense de marche et de course pour quatorze jours",
            "Glaçage 3×/jour",
            "Ibuprofène 400 mg, 3×/jour pendant cinq jours",
            "Physiothérapie de renforcement excentrique, 2×/semaine",
        ],
        consultations=[
            ("09.04.2026",
             "S : douleur 5/10 à la descente d'escalier, absente au repos.\n"
             "O : douleur exquise à la pointe de la rotule, test de Kujala 68/100, "
             "pas d'épanchement, ligaments stables.\n"
             "A : tendinopathie rotulienne d'effort, liée à la charge d'entraînement.\n"
             "P : dispense de marche au pas et de course pour quatorze jours, service "
             "adapté en salle. Physiothérapie."),
            ("07.04.2026",
             "S : douleur apparue en fin de marche de 20 km.\n"
             "O : boiterie, douleur à la palpation du tendon rotulien.\n"
             "A : surcharge d'effort.\n"
             "P : arrêt des activités physiques, consultation de contrôle à 48 h."),
        ],
        documents=[
            ("attestation-service", "Attestation de service",
             "Incorporation : École de recrues 12-1/2026, place d'armes de Payerne.\n"
             "Entrée en service : 16.03.2026.\n"
             "Fonction : soldat d'infanterie mécanisée.\n\n"
             "L'affection est survenue le 07.04.2026, pendant le service, au cours d'une "
             "marche d'entraînement de 20 km avec charge réglementaire de 25 kg.\n\n"
             "Le militaire est resté incorporé. Service adapté ordonné du 09.04.2026 au "
             "23.04.2026 : dispense de marche, de course et de port de charge, activités "
             "de salle et instruction théorique maintenues.\n\n"
             "Aucune incapacité de travail civile n'est à attester : l'intéressé est "
             "apprenti et son contrat est suspendu pendant le service."),
        ],
        evolution=(
            "Amélioration attendue sous décharge relative et rééducation excentrique."),
        pronostic=(
            "Favorable. Reprise progressive des activités physiques militaires envisagée "
            "à trois semaines, avec réintégration complète avant la fin de l'école."),
    ),

    Scenario(
        form="LAM_RapportIntermediaire",
        titre="Rapport intermédiaire — assurance militaire",
        patient=Patient(
            nom="RUFFIEUX", prenom="Damien", sexe="M", naissance="21.09.2001",
            avs="756.3348.7790.26", rue="Grand-Rue 41", npa="1630",
            ville="Bulle", canton="FR", tel="+41 78 227 65 90",
            email="d.ruffieux@exemple-mail.ch", etat_civil="célibataire",
            profession="mécanicien sur automobiles", employeur="Garage du Moléson SA"),
        medecin=BRUNNER,
        assureur="Assurance militaire (Suva AM), Lucerne",
        police="AM-2025-098331",
        date_rapport="18.05.2026",
        contexte=(
            "Affection dorsale reconnue par l'assurance militaire à la suite d'un cours "
            "de répétition en 09.2025. Un rapport intermédiaire est demandé huit mois "
            "après l'annonce initiale, pour apprécier l'évolution et le droit aux "
            "prestations."),
        anamnese=(
            "Lombalgie aiguë survenue le 15.09.2025 lors du chargement de matériel lourd "
            "pendant un cours de répétition. Évolution vers une lombalgie chronique avec "
            "irradiation sciatique gauche intermittente. Traitement conservateur "
            "poursuivi depuis huit mois, avec amélioration partielle."),
        antecedents=[
            "Lombalgies mécaniques épisodiques depuis 2022, sans arrêt de travail",
            "Aucun antécédent chirurgical",
        ],
        diagnostics=[
            ("M54.5", "Lombalgie chronique", "15.09.2025"),
            ("M51.2", "Discopathie L5-S1 avec protrusion", "12.11.2025"),
        ],
        traitements=[
            "Physiothérapie, 1×/semaine depuis 10.2025",
            "École du dos suivie en 01.2026",
            "Paracétamol et AINS en réserve",
            "Adaptation du poste de travail depuis 02.2026",
        ],
        consultations=[
            ("12.05.2026",
             "S : douleurs 3/10 en moyenne, épisodes aigus une fois par mois. Sciatalgie "
             "gauche devenue rare.\n"
             "O : Schober 4,5 cm, Lasègue négatif, pas de déficit neurologique.\n"
             "A : amélioration nette depuis le rapport initial.\n"
             "P : poursuite de l'entretien musculaire, reprise à 100 % dès le "
             "01.06.2026."),
            ("14.01.2026",
             "S : douleurs persistantes, gênantes en position penchée.\n"
             "O : contracture paravertébrale, Schober 3 cm.\n"
             "A : lombalgie chronique en cours d'amélioration.\n"
             "P : école du dos, reprise à 50 %."),
        ],
        incapacites=[("15.09.2025", "31.12.2025", "100 %"),
                     ("01.01.2026", "31.05.2026", "50 %")],
        documents=[
            ("irm-lombaire", "Rapport d'imagerie",
             "IRM lombaire du 12.11.2025.\n\n"
             "Discopathie dégénérative L5-S1 avec perte de hauteur discale et "
             "déshydratation. Protrusion discale postérieure médiane de 4 mm, sans "
             "conflit radiculaire net. Pas de sténose canalaire. Articulaires "
             "postérieures sans arthrose significative.\n\n"
             "Conclusion : discopathie L5-S1, sans indication chirurgicale."),
            ("evolution-huit-mois", "Synthèse de l'évolution à huit mois",
             "Situation lors de l'annonce initiale (09.2025) : lombalgie aiguë "
             "invalidante, EVA 8/10, incapacité totale, Schober à 2 cm.\n\n"
             "Situation actuelle (05.2026) : EVA moyenne 3/10, épisodes aigus mensuels, "
             "Schober à 4,5 cm, Lasègue négatif, activité professionnelle reprise à "
             "50 % depuis janvier.\n\n"
             "Le poste de mécanicien a été adapté : élévateur systématique pour les "
             "travaux sous véhicule, interdiction de port de charge supérieure à 20 kg "
             "sans aide.\n\n"
             "Une reprise à 100 % est possible dès le 01.06.2026, avec maintien des "
             "adaptations de poste. Aucune séquelle durable n'est attendue. Le suivi peut "
             "être clos à trois mois si l'évolution se confirme."),
        ],
        evolution="Amélioration franche et régulière sur huit mois.",
        pronostic=(
            "Favorable. Pas de séquelle durable attendue, sous réserve du maintien des "
            "adaptations de poste."),
    ),

    Scenario(
        form="LCA_IncapaciteTravail",
        titre="Certificat médical d'incapacité de travail pour assureur-vie",
        patient=Patient(
            nom="NICOLET", prenom="Fabienne", sexe="F", naissance="06.01.1981",
            avs="756.7714.2265.03", rue="Chemin des Ramiers 9", npa="1260",
            ville="Nyon", canton="VD", tel="+41 79 348 71 22",
            email="f.nicolet@exemple-mail.ch", etat_civil="mariée",
            profession="responsable des ressources humaines", employeur="Groupe Lémanic SA"),
        medecin=FAVRE,
        assureur="Bâloise Vie SA",
        police="LCA-VIE-772.309.14",
        date_rapport="27.05.2026",
        contexte=(
            "Assurance perte de gain en cas de maladie souscrite à titre privé. "
            "L'assureur-vie demande un certificat médical détaillé après quatre mois "
            "d'incapacité de travail."),
        anamnese=(
            "Épuisement professionnel installé sur dix-huit mois, dans un contexte de "
            "restructuration et de conduite de plans sociaux. Décompensation le "
            "26.01.2026 : crise anxieuse aiguë sur le lieu de travail, arrêt immédiat. "
            "Troubles du sommeil, ruminations, anhédonie, perte de 6 kg en deux mois."),
        antecedents=[
            "Aucun antécédent psychiatrique",
            "Thyroïdite de Hashimoto substituée depuis 2017 (E06.3)",
            "Deux accouchements par voie basse, 2010 et 2013",
        ],
        diagnostics=[
            ("F32.2", "Épisode dépressif sévère sans symptômes psychotiques", "26.01.2026"),
            ("F41.0", "Trouble panique", "26.01.2026"),
            ("Z73.0", "Épuisement professionnel", "26.01.2026"),
            ("E06.3", "Thyroïdite auto-immune substituée", "09.03.2017"),
        ],
        traitements=[
            "Sertraline 100 mg, 1×/jour depuis le 02.02.2026",
            "Trazodone 50 mg au coucher",
            "Psychothérapie hebdomadaire depuis le 03.02.2026",
            "Euthyrox 100 µg, 1×/jour",
        ],
        consultations=[
            ("20.05.2026",
             "S : sommeil amélioré, crises de panique espacées à une par mois. "
             "Ruminations professionnelles persistantes.\n"
             "O : MADRS 19, contre 32 en février. Pas d'idéation suicidaire. Reprise du "
             "poids, +3 kg.\n"
             "A : amélioration partielle sous traitement.\n"
             "P : poursuite du traitement, incapacité maintenue à 100 %, réévaluation "
             "dans six semaines."),
            ("25.03.2026",
             "S : persistance de l'anhédonie, évitement de tout contact professionnel.\n"
             "O : MADRS 26.\n"
             "A : réponse partielle au traitement.\n"
             "P : majoration de la sertraline à 100 mg."),
            ("26.01.2026",
             "S : crise anxieuse aiguë au travail, sentiment de perte de contrôle.\n"
             "O : tachycardie, tremblements, pleurs. MADRS 32.\n"
             "A : décompensation dépressive et anxieuse.\n"
             "P : arrêt de travail immédiat, introduction de sertraline 50 mg."),
        ],
        incapacites=[("26.01.2026", "", "100 %")],
        documents=[
            ("evaluation-capacite-lca", "Évaluation de la capacité de travail",
             "Profession exercée : responsable des ressources humaines, à 100 %, avec "
             "conduite d'équipe de six personnes et gestion de procédures de "
             "licenciement.\n\n"
             "Taux d'occupation avant l'incapacité : 42 heures par semaine, 5 jours par "
             "semaine.\n\n"
             "Début de l'incapacité de travail : 26.01.2026.\n"
             "Taux et périodes : 100 % du 26.01.2026 à ce jour, sans interruption.\n\n"
             "Le traitement ambulatoire est assuré par la soussignée depuis le "
             "03.02.2026. Aucun traitement n'était en cours auparavant pour cette "
             "affection.\n\n"
             "Limitations fonctionnelles : intolérance au stress et aux conflits, "
             "fatigabilité cognitive, difficulté de concentration au-delà de trente "
             "minutes, évitement des situations d'exposition sociale professionnelle.\n\n"
             "Une reprise dans la fonction d'origine n'est pas exigible avant six mois. "
             "Une activité adaptée, sans responsabilité hiérarchique ni gestion de "
             "conflit, pourrait être envisagée à 30 % dès septembre 2026.\n\n"
             "Facteurs extra-médicaux : conflit avec la direction, procédure "
             "prud'homale en cours, susceptibles d'influencer l'évolution."),
        ],
        evolution=(
            "Amélioration lente mais réelle sous traitement combiné, MADRS passé de 32 "
            "à 19 en quatre mois."),
        pronostic=(
            "Réservé à court terme. Une reprise progressive en activité adaptée est "
            "envisageable à l'automne 2026."),
    ),

    Scenario(
        form="Adressage_Angiologie",
        titre="Adressage en angiologie — claudication intermittente",
        patient=Patient(
            nom="CHEVALLEY", prenom="Roger", sexe="M", naissance="18.11.1957",
            avs="756.8802.3317.71", rue="Route de Cossonay 118", npa="1008",
            ville="Prilly", canton="VD", tel="+41 79 601 44 02",
            email="r.chevalley@exemple-mail.ch", etat_civil="marié",
            profession="retraité, ancien maçon", taux_activite="—"),
        medecin=VERNET,
        assureur="CSS Assurance-maladie SA",
        police="LAMal-8823041",
        date_rapport="16.04.2026",
        contexte=(
            "Suspicion d'artériopathie oblitérante des membres inférieurs. Le patient est "
            "adressé en angiologie pour bilan hémodynamique et avis thérapeutique."),
        anamnese=(
            "Douleurs à type de crampe du mollet droit à la marche, apparaissant après "
            "environ 200 mètres sur terrain plat et cédant en deux minutes à l'arrêt. "
            "Évolution sur douze mois avec réduction progressive du périmètre de marche. "
            "Pas de douleur de décubitus, pas de trouble trophique."),
        antecedents=[
            "Tabagisme 45 UPA, actif, 15 cigarettes par jour",
            "Diabète de type 2 depuis 2011, sous metformine (E11.9)",
            "Dyslipidémie sous atorvastatine (E78.5)",
            "Hypertension artérielle depuis 2009 (I10)",
            "Infarctus du myocarde inférieur en 2018, stent sur la coronaire droite",
        ],
        diagnostics=[
            ("I70.2", "Suspicion d'artériopathie oblitérante des membres inférieurs, stade IIa", "10.04.2026"),
            ("I25.1", "Cardiopathie ischémique, status après infarctus", "04.05.2018"),
            ("E11.9", "Diabète de type 2", "17.03.2011"),
            ("I10", "Hypertension artérielle", "20.08.2009"),
        ],
        traitements=[
            "Aspirine cardio 100 mg, 1×/jour",
            "Atorvastatine 40 mg, 1×/jour",
            "Metformine 1000 mg, 2×/jour",
            "Lisinopril 10 mg, 1×/jour",
            "Métoprolol 50 mg, 1×/jour",
        ],
        consultations=[
            ("10.04.2026",
             "S : périmètre de marche réduit à 200 m, crampe du mollet droit.\n"
             "O : pouls fémoraux perçus, poplités faibles, pédieux et tibiaux postérieurs "
             "non perçus à droite. Peau sèche, pas d'ulcère. Temps de recoloration "
             "3 s au gros orteil droit.\n"
             "A : claudication intermittente droite, suspicion d'AOMI.\n"
             "P : mesure de l'index cheville-bras, adressage en angiologie."),
        ],
        documents=[
            ("demande-consultation-angiologie", "Demande de consultation spécialisée",
             "Motif de l'adressage : claudication intermittente du membre inférieur "
             "droit, périmètre de marche 200 mètres, suspicion d'artériopathie "
             "oblitérante chez un patient à haut risque cardio-vasculaire.\n\n"
             "Question posée au spécialiste :\n"
             "1. Confirmer le diagnostic d'AOMI et en préciser le stade et le niveau "
             "lésionnel.\n"
             "2. Y a-t-il une indication à une revascularisation, endovasculaire ou "
             "chirurgicale ?\n"
             "3. Le traitement médical actuel est-il optimal ?\n\n"
             "Degré d'urgence : semi-urgent, consultation souhaitée dans les quatre "
             "semaines.\n\n"
             "Index cheville-bras mesuré au cabinet le 10.04.2026 : 0,62 à droite, 0,91 "
             "à gauche.\n\n"
             "Examens joints : bilan lipidique et HbA1c du 02.04.2026, ECG de repos du "
             "10.04.2026, rapport de coronarographie de 2018."),
            ("bilan-biologique", "Bilan biologique",
             "Prélèvement du 02.04.2026, à jeun.\n\n"
             "HbA1c : 7,4 % (cible < 7,0 %)\n"
             "Cholestérol total : 4,8 mmol/L\n"
             "LDL-cholestérol : 2,6 mmol/L (cible < 1,4 mmol/L chez ce patient)\n"
             "HDL-cholestérol : 1,0 mmol/L\n"
             "Triglycérides : 2,1 mmol/L\n"
             "Créatinine : 94 µmol/L, DFG estimé 76 mL/min/1,73 m²\n"
             "Hémoglobine : 141 g/L\n\n"
             "Commentaire : LDL au-dessus de la cible en prévention secondaire, contrôle "
             "glycémique insuffisant. Une intensification du traitement hypolipémiant "
             "est à discuter."),
        ],
        pronostic=(
            "Dépend du bilan angiologique. Le sevrage tabagique et l'optimisation du "
            "traitement médical restent les mesures les plus déterminantes."),
    ),

    Scenario(
        form="Adressage_Cardiologie",
        titre="Adressage en cardiologie — angor d'effort",
        patient=Patient(
            nom="PERRIN", prenom="Anne-Lise", sexe="F", naissance="29.05.1969",
            avs="756.5527.8834.19", rue="Rue de la Paix 33", npa="1400",
            ville="Yverdon-les-Bains", canton="VD", tel="+41 78 902 37 55",
            email="al.perrin@exemple-mail.ch", etat_civil="mariée",
            profession="enseignante primaire", employeur="Établissement scolaire d'Yverdon"),
        medecin=VERNET,
        assureur="Groupe Mutuel Assurances SA",
        police="LAMal-6619203",
        date_rapport="05.05.2026",
        contexte=(
            "Douleurs thoraciques d'effort d'apparition récente chez une patiente "
            "présentant plusieurs facteurs de risque. Adressage en cardiologie pour "
            "évaluation d'une maladie coronarienne."),
        anamnese=(
            "Depuis six semaines, oppression rétrosternale survenant à la montée d'un "
            "étage ou lors d'une marche rapide, avec irradiation dans la mâchoire, cédant "
            "en trois à cinq minutes à l'arrêt de l'effort. Pas de douleur au repos. Un "
            "épisode nocturne isolé le 28.04.2026, spontanément résolutif."),
        antecedents=[
            "Hypertension artérielle depuis 2018, traitée (I10)",
            "Dyslipidémie non traitée jusqu'à ce jour",
            "Ménopause depuis 2020, sans traitement hormonal",
            "Père décédé d'un infarctus à 58 ans",
            "Non-fumeuse",
        ],
        diagnostics=[
            ("I20.8", "Angor d'effort, suspicion de maladie coronarienne", "05.05.2026"),
            ("I10", "Hypertension artérielle", "11.06.2018"),
            ("E78.5", "Dyslipidémie", "05.05.2026"),
        ],
        traitements=[
            "Amlodipine 5 mg, 1×/jour",
            "Aspirine cardio 100 mg, 1×/jour, introduite ce jour",
            "Atorvastatine 40 mg, 1×/jour, introduite ce jour",
            "Trinitrine sublinguale en réserve",
        ],
        consultations=[
            ("05.05.2026",
             "S : oppression thoracique d'effort, reproductible, depuis six semaines. "
             "Un épisode nocturne isolé.\n"
             "O : TA 148/88 mmHg, FC 76/min régulière, auscultation cardiaque sans "
             "souffle, pas de signe d'insuffisance cardiaque. IMC 27.\n"
             "A : angor d'effort stable, probabilité pré-test intermédiaire.\n"
             "P : introduction d'aspirine et de statine, adressage en cardiologie, "
             "consignes de recours aux urgences en cas de douleur prolongée."),
        ],
        documents=[
            ("demande-consultation-cardiologie", "Demande de consultation spécialisée",
             "Motif de l'adressage : angor d'effort d'apparition récente, probabilité "
             "pré-test intermédiaire de maladie coronarienne.\n\n"
             "Question posée au spécialiste :\n"
             "1. Confirmer ou infirmer une maladie coronarienne obstructive.\n"
             "2. Quelle stratégie d'imagerie privilégier — coroscanner ou test "
             "fonctionnel ?\n"
             "3. Adapter le traitement anti-ischémique.\n\n"
             "Degré d'urgence : consultation souhaitée dans les dix jours. Un épisode "
             "nocturne fait craindre une évolution vers un angor instable.\n\n"
             "Examens joints : ECG de repos du 05.05.2026, bilan biologique du "
             "30.04.2026.\n\n"
             "Traitement introduit ce jour : aspirine 100 mg et atorvastatine 40 mg. "
             "La patiente a reçu des consignes écrites de recours aux urgences."),
            ("ecg-biologie", "ECG et bilan biologique",
             "ECG de repos du 05.05.2026 : rythme sinusal régulier à 76/min, axe normal, "
             "pas de trouble de la repolarisation, pas d'onde Q pathologique. QTc "
             "412 ms.\n\n"
             "Bilan du 30.04.2026 :\n"
             "Cholestérol total 6,4 mmol/L, LDL 4,1 mmol/L, HDL 1,4 mmol/L, "
             "triglycérides 1,8 mmol/L.\n"
             "HbA1c 5,6 %. Créatinine 68 µmol/L. TSH 2,1 mUI/L.\n"
             "Troponine hs T : 6 ng/L (norme < 14).\n\n"
             "Commentaire : dyslipidémie non traitée, troponine négative en dehors des "
             "épisodes douloureux."),
        ],
        pronostic=(
            "Dépend du bilan cardiologique. La prise en charge des facteurs de risque a "
            "été engagée."),
    ),

    Scenario(
        form="Gyneco_AnnonceMaternite",
        titre="Annonce de maternité",
        patient=Patient(
            nom="DA SILVA", prenom="Carla", sexe="F", naissance="12.07.1995",
            avs="756.4419.7702.83", rue="Avenue de Morges 104", npa="1004",
            ville="Lausanne", canton="VD", tel="+41 76 481 33 09",
            email="c.dasilva@exemple-mail.ch", etat_civil="mariée",
            profession="vendeuse en boulangerie", employeur="Boulangerie du Centre Sàrl",
            taux_activite="80 %"),
        medecin=ROSSIER,
        assureur="Sanitas Assurance-maladie SA",
        police="LAMal-3308827",
        date_rapport="23.04.2026",
        contexte=(
            "Grossesse évolutive de 12 semaines d'aménorrhée, confirmée par échographie. "
            "Annonce de maternité à l'assureur en vue de la prise en charge des "
            "prestations de maternité."),
        anamnese=(
            "Première grossesse, spontanée, désirée. Dernières règles le 29.01.2026, "
            "cycles réguliers de 28 jours. Terme calculé au 05.11.2026. Nausées "
            "matinales modérées au premier trimestre, en régression. Pas de métrorragie, "
            "pas de contraction."),
        antecedents=[
            "Gestité 1, parité 0",
            "Aucun antécédent chirurgical",
            "Sérologie rubéole immune, toxoplasmose non immune",
            "Groupe sanguin A Rhésus positif",
            "Non-fumeuse, pas de consommation d'alcool",
        ],
        diagnostics=[
            ("Z34.0", "Surveillance d'une première grossesse normale", "23.04.2026"),
            ("O21.0", "Vomissements légers de la grossesse", "12.03.2026"),
        ],
        traitements=[
            "Acide folique 0,4 mg/jour depuis le 15.02.2026",
            "Vitamine D 800 UI/jour",
            "Conseils diététiques, prévention de la toxoplasmose",
        ],
        consultations=[
            ("23.04.2026",
             "S : nausées en régression, pas de saignement, mouvements non encore "
             "perçus.\n"
             "O : TA 108/68 mmHg, poids 62 kg (+1 kg), hauteur utérine non mesurable à "
             "ce terme. Échographie : embryon unique, LCC 58 mm, activité cardiaque "
             "présente à 158/min, clarté nucale 1,4 mm.\n"
             "A : grossesse évolutive de 12 SA + 2 jours, normale.\n"
             "P : test combiné du premier trimestre, contrôle à 16 SA."),
            ("12.03.2026",
             "S : test de grossesse positif, nausées matinales.\n"
             "O : examen gynécologique sans particularité.\n"
             "A : grossesse débutante.\n"
             "P : bilan sanguin, acide folique, échographie de datation."),
        ],
        documents=[
            ("suivi-grossesse", "Feuille de suivi de grossesse",
             "Date des dernières règles : 29.01.2026.\n"
             "Terme prévu : 05.11.2026.\n"
             "Âge gestationnel au jour du rapport : 12 semaines d'aménorrhée + 2 jours.\n"
             "Grossesse unique, spontanée.\n\n"
             "Échographie du 23.04.2026 : longueur cranio-caudale 58 mm, activité "
             "cardiaque 158/min, clarté nucale 1,4 mm, os propres du nez présents. "
             "Datation concordante avec la date des dernières règles.\n\n"
             "Bilan sérologique du 12.03.2026 : rubéole immune, toxoplasmose non "
             "immune, syphilis négative, VIH négatif, hépatite B négative. Groupe A "
             "Rhésus positif, RAI négatives.\n\n"
             "Suivi prévu : consultations mensuelles jusqu'à 32 SA, puis bimensuelles. "
             "Échographies morphologiques prévues à 22 et 32 SA. Accouchement prévu à la "
             "Maternité du CHUV.\n\n"
             "Aucun facteur de risque identifié à ce stade. Grossesse à bas risque."),
        ],
        pronostic="Grossesse à bas risque, suivi standard.",
    ),

    Scenario(
        form="Prescription_EnseignementDiabete",
        titre="Prescription d'enseignement thérapeutique du diabète",
        patient=Patient(
            nom="AMSTUTZ", prenom="Werner", sexe="M", naissance="03.02.1972",
            avs="756.6035.4419.28", rue="Chemin du Levant 6", npa="1005",
            ville="Lausanne", canton="VD", tel="+41 79 447 12 66",
            email="w.amstutz@exemple-mail.ch", etat_civil="marié",
            profession="chauffeur de bus", employeur="Transports publics lausannois"),
        medecin=VERNET,
        assureur="Visana Assurance SA",
        police="LAMal-5540912",
        date_rapport="12.05.2026",
        contexte=(
            "Diabète de type 2 nouvellement diagnostiqué, avec passage à l'insuline. "
            "Prescription d'un enseignement thérapeutique structuré, remboursé par "
            "l'assurance de base sur ordonnance médicale."),
        anamnese=(
            "Diabète de type 2 découvert le 18.03.2026 devant une polyurie, une "
            "polydipsie et une perte de 7 kg en trois mois. HbA1c initiale à 10,8 %. "
            "Metformine introduite d'emblée, insuffisante : passage à une insulinothérapie "
            "basale le 28.04.2026. Le patient n'a jamais reçu d'enseignement structuré et "
            "exerce une profession à risque en cas d'hypoglycémie."),
        antecedents=[
            "Surcharge pondérale, IMC 32",
            "Hypertension artérielle depuis 2020 (I10)",
            "Stéatose hépatique découverte en 2023",
            "Père diabétique de type 2",
            "Tabagisme 20 UPA, sevré en 2019",
        ],
        diagnostics=[
            ("E11.9", "Diabète de type 2, sans complication documentée", "18.03.2026"),
            ("I10", "Hypertension artérielle", "07.09.2020"),
            ("E66.9", "Obésité de grade I", "07.09.2020"),
        ],
        traitements=[
            "Metformine 1000 mg, 2×/jour depuis le 18.03.2026",
            "Insuline glargine 18 UI au coucher depuis le 28.04.2026",
            "Lisinopril 10 mg, 1×/jour",
            "Autosurveillance glycémique, 2 mesures par jour",
        ],
        consultations=[
            ("12.05.2026",
             "S : glycémies à jeun entre 8 et 11 mmol/L, deux épisodes de sueurs "
             "matinales non mesurées. Technique d'injection incertaine.\n"
             "O : poids 96 kg, TA 138/84 mmHg. Pieds : sensibilité au monofilament "
             "conservée, pas de lésion. Sites d'injection : début de lipohypertrophie "
             "ombilicale.\n"
             "A : équilibre glycémique insuffisant, éducation thérapeutique lacunaire, "
             "profession exposée au risque hypoglycémique.\n"
             "P : prescription d'un enseignement thérapeutique structuré."),
            ("28.04.2026",
             "S : HbA1c de contrôle à 9,4 % malgré la metformine à dose maximale.\n"
             "O : poids 97 kg.\n"
             "A : contrôle insuffisant sous monothérapie.\n"
             "P : introduction d'une insuline basale, autosurveillance."),
        ],
        documents=[
            ("prescription-enseignement", "Prescription d'enseignement thérapeutique",
             "Prestation prescrite : enseignement thérapeutique structuré du diabète, "
             "dispensé par une infirmière spécialisée en diabétologie.\n\n"
             "Nombre de séances : 10 séances individuelles.\n"
             "Durée : 60 minutes par séance.\n"
             "Rythme : hebdomadaire pendant 6 semaines, puis bimensuel.\n\n"
             "Contenu :\n"
             "- physiopathologie du diabète de type 2 et objectifs glycémiques ;\n"
             "- technique d'injection de l'insuline, rotation des sites, prévention des "
             "lipohypertrophies ;\n"
             "- autosurveillance glycémique, tenue du carnet, interprétation ;\n"
             "- reconnaissance et correction de l'hypoglycémie — point critique compte "
             "tenu de la profession de chauffeur de bus et des obligations liées au "
             "permis professionnel ;\n"
             "- alimentation et équivalences glucidiques ;\n"
             "- activité physique adaptée ;\n"
             "- soins des pieds et prévention des complications.\n\n"
             "Objectifs mesurables à six mois : HbA1c inférieure à 7,5 %, absence "
             "d'hypoglycémie sévère, autonomie complète dans la gestion de l'insuline.\n\n"
             "Prestataire : consultation infirmière en diabétologie, Policlinique "
             "médicale universitaire, Lausanne."),
            ("bilan-biologique-diabete", "Bilan biologique",
             "Évolution des paramètres :\n\n"
             "18.03.2026 — HbA1c 10,8 %, glycémie à jeun 14,2 mmol/L, créatinine "
             "82 µmol/L, DFG 89 mL/min/1,73 m².\n"
             "28.04.2026 — HbA1c 9,4 %, glycémie à jeun 11,1 mmol/L.\n"
             "08.05.2026 — glycémie à jeun 9,6 mmol/L, rapport albumine/créatinine "
             "urinaire 1,8 mg/mmol (normal).\n\n"
             "Bilan lipidique du 18.03.2026 : LDL 3,2 mmol/L, HDL 0,9 mmol/L, "
             "triglycérides 3,4 mmol/L.\n\n"
             "Fond d'œil du 22.04.2026 : pas de rétinopathie diabétique."),
        ],
        pronostic=(
            "Bon sous réserve de l'acquisition de l'autonomie thérapeutique. Le maintien "
            "du permis professionnel dépend de l'absence d'hypoglycémie sévère."),
    ),
]
