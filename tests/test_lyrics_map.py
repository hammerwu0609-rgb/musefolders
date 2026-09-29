from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from musefolders.lyrics_map import (
    FastTextLanguageDetector,
    MAX_LYRIC_CHUNK_CHARS,
    THEME_PROMPTS,
    LocalLyricsEmbedder,
    build_lyrics_map,
    clean_lyrics,
    detect_lyric_language,
    lyrics_are_usable,
    resolve_track_lyrics,
    scan_lyric_languages,
)


class FakeEmbedder:
    def __init__(self, version: str = "fake-v1") -> None:
        self.model_version = version
        self.calls: list[list[str]] = []

    def encode(self, texts):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([float(digest[0] + 1), float(digest[1] + 1), float(digest[2] + 1)])
        return vectors


def _track(directory: Path, name: str, track_id: str):
    audio = directory / f"{name}.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"unchanged audio")
    return SimpleNamespace(track_id=track_id, source_path=str(audio))


CHINESE_LYRICS = "[ar:歌手]\n[00:01.23]春天的风吹过安静的街道\n[00:08.50]我想起那年夏天我们走过的桥\n[00:15.00]远处的灯火照亮了回家的方向\n[00:21.00]这里还有一段值得记住的故事\n"
JAPANESE_LYRICS = "[00:01.00]あの日の空を見上げながら一人で歩いた\n[00:05.20]遠い街の明かりが今も心に残っている\n[00:10.30]君と過ごした時間を静かに思い出している\n"


def test_clean_lyrics_handles_timestamps_headers_and_cjk() -> None:
    cleaned = clean_lyrics(CHINESE_LYRICS)
    assert "[00:" not in cleaned
    assert "[ar:" not in cleaned
    assert "春天的风" in cleaned
    assert lyrics_are_usable(cleaned)
    assert lyrics_are_usable(clean_lyrics(JAPANESE_LYRICS))
    assert not lyrics_are_usable(clean_lyrics("[00:01.00]啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊"))


def test_sidecar_statuses_and_no_plaintext_cache(tmp_path: Path) -> None:
    music = tmp_path / "music"
    adjacent = _track(music, "相遇", "one")
    missing = _track(music, "missing", "two")
    short = _track(music, "short", "three")
    instrumental = _track(music, "instrumental", "four")
    (music / "相遇.lrc").write_text(CHINESE_LYRICS, encoding="utf-8")
    (music / "short.txt").write_text("la la la", encoding="utf-8")
    fake = FakeEmbedder()

    result = build_lyrics_map(
        [adjacent, missing, short, instrumental],
        tmp_path / "artifacts",
        manual_instrumental_ids=["four"],
        embedder=fake,
    )
    assert result.statuses == {"one": "valid", "two": "missing", "three": "short", "four": "instrumental"}
    assert result.sources == {"one": "adjacent"}
    assert result.points == {"one": (0.0, 0.0)}
    assert result.projection_method == "single-point"
    assert set(result.theme_scores["one"]) == set(THEME_PROMPTS)
    assert all(-1 <= score <= 1 for score in result.theme_scores["one"].values())
    cached_files = list((tmp_path / "artifacts" / "lyrics_cache" / "embeddings").rglob("*.json"))
    assert len(cached_files) == 1
    assert "春天的风" not in cached_files[0].read_text(encoding="utf-8")
    assert adjacent.source_path and Path(adjacent.source_path).read_bytes() == b"unchanged audio"


