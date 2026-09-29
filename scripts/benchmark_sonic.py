"""Compare distributed excerpts with full-track MusiCNN on a small sample.

Run from the project root with ``uv run --extra sonic python scripts/benchmark_sonic.py``.
This reads music files but only writes a JSON report under artifacts/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from musefolders.service import load_plan
from musefolders.sonic_map import DEFAULT_MODEL_PATH, _MusicnnEncoder


def _neighbors(vectors: np.ndarray, index: int, count: int = 5) -> set[int]:
    scores = vectors @ vectors[index]
    scores[index] = -np.inf
    return set(np.argsort(scores)[-count:].tolist())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--plan", type=Path, default=ROOT / "artifacts" / "collection_plan.json")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    args = parser.parse_args()
    if args.count < 6:
        raise SystemExit("Use at least six tracks for a top-five comparison")
    plan = load_plan(args.plan)
    chosen = [plan.tracks[int(index)] for index in np.linspace(0, len(plan.tracks) - 1, min(args.count, len(plan.tracks)))]
    encoder = _MusicnnEncoder(args.model)
    sampled, full = [], []
    sample_seconds = full_seconds = 0.0
    for index, track in enumerate(chosen, 1):
        path = Path(track.source_path)
        started = time.perf_counter()
        sampled.append(encoder.encode(path, track.acoustic.duration_s))
        sample_seconds += time.perf_counter() - started
        started = time.perf_counter()
        full.append(encoder.encode(path, track.acoustic.duration_s, full_track=True))
        full_seconds += time.perf_counter() - started
        print(f"{index}/{len(chosen)}", flush=True)
    sampled_matrix = np.stack(sampled)
    full_matrix = np.stack(full)
    overlap = [len(_neighbors(sampled_matrix, index) & _neighbors(full_matrix, index)) / 5
               for index in range(len(chosen))]
    report = {
        "count": len(chosen),
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "sample_seconds": round(sample_seconds, 3),
        "full_seconds": round(full_seconds, 3),
        "mean_top5_overlap": round(float(np.mean(overlap)), 3),
        "per_track_top5_overlap": [round(value, 3) for value in overlap],
        "method_note": "Overlap among only the sampled tracks; not a human similarity-quality score.",
    }
    target = ROOT / "artifacts" / "sonic_benchmark.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
