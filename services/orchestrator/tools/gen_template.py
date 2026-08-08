"""
tools/gen_template.py — Génère un template DoctorFill à partir d'un PDF medForms.

Les formulaires medForms sont des XFA statiques hybrides : le packet XFA `template`
décrit chaque champ (nom, type d'UI, libellé, valeurs possibles) et le PDF porte en
parallèle une couche AcroForm dont les noms de widgets sont exactement les expressions
SOM du XFA. On peut donc dériver mécaniquement le `xml_path` et l'`acroform_name` de
chaque champ, au lieu de les saisir à la main.

Le script vérifie systématiquement ses dérivations contre le PDF réel et refuse
d'écrire un template incohérent.

Usage :
    python -m tools.gen_template forms/Form_AVS.pdf --out template/Form_AVS.json
    python -m tools.gen_template --url https://medforms.ch/formTemplates/medforms.20.10.25.5010_fr.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.acroform import extract_acroform_field_names  # noqa: E402
from core.extract import extract_xfa_packets  # noqa: E402

logger = logging.getLogger(__name__)

# Le catalogue medForms mélange les versions du schéma XFA (2.6 et 2.8 observées).
# Plutôt que de gérer chaque version, tout le parcours raisonne sur le nom local
# des éléments et ignore l'espace de noms.

# Types d'UI XFA → type DoctorFill exploité par _normalize_field_value / core.fill.
UI_TO_TYPE = {
    "checkButton": "bool",
    "dateTimeEdit": "date",
    "numericEdit": "int",
    "choiceList": "choice",
    "textEdit": None,
    "signature": None,
    "imageEdit": None,
    "barcode": None,
}

# Champs techniques du gabarit medForms : jamais renseignés par le clinicien.
# Volontairement restreint — `blockAddress`, `input` et les dates de formulaire
# portent du contenu réel (bloc adresse, texte libre, date du rapport) et sont
# utilisés comme tels dans les templates rédigés à la main.
TECHNICAL_NAMES = {
    "pageNumber", "oid", "guid", "serialNum", "version", "language",
    "supervisorData", "instructions", "formDescription", "formArea",
    "formTitle", "formType", "formOID", "submitDesc", "submitLog",
    "submitCtrl", "dataSubmit", "dataSubmitAlt", "copyright", "logo", "constraint",
    # Aides contextuelles affichées au clinicien, pas des données à extraire.
    "helpICD10", "helpCHOP9",
    # Plomberie de pièce jointe et d'affichage, sans contenu clinique.
    "file", "mimeType", "docOpenTime", "subaddressing", "recipientChoice",
    # Boutons et sondes du gabarit : aucune donnée à extraire.
    "deleteMe", "clearMe", "javascriptAvailability", "calcSubmitLog",
    "calcGPManagement", "calcAppointmentPendencyTask",
    # Plomberie interne repérée en parcourant le catalogue.
    "helpSystem", "openAttach", "production_modus", "pad_medforms_form_id",
    "miscData", "subaddressingSelector",
}


class GenerationError(RuntimeError):
    """La dérivation ne correspond pas au PDF — le template n'est pas écrit."""


def medforms_identity(packets: dict[str, str]) -> tuple[str, str]:
    """
    Retrouve le code medForms et le chemin de taxonomie d'un formulaire.

    Le packet `config` porte le chemin d'origine du gabarit, par exemple
    `…\\medforms\\20.providers\\10.physician\\140.cardiology\\5010.application\\`.
    Les préfixes numériques de ce chemin *sont* le code : `medforms.20.10.140.5010`.
    C'est la seule source fiable — l'`oid` du packet `datasets` n'est renseigné
    que sur une partie du catalogue.
    """
    base = re.search(r"<base\s*>([^<]+)</base", packets.get("config", ""))
    if not base:
        return "", ""
    segments = [s for s in re.split(r"[\\/]+", base.group(1).strip()) if s]
    if "medforms" not in segments:
        return "", ""
    taxonomy = segments[segments.index("medforms") + 1:]
    numbers = [s.split(".", 1)[0] for s in taxonomy if s.split(".", 1)[0].isdigit()]
    code = f"medforms.{'.'.join(numbers)}" if numbers else ""
    return code, "/".join(taxonomy)


# ---------------------------------------------------------------------------
# Parcours de l'arbre XFA
# ---------------------------------------------------------------------------


def _tag(elem: ET.Element) -> str:
    """Nom local d'un élément, quelle que soit la version du schéma XFA."""
    return elem.tag.rsplit("}", 1)[-1]


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _tag(c) == name]


def _descend(elem: ET.Element, *names: str) -> ET.Element | None:
    """Descend une chaîne d'éléments par nom local, en prenant le premier de chaque niveau."""
    current = elem
    for name in names:
        found = _children(current, name)
        if not found:
            return None
        current = found[0]
    return current


def _caption(elem: ET.Element) -> str:
    node = _descend(elem, "caption", "value", "text")
    if node is None or not node.text:
        return ""
    return " ".join(node.text.split())