def test_cache_is_by_cleaned_text_and_model_version(tmp_path: Path) -> None:
    music = tmp_path / "music"
    track = _track(music, "song", "one")
    lyric = music / "song.lrc"
    lyric.write_text(CHINESE_LYRICS, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    first_embedder = FakeEmbedder()
    first = build_lyrics_map([track], artifacts, embedder=first_embedder)
    assert first.cache_hits == 0
    assert len(first_embedder.calls) == 2  # text, then comparison prompts

    second_embedder = FakeEmbedder()
    second = build_lyrics_map([track], artifacts, embedder=second_embedder)
    assert second.cache_hits == 1
    assert second_embedder.calls == []  # track and comparison anchors both cached
    assert second.points == first.points

    lyric.write_text(CHINESE_LYRICS.replace("[00:01.23]", "[00:02.50]"), encoding="utf-8")
    timestamp_change = build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    assert timestamp_change.cache_hits == 1
    lyric.write_text(CHINESE_LYRICS + "[00:20.00]新的故事从这里开始\n", encoding="utf-8")
    text_change = build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    assert text_change.cache_hits == 0
    model_change = build_lyrics_map([track], artifacts, embedder=FakeEmbedder("fake-v2"))
    assert model_change.cache_hits == 0
    assert not (artifacts / "cache").exists()  # audio analysis cache is untouched


def test_external_matching_is_exact_and_unambiguous(tmp_path: Path) -> None:
    music = tmp_path / "music"
    external = tmp_path / "lyrics"
    external.mkdir()
    one = _track(music / "a", "same", "one")
    two = _track(music / "b", "same", "two")
    three = _track(music / "c", "exact", "three")
    (external / "same.lrc").write_text(CHINESE_LYRICS, encoding="utf-8")
    (external / "exact.lrc").write_text(JAPANESE_LYRICS, encoding="utf-8")
    (external / "exact remix.lrc").write_text(CHINESE_LYRICS, encoding="utf-8")
    result = build_lyrics_map([one, two, three], tmp_path / "artifacts", lyrics_root=external, embedder=FakeEmbedder())
    assert result.statuses == {"one": "ambiguous", "two": "ambiguous", "three": "valid"}
    assert result.sources["three"] == "external"

    (external / "other").mkdir()
    (external / "other" / "exact.txt").write_text(CHINESE_LYRICS, encoding="utf-8")
    ambiguous = build_lyrics_map([three], tmp_path / "artifacts", lyrics_root=external, embedder=FakeEmbedder())
    assert ambiguous.statuses["three"] == "ambiguous"

    (music / "c" / "exact.lrc").write_text(CHINESE_LYRICS, encoding="utf-8")
    adjacent_wins = build_lyrics_map([three], tmp_path / "artifacts", lyrics_root=external, embedder=FakeEmbedder())
    assert adjacent_wins.statuses["three"] == "valid"
    assert adjacent_wins.sources["three"] == "adjacent"


def test_two_or_three_valid_tracks_get_finite_pca_points(tmp_path: Path) -> None:
    music = tmp_path / "music"
    tracks = [_track(music, str(index), str(index)) for index in range(3)]
    for index in range(3):
        (music / f"{index}.txt").write_text(CHINESE_LYRICS + f"这是不同的额外内容第{index}号。", encoding="utf-8")
    result = build_lyrics_map(tracks, tmp_path / "artifacts", embedder=FakeEmbedder())
    assert len(result.points) == 3
    assert result.projection_method == "pca"
    assert all(len(coordinate) == 2 for coordinate in result.points.values())


def test_no_valid_lyrics_does_not_load_model(tmp_path: Path) -> None:
    track = _track(tmp_path / "music", "missing", "one")
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=LocalLyricsEmbedder())
    assert result.statuses == {"one": "missing"}
    assert result.points == {}
    assert result.projection_method == "none"
    assert not (tmp_path / "artifacts").exists()


def test_cache_corruption_is_recomputed_without_exposing_lyric_text(tmp_path: Path) -> None:
    music = tmp_path / "music"
    track = _track(music, "song", "one")
    (music / "song.txt").write_text(CHINESE_LYRICS, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    cache_file = next((artifacts / "lyrics_cache" / "embeddings").rglob("*.json"))
    cache_file.write_text(json.dumps({"embedding": [1, 2]}), encoding="utf-8")
    result = build_lyrics_map([track], artifacts, embedder=FakeEmbedder())
    assert result.cache_hits == 0
    assert result.statuses["one"] == "valid"


def test_utf16_lyric_sidecar_is_detected(tmp_path: Path) -> None:
    music = tmp_path / "music"
    track = _track(music, "song", "one")
    (music / "song.lrc").write_text(CHINESE_LYRICS, encoding="utf-16")
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder())
    assert result.statuses["one"] == "valid"


