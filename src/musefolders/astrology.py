"""Deterministic, explicitly playful silhouettes for the *displayed* sonic map.

The result describes the whole library's plotted shape, not a birth chart,
personality, mood, or independently inferred four-element acoustic score.
Neither matching nor rendering changes a SonicMap point or sound vector.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Sequence

import numpy as np

if TYPE_CHECKING:
    from .models import TrackEncoding
    from .sonic_map import SonicMap


ZODIAC_VERSION = "sonic-silhouettes-v1"
MIN_ZODIAC_TRACKS = 12
ZODIAC_LABELS = {
    "zh": {
        "aries": "白羊座", "taurus": "金牛座", "gemini": "双子座",
        "cancer": "巨蟹座", "leo": "狮子座", "virgo": "处女座",
        "libra": "天秤座", "scorpio": "天蝎座", "sagittarius": "射手座",
        "capricorn": "摩羯座", "aquarius": "水瓶座", "pisces": "双鱼座",
    },
    "en": {
        "aries": "Aries", "taurus": "Taurus", "gemini": "Gemini",
        "cancer": "Cancer", "leo": "Leo", "virgo": "Virgo",
        "libra": "Libra", "scorpio": "Scorpio", "sagittarius": "Sagittarius",
        "capricorn": "Capricorn", "aquarius": "Aquarius", "pisces": "Pisces",
    },
}
ELEMENT_LABELS = {
    "zh": {"fire": "火象", "earth": "土象", "air": "风象", "water": "水象"},
    "en": {"fire": "Fire", "earth": "Earth", "air": "Air", "water": "Water"},
}
_ELEMENT_BY_SIGN = {
    "aries": "fire", "taurus": "earth", "gemini": "air", "cancer": "water",
    "leo": "fire", "virgo": "earth", "libra": "air", "scorpio": "water",
    "sagittarius": "fire", "capricorn": "earth", "aquarius": "air", "pisces": "water",
}


@dataclass(frozen=True, slots=True)
class ZodiacResult:
    version: str
    status: Literal["seed", "matched"]
    sign: str | None
    element: str | None
    overlay_nodes: tuple[tuple[float, float], ...]
    overlay_edges: tuple[tuple[int, int], ...]
    representative_track_ids: tuple[str, ...]
    unique_track_count: int
    is_override: bool
    mode: str
    projection: str
    point_fingerprint: str
    match_score: float | None  # Internal diagnostic; never a scientific confidence.
    rationale_zh: str
    rationale_en: str


@dataclass(frozen=True, slots=True)
class _Template:
    nodes: np.ndarray
    edges: tuple[tuple[int, int], ...]
    samples: np.ndarray


def _template(*paths: tuple[tuple[float, float], ...]) -> _Template:
    """Combine pen strokes into a symbol; lines are decorative, not astronomy."""
    nodes: list[tuple[float, float]] = []
    edges: list[tuple[int, int]] = []
    samples: list[tuple[float, float]] = []
    for path in paths:
        start = len(nodes)
        nodes.extend(path)
        for index in range(len(path) - 1):
            left = np.asarray(path[index], dtype=float)
            right = np.asarray(path[index + 1], dtype=float)
            edges.append((start + index, start + index + 1))
            for fraction in (0.0, 0.25, 0.5, 0.75):
                samples.append(tuple(left + (right - left) * fraction))
        if len(path) == 1:
            samples.append(path[0])
        elif path:
            samples.append(path[-1])
    return _Template(np.asarray(nodes, dtype=float), tuple(edges), np.asarray(samples, dtype=float))


# Symbolic animal / figure outlines, deliberately distinct from astronomical star charts.
# Each path is a separate pen stroke. All templates are sampled at the same line density.
_TEMPLATES = {
    "aries": _template(
        ((0.0, -1.0), (-0.28, -0.55), (-0.35, 0.2), (-0.78, 0.72),
         (-0.96, 0.55), (-0.74, 0.35), (-0.5, 0.47), (-0.35, 0.83), (0.0, 0.98)),
        ((0.0, -1.0), (0.28, -0.55), (0.35, 0.2), (0.78, 0.72),
         (0.96, 0.55), (0.74, 0.35), (0.5, 0.47), (0.35, 0.83), (0.0, 0.98)),
    ),
    "taurus": _template(
        ((-0.9, 0.92), (-0.85, 0.37), (-0.46, 0.16), (-0.49, -0.57),
         (-0.18, -0.96), (0.18, -0.96), (0.49, -0.57), (0.46, 0.16),
         (0.85, 0.37), (0.9, 0.92)),
        ((-0.46, 0.16), (0.0, 0.42), (0.46, 0.16)),
        ((-0.25, -0.29), (0.25, -0.29)),
    ),
    "gemini": _template(
        ((-0.91, 0.82), (-0.54, 0.92), (-0.28, 0.68), (-0.52, 0.4),
         (-0.74, 0.43), (-0.8, -0.4), (-0.95, -0.91)),
        ((0.91, 0.82), (0.54, 0.92), (0.28, 0.68), (0.52, 0.4),
         (0.74, 0.43), (0.8, -0.4), (0.95, -0.91)),
        ((-0.7, 0.07), (0.0, -0.05), (0.7, 0.07)),
        ((-0.5, -0.43), (0.0, -0.33), (0.5, -0.43)),
    ),
    "cancer": _template(
        ((-0.75, 0.14), (-0.45, 0.53), (0.0, 0.67), (0.45, 0.53),
         (0.75, 0.14), (0.48, -0.42), (0.0, -0.58), (-0.48, -0.42), (-0.75, 0.14)),
        ((-0.62, 0.29), (-0.91, 0.7), (-0.97, 0.96), (-0.63, 0.76)),
        ((0.62, 0.29), (0.91, 0.7), (0.97, 0.96), (0.63, 0.76)),
        ((-0.52, -0.34), (-0.89, -0.59), (-0.98, -0.83)),
        ((0.52, -0.34), (0.89, -0.59), (0.98, -0.83)),
    ),
    "leo": _template(
        ((0.0, 0.95), (0.58, 0.7), (0.89, 0.18), (0.79, -0.52),
         (0.3, -0.84), (-0.3, -0.84), (-0.79, -0.52), (-0.89, 0.18),
         (-0.58, 0.7), (0.0, 0.95)),
        ((-0.39, 0.41), (0.0, 0.62), (0.39, 0.41), (0.43, -0.3),
         (0.0, -0.57), (-0.43, -0.3), (-0.39, 0.41)),
        ((0.79, -0.52), (1.0, -0.8), (0.87, -0.99)),
    ),
    "virgo": _template(
        ((-0.16, 0.96), (0.2, 0.98), (0.43, 0.7), (0.24, 0.38),
         (-0.17, 0.43), (-0.37, 0.72), (-0.16, 0.96)),
        ((-0.31, 0.39), (-0.81, -0.03), (-0.58, -0.34), (-0.97, -0.95)),
        ((0.2, 0.37), (0.83, -0.03), (0.57, -0.35), (0.97, -0.95)),
        ((-0.31, 0.39), (-0.48, -0.52), (0.0, -0.83), (0.48, -0.52), (0.2, 0.37)),
    ),
    "libra": _template(
        ((-0.92, -0.77), (0.92, -0.77)),
        ((0.0, 0.9), (0.0, -0.77)),
        ((-0.95, 0.42), (0.0, 0.65), (0.95, 0.42)),
        ((-0.95, 0.42), (-0.78, -0.23), (-0.45, -0.23), (-0.25, 0.42)),
        ((0.95, 0.42), (0.78, -0.23), (0.45, -0.23), (0.25, 0.42)),
    ),
    "scorpio": _template(
        ((-0.91, 0.56), (-0.62, 0.16), (-0.36, 0.48), (-0.1, 0.13),
         (0.17, 0.43), (0.34, 0.0), (0.27, -0.42), (0.55, -0.73),
         (0.87, -0.63), (0.99, -0.29), (0.79, -0.12)),
        ((-0.63, 0.15), (-0.74, -0.61), (-0.96, -0.81)),
        ((-0.37, 0.46), (-0.22, 0.94)),
        ((0.17, 0.43), (0.37, 0.91)),
    ),
    "sagittarius": _template(
        ((-0.85, -0.83), (0.82, 0.83)),
        ((0.29, 0.84), (0.82, 0.83), (0.79, 0.3)),
        ((-0.49, -0.92), (-0.83, -0.51), (-0.59, 0.26),
         (0.08, 0.77), (0.64, 0.88)),
        ((-0.83, -0.51), (-0.45, -0.25), (-0.17, 0.2), (0.08, 0.77)),
    ),
    "capricorn": _template(
        ((-0.94, 0.74), (-0.85, 0.28), (-0.54, 0.62), (-0.28, 0.21),
         (0.04, 0.36), (0.19, -0.11), (0.59, -0.31), (0.92, -0.16),
         (0.73, -0.69), (0.35, -0.9), (-0.1, -0.75)),
        ((-0.54, 0.62), (-0.42, 0.96), (-0.1, 0.69)),
        ((-0.28, 0.21), (-0.32, -0.44), (-0.1, -0.75)),
        ((0.59, -0.31), (0.95, -0.82), (0.73, -0.69)),
    ),
    "aquarius": _template(
        ((-0.82, 0.78), (-0.18, 0.98), (0.31, 0.76), (0.49, 0.28),
         (0.07, -0.02), (-0.58, 0.06), (-0.82, 0.78)),
        ((0.43, 0.23), (0.93, 0.05), (0.56, -0.3), (0.13, -0.18),
         (-0.35, -0.41), (-0.83, -0.23)),
        ((0.93, -0.43), (0.56, -0.78), (0.13, -0.66), (-0.35, -0.89), (-0.83, -0.71)),
    ),
    "pisces": _template(
        ((-0.93, 0.43), (-0.55, 0.91), (-0.14, 0.45), (-0.55, -0.01), (-0.93, 0.43)),
        ((0.93, -0.43), (0.55, 0.01), (0.14, -0.45), (0.55, -0.91), (0.93, -0.43)),
        ((-0.14, 0.45), (0.14, -0.45)),
        ((-0.93, 0.43), (-0.95, -0.05), (-0.63, 0.22)),
        ((0.93, -0.43), (0.95, 0.05), (0.63, -0.22)),
    ),
}


def zodiac_element(sign: str) -> str:
    """Four elements are a fixed cultural mapping from sign, never acoustic scores."""
    try:
        return _ELEMENT_BY_SIGN[sign]
    except KeyError as exc:
        raise ValueError(f"Unknown zodiac sign: {sign}") from exc


def _unique_points(
    sound: SonicMap, tracks: Sequence[TrackEncoding] = (),
) -> tuple[tuple[str, float, float], ...]:
    """Use every finite distinct audio once; equal XY alone is not a duplicate.

    A copied file can have another track ID. Prefer its audio SHA-256 when
    available, and otherwise fall back to the stable plotted ID.
    """
    by_id: dict[str, tuple[float, float]] = {}
    for point in sorted(sound.points, key=lambda p: (str(p.track_id), float(p.x), float(p.y))):
        if point.track_id and math.isfinite(point.x) and math.isfinite(point.y):
            by_id.setdefault(str(point.track_id), (float(point.x), float(point.y)))
    hashes = {
        str(track.track_id): str(track.source_sha256).strip().lower()
        for track in tracks if getattr(track, "source_sha256", "")
    }
    seen_content: set[str] = set()
    unique: list[tuple[str, float, float]] = []
    for track_id in sorted(by_id):
        content = f"sha256:{hashes[track_id]}" if track_id in hashes else f"id:{track_id}"
        if content in seen_content:
            continue
        seen_content.add(content)
        unique.append((track_id, *by_id[track_id]))
    return tuple(unique)


def _point_fingerprint(points: tuple[tuple[str, float, float], ...], sound: SonicMap) -> str:
    digest = hashlib.sha256()
    digest.update(f"{ZODIAC_VERSION}|{sound.mode}|{sound.projection}|".encode())
    for track_id, x, y in points:
        digest.update(f"{track_id}\0{x.hex()}\0{y.hex()}\n".encode("utf-8"))
    return digest.hexdigest()[:24]


def _match_shape(cloud: np.ndarray) -> tuple[str, float, float, float, bool]:
    """Symmetric Chamfer search over the *entire* cloud, without selecting songs.

    Both directions matter: every song contributes to cloud-to-outline distance,
    and every part of a template must be near some song. No reflection or
    non-uniform stretching is allowed; rotations and uniform scales are.
    """
    center = cloud.mean(axis=0)
    radius = float(np.sqrt(np.mean(np.sum((cloud - center) ** 2, axis=1))))
    if radius < 1e-7:
        # Twelve or more songs but no identifiable cloud shape. Return a stable
        # playful default, explicitly qualified in the rationale below.
        return "aries", 0.0, 1.0, 0.0, True
    normalized_cloud = (cloud - center) / radius
    scales = np.asarray((0.75, 0.875, 1.0, 1.125, 1.25), dtype=float)
    best = (float("inf"), "", 0.0, 1.0)
    for sign, template in _TEMPLATES.items():
        sample = template.samples
        sample_center = sample.mean(axis=0)
        sample_radius = float(np.sqrt(np.mean(np.sum((sample - sample_center) ** 2, axis=1))))
        canonical = (sample - sample_center) / sample_radius
        for degrees in range(0, 360, 10):
            angle = math.radians(degrees)
            rotation = np.asarray(((math.cos(angle), -math.sin(angle)),
                                   (math.sin(angle), math.cos(angle))))
            rotated = canonical @ rotation.T
            alternatives = scales[:, None, None] * rotated[None, :, :]
            squared = np.sum(
                (normalized_cloud[None, :, None, :] - alternatives[:, None, :, :]) ** 2,
                axis=-1,
            )
            score = (
                0.72 * squared.min(axis=2).mean(axis=1)
                + 0.28 * squared.min(axis=1).mean(axis=1)
            )
            index = int(np.argmin(score))
            candidate = (float(score[index]), sign, angle, float(scales[index]))
            if candidate < best:
                best = candidate
    return best[1], best[2], best[3], best[0], False


def _overlay(sign: str, cloud: np.ndarray, angle: float, scale: float,
             *, concentrated: bool = False) -> tuple[tuple[float, float], ...]:
    template = _TEMPLATES[sign]
    sample_center = template.samples.mean(axis=0)
    sample_radius = float(np.sqrt(np.mean(np.sum((template.samples - sample_center) ** 2, axis=1))))
    center = cloud.mean(axis=0)
    cloud_radius = float(np.sqrt(np.mean(np.sum((cloud - center) ** 2, axis=1))))
    if concentrated:
        cloud_radius = 13.0
    rotation = np.asarray(((math.cos(angle), -math.sin(angle)),
                           (math.sin(angle), math.cos(angle))))
    nodes = ((template.nodes - sample_center) / sample_radius) @ rotation.T
    nodes = nodes * (scale * cloud_radius) + center
    # The map is displayed on fixed 0–100 axes: contain decoration inside those
    # axes rather than allowing an overlay toggle to autoscale the real songs.
    bounds = nodes.max(axis=0) - nodes.min(axis=0)
    factor = min(1.0, 94.0 / max(bounds[0], 1e-9), 94.0 / max(bounds[1], 1e-9))
    nodes = (nodes - center) * factor + center
    shift = np.clip(nodes.min(axis=0), 3.0, np.inf) - nodes.min(axis=0)
    nodes += shift
    shift = np.clip(nodes.max(axis=0), -np.inf, 97.0) - nodes.max(axis=0)
    nodes += shift
    return tuple((float(x), float(y)) for x, y in nodes)


def _representatives(points: tuple[tuple[str, float, float], ...], limit: int = 3) -> tuple[str, ...]:
    """Display dispersed actual songs *after* whole-cloud matching is complete."""
    coords = np.asarray([(x, y) for _, x, y in points], dtype=float)
    chosen: list[int] = []
    centroid = coords.mean(axis=0)
    first = int(np.argmax(np.sum((coords - centroid) ** 2, axis=1)))
    chosen.append(first)
    while len(chosen) < min(limit, len(points)):
        distances = np.min(
            np.sum((coords[:, None, :] - coords[chosen][None, :, :]) ** 2, axis=2),
            axis=1,
        )
        distances[chosen] = -1
        chosen.append(int(np.argmax(distances)))
    return tuple(points[index][0] for index in chosen)


def build_zodiac(
    sound: SonicMap, tracks: Sequence[TrackEncoding] = (), *, override_sign: str | None = None,
) -> ZodiacResult:
    """Match one symbolic sign to displayed XY positions; never mutate ``sound``.

    ``tracks`` supplies audio hashes for duplicate-content removal. Only plotted
    XY determines the shape; metadata and ACT never influence shape matching.
    """
    if override_sign is not None and override_sign not in _TEMPLATES:
        raise ValueError(f"Unknown zodiac sign: {override_sign}")
    points = _unique_points(sound, tracks)
    fingerprint = _point_fingerprint(points, sound)
    count = len(points)
    common = dict(
        version=ZODIAC_VERSION, unique_track_count=count,
        mode=sound.mode, projection=sound.projection, point_fingerprint=fingerprint,
    )
    if count < MIN_ZODIAC_TRACKS:
        return ZodiacResult(
            **common, status="seed", sign=None, element=None,
            overlay_nodes=(), overlay_edges=(), representative_track_ids=(),
            is_override=False, match_score=None,
            rationale_zh=f"星群种子：当前有 {count} 首可用歌曲；满 12 首后生成趣味听感星象。",
            rationale_en=f"Star cluster seed: {count} usable songs; 12 are needed for a playful sonic silhouette.",
        )
    cloud = np.asarray([(x, y) for _, x, y in points], dtype=float)
    matched_sign, angle, scale, score, concentrated = _match_shape(cloud)
    sign = override_sign or matched_sign
    if override_sign and override_sign != matched_sign:
        # An override chooses the symbol but never re-matches or relocates music.
        # Retain an intelligible fixed pose for the user's chosen decoration.
        angle, scale = 0.0, 1.0
    is_override = override_sign is not None
    if is_override:
        rationale_zh = f"已自选{ZODIAC_LABELS['zh'][sign]}；{ELEMENT_LABELS['zh'][zodiac_element(sign)]}随星座派生，歌曲点位未改变。"
        rationale_en = f"You chose {ZODIAC_LABELS['en'][sign]}; {ELEMENT_LABELS['en'][zodiac_element(sign)]} follows that sign. Song positions are unchanged."
    elif concentrated:
        rationale_zh = "歌曲点位高度重合；仍按约定呈现一个固定的趣味轮廓，不代表可辨认的星座形状或个人性格。"
        rationale_en = "The song positions overlap heavily; this stable playful symbol does not imply a recognizable constellation or personality."
    else:
        rationale_zh = f"比较全部 {count} 首歌曲的实际听感点位与十二种象征性轮廓，选出相对最接近的{ZODIAC_LABELS['zh'][sign]}；不移动歌曲。"
        rationale_en = f"Compared all {count} displayed song positions with twelve symbolic silhouettes; {ZODIAC_LABELS['en'][sign]} was the relative match. Songs were not moved."
    if sound.mode != "musicnn":
        rationale_zh += " 当前为基础声学地图，而非完整模型听感画像。"
        rationale_en += " This is a basic acoustic map, not a full model-derived sound profile."
    return ZodiacResult(
        **common, status="matched", sign=sign, element=zodiac_element(sign),
        overlay_nodes=_overlay(sign, cloud, angle, scale, concentrated=concentrated),
        overlay_edges=_TEMPLATES[sign].edges,
        representative_track_ids=_representatives(points),
        is_override=is_override, match_score=score if not is_override else None,
        rationale_zh=rationale_zh, rationale_en=rationale_en,
    )


def _font(size: int, language: str):
    from PIL import ImageFont

    candidates = (
        (Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"), Path("C:/Windows/Fonts/msyh.ttc"),
         Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
         Path("/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf"))
        if language == "zh" else
        (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/arial.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    )
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                pass
    if language == "zh":
        raise RuntimeError("No local CJK font is available for the Chinese share card")
    return ImageFont.load_default()


def _safe_title(value: str) -> str:
    # Metadata can be dirty. A share card must not accidentally reveal a path.
    title = re.split(r"[\\/]", str(value))[-1].strip()
    return title[:64] or "—"


def _act_color(value: float | None) -> tuple[int, int, int]:
    if value is None or not math.isfinite(value):
        return (177, 194, 212)
    t = min(1.0, max(0.0, float(value) / 100.0))
    cold, warm = (49, 95, 168), (237, 133, 71)
    return tuple(round(a + (b - a) * t) for a, b in zip(cold, warm))


def make_zodiac_share_card(
    result: ZodiacResult, sound: SonicMap, tracks: Sequence[TrackEncoding], *,
    language: str = "zh", include_track_titles: bool = False, date: Date | str | None = None,
) -> bytes:
    """Render a private, local portrait PNG; never include lyrics or file paths.

    A stale result is rejected so the card cannot silently pair one constellation
    with a different library. Pillow is loaded lazily and performs no networking.
    """
    if language not in ("zh", "en"):
        raise ValueError("language must be 'zh' or 'en'")
    if result.status != "matched" or result.sign is None or result.element is None:
        raise ValueError("At least 12 usable songs are required for a zodiac share card")
    points = _unique_points(sound, tracks)
    if result.version != ZODIAC_VERSION or result.point_fingerprint != _point_fingerprint(points, sound):
        raise ValueError("Zodiac result is stale; rebuild it from the current sonic map")
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required to render the local share card") from exc

    width, height = 1080, 1600
    image = Image.new("RGB", (width, height), "#10182b")
    draw = ImageDraw.Draw(image)
    # Quiet vertical gradient and deterministic stars: no data leaves this image.
    for y in range(height):
        t = y / height
        draw.line((0, y, width, y), fill=(round(15 + 13 * t), round(22 + 9 * t), round(43 + 18 * t)))
    random = np.random.default_rng(int(result.point_fingerprint[:8], 16))
    for x, y in random.integers((30, 30), (width - 30, height - 30), size=(95, 2)):
        draw.ellipse((int(x), int(y), int(x) + 2, int(y) + 2), fill="#65708a")

    large, medium, small = _font(72, language), _font(34, language), _font(25, language)
    heading = "曲境 · 听感星象" if language == "zh" else "SONIC CONSTELLATION"
    sign_label = ZODIAC_LABELS[language][result.sign]
    element_label = ELEMENT_LABELS[language][result.element]
    draw.text((72, 72), heading, font=medium, fill="#a9b9d0")
    draw.text((72, 146), sign_label, font=large, fill="#f2eee8")
    element_text = f"{element_label} · {result.unique_track_count} 首歌曲" if language == "zh" else f"{element_label} · {result.unique_track_count} songs"
    draw.text((74, 250), element_text, font=medium, fill="#e7a77f")

    chart_left, chart_top, chart_size = 90, 355, 900
    draw.rounded_rectangle((chart_left, chart_top, chart_left + chart_size,
                            chart_top + chart_size), radius=34, fill="#1d2942")
    for fraction in (0.25, 0.5, 0.75):
        x = chart_left + chart_size * fraction
        y = chart_top + chart_size * fraction
        draw.line((x, chart_top + 20, x, chart_top + chart_size - 20), fill="#303d59", width=1)
        draw.line((chart_left + 20, y, chart_left + chart_size - 20, y), fill="#303d59", width=1)

    def pixels(x: float, y: float) -> tuple[float, float]:
        return chart_left + 28 + x / 100.0 * (chart_size - 56), chart_top + chart_size - 28 - y / 100.0 * (chart_size - 56)

    overlay = [pixels(x, y) for x, y in result.overlay_nodes]
    for start, end in result.overlay_edges:
        draw.line((*overlay[start], *overlay[end]), fill="#8c9cbd", width=5)
    for x, y in overlay:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#b3c2d9")

    by_id = {track.track_id: track for track in tracks}
    for track_id, x, y in points:
        track = by_id.get(track_id)
        standard = getattr(track, "standard", None)
        act = getattr(standard, "agitation", None)
        px, py = pixels(x, y)
        color = _act_color(act)
        draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=color, outline="#e9eff8", width=1)

    if date is None:
        stamp = Date.today().isoformat()
    elif isinstance(date, Date):
        stamp = date.isoformat()
    else:
        stamp = str(date)
    if language == "zh":
        source = "听感画像" if result.mode == "musicnn" else "基础声学"
        basis = f"依据：比较全部 {result.unique_track_count} 首歌曲的{source}点位与十二种趣味轮廓"
        qualification = "仅为相对匹配，不代表真实天象、性格或此刻心情"
    else:
        source = "sonic-profile" if result.mode == "musicnn" else "basic-acoustic"
        basis = f"Basis: all {result.unique_track_count} {source} points vs 12 playful outlines"
        qualification = "Relative match only; not astrology, personality, or current mood"
    draw.text((72, 1304), basis, font=small, fill="#c4cfdf")
    draw.text((72, 1340), qualification, font=small, fill="#a9b9d0")
    if result.is_override:
        override = "星座由你自选" if language == "zh" else "Sign selected by you"
        draw.text((72, 1376), override, font=small, fill="#e7a77f")
    if include_track_titles:
        titles = [
            _safe_title(by_id[track_id].metadata.title)
            for track_id in result.representative_track_ids
            if track_id in by_id and getattr(by_id[track_id], "metadata", None)
        ]
        if titles:
            heading = "代表曲目：" if language == "zh" else "Representative songs: "
            caption = heading + " · ".join(titles)
            while draw.textlength(caption, font=small) > width - 144 and len(caption) > len(heading) + 4:
                caption = caption[:-2].rstrip() + "…"
            draw.text((72, 1420), caption, font=small, fill="#c4cfdf")
    draw.text((72, 1518), stamp, font=small, fill="#9daac0")
    draw.text((width - 76, 1518), "曲境" if language == "zh" else "MUSEFOLDERS",
              font=small, fill="#9daac0", anchor="ra")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
