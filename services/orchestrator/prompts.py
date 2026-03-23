"""
prompts.py — Centralisation de tous les prompts LLM de DoctorFill.

Trois familles de prompts :
1. Synthèse médicale globale (nouveau pipeline)
2. Résumé par document (pipeline hiérarchique, si trop de documents)
3. Extraction de champ (remplissage du formulaire)
"""

# ---------------------------------------------------------------------------
# 1. SYNTHÈSE MÉDICALE GLOBALE
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_SYNTHESIS = """\
Tu es un médecin expert spécialisé dans l'analyse de dossiers médicaux complexes.
On te fournit le contenu intégral de plusieurs documents médicaux (rapports, expertises, bilans).

TON RÔLE :
Extraire de manière EXHAUSTIVE et STRUCTURÉE toutes les informations médicales pertinentes
présentes dans l'ensemble des documents fournis.

RÈGLES ABSOLUES :
1. NE LAISSE AUCUN diagnostic de côté, même les antécédents ou diagnostics secondaires.
2. Pour chaque diagnostic, note TOUJOURS la date si elle est mentionnée et le document source.
3. Extrais TOUTES les périodes d'incapacité de travail avec leurs taux exacts.
4. Si deux documents donnent des informations contradictoires sur la même chose, inclus les deux
   avec leurs sources respectives et date la plus récente en premier.
5. Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après le JSON.
6. Si une information est absente, utilise null (pas de chaîne vide, pas "inconnu").
7. Conserve les codes ICD/CIM exacts s'ils sont mentionnés (ex: M54.4, F32.1).
8. Pour les dates, utilise le format DD.MM.YYYY.
"""


def build_synthesis_prompt(docs_text: str) -> str:
    """
    Prompt utilisateur pour la synthèse globale (tous les documents en un seul appel).
    Utilisé quand le total de tokens est < 28 000.
    """
    return f"""\
DOCUMENTS MÉDICAUX À ANALYSER :
{docs_text}

---

Produis une synthèse médicale complète en JSON avec la structure suivante :

{{
  "patient": {{
    "nom": "...",
    "prenom": "...",
    "date_naissance": "DD.MM.YYYY",
    "numero_avs": "...",
    "adresse": "...",
    "canton": "..."
  }},
  "diagnostics": [
    {{
      "code_icd": "...",
      "description": "...",
      "date_diagnostic": "DD.MM.YYYY",
      "document_source": "...",
      "medecin": "...",
      "statut": "principal | secondaire | antecedent"
    }}
  ],
  "incapacites_travail": [
    {{
      "taux": 50,
      "date_debut": "DD.MM.YYYY",
      "date_fin": "DD.MM.YYYY",
      "motif": "...",
      "document_source": "..."
    }}
  ],
  "traitements": [
    {{
      "type": "medicament | physiotherapie | chirurgie | autre",
      "description": "...",
      "date_debut": "DD.MM.YYYY",
      "date_fin": "DD.MM.YYYY"
    }}
  ],
  "medecins": [
    {{
      "nom": "...",
      "prenom": "...",
      "specialite": "...",
      "etablissement": "...",
      "role": "traitant | consultant | expert"
    }}
  ],
  "dates_cles": {{
    "premier_arret_travail": "DD.MM.YYYY",
    "debut_maladie": "DD.MM.YYYY",
    "derniere_consultation": "DD.MM.YYYY",
    "accident": "DD.MM.YYYY"
  }},
  "pronostic": "...",
  "canton_traitement": "..."
}}

RAPPEL : inclus ABSOLUMENT tous les diagnostics, même les antécédents et les diagnostics secondaires.\
"""


# ---------------------------------------------------------------------------
# 2. SYNTHÈSE HIÉRARCHIQUE (par document, puis fusion)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_PER_DOC_SUMMARY = """\
Tu es un médecin expert. On te fournit un document médical.
Extrais toutes les informations médicales importantes de ce document.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après.
"""


def build_per_doc_summary_prompt(doc_text: str, doc_name: str) -> str:
    """
    Prompt pour résumer un document individuel (pipeline hiérarchique).
    Utilisé quand le total de tokens dépasse 28 000.
    """
    return f"""\
