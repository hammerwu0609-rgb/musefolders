from pathlib import Path
import hashlib

import pytest

from musefolders.adapters import LocalFolderAdapter, QQMusicAdapter
from musefolders.models import AcousticFeatures, CollectionPlan, FolderProposal, StandardScores, TrackEncoding, TrackMetadata


def test_adapters_share_stable_collection_plan(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "source.mp3"
    source.write_bytes(b"fake audio for adapter contract")
    track = TrackEncoding(
        track_id="abc", source_path=str(source), source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata=TrackMetadata("Song", "Artist"),
        acoustic=AcousticFeatures(10, 100, .5, -20, 8, 1800, 4000, .05, .4, 2, .6, "C", "major", .5, 10),
        standard=StandardScores(50, "中躁动", 55, 50, 45, 45),
        folder_id="F01", folder_name="沿途晴光", reasons=["test"],
    )
    folder = FolderProposal("F01", "沿途晴光", "沿途晴光", "中躁动", "明亮", "旋律流行", ["abc"], 90, "test")
    plan = CollectionPlan("id", str(source_root), "poetic", [folder], [track])
    local = LocalFolderAdapter(tmp_path / "out")
    qq = QQMusicAdapter()
    assert len(local.preview(plan)) == 1
    qq_actions = qq.preview(plan)
    assert [action.operation for action in qq_actions] == ["create_playlist", "add_track"]
    result = local.apply(plan)
    assert result["copied"] == 1
    assert Path(result["manifest"]).exists()
    rollback = local.rollback(Path(result["manifest"]))
    assert rollback == {"removed_copies": 1, "modified_files_preserved": 0, "source_files_touched": 0}
    assert source.exists()
    assert not (tmp_path / "out").exists()
    folder.track_ids.clear()
    with pytest.raises(ValueError, match="分类方案不完整"):
        local.apply(plan)
    assert not (tmp_path / "out").exists()


def test_local_adapter_rejects_changed_source_before_copy(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "source.mp3"
    source.write_bytes(b"first version")
    track = TrackEncoding(
        track_id="abc", source_path=str(source), source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata=TrackMetadata("Song", "Artist"),
        acoustic=AcousticFeatures(10, 100, .5, -20, 8, 1800, 4000, .05, .4, 2, .6, "C", "major", .5, 10),
        standard=StandardScores(50, "中躁动", 55, 50, 45, 45),
        folder_id="F01", folder_name="沿途晴光", reasons=["test"],
    )
    folder = FolderProposal("F01", "沿途晴光", "沿途晴光", "中躁动", "明亮", "旋律流行", ["abc"], 90, "test")
    plan = CollectionPlan("id", str(source_root), "poetic", [folder], [track])
    source.write_bytes(b"changed after analysis")

    with pytest.raises(ValueError, match="分析后发生变化"):
        LocalFolderAdapter(tmp_path / "out").apply(plan)
    assert not (tmp_path / "out").exists()


def test_sanitized_folder_names_remain_distinct(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    sources = []
    tracks = []
    folders = []
    for index, name in enumerate(("A:B", "A?B"), 1):
        source = source_root / f"source{index}.mp3"
        source.write_bytes(f"audio-{index}".encode())
        sources.append(source)
        track_id = f"t{index}"
        tracks.append(TrackEncoding(
            track_id=track_id, source_path=str(source), source_size=source.stat().st_size,
            source_mtime_ns=source.stat().st_mtime_ns,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            metadata=TrackMetadata(f"Song {index}", "Artist"),
            acoustic=AcousticFeatures(10, 100, .5, -20, 8, 1800, 4000, .05, .4, 2, .6, "C", "major", .5, 10),
            standard=StandardScores(50, "中躁动", 55, 50, 45, 45),
            folder_id=f"F0{index}", folder_name=name, reasons=["test"],
        ))
        folders.append(FolderProposal(f"F0{index}", name, name, "中躁动", "明亮", "旋律流行", [track_id], 90, "test"))
    plan = CollectionPlan("id", str(source_root), "poetic", folders, tracks)

    actions = LocalFolderAdapter(tmp_path / "out").preview(plan)
    assert len({Path(action.destination).parent for action in actions}) == 2


def test_rollback_preserves_user_modified_copy(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "source.mp3"
    source.write_bytes(b"original audio")
    track = TrackEncoding(
        track_id="abc", source_path=str(source), source_size=source.stat().st_size,
        source_mtime_ns=source.stat().st_mtime_ns,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        metadata=TrackMetadata("Song", "Artist"),
        acoustic=AcousticFeatures(10, 100, .5, -20, 8, 1800, 4000, .05, .4, 2, .6, "C", "major", .5, 10),
        standard=StandardScores(50, "中躁动", 55, 50, 45, 45),
        folder_id="F01", folder_name="沿途晴光", reasons=["test"],
    )
    folder = FolderProposal("F01", "沿途晴光", "沿途晴光", "中躁动", "明亮", "旋律流行", ["abc"], 90, "test")
    plan = CollectionPlan("id", str(source_root), "poetic", [folder], [track])
    adapter = LocalFolderAdapter(tmp_path / "out")
    result = adapter.apply(plan)
    copied = next((tmp_path / "out").rglob("*.mp3"))
    copied.write_bytes(b"user edited this copy")

    rollback = adapter.rollback(Path(result["manifest"]))
    assert rollback["removed_copies"] == 0
    assert rollback["modified_files_preserved"] == 1
    assert copied.read_bytes() == b"user edited this copy"
    assert source.read_bytes() == b"original audio"

