"""Reviewable per-track facts assembled from the three local evidence sources.

No lyric text is retained in a profile. A theme is a keyword clue, never a
verified interpretation of a song. Raw file genres remain visibly unverified.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .lyrics_map import resolve_track_lyrics
from .models import TrackEncoding

TAG_CATALOG_VERSION = "three-source-v2"
MANUAL_THEME_NAMES = {
    "love": "爱情", "family": "亲情", "friendship": "友情", "memory": "回忆",
    "solitude": "孤独", "hope": "成长", "journey": "旅途",
    "celebration": "庆祝", "nature": "自然",
}
THEME_TERMS: dict[str, tuple[str, ...]] = {
    "爱情": ("爱情", "恋爱", "恋人", "爱你", "爱我", "相爱", "亲吻", "love", "lover"),
    "暗恋": ("暗恋", "偷偷喜欢", "crush"),
    "失恋": ("失恋", "分手", "离开我", "不再爱", "breakup"),
    "思念": ("思念", "想念", "想你", "miss you"),
    "成长": ("成长", "希望", "梦想", "勇敢", "未来", "hope"),
    "友情": ("友情", "友谊", "朋友", "friend"),
    "亲情": ("亲情", "妈妈", "爸爸", "母亲", "父亲", "family"),
    "回忆": ("回忆", "记忆", "往事", "童年", "memory", "memories"),
    "孤独": ("孤独", "寂寞", "孤单", "lonely", "alone"),
    "旅途": ("旅途", "旅行", "远方", "journey", "travel"),
    "庆祝": ("庆祝", "派对", "欢聚", "celebrate", "party"),
    "自然": ("森林", "海洋", "山川", "自然", "forest", "ocean"),
}


def contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I)) if term.isascii() else term in text


@dataclass(frozen=True)
class TagEvidence:
    dimension: str
    label: str
    source: str
    status: str
    clues: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackProfile:
    track_id: str
    tags: tuple[TagEvidence, ...]
    lyrics_status: str
    tempo_bpm: float | None
    activity: float | None
    brightness: float | None
    title: str
    artist: str
    album: str
    year: int | None
    raw_genre: str
    version: str = TAG_CATALOG_VERSION
    metadata_source: str = "file_metadata"
    year_source: str = "file_metadata"
    language: str = ""
    recording_version: str = ""
    platform_mid: str = ""

    def theme(self, name: str) -> TagEvidence | None:
        return next((tag for tag in self.tags if tag.dimension == "theme" and tag.label == name), None)


def _release_year(raw: str) -> int | None:
    match = re.match(r"^(18|19|20|21)\d{2}(?:\D|$)", str(raw).strip())
    return int(match.group(0)[:4]) if match else None


def build_track_profiles(
    tracks: Sequence[TrackEncoding], *, lyrics_root: Path | None = None,
    selected_sources: Mapping[str, Path] | None = None,
    manual_themes: Mapping[str, str] | None = None,
    ai_themes: Mapping[str, tuple[str, ...]] | None = None,
    verified_genres: Mapping[str, str] | None = None,
    instrumental_ids: frozenset[str] = frozenset(),
    platform_metadata: Mapping[str, Mapping] | None = None,
    fallback_sources: Mapping[str, Path] | None = None,
) -> dict[str, TrackProfile]:
    """Read source files without changing them or caching copyrighted text."""
    root = Path(lyrics_root) if lyrics_root is not None else None
    selected = selected_sources or {}
    manual = manual_themes or {}
    inferred = ai_themes or {}
    platform = platform_metadata or {}
    fallback = fallback_sources or {}
    confirmed_genres = verified_genres or {}
    profiles: dict[str, TrackProfile] = {}
    for track in tracks:
        lyrics = resolve_track_lyrics(track, lyrics_root=root, all_tracks=tracks,
                                      selected_path=selected.get(track.track_id),
                                      fallback_path=fallback.get(track.track_id))
        tags: list[TagEvidence] = []
        if track.track_id in manual:
            manual_name = MANUAL_THEME_NAMES.get(manual[track.track_id])
            if manual_name:
                tags.append(TagEvidence("theme", manual_name, "user_confirmation", "verified"))
        elif track.track_id in inferred:
            tags.extend(TagEvidence("theme", name, "ai_lyrics", "inferred")
                        for name in inferred[track.track_id] if name in THEME_TERMS)
        elif lyrics.status == "valid":
            text = lyrics.text.casefold()
            for name, terms in THEME_TERMS.items():
                clues = tuple(term for term in terms if contains(text, term))
                if clues:
                    tags.append(TagEvidence("theme", name, lyrics.source, "keyword_clue", clues))
        acoustic = track.acoustic
        standard = track.standard
        if standard is not None:
            raw_activity = getattr(standard, "agitation", None)
            raw_brightness = getattr(standard, "brightness", None)
            activity = float(raw_activity) if raw_activity is not None else None
            brightness = float(raw_brightness) if raw_brightness is not None else None
            if activity is not None and 0 <= activity <= 100:
                band = "安静" if activity < 35 else "活跃" if activity >= 60 else "适中"
                tags.append(TagEvidence("sound", band, "audio_analysis", "estimated"))
            else:
                activity = None
            if brightness is not None and not 0 <= brightness <= 100:
                brightness = None
        else:
            activity = brightness = None
        tempo = float(acoustic.tempo_bpm)
        if not (0 < tempo <= 300 and acoustic.tempo_confidence > 0):
            tempo = None
        metadata = track.metadata
        extra = platform.get(track.track_id, {})
        year = extra.get("release_year")
        platform_year = isinstance(year, int) and not isinstance(year, bool) and 1800 <= year <= 2199
        language = extra.get("language", "")
        recording_version = extra.get("version", "")
        if language:
            tags.append(TagEvidence("language", str(language), "qqmusic", "metadata"))
        for label in extra.get("version_tags", []):
            tags.append(TagEvidence("version", str(label), "qqmusic", "metadata"))
        genre = str(getattr(metadata, "genre", "") or "").strip()
        if extra.get('genre'):
            tags.append(TagEvidence("genre", str(extra['genre']), "qqmusic", "metadata"))
        elif genre:
            tags.append(TagEvidence("genre", genre, "file_metadata", "raw_unverified"))
        confirmed_genre = confirmed_genres.get(track.track_id)
        if confirmed_genre:
            tags.append(TagEvidence("genre", confirmed_genre, "user_confirmation", "verified"))
        if track.track_id in instrumental_ids:
            tags.append(TagEvidence("vocal", "纯音乐", "user_confirmation", "verified"))
        profiles[track.track_id] = TrackProfile(
            track_id=track.track_id, tags=tuple(tags), lyrics_status=lyrics.status,
            tempo_bpm=tempo, activity=activity, brightness=brightness,
            title=str(extra.get("title") or metadata.title), artist=str(extra.get("artist") or metadata.artist),
            album=str(extra.get("album") or metadata.album),
            year=year if platform_year else _release_year(getattr(metadata, "year", "")), raw_genre=genre,
            metadata_source="qqmusic" if extra else "file_metadata",
            year_source="qqmusic" if platform_year else "file_metadata",
            language=str(language or ""), recording_version=str(recording_version or ""),
            platform_mid=str(extra.get("mid") or ""),
        )
    return profiles


def save_profile_catalog(profiles: Mapping[str, TrackProfile], artifacts: Path,
                         *, analysis_id: str) -> Path:
    """Save inspectable labels and measurements, excluding lyric text and paths."""
    target = Path(artifacts) / "tag_catalog.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for profile in profiles.values():
        records.append({
            "track_id": profile.track_id, "lyrics_status": profile.lyrics_status,
            "tempo_bpm": profile.tempo_bpm, "activity": profile.activity,
            "brightness": profile.brightness, "title": profile.title,
            "artist": profile.artist, "album": profile.album,
            "year": profile.year, "raw_genre": profile.raw_genre,
            "metadata_source": profile.metadata_source, "year_source": profile.year_source,
            "language": profile.language, "recording_version": profile.recording_version,
            "platform_mid": profile.platform_mid,
            "tags": [{"dimension": tag.dimension, "label": tag.label,
                      "source": tag.source, "status": tag.status} for tag in profile.tags],
        })
    data = {"version": TAG_CATALOG_VERSION, "analysis_id": analysis_id,
            "tracks": records}
    pending = target.with_suffix(".pending")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(target)
    return target
