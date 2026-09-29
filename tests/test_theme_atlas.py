from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from musefolders.lyrics_map import LyricsMapResult, build_lyrics_map, rank_theme_neighbors
from musefolders.theme_atlas import THEME_VIEW_BOX, build_theme_atlas


class FakeEmbedder:
    model_version = "theme-test-v1"

    def encode(self, texts):
        # Fixed dimensions but distinct values: classification of title-only
        # tracks is based on *explicit* cues, not accidental fake cosine scores.
        return [[float(len(text) % 7 + 1), float(sum(map(ord, text)) % 11 + 1), 1.0] for text in texts]


def _track(root: Path, title: str, track_id: str):
    path = root / f"{track_id}.mp3"
    root.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unchanged")
    return SimpleNamespace(
        track_id=track_id, source_path=str(path),
        metadata=SimpleNamespace(title=title),
    )


def _area(outline):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in
                   zip(outline, outline[1:] + outline[:1]))) / 2


def _inside(outline, x, y):
    inside = False
    for (x1, y1), (x2, y2) in zip(outline, outline[1:] + outline[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def test_title_only_cues_ambiguity_and_manual_override(tmp_path: Path) -> None:
    tracks = [
        _track(tmp_path / "music", "写给妈妈的歌", "mother"),
        _track(tmp_path / "music", "Love in Winter", "love"),
        _track(tmp_path / "music", "爱情与亲情", "mixed"),
        _track(tmp_path / "music", "Home", "home"),
        _track(tmp_path / "music", "雨", "rain"),
        _track(tmp_path / "music", "Home!", "home_punctuated"),
        _track(tmp_path / "music", "Song 07", "generic_filename"),
        _track(tmp_path / "music", "Spring Sunrise", "uncued"),
    ]
    result = build_lyrics_map(
        tracks, tmp_path / "artifacts", embedder=FakeEmbedder(),
        manual_themes={"home": "family", "love": "unknown"},
    )
    assert all(status == "missing" for status in result.statuses.values())
    assert result.primary_themes == {
        "mother": "family", "love": "unknown", "mixed": "unknown",
        "home": "family", "rain": "unknown", "home_punctuated": "unknown",
        "generic_filename": "unknown", "uncued": "unknown",
    }
    assert result.evidence_sources == {
        "mother": "title_only", "love": "manual", "mixed": "title_only",
        "home": "manual", "rain": "unknown", "home_punctuated": "unknown",
        "generic_filename": "unknown", "uncued": "title_only",
    }
    assert set(result.secondary_themes["mixed"]) == {"love", "family"}
    assert "rain" not in result.embeddings
    assert "uncued" in result.embeddings  # useful for similarity, not asserted as a topic
    assert result.languages == {track.track_id: "unknown" for track in tracks}
    cache_files = list((tmp_path / "artifacts" / "lyrics_cache" / "embeddings").glob("*.json"))
    assert cache_files
    assert all("写给妈妈" not in path.read_text(encoding="utf-8") for path in cache_files)


def test_partial_lyrics_weight_and_language_remains_lyric_only(tmp_path: Path) -> None:
    class OrthogonalEmbedder:
        model_version = "orthogonal-v1"

        def encode(self, texts):
            return [[1.0, 0.0] if text == "TITLE_ONLY" else [0.0, 1.0] for text in texts]

    track = _track(tmp_path / "music", "TITLE_ONLY", "one")
    (tmp_path / "music" / "one.lrc").write_text(
        "[00:01.00]妈妈在远方等我回家，春天来时再一起看花\n", encoding="utf-8",
    )
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=OrthogonalEmbedder())
    assert result.statuses["one"] == "short"
    assert result.evidence_sources["one"] == "partial_lyrics"
    assert result.sources["one"] == "adjacent"
    np.testing.assert_allclose(result.embeddings["one"], np.array([0.6, 0.4]) / math.hypot(0.6, 0.4))
    assert result.languages["one"] == "unknown"
    assert result.language_statuses["one"] == "unknown"


def test_generic_title_does_not_dilute_valid_lyric_meaning(tmp_path: Path) -> None:
    class OrthogonalEmbedder:
        model_version = "generic-title-v1"

        def encode(self, texts):
            return [[1.0, 0.0] if text == "song" else [0.0, 1.0] for text in texts]

    track = _track(tmp_path / "music", "song", "one")
    (tmp_path / "music" / "one.txt").write_text(
        "妈妈在远方等我回家，春天来时再一起看花。" * 4, encoding="utf-8",
    )
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=OrthogonalEmbedder())
    assert result.statuses["one"] == "valid"
    np.testing.assert_allclose(result.embeddings["one"], [0.0, 1.0])


