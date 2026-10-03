"""QQ Music metadata adapter; source audio and local tags are never rewritten."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

if TYPE_CHECKING:
    from .models import TrackEncoding

VERSION = "qqmusic-catalog-v1"


class QQMusicConnectionError(RuntimeError):
    pass


def _text(value: object) -> str:
    return str(value or "").strip()


def _key(value: str) -> str:
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())


def _base_title(value: str) -> str:
    return _key(re.sub(r"[（(\[].*?[）)\]]", "", value))


def version_tags(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return tuple(label for pattern, label in (
        (r"\blive\b|现场", "Live"), (r"\bremix\b|混音", "Remix"),
        (r"伴奏|纯音乐|\binstrumental\b", "伴奏／纯音乐版本"),
        (r"\bacoustic\b|不插电", "Acoustic"),
    ) if re.search(pattern, folded))


def _artist_keys(value: str) -> set[str]:
    return {_base_title(part) for part in re.split(r"/|、|&|\s+feat\.?\s+", value, flags=re.I) if _base_title(part)}


def choose_candidate(query: Mapping, candidates: Sequence[Mapping]) -> tuple[dict | None, str]:
    """Automatically accept a close identity match, leaving uncertainty unresolved."""
    title, artist = _text(query.get("title")), _text(query.get("artist"))
    artists = _artist_keys(artist)
    duration = float(query.get("duration_seconds") or 0)
    scored: list[tuple[float, dict]] = []
    seen = set()
    for candidate in candidates:
        mid = _text(candidate.get("mid"))
        name = _text(candidate.get("name"))
        if not re.fullmatch(r"[A-Za-z0-9]{1,128}", mid) or mid in seen:
            continue
        seen.add(mid)
        if not _base_title(title) or _base_title(title) != _base_title(name):
            continue
        if version_tags(title) != version_tags(name):
            continue
        singers = candidate.get("singers", [])
        if not isinstance(singers, list):
            continue
        candidate_artists = set().union(*(_artist_keys(str(s)) for s in singers)) if singers else set()
        if not artists or not artists <= candidate_artists:
            continue
        candidate_duration = float(candidate.get("duration_seconds") or 0)
        if duration <= 0 or candidate_duration <= 0:
            continue
        delta = abs(duration - candidate_duration)
        tolerance = max(6, duration * .03)
        if delta > tolerance:
            continue
        score = .85 + .15 * (1 - delta / tolerance)
        scored.append((score, dict(candidate)))
    if not scored:
        return None, "not_matched"
    scored.sort(key=lambda row: -row[0])
    best_score, best = scored[0]
    if len(scored) > 1 and best_score - scored[1][0] < .04:
        other = scored[1][1]
        # Equivalent catalog entries of the same recording can have different MIDs.
        if abs(float(best.get("duration_seconds", 0)) - float(other.get("duration_seconds", 0))) > 1:
            return None, "ambiguous"
    best["match_score"] = round(best_score, 3)
    return best, "matched"


def normalize_detail(song: Mapping, detail: Mapping) -> dict:
    title = _text(detail.get("title") or detail.get("name") or song.get("name"))
    subtitle = _text(detail.get("subtitle"))
    album = detail.get("album") if isinstance(detail.get("album"), dict) else {}
    date = _text(detail.get("time_public") or detail.get("publish_date") or album.get("time_public"))
    language = detail.get("language")
    if language is None:
        language = detail.get("lan")
    genre = detail.get("genre")
    singers = detail.get("singer")
    artist = "/".join(_text(s.get("name")) for s in singers if isinstance(s, dict) and s.get("name")) if isinstance(singers, list) else ""
    return {
        "mid": song["mid"], "title": title, "artist": artist or "/".join(song.get("singers", [])),
        "album": _text(album.get("name") or song.get("album")),
        "publish_date": date, "release_year": int(date[:4]) if re.match(r"^(18|19|20|21)\d{2}", date) else None,
        "language_raw": language, "genre_raw": genre,
        "language": language if isinstance(language, str) and not language.isdigit() else "",
        "genre": genre if isinstance(genre, str) and not genre.isdigit() else "",
        "version": _text(detail.get("version")) or subtitle,
        "version_tags": list(version_tags(title + " " + subtitle)),
        "duration_seconds": song.get("duration_seconds", 0),
    }


def _read(artifacts: Path) -> dict:
    try:
        data = json.loads((artifacts / "platform_catalog.json").read_text(encoding="utf-8"))
        if data.get("version") == VERSION and isinstance(data.get("tracks"), dict):
            data["tracks"] = {key: entry for key, entry in data["tracks"].items() if isinstance(entry, dict)}
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {"version": VERSION, "provider": "qqmusic", "tracks": {}}


def cached_platform(tracks: Sequence[TrackEncoding], artifacts: Path) -> dict[str, dict]:
    records = _read(artifacts)["tracks"]
    return {track.track_id: entry for track in tracks
            if isinstance((entry := records.get(track.track_id)), dict)
            and entry.get("source_sha256") == track.source_sha256 and entry.get("status") == "matched"}


def platform_lyrics(records: Mapping[str, Mapping], artifacts: Path) -> dict[str, Path]:
    return {track_id: path for track_id, entry in records.items()
            if re.fullmatch(r"[A-Za-z0-9]{1,128}", _text(entry.get("mid")))
            and (path := artifacts / "platform_lyrics" / f"{entry['mid']}.lrc").is_file()}


def _save(artifacts: Path, data: dict) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    target = artifacts / "platform_catalog.json"
    pending = target.with_suffix(".pending")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(target)


def _bridge_paths() -> tuple[Path, Path]:
    home = Path(os.getenv("MUSEFOLDERS_QQMUSIC_HOME", r"E:\MuseFolders\qqmusic-mcp"))
    python = home / ".venv" / "Scripts" / "python.exe"
    helper = Path(__file__).resolve().parents[2] / "scripts" / "qqmusic_bridge.py"
    if not python.is_file() or not helper.is_file():
        raise QQMusicConnectionError("未找到 QQ 音乐连接程序，请检查安装目录。")
    return python, helper


def _events(payload: dict):
    python, helper = _bridge_paths()
    process = subprocess.Popen([str(python), str(helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        process.stdin.write(json.dumps(payload, ensure_ascii=False))
        process.stdin.close()
        for line in process.stdout:
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("invalid event")
            except ValueError:
                raise QQMusicConnectionError("QQ 音乐连接程序返回了无效数据。") from None
            if event.get("event") == "fatal":
                raise QQMusicConnectionError(event.get("message", "QQ 音乐连接失败。"))
            yield event
        if process.wait(timeout=10) != 0:
            raise QQMusicConnectionError("QQ 音乐连接未完成，请检查本机登录状态。")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def connection_status() -> dict:
    for event in _events({"operation": "status"}):
        if event.get("event") == "status":
            return event["result"]
    raise QQMusicConnectionError("无法读取 QQ 音乐登录状态。")


def enrich_library(tracks: Sequence[TrackEncoding], artifacts: Path, *, force_refresh: bool = False,
                   progress: Callable[[int, int], None] | None = None) -> dict:
    data = _read(artifacts)
    pending = []
    cached = 0
    now = datetime.now(timezone.utc)
    for track in tracks:
        entry = data["tracks"].get(track.track_id, {})
        try:
            valid = datetime.fromisoformat(entry["checked_at"]) > now - timedelta(days=30 if entry.get("status") == "matched" else 1)
        except (KeyError, TypeError, ValueError):
            valid = False
        if entry.get("status") == "error" or entry.get("lyrics_error"):
            valid = False
        if entry.get("has_lyrics") and not (artifacts / "platform_lyrics" / f"{entry.get('mid', '')}.lrc").is_file():
            valid = False
        if not force_refresh and valid and entry.get("source_sha256") == track.source_sha256:
            cached += 1
            continue
        pending.append({"track_id": track.track_id, "source_sha256": track.source_sha256,
                        "title": track.metadata.title, "artist": track.metadata.artist,
                        "duration_seconds": track.acoustic.duration_s})
    if progress:
        progress(cached, len(tracks))
    by_id = {query["track_id"]: query for query in pending}
    completed = 0
    if pending:
        for event in _events({"operation": "enrich", "tracks": pending}):
            if event.get("event") != "song" or event.get("track_id") not in by_id:
                continue
            query = by_id.pop(event["track_id"])
            result = dict(event["result"])
            lyrics = result.pop("lyrics", None)
            mid = _text(result.get("mid"))
            if lyrics and result.get("status") == "matched" and re.fullmatch(r"[A-Za-z0-9]{1,128}", mid):
                from .lyrics_map import clean_lyrics, lyrics_are_usable
                result["has_lyrics"] = lyrics_are_usable(clean_lyrics(str(lyrics)))
                folder = artifacts / "platform_lyrics"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{mid}.lrc"
                temp = path.with_suffix(".pending")
                temp.write_text(str(lyrics), encoding="utf-8")
                temp.replace(path)
            result.update(source_sha256=query["source_sha256"], checked_at=datetime.now(timezone.utc).isoformat())
            data["tracks"][query["track_id"]] = result
            _save(artifacts, data)
            completed += 1
            if progress:
                progress(cached + completed, len(tracks))
        if by_id:
            raise QQMusicConnectionError("部分歌曲未处理完成，可再次点击继续补充。")
    from .lyrics_map import clean_lyrics, lyrics_are_usable
    changed = False
    active_records = cached_platform(tracks, artifacts)
    lyric_paths = platform_lyrics(active_records, artifacts)
    for track_id, entry in active_records.items():
        path = lyric_paths.get(track_id)
        usable = bool(path and lyrics_are_usable(clean_lyrics(path.read_text(encoding="utf-8"))))
        # Reconcile older/raw lyric flags without making another network request.
        if entry.get("has_lyrics") != usable:
            data["tracks"][track_id]["has_lyrics"] = usable
            changed = True
    if changed:
        _save(artifacts, data)
    active = [data["tracks"].get(track.track_id, {}) for track in tracks]
    return {"matched": sum(entry.get("status") == "matched" for entry in active), "cached": cached,
            "processed": completed, "total": len(tracks),
            "lyrics": sum(bool(entry.get("has_lyrics")) for entry in active),
            "unmatched": sum(entry.get("status") in {"not_matched", "ambiguous"} for entry in active),
            "errors": sum(entry.get("status") == "error" for entry in active)}
