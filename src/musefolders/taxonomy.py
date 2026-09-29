from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from .models import AcousticFeatures, FolderProposal, StandardScores, TONIC_NAMES, TrackEncoding


NAMING_MODES = {
    "poetic": "意象主名 + 可核验声学副名",
    "style": "风格倾向 + 物理特征",
    "quant": "纯量化",
}

# Fixed physical ranges make one song score the same in different libraries.
# Values outside a range are clipped instead of moving the reference scale.
STANDARD_RANGES = {
    "tempo_bpm": (60.0, 180.0),
    "rms_dbfs": (-38.0, -10.0),
    "percussive_ratio": (0.0, 0.5),
    "onset_rate": (0.5, 6.0),
    "spectral_centroid_hz": (500.0, 4500.0),
    "spectral_rolloff_hz": (2000.0, 9000.0),
    "high_frequency_ratio": (0.01, 0.30),
}

# Provisional, fixed (not library-relative) listening scores.  They are
# transparent descriptors, not a learned perceptual ground truth.  The
# brightness components are correlated by construction, which is why ACT does
# not directly include any brightness component.
BRIGHTNESS_WEIGHTS = {
    "spectral_centroid_hz": 0.50,
    "spectral_rolloff_hz": 0.25,
    "high_frequency_ratio": 0.25,
}
ACTIVITY_WEIGHTS = {
    "tempo_bpm": 0.30,
    "rms_dbfs": 0.25,
    "percussive_ratio": 0.25,
    "onset_rate": 0.20,
}

_IMAGERY = {
    ("低躁动", "暗色"): "深夜余温",
    ("低躁动", "明亮"): "晨光微风",
    ("中躁动", "暗色"): "雨幕回声",
    ("中躁动", "明亮"): "沿途晴光",
    ("高躁动", "暗色"): "夜行脉冲",
    ("高躁动", "明亮"): "盛夏燃点",
}


def _fixed_scale(values: list[float], field: str) -> np.ndarray:
    lo, hi = STANDARD_RANGES[field]
    return np.clip((np.asarray(values, dtype=float) - lo) / (hi - lo), 0.0, 1.0)


def brightness_score(acoustic: AcousticFeatures) -> float:
    """BRI v2 on a fixed 0–100 scale, with an explicit legacy fallback."""
    centroid = float(_fixed_scale([acoustic.spectral_centroid_hz], "spectral_centroid_hz")[0])
    rolloff = float(_fixed_scale([acoustic.spectral_rolloff_hz], "spectral_rolloff_hz")[0])
    if acoustic.high_frequency_ratio is None:
        return 100.0 * (
            BRIGHTNESS_WEIGHTS["spectral_centroid_hz"] * centroid
            + BRIGHTNESS_WEIGHTS["spectral_rolloff_hz"] * rolloff
        ) / (BRIGHTNESS_WEIGHTS["spectral_centroid_hz"] + BRIGHTNESS_WEIGHTS["spectral_rolloff_hz"])
    ratio = float(_fixed_scale([acoustic.high_frequency_ratio], "high_frequency_ratio")[0])
    return 100.0 * (
        BRIGHTNESS_WEIGHTS["spectral_centroid_hz"] * centroid
        + BRIGHTNESS_WEIGHTS["spectral_rolloff_hz"] * rolloff
        + BRIGHTNESS_WEIGHTS["high_frequency_ratio"] * ratio
    )


def _band(score: float) -> str:
    if score < 35:
        return "低躁动"
    if score < 60:
        return "中躁动"
    return "高躁动"


def _style_hint(track: TrackEncoding) -> str:
    # Acoustic measurements do not establish a professional genre.
    return "声学特征（非流派）"


def key_tag_value(acoustic: AcousticFeatures) -> str:
    """Store tonic and mode together; weak or malformed estimates stay uncertain."""
    if acoustic.key_confidence < 0.25 or acoustic.key not in TONIC_NAMES or acoustic.mode not in {"major", "minor"}:
        return "uncertain"
    return f"{acoustic.key}:{acoustic.mode}"


