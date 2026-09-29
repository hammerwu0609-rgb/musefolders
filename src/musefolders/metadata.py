from __future__ import annotations

import re
import base64
from pathlib import Path

from tinytag import TinyTag

from .models import TrackMetadata


_SUFFIX_RE = re.compile(r"(?:_L|_SQ|_HQ)$", re.IGNORECASE)


def _clean(value: object | None) -> str:
    return " ".join(str(value or "").replace("\x00", "").split()).strip()


def parse_filename(path: Path) -> tuple[str, str]:
    stem = _SUFFIX_RE.sub("", path.stem).strip()
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return _clean(title), _clean(artist.replace(" _ ", " / "))
    return _clean(stem), ""


def read_metadata(path: Path) -> TrackMetadata:
    fallback_title, fallback_artist = parse_filename(path)
    try:
        tag = TinyTag.get(path, image=False)
        title = _clean(tag.title) or fallback_title
        artist = _clean(tag.artist) or fallback_artist
        album = _clean(tag.album)
        genre = _clean(tag.genre)
        year = _clean(tag.year)
        source_ids = (getattr(tag, "other", {}) or {}).get("id", [])
        source_track_id = _clean(source_ids[0] if source_ids else "")
        source = "embedded+filename" if tag.title or tag.artist else "filename"
        return TrackMetadata(
            title=title,
            artist=artist,
            album=album,
            genre=genre,
            year=year,
            source_track_id=source_track_id,
            source=source,
        )
    except Exception:
        return TrackMetadata(title=fallback_title, artist=fallback_artist, source="filename")


def read_cover_data_uri(path: Path) -> str | None:
    """Read embedded cover art only; no network lookup or source-file writes."""
    try:
        tag = TinyTag.get(path, image=True)
        image = tag.images.any
        if image is None or not image.data or image.mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            return None
        return f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}"
    except Exception:
        return None

