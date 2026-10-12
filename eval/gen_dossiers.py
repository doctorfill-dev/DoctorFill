"""
Génère un dossier patient par formulaire du catalogue.

Chaque dossier décrit une situation clinique dans laquelle *ce* formulaire est
celui qu'un médecin remplirait réellement. C'est la condition pour qu'un
résultat d'extraction soit interprétable : un formulaire de moyens auxiliaires
AI passé sur un dossier sans procédure AI laisse forcément vide le champ qui
compte, et on ne sait alors rien de la qualité du pipeline.

    python gen_dossiers.py                    # tous les dossiers
    python gen_dossiers.py --form LCA_IncapaciteTravail      # et ses variantes
    python gen_dossiers.py --markdown-only    # sans les PDF

Sortie : eval/dossiers/<dossier>/NN_<document>.md (+ .pdf), où <dossier> est le
formulaire, ou <formulaire>__<cas> pour une variante. Seuls les 21 dossiers de
base sont versionnés : une variante se déduit de son scénario
(`dossiers/scenarios_cas.py`), et `truth.py` la rend à la demande. La générer
ici ne sert qu'à la lire.
"""

import argparse
import json
from pathlib import Path

from dossiers import SCENARIOS
from dossiers.render import documents, illegible_documents, illegible_pdf, to_pdf

OUT_DIR = Path(__file__).parent / "dossiers"


def main() -> int:
    parser = argparse.ArgumentParser(description="Générateur de dossiers patients de test")
    parser.add_argument("--form", help="Ne générer que ce formulaire (variantes comprises) ou ce dossier")
    parser.add_argument("--markdown-only", action="store_true",
                        help="Ne pas produire les PDF")
    parser.add_argument("--templates", type=Path,
                        default=Path(__file__).parent.parent / "services/orchestrator/template",
                        help="Répertoire des templates, pour contrôler la couverture")
    args = parser.parse_args()

    scenarios = [s for s in SCENARIOS if not args.form or args.form in (s.form, s.dossier)]
    if not scenarios:
        print(f"Aucun scénario pour {args.form}")
        return 1

    for scenario in scenarios:
        target = OUT_DIR / scenario.dossier
        target.mkdir(parents=True, exist_ok=True)
        docs = documents(scenario)
        illisibles = illegible_documents(scenario)
        for nom, markdown in docs:
            (target / f"{nom}.md").write_text(markdown, encoding="utf-8")
            if not args.markdown_only:
                to_pdf(markdown, target / f"{nom}.pdf")
        if not args.markdown_only:
            for nom, nature in illisibles:
                illegible_pdf(nature, target / f"{nom}.pdf")
        (target / "00_scenario.json").write_text(json.dumps({
            "form": scenario.form,
            **({"cas": scenario.cas, "mode": scenario.mode} if scenario.cas else {}),
            "titre": scenario.titre,
            "patient": f"{scenario.patient.nom} {scenario.patient.prenom}",
            "naissance": scenario.patient.naissance,
            "avs": scenario.patient.avs,
            "assureur": scenario.assureur,
            "medecin": scenario.medecin.nom,
            "documents": [n for n, _ in docs],
            **({"illisibles": [n for n, _ in illisibles]} if illisibles else {}),
            **({"absents": list(scenario.absents)} if scenario.absents else {}),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {scenario.dossier:48} {len(docs)} documents"
              + (f" + {len(illisibles)} illisible(s)" if illisibles else ""))

    # Couverture : un formulaire du catalogue sans dossier ne peut pas être évalué.
    if args.templates.exists():
        catalogue = {p.stem.replace("Form_", "") for p in args.templates.glob("Form_*.json")}
        couverts = {s.form for s in SCENARIOS}
        manquants = sorted(catalogue - couverts)
        orphelins = sorted(couverts - catalogue)
        print(f"\ncouverture : {len(couverts & catalogue)}/{len(catalogue)} formulaires")
        if manquants:
            print("  sans dossier :", ", ".join(manquants))
        if orphelins:
            print("  scénarios sans formulaire :", ", ".join(orphelins))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