# --------------------------------------------------------------------------
# Vocabulaire medForms
#
# Les 99 formulaires partagent le modèle de données Sumex / Forum Datenaustausch :
# les mêmes sous-formulaires d'adresse et les mêmes noms de champs y reviennent
# (mesuré sur 19 formulaires : patientS1Address ×200, consumerS1Address ×137,
# ean ×53, zsr ×28…). Décrire ce vocabulaire une fois couvre donc la majeure
# partie des champs de tout le catalogue.
# --------------------------------------------------------------------------

ROLE_VOCAB = {
    "patientS1Address": "du patient",
    "consumerS1Address": "du destinataire du formulaire",
    "providerS1Address": "du médecin traitant (fournisseur de prestations)",
    "insuranceS1Address": "de l'assureur",
    "gpS1Address": "du médecin de famille",
    "employerS1Address": "de l'employeur",
    "recipientS1Address": "du destinataire",
    "supervisorS1Address": "du médecin superviseur",
    "physiotherapistS1Address": "du physiothérapeute",
    "hospitalS1Address": "de l'hôpital ou de la clinique",
    "othertechnicianS1Address": "du technicien ou fournisseur de moyens auxiliaires",
    "pharmacyS1Address": "de la pharmacie",
    "therapistS1Address": "du thérapeute",
    "guardianS1Address": "du représentant légal",
    "surgeonS1Address": "du chirurgien",
    "anesthetistS1Address": "de l'anesthésiste",
    "specialistS1Address": "du médecin spécialiste",
    "counselingS1Address": "du centre de conseil",
}

