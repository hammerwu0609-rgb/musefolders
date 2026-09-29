from __future__ import annotations

from pathlib import Path

from musefolders.adapters import LocalFolderAdapter
from musefolders.audio import sha256_file
from musefolders.models import AcousticFeatures, CollectionPlan, StandardScores, TrackEncoding, TrackMetadata
from musefolders.playlist_filters import (
    PlaylistFilters, build_playlist_plan, facet_counts, filter_tracks, playlist_bytes, relaxation_counts,
)
from musefolders.service import load_plan, save_plan


def make_track(path: Path, artist: str, instrument: str, key: str, loudness: str, tempo: str,
               act: float, bri: float) -> TrackEncoding:
    path.write_bytes(f"audio-{path.name}".encode())
    return TrackEncoding(
        track_id=path.stem, source_path=str(path), source_size=path.stat().st_size,
        source_mtime_ns=path.stat().st_mtime_ns, source_sha256=sha256_file(path),
        metadata=TrackMetadata(title=path.stem, artist=artist, album="Album", genre="Blues", year="2024"),
        acoustic=AcousticFeatures(
            duration_s=60, tempo_bpm=120, tempo_confidence=.8, rms_dbfs=-18, dynamic_range_db=10,
            spectral_centroid_hz=1900, spectral_rolloff_hz=3600, zero_crossing_rate=.04,
            percussive_ratio=.2, onset_rate=2, harmonic_ratio=.8, key="C", mode="major",
            key_confidence=.6, analyzed_audio_s=30,
        ),
        instrument=instrument, standard=StandardScores(
            agitation=act, agitation_band="", brightness=bri, energy=50, rhythmicity=50, warmth=50,
        ),
        tags={"key": key, "loudness": loudness, "tempo": tempo},
    )


def test_combined_filters_show_empty_result_and_recoverable_conditions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    tracks = [
        make_track(source / "one.mp3", "Alice", "piano", "C:major", "loud", "fast", 82, 60),
        make_track(source / "two.mp3", "Alice", "voice", "G:minor", "soft", "slow", 20, 25),
        make_track(source / "three.mp3", "Bob", "piano", "C:major", "loud", "fast", 75, 70),
    ]
    filters = PlaylistFilters(
        artists=frozenset({"Alice"}), instruments=frozenset({"piano", "voice"}),
        loudness=frozenset({"loud"}), act_range=(0, 30),
    )
    assert filter_tracks(tracks, filters) == []
    assert relaxation_counts(tracks, filters)["act_range"] == 1
    assert relaxation_counts(tracks, filters)["loudness"] == 1
    assert facet_counts(tracks, filters, "loudness") == {"soft": 1}

    compatible = PlaylistFilters(
        artists=frozenset({"Alice"}), instruments=frozenset({"piano", "voice"}),
        keys=frozenset({"C:major"}), loudness=frozenset({"loud"}),
        tempo=frozenset({"fast"}), act_range=(70, 90), bri_range=(50, 70),
    )
    assert [track.track_id for track in filter_tracks(tracks, compatible)] == ["one"]


def test_filtered_plan_copies_only_matches_and_can_be_undone(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    tracks = [
        make_track(source / "one.mp3", "Alice", "piano", "C:major", "loud", "fast", 82, 60),
        make_track(source / "two.mp3", "Bob", "voice", "G:minor", "soft", "slow", 20, 25),
    ]
    source_plan = CollectionPlan("analysis", str(source), "quant", [], tracks)
    filters = PlaylistFilters(artists=frozenset({"Alice"}))
    selected = filter_tracks(tracks, filters)
    custom = build_playlist_plan(source_plan, selected, "My playlist", filters, "en")
    assert custom.selection_query["artists"] == ["Alice"]
    assert load_plan(save_plan(custom, tmp_path / "records")).selection_query["artists"] == ["Alice"]
    assert len(custom.tracks) == 1
    assert custom.tracks[0] is not selected[0]
    assert selected[0].folder_id == ""
    assert str(source / "one.mp3").encode() in playlist_bytes(selected)

    adapter = LocalFolderAdapter(tmp_path / "exports")
    assert len(adapter.preview(custom)) == 1
    result = adapter.apply(custom)
    assert result["copied"] == 1
    assert (tmp_path / "exports" / "My playlist" / "one.mp3").is_file()
    assert not (tmp_path / "exports" / "My playlist" / "two.mp3").exists()
    assert (tmp_path / "exports" / "My playlist" / "playlist.m3u8").is_file()
    assert adapter.rollback(Path(result["manifest"]))["removed_copies"] == 1
    assert (source / "one.mp3").is_file()
