"""Pure, explainable playlist exploration over original sound embeddings.

The vectors supplied here are *not* 2-D map coordinates. A projection is useful
for browsing, but ranking and paths must use the source acoustic embeddings.
The module never reads, alters, or copies a music file.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from .models import TrackEncoding
from .playlist_filters import PlaylistFilters, matches


@dataclass(frozen=True)
class ExplorationConstraints:
    """Hard conditions applied before ranking; unknown is never "instrumental"."""

    filters: PlaylistFilters = field(default_factory=PlaylistFilters)
    excluded_track_ids: frozenset[str] = frozenset()
    require_instrumental: bool = False
    verified_instrumental_ids: frozenset[str] = frozenset()
    max_per_artist: int = 2


@dataclass(frozen=True)
class ExplorationResult:
    track_ids: tuple[str, ...]
    scores: dict[str, float]
    reason_code: str
    eligible_count: int
    requested_count: int

    @property
    def is_empty(self) -> bool:
        return not self.track_ids


def _normal_vector(value: object, dimension: int | None = None) -> np.ndarray | None:
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if vector.ndim != 1 or not vector.size or (dimension is not None and vector.size != dimension):
        return None
    if not np.all(np.isfinite(vector)):
        return None
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        return None
    return vector / norm


def _content_key(track: TrackEncoding) -> str:
    return track.source_sha256 or f"track:{track.track_id}"


def _artist_key(track: TrackEncoding) -> str:
    return track.metadata.artist.strip().casefold()


def _allowed(track: TrackEncoding, constraints: ExplorationConstraints) -> bool:
    return (
        track.track_id not in constraints.excluded_track_ids
        and matches(track, constraints.filters)
        and (not constraints.require_instrumental or track.track_id in constraints.verified_instrumental_ids)
    )


def _candidate_vectors(
    tracks: Sequence[TrackEncoding], embeddings: Mapping[str, Sequence[float] | np.ndarray],
    constraints: ExplorationConstraints, dimension: int,
) -> tuple[dict[str, TrackEncoding], dict[str, np.ndarray]]:
    eligible = {track.track_id: track for track in tracks if _allowed(track, constraints)}
    vectors = {}
    for track_id in eligible:
        if track_id in embeddings:
            vector = _normal_vector(embeddings[track_id], dimension)
            if vector is not None:
                vectors[track_id] = vector
    return eligible, vectors


def _result(ids: Sequence[str], scores: Mapping[str, float], eligible: int, requested: int,
            *, empty_reason: str = "no_candidates") -> ExplorationResult:
    if not ids:
        reason = empty_reason
    elif len(ids) < requested:
        reason = "shortfall"
    else:
        reason = "ok"
    return ExplorationResult(tuple(ids), {key: round(float(scores[key]), 6) for key in ids}, reason, eligible, requested)


def _failure(reason: str, requested: int, eligible: int = 0) -> ExplorationResult:
    return ExplorationResult((), {}, reason, eligible, requested)


def _take_ranked(
    ranked: Sequence[tuple[str, float]], tracks: Mapping[str, TrackEncoding], limit: int,
    constraints: ExplorationConstraints, *, reserved_hashes: frozenset[str] = frozenset(),
) -> tuple[list[str], dict[str, float]]:
    chosen: list[str] = []
    scores: dict[str, float] = {}
    hashes = set(reserved_hashes)
    artists: Counter[str] = Counter()
    for track_id, score in sorted(ranked, key=lambda item: (-item[1], item[0])):
        track = tracks[track_id]
        content = _content_key(track)
        artist = _artist_key(track)
        if content in hashes or (artist and artists[artist] >= constraints.max_per_artist):
            continue
        chosen.append(track_id)
        scores[track_id] = score
        hashes.add(content)
        if artist:
            artists[artist] += 1
        if len(chosen) >= limit:
            break
    return chosen, scores


def similar_tracks(
    tracks: Sequence[TrackEncoding], embeddings: Mapping[str, Sequence[float] | np.ndarray], seed_id: str,
    *, limit: int = 20, constraints: ExplorationConstraints = ExplorationConstraints(),
    minimum_similarity: float = 0.0,
) -> ExplorationResult:
    """Find exact cosine neighbours, without self, duplicate audio, or blind fill."""
    if limit < 1 or constraints.max_per_artist < 1 or not -1 <= minimum_similarity <= 1:
        return _failure("invalid_parameters", limit)
    by_id = {track.track_id: track for track in tracks}
    if seed_id not in by_id:
        return _failure("unknown_anchor", limit)
    anchor = _normal_vector(embeddings.get(seed_id))
    if anchor is None:
        return _failure("anchor_missing_embedding", limit)
    eligible, vectors = _candidate_vectors(tracks, embeddings, constraints, anchor.size)
    ranked = [
        (track_id, float(np.dot(anchor, vector))) for track_id, vector in vectors.items()
        if track_id != seed_id and float(np.dot(anchor, vector)) >= minimum_similarity
    ]
    chosen, scores = _take_ranked(
        ranked, eligible, limit, constraints, reserved_hashes=frozenset({_content_key(by_id[seed_id])}),
    )
    return _result(chosen, scores, len(vectors), limit)


def song_path(
    tracks: Sequence[TrackEncoding], embeddings: Mapping[str, Sequence[float] | np.ndarray],
    start_id: str, end_id: str, *, length: int = 8,
    constraints: ExplorationConstraints = ExplorationConstraints(), minimum_alignment: float = 0.5,
) -> ExplorationResult:
    """Build a real-song route guided by normalized interpolation between A and B.

    Adjacent songs and each interpolated waypoint must clear minimum_alignment.
    A bounded beam search avoids adding distant songs merely to fill a path.
    """
    if length < 2 or constraints.max_per_artist < 1 or not -1 <= minimum_alignment <= 1:
        return _failure("invalid_parameters", length)
    by_id = {track.track_id: track for track in tracks}
    if start_id not in by_id or end_id not in by_id:
        return _failure("unknown_anchor", length)
    if start_id == end_id or _content_key(by_id[start_id]) == _content_key(by_id[end_id]):
        return _failure("same_content", length)
    if not _allowed(by_id[start_id], constraints) or not _allowed(by_id[end_id], constraints):
        return _failure("anchor_filtered", length)
    start = _normal_vector(embeddings.get(start_id))
    end = _normal_vector(embeddings.get(end_id), start.size if start is not None else None)
    if start is None or end is None:
        return _failure("anchor_missing_embedding", length)
    eligible, vectors = _candidate_vectors(tracks, embeddings, constraints, start.size)
    start_artist, end_artist = _artist_key(by_id[start_id]), _artist_key(by_id[end_id])
    endpoint_artists = Counter(artist for artist in (start_artist, end_artist) if artist)
    if any(count > constraints.max_per_artist for count in endpoint_artists.values()):
        return _failure("anchor_artist_limit", length, len(vectors))
    endpoints = frozenset({_content_key(by_id[start_id]), _content_key(by_id[end_id])})
    others = [track_id for track_id in vectors if track_id not in {start_id, end_id}
              and _content_key(by_id[track_id]) not in endpoints]
    # Beam item: (track IDs, accumulated alignment, waypoint scores, used hashes, artist counts).
    beam = [((start_id,), 0.0, {start_id: 1.0}, endpoints, endpoint_artists)]
    completed: list[tuple[tuple[str, ...], float, dict[str, float]]] = []
    for step in range(1, length):
        fraction = step / (length - 1)
        waypoint = _normal_vector((1 - fraction) * start + fraction * end)
        if waypoint is None:
            # Opposite vectors have no midpoint direction: no fabricated route.
            return _failure("no_path", length, len(vectors))
        expanded = []
        for ids, total, scores, hashes, artists in beam:
            previous = vectors[ids[-1]]
            edge_to_end = float(np.dot(previous, end))
            if edge_to_end >= minimum_alignment:
                completed.append((ids + (end_id,), total + edge_to_end, {**scores, end_id: edge_to_end}))
            if step == length - 1:
                continue
            for track_id in others:
                track = by_id[track_id]
                content = _content_key(track)
                artist = _artist_key(track)
                if content in hashes or (artist and artists[artist] >= constraints.max_per_artist):
                    continue
                vector = vectors[track_id]
                edge = float(np.dot(previous, vector))
                alignment = float(np.dot(waypoint, vector))
                if edge < minimum_alignment or alignment < minimum_alignment:
                    continue
                next_artists = artists.copy()
                if artist:
                    next_artists[artist] += 1
                quality = 0.7 * alignment + 0.3 * edge
                expanded.append((ids + (track_id,), total + quality,
                                 {**scores, track_id: alignment}, hashes | {content}, next_artists))
        expanded.sort(key=lambda item: (-item[1], item[0]))
        beam = expanded[:64]
        if not beam:
            break
    if not completed:
        return _failure("no_path", length, len(vectors))
    ids, _, scores = min(completed, key=lambda item: (-len(item[0]), -item[1], item[0]))
    return _result(ids, scores, len(vectors), length)


def song_alchemy(
    tracks: Sequence[TrackEncoding], embeddings: Mapping[str, Sequence[float] | np.ndarray],
    positive_ids: Sequence[str], *, positive_weights: Sequence[float] | None = None,
    negative_ids: Sequence[str] = (), limit: int = 20,
    constraints: ExplorationConstraints = ExplorationConstraints(),
    negative_exclusion_percentile: float = 85.0, minimum_similarity: float = 0.0,
) -> ExplorationResult:
    """Mix liked anchors and remove songs nearest to disliked anchors.

    The exclusion percentile is computed within the eligible candidate set;
    85 means the 15% most similar to a negative anchor are excluded.
    """
    if (limit < 1 or constraints.max_per_artist < 1 or not positive_ids
            or len(set(positive_ids)) != len(positive_ids)
            or not 0 <= negative_exclusion_percentile <= 100
            or not -1 <= minimum_similarity <= 1):
        return _failure("invalid_parameters", limit)
    weights = [1.0] * len(positive_ids) if positive_weights is None else list(positive_weights)
    if (len(weights) != len(positive_ids) or not all(np.isfinite(w) and w > 0 for w in weights)):
        return _failure("invalid_parameters", limit)
    by_id = {track.track_id: track for track in tracks}
    if any(track_id not in by_id for track_id in (*positive_ids, *negative_ids)):
        return _failure("unknown_anchor", limit)
    first = _normal_vector(embeddings.get(positive_ids[0]))
    if first is None:
        return _failure("anchor_missing_embedding", limit)
    dimension = first.size
    positive = [_normal_vector(embeddings.get(track_id), dimension) for track_id in positive_ids]
    negative = [_normal_vector(embeddings.get(track_id), dimension) for track_id in negative_ids]
    if any(vector is None for vector in (*positive, *negative)):
        return _failure("anchor_missing_embedding", limit)
    centroid = _normal_vector(sum(weight * vector for weight, vector in zip(weights, positive)))
    if centroid is None:
        return _failure("incompatible_anchors", limit)
    eligible, vectors = _candidate_vectors(tracks, embeddings, constraints, dimension)
    anchors = set(positive_ids) | set(negative_ids)
    anchor_hashes = frozenset(_content_key(by_id[track_id]) for track_id in anchors)
    candidate_ids = [track_id for track_id in vectors if track_id not in anchors
                     and _content_key(by_id[track_id]) not in anchor_hashes]
    # A 100th-percentile cutoff represents 0% exclusion in the UI. Do not
    # remove the maximum (or every song when similarities happen to tie).
    if negative and candidate_ids and negative_exclusion_percentile < 100:
        negative_similarities = {
            track_id: max(float(np.dot(vectors[track_id], vector)) for vector in negative)
            for track_id in candidate_ids
        }
        cutoff = float(np.percentile(list(negative_similarities.values()), negative_exclusion_percentile))
        candidate_ids = [track_id for track_id in candidate_ids if negative_similarities[track_id] < cutoff]
    ranked = [(track_id, float(np.dot(centroid, vectors[track_id]))) for track_id in candidate_ids]
    chosen, scores = _take_ranked(
        [(track_id, score) for track_id, score in ranked if score >= minimum_similarity],
        eligible, limit, constraints, reserved_hashes=anchor_hashes,
    )
    return _result(chosen, scores, len(vectors), limit)
