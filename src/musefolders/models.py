from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.6"
ENGINE_VERSION = "0.5.0"
TAXONOMY_VERSION = "act-bri-v2-key-tag"
TONIC_NAMES = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")


@dataclass(slots=True)
class TrackMetadata:
    title: str
    artist: str
    album: str = ""
    genre: str = ""
    year: str = ""
    source_track_id: str = ""
    source: str = "filename"


@dataclass(slots=True)
class AcousticFeatures:
    duration_s: float
    tempo_bpm: float
    tempo_confidence: float
    rms_dbfs: float
    dynamic_range_db: float
    spectral_centroid_hz: float
    spectral_rolloff_hz: float
    zero_crossing_rate: float
    percussive_ratio: float
    onset_rate: float
    harmonic_ratio: float
    key: str
    mode: str
    key_confidence: float
    analyzed_audio_s: float
    # None identifies legacy analyses whose high-frequency spectrum was never measured.
    high_frequency_ratio: float | None = None


@dataclass(slots=True)
class StandardScores:
    agitation: float
    agitation_band: str
    brightness: float
    energy: float
    rhythmicity: float
    warmth: float


@dataclass(slots=True)
class TrackEncoding:
    track_id: str
    source_path: str
    source_size: int
    source_mtime_ns: int
    source_sha256: str
    metadata: TrackMetadata
    acoustic: AcousticFeatures
    source_ctime_ns: int = 0
    instrument: str = "unknown"
    instrument_score: float = 0.0
    instrument_status: str = "unavailable"
    standard: StandardScores | None = None
    style_hint: str = "待判定"
    genre_value: str = ""
    genre_status: str = "unavailable"
    genre_source: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    folder_id: str = ""
    folder_name: str = ""
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    taxonomy_version: str = TAXONOMY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FolderProposal:
    folder_id: str
    name: str
    imagery: str
    agitation_band: str
    tone: str
    style_hint: str
    track_ids: list[str]
    cohesion: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CollectionPlan:
    analysis_id: str
    source_root: str
    naming_mode: str
    folders: list[FolderProposal]
    tracks: list[TrackEncoding]
    scheme_id: str = "agitation_brightness"
    tag_keys: list[str] = field(default_factory=lambda: ["agitation", "brightness"])
    language: str = "zh"
    selection_query: dict[str, Any] = field(default_factory=dict)
    unsupported_files: list[dict[str, str]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    taxonomy_version: str = TAXONOMY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def track_by_id(self) -> dict[str, TrackEncoding]:
        return {track.track_id: track for track in self.tracks}

    @property
    def source_path(self) -> Path:
        return Path(self.source_root)