def test_lyrics_to_title_fallback_reuses_audio_but_not_text_embedding(tmp_path: Path) -> None:
    track = _track(tmp_path / "music", "我的朋友", "one")
    artifacts = tmp_path / "artifacts"
    title_only = build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    assert title_only.primary_themes["one"] == "friendship"
    assert title_only.evidence_sources["one"] == "title_only"
    lyric_path = tmp_path / "music" / "one.lrc"
    lyric_path.write_text("[00:01.00]" + "这里有一段讲述朋友们在远方再次相逢的故事。" * 3,
                          encoding="utf-8")
    with_lyrics = build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    assert with_lyrics.statuses["one"] == "valid"
    assert with_lyrics.evidence_sources["one"] == "lyrics"
    assert with_lyrics.cache_hits == 0
    assert title_only.embeddings["one"] != with_lyrics.embeddings["one"]
    assert not (artifacts / "cache").exists()


def test_manual_theme_without_any_text_or_model(tmp_path: Path) -> None:
    track = _track(tmp_path / "music", "song", "one")
    result = build_lyrics_map(
        [track], tmp_path / "artifacts", embedder=FakeEmbedder(),
        manual_themes={"one": "nature"},
    )
    assert result.embeddings == {}
    assert result.primary_themes["one"] == "nature"
    assert result.evidence_sources["one"] == "manual"
    assert build_theme_atlas(result.primary_themes).regions["nature"].track_ids == ("one",)


def test_island_layout_is_stable_semantic_and_nonoverlapping() -> None:
    assignments = {f"love-{index}": "love" for index in range(9)}
    assignments.update({"f": "family", "p": "friendship", "n": "nature", "u": "unknown"})
    atlas = build_theme_atlas(assignments)
    assert atlas.view_box == THEME_VIEW_BOX
    assert atlas.regions["love"].count == 9
    assert atlas.regions["unknown"].count == 1
    assert _area(atlas.regions["love"].outline) > _area(atlas.regions["family"].outline)
    centers = {key: region.center for key, region in atlas.regions.items()}
    assert math.dist(centers["love"], centers["family"]) < math.dist(centers["love"], centers["nature"])
    assert math.dist(centers["family"], centers["friendship"]) < math.dist(centers["family"], centers["nature"])
    # The new landmass is tessellated: neighboring polygons intentionally share
    # edges, unlike the old separate circles. No sampled interior may overlap.
    for x in range(10, 990, 13):
        for y in range(10, 670, 13):
            assert sum(_inside(region.outline, x, y) for region in atlas.regions.values()) <= 1
    assert _area(atlas.regions["unknown"].outline) < sum(
        _area(region.outline) for key, region in atlas.regions.items() if key != "unknown")
    larger = build_theme_atlas({**assignments, "another": "nature"})
    assert larger.regions["love"].track_ids == atlas.regions["love"].track_ids
    assert _area(larger.regions["nature"].outline) > _area(atlas.regions["nature"].outline)
    assert build_theme_atlas(assignments) == atlas


def test_theme_neighbors_use_original_embedding_not_island_coordinates() -> None:
    result = LyricsMapResult(embeddings={
        "anchor": [1.0, 0.0], "near": [0.8, 0.6], "far": [0.0, 1.0],
    })
    assert rank_theme_neighbors(result, "anchor") == [("near", 0.8), ("far", 0.0)]
    assert rank_theme_neighbors(result, "absent") == []
