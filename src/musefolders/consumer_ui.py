"""Single-page music workspace using Streamlit's bidirectional component API."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from copy import deepcopy
from pathlib import Path

import streamlit as st
from streamlit import runtime

from .consumer_workspace import (payload, parse_command, edit_playlist, archive_playlist,
                                 switch_playlist, saved_playlists)
from .playlist_draft import (PlaylistDraft, apply_selection, save_draft, reconcile, set_single,
                             add_group, remove_entry, move_entry, draft_path, delete_song, move_song)
from .playlist_filters import playlist_bytes, safe_playlist_name
from .playlist_export import export_music_zip
from .library_search import parse_search, search_library, SearchHit
from .intent_assistant import translate_request, IntentAssistantError
from .model_settings import active_settings
from .demo_mode import check_ai_budget, portable_playlist_bytes
from .qqmusic_catalog import cached_platform, platform_lyrics
from .astrology import build_zodiac, make_zodiac_share_card

FRONTEND = Path(__file__).parent / "consumer_frontend"
SEARCH_RESULT_LIMIT = 15


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


def _zip_signature(draft, plan):
    import hashlib
    selected, missing = reconcile(draft, plan)
    content = (plan.source_root, plan.analysis_id, draft.name, selected,
               [item.content_id for item in missing], draft.excluded)
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def dispatch(action, plan, profiles, root, sound):
    """Validate client actions before using existing local services."""
    if not isinstance(action, dict):
        raise ValueError("页面操作无效，请刷新后重试。")
    kind = action.get("kind")
    artifacts = root / "artifacts"
    draft = deepcopy(st.session_state.simple_draft)
    valid_ids = plan.track_by_id()
    settings = active_settings(root)
    key = settings.api_key
    added = False

    def persist(candidate=None):
        candidate = draft if candidate is None else candidate
        previous = st.session_state.simple_draft
        existing = draft_path(artifacts, plan.source_root).is_file()
        try:
            save_draft(artifacts, candidate)
            archive_playlist(artifacts, candidate)
        except OSError:
            if existing:
                save_draft(artifacts, previous)
            else:
                draft_path(artifacts, plan.source_root).unlink(missing_ok=True)
            raise
        st.session_state.simple_draft = candidate

    def search_source(query):
        conditions = st.session_state.get("simple_conditions")
        return {"kind": "search", "key": query, "label": query[:100] or "搜索结果",
                "description": " · ".join(conditions[1]) if conditions else "搜索结果快照",
                "criteria": {"query": query}}

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
        total = len(hits)
        if key:
            hits = hits[:SEARCH_RESULT_LIMIT]
        st.session_state.simple_results = plan.analysis_id, query, hits, total
        st.session_state.simple_conditions = plan.analysis_id, intent.conditions()
        return [hit.track_id for hit in hits]

    def create(name, ids, source=None):
        name = safe_playlist_name(name)
        # Separate same-name playlists instead of silently replacing an older one.
        known = {p['name'] for p in saved_playlists(artifacts, plan)} | {draft.name or "我的预备歌单"}
        base = name
        index = 2
        while name in known:
            name = f"{base[:55]} ({index})"
            index += 1
        archive_playlist(artifacts, draft)
        new = PlaylistDraft(plan.source_root, plan.analysis_id, name=name)
        if ids:
            add_group(new, plan, ids, source or {"kind": "selection", "label": name,
                      "description": "选中歌曲快照"})
        persist(new)
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
        before = len(draft.entries)
        edit_playlist(draft, plan, action)
        added = kind == "add" and len(draft.entries) > before
        persist()
        st.session_state.consumer_message = "预备歌单已保存。"
    elif kind == "set_single":
        active_before = {item.content_id for item in draft.items if item.content_id not in draft.excluded}
        set_single(draft, plan, action.get("id"), action.get("selected"))
        added = any(item.content_id not in active_before and item.content_id not in draft.excluded for item in draft.items)
        persist()
        st.session_state.consumer_message = "已单独加入预备歌单。" if added else (
            "已单独加入，无需重复添加。" if action.get("selected") else "已移除单曲来源，所属板块保持不变。")
    elif kind in {"add_many", "add_group"}:
        ids = select_ids(action.get("ids"))
        active_before = {item.content_id for item in draft.items if item.content_id not in draft.excluded}
        add_group(draft, plan, ids, action.get("source") or {
            "kind": "selection", "label": "选中歌曲", "description": "选中歌曲快照"})
        added = any(item.content_id not in active_before and item.content_id not in draft.excluded for item in draft.items)
        persist()
        count = sum(item.content_id not in draft.excluded for item in draft.items)
        st.session_state.consumer_message = f"已保存 · 共 {count} 首，已去重。" if added else "歌曲已在预备歌单中，已更新加入来源。"
    elif kind == "clear_playlist":
        if any(item.content_id not in draft.excluded for item in draft.items):
            previous = deepcopy(st.session_state.simple_draft)
            draft.excluded = list(dict.fromkeys([*draft.excluded, *(item.content_id for item in draft.items)]))
            persist()
            st.session_state.consumer_delete_undo = (previous, draft.to_dict(), time.time() + 20, "clear")
            st.session_state.consumer_message = "已清空当前预备歌单，可在 20 秒内撤销。"
        else:
            st.session_state.consumer_message = "当前预备歌单已经为空。"
    elif kind == "delete_song":
        previous = deepcopy(st.session_state.simple_draft)
        delete_song(draft, str(action.get("content", "")))
        persist()
        st.session_state.consumer_delete_undo = (previous, draft.to_dict(), time.time() + 20)
        st.session_state.consumer_message = "已从预备歌单删除此曲，可在 20 秒内撤销。"
    elif kind == "undo_delete":
        undo = st.session_state.get("consumer_delete_undo")
        if not undo or time.time() > undo[2] or draft.to_dict() != undo[1]:
            raise ValueError("撤销已过期或歌单已变更。")
        persist(deepcopy(undo[0]))
        st.session_state.pop("consumer_delete_undo", None)
        st.session_state.consumer_message = "已恢复歌曲、顺序及来源。"
    elif kind == "move_song":
        move_song(draft, str(action.get("content", "")), action.get("offset"))
        persist()
        st.session_state.consumer_message = "歌曲顺序已保存。"
    elif kind == "remove_entry":
        remove_entry(draft, str(action.get("id", "")))
        persist()
        st.session_state.consumer_message = "已移除此条来源，其他板块和单曲保留。"
    elif kind == "move_entry":
        move_entry(draft, str(action.get("id", "")), action.get("offset"))
        persist()
        st.session_state.consumer_message = "预备歌单顺序已保存。"
    elif kind == "create":
        ids = select_ids(action.get("ids"))
        st.session_state.consumer_message = create(str(action.get("name", "")), ids, action.get("source"))
        added = bool(ids)
    elif kind == "switch":
        st.session_state.simple_draft = switch_playlist(artifacts, plan, draft, str(action.get("id", "")))
        st.session_state.consumer_message = "已打开预备歌单。"
    elif kind == "query":
        mode, query, name = parse_command(str(action.get("text", "")))
        previous = st.session_state.get("simple_results")
        if mode == "remove":
            if not query:
                raise ValueError("请说明要从歌单移除的歌名。")
            ids = [tid for tid in reconcile(draft, plan)[0] if query.casefold() in profiles[tid].title.casefold()
                   and (valid_ids[tid].source_sha256 or tid) not in draft.excluded]
            if not ids:
                raise ValueError("预备歌单中没有找到这首歌。")
            for tid in ids:
                edit_playlist(draft, plan, {"kind": "remove", "id": tid})
            persist()
            st.session_state.consumer_message = f"已从预备歌单删除 {len(ids)} 首歌曲。"
        else:
            ids = search(query) if query else [hit.track_id for hit in previous[2]] if previous else []
            source = search_source(query or (previous[1] if previous else ""))
            if mode == "create":
                st.session_state.consumer_message = create(name, ids, source)
                added = bool(ids)
            elif mode == "add":
                active_before = {item.content_id for item in draft.items if item.content_id not in draft.excluded}
                add_group(draft, plan, ids, source)
                added = any(item.content_id not in active_before and item.content_id not in draft.excluded for item in draft.items)
                persist()
                st.session_state.consumer_message = "搜索板块已加入预备歌单。" if added else "这个搜索板块已经加入。"
            else:
                conditions = st.session_state.get("simple_conditions")
                summary = "理解为：" + " · ".join(conditions[1]) if conditions and conditions[1] else f"找到 {len(ids)} 首收藏。"
                total = st.session_state.simple_results[3] if query else (previous[3] if previous and len(previous) > 3 else len(ids))
                if total > len(ids):
                    summary += f" 共匹配 {total} 首，优先选出前 {len(ids)} 首。"
                st.session_state.consumer_message = summary
    elif kind == "share":
        zodiac = build_zodiac(sound, plan.tracks)
        try:
            card = make_zodiac_share_card(zodiac, sound, plan.tracks)
        except RuntimeError:
            st.session_state.consumer_message = "星座卡生成失败：服务端图像或中文字体依赖不可用，请联系维护者。"
            return {"success": False, "added": False, "kind": kind, "token": action.get("token")}
        st.session_state.consumer_share = "data:image/png;base64," + base64.b64encode(card).decode()
        st.session_state.consumer_message = "分享卡已生成，可在星座下方下载。"
    elif kind == "export_zip":
        ids, missing = reconcile(draft, plan)
        tracks = [valid_ids[tid] for tid in ids
                  if (valid_ids[tid].source_sha256 or tid) not in draft.excluded]
        missing = [item.title for item in missing if item.content_id not in draft.excluded]
        package = export_music_zip(tracks, draft.name or "我的预备歌单", root / "exports",
                                   missing_titles=missing)
        previous = st.session_state.get("consumer_zip_export")
        st.session_state.consumer_zip_export = {
            "path": str(package.path), "name": package.name, "count": package.count,
            "size": package.path.stat().st_size, "token": action.get("token"),
            "signature": _zip_signature(draft, plan),
        }
        if previous:
            old = Path(previous["path"])
            if old.parent.resolve() == (root / "exports").resolve() and old.name.startswith("music-"):
                old.unlink(missing_ok=True)
        omitted = f"，{len(package.skipped)} 首未导出，原因见包内说明" if package.skipped else ""
        fallback = f"，{len(package.metadata_fallbacks)} 首歌名或歌手资料不完整，已使用替代名称" if package.metadata_fallbacks else ""
        st.session_state.consumer_message = f"音乐包已生成：{package.count} 首 MP3{omitted}{fallback}。可点击歌单内的下载链接保存。"
    elif kind == "export":
        ids, _ = reconcile(draft, plan)
        name = safe_playlist_name(draft.name or "我的预备歌单")
        ids = [tid for tid in ids if (valid_ids[tid].source_sha256 or tid) not in draft.excluded]
        if not ids:
            raise ValueError("先把喜欢的歌加入预备歌单，再导出。")
        writer = portable_playlist_bytes if st.session_state.get("simple_demo_mode") else playlist_bytes
        encoded = base64.b64encode(writer([valid_ids[tid] for tid in ids])).decode()
        st.session_state.consumer_download = {"name": name + ".m3u8", "url": "data:audio/x-mpegurl;base64," + encoded}
        st.session_state.consumer_message = "已导出本地播放清单。"
    else:
        raise ValueError("未知的页面操作。")
    result = {"token": action.get("token"), "success": True, "added": added, "kind": kind}
    if kind == "query":
        result["selectionSaved"] = mode in {"add", "create"}
    return result


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
    package = st.session_state.get("consumer_zip_export")
    value["zipDownload"] = None
    if package and package["signature"] == _zip_signature(draft, plan) and Path(package["path"]).is_file() and runtime.exists():
        url = runtime.get_instance().media_file_mgr.add(
            package["path"], "application/zip", "consumer.zip",
            file_name=package["name"], is_for_static_download=True,
        )
        value["zipDownload"] = {key: package[key] for key in ("name", "count", "size", "token")}
        value["zipDownload"]["url"] = url
    conditions = st.session_state.get("simple_conditions")
    value["conditions"] = conditions[1] if conditions else []
    # Even a no-op action must acknowledge completion to release the frontend.
    value["revision"] = st.session_state.get("consumer_last_token")
    value["actionResult"] = st.session_state.get("consumer_action_result")
    value["zipMessage"] = value["message"] if (value["actionResult"] or {}).get("kind") == "export_zip" else ""
    undo = st.session_state.get("consumer_delete_undo")
    value["undoUntil"] = undo[2] if undo and time.time() < undo[2] and draft.to_dict() == undo[1] else None
    value["undoLabel"] = "撤销清空" if undo and len(undo) > 3 and undo[3] == "clear" else "撤销删除"
    result = _component()(data=value, key="consumer_workspace", on_action_change=lambda: None, height="content")
    action = result.action
    if action:
        token = action.get("token") if isinstance(action, dict) else None
        if token and token == st.session_state.get("consumer_last_token"):
            return
        st.session_state.consumer_last_token = token
        try:
            st.session_state.consumer_action_result = dispatch(action, plan, profiles, root, sound)
        except (ValueError, IntentAssistantError, OSError, TypeError, KeyError) as exc:
            st.session_state.consumer_message = str(exc) if isinstance(exc, (ValueError, IntentAssistantError)) else "操作未完成，请检查曲库文件和保存目录后重试。"
            st.session_state.consumer_action_result = {"token": token, "success": False,
                                                      "added": False, "kind": action.get("kind")}
        st.rerun()
