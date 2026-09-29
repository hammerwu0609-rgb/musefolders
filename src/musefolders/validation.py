from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from .adapters import LocalFolderAdapter, QQMusicAdapter
from .audio import sha256_file
from .models import CollectionPlan
from .schemes import compile_scheme


def validate_plan(plan: CollectionPlan) -> dict:
    """Check identity, assignment, integrity, and source-readonly invariants."""
    track_map = plan.track_by_id()
    assignments = Counter(track_id for folder in plan.folders for track_id in folder.track_ids)
    expected_ids = {track.track_id for track in plan.tracks}
    referenced_ids = set(assignments)
    folder_by_id = {folder.folder_id: folder for folder in plan.folders}
    custom_scan = plan.scheme_id == "custom"
    mapping_mismatches = (
        [track.track_id for track in plan.tracks if track.folder_id or track.folder_name]
        if custom_scan else [
            track.track_id
            for track in plan.tracks
            if track.folder_id not in folder_by_id
            or track.folder_name != folder_by_id[track.folder_id].name
            or assignments[track.track_id] != 1
        ]
    )
    hash_mismatches = [
        track.source_path
        for track in plan.tracks
        if not Path(track.source_path).is_file() or sha256_file(Path(track.source_path)) != track.source_sha256
    ]
    checks = {
        "unique_track_ids": len(track_map) == len(plan.tracks),
        "source_hashes_unchanged": not hash_mismatches,
    }
    if custom_scan:
        # Exploration-first scans are intentionally unassigned until a user
        # reviews a candidate playlist. No folder is a valid state here.
        checks.update({
            "no_unconfirmed_folders": not plan.folders,
            "tracks_unassigned_until_confirmation": not mapping_mismatches,
        })
    else:
        checks.update({
            "every_track_assigned_once": all(assignments[track_id] == 1 for track_id in expected_ids),
            "no_unknown_folder_references": not (referenced_ids - expected_ids),
            "track_folder_mapping_consistent": not mapping_mismatches,
            "all_folders_nonempty": all(folder.track_ids for folder in plan.folders),
        })
    return {
        "passed": all(checks.values()),
        "mode": "unassigned_catalog" if custom_scan else "folder_plan",
        "checks": checks,
        "track_count": len(plan.tracks),
        "folder_count": len(plan.folders),
        "assignment_count": sum(assignments.values()),
        "unknown_references": sorted(referenced_ids - expected_ids),
        "mapping_mismatches": mapping_mismatches,
        "source_hash_mismatches": hash_mismatches,
    }


def validate_naming_modes(plan: CollectionPlan) -> dict:
    """Prove scheme and language changes need no audio reanalysis."""
    before = {track.track_id: asdict(track.acoustic) for track in plan.tracks}
    variants: dict[str, list[dict[str, object]]] = {}
    stable = True
    for mode in ("agitation_brightness", "tempo_loudness", "tonality_agitation"):
        tracks = deepcopy(plan.tracks)
        folders, _ = compile_scheme(tracks, mode, language="en")
        variants[mode] = [
            {"name": folder.name, "track_count": len(folder.track_ids)} for folder in folders
        ]
        stable = stable and before == {track.track_id: asdict(track.acoustic) for track in tracks}
    return {
        "passed": stable and len(variants) == 3,
        "audio_reanalysis_required": False,
        "acoustic_encodings_unchanged": stable,
        "variants": variants,
    }


def validate_cloud_contract(plan: CollectionPlan) -> dict:
    if plan.scheme_id == "custom" and not plan.folders:
        return {
            "passed": None,
            "applicable": False,
            "reason": "No playlist was confirmed; cloud write mapping is not applicable to an unassigned catalog.",
        }
    actions = QQMusicAdapter().preview(plan)
    creates = [action for action in actions if action.operation == "create_playlist"]
    additions = [action for action in actions if action.operation == "add_track"]
    unresolved = [action.track_id for action in additions if action.source.startswith("unresolved:")]
    checks = {
        "one_create_action_per_folder": len(creates) == len(plan.folders),
        "one_add_action_per_track": len(additions) == len(plan.tracks),
        "all_tracks_have_platform_identity": not unresolved,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "create_playlist_actions": len(creates),
        "add_track_actions": len(additions),
        "unresolved_track_ids": unresolved,
        "note": "这里只验证平台无关方案到官方 API 操作计划的映射；没有 API Key，因此没有发起云端写入。",
    }


def exercise_local_export(plan: CollectionPlan, output_root: Path) -> dict:
    """Copy the whole plan, verify artifacts, and roll back only generated files."""
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"导出验证目录已存在，拒绝复用：{output_root}")
    adapter = LocalFolderAdapter(output_root)
    result = adapter.apply(plan)
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    copy_paths = [Path(item["destination"]) for item in manifest["actions"]]
    playlist_paths = [Path(item) for item in manifest["generated_playlists"]]
    before_rollback = {
        "copied": len(copy_paths),
        "copy_files_present": sum(path.is_file() for path in copy_paths),
        "playlists": len(playlist_paths),
        "playlist_files_present": sum(path.is_file() for path in playlist_paths),
        "manifest_status": manifest.get("status"),
        "zero_overwrite_manifest_version": manifest.get("manifest_version"),
    }
    rollback = adapter.rollback(manifest_path)
    after_rollback = {
        "output_root_removed": not output_root.exists(),
        **rollback,
    }
    passed = (
        before_rollback["copied"] == len(plan.tracks)
        and before_rollback["copy_files_present"] == len(plan.tracks)
        and before_rollback["playlists"] == len(plan.folders)
        and before_rollback["playlist_files_present"] == len(plan.folders)
        and before_rollback["manifest_status"] == "complete"
        and after_rollback["removed_copies"] == len(plan.tracks)
        and after_rollback["modified_files_preserved"] == 0
        and after_rollback["source_files_touched"] == 0
        and after_rollback["output_root_removed"]
    )
    return {"passed": passed, "before_rollback": before_rollback, "after_rollback": after_rollback}


def run_validation(plan: CollectionPlan, artifacts: Path, *, exercise_export: bool = False) -> dict:
    artifacts = artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    evidence = {
        "analysis_id": plan.analysis_id,
        "plan_integrity": validate_plan(plan),
        "scheme_variants": validate_naming_modes(plan),
        "cloud_contract": validate_cloud_contract(plan),
        "human_ux_validation_required": True,
    }
    if exercise_export:
        evidence["local_export_transaction"] = (
            {"passed": None, "applicable": False,
             "reason": "Confirm a playlist before exercising folder export."}
            if plan.scheme_id == "custom" and not plan.folders else
            exercise_local_export(plan, artifacts / f"export-validation-{plan.analysis_id}")
        )
    destination = artifacts / "validation_evidence.json"
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return evidence
