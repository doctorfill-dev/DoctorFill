"""Scénarios des formulaires de l'assurance-invalidité (LAI)."""

from .praticiens import BRUNNER, FAVRE, KELLER, VERNET
from .render import Patient, Scenario

SCENARIOS = [
    Scenario(
        form="AI_MoyensAuxiliaires",
        titre="Demande de moyens auxiliaires AI — prothèse tibiale",
        patient=Patient(
            nom="MERCIER", prenom="Sylvie", sexe="F", naissance="22.09.1968",
            avs="756.3312.8845.07", rue="Chemin des Vignes 4", npa="1095",
            ville="Lutry", canton="VD", tel="+41 79 224 61 03",
            email="s.mercier@exemple-mail.ch", etat_civil="mariée",
            profession="assistante en pharmacie", employeur="Pharmacie du Bourg SA",
            taux_activite="80 %"),
        medecin=BRUNNER,
        assureur="Office AI du canton de Vaud",
        police="AI-VD-2024-118ّ340".replace("ّ", ""),
        date_rapport="14.05.2026",
        contexte=(
            "Une procédure AI est ouverte depuis le 03.02.2026. La patiente, amputée "
            "de jambe gauche au niveau transtibial après un accident de la voie publique, "
            "sollicite la prise en charge d'une prothèse définitive et d'un fauteuil "
            "roulant de transfert. Le présent dossier accompagne la demande de moyens "
            "auxiliaires."),
        anamnese=(
            "Accident de la voie publique le 11.11.2025 : collision voiture-scooter, "
            "fracture ouverte Gustilo III-C de la jambe gauche. Amputation transtibiale "
            "gauche réalisée en urgence différée le 15.11.2025 au CHUV après échec de "
            "revascularisation. Suites opératoires simples, cicatrisation du moignon "
            "acquise à six semaines. Appareillage provisoire depuis le 20.01.2026, "
            "toléré, avec périmètre de marche actuel de 400 mètres avec une canne."),
        antecedents=[
            "Hypothyroïdie substituée depuis 2011 (E03.9)",
            "Césarienne en 2001",
            "Pas de diabète, pas d'artériopathie",
        ],
        diagnostics=[
            ("S88.1", "Amputation transtibiale gauche post-traumatique", "15.11.2025"),
            ("Z89.5", "Absence acquise de la jambe au-dessous du genou", "15.11.2025"),
            ("E03.9", "Hypothyroïdie substituée", "04.06.2011"),
        ],
        traitements=[
            "Euthyrox 75 µg, 1×/jour",
            "Physiothérapie de rééducation à la marche, 2×/semaine",
            "Suivi prothétique au centre d'appareillage, toutes les 3 semaines",
        ],
        consultations=[
            ("06.05.2026",
             "S : marche 400 m avec canne simple, douleurs de moignon cotées 2/10 en fin "
             "de journée. Pas de douleur fantôme invalidante.\n"
             "O : moignon bien cicatrisé, volume stabilisé depuis 6 semaines, pas de "
             "conflit d'emboîture. Force quadricipitale 5/5.\n"
             "A : appareillage provisoire arrivé au terme de son utilité, volume stable.\n"
             "P : demande de prothèse définitive avec pied à restitution d'énergie, et "
             "fauteuil roulant de transfert pour les déplacements longs."),
            ("18.03.2026",
             "S : progression régulière, autonomie au domicile acquise.\n"
             "O : périmètre de marche 250 m, appui monopodal 8 s.\n"
             "A : évolution favorable.\n"
             "P : poursuite de la physiothérapie, réévaluation dans 6 semaines."),
        ],
        incapacites=[("11.11.2025", "31.03.2026", "100 %"),
                     ("01.04.2026", "", "50 %")],
        documents=[
            ("prescription-appareillage", "Prescription d'appareillage",
             "Moyens auxiliaires sollicités auprès de l'AI :\n\n"
             "1. Prothèse tibiale définitive gauche, emboîture à contact total, manchon "
             "en silicone, pied à restitution d'énergie de classe 3. Nécessaire à la "
             "reprise de l'activité professionnelle en station debout prolongée.\n"
             "2. Fauteuil roulant manuel de transfert, pour les déplacements de plus de "
             "500 mètres et les jours de douleur de moignon.\n"
             "3. Deux manchons de rechange par an.\n\n"
             "Fournisseur pressenti : Centre d'appareillage orthopédique de Lausanne.\n"
             "Devis établi le 28.04.2026 : CHF 18 400.— pour la prothèse, CHF 2 150.— "
             "pour le fauteuil.\n\n"
             "Le moyen auxiliaire est indispensable à la poursuite de l'activité "
             "lucrative et à l'accomplissement des travaux habituels. La patiente a "
             "repris son activité à 50 % depuis le 01.04.2026 et vise un retour à 80 %."),
            ("rapport-centre-appareillage", "Rapport du centre d'appareillage",
             "Évaluation du 28.04.2026.\n\n"
             "Moignon transtibial gauche de 14 cm, forme conique régulière, cicatrice "
             "non adhérente, sensibilité conservée. Volume mesuré stable sur trois "
             "contrôles successifs (écart < 2 %).\n\n"
             "L'emboîture provisoire présente un jeu distal de 6 mm, non corrigible par "
             "adjonction de bonnets. Le passage à une emboîture définitive est indiqué.\n\n"
             "Classification fonctionnelle : niveau 3 (marche en extérieur à vitesse "
             "variable, franchissement d'obstacles). Un pied à restitution d'énergie est "
             "adapté à ce niveau."),
        ],
        evolution=(
            "Évolution favorable et régulière depuis l'amputation. Le volume du moignon "
            "est stabilisé, ce qui autorise le passage à un appareillage définitif."),
        pronostic=(
            "Reprise de l'activité professionnelle à 80 % attendue dans les six mois "
            "suivant la livraison de la prothèse définitive."),
    ),

    Scenario(
        form="AI_ReadaptationRente",
        titre="Rapport médical AI — réadaptation et droit à la rente",
        patient=Patient(
            nom="DUBOIS", prenom="Marie", sexe="F", naissance="15.03.1985",
            avs="756.1234.5678.90", rue="Rue du Lac 12", npa="2000",
            ville="Neuchâtel", canton="NE", tel="079 123 45 67",
            email="m.dubois@exemple-mail.ch", etat_civil="divorcée",
            profession="employée de bureau", employeur="Fiduciaire du Littoral Sàrl"),
        medecin=KELLER,
        assureur="Office AI du canton de Neuchâtel",
        police="AI-NE-2025-047812",
        date_rapport="10.03.2026",
        contexte=(
            "Demande AI déposée le 12.09.2025 pour lombalgies chroniques invalidantes. "
            "L'office AI sollicite un rapport médical en vue d'examiner le droit à des "
            "mesures de réadaptation et, subsidiairement, à une rente."),
        anamnese=(
            "Lombalgies chroniques depuis 2023, aggravées progressivement. IRM du "
            "15.04.2025 : protrusion discale postéro-latérale droite L4-L5 avec contact "
            "radiculaire. Douleurs lombaires basses avec irradiation dans le membre "
            "inférieur droit jusqu'au genou, aggravées par la position assise prolongée "
            "et le port de charges. EVA 6/10 au repos, 8/10 en activité."),
        antecedents=[
            "Hypertension artérielle contrôlée depuis 2020 (I10)",
            "Appendicectomie en 2004",
        ],
        diagnostics=[
            ("M51.1", "Lombalgies chroniques sur hernie discale L4-L5", "20.03.2025"),
            ("M54.1", "Lomboradiculopathie droite L5", "20.03.2025"),
            ("I10", "Hypertension artérielle contrôlée", "08.02.2020"),
        ],
        traitements=[
            "Dafalgan 1000 mg, 3×/jour",
            "Irfen 400 mg, 2×/jour en réserve lors des crises",
            "Sirdalud 4 mg au coucher",
            "Physiothérapie hebdomadaire depuis le 01.06.2025",
        ],
        consultations=[
            ("05.03.2026",
             "S : douleurs stables, tolérance à la position assise limitée à 30 minutes.\n"
             "O : Lasègue positif à 45° à droite, réflexes conservés, pas de déficit moteur.\n"
             "A : lomboradiculopathie chronique, sans indication chirurgicale.\n"
             "P : poursuite du traitement conservateur, soutien à une réorientation vers "
             "une activité adaptée sans port de charges supérieur à 5 kg."),
            ("12.12.2025",
             "S : persistance des douleurs malgré la physiothérapie.\n"
             "O : mobilité lombaire réduite, Schober 3 cm.\n"
             "A : évolution défavorable sur le plan fonctionnel.\n"
             "P : discussion d'une reprise à taux réduit en activité adaptée."),
        ],
        incapacites=[("01.06.2025", "31.08.2025", "50 %"),
                     ("01.09.2025", "31.12.2025", "30 %"),
                     ("01.01.2026", "", "40 %")],
        documents=[
            ("rapport-irm", "Rapport d'imagerie",
             "IRM lombaire du 15.04.2025.\n\n"
             "Protrusion discale postéro-latérale droite en L4-L5, venant au contact de "
             "la racine L5 droite dans le récessus latéral. Pas de sténose canalaire "
             "significative. Discopathie débutante L5-S1. Pas de lésion osseuse "
             "suspecte.\n\n"
             "Conclusion : hernie discale L4-L5 avec conflit radiculaire L5 droit."),
            ("evaluation-capacite-travail", "Évaluation de la capacité de travail",
             "Activité habituelle d'employée de bureau : exigible à 60 %, avec "
             "alternance des positions toutes les 30 minutes et poste de travail adapté "
             "(siège ergonomique, bureau assis-debout).\n\n"
             "Activité adaptée — travail sédentaire léger, sans port de charges de plus "
             "de 5 kg, sans posture penchée en avant prolongée, avec possibilité "
             "d'alterner les positions : exigible à 70 %.\n\n"
             "Mesures de réadaptation envisageables : adaptation du poste de travail, "
             "reclassement dans une activité de type secrétariat spécialisé. La patiente "
             "est motivée et a entamé une formation en comptabilité à distance.\n\n"
             "Une reprise progressive à 70 % est envisageable dès janvier 2027 dans une "
             "activité adaptée."),
        ],
        pronostic=(
            "Pronostic réservé quant à l'activité habituelle. Favorable dans une "
            "activité adaptée, sous réserve de l'aboutissement des mesures de "
            "réadaptation."),
    ),

    Scenario(
        form="AI_RapportIntermediaire_Actualisation",
        titre="Rapport intermédiaire AI — actualisation",
        patient=Patient(
            nom="BERNASCONI", prenom="Elena", sexe="F", naissance="07.07.1987",
            avs="756.8821.4409.62", rue="Avenue de la Gare 31", npa="1800",
            ville="Vevey", canton="VD", tel="+41 78 551 20 74",
            email="e.bernasconi@exemple-mail.ch", etat_civil="célibataire",
            profession="infirmière en soins généraux", employeur="EMS Les Tilleuls",
            taux_activite="90 %"),
        medecin=VERNET,
        assureur="Office AI du canton de Vaud",
        police="AI-VD-2023-092155",
        date_rapport="21.04.2026",
        contexte=(
            "Une rente AI partielle est versée depuis le 01.07.2024. L'office AI demande "
            "une actualisation du rapport médical afin d'apprécier l'évolution de l'état "
            "de santé depuis le dernier rapport du 19.04.2025."),
        anamnese=(
            "Sclérose en plaques de forme rémittente diagnostiquée en 03.2021 après un "
            "premier épisode de névrite optique droite. Deux poussées documentées depuis "
            "le dernier rapport : une poussée sensitive du membre supérieur gauche en "
            "09.2025, régressive, et une poussée motrice du membre inférieur droit en "
            "01.2026, partiellement régressive. Fatigue chronique invalidante, majorée "
            "en fin de journée et par la chaleur."),
        antecedents=[
            "Névrite optique rétrobulbaire droite en 03.2021, séquelle : baisse d'acuité à 0.7",
            "Migraine sans aura depuis l'adolescence (G43.0)",
        ],
        diagnostics=[
            ("G35", "Sclérose en plaques de forme rémittente-récurrente", "18.03.2021"),
            ("G43.0", "Migraine sans aura", "01.09.2003"),
            ("R53", "Fatigue chronique dans le cadre de la SEP", "18.03.2021"),
        ],
        traitements=[
            "Ocrelizumab 600 mg en perfusion semestrielle depuis 06.2021",
            "Amantadine 100 mg, 2×/jour, pour la fatigue",
            "Physiothérapie neurologique, 1×/semaine",
        ],
        consultations=[
            ("14.04.2026",
             "S : fatigue au premier plan, limite l'activité à 3 heures continues. "
             "Récupération incomplète de la poussée de janvier.\n"
             "O : EDSS 4.0 (contre 3.5 en 04.2025). Démarche possible sans aide sur "
             "300 m. Force MI droit 4/5.\n"
             "A : aggravation modérée depuis le dernier rapport.\n"
             "P : maintien du traitement de fond, réévaluation de la capacité de travail."),
            ("22.01.2026",
             "S : déficit moteur du membre inférieur droit d'installation subaiguë.\n"
             "O : parésie 3/5 à la dorsiflexion, signe de Babinski droit.\n"
             "A : poussée motrice.\n"
             "P : corticothérapie IV 1 g/jour pendant 3 jours, puis physiothérapie "
             "intensive."),
        ],
        incapacites=[("01.07.2024", "31.12.2025", "50 %"),
                     ("01.01.2026", "", "70 %")],
        documents=[
            ("irm-cerebrale", "Rapport d'imagerie",
             "IRM cérébrale et médullaire du 26.01.2026, comparée à celle du 11.03.2025.\n\n"
             "Apparition de deux nouvelles lésions démyélinisantes en hypersignal T2 "
             "FLAIR, périventriculaire gauche et juxta-corticale frontale droite. Une "
             "lésion médullaire cervicale C4 rehaussée après gadolinium, en faveur d'une "
             "activité récente.\n\n"
             "Conclusion : progression radiologique depuis l'examen de référence."),
            ("evaluation-fonctionnelle", "Évaluation fonctionnelle actualisée",
             "Depuis le rapport du 19.04.2025, l'état s'est aggravé : EDSS passé de 3.5 "
             "à 4.0, deux poussées, progression radiologique documentée.\n\n"
             "Capacité de travail dans l'activité habituelle d'infirmière, qui suppose "
             "station debout prolongée et manutention de patients : nulle.\n\n"
             "Capacité dans une activité adaptée — sédentaire, à l'abri de la chaleur, "
             "avec pauses régulières et horaires souples : 30 %, soit environ 3 heures "
             "par jour, contre 50 % lors du précédent rapport.\n\n"
             "Aucune mesure de réadaptation supplémentaire n'est indiquée dans "
             "l'immédiat, compte tenu de l'activité inflammatoire persistante."),
        ],
        evolution=(
            "Aggravation objectivée depuis le dernier rapport, tant sur le plan clinique "
            "que radiologique."),
        pronostic=(
            "Réservé. La maladie reste active malgré un traitement de fond bien conduit. "
            "Réévaluation proposée dans douze mois."),
    ),

    Scenario(
        form="AI_RapportIntermediaire_Revision",
        titre="Rapport intermédiaire AI — révision du droit",
        patient=Patient(
            nom="AEBISCHER", prenom="Daniel", sexe="M", naissance="30.11.1974",
            avs="756.4477.1203.85", rue="Route de Berne 88", npa="1010",
            ville="Lausanne", canton="VD", tel="+41 76 318 44 21",
            email="d.aebischer@exemple-mail.ch", etat_civil="marié",
            profession="chef d'équipe en logistique", employeur="TransLog Vaud SA"),
        medecin=FAVRE,
        assureur="Office AI du canton de Vaud",
        police="AI-VD-2021-063401",
        date_rapport="03.06.2026",
        contexte=(
            "Une rente entière est versée depuis le 01.03.2022 pour un épisode dépressif "
            "sévère. L'office AI procède à une révision d'office et sollicite un rapport "
            "sur l'évolution et sur l'exigibilité d'une reprise d'activité."),
        anamnese=(
            "Épisode dépressif sévère sans symptômes psychotiques survenu en 09.2021, "
            "dans un contexte de surcharge professionnelle et de conflit hiérarchique "
            "prolongé. Hospitalisation de six semaines en 11.2021. Amélioration lente "
            "sous traitement combiné. Depuis 2025, rémission partielle stable : l'humeur "
            "est thymorégulée, l'anhédonie a régressé, mais persistent une fatigabilité "
            "cognitive et une intolérance au stress."),
        antecedents=[
            "Aucun antécédent psychiatrique avant 2021",
            "Lombalgies mécaniques occasionnelles, sans substrat radiologique",
            "Tabagisme 15 UPA, sevré en 2022",
        ],
        diagnostics=[
            ("F33.1", "Trouble dépressif récurrent, épisode actuel moyen", "12.09.2021"),
            ("F41.1", "Trouble anxieux généralisé", "12.09.2021"),
            ("Z56.3", "Difficultés liées au rythme de travail", "12.09.2021"),
        ],
        traitements=[
            "Escitalopram 15 mg, 1×/jour",
            "Quétiapine 50 mg au coucher",
            "Psychothérapie cognitivo-comportementale, séance bimensuelle",
        ],
        consultations=[
            ("27.05.2026",
             "S : humeur stable depuis douze mois, sommeil réparateur, projets "
             "réinvestis. Appréhension marquée à l'idée d'un retour dans une fonction "
             "d'encadrement.\n"
             "O : MADRS à 11 (contre 28 en 2022). Pas d'idéation suicidaire. Ralentissement "
             "psychomoteur résiduel discret.\n"
             "A : rémission partielle stable.\n"
             "P : soutien à une reprise progressive en activité adaptée, sans "
             "responsabilité hiérarchique."),
            ("15.01.2026",
             "S : bonne observance, pas de rechute depuis 18 mois.\n"
             "O : MADRS 13, fonctionnement social conservé.\n"
             "A : stabilité.\n"
             "P : maintien du traitement, envisager une mesure d'orientation "
             "professionnelle."),
        ],
        incapacites=[("12.09.2021", "31.12.2024", "100 %"),
                     ("01.01.2025", "31.12.2025", "80 %"),
                     ("01.01.2026", "", "60 %")],
        documents=[
            ("bilan-neuropsychologique", "Bilan neuropsychologique",
             "Examen du 12.05.2026.\n\n"
             "Efficience intellectuelle globale dans la norme. Ralentissement du "
             "traitement de l'information (percentile 15). Attention divisée déficitaire "
             "en situation de double tâche. Mémoire de travail à la limite inférieure de "
             "la norme. Fonctions exécutives préservées en situation calme, se "
             "dégradant sous contrainte temporelle.\n\n"
             "Conclusion : profil compatible avec une activité structurée, à rythme "
             "maîtrisé, sans interruptions fréquentes ni gestion simultanée de plusieurs "
             "dossiers. Une fonction d'encadrement n'est pas exigible."),
            ("evaluation-revision", "Évaluation en vue de la révision",
             "Comparaison avec la situation lors de l'octroi de la rente en 03.2022 :\n\n"
             "- MADRS passé de 28 à 11 ;\n"
             "- absence de rechute depuis 18 mois ;\n"
             "- reprise d'activités sociales et associatives ;\n"
             "- persistance d'une fatigabilité cognitive objectivée.\n\n"
             "L'état de santé s'est notablement amélioré depuis la décision initiale. "
             "Une capacité de travail de 60 % est exigible dans une activité adaptée — "
             "tâches structurées, sans responsabilité d'encadrement, sans contrainte "
             "temporelle forte. Dans l'activité habituelle de chef d'équipe, la capacité "
             "reste nulle.\n\n"
             "Des mesures d'ordre professionnel — orientation puis placement — sont "
             "indiquées et le patient y adhère."),
        ],
        evolution=(
            "Amélioration notable et durable depuis l'octroi de la rente, sans rechute "
            "depuis dix-huit mois."),
        pronostic=(
            "Favorable dans une activité adaptée. Une reprise à 60 % est réaliste dans "
            "un délai de six mois, avec accompagnement."),
    ),
]
