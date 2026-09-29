"""Deterministic, compact semantic regions for the theme overview.

The layout describes *relationships between themes*, not song similarity or
measured x/y coordinates. Counts adjust space modestly; unknown is separate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .lyrics_map import THEME_PROMPTS


THEME_ATLAS_VERSION = "theme-islands-v2"
THEME_VIEW_BOX = (0, 0, 1000, 680)

# The relationship graph is deliberately fixed. Empty themes do not acquire a
# misleading region; occupied themes share one contiguous landmass.
_ANCHORS: dict[str, tuple[float, float]] = {
    "love": (700.0, 190.0), "family": (790.0, 270.0),
    "friendship": (805.0, 400.0), "memory": (410.0, 180.0),
    "solitude": (325.0, 320.0), "hope": (555.0, 345.0),
    "journey": (570.0, 485.0), "celebration": (790.0, 515.0),
    "nature": (385.0, 510.0), "unknown": (115.0, 335.0),
}

_LAND = ((258.0, 93.0), (393.0, 67.0), (559.0, 83.0),
         (713.0, 65.0), (885.0, 104.0), (939.0, 217.0),
         (926.0, 391.0), (956.0, 557.0), (833.0, 608.0),
         (654.0, 590.0), (480.0, 616.0), (310.0, 572.0),
         (238.0, 430.0), (251.0, 260.0))
_UNKNOWN = ((42.0, 178.0), (152.0, 157.0), (210.0, 231.0),
            (200.0, 409.0), (150.0, 505.0), (38.0, 478.0))


@dataclass(frozen=True, slots=True)
class ThemeRegion:
    theme_id: str
    track_ids: tuple[str, ...]
    count: int
    center: tuple[float, float]
    outline: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class ThemeAtlas:
    version: str
    view_box: tuple[int, int, int, int]
    regions: dict[str, ThemeRegion]


def _clip(poly: tuple[tuple[float, float], ...], a: float, b: float,
          limit: float) -> tuple[tuple[float, float], ...]:
    """Clip a convex polygon against ``a*x + b*y <= limit``."""
    if not poly:
        return ()
    result: list[tuple[float, float]] = []
    for start, end in zip(poly, poly[1:] + poly[:1]):
        start_side = a * start[0] + b * start[1] - limit
        end_side = a * end[0] + b * end[1] - limit
        if start_side <= 1e-7:
            result.append(start)
        if (start_side < -1e-7 and end_side > 1e-7) or (start_side > 1e-7 and end_side < -1e-7):
            t = start_side / (start_side - end_side)
            result.append((start[0] + t * (end[0] - start[0]),
                           start[1] + t * (end[1] - start[1])))
    return tuple(result)


def _centroid(poly: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    if len(poly) < 3:
        return poly[0] if poly else (500.0, 340.0)
    cross = [x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1])]
    area6 = 3.0 * sum(cross)
    if abs(area6) < 1e-8:
        return (sum(x for x, _ in poly) / len(poly), sum(y for _, y in poly) / len(poly))
    return (sum((poly[i][0] + poly[(i + 1) % len(poly)][0]) * cross[i]
                for i in range(len(poly))) / area6,
            sum((poly[i][1] + poly[(i + 1) % len(poly)][1]) * cross[i]
                for i in range(len(poly))) / area6)


def _weight(count: int) -> float:
    # Sublinear and capped: one popular theme must not swallow the map.
    return min(12000.0, 2600.0 * math.sqrt(count))


def build_theme_atlas(primary_themes: Mapping[str, str]) -> ThemeAtlas:
    unknown_ids = set(primary_themes.values()) - set(_ANCHORS)
    if unknown_ids:
        raise ValueError(f"unrecognized theme ids: {', '.join(sorted(unknown_ids))}")
    if set(THEME_PROMPTS) != set(_ANCHORS) - {"unknown"}:
        raise ValueError("theme atlas anchors are out of sync with theme prompts")
    grouped: dict[str, list[str]] = {theme_id: [] for theme_id in _ANCHORS}
    for track_id, theme_id in primary_themes.items():
        grouped[theme_id].append(track_id)
    active = [theme_id for theme_id in _ANCHORS if theme_id != "unknown" and grouped[theme_id]]
    regions: dict[str, ThemeRegion] = {}
    for theme_id in active:
        sx, sy = _ANCHORS[theme_id]
        poly = _LAND
        for other_id in active:
            if other_id == theme_id:
                continue
            ox, oy = _ANCHORS[other_id]
            # Weighted Voronoi (power) cells share borders; counts gently bias area.
            limit = ox * ox + oy * oy - sx * sx - sy * sy
            limit += _weight(len(grouped[theme_id])) - _weight(len(grouped[other_id]))
            poly = _clip(poly, 2 * (ox - sx), 2 * (oy - sy), limit)
        regions[theme_id] = ThemeRegion(
            theme_id, tuple(sorted(grouped[theme_id])), len(grouped[theme_id]),
            tuple(round(value, 2) for value in _centroid(poly)),
            tuple((round(x, 2), round(y, 2)) for x, y in poly),
        )
    if grouped["unknown"]:
        poly = _UNKNOWN if active else _LAND
        regions["unknown"] = ThemeRegion(
            "unknown", tuple(sorted(grouped["unknown"])), len(grouped["unknown"]),
            tuple(round(value, 2) for value in _centroid(poly)), poly,
        )
    return ThemeAtlas(THEME_ATLAS_VERSION, THEME_VIEW_BOX, regions)
