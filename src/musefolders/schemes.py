"""Deterministic, user-selectable grouping rules over auditable track tags."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .models import FolderProposal, TONIC_NAMES, TrackEncoding
from .taxonomy import key_tag_value


SCHEMES = {
    "agitation_brightness": ("agitation", "brightness"),
    "tempo_loudness": ("tempo", "loudness"),
    "tonality_agitation": ("tonality", "agitation"),
    "genre_agitation": ("genre", "agitation"),
    "custom": (),
}
TAG_LABELS = {
    "zh": {"instrument": "主要声源", "tempo": "节奏", "loudness": "响度", "tonality": "调式", "key": "调性", "agitation": "声音活跃度", "brightness": "声音明亮度", "rhythmicity": "节奏感", "genre": "已核实流派"},
    "en": {"instrument": "Main sound", "tempo": "Tempo", "loudness": "Loudness", "tonality": "Mode", "key": "Key", "agitation": "ACT", "brightness": "BRI", "rhythmicity": "Rhythmicity", "genre": "Verified genre"},
}
VALUE_LABELS = {
    "zh": {"slow": "慢速", "moderate": "中速", "fast": "快速", "unsteady": "节拍待定", "soft": "轻响", "medium": "中等", "loud": "响亮", "major": "大调", "minor": "小调", "uncertain": "待确定", "low": "低", "high": "高", "dark": "偏暗", "bright": "偏亮", "weak": "弱", "strong": "强", "unverified": "待核实", "voice": "人声", "piano": "钢琴", "guitar": "吉他", "strings": "弦乐", "wind": "管乐", "percussion": "打击乐", "synthesizer": "合成器", "unknown": "待确定"},
    "en": {"slow": "Slow", "moderate": "Moderate", "fast": "Fast", "unsteady": "Beat uncertain", "soft": "Soft", "medium": "Medium", "loud": "Loud", "major": "Major", "minor": "Minor", "uncertain": "Uncertain", "low": "Low", "high": "High", "dark": "Dark", "bright": "Bright", "weak": "Weak", "strong": "Strong", "unverified": "Unverified", "voice": "Vocals", "piano": "Piano", "guitar": "Guitar", "strings": "Strings", "wind": "Winds", "percussion": "Percussion", "synthesizer": "Synthesizer", "unknown": "Uncertain"},
}
POETIC_NAMES = {
    ("low", "dark"): ("深夜余温", "Afterglow"),
    ("low", "bright"): ("清晨微光", "Morning Light"),
    ("medium", "dark"): ("雨幕回声", "Rain Echo"),
    ("medium", "bright"): ("沿途晴光", "Daylight Drive"),
    ("high", "dark"): ("夜行脉冲", "Night Pulse"),
    ("high", "bright"): ("盛夏燃点", "Summer Pulse"),
}


def available_schemes(tracks: list[TrackEncoding]) -> list[str]:
    schemes = ["agitation_brightness", "tempo_loudness", "tonality_agitation", "custom"]
    if any(track.genre_status == "verified" and track.genre_value for track in tracks):
        schemes.insert(3, "genre_agitation")
    return schemes


def _tag_value(track: TrackEncoding, key: str) -> str:
    if key == "genre":
        return track.genre_value if track.genre_status == "verified" and track.genre_value else "unverified"
    if key == "key" and key not in track.tags:
        # Existing saved plans can use the new tag without re-decoding audio.
        track.tags[key] = key_tag_value(track.acoustic)
    if key not in track.tags:
        raise ValueError(f"Missing encoded tag: {key}")
    return track.tags[key]


def format_tag_value(key: str, value: str, language: str) -> str:
    if key == "key":
        tonic, separator, mode = value.partition(":")
        if separator and tonic in TONIC_NAMES and mode in {"major", "minor"}:
            return f"{tonic}{VALUE_LABELS[language][mode]}" if language == "zh" else f"{tonic} {mode}"
        return VALUE_LABELS[language]["uncertain"]
    return VALUE_LABELS[language].get(value, value)


def compile_scheme(
    tracks: list[TrackEncoding], scheme_id: str, *, tag_keys: list[str] | None = None,
    naming_mode: str = "poetic", language: str = "zh",
) -> tuple[list[FolderProposal], list[str]]:
    if scheme_id not in SCHEMES:
        raise ValueError(f"Unknown scheme: {scheme_id}")
    if language not in TAG_LABELS:
        raise ValueError(f"Unknown language: {language}")
    keys = list(SCHEMES[scheme_id]) if scheme_id != "custom" else list(tag_keys or [])
    if not 1 <= len(keys) <= 3 or len(set(keys)) != len(keys):
        raise ValueError("Choose one to three distinct tags")
    if any(key not in TAG_LABELS[language] for key in keys):
        raise ValueError("Unknown tag key")
    if "genre" in keys and scheme_id != "genre_agitation" and not any(
        t.genre_status == "verified" for t in tracks
    ):
        raise ValueError("No verified genres are available")

    buckets: dict[tuple[str, ...], list[TrackEncoding]] = defaultdict(list)
    for track in tracks:
        if track.standard is None:
            raise ValueError("Tracks must be scored before grouping")
        buckets[tuple(_tag_value(track, key) for key in keys)].append(track)

    folders: list[FolderProposal] = []
    for index, (values, members) in enumerate(sorted(buckets.items()), 1):
        labels = [format_tag_value(key, value, language) for key, value in zip(keys, values)]
        descriptive = " · ".join(f"{TAG_LABELS[language][key]} {label}" for key, label in zip(keys, labels))
        name = descriptive
        vectors = np.asarray([
            [m.standard.agitation, m.standard.brightness, m.standard.energy, m.standard.rhythmicity]
            for m in members
        ], dtype=float)
        center = np.median(vectors, axis=0)
        distance = np.mean(np.abs(vectors - center), axis=1)
        cohesion = round(float(np.clip(100 - 2.5 * np.mean(distance), 0, 100)), 1)
        folder_id = f"F{index:02d}"
        explanation = (
            f"按 {' + '.join(TAG_LABELS[language][key] for key in keys)} 分组：{descriptive}。声学相近度 {cohesion:.0f}/100。"
            if language == "zh" else
            f"Grouped by {' + '.join(TAG_LABELS[language][key] for key in keys)}: {descriptive}. Acoustic similarity {cohesion:.0f}/100."
        )
        folders.append(FolderProposal(
            folder_id=folder_id, name=name, imagery="", agitation_band=members[0].standard.agitation_band,
            tone=members[0].tags.get("brightness", ""), style_hint="", track_ids=[m.track_id for m in members],
            cohesion=cohesion, explanation=explanation,
        ))
        for member, deviation in zip(members, distance):
            member.folder_id = folder_id
            member.folder_name = name
            member.confidence = round(float(np.clip(1 - deviation / 75, 0, 1)), 3)
            member.reasons = [f"{TAG_LABELS[language][key]}: {label}" for key, label in zip(keys, labels)]
    return folders, keys
