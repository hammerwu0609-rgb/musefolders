"""Compile a request into a small, validated intent and match local evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .lyrics_map import resolve_track_lyrics
from .models import TrackEncoding
from .tag_catalog import THEME_TERMS, TrackProfile, build_track_profiles, contains

THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "爱情": ("爱情", "恋爱", "恋人", "love"),
    "暗恋": ("暗恋", "偷偷喜欢", "crush"),
    "失恋": ("失恋", "分手", "breakup"),
    "思念": ("思念", "想念", "想你"),
    "成长": ("成长", "希望", "梦想"),
    "友情": ("友情", "友谊", "朋友"),
    "亲情": ("亲情", "家人", "父母"),
    "回忆": ("回忆", "记忆", "往事"),
    "孤独": ("孤独", "寂寞", "孤单"),
    "旅途": ("旅途", "旅行", "远方"),
    "庆祝": ("庆祝", "派对", "欢聚"),
    "自然": ("自然", "森林", "海洋"),
}
THEME_CHILDREN = {"爱情": ("暗恋", "失恋")}
SCENE_ALIASES = {
    "睡前": ("睡前", "入睡", "助眠", "bedtime", "sleep"),
    "放松": ("放松", "解压", "relax"),
    "专注": ("专注", "学习", "工作", "focus", "study"),
    "运动": ("运动", "跑步", "健身", "workout", "running"),
}
SCENE_DESCRIPTIONS = {
    "睡前": "优先安静、慢速",
    "放松": "优先舒缓、低活跃度",
    "专注": "优先平稳、适中速度",
    "运动": "优先活跃、快速",
}
UNSUPPORTED_WORDS = (
    "晚上", "夜晚", "适合", "治愈", "纯音乐", "有人声", "女声", "男声",
    "流派", "摇滚", "流行", "古典", "爵士", "悲伤", "伤感", "开心", "快乐", "温柔",
)


@dataclass(frozen=True)
class SearchIntent:
    themes: tuple[str, ...] = ()
    tempo_min: float | None = None
    tempo_max: float | None = None
    activity_min: float | None = None
    activity_max: float | None = None
    brightness_min: float | None = None
    artist: str = ""
    year_from: int | None = None
    year_to: int | None = None
    literal: str = ""
    scene: str = ""

    def conditions(self) -> tuple[str, ...]:
        items = [f"歌词主题：{'、'.join(self.themes)}"] if self.themes else []
        if self.scene:
            items.append(f"场景偏好：{self.scene}（{SCENE_DESCRIPTIONS[self.scene]}）")
        if self.tempo_max is not None:
            items.append(f"速度 ≤{self.tempo_max:g} BPM")
        if self.tempo_min is not None:
            items.append(f"速度 ≥{self.tempo_min:g} BPM")
        if self.activity_max is not None:
            items.append(f"活跃度 <{self.activity_max:g}/100")
        if self.activity_min is not None:
            items.append(f"活跃度 ≥{self.activity_min:g}/100")
        if self.brightness_min is not None:
            items.append(f"明亮度 ≥{self.brightness_min:g}/100")
        if self.artist:
            items.append(f"歌手：{self.artist}")
        if self.year_from is not None or self.year_to is not None:
            items.append(f"年份：{self.year_from or '不限'}—{self.year_to or '不限'}")
        if self.literal:
            items.append(f"文字包含：{self.literal}")
        return tuple(items)


@dataclass(frozen=True)
class SearchHit:
    track_id: str
    reasons: tuple[str, ...]
    score: float = 0.0


def _range(value: object, label: str, low: float, high: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{label}超出支持的范围。")
    return float(value)


def validate_intent(payload: Mapping[str, object]) -> SearchIntent:
    """Strict JSON contract for a future optional AI intent translator."""
    if not isinstance(payload, dict):
        raise ValueError("检索条件必须是一个对象。")
    allowed = set(SearchIntent.__dataclass_fields__)
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"不支持的检索字段：{', '.join(sorted(unknown))[:100]}")
    raw_themes = payload.get("themes", [])
    if not isinstance(raw_themes, list) or len(raw_themes) > 4 or any(
            not isinstance(theme, str) or theme not in THEME_ALIASES for theme in raw_themes):
        raise ValueError("主题须从固定标签表中选择。")
    themes = tuple(dict.fromkeys(raw_themes))
    scene = payload.get("scene", "")
    if not isinstance(scene, str) or (scene and scene not in SCENE_ALIASES):
        raise ValueError("场景须从支持的偏好中选择。")
    artist = payload.get("artist", "")
    literal = payload.get("literal", "")
    if not isinstance(artist, str) or len(artist) > 80 or not isinstance(literal, str) or len(literal) > 80:
        raise ValueError("歌手或关键词过长。")
    years = {}
    for field in ("year_from", "year_to"):
        value = payload.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1800 <= value <= 2100):
            raise ValueError("年份超出支持的范围。")
        years[field] = value
    values = {field: _range(payload.get(field), field, *bounds) for field, bounds in {
        "tempo_min": (1, 300), "tempo_max": (1, 300),
        "activity_min": (0, 100), "activity_max": (0, 100),
        "brightness_min": (0, 100),
    }.items()}
    for low, high in (("tempo_min", "tempo_max"), ("activity_min", "activity_max")):
        if values[low] is not None and values[high] is not None and values[low] > values[high]:
            raise ValueError("检索范围的下限不能大于上限。")
    if years["year_from"] and years["year_to"] and years["year_from"] > years["year_to"]:
        raise ValueError("年份范围的下限不能大于上限。")
    intent = SearchIntent(themes=themes, scene=scene, artist=artist.strip(), literal=literal.strip(), **years, **values)
    if not intent.conditions():
        raise ValueError("没有可执行的检索条件。")
    return intent


def parse_search(text: str, *, artists: Sequence[str] = ()) -> SearchIntent:
    """Conservative offline translation of common natural-language requests."""
    query = text.strip().casefold()
    if not query or len(query) > 500:
        raise ValueError("请输入 1—500 字的检索条件。")
    if any(word in query for word in ("不要", "不想", "排除", "除了", "或者", "或是")) or re.search(
            r"(?:不|别).{0,3}(?:快|慢)|not\s+(?:too\s+)?(?:fast|slow)", query):
        raise ValueError("当前支持同时满足的条件；否定和“或者”条件尚未实现。")
    scenes = [name for name, aliases in SCENE_ALIASES.items() if any(contains(query, alias) for alias in aliases)]
    if len(scenes) > 1:
        raise ValueError("请一次选择一个使用场景。")
    scene = scenes[0] if scenes else ""
    if any(word in query for word in UNSUPPORTED_WORDS if word != "适合" or not scene):
        raise ValueError("这个描述包含尚未分析的场景、人声或流派条件；请改用主题、快慢、活跃度、明亮度或歌手。")
    themes = tuple(name for name, aliases in THEME_ALIASES.items()
                   if any(contains(query, alias) for alias in aliases))
    slow = bool(re.search(r"慢|slow", query))
    fast = bool(re.search(r"快|fast", query))
    if slow and fast:
        raise ValueError("请只选择慢速或快速中的一种。")
    calm = any(word in query for word in ("安静", "平静", "舒缓", "calm"))
    energetic = any(word in query for word in ("活跃", "热烈", "激烈", "energetic"))
    if calm and energetic:
        raise ValueError("安静与活跃条件不能同时使用。")
    bright = any(word in query for word in ("明亮", "bright"))
    year_from = year_to = None
    after = re.search(r"((?:19|20)\d{2})年?(?:后|以来|以后)", query)
    before = re.search(r"((?:19|20)\d{2})年?(?:前|以前)", query)
    if after:
        year_from = int(after[1])
    if before:
        year_to = int(before[1])
    artist = next((name for name in sorted(set(artists), key=len, reverse=True)
                   if name and contains(query, name.casefold())), "")
    known = bool(scene or themes or slow or fast or calm or energetic or bright or year_from or year_to or artist)
    literal = "" if known else re.sub(r"^(?:帮我|给我|我想|想听|寻找|查找|找)(?:找|听)?|(?:的歌|的歌曲|歌曲|音乐)$", "", query).strip()
    return validate_intent({
        "themes": list(themes), "scene": scene, "tempo_max": 90 if slow else None,
        "tempo_min": 120 if fast else None,
        "activity_max": 35 if calm else None, "activity_min": 60 if energetic else None,
        "brightness_min": 60 if bright else None,
        "year_from": year_from, "year_to": year_to, "artist": artist, "literal": literal,
    })


def _scene_score(profile: TrackProfile, scene: str) -> float | None:
    """Acoustic preference ranking, not a factual claim of scene suitability."""
    activity_target, tempo_target, brightness_target = {
        "睡前": (15, 70, 35), "放松": (25, 80, 45),
        "专注": (25, 90, 45), "运动": (80, 135, 65),
    }[scene]
    signals = [(profile.activity, activity_target, 100, .65),
               (profile.tempo_bpm, tempo_target, 150, .25),
               (profile.brightness, brightness_target, 100, .10)]
    available = [(value, target, scale, weight) for value, target, scale, weight in signals if value is not None]
    if not available:
        return None
    return sum(max(0., 1-abs(value-target)/scale)*weight
               for value,target,scale,weight in available)/sum(row[3] for row in available)


def match_profiles(profiles: Mapping[str, TrackProfile], intent: SearchIntent) -> list[SearchHit]:
    """The same fact matching is used for offline and AI-translated intent."""
    hits: list[SearchHit] = []
    for profile in profiles.values():
        reasons: list[str] = []
        for theme in intent.themes:
            tag = profile.theme(theme)
            if tag is None:
                tag = next((profile.theme(child) for child in THEME_CHILDREN.get(theme, ()) if profile.theme(child)), None)
            if tag is None:
                break
            if tag.source == "ai_lyrics":
                reasons.append(f"AI 歌词主题：{tag.label}")
            elif tag.clues:
                reasons.append(f"歌词关键词线索：{tag.label}（{'、'.join(tag.clues[:3])}）")
            else:
                reasons.append(f"歌词主题：{tag.label}")
        else:
            bpm = profile.tempo_bpm
            if intent.tempo_min is not None or intent.tempo_max is not None:
                if bpm is None or (intent.tempo_min is not None and bpm < intent.tempo_min) or (
                        intent.tempo_max is not None and bpm > intent.tempo_max):
                    continue
                reasons.append(f"音频估计速度 {bpm:.0f} BPM")
            activity = profile.activity
            if intent.activity_min is not None or intent.activity_max is not None:
                if activity is None or (intent.activity_min is not None and activity < intent.activity_min) or (
                        intent.activity_max is not None and activity >= intent.activity_max):
                    continue
                reasons.append(f"音频活跃度 {activity:.0f}/100")
            if intent.brightness_min is not None:
                if profile.brightness is None or profile.brightness < intent.brightness_min:
                    continue
                reasons.append(f"音频明亮度 {profile.brightness:.0f}/100")
            if intent.year_from is not None or intent.year_to is not None:
                year = profile.year
                if year is None or (intent.year_from is not None and year < intent.year_from) or (
                        intent.year_to is not None and year > intent.year_to):
                    continue
                reasons.append(f"发行年份 {year}（{'QQ 音乐' if profile.year_source == 'qqmusic' else '原始元数据'}）")
            if intent.artist:
                if not contains(profile.artist.casefold(), intent.artist.casefold()):
                    continue
                reasons.append("歌手匹配")
            if intent.literal:
                metadata = " ".join((profile.title, profile.artist, profile.album)).casefold()
                if not contains(metadata, intent.literal.casefold()):
                    continue
                reasons.append("曲名／歌手／专辑匹配")
            score = 0.0
            if intent.scene:
                ranked = _scene_score(profile, intent.scene)
                if ranked is None:
                    continue
                score = ranked
                reasons.append(f"{intent.scene}偏好排序：{SCENE_DESCRIPTIONS[intent.scene]}")
            hits.append(SearchHit(profile.track_id, tuple(reasons), score))
    if intent.scene:
        hits.sort(key=lambda hit: -hit.score)
    return hits


def search_library(tracks: Sequence[TrackEncoding], text: str, *, lyrics_root: Path | None = None,
                   selected_sources: dict[str, Path] | None = None,
                   fallback_sources: Mapping[str, Path] | None = None,
                   profiles: Mapping[str, TrackProfile] | None = None,
                   intent: SearchIntent | None = None) -> list[SearchHit]:
    resolved = intent or parse_search(text, artists=[profile.artist for profile in profiles.values()] if profiles is not None
                                     else [track.metadata.artist for track in tracks])
    catalog = profiles if profiles is not None else build_track_profiles(
        tracks, lyrics_root=lyrics_root, selected_sources=selected_sources, fallback_sources=fallback_sources)
    hits = match_profiles(catalog, resolved)
    if not resolved.literal:
        return hits
    # Literal lyric search is separate, because TrackProfile never stores lyrics.
    selected = selected_sources or {}
    present = {hit.track_id for hit in hits}
    for track in tracks:
        if track.track_id in present:
            continue
        profile = catalog[track.track_id]
        if any((resolved.themes, resolved.tempo_min is not None, resolved.tempo_max is not None,
                resolved.activity_min is not None, resolved.activity_max is not None,
                resolved.brightness_min is not None, resolved.artist, resolved.year_from, resolved.year_to, resolved.scene)):
            continue
        lyric = resolve_track_lyrics(track, lyrics_root=lyrics_root, all_tracks=tracks,
                                     selected_path=selected.get(track.track_id),
                                     fallback_path=(fallback_sources or {}).get(track.track_id))
        if lyric.status == "valid" and contains(lyric.text.casefold(), resolved.literal.casefold()):
            hits.append(SearchHit(profile.track_id, ("歌词关键词匹配",)))
    return hits
