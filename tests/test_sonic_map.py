from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import musefolders.sonic_map as sonic_module
from musefolders.models import AcousticFeatures
from musefolders.sonic_map import (
    MapPoint, SonicMap, _choose_hybrid, _mel_patches, _neighbor_overlap,
    _spearman, build_sonic_map, project_vectors,
)


def _track(folder: Path, number: int) -> SimpleNamespace:
    path = folder / f"song-{number}.mp3"
    content = f"test audio bytes {number}".encode()
    path.write_bytes(content)
    acoustic = AcousticFeatures(
        duration_s=80.0,
        tempo_bpm=70.0 + number * 27.0,
        tempo_confidence=0.7,
        rms_dbfs=-30.0 + number * 3.0,
        dynamic_range_db=13.0 + number,
        spectral_centroid_hz=1100.0 + number * 650.0,
        spectral_rolloff_hz=3300.0 + number * 980.0,
        zero_crossing_rate=0.04 + number * 0.02,
        percussive_ratio=0.15 + number * 0.12,
        onset_rate=0.9 + number * 0.7,
        harmonic_ratio=0.75 - number * 0.11,
        key="C", mode="major", key_confidence=0.7,
        analyzed_audio_s=24.0, high_frequency_ratio=0.03 + number * 0.05,
    )
    return SimpleNamespace(
        track_id=f"track-{number}", source_path=str(path),
        source_sha256=hashlib.sha256(content).hexdigest(),
        engine_version="test-v1", acoustic=acoustic,
    )


def test_missing_model_is_explicit_and_independently_cached(tmp_path: Path) -> None:
    tracks = [_track(tmp_path, i) for i in range(3)]
    artifacts = tmp_path / "artifacts"
    model = tmp_path / "not-present.onnx"

    first = build_sonic_map(tracks, artifacts, model_path=model)
    second = build_sonic_map(tracks, artifacts, model_path=model)

    assert first.mode == "basic-acoustic"
    assert first.projection == "semantic-only"
    assert first.fallback_reason == "model_missing"
    assert "basic_acoustic_fallback:model_missing" in first.warnings
    assert len(first.points) == 3
    assert first.computed == 3 and first.cache_hits == 0
    assert second.computed == 0 and second.cache_hits == 3
    assert second.projection == first.projection
    assert second.points == first.points
    assert not first.failures
    assert first.layout_metrics["blend_weight"] == 0.0
    assert first.layout_metrics["bpm_axis_spearman"] == 1.0


def test_basic_map_axes_have_fixed_bpm_and_brightness_meanings(tmp_path: Path) -> None:
    tracks = [_track(tmp_path, i) for i in range(3)]
    sonic = build_sonic_map(tracks, tmp_path / "artifacts", model_path=tmp_path / "missing.onnx")
    by_id = {point.track_id: point for point in sonic.points}
    assert by_id["track-0"].x == pytest.approx((70 - 60) / 120 * 100, abs=1e-4)
    assert by_id["track-0"].x < by_id["track-1"].x < by_id["track-2"].x
    assert by_id["track-0"].y < by_id["track-1"].y < by_id["track-2"].y
    assert sonic.layout_metrics["axis_scale"].startswith("0-100")


def test_hybrid_cannot_lower_axis_fidelity_or_neighbor_overlap() -> None:
    rng = np.random.default_rng(41)
    count = 36
    semantic = rng.uniform(15.0, 85.0, size=(count, 2)).astype(np.float32)
    sound = semantic + rng.normal(0, 9, size=(count, 2))
    sound = sound.astype(np.float32)
    matrix = np.column_stack((sound, np.full(count, 30.0))).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    display, method, weight = _choose_hybrid(matrix, semantic, sound)

    assert method in {"semantic-only", "semantic-hybrid-umap"}
    assert weight in {0.0, 0.1, 0.2, 0.3}
    assert _spearman(semantic[:, 0], display[:, 0]) >= 0.85
    assert _spearman(semantic[:, 1], display[:, 1]) >= 0.85
    assert _neighbor_overlap(matrix, display) >= _neighbor_overlap(matrix, semantic) - 1e-8


def test_added_song_preserves_existing_point_coordinates(tmp_path: Path) -> None:
    tracks = [_track(tmp_path, i) for i in range(3)]
    artifacts = tmp_path / "artifacts"
    model = tmp_path / "missing.onnx"
    first = build_sonic_map(tracks, artifacts, model_path=model)

    extra = _track(tmp_path, 3)
    second = build_sonic_map([*tracks, extra], artifacts, model_path=model)

    old = {point.track_id: (point.x, point.y) for point in first.points}
    new = {point.track_id: (point.x, point.y) for point in second.points}
    assert all(new[track_id] == old_xy for track_id, old_xy in old.items())
    assert extra.track_id in new
    assert second.projection.startswith("anchored-")
    assert second.cache_hits == 3 and second.computed == 1


