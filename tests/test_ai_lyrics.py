from __future__ import annotations

import json
from types import SimpleNamespace

from musefolders.ai_lyrics import analyze_lyrics, classify_lyrics, lyric_labels
from musefolders.library_search import match_profiles, validate_intent
from musefolders.tag_catalog import build_track_profiles


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": '{"themes":["暗恋","爱情"]}'}}]}).encode()


def test_ai_labels_flow_into_search_without_storing_lyrics(tmp_path):
    audio = tmp_path / "Singer - Song.mp3"
    audio.write_bytes(b"audio")
    audio.with_suffix(".lrc").write_text(
        "想靠近你却始终不敢开口，走过那条很长的街。\n"
        "我把心事藏起来，盼着有一天能够相见。\n"
        "每天都想对你说出那些话，却只能远远看着你走过。", encoding="utf-8")
    track = SimpleNamespace(
        track_id="one", source_path=str(audio), source_sha256="sound-hash",
        metadata=SimpleNamespace(title="Song", artist="Singer", album="", year="", genre=""),
        acoustic=SimpleNamespace(tempo_bpm=80, tempo_confidence=.8),
        standard=SimpleNamespace(agitation=25, brightness=50),
    )
    calls = []

    def fake_classify(title, lyrics, *, api_key):
        calls.append((title, lyrics))
        return classify_lyrics(title, lyrics, api_key=api_key, opener=lambda *_args, **_kwargs: _Response())

    assert analyze_lyrics([track], tmp_path, tmp_path / "artifacts", api_key="test", classifier=fake_classify) == (1, 0, 1)
    assert analyze_lyrics([track], tmp_path, tmp_path / "artifacts", api_key="test", classifier=fake_classify) == (0, 1, 1)
    assert len(calls) == 1
    cache = (tmp_path / "artifacts" / "ai_lyrics_tags.json").read_text(encoding="utf-8")
    assert "想靠近" not in cache and "test" not in cache
    labels = lyric_labels([track], tmp_path, tmp_path / "artifacts")
    profile = build_track_profiles([track], ai_themes=labels)["one"]
    assert profile.theme("暗恋").source == "ai_lyrics"
    hits = match_profiles({"one": profile}, validate_intent({"themes": ["暗恋"]}))
    assert [hit.track_id for hit in hits] == ["one"]
    # Identical model names from a different endpoint must not reuse labels.
    assert lyric_labels([track], tmp_path, tmp_path / "artifacts", api_url="https://other.example/v1/chat/completions") == {}
    def other_classifier(title, lyrics, **kwargs):
        return ("成长",)
    assert analyze_lyrics([track], tmp_path, tmp_path / "artifacts", api_key="test", api_url="https://other.example/v1/chat/completions", classifier=other_classifier) == (1, 0, 1)
    assert lyric_labels([track], tmp_path, tmp_path / "artifacts") == {}
    assert lyric_labels([track], tmp_path, tmp_path / "artifacts", api_url="https://other.example/v1/chat/completions") == {"one": ("成长",)}
    audio.with_suffix(".lrc").write_text("完全不同的歌词内容。" * 5, encoding="utf-8")
    assert lyric_labels([track], tmp_path, tmp_path / "artifacts") == {}