FIELD_VOCAB = {
    "lastName": ("Quel est le nom de famille {role} ?", None),
    "firstName": ("Quel est le prénom {role} ?", None),
    "birthDate": ("Quelle est la date de naissance {role} ? [format : JJ.MM.AAAA]", "date"),
    "ssn": ("Quel est le numéro AVS {role} ? [format : 756.XXXX.XXXX.XX]", None),
    "sex": ("Quel est le sexe {role} ? Répondre UNIQUEMENT par M (masculin) ou F (féminin).", "sex"),
    "street": ("Quelle est la rue et le numéro de l'adresse {role} ?", None),
    "zip": ("Quel est le code postal (NPA) de l'adresse {role} ?", None),
    "city": ("Quelle est la localité de l'adresse {role} ?", None),
    "phone": ("Quel est le numéro de téléphone {role} ?", None),
    "email": ("Quelle est l'adresse e-mail {role} ?", None),
    "ean": ("Quel est le numéro GLN (anciennement EAN) {role} ?", None),
    "zsr": ("Quel est le numéro RCC (ZSR) {role} ?", None),
    "blockAddress": ("Quelle est l'adresse postale complète {role} "
                     "(nom, rue, NPA et localité) ?", None),
    "companyName": ("Quel est le nom de l'entreprise ou de l'institution {role} ?", None),
    "departmentName": ("Quel est le nom du service ou du département {role} ?", None),
    "insuredID": ("Quel est le numéro d'assuré du patient auprès de l'assureur ?", None),
    "caseID": ("Quel est le numéro de dossier ou de sinistre ?", None),
    "caseDate": ("Quelle est la date de l'événement assuré (accident, sinistre) ? "
                 "[format : JJ.MM.AAAA]", "date"),
    "creationDate": ("Quelle est la date d'établissement du rapport ? [format : JJ.MM.AAAA]", "date"),
    "modificationDate": ("Quelle est la date de dernière mise à jour du rapport ? "
                         "[format : JJ.MM.AAAA]", "date"),
    # Second rang : champs récurrents du catalogue au-delà des blocs d'adresse.
    "fax": ("Quel est le numéro de fax {role} ?", None),
    "pobox": ("Quelle est la case postale de l'adresse {role} ?", None),
    "beginDate": ("Quelle est la date de début de la période concernée ? [format : JJ.MM.AAAA]", "date"),
    "endDate": ("Quelle est la date de fin de la période concernée ? [format : JJ.MM.AAAA]", "date"),
    "date": ("Quelle est la date concernée ? [format : JJ.MM.AAAA]", "date"),
    "percentWorkload": ("Quel est le taux d'activité, en pourcentage ? "
                        "Répondre par le nombre seul.", "percent"),
    "percentageNum": ("Quel est le pourcentage indiqué ? Répondre par le nombre seul.", "percent"),
    "dailyWorktime": ("Quel est le temps de travail quotidien, en heures ?", None),
    "treatmentReason": ("Quel est le motif du traitement ou de la consultation ?", None),
    "input": ("Y a-t-il une remarque ou une précision à ajouter concernant "
              "les coordonnées {role} ?", None),
    # Troisième rang : champs cliniques et administratifs récurrents du catalogue.
    "profession": ("Quelle est la profession exercée par le patient ?", None),
    "anamnesis": ("Quelle est l'anamnèse du patient : antécédents, évolution et "
                  "circonstances ayant conduit à la situation actuelle ?", None),
    "remark": ("Y a-t-il une remarque particulière à signaler ?", None),
    "comment": ("Y a-t-il un commentaire à ajouter ?", None),
    "formRemark": ("Y a-t-il une remarque générale à joindre au formulaire ?", None),
    "addendum": ("Y a-t-il une information complémentaire à ajouter au rapport ?", None),
    "procedure": ("Quelle procédure ou intervention a été réalisée ou est prévue ?", None),
    "treatmentCanton": ("Dans quel canton suisse le patient est-il traité ? "
                        "Répondre par le sigle du canton (VD, GE, VS, FR…).", None),
    "insuranceSelector": ("Quel est le nom de l'assureur qui prend en charge le cas ?", None),
    "condensedName": ("Quel est le nom complet {role} ?", None),
    "condensedAddress": ("Quelle est l'adresse complète {role} "
                         "(rue, NPA et localité) ?", None),
    "returnToWorkFrom": ("À partir de quelle date le patient peut-il reprendre le "
                         "travail ? [format : JJ.MM.AAAA]", "date"),
    "returnToWorkInWeeks": ("Dans combien de semaines une reprise du travail "
                            "est-elle envisageable ? Répondre par le nombre seul.", "int"),
    "dailyAttendance": ("Combien d'heures de présence quotidienne le patient "
                        "peut-il assurer ?", None),
    "dailyResilience": ("Quelle est la capacité de résistance quotidienne du "
                        "patient, en heures ?", None),
    # Quatrième rang : vocabulaire clinique partagé par plusieurs formulaires du
    # catalogue (état de santé, évolution, traitement, capacité de travail).
    "stateOfHealth": ("Quel est l'état de santé actuel du patient ?", None),
    "changeOfDiagnosis": ("Le diagnostic a-t-il changé depuis le dernier rapport ? "
                          "Si oui, préciser en quoi.", None),
    "influenceOnChangedDiagnosis": ("Quelle influence ce changement de diagnostic a-t-il "
                                    "sur la capacité de travail du patient ?", None),
    "degreeOnChangedDiagnosis": ("Dans quelle mesure ce changement de diagnostic "
                                 "modifie-t-il le pronostic ?", None),
    "changedClinicalResults": ("Quels résultats cliniques ou d'examens ont évolué "
                               "depuis le dernier rapport ?", None),
    "therapeuticalMeasure": ("Quelles mesures thérapeutiques sont en cours ou prévues ?", None),
    "lastExaminationDate": ("À quelle date le patient a-t-il été examiné pour la "
                            "dernière fois ? [format : JJ.MM.AAAA]", "date"),
    "progressUpdateStartDate": ("À partir de quelle date porte cette actualisation "
                                "du dossier ? [format : JJ.MM.AAAA]", "date"),
    "needChangeInProfession": ("Une reconversion ou un changement d'activité "
                               "professionnelle est-il nécessaire ? Si oui, préciser.", None),
    "needThirdPartyHelp": ("Le patient a-t-il besoin de l'aide d'un tiers ? "
                           "Si oui, préciser pour quels actes.", None),
    "thirdPartyHelpBeginDate": ("À partir de quelle date l'aide d'un tiers est-elle "
                                "nécessaire ? [format : JJ.MM.AAAA]", "date"),
    "needAdditionalClarification": ("Des investigations complémentaires sont-elles "
                                    "nécessaires ? Si oui, lesquelles ?", None),
    "treatmentStartDate": ("À quelle date le traitement a-t-il débuté ? "
                           "[format : JJ.MM.AAAA]", "date"),
    "treatmentEndDate": ("À quelle date le traitement s'est-il terminé ou doit-il "
                         "se terminer ? [format : JJ.MM.AAAA]", "date"),
    "treatmentTypes": ("Quels types de traitement sont prescrits ou en cours ?", None),
    "treatmentGoals": ("Quels sont les objectifs thérapeutiques visés ?", None),
    "numSessions": ("Combien de séances sont prescrites ? Répondre par le nombre seul.", "int"),
    "atHomeTreatment": ("Le traitement doit-il être effectué au domicile du patient ? "
                        "Répondre par oui ou non.", None),
    "weekendTreatment": ("Le traitement doit-il être poursuivi le week-end ? "
                         "Répondre par oui ou non.", None),
    "splintTreatment": ("Un traitement par attelle ou orthèse est-il prescrit ? "
                        "Si oui, préciser.", None),
    "hoursPerDayPlanned": ("Combien d'heures par jour le traitement est-il prévu ?", None),
    "evaluation": ("Quelle est l'appréciation médicale de la situation du patient ?", None),
    "request": ("Quelle est la demande adressée à l'assureur ou à l'office ?", None),
    "attachment": ("Quels documents sont joints au rapport ?", None),
    "fillerName": ("Qui a rempli ce formulaire ? Indiquer le nom de la personne.", None),
    "accidentDate": ("À quelle date l'accident est-il survenu ? [format : JJ.MM.AAAA]", "date"),
    "accidentDescription": ("Comment l'accident s'est-il produit ? Décrire les "
                            "circonstances.", None),
    "firstTreatmentDate": ("À quelle date le patient a-t-il été traité pour la "
                           "première fois ? [format : JJ.MM.AAAA]", "date"),
    "prognosis": ("Quel est le pronostic pour ce patient ?", None),
    "findings": ("Quelles sont les constatations cliniques ?", None),
    "diagnosis": ("Quel est le diagnostic posé ?", None),
    "therapy": ("Quelle thérapie est mise en place ?", None),
    "medication": ("Quels médicaments le patient prend-il ?", None),
    "hospitalisationFrom": ("À partir de quelle date le patient est-il hospitalisé ? "
                            "[format : JJ.MM.AAAA]", "date"),
    "hospitalisationTo": ("Jusqu'à quelle date le patient est-il hospitalisé ? "
                          "[format : JJ.MM.AAAA]", "date"),
    "workIncapacityFrom": ("À partir de quelle date le patient est-il en incapacité de "
                           "travail ? [format : JJ.MM.AAAA]", "date"),
    "workIncapacityTo": ("Jusqu'à quelle date l'incapacité de travail est-elle "
                         "attestée ? [format : JJ.MM.AAAA]", "date"),
    "workIncapacityDegree": ("Quel est le taux d'incapacité de travail, en pourcentage ? "
                             "Répondre par le nombre seul.", "percent"),
    # Cinquième rang : anamnèse, premiers soins et suivi, présents dans les
    # rapports initiaux LAA / LaMal / LAM sous des noms identiques.
    "firstTreatmentCity": ("Dans quelle localité le premier traitement a-t-il eu lieu ?", None),
    "firstTreatmentTime": ("À quelle heure le premier traitement a-t-il eu lieu ? "
                           "[format : HH:MM]", None),
    "firstTreatmentDoctor": ("Quel médecin a assuré le premier traitement ?", None),
    "firstTreatmentSpeciality": ("Quelle est la spécialité du médecin ayant assuré le "
                                 "premier traitement ?", None),
    "firstIncidence": ("Quand les premiers symptômes sont-ils apparus ?", None),
    "previousTreatments": ("Quels traitements le patient a-t-il déjà reçus pour cette "
                           "affection ?", None),
    "hasPreviousTreatments": ("Le patient a-t-il déjà été traité pour cette affection ? "
                              "Répondre par oui ou non.", None),
    "previousTherapies": ("Quelles thérapies ont déjà été tentées ?", None),
    "previousDiseases": ("Quels antécédents médicaux le patient présente-t-il ?", None),
    "patientIndications": ("Quelles plaintes le patient rapporte-t-il lui-même ?", None),
    "anamnesisOther": ("Y a-t-il d'autres éléments d'anamnèse à signaler ?", None),
    "morphologicalDamage": ("Quelles atteintes morphologiques sont constatées "
                            "(lésions, déformations) ?", None),
    "functionalDamage": ("Quelles atteintes fonctionnelles sont constatées "
                         "(limitations de mobilité, de force) ?", None),
    "exams": ("Quels examens complémentaires ont été réalisés et avec quels résultats ?", None),
    "objectiveLimitation": ("Quelles limitations objectives l'examen met-il en évidence ?", None),
    "currentSituation": ("Quelle est la situation actuelle du patient ?", None),
    "hasOtherFactors": ("D'autres facteurs influencent-ils l'évolution ? "
                        "Répondre par oui ou non.", None),
    "otherFactors": ("Quels autres facteurs influencent l'évolution du cas "
                     "(contexte professionnel, social, psychique) ?", None),
    "nationality": ("Quelle est la nationalité du patient ?", None),
    "workHours": ("Quel est l'horaire de travail habituel du patient ?", None),
    "workingHours": ("Quel est l'horaire de travail habituel du patient ?", None),
    "workingDays": ("Combien de jours par semaine le patient travaille-t-il "
                    "habituellement ?", None),
    "reason": ("Quel est le motif de ce rapport ?", None),
    "pregnancyDueDate": ("Quelle est la date prévue de l'accouchement ? "
                         "[format : JJ.MM.AAAA]", "date"),
    "hospitalisationList": ("Dans quels établissements le patient a-t-il été hospitalisé, "
                            "et à quelles dates ?", None),
    "hospitalisationChoice": ("Le patient a-t-il été hospitalisé ? Répondre par oui ou non.", None),
    "otherInvolvedDoctor": ("Quel autre médecin est intervenu dans la prise en charge ?", None),
    "otherInvolvedSpeciality": ("Quelle est la spécialité de cet autre médecin intervenant ?", None),
    "otherInvolvedCity": ("Dans quelle localité cet autre médecin exerce-t-il ?", None),
    "otherInvolvedDate": ("À quelle date cet autre médecin est-il intervenu ? "
                          "[format : JJ.MM.AAAA]", "date"),
    "hasOtherInsurer": ("Un autre assureur est-il concerné par ce cas ? "
                        "Répondre par oui ou non.", None),
    "otherInsurerList": ("Quels autres assureurs sont concernés par ce cas ?", None),
    "nextTreatmentDate": ("Quelle est la date du prochain traitement prévu ? "
                          "[format : JJ.MM.AAAA]", "date"),
    "treatmentDateList": ("Quelles sont les dates des traitements effectués ?", None),
    "treatmentDuration": ("Quelle est la durée prévue du traitement ?", None),
    "treatmentProblem": ("Quel problème le traitement doit-il résoudre ?", None),
    "examinationDate": ("À quelle date le patient a-t-il été examiné ? "
                        "[format : JJ.MM.AAAA]", "date"),
    "accidentDetails": ("Quelles sont les circonstances détaillées de l'accident ?", None),
    "accidentTime": ("À quelle heure l'accident est-il survenu ? [format : HH:MM]", None),
    "courseOfAccident": ("Comment l'accident s'est-il déroulé ?", None),
    "classification": ("Quelle est la classification retenue pour cette atteinte ?", None),
    "aidsDescription": ("Quels moyens auxiliaires sont demandés ? Les décrire précisément.", None),
    "physioGoals": ("Quels sont les objectifs de la physiothérapie ?", None),
    "physioMethods": ("Quelles méthodes de physiothérapie sont prescrites ?", None),
    "mdRecommendation": ("Quelle est la recommandation du médecin ?", None),
    # Sixième rang : suivi et capacité de travail des rapports intermédiaires
    # LAA / LAM, dont les libellés sont identiques d'un régime à l'autre.
    "course": ("Quelle a été l'évolution du cas depuis le dernier rapport ?", None),
    "ask4FormerProlapses": ("Le patient a-t-il déjà présenté des rechutes de cette "
                            "affection ? Répondre UNIQUEMENT par oui ou non.", None),
    "formerProlapses": ("Quelles rechutes le patient a-t-il déjà présentées, et à "
                        "quelles dates ?", None),
    "recommendation": ("Quelle recommandation formulez-vous pour la suite de la "
                       "prise en charge ?", None),
    "consultationInterval": ("À quel intervalle les consultations de suivi sont-elles "
                             "prévues ?", None),
    "therapyLength": ("Quelle est la durée prévue de la thérapie ?", None),
    "ask4NewWorkplace": ("Une adaptation du poste de travail est-elle nécessaire ? "
                         "Répondre UNIQUEMENT par oui ou non.", None),
    "ask4LastingHandicap": ("Une atteinte durable à l'intégrité est-elle à prévoir ? "
                            "Répondre UNIQUEMENT par oui ou non.", None),
    "handicap": ("Quelle atteinte durable à l'intégrité est à prévoir ?", None),
    "poBox": ("Quelle est la case postale de l'adresse ?", None),
    "geschlecht": ("Quel est le sexe du patient ? Répondre UNIQUEMENT par la lettre "
                   "M (masculin) ou F (féminin).", "sex"),
    "hoursPerDayFixed": ("Combien d'heures par jour le patient peut-il travailler ?", None),
    "hoursPerDayFix": ("Combien d'heures par jour le patient peut-il travailler ?", None),
    "returnBeforeWeekend": ("Le patient peut-il reprendre le travail avant le week-end ? "
                            "Répondre par oui ou non.", None),
    "DiagnosesUnemployabilityRelated": ("Quels diagnostics justifient l'incapacité de "
                                        "travail ?", None),
    "DiagnosesUnemployabilityUnrelated": ("Quels diagnostics n'ont pas d'incidence sur "
                                          "la capacité de travail ?", None),
    "impossibleActivities": ("Quelles activités le patient ne peut-il plus exercer ?", None),
    "possibleActivities": ("Quelles activités le patient peut-il encore exercer ?", None),
    "generalCondition": ("Quel est l'état général du patient ?", None),
    "proposedTherapy": ("Quelle thérapie proposez-vous ?", None),
    # Blocs destinataire de l'en-tête, communs aux formulaires d'assureur.
    "recipientBlockAddressLeft": (
        "Quelle est l'adresse complète de l'organisme destinataire du rapport "
        "(nom, rue, NPA et localité) ? Elle correspond au canton de traitement du patient.", None),
    "recipientBlockAddressRight": (
        "Quelle est l'adresse complète du service ou de la personne destinataire du "
        "rapport, si elle diffère de l'organisme principal (nom, rue, NPA et localité) ?", None),
}

