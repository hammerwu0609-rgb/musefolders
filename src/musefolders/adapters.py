from __future__ import annotations

import json
import re
import shutil
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

from .audio import sha256_file
from .models import CollectionPlan


@dataclass(slots=True)
class OutputAction:
    track_id: str
    source: str
    destination: str
    folder_id: str
    operation: str = "copy"


class CollectionOutputAdapter(ABC):
    """Stable boundary for local folders, Navidrome, or a future QQ Music API."""

    @abstractmethod
    def preview(self, plan: CollectionPlan) -> list[OutputAction]:
        raise NotImplementedError

    @abstractmethod
    def apply(self, plan: CollectionPlan) -> dict:
        raise NotImplementedError


def _safe_component(name: str) -> str:
    clean = unicodedata.normalize("NFC", name)
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean).strip().rstrip(". ")
    clean = clean[:80].rstrip(". ") or "未命名文件夹"
    stem = clean.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    return f"_{clean}" if stem in reserved else clean


class LocalFolderAdapter(CollectionOutputAdapter):
    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()

    def _validate_destination(self, plan: CollectionPlan) -> None:
        source_root = Path(plan.source_root).resolve()
        if self.output_root.parent == self.output_root:
            raise ValueError("输出目录不能是磁盘根目录")
        if (
            self.output_root == source_root
            or source_root in self.output_root.parents
            or self.output_root in source_root.parents
        ):
            raise ValueError("输出目录不能与源曲库互为上下级目录")
        if self.output_root.exists() and not self.output_root.is_dir():
            raise ValueError("输出路径已经存在且不是文件夹")

    def _folder_paths(self, plan: CollectionPlan) -> dict[str, Path]:
        """Give every logical folder a distinct Windows-safe path."""
        paths: dict[str, Path] = {}
        reserved: set[str] = set()
        for folder in plan.folders:
            base = _safe_component(folder.name)
            candidate = self.output_root / base
            counter = 2
            while str(candidate).casefold() in reserved:
                candidate = self.output_root / f"{base} ({counter})"
                counter += 1
            reserved.add(str(candidate).casefold())
            paths[folder.folder_id] = candidate
        return paths

    @staticmethod
    def _unique_file(path: Path, reserved: set[str]) -> Path:
        candidate = path
        counter = 2
        key = str(candidate).casefold()
        while key in reserved or candidate.exists():
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            key = str(candidate).casefold()
            counter += 1
        reserved.add(key)
        return candidate

    def _validate_sources(self, plan: CollectionPlan, actions: list[OutputAction]) -> None:
        """Fail before copying if a plan is stale, duplicated, or points outside its library."""
        source_root = Path(plan.source_root).resolve()
        tracks = plan.track_by_id()
        seen: set[str] = set()
        for action in actions:
            if action.track_id in seen:
                raise ValueError(f"同一曲目被分配到多个文件夹：{action.track_id}")
            seen.add(action.track_id)
            track = tracks[action.track_id]
            source = Path(action.source).resolve()
            if source_root not in source.parents or not source.is_file():
                raise ValueError(f"源文件不在已选曲库内或已经不存在：{source}")
            if sha256_file(source) != track.source_sha256:
                raise ValueError(f"源文件在分析后发生变化，请重新分析：{source.name}")
        if seen != set(tracks):
            raise ValueError("分类方案不完整：并非每首曲目都恰好分配到一个文件夹")

    @staticmethod
    def _write_manifest(path: Path, manifest: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def preview(self, plan: CollectionPlan) -> list[OutputAction]:
        self._validate_destination(plan)
        tracks = plan.track_by_id()
        folder_paths = self._folder_paths(plan)
        actions: list[OutputAction] = []
        reserved: set[str] = set()
        for folder in plan.folders:
            folder_path = folder_paths[folder.folder_id]
            for track_id in folder.track_ids:
                if track_id not in tracks:
                    raise ValueError(f"文件夹引用了不存在的曲目：{track_id}")
                track = tracks[track_id]
                source = Path(track.source_path)
                candidate = self._unique_file(folder_path / source.name, reserved)
                actions.append(OutputAction(track_id, str(source), str(candidate), folder.folder_id))
        return actions

    def apply(self, plan: CollectionPlan) -> dict:
        actions = self.preview(plan)
        self._validate_sources(plan, actions)
        output_root_created = not self.output_root.exists()
        self.output_root.mkdir(parents=True, exist_ok=True)
        folder_paths = self._folder_paths(plan)
        source_hashes_before = {item.track_id: plan.track_by_id()[item.track_id].source_sha256 for item in actions}
        playlists: dict[str, list[str]] = {}
        manifest_path = self._unique_file(self.output_root / f"整理清单-{_safe_component(plan.analysis_id)}.json", set())
        manifest = {
            "manifest_version": "1.1",
            "analysis_id": plan.analysis_id,
            "selection_query": plan.selection_query,
            "operation": "copy_only",
            "status": "in_progress",
            "source_root": plan.source_root,
            "output_root": str(self.output_root),
            "actions": [asdict(item) for item in actions],
            "generated_playlists": [],
            "generated_directories": [],
            "generated_hashes": {},
            "created_output_root": output_root_created,
            "source_hashes_before": source_hashes_before,
        }
        self._write_manifest(manifest_path, manifest)
        created: list[Path] = []
        created_directories: list[Path] = []
        try:
            for action in actions:
                source = Path(action.source)
                destination = Path(action.destination)
                if not destination.parent.exists():
                    created_directories.append(destination.parent)
                    manifest["generated_directories"].append(str(destination.parent))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
                    shutil.copyfileobj(source_handle, destination_handle)
                shutil.copystat(source, destination)
                created.append(destination)
                manifest["generated_hashes"][str(destination.resolve())] = source_hashes_before[action.track_id]
                playlists.setdefault(action.folder_id, []).append(destination.name)

            playlist_reserved: set[str] = set()
            for folder in plan.folders:
                entries = playlists.get(folder.folder_id, [])
                if not entries:
                    continue
                playlist_name = "playlist.m3u8" if plan.language == "en" else "歌单.m3u8"
                playlist_path = self._unique_file(folder_paths[folder.folder_id] / playlist_name, playlist_reserved)
                content = "#EXTM3U\n" + "\n".join(entries) + "\n"
                playlist_path.write_text(content, encoding="utf-8-sig")
                created.append(playlist_path)
                manifest["generated_playlists"].append(str(playlist_path))
                manifest["generated_hashes"][str(playlist_path.resolve())] = sha256_file(playlist_path)
            manifest["status"] = "complete"
            self._write_manifest(manifest_path, manifest)
        except Exception:
            for path in reversed(created):
                if path.is_file():
                    path.unlink()
            for path in sorted(set(created_directories), key=lambda item: len(item.parts), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            manifest["status"] = "failed_and_rolled_back"
            self._write_manifest(manifest_path, manifest)
            raise
        return {"copied": len(actions), "manifest": str(manifest_path), "output_root": str(self.output_root)}

    def rollback(self, manifest_path: Path) -> dict:
        """Delete only files recorded in one generated manifest; never touch sources."""
        manifest_path = manifest_path.resolve()
        if not manifest_path.is_file() or self.output_root not in manifest_path.parents:
            raise ValueError("撤销清单必须位于当前输出目录内")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if Path(manifest.get("output_root", "")).resolve() != self.output_root:
            raise ValueError("清单与当前输出目录不匹配")
        removed = 0
        preserved = 0
        generated_hashes = manifest.get("generated_hashes", {})
        generated = [Path(item["destination"]) for item in manifest.get("actions", [])]
        generated.extend(Path(item) for item in manifest.get("generated_playlists", []))
        for original in generated:
            destination = original.resolve()
            if self.output_root not in destination.parents or not destination.is_file():
                continue
            expected_hash = generated_hashes.get(str(destination))
            if not expected_hash or sha256_file(destination) != expected_hash:
                preserved += 1
                continue
            destination.unlink()
            if destination.suffix.lower() != ".m3u8":
                removed += 1
        generated_directories = [Path(item).resolve() for item in manifest.get("generated_directories", [])]
        for path in sorted(generated_directories, key=lambda item: len(item.parts), reverse=True):
            if self.output_root not in path.parents:
                continue
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        if manifest_path.exists():
            manifest_path.unlink()
        if manifest.get("created_output_root") and self.output_root.is_dir() and not any(self.output_root.iterdir()):
            self.output_root.rmdir()
        return {"removed_copies": removed, "modified_files_preserved": preserved, "source_files_touched": 0}


class QQMusicAdapter(CollectionOutputAdapter):
    """Future adapter contract; intentionally contains no unofficial API calls."""

    required_capabilities = ("list_favorites", "create_playlist", "add_tracks", "remove_tracks")

    def __init__(self, official_client: object | None = None):
        self.official_client = official_client

    def preview(self, plan: CollectionPlan) -> list[OutputAction]:
        tracks = plan.track_by_id()
        actions: list[OutputAction] = []
        for folder in plan.folders:
            playlist_uri = f"qqmusic://playlist/pending/{folder.folder_id}"
            actions.append(OutputAction("", "", playlist_uri, folder.folder_id, "create_playlist"))
            for track_id in folder.track_ids:
                track = tracks[track_id]
                source_id = track.metadata.source_track_id or f"unresolved:{track.track_id}"
                actions.append(OutputAction(track.track_id, source_id, playlist_uri, folder.folder_id, "add_track"))
        return actions

    def apply(self, plan: CollectionPlan) -> dict:
        if self.official_client is None:
            raise RuntimeError("尚未配置官方 QQ 音乐 API 客户端；分类计划本身已可直接复用")
        raise NotImplementedError("取得官方 API 后，在此实现四项能力，不修改编码与分类引擎")

