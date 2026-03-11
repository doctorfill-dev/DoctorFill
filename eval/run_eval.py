"""
DoctorFill - Script d'évaluation du pipeline RAG
==================================================
Envoie les documents de test à l'API, récupère les résultats bruts via
l'endpoint /debug, et compare au ground truth.

Usage:
    python run_eval.py                                  # Évalue avec les docs générés
    python run_eval.py --api http://localhost:8080       # API locale
    python run_eval.py --api https://api.doctorfill.ch  # API prod
    python run_eval.py --api-key <KEY>                  # Avec clé API
"""

import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import httpx
except ImportError:
    print("httpx requis : pip install httpx")
    raise SystemExit(1)

GROUND_TRUTH_PATH = Path(__file__).parent / "ground_truth.json"
TEST_DOCS_DIR = Path(__file__).parent / "test_docs"
RESULTS_DIR = Path(__file__).parent / "results"


def load_ground_truth() -> dict:
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# COMPARAISON
# ---------------------------------------------------------------------------

def normalize(val: str) -> str:
    """Normalise une valeur pour comparaison."""
    if val is None:
        return ""
    return str(val).strip().lower()


def compare_field(field_id: str, extracted: str, gt_entry: dict) -> dict:
    """Compare une valeur extraite au ground truth. Retourne un dict de résultat."""
    expected = gt_entry.get("expected")
    tolerance = gt_entry.get("tolerance", "exact")
    result = {
        "field_id": field_id,
        "expected": expected,
        "extracted": extracted,
        "tolerance": tolerance,
        "category": gt_entry.get("category", ""),
    }

    if extracted is None or extracted == "":
        result["match"] = False
        result["reason"] = "Pas de valeur extraite"
        return result

    ext_norm = normalize(extracted)

    if tolerance == "exact":
        # Normaliser : supprimer %, espaces, et gérer M/F vs Masculin/Féminin
        exp_clean = normalize(expected).rstrip("%").strip()
        ext_clean = ext_norm.rstrip("%").strip()
        # Mapping codes courants
        gender_map = {"féminin": "f", "feminin": "f", "masculin": "m", "femme": "f", "homme": "m"}
        if ext_clean in gender_map:
            ext_clean = gender_map[ext_clean]
        result["match"] = exp_clean == ext_clean
        if not result["match"]:
            result["reason"] = f"Attendu '{expected}', obtenu '{extracted}'"

    elif tolerance == "fuzzy":
        # Match si la valeur attendue est contenue dans l'extraction ou vice versa
        exp_norm = normalize(expected)
        result["match"] = exp_norm in ext_norm or ext_norm in exp_norm
        if not result["match"]:
            result["reason"] = f"Fuzzy fail: '{expected}' vs '{extracted}'"

    elif tolerance == "date":
        # Normaliser les dates (supprimer espaces, remplacer / par .)
        exp_clean = normalize(expected).replace("/", ".").replace("-", ".")
        ext_clean = ext_norm.replace("/", ".").replace("-", ".")
        result["match"] = exp_clean == ext_clean
        if not result["match"]:
            result["reason"] = f"Date: '{expected}' vs '{extracted}'"

    elif tolerance == "contains":
        # Vérifier que des mots-clés sont présents
        keywords = gt_entry.get("keywords", [])
        found = [kw for kw in keywords if kw.lower() in ext_norm]
        missing = [kw for kw in keywords if kw.lower() not in ext_norm]
        result["match"] = len(missing) == 0
        result["keywords_found"] = found
        result["keywords_missing"] = missing
        if not result["match"]:
            result["reason"] = f"Mots-clés manquants: {missing}"

    else:
        result["match"] = False
        result["reason"] = f"Tolérance inconnue: {tolerance}"

    return result


# ---------------------------------------------------------------------------
# PIPELINE D'ÉVALUATION
# ---------------------------------------------------------------------------

