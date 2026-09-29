from __future__ import annotations

import hashlib
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from .metadata import read_metadata
from .models import AcousticFeatures, ENGINE_VERSION, TONIC_NAMES, TrackEncoding


SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"}
PROTECTED_EXTENSIONS = {".mgg", ".qmc0", ".qmc3", ".qmcflac", ".kgm", ".ncm"}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def track_instance_id(path: Path, source_hash: str) -> str:
    """Identify one file instance while keeping content identity separately."""
    raw = f"{source_hash}|{path.resolve()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _duration(path: Path) -> float:
    try:
        return float(sf.info(path).duration)
    except Exception:
        return float(librosa.get_duration(path=str(path)))


def _segment_offsets(duration: float, segment_s: float) -> list[float]:
    if duration <= segment_s + 1:
        return [0.0]
    usable_end = max(0.0, duration - segment_s)
    candidates = [min(8.0, usable_end), max(0.0, duration / 2 - segment_s / 2), usable_end]
    out: list[float] = []
    for value in candidates:
        value = round(value, 3)
        if all(abs(value - previous) > segment_s * 0.4 for previous in out):
            out.append(value)
    return out


def _safe_scalar(value: object, default: float = 0.0) -> float:
    arr = np.asarray(value, dtype=float).reshape(-1)
    return float(arr[0]) if arr.size and np.isfinite(arr[0]) else default


def _key_and_mode(chroma: np.ndarray) -> tuple[str, str, float]:
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    pitch = np.mean(chroma, axis=1)
    if not np.any(pitch):
        return "未知", "unknown", 0.0
    pitch = (pitch - pitch.mean()) / (pitch.std() + 1e-9)
    scores: list[tuple[float, int, str]] = []
    for tonic in range(12):
        for profile, mode in ((major, "major"), (minor, "minor")):
            rolled = np.roll(profile, tonic)
            rolled = (rolled - rolled.mean()) / (rolled.std() + 1e-9)
            scores.append((float(np.dot(pitch, rolled) / len(pitch)), tonic, mode))
    scores.sort(reverse=True)
    best, tonic, mode = scores[0]
    second = scores[1][0]
    confidence = float(np.clip((best - second + 0.08) / 0.35, 0.0, 1.0))
    return TONIC_NAMES[tonic], mode, confidence


def _extract_segment(y: np.ndarray, sr: int) -> dict[str, float | np.ndarray]:
    if y.size < sr:
        y = np.pad(y, (0, sr - y.size))
    y = np.nan_to_num(y.astype(np.float32), copy=False)
    peak = float(np.max(np.abs(y)))
    if peak < 1e-7:
        raise ValueError("音频片段接近静音")

    hop = 512
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    rms_db = librosa.amplitude_to_db(np.maximum(rms, 1e-8), ref=1.0)
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop, units="frames")
    tempo_value = _safe_scalar(tempo)
    beat_strength = float(np.mean(onset[beats])) if len(beats) else 0.0
    onset_mean = float(np.mean(onset)) + 1e-9
    tempo_confidence = float(np.clip(beat_strength / (onset_mean * 3.0), 0.0, 1.0))
    onset_events = librosa.onset.onset_detect(onset_envelope=onset, sr=sr, hop_length=hop)

    # Reuse the same spectrum for the three brightness measurements.  A frame
    # with only near-silence must not dominate the high-frequency proportion.
    spectrum = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    centroid = librosa.feature.spectral_centroid(S=spectrum, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=spectrum, sr=sr, roll_percent=0.85)[0]
    power = np.square(spectrum, dtype=np.float64)
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=2048)
    broadband = np.sum(power[frequencies >= 80], axis=0)
    highband = np.sum(power[frequencies >= 3000], axis=0)
    usable = broadband > max(float(np.max(broadband)) * 0.01, 1e-12)
    high_frequency_ratio = (
        float(np.median(highband[usable] / broadband[usable])) if np.any(usable) else 0.0
    )
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=2048, hop_length=hop)[0]
    harmonic, percussive = librosa.effects.hpss(y)
    harmonic_energy = float(np.mean(harmonic**2))
    percussive_energy = float(np.mean(percussive**2))
    total_hp = harmonic_energy + percussive_energy + 1e-12
    chroma = librosa.feature.chroma_stft(y=harmonic, sr=sr, hop_length=hop)
    return {
        "tempo": tempo_value,
        "tempo_confidence": tempo_confidence,
        "rms_db": float(np.mean(rms_db)),
        "dynamic_range": float(np.percentile(rms_db, 90) - np.percentile(rms_db, 10)),
        "centroid": float(np.median(centroid)),
        "rolloff": float(np.median(rolloff)),
        "high_frequency_ratio": float(np.clip(high_frequency_ratio, 0.0, 1.0)),
        "zcr": float(np.median(zcr)),
        "percussive_ratio": percussive_energy / total_hp,
        "harmonic_ratio": harmonic_energy / total_hp,
        "onset_rate": len(onset_events) / max(len(y) / sr, 1e-9),
        "chroma": chroma,
    }


def extract_acoustic_features(path: Path, sample_rate: int = 22_050, segment_s: float = 24.0) -> AcousticFeatures:
    duration = _duration(path)
    offsets = _segment_offsets(duration, segment_s)
    segments: list[dict[str, float | np.ndarray]] = []
    for offset in offsets:
        y, sr = librosa.load(str(path), sr=sample_rate, mono=True, offset=offset, duration=segment_s)
        segments.append(_extract_segment(y, sr))

    numeric_keys = [
        "tempo", "tempo_confidence", "rms_db", "dynamic_range", "centroid", "rolloff",
        "high_frequency_ratio", "zcr", "percussive_ratio", "harmonic_ratio", "onset_rate",
    ]
    aggregated = {key: float(np.median([float(segment[key]) for segment in segments])) for key in numeric_keys}
    all_chroma = np.concatenate([np.asarray(segment["chroma"]) for segment in segments], axis=1)
    key, mode, key_conf = _key_and_mode(all_chroma)
    return AcousticFeatures(
        duration_s=round(duration, 3),
        tempo_bpm=round(aggregated["tempo"], 2),
        tempo_confidence=round(aggregated["tempo_confidence"], 3),
        rms_dbfs=round(aggregated["rms_db"], 3),
        dynamic_range_db=round(aggregated["dynamic_range"], 3),
        spectral_centroid_hz=round(aggregated["centroid"], 2),
        spectral_rolloff_hz=round(aggregated["rolloff"], 2),
        zero_crossing_rate=round(aggregated["zcr"], 5),
        percussive_ratio=round(aggregated["percussive_ratio"], 4),
        onset_rate=round(aggregated["onset_rate"], 4),
        harmonic_ratio=round(aggregated["harmonic_ratio"], 4),
        key=key,
        mode=mode,
        key_confidence=round(key_conf, 3),
        analyzed_audio_s=round(min(duration, segment_s * len(offsets)), 2),
        high_frequency_ratio=round(aggregated["high_frequency_ratio"], 5),
    )


def analyze_track(path: Path) -> TrackEncoding:
    stat = path.stat()
    source_hash = sha256_file(path)
    metadata = read_metadata(path)
    acoustic = extract_acoustic_features(path)
    return TrackEncoding(
        track_id=track_instance_id(path, source_hash),
        source_path=str(path.resolve()),
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        source_sha256=source_hash,
        metadata=metadata,
        acoustic=acoustic,
        source_ctime_ns=stat.st_ctime_ns,
    )

