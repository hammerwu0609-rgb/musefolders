"""Read-only sample audit. Writes statuses/metadata counts, never lyric text."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from musefolders.lyrics_map import scan_lyric_languages
from musefolders.metadata import read_metadata

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
audio = sorted(args.source.rglob("*.mp3"))
tracks = [SimpleNamespace(track_id=str(index), source_path=str(path), metadata=read_metadata(path))
          for index, path in enumerate(audio)]
result = scan_lyric_languages(tracks, lyrics_root=args.source)
with patch("musefolders.lyrics_map.lyric_match_key", side_effect=lambda stem: stem.casefold()):
    baseline = scan_lyric_languages(tracks, lyrics_root=args.source)
report = {"audio_count": len(tracks), "lyric_statuses": dict(Counter(result.statuses.values())),
          "strict_filename_baseline": dict(Counter(baseline.statuses.values())),
          "raw_genres": dict(Counter(track.metadata.genre or "unknown" for track in tracks)),
          "tracks": [{"title": track.metadata.title, "artist": track.metadata.artist,
                      "lyric_status": result.statuses[track.track_id],
                      "lyric_source": result.sources.get(track.track_id, "")} for track in tracks]}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "tracks"}, ensure_ascii=False))
