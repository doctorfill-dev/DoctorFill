"""
DoctorFill - Générateur de documents PDF synthétiques pour évaluation RAG
=========================================================================
Génère des rapports médicaux fictifs contenant des informations patient connues
(ground truth) dans différents styles pour tester le pipeline d'extraction.

Usage:
    python generate_docs.py                     # Génère les 3 styles de base
    python generate_docs.py --count 60          # 60 docs (20 par style)
    python generate_docs.py --count 100 --noise 10  # 100 docs + 10 docs bruit
"""

import argparse
import json
import random
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("fpdf2 requis : pip install fpdf2")
    raise SystemExit(1)


GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"
OUTPUT_DIR = Path(__file__).parent / "test_docs"


def load_ground_truth() -> dict:
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# STYLES DE DOCUMENTS
# ---------------------------------------------------------------------------

def style_structured_report(gt: dict) -> str:
    """Style 1 : Rapport structuré avec en-têtes clairs."""
    f = gt["fields"]
    return f"""RAPPORT MÉDICAL STRUCTURÉ
Cabinet Dr. {f['7.2']['expected']}
Médecine générale et médecine interne FMH
Tél. {f['2.10']['expected']}

═══════════════════════════════════════════════

DONNÉES PATIENT
    Nom :           {f['2.2']['expected']}
    Prénom :        {f['2.1']['expected']}
    Date de naiss.: {f['2.3']['expected']}
    No AVS :        {f['2.4']['expected']}
    Adresse :       {f['2.5']['expected']}, {f['2.7']['expected']} {f['2.6']['expected']}
    Téléphone :     {f['2.8']['expected']}
    Sexe :          Féminin

Canton de traitement : {f['1.2']['expected']}

═══════════════════════════════════════════════

ANAMNÈSE ET SITUATION MÉDICALE

Mme {f['2.2']['expected']} {f['2.1']['expected']}, née le {f['2.3']['expected']}, consulte pour des lombalgies
chroniques persistantes depuis 2023 avec hernie discale documentée en L4-L5.
L'IRM du 15.04.2025 confirme une protrusion discale postéro-latérale droite
au niveau L4-L5 avec contact radiculaire.

Situation actuelle : douleurs lombaires basses avec irradiation dans le
membre inférieur droit jusqu'au genou. Aggravation en position assise prolongée
et lors du port de charges. Score EVA : 6/10 au repos, 8/10 en activité.

═══════════════════════════════════════════════

DIAGNOSTIC

Diagnostic principal ayant une incidence sur la capacité de travail :
- Lombalgies chroniques sur hernie discale L4-L5 (M51.1)
- Lomboradiculopathie droite L5 (M54.1)
Diagnostics posés le 20.03.2025.

Diagnostic secondaire sans incidence sur la capacité de travail :
- Hypertension artérielle contrôlée (I10)

═══════════════════════════════════════════════

TRAITEMENT

Fréquence du traitement : {f['3.1']['expected']}
Période de traitement : du {f['3.2']['expected']} au {f['3.3']['expected']}

Médication actuelle :
- Dafalgan 1000 mg, 3x/jour
- Irfen 400 mg, 2x/jour en cas de crise
- Sirdalud 4 mg au coucher

Médecin spécialiste référent : Dr. Anna Keller, Rhumatologie
Tél. spécialiste : {f['2.13']['expected']}

═══════════════════════════════════════════════

INCAPACITÉ DE TRAVAIL

Activité exercée : {f['3.8']['expected']}

Période 1 : du {f['3.10']['expected']} au {f['3.11']['expected']} — {f['3.9']['expected']}%
Période 2 : du {f['3.13']['expected']} au {f['3.14']['expected']} — {f['3.12']['expected']}%

═══════════════════════════════════════════════

PRONOSTIC

Le pronostic concernant la capacité de travail est réservé. Une reprise
progressive à 70% est envisageable dès janvier 2026 dans une activité
adaptée sans port de charges > 5 kg.

═══════════════════════════════════════════════

{f['7.2']['expected']}
Neuchâtel, le 10.03.2026
"""


