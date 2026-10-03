"""Build lyric/instrumental test-set manifests from an existing collection plan.

This is deliberately conservative: missing lyrics alone never proves that a track
is instrumental. The output keeps a review bucket for uncertain tracks.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INSTRUMENTAL_ARTISTS = (
    "a_hisa", "bandari", "depapepe", "james horner", "jay vincent",
    "michael kramer", "kenny g", "s.e.n.s.", "secret garden", "the piano guys",
    "v.k", "やまだ豊", "久石让", "坂本龙一", "天门", "小濑村晶", "林有三",
    "西村由纪江", "高梨康治", "山本康太", "牛尾憲輔", "石川真也", "游学志",
)
INSTRUMENTAL_TITLE = re.compile(
    r"instrumental|overture|nocturne|piano|soundtrack|ost|film version|theme|interlude|variation|\bvar\b|radio edit instrumental",
    re.I,
)


def _lyric_statuses(root: Path, tracks: list[dict]) -> dict[str, dict]:
    report_path = root / "artifacts" / "lyrics_audit.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return {
            f"{item['artist']}\u0000{item['title']}": item
            for item in report.get("tracks", [])
        }
    return {}


def _instrumental_score(track: dict, lyric: dict) -> tuple[int, list[str]]:
    meta = track.get("metadata", {})
    artist = str(meta.get("artist", ""))
    title = str(meta.get("title", ""))
    score = 0
    reasons: list[str] = []
    folded_artist = artist.casefold()
    if any(name in folded_artist for name in INSTRUMENTAL_ARTISTS):
        score += 2
        reasons.append("artist commonly associated with instrumental/score music")
    if INSTRUMENTAL_TITLE.search(title):
        score += 2
        reasons.append("title contains an instrumental/score cue")
    if str(meta.get("genre", "")).casefold() in {"classical", "soundtrack", "new age"}:
        score += 1
        reasons.append("metadata genre suggests score/instrumental music")
    if lyric.get("lyric_status") == "missing":
        reasons.append("no usable lyric file matched")
    return score, reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "artifacts" / "collection_plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "test_sets.json")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    tracks = plan.get("tracks", [])
    statuses = _lyric_statuses(ROOT, tracks)
    lyric_set: list[dict] = []
    instrumental_set: list[dict] = []
    review_set: list[dict] = []
    for track in tracks:
        meta = track.get("metadata", {})
        key = f"{meta.get('artist', '')}\u0000{meta.get('title', '')}"
        lyric = statuses.get(key, {"lyric_status": "unknown", "lyric_source": ""})
        base = {
            "track_id": track.get("track_id", ""),
            "title": meta.get("title", ""),
            "artist": meta.get("artist", ""),
            "album": meta.get("album", ""),
            "source_path": track.get("source_path", ""),
            "lyric_status": lyric.get("lyric_status", "unknown"),
            "lyric_source": lyric.get("lyric_source", ""),
            "metadata": meta,
        }
        if lyric.get("lyric_status") == "valid":
            lyric_set.append({**base, "test_role": "歌词主题检索"})
            continue
        score, reasons = _instrumental_score(track, lyric)
        entry = {**base, "instrumental_score": score, "reasons": reasons}
        if score >= 3:
            entry["test_role"] = "音频气质/纯音乐检索"
            instrumental_set.append(entry)
        else:
            entry["test_role"] = "需要人工确认"
            review_set.append(entry)
    output = {
        "schema_version": "test-sets-v1",
        "source_plan": str(args.plan),
        "counts": {"all": len(tracks), "lyrics": len(lyric_set), "instrumental_candidates": len(instrumental_set), "review": len(review_set)},
        "lyrics": lyric_set,
        "instrumental_candidates": instrumental_set,
        "review": review_set,
        "notes": [
            "instrumental_candidates are heuristic candidates, not verified facts",
            "missing lyrics alone is never treated as instrumental",
            "confirm title, artist, version, and audible vocals before using a track as ground truth",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
