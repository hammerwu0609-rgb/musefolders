import numpy as np

from musefolders.audio import _extract_segment


def test_high_frequency_ratio_distinguishes_low_and_high_tones() -> None:
    sr = 22_050
    time = np.arange(sr, dtype=np.float32) / sr
    low = 0.4 * np.sin(2 * np.pi * 440 * time)
    high = 0.4 * np.sin(2 * np.pi * 5000 * time)

    low_features = _extract_segment(low, sr)
    high_features = _extract_segment(high, sr)

    assert 0.0 <= low_features["high_frequency_ratio"] <= 1.0
    assert 0.0 <= high_features["high_frequency_ratio"] <= 1.0
    assert high_features["high_frequency_ratio"] > low_features["high_frequency_ratio"] + 0.5
    assert high_features["centroid"] > low_features["centroid"]
    assert high_features["rolloff"] > low_features["rolloff"]
