"""
Rendu des dossiers patients de test, en markdown puis en PDF.

Un dossier par formulaire du catalogue : chaque scénario décrit une situation
clinique dans laquelle *ce* formulaire est celui qu'un médecin remplirait
réellement. Sans ça, une extraction ne peut pas être jugée — un formulaire de
moyens auxiliaires AI sur un dossier sans procédure AI laisse forcément vide le
champ qui compte, et le résultat est ininterprétable.

Les documents ne contiennent aucune donnée réelle : patients, médecins,
assureurs et numéros sont fictifs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Patient:
    nom: str
    prenom: str
    sexe: str                 # "M" ou "F"
    naissance: str            # JJ.MM.AAAA
    avs: str
    rue: str
    npa: str
    ville: str
    canton: str               # code à deux lettres
    tel: str
    email: str
    etat_civil: str
    profession: str
    employeur: str = ""
    taux_activite: str = "100 %"


@dataclass
class Medecin:
    nom: str
    specialite: str
    cabinet: str
    rue: str
    npa: str
    ville: str
    tel: str
    email: str
    rcc: str
    gln: str


@dataclass
class Scenario:
    """Une situation clinique et le formulaire qu'elle appelle."""
    form: str
    titre: str
    patient: Patient
    medecin: Medecin
    assureur: str
    police: str
    date_rapport: str
    contexte: str                                   # pourquoi ce formulaire
    anamnese: str
    antecedents: list[str]
    diagnostics: list[tuple[str, str, str]]         # (code, libellé, date)
    traitements: list[str]
    consultations: list[tuple[str, str]]            # (date, note SOAP)
    incapacites: list[tuple[str, str, str]] = field(default_factory=list)
    accident: dict | None = None
    documents: list[tuple[str, str, str]] = field(default_factory=list)
    evolution: str = ""
    pronostic: str = ""


# ---------------------------------------------------------------------------
# Rendu markdown
# ---------------------------------------------------------------------------

def _fiche_administrative(s: Scenario) -> str:
    p, m = s.patient, s.medecin
    lignes = [
        "# Fiche administrative",
        "",
        f"Établie le {s.date_rapport} — document interne du cabinet.",
        "",
        "## Identité",
        "",
        f"- Nom : {p.nom}",
        f"- Prénom : {p.prenom}",
        f"- Sexe : {p.sexe}",
        f"- Date de naissance : {p.naissance}",
        f"- N° AVS : {p.avs}",
        f"- État civil : {p.etat_civil}",
        "",
        "## Coordonnées",
        "",
        f"- Adresse : {p.rue}, {p.npa} {p.ville} (canton de {p.canton})",
        f"- Téléphone : {p.tel}",
        f"- E-mail : {p.email}",
        "",
        "## Situation professionnelle",
        "",
        f"- Profession : {p.profession}",
    ]
    if p.employeur:
        lignes.append(f"- Employeur : {p.employeur}")
    lignes += [
        f"- Taux d'activité : {p.taux_activite}",
        "",
        "## Couverture",
        "",
        f"- Assureur concerné : {s.assureur}",
        f"- N° de police / de contrat : {s.police}",
        "",
        "## Médecin traitant",
        "",
        f"- {m.nom}, {m.specialite}",
        f"- {m.cabinet}, {m.rue}, {m.npa} {m.ville}",
        f"- Téléphone : {m.tel}",
        f"- E-mail : {m.email}",
        f"- N° RCC : {m.rcc}",
        f"- N° GLN : {m.gln}",
        "",
        "## Contexte de la démarche",
        "",
        s.contexte,
        "",
    ]
    return "\n".join(lignes)


def _anamnese(s: Scenario) -> str:
    lignes = [
        "# Anamnèse et antécédents",
        "",
        f"Patient : {s.patient.nom} {s.patient.prenom}, né(e) le {s.patient.naissance}",
        "",
        "## Anamnèse actuelle",
        "",
        s.anamnese,
        "",
        "## Antécédents",
        "",
    ]
    lignes += [f"- {a}" for a in s.antecedents]
    lignes += ["", "## Diagnostics retenus", ""]
    for code, libelle, date in s.diagnostics:
        lignes.append(f"- {libelle} ({code}) — depuis le {date}")
    lignes += ["", "## Traitement en cours", ""]
    lignes += [f"- {t}" for t in s.traitements]
    lignes.append("")
    return "\n".join(lignes)


