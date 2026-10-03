"""Temporary listening desk for building a manually verified test set."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import mimetypes
import os
from pathlib import Path
import tempfile

import streamlit as st

from .lyrics_map import resolve_track_lyrics
from .metadata import read_cover_data_uri
from .service import load_plan
from .user_annotations import set_instrumental_confirmation


LABELS = {
    "instrumental": ("纯音乐", "无可辨认的人声歌词"),
    "vocal_with_lyrics": ("有人声·歌词可用", "当前歌词与录音对应"),
    "vocal_missing_lyrics": ("有人声·歌词缺失", "需要继续补歌词"),
    "skip": ("暂时跳过", "版本或内容无法确认"),
}
REVIEW_FILE = "manual_test_review.json"


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback
    except (OSError, ValueError):
        return fallback


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".manual-review-", suffix=".tmp", delete=False) as file:
            pending = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(pending, path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _candidate_ids(test_sets: dict, mode: str) -> list[str]:
    if mode == "优先审核":
        rows = test_sets.get("instrumental_candidates", []) + test_sets.get("review", [])
    elif mode == "纯音乐候选":
        rows = test_sets.get("instrumental_candidates", [])
    elif mode == "待复核歌曲":
        rows = test_sets.get("review", [])
    else:
        rows = test_sets.get("lyrics", []) + test_sets.get("instrumental_candidates", []) + test_sets.get("review", [])
    return [str(row.get("track_id", "")) for row in rows if row.get("track_id")]


def _metadata_candidate(enrichment: dict, track_id: str) -> dict | None:
    item = enrichment.get("results", {}).get(track_id, {})
    matches = item.get("matches", [])
    return matches[0] if matches else None


def _record_review(track, label: str, note: str, metadata_decision: str,
                   artifacts: Path, existing: dict) -> dict:
    digest = track.source_sha256.lower()
    existing.setdefault("schema_version", 1)
    records = existing.setdefault("records_by_sha256", {})
    records[digest] = {
        "track_id": track.track_id,
        "title": track.metadata.title,
        "artist": track.metadata.artist,
        "label": label,
        "note": note.strip()[:500],
        "metadata_decision": metadata_decision,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(artifacts / REVIEW_FILE, existing)
    set_instrumental_confirmation(track, artifacts, label == "instrumental")
    return existing


def _css() -> None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700;900&family=DM+Mono:wght@400;500&display=swap');
    :root { --ink:#18201d; --paper:#f3efe5; --orange:#ef5b2a; --sage:#9aa899; --line:#cfc8b8; }
    .stApp { background:
      linear-gradient(90deg, rgba(24,32,29,.035) 1px, transparent 1px) 0 0/28px 28px,
      var(--paper); color:var(--ink); }
    .block-container { max-width:1080px; padding-top:2rem; padding-bottom:5rem; }
    h1,h2,h3 { font-family:'Noto Serif SC',serif !important; letter-spacing:-.035em; color:var(--ink) !important; }
    p, label, .stMarkdown { color:var(--ink); }
    [data-testid="stMetric"] { border-top:3px solid var(--ink); padding-top:.7rem; }
    [data-testid="stAudio"] { border-radius:2px; border:1px solid var(--line); background:#fffaf0; }
    .review-kicker { font-family:'DM Mono',monospace; text-transform:uppercase; letter-spacing:.12em; color:var(--orange); font-size:.76rem; }
    .review-card { border-top:1px solid var(--ink); border-bottom:1px solid var(--ink); padding:1.25rem 0; margin:.4rem 0 1rem; }
    .review-title { font-family:'Noto Serif SC',serif; font-size:clamp(2rem,5vw,4.6rem); font-weight:900; line-height:1.02; letter-spacing:-.055em; }
    .review-artist { font-family:'DM Mono',monospace; margin-top:.6rem; font-size:.95rem; }
    .status-chip { display:inline-block; border:1px solid var(--ink); padding:.25rem .55rem; margin:.2rem .3rem .2rem 0; font-family:'DM Mono',monospace; font-size:.72rem; }
    div.stButton > button { border:1px solid var(--ink); border-radius:0; min-height:3rem; font-weight:700; background:#fffaf0; }
    div.stButton > button:hover { background:var(--orange); color:white; border-color:var(--orange); }
    [data-testid="stSidebar"] { background:#e8e2d5; border-right:1px solid var(--line); }
    </style>
    """, unsafe_allow_html=True)


