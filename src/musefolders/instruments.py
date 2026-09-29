"""Conservative, offline instrument inference from Google's YAMNet AudioSet model.

The result is an audible-source hint, not source separation or a verified credit.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import librosa
import numpy as np


MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "yamnet.tflite"

# Use only music-relevant YAMNet classes. Broad classes are deliberate fallbacks.
CLASS_GROUPS = {
    "voice": {"Singing", "Choir", "Child singing", "Vocal music", "A capella", "Humming", "Rapping"},
    "piano": {"Piano", "Electric piano"},
    "guitar": {"Guitar", "Acoustic guitar", "Electric guitar", "Bass guitar"},
    "strings": {"Bowed string instrument", "String section", "Violin, fiddle", "Cello", "Double bass", "Plucked string instrument", "Harp"},
    "wind": {"Wind instrument, woodwind instrument", "Flute", "Saxophone", "Clarinet", "Brass instrument", "Trumpet", "Trombone", "French horn"},
    "percussion": {"Percussion", "Drum kit", "Drum machine", "Drum", "Mallet percussion", "Marimba, xylophone", "Vibraphone"},
    "synthesizer": {"Synthesizer", "Keyboard (musical)", "Electronic organ", "Organ"},
}


@lru_cache(maxsize=1)
def _classifier():
    if not MODEL_PATH.is_file():
        return None
    import mediapipe as mp

    options = mp.tasks.audio.AudioClassifierOptions(
        # A byte buffer avoids native-library file-path decoding failures on Windows
        # when the project lives under a non-ASCII directory.
        base_options=mp.tasks.BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
        max_results=-1,
    )
    return mp.tasks.audio.AudioClassifier.create_from_options(options)


def summarize_scores(frames: list[dict[str, float]]) -> tuple[str, float, str]:
    """Return one dominant family only when repeated frames support it."""
    if not frames:
        return "unknown", 0.0, "uncertain"
    strengths: dict[str, float] = {}
    for group, classes in CLASS_GROUPS.items():
        values = np.asarray([max((frame.get(name, 0.0) for name in classes), default=0.0) for frame in frames])
        # Mean over all sampled frames avoids declaring a brief solo dominant.
        strengths[group] = float(np.mean(values))
    ordered = sorted(strengths.items(), key=lambda pair: pair[1], reverse=True)
    winner, score = ordered[0]
    runner_up = ordered[1][1]
    threshold = 0.16 if winner in {"voice", "piano"} else 0.20
    if score < threshold or score - runner_up < 0.04:
        return "unknown", round(score, 3), "uncertain"
    return winner, round(score, 3), "model_estimate"


def detect_instrument(path: Path) -> tuple[str, float, str]:
    """Analyze two short portions locally; never infer an instrument from metadata."""
    try:
        classifier = _classifier()
        if classifier is None:
            return "unknown", 0.0, "unavailable"
        import mediapipe as mp

        duration = librosa.get_duration(path=str(path))
        offsets = [min(8.0, max(0.0, duration - 8.0))]
        middle = max(0.0, duration / 2 - 4.0)
        if abs(middle - offsets[0]) > 4.0:
            offsets.append(middle)
        frames: list[dict[str, float]] = []
        for offset in offsets:
            samples, rate = librosa.load(str(path), sr=16_000, mono=True, offset=offset, duration=8.0)
            if len(samples) < 4_000:
                continue
            audio = mp.tasks.components.containers.AudioData.create_from_array(
                samples.astype(np.float32), sample_rate=rate,
            )
            for result in classifier.classify(audio):
                if result.classifications:
                    frames.append({item.category_name: item.score for item in result.classifications[0].categories})
        return summarize_scores(frames)
    except Exception:
        # Analysis of tempo/key can still succeed if the optional model fails.
        return "unknown", 0.0, "unavailable"
