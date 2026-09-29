from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .audio import PROTECTED_EXTENSIONS, SUPPORTED_EXTENSIONS, analyze_track, sha256_file, track_instance_id
from .models import (
    AcousticFeatures,
    CollectionPlan,
    ENGINE_VERSION,
    FolderProposal,
    SCHEMA_VERSION,
    StandardScores,
    TrackEncoding,
    TrackMetadata,
    TAXONOMY_VERSION,
)
from .schemes import compile_scheme
from .instruments import detect_instrument
from .taxonomy import score_tracks


ProgressCallback = Callable[[int, int, str], None]
INSTRUMENT_VALUES = {"voice", "piano", "guitar", "strings", "wind", "percussion", "synthesizer", "unknown"}


def save_instrument_override(track: TrackEncoding, artifacts: Path) -> None:
    """Persist an explicit correction without modifying the source audio file."""
    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / "instrument_overrides.json"
    try:
        overrides = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        overrides = {}
    if track.instrument not in INSTRUMENT_VALUES:
        raise ValueError("Invalid instrument")
    overrides[track.source_sha256] = track.instrument
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def discover_audio(source: Path) -> tuple[list[Path], list[dict[str, str]]]:
    supported: list[Path] = []
    unsupported: list[dict[str, str]] = []
    for path in sorted(source.rglob("*"), key=lambda item: str(item).casefold()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS:
            supported.append(path)
        elif suffix in PROTECTED_EXTENSIONS:
            unsupported.append({"path": str(path.resolve()), "reason": "受保护格式，不尝试解密"})
    return supported, unsupported


def _cache_key(path: Path, engine_version: str = ENGINE_VERSION) -> str:
    stat = path.stat()
    import hashlib
    raw = f"{engine_version}|{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _encoding_from_dict(data: dict, *, refresh_for_analysis: bool = False) -> TrackEncoding:
    track = TrackEncoding(
        track_id=data["track_id"], source_path=data["source_path"], source_size=data["source_size"],
        source_mtime_ns=data["source_mtime_ns"], source_sha256=data["source_sha256"],
        metadata=TrackMetadata(**data["metadata"]), acoustic=AcousticFeatures(**data["acoustic"]),
        source_ctime_ns=data.get("source_ctime_ns", 0),
        instrument=data.get("instrument", "unknown"),
        instrument_score=data.get("instrument_score", 0.0),
        instrument_status=data.get("instrument_status", "unavailable"),
        standard=StandardScores(**data["standard"]) if data.get("standard") else None,
        style_hint=data.get("style_hint", "待判定"), folder_id=data.get("folder_id", ""),
        genre_value=data.get("genre_value", ""), genre_status=data.get("genre_status", "unavailable"),
        genre_source=data.get("genre_source", ""), tags=data.get("tags", {}),
        folder_name=data.get("folder_name", ""), confidence=data.get("confidence", 0.0),
        reasons=data.get("reasons", []), warnings=data.get("warnings", []),
        schema_version=data.get("schema_version", "1.0"), engine_version=data.get("engine_version", "0.1.0"),
        taxonomy_version=data.get("taxonomy_version", TAXONOMY_VERSION),
    )
    if refresh_for_analysis:
        track.track_id = track_instance_id(Path(track.source_path), track.source_sha256)
        track.standard = None
        track.style_hint = "待判定"
        track.genre_value = ""
        track.genre_status = "unavailable"
        track.genre_source = ""
        track.tags = {}
        track.folder_id = ""
        track.folder_name = ""
        track.confidence = 0.0
        track.reasons = []
        track.warnings = []
        track.schema_version = SCHEMA_VERSION
        track.engine_version = ENGINE_VERSION
        track.taxonomy_version = TAXONOMY_VERSION
    return track


def analyze_library(
    source: Path,
    artifacts: Path,
    naming_mode: str = "poetic",
    progress: ProgressCallback | None = None,
    use_cache: bool = True,
    scheme_id: str = "agitation_brightness",
    language: str = "zh",
) -> tuple[CollectionPlan, dict]:
    source = source.resolve()
    artifacts = artifacts.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"音乐目录不存在：{source}")
    if artifacts == source or source in artifacts.parents:
        raise ValueError("分析档案不能写入源曲库；请选择曲库外的目录")
    artifacts.mkdir(parents=True, exist_ok=True)
    cache_dir = artifacts / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    files, unsupported = discover_audio(source)
    if not files:
        raise ValueError("目录中没有可分析的音频文件")

    tracks: list[TrackEncoding] = []
    failures: list[dict[str, str]] = []
    timings: list[float] = []
    cache_hits = 0
    started = time.perf_counter()
    for index, path in enumerate(files, 1):
        if progress:
            progress(index - 1, len(files), path.name)
        cache_file = cache_dir / f"{_cache_key(path)}.json"
        tick = time.perf_counter()
        try:
            track: TrackEncoding | None = None
            if use_cache:
                cache_candidates = [cache_file]
                cache_candidates.extend(cache_dir / f"{_cache_key(path, version)}.json" for version in ("0.4.0", "0.3.0", "0.2.0", "0.1.1", "0.1.0"))
                for candidate in cache_candidates:
                    if not candidate.exists():
                        continue
                    cached_data = json.loads(candidate.read_text(encoding="utf-8"))
                    # v2 brightness needs a measured high-frequency energy
                    # ratio; old feature caches cannot be upgraded by simply
                    # recalculating the taxonomy score.
                    if cached_data.get("acoustic", {}).get("high_frequency_ratio") is None:
                        continue
                    cached = _encoding_from_dict(
                        cached_data, refresh_for_analysis=True,
                    )
                    if sha256_file(path) != cached.source_sha256:
                        continue
                    track = cached
                    track.source_ctime_ns = path.stat().st_ctime_ns
                    needs_instrument = track.instrument_status == "unavailable"
                    if needs_instrument:
                        instrument = detect_instrument(path)
                        track.instrument, track.instrument_score, track.instrument_status = instrument
                    cache_hits += 1
                    if candidate != cache_file or needs_instrument:
                        cache_file.write_text(json.dumps(track.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                    break
            if track is None:
                track = analyze_track(path)
                instrument = detect_instrument(path)
                track.instrument, track.instrument_score, track.instrument_status = instrument
                cache_file.write_text(json.dumps(track.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            tracks.append(track)
            timings.append(time.perf_counter() - tick)
        except Exception as exc:
            failures.append({"path": str(path.resolve()), "reason": f"{type(exc).__name__}: {exc}"})
    if progress:
        progress(len(files), len(files), "完成")
    if not tracks:
        raise RuntimeError("所有音频都分析失败，请查看失败列表")

    override_file = artifacts / "instrument_overrides.json"
    try:
        overrides = json.loads(override_file.read_text(encoding="utf-8")) if override_file.exists() else {}
    except (OSError, ValueError):
        overrides = {}
    for track in tracks:
        value = overrides.get(track.source_sha256)
        if value in INSTRUMENT_VALUES:
            track.instrument = value
            track.instrument_score = 0.0
            track.instrument_status = "manual"

    score_tracks(tracks)
    # A custom scan only encodes songs. No classification plan exists until the
    # user checks dimensions and confirms them in the interface.
    if scheme_id == "custom":
        folders, tag_keys = [], []
    else:
        folders, tag_keys = compile_scheme(tracks, scheme_id, naming_mode=naming_mode, language=language)
    analysis_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    plan = CollectionPlan(
        analysis_id=analysis_id,
        source_root=str(source),
        naming_mode=naming_mode,
        folders=folders,
        tracks=tracks,
        scheme_id=scheme_id,
        tag_keys=tag_keys,
        language=language,
        unsupported_files=unsupported,
        failures=failures,
        taxonomy_version=TAXONOMY_VERSION,
    )
    analysis_elapsed = time.perf_counter() - started
    verification_started = time.perf_counter()
    source_hash_mismatches: list[str] = []
    for track in tracks:
        if sha256_file(Path(track.source_path)) != track.source_sha256:
            source_hash_mismatches.append(track.source_path)
    verification_elapsed = time.perf_counter() - verification_started
    total_elapsed = time.perf_counter() - started

    evidence = {
        "analysis_id": analysis_id,
        "discovered": len(files),
        "analyzed": len(tracks),
        "failed": len(failures),
        "unsupported": len(unsupported),
        "cache_hits": cache_hits,
        "analysis_elapsed_s": round(analysis_elapsed, 3),
        "verification_elapsed_s": round(verification_elapsed, 3),
        "elapsed_s": round(total_elapsed, 3),
        "median_track_s": round(sorted(timings)[len(timings) // 2], 3) if timings else 0,
        "source_mutations": len(source_hash_mismatches),
        "source_hash_mismatches": source_hash_mismatches,
        "qq_source_ids_preserved": sum(bool(track.metadata.source_track_id) for track in tracks),
    }
    save_plan(plan, artifacts)
    (artifacts / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan, evidence


def save_plan(plan: CollectionPlan, artifacts: Path) -> Path:
    artifacts.mkdir(parents=True, exist_ok=True)
    destination = artifacts / "collection_plan.json"
    destination.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def load_plan(path: Path) -> CollectionPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    tracks = [_encoding_from_dict(item) for item in data["tracks"]]
    folders = [FolderProposal(**item) for item in data["folders"]]
    return CollectionPlan(
        analysis_id=data["analysis_id"], source_root=data["source_root"], naming_mode=data["naming_mode"],
        folders=folders, tracks=tracks, scheme_id=data.get("scheme_id", "agitation_brightness"),
        tag_keys=data.get("tag_keys", ["agitation", "brightness"]), language=data.get("language", "zh"),
        selection_query=data.get("selection_query", {}),
        unsupported_files=data.get("unsupported_files", []),
        failures=data.get("failures", []), schema_version=data.get("schema_version", "1.0"),
        engine_version=data.get("engine_version", "0.1.0"),
        taxonomy_version=data.get("taxonomy_version", TAXONOMY_VERSION),
    )

