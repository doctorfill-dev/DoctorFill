"""
Vérité terrain dérivée des scénarios de test, pour les 21 formulaires.

`ground_truth.json` ne couvre qu'un formulaire (AI_ReadaptationRente) et a dû
être réaligné à la main à chaque régénération de template. Les dossiers de
`eval/dossiers/` sont, eux, générés à partir de scénarios structurés (patient,
médecin, incapacités, diagnostics) : la valeur attendue d'un champ se déduit
donc de sa structure medForms et de son nom, pour n'importe quel formulaire.

Seuls les faits effectivement présents dans le texte du dossier sont retenus :
un champ que le dossier ne documente pas ne peut pas être reproché au modèle.

Utilisé par eval/regression.py (contre le vrai backend) et par les tests de
l'orchestrateur (services simulés) : les deux mesurent avec la même règle.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
REPO_DIR = EVAL_DIR.parent
ORCHESTRATOR_DIR = REPO_DIR / "services" / "orchestrator"
DOSSIERS_DIR = EVAL_DIR / "dossiers"
TEMPLATES_DIR = ORCHESTRATOR_DIR / "template"

for _path in (EVAL_DIR, ORCHESTRATOR_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from core.fields import coding_systems, fold, normalize_date, prepare_fields  # noqa: E402
from core.provenance import SourceIndex  # noqa: E402

# (structure, champ) → (attribut du patient, tolérance)
_PATIENT = {
    "lastName": ("nom", "exact"), "firstName": ("prenom", "exact"),
    "birthDate": ("naissance", "date"), "sex": ("sexe", "exact"), "ssn": ("avs", "alnum"),
    "street": ("rue", "fuzzy"), "zip": ("npa", "exact"), "city": ("ville", "fuzzy"),
    "phone": ("tel", "phone"), "email": ("email", "exact"),
}
# Le fournisseur de prestations est le médecin traitant du scénario.
_PROVIDER = {
    "ean": ("gln", "alnum"), "zsr": ("rcc", "alnum"), "phone": ("tel", "phone"),
    "email": ("email", "exact"), "street": ("rue", "fuzzy"), "zip": ("npa", "exact"),
    "city": ("ville", "fuzzy"),
}

_INDEX = re.compile(r"\[(\d+)\]$")


@dataclass
class Expectation:
    expected: str
    tolerance: str
    category: str

    def as_dict(self) -> dict[str, str]:
        return {"expected": self.expected, "tolerance": self.tolerance, "category": self.category}


def load_scenarios() -> dict[str, Any]:
    """Scénarios par identifiant de formulaire."""
    from dossiers import SCENARIOS
    return {s.form: s for s in SCENARIOS}


def dossier_documents(form_id: str) -> list[dict[str, str]]:
    """Texte des documents d'un dossier, tel que l'OCR le rendrait."""
    folder = DOSSIERS_DIR / form_id
    return [{"filename": md.with_suffix(".pdf").name, "markdown": md.read_text(encoding="utf-8")}
            for md in sorted(folder.glob("[0-9]*.md"))]


def dossier_pdfs(form_id: str) -> list[Path]:
    return sorted((DOSSIERS_DIR / form_id).glob("[0-9]*.pdf"))


def load_template(form_id: str, templates_dir: Path = TEMPLATES_DIR) -> dict:
    return json.loads((templates_dir / f"Form_{form_id}.json").read_text(encoding="utf-8"))


def _segments(field: dict) -> list[str]:
    return [s for s in str(field.get("xml_path") or "").split("/") if s]


def _index(segment: str) -> int:
    match = _INDEX.search(segment)
    return int(match.group(1)) if match else 0


def _bare(segment: str) -> str:
    return _INDEX.sub("", segment)


def _candidates(scenario, fields: list[dict], coding: dict[str, str]) -> dict[str, Expectation]:
    """Valeur attendue de chaque champ que le scénario renseigne."""
    patient, medecin = scenario.patient, scenario.medecin
    truth: dict[str, Expectation] = {}
    diagnosis_rank = 0
    for field in fields:
        parts = _segments(field)
        if not parts:
            continue
        leaf_segment = parts[-1]
        leaf = _bare(leaf_segment)
        container = parts[-2] if len(parts) >= 2 else ""
        struct = _bare(container)
        fid = str(field["id"])

        if leaf == "treatmentCanton":
            truth[fid] = Expectation(patient.canton, "exact", "admin")
        elif struct == "patientS1Address" and leaf in _PATIENT and _index(leaf_segment) == 0:
            attr, tol = _PATIENT[leaf]
            truth[fid] = Expectation(getattr(patient, attr), tol, "patient")
        elif struct == "providerS1Address" and leaf in _PROVIDER and _index(leaf_segment) == 0:
            attr, tol = _PROVIDER[leaf]
            truth[fid] = Expectation(getattr(medecin, attr), tol, "medecin")
        elif struct == "unemployabilityS1Struct" and leaf in ("beginDate", "endDate", "percentageNum"):
            rank = _index(container)
            if rank < len(scenario.incapacites):
                begin, end, rate = scenario.incapacites[rank]
                value, tol = {"beginDate": (begin, "date"), "endDate": (end, "date"),
                              "percentageNum": (rate, "percent")}[leaf]
                truth[fid] = Expectation(value, tol, "incapacite")
        elif struct.endswith("diagnosisS1Struct") and leaf == "code" \
                and coding.get("/".join(parts[:-1])) != "CHOP":
            if diagnosis_rank < len(scenario.diagnostics):
                truth[fid] = Expectation(scenario.diagnostics[diagnosis_rank][0], "alnum", "diagnostic")
            diagnosis_rank += 1
        elif struct == "employerS1Address" and leaf in ("condensedName", "companyName"):
            truth[fid] = Expectation(patient.employeur, "fuzzy", "travail")
        elif leaf == "profession":
            truth[fid] = Expectation(patient.profession, "fuzzy", "travail")
        elif struct == "lawS1Struct" and leaf == "caseDate" and scenario.accident:
            truth[fid] = Expectation(scenario.accident.get("date", ""), "date", "accident")
    return {k: v for k, v in truth.items() if str(v.expected or "").strip()}


def derive_truth(form_id: str, templates_dir: Path = TEMPLATES_DIR) -> dict[str, Expectation]:
    """
    Vérité terrain d'un formulaire : les champs extraits par le pipeline dont le
    scénario fixe la valeur, et que le dossier documente réellement.
    """
    scenario = load_scenarios()[form_id]
    template = load_template(form_id, templates_dir)
    fields = prepare_fields(template)
    index = SourceIndex(dossier_documents(form_id))
    truth = {}
    for fid, exp in _candidates(scenario, fields, coding_systems(template)).items():
        needle = exp.expected
        if exp.tolerance == "percent":
            needle = re.sub(r"\D", "", needle)
        if index.find(needle, whole_words=True) is not None:
            truth[fid] = exp
    return truth


# ---------------------------------------------------------------------------
# Comparaison
# ---------------------------------------------------------------------------

def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", fold(text))


def _phone(text: str) -> str:
    digits = re.sub(r"\D", "", text)
    if digits.startswith("0041"):
        digits = "0" + digits[4:]
    elif digits.startswith("41") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[0-9a-z]+", fold(text)))


def matches(expected: str, extracted: str, tolerance: str) -> bool:
    """La valeur extraite équivaut-elle à la valeur attendue ?"""
    if not str(extracted or "").strip():
        return False
    if tolerance == "date":
        return normalize_date(expected) == normalize_date(extracted)
    if tolerance == "alnum":
        return _alnum(expected) == _alnum(extracted)
    if tolerance == "phone":
        return _phone(expected) == _phone(extracted)
    if tolerance == "percent":
        exp, ext = re.search(r"\d+", expected), re.search(r"\d+", extracted)
        return bool(exp and ext) and int(exp.group()) == int(ext.group())
    if tolerance == "fuzzy":
        a, b = fold(expected), fold(extracted)
        if a in b or b in a:
            return True
        ta, tb = _tokens(a), _tokens(b)
        return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6
    return fold(expected) == fold(extracted)


def score(truth: dict[str, Expectation], fields_payload: list[dict]) -> dict[str, Any]:
    """
    Compare le résultat de /fields à la vérité terrain.

    Returns:
        métriques (précision, taux de remplissage, erreurs) et détail par champ.
    """
    by_id = {str(f["id"]): f for f in fields_payload}
    details = []
    correct = 0
    for fid, exp in sorted(truth.items(), key=lambda kv: [int(p) for p in kv[0].split(".")]):
        got = str((by_id.get(fid) or {}).get("value") or "")
        ok = matches(exp.expected, got, exp.tolerance)
        correct += ok
        details.append({"id": fid, "category": exp.category, "expected": exp.expected,
                        "extracted": got, "match": ok,
                        "status": "ok" if ok else ("missing" if not got.strip() else "wrong")})
    filled = sum(1 for f in fields_payload if str(f.get("value") or "").strip())
    errors = sum(1 for f in fields_payload if f.get("error"))
    return {
        "truth_fields": len(truth),
        "correct": correct,
        "accuracy": round(correct / len(truth), 4) if truth else None,
        "fields": len(fields_payload),
        "filled": filled,
        "fill_rate": round(filled / len(fields_payload), 4) if fields_payload else None,
        "errors": errors,
        "details": details,
    }
