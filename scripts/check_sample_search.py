"""Exercise real library queries and save result metadata, never lyric text."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from musefolders.library_search import search_library
from musefolders.service import load_plan

plan = load_plan(ROOT / "artifacts" / "collection_plan.json")
by_id = plan.track_by_id()
report = {}
for query in ("爱情", "失恋", "成长", "爱情慢一点", "明亮", "许嵩"):
    hits = search_library(plan.tracks, query, lyrics_root=Path(plan.source_root))
    report[query] = [{"title": by_id[hit.track_id].metadata.title,
                      "artist": by_id[hit.track_id].metadata.artist,
                      "reasons": list(hit.reasons)} for hit in hits]
output = ROOT / "artifacts" / "sample_search_results.json"
output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({query: len(hits) for query, hits in report.items()}, ensure_ascii=False))
