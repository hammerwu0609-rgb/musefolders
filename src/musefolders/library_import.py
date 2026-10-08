"""Portable music packages and staged audio imports for local and web workspaces."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import BinaryIO, Callable
import uuid
import zipfile

from .audio import SUPPORTED_EXTENSIONS, sha256_file
from .demo_mode import FIXED_ARTIFACTS, prepare_workspace
from .models import CollectionPlan
from .service import analyze_library, load_plan, save_plan

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_FILES = 2000
SIDECARS = {".lrc", ".txt"}
MANIFEST = "music_package.json"
Progress = Callable[[int, int, str], None]


class MusicImportError(ValueError):
    """An actionable import error that does not expose server paths."""


@dataclass
class MusicImport:
    workspace: Path
    plan: CollectionPlan
    report: dict


def safe_relative(name: str) -> Path:
    # ZIP paths use '/'; disallow Windows drive names, alternate streams and links.
    pure = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or "\x00" in name or
            pure.is_absolute() or any(p in {"..", "."} for p in name.split("/"))):
        raise MusicImportError("音乐包包含无效路径，请重新打包。")
    if any(p.rstrip(" .") != p for p in pure.parts):
        raise MusicImportError("音乐包中的文件名不兼容，请重新打包。")
    return Path(*pure.parts)


def _json(path: Path) -> dict:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise MusicImportError("音乐包中的资料文件过大。")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError):
        raise MusicImportError("音乐包中的资料文件无法读取。") from None
    if not isinstance(value, dict):
        raise MusicImportError("音乐包中的资料格式不正确。")
    return value


def _new_workspace(root: Path) -> Path:
    parent = root / "library_imports"
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="music-", dir=parent))


def _discard(workspace: Path, root: Path):
    if workspace.resolve().parent != (root / "library_imports").resolve():
        raise MusicImportError("导入临时目录不正确。")
    shutil.rmtree(workspace)


def _extract(archive: zipfile.ZipFile, destination: Path, progress: Progress):
    members = archive.infolist()
    if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
        raise MusicImportError("音乐包最多 2000 个文件，解压后最多 1 GB。")
    files, seen = [], set()
    for member in members:
        path = safe_relative(member.filename.rstrip("/"))
        identity = str(path).casefold()
        if identity in seen or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
            raise MusicImportError("音乐包有重名、链接或加密文件，请重新打包。")
        seen.add(identity)
        if member.is_dir():
            continue
        if member.file_size > MAX_UPLOAD_BYTES:
            raise MusicImportError("音乐包中的单个文件超过 512 MB。")
        if path.suffix.lower() in SIDECARS and member.file_size > 2 * 1024 * 1024:
            raise MusicImportError("单个歌词文件最大 2 MB。")
        allowed = (path.suffix.lower() in SUPPORTED_EXTENSIONS | SIDECARS or
                   path.name in {"collection_plan.json", MANIFEST, *FIXED_ARTIFACTS,
                                 "README.md", "使用说明.md"})
        if not allowed:
            raise MusicImportError("请仅打包音频、歌词和曲境资料，不要包含其他文件。")
        files.append((member, path))
    if not files:
        raise MusicImportError("音乐包为空。")
    for index, (member, relative) in enumerate(files, 1):
        progress(index - 1, len(files), "正在读取音乐包")
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, output.open("wb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    progress(len(files), len(files), "音乐包读取完成")


def _verify_manifest(bundle: Path, progress: Progress):
    path = bundle / MANIFEST
    if not path.is_file():
        return
    manifest = _json(path)
    entries = manifest.get("files")
    if manifest.get("format") != "musefolders-music-v1" or not isinstance(entries, list):
        raise MusicImportError("音乐包的校验清单格式不正确。")
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*")
              if p.is_file() and p != path}
    recorded = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise MusicImportError("音乐包的校验记录不正确。")
        relative = safe_relative(entry["path"])
        file = bundle / relative
        if entry["path"] in recorded:
            raise MusicImportError("音乐包的校验清单有重复记录。")
        recorded.add(entry["path"])
        progress(index - 1, len(entries), "正在校验音频、歌词与资料")
        if (not file.is_file() or file.stat().st_size != entry.get("size") or
                sha256_file(file) != entry.get("sha256")):
            raise MusicImportError("音乐包文件不完整或已被修改，请重新下载。")
    if recorded != actual:
        raise MusicImportError("音乐包内容与校验清单不一致，请重新下载。")


def _portable_plan(bundle: Path, workspace: Path, progress: Progress) -> CollectionPlan:
    raw = _json(bundle / "collection_plan.json")
    tracks = raw.get("tracks")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= MAX_FILES:
        raise MusicImportError("音乐包中没有有效的歌曲清单。")
    ids = set()
    paths = set()
    for index, track in enumerate(tracks, 1):
        if not isinstance(track, dict) or not isinstance(track.get("source_path"), str):
            raise MusicImportError("音乐包的歌曲记录不正确。")
        relative = safe_relative(track["source_path"])
        source = bundle / relative
        tid = track.get("track_id")
        if (not isinstance(tid, str) or not tid or tid in ids or
                relative in paths or not relative.parts or relative.parts[0] != "audio" or
                relative.suffix.lower() not in SUPPORTED_EXTENSIONS or not source.is_file()):
            raise MusicImportError("音乐包的音频路径、歌曲编号或文件不正确。")
        progress(index - 1, len(tracks), "正在核对歌曲与分析资料")
        if (source.stat().st_size != track.get("source_size") or
                sha256_file(source) != track.get("source_sha256")):
            raise MusicImportError("歌曲与分析资料不匹配，请重新下载音乐包。")
        ids.add(tid)
        paths.add(relative)
    for name in FIXED_ARTIFACTS:
        if (bundle / name).is_file():
            data = _json(bundle / name)
            if name in {"platform_catalog.json", "ai_lyrics_tags.json"}:
                records = data.get("tracks", {})
                by_id = {t["track_id"]: t for t in tracks}
                if (not isinstance(records, dict) or any(
                        tid not in by_id or not isinstance(entry, dict) or
                        entry.get("source_sha256") != by_id[tid]["source_sha256"]
                        for tid, entry in records.items())):
                    raise MusicImportError("歌词标签或平台资料与歌曲不匹配。")
    prepare_workspace(bundle, workspace)
    try:
        plan = load_plan(workspace / "artifacts" / "collection_plan.json")
    except (KeyError, TypeError, ValueError):
        raise MusicImportError("音乐包的分析档案不兼容，请重新导出。") from None
    if any(t.standard is None for t in plan.tracks):
        raise MusicImportError("音乐包缺少听感分析，请先分析或改用音频文件导入。")
    return plan


def _analyze(source: Path, workspace: Path, progress: Progress):
    plan, evidence = analyze_library(source, workspace / "artifacts", naming_mode="quant",
                                    scheme_id="custom", language="zh", progress=progress)
    return plan, evidence


def import_zip(upload: BinaryIO, root: Path, *, reanalyze: bool = False,
               progress: Progress = lambda done, total, text: None) -> MusicImport:
    workspace = _new_workspace(root)
    try:
        upload.seek(0, 2)
        if upload.tell() > MAX_UPLOAD_BYTES:
            raise MusicImportError("音乐包最大 512 MB。")
        upload.seek(0)
        source = workspace / "source"
        source.mkdir()
        with zipfile.ZipFile(upload) as archive:
            _extract(archive, source, progress)
        plans = list(source.rglob("collection_plan.json"))
        if len(plans) > 1:
            raise MusicImportError("一个音乐包只能包含一份收藏清单。")
        evidence = {}
        if plans:
            bundle = plans[0].parent
            _verify_manifest(bundle, progress)
            plan = _portable_plan(bundle, workspace, progress)
            if reanalyze:
                previous = {t.source_path: t for t in plan.tracks}
                new, evidence = _analyze(Path(plan.source_root), workspace, progress)
                # Preserve the verified IDs so lyrics, platform and manual data stay linked.
                for track in new.tracks:
                    old = previous.get(track.source_path)
                    if old and old.source_sha256 == track.source_sha256:
                        track.track_id, track.metadata = old.track_id, old.metadata
                new.folders = []
                plan = new
                save_plan(plan, workspace / "artifacts")
                valid_ids = {t.track_id for t in plan.tracks}
                for name in ("platform_catalog.json", "ai_lyrics_tags.json"):
                    path = workspace / "artifacts" / name
                    if path.is_file():
                        data = _json(path)
                        data["tracks"] = {k: v for k, v in data.get("tracks", {}).items() if k in valid_ids}
                        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            cached = 0 if reanalyze else len(plan.tracks)
        else:
            plan, evidence = _analyze(source, workspace, progress)
            cached = evidence.get("cache_hits", 0)
        report = {"tracks": len(plan.tracks), "cached": cached,
                  "measured": len(plan.tracks) - cached,
                  "lyrics_files": len(list(Path(plan.source_root).rglob("*.lrc"))),
                  "failed": len(plan.failures), "unsupported": len(plan.unsupported_files)}
        progress(1, 1, "导入完成")
        return MusicImport(workspace, plan, report)
    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        _discard(workspace, root)
        if isinstance(exc, MusicImportError):
            raise
        raise MusicImportError("音乐包读取或分析失败，请检查文件格式和包内结构。") from None


def import_files(uploads, root: Path, *,
                 progress: Progress = lambda done, total, text: None) -> MusicImport:
    if not uploads or len(uploads) > MAX_FILES or sum(u.size for u in uploads) > MAX_UPLOAD_BYTES:
        raise MusicImportError("请上传音频及同名歌词，总计不超过 512 MB、2000 个文件。")
    workspace = _new_workspace(root)
    try:
        source = workspace / "source"
        source.mkdir()
        seen = set()
        for upload in uploads:
            relative = safe_relative(upload.name)
            if relative.suffix.lower() not in SUPPORTED_EXTENSIONS | SIDECARS:
                raise MusicImportError("请选择可支持的音频或歌词文件。")
            if relative.suffix.lower() in SIDECARS and upload.size > 2 * 1024 * 1024:
                raise MusicImportError("单个歌词文件最大 2 MB。")
            identity = str(relative).casefold()
            if identity in seen:
                raise MusicImportError("上传了重名文件，请分开导入或使用 ZIP 保留文件夹结构。")
            seen.add(identity)
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            upload.seek(0)
            with target.open("wb") as handle:
                shutil.copyfileobj(upload, handle, 1024 * 1024)
        plan, evidence = _analyze(source, workspace, progress)
        return MusicImport(workspace, plan, {"tracks": len(plan.tracks),
            "cached": evidence["cache_hits"], "measured": len(plan.tracks) - evidence["cache_hits"],
            "lyrics_files": len(list(source.rglob("*.lrc"))), "failed": len(plan.failures),
            "unsupported": len(plan.unsupported_files)})
    except (OSError, ValueError, RuntimeError) as exc:
        _discard(workspace, root)
        if isinstance(exc, MusicImportError):
            raise
        raise MusicImportError("音频分析未能完成，请检查文件是否能正常播放。") from None


def import_folder(source: Path, root: Path, *,
                  progress: Progress = lambda done, total, text: None) -> MusicImport:
    """Analyze original local files in a staging area before replacing the active plan."""
    workspace = _new_workspace(root)
    try:
        artifacts = workspace / "artifacts"
        artifacts.mkdir()
        current = root / "artifacts"
        for name in (*FIXED_ARTIFACTS, "instrument_overrides.json"):
            if (current / name).is_file():
                shutil.copy2(current / name, artifacts / name)
        for name in ("cache", "platform_lyrics"):
            if (current / name).is_dir():
                shutil.copytree(current / name, artifacts / name)
        plan, evidence = _analyze(source, workspace, progress)
        if (current / "collection_plan.json").is_file():
            try:
                previous = load_plan(current / "collection_plan.json")
            except (OSError, ValueError, KeyError, TypeError):
                previous = None
            if previous:
                by_path = {t.source_path: t for t in previous.tracks}
                by_hash = {}
                for track in previous.tracks:
                    by_hash.setdefault(track.source_sha256, []).append(track)
                used = set()
                for track in plan.tracks:
                    match = by_path.get(track.source_path)
                    candidates = by_hash.get(track.source_sha256, [])
                    if match is None and len(candidates) == 1:
                        match = candidates[0]
                    if (match and match.source_sha256 == track.source_sha256 and
                            match.track_id not in used):
                        track.track_id = match.track_id
                        used.add(match.track_id)
                save_plan(plan, artifacts)
        return MusicImport(workspace, plan, {"tracks": len(plan.tracks),
            "cached": evidence["cache_hits"], "measured": len(plan.tracks) - evidence["cache_hits"],
            "lyrics_files": len(list(source.rglob("*.lrc"))), "failed": len(plan.failures),
            "unsupported": len(plan.unsupported_files)})
    except (OSError, ValueError, RuntimeError) as exc:
        _discard(workspace, root)
        raise MusicImportError("文件夹读取或分析失败，请检查路径、格式和访问权限。") from exc


def import_cloud_bundle(bundle: Path, root: Path, *,
                        progress: Progress = lambda done, total, text: None) -> MusicImport:
    """Explicitly activate server-resident music without relocating shared audio."""
    workspace = _new_workspace(root)
    try:
        _verify_manifest(bundle, progress)
        plan = _portable_plan(bundle, workspace, progress)
        report = {"tracks": len(plan.tracks), "cached": len(plan.tracks), "measured": 0,
                  "lyrics_files": len(list(Path(plan.source_root).rglob("*.lrc"))),
                  "failed": len(plan.failures), "unsupported": len(plan.unsupported_files)}
        progress(1, 1, "云端音乐包导入完成")
        return MusicImport(workspace, plan, report)
    except (OSError, ValueError, KeyError, TypeError):
        _discard(workspace, root)
        raise MusicImportError("云端音乐包暂时无法读取，请稍后重试。") from None


def publish_import(result: MusicImport, root: Path):
    """Publish only after validation; preserve prior library data for local recovery."""
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    backup = root / "library_backups" / uuid.uuid4().hex
    names = ("collection_plan.json", *FIXED_ARTIFACTS, "platform_lyrics", "tag_catalog.json",
             "cache", "evidence.json", "music_import_report.json", "instrument_overrides.json")
    moved, published = [], []
    try:
        for name in names:
            old = artifacts / name
            if old.exists():
                backup.mkdir(parents=True, exist_ok=True)
                old.rename(backup / name)
                moved.append(name)
        for name in names:
            new = result.workspace / "artifacts" / name
            if new.exists():
                new.rename(artifacts / name)
                published.append(name)
        (result.workspace / "artifacts" / "music_import_report.json").write_text(
            json.dumps(result.report, ensure_ascii=False, indent=2), encoding="utf-8")
        (result.workspace / "artifacts" / "music_import_report.json").rename(
            artifacts / "music_import_report.json")
        published.append("music_import_report.json")
    except OSError:
        # Roll back every moved file; a failed import must leave the active library intact.
        for name in reversed(published):
            new = artifacts / name
            staged = result.workspace / "artifacts" / name
            new.rename(staged)
        for name in moved:
            old = backup / name
            if old.exists():
                old.rename(artifacts / name)
        raise MusicImportError("无法保存导入结果，已恢复原曲库。") from None


def build_music_package(bundle: Path, output: Path, *, progress: Progress = lambda d, t, s: None):
    """Export the data allowlist only, with a checksum manifest and portable paths."""
    bundle = bundle.resolve()
    raw = _json(bundle / "collection_plan.json")
    names = {"collection_plan.json", *FIXED_ARTIFACTS}
    files = [bundle / name for name in sorted(names) if (bundle / name).is_file()]
    files += sorted(p for p in (bundle / "audio").rglob("*") if p.is_file()
                    and p.suffix.lower() in SUPPORTED_EXTENSIONS | SIDECARS)
    if (bundle / "platform_lyrics").is_dir():
        files += sorted(p for p in (bundle / "platform_lyrics").rglob("*")
                        if p.is_file() and p.suffix.lower() in SIDECARS)
    for track in raw.get("tracks", []):
        relative = safe_relative(track["source_path"])
        if relative.parts[0] != "audio" or not (bundle / relative).is_file():
            raise MusicImportError("请使用音频路径为 audio/… 的便携数据目录打包。")
        if sha256_file(bundle / relative) != track["source_sha256"]:
            raise MusicImportError("音频与分析档案不一致，无法打包。")
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_suffix(".pending")
    manifest = {"format": "musefolders-music-v1", "tracks": len(raw.get("tracks", [])),
                "analysis": "verified-cache", "files": []}
    try:
        with zipfile.ZipFile(pending, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for index, path in enumerate(files, 1):
                progress(index - 1, len(files), "正在打包音频与资料")
                relative = path.relative_to(bundle).as_posix()
                manifest["files"].append({"path": relative, "size": path.stat().st_size,
                                         "sha256": sha256_file(path)})
                archive.write(path, relative)
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    return manifest
