"""Run the product's read-only QQ enrichment from a terminal."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from musefolders.qqmusic_catalog import connection_status, enrich_library
from musefolders.service import load_plan

parser = argparse.ArgumentParser()
parser.add_argument("--status", action="store_true")
parser.add_argument("--limit", type=int)
parser.add_argument("--force", action="store_true")
args = parser.parse_args()
if args.status:
    print(json.dumps(connection_status(), ensure_ascii=False))
else:
    plan = load_plan(ROOT / "artifacts" / "collection_plan.json")
    tracks = plan.tracks[:args.limit] if args.limit is not None else plan.tracks
    def progress(done, total):
        if done % 10 == 0 or done == total:
            print(f"{done}/{total}", flush=True)
    print(json.dumps(enrich_library(tracks, ROOT / "artifacts", force_refresh=args.force,
                                   progress=progress), ensure_ascii=False))
