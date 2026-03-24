"""
prompts.py — Centralisation de tous les prompts LLM de DoctorFill.

Trois familles de prompts :
1. Synthèse médicale globale (nouveau pipeline)
2. Résumé par document (pipeline hiérarchique, si trop de documents)
3. Extraction de champs (remplissage du formulaire — mode batch)
"""

from typing import Dict, List

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
# 3. EXTRACTION BATCH (remplissage du formulaire — plusieurs champs par appel)
# ---------------------------------------------------------------------------

# Mapping section → clés de la synthèse pertinentes
# La clé est le préfixe de l'ID du champ (avant le premier '.')
SECTION_SYNTHESIS_KEYS: Dict[str, List[str]] = {
    "1":  ["canton_traitement", "patient"],
    "2":  ["patient", "medecins"],
    "3":  ["incapacites_travail", "dates_cles"],
    "4":  ["diagnostics", "traitements"],
    "5":  ["incapacites_travail", "pronostic"],
    "6":  ["incapacites_travail", "traitements"],
    "7":  ["medecins"],
    "8":  ["diagnostics", "traitements"],
    "9":  ["medecins"],
    "10": ["pronostic"],
}


SYSTEM_PROMPT_BATCH_EXTRACT = """\
Tu es un assistant spécialisé dans l'extraction précise de données depuis des dossiers médicaux suisses.
On te fournit une SYNTHÈSE MÉDICALE structurée et/ou des EXTRAITS de documents, \
ainsi qu'une liste de CHAMPS à remplir pour un formulaire administratif.

RÈGLES STRICTES :
1. Cherche la réponse de chaque champ EN PRIORITÉ dans la SYNTHÈSE MÉDICALE si elle est fournie.
2. Si la synthèse ne contient pas l'information, cherche dans les EXTRAITS DE DOCUMENTS.
3. Si l'information est introuvable dans toutes les sources, retourne exactement "" (chaîne vide).
4. NE JAMAIS inventer, déduire ou supposer une valeur absente des sources.
5. Réponds UNIQUEMENT en JSON valide, sans texte avant ou après.
6. Réponds à TOUS les IDs demandés, même si la valeur est "".
7. Pour les dates, utilise le format DD.MM.YYYY.
8. Pour les listes (ex: diagnostics), liste TOUTES les entrées séparées par des sauts de ligne.
9. "source_quote" doit être la citation EXACTE du texte source (max 100 caractères).
   Si valeur vide, mettre "" pour source_quote aussi.
"""


def build_batch_extraction_prompt(
    fields: List[Dict],
    synthesis_json: str | None,
    chunks_context: str | None,
) -> str:
    """
    Construit le prompt pour extraire plusieurs champs en un seul appel LLM.
    La synthèse est déjà pré-filtrée sur la section pertinente.
    """
    import json as _json

    parts = []

    if synthesis_json:
        parts.append(f"SYNTHÈSE MÉDICALE (source principale) :\n{synthesis_json}")

    if chunks_context:
        parts.append(f"EXTRAITS DE DOCUMENTS (source secondaire) :\n{chunks_context}")

    field_lines = "\n".join(f'• [{f["id"]}] {f["question"]}' for f in fields)
    parts.append(f"CHAMPS À EXTRAIRE :\n{field_lines}")

    # Fournir un exemple JSON avec tous les IDs pour guider le modèle
    example = {str(f["id"]): {"value": "...", "source_quote": "..."} for f in fields}
    parts.append(
        f"RÉPONDS UNIQUEMENT avec ce JSON (tous les IDs sont obligatoires) :\n"
        + _json.dumps(example, ensure_ascii=False, indent=2)
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Compatibilité ascendante (ancienne interface mono-champ)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_EXTRACT = SYSTEM_PROMPT_BATCH_EXTRACT


def build_field_extraction_prompt(
    question: str,
    synthesis_json: str | None,
    chunks_context: str | None,
) -> str:
    """Interface mono-champ conservée pour compatibilité."""
    return build_batch_extraction_prompt(
        fields=[{"id": "result", "question": question}],
        synthesis_json=synthesis_json,
        chunks_context=chunks_context,
    )


# ---------------------------------------------------------------------------
# 4. CHAT MÉDICAL INTERACTIF
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_CHAT = """\
Tu es un assistant médical expert qui analyse le dossier médical d'un patient spécifique.
Tu as accès à : (1) une synthèse structurée du dossier, (2) les valeurs pré-remplies dans le formulaire administratif, (3) des extraits pertinents des documents originaux.

RÈGLES STRICTES :
1. Réponds en français, de manière précise et concise.
2. Base-toi UNIQUEMENT sur les informations présentes dans les données fournies.
3. Si l'information demandée est absente, dis-le clairement : "Cette information ne figure pas dans les documents."
4. Ne pose pas de diagnostic, ne prescris rien — tu analyses et résumes des données existantes.
5. Cite les sources quand c'est utile (ex: "selon le rapport du Dr X du...").
6. **Formate toujours tes réponses en Markdown** : utilise les listes (`-`), le gras (`**`), les titres (`###`) et les blocs de code si pertinent.
7. Pour les listes (diagnostics, traitements, périodes), utilise des puces Markdown avec une entrée par ligne.
"""


def build_chat_messages(
    synthesis_json: str | None,
    chunks_context: str | None,
    fields_context: str | None,
    history: List[Dict],
    question: str,
) -> List[Dict]:
    """Construit la liste de messages pour le chat médical (format OpenAI)."""
    messages: List[Dict] = [{"role": "system", "content": SYSTEM_PROMPT_CHAT}]

    # Injecter le contexte comme premier échange (grounding)
    context_parts = []
    if synthesis_json:
        context_parts.append(f"SYNTHÈSE MÉDICALE STRUCTURÉE :\n{synthesis_json}")
    if fields_context:
        context_parts.append(f"VALEURS PRÉ-REMPLIES DANS LE FORMULAIRE :\n{fields_context}")
    if chunks_context:
        context_parts.append(f"EXTRAITS PERTINENTS DES DOCUMENTS ORIGINAUX :\n{chunks_context}")

    if context_parts:
        messages.append({
            "role": "user",
            "content": "Voici le dossier médical du patient :\n\n" + "\n\n---\n\n".join(context_parts),
        })
        messages.append({
            "role": "assistant",
            "content": "J'ai pris connaissance du dossier médical et des valeurs pré-remplies dans le formulaire. Je suis prêt à répondre à vos questions.",
        })

    # Historique de conversation
    for msg in history:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Question courante
    messages.append({"role": "user", "content": question})
    return messages
