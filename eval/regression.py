"""
Garde-fou qualité : les dossiers de test contre un backend réel, comparés à une référence.

Les tests de CI simulent le modèle : ils prouvent que la chaîne de traitement est
intacte, pas que le modèle trouve encore les bonnes valeurs. Une modification de
prompt, de découpage, de modèle ou de template peut dégrader l'extraction sans
casser un seul test. Ce script la mesure : il soumet chaque dossier de
`eval/dossiers/` à l'API, compare le résultat à la vérité terrain dérivée des
scénarios (`truth.py`), puis à la dernière référence validée (`baseline.json`).

    # Fixer la référence (sur main, après validation) :
    python eval/regression.py --api http://localhost:8080 --api-key $KEY --update-baseline

    # Vérifier une branche avant merge :
    python eval/regression.py --api http://localhost:8080 --api-key $KEY --report report.md

    # Sous-ensemble :
    python eval/regression.py ... --forms LCA_IncapaciteTravail AI_ReadaptationRente

Code de sortie : 0 sans régression, 1 en cas de régression, 2 si un dossier n'a
pas pu être traité (job en échec, délai dépassé, API injoignable).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from truth import derive_truth, dossier_pdfs, load_scenarios, score

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"

# Tolérances par défaut. vLLM n'est pas strictement déterministe (ordre du batch
# continu), même à température 0 : un champ d'écart par formulaire est du bruit.
MAX_FIELD_DROP = 1
MAX_GLOBAL_DROP = 0.02


def run_form(client: httpx.Client, form_id: str, pdfs: list[Path], poll_interval: float = 5.0,
             timeout: float = 1800.0, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Soumet un dossier, attend le résultat et le note."""
    started = time.monotonic()
    files = [("report_files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]
    resp = client.post("/process-form", files=files, data={"form_id": form_id})
    if resp.status_code != 200:
        return {"form": form_id, "status": "rejected", "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    job = resp.json()
    job_id, token = job["job_id"], job.get("token", "")

    while True:
        status = client.get(f"/status/{job_id}").json()
        if status["status"] == "completed":
            break
        if status["status"] == "failed":
            return {"form": form_id, "status": "failed", "message": status.get("message")}
        if time.monotonic() - started > timeout:
            return {"form": form_id, "status": "timeout", "message": f"> {timeout:.0f} s"}
        sleep(poll_interval)

    fields = client.get(f"/fields/{job_id}", params={"token": token}).json()["fields"]
    result = score(derive_truth(form_id), fields)
    result.update({
        "form": form_id,
        "status": "completed",
        "seconds": round(time.monotonic() - started, 1),
        "warnings": status.get("warnings", []),
        "job_id": job_id,
    })
    return result


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    done = [r for r in results if r["status"] == "completed"]
    truth = sum(r["truth_fields"] for r in done)
    correct = sum(r["correct"] for r in done)
    return {
        "forms": len(results),
        "completed": len(done),
        "truth_fields": truth,
        "correct": correct,
        "accuracy": round(correct / truth, 4) if truth else None,
        "errors": sum(r["errors"] for r in done),
    }


def compare(results: list[dict[str, Any]], baseline: dict[str, Any] | None,
            max_field_drop: int = MAX_FIELD_DROP, max_global_drop: float = MAX_GLOBAL_DROP,
            min_accuracy: float | None = None) -> list[str]:
    """Régressions par rapport à la référence, en clair."""
    problems: list[str] = []
    reference = (baseline or {}).get("forms", {})
    for r in results:
        form = r["form"]
        if r["status"] != "completed":
            problems.append(f"{form} : job {r['status']} ({r.get('message')})")
            continue
        base = reference.get(form)
        if base is None:
            continue
        if r["correct"] < base["correct"] - max_field_drop:
            problems.append(f"{form} : {r['correct']}/{r['truth_fields']} champs justes "
                            f"(référence {base['correct']}/{base['truth_fields']})")
        if r["errors"] > base.get("errors", 0):
            problems.append(f"{form} : {r['errors']} champ(s) en erreur (référence {base.get('errors', 0)})")

    # Précision globale, sur les seuls formulaires présents des deux côtés.
    shared = [r for r in results if r["status"] == "completed" and r["form"] in reference]
    if shared:
        cur = sum(r["correct"] for r in shared) / max(1, sum(r["truth_fields"] for r in shared))
        ref = (sum(reference[r["form"]]["correct"] for r in shared)
               / max(1, sum(reference[r["form"]]["truth_fields"] for r in shared)))
        if cur < ref - max_global_drop:
            problems.append(f"précision globale {cur:.1%} (référence {ref:.1%})")
    if min_accuracy is not None:
        overall = summarize(results)["accuracy"]
        if overall is not None and overall < min_accuracy:
            problems.append(f"précision globale {overall:.1%} sous le plancher {min_accuracy:.0%}")
    return problems


def baseline_from(results: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "_meta": {**meta, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "global": summarize(results),
        "forms": {r["form"]: {k: r[k] for k in ("correct", "truth_fields", "accuracy", "fill_rate", "errors")}
                  for r in results if r["status"] == "completed"},
    }


def report_markdown(results: list[dict[str, Any]], problems: list[str],
                    baseline: dict[str, Any] | None) -> str:
    """Rapport lisible dans le résumé d'un job GitHub Actions ou en commentaire de PR."""
    reference = (baseline or {}).get("forms", {})
    summary = summarize(results)
    lines = ["## Non-régression de l'extraction", ""]
    if summary["accuracy"] is not None:
        lines.append(f"**Précision globale : {summary['accuracy']:.1%}** "
                     f"({summary['correct']}/{summary['truth_fields']} champs, "
                     f"{summary['completed']}/{summary['forms']} dossiers traités, "
                     f"{summary['errors']} champ(s) en erreur)")
    lines.append("")
    lines.append("✅ Aucune régression." if not problems else "❌ **Régressions :**")
    lines += [f"- {p}" for p in problems]
    lines += ["", "| Formulaire | Justes | Δ réf. | Remplis | Erreurs | Durée |",
              "|---|---|---|---|---|---|"]
    for r in results:
        if r["status"] != "completed":
            lines.append(f"| {r['form']} | — | — | — | {r['status']} | — |")
            continue
        base = reference.get(r["form"])
        delta = f"{r['correct'] - base['correct']:+d}" if base else "n/a"
        lines.append(f"| {r['form']} | {r['correct']}/{r['truth_fields']} | {delta} | "
                     f"{r['filled']}/{r['fields']} | {r['errors']} | {r.get('seconds', 0):.0f} s |")
    wrong = [(r["form"], d) for r in results if r["status"] == "completed"
             for d in r["details"] if not d["match"]]
    if wrong:
        lines += ["", "<details><summary>Champs faux ou manquants</summary>", "",
                  "| Formulaire | Champ | Attendu | Obtenu |", "|---|---|---|---|"]
        for form, d in wrong:
            got = d["extracted"].replace("\n", " ").replace("|", "/")[:60] or "∅"
            lines.append(f"| {form} | {d['id']} ({d['category']}) | {d['expected']} | {got} |")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, client: httpx.Client | None = None) -> int:
    """Point d'entrée. `client` permet aux tests de viser l'application en mémoire."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--forms", nargs="*", help="Formulaires à évaluer (défaut : tous)")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--update-baseline", action="store_true", help="Écrire le résultat comme nouvelle référence")
    parser.add_argument("--max-field-drop", type=int, default=MAX_FIELD_DROP)
    parser.add_argument("--max-global-drop", type=float, default=MAX_GLOBAL_DROP)
    parser.add_argument("--min-accuracy", type=float, help="Plancher absolu de précision globale (0-1)")
    parser.add_argument("--parallel", type=int, default=2, help="Dossiers soumis de front")
    parser.add_argument("--report", type=Path, help="Rapport markdown")
    parser.add_argument("--json", type=Path, help="Résultats détaillés")
    args = parser.parse_args(argv)

    forms = args.forms or sorted(load_scenarios())
    client = client or httpx.Client(base_url=args.api, headers={"X-API-Key": args.api_key}, timeout=900.0)
    try:
        health = client.get("/health").json()
    except httpx.HTTPError as exc:
        print(f"API injoignable ({args.api}) : {exc}", file=sys.stderr)
        return 2
    print(f"Backend {health.get('build')} — modèle {health.get('model')} — {len(forms)} dossiers")

    def _one(form: str) -> dict[str, Any]:
        result = run_form(client, form, dossier_pdfs(form))
        shown = (f"{result['correct']}/{result['truth_fields']}" if result["status"] == "completed"
                 else result["status"])
        print(f"  {form:40} {shown}")
        return result

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = list(pool.map(_one, forms))

    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
    problems = compare(results, baseline, args.max_field_drop, args.max_global_drop, args.min_accuracy)
    report = report_markdown(results, problems, baseline)
    print("\n" + report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = [r for r in results if r["status"] != "completed"]
    if args.update_baseline:
        if failed:
            print("Référence non écrite : des dossiers n'ont pas été traités.", file=sys.stderr)
            return 2
        meta = {"build": health.get("build"), "model": health.get("model")}
        args.baseline.write_text(json.dumps(baseline_from(results, meta), ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"Référence écrite : {args.baseline}")
        return 0
    if baseline is None:
        print("Aucune référence : lancer une fois avec --update-baseline sur main.", file=sys.stderr)
    if failed:
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
