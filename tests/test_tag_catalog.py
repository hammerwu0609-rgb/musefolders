from pathlib import Path
from types import SimpleNamespace

import pytest

from musefolders.library_search import match_profiles, parse_search, validate_intent
from musefolders.tag_catalog import build_track_profiles, save_profile_catalog


LYRIC = "暗恋时我偷偷喜欢你，仍然盼望未来的相遇。\n" \
        "走过很远的街道与桥，我的心里还记得那天的故事。\n" \
        "每一年都会想起那段回忆，心里的希望始终没有离开。"


def _track(root: Path):
    audio = root / "歌手 - 夜曲.mp3"
    audio.write_bytes(b"test audio")
    audio.with_suffix(".lrc").write_text(LYRIC, encoding="utf-8")
    return SimpleNamespace(track_id="one", source_path=str(audio),
                           metadata=SimpleNamespace(title="夜曲", artist="歌手", album="专辑",
                                                    year="2021-05-10", genre="Blues"),
                           acoustic=SimpleNamespace(tempo_bpm=84, tempo_confidence=.8),
                           standard=SimpleNamespace(agitation=28, brightness=65))


def test_evidence_provenance_and_structured_matching(tmp_path):
    member = _track(tmp_path)
    profile = build_track_profiles([member])["one"]
    assert profile.theme("暗恋").source == "adjacent"
    assert profile.theme("暗恋").status == "keyword_clue"
    assert profile.year == 2021
    assert any(tag.label == "Blues" and tag.status == "raw_unverified" for tag in profile.tags)
    assert not any(hasattr(profile, field) for field in ("lyrics", "lyric_text"))
    intent = validate_intent({"themes": ["爱情"], "tempo_max": 90, "activity_max": 35,
                              "year_from": 2020, "artist": "歌手"})
    hits = match_profiles({"one": profile}, intent)
    assert [hit.track_id for hit in hits] == ["one"]  # parent theme accepts an explicit child
    assert "暗恋" in hits[0].reasons[0]
    assert not match_profiles({"one": profile}, validate_intent({"tempo_min": 120}))
    catalog = save_profile_catalog({"one": profile}, tmp_path / "artifacts", analysis_id="demo")
    stored = catalog.read_text(encoding="utf-8")
    assert '"analysis_id": "demo"' in stored
    assert "偷偷喜欢你" not in stored and str(tmp_path) not in stored


def test_manual_correction_overrides_keyword_clue(tmp_path):
    member = _track(tmp_path)
    profile = build_track_profiles([member], manual_themes={"one": "family"},
                                   verified_genres={"one": "Pop"},
                                   instrumental_ids=frozenset({"one"}))["one"]
    assert profile.theme("暗恋") is None
    assert profile.theme("亲情").status == "verified"
    assert any(tag.label == "Pop" and tag.status == "verified" for tag in profile.tags)
    assert any(tag.label == "纯音乐" and tag.status == "verified" for tag in profile.tags)
    unknown = build_track_profiles([member], manual_themes={"one": "unknown"})["one"]
    assert not any(tag.dimension == "theme" for tag in unknown.tags)


@pytest.mark.parametrize("payload", [
    {"themes": ["女声"]}, {"themes": ["爱情"], "source_path": "C:\\private"},
    {"tempo_min": 180, "tempo_max": 90}, {"year_from": 2025, "year_to": 2020},
    {"brightness_min": 101}, {},
])
def test_model_contract_rejects_unsupported_or_conflicting_fields(payload):
    with pytest.raises(ValueError):
        validate_intent(payload)


def test_local_parser_combines_artist_theme_and_year():
    intent = parse_search("找歌手2020年后的暗恋歌曲", artists=["歌手"])
    assert intent.themes == ("暗恋",)
    assert intent.artist == "歌手"
    assert intent.year_from == 2020
    assert parse_search("Taylor Swift的爱情歌", artists=["Taylor Swift"]).artist == "Taylor Swift"
    with pytest.raises(ValueError):
        parse_search("爱情不太快")  # never invert a negated tempo request
