from __future__ import annotations

from types import SimpleNamespace

from musefolders.playlist_draft import (PlaylistDraft, apply_selection, load_draft,
                                        move_item, reconcile, save_draft)


def _plan(source, analysis, tracks):
    return SimpleNamespace(source_root=str(source), analysis_id=analysis,
                           tracks=tracks, track_by_id=lambda: {t.track_id: t for t in tracks})


def _track(track_id, content, title="Song"):
    return SimpleNamespace(track_id=track_id, source_sha256=content,
                           metadata=SimpleNamespace(title=title))


def test_shared_draft_modes_persistence_and_fingerprint_reconciliation(tmp_path):
    first = _plan(tmp_path / "music", "scan-1", [
        _track("a", "hash-a", "A"), _track("b", "hash-b", "B"),
        _track("copy-a", "hash-a", "Duplicate A"),
    ])
    draft = PlaylistDraft(first.source_root, first.analysis_id)
    apply_selection(draft, first, ["a", "copy-a", "b"], "add", "sound_map")
    assert [item.track_id for item in draft.items] == ["a", "b"]
    move_item(draft, "hash-b", -1)
    assert [item.track_id for item in draft.items] == ["b", "a"]
    apply_selection(draft, first, ["a"], "intersect", "catalog_filter")
    assert [item.track_id for item in draft.items] == ["a"]
    draft.excluded = ["hash-a"]
    save_draft(tmp_path / "artifacts", draft)
    loaded = load_draft(tmp_path / "artifacts", first)
    assert loaded.excluded == ["hash-a"]
    second = _plan(first.source_root, "scan-2", [_track("renamed-a", "hash-a")])
    assert reconcile(loaded, second) == (["renamed-a"], [])
    third = _plan(first.source_root, "scan-3", [_track("a", "different-audio")])
    assert reconcile(loaded, third)[0] == []
    assert reconcile(loaded, third)[1][0].title == "A"


def test_replace_clears_exclusions_and_add_reenables_selected_song(tmp_path):
    plan = _plan(tmp_path / "music", "scan", [_track("a", "a"), _track("b", "b")])
    draft = PlaylistDraft(plan.source_root, plan.analysis_id)
    apply_selection(draft, plan, ["a", "b"], "replace", "map")
    draft.excluded = ["a"]
    apply_selection(draft, plan, ["a"], "add", "map")
    assert draft.excluded == []
    apply_selection(draft, plan, ["b"], "replace", "catalog")
    assert [item.content_id for item in draft.items] == ["b"]
