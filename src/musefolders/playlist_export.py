"""Export actual playlist audio as a portable MP3 folder in a ZIP archive."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import subprocess
import tempfile
import uuid
import zipfile

from mutagen import MutagenError
from mutagen.mp3 import MP3

from .audio import SUPPORTED_EXTENSIONS
from .models import TrackEncoding
from .playlist_filters import safe_playlist_name

MAX_EXPORT_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class MusicZip:
    path: Path
    name: str
    count: int
    converted: int
    skipped: tuple[tuple[str, str], ...]
    metadata_fallbacks: tuple[str, ...]


def _mp3_duration(path: Path) -> float | None:
    try:
        audio = MP3(path)
        duration = float(audio.info.length)
        if math.isfinite(duration) and duration > 0 and audio.info.channels in (1, 2):
            return duration
    except (MutagenError, OSError, ValueError, AttributeError):
        return None
    return None


def _transcode(source: Path, destination: Path) -> float:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        executable = get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        raise ValueError("MP3 转换组件不可用，请更新运行依赖后重试。") from None
    try:
        process = subprocess.run(
            [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(source), "-map", "0:a:0", "-vn", "-map_metadata", "0",
             "-codec:a", "libmp3lame", "-q:a", "2", "-ar", "44100", "-ac", "2",
             str(destination)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=300, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("音频转换超时。") from None
    except OSError:
        raise ValueError("无法启动 MP3 转换组件。") from None
    duration = _mp3_duration(destination) if process.returncode == 0 else None
    if duration is None:
        raise ValueError("音频损坏或格式无法转换为可播放的 MP3。")
    return duration


def export_music_zip(
    tracks: list[TrackEncoding], name: str, output_root: Path, *,
    missing_titles: list[str] | None = None, max_bytes: int = MAX_EXPORT_BYTES,
) -> MusicZip:
    """Copy valid MP3s, convert other audio, preserve order and report omissions.

    Only server-resolved collection tracks are accepted; ZIP members never contain
    absolute source paths. Originals are read-only and the final archive is atomic.
    """
    if not tracks and not missing_titles:
        raise ValueError("先把喜欢的歌加入预备歌单，再导出音乐包。")
    folder = safe_playlist_name(name)[:60].rstrip(". ")
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / ("music-" + uuid.uuid4().hex + ".zip")
    skipped = [(str(title), "当前曲库中找不到此录音。") for title in missing_titles or []]
    lines = ["#EXTM3U"]
    converted = count = total_bytes = 0
    metadata_fallbacks = []
    seen = set()
    with tempfile.TemporaryDirectory(prefix=".music-zip-", dir=output_root) as temporary:
        work = Path(temporary)
        archive_path = work / "ready.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for track in tracks:
                identity = track.source_sha256 or track.track_id
                if identity in seen:
                    continue
                seen.add(identity)
                source = Path(track.source_path).resolve()
                title = track.metadata.title.strip() or source.stem or "未命名歌曲"
                if not source.is_file():
                    skipped.append((title, "没有可读取的音频文件；仅有歌曲资料无法导出音乐。"))
                    continue
                if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    skipped.append((title, "不支持此音频格式。"))
                    continue
                if source.stat().st_size > max_bytes:
                    raise ValueError("单曲文件超过导出容量，请减少导出歌曲后重试。")
                duration = _mp3_duration(source) if source.suffix.lower() == ".mp3" else None
                was_converted = duration is None
                if was_converted:
                    destination = work / "converted.mp3"
                    try:
                        duration = _transcode(source, destination)
                    except ValueError as exc:
                        skipped.append((title, str(exc)))
                        continue
                else:
                    destination = source
                total_bytes += destination.stat().st_size
                if total_bytes > max_bytes:
                    raise ValueError("音乐包超过 512 MB，请分成较小的预备歌单后导出。")
                if not track.metadata.title.strip() or not track.metadata.artist.strip():
                    metadata_fallbacks.append(title)
                label = (track.metadata.artist.strip() or "未知歌手") + " - " + title
                stem = safe_playlist_name(label)[:110].rstrip(". ")
                filename = f"{count + 1:03d} - {stem}.mp3"
                archive.write(destination, f"{folder}/{filename}")
                display = label.replace("\r", " ").replace("\n", " ")
                lines.extend([f"#EXTINF:{round(duration)},{display}", filename])
                count += 1
                converted += int(was_converted)
            if not count:
                reasons = "；".join(f"{title}：{reason}" for title, reason in skipped[:3])
                raise ValueError("没有可导出的 MP3 音频。" + reasons)
            archive.writestr(f"{folder}/播放清单.m3u8", ("\n".join(lines) + "\n").encode("utf-8-sig"))
            notes = [f"{folder} · 曲境音乐包", f"包含 {count} 首真实 MP3 音频，已按音频指纹去重。",
                     "解压此文件夹后，可直接播放 MP3；播放清单中的路径均为相对路径。",
                     f"已有 MP3 保持原文件；{converted} 首其他音频已转换为 MP3，原曲库文件未修改。"]
            if metadata_fallbacks:
                notes.extend(["", "以下歌曲的歌名或歌手资料不完整，已使用文件名／未知歌手命名，音频可播放："])
                notes.extend(f"- {title}" for title in metadata_fallbacks)
            if skipped:
                notes.extend(["", f"以下 {len(skipped)} 首没有导出："])
                notes.extend(f"- {title}：{reason}" for title, reason in skipped)
            archive.writestr(f"{folder}/导出说明.txt", ("\n".join(notes) + "\n").encode("utf-8-sig"))
        archive_path.replace(final)
    return MusicZip(final, folder + ".zip", count, converted, tuple(skipped), tuple(metadata_fallbacks))
