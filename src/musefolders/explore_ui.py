"""The local music exploration workspace.

All expensive analysis is explicit. Plot coordinates are only a view; playlist
ranking uses the original vectors retained by :mod:`sonic_map`.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import logging
import math
import os
from collections import Counter
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .adapters import LocalFolderAdapter
from .exploration import (
    ExplorationConstraints, ExplorationResult, similar_tracks, song_alchemy, song_path,
)
from .filter_assistant import FilterAssistantError, suggest_filters
from .lyrics_map import (
    FastTextLanguageDetector, LocalLyricsEmbedder, LyricsModelUnavailable,
    build_lyrics_map, build_title_clue_map, rank_theme_neighbors,
    resolve_track_lyrics, scan_lyric_languages,
)
from .theme_atlas import build_theme_atlas
from .astrology import build_zodiac, make_zodiac_share_card, ZODIAC_LABELS, ELEMENT_LABELS
from .metadata import read_cover_data_uri
from .models import CollectionPlan, TrackEncoding
from .playlist_filters import (PlaylistFilters, build_playlist_plan, facet_options, filter_tracks, matches,
                               playlist_bytes, relaxation_counts, safe_playlist_name)
from .playlist_draft import PlaylistDraft, apply_selection, load_draft, move_item, reconcile, save_draft
from .schemes import TAG_LABELS, VALUE_LABELS, compile_scheme
from .sonic_map import DEFAULT_MODEL_PATH, SonicMap, build_sonic_map
from .theme_assistant import ThemeAssistantError, preview_theme_request, suggest_theme
from .user_annotations import (
    clear_verified_genre, confirmed_instrumental_ids, set_instrumental_confirmation,
    set_theme_assignment, set_verified_genre, theme_assignments, verified_genre_assignments,
)


LOGGER = logging.getLogger(__name__)


# Static, trusted component code. All dynamic island names/counts arrive through
# Streamlit's JSON `data` argument and are inserted with textContent, never HTML.
_THEME_ISLAND_JS = r"""
export default function(component) {
  const {parentElement, data, setStateValue, setTriggerValue} = component;
  const root = parentElement.querySelector('[data-theme-atlas]');
  root.replaceChildren();
  const ns = 'http://www.w3.org/2000/svg';
  const toolbar = document.createElement('div');
  toolbar.className = 'theme-toolbar';
  root.appendChild(toolbar);
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('role', 'group');
  svg.setAttribute('aria-label', data.map_label);
  root.appendChild(svg);
  const levels = [1, 2, 4, 8];
  let viewport = Array.isArray(data.viewport) && data.viewport.length === 4
    ? data.viewport.map(Number) : [0, 0, 1000, 680];
  function normalize(box) {
    const width = Math.max(125, Math.min(1000, Number(box[2]) || 1000));
    const height = width * .68;
    return [Math.max(0, Math.min(1000-width, Number(box[0]) || 0)),
            Math.max(0, Math.min(680-height, Number(box[1]) || 0)), width, height];
  }
  function show() {
    viewport = normalize(viewport);
    svg.setAttribute('viewBox', viewport.join(' '));
    scale.textContent = String(Math.round(1000 / viewport[2])) + '×';
  }
  function persist() { show(); setStateValue('viewport', viewport); }
  function button(label, action) {
    const control = document.createElement('button');
    control.type = 'button'; control.textContent = label;
    control.setAttribute('aria-label', label);
    control.addEventListener('click', action); toolbar.appendChild(control);
  }
  function changeZoom(next) {
    const width = 1000 / next, height = 680 / next;
    viewport = [viewport[0] + (viewport[2]-width)/2,
                viewport[1] + (viewport[3]-height)/2, width, height];
    persist();
  }
  button(data.zoom_out, () => {
    const current = 1000 / viewport[2];
    changeZoom(levels[Math.max(0, levels.findIndex(v => v >= current - .01)-1)] || 1);
  });
  const scale = document.createElement('span');
  scale.className = 'theme-scale'; scale.setAttribute('aria-live', 'polite');
  toolbar.appendChild(scale);
  button(data.zoom_in, () => {
    const current = 1000 / viewport[2];
    changeZoom(levels.find(v => v > current + .01) || 8);
  });
  button(data.zoom_reset, () => { viewport = [0,0,1000,680]; persist(); });
  show();
  let drag = null;
  svg.addEventListener('pointerdown', event => {
    drag = {x: event.clientX, y: event.clientY, box: viewport.slice(), moved: false};
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove', event => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect();
    const dx = (event.clientX-drag.x) * viewport[2] / Math.max(rect.width, 1);
    const dy = (event.clientY-drag.y) * viewport[3] / Math.max(rect.height, 1);
    if (Math.abs(event.clientX-drag.x) + Math.abs(event.clientY-drag.y) > 4) drag.moved = true;
    if (drag.moved) { viewport = [drag.box[0]-dx, drag.box[1]-dy, drag.box[2], drag.box[3]]; show(); }
  });
  svg.addEventListener('pointerup', () => {
    if (!drag) return;
    if (drag.moved) { root.dataset.justDragged = '1'; persist(); }
    drag = null;
  });
  for (const region of data.regions) {
    const group = document.createElementNS(ns, 'g');
    group.classList.add('theme-region');
    if (region.id === data.selected) group.classList.add('theme-selected');
    group.setAttribute('role', 'button');
    group.setAttribute('tabindex', '0');
    group.setAttribute('aria-label', region.label + ', ' + region.count + ' ' + data.song_unit);
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', 'M ' + region.outline.map(p => p[0] + ',' + p[1]).join(' L ') + ' Z');
    path.setAttribute('fill', region.fill);
    group.appendChild(path);
    const name = document.createElementNS(ns, 'text');
    name.setAttribute('x', region.center[0]);
    name.setAttribute('text-anchor', 'middle');
    name.classList.add('theme-name');
    const han = /[\u3400-\u9fff]/.test(region.label);
    const words = region.label.split(/\s+/).filter(Boolean);
    let lines = [region.label];
    if (han && Array.from(region.label).length > 3) {
      const chars = Array.from(region.label);
      lines = [chars.slice(0, Math.ceil(chars.length / 2)).join(''),
               chars.slice(Math.ceil(chars.length / 2)).join('')];
    } else if (!han && words.length > 1) {
      const split = Math.ceil(words.length / 2);
      lines = [words.slice(0, split).join(' '), words.slice(split).join(' ')];
    }
    name.style.fontSize = han ? '15px' : (region.label.length > 8 ? '11px' : '13px');
    name.setAttribute('y', region.center[1] - (lines.length > 1 ? 19 : 7));
    for (let index = 0; index < lines.length; index++) {
      const line = document.createElementNS(ns, 'tspan');
      line.setAttribute('x', region.center[0]);
      line.setAttribute('dy', index === 0 ? '0' : '17');
      line.textContent = lines[index];
      name.appendChild(line);
    }
    group.appendChild(name);
    const count = document.createElementNS(ns, 'text');
    count.setAttribute('x', region.center[0]);
    count.setAttribute('y', region.center[1] + 21);
    count.setAttribute('text-anchor', 'middle');
    count.classList.add('theme-count');
    count.textContent = String(region.count) + ' ' + data.song_unit;
    group.appendChild(count);
    group.addEventListener('click', () => {
      if (root.dataset.justDragged === '1') { root.dataset.justDragged = ''; return; }
      setTriggerValue('clicked', region.id);
    });
    group.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        setTriggerValue('clicked', region.id);
      }
    });
    svg.appendChild(group);
    // Long translated labels must stay inside a small island rather than
    // becoming unreadable against the page background in dark mode.
    const islandWidth = Math.max(42, Math.max(...region.outline.map(p => p[0]))
                                - Math.min(...region.outline.map(p => p[0])) - 14);
    for (const line of name.children) {
      if (line.getComputedTextLength() > islandWidth) {
        line.setAttribute('textLength', islandWidth);
        line.setAttribute('lengthAdjust', 'spacingAndGlyphs');
      }
    }
  }
}
"""
_THEME_ISLAND_CSS = """
[data-theme-atlas] { width: 100%; border-radius: 18px; background: var(--st-secondary-background-color, #f5f8fc); overflow: hidden; }
[data-theme-atlas] svg { display: block; width: 100%; height: auto; min-height: 340px; }
[data-theme-atlas] .theme-toolbar { display: flex; align-items: center; justify-content: flex-end; gap: .4rem; padding: .35rem .55rem; }
[data-theme-atlas] .theme-toolbar button { border: 1px solid #8f9aab; border-radius: 7px; background: transparent; color: var(--st-text-color, #1e2d41); padding: .2rem .55rem; cursor: pointer; }
[data-theme-atlas] .theme-toolbar button:focus-visible { outline: 2px solid #e4574f; }
[data-theme-atlas] .theme-scale { min-width: 2.3rem; text-align: center; font: 600 13px system-ui, sans-serif; }
.theme-region { cursor: pointer; }
.theme-region path { stroke: var(--st-secondary-background-color, #f5f8fc); stroke-width: 4; transition: filter .16s, stroke .16s; }
.theme-region:hover path, .theme-region:focus path { filter: brightness(.94); stroke: #586a86; }
.theme-region:focus { outline: none; }
.theme-selected path { stroke: #e4574f; stroke-width: 7; }
.theme-name { font: 600 16px system-ui, sans-serif; fill: #1e2d41; pointer-events: none; }
.theme-count { font: 12px system-ui, sans-serif; fill: #465972; pointer-events: none; }
"""
_THEME_COLORS = {
    "love": "#f4c4c2", "family": "#f4d4aa", "friendship": "#bde0c5",
    "memory": "#ced0eb", "solitude": "#b9d3ec", "hope": "#f2e9ac",
    "journey": "#b7dfdf", "celebration": "#f5c6a5", "nature": "#b9dfad",
    "unknown": "#d9dde3",
}

LABELS = {
    "zh": {
        "intro": "从曲库出发，在四张地图中探索、试听、筛选，审查后再保存歌单。",
        "sonic_view": "听感地图", "lyrics_view": "歌曲主题地图", "genre_view": "流派地图", "language_view": "演唱语言地图", "basic_mode": "基础声学地图",
        "model_mode": "模型听感地图", "basic_warning": "目前显示基础声学地图：位置主要依赖节奏与明亮度等声学量，不能等同完整声音画像的邻域图。",
        "build_model": "建立模型听感地图", "model_missing": "缺少本地音乐模型文件，暂时只能使用基础声学地图。",
        "model_failure": "模型分析未成功，保留基础声学地图。请检查模型文件、运行环境及分析档案。",
        "model_progress": "正在建立声音画像", "map_coverage": "地图覆盖", "cache_hits": "复用缓存",
        "color": "地图着色", "color_act": "声音活跃度", "color_bri": "声音明亮度",
        "map_action": "地图操作", "action_point": "点选歌曲", "action_box": "框选区域", "action_lasso": "圈选区域",
        "color_genre": "原始流派", "color_instrument": "主要声源", "unprovided": "未提供",
        "unknown": "待确定", "map_help": "横向是节奏速度趋势，纵向是明亮度趋势，颜色是活跃度。位置受声音画像微调，不是精确刻度；相似曲仍按完整声音画像排序。点选可查看，框选或圈选可加入候选。",
        "tempo_axis": "节奏速度趋势（BPM）· 慢 → 快", "bri_axis": "明亮度趋势（BRI）· 暗 → 亮",
        "act_colorbar": "活跃度 ACT", "exact_tempo": "实际节奏速度", "exact_bri": "实际明亮度", "exact_act": "实际活跃度",
        "map_trend_note": "横纵是趋势而非精确数值；准确数值见悬停提示和曲目详情。二维距离不等于完整声音画像距离。",
        "map_semantic_only": "当前没有可证明有益的声音画像位置微调，点位仅按节奏与明亮度趋势排列；相似曲仍按声音画像计算。",
        "map_hybrid": "点位在节奏与明亮度趋势上进行了受约束的声音画像微调。",
        "legacy_brightness_warning": "旧分析档案缺少新版明亮度所需的高频比例。请回到分析页重新分析来源文件夹，然后再判断明亮度和地图分布。",
        "axis_fidelity_warning": "这批歌曲的横纵趋势一致性偏低，请以悬停的实际数值为准，不要把轴位置当精确测量。",
        "low_tempo_warning": "部分歌曲节奏估计可信度较低；它们的横向位置仅供参考。",
        "layout_quality": "地图布局校验", "tempo_order": "节奏轴排序一致度", "bri_order": "明亮度轴排序一致度",
        "neighbor_retention": "前十邻曲保留率", "layout_quality_note": "轴排序一致度范围为 −1 至 1，越接近 1 越符合实测顺序；邻曲保留率是二维地图与完整声音画像的前十邻曲重合比例，不是听感正确率。",
        "basic_layout_note": "轴排序一致度范围为 −1 至 1，越接近 1 越符合实测顺序。基础声学地图不报告模型听感邻域保留率。",
        "selected_count": "地图已选", "clear_map": "清除地图选区", "use_region": "将选区列为待加入",
        "zoom_in": "放大", "zoom_out": "缩小", "zoom_reset": "复位", "zoom_note": "查看倍率 {scale}×；不是歌曲距离的单位。",
        "overlap": "重叠歌曲", "overlap_group": "重叠位置", "overlap_view": "查看这首歌",
        "step_find": "① 找歌", "step_review": "② 审查", "step_save": "③ 保存",
        "current_draft": "当前候选", "go_review": "去审查", "go_save": "去保存", "back_find": "继续找歌",
        "stage_focus": "将当前歌曲列为待加入",
        "pending": "这批发现", "add_candidates": "加入候选", "intersect_candidates": "仅保留交集", "replace_candidates": "新建候选",
        "missing_draft": "草稿中有 {count} 首原歌曲已不在当前曲库；不会用其他录音替代。请重扫或新建候选。",
        "draft_error": "无法读取或保存本地歌单草稿；请检查分析档案目录。", "move_up": "上移", "move_down": "下移", "reorder": "调整歌曲顺序",
        "scale_note": "倍率只改变查看范围，声音坐标与主题判断不变。",
        "grouped_copy": "按标签分成多个文件夹", "group_tags": "选择分组标签（1—3项）",
        "group_preview": "预计文件夹", "group_many": "文件夹较多，可减少标签再生成。",
        "filter_assistant": "可选：用一句话提出筛选条件", "filter_prompt": "你想找什么样的歌曲？",
        "filter_consent": "同意仅发送上面的描述文字到大模型；不发送音频、歌词、曲名或本地路径",
        "filter_run": "提出条件草案", "filter_key_missing": "未配置新的大模型密钥；可继续使用下方手动筛选和地图。",
        "filter_error": "条件草案生成失败；请检查网络或密钥，手动筛选仍可使用。",
        "filter_unsupported": "无法可靠表达的要求", "filter_explanation": "模型说明",
        "filter_matched": "草案预计匹配", "filter_stage": "确认草案并列为待加入",
        "filter_zero": "当前草案匹配零首，请修改条件；不会自动加入无关歌曲。",
        "filter_clear": "撤销这份草案", "filter_title": "曲名包含",
        "filter_year": "发行时间", "filter_key": "调性",
        "undo_filter": "撤销最近一项条件修改",
        "song_search": "搜索或选择歌曲", "detail": "歌曲详情", "cover_missing": "没有内嵌封面",
        "title": "曲名", "artist": "歌手", "album": "专辑", "genre": "原始流派", "instrument": "主要声源",
        "tempo": "节奏", "loudness": "响度代理", "act": "声音活跃度", "bri": "声音明亮度",
        "metadata_caution": "流派来自原始文件；乐器及听感标签是估计值，不能当作演奏名单。",
        "verified": "已人工确认无人声", "verify": "试听后标记为无人声", "unverify": "撤销无人声确认",
        "verify_help": "仅人工确认的曲目可通过严格“无人声”筛选；钢琴等主要声源标签不能证明整首无人声。",
        "verify_error": "无法保存确认。请检查分析档案目录的写入权限。",
        "hard_filters": "不可放宽的条件", "genre_filter": "原始流派", "instrument_filter": "主要声源",
        "act_filter": "活跃度范围", "bri_filter": "明亮度范围", "no_vocals": "必须已确认无人声",
        "no_vocals_warning": "目前没有人工确认无人声的歌曲；开启此条件将得到空结果。",
        "similar": "按听感找相似", "path": "渐变路径", "alchemy": "混合歌单", "find_similar": "按听感找相似",
        "similar_help": "从当前歌曲出发，在原始声音画像中寻找邻曲；不会按二维画面距离直接排序。",
        "path_start": "起点", "path_end": "终点", "path_length": "期望曲数", "make_path": "生成渐变路径",
        "path_help": "在两首歌之间逐步寻找真实曲目。曲库不够时会缩短，不会塞入不相关歌曲。",
        "positive": "喜欢的歌曲", "negative": "希望避开的歌曲", "negative_strength": "排斥范围（曲库比例）",
        "make_alchemy": "生成混合歌单", "alchemy_help": "把喜欢的歌曲作为混合中心；排斥范围会剔除靠近不喜欢歌曲的候选，不是假装做声音减法。",
        "requested": "期望数量", "candidate": "候选歌单", "no_candidate": "尚无候选。可选一首歌找相似曲，或圈选地图区域。",
        "excluded": "从结果中移除", "remaining": "保留曲目", "preview_song": "试听候选曲目",
        "score": "画像贴合度", "score_note": "贴合度是声音画像中的比较分数，不是正确率或流派概率。",
        "common": "可核对的共同特征", "no_common": "没有足够可靠的共同特征；请试听判断。",
        "playlist_name": "歌单名称", "name_default": "我的地图歌单", "name_invalid": "请输入有效名称。",
        "download": "下载播放清单", "download_note": "播放清单引用本地原文件；移动原文件后需重新生成。",
        "copy": "复制为文件夹", "output": "输出位置", "copy_preview": "复制预览", "source": "源文件", "target": "目标文件",
        "agree": "我已试听并核对曲目及目标位置，同意创建副本", "create": "创建文件夹", "created": "文件夹已创建",
        "copy_error": "无法创建文件夹。请检查路径、重复文件及写入权限。", "duplicate": "相同歌单已在此位置创建。",
        "undo": "撤销上次复制", "undo_agree": "确认仅删除本次记录且未修改的副本", "undone": "已撤销副本",
        "status_shortfall": "条件下可用曲目不足，已返回真实匹配结果；没有补入无关歌曲。",
        "status_no_candidates": "没有满足条件的曲目；可尝试放宽条件或人工确认无人声。",
        "status_no_path": "当前曲库中找不到可信的过渡路径；请换起终点或放宽条件。",
        "status_anchor_missing_embedding": "所选歌曲缺少可用的声音画像。",
        "status_anchor_filtered": "起点或终点被当前严格条件排除。",
        "status_same_content": "起点和终点是相同音频。",
        "status_unknown_anchor": "所选歌曲已不在当前曲库，请重新分析。",
        "status_invalid_parameters": "参数无效，请检查曲数与条件。",
        "status_other": "当前组合无法生成结果，请调整选曲或条件。",
        "lyrics_intro": "主题相近的区块彼此靠近；通常越大歌越多，确切数量以数字为准。横纵没有固定含义，无歌词时标题仅提供有限线索。",
        "lyrics_folder": "可选的独立歌词文件夹", "lyrics_scan": "读取本地歌词并建图",
        "lyrics_local_only": "仅读取本地嵌入歌词、同名歌词文件及指定文件夹；不会自动访问歌词网站。",
        "lyrics_language_model": "本地语言识别模型文件（可选）", "lyrics_language_model_missing": "未提供可用的本地语言识别模型；语言暂记为未知，不根据歌名或歌手猜测。",
        "lyrics_source": "歌词来源", "lyrics_source_adjacent": "音频旁的同名文件", "lyrics_source_embedded": "音频内嵌歌词",
        "lyrics_source_external": "指定歌词文件夹", "lyrics_source_manual": "人工指定文件",
        "lyrics_status": "歌词状态", "lyrics_match": "确认歌词匹配", "lyrics_match_file": "选择正确的歌词文件",
        "lyrics_match_help": "同名歌词有多个候选时，请确认对应文件；未确认前不会拿它做主题或语言判断。",
        "lyrics_allow_download": "同意下载固定版本本地多语模型，并在本机运行其模型代码",
        "lyrics_download_warning": "模型体积较大且包含第三方模型代码；仅勾选后才允许下载。默认不会上传歌词。",
        "lyrics_coverage": "有效歌词", "lyrics_valid": "已读取", "lyrics_missing": "未提供", "lyrics_short": "文本不足",
        "lyrics_ambiguous": "匹配不明确", "lyrics_instrumental": "人工确认为纯音乐", "lyrics_read_error": "读取失败",
        "lyrics_no_data": "还没有可用的主题线索。可补充歌词，或人工确认曲目主题。",
        "lyrics_model_missing": "本地多语文本模型尚未就绪。当前可用基础标题词线索与人工修正；若要理解歌词或隐喻歌名，请安装可选歌词依赖，并明确同意下载本地模型。不会自动改用云端模型。",
        "lyrics_other_error": "歌词分析未成功。请检查歌词编码、模型安装与分析档案权限。",
        "lyrics_theme": "建议主题", "lyrics_theme_note": "主题是与参考描述的相近程度，不是客观类型或概率；用户可凭歌词自行判断。",
        "theme_love": "爱情", "theme_family": "亲情", "theme_friendship": "友情",
        "theme_memory": "回忆", "theme_solitude": "孤独", "theme_hope": "希望与成长",
        "theme_journey": "旅途", "theme_celebration": "欢聚", "theme_nature": "自然",
        "theme_unknown": "待确认", "theme_map_label": "可点击的主题群岛", "theme_song_unit": "首",
        "theme_region": "主题区块", "theme_region_tracks": "区块内歌曲", "theme_play": "试听区块歌曲",
        "theme_add": "加入候选歌单", "theme_find_similar": "按主题找相似",
        "theme_similar_note": "使用原始文字语义画像检索，不按区块之间的屏幕距离排序。",
        "theme_no_embedding": "所选歌曲没有可用的文字画像，无法按主题找相似。",
        "theme_evidence": "主题依据", "theme_evidence_lyrics": "歌词支持",
        "theme_evidence_partial_lyrics": "部分歌词支持", "theme_evidence_title_only": "仅标题推测",
        "theme_evidence_title_clue": "基础标题线索",
        "theme_evidence_manual": "人工修正", "theme_evidence_unknown": "待确认",
        "theme_edit": "人工修正主题", "theme_save": "保存主题修正", "theme_reset": "撤销人工修正",
        "theme_save_error": "无法保存主题修正；请检查分析档案目录写入权限。",
        "theme_manual_note": "试听或核对内容后再修正；标题推测不等于歌词证明。",
        "theme_empty_region": "当前区块没有可审查的曲目。",
        "theme_region_note": "选中的曲目先进入候选区供试听与排除；下方的严格条件仅用于听感推荐玩法。",
        "theme_component_error": "主题区块交互暂不可用；请更新至支持组件的 Streamlit 版本，或先用下方列表选择主题。",
        "theme_basic_title": "基础标题线索图：只匹配明确的标题词汇，不能理解隐喻；其余歌曲保留“待确认”。安装并启用本地文本模型后才能进行语义分析。",
        "theme_score_note": "这是文字画像相近度，不是主题正确率。",
        "theme_score": "主题画像相近度",
        "zodiac_seed": "星群种子", "zodiac_seed_note": "至少需要 12 首不同音频，才能从十二种趣味轮廓中选择一款。",
        "zodiac_heading": "听感星象", "zodiac_overlay": "显示星象轮廓", "zodiac_auto": "自动匹配",
        "zodiac_choice": "星座外观", "zodiac_element": "对应元素", "zodiac_override": "自选外观",
        "zodiac_explain": "象征性轮廓只供趣味探索，不是天文星图或人格判断。元素只由星座外观对应得出。",
        "zodiac_representatives": "点阵代表曲目", "zodiac_include_titles": "分享卡包含代表曲目名",
        "zodiac_download": "下载本地星象卡", "zodiac_card_error": "分享卡生成失败；请检查本地图像依赖。",
        "genre_intro": "按已核实的流派形成分类群岛；原始文件中的流派不等于已核实分类。群岛内位置只为避免重叠。",
        "genre_coverage": "已核实流派", "genre_insufficient": "可靠流派类别不足，暂不能绘制有意义的流派地图。可在右侧曲目详情逐首核实流派；原始文件流派仍可查看，但不会自动当作事实。",
        "genre_review": "人工核实流派", "genre_review_help": "请先试听并核对可靠来源，再填写专业流派；原始文件中的流派仅供参考，不会自动认证。",
        "genre_review_input": "已核实的专业流派", "genre_review_save": "保存核实流派", "genre_review_clear": "撤销流派核实",
        "genre_review_error": "无法保存流派核实；请检查名称和分析档案目录的写入权限。",
        "genre_categories": "可靠流派类别", "category_help": "同一群岛表示同一类别；群岛之间的距离没有流派或语言远近含义。",
        "category": "分类",
        "language_intro": "按歌词识别到的演唱语言分群。缺歌词、语种混合或纯音乐分别列示，不根据歌名猜测。",
        "language_insufficient": "尚无可靠的歌词语言结果。先导入歌词并提供本地语言识别模型。",
        "language_coverage": "已识别语言", "language_zh": "中文", "language_en": "英语", "language_de": "德语",
        "language_ja": "日语", "language_ko": "韩语", "language_fr": "法语", "language_es": "西班牙语",
        "language_mixed": "多种语言", "language_unknown": "未知", "language_instrumental": "已确认纯音乐",
        "language_status": "演唱语言", "language_uncertain": "语言未获可靠识别，不能仅凭标题判断。",
        "language_runtime_unavailable": "本地语言识别尚不可用。请检查模型文件和 fasttext 可选依赖，然后重新读取歌词。",
        "assistant_title": "可选的主题解释", "assistant_purpose": "仅在你逐曲确认后，将下方显示的标题与歌词片段发送给 DeepSeek，用于生成可审查的主题建议；本地地图不依赖它。",
        "assistant_preview": "将发送的文字", "assistant_consent": "我同意仅将这首歌显示的标题与歌词片段发送给 DeepSeek",
        "assistant_run": "生成这首歌的主题解释", "assistant_key_missing": "本机尚未设置新的 DEEPSEEK_API_KEY；请先轮换已公开的旧密钥，并通过本机环境变量配置，不要写入代码或聊天。",
        "assistant_unavailable": "这首歌还没有可用的本地歌词，无法生成有依据的主题解释。",
        "assistant_error": "主题解释请求失败；请检查网络、密钥权限或服务状态。本地地图不受影响。",
        "assistant_result": "主题建议", "assistant_model": "模型", "assistant_destination": "接收服务",
    },
    "en": {
        "intro": "Explore your library across four maps, listen, filter, and review before saving a playlist.",
        "sonic_view": "Sound map", "lyrics_view": "Song theme map", "genre_view": "Genre map", "language_view": "Vocal language map", "basic_mode": "Basic acoustic map",
        "model_mode": "Model-based sound map", "basic_warning": "This basic acoustic map places tracks mainly by tempo and brightness. It is not a full sound-profile neighborhood map.",
        "build_model": "Build model-based sound map", "model_missing": "The local music model file is missing; only the basic acoustic map is available.",
        "model_failure": "Model analysis did not succeed. The basic map remains available; check the model, runtime, and analysis records.",
        "model_progress": "Building sound profiles", "map_coverage": "Map coverage", "cache_hits": "Cached profiles",
        "color": "Color by", "color_act": "Activity", "color_bri": "Brightness",
        "map_action": "Map action", "action_point": "Inspect a point", "action_box": "Box-select", "action_lasso": "Lasso-select",
        "color_genre": "Raw genre", "color_instrument": "Main sound", "unprovided": "Not provided",
        "unknown": "Uncertain", "map_help": "Horizontal position trends from slow to fast, vertical from dark to bright, and color shows activity. Sound profiles adjust positions slightly, so axes are trends, not exact scales. Similarity still uses full sound profiles. Click to inspect; box or lasso to add candidates.",
        "tempo_axis": "Tempo trend (BPM) · slow → fast", "bri_axis": "Brightness trend (BRI) · dark → bright",
        "act_colorbar": "Activity ACT", "exact_tempo": "Measured tempo", "exact_bri": "Measured brightness", "exact_act": "Measured activity",
        "map_trend_note": "Axes show trends, not exact values; hover or open track details for measurements. Two-dimensional distance is not the full sound-profile distance.",
        "map_semantic_only": "No beneficial sound-profile adjustment was supported for these tracks, so positions follow tempo and brightness trends alone. Similarity still uses full profiles.",
        "map_hybrid": "Sound profiles adjust positions within tempo and brightness trend constraints.",
        "legacy_brightness_warning": "These older analysis records lack the high-frequency measure needed for the revised brightness score. Re-analyze the source folder before judging brightness or map placement.",
        "axis_fidelity_warning": "Axis trend fidelity is low for this library. Trust the measured values on hover, not exact point position.",
        "low_tempo_warning": "Some tempo estimates have low confidence, so their horizontal positions are only approximate.",
        "layout_quality": "Map layout checks", "tempo_order": "Tempo-axis rank agreement", "bri_order": "Brightness-axis rank agreement",
        "neighbor_retention": "Top-10 neighbor retention", "layout_quality_note": "Axis rank agreement runs from −1 to 1; values nearer 1 follow measured order more closely. Neighbor retention compares the map's and full sound profiles' top-10 neighbors; it is not listening accuracy.",
        "basic_layout_note": "Axis rank agreement runs from −1 to 1; values nearer 1 follow measured order more closely. A basic acoustic map cannot report model-profile neighbor retention.",
        "selected_count": "Selected on map", "clear_map": "Clear map selection", "use_region": "Stage selected region",
        "zoom_in": "Zoom in", "zoom_out": "Zoom out", "zoom_reset": "Reset view", "zoom_note": "View magnification {scale}×; not a song-distance unit.",
        "overlap": "Overlapping songs", "overlap_group": "Crowded location", "overlap_view": "Inspect this song",
        "step_find": "① Find", "step_review": "② Review", "step_save": "③ Save",
        "current_draft": "Current candidates", "go_review": "Review candidates", "go_save": "Continue to save", "back_find": "Find more songs",
        "stage_focus": "Stage current song",
        "pending": "Newly found songs", "add_candidates": "Add to candidates", "intersect_candidates": "Keep intersection", "replace_candidates": "Start new candidates",
        "missing_draft": "{count} songs in this draft are no longer in the current library. No different recording will be substituted. Rescan or start new candidates.",
        "draft_error": "Could not read or save the local playlist draft. Check the analysis-records folder.", "move_up": "Move up", "move_down": "Move down", "reorder": "Reorder songs",
        "scale_note": "Magnification only changes the view, not sound coordinates or theme evidence.",
        "grouped_copy": "Split into folders by tags", "group_tags": "Grouping tags (1–3)",
        "group_preview": "Proposed folders", "group_many": "Many folders will be created. Consider fewer tags.",
        "filter_assistant": "Optional: describe the songs you want", "filter_prompt": "What kind of songs would you like?",
        "filter_consent": "Send only the description above to the model; no audio, lyrics, song titles or local paths",
        "filter_run": "Propose filter draft", "filter_key_missing": "No new model key is configured. Maps and manual filters still work.",
        "filter_error": "Could not propose filters. Check connection or key; manual filtering still works.",
        "filter_unsupported": "Requests not reliably expressible", "filter_explanation": "Model note",
        "filter_matched": "Draft matches", "filter_stage": "Confirm draft and stage songs",
        "filter_zero": "This draft matches no songs. Edit its conditions; unrelated songs will not be added.",
        "filter_clear": "Discard this draft", "filter_title": "Title contains",
        "filter_year": "Release year", "filter_key": "Key",
        "undo_filter": "Undo the latest filter change",
        "song_search": "Search or select a track", "detail": "Track details", "cover_missing": "No embedded cover",
        "title": "Title", "artist": "Artist", "album": "Album", "genre": "Raw genre", "instrument": "Main sound",
        "tempo": "Tempo", "loudness": "Loudness proxy", "act": "Activity", "bri": "Brightness",
        "metadata_caution": "Genre is raw file metadata. Sound and instrument labels are estimates, not performance credits.",
        "verified": "Confirmed instrumental", "verify": "Confirm no vocals after listening", "unverify": "Remove no-vocals confirmation",
        "verify_help": "Only manually confirmed tracks pass the strict no-vocals filter. A piano label does not establish that the whole song has no vocals.",
        "verify_error": "Could not save the confirmation. Check write access to analysis records.",
        "hard_filters": "Strict conditions", "genre_filter": "Raw genres", "instrument_filter": "Main sounds",
        "act_filter": "Activity range", "bri_filter": "Brightness range", "no_vocals": "Require confirmed instrumental",
        "no_vocals_warning": "No tracks have been manually confirmed instrumental. This condition will return no results.",
        "similar": "Find by sound", "path": "Song path", "alchemy": "Song blend", "find_similar": "Find by sound",
        "similar_help": "Find neighbors using source sound profiles, not direct distances on the 2D display.",
        "path_start": "Start track", "path_end": "End track", "path_length": "Target track count", "make_path": "Build song path",
        "path_help": "Choose real songs along a gradual transition. A small library may yield a shorter path; unrelated songs are never added to fill it.",
        "positive": "Songs you like", "negative": "Songs to avoid", "negative_strength": "Exclusion share of library",
        "make_alchemy": "Build song blend", "alchemy_help": "Liked songs form a blend center; the exclusion share removes candidates near disliked songs. This is not literal audio subtraction.",
        "requested": "Target count", "candidate": "Candidate playlist", "no_candidate": "No candidates yet. Find neighbors of one song or select a map region.",
        "excluded": "Remove from results", "remaining": "Tracks kept", "preview_song": "Listen to a candidate",
        "score": "Profile fit", "score_note": "Fit compares sound profiles; it is not accuracy or genre probability.",
        "common": "Shared features to check", "no_common": "No reliable shared feature to show; please listen and decide.",
        "playlist_name": "Playlist name", "name_default": "My map playlist", "name_invalid": "Enter a valid name.",
        "download": "Download playlist", "download_note": "This playlist references the original files; recreate it if they move.",
        "copy": "Copy into a folder", "output": "Output location", "copy_preview": "Copy preview", "source": "Source file", "target": "Target file",
        "agree": "I listened to and reviewed the tracks and destination; create copies", "create": "Create folder", "created": "Folder created",
        "copy_error": "Could not create the folder. Check the path, existing files, and permissions.", "duplicate": "This playlist was already created here.",
        "undo": "Undo last copy", "undo_agree": "Remove only unchanged copies recorded in this run", "undone": "Copies undone",
        "status_shortfall": "Fewer tracks meet the conditions; only actual matches were returned, with no unrelated filler.",
        "status_no_candidates": "No tracks meet the conditions. Relax a filter or confirm instrumental tracks manually.",
        "status_no_path": "No credible transition path was found. Change the endpoints or relax the conditions.",
        "status_anchor_missing_embedding": "A selected track has no usable sound profile.",
        "status_anchor_filtered": "A start or end track is excluded by a strict condition.",
        "status_same_content": "The endpoints contain the same audio.",
        "status_unknown_anchor": "A selected track is no longer in this library; analyze it again.",
        "status_invalid_parameters": "Invalid parameters; check the count and conditions.",
        "status_other": "This combination cannot produce results. Adjust tracks or conditions.",
        "lyrics_intro": "Related theme regions sit nearby. Larger usually means more tracks; use the printed count for exact numbers. The axes have no fixed meaning. Titles offer limited clues when lyrics are absent.",
        "lyrics_folder": "Optional separate lyrics folder", "lyrics_scan": "Read local lyrics and build map",
        "lyrics_local_only": "Reads only embedded lyrics, adjacent matching lyric files, and the chosen folder. No lyric sites are contacted automatically.",
        "lyrics_language_model": "Local language-ID model file (optional)", "lyrics_language_model_missing": "No usable local language-ID model is set. Language stays unknown; titles and artists are not used to guess it.",
        "lyrics_source": "Lyrics source", "lyrics_source_adjacent": "Matching file beside audio", "lyrics_source_embedded": "Embedded in audio",
        "lyrics_source_external": "Chosen lyrics folder", "lyrics_source_manual": "Manually chosen file",
        "lyrics_status": "Lyrics status", "lyrics_match": "Confirm lyric match", "lyrics_match_file": "Choose the correct lyric file",
        "lyrics_match_help": "When multiple lyric files match, confirm the right one. No theme or language is inferred until then.",
        "lyrics_allow_download": "Allow downloading a pinned local multilingual model and running its model code on this device",
        "lyrics_download_warning": "The model is large and contains third-party model code. It is downloaded only after opt-in. Lyrics are not uploaded by default.",
        "lyrics_coverage": "Usable lyrics", "lyrics_valid": "Available", "lyrics_missing": "Missing", "lyrics_short": "Too short",
        "lyrics_ambiguous": "Ambiguous match", "lyrics_instrumental": "Manually marked instrumental", "lyrics_read_error": "Read error",
        "lyrics_no_data": "No usable theme clues yet. Add lyrics or manually confirm themes.",
        "lyrics_model_missing": "The local multilingual text model is unavailable. Basic title cues and manual corrections still work. For lyric or metaphorical-title understanding, install the optional lyrics dependencies and explicitly opt in to download the local model. No cloud model is used automatically.",
        "lyrics_other_error": "Lyrics analysis failed. Check file encoding, model installation, and analysis-records permissions.",
        "lyrics_theme": "Suggested theme", "lyrics_theme_note": "Themes compare with reference descriptions; they are not objective categories or probabilities. Review the lyrics yourself.",
        "theme_love": "Love", "theme_family": "Family", "theme_friendship": "Friendship",
        "theme_memory": "Memory", "theme_solitude": "Solitude", "theme_hope": "Hope and growth",
        "theme_journey": "Journey", "theme_celebration": "Celebration", "theme_nature": "Nature",
        "theme_unknown": "To review", "theme_map_label": "Clickable theme islands", "theme_song_unit": "tracks",
        "theme_region": "Theme region", "theme_region_tracks": "Tracks in region", "theme_play": "Preview a region track",
        "theme_add": "Add to playlist tray", "theme_find_similar": "Find by theme",
        "theme_similar_note": "Search uses original text embeddings, not on-screen region distance.",
        "theme_no_embedding": "The selected track has no text embedding and cannot seed a theme-neighbor search.",
        "theme_evidence": "Theme evidence", "theme_evidence_lyrics": "Supported by lyrics",
        "theme_evidence_partial_lyrics": "Supported by partial lyrics", "theme_evidence_title_only": "Title-based guess",
        "theme_evidence_title_clue": "Basic title clue",
        "theme_evidence_manual": "Manual correction", "theme_evidence_unknown": "To review",
        "theme_edit": "Correct theme manually", "theme_save": "Save correction", "theme_reset": "Remove correction",
        "theme_save_error": "Could not save theme correction. Check write access to analysis records.",
        "theme_manual_note": "Listen or inspect content before correcting. A title guess is not lyric evidence.",
        "theme_empty_region": "No reviewable tracks are in this region.",
        "theme_region_note": "Selected tracks go to the review tray for listening and removal. The strict conditions below apply to sound-based recommendations only.",
        "theme_component_error": "Interactive theme regions are unavailable. Update Streamlit to the supported version or select a theme from the list below.",
        "theme_basic_title": "Basic title-clue map: only explicit title words match; metaphors are not understood. Other tracks remain To review. Install and enable the local text model for semantic analysis.",
        "theme_score_note": "This is text-embedding similarity, not theme accuracy.",
        "theme_score": "Theme-text similarity",
        "zodiac_seed": "Star cluster seed", "zodiac_seed_note": "At least 12 distinct audio files are needed to pick among twelve playful silhouettes.",
        "zodiac_heading": "Sound constellation", "zodiac_overlay": "Show constellation outline", "zodiac_auto": "Automatic match",
        "zodiac_choice": "Zodiac silhouette", "zodiac_element": "Corresponding element", "zodiac_override": "Chosen manually",
        "zodiac_explain": "Symbolic silhouettes are for playful exploration, not astronomy or personality assessment. The element follows only from the chosen sign.",
        "zodiac_representatives": "Representative map tracks", "zodiac_include_titles": "Include representative track titles on share card",
        "zodiac_download": "Download local constellation card", "zodiac_card_error": "Could not create the share card. Check local image dependencies.",
        "genre_intro": "Verified genres form category islands. Raw file genre does not count as a verified classification. Positions within an island only prevent overlap.",
        "genre_coverage": "Verified genres", "genre_insufficient": "Too few reliable genre categories for a meaningful genre map. Verify genres track by track in the details panel. Raw file genre remains visible but is not automatically treated as fact.",
        "genre_review": "Verify genre manually", "genre_review_help": "Listen and check a reliable source before entering a professional genre. Raw file genre is a hint, not automatic verification.",
        "genre_review_input": "Verified professional genre", "genre_review_save": "Save verified genre", "genre_review_clear": "Remove genre verification",
        "genre_review_error": "Could not save genre verification. Check the name and write access to analysis records.",
        "genre_categories": "Reliable genre categories", "category_help": "An island means one category; distance between islands does not measure genre or language similarity.",
        "category": "Category",
        "language_intro": "Group songs by vocal language detected from lyrics. Missing lyrics, mixed languages, and instrumental tracks remain separate; titles are not used to guess.",
        "language_insufficient": "No reliable lyric-language result is available. Import lyrics and configure a local language-ID model first.",
        "language_coverage": "Identified languages", "language_zh": "Chinese", "language_en": "English", "language_de": "German",
        "language_ja": "Japanese", "language_ko": "Korean", "language_fr": "French", "language_es": "Spanish",
        "language_mixed": "Multiple languages", "language_unknown": "Unknown", "language_instrumental": "Confirmed instrumental",
        "language_status": "Vocal language", "language_uncertain": "Vocal language has not been reliably identified; a title is not enough.",
        "language_runtime_unavailable": "Local language identification is unavailable. Check the model file and optional fasttext dependency, then rescan lyrics.",
        "assistant_title": "Optional theme explanation", "assistant_purpose": "Only after you confirm each track, send the title and lyric excerpt shown below to DeepSeek for a reviewable theme suggestion. Local maps do not depend on it.",
        "assistant_preview": "Text to be sent", "assistant_consent": "I agree to send only this track's displayed title and lyric excerpt to DeepSeek",
        "assistant_run": "Explain this track's themes", "assistant_key_missing": "No fresh DEEPSEEK_API_KEY is set locally. Rotate the previously exposed key and configure the replacement as a local environment variable, not in code or chat.",
        "assistant_unavailable": "No usable local lyrics are available for this track, so a grounded theme explanation cannot be generated.",
        "assistant_error": "The theme request failed. Check connectivity, key permission, or service status; local maps still work.",
        "assistant_result": "Suggested themes", "assistant_model": "Model", "assistant_destination": "Destination",
    },
}


def _track_name(track: TrackEncoding) -> str:
    return f"{track.metadata.title} — {track.metadata.artist or '—'}"


def _ensure_draft(plan: CollectionPlan, artifacts: Path, labels: dict[str, str]) -> PlaylistDraft:
    identity = (str(artifacts.resolve()), plan.source_root)
    if st.session_state.get("playlist_draft_identity") != identity:
        try:
            draft = load_draft(artifacts, plan)
            st.session_state.playlist_draft_writable = True
        except (OSError, ValueError, TypeError):
            LOGGER.exception("Could not load playlist draft")
            draft = PlaylistDraft(plan.source_root, plan.analysis_id)
            st.session_state.playlist_draft_writable = False
        st.session_state.playlist_draft = draft
        st.session_state.playlist_draft_identity = identity
        st.session_state.explore_exclusion_signature = None
    draft = st.session_state.playlist_draft
    ids, missing = reconcile(draft, plan)
    st.session_state.explore_candidate_ids = ids
    if missing:
        st.warning(labels["missing_draft"].format(count=len(missing)))
    if not st.session_state.get("playlist_draft_writable", True):
        st.error(labels["draft_error"])
    return draft


def _save_draft(artifacts: Path, draft: PlaylistDraft, labels: dict[str, str]) -> None:
    if not st.session_state.get("playlist_draft_writable", True):
        st.error(labels["draft_error"])
        return
    try:
        save_draft(artifacts, draft)
    except OSError:
        LOGGER.exception("Could not save playlist draft")
        st.error(labels["draft_error"])


def _stage_candidates(ids: list[str], kind: str, *, scores: dict[str, float] | None = None,
                      seed_id: str | None = None, filters: dict | None = None) -> None:
    st.session_state.explore_pending_ids = list(dict.fromkeys(ids))
    st.session_state.explore_pending_kind = kind
    st.session_state.explore_pending_scores = scores or {}
    st.session_state.explore_pending_seed_id = seed_id
    st.session_state.explore_pending_filters = filters or {}


def _pending_actions(plan: CollectionPlan, artifacts: Path, labels: dict[str, str]) -> None:
    ids = [item for item in st.session_state.get("explore_pending_ids", []) if item in plan.track_by_id()]
    if not ids:
        return
    st.subheader(f"{labels['pending']} · {len(ids)}")
    draft: PlaylistDraft = st.session_state.playlist_draft
    st.caption(f"{labels['current_draft']}: {len(reconcile(draft, plan)[0])}")
    cols = st.columns(3)
    for column, mode, label in zip(cols, ("add", "intersect", "replace"),
                                   ("add_candidates", "intersect_candidates", "replace_candidates")):
        if column.button(labels[label], key=f"explore_pending_{mode}"):
            apply_selection(draft, plan, ids, mode, st.session_state.get("explore_pending_kind", "map"))
            draft.filters = st.session_state.get("explore_pending_filters", {})
            st.session_state.explore_candidate_scores = st.session_state.get("explore_pending_scores", {})
            st.session_state.explore_candidate_kind = st.session_state.get("explore_pending_kind", "map")
            st.session_state.explore_seed_id = st.session_state.get("explore_pending_seed_id")
            st.session_state.explore_pending_ids = []
            _save_draft(artifacts, draft, labels)
            st.rerun()


@st.cache_data(show_spinner=False)
def _cover_for(path: str, modified_ns: int) -> str | None:
    return read_cover_data_uri(Path(path))


def _model_state(plan: CollectionPlan, artifacts: Path, labels: dict[str, str]) -> SonicMap:
    signature = (plan.analysis_id, str(artifacts.resolve()))
    if st.session_state.get("explore_map_signature") != signature:
        # A fast, clearly named preview appears before the optional model pass.
        st.session_state.explore_sonic_map = build_sonic_map(
            plan.tracks, artifacts, model_path=artifacts / "model-not-selected.onnx",
        )
        st.session_state.explore_map_signature = signature
        st.session_state.explore_candidate_scores = {}
        st.session_state.explore_map_ids = []
        st.session_state.explore_lyrics_selected_sources = {}
        st.session_state.explore_lyrics_result = None
        st.session_state.explore_language_result = None
    if DEFAULT_MODEL_PATH.is_file():
        if st.button(labels["build_model"], key="explore_build_model"):
            progress_bar = st.progress(0.0)

            def update(done: int, total: int, name: str) -> None:
                progress_bar.progress(done / max(total, 1), text=f"{labels['model_progress']} {done}/{total}: {name}")

            st.session_state.explore_sonic_map = build_sonic_map(
                plan.tracks, artifacts, model_path=DEFAULT_MODEL_PATH, progress=update,
            )
            progress_bar.progress(1.0)
    else:
        st.info(labels["model_missing"])
    return st.session_state.explore_sonic_map


def _sonic_rows(plan: CollectionPlan, sound: SonicMap, labels: dict[str, str], language: str) -> list[dict]:
    by_id = plan.track_by_id()
    rows: list[dict] = []
    for point in sound.points:
        track = by_id.get(point.track_id)
        if track is None:
            continue
        rows.append({
            "track_id": point.track_id, "x": point.x, "y": point.y,
            "name": _track_name(track), "genre": track.metadata.genre or labels["unprovided"],
            "instrument": VALUE_LABELS[language].get(track.instrument, labels["unknown"]),
            "act": round(track.standard.agitation, 1) if track.standard else None,
            "bri": round(track.standard.brightness, 1) if track.standard else None,
            "tempo_bpm": round(track.acoustic.tempo_bpm, 1),
        })
    return rows


def _zodiac_controls(plan: CollectionPlan, sound: SonicMap, language: str,
                     labels: dict[str, str]) -> tuple[object, bool]:
    """Prepare a decorative interpretation without altering SonicMap positions."""
    choices = ["auto", *ZODIAC_LABELS[language]]
    selected = st.selectbox(
        labels["zodiac_choice"], choices,
        format_func=lambda sign: labels["zodiac_auto"] if sign == "auto" else ZODIAC_LABELS[language][sign],
        key="explore_zodiac_choice",
    )
    zodiac = build_zodiac(sound, plan.tracks, override_sign=None if selected == "auto" else selected)
    show = st.checkbox(labels["zodiac_overlay"], value=True, key="explore_zodiac_overlay")
    return zodiac, show


def _zodiac_summary(plan: CollectionPlan, sound: SonicMap, zodiac: object,
                    language: str, labels: dict[str, str]) -> None:
    st.subheader(labels["zodiac_heading"])
    if zodiac.status != "matched":
        st.write(labels["zodiac_seed"])
        st.caption(f"{zodiac.unique_track_count}/12 · {labels['zodiac_seed_note']}")
        return
    sign_name = ZODIAC_LABELS[language][zodiac.sign]
    element_name = ELEMENT_LABELS[language][zodiac.element]
    st.write(f"{sign_name} · {labels['zodiac_element']}: {element_name}")
    if zodiac.is_override:
        st.caption(labels["zodiac_override"])
    st.caption(zodiac.rationale_zh if language == "zh" else zodiac.rationale_en)
    st.caption(labels["zodiac_explain"])
    by_id = plan.track_by_id()
    names = [_track_name(by_id[track_id]) for track_id in zodiac.representative_track_ids if track_id in by_id]
    if names:
        st.write(f"{labels['zodiac_representatives']}: " + " · ".join(names[:3]))
    include_titles = st.checkbox(labels["zodiac_include_titles"], key="explore_zodiac_titles")
    card_signature = (
        plan.analysis_id, zodiac.point_fingerprint,
        zodiac.sign, zodiac.is_override, language, include_titles, date.today().isoformat(),
    )
    try:
        cached = st.session_state.get("explore_zodiac_card_cache")
        if cached and cached[0] == card_signature:
            card = cached[1]
        else:
            card = make_zodiac_share_card(
                zodiac, sound, plan.tracks, language=language, include_track_titles=include_titles,
            )
            st.session_state.explore_zodiac_card_cache = (card_signature, card)
    except Exception:
        LOGGER.exception("Could not render zodiac share card")
        st.warning(labels["zodiac_card_error"])
        return
    st.download_button(
        labels["zodiac_download"], card,
        file_name=f"musefolders-{zodiac.sign}-{language}.png", mime="image/png",
        key="explore_zodiac_card",
    )


def _draw_map(rows: list[dict], *, color: str, focus_id: str | None, chart_key: str,
              labels: dict[str, str], dragmode: str = "pan", sonic_axes: bool = False,
              category_centers: dict[str, tuple[float, float, int]] | None = None,
              zodiac: object | None = None) -> list[str]:
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    hover_fields = {"x": False, "y": False}
    for column in ("genre", "instrument", "tempo_bpm", "act", "bri", "theme", "category"):
        if column in frame.columns:
            hover_fields[column] = True
    continuous_act = sonic_axes and color == "act"
    figure = px.scatter(
        frame, x="x", y="y", color=color, hover_name="name",
        hover_data=hover_fields,
        labels={"genre": labels["genre"], "instrument": labels["instrument"],
                "tempo_bpm": labels["exact_tempo"], "act": labels["exact_act"],
                "bri": labels["exact_bri"], "theme": labels["lyrics_theme"],
                "category": labels["category"]},
        color_continuous_scale=[(0.0, "#315FA8"), (0.5, "#C5D2DF"), (1.0, "#ED8547")] if continuous_act else None,
        range_color=(0.0, 100.0) if continuous_act else None,
        custom_data=["track_id"], render_mode="webgl" if len(rows) > 500 else "svg",
    )
    figure.update_traces(marker={"size": 11, "opacity": 0.84})
    # Plotly shapes do not join the selectable song traces. Fixed ranges keep
    # toggling a decorative outline from visually shifting any actual song.
    if sonic_axes and zodiac is not None and getattr(zodiac, "status", "") == "matched":
        nodes = zodiac.overlay_nodes
        for start, end in zodiac.overlay_edges:
            if 0 <= start < len(nodes) and 0 <= end < len(nodes):
                figure.add_shape(
                    type="line", x0=nodes[start][0], y0=nodes[start][1],
                    x1=nodes[end][0], y1=nodes[end][1],
                    line={"color": "rgba(108, 114, 165, 0.28)", "width": 3},
                    layer="below",
                )
        for x, y in nodes:
            figure.add_shape(
                type="circle", x0=x - 0.65, x1=x + 0.65,
                y0=y - 0.65, y1=y + 0.65,
                line={"color": "rgba(108, 114, 165, 0.42)", "width": 1},
                fillcolor="rgba(108, 114, 165, 0.18)", layer="below",
            )
    if continuous_act:
        figure.update_coloraxes(colorbar={"title": labels["act_colorbar"], "tickvals": [0, 25, 50, 75, 100]})
    if category_centers:
        for category, (x, y, count) in category_centers.items():
            figure.add_annotation(x=x, y=y + 0.9, text=f"{category} ({count})",
                                  showarrow=False, font={"size": 14})
    if focus_id and focus_id in set(frame["track_id"]):
        point = frame.loc[frame["track_id"] == focus_id].iloc[0]
        figure.add_trace(go.Scatter(
            x=[point["x"]], y=[point["y"]], mode="markers",
            marker={"size": 20, "color": "rgba(0,0,0,0)", "line": {"color": "#e4574f", "width": 3}},
            customdata=[[focus_id]], name=labels["detail"], showlegend=False,
        ))
    level = int(st.session_state.get(f"{chart_key}_zoom", 0))
    level = max(0, min(3, level))
    if sonic_axes:
        base_x, base_y = (0.0, 100.0), (0.0, 100.0)
    else:
        xs, ys = [float(row["x"]) for row in rows], [float(row["y"]) for row in rows]
        base_x = (min(xs) - 2.0, max(xs) + 2.0)
        base_y = (min(ys) - 2.0, max(ys) + 2.0)
    center = st.session_state.get(f"{chart_key}_center")
    if not isinstance(center, (tuple, list)) or len(center) != 2:
        center = ((base_x[0] + base_x[1]) / 2, (base_y[0] + base_y[1]) / 2)
    scale = 2 ** level
    half_x = (base_x[1] - base_x[0]) / (2 * scale)
    half_y = (base_y[1] - base_y[0]) / (2 * scale)
    center_x = max(base_x[0] + half_x, min(base_x[1] - half_x, float(center[0])))
    center_y = max(base_y[0] + half_y, min(base_y[1] - half_y, float(center[1])))
    view_x = [center_x - half_x, center_x + half_x]
    view_y = [center_y - half_y, center_y + half_y]
    xaxis = {"visible": False, "range": view_x, "fixedrange": False}
    yaxis = {"visible": False, "range": view_y, "fixedrange": False}
    if sonic_axes:
        xaxis = {"visible": True, "title": labels["tempo_axis"], "showticklabels": False,
                 "showgrid": True, "zeroline": False, "range": view_x, "fixedrange": False}
        yaxis = {"visible": True, "title": labels["bri_axis"], "showticklabels": False,
                 "showgrid": True, "zeroline": False, "range": view_y,
                 "scaleanchor": "x", "scaleratio": 1, "fixedrange": False}
    figure.update_layout(
        height=600, dragmode=dragmode, clickmode="event+select", hovermode="closest",
        margin={"l": 35 if sonic_axes else 10, "r": 10, "t": 15, "b": 45 if sonic_axes else 10},
        xaxis=xaxis, yaxis=yaxis, legend={"title": {"text": ""}},
        uirevision=f"{chart_key}:{st.session_state.get(f'{chart_key}_view_revision', 0)}",
    )
    widget_key = f"{chart_key}_{st.session_state.get(f'{chart_key}_nonce', 0)}"
    event = st.plotly_chart(
        figure, key=widget_key, on_select="rerun", selection_mode=("points", "box", "lasso"),
        width="stretch", config={"displaylogo": False, "displayModeBar": True,
                                 "scrollZoom": False, "modeBarButtonsToRemove": ["toImage"]},
    )
    ids: list[str] = []
    for selected_point in event.selection.points:
        data = selected_point.get("customdata")
        if data and data[0] in set(frame["track_id"]):
            ids.append(str(data[0]))
    return list(dict.fromkeys(ids))


def _zoom_controls(rows: list[dict], chart_key: str, labels: dict[str, str],
                   focus_id: str | None) -> None:
    """Explicit zoom survives Python reruns; native Plotly pan/zoom remains available."""
    if not rows:
        return
    level = max(0, min(3, int(st.session_state.get(f"{chart_key}_zoom", 0))))
    minus, value, plus, reset = st.columns([1, 1, 1, 1])
    changed = None
    if minus.button(labels["zoom_out"], disabled=level == 0, key=f"{chart_key}_out"):
        changed = level - 1
    if plus.button(labels["zoom_in"], disabled=level == 3, key=f"{chart_key}_in"):
        changed = level + 1
    if reset.button(labels["zoom_reset"], key=f"{chart_key}_reset"):
        changed = 0
        st.session_state.pop(f"{chart_key}_center", None)
    if changed is not None:
        if changed > 0 and level == 0 and focus_id:
            focused = next((row for row in rows if row["track_id"] == focus_id), None)
            if focused:
                st.session_state[f"{chart_key}_center"] = (focused["x"], focused["y"])
        st.session_state[f"{chart_key}_zoom"] = changed
        st.session_state[f"{chart_key}_view_revision"] = st.session_state.get(f"{chart_key}_view_revision", 0) + 1
    value.caption(labels["zoom_note"].format(scale=2 ** (changed if changed is not None else level)))


def overlap_groups(rows: list[dict], *, width: int = 450, height: int = 520,
                   x_range: tuple[float, float] | None = None,
                   y_range: tuple[float, float] | None = None,
                   threshold: float = 12.0) -> list[list[str]]:
    """Bounded screen-space groups; no transitive chaining of distant songs."""
    if not rows:
        return []
    xs, ys = [float(row["x"]) for row in rows], [float(row["y"]) for row in rows]
    x0, x1 = x_range or (min(xs) - .01, max(xs) + .01)
    y0, y1 = y_range or (min(ys) - .01, max(ys) + .01)
    anchors: list[tuple[float, float, list[str]]] = []
    for row in sorted(rows, key=lambda item: str(item["track_id"])):
        px = (float(row["x"]) - x0) / max(x1 - x0, 1e-9) * width
        py = (float(row["y"]) - y0) / max(y1 - y0, 1e-9) * height
        for ax, ay, group in anchors:
            if math.hypot(px - ax, py - ay) <= threshold:
                group.append(str(row["track_id"]))
                break
        else:
            anchors.append((px, py, [str(row["track_id"])]))
    return [group for _, _, group in anchors if len(group) > 1]


def _overlap_picker(rows: list[dict], chart_key: str, plan: CollectionPlan,
                    labels: dict[str, str], *, sonic_axes: bool = False) -> None:
    if sonic_axes:
        groups = overlap_groups(rows, x_range=(0.0, 100.0), y_range=(0.0, 100.0))
    else:
        groups = overlap_groups(rows)
    if not groups:
        return
    by_id = plan.track_by_id()
    with st.expander(f"{labels['overlap']} · {sum(map(len, groups))}"):
        group_index = st.selectbox(labels["overlap_group"], range(len(groups)),
                                   format_func=lambda index: f"{index + 1} · {len(groups[index])}",
                                   key=f"{chart_key}_overlap_group")
        chosen = st.selectbox(labels["song_search"], groups[group_index],
                              format_func=lambda track_id: _track_name(by_id[track_id]),
                              key=f"{chart_key}_overlap_song")
        if st.button(labels["overlap_view"], key=f"{chart_key}_overlap_view"):
            st.session_state.explore_focus_id = chosen
            st.session_state.explore_track_search = chosen
            st.rerun()


def _sync_chart_selection(ids: list[str], chart_key: str) -> None:
    """Only the chart whose selection changed may update shared focus and tray."""
    remembered_key = f"{chart_key}_selected_ids"
    selection = tuple(ids)
    if selection == tuple(st.session_state.get(remembered_key, ())):
        return
    st.session_state[remembered_key] = selection
    st.session_state.explore_map_ids = ids
    if ids:
        st.session_state.explore_focus_id = ids[-1]
        st.session_state.explore_track_search = ids[-1]


def _category_rows(plan: CollectionPlan, assignments: dict[str, str],
                   valid_ids: set[str]) -> tuple[list[dict], dict[str, tuple[float, float, int]]]:
    """Stable categorical islands; inter-island distance has no semantic meaning."""
    by_id = plan.track_by_id()
    groups: dict[str, list[str]] = {}
    for track_id, category in assignments.items():
        if track_id in by_id and track_id in valid_ids:
            groups.setdefault(category, []).append(track_id)
    names = sorted(groups, key=str.casefold)
    centers: dict[str, tuple[float, float, int]] = {}
    rows: list[dict] = []
    for group_index, category in enumerate(names):
        angle = 2 * math.pi * group_index / max(1, len(names))
        center_x = 4.5 * math.cos(angle) if len(names) > 1 else 0.0
        center_y = 4.5 * math.sin(angle) if len(names) > 1 else 0.0
        members = sorted(groups[category])
        centers[category] = (center_x, center_y, len(members))
        for index, track_id in enumerate(members):
            digest = hashlib.sha256(track_id.encode("utf-8")).digest()
            phase = int.from_bytes(digest[:4], "big") / 2**32 * 2 * math.pi
            spread = min(1.25, 0.17 * math.sqrt(index))
            direction = phase + index * 2.399963229728653
            track = by_id[track_id]
            rows.append({
                "track_id": track_id,
                "x": center_x + spread * math.cos(direction),
                "y": center_y + spread * math.sin(direction),
                "name": _track_name(track), "category": category,
                "genre": track.metadata.genre or "—",
                "tempo_bpm": round(track.acoustic.tempo_bpm, 1),
                "act": round(track.standard.agitation, 1) if track.standard else None,
                "bri": round(track.standard.brightness, 1) if track.standard else None,
            })
    return rows, centers


def _theme_island_map(atlas: object, selected_id: str | None,
                      labels: dict[str, str]) -> str | None:
    """Render true whole-region SVG hit targets; never interpolate title HTML."""
    regions = [
        {
            "id": region.theme_id,
            "label": labels[f"theme_{region.theme_id}"],
            "count": region.count,
            "center": list(region.center),
            "outline": [list(point) for point in region.outline],
            "fill": _THEME_COLORS[region.theme_id],
        }
        for region in atlas.regions.values()
    ]
    try:
        component_state = getattr(st, "session_state", {}).get("explore_theme_islands", {})
        viewport = component_state.get("viewport", [0, 0, 1000, 680]) if isinstance(component_state, dict) else [0, 0, 1000, 680]
        # Register in the active Streamlit runtime. AppTest creates a fresh
        # component registry for each run; import-time registration is lost.
        component = st.components.v2.component(
            "musefolders_theme_islands", html='<div data-theme-atlas></div>',
            css=_THEME_ISLAND_CSS, js=_THEME_ISLAND_JS,
        )
        clicked = component(
            data={"regions": regions, "selected": selected_id,
                  "map_label": labels["theme_map_label"], "song_unit": labels["theme_song_unit"],
                  "zoom_in": labels["zoom_in"], "zoom_out": labels["zoom_out"],
                  "zoom_reset": labels["zoom_reset"], "viewport": viewport},
            default={"viewport": [0, 0, 1000, 680]},
            key="explore_theme_islands", on_clicked_change=lambda: None,
            on_viewport_change=lambda: None,
        ).clicked
        return clicked if clicked in atlas.regions else None
    except Exception:
        LOGGER.exception("Theme island component failed")
        st.warning(labels["theme_component_error"])
        fallback = st.selectbox(
            labels["theme_region"], list(atlas.regions),
            index=list(atlas.regions).index(selected_id) if selected_id in atlas.regions else 0,
            format_func=lambda value: labels[f"theme_{value}"],
            key="explore_theme_fallback",
        )
        return fallback if fallback != selected_id else None


def _theme_region_detail(plan: CollectionPlan, atlas: object, result: object,
                         artifacts: Path, selected_id: str,
                         labels: dict[str, str], language: str) -> None:
    """Review a semantic island before routing selected tracks to the tray."""
    by_id = plan.track_by_id()
    region = atlas.regions[selected_id]
    members = [track_id for track_id in region.track_ids if track_id in by_id]
    st.subheader(f"{labels['theme_region']}: {labels[f'theme_{selected_id}']} ({len(members)})")
    if not members:
        st.info(labels["theme_empty_region"])
        return
    st.dataframe(pd.DataFrame([
        {labels["title"]: by_id[track_id].metadata.title,
         labels["artist"]: by_id[track_id].metadata.artist or labels["unprovided"],
         labels["theme_evidence"]: labels.get(
             f"theme_evidence_{result.evidence_sources.get(track_id, 'unknown')}",
             labels["theme_evidence_unknown"],
         )}
        for track_id in members
    ]), hide_index=True, width="stretch")
    chosen = st.multiselect(
        labels["theme_region_tracks"], members, default=members,
        format_func=lambda track_id: _track_name(by_id[track_id]),
        key=f"explore_theme_region_members_{plan.analysis_id}_{selected_id}",
    )
    st.caption(labels["theme_region_note"])
    if st.button(labels["theme_add"], disabled=not chosen,
                 key=f"explore_add_theme_region_{selected_id}"):
        unique_ids: list[str] = []
        seen_content: set[str] = set()
        for track_id in chosen:
            content = by_id[track_id].source_sha256 or track_id
            if content not in seen_content:
                unique_ids.append(track_id)
                seen_content.add(content)
        _stage_candidates(unique_ids, "theme_region")
    preview_id = st.selectbox(
        labels["theme_play"], members,
        format_func=lambda track_id: _track_name(by_id[track_id]),
        key=f"explore_theme_preview_{plan.analysis_id}_{selected_id}",
    )
    remembered_key = f"explore_theme_preview_remembered_{plan.analysis_id}_{selected_id}"
    remembered = st.session_state.get(remembered_key)
    if remembered is not None and remembered != preview_id:
        st.session_state.explore_focus_id = preview_id
        st.session_state.explore_track_search = preview_id
    st.session_state[remembered_key] = preview_id
    st.audio(by_id[preview_id].source_path)
    st.caption(f"{labels['theme_evidence']}: " + labels.get(
        f"theme_evidence_{result.evidence_sources.get(preview_id, 'unknown')}",
        labels["theme_evidence_unknown"],
    ))
    st.caption(labels["theme_manual_note"])
    theme_ids = list(_THEME_COLORS)
    current_theme = result.primary_themes.get(preview_id, "unknown")
    edit_nonce = f"explore_theme_edit_nonce_{preview_id}"
    corrected = st.selectbox(
        labels["theme_edit"], theme_ids,
        index=theme_ids.index(current_theme) if current_theme in theme_ids else theme_ids.index("unknown"),
        format_func=lambda value: labels[f"theme_{value}"],
        key=f"explore_theme_edit_{plan.analysis_id}_{preview_id}_{st.session_state.get(edit_nonce, 0)}",
    )
    correction = result.evidence_sources.get(preview_id) == "manual"
    if st.button(labels["theme_save"], disabled=corrected == current_theme,
                 key=f"explore_theme_save_{preview_id}"):
        try:
            set_theme_assignment(by_id[preview_id], artifacts, corrected)
            st.session_state[edit_nonce] = st.session_state.get(edit_nonce, 0) + 1
            st.session_state.explore_lyrics_signature = None
            st.rerun()
        except (OSError, ValueError):
            LOGGER.exception("Could not save theme correction")
            st.error(labels["theme_save_error"])
    if correction and st.button(labels["theme_reset"], key=f"explore_theme_reset_{preview_id}"):
        try:
            set_theme_assignment(by_id[preview_id], artifacts, None)
            st.session_state[edit_nonce] = st.session_state.get(edit_nonce, 0) + 1
            st.session_state.explore_lyrics_signature = None
            st.rerun()
        except (OSError, ValueError):
            LOGGER.exception("Could not remove theme correction")
            st.error(labels["theme_save_error"])
    st.caption(labels["theme_similar_note"])
    if st.button(labels["theme_find_similar"], key=f"explore_theme_similar_{preview_id}"):
        ranked = rank_theme_neighbors(result, preview_id, limit=len(plan.tracks))
        if not ranked:
            st.info(labels["theme_no_embedding"])
        else:
            accepted: list[str] = []
            seen = {by_id[preview_id].source_sha256 or preview_id}
            scores: dict[str, float] = {}
            for track_id, score in ranked:
                track = by_id.get(track_id)
                if track is None:
                    continue
                content = track.source_sha256 or track_id
                if content in seen:
                    continue
                seen.add(content)
                accepted.append(track_id)
                scores[track_id] = float(score)
                if len(accepted) >= 12:
                    break
            _stage_candidates(accepted, "theme_similar", scores=scores, seed_id=preview_id)


def _shared_features(seed: TrackEncoding, candidate: TrackEncoding, labels: dict[str, str]) -> str:
    shared: list[str] = []
    if seed.metadata.genre and seed.metadata.genre == candidate.metadata.genre:
        shared.append(f"{labels['genre']}: {seed.metadata.genre}")
    if (seed.instrument == candidate.instrument and seed.instrument != "unknown"
            and seed.instrument_status in {"manual", "model_estimate"}
            and candidate.instrument_status in {"manual", "model_estimate"}):
        shared.append(labels["instrument"])
    if abs(seed.acoustic.tempo_bpm - candidate.acoustic.tempo_bpm) <= 12:
        shared.append(labels["tempo"])
    if seed.standard and candidate.standard and abs(seed.standard.agitation - candidate.standard.agitation) <= 12:
        shared.append(labels["act"])
    return ", ".join(shared) if shared else labels["no_common"]


def _filters(plan: CollectionPlan, labels: dict[str, str], language: str,
             verified: frozenset[str]) -> ExplorationConstraints:
    filter_keys = ("explore_genres", "explore_instruments", "explore_act",
                   "explore_bri", "explore_no_vocals")
    restore = st.session_state.pop("explore_filter_restore", None)
    if restore and restore[0] in filter_keys:
        st.session_state[restore[0]] = restore[1]
        st.session_state.explore_last_filter_change = None
    current = {key: st.session_state.get(key) for key in filter_keys}
    previous = st.session_state.get("explore_filter_snapshot")
    if previous and not restore:
        changed = [key for key in filter_keys if current[key] != previous.get(key)]
        if changed:
            st.session_state.explore_last_filter_change = (changed[-1], previous.get(changed[-1]))
    with st.expander(labels["hard_filters"]):
        genres = sorted({track.metadata.genre for track in plan.tracks if track.metadata.genre})
        instruments = sorted({track.instrument for track in plan.tracks if track.instrument != "unknown"})
        chosen_genres = st.multiselect(labels["genre_filter"], genres, key="explore_genres")
        chosen_instruments = st.multiselect(labels["instrument_filter"], instruments,
                                            format_func=lambda value: VALUE_LABELS[language].get(value, value),
                                            key="explore_instruments")
        act = st.slider(labels["act_filter"], 0.0, 10.0, (0.0, 10.0), 0.1, key="explore_act")
        bri = st.slider(labels["bri_filter"], 0.0, 10.0, (0.0, 10.0), 0.1, key="explore_bri")
        no_vocals = st.toggle(labels["no_vocals"], key="explore_no_vocals")
        if no_vocals and not verified:
            st.warning(labels["no_vocals_warning"])
        last_change = st.session_state.get("explore_last_filter_change")
        if last_change and st.button(labels["undo_filter"], key="explore_undo_filter"):
            st.session_state.explore_filter_restore = last_change
            st.rerun()
    st.session_state.explore_filter_snapshot = {key: st.session_state.get(key) for key in filter_keys}
    return ExplorationConstraints(
        filters=PlaylistFilters(
            genres=frozenset(chosen_genres), instruments=frozenset(chosen_instruments),
            act_range=(act[0] * 10, act[1] * 10), bri_range=(bri[0] * 10, bri[1] * 10),
        ),
        require_instrumental=no_vocals,
        verified_instrumental_ids=verified,
    )


def _natural_language_filters(plan: CollectionPlan, labels: dict[str, str],
                              language: str) -> None:
    """Cloud text is an editable proposal, never an action or a classifier."""
    with st.expander(labels["filter_assistant"]):
        prompt = st.text_area(labels["filter_prompt"], max_chars=500, key="explore_filter_prompt")
        key_available = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
        if not key_available:
            st.info(labels["filter_key_missing"])
        consent = st.checkbox(labels["filter_consent"], key="explore_filter_consent")
        if st.button(labels["filter_run"], disabled=not key_available or not consent or not prompt.strip(),
                     key="explore_filter_run"):
            try:
                proposal = suggest_filters(prompt, plan.tracks,
                                           api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                                           consent=True, language=language)
                st.session_state.explore_filter_proposal = proposal
                st.session_state.explore_filter_nonce = st.session_state.get("explore_filter_nonce", 0) + 1
            except FilterAssistantError:
                LOGGER.warning("Optional filter assistant failed")
                st.error(labels["filter_error"])
        proposal = st.session_state.get("explore_filter_proposal")
        if proposal is None:
            return
        nonce = st.session_state.get("explore_filter_nonce", 0)
        if proposal.explanation:
            st.caption(f"{labels['filter_explanation']}: {proposal.explanation}")
        if proposal.unsupported:
            st.warning(f"{labels['filter_unsupported']}: {', '.join(proposal.unsupported)}")
        source = proposal.filters
        title = st.text_input(labels["filter_title"], value=source.title_query,
                              key=f"filter_title_{nonce}")
        label_keys = {"artists": "artist", "albums": "album", "genres": "genre",
                      "years": "filter_year", "instruments": "instrument", "keys": "filter_key",
                      "loudness": "loudness", "tempo": "tempo"}
        selections = {}
        for field, label_key in label_keys.items():
            options = facet_options(plan.tracks, field)
            selections[field] = frozenset(st.multiselect(
                labels[label_key], options, default=sorted(getattr(source, field)),
                format_func=(lambda value: VALUE_LABELS[language].get(value, value))
                if field in {"instruments", "loudness", "tempo"} else None,
                key=f"filter_{field}_{nonce}",
            ))
        act = st.slider(labels["act_filter"], 0.0, 10.0,
                        (source.act_range[0] / 10, source.act_range[1] / 10), 0.1,
                        key=f"filter_act_{nonce}")
        bri = st.slider(labels["bri_filter"], 0.0, 10.0,
                        (source.bri_range[0] / 10, source.bri_range[1] / 10), 0.1,
                        key=f"filter_bri_{nonce}")
        filters = PlaylistFilters(title_query=title, act_range=(act[0] * 10, act[1] * 10),
                                  bri_range=(bri[0] * 10, bri[1] * 10), **selections)
        found = filter_tracks(plan.tracks, filters)
        st.metric(labels["filter_matched"], len(found))
        if not found:
            st.warning(labels["filter_zero"])
            suggestions = relaxation_counts(plan.tracks, filters)
            if suggestions:
                field, count = max(suggestions.items(), key=lambda item: item[1])
                st.caption(f"{labels.get(label_keys.get(field, field), field)} → {count}")
        if st.button(labels["filter_stage"], disabled=not found, key="explore_filter_stage"):
            _stage_candidates([track.track_id for track in found], "natural_language",
                              filters=filters.to_dict())
        if st.button(labels["filter_clear"], key="explore_filter_clear"):
            st.session_state.explore_filter_proposal = None
            st.rerun()


def _accept_result(result: ExplorationResult, kind: str, seed_id: str | None,
                   labels: dict[str, str], filters: dict | None = None) -> None:
    _stage_candidates(list(result.track_ids), kind, scores=result.scores,
                      seed_id=seed_id, filters=filters)
    if result.reason_code == "shortfall":
        st.warning(labels["status_shortfall"])
    elif result.reason_code != "ok":
        st.warning(labels.get(f"status_{result.reason_code}", labels["status_other"]))


def _candidate_actions(plan: CollectionPlan, sound: SonicMap, focus_id: str,
                       map_ids: list[str], constraints: ExplorationConstraints,
                       labels: dict[str, str]) -> None:
    by_id = plan.track_by_id()
    options = [track.track_id for track in plan.tracks if track.track_id in sound.vectors]
    sound_focus_id = focus_id if focus_id in options else options[0]
    tabs = st.tabs([labels["similar"], labels["path"], labels["alchemy"]])
    with tabs[0]:
        st.caption(labels["similar_help"])
        if focus_id not in options:
            st.info(labels["status_anchor_missing_embedding"])
        count = (st.slider(labels["requested"], 1, min(40, len(options) - 1),
                           min(12, len(options) - 1), key="explore_similar_count")
                 if len(options) > 2 else 1)
        if st.button(labels["find_similar"], type="primary", key="explore_similar_button",
                     disabled=focus_id not in options):
            _accept_result(similar_tracks(plan.tracks, sound.vectors, focus_id, limit=count, constraints=constraints),
                           "similar", focus_id, labels, constraints.filters.to_dict())
        st.metric(labels["selected_count"], len(map_ids))
        if st.button(labels["use_region"], disabled=not map_ids, key="explore_use_region"):
            hashes: set[str] = set()
            accepted: list[str] = []
            for track_id in map_ids:
                track = by_id[track_id]
                if (not matches(track, constraints.filters)
                        or (constraints.require_instrumental and track_id not in constraints.verified_instrumental_ids)
                        or track_id in constraints.excluded_track_ids):
                    continue
                content_key = track.source_sha256 or track.track_id
                if content_key not in hashes:
                    accepted.append(track_id)
                    hashes.add(content_key)
            _stage_candidates(accepted, "region", filters=constraints.filters.to_dict())
            if not accepted:
                st.warning(labels["status_no_candidates"])
    with tabs[1]:
        st.caption(labels["path_help"])
        start = st.selectbox(labels["path_start"], options, index=options.index(sound_focus_id),
                             format_func=lambda value: _track_name(by_id[value]), key="explore_path_start")
        end = st.selectbox(labels["path_end"], options, index=min(1, len(options) - 1),
                           format_func=lambda value: _track_name(by_id[value]), key="explore_path_end")
        length = st.slider(labels["path_length"], 3, 20, 8, key="explore_path_length")
        if st.button(labels["make_path"], key="explore_path_button"):
            _accept_result(song_path(plan.tracks, sound.vectors, start, end, length=length,
                                     constraints=constraints), "path", start, labels, constraints.filters.to_dict())
    with tabs[2]:
        st.caption(labels["alchemy_help"])
        positive = st.multiselect(labels["positive"], options, default=[sound_focus_id],
                                  format_func=lambda value: _track_name(by_id[value]), key="explore_positive")
        negative = st.multiselect(labels["negative"], options,
                                  format_func=lambda value: _track_name(by_id[value]), key="explore_negative")
        exclusion = st.slider(labels["negative_strength"], 0, 50, 15, key="explore_negative_share")
        length = (st.slider(labels["requested"], 1, min(40, len(options)),
                            min(12, len(options)), key="explore_alchemy_count")
                  if len(options) > 1 else 1)
        if st.button(labels["make_alchemy"], disabled=not positive, key="explore_alchemy_button"):
            _accept_result(song_alchemy(plan.tracks, sound.vectors, positive, negative_ids=negative,
                                        limit=length, constraints=constraints,
                                        negative_exclusion_percentile=100 - exclusion),
                           "alchemy", positive[0], labels, constraints.filters.to_dict())


def _playlist_tray(plan: CollectionPlan, artifacts: Path, app_root: Path, language: str,
                   labels: dict[str, str], *, stage: str = "review") -> None:
    st.subheader(labels["candidate"])
    by_id = plan.track_by_id()
    draft: PlaylistDraft = st.session_state.playlist_draft
    ids = [track_id for track_id in st.session_state.get("explore_candidate_ids", []) if track_id in by_id]
    if not ids:
        st.info(labels["no_candidate"])
        return
    exclusion_signature = tuple(ids)
    if st.session_state.get("explore_exclusion_signature") != exclusion_signature:
        st.session_state.explore_excluded_ids = [track_id for track_id in ids
            if (by_id[track_id].source_sha256 or track_id) in draft.excluded]
        st.session_state.explore_exclusion_signature = exclusion_signature
    if stage == "review":
        excluded = st.multiselect(labels["excluded"], ids, key="explore_excluded_ids",
                                  format_func=lambda value: _track_name(by_id[value]))
        content_excluded = [by_id[track_id].source_sha256 or track_id for track_id in excluded]
        if draft.excluded != content_excluded:
            draft.excluded = content_excluded
            _save_draft(artifacts, draft, labels)
    else:
        excluded = st.session_state.get("explore_excluded_ids", [])
    kept = [by_id[track_id] for track_id in ids if track_id not in excluded]
    st.metric(labels["remaining"], len(kept))
    if not kept:
        st.warning(labels["status_no_candidates"])
        return
    if stage == "review":
        seed = by_id.get(st.session_state.get("explore_seed_id"))
        scores = st.session_state.get("explore_candidate_scores", {})
        rows = []
        for index, track in enumerate(kept, 1):
            row = {"#": index, labels["title"]: track.metadata.title, labels["artist"]: track.metadata.artist,
                   labels["genre"]: track.metadata.genre or labels["unprovided"]}
            if track.track_id in scores and st.session_state.get("explore_candidate_kind") != "path":
                row[labels["theme_score"] if st.session_state.get("explore_candidate_kind") == "theme_similar"
                    else labels["score"]] = round(scores[track.track_id], 3)
            if seed and seed.track_id != track.track_id and st.session_state.get("explore_candidate_kind") != "theme_similar":
                row[labels["common"]] = _shared_features(seed, track, labels)
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if scores and st.session_state.get("explore_candidate_kind") != "path":
            st.caption(labels["theme_score_note"] if st.session_state.get("explore_candidate_kind") == "theme_similar"
                       else labels["score_note"])
        preview_id = st.selectbox(labels["preview_song"], [track.track_id for track in kept],
                                  format_func=lambda value: _track_name(by_id[value]), key="explore_preview_song")
        st.audio(by_id[preview_id].source_path)
        st.caption(labels["reorder"])
        order_id = st.selectbox(labels["reorder"], [track.track_id for track in kept],
                                format_func=lambda value: _track_name(by_id[value]), key="explore_reorder_song")
        up, down, next_step = st.columns(3)
        if up.button(labels["move_up"], key="explore_move_up"):
            move_item(draft, by_id[order_id].source_sha256 or order_id, -1)
            _save_draft(artifacts, draft, labels)
            st.rerun()
        if down.button(labels["move_down"], key="explore_move_down"):
            move_item(draft, by_id[order_id].source_sha256 or order_id, 1)
            _save_draft(artifacts, draft, labels)
            st.rerun()
        if next_step.button(labels["go_save"], type="primary", key="explore_go_save"):
            st.session_state.explore_next_stage = "save"
            st.rerun()
        return
    st.dataframe(pd.DataFrame([{"#": index, labels["title"]: track.metadata.title,
                                labels["artist"]: track.metadata.artist}
                               for index, track in enumerate(kept, 1)]), hide_index=True, width="stretch")
    previous_language = st.session_state.get("explore_playlist_name_language")
    previous_default = LABELS.get(previous_language, {}).get("name_default")
    if previous_language != language:
        if st.session_state.get("explore_playlist_name") in (None, previous_default):
            st.session_state.explore_playlist_name = draft.name or labels["name_default"]
        st.session_state.explore_playlist_name_language = language
    name = st.text_input(labels["playlist_name"], key="explore_playlist_name")
    if name != draft.name:
        draft.name = name
        _save_draft(artifacts, draft, labels)
    try:
        clean_name = safe_playlist_name(name)
    except ValueError:
        clean_name = None
        st.warning(labels["name_invalid"])
    st.caption(labels["download_note"])
    st.download_button(labels["download"], playlist_bytes(kept),
                       file_name=f"{clean_name or 'playlist'}.m3u8", mime="audio/x-mpegurl",
                       disabled=clean_name is None, key="explore_download")
    if clean_name is None:
        return
    with st.expander(labels["copy"]):
        output = Path(st.text_input(labels["output"], value=str(app_root / "output" / "Map Playlists"),
                                    key="explore_output"))
        adapted = build_playlist_plan(plan, kept, clean_name, PlaylistFilters(), language)
        adapted.selection_query = {
            "origin": ("theme_map" if st.session_state.get("explore_candidate_kind") in
                       {"theme_region", "theme_similar"} else "sound_map"),
            "mode": st.session_state.get("explore_candidate_kind", "region"),
            "selected_track_ids": [track.track_id for track in kept],
            "seed_track_id": st.session_state.get("explore_seed_id"),
        }
        adapter = LocalFolderAdapter(output)
        signature = (plan.analysis_id, tuple(track.track_id for track in kept), clean_name, str(output.resolve()))
        try:
            operations = adapter.preview(adapted)
        except Exception:
            LOGGER.exception("Could not preview map playlist folder")
            st.error(labels["copy_error"])
            return
        st.write(f"{labels['copy_preview']}: {len(operations)}")
        st.dataframe(pd.DataFrame([{labels["source"]: item.source, labels["target"]: item.destination}
                                   for item in operations[:20]]), hide_index=True, width="stretch")
        if st.session_state.get("explore_copy_signature") != signature:
            st.session_state.explore_copy_signature = signature
            st.session_state.explore_copy_agree = False
        previous = st.session_state.get("explore_last_copy")
        duplicate = bool(previous and previous[0] == signature and Path(previous[1]).is_file())
        if duplicate:
            st.info(labels["duplicate"])
        agreed = st.checkbox(labels["agree"], key="explore_copy_agree")
        if st.button(labels["create"], type="primary", disabled=not agreed or duplicate,
                     key="explore_copy_create"):
            try:
                result = adapter.apply(adapted)
                st.session_state.explore_last_copy = (signature, result["manifest"], str(output.resolve()))
                st.success(f"{labels['created']}: {result['copied']}")
            except Exception:
                LOGGER.exception("Could not create map playlist folder")
                st.error(labels["copy_error"])
    with st.expander(labels["grouped_copy"]):
        selectable = ["instrument", "tonality", "key", "loudness", "tempo", "agitation", "brightness"]
        tags = st.multiselect(labels["group_tags"], selectable, default=["agitation"],
                              max_selections=3, format_func=lambda value: TAG_LABELS[language][value],
                              key="explore_group_tags")
        if tags:
            grouped = build_playlist_plan(plan, kept, clean_name, PlaylistFilters(), language)
            try:
                grouped.folders, grouped.tag_keys = compile_scheme(
                    grouped.tracks, "custom", tag_keys=tags, naming_mode="quant", language=language,
                )
            except ValueError:
                st.error(labels["copy_error"])
            else:
                grouped.selection_query = {"origin": "unified_playlist", "mode": "grouped",
                                           "selected_track_ids": [track.track_id for track in kept],
                                           "tag_keys": tags}
                st.write(f"{labels['group_preview']}: {len(grouped.folders)}")
                st.dataframe(pd.DataFrame([{labels["group_preview"]: folder.name,
                                            labels["remaining"]: len(folder.track_ids)}
                                           for folder in grouped.folders]), hide_index=True, width="stretch")
                if len(grouped.folders) > max(12, len(kept) // 3):
                    st.warning(labels["group_many"])
                group_output = Path(st.text_input(labels["output"],
                                                  value=str(app_root / "output" / "Grouped Playlists"),
                                                  key="explore_group_output"))
                group_adapter = LocalFolderAdapter(group_output)
                group_signature = (plan.analysis_id, tuple(track.track_id for track in kept),
                                   tuple(tags), str(group_output.resolve()))
                try:
                    group_operations = group_adapter.preview(grouped)
                except Exception:
                    LOGGER.exception("Could not preview grouped playlist folders")
                    st.error(labels["copy_error"])
                else:
                    st.caption(f"{labels['copy_preview']}: {len(group_operations)}")
                    st.dataframe(pd.DataFrame([{labels["source"]: item.source,
                                                labels["target"]: item.destination}
                                               for item in group_operations[:20]]),
                                 hide_index=True, width="stretch")
                    if st.session_state.get("explore_group_signature") != group_signature:
                        st.session_state.explore_group_signature = group_signature
                        st.session_state.explore_group_agree = False
                    previous_group = st.session_state.get("explore_last_copy")
                    duplicate_group = bool(previous_group and previous_group[0] == group_signature
                                           and Path(previous_group[1]).is_file())
                    group_agreed = st.checkbox(labels["agree"], key="explore_group_agree")
                    if st.button(labels["create"], disabled=not group_agreed or duplicate_group,
                                 key="explore_group_create"):
                        try:
                            result = group_adapter.apply(grouped)
                            st.session_state.explore_last_copy = (
                                group_signature, result["manifest"], str(group_output.resolve()))
                            st.success(f"{labels['created']}: {result['copied']}")
                        except Exception:
                            LOGGER.exception("Could not create grouped playlist folders")
                            st.error(labels["copy_error"])
    previous = st.session_state.get("explore_last_copy")
    if previous and Path(previous[1]).is_file():
        agreed = st.checkbox(labels["undo_agree"], key="explore_undo_agree")
        if st.button(labels["undo"], disabled=not agreed, key="explore_undo"):
            try:
                result = LocalFolderAdapter(Path(previous[2])).rollback(Path(previous[1]))
                st.session_state.explore_last_copy = None
                st.success(f"{labels['undone']}: {result['removed_copies']}")
            except Exception:
                LOGGER.exception("Could not undo map playlist folder")
                st.error(labels["copy_error"])


def _lyrics_workspace(plan: CollectionPlan, artifacts: Path, focus_id: str | None,
                      labels: dict[str, str], language: str, verified: frozenset[str],
                      app_root: Path) -> None:
    st.caption(labels["lyrics_intro"])
    folder_text = st.text_input(labels["lyrics_folder"], key="explore_lyrics_folder")
    language_model_text = st.text_input(labels["lyrics_language_model"],
                                        value=str(app_root / "models" / "lid.176.ftz"),
                                        key="explore_language_model")
    if not language_model_text.strip() or not Path(language_model_text).is_file():
        st.caption(labels["lyrics_language_model_missing"])
    st.caption(labels["lyrics_local_only"])
    st.caption(labels["lyrics_download_warning"])
    allow_download = st.checkbox(labels["lyrics_allow_download"], key="explore_lyrics_download")
    selected_sources = st.session_state.get("explore_lyrics_selected_sources", {})
    try:
        manual_themes = theme_assignments(plan.tracks, artifacts)
    except (OSError, ValueError):
        LOGGER.exception("Could not read theme annotations")
        manual_themes = {}
        st.warning(labels["theme_save_error"])
    local_signature = (plan.analysis_id, folder_text, language_model_text, tuple(sorted(verified)),
                       tuple(sorted(selected_sources.items())))
    # Checking download consent alone must not start a network fetch; the scan button does.
    theme_signature = local_signature + (tuple(sorted(manual_themes.items())),)
    refresh = st.button(labels["lyrics_scan"], key="explore_lyrics_scan")
    sources = {track_id: Path(path) for track_id, path in selected_sources.items()}
    lyrics_root = Path(folder_text) if folder_text.strip() else None
    if refresh or st.session_state.get("explore_language_signature") != local_signature:
        try:
            language_detector = (FastTextLanguageDetector(Path(language_model_text))
                                 if language_model_text.strip() and Path(language_model_text).is_file() else None)
            local_result = scan_lyric_languages(
                plan.tracks, lyrics_root=lyrics_root,
                manual_instrumental_ids=tuple(verified),
                selected_sources=sources,
                language_detector=language_detector,
            )
            st.session_state.explore_language_result = local_result
            st.session_state.explore_language_signature = local_signature
        except Exception:
            LOGGER.exception("Local lyric/language scan failed")
            st.error(labels["lyrics_other_error"])
    if refresh or st.session_state.get("explore_lyrics_signature") != theme_signature:
        try:
            result = build_lyrics_map(
                plan.tracks, artifacts, lyrics_root=lyrics_root,
                manual_instrumental_ids=tuple(verified),
                embedder=LocalLyricsEmbedder(allow_download=allow_download and refresh),
                selected_sources=sources,
                manual_themes=manual_themes,
            )
            st.session_state.explore_lyrics_result = result
            st.session_state.explore_lyrics_error = None
        except LyricsModelUnavailable:
            st.session_state.explore_lyrics_result = build_title_clue_map(
                plan.tracks, manual_themes=manual_themes,
            )
            st.session_state.explore_lyrics_error = "model_missing"
        except Exception:
            LOGGER.exception("Lyrics map failed")
            st.session_state.explore_lyrics_result = None
            st.session_state.explore_lyrics_error = "other_error"
        st.session_state.explore_lyrics_signature = theme_signature
    local_result = st.session_state.get("explore_language_result")
    if not local_result or st.session_state.get("explore_language_signature") != local_signature:
        # Lyric-language recognition is separate from theme classification;
        # its failure must not hide a manually curated or title-based atlas.
        local_result = SimpleNamespace(statuses={}, ambiguous_candidates={}, sources={}, languages={})
    counts = Counter(local_result.statuses.values())
    st.metric(labels["lyrics_coverage"], f"{counts.get('valid', 0)}/{len(plan.tracks)}")
    for status in ("missing", "short", "ambiguous", "instrumental", "read_error"):
        if counts.get(status):
            st.caption(f"{labels[f'lyrics_{status}']}: {counts[status]}")
    ambiguous = getattr(local_result, "ambiguous_candidates", {})
    if ambiguous:
        with st.expander(labels["lyrics_match_help"]):
            by_id = plan.track_by_id()
            for track_id, candidates in ambiguous.items():
                if track_id not in by_id or not candidates:
                    continue
                chosen = st.selectbox(
                    f"{labels['lyrics_match_file']}: {_track_name(by_id[track_id])}", candidates,
                    key=f"explore_lyrics_match_{track_id}",
                )
                if st.button(labels["lyrics_match"], key=f"explore_lyrics_confirm_{track_id}"):
                    st.session_state.explore_lyrics_selected_sources = {**selected_sources, track_id: chosen}
                    st.session_state.explore_lyrics_signature = None
                    st.session_state.explore_language_signature = None
                    st.rerun()
    by_id = plan.track_by_id()
    result = st.session_state.get("explore_lyrics_result")
    if st.session_state.get("explore_lyrics_error") == "model_missing":
        st.warning(labels["lyrics_model_missing"])
    elif st.session_state.get("explore_lyrics_error") == "other_error":
        st.error(labels["lyrics_other_error"])
    if result is not None and st.session_state.get("explore_lyrics_error") == "model_missing":
        st.caption(labels["theme_basic_title"])
    if result:
        atlas = build_theme_atlas({track_id: theme_id for track_id, theme_id in result.primary_themes.items()
                                   if track_id in by_id})
        if atlas.regions:
            if "unknown" in atlas.regions:
                total = sum(region.count for region in atlas.regions.values())
                st.caption(f"{labels['theme_unknown']}: {atlas.regions['unknown'].count}/{total}")
            selected_id = st.session_state.get("explore_selected_theme")
            if selected_id not in atlas.regions:
                selected_id = next(iter(atlas.regions))
                st.session_state.explore_selected_theme = selected_id
            clicked = _theme_island_map(atlas, selected_id, labels)
            if clicked and clicked != selected_id:
                st.session_state.explore_selected_theme = clicked
                st.rerun()
            _theme_region_detail(plan, atlas, result, artifacts, selected_id, labels, language)
        else:
            st.info(labels["lyrics_no_data"])
    elif st.session_state.get("explore_lyrics_error") is None:
        st.info(labels["lyrics_no_data"])
    focused = st.session_state.get("explore_focus_id")
    if result and focused in result.primary_themes:
        theme_id = result.primary_themes[focused]
        evidence = result.evidence_sources.get(focused, "unknown")
        st.write(f"{labels['lyrics_theme']}: {labels.get(f'theme_{theme_id}', labels['theme_unknown'])}")
        st.caption(f"{labels['theme_evidence']}: " + labels.get(
            f"theme_evidence_{evidence}", labels["theme_evidence_unknown"],
        ))
    with st.expander(labels["assistant_title"]):
        if focused not in by_id or local_result.statuses.get(focused) != "valid":
            st.info(labels["assistant_unavailable"])
        else:
            try:
                resolution = resolve_track_lyrics(
                    by_id[focused], lyrics_root=Path(folder_text) if folder_text.strip() else None,
                    all_tracks=plan.tracks,
                    selected_path=Path(selected_sources[focused]) if focused in selected_sources else None,
                )
                if resolution.status != "valid":
                    st.info(labels["assistant_unavailable"])
                else:
                    preview = preview_theme_request(by_id[focused].metadata.title, resolution.text)
                    st.caption(labels["assistant_purpose"])
                    st.json({
                        labels["assistant_destination"]: "DeepSeek API",
                        labels["assistant_model"]: "deepseek-flash",
                        labels["title"]: preview.title,
                        labels["assistant_preview"]: preview.lyric_excerpt,
                    })
                    api_key_available = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
                    if not api_key_available:
                        st.info(labels["assistant_key_missing"])
                    consent = st.checkbox(labels["assistant_consent"], key=f"explore_ai_consent_{focused}")
                    if st.button(labels["assistant_run"], disabled=not consent or not api_key_available,
                                 key=f"explore_ai_run_{focused}"):
                        try:
                            suggestion = suggest_theme(
                                preview, api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                                consent=True, language=language,
                            )
                            signature = hashlib.sha256(
                                f"{focused}|{preview.title}|{preview.lyric_excerpt}".encode("utf-8")
                            ).hexdigest()
                            st.session_state.explore_ai_suggestion = (signature, suggestion)
                        except ThemeAssistantError:
                            LOGGER.warning("Theme assistant request failed for track %s", focused)
                            st.error(labels["assistant_error"])
                    signature = hashlib.sha256(
                        f"{focused}|{preview.title}|{preview.lyric_excerpt}".encode("utf-8")
                    ).hexdigest()
                    saved = st.session_state.get("explore_ai_suggestion")
                    if saved and saved[0] == signature:
                        st.write(f"{labels['assistant_result']}: {', '.join(saved[1].themes)}")
                        st.write(saved[1].explanation)
            except (OSError, ValueError, UnicodeError):
                LOGGER.exception("Could not prepare lyric excerpt for optional theme assistant")
                st.error(labels["assistant_error"])


def _genre_workspace(plan: CollectionPlan, sound: SonicMap, artifacts: Path,
                     labels: dict[str, str], focus_id: str) -> None:
    st.caption(labels["genre_intro"])
    try:
        assignments = verified_genre_assignments(plan.tracks, artifacts)
    except (OSError, ValueError):
        LOGGER.exception("Could not read verified genre annotations")
        assignments = {}
        st.error(labels["genre_review_error"])
    st.metric(labels["genre_coverage"], f"{len(assignments)}/{len(plan.tracks)}")
    st.metric(labels["genre_categories"], len(set(assignments.values())))
    if len(set(assignments.values())) < 2:
        st.info(labels["genre_insufficient"])
        return
    rows, centers = _category_rows(plan, assignments, set(sound.vectors))
    if not rows or len(centers) < 2:
        st.info(labels["genre_insufficient"])
        return
    _zoom_controls(rows, "explore_genre_chart", labels, focus_id)
    selected = _draw_map(rows, color="category", focus_id=focus_id,
                         chart_key="explore_genre_chart", labels=labels, category_centers=centers)
    _sync_chart_selection(selected, "explore_genre_chart")
    _overlap_picker(rows, "explore_genre_chart", plan, labels)
    st.caption(labels["category_help"])


def _language_name(code: str, labels: dict[str, str]) -> str:
    return labels.get(f"language_{code}", code.upper() if code and code != "unknown" else labels["language_unknown"])


def _language_workspace(plan: CollectionPlan, sound: SonicMap, labels: dict[str, str],
                        focus_id: str, verified: frozenset[str]) -> None:
    st.caption(labels["language_intro"])
    result = st.session_state.get("explore_language_result")
    languages = getattr(result, "languages", {}) if result is not None else {}
    statuses = getattr(result, "language_statuses", {}) if result is not None else {}
    if "unavailable" in statuses.values():
        st.caption(labels["language_runtime_unavailable"])
    known_count = sum(statuses.get(track.track_id) == "known" and track.track_id in sound.vectors
                      for track in plan.tracks)
    st.metric(labels["language_coverage"], f"{known_count}/{len(plan.tracks)}")
    if not known_count:
        st.info(labels["language_insufficient"])
        return
    assignments = {
        track.track_id: _language_name("instrumental" if track.track_id in verified
                                      else languages.get(track.track_id, "unknown"), labels)
        for track in plan.tracks
    }
    rows, centers = _category_rows(plan, assignments, set(sound.vectors))
    if not rows:
        st.info(labels["language_insufficient"])
        return
    _zoom_controls(rows, "explore_language_chart", labels, focus_id)
    selected = _draw_map(rows, color="category", focus_id=focus_id,
                         chart_key="explore_language_chart", labels=labels, category_centers=centers)
    _sync_chart_selection(selected, "explore_language_chart")
    _overlap_picker(rows, "explore_language_chart", plan, labels)
    st.caption(labels["category_help"])


def _focus_detail(plan: CollectionPlan, sound: SonicMap, artifacts: Path,
                  language: str, labels: dict[str, str], verified: frozenset[str]) -> str:
    by_id = plan.track_by_id()
    options = [track.track_id for track in plan.tracks]
    focus_id = st.session_state.get("explore_focus_id")
    if focus_id not in options:
        focus_id = options[0]
        st.session_state.explore_focus_id = focus_id
    if st.session_state.get("explore_track_search") not in options:
        st.session_state.explore_track_search = focus_id
    chosen_id = st.selectbox(labels["song_search"], options,
                             format_func=lambda value: _track_name(by_id[value]),
                             key="explore_track_search")
    st.session_state.explore_focus_id = chosen_id
    focused = by_id[chosen_id]
    st.subheader(labels["detail"])
    cover = _cover_for(focused.source_path, focused.source_mtime_ns)
    if cover:
        st.image(base64.b64decode(cover.split(",", 1)[1]), width="stretch")
    else:
        st.caption(labels["cover_missing"])
    st.write(f"{labels['title']}: {focused.metadata.title}")
    st.write(f"{labels['artist']}: {focused.metadata.artist or labels['unprovided']}")
    st.write(f"{labels['album']}: {focused.metadata.album or labels['unprovided']}")
    st.write(f"{labels['genre']}: {focused.metadata.genre or labels['unprovided']}")
    with st.expander(labels["genre_review"]):
        st.caption(labels["genre_review_help"])
        try:
            verified_genre = verified_genre_assignments(plan.tracks, artifacts).get(chosen_id, "")
        except (OSError, ValueError):
            LOGGER.exception("Could not read verified genre annotations")
            verified_genre = ""
            st.error(labels["genre_review_error"])
        genre_nonce_key = f"explore_verified_genre_nonce_{chosen_id}"
        genre_input_key = f"explore_verified_genre_{chosen_id}_{st.session_state.get(genre_nonce_key, 0)}"
        proposed_genre = st.text_input(
            labels["genre_review_input"], value=verified_genre,
            key=genre_input_key,
        )
        if st.button(labels["genre_review_save"], disabled=not proposed_genre.strip(),
                     key=f"explore_save_genre_{chosen_id}"):
            try:
                set_verified_genre(focused, artifacts, proposed_genre)
                st.session_state[genre_nonce_key] = st.session_state.get(genre_nonce_key, 0) + 1
                st.rerun()
            except (OSError, ValueError):
                LOGGER.exception("Could not save verified genre annotation")
                st.error(labels["genre_review_error"])
        if verified_genre and st.button(labels["genre_review_clear"],
                                        key=f"explore_clear_genre_{chosen_id}"):
            try:
                clear_verified_genre(focused, artifacts)
                st.session_state[genre_nonce_key] = st.session_state.get(genre_nonce_key, 0) + 1
                st.rerun()
            except (OSError, ValueError):
                LOGGER.exception("Could not clear verified genre annotation")
                st.error(labels["genre_review_error"])
    st.write(f"{labels['instrument']}: {VALUE_LABELS[language].get(focused.instrument, labels['unknown'])}")
    st.write(f"{labels['tempo']}: {focused.acoustic.tempo_bpm:.1f} BPM")
    st.write(f"{labels['loudness']}: {focused.acoustic.rms_dbfs:.1f} dBFS")
    if focused.standard:
        st.write(f"{labels['act']}: {focused.standard.agitation:.1f}/100")
        st.write(f"{labels['bri']}: {focused.standard.brightness:.1f}/100")
    st.caption(labels["metadata_caution"])
    lyric_result = st.session_state.get("explore_language_result")
    if lyric_result and st.session_state.get("explore_language_signature", (None,))[0] == plan.analysis_id:
        status = lyric_result.statuses.get(chosen_id, "missing")
        st.write(f"{labels['lyrics_status']}: {labels.get(f'lyrics_{status}', labels['unknown'])}")
        source = lyric_result.sources.get(chosen_id)
        if source:
            st.write(f"{labels['lyrics_source']}: {labels.get(f'lyrics_source_{source}', labels['unknown'])}")
        code = getattr(lyric_result, "languages", {}).get(chosen_id, "unknown")
        st.write(f"{labels['language_status']}: {_language_name(code, labels)}")
        if code == "unknown":
            st.caption(labels["language_uncertain"])
    st.audio(focused.source_path)
    st.caption(labels["verify_help"])
    if chosen_id in verified:
        st.success(labels["verified"])
    if st.button(labels["unverify"] if chosen_id in verified else labels["verify"],
                 key="explore_verify_instrumental"):
        try:
            set_instrumental_confirmation(focused, artifacts, chosen_id not in verified)
            st.rerun()
        except (OSError, ValueError):
            LOGGER.exception("Could not save instrumental confirmation")
            st.error(labels["verify_error"])
    return chosen_id


def render_explorer(plan: CollectionPlan, artifacts: Path, language: str, app_root: Path) -> None:
    labels = LABELS[language]
    draft = _ensure_draft(plan, artifacts, labels)
    stages = ("find", "review", "save")
    pending_stage = st.session_state.pop("explore_next_stage", None)
    if pending_stage in stages:
        st.session_state.explore_stage = pending_stage
    if st.session_state.get("explore_stage") not in stages:
        st.session_state.explore_stage = "find"
    stage = st.radio(labels["candidate"], stages, horizontal=True,
                     format_func=lambda value: labels[f"step_{value}"], key="explore_stage")
    st.caption(f"{labels['current_draft']}: {len(reconcile(draft, plan)[0])} · " + labels["scale_note"])
    if stage in {"review", "save"}:
        _playlist_tray(plan, artifacts, app_root, language, labels, stage=stage)
        if st.button(labels["back_find"], key="explore_back_find"):
            st.session_state.explore_next_stage = "find"
            st.rerun()
        return
    st.caption(labels["intro"])
    sound = _model_state(plan, artifacts, labels)
    st.caption(labels["model_mode"] if sound.mode == "musicnn" else labels["basic_mode"])
    if sound.mode != "musicnn":
        st.warning(labels["basic_warning"] if sound.fallback_reason == "model_missing" else labels["model_failure"])
    st.caption(f"{labels['map_coverage']}: {len(sound.points)}/{len(plan.tracks)} · "
               f"{labels['cache_hits']}: {sound.cache_hits}")
    warning_codes = tuple(sound.warnings)
    if any(item.startswith("legacy_brightness_missing_high_frequency_ratio:") for item in warning_codes):
        st.warning(labels["legacy_brightness_warning"])
    if "axis_fidelity_below_threshold_in_preserved_layout" in warning_codes:
        st.warning(labels["axis_fidelity_warning"])
    if any(item.startswith("low_tempo_confidence:") for item in warning_codes):
        st.caption(labels["low_tempo_warning"])
    if not sound.points:
        st.warning(labels["status_no_candidates"])
        return
    by_id = plan.track_by_id()
    if st.session_state.get("explore_focus_id") not in by_id:
        st.session_state.explore_focus_id = sound.points[0].track_id
    focus_id = st.session_state.explore_focus_id
    try:
        verified = confirmed_instrumental_ids(plan.tracks, artifacts)
    except (OSError, ValueError):
        LOGGER.exception("Could not read user annotations")
        verified = frozenset()
    left, right = st.columns([3, 1.35], gap="large")
    with left:
        tab_names = [labels["sonic_view"], labels["lyrics_view"],
                     labels["genre_view"], labels["language_view"]]
        tab_key = "explore_map_tab"
        previous_language = st.session_state.get("explore_map_tab_language")
        if previous_language != language:
            previous_names = ([LABELS[previous_language][key] for key in
                               ("sonic_view", "lyrics_view", "genre_view", "language_view")]
                              if previous_language in LABELS else ())
            current = st.session_state.get(tab_key)
            index = previous_names.index(current) if current in previous_names else 0
            st.session_state[tab_key] = tab_names[index]
            st.session_state.explore_map_tab_language = language
        elif st.session_state.get(tab_key) not in tab_names:
            st.session_state[tab_key] = tab_names[0]
        # Tracked tabs retain the active map across a component-triggered rerun.
        # In particular, clicking a theme island must not reveal the sound tab.
        tabs = st.tabs(tab_names, key=tab_key, on_change="rerun")
        with tabs[0]:
            action = st.radio(
                labels["map_action"], ("point", "box", "lasso"), horizontal=True,
                format_func=lambda value: labels[f"action_{value}"],
                key="explore_map_action",
            )
            zodiac, show_zodiac = _zodiac_controls(plan, sound, language, labels)
            sound_rows = _sonic_rows(plan, sound, labels, language)
            _zoom_controls(sound_rows, "explore_sonic_chart", labels, focus_id)
            selected = _draw_map(
                sound_rows, color="act", focus_id=focus_id,
                chart_key="explore_sonic_chart", labels=labels, sonic_axes=True,
                dragmode={"point": "pan", "box": "select", "lasso": "lasso"}[action],
                zodiac=zodiac if show_zodiac else None,
            )
            _sync_chart_selection(selected, "explore_sonic_chart")
            _overlap_picker(sound_rows, "explore_sonic_chart", plan, labels, sonic_axes=True)
            _zodiac_summary(plan, sound, zodiac, language, labels)
            st.caption(labels["map_help"])
            st.caption(labels["map_semantic_only"] if "semantic-only" in sound.projection
                       else labels["map_hybrid"])
            st.caption(labels["map_trend_note"])
            if sound.layout_metrics:
                with st.expander(labels["layout_quality"]):
                    metrics = sound.layout_metrics
                    checks = st.columns(2)
                    checks[0].metric(labels["tempo_order"],
                                     f"{float(metrics.get('bpm_axis_spearman', 0.0)):.2f}")
                    checks[1].metric(labels["bri_order"],
                                     f"{float(metrics.get('bri_axis_spearman', 0.0)):.2f}")
                    if sound.mode == "musicnn" and len(sound.points) > 11:
                        st.metric(labels["neighbor_retention"],
                                  f"{100 * float(metrics.get('neighbor_overlap_at_10', 0.0)):.0f}%")
                    st.caption(labels["layout_quality_note"] if sound.mode == "musicnn"
                               else labels["basic_layout_note"])
            if st.button(labels["clear_map"], key="explore_clear_map"):
                st.session_state.explore_map_ids = []
                for chart in ("explore_sonic_chart", "explore_lyrics_chart",
                              "explore_genre_chart", "explore_language_chart"):
                    st.session_state[f"{chart}_nonce"] = st.session_state.get(f"{chart}_nonce", 0) + 1
                    st.session_state[f"{chart}_selected_ids"] = ()
                st.rerun()
        with tabs[1]:
            _lyrics_workspace(plan, artifacts, st.session_state.get("explore_focus_id"),
                              labels, language, verified, app_root)
        with tabs[2]:
            _genre_workspace(plan, sound, artifacts, labels, st.session_state.get("explore_focus_id"))
        with tabs[3]:
            _language_workspace(plan, sound, labels, st.session_state.get("explore_focus_id"), verified)
    with right:
        st.metric(labels["current_draft"], len(reconcile(draft, plan)[0]))
        if st.button(labels["go_review"], disabled=not reconcile(draft, plan)[0], key="explore_go_review_side"):
            st.session_state.explore_next_stage = "review"
            st.rerun()
        _focus_detail(plan, sound, artifacts, language, labels, verified)
        if st.button(labels["stage_focus"], key="explore_stage_focus"):
            _stage_candidates([st.session_state.explore_focus_id], "single_song")
    constraints = _filters(plan, labels, language, verified)
    _natural_language_filters(plan, labels, language)
    _candidate_actions(plan, sound, st.session_state.explore_focus_id,
                       st.session_state.get("explore_map_ids", []), constraints, labels)
    _pending_actions(plan, artifacts, labels)
    if st.button(labels["go_review"], disabled=not reconcile(draft, plan)[0], type="primary", key="explore_go_review"):
        st.session_state.explore_next_stage = "review"
        st.rerun()