def test_source_change_is_not_served_from_stale_hash_cache(tmp_path: Path) -> None:
    track = _track(tmp_path, 1)
    Path(track.source_path).write_bytes(b"different song now")

    result = build_sonic_map([track], tmp_path / "artifacts", model_path=tmp_path / "missing.onnx")

    assert not result.points
    assert result.failures and "re-analyze" in result.failures[0]["reason"]


def test_similarity_uses_original_vectors_not_2d_coordinates() -> None:
    sonic = SonicMap(
        mode="musicnn", projection="umap",
        points=(MapPoint("a", 0.0, 0.0), MapPoint("b", 100.0, 0.0), MapPoint("c", 0.1, 0.0)),
        vectors={
            "a": np.array([1.0, 0.0], dtype=np.float32),
            "b": np.array([0.8, 0.6], dtype=np.float32),
            "c": np.array([-1.0, 0.0], dtype=np.float32),
        },
    )

    neighbors = sonic.similar("a")
    assert [item.track_id for item in neighbors] == ["b", "c"]
    assert neighbors[0].score == pytest.approx(0.8)
    assert sonic.rank_by_vector([1.0, 0.0], exclude_ids=("a",))[0].track_id == "b"
    with pytest.raises(ValueError, match="dimension"):
        sonic.rank_by_vector([1.0, 0.0, 0.0])


def test_projection_of_small_catalog_is_finite() -> None:
    coordinates, method = project_vectors({
        "first": np.array([1.0, 0.0]),
        "second": np.array([0.0, 1.0]),
    })
    assert method == "pca"
    assert set(coordinates) == {"first", "second"}
    assert all(np.isfinite(pair).all() for pair in coordinates.values())


def test_umap_only_runs_for_model_catalogs_of_at_least_sixteen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    class FakeUMAP:
        def __init__(self, **_kwargs: object):
            pass

        def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
            calls.append(len(matrix))
            return np.column_stack((np.arange(len(matrix)), np.zeros(len(matrix))))

    monkeypatch.setitem(sys.modules, "umap", SimpleNamespace(UMAP=FakeUMAP))
    vectors = {
        f"track-{index:02d}": np.eye(16, dtype=np.float32)[index]
        for index in range(16)
    }
    _, small_method = project_vectors(dict(list(vectors.items())[:4]))
    _, basic_method = project_vectors(vectors, allow_umap=False)
    assert small_method == basic_method == "pca"
    assert calls == []

    _, model_method = project_vectors(vectors, allow_umap=True)
    assert model_method == "umap"
    assert calls == [16]


def test_short_excerpt_is_padded_to_one_musicnn_patch() -> None:
    samples = np.sin(2 * np.pi * 440 * np.arange(16_000) / 16_000).astype(np.float32)
    patches = _mel_patches(samples, 16_000)
    assert patches.shape == (1, 187, 96)
    assert np.isfinite(patches).all()
    with pytest.raises(ValueError, match="Silent"):
        _mel_patches(np.zeros(16_000, dtype=np.float32), 16_000)


def test_model_bytes_and_preprocessing_have_separate_vector_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracks = [_track(tmp_path, i) for i in range(3)]
    model = tmp_path / "musicnn_embedding.onnx"
    model.write_bytes(b"fake model version one")
    calls: list[str] = []

    class FakeEncoder:
        def __init__(self, _model_path: Path):
            pass

        def encode(self, path: Path, _duration_s: float) -> np.ndarray:
            calls.append(path.name)
            vector = np.zeros(200, dtype=np.float32)
            vector[int(path.stem.split("-")[-1])] = 1.0
            return vector

    monkeypatch.setattr(sonic_module, "_MusicnnEncoder", FakeEncoder)
    first = build_sonic_map(tracks, tmp_path / "artifacts", model_path=model)
    second = build_sonic_map(tracks, tmp_path / "artifacts", model_path=model)
    assert first.mode == "musicnn" and first.computed == 3
    assert second.cache_hits == 3 and second.computed == 0
    assert len(calls) == 3
    assert first.similar("track-0")[0].score == pytest.approx(0.0)

    model.write_bytes(b"fake model version two")
    third = build_sonic_map(tracks, tmp_path / "artifacts", model_path=model)
    assert third.computed == 3 and third.cache_hits == 0
    assert len(calls) == 6

