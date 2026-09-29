from __future__ import annotations

import numpy as np

from musefolders.exploration import (
    ExplorationConstraints, similar_tracks, song_alchemy, song_path,
)
from musefolders.models import AcousticFeatures, TrackEncoding, TrackMetadata
from musefolders.playlist_filters import PlaylistFilters


def track(track_id: str, artist: str = "Artist", *, digest: str | None = None,
          instrument: str = "unknown") -> TrackEncoding:
    return TrackEncoding(
        track_id=track_id, source_path=f"/music/{track_id}.mp3", source_size=1,
        source_mtime_ns=1, source_sha256=digest or track_id,
        metadata=TrackMetadata(title=track_id, artist=artist),
        acoustic=AcousticFeatures(
            duration_s=30, tempo_bpm=120, tempo_confidence=1, rms_dbfs=-15,
            dynamic_range_db=10, spectral_centroid_hz=2000, spectral_rolloff_hz=3500,
            zero_crossing_rate=.05, percussive_ratio=.5, onset_rate=2,
            harmonic_ratio=.5, key="C", mode="major", key_confidence=.8, analyzed_audio_s=30,
        ), instrument=instrument,
    )


def test_similar_ranks_by_original_cosine_then_deduplicates_and_caps_artist() -> None:
    tracks = [
        track("seed", "Starter"), track("near", "A"), track("duplicate", "A", digest="near"),
        track("second", "A"), track("third", "A"), track("other", "B"),
    ]
    embeddings = {
        "seed": [1, 0, 0], "near": [1, .01, 0], "duplicate": [1, .011, 0],
        "second": [1, .02, 0], "third": [1, .03, 0], "other": [.9, .1, 0],
    }
    result = similar_tracks(tracks, embeddings, "seed", limit=4)
    assert result.track_ids == ("near", "second", "other")
    assert result.reason_code == "shortfall"
    assert result.scores["near"] > result.scores["second"] > result.scores["other"]


def test_similar_honours_hard_filters_exclusions_and_never_guesses_instrumental() -> None:
    tracks = [track("seed", "S"), track("piano", "A", instrument="piano"),
              track("verified", "B", instrument="piano"), track("voice", "C", instrument="voice")]
    embeddings = {item.track_id: [1, .1 * index] for index, item in enumerate(tracks)}
    strict = ExplorationConstraints(
        require_instrumental=True, verified_instrumental_ids=frozenset({"verified"}),
    )
    assert similar_tracks(tracks, embeddings, "seed", constraints=strict).track_ids == ("verified",)
    excluded = ExplorationConstraints(
        filters=PlaylistFilters(artists=frozenset({"B"})),
        excluded_track_ids=frozenset({"verified"}),
    )
    result = similar_tracks(tracks, embeddings, "seed", constraints=excluded)
    assert result.is_empty and result.reason_code == "no_candidates"


def test_similar_rejects_unusable_embedding_or_unrelated_threshold() -> None:
    tracks = [track("seed"), track("other")]
    assert similar_tracks(tracks, {"seed": [0, 0], "other": [1, 0]}, "seed").reason_code == "anchor_missing_embedding"
    result = similar_tracks(tracks, {"seed": [1, 0], "other": [0, 1]}, "seed", minimum_similarity=.3)
    assert result.reason_code == "no_candidates"


def test_path_uses_real_tracks_and_bounded_adjacent_similarity() -> None:
    tracks = [track("start", "A"), track("middle", "B"), track("end", "C")]
    embeddings = {"start": [1, 0], "middle": [1, 1], "end": [0, 1]}
    result = song_path(tracks, embeddings, "start", "end", length=3, minimum_alignment=.6)
    assert result.track_ids == ("start", "middle", "end")
    assert result.reason_code == "ok"
    assert song_path(tracks, embeddings, "start", "end", length=3, minimum_alignment=.9).reason_code == "no_path"


def test_path_shortfall_and_filtered_endpoint_are_explicit() -> None:
    tracks = [track("start", "A"), track("end", "B")]
    embeddings = {"start": [1, 0], "end": [1, 0.1]}
    result = song_path(tracks, embeddings, "start", "end", length=5)
    assert result.track_ids == ("start", "end")
    assert result.reason_code == "shortfall"
    constrained = ExplorationConstraints(filters=PlaylistFilters(artists=frozenset({"A"})))
    assert song_path(tracks, embeddings, "start", "end", constraints=constrained).reason_code == "anchor_filtered"


def test_path_does_not_repeat_audio_content() -> None:
    tracks = [track("start", "A"), track("copy", "B", digest="start"), track("end", "C")]
    embeddings = {item.track_id: np.array([1, 0]) for item in tracks}
    result = song_path(tracks, embeddings, "start", "end", length=3)
    assert result.track_ids == ("start", "end")


def test_alchemy_positive_centroid_and_negative_nearest_percentile() -> None:
    tracks = [track("positive", "P"), track("negative", "N"), track("near_positive", "A"),
              track("middle", "B"), track("near_negative", "C")]
    embeddings = {
        "positive": [1, 0], "negative": [0, 1],
        "near_positive": [.95, .05], "middle": [.7, .7], "near_negative": [.05, .95],
    }
    result = song_alchemy(tracks, embeddings, ["positive"], negative_ids=["negative"],
                          limit=3, negative_exclusion_percentile=75)
    assert result.track_ids == ("near_positive", "middle")
    assert result.reason_code == "shortfall"
    assert "near_negative" not in result.track_ids


def test_alchemy_invalid_negative_anchor_is_not_silently_ignored() -> None:
    tracks = [track("positive"), track("negative"), track("candidate")]
    result = song_alchemy(tracks, {"positive": [1, 0], "candidate": [1, 0]},
                          ["positive"], negative_ids=["negative"])
    assert result.reason_code == "anchor_missing_embedding"


def test_alchemy_zero_negative_exclusion_retains_candidates() -> None:
    tracks = [track("positive"), track("negative"), track("near_negative")]
    embeddings = {
        "positive": [1, 0], "negative": [0, 1], "near_negative": [.6, .8],
    }
    result = song_alchemy(
        tracks, embeddings, ["positive"], negative_ids=["negative"],
        negative_exclusion_percentile=100, limit=1,
    )
    assert result.track_ids == ("near_negative",)
    assert result.reason_code == "ok"


def test_alchemy_weighted_centroid_changes_rank() -> None:
    tracks = [track("p1"), track("p2"), track("toward_p1"), track("toward_p2")]
    embeddings = {"p1": [1, 0], "p2": [0, 1], "toward_p1": [.8, .2], "toward_p2": [.2, .8]}
    result = song_alchemy(tracks, embeddings, ["p1", "p2"], positive_weights=[4, 1], limit=2)
    assert result.track_ids[0] == "toward_p1"
