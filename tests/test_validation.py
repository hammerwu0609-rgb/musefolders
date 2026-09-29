from __future__ import annotations

import hashlib
from pathlib import Path

from musefolders.models import AcousticFeatures, CollectionPlan, TrackEncoding, TrackMetadata
from musefolders.schemes import compile_scheme
from musefolders.taxonomy import score_tracks
from musefolders.validation import run_validation, validate_cloud_contract, validate_plan


def _track(tmp_path: Path) -> TrackEncoding:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"test audio bytes")
    track = TrackEncoding(
        track_id="song", source_path=str(source), source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata=TrackMetadata("Song", "Artist"),
        acoustic=AcousticFeatures(20, 110, .9, -22, 8, 2000, 4500, .05,
                                  .2, 2, .8, "C", "major", .6, 20, .1),
    )
    score_tracks([track])
    return track


def test_unassigned_exploration_catalog_is_valid_without_folders(tmp_path: Path) -> None:
    track = _track(tmp_path)
    plan = CollectionPlan("id", str(tmp_path), "poetic", [], [track], scheme_id="custom")
    integrity = validate_plan(plan)
    assert integrity["passed"] is True
    assert integrity["mode"] == "unassigned_catalog"
    assert integrity["checks"]["tracks_unassigned_until_confirmation"] is True
    assert integrity["checks"]["source_hashes_unchanged"] is True
    assert validate_cloud_contract(plan)["applicable"] is False

    evidence = run_validation(plan, tmp_path / "artifacts", exercise_export=True)
    assert evidence["plan_integrity"]["passed"] is True
    assert evidence["scheme_variants"]["passed"] is True
    assert evidence["cloud_contract"]["applicable"] is False
    assert evidence["local_export_transaction"]["applicable"] is False
    assert not (tmp_path / "artifacts" / "export-validation-id").exists()


def test_confirmed_folder_plan_still_requires_assignment(tmp_path: Path) -> None:
    track = _track(tmp_path)
    folders, keys = compile_scheme([track], "agitation_brightness")
    plan = CollectionPlan("id", str(tmp_path), "poetic", folders, [track],
                          scheme_id="agitation_brightness", tag_keys=keys)
    assert validate_plan(plan)["passed"] is True
    folders[0].track_ids.clear()
    assert validate_plan(plan)["passed"] is False
