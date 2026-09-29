from __future__ import annotations

import wave
from pathlib import Path

import pytest

from musefolders.models import TrackMetadata
from musefolders.ports import CatalogTrack
from musefolders.source_capabilities import (
    LocalM3U8Writer, LocalMusicSource, collect_map_audio_inputs,
    local_capability_report, source_capability_report,
)


class MetadataOnlyQQ:
    """A catalog response is not a grant to download or rewrite the library."""

    def list_catalog_tracks(self) -> list[CatalogTrack]:
        return [CatalogTrack("qq-1", TrackMetadata("Song", "Artist", source_track_id="qq-1", source="qqmusic"))]


class UnauthorizedAudio:
    def __init__(self, path: Path):
        self.path = path
        self.calls = 0

    def analyzable_audio_path(self, source_track_id: str) -> Path:
        self.calls += 1
        return self.path


class UnauthorizedWriter:
    def __init__(self):
        self.calls = 0

    def write_playlist(self, name: str, source_track_ids: list[str]) -> str:
        self.calls += 1
        return "qqmusic://playlist/unexpected"


def _valid_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)


def test_metadata_only_qq_has_no_map_inputs_or_write_permission(tmp_path: Path) -> None:
    audio = tmp_path / "song.wav"
    _valid_wav(audio)
    qq = MetadataOnlyQQ()
    unauthorized_audio = UnauthorizedAudio(audio)
    unauthorized_writer = UnauthorizedWriter()
    inputs = collect_map_audio_inputs(qq, unauthorized_audio, audio_authorized=False)
    assert len(inputs.catalog_tracks) == 1
    assert inputs.audio_paths == {}
    assert inputs.status == "unavailable"
    assert inputs.reason_code == "audio_permission_missing"
    assert not hasattr(inputs, "embeddings")  # No invented sound vectors from metadata.
    report = source_capability_report(
        "qqmusic", qq, unauthorized_audio, unauthorized_writer,
        audio_authorized=False, write_authorized=False,
    )
    assert report.catalog_status == "available" and report.catalog_count == 1
    assert report.map_status == "unavailable"
    assert report.map_reason_code == "audio_permission_missing"
    assert report.analyzable_count == 0
    assert report.playlist_status == "unavailable"
    assert report.playlist_reason_code == "write_permission_missing"
    assert unauthorized_audio.calls == unauthorized_writer.calls == 0


def test_local_source_reports_real_audio_inputs_and_separate_writer(tmp_path: Path) -> None:
    source_root = tmp_path / "music"
    source_root.mkdir()
    song = source_root / "Artist - Song.wav"
    _valid_wav(song)
    (source_root / "protected.qmcflac").write_bytes(b"not accessible")
    (source_root / "notes.txt").write_text("not audio", encoding="utf-8")
    output_root = tmp_path / "playlists"
    source = LocalMusicSource(source_root)
    tracks = source.list_catalog_tracks()
    assert len(tracks) == 1
    assert tracks[0].metadata.title == "Song"
    assert source.analyzable_audio_path(tracks[0].source_track_id) == song.resolve()
    assert source.analyzable_audio_path(str(tmp_path / "other.wav")) is None
    inputs = collect_map_audio_inputs(source, source, audio_authorized=True)
    assert inputs.status == "available"
    assert inputs.audio_paths == {tracks[0].source_track_id: song.resolve()}
    report = local_capability_report(source_root, output_root)
    assert report.catalog_count == report.analyzable_count == 1
    assert report.map_status == report.playlist_status == "available"
    writer = LocalM3U8Writer(source, output_root)
    playlist = Path(writer.write_playlist("My Song", [tracks[0].source_track_id]))
    assert playlist.is_file()
    assert str(song.resolve()) in playlist.read_text(encoding="utf-8-sig")
    with pytest.raises(FileExistsError):
        writer.write_playlist("My Song", [tracks[0].source_track_id])
    assert song.is_file()


def test_local_report_distinguishes_empty_folder_and_unconfigured_output(tmp_path: Path) -> None:
    source_root = tmp_path / "music"
    source_root.mkdir()
    report = local_capability_report(source_root)
    assert report.map_status == "unavailable" and report.map_reason_code == "catalog_empty"
    assert report.playlist_status == "unavailable"
    assert report.playlist_reason_code == "write_permission_missing"
    with pytest.raises(ValueError, match="separate"):
        LocalM3U8Writer(LocalMusicSource(source_root), source_root / "exports")