# Champs dont le sens dépend du sous-formulaire qui les porte. Consultés avant
# FIELD_VOCAB : `type` ne veut pas dire la même chose dans un bloc assurance et
# dans un bloc document.
CONTEXT_VOCAB = {
    ("lawS1Struct", "type"): (
        "De quel régime d'assurance relève la prise en charge ? Répondre UNIQUEMENT "
        "par LAA (accident), LaMal (assurance de base), LCA (assurance complémentaire) "
        "ou LAM (assurance militaire).", None),
    ("documentS1Struct", "title"): ("Quel est l'intitulé du document annexé au rapport ?", None),
    ("documentS1Struct", "type"): ("De quel type de document s'agit-il ?", None),
    # Diagnostics : le contenu clinique le plus important du formulaire.
    ("diagnosisS1Struct", "code"): (
        "Quel est le code CIM-10 du diagnostic ? Reprendre le code exactement tel "
        "qu'il figure dans les documents, sans le reformuler.", None),
    ("diagnosisS1Struct", "name"): (
        "Quel est le libellé du diagnostic posé ?", None),
    ("diagnosisS1Struct", "date"): (
        "À quelle date ce diagnostic a-t-il été posé ? [format : JJ.MM.AAAA]", "date"),
    ("diagnosisS1Struct", "remark"): (
        "Y a-t-il une précision à apporter sur ce diagnostic ?", None),
    ("employerS1Address", "nif"): (
        "Quel est le numéro d'identification de l'entreprise (IDE/NIF) de l'employeur ?", None),
    ("consumerS1Address", "title"): (
        "Quel est le titre ou la civilité du destinataire du formulaire "
        "(Dr, Prof., Madame, Monsieur) ?", None),
    # Champs `input` : remarque libre attachée à une structure. Le contexte change
    # complètement le sens, d'où une entrée par conteneur.
    ("lawS1Struct", "input"): (
        "Y a-t-il une précision à apporter sur la couverture d'assurance "
        "(régime applicable, réserve, prise en charge particulière) ?", None),
    ("treatmentS1Struct", "input"): (
        "Y a-t-il une précision à apporter sur le lieu ou le contexte du traitement "
        "(établissement, service, cadre ambulatoire ou hospitalier) ?", None),
    ("documentS1Struct", "input"): (
        "Y a-t-il une remarque à joindre au sujet des documents annexés ?", None),
    ("diagnosisS1Struct", "input"): (
        "Y a-t-il une précision à apporter sur le diagnostic ?", None),
    ("diagnosisS1Struct", "type"): (
        "Quel système de codage est employé pour cette entrée ? Répondre UNIQUEMENT "
        "par ICD (diagnostic), CHOP (intervention) ou FreeText (texte libre).", None),
    ("unemployabilityS1Struct", "input"): (
        "Y a-t-il une précision à apporter sur cette période d'incapacité de travail ?", None),
    ("cardS1Struct", "input"): (
        "Y a-t-il une remarque concernant la carte d'assuré ?", None),
    ("cardS1Struct", "cardID"): (
        "Quel est le numéro de la carte d'assuré du patient ?", None),
    ("anamnesisStruct", "input"): (
        "Y a-t-il une précision à apporter sur l'anamnèse ?", None),
    ("therapyStruct", "input"): (
        "Y a-t-il une précision à apporter sur la thérapie ?", None),
    # Anamnèse et constatations du certificat médical LAA.
    ("anamnesisStruct", "morphologicalFinding"): (
        "Quelles sont les constatations morphologiques à l'examen "
        "(lésions, tuméfactions, déformations) ?", None),
    ("anamnesisStruct", "functionalFinding"): (
        "Quelles sont les constatations fonctionnelles à l'examen "
        "(mobilité, force, limitations) ?", None),
    ("anamnesisStruct", "xray"): (
        "Quels sont les résultats des examens radiologiques ?", None),
    ("generalConditionStruct", "ask4specialPerception"): (
        "L'état général du patient présente-t-il une particularité à signaler ? "
        "Répondre UNIQUEMENT par oui ou non.", None),
    ("generalConditionStruct", "specialPerception"): (
        "Quelle est la particularité constatée dans l'état général du patient ?", None),
    ("therapyStruct", "ask4Hospitalization"): (
        "Le patient a-t-il été hospitalisé ? Répondre UNIQUEMENT par oui ou non.", None),
}

