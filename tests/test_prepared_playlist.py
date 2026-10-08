import json
from types import SimpleNamespace

import pytest

from musefolders.playlist_draft import (PlaylistDraft, add_group, set_single, remove_entry,
    move_entry, reconcile, save_draft, load_draft, draft_path, delete_song, move_song)
from musefolders.consumer_workspace import parse_command


def plan(root, *, renamed=False):
    tracks = [SimpleNamespace(track_id=("new-" if renamed else "") + tid,
        source_sha256="hash-" + tid, metadata=SimpleNamespace(title=tid.upper(), artist="Artist"),
        source_path=str(root / (tid + ".mp3")), acoustic=SimpleNamespace(duration_s=120))
        for tid in ("a", "b", "c")]
    return SimpleNamespace(source_root=str(root), analysis_id="new" if renamed else "old",
        tracks=tracks, track_by_id=lambda: {t.track_id: t for t in tracks})


def source(label):
    return {"kind": "themes", "key": label, "label": label,
            "description": "歌词主题 · " + label, "criteria": {"theme": label}}


def test_individual_and_overlapping_groups_keep_independent_memberships(tmp_path):
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    assert add_group(draft, p, ["a", "b"], source("爱情"))
    first = draft.entries[0].entry_id
    assert add_group(draft, p, ["b", "c"], source("回忆"))
    assert set_single(draft, p, "b", True)
    assert not set_single(draft, p, "b", True)
    assert len(draft.entries) == 3
    assert reconcile(draft, p)[0] == ["a", "b", "c"]
    set_single(draft, p, "b", False)
    assert len(draft.entries) == 2
    assert [len(e.members) for e in draft.entries] == [2, 2]
    remove_entry(draft, first)
    assert reconcile(draft, p)[0] == ["b", "c"]
    assert draft.entries[0].label == "回忆"


def test_snapshots_deduplicate_groups_and_reconcile_by_fingerprint(tmp_path):
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    add_group(draft, p, ["a", "b"], source("爱情"))
    assert not add_group(draft, p, ["b", "a"], source("爱情"))
    set_single(draft, p, "c", True)
    move_entry(draft, draft.entries[1].entry_id, -1)
    assert reconcile(draft, p)[0] == ["c", "a", "b"]
    save_draft(tmp_path / "artifacts", draft)
    changed = plan(tmp_path, renamed=True)
    changed.tracks.pop()
    loaded = load_draft(tmp_path / "artifacts", changed)
    found, missing = reconcile(loaded, changed)
    assert found == ["new-a", "new-b"]
    assert [m.title for m in missing] == ["C"]
    assert len(loaded.entries[1].members) == 2
    assert loaded.entries[1].source == source("爱情")


def test_v1_migration_preserves_name_order_exclusions_and_archive_identity(tmp_path):
    p = plan(tmp_path)
    path = draft_path(tmp_path / "artifacts", p.source_root)
    path.parent.mkdir(parents=True)
    old = {"version": 1, "source_root": p.source_root, "analysis_id": p.analysis_id,
        "name": "我自己的名字", "items": [
            {"track_id": tid, "content_id": "hash-" + tid, "title": tid.upper(), "origin": "old_map"}
            for tid in ("b", "a")], "excluded": ["hash-a"], "filters": {"theme": "爱情"}}
    path.write_text(json.dumps(old), encoding="utf-8")
    loaded = load_draft(tmp_path / "artifacts", p)
    assert loaded.name == old["name"]
    assert loaded.excluded == old["excluded"]
    assert [e.kind for e in loaded.entries] == ["single", "single"]
    assert reconcile(loaded, p)[0] == ["b", "a"]
    save_draft(tmp_path / "artifacts", loaded)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
    assert load_draft(tmp_path / "artifacts", p).to_dict() == loaded.to_dict()


def test_invalid_entry_and_group_members_are_rejected(tmp_path):
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    with pytest.raises(ValueError):
        add_group(draft, p, ["absent"], source("爱情"))
    with pytest.raises(ValueError):
        set_single(draft, p, "a", "true")
    assert not draft.entries


@pytest.mark.parametrize("text,expected", [
    ("把搜索结果加入我的预备歌单", ("add", "", "")),
    ("从预备歌单移除Caravan", ("remove", "Caravan", "")),
    ("找睡前听的歌，建成「今晚」预备歌单", ("create", "睡前听的歌", "今晚")),
])
def test_new_playlist_vocabulary(text, expected):
    assert parse_command(text) == expected


