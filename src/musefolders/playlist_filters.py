"""Reusable, platform-independent queries for on-demand local playlists."""

from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import CollectionPlan, FolderProposal, TrackEncoding
from .taxonomy import key_tag_value


MISSING_VALUE = "\x00missing"
FACET_FIELDS = ("artists", "albums", "genres", "years", "instruments", "keys", "loudness", "tempo")


@dataclass(frozen=True)
class PlaylistFilters:
    title_query: str = ""
    artists: frozenset[str] = frozenset()
    albums: frozenset[str] = frozenset()
    genres: frozenset[str] = frozenset()
    years: frozenset[str] = frozenset()
    instruments: frozenset[str] = frozenset()
    keys: frozenset[str] = frozenset()
    loudness: frozenset[str] = frozenset()
    tempo: frozenset[str] = frozenset()
    act_range: tuple[float, float] = (0.0, 100.0)
    bri_range: tuple[float, float] = (0.0, 100.0)

    def to_dict(self) -> dict:
        data = asdict(self)
        for field in FACET_FIELDS:
            data[field] = sorted(data[field])
        return data


def facet_value(track: TrackEncoding, field: str) -> str:
    if field == "artists":
        return track.metadata.artist.strip() or MISSING_VALUE
    if field == "albums":
        return track.metadata.album.strip() or MISSING_VALUE
    if field == "genres":
        return track.metadata.genre.strip() or MISSING_VALUE
    if field == "years":
        return track.metadata.year.strip() or MISSING_VALUE
    if field == "instruments":
        return track.instrument
    if field == "keys":
        return track.tags.get("key", key_tag_value(track.acoustic))
    if field in {"loudness", "tempo"}:
        return track.tags.get(field, "uncertain")
    raise ValueError(f"Unknown filter field: {field}")


def facet_options(tracks: list[TrackEncoding], field: str) -> list[str]:
    return sorted({facet_value(track, field) for track in tracks}, key=lambda value: (value == MISSING_VALUE, value.casefold()))


def matches(track: TrackEncoding, filters: PlaylistFilters, *, omit: str | None = None) -> bool:
    if omit != "title_query" and filters.title_query.strip().casefold() not in track.metadata.title.casefold():
        return False
    for field in FACET_FIELDS:
        chosen = getattr(filters, field)
        if field != omit and chosen and facet_value(track, field) not in chosen:
            return False
    if omit != "act_range" and filters.act_range != (0.0, 100.0):
        if track.standard is None or not filters.act_range[0] <= track.standard.agitation <= filters.act_range[1]:
            return False
    if omit != "bri_range" and filters.bri_range != (0.0, 100.0):
        if track.standard is None or not filters.bri_range[0] <= track.standard.brightness <= filters.bri_range[1]:
            return False
    return True


def filter_tracks(tracks: list[TrackEncoding], filters: PlaylistFilters, *, omit: str | None = None) -> list[TrackEncoding]:
    return [track for track in tracks if matches(track, filters, omit=omit)]


def facet_counts(tracks: list[TrackEncoding], filters: PlaylistFilters, field: str) -> dict[str, int]:
    """Count each option among tracks meeting every *other* active condition."""
    if field not in FACET_FIELDS:
        raise ValueError(f"Unknown filter field: {field}")
    return dict(Counter(facet_value(track, field) for track in filter_tracks(tracks, filters, omit=field)))


def relaxation_counts(tracks: list[TrackEncoding], filters: PlaylistFilters) -> dict[str, int]:
    active = [field for field in FACET_FIELDS if getattr(filters, field)]
    if filters.title_query.strip():
        active.append("title_query")
    if filters.act_range != (0.0, 100.0):
        active.append("act_range")
    if filters.bri_range != (0.0, 100.0):
        active.append("bri_range")
    return {field: count for field in active if (count := len(filter_tracks(tracks, filters, omit=field))) > 0}


def safe_playlist_name(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", " ".join(name.split())).strip().rstrip(". ")
    clean = clean[:80].rstrip(". ")
    if not clean:
        raise ValueError("Playlist name is empty")
    if clean.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean = f"_{clean}"
    return clean


def playlist_bytes(tracks: list[TrackEncoding]) -> bytes:
    """Create an M3U8 whose absolute entries refer to the original local files."""
    lines = ["#EXTM3U", *(str(Path(track.source_path).resolve()) for track in tracks)]
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def build_playlist_plan(
    source_plan: CollectionPlan, selected: list[TrackEncoding], name: str,
    filters: PlaylistFilters, language: str,
) -> CollectionPlan:
    if not selected:
        raise ValueError("A playlist needs at least one track")
    clean_name = safe_playlist_name(name)
    tracks = copy.deepcopy(selected)
    for track in tracks:
        track.folder_id = "P01"
        track.folder_name = clean_name
    folder = FolderProposal(
        folder_id="P01", name=clean_name, imagery="", agitation_band="", tone="", style_hint="",
        track_ids=[track.track_id for track in tracks], cohesion=0.0,
        explanation="Tracks matching the chosen filters." if language == "en" else "符合所选筛选条件的曲目。",
    )
    return CollectionPlan(
        analysis_id=f"{source_plan.analysis_id}-playlist", source_root=source_plan.source_root,
        naming_mode="custom", folders=[folder], tracks=tracks, scheme_id="filtered_playlist",
        tag_keys=[], language=language, selection_query=filters.to_dict(),
    )
