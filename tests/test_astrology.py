from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from musefolders.astrology import (
    _TEMPLATES, _safe_title, ELEMENT_LABELS, ZODIAC_LABELS, build_zodiac,
    make_zodiac_share_card, zodiac_element,
)
from musefolders.sonic_map import MapPoint, SonicMap


def _sound(points: list[tuple[str, float, float]], *, mode: str = "musicnn") -> SonicMap:
    return SonicMap(
        mode=mode, projection="semantic-hybrid-umap",
        points=tuple(MapPoint(track_id, x, y) for track_id, x, y in points),
        vectors={},
    )


def _cloud(count: int) -> list[tuple[str, float, float]]:
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False)
    return [(f"song-{i}", float(50 + 28 * np.cos(angle)), float(50 + 17 * np.sin(angle)))
            for i, angle in enumerate(angles)]


def test_seed_boundary_and_duplicate_song_ids() -> None:
    eleven = _cloud(11)
    seed = build_zodiac(_sound([*eleven, eleven[0]]), override_sign="cancer")
    assert seed.status == "seed"
    assert seed.unique_track_count == 11
    assert seed.sign is None and seed.element is None
    assert not seed.overlay_nodes and not seed.overlay_edges
    assert not seed.is_override

    matched = build_zodiac(_sound(_cloud(12)))
    assert matched.status == "matched"
    assert matched.unique_track_count == 12
    assert matched.sign in ZODIAC_LABELS["zh"]
    assert matched.element == zodiac_element(matched.sign)
    assert matched.overlay_nodes and matched.overlay_edges


def test_copied_audio_with_different_ids_counts_once() -> None:
    sound = _sound(_cloud(12))
    tracks = [
        SimpleNamespace(track_id=f"song-{i}", source_sha256=f"audio-{min(i, 10)}")
        for i in range(12)
    ]
    result = build_zodiac(sound, tracks)
    assert result.status == "seed"
    assert result.unique_track_count == 11


def test_all_positions_are_used_and_similarity_transform_is_invariant() -> None:
    # An exact symbolic outline is the most favorable possible full-cloud case.
    # Rotate, scale, and translate *every* sampled point; the chosen sign holds.
    sample = _TEMPLATES["libra"].samples
    center = sample.mean(axis=0)
    normalized = sample - center
    angle = np.deg2rad(40)
    rotation = np.asarray(((np.cos(angle), -np.sin(angle)),
                           (np.sin(angle), np.cos(angle))))
    first = _sound([(f"t-{i}", float(x), float(y))
                    for i, (x, y) in enumerate(normalized * 15 + [50, 50])])
    second = _sound([(f"t-{i}", float(x), float(y))
                     for i, (x, y) in enumerate((normalized @ rotation.T) * 19 + [42, 57])])
    before_points = first.points
    one = build_zodiac(first)
    two = build_zodiac(second)

    assert one.sign == "libra" and two.sign == "libra"
    assert one.match_score == pytest.approx(0.0, abs=1e-9)
    assert two.match_score == pytest.approx(0.0, abs=1e-9)
    assert first.points == before_points  # Overlay never mutates actual song coordinates.
    assert len(one.representative_track_ids) == 3
    assert len(set(one.representative_track_ids)) == 3
    assert all(0 <= value <= 100 for xy in one.overlay_nodes for value in xy)


def test_override_changes_only_symbol_and_derived_element() -> None:
    sound = _sound(_cloud(12), mode="basic-acoustic")
    before = sound.points
    natural = build_zodiac(sound)
    chosen = build_zodiac(sound, override_sign="scorpio")

    assert chosen.sign == "scorpio" and chosen.element == "water"
    assert chosen.is_override
    assert chosen.mode == "basic-acoustic"
    assert "基础声学地图" in chosen.rationale_zh
    assert chosen.point_fingerprint == natural.point_fingerprint
    assert chosen.representative_track_ids == natural.representative_track_ids
    assert sound.points == before
    assert "自选" in chosen.rationale_zh
    assert "chose" in chosen.rationale_en
    with pytest.raises(ValueError, match="Unknown zodiac sign"):
        build_zodiac(sound, override_sign="serpentarius")


def test_twelve_overlapping_songs_get_qualified_stable_result() -> None:
    sound = _sound([(f"song-{i}", 50.0, 50.0) for i in range(12)])
    first = build_zodiac(sound)
    second = build_zodiac(sound)
    assert first == second
    assert first.status == "matched" and first.sign == "aries"
    assert "高度重合" in first.rationale_zh
    assert len(first.representative_track_ids) == 3
    assert all(0 <= value <= 100 for xy in first.overlay_nodes for value in xy)


def test_element_mapping_is_only_sign_derived() -> None:
    expected = {
        "aries": "fire", "leo": "fire", "sagittarius": "fire",
        "taurus": "earth", "virgo": "earth", "capricorn": "earth",
        "gemini": "air", "libra": "air", "aquarius": "air",
        "cancer": "water", "scorpio": "water", "pisces": "water",
    }
    assert {sign: zodiac_element(sign) for sign in ZODIAC_LABELS["en"]} == expected
    assert set(ELEMENT_LABELS["zh"]) == set(ELEMENT_LABELS["en"]) == set(expected.values())


def test_local_png_is_bilingual_opt_in_for_titles_and_stale_safe() -> None:
    image_module = pytest.importorskip("PIL.Image")
    sound = _sound(_cloud(12))
    tracks = [
        SimpleNamespace(
            track_id=f"song-{i}",
            metadata=SimpleNamespace(title=f"C:\\Private\\Album\\Song {i}"),
            standard=SimpleNamespace(agitation=float(i * 8)),
        )
        for i in range(12)
    ]
    result = build_zodiac(sound, tracks, override_sign="cancer")
    zh_png = make_zodiac_share_card(
        result, sound, tracks, language="zh", include_track_titles=True,
        date=date(2026, 9, 28),
    )
    en_png = make_zodiac_share_card(result, sound, tracks, language="en")
    assert zh_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert en_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert image_module.open(__import__("io").BytesIO(zh_png)).size == (1080, 1600)
    assert len(zh_png) > 10000 and len(en_png) > 10000
    assert zh_png != en_png
    assert _safe_title(r"C:\Private\Album\Song 1") == "Song 1"
    assert _safe_title("/home/person/Music/Song 2") == "Song 2"

    changed = _sound([*_cloud(11), ("song-11", 60.0, 60.0)])
    with pytest.raises(ValueError, match="stale"):
        make_zodiac_share_card(result, changed, tracks)
    with pytest.raises(ValueError, match="language"):
        make_zodiac_share_card(result, sound, tracks, language="fr")