# Conteneurs medForms reconnus par suffixe : les diagnostics successifs portent un
# préfixe d'ordre (`adiagnosisS1Struct`, `bdiagnosisS1Struct`…) pour une structure
# identique.
STRUCT_SUFFIXES = (
    "diagnosisS1Struct", "lawS1Struct", "documentS1Struct", "treatmentS1Struct",
    "formS1Struct", "employerS1Address", "consumerS1Address", "patientS1Address",
    "providerS1Address", "insuranceS1Address", "gpS1Address",
    "physiotherapistS1Address", "hospitalS1Address", "othertechnicianS1Address",
    "unemployabilityS1Struct", "anamnesisStruct", "therapyStruct",
    "generalConditionStruct", "cardS1Struct",
)

# Conteneurs nommés autrement mais de structure identique — certains formulaires
# écrivent `diagnosis` là où d'autres écrivent `diagnosisS1Struct`.
STRUCT_ALIASES = {
    "diagnosis": "diagnosisS1Struct",
    "anamnesis": "anamnesisStruct",
    "therapy": "therapyStruct",
}


def _normalize_struct(ancestor: str) -> str:
    """
    Ramène un conteneur medForms à son nom canonique.

    Les diagnostics successifs d'un formulaire sont portés par `diagnosisS1Struct`,
    `adiagnosisS1Struct`, `bdiagnosisS1Struct`… : même structure, préfixe d'ordre.
    """
    for known in STRUCT_SUFFIXES:
        if ancestor.endswith(known):
            return known
    return STRUCT_ALIASES.get(ancestor, ancestor)


