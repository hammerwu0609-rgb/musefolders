"""Local sonic embeddings and a stable, explicitly qualified 2-D map.

This module does not depend on or import AudioMuse application source code.
The optional MusiCNN-compatible ONNX graph can be bundled separately with its
own attribution. Without it, the map is *only* a basic-acoustic projection.
Cosine queries always use the original vectors, never the displayed points.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

import numpy as np

from .models import ENGINE_VERSION, TAXONOMY_VERSION
from .taxonomy import STANDARD_RANGES, brightness_score

if TYPE_CHECKING:
    from .models import TrackEncoding


MUSICNN_PREPROCESS_VERSION = "musicnn-mel16k-96x187-three8s-v1"
BASIC_VECTOR_VERSION = "basic-acoustic-v2-high-frequency"
PROJECTION_VERSION = "semantic-hybrid-anchored-v1"
MIN_UMAP_TRACKS = 16
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "musicnn_embedding.onnx"
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class MapPoint:
    track_id: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Neighbor:
    track_id: str
    score: float  # Exact cosine similarity in the original vector space.


@dataclass(slots=True)
class SonicMap:
    mode: str  # "musicnn" or "basic-acoustic"; never silently interchangeable.
    projection: str  # "semantic-only" or qualified hybrid/anchored mode.
    points: tuple[MapPoint, ...]
    vectors: dict[str, np.ndarray] = field(repr=False)
    warnings: tuple[str, ...] = ()
    failures: tuple[dict[str, str], ...] = ()
    cache_hits: int = 0
    computed: int = 0
    fallback_reason: str = ""  # model_missing, runtime_missing, model_load_failed, or model_inference_failed.
    layout_metrics: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def track_ids(self) -> tuple[str, ...]:
        return tuple(point.track_id for point in self.points)

    def vector(self, track_id: str) -> np.ndarray:
        return self.vectors[track_id].copy()

    def rank_by_vector(
        self, query: np.ndarray | Sequence[float], *, limit: int = 20,
        exclude_ids: Sequence[str] = (),
    ) -> list[Neighbor]:
        """Rank using exact original-space cosine; ties resolve by track ID."""
        if not self.vectors or limit <= 0:
            return []
        ids = self.track_ids
        matrix = np.stack([self.vectors[track_id] for track_id in ids])
        vector = _unit_vector(np.asarray(query, dtype=np.float32))
        if vector.shape != (matrix.shape[1],):
            raise ValueError("Query vector dimension does not match this map")
        excluded = set(exclude_ids)
        results = [
            Neighbor(track_id, float(score))
            for track_id, score in zip(ids, matrix @ vector)
            if track_id not in excluded
        ]
        results.sort(key=lambda item: (-item.score, item.track_id))
        return results[:limit]

    def similar(self, track_id: str, limit: int = 20) -> list[Neighbor]:
        """Return true vector neighbors, excluding the query song itself."""
        return self.rank_by_vector(self.vectors[track_id], limit=limit, exclude_ids=(track_id,))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unit_vector(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(vector)):
        raise ValueError("Embedding contains non-finite values")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError("Embedding is empty or silent")
    return vector / norm


def _scaled(value: float, center: float, half_range: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(np.clip((value - center) / half_range, -1.0, 1.0))


def basic_acoustic_vector(track: TrackEncoding) -> np.ndarray:
    """Transparent fallback from measured features, not a learned sonic embedding."""
    acoustic = track.acoustic
    chromatic = {name: i for i, name in enumerate(
        ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
    )}
    tonic = chromatic.get(acoustic.key)
    phase = (2 * math.pi * tonic / 12) if tonic is not None else 0.0
    key_weight = max(0.0, min(1.0, acoustic.key_confidence)) if tonic is not None else 0.0
    mode = 1.0 if acoustic.mode == "major" else (-1.0 if acoustic.mode == "minor" else 0.0)
    values = np.array([
        _scaled(acoustic.tempo_bpm, 120, 100),
        _scaled(acoustic.rms_dbfs, -25, 25),
        _scaled(acoustic.dynamic_range_db, 15, 20),
        _scaled(acoustic.spectral_centroid_hz, 3000, 3000),
        _scaled(acoustic.spectral_rolloff_hz, 6500, 6500),
        _scaled(acoustic.high_frequency_ratio or 0.0, 0.15, 0.15),
        _scaled(acoustic.zero_crossing_rate, 0.15, 0.15),
        _scaled(acoustic.percussive_ratio, 0.5, 0.5),
        _scaled(acoustic.onset_rate, 3, 3),
        _scaled(acoustic.harmonic_ratio, 0.5, 0.5),
        key_weight * math.cos(phase),
        key_weight * math.sin(phase),
        key_weight * mode,
    ], dtype=np.float32)
    if not np.any(values):
        # A valid but uninformative record must not be mistaken for a model result.
        values[-1] = 1e-4
    return _unit_vector(values)


def _excerpt_offsets(duration_s: float, excerpt_s: float = 8.0) -> list[float]:
    latest = max(0.0, duration_s - excerpt_s)
    offsets: list[float] = []
    for fraction in (0.08, 0.50, 0.92):
        candidate = round(latest * fraction, 3)
        if all(abs(candidate - old) >= excerpt_s * 0.4 for old in offsets):
            offsets.append(candidate)
    return offsets or [0.0]


def _mel_patches(y: np.ndarray, sr: int) -> np.ndarray:
    """Convert mono 16 kHz audio into non-overlapping [patch,187,96] tensors."""
    import librosa  # Optional model processing should not slow basic-map import.

    if sr != 16_000:
        raise ValueError("MusiCNN input must be 16 kHz")
    y = np.asarray(y, dtype=np.float32)
    minimum_samples = 512 + 256 * (187 - 1)
    if y.size < minimum_samples:
        y = np.pad(y, (0, minimum_samples - y.size))
    y = np.nan_to_num(y)
    if float(np.max(np.abs(y))) < 1e-7:
        raise ValueError("Silent audio excerpt")
    mel = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=512, hop_length=256, n_mels=96,
        window="hann", center=False, power=2.0, norm="slaney", htk=False,
    )
    log_mel = np.log10(1.0 + 10_000.0 * np.maximum(mel, 0.0))
    count = log_mel.shape[1] // 187
    if count < 1:
        raise ValueError("Audio excerpt is too short for a spectrogram patch")
    chunks = [log_mel[:, i * 187:(i + 1) * 187].T for i in range(count)]
    return np.stack(chunks).astype(np.float32)


class _MusicnnEncoder:
    def __init__(self, model_path: Path):
        import onnxruntime as ort  # Lazy: the base app does not require it.

        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise ValueError("Expected a MusiCNN graph with exactly one input")
        self.input_name = inputs[0].name
        shape = inputs[0].shape
        self.transpose = len(shape) == 3 and shape[1:3] == [96, 187]
        if len(shape) != 3 or (not self.transpose and any(
            isinstance(dim, int) and dim != expected
            for dim, expected in zip(shape[1:3], (187, 96))
        )):
            raise ValueError(f"Unsupported MusiCNN input shape: {shape}")

    def encode(self, path: Path, duration_s: float, *, full_track: bool = False) -> np.ndarray:
        import librosa

        patches: list[np.ndarray] = []
        if full_track:
            audio, _ = librosa.load(str(path), sr=16_000, mono=True)
            patches.append(_mel_patches(audio, 16_000))
        else:
            for offset in _excerpt_offsets(duration_s):
                audio, _ = librosa.load(
                    str(path), sr=16_000, mono=True, offset=offset, duration=8.0,
                )
                if audio.size and float(np.max(np.abs(audio))) >= 1e-7:
                    patches.append(_mel_patches(audio, 16_000))
        if not patches:
            raise ValueError("No usable non-silent audio excerpt")
        batch = np.concatenate(patches)
        if self.transpose:
            batch = batch.transpose(0, 2, 1)
        outputs: list[np.ndarray] = []
        for start in range(0, len(batch), 16):
            raw = self.session.run(None, {self.input_name: batch[start:start + 16]})[0]
            embedding = np.asarray(raw, dtype=np.float32).reshape(len(batch[start:start + 16]), -1)
            if embedding.shape[1] != 200:
                raise ValueError(f"Expected a 200-dimensional MusiCNN output, got {embedding.shape[1]}")
            outputs.append(embedding)
        return _unit_vector(np.mean(np.concatenate(outputs), axis=0))


def _cache_file(cache_dir: Path, content_hash: str, mode_key: str) -> Path:
    digest = hashlib.sha256(f"{content_hash}|{mode_key}".encode("utf-8")).hexdigest()
    return cache_dir / "vectors" / f"{digest}.npy"


def _read_vector(path: Path, expected_dim: int | None = None) -> np.ndarray | None:
    try:
        with path.open("rb") as handle:
            vector = np.load(handle, allow_pickle=False)
        if vector.ndim != 1 or (expected_dim is not None and len(vector) != expected_dim):
            return None
        return _unit_vector(vector)
    except (OSError, ValueError, TypeError):
        return None


def _atomic_save_npy(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + f".{uuid.uuid4().hex}.pending")
    try:
        with pending.open("wb") as handle:
            np.save(handle, array)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def project_vectors(
    vectors: Mapping[str, np.ndarray], *, allow_umap: bool = True,
) -> tuple[dict[str, tuple[float, float]], str]:
    """Fit a fresh view; UMAP only for sizeable model-vector catalogs."""
    ids = sorted(vectors)
    if not ids:
        return {}, "none"
    matrix = np.stack([_unit_vector(vectors[track_id]) for track_id in ids])
    if len(ids) == 1:
        coordinates = np.zeros((1, 2), dtype=np.float32)
        method = "single-point"
    elif allow_umap and len(ids) >= MIN_UMAP_TRACKS:
        try:
            import umap  # Lazy optional dependency.

            reducer = umap.UMAP(
                n_components=2, n_neighbors=min(15, len(ids) - 1),
                min_dist=0.18, metric="cosine", random_state=42,
            )
            coordinates = np.asarray(reducer.fit_transform(matrix), dtype=np.float32)
            method = "umap"
        except Exception:
            coordinates = _pca_coordinates(matrix)
            method = "pca"
    else:
        coordinates = _pca_coordinates(matrix)
        method = "pca"
    return {track_id: tuple(map(float, xy)) for track_id, xy in zip(ids, coordinates)}, method


def _pca_coordinates(matrix: np.ndarray) -> np.ndarray:
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    if not np.any(centered):
        return np.zeros((len(matrix), 2), dtype=np.float32)
    _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
    coordinates = centered @ vh[:2].T
    if coordinates.shape[1] == 1:
        coordinates = np.column_stack([coordinates[:, 0], np.zeros(len(matrix))])
    # SVD signs are arbitrary; choose one by the strongest loading in each axis.
    for axis in range(2):
        if axis < len(vh) and vh[axis, np.argmax(np.abs(vh[axis]))] < 0:
            coordinates[:, axis] *= -1
    return coordinates.astype(np.float32)


def _projection_path(cache_dir: Path, mode_key: str) -> Path:
    digest = hashlib.sha256(f"{PROJECTION_VERSION}|{mode_key}".encode()).hexdigest()[:24]
    return cache_dir / f"projection-{digest}.npz"


def _semantic_positions(tracks: Sequence[TrackEncoding], ids: list[str]) -> np.ndarray:
    """Fixed 0–100 BPM and BRI coordinates; no per-library rescaling."""
    by_id = {track.track_id: track for track in tracks}
    lo, hi = STANDARD_RANGES["tempo_bpm"]
    return np.asarray([
        (
            100.0 * np.clip((by_id[track_id].acoustic.tempo_bpm - lo) / (hi - lo), 0.0, 1.0),
            brightness_score(by_id[track_id].acoustic),
        )
        for track_id in ids
    ], dtype=np.float32)


def _average_ranks(values: np.ndarray) -> np.ndarray:
    """Ranks with midranks for tied scores, avoiding a scipy import at map load."""
    _unique, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    mids = (ends - counts + 1 + ends) / 2.0
    return mids[inverse]


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or np.ptp(left) < 1e-9:
        return 1.0  # A constant source dimension has no ordering to disrupt.
    left_rank = _average_ranks(left)
    right_rank = _average_ranks(right)
    if np.ptp(right_rank) < 1e-9:
        return 0.0
    return float(np.corrcoef(left_rank, right_rank)[0, 1])


def _neighbor_overlap(matrix: np.ndarray, coordinates: np.ndarray, k: int = 10) -> float:
    """Mean original-cosine/2-D neighbor intersection, not a similarity score."""
    count = len(matrix)
    if count < 3:
        return 1.0
    neighbors = min(k, count - 1)
    cosine = matrix @ matrix.T
    squared = np.sum((coordinates[:, None, :] - coordinates[None, :, :]) ** 2, axis=2)
    np.fill_diagonal(cosine, -np.inf)
    np.fill_diagonal(squared, np.inf)
    true_order = np.argsort(-cosine, axis=1, kind="stable")[:, :neighbors]
    map_order = np.argsort(squared, axis=1, kind="stable")[:, :neighbors]
    return float(np.mean([
        len(set(true_order[index]) & set(map_order[index])) / neighbors
        for index in range(count)
    ]))


def _layout_metrics(matrix: np.ndarray, semantic: np.ndarray, display: np.ndarray, weight: float) -> dict[str, float | int | str]:
    k = min(10, max(0, len(matrix) - 1))
    return {
        "bpm_axis_spearman": round(_spearman(semantic[:, 0], display[:, 0]), 4),
        "bri_axis_spearman": round(_spearman(semantic[:, 1], display[:, 1]), 4),
        "neighbor_overlap_at_10": round(_neighbor_overlap(matrix, display), 4),
        "semantic_baseline_overlap_at_10": round(_neighbor_overlap(matrix, semantic), 4),
        "blend_weight": weight,
        "neighbor_k": k,
        "axis_scale": "0-100; BPM 60-180 fixed, BRI v2 0-100",
    }


def _align_to_semantic(sound: np.ndarray, semantic: np.ndarray) -> np.ndarray:
    """Orthogonal Procrustes makes an arbitrary UMAP rotation interpretable."""
    source = sound - sound.mean(axis=0)
    target = semantic - semantic.mean(axis=0)
    if np.linalg.norm(source) < 1e-8 or np.linalg.norm(target) < 1e-8:
        return semantic.copy()
    u, singular, vt = np.linalg.svd(source.T @ target)
    rotation = u @ vt
    scale = float(np.sum(singular) / max(np.sum(source ** 2), 1e-12))
    return source @ rotation * scale + semantic.mean(axis=0)


def _choose_hybrid(
    matrix: np.ndarray, semantic: np.ndarray, sound: np.ndarray,
) -> tuple[np.ndarray, str, float]:
    """Add only model-derived movement that improves neighborhood fidelity."""
    baseline = _neighbor_overlap(matrix, semantic)
    # A top-10 overlap is uninformative for a catalog of <=11 songs: everyone
    # is everyone's neighbor.  Keep honest semantic axes in that case.
    if len(matrix) <= 11:
        return semantic.copy(), "semantic-only", 0.0
    aligned = _align_to_semantic(sound, semantic)
    residual = np.clip(aligned - semantic, -20.0, 20.0)
    best = semantic.copy()
    best_overlap = baseline
    best_weight = 0.0
    for weight in (0.1, 0.2, 0.3):
        candidate = np.clip(semantic + weight * residual, 0.0, 100.0)
        if _spearman(semantic[:, 0], candidate[:, 0]) < 0.85:
            continue
        if _spearman(semantic[:, 1], candidate[:, 1]) < 0.85:
            continue
        overlap = _neighbor_overlap(matrix, candidate)
        if overlap > best_overlap + 1e-6:
            best, best_overlap, best_weight = candidate, overlap, weight
    return best, "semantic-hybrid-umap" if best_weight else "semantic-only", best_weight


def _load_projection(path: Path) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, str, float] | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            ids = [str(value) for value in data["ids"]]
            vectors = np.asarray(data["vectors"], dtype=np.float32)
            semantic = np.asarray(data["semantic"], dtype=np.float32)
            coordinates = np.asarray(data["coordinates"], dtype=np.float32)
            method = str(data["method"].item())
            weight = float(data["blend_weight"].item())
        if (
            len(ids) != len(set(ids)) or vectors.ndim != 2 or
            vectors.shape[0] != len(ids) or semantic.shape != (len(ids), 2) or
            coordinates.shape != (len(ids), 2) or not 0.0 <= weight <= 0.3 or
            not np.all(np.isfinite(vectors)) or not np.all(np.isfinite(semantic)) or
            not np.all(np.isfinite(coordinates))
        ):
            return None
        return ids, vectors, semantic, coordinates, method, weight
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_projection(
    path: Path, ids: list[str], matrix: np.ndarray, semantic: np.ndarray,
    coordinates: np.ndarray, method: str, weight: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + f".{uuid.uuid4().hex}.pending")
    try:
        with pending.open("wb") as handle:
            np.savez_compressed(
                handle, ids=np.asarray(ids), vectors=matrix, semantic=semantic,
                coordinates=coordinates, method=np.asarray(method),
                blend_weight=np.asarray(weight),
            )
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _stable_coordinates(
    vectors: Mapping[str, np.ndarray], tracks: Sequence[TrackEncoding],
    projection_path: Path, *, allow_umap: bool,
) -> tuple[dict[str, tuple[float, float]], str, dict[str, float | int | str]]:
    ids = sorted(vectors)
    matrix = np.stack([vectors[track_id] for track_id in ids])
    semantic = _semantic_positions(tracks, ids)
    previous = _load_projection(projection_path) if projection_path.exists() else None
    if previous is not None:
        old_ids, old_matrix, old_semantic, old_xy, old_method, old_weight = previous
        old_by_id = {track_id: i for i, track_id in enumerate(old_ids)}
        positions = {track_id: index for index, track_id in enumerate(ids)}
        anchors = [track_id for track_id in ids if track_id in old_by_id and
                   np.allclose(vectors[track_id], old_matrix[old_by_id[track_id]], atol=1e-6) and
                   np.allclose(semantic[positions[track_id]], old_semantic[old_by_id[track_id]], atol=1e-5)]
        if len(anchors) >= 3:
            display = semantic.copy()
            for track_id in anchors:
                display[positions[track_id]] = old_xy[old_by_id[track_id]]
            if len(anchors) == len(ids):
                return (
                    {track_id: tuple(map(float, display[i])) for i, track_id in enumerate(ids)},
                    old_method, _layout_metrics(matrix, semantic, display, old_weight),
                )
            anchor_vectors = np.stack([vectors[track_id] for track_id in anchors])
            anchor_semantic = np.stack([semantic[positions[track_id]] for track_id in anchors])
            anchor_residual = np.stack([display[positions[track_id]] for track_id in anchors]) - anchor_semantic
            for track_id in ids:
                if track_id in anchors or old_weight == 0.0:
                    continue
                scores = anchor_vectors @ vectors[track_id]
                nearest = np.argsort(-scores, kind="stable")[:min(5, len(scores))]
                weights = np.exp((scores[nearest] - scores[nearest[0]]) / 0.05)
                weights /= weights.sum()
                display[positions[track_id]] = np.clip(
                    semantic[positions[track_id]] + weights @ anchor_residual[nearest], 0.0, 100.0,
                )
            # Never sacrifice semantic axis fidelity merely to keep an
            # interpolated displacement for a newly added song.
            if any(_spearman(semantic[:, axis], display[:, axis]) < 0.85 for axis in (0, 1)):
                for track_id in ids:
                    if track_id not in anchors:
                        display[positions[track_id]] = semantic[positions[track_id]]
            method = f"anchored-{old_method.removeprefix('anchored-')}"
            _save_projection(projection_path, ids, matrix, semantic, display, method, old_weight)
            return (
                {track_id: tuple(map(float, display[i])) for i, track_id in enumerate(ids)},
                method, _layout_metrics(matrix, semantic, display, old_weight),
            )
    display = semantic.copy()
    method = "semantic-only"
    weight = 0.0
    if allow_umap and len(ids) >= MIN_UMAP_TRACKS:
        sound, sound_method = project_vectors(vectors, allow_umap=True)
        if sound_method == "umap":
            sound_array = np.asarray([sound[track_id] for track_id in ids], dtype=np.float32)
            display, method, weight = _choose_hybrid(matrix, semantic, sound_array)
    _save_projection(projection_path, ids, matrix, semantic, display, method, weight)
    return (
        {track_id: tuple(map(float, display[i])) for i, track_id in enumerate(ids)},
        method, _layout_metrics(matrix, semantic, display, weight),
    )


def build_sonic_map(
    tracks: Sequence[TrackEncoding], artifacts: Path, model_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> SonicMap:
    """Index a catalog and return a stable view plus exact cosine search.

    Files are read-only.  Cache is separate from the application's existing
    ``TrackEncoding`` JSON files and keyed by real audio content, model bytes,
    and preprocessing version.  Source files changed since analysis are skipped.
    """
    artifacts = Path(artifacts).resolve()
    cache_dir = artifacts / "sonic_map"
    model_path = Path(model_path or DEFAULT_MODEL_PATH).resolve()
    warnings: list[str] = []
    failures: list[dict[str, str]] = []
    encoder: _MusicnnEncoder | None = None
    fallback_reason = ""
    model_hash = ""
    if not model_path.is_file():
        fallback_reason = "model_missing"
    else:
        try:
            model_hash = _sha256_file(model_path)
            encoder = _MusicnnEncoder(model_path)
        except ImportError:
            fallback_reason = "runtime_missing"
        except Exception as exc:
            fallback_reason = "model_load_failed"
            warnings.append(f"model_load_failed: {type(exc).__name__}: {exc}")
    mode = "musicnn" if encoder is not None else "basic-acoustic"
    if fallback_reason:
        warnings.append(f"basic_acoustic_fallback:{fallback_reason}")
    mode_key = (
        f"musicnn|{MUSICNN_PREPROCESS_VERSION}|{model_hash}"
        if encoder is not None else f"basic|{BASIC_VECTOR_VERSION}"
    )
    vectors: dict[str, np.ndarray] = {}
    cache_hits = 0
    computed = 0
    ordered_tracks = sorted(tracks, key=lambda track: track.track_id)
    for index, track in enumerate(ordered_tracks, 1):
        if progress:
            progress(index - 1, len(ordered_tracks), Path(track.source_path).name)
        path = Path(track.source_path)
        try:
            if not path.is_file():
                raise FileNotFoundError("Source audio file is missing")
            actual_hash = _sha256_file(path)
            if actual_hash != track.source_sha256:
                raise ValueError("Source audio changed; re-analyze the library first")
            vector_file = _cache_file(cache_dir, actual_hash, mode_key + (f"|{track.engine_version}" if encoder is None else ""))
            vector = _read_vector(vector_file, expected_dim=200 if encoder else 13)
            if vector is None:
                vector = encoder.encode(path, track.acoustic.duration_s) if encoder else basic_acoustic_vector(track)
                _atomic_save_npy(vector_file, vector)
                computed += 1
            else:
                cache_hits += 1
            vectors[track.track_id] = vector
        except Exception as exc:
            failures.append({"track_id": track.track_id, "path": str(path),
                             "reason": f"{type(exc).__name__}: {exc}"})
    if progress:
        progress(len(ordered_tracks), len(ordered_tracks), "done")
    if not vectors and encoder is not None:
        # A graph that cannot infer any song should never produce a blank
        # supposedly model-derived map when the catalog itself is usable.
        fallback = build_sonic_map(tracks, artifacts, model_path=Path("__missing_musicnn_model__"), progress=progress)
        fallback.fallback_reason = "model_inference_failed"
        fallback.warnings = tuple(
            warning for warning in fallback.warnings if not warning.startswith("basic_acoustic_fallback:")
        ) + (f"basic_acoustic_fallback:model_inference_failed:{len(failures)}",)
        return fallback
    if vectors:
        coordinates, projection, layout_metrics = _stable_coordinates(
            vectors, tracks,
            _projection_path(cache_dir, f"{mode_key}|{ENGINE_VERSION}|{TAXONOMY_VERSION}"),
            allow_umap=mode == "musicnn",
        )
    else:
        coordinates, projection, layout_metrics = {}, "none", {}
    points = tuple(MapPoint(track_id, *coordinates[track_id]) for track_id in sorted(coordinates))
    if projection.startswith("anchored-"):
        warnings.append("existing_points_preserved_new_points_semantic_anchored")
        if (
            layout_metrics.get("blend_weight", 0.0) > 0.0 and
            layout_metrics["neighbor_overlap_at_10"] <=
            layout_metrics["semantic_baseline_overlap_at_10"]
        ):
            warnings.append("anchored_hybrid_no_longer_improves_neighborhoods")
    if layout_metrics and (
        layout_metrics["bpm_axis_spearman"] < 0.85 or
        layout_metrics["bri_axis_spearman"] < 0.85
    ):
        warnings.append("axis_fidelity_below_threshold_in_preserved_layout")
    if mode == "musicnn" and projection.removeprefix("anchored-") == "semantic-only":
        warnings.append("no_neighborhood_gain_from_hybrid_semantic_layout_used")
    weak_tempo = sum(
        track.acoustic.tempo_confidence < 0.65
        for track in tracks if track.track_id in coordinates
    )
    if weak_tempo:
        warnings.append(f"low_tempo_confidence:{weak_tempo}")
    legacy_brightness = sum(
        track.acoustic.high_frequency_ratio is None
        for track in tracks if track.track_id in coordinates
    )
    if legacy_brightness:
        warnings.append(f"legacy_brightness_missing_high_frequency_ratio:{legacy_brightness}")
    return SonicMap(
        mode=mode, projection=projection, points=points, vectors=vectors,
        warnings=tuple(warnings), failures=tuple(failures), cache_hits=cache_hits,
        computed=computed, fallback_reason=fallback_reason, layout_metrics=layout_metrics,
    )