def _consultations(s: Scenario) -> str:
    lignes = [
        "# Notes de consultation",
        "",
        f"Patient : {s.patient.nom} {s.patient.prenom}, {s.patient.naissance}",
        "Format SOAP, ordre antichronologique.",
        "",
    ]
    for date, note in s.consultations:
        lignes += [f"## Consultation du {date}", "", note.strip(), ""]
    if s.evolution:
        lignes += ["## Évolution", "", s.evolution.strip(), ""]
    if s.pronostic:
        lignes += ["## Pronostic", "", s.pronostic.strip(), ""]
    return "\n".join(lignes)


def _incapacites(s: Scenario) -> str:
    if not s.incapacites:
        return ""
    lignes = [
        "# Attestations d'incapacité de travail",
        "",
        f"Patient : {s.patient.nom} {s.patient.prenom}, {s.patient.naissance}",
        f"Profession : {s.patient.profession}",
        "",
    ]
    for debut, fin, taux in s.incapacites:
        borne = f"du {debut} au {fin}" if fin else f"depuis le {debut}, sans terme fixé"
        lignes.append(f"- Incapacité de travail de {taux} {borne}.")
    lignes.append("")
    return "\n".join(lignes)


def _accident(s: Scenario) -> str:
    if not s.accident:
        return ""
    a = s.accident
    lignes = [
        "# Déclaration d'accident",
        "",
        f"Patient : {s.patient.nom} {s.patient.prenom}, {s.patient.naissance}",
        "",
        f"- Date de l'accident : {a['date']}",
        f"- Heure : {a['heure']}",
        f"- Lieu : {a['lieu']}",
        f"- Employeur au moment des faits : {a.get('employeur', s.patient.employeur)}",
        f"- Assureur-accidents : {s.assureur}, police {s.police}",
        "",
        "## Déroulement",
        "",
        a["description"].strip(),
        "",
    ]
    if a.get("temoin"):
        lignes += ["## Témoin", "", a["temoin"], ""]
    if a.get("premiers_soins"):
        lignes += ["## Premiers soins", "", a["premiers_soins"].strip(), ""]
    return "\n".join(lignes)


def documents(s: Scenario) -> list[tuple[str, str]]:
    """Retourne la liste (nom de fichier sans extension, contenu markdown)."""
    out = [
        ("01_fiche-administrative", _fiche_administrative(s)),
        ("02_anamnese-antecedents", _anamnese(s)),
        ("03_consultations", _consultations(s)),
    ]
    index = 4
    for nom, titre, corps in s.documents:
        entete = f"# {titre}\n\nPatient : {s.patient.nom} {s.patient.prenom}, {s.patient.naissance}\n\n"
        out.append((f"{index:02d}_{nom}", entete + corps.strip() + "\n"))
        index += 1
    for renderer in (_accident, _incapacites):
        corps = renderer(s)
        if corps:
            nom = "accident" if renderer is _accident else "incapacites-travail"
            out.append((f"{index:02d}_{nom}", corps))
            index += 1
    return out


# ---------------------------------------------------------------------------
# Rendu PDF
# ---------------------------------------------------------------------------

def _plain(markdown: str) -> str:
    """Aplatit le markdown : les PDF de test imitent des exports de DPI."""
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text)


# Repli sans police Unicode : translittérer plutôt que remplacer. Les « ? »
# produits par un encodage latin-1 se retrouvaient tels quels dans les valeurs
# extraites — un défaut du corpus qu'on aurait imputé au pipeline.
_TRANSLITTERATION = str.maketrans({
    "—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
    "…": "...", "«": '"', "»": '"', " ": " ", "€": "EUR", "×": "x",
})

# Chemins usuels d'une police Unicode, Debian puis Arch. `fc-match` est un
# meilleur repli mais suppose fontconfig ; on l'essaie en dernier.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)


def _unicode_font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    try:
        import subprocess
        found = subprocess.run(["fc-match", "-f", "%{file}", "sans-serif"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return found if found.endswith((".ttf", ".otf")) and Path(found).exists() else None
    except Exception:
        return None


def to_pdf(markdown: str, path: Path) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    font = _unicode_font()
    if font:
        pdf.add_font("corps", "", font)
        pdf.set_font("corps", size=9)
        encode = lambda t: t  # noqa: E731
    else:
        pdf.set_font("Helvetica", size=9)
        encode = lambda t: t.translate(_TRANSLITTERATION).encode(  # noqa: E731
            "latin-1", "replace").decode("latin-1")
    for line in _plain(markdown).split("\n"):
        pdf.multi_cell(0, 5, encode(line) or " ", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
