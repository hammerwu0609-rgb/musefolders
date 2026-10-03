from dataclasses import replace

import pytest

from musefolders.library_search import match_profiles, parse_search, validate_intent
from musefolders.tag_catalog import TagEvidence, TrackProfile


def _profile(track_id, activity, tempo):
    return TrackProfile(track_id, (TagEvidence("theme", "爱情", "ai_lyrics", "inferred"),),
                        "valid", tempo, activity, 45, track_id, "歌手", "", 2020, "")


def test_scene_ranks_available_audio_and_preserves_explicit_filters():
    profiles = {"fast": _profile("fast", 85, 145), "calm": _profile("calm", 20, 75)}
    profiles["unknown"] = replace(profiles["calm"], track_id="unknown", activity=None,
                                  tempo_bpm=None, brightness=None)
    bedtime = match_profiles(profiles, validate_intent({"scene": "睡前"}))
    assert [hit.track_id for hit in bedtime] == ["calm", "fast"]
    assert bedtime[0].score > bedtime[1].score
    exercise = match_profiles(profiles, validate_intent({"scene": "运动"}))
    assert exercise[0].track_id == "fast"
    filtered = match_profiles(profiles, validate_intent({"scene": "睡前", "themes": ["爱情"], "tempo_max": 100}))
    assert [hit.track_id for hit in filtered] == ["calm"]
    assert not match_profiles(profiles, validate_intent({"scene": "睡前", "themes": ["亲情"]}))


@pytest.mark.parametrize("text,scene", [("适合睡前听的歌", "睡前"), ("运动时听的歌", "运动"),
                                        ("学习时的音乐", "专注"), ("想放松一下", "放松")])
def test_offline_scene_translation(text, scene):
    intent = parse_search(text)
    assert intent.scene == scene and not intent.literal


def test_unknown_scene_and_negation_are_not_silently_ignored():
    with pytest.raises(ValueError):
        validate_intent({"scene": "太空"})
    with pytest.raises(ValueError):
        parse_search("不要睡前的歌")