def test_embedded_id3_lyrics_and_manual_precedence(tmp_path: Path) -> None:
    mutagen = pytest.importorskip("mutagen")
    from mutagen.id3 import ID3, USLT

    music = tmp_path / "music"
    track = _track(music, "song", "one")
    tags = ID3()
    tags.add(USLT(encoding=3, lang="eng", text=CHINESE_LYRICS))
    tags.save(track.source_path)
    embedded = resolve_track_lyrics(track)
    assert embedded.status == "valid"
    assert embedded.source == "embedded"
    assert "春天的风" in embedded.text

    (music / "song.lrc").write_text(JAPANESE_LYRICS, encoding="utf-8")
    adjacent = resolve_track_lyrics(track)
    assert adjacent.source == "adjacent"
    assert "あの日" in adjacent.text

    manual = music / "chosen.txt"
    manual.write_text(CHINESE_LYRICS, encoding="utf-8")
    explicit = resolve_track_lyrics(track, selected_path=manual)
    assert explicit.source == "manual"
    assert "春天" in explicit.text
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder(),
                              selected_sources={"one": manual})
    assert result.sources["one"] == "manual"
    assert Path(track.source_path).is_file() and mutagen is not None


def test_embedded_id3_sylt_and_vorbis_comment(tmp_path: Path) -> None:
    pytest.importorskip("mutagen")
    import mutagen
    from mutagen.id3 import ID3, SYLT

    track = _track(tmp_path / "music", "sync", "one")
    lines = clean_lyrics(CHINESE_LYRICS).splitlines()
    tags = ID3()
    tags.add(SYLT(encoding=3, lang="zho", text=[(line, index * 1000) for index, line in enumerate(lines)]))
    tags.save(track.source_path)
    assert resolve_track_lyrics(track).status == "valid"

    # Vorbis-comment formats share the same tag access shape; use a fake
    # container here so the test needs no audio encoder or network fixture.
    ogg = SimpleNamespace(track_id="ogg", source_path=str(tmp_path / "music" / "ogg.ogg"))
    Path(ogg.source_path).write_bytes(b"not an actual audio file")
    original_file = mutagen.File
    try:
        mutagen.File = lambda _path, **_kwargs: SimpleNamespace(tags={"LYRICS": [CHINESE_LYRICS]})
        parsed = resolve_track_lyrics(ogg)
    finally:
        mutagen.File = original_file
    assert parsed.status == "valid"
    assert parsed.source == "embedded"


def test_conflicting_lyric_sources_are_exposed_not_silently_picked(tmp_path: Path) -> None:
    music = tmp_path / "music"
    track = _track(music, "song", "one")
    first = music / "song.lrc"
    second = music / "song.txt"
    first.write_text(CHINESE_LYRICS, encoding="utf-8")
    second.write_text(JAPANESE_LYRICS, encoding="utf-8")
    resolution = resolve_track_lyrics(track)
    assert resolution.status == "ambiguous"
    assert set(resolution.candidates) == {str(first), str(second)}
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder())
    assert set(result.ambiguous_candidates["one"]) == {str(first), str(second)}
    assert result.points == {}
    resolved = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder(),
                                selected_sources={"one": second})
    assert resolved.statuses["one"] == "valid"
    assert resolved.sources["one"] == "manual"


