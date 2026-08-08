"""
Répartition des verdicts de provenance sur un job réel.

Complète run_eval.py : celui-ci mesure l'exactitude contre un ground truth,
celui-là mesure la traçabilité — quelle part des valeurs produites se retrouve
dans le texte des documents, et lesquelles sont à relire.

    python check_grounding.py --api-key <clé> --form LCA_IncapaciteTravail \\
        --docs "~/code/doctorfill/Dossier patient de John Doe"
"""

import argparse
import collections
import json
import pathlib
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx requis : pip install httpx")
    raise SystemExit(1)

# Ordre d'affichage : du plus solide au plus douteux.
ORDER = ["verified", "attested", "not_checkable", "inferred", "unverified"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Traçabilité des valeurs extraites")
    parser.add_argument("--api", default="https://api.doctorfill.ch")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--form", default="LCA_IncapaciteTravail")
    parser.add_argument("--docs", required=True, help="Dossier de PDF à soumettre")
    parser.add_argument("--out", type=pathlib.Path, help="Écrire les champs bruts en JSON")
    args = parser.parse_args()

    src = pathlib.Path(args.docs).expanduser()
    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        print(f"Aucun PDF dans {src}")
        return 1

    client = httpx.Client(timeout=900.0, headers={"X-API-Key": args.api_key})
    files = [("report_files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]

    started = time.time()
    resp = client.post(f"{args.api}/process-form", files=files, data={"form_id": args.form})
    resp.raise_for_status()
    job = resp.json()
    job_id, token = job["job_id"], job.get("token", "")
    print(f"job {job_id[:8]} — {args.form} — {len(pdfs)} documents")

    while True:
        status = client.get(f"{args.api}/status/{job_id}").json()
        if status["status"] == "completed":
            break
        if status["status"] == "failed":
            print(f"ÉCHEC : {status.get('message')}")
            return 1
        sys.stdout.write(f"\r  {status.get('progress', 0):3d}% {status.get('message', '')[:60]:<60}")
        sys.stdout.flush()
        time.sleep(5)
    print(f"\rpipeline : {time.time() - started:.0f}s{'':<50}")

    payload = client.get(f"{args.api}/fields/{job_id}", params={"token": token}).json()
    rows = payload["fields"] if isinstance(payload, dict) else payload
    filled = [f for f in rows if f.get("value")]
    if not filled:
        print("Aucun champ rempli.")
        return 1

    counts = collections.Counter(f.get("grounding") for f in filled)
    print(f"\nchamps remplis : {len(filled)}/{len(rows)}")
    for key in ORDER + [k for k in counts if k not in ORDER]:
        if counts.get(key):
            n = counts[key]
            print(f"  {str(key):15} {n:3}  ({100 * n / len(filled):3.0f} %)")

    doubtful = [f for f in filled if f.get("grounding") == "unverified"]
    if doubtful:
        print(f"\n— non tracés : citation introuvable dans le dossier ({len(doubtful)}) —")
        for f in doubtful:
            print(f"  [{f['id']:5}] {str(f['label'])[:26]:28} {str(f['value'])[:44]!r}")
            print(f"           citation : {str(f.get('source_quote'))[:78]!r}")

    sample = [f for f in filled if f.get("grounding") == "verified" and f.get("source_excerpt")][:3]
    if sample:
        print("\n— exemples d'ancrage —")
        for f in sample:
            origin = f"{f['source_document']}" + (f" p.{f['source_page']}" if f.get("source_page") else "")
            print(f"  [{f['id']}] {str(f['value'])[:40]!r} → {origin}")
            print(f"        « …{str(f.get('source_match'))[:70]}… »")

    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nChamps bruts écrits dans {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
