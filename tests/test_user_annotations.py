from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from musefolders.user_annotations import (
    ANNOTATIONS_FILE,
    clear_verified_genre,
    confirmed_instrumental_ids,
    set_instrumental_confirmation,
    set_verified_genre,
    set_theme_assignment,
    theme_assignments,
    verified_genre_assignments,
)


def test_only_explicit_content_confirmation_counts(tmp_path) -> None:
    one = SimpleNamespace(track_id="one", source_sha256="same-audio")
    duplicate = SimpleNamespace(track_id="duplicate", source_sha256="same-audio")
    other = SimpleNamespace(track_id="other", source_sha256="different-audio")
    tracks = [one, duplicate, other]

    assert confirmed_instrumental_ids(tracks, tmp_path) == frozenset()
    set_instrumental_confirmation(one, tmp_path, True)
    assert confirmed_instrumental_ids(tracks, tmp_path) == frozenset({"one", "duplicate"})
    set_instrumental_confirmation(one, tmp_path, False)
    assert confirmed_instrumental_ids(tracks, tmp_path) == frozenset()


def test_genre_confirmation_applies_to_duplicate_audio_and_can_be_withdrawn(tmp_path) -> None:
    digest = "a" * 64
    one = SimpleNamespace(track_id="one", source_sha256=digest)
    duplicate = SimpleNamespace(track_id="duplicate", source_sha256=digest)
    other = SimpleNamespace(track_id="other", source_sha256="b" * 64)
    tracks = [one, duplicate, other]

    assert verified_genre_assignments(tracks, tmp_path) == {}
    set_verified_genre(one, tmp_path, "  J-pop  ")
    assert verified_genre_assignments(tracks, tmp_path) == {"one": "J-pop", "duplicate": "J-pop"}
    clear_verified_genre(duplicate, tmp_path)
    assert verified_genre_assignments(tracks, tmp_path) == {}


def test_genre_confirmation_never_modifies_source_music(tmp_path) -> None:
    source = tmp_path / "music" / "song.mp3"
    source.parent.mkdir()
    source.write_bytes(b"original audio bytes")
    artifacts = tmp_path / "artifacts"
    track = SimpleNamespace(track_id="song", source_sha256="f" * 64, source_path=str(source))

    set_verified_genre(track, artifacts, "  Contemporary  Jazz  ")
    assert verified_genre_assignments([track], artifacts) == {"song": "Contemporary Jazz"}
    assert source.read_bytes() == b"original audio bytes"
    assert sorted(path.name for path in source.parent.iterdir()) == ["song.mp3"]


def test_genre_and_instrumental_confirmations_preserve_each_other(tmp_path) -> None:
    track = SimpleNamespace(track_id="one", source_sha256="c" * 64)
    set_instrumental_confirmation(track, tmp_path, True)
    set_verified_genre(track, tmp_path, "Ambient")
    assert confirmed_instrumental_ids([track], tmp_path) == frozenset({"one"})
    set_instrumental_confirmation(track, tmp_path, False)
    assert verified_genre_assignments([track], tmp_path) == {"one": "Ambient"}


def test_theme_correction_persists_by_audio_hash_and_preserves_other_annotations(tmp_path) -> None:
    digest = "a" * 64
    one = SimpleNamespace(track_id="one", source_sha256=digest)
    duplicate = SimpleNamespace(track_id="duplicate", source_sha256=digest)
    set_verified_genre(one, tmp_path, "Ambient")
    set_theme_assignment(one, tmp_path, "family")
    assert theme_assignments([one, duplicate], tmp_path) == {
        "one": "family", "duplicate": "family",
    }
    assert verified_genre_assignments([one], tmp_path) == {"one": "Ambient"}
    set_theme_assignment(one, tmp_path, "unknown")
    assert theme_assignments([one], tmp_path) == {"one": "unknown"}
    set_theme_assignment(duplicate, tmp_path, None)
    assert theme_assignments([one, duplicate], tmp_path) == {}
    assert verified_genre_assignments([one], tmp_path) == {"one": "Ambient"}


def test_invalid_theme_cannot_modify_annotations(tmp_path) -> None:
    track = SimpleNamespace(track_id="one", source_sha256="a" * 64)
    set_theme_assignment(track, tmp_path, "love")
    original = (tmp_path / ANNOTATIONS_FILE).read_bytes()
    with pytest.raises(ValueError, match="Unknown theme"):
        set_theme_assignment(track, tmp_path, "<script>")
    assert (tmp_path / ANNOTATIONS_FILE).read_bytes() == original


@pytest.mark.parametrize("genre", ["", "   ", "House\nRock", "<script>", "X" * 81, 123])
def test_invalid_genre_cannot_modify_annotations(tmp_path, genre) -> None:
    track = SimpleNamespace(track_id="one", source_sha256="d" * 64)
    set_verified_genre(track, tmp_path, "Jazz")
    original = (tmp_path / ANNOTATIONS_FILE).read_bytes()
    with pytest.raises(ValueError):
        set_verified_genre(track, tmp_path, genre)
    assert (tmp_path / ANNOTATIONS_FILE).read_bytes() == original


def test_invalid_hash_cannot_create_confirmation(tmp_path) -> None:
    track = SimpleNamespace(track_id="one", source_sha256="not-a-sha256")
    with pytest.raises(ValueError, match="SHA-256"):
        set_verified_genre(track, tmp_path, "Jazz")
    assert not (tmp_path / ANNOTATIONS_FILE).exists()


def test_malformed_existing_annotations_are_not_overwritten(tmp_path) -> None:
    target = tmp_path / ANNOTATIONS_FILE
    target.write_text('{"schema_version": 1, "verified_genres_by_sha256": {"bad": "Jazz"}}', encoding="utf-8")
    track = SimpleNamespace(track_id="one", source_sha256="a" * 64)
    with pytest.raises(ValueError, match="Invalid verified genre"):
        set_verified_genre(track, tmp_path, "Jazz")
    assert json.loads(target.read_text(encoding="utf-8"))["verified_genres_by_sha256"] == {"bad": "Jazz"}


def test_failed_atomic_replace_preserves_previous_document(tmp_path, monkeypatch) -> None:
    track = SimpleNamespace(track_id="one", source_sha256="e" * 64)
    set_verified_genre(track, tmp_path, "Jazz")
    target = tmp_path / ANNOTATIONS_FILE
    original = target.read_bytes()

    def fail_replace(_source, _target) -> None:
        raise OSError("simulated interruption")

    monkeypatch.setattr("musefolders.user_annotations.os.replace", fail_replace)
    with pytest.raises(OSError, match="interruption"):
        set_verified_genre(track, tmp_path, "Rock")
    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".user_annotations-*.tmp"))