def render(root: Path) -> None:
    st.set_page_config(page_title="曲境 · 人工试听台", page_icon="◉", layout="wide")
    _css()
    artifacts = root / "artifacts"
    plan_path = artifacts / "collection_plan.json"
    tests_path = artifacts / "test_sets.json"
    if not plan_path.is_file() or not tests_path.is_file():
        st.error("缺少 collection_plan.json 或 test_sets.json，请先生成测试集。")
        return
    plan = load_plan(plan_path)
    by_id = plan.track_by_id()
    test_sets = _read_json(tests_path, {})
    enrichment = _read_json(artifacts / "metadata_enrichment.json", {})
    review_path = artifacts / REVIEW_FILE
    reviews = _read_json(review_path, {"schema_version": 1, "records_by_sha256": {}})
    records = reviews.get("records_by_sha256", {})

    with st.sidebar:
        st.markdown("### 试听队列")
        mode = st.radio("范围", ["优先审核", "纯音乐候选", "待复核歌曲", "全部歌曲"], label_visibility="collapsed")
        hide_done = st.toggle("隐藏已审核", value=True)
        query = st.text_input("搜索", placeholder="歌名或歌手")
    ids = _candidate_ids(test_sets, mode)
    if query.strip():
        needle = query.casefold().strip()
        ids = [track_id for track_id in ids if track_id in by_id and needle in
               f"{by_id[track_id].metadata.title} {by_id[track_id].metadata.artist}".casefold()]
    if hide_done:
        ids = [track_id for track_id in ids if by_id[track_id].source_sha256.lower() not in records]
    all_ids = _candidate_ids(test_sets, mode)
    reviewed_count = sum(by_id[i].source_sha256.lower() in records for i in all_ids if i in by_id)

    st.markdown('<div class="review-kicker">MuseFolders / Manual listening desk</div>', unsafe_allow_html=True)
    st.title("人工试听台")
    m1, m2, m3 = st.columns(3)
    m1.metric("当前队列", len(ids))
    m2.metric("已审核", reviewed_count)
    m3.metric("总进度", f"{reviewed_count}/{len(all_ids)}")
    st.progress(reviewed_count / max(1, len(all_ids)))
    if not ids:
        st.success("这个队列已经审核完成。可关闭“隐藏已审核”查看或修改结果。")
        return

    current_id = st.session_state.get("review_current_id")
    if current_id not in ids:
        current_id = ids[0]
        st.session_state.review_current_id = current_id
    pos = ids.index(current_id)
    track = by_id[current_id]
    digest = track.source_sha256.lower()
    existing = records.get(digest, {})

    prev_col, select_col, next_col = st.columns([1, 5, 1])
    if prev_col.button("← 上一首", disabled=pos == 0, use_container_width=True):
        st.session_state.review_current_id = ids[pos - 1]; st.rerun()
    selected = select_col.selectbox("选择歌曲", ids, index=pos,
        format_func=lambda tid: f"{by_id[tid].metadata.artist} — {by_id[tid].metadata.title}", label_visibility="collapsed")
    if selected != current_id:
        st.session_state.review_current_id = selected; st.rerun()
    if next_col.button("下一首 →", disabled=pos == len(ids) - 1, use_container_width=True):
        st.session_state.review_current_id = ids[pos + 1]; st.rerun()

    safe_title = html.escape(track.metadata.title)
    safe_artist = html.escape(track.metadata.artist or "未知歌手")
    safe_album = html.escape(track.metadata.album or "专辑未知")
    st.markdown(f'<div class="review-card"><div class="review-title">{safe_title}</div><div class="review-artist">{safe_artist} · {safe_album}</div></div>', unsafe_allow_html=True)
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        cover = read_cover_data_uri(Path(track.source_path))
        if cover:
            st.image(cover, width=220)
        try:
            st.audio(Path(track.source_path).read_bytes(), format=mimetypes.guess_type(track.source_path)[0] or "audio/mpeg")
        except OSError:
            st.error("无法读取本地音频文件。")
        lyrics = resolve_track_lyrics(track, lyrics_root=Path(plan.source_root), all_tracks=plan.tracks)
        chips = [f"歌词：{lyrics.status}", f"时长：{track.acoustic.duration_s:.0f}s", f"BPM：{track.acoustic.tempo_bpm:.0f}"]
        st.markdown("".join(f'<span class="status-chip">{value}</span>' for value in chips), unsafe_allow_html=True)
        with st.expander("查看匹配歌词", expanded=lyrics.status == "valid"):
            st.text(lyrics.text if lyrics.text else "没有匹配到可用歌词。")
    with right:
        st.markdown("### 元数据核对")
        candidate = _metadata_candidate(enrichment, track.track_id)
        st.caption("本地记录")
        st.write(f"**{track.metadata.title}**  \n{track.metadata.artist}  \n{track.metadata.album or '专辑未知'} · {track.metadata.year or '年份未知'}")
        if candidate:
            release = candidate.get("releases", [{}])[0] if candidate.get("releases") else {}
            st.caption("联网候选")
            st.write(f"**{candidate.get('title','')}**  \n{candidate.get('artist','')}  \n{release.get('title','') or '专辑未知'} · {release.get('date','') or '年份未知'}")
            metadata_decision = st.radio("联网候选是否对应当前录音？", ["不确定", "正确", "错误"],
                                         index=max(0, ["不确定", "正确", "错误"].index(existing.get("metadata_decision", "不确定"))), horizontal=True)
        else:
            st.info("当前没有联网元数据候选。")
            metadata_decision = "无候选"
        note = st.text_area("备注", value=existing.get("note", ""), placeholder="例如：副歌有人声、现场版、需要补歌词……")

    st.markdown("### 听完后选择")
    cols = st.columns(4)
    for column, (label, (title, help_text)) in zip(cols, LABELS.items()):
        if column.button(title, help=help_text, use_container_width=True, type="primary" if label == "instrumental" else "secondary"):
            reviews = _record_review(track, label, note, metadata_decision, artifacts, reviews)
            st.toast(f"已保存：{title}")
            remaining = [tid for tid in ids if tid != current_id]
            st.session_state.review_current_id = remaining[min(pos, len(remaining) - 1)] if remaining else None
            st.rerun()
    if existing:
        st.caption(f"当前已标记：{LABELS.get(existing.get('label'), ('未知', ''))[0]} · {existing.get('reviewed_at','')[:19]}")

    with st.expander("审核记录与导出"):
        counts = {key: sum(item.get("label") == key for item in records.values()) for key in LABELS}
        st.json({LABELS[key][0]: value for key, value in counts.items()})
        if review_path.is_file():
            st.download_button("下载审核记录 JSON", review_path.read_bytes(), file_name=REVIEW_FILE, mime="application/json")
