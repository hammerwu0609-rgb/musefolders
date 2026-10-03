"""Single-page music workspace using Streamlit's bidirectional component API."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path

import streamlit as st
from streamlit import runtime

from .consumer_workspace import (payload, parse_command, edit_playlist, archive_playlist,
                                 switch_playlist, saved_playlists)
from .playlist_draft import PlaylistDraft, apply_selection, save_draft, reconcile
from .playlist_filters import playlist_bytes, safe_playlist_name
from .library_search import parse_search, search_library, SearchHit
from .intent_assistant import translate_request, IntentAssistantError
from .model_settings import active_settings
from .demo_mode import check_ai_budget, portable_playlist_bytes
from .qqmusic_catalog import cached_platform, platform_lyrics
from .astrology import build_zodiac, make_zodiac_share_card

FRONTEND = Path(__file__).parent / "consumer_frontend"


@st.cache_data(show_spinner=False)
def _assets(stamp):
    vendor = (FRONTEND / "vendor" / "d3.min.js").read_text(encoding="utf-8")
    world = (FRONTEND / "vendor" / "world.json").read_text(encoding="utf-8")
    js = "const d3=(()=>{const exports={};const module={exports};\n" + vendor + "\nreturn module.exports;})();\nconst world=" + world + ";\n" + (FRONTEND / "workspace.js").read_text(encoding="utf-8")
    art = base64.b64encode((FRONTEND / "art" / "landscape-atlas.webp").read_bytes()).decode("ascii")
    art_css = ".landscape-art{background-image:url(data:image/webp;base64," + art + ");}\n"
    return ((FRONTEND / "workspace.html").read_text(encoding="utf-8"),
            "/* MuseFolders */\n" + art_css + (FRONTEND / "workspace.css").read_text(encoding="utf-8"), js)


def _component():
    stamp = tuple((FRONTEND / name).stat().st_mtime_ns for name in ("workspace.html", "workspace.css", "workspace.js", "art/landscape-atlas.webp"))
    html, css, js = _assets(stamp)
    return st.components.v2.component("musefolders_workspace", html=html, css=css, js=js)


def _media(path: str, mime: str, coordinate: str) -> str:
    if runtime.exists():
        return runtime.get_instance().media_file_mgr.add(path, mime, coordinate)
    return ""


def dispatch(action, plan, profiles, root, sound):
    """Validate client actions before using existing local services."""
    if not isinstance(action, dict):
        raise ValueError("页面操作无效，请刷新后重试。")
    kind = action.get("kind")
    artifacts = root / "artifacts"
    draft = st.session_state.simple_draft
    valid_ids = plan.track_by_id()
    settings = active_settings(root)
    key = settings.api_key

    def select_ids(raw):
        if not isinstance(raw, list) or len(raw) > len(plan.tracks) or any(not isinstance(tid, str) or tid not in valid_ids for tid in raw):
            raise ValueError("选择包含已失效的歌曲，请刷新曲库。")
        return raw

    def search(query):
        if key:
            check_ai_budget()
        intent = translate_request(query, api_key=key, consent=True, api_url=settings.api_url, model=settings.model) if key else parse_search(query, artists=[p.artist for p in profiles.values()])
        hits = search_library(plan.tracks, query, lyrics_root=Path(plan.source_root),
                              fallback_sources=platform_lyrics(cached_platform(plan.tracks, artifacts), artifacts),
                              profiles=profiles, intent=intent)
        st.session_state.simple_results = plan.analysis_id, query, hits
        st.session_state.simple_conditions = plan.analysis_id, intent.conditions()
        return [hit.track_id for hit in hits]

    def create(name, ids):
        name = safe_playlist_name(name)
        # Separate same-name playlists instead of silently replacing an older one.
        known = {p['name'] for p in saved_playlists(artifacts, plan)} | {draft.name or "我的歌单"}
        base = name
        index = 2
        while name in known:
            name = f"{base[:55]} ({index})"
            index += 1
        archive_playlist(artifacts, draft)
        new = PlaylistDraft(plan.source_root, plan.analysis_id, name=name)
        apply_selection(new, plan, ids, "replace", "consumer_create")
        save_draft(artifacts, new)
        archive_playlist(artifacts, new)
        st.session_state.simple_draft = new
        return f"已创建「{name}」 · {len(new.items)} 首。"

    if kind == "manage":
        st.session_state.simple_edit_library = not st.session_state.get("simple_edit_library", False)
    elif kind == "all":
        st.session_state.pop("simple_results", None)
        st.session_state.pop("simple_conditions", None)
        st.session_state.consumer_message = ""
    elif kind == "play":
        track = valid_ids.get(action.get("id"))
        if track is None:
            raise ValueError("这首歌曲已不在当前曲库。")
        path = Path(track.source_path)
        if not path.is_file():
            raise ValueError("这首歌暂无本地音频，可通过歌曲旁的 QQ 音乐链接打开。")
        st.session_state.consumer_audio = {"id": track.track_id, "url": _media(str(path), mimetypes.guess_type(str(path))[0] or "audio/mpeg", "consumer.audio")}
        st.session_state.consumer_message = ""
    elif kind in {"add", "remove", "move", "rename"}:
        edit_playlist(draft, plan, action)
        save_draft(artifacts, draft)
        archive_playlist(artifacts, draft)
        st.session_state.consumer_message = "歌单已保存。"
    elif kind == "add_many":
        ids = select_ids(action.get("ids"))
        apply_selection(draft, plan, ids, "add", "consumer_selection")
        save_draft(artifacts, draft)
        archive_playlist(artifacts, draft)
        st.session_state.consumer_message = f"歌单已更新 · {len(draft.items)} 首。"
    elif kind == "create":
        st.session_state.consumer_message = create(str(action.get("name", "")), select_ids(action.get("ids")))
    elif kind == "switch":
        st.session_state.simple_draft = switch_playlist(artifacts, plan, draft, str(action.get("id", "")))
        st.session_state.consumer_message = "已打开本地歌单。"
    elif kind == "query":
        mode, query, name = parse_command(str(action.get("text", "")))
        previous = st.session_state.get("simple_results")
        if mode == "remove":
            if not query:
                raise ValueError("请说明要从歌单移除的歌名。")
            ids = [tid for tid in reconcile(draft, plan)[0] if query.casefold() in profiles[tid].title.casefold()]
            if not ids:
                raise ValueError("歌单里没有找到这个歌名。")
            for tid in ids:
                edit_playlist(draft, plan, {"kind": "remove", "id": tid})
            save_draft(artifacts, draft)
            archive_playlist(artifacts, draft)
            st.session_state.consumer_message = f"已从歌单移除 {len(ids)} 首。"
            return
        ids = search(query) if query else [hit.track_id for hit in previous[2]] if previous else []
        if mode == "create":
            st.session_state.consumer_message = create(name, ids)
        elif mode == "add":
            apply_selection(draft, plan, ids, "add", "consumer_query")
            save_draft(artifacts, draft)
            archive_playlist(artifacts, draft)
            st.session_state.consumer_message = f"歌单已更新 · {len(draft.items)} 首。"
        else:
            conditions = st.session_state.get("simple_conditions")
            st.session_state.consumer_message = "理解为：" + " · ".join(conditions[1]) if conditions and conditions[1] else f"找到 {len(ids)} 首收藏。"
    elif kind == "share":
        zodiac = build_zodiac(sound, plan.tracks)
        card = make_zodiac_share_card(zodiac, sound, plan.tracks)
        st.session_state.consumer_share = "data:image/png;base64," + base64.b64encode(card).decode()
        st.session_state.consumer_message = "分享卡已生成，可在星座下方下载。"
    elif kind == "export":
        ids, _ = reconcile(draft, plan)
        if not ids:
            raise ValueError("先把喜欢的歌加入歌单，再导出。")
        name = safe_playlist_name(draft.name or "我的歌单")
        writer = portable_playlist_bytes if st.session_state.get("simple_demo_mode") else playlist_bytes
        encoded = base64.b64encode(writer([valid_ids[tid] for tid in ids])).decode()
        st.session_state.consumer_download = {"name": name + ".m3u8", "url": "data:audio/x-mpegurl;base64," + encoded}
        st.session_state.consumer_message = "已导出本地播放清单。"
    else:
        raise ValueError("未知的页面操作。")


def render_workspace(root, plan, profiles, draft, sound):
    ready = bool(active_settings(root).api_key)
    audio = st.session_state.get("consumer_audio")
    if audio:
        track = plan.track_by_id().get(audio.get("id"))
        if track and Path(track.source_path).is_file():
            # Streamlit clears media references at the start of every rerun.
            # Re-register the current song so playlist edits do not orphan it.
            audio = {"id": track.track_id, "url": _media(track.source_path, mimetypes.guess_type(track.source_path)[0] or "audio/mpeg", "consumer.audio")}
        else:
            audio = None
            st.session_state.pop("consumer_audio", None)
    value = payload(plan, profiles, draft, sound, root / "artifacts", results=st.session_state.get("simple_results"),
                    message=st.session_state.get("consumer_message", ""), ai_ready=ready,
                    audio=audio, share=st.session_state.get("consumer_share"))
    value["demoMode"] = bool(st.session_state.get("simple_demo_mode"))
    value["personalMode"] = bool(st.session_state.get("personal_active"))
    value["download"] = st.session_state.pop("consumer_download", None)
    # Even a no-op action must acknowledge completion to release the frontend.
    value["revision"] = st.session_state.get("consumer_last_token")
    result = _component()(data=value, key="consumer_workspace", on_action_change=lambda: None, height="content")
    action = result.action
    if action:
        token = action.get("token") if isinstance(action, dict) else None
        if token and token == st.session_state.get("consumer_last_token"):
            return
        st.session_state.consumer_last_token = token
        try:
            dispatch(action, plan, profiles, root, sound)
        except (ValueError, IntentAssistantError, OSError, TypeError, KeyError) as exc:
            st.session_state.consumer_message = str(exc) if isinstance(exc, (ValueError, IntentAssistantError)) else "操作未完成，请检查曲库文件和保存目录后重试。"
        st.rerun()