def _describe(leaf: str, ancestors: list[str]) -> tuple[str, str | None]:
    """
    Rédige la question d'un champ à partir du vocabulaire medForms.

    Returns:
        (question, type) — question vide si le champ n'est pas dans le vocabulaire.
    """
    contexts = [_normalize_struct(a) for a in reversed(ancestors)]
    entry = next((CONTEXT_VOCAB[(c, leaf)] for c in contexts
                  if (c, leaf) in CONTEXT_VOCAB), None) or FIELD_VOCAB.get(leaf)
    if entry is None:
        return "", None
    template, field_type = entry
    role = next((ROLE_VOCAB[a] for a in reversed(ancestors) if a in ROLE_VOCAB), "")
    if "{role}" in template and not role:
        # Sans rôle identifiable la question serait ambiguë : mieux vaut la laisser à rédiger.
        return "", field_type
    return template.format(role=role).replace("  ", " "), field_type


def _ui_kind(elem: ET.Element) -> str:
    """Type d'éditeur XFA : textEdit, checkButton, dateTimeEdit, choiceList…"""
    ui = _children(elem, "ui")
    if not ui or len(ui[0]) == 0:
        return "textEdit"
    return _tag(ui[0][0])


def _items(elem: ET.Element) -> list[str]:
    """Valeurs proposées par le champ (états d'une case, options d'une liste)."""
    return [t.text for group in _children(elem, "items")
            for t in _children(group, "text") if t.text]