def run_evaluation(api_url: str, api_key: str = "", form_id: str = "AVS"):
    """Exécute l'évaluation complète."""
    gt = load_ground_truth()
    assert gt["_meta"]["form_id"] == form_id, f"Ground truth pour {gt['_meta']['form_id']}, pas {form_id}"

    # Collecter les PDFs
    pdf_files = sorted(TEST_DOCS_DIR.glob("*.pdf"))
    if not pdf_files:
        print("Aucun PDF trouvé dans test_docs/. Lancez d'abord : python generate_docs.py")
        return

    print(f"\n{'='*70}")
    print(f"  ÉVALUATION DOCTORFILL RAG")
    print(f"{'='*70}")
    print(f"  API       : {api_url}")
    print(f"  Formulaire: {form_id}")
    print(f"  Documents : {len(pdf_files)} PDFs")
    print(f"  Champs GT : {len(gt['fields'])} champs à évaluer")
    print(f"{'='*70}\n")

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    client = httpx.Client(timeout=600.0, headers=headers)

    # 1. Envoyer les fichiers
    print("[1/4] Upload des documents...")
    files = [("report_files", (f.name, open(f, "rb"), "application/pdf")) for f in pdf_files]
    data = {"form_id": form_id}

    t_start = time.time()
    try:
        resp = client.post(f"{api_url}/process-form", files=files, data=data)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"ERREUR upload: {e.response.status_code} - {e.response.text}")
        return
    except httpx.ConnectError:
        print(f"ERREUR: Impossible de se connecter à {api_url}")
        return
    finally:
        for _, (_, fh, _) in files:
            fh.close()

    result = resp.json()
    job_id = result["job_id"]
    token = result.get("token", "")
    print(f"      Job ID: {job_id[:12]}...")

    # 2. Polling
    print("[2/4] Traitement en cours...")
    while True:
        status_resp = client.get(f"{api_url}/status/{job_id}")
        status = status_resp.json()

        progress = status.get("progress", 0)
        message = status.get("message", "")
        sys.stdout.write(f"\r      {progress:3d}% | {message[:60]:<60}")
        sys.stdout.flush()

        if status["status"] == "completed":
            print()
            break
        elif status["status"] == "failed":
            print(f"\n      ÉCHEC: {status.get('message')}")
            return

        time.sleep(2)

    t_pipeline = time.time() - t_start
    print(f"      Temps pipeline: {t_pipeline:.1f}s")

    # 3. Récupérer les résultats debug
    print("[3/4] Récupération des résultats bruts...")
    debug_resp = client.get(f"{api_url}/debug/{job_id}", params={"token": token})
    if debug_resp.status_code != 200:
        print(f"      ERREUR debug endpoint: {debug_resp.status_code}")
        print("      Assurez-vous que l'orchestrateur est à jour (endpoint /debug)")
        return

    debug_data = debug_resp.json()
    extractions = {e["field_id"]: e for e in debug_data["extractions"]}

    # 4. Comparaison
    print(f"[4/4] Comparaison ({debug_data['chunks_count']} chunks générés)...\n")

    results = []
    for field_id, gt_entry in gt["fields"].items():
        extraction = extractions.get(field_id, {})
        extracted_value = extraction.get("value")
        comparison = compare_field(field_id, extracted_value, gt_entry)
        comparison["source_quote"] = extraction.get("source_quote", "")
        results.append(comparison)

    # ---------------------------------------------------------------------------
    # AFFICHAGE DES RÉSULTATS
    # ---------------------------------------------------------------------------

    # Résumé par catégorie
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "match": 0}
        categories[cat]["total"] += 1
        if r["match"]:
            categories[cat]["match"] += 1

    total_match = sum(1 for r in results if r["match"])
    total_fields = len(results)
    accuracy = total_match / total_fields * 100 if total_fields > 0 else 0

    print(f"{'─'*70}")
    print(f"  RÉSULTATS : {total_match}/{total_fields} champs corrects ({accuracy:.1f}%)")
    print(f"  Pipeline  : {t_pipeline:.1f}s | Chunks: {debug_data['chunks_count']}")
    print(f"{'─'*70}")

    print(f"\n  {'Catégorie':<15} {'Score':<12} {'Détail'}")
    print(f"  {'─'*50}")
    for cat, stats in sorted(categories.items()):
        pct = stats["match"] / stats["total"] * 100
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        status = "OK" if pct == 100 else "PARTIEL" if pct > 0 else "ÉCHEC"
        print(f"  {cat:<15} {stats['match']}/{stats['total']:<8} {bar} {pct:.0f}% {status}")

    # Détails des échecs
    failures = [r for r in results if not r["match"]]
    if failures:
        print(f"\n  ÉCHECS DÉTAILLÉS ({len(failures)}):")
        print(f"  {'─'*60}")
        for r in failures:
            print(f"  [{r['field_id']}] {r['category']}")
            print(f"    Attendu  : {r['expected']}")
            print(f"    Obtenu   : {r['extracted']}")
            if r.get("reason"):
                print(f"    Raison   : {r['reason']}")
            if r.get("keywords_missing"):
                print(f"    Manquant : {r['keywords_missing']}")
            print()

    # Succès
    successes = [r for r in results if r["match"]]
    if successes:
        print(f"  SUCCÈS ({len(successes)}):")
        print(f"  {'─'*60}")
        for r in successes:
            val = str(r['extracted'])[:40]
            print(f"  [{r['field_id']}] {r['category']:<12} {val}")

    # Sauvegarder le rapport JSON
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": timestamp,
        "config": {
            "api_url": api_url,
            "form_id": form_id,
            "doc_count": len(pdf_files),
            "chunks_count": debug_data["chunks_count"],
            "pipeline_time_s": round(t_pipeline, 1),
        },
        "summary": {
            "accuracy": round(accuracy, 1),
            "total_fields": total_fields,
            "correct": total_match,
            "failed": len(failures),
            "by_category": categories,
        },
        "details": results,
    }
    report_path = RESULTS_DIR / f"eval_{timestamp}_{len(pdf_files)}docs.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n  Rapport sauvegardé : {report_path}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Évaluation du pipeline RAG DoctorFill")
    parser.add_argument("--api", default="http://localhost:8080", help="URL de l'API (default: localhost:8080)")
    parser.add_argument("--api-key", default="", help="Clé API (X-API-Key)")
    parser.add_argument("--form", default="AVS", help="Form ID (default: AVS)")
    args = parser.parse_args()
    run_evaluation(api_url=args.api, api_key=args.api_key, form_id=args.form)
