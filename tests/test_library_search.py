from pathlib import Path
from types import SimpleNamespace

import pytest

from musefolders.library_search import parse_search, search_library
from musefolders.lyrics_map import resolve_track_lyrics, scan_lyric_languages


def track(root, name, track_id="one", bpm=75):
    path = root / f"{name}.mp3"
    path.write_bytes(b"fake audio")
    return SimpleNamespace(track_id=track_id, source_path=str(path),
                           metadata=SimpleNamespace(title=name, artist="歌手", album=""),
                           acoustic=SimpleNamespace(tempo_bpm=bpm, tempo_confidence=0.8),
                           standard=SimpleNamespace(brightness=70))


LYRICS = "爱情里我们曾相爱，分手以后我仍然想念你。\n远方的灯火照亮安静街道，我们走过的桥留下许多故事。\n勇敢面对未来的日子，回忆仍然在心里。"


def test_exporter_names_match_without_dropping_versions(tmp_path):
    member = track(tmp_path, "歌手 - 相遇_L")
    lyrics = tmp_path / "lyrics"
    lyrics.mkdir()
    (lyrics / "歌手 - 相遇 (12345678).lrc").write_text(LYRICS, encoding="utf-8")
    assert resolve_track_lyrics(member, lyrics_root=lyrics, all_tracks=[member]).status == "valid"
    assert scan_lyric_languages([member], lyrics_root=lyrics).statuses["one"] == "valid"
    (lyrics / "歌手 - 相遇 (87654321).lrc").write_text(LYRICS, encoding="utf-8")
    assert resolve_track_lyrics(member, lyrics_root=lyrics, all_tracks=[member]).status == "ambiguous"


def test_duplicate_recordings_and_live_versions_do_not_auto_match(tmp_path):
    one = track(tmp_path, "歌手 - 相遇_L")
    two = track(tmp_path, "歌手 - 相遇_HQ", "two")
    lyrics = tmp_path / "lyrics"
    lyrics.mkdir()
    (lyrics / "歌手 - 相遇 (12345678).lrc").write_text(LYRICS, encoding="utf-8")
    assert resolve_track_lyrics(one, lyrics_root=lyrics, all_tracks=[one, two]).status == "ambiguous"
    live = track(tmp_path, "歌手 - 相遇 (Live)_L", "live")
    assert resolve_track_lyrics(live, lyrics_root=lyrics, all_tracks=[live]).status == "missing"


def test_search_uses_lyrics_and_intersects_audio_conditions(tmp_path):
    one = track(tmp_path, "无关标题", bpm=75)
    two = track(tmp_path, "爱情", "two", bpm=140)
    (tmp_path / "无关标题.lrc").write_text(LYRICS, encoding="utf-8")
    hits = search_library([one, two], "关于爱情、慢一点、明亮的歌")
    assert [hit.track_id for hit in hits] == ["one"]
    assert any("歌词关键词" in reason for reason in hits[0].reasons)
    assert search_library([two], "爱情") == []  # title is not lyric evidence
    one.acoustic.tempo_confidence = 0
    assert search_library([one], "爱情慢速") == []


@pytest.mark.parametrize("query", ["不要爱情", "爱情或者友情", "快一点慢一点",
                                   "适合晚上听", "悲伤的爱情歌", "摇滚歌曲", ""])
def test_unsupported_intents_are_visible(query):
    with pytest.raises(ValueError):
        parse_search(query)
