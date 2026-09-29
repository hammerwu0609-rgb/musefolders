"""Separate music catalog, analyzable audio, and playlist-write access.

An API key or a catalog response is never treated as an audio grant. This
module only gathers *real* local audio paths; it does not synthesize vectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .audio import SUPPORTED_EXTENSIONS
from .metadata import read_metadata
from .playlist_filters import safe_playlist_name
from .ports import AnalyzableAudioProvider, CatalogReader, CatalogTrack, PlaylistWriter


@dataclass(frozen=True, slots=True)
class MapAudioInputs:
    catalog_tracks: tuple[CatalogTrack, ...]
    audio_paths: dict[str, Path]
    status: str  # available | unavailable
    reason_code: str  # ok | catalog_unavailable | catalog_empty | audio_permission_missing | ...


@dataclass(frozen=True, slots=True)
class SourceCapabilityReport:
    source_name: str
    catalog_status: str
    catalog_count: int
    map_status: str
    map_reason_code: str
    analyzable_count: int
    playlist_status: str
    playlist_reason_code: str


def collect_map_audio_inputs(
    catalog_reader: CatalogReader | None,
    audio_provider: AnalyzableAudioProvider | None = None,
    *, audio_authorized: bool = False,
) -> MapAudioInputs:
    """Collect only files the source actually exposes and authorization allows.

    The result is an input to the embedding engine, not an embedding itself.
    Missing, protected, or inaccessible songs remain catalog-only entries.
    """
    if catalog_reader is None:
        return MapAudioInputs((), {}, "unavailable", "catalog_unavailable")
    try:
        catalog = tuple(catalog_reader.list_catalog_tracks())
    except (OSError, PermissionError, NotImplementedError):
        return MapAudioInputs((), {}, "unavailable", "catalog_unavailable")
    if not catalog:
        return MapAudioInputs(catalog, {}, "unavailable", "catalog_empty")
    if not audio_authorized:
        return MapAudioInputs(catalog, {}, "unavailable", "audio_permission_missing")
    if audio_provider is None:
        return MapAudioInputs(catalog, {}, "unavailable", "audio_provider_missing")
    paths: dict[str, Path] = {}
    for track in catalog:
        try:
            candidate = audio_provider.analyzable_audio_path(track.source_track_id)
            if candidate is not None:
                path = Path(candidate).resolve()
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    paths[track.source_track_id] = path
        except (OSError, PermissionError, NotImplementedError, TypeError, ValueError):
            continue
    if not paths:
        return MapAudioInputs(catalog, {}, "unavailable", "no_analyzable_audio")
    return MapAudioInputs(catalog, paths, "available", "ok")


def source_capability_report(
    source_name: str,
    catalog_reader: CatalogReader | None,
    audio_provider: AnalyzableAudioProvider | None = None,
    playlist_writer: PlaylistWriter | None = None,
    *, audio_authorized: bool = False, write_authorized: bool = False,
) -> SourceCapabilityReport:
    """Report explicit grants and usable map inputs; do not attempt a write."""
    inputs = collect_map_audio_inputs(catalog_reader, audio_provider, audio_authorized=audio_authorized)
    if not write_authorized:
        playlist_status, playlist_reason = "unavailable", "write_permission_missing"
    elif playlist_writer is None:
        playlist_status, playlist_reason = "unavailable", "playlist_writer_missing"
    else:
        playlist_status, playlist_reason = "available", "ok"
    return SourceCapabilityReport(
        source_name=source_name,
        catalog_status="available" if inputs.catalog_tracks else "unavailable",
        catalog_count=len(inputs.catalog_tracks),
        map_status=inputs.status, map_reason_code=inputs.reason_code,
        analyzable_count=len(inputs.audio_paths),
        playlist_status=playlist_status, playlist_reason_code=playlist_reason,
    )


class LocalMusicSource:
    """Ordinary files: catalog and authorized local path, no DRM bypass."""

    def __init__(self, source_root: Path):
        self.source_root = Path(source_root).resolve()

    def list_catalog_tracks(self) -> list[CatalogTrack]:
        if not self.source_root.is_dir():
            return []
        result: list[CatalogTrack] = []
        for path in sorted(self.source_root.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            resolved = path.resolve()
            if self.source_root not in resolved.parents:
                continue
            result.append(CatalogTrack(str(resolved), read_metadata(resolved)))
        return result

    def analyzable_audio_path(self, source_track_id: str) -> Path | None:
        path = Path(source_track_id).resolve()
        if (self.source_root not in path.parents or not path.is_file()
                or path.suffix.lower() not in SUPPORTED_EXTENSIONS):
            return None
        return path


class LocalM3U8Writer:
    """Create one reviewed playlist outside the source folder, never overwrite."""

    def __init__(self, source: LocalMusicSource, output_root: Path):
        self.source = source
        self.output_root = Path(output_root).resolve()
        root = source.source_root
        if (self.output_root.parent == self.output_root or self.output_root == root
                or root in self.output_root.parents or self.output_root in root.parents):
            raise ValueError("Playlist output must be separate from the source folder")

    def write_playlist(self, name: str, source_track_ids: list[str]) -> str:
        if not source_track_ids or len(set(source_track_ids)) != len(source_track_ids):
            raise ValueError("Playlist must contain distinct tracks")
        paths = [self.source.analyzable_audio_path(track_id) for track_id in source_track_ids]
        if any(path is None for path in paths):
            raise ValueError("A selected source track is inaccessible or unsupported")
        filename = safe_playlist_name(name) + ".m3u8"
        self.output_root.mkdir(parents=True, exist_ok=True)
        target = self.output_root / filename
        with target.open("x", encoding="utf-8-sig", newline="\n") as handle:
            handle.write("#EXTM3U\n")
            for path in paths:
                handle.write(f"{path}\n")
        return str(target)


def local_capability_report(source_root: Path, output_root: Path | None = None) -> SourceCapabilityReport:
    """Inspect a local folder without modifying it; output is optional."""
    source = LocalMusicSource(source_root)
    writer = LocalM3U8Writer(source, output_root) if output_root is not None else None
    return source_capability_report(
        "local", source, source, writer,
        audio_authorized=True, write_authorized=writer is not None,
    )
