"""Merge automatic lyric coverage and manual listening decisions into ground truth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "artifacts" / "collection_plan.json")
    parser.add_argument("--test-sets", type=Path, default=ROOT / "artifacts" / "test_sets.json")
    parser.add_argument("--reviews", type=Path, default=ROOT / "artifacts" / "manual_test_review.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "verified_test_sets.json")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    tests = json.loads(args.test_sets.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews.read_text(encoding="utf-8")).get("records_by_sha256", {})
    by_id = {track["track_id"]: track for track in plan.get("tracks", [])}
    reviewed_by_id = {record["track_id"]: record for record in reviews.values()}
    expected_review_ids = {
        row["track_id"]
        for name in ("instrumental_candidates", "review")
        for row in tests.get(name, [])
    }
    missing = sorted(expected_review_ids - set(reviewed_by_id))
    if missing:
        raise SystemExit(f"Manual review is incomplete: {len(missing)} tracks remain")

    groups = {
        "lyrics_available": [],
        "instrumental": [],
        "vocal_missing_lyrics": [],
        "vocal_with_lyrics": [],
        "skipped": [],
    }
    lyric_ids = {row["track_id"] for row in tests.get("lyrics", [])}
    for track_id, track in by_id.items():
        meta = track.get("metadata", {})
        base = {
            "track_id": track_id,
            "source_sha256": track.get("source_sha256", ""),
            "source_path": track.get("source_path", ""),
            "title": meta.get("title", ""),
            "artist": meta.get("artist", ""),
            "album": meta.get("album", ""),
        }
        if track_id in reviewed_by_id:
            review = reviewed_by_id[track_id]
            label = review.get("label", "skip")
            target = "skipped" if label == "skip" else label
            groups[target].append({**base, "verification": "manual_listening", "review": review})
        elif track_id in lyric_ids:
            groups["lyrics_available"].append({**base, "verification": "usable_matched_lyrics"})
        else:
            groups["skipped"].append({**base, "verification": "unclassified"})

    output = {
        "schema_version": "verified-test-sets-v1",
        "source_analysis_id": plan.get("analysis_id", ""),
        "counts": {name: len(rows) for name, rows in groups.items()},
        "total": sum(len(rows) for rows in groups.values()),
        **groups,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": output["total"], **output["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