DOCUMENT : {doc_name}

CONTENU :
{doc_text}

---

Extrais les informations médicales de ce document en JSON :

{{
  "document": "{doc_name}",
  "patient": {{
    "nom": null,
    "prenom": null,
    "date_naissance": null,
    "numero_avs": null
  }},
  "diagnostics": [
    {{
      "code_icd": null,
      "description": "...",
      "date_diagnostic": null,
      "statut": "principal | secondaire | antecedent"
    }}
  ],
  "incapacites_travail": [
    {{
      "taux": null,
      "date_debut": null,
      "date_fin": null,
      "motif": null
    }}
  ],
  "traitements": ["..."],
  "medecins": [
    {{
      "nom": "...",
      "specialite": "...",
      "role": "traitant | consultant | expert"
    }}
  ],
  "dates_importantes": ["DD.MM.YYYY : description"],
  "pronostic": null
}}\
"""


SYSTEM_PROMPT_MERGE_SUMMARIES = """\
Tu es un médecin expert. On te fournit les résumés JSON de plusieurs documents médicaux d'un même patient.
Fusionne ces résumés en un seul dossier médical complet et cohérent.
En cas de conflit entre documents, garde TOUTES les versions avec leurs sources.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après.
"""


def build_merge_summaries_prompt(summaries_json: str) -> str:
    """
    Prompt pour fusionner les résumés de chaque document en un seul JSON.
    """
    return f"""\
RÉSUMÉS DES DOCUMENTS MÉDICAUX :
{summaries_json}

---

Fusionne ces résumés en un dossier médical unifié. Structure identique à celle demandée
dans la synthèse globale (patient, diagnostics[], incapacites_travail[], traitements[],
medecins[], dates_cles{{}}, pronostic, canton_traitement).

IMPORTANT : inclus TOUS les diagnostics de TOUS les documents, sans en omettre aucun.
Ajoute un champ "document_source" à chaque diagnostic et chaque période d'incapacité.\
"""


# ---------------------------------------------------------------------------
# 3. EXTRACTION DE CHAMP (remplissage du formulaire)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_EXTRACT = """\
Tu es un assistant spécialisé dans l'extraction de données depuis des documents médicaux.
On te fournit une SYNTHÈSE MÉDICALE STRUCTURÉE et/ou des EXTRAITS de documents,
ainsi qu'une QUESTION sur un champ de formulaire.

RÈGLES STRICTES :
1. Cherche la réponse en priorité dans la SYNTHÈSE MÉDICALE si elle est fournie.
2. Si la synthèse ne contient pas l'information, cherche dans les EXTRAITS DE DOCUMENTS.
3. Extrais la valeur EXACTE telle qu'elle apparaît dans les sources.
4. Ne réponds "Inconnu" que si l'information est RÉELLEMENT ABSENTE de toutes les sources.
5. Réponds UNIQUEMENT en JSON valide avec la structure : {"value": "...", "source_quote": "..."}.
6. Pour les dates, conserve le format DD.MM.YYYY.
7. Pour les noms/prénoms, conserve la casse originale.
8. Pour les listes de diagnostics, liste-les TOUS séparés par des virgules ou retours à la ligne.
"""


def build_field_extraction_prompt(
    question: str,
    synthesis_json: str | None,
    chunks_context: str | None,
) -> str:
    """
    Construit le prompt utilisateur pour l'extraction d'un champ.
    Utilise la synthèse comme source primaire et les chunks comme source secondaire.
    """
    parts = []

    if synthesis_json:
        parts.append(f"SYNTHÈSE MÉDICALE DU PATIENT :\n{synthesis_json}")

    if chunks_context:
        parts.append(f"EXTRAITS DE DOCUMENTS (source secondaire) :\n{chunks_context}")

    parts.append(f"QUESTION : {question}")

    return "\n\n".join(parts)
