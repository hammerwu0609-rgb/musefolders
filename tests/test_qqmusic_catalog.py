import json
from types import SimpleNamespace

import pytest

from musefolders import qqmusic_catalog as qq
from musefolders.ai_lyrics import analyze_lyrics, lyric_labels
from musefolders.library_search import search_library, validate_intent
from musefolders.tag_catalog import build_track_profiles

LYRICS = "想靠近你却不敢开口，我们在漫长的街上走过。\n每天都把那些心事藏在心里，盼望有一天能够再见。\n我看着远处的灯火，等待与你相遇的那一个时刻。"


def song(mid="one", name="夜曲", duration=240, singers=None):
    return {"mid": mid, "name": name, "duration_seconds": duration, "singers": singers or ["歌手"], "album": "专辑"}


def test_identity_match_checks_artist_duration_and_version():
    query = {"title": "夜曲 (译名)", "artist": "歌手", "duration_seconds": 241}
    matched, status = qq.choose_candidate(query, [song()])
    assert status == "matched" and matched["mid"] == "one"
    for wrong in (song(singers=["其他歌手"]), song(duration=200), song(name="夜曲 (Live)")):
        assert qq.choose_candidate(query, [wrong])[0] is None
    assert qq.choose_candidate(query, [song(duration=239), song(mid="two", duration=243)])[1] == "ambiguous"


def test_normalization_preserves_zero_codes_and_subtitle_versions():
    normalized = qq.normalize_detail(song(), {"title": "夜曲", "subtitle": "Live Remix", "language": 0,
                                       "genre": 0, "time_public": "2021-03-04"})
    assert normalized["language_raw"] == 0 and normalized["genre_raw"] == 0
    assert normalized["language"] == "" and normalized["release_year"] == 2021
    assert normalized["version_tags"] == ["Live", "Remix"]


def track(root):
    audio = root / "歌手 - 夜曲.mp3"
    audio.write_bytes(b"original audio")
    return SimpleNamespace(track_id="local", source_sha256="audio-hash", source_path=str(audio),
        metadata=SimpleNamespace(title="夜曲", artist="歌手", album="", year="", genre="Blues"),
        acoustic=SimpleNamespace(tempo_bpm=80, tempo_confidence=.9, duration_s=240),
        standard=SimpleNamespace(agitation=25, brightness=50))


def test_platform_cache_lyrics_ai_tags_and_year_search_flow(tmp_path, monkeypatch):
    member = track(tmp_path)
    artifacts = tmp_path / "artifacts"
    seen = []
    def events(payload):
        seen.append(payload)
        yield {"event": "song", "track_id": "local", "result": {
            "status": "matched", "mid": "MID123", "title": "夜曲", "artist": "歌手", "album": "新专辑",
            "release_year": 2021, "language_raw": 0, "language": "", "version_tags": [],
            "has_lyrics": True, "lyrics": LYRICS}}
    monkeypatch.setattr(qq, "_events", events)
    report = qq.enrich_library([member], artifacts)
    assert report["matched"] == 1 and report["lyrics"] == 1
    assert qq.enrich_library([member], artifacts)["cached"] == 1 and len(seen) == 1
    assert "source_path" not in json.dumps(seen)
    records = qq.cached_platform([member], artifacts)
    fallback = qq.platform_lyrics(records, artifacts)
    classified = []
    def classify(title, lyrics, *, api_key):
        classified.append(lyrics)
        return ("暗恋",)
    assert analyze_lyrics([member], tmp_path, artifacts, api_key="fake", classifier=classify,
                          fallback_sources=fallback) == (1, 0, 1)
    labels = lyric_labels([member], tmp_path, artifacts, fallback_sources=fallback)
    profiles = build_track_profiles([member], platform_metadata=records, fallback_sources=fallback, ai_themes=labels)
    assert profiles["local"].lyrics_status == "valid" and profiles["local"].album == "新专辑"
    assert profiles["local"].year_source == "qqmusic"
    hits = search_library([member], "", profiles=profiles, intent=validate_intent({"themes": ["暗恋"], "year_from": 2020}))
    assert [hit.track_id for hit in hits] == ["local"] and "QQ 音乐" in hits[0].reasons[-1]
    literal = search_library([member], "心事藏在心里", profiles=profiles, fallback_sources=fallback)
    assert [hit.track_id for hit in literal] == ["local"]
    assert member.metadata.album == "" and (tmp_path / "歌手 - 夜曲.mp3").read_bytes() == b"original audio"
    member.source_sha256 = "different-recording"
    assert qq.cached_platform([member], artifacts) == {}


def test_partial_cache_survives_connection_failure(tmp_path, monkeypatch):
    member = track(tmp_path)
    other = SimpleNamespace(**vars(member))
    other.track_id = "other"
    def events(payload):
        yield {"event": "song", "track_id": "local", "result": {"status": "not_matched"}}
        raise qq.QQMusicConnectionError("网络暂时不可用")
    monkeypatch.setattr(qq, "_events", events)
    with pytest.raises(qq.QQMusicConnectionError):
        qq.enrich_library([member, other], tmp_path / "artifacts")
    saved = json.loads((tmp_path / "artifacts" / "platform_catalog.json").read_text(encoding="utf-8"))
    assert saved["tracks"]["local"]["status"] == "not_matched"


def test_valid_local_lyrics_keep_precedence(tmp_path):
    member = track(tmp_path)
    local = tmp_path / "歌手 - 夜曲.lrc"
    local.write_text(LYRICS, encoding="utf-8")
    remote = tmp_path / "remote.lrc"
    remote.write_text("完全不同的歌词。" * 10, encoding="utf-8")
    captured = []
    analyze_lyrics([member], tmp_path, tmp_path / "artifacts", api_key="fake",
        fallback_sources={"local": remote}, classifier=lambda title, lyrics, **kwargs: captured.append(lyrics) or ())
    assert captured == [LYRICS]
