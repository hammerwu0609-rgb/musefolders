from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import CollectionPlan, TrackEncoding, TrackMetadata


@dataclass(frozen=True, slots=True)
class CatalogTrack:
    """A source song's identity and metadata, without claiming audio access."""

    source_track_id: str
    metadata: TrackMetadata


class CatalogReader(Protocol):
    """List visible music. This permission does not imply playable audio."""

    def list_catalog_tracks(self) -> list[CatalogTrack]: ...


class AnalyzableAudioProvider(Protocol):
    """Return an authorized local audio file, or None when it is unavailable.

    A future cloud implementation owns the lifecycle of any temporary file.
    Merely having a search/catalog API or an API key does not satisfy this port.
    """

    def analyzable_audio_path(self, source_track_id: str) -> Path | None: ...


class PlaylistWriter(Protocol):
    """Persist an explicitly reviewed, ordered playlist and return its URI/path."""

    def write_playlist(self, name: str, source_track_ids: list[str]) -> str: ...


class SemanticEncoder(Protocol):
    """Future CLAP/platform-model boundary; acoustic encoding does not depend on it."""

    model_version: str

    def enrich(self, tracks: list[TrackEncoding]) -> list[TrackEncoding]: ...


class NaturalLanguageRuleCompiler(Protocol):
    """Future natural-language input must compile to the same inspectable plan."""

    compiler_version: str

    def compile(self, request: str, tracks: list[TrackEncoding]) -> CollectionPlan: ...


class CloudLibraryClient(Protocol):
    """Legacy QQMusicAdapter contract; retained for backward compatibility.

    Its catalog and playlist methods do not imply analyzable-audio permission.
    New cloud integrations should implement the independent ports above only
    when official access grants each capability.
    """

    def list_favorites(self) -> list[dict]: ...

    def create_playlist(self, name: str, description: str = "") -> str: ...

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> None: ...

    def remove_tracks(self, playlist_id: str, track_ids: list[str]) -> None: ...