def test_dispatch_acknowledges_idempotence_and_rolls_back_save_failure(tmp_path, monkeypatch):
    from musefolders import consumer_ui as ui
    p = plan(tmp_path)
    state = SimpleNamespace(simple_draft=PlaylistDraft(p.source_root, p.analysis_id))
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(ui, "active_settings", lambda root: SimpleNamespace(api_key=""))
    action = {"kind": "set_single", "id": "a", "selected": True, "token": 1}
    result = ui.dispatch(action, p, {}, tmp_path, None)
    assert result == {"kind": "set_single", "token": 1, "success": True, "added": True}
    assert not ui.dispatch(action, p, {}, tmp_path, None)["added"]
    before = state.simple_draft.to_dict()
    def fail(artifacts, draft):
        raise OSError("unwritable archive")
    monkeypatch.setattr(ui, "archive_playlist", fail)
    with pytest.raises(OSError):
        ui.dispatch({**action, "id": "b", "token": 2}, p, {}, tmp_path, None)
    assert state.simple_draft.to_dict() == before
    assert load_draft(tmp_path / "artifacts", p).to_dict() == before


def test_export_flattens_sources_once_and_keeps_entry_order(tmp_path, monkeypatch):
    import base64
    from musefolders import consumer_ui as ui
    class State(dict):
        def __getattr__(self, key):
            return self[key]
        def __setattr__(self, key, value):
            self[key] = value
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    add_group(draft, p, ["a", "b"], source("爱情"))
    add_group(draft, p, ["b", "c"], source("回忆"))
    set_single(draft, p, "b", True)
    state = State(simple_draft=draft, simple_demo_mode=True)
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(ui, "active_settings", lambda root: SimpleNamespace(api_key=""))
    ui.dispatch({"kind": "export", "token": 1}, p, {}, tmp_path, None)
    text = base64.b64decode(state.consumer_download["url"].split(",", 1)[1]).decode("utf-8-sig")
    assert text.count("#EXTINF:") == 3
    assert [line for line in text.splitlines() if line.endswith(".mp3")] == ["a.mp3", "b.mp3", "c.mp3"]
    assert "爱情" not in text and "回忆" not in text
    assert str(tmp_path) not in text


def test_global_delete_restore_group_and_per_song_order(tmp_path):
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    add_group(draft, p, ["a", "b"], source("爱情"))
    add_group(draft, p, ["b", "c"], source("回忆"))
    set_single(draft, p, "b", True)
    delete_song(draft, "hash-b")
    assert [item.track_id for item in draft.items if item.content_id not in draft.excluded] == ["a", "c"]
    assert len(draft.entries) == 3
    assert add_group(draft, p, ["a", "b"], source("爱情"))
    assert len(draft.entries) == 3 and not draft.excluded
    move_song(draft, "hash-c", -1)
    assert reconcile(draft, p)[0] == ["a", "c", "b"]
    save_draft(tmp_path / "artifacts", draft)
    assert reconcile(load_draft(tmp_path / "artifacts", p), p)[0] == ["a", "c", "b"]
    assert [m.track_id for m in draft.entries[0].members] == ["a", "b"]


def test_delete_undo_and_source_only_addition_do_not_claim_new_song(tmp_path, monkeypatch):
    from musefolders import consumer_ui as ui
    class State(dict):
        def __getattr__(self, key):
            return self[key]
        def __setattr__(self, key, value):
            self[key] = value
    p = plan(tmp_path)
    draft = PlaylistDraft(p.source_root, p.analysis_id)
    add_group(draft, p, ["a", "b"], source("爱情"))
    state = State(simple_draft=draft)
    monkeypatch.setattr(ui.st, "session_state", state)
    monkeypatch.setattr(ui, "active_settings", lambda root: SimpleNamespace(api_key=""))
    result = ui.dispatch({"kind": "set_single", "id": "b", "selected": True, "token": 1}, p, {}, tmp_path, None)
    assert result["success"] and not result["added"]
    before = state.simple_draft.to_dict()
    ui.dispatch({"kind": "delete_song", "content": "hash-b", "token": 2}, p, {}, tmp_path, None)
    assert state.simple_draft.excluded == ["hash-b"]
    ui.dispatch({"kind": "undo_delete", "token": 3}, p, {}, tmp_path, None)
    assert state.simple_draft.to_dict() == before
    ui.dispatch({"kind": "delete_song", "content": "hash-b", "token": 4}, p, {}, tmp_path, None)
    ui.dispatch({"kind": "move_song", "content": "hash-a", "offset": 1, "token": 5}, p, {}, tmp_path, None)
    ui.dispatch({"kind": "rename", "name": "新名字", "token": 6}, p, {}, tmp_path, None)
    with pytest.raises(ValueError):
        ui.dispatch({"kind": "undo_delete", "token": 7}, p, {}, tmp_path, None)
