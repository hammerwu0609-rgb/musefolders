import json
from pathlib import Path

from musefolders.audio import sha256_file, track_instance_id
from musefolders.models import AcousticFeatures, TrackEncoding, TrackMetadata
from musefolders.service import _cache_key, analyze_library


def _track(path: Path, *, high_frequency_ratio: float | None) -> TrackEncoding:
    stat = path.stat()
    source_hash = sha256_file(path)
    return TrackEncoding(
        track_id=track_instance_id(path, source_hash), source_path=str(path.resolve()),
        source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
        source_sha256=source_hash, metadata=TrackMetadata(title="Song", artist="Artist"),
        acoustic=AcousticFeatures(
            duration_s=15, tempo_bpm=110, tempo_confidence=.8, rms_dbfs=-22,
            dynamic_range_db=10, spectral_centroid_hz=2200,
            spectral_rolloff_hz=5400, zero_crossing_rate=.05,
            percussive_ratio=.2, onset_rate=2, harmonic_ratio=.8,
            key="C", mode="major", key_confidence=.7, analyzed_audio_s=15,
            high_frequency_ratio=high_frequency_ratio,
        ),
    )


def test_legacy_audio_cache_is_reanalyzed_for_brightness_v2(tmp_path, monkeypatch) -> None:
    source = tmp_path / "music"
    artifacts = tmp_path / "artifacts"
    cache_dir = artifacts / "cache"
    source.mkdir()
    cache_dir.mkdir(parents=True)
    path = source / "Artist - Song.mp3"
    path.write_bytes(b"local test source")

    legacy = _track(path, high_frequency_ratio=None).to_dict()
    del legacy["acoustic"]["high_frequency_ratio"]
    (cache_dir / f"{_cache_key(path, '0.4.0')}.json").write_text(
        json.dumps(legacy), encoding="utf-8",
    )
    calls: list[Path] = []

    def fake_analyze(target: Path) -> TrackEncoding:
        calls.append(target)
        return _track(target, high_frequency_ratio=.12)

    monkeypatch.setattr("musefolders.service.analyze_track", fake_analyze)
    monkeypatch.setattr("musefolders.service.detect_instrument", lambda _path: ("unknown", 0.0, "unavailable"))

    plan, evidence = analyze_library(source, artifacts)

    assert calls == [path]
    assert evidence["cache_hits"] == 0
    assert plan.tracks[0].acoustic.high_frequency_ratio == .12
    assert plan.tracks[0].standard is not None