def style_narrative_letter(gt: dict) -> str:
    """Style 2 : Lettre narrative du médecin (texte libre, moins structuré)."""
    f = gt["fields"]
    return f"""Dr. {f['7.2']['expected']}
Médecine générale FMH
Rue des Alpes 7, 2000 Neuchâtel
Tél. : {f['2.10']['expected']}

                                        Neuchâtel, le 10 mars 2026

À l'attention de l'Office AI du canton de {f['1.2']['expected']}

Concerne : Mme {f['2.1']['expected']} {f['2.2']['expected']}, née le {f['2.3']['expected']}
No AVS : {f['2.4']['expected']}
Domiciliée au {f['2.5']['expected']}, {f['2.7']['expected']} {f['2.6']['expected']}
Joignable au {f['2.8']['expected']}

Chère Madame, cher Monsieur,

Je vous adresse ce rapport concernant ma patiente Mme {f['2.2']['expected']}, que je
suis depuis février 2024 pour des lombalgies chroniques. L'évolution est
malheureusement défavorable malgré un traitement {f['3.1']['expected']} comprenant
physiothérapie et médication antalgique.

Sur le plan clinique, la patiente présente des douleurs lombaires basses
persistantes avec irradiation dans le membre inférieur droit. L'examen du
15.04.2025 a mis en évidence une hernie discale au niveau L4-L5 avec
compression radiculaire confirmée par IRM. Les douleurs sont constantes,
évaluées à 6/10 au repos et jusqu'à 8/10 en activité professionnelle.

Le traitement actuel comprend Dafalgan 1000 mg trois fois par jour et
Irfen 400 mg en réserve, ainsi que Sirdalud 4 mg le soir. Malgré cela, les
douleurs persistent et limitent considérablement les activités quotidiennes.

Concernant la capacité de travail, Mme {f['2.2']['expected']} exerce la profession
d'{f['3.8']['expected'].lower()}. J'ai attesté une incapacité de travail de {f['3.9']['expected']}%
du {f['3.10']['expected']} au {f['3.11']['expected']}, puis de {f['3.12']['expected']}% du {f['3.13']['expected']}
au {f['3.14']['expected']}, la période de traitement s'étendant du {f['3.2']['expected']}
au {f['3.3']['expected']}.

La patiente est également suivie par le Dr. Anna Keller, rhumatologue,
joignable au {f['2.13']['expected']}.

Je reste à votre disposition pour tout complément d'information.

Avec mes salutations distinguées,

{f['7.2']['expected']}
"""


def style_clinical_notes(gt: dict) -> str:
    """Style 3 : Notes cliniques brèves (format télégraphique)."""
    f = gt["fields"]
    return f"""NOTES CLINIQUES - CONSULTATION DU 10.03.2026

Pat. : {f['2.2']['expected']} {f['2.1']['expected']} | F | {f['2.3']['expected']} | AVS {f['2.4']['expected']}
Adr. : {f['2.5']['expected']}, {f['2.7']['expected']} {f['2.6']['expected']} | Tél. {f['2.8']['expected']}
Canton : {f['1.2']['expected']}
Méd. traitant : {f['7.2']['expected']} | Tél. cab. {f['2.10']['expected']}
Spéc. : Dr. A. Keller (Rhumato) | {f['2.13']['expected']}

---

MOTIF : Suivi lombalgies chroniques + évaluation IT

ATCD :
- Lombalgies chroniques dep. 2023
- Hernie discale L4-L5 (IRM 04/2025)
- HTA contrôlée

CLINIQUE :
- Dlrs lombaires basses + irradiation MID
- EVA 6/10 repos, 8/10 activité
- Lasègue + à 40° à droite
- Réflexes conservés, pas de déficit moteur

DG :
- Lombalgies chron. / hernie L4-L5 (M51.1)
- Lomboradiculopathie D L5 (M54.1)

TTT :
- Dafalgan 1000mg 3x/j
- Irfen 400mg 2x/j si crise
- Sirdalud 4mg HS
- Physio 2x/sem ({f['3.1']['expected']})
- Période ttt : {f['3.2']['expected']} - {f['3.3']['expected']}

IT :
- Prof : {f['3.8']['expected']}
- P1 : {f['3.10']['expected']}-{f['3.11']['expected']} = {f['3.9']['expected']}%
- P2 : {f['3.13']['expected']}-{f['3.14']['expected']} = {f['3.12']['expected']}%

PLAN : Rééval. dans 3 mois. IRM contrôle si aggravation.
"""


