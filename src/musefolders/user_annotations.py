"""Explicit user confirmations kept separate from inferred audio labels.

Annotations are indexed by the original file's SHA-256, not its current path.
They live in ``artifacts`` and never change a source music file.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Sequence

from .lyrics_map import THEME_PROMPTS
from .models import TrackEncoding


ANNOTATIONS_FILE = "user_annotations.json"
_SCHEMA_VERSION = 1
_GENRE_FIELD = "verified_genres_by_sha256"
_THEME_FIELD = "verified_themes_by_sha256"
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_MAX_GENRE_LENGTH = 80


def _normalize_genre(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Genre must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if not value or len(value) > _MAX_GENRE_LENGTH:
        raise ValueError("Genre must contain 1–80 characters")
    if any(unicodedata.category(char)[0] == "C" or char in "<>" for char in value):
        raise ValueError("Genre cannot contain control characters or markup")
    return re.sub(r" {2,}", " ", value)


def _track_hash(track: TrackEncoding) -> str:
    digest = track.source_sha256
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ValueError("Cannot annotate a track without a valid SHA-256 content hash")
    return digest.lower()


def _read_annotations(artifacts: Path) -> dict:
    path = artifacts / ANNOTATIONS_FILE
    if not path.exists():
        return {"schema_version": _SCHEMA_VERSION,
                "confirmed_instrumental_hashes": [], _GENRE_FIELD: {}, _THEME_FIELD: {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError("Unsupported user annotations format")
    instrumental = data.get("confirmed_instrumental_hashes", [])
    if not isinstance(instrumental, list) or any(not isinstance(value, str) for value in instrumental):
        raise ValueError("Invalid user annotations")
    genres = data.get(_GENRE_FIELD, {})
    if not isinstance(genres, dict) or any(
        not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest) or digest != digest.lower()
        or not isinstance(genre, str) or _normalize_genre(genre) != genre
        for digest, genre in genres.items()
    ):
        raise ValueError("Invalid verified genre annotations")
    data["confirmed_instrumental_hashes"] = instrumental
    data[_GENRE_FIELD] = genres
    themes = data.get(_THEME_FIELD, {})
    if not isinstance(themes, dict) or any(
        not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest) or digest != digest.lower()
        or not isinstance(theme, str) or theme not in (*THEME_PROMPTS, "unknown")
        for digest, theme in themes.items()
    ):
        raise ValueError("Invalid verified theme annotations")
    data[_THEME_FIELD] = themes
    return data


def _write_annotations(artifacts: Path, data: dict) -> None:
    """Replace the JSON document atomically, preserving the previous file on error."""
    artifacts.mkdir(parents=True, exist_ok=True)
    target = artifacts / ANNOTATIONS_FILE
    pending: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=artifacts,
            prefix=".user_annotations-", suffix=".tmp", delete=False,
        ) as file:
            pending = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def confirmed_instrumental_ids(tracks: Sequence[TrackEncoding], artifacts: Path) -> frozenset[str]:
    hashes = set(_read_annotations(artifacts)["confirmed_instrumental_hashes"])
    return frozenset(track.track_id for track in tracks if track.source_sha256 in hashes)


def set_instrumental_confirmation(track: TrackEncoding, artifacts: Path, confirmed: bool) -> None:
    """Only the user's explicit confirmation can set the strict no-vocals flag."""
    if not track.source_sha256:
        raise ValueError("Cannot annotate a track without a content hash")
    data = _read_annotations(artifacts)
    hashes = set(data["confirmed_instrumental_hashes"])
    if confirmed:
        hashes.add(track.source_sha256)
    else:
        hashes.discard(track.source_sha256)
    data["confirmed_instrumental_hashes"] = sorted(hashes)
    _write_annotations(artifacts, data)


def verified_genre_assignments(tracks: Sequence[TrackEncoding], artifacts: Path) -> dict[str, str]:
    """Map current track IDs to explicit genre confirmations only.

    A duplicate audio file inherits the same confirmed genre. Metadata genres
    and model guesses are intentionally excluded.
    """
    genres = _read_annotations(artifacts)[_GENRE_FIELD]
    return {track.track_id: genres[track.source_sha256.lower()]
            for track in tracks if isinstance(track.source_sha256, str)
            and track.source_sha256.lower() in genres}


def set_verified_genre(track: TrackEncoding, artifacts: Path, genre: str | None) -> None:
    """Save or remove a user-confirmed professional genre label for this audio."""
    digest = _track_hash(track)
    clean_genre = _normalize_genre(genre) if genre is not None else None
    data = _read_annotations(artifacts)
    genres = data[_GENRE_FIELD]
    if clean_genre is None:
        genres.pop(digest, None)
    else:
        genres[digest] = clean_genre
    _write_annotations(artifacts, data)


def clear_verified_genre(track: TrackEncoding, artifacts: Path) -> None:
    """Withdraw the user's previous genre confirmation, if one exists."""
    set_verified_genre(track, artifacts, None)


def theme_assignments(tracks: Sequence[TrackEncoding], artifacts: Path) -> dict[str, str]:
    """Return only the user's saved theme choices, never inferred labels."""
    themes = _read_annotations(artifacts)[_THEME_FIELD]
    return {
        track.track_id: themes[track.source_sha256.lower()]
        for track in tracks
        if isinstance(track.source_sha256, str)
        and track.source_sha256.lower() in themes
    }


def set_theme_assignment(track: TrackEncoding, artifacts: Path, theme_id: str | None) -> None:
    """Save or withdraw a user's theme correction without touching source audio."""
    digest = _track_hash(track)
    if theme_id is not None and theme_id not in (*THEME_PROMPTS, "unknown"):
        raise ValueError("Unknown theme ID")
    data = _read_annotations(artifacts)
    themes = data[_THEME_FIELD]
    if theme_id is None:
        themes.pop(digest, None)
    else:
        themes[digest] = theme_id
    _write_annotations(artifacts, data)
