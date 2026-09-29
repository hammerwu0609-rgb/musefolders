from __future__ import annotations

from musefolders.instruments import summarize_scores


def test_instrument_requires_repeated_evidence() -> None:
    assert summarize_scores([{"Piano": 0.8}] + [{}] * 15)[0] == "unknown"
    label, score, status = summarize_scores([{"Piano": 0.42, "Singing": 0.03}] * 10)
    assert (label, status) == ("piano", "model_estimate")
    assert score > 0.4


def test_broad_family_and_ambiguous_mix() -> None:
    assert summarize_scores([{"Flute": 0.5, "Piano": 0.02}] * 10)[0] == "wind"
    assert summarize_scores([{"Piano": 0.35, "Singing": 0.34}] * 10)[0] == "unknown"