def score_tracks(tracks: list[TrackEncoding]) -> list[TrackEncoding]:
    if not tracks:
        return tracks
    tempo = _fixed_scale([t.acoustic.tempo_bpm for t in tracks], "tempo_bpm")
    energy = _fixed_scale([t.acoustic.rms_dbfs for t in tracks], "rms_dbfs")
    perc = _fixed_scale([t.acoustic.percussive_ratio for t in tracks], "percussive_ratio")
    onset = _fixed_scale([t.acoustic.onset_rate for t in tracks], "onset_rate")
    bright = np.asarray([brightness_score(t.acoustic) / 100.0 for t in tracks], dtype=float)
    # Old saved plans remain readable, but recalculated legacy scores warn that
    # the full three-component brightness measurement is unavailable.
    legacy = np.array([t.acoustic.high_frequency_ratio is None for t in tracks])
    rhythmicity = np.clip(0.55 * perc + 0.45 * onset, 0, 1)
    agitation = np.clip(
        ACTIVITY_WEIGHTS["tempo_bpm"] * tempo
        + ACTIVITY_WEIGHTS["rms_dbfs"] * energy
        + ACTIVITY_WEIGHTS["percussive_ratio"] * perc
        + ACTIVITY_WEIGHTS["onset_rate"] * onset,
        0, 1,
    )

    genres = [track.metadata.genre.strip().casefold() for track in tracks if track.metadata.genre.strip()]
    dominant_genre_ratio = Counter(genres).most_common(1)[0][1] / len(genres) if genres else 0.0
    retain_embedded_genre = len(genres) < 5 or dominant_genre_ratio < 0.80

    for index, track in enumerate(tracks):
        ag = round(float(agitation[index] * 100), 1)
        br = round(float(bright[index] * 100), 1)
        en = round(float(energy[index] * 100), 1)
        rhythm = round(float(rhythmicity[index] * 100), 1)
        track.standard = StandardScores(
            agitation=ag,
            agitation_band=_band(ag),
            brightness=br,
            energy=en,
            rhythmicity=rhythm,
            warmth=round(100 - br, 1),
        )
        track.style_hint = _style_hint(track)
        if legacy[index] and "brightness_missing_high_frequency_ratio" not in track.warnings:
            track.warnings.append("brightness_missing_high_frequency_ratio")
        raw_genre = track.metadata.genre.strip()
        track.genre_value = raw_genre if retain_embedded_genre else ""
        track.genre_status = "embedded_unverified" if raw_genre and retain_embedded_genre else "unavailable"
        track.genre_source = "ID3 Genre" if raw_genre and retain_embedded_genre else ""
        beat_uncertain = track.acoustic.tempo_confidence < 0.65 and track.acoustic.percussive_ratio < 0.08
        full_key = key_tag_value(track.acoustic)
        track.tags = {
            "instrument": track.instrument,
            "tempo": "unsteady" if beat_uncertain else "slow" if track.acoustic.tempo_bpm < 90 else "fast" if track.acoustic.tempo_bpm >= 130 else "moderate",
            "loudness": "soft" if track.acoustic.rms_dbfs < -27 else "loud" if track.acoustic.rms_dbfs >= -19 else "medium",
            "tonality": track.acoustic.mode if full_key != "uncertain" else "uncertain",
            "key": full_key,
            "agitation": "low" if ag < 35 else "high" if ag >= 60 else "medium",
            "brightness": "dark" if br < 40 else "bright",
            "rhythmicity": "weak" if rhythm < 40 else "strong",
        }
        if raw_genre and not retain_embedded_genre:
            track.warnings.append(
                f"曲库中 {dominant_genre_ratio:.0%} 的 Genre 标签相同，疑似批量错误；未作为专业流派使用"
            )
    return tracks


def _folder_name(mode: str, band: str, tone: str, imagery: str, style: str, tracks: list[TrackEncoding]) -> str:
    if mode == "style":
        return f"{style}｜{band}·{tone}"
    if mode == "quant":
        median_bpm = int(round(float(np.median([t.acoustic.tempo_bpm for t in tracks]))))
        median_db = int(round(float(np.median([t.acoustic.rms_dbfs for t in tracks]))))
        return f"BPM约{median_bpm}｜响度{median_db}dB·{tone}"
    return f"{imagery}｜{band}·{tone}"