def test_title_and_lyrics_are_weighted_and_long_text_is_chunked(tmp_path: Path) -> None:
    class SemanticEmbedder:
        model_version = "semantic-v1"

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def encode(self, texts):
            self.calls.append(list(texts))
            return [[1.0, 0.0] if text == "TITLE_ONLY" else [0.0, 1.0] for text in texts]

    music = tmp_path / "music"
    track = _track(music, "song", "one")
    track.metadata = SimpleNamespace(title="TITLE_ONLY")
    (music / "song.txt").write_text("\n".join(["远处的灯火照亮了回家的方向" * 6] * 15), encoding="utf-8")
    embedder = SemanticEmbedder()
    result = build_lyrics_map([track], tmp_path / "artifacts", embedder=embedder)
    assert result.statuses["one"] == "valid"
    assert len(embedder.calls[0]) > 2  # title plus multiple lyric chunks
    assert max(map(len, embedder.calls[0][1:])) <= MAX_LYRIC_CHUNK_CHARS
    np.testing.assert_allclose(result.embeddings["one"], np.array([0.2, 0.8]) / np.linalg.norm([0.2, 0.8]))


def test_language_codes_require_lyric_evidence_and_model(tmp_path: Path) -> None:
    class FakeDetector:
        model_version = "fake-language-v1"

        def predict(self, text: str):
            return ("zh", 0.99) if any("\u4e00" <= char <= "\u9fff" for char in text) else ("en", 0.99)

    chinese = clean_lyrics(CHINESE_LYRICS)
    assert detect_lyric_language(chinese, FakeDetector()).code == "zh"
    assert detect_lyric_language(chinese + "\nThe morning lights are shining in my city", FakeDetector()).code == "mixed"
    assert detect_lyric_language(chinese).status == "unavailable"

    track = _track(tmp_path / "music", "English song title", "one")
    (Path(track.source_path).parent / "English song title.txt").write_text(CHINESE_LYRICS, encoding="utf-8")
    with_model = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder(),
                                  language_detector=FakeDetector())
    assert with_model.languages["one"] == "zh"  # never infer English from the title
    assert with_model.language_statuses["one"] == "known"
    unavailable = build_lyrics_map([track], tmp_path / "artifacts", embedder=FakeEmbedder(),
                                   language_detector=FastTextLanguageDetector(tmp_path / "missing.ftz"))
    assert unavailable.languages["one"] == "unknown"
    assert unavailable.language_statuses["one"] == "unavailable"


def test_external_resolver_requires_complete_library_for_disambiguation(tmp_path: Path) -> None:
    music = tmp_path / "music"
    lyrics = tmp_path / "lyrics"
    lyrics.mkdir()
    track = _track(music, "song", "one")
    (lyrics / "song.txt").write_text(CHINESE_LYRICS, encoding="utf-8")
    with pytest.raises(ValueError, match="all_tracks"):
        resolve_track_lyrics(track, lyrics_root=lyrics)
    assert resolve_track_lyrics(track, lyrics_root=lyrics, all_tracks=[track]).source == "external"


def test_language_scan_needs_no_theme_model_or_artifact_cache(tmp_path: Path) -> None:
    class FakeDetector:
        model_version = "fake-language-v1"

        def predict(self, _text: str):
            return "zh", 0.98

    music = tmp_path / "music"
    with_lyrics = _track(music, "song", "one")
    no_lyrics = _track(music, "missing", "two")
    instrumental = _track(music, "instrumental", "three")
    (music / "song.lrc").write_text(CHINESE_LYRICS, encoding="utf-8")
    result = scan_lyric_languages(
        [with_lyrics, no_lyrics, instrumental],
        manual_instrumental_ids=["three"], language_detector=FakeDetector(),
    )
    assert result.statuses == {"one": "valid", "two": "missing", "three": "instrumental"}
    assert result.sources == {"one": "adjacent"}
    assert result.languages == {"one": "zh", "two": "unknown", "three": "instrumental"}
    assert result.language_statuses == {"one": "known", "two": "unknown", "three": "instrumental"}
    assert result.points == result.embeddings == result.theme_scores == {}
    assert not (tmp_path / "artifacts").exists()