def _walk(node: ET.Element, path: list[str]) -> Iterator[tuple[list[str], ET.Element, ET.Element]]:
    """
    Parcourt l'arbre et produit (chemin SOM, élément) pour chaque champ.

    Les frères de même nom sont indexés (`phone[0]`, `phone[1]`) : c'est le cas
    réel des blocs adresse medForms, où une indexation `[0]` systématique
    produirait des noms faux.
    """
    counts: dict[str, int] = {}
    for child in node:
        tag = _tag(child)
        if tag not in ("subform", "field", "exclGroup", "area"):
            continue
        name = child.get("name")
        if tag == "area":
            # Un `area` regroupe visuellement sans peser sur l'expression SOM.
            yield from _walk(child, path)
            continue
        if not name:
            yield from _walk(child, path)
            continue

        index = counts.get(name, 0)
        counts[name] = index + 1
        child_path = path + [f"{name}[{index}]"]

        if tag in ("field", "exclGroup"):
            yield child_path, child, node
        yield from _walk(child, child_path)


def parse_xfa_fields(template_xml: str) -> list[dict[str, Any]]:
    """Extrait la description de chaque champ du packet XFA `template`."""
    root = ET.fromstring(template_xml)
    fields = []
    for som_path, elem, _parent in _walk(root, []):
        ui = _ui_kind(elem)
        segments = [s.split("[")[0] for s in som_path]
        question, vocab_type = _describe(segments[-1], segments[:-1])
        fields.append({
            "question": question,
            "vocab_type": vocab_type,
            "som": ".".join(som_path),
            # xml_path suit le datasets. L'index n'est écrit que s'il est non nul :
            # les chemins restent identiques aux templates rédigés à la main, et
            # deux frères de même nom (phone[0]/phone[1]) cessent de se confondre.
            "xml_path": "/".join(p if not p.endswith("[0]") else p[:-3] for p in som_path),
            "name": som_path[-1].split("[")[0],
            "ui": ui,
            "type": UI_TO_TYPE.get(ui),
            "label": _caption(elem),
            "options": _items(elem),
            "readonly": elem.get("access") == "readOnly",
        })
    return fields


# ---------------------------------------------------------------------------
# Construction du template
# ---------------------------------------------------------------------------


def _section_of(som: str) -> str:
    """Section = 2e segment du chemin SOM (page1, Seite2, …), sans son index."""
    parts = som.split(".")
    return parts[1].split("[")[0] if len(parts) > 1 else "misc"


def _load_existing(path: Path | None) -> dict[str, dict[str, Any]]:
    """
    Indexe un template existant par acroform_name, puis par xml_path.

    Sert à ne jamais perdre le travail de rédaction déjà fait : régénérer un
    template doit rafraîchir la mécanique (chemins, types) sans toucher aux
    questions écrites à la main.
    """
    if path is None or not path.exists():
        return {}
    try:
        fields = json.loads(path.read_text(encoding="utf-8")).get("fields", [])
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Template existant illisible (%s) : %s", path, exc)
        return {}

    index: dict[str, dict[str, Any]] = {}
    for f in fields:
        if not f.get("question"):
            continue
        for key in (f.get("acroform_name"), _path_key(f.get("xml_path"))):
            if key and key not in index:
                index[key] = f
    return index


def _path_key(xml_path: str | None) -> str | None:
    """
    Clé de rapprochement d'un xml_path, insensible au sous-formulaire racine.

    Les templates rédigés à la main écrivent `Seite6/q31Unknown` là où la
    dérivation produit `mutter_dok/Seite6/q31Unknown` : on compare donc sur les
    deux derniers segments, suffisants pour identifier un champ.
    """
    if not xml_path:
        return None
    segments = [s for s in xml_path.split("/") if s]
    return "/".join(segments[-2:]) if segments else None


