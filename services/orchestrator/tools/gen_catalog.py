"""
tools/gen_catalog.py — Génère en lot les templates d'une sélection medForms.

Télécharge chaque formulaire, dérive son template, et écrit un rapport de
couverture indiquant combien de questions restent à rédiger. Les PDF sont mis
en cache pour ne pas retélécharger à chaque exécution.

Usage :
    python -m tools.gen_catalog --list tools/catalog_fr.txt
    python -m tools.gen_catalog --list tools/catalog_fr.txt --write
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.gen_template import GenerationError, build_template  # noqa: E402

logger = logging.getLogger(__name__)

BASE_URL = "https://medforms.ch/formTemplates"
FORMS_DIR = Path("forms")
TEMPLATE_DIR = Path("template")

def _prior_template(form_id: str) -> Path | None:
    """Template existant dont reprendre les questions déjà rédigées."""
    candidate = TEMPLATE_DIR / f"Form_{form_id}.json"
    return candidate if candidate.exists() else None


def fetch(code: str, cache_dir: Path) -> Path:
    """Télécharge un formulaire medForms, en s'appuyant sur le cache local."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{code}.pdf"
    if target.exists() and target.stat().st_size > 0:
        return target
    url = f"{BASE_URL}/{code}.pdf"
    logger.info("Téléchargement %s", url)
    urllib.request.urlretrieve(url, target)  # noqa: S310
    return target


def parse_list(path: Path) -> list[tuple[str, str]]:
    """
    Lit la liste des formulaires à générer.

    Format : `<code medForms> <identifiant DoctorFill>`, un par ligne.
    Les lignes vides et celles commençant par # sont ignorées.
    """
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            logger.warning("Ligne ignorée (format attendu : code id) : %s", line)
            continue
        entries.append((parts[0], parts[1]))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", type=Path, required=True, help="Fichier code/identifiant")
    parser.add_argument("--cache", type=Path, default=Path(".medforms_cache"))
    parser.add_argument("--write", action="store_true",
                        help="Écrit dans forms/ et template/ (sinon simple rapport)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    entries = parse_list(args.list)
    print(f"\n{'identifiant':<22}{'champs':>7}{'auto':>6}{'à rédiger':>11}  état")

    total_fields = total_auto = 0
    failures = 0
    for code, form_id in entries:
        try:
            pdf = fetch(code, args.cache)
        except Exception as exc:
            print(f"{form_id:<22}{'':>7}{'':>6}{'':>11}  téléchargement échoué : {exc}")
            failures += 1
            continue

        target = TEMPLATE_DIR / f"Form_{form_id}.json"
        try:
            template = build_template(pdf, existing=_prior_template(form_id))
        except GenerationError as exc:
            print(f"{form_id:<22}{'':>7}{'':>6}{'':>11}  écarté : {exc}")
            failures += 1
            continue

        # Un champ `computed` (bloc adresse destinataire) n'a pas de question à
        # écrire : sa valeur se déduit du formulaire. Le compter comme « à
        # rédiger » faisait basculer trois formulaires en non relu, donc hors
        # catalogue.
        fields = [e for e in template["fields"] if "id" in e and "computed" not in e]
        auto = sum(1 for e in fields if e.get("question"))
        total_fields += len(fields)
        total_auto += auto

        state = "généré" if args.write else "simulation"
        if args.write:
            FORMS_DIR.mkdir(parents=True, exist_ok=True)
            TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
            (FORMS_DIR / f"Form_{form_id}.pdf").write_bytes(pdf.read_bytes())
            # Un formulaire n'est publiable que si toutes ses questions sont écrites.
            template["_reviewed"] = auto == len(fields)
            target.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"{form_id:<22}{len(fields):>7}{auto:>6}{len(fields) - auto:>11}  {state}")

    if total_fields:
        print(f"\n{total_auto}/{total_fields} questions générées automatiquement "
              f"({total_auto / total_fields:.0%}), {total_fields - total_auto} à rédiger, "
              f"{failures} formulaire(s) en échec")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