def compile_folders(tracks: list[TrackEncoding], naming_mode: str = "poetic") -> list[FolderProposal]:
    if naming_mode not in NAMING_MODES:
        raise ValueError(f"未知命名模式：{naming_mode}")
    buckets: dict[tuple[str, str], list[TrackEncoding]] = defaultdict(list)
    for track in tracks:
        if track.standard is None:
            raise ValueError("曲目尚未计算标准分数")
        tone = "明亮" if track.standard.brightness >= 40 else "暗色"
        buckets[(track.standard.agitation_band, tone)].append(track)

    proposals: list[FolderProposal] = []
    for ordinal, ((band, tone), members) in enumerate(sorted(buckets.items()), 1):
        imagery = _IMAGERY[(band, tone)]
        style_counts = Counter(member.style_hint for member in members)
        style, style_count = style_counts.most_common(1)[0]
        style_ratio = style_count / len(members)
        naming_style = style if style_ratio >= 0.60 else "混合风格（待确认）"
        ag_values = np.asarray([member.standard.agitation for member in members], dtype=float)
        br_values = np.asarray([member.standard.brightness for member in members], dtype=float)
        spread = float(np.std(ag_values) * 0.65 + np.std(br_values) * 0.35)
        acoustic_cohesion = float(np.clip(100 - spread * 2.4, 0, 100))
        cohesion = round(
            acoustic_cohesion if naming_mode != "style" else 0.70 * acoustic_cohesion + 0.30 * style_ratio * 100,
            1,
        )
        folder_id = f"F{ordinal:02d}-{band}-{tone}"
        name = _folder_name(naming_mode, band, tone, imagery, naming_style, members)
        explanation = (
            f"共同特征：{band}、{tone}音色；主导风格倾向为“{style}”"
            f"（占 {style_ratio:.0%}）。一致度 {cohesion:.0f}/100。"
        )
        proposals.append(FolderProposal(
            folder_id=folder_id,
            name=name,
            imagery=imagery,
            agitation_band=band,
            tone=tone,
            style_hint=style,
            track_ids=[member.track_id for member in members],
            cohesion=cohesion,
            explanation=explanation,
        ))
        median_ag = float(np.median(ag_values))
        median_br = float(np.median(br_values))
        for member in members:
            member.folder_id = folder_id
            member.folder_name = name
            distance = abs(member.standard.agitation - median_ag) * 0.65 + abs(member.standard.brightness - median_br) * 0.35
            member.confidence = round(float(np.clip(1 - distance / 70, 0.35, 0.99)), 3)
            member.reasons = [
                f"躁动度 {member.standard.agitation:.0f}/100，属于{band}",
                f"音色亮度 {member.standard.brightness:.0f}/100，属于{tone}",
                f"BPM {member.acoustic.tempo_bpm:.0f}，风格判断为“{member.style_hint}”",
            ]
            if not member.metadata.genre:
                member.warnings = ["风格为声学规则推断，并非专业流派模型结论"]
    return proposals


def _refresh_folder(folder: FolderProposal, tracks: list[TrackEncoding], naming_mode: str, language: str = "zh") -> None:
    track_map = {track.track_id: track for track in tracks}
    members = [track_map[track_id] for track_id in folder.track_ids if track_id in track_map]
    if not members:
        folder.cohesion = 0.0
        folder.style_hint = "暂无曲目"
        folder.explanation = "This folder is empty after manual changes." if language == "en" else "该文件夹已被用户移空，可继续加入曲目或忽略。"
        return
    ag_values = np.asarray([member.standard.agitation for member in members if member.standard], dtype=float)
    br_values = np.asarray([member.standard.brightness for member in members if member.standard], dtype=float)
    spread = float(np.std(ag_values) * 0.65 + np.std(br_values) * 0.35)
    acoustic_cohesion = float(np.clip(100 - spread * 2.4, 0, 100))
    style, count = Counter(member.style_hint for member in members).most_common(1)[0]
    style_ratio = count / len(members)
    folder.style_hint = style
    folder.cohesion = round(
        acoustic_cohesion if naming_mode != "style" else 0.70 * acoustic_cohesion + 0.30 * style_ratio * 100,
        1,
    )
    folder.explanation = (
        f"After manual changes: acoustic similarity {folder.cohesion:.0f}/100."
        if language == "en" else f"用户调整后的声学相近度：{folder.cohesion:.0f}/100。"
    )


def rename_folder(tracks: list[TrackEncoding], folders: list[FolderProposal], folder_id: str, new_name: str) -> None:
    clean = " ".join(new_name.split()).strip()
    if not clean:
        raise ValueError("文件夹名称不能为空")
    folder = next((item for item in folders if item.folder_id == folder_id), None)
    if folder is None:
        raise KeyError(folder_id)
    folder.name = clean
    for track in tracks:
        if track.folder_id == folder_id:
            track.folder_name = clean


def reassign_track(
    tracks: list[TrackEncoding], folders: list[FolderProposal], track_id: str, target_folder_id: str,
    naming_mode: str = "poetic", language: str = "zh",
) -> None:
    track = next((item for item in tracks if item.track_id == track_id), None)
    target = next((item for item in folders if item.folder_id == target_folder_id), None)
    if track is None or target is None:
        raise KeyError(track_id if track is None else target_folder_id)
    for folder in folders:
        if track_id in folder.track_ids:
            folder.track_ids.remove(track_id)
    if track_id not in target.track_ids:
        target.track_ids.append(track_id)
    track.folder_id = target.folder_id
    track.folder_name = target.name
    track.confidence = 1.0
    if "用户手动调整了归类" not in track.reasons:
        track.reasons.append("用户手动调整了归类")
    folders[:] = [folder for folder in folders if folder.track_ids]
    for folder in folders:
        _refresh_folder(folder, tracks, naming_mode, language)