def build_template(pdf_path: Path, keep_technical: bool = False,
                   existing: Path | None = None) -> dict[str, Any]:
    """
    Construit le template JSON d'un formulaire medForms.

    Args:
        existing: template déjà rédigé dont on reprend les questions.

    Raises:
        GenerationError: si les noms dérivés ne se retrouvent pas dans le PDF.
    """
    prior = _load_existing(existing)
    packets = extract_xfa_packets(pdf_path)
    if "template" not in packets:
        raise GenerationError(f"{pdf_path.name} : pas de packet XFA 'template'")

    xfa_fields = parse_xfa_fields(packets["template"])
    if not xfa_fields:
        raise GenerationError(f"{pdf_path.name} : aucun champ trouvé dans le XFA")

    acro_names = set(extract_acroform_field_names(pdf_path))

    fillable, skipped, unmatched = [], [], []
    for f in xfa_fields:
        if f["ui"] in ("signature", "imageEdit", "barcode") or f["readonly"]:
            skipped.append(f["som"])
            continue
        if not keep_technical and f["name"] in TECHNICAL_NAMES:
            skipped.append(f["som"])
            continue
        if f["som"] not in acro_names:
            # exclGroup et conteneurs n'ont pas de widget propre : normal.
            unmatched.append(f["som"])
            continue
        fillable.append(f)

    if not fillable:
        raise GenerationError(f"{pdf_path.name} : aucun champ remplissable retenu")

    match_rate = len(fillable) / max(1, len(fillable) + len(unmatched))
    if match_rate < 0.5:
        raise GenerationError(
            f"{pdf_path.name} : seulement {match_rate:.0%} des champs dérivés existent "
            f"dans l'AcroForm — la dérivation SOM est probablement fausse"
        )

    sections: dict[str, int] = {}
    entries: list[dict[str, Any]] = []
    reused_keys: set[str | None] = set()

    # Les sections d'un template rédigé encodent un découpage métier que
    # SECTION_SYNTHESIS_KEYS (prompts.py) exploite pour cibler la synthèse
    # injectée dans chaque prompt. Une numérotation dérivée des pages XFA le
    # détruirait : on repart donc du numéro de section existant, et les champs
    # nouveaux vont dans une section créée après la dernière connue.
    prior_sections = {
        int(str(f["id"]).split(".")[0])
        for f in prior.values()
        if str(f.get("id", "")).split(".")[0].isdigit()
    }
    next_section = max(prior_sections) + 1 if prior_sections else 1
    counters: dict[str, int] = {}
    for f in fillable:
        kept = prior.get(f["som"]) or prior.get(_path_key(f["xml_path"])) or {}
        if kept:
            reused_keys.add(kept.get("question"))

        prior_section = str(kept.get("id", "")).split(".")[0]
        if prior_section.isdigit():
            section_no = int(prior_section)
        else:
            # Champ nouveau : regroupé par page XFA, dans une section inédite.
            page = _section_of(f["som"])
            if page not in sections:
                sections[page] = next_section + len(sections)
            section_no = sections[page]

        if section_no not in {int(str(e["comments"]).split()[1])
                              for e in entries if "comments" in e}:
            entries.append({"comments": f"Section {section_no} — {_section_of(f['som'])}"})

        counters[str(section_no)] = counters.get(str(section_no), 0) + 1
        entry: dict[str, Any] = {
            "id": f"{section_no}.{counters[str(section_no)]}",
            "name": f["name"],
            "label": f["label"] or f["name"],
            # Priorité : question rédigée à la main > vocabulaire medForms > à écrire.
            "question": kept.get("question") or f["question"],
            "required": kept.get("required", False),
            "xml_path": f["xml_path"],
            "acroform_name": f["som"],
        }
        # Un type saisi à la main l'emporte : il encode une intention métier
        # (« percent », « sex ») que l'UI XFA ne dit pas.
        resolved_type = kept.get("type") or f["vocab_type"] or f["type"]
        if resolved_type:
            entry["type"] = resolved_type
        if f["options"]:
            entry["options"] = f["options"]
        entries.append(entry)

    orphans = {q for q in (f.get("question") for f in prior.values()) if q} - reused_keys
    for q in sorted(orphans):
        logger.warning("Question rédigée sans champ correspondant, à replacer : %.90s", q)

    reused = sum(1 for e in entries if e.get("question"))
    logger.info(
        "%s : %d champs retenus, %d techniques/lecture seule écartés, %d sans widget, "
        "%d questions reprises, %d à rédiger",
        pdf_path.name, len(fillable), len(skipped), len(unmatched),
        reused, len(fillable) - reused,
    )
    return {
        "_generated_from": pdf_path.name,
        "_reviewed": False,
        "fields": entries,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", nargs="?", type=Path, help="PDF medForms local")
    parser.add_argument("--url", help="URL d'un formulaire medForms à télécharger")
    parser.add_argument("--out", type=Path, help="Fichier JSON de sortie (défaut : stdout)")
    parser.add_argument("--keep-technical", action="store_true",
                        help="Conserver les champs techniques du gabarit medForms")
    parser.add_argument("--merge", type=Path,
                        help="Template existant dont on reprend les questions déjà rédigées "
                             "(par défaut : --out s'il existe)")
    parser.add_argument("--identify", action="store_true",
                        help="Affiche le code medForms et la taxonomie du PDF, sans générer")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    pdf_path = args.pdf
    if args.url:
        import tempfile
        import urllib.request
        tmp = Path(tempfile.gettempdir()) / Path(args.url).name
        logger.info("Téléchargement de %s", args.url)
        urllib.request.urlretrieve(args.url, tmp)  # noqa: S310
        pdf_path = tmp
    if pdf_path is None:
        parser.error("fournir un PDF ou --url")

    if args.identify:
        code, taxonomy = medforms_identity(extract_xfa_packets(pdf_path))
        print(f"code      : {code or '(introuvable)'}")
        print(f"taxonomie : {taxonomy or '(introuvable)'}")
        return 0

    # Par défaut on fusionne avec la cible : régénérer ne doit jamais perdre
    # les questions déjà rédigées.
    existing = args.merge or args.out
    try:
        template = build_template(pdf_path, keep_technical=args.keep_technical,
                                  existing=existing)
    except GenerationError as exc:
        logger.error("%s", exc)
        return 1

    payload = json.dumps(template, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
        logger.info("→ %s", args.out)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