def style_noise_document() -> str:
    """Document bruit : contenu médical sans rapport avec le patient cible."""
    names = ["Müller Hans", "Schmidt Anna", "Weber Peter", "Fischer Sarah"]
    name = random.choice(names)
    return f"""RAPPORT DE LABORATOIRE

Patient : {name}
Date : 05.02.2026
Référence : LAB-2026-{random.randint(10000, 99999)}

Résultats d'analyses sanguines :

Hématologie
- Hémoglobine : {random.uniform(12, 16):.1f} g/dL (N: 12.0-16.0)
- Leucocytes : {random.uniform(4, 10):.1f} G/L (N: 4.0-10.0)
- Thrombocytes : {random.randint(150, 400)} G/L (N: 150-400)
- VS : {random.randint(2, 25)} mm/h (N: <20)

Chimie clinique
- Créatinine : {random.randint(60, 100)} µmol/L (N: 60-100)
- ASAT : {random.randint(10, 40)} U/L (N: 10-40)
- ALAT : {random.randint(10, 40)} U/L (N: 10-40)
- CRP : {random.uniform(0.1, 5):.1f} mg/L (N: <5.0)
- Glycémie : {random.uniform(4, 6):.1f} mmol/L (N: 4.1-5.9)
- HbA1c : {random.uniform(4.5, 6):.1f}% (N: <6.0%)
- TSH : {random.uniform(0.5, 4):.2f} mUI/L (N: 0.4-4.0)
- Cholestérol total : {random.uniform(4, 6):.1f} mmol/L

Conclusion : bilan dans les normes. Pas de suite particulière.

Laboratoire Unilabs SA, Neuchâtel
"""


STYLES = [style_structured_report, style_narrative_letter, style_clinical_notes]


# ---------------------------------------------------------------------------
# GÉNÉRATION PDF
# ---------------------------------------------------------------------------

def text_to_pdf(text: str, output_path: Path):
    """Convertit un texte en PDF simple."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    # Utiliser une police avec support Unicode
    pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", uni=True)
    pdf.set_font("DejaVu", size=9)
    for line in text.split("\n"):
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(output_path))


def text_to_pdf_fallback(text: str, output_path: Path):
    """Fallback si DejaVu n'est pas disponible (macOS)."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Helvetica", size=9)
    for line in text.split("\n"):
        # Remplacer les caractères non-latin1 pour Helvetica
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        pdf.cell(0, 5, safe_line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(output_path))


def create_pdf(text: str, output_path: Path):
    """Crée un PDF, avec fallback si la police Unicode n'est pas dispo."""
    try:
        text_to_pdf(text, output_path)
    except (RuntimeError, OSError):
        text_to_pdf_fallback(text, output_path)


def generate(count: int = 3, noise: int = 0):
    """Génère les documents de test."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Nettoyer les anciens fichiers
    for f in OUTPUT_DIR.glob("*.pdf"):
        f.unlink()

    gt = load_ground_truth()

    # Répartir les styles
    docs_per_style = max(1, count // len(STYLES))
    remainder = count - docs_per_style * len(STYLES)

    doc_index = 0
    for style_idx, style_fn in enumerate(STYLES):
        n = docs_per_style + (1 if style_idx < remainder else 0)
        style_name = style_fn.__name__.replace("style_", "")
        for i in range(n):
            doc_index += 1
            text = style_fn(gt)
            path = OUTPUT_DIR / f"patient_{doc_index:03d}_{style_name}.pdf"
            create_pdf(text, path)

    # Documents bruit
    for i in range(noise):
        doc_index += 1
        text = style_noise_document()
        path = OUTPUT_DIR / f"noise_{doc_index:03d}.pdf"
        create_pdf(text, path)

    total = doc_index
    print(f"Généré {count} documents patient + {noise} documents bruit = {total} PDFs")
    print(f"Répertoire : {OUTPUT_DIR}")
    print(f"Styles : {docs_per_style} par style ({', '.join(s.__name__ for s in STYLES)})")

    # Sauvegarder le manifest
    manifest = {
        "total_docs": total,
        "patient_docs": count,
        "noise_docs": noise,
        "ground_truth": str(GROUND_TRUTH_PATH.name),
        "form_id": gt["_meta"]["form_id"],
        "styles": [s.__name__ for s in STYLES],
    }
    with open(OUTPUT_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère des PDFs de test pour DoctorFill")
    parser.add_argument("--count", type=int, default=3, help="Nombre de documents patient (default: 3)")
    parser.add_argument("--noise", type=int, default=0, help="Nombre de documents bruit (default: 0)")
    args = parser.parse_args()
    generate(count=args.count, noise=args.noise)
