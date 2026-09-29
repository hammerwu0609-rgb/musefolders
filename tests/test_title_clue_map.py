from __future__ import annotations

from types import SimpleNamespace

from musefolders.lyrics_map import build_title_clue_map
from musefolders.theme_atlas import build_theme_atlas


def _track(track_id: str, title: str):
    return SimpleNamespace(
        track_id=track_id,
        metadata=SimpleNamespace(title=title),
        source_path=f"nonexistent/{track_id}.mp3",
    )


def test_no_model_preview_assigns_only_explicit_multilingual_title_cues() -> None:
    tracks = [
        _track("family", "父と母"),
        _track("friend", "Friendships"),
        _track("memory", "REMEMBER"),
        _track("journey", "路途"),
        _track("ambiguous", "爱情与亲情"),
        _track("generic", "Home"),
        _track("poetic", "蓝色花朵"),
    ]
    result = build_title_clue_map(tracks)
    assert result.primary_themes == {
        "family": "family", "friend": "friendship", "memory": "memory",
        "journey": "journey", "ambiguous": "unknown", "generic": "unknown",
        "poetic": "unknown",
    }
    assert result.secondary_themes["ambiguous"] == ("love", "family")
    assert result.evidence_sources["family"] == "title_clue"
    assert result.embeddings == result.theme_scores == result.points == {}
    atlas = build_theme_atlas(result.primary_themes)
    assert sum(region.count for region in atlas.regions.values()) == len(tracks)


def test_no_model_preview_preserves_explicit_manual_correction() -> None:
    tracks = [_track("one", "Love"), _track("two", "Home")]
    result = build_title_clue_map(tracks, manual_themes={"one": "unknown", "two": "family"})
    assert result.primary_themes == {"one": "unknown", "two": "family"}
    assert result.evidence_sources == {"one": "manual", "two": "manual"}
