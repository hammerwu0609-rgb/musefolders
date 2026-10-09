"""Consumer workspace: search a collection and share its portrait."""
from __future__ import annotations
import os
from pathlib import Path
import streamlit as st
from .tag_catalog import build_track_profiles, save_profile_catalog
from .ai_lyrics import LyricAnalysisError, analyze_lyrics, lyric_labels
from .qqmusic_catalog import (QQMusicConnectionError, cached_platform, platform_lyrics,
                             connection_status, enrich_library)
from .user_annotations import confirmed_instrumental_ids, theme_assignments, verified_genre_assignments
from .models import CollectionPlan
from .playlist_draft import load_draft, PlaylistDraft
from .service import load_plan
from .sonic_map import MapPoint, SonicMap
from .artist_regions import enrich_regions
from .qqmusic_login import start_login, login_result
from .model_settings import (ModelSettings, ModelSettingsError, active_settings, validate,
                             save_settings, delete_settings, config_path, test_connection)

STYLE = """<style>
.stApp{background:#0e1110;color:#eef3ef;color-scheme:dark;}
.stMainBlockContainer{width:100%;max-width:1760px;padding:0 clamp(16px,2vw,32px) 2rem;}
header[data-testid=stHeader]{height:0;background:transparent;}
[data-testid=stToolbar]{display:none;}
.stButton button,.stDownloadButton button{border-radius:6px;min-height:40px;}
h1,h2,h3{font-family:'Microsoft YaHei','PingFang SC',sans-serif!important;}
@media(max-width:680px){.stMainBlockContainer{padding:0 14px 1rem;}}
</style>"""

def portrait_map(plan: CollectionPlan) -> SonicMap:
    """Stable basic map from measured tempo and brightness, with no audio reanalysis."""
    points = tuple(MapPoint(t.track_id, max(0., min(100., (t.acoustic.tempo_bpm-60)/120*100)),
                            max(0., min(100., t.standard.brightness)))
                   for t in plan.tracks if t.standard is not None)
    return SonicMap(mode="basic-acoustic", projection="semantic-only", points=points, vectors={})


def _import(root, initial):
    from .library_import_ui import render_import
    render_import(root, initial, _folder_import)


def _folder_import(root):
    if st.button("选择文件夹", key="simple_choose_folder"):
        window = None
        try:
            import tkinter as tk
            from tkinter import filedialog
            window = tk.Tk()
            window.withdraw()
            chosen = filedialog.askdirectory(title="选择你的音乐文件夹", parent=window)
            if chosen:
                st.session_state.simple_source = chosen
        except Exception:
            st.warning("文件夹选择窗口未能打开，也可以在下面填写完整路径。")
        finally:
            if window is not None:
                window.destroy()
    source = st.text_input("音乐文件夹", key="simple_source", placeholder="填写保存 MP3、FLAC 等音乐的文件夹位置")
    st.caption("歌曲与歌词在本机分析。原始文件不会被修改。")
    if st.button("读取并分析文件夹", type="primary", key="simple_import"):
        if not source.strip():
            st.warning("请先填写音乐文件夹的位置。")
            return
        progress = st.progress(0, text="正在准备你的音乐收藏…")
        try:
            from .library_import import import_folder, MusicImportError
            from .library_import_ui import activate_import
            result = import_folder(Path(source.strip()), root,
                progress=lambda done,total,name: progress.progress(min(done/max(total,1),1.),
                    text=f"正在认识你的音乐 · {done}/{total}"))
            activate_import(result, root)
        except MusicImportError as exc:
            st.error(str(exc))
        except OSError:
            st.error("无法读取这个文件夹。请检查路径和访问权限，并确保它与分析保存目录分开。")
        except Exception:
            st.error("分析未能完成，请检查音频格式后重试；已完成的分析会复用。")

def _catalog(plan):
    artifact_dir = st.session_state.get("simple_artifact_dir", Path("artifacts"))
    settings = active_settings(artifact_dir.parent)
    lyric_files = sorted((path for path in Path(plan.source_root).rglob("*")
                          if path.is_file() and path.suffix.casefold() in {".lrc", ".txt"}),
                         key=str)
    annotations = artifact_dir / "user_annotations.json"
    ai_cache = artifact_dir / "ai_lyrics_tags.json"
    platform_cache = artifact_dir / "platform_catalog.json"
    platform = cached_platform(plan.tracks, artifact_dir)
    fallback = platform_lyrics(platform, artifact_dir)
    signature = (settings.api_url, settings.model, plan.analysis_id, tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns)
                                         for path in lyric_files),
                 (annotations.stat().st_size, annotations.stat().st_mtime_ns) if annotations.is_file() else None,
                 (ai_cache.stat().st_size, ai_cache.stat().st_mtime_ns) if ai_cache.is_file() else None,
                 (platform_cache.stat().st_size, platform_cache.stat().st_mtime_ns) if platform_cache.is_file() else None,
                 tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(set(fallback.values()))))
    saved = st.session_state.get("simple_profiles")
    if saved and saved[0] == signature:
        return saved[1]
    st.session_state.pop("simple_results", None)
    st.session_state.pop("simple_conditions", None)
    try:
        manual = theme_assignments(plan.tracks, artifact_dir)
        genres = verified_genre_assignments(plan.tracks, artifact_dir)
        instrumental = confirmed_instrumental_ids(plan.tracks, artifact_dir)
    except (OSError, ValueError):
        manual, genres, instrumental = {}, {}, frozenset()
        st.warning("已保存的人工标签无法读取，当前仅使用音频、歌词与原始元数据。")
    fallback = {track_id: path for track_id, path in fallback.items() if track_id not in instrumental}
    profiles = build_track_profiles(plan.tracks, lyrics_root=Path(plan.source_root),
                                    manual_themes=manual, verified_genres=genres,
                                    ai_themes=lyric_labels(plan.tracks, Path(plan.source_root), artifact_dir,
                                                           fallback_sources=fallback, api_url=settings.api_url, model=settings.model),
                                    platform_metadata=platform, fallback_sources=fallback,
                                    instrumental_ids=instrumental)
    try:
        save_profile_catalog(profiles, artifact_dir, analysis_id=plan.analysis_id)
    except OSError:
        st.warning("当前可继续检索，但逐曲标签档案未能写入本地。")
    st.session_state.simple_profiles = signature, profiles
    st.session_state.pop("simple_summary", None)
    return profiles


def _management(root, plan):
    if st.session_state.get("simple_demo_mode"):
        from .web_management import render_management
        render_management(root, plan)
        return
    source, details, ai = st.tabs(["音乐来源", "歌曲资料", "AI 设置"], key="simple_management_tab", on_change="rerun")
    with source:
        _import(root,False)
    with details:
        _metadata_controls(root, plan)
    with ai:
        _ai_controls(root, plan)


def _qq_login_controls(root):
    job = st.session_state.get("simple_qq_login_job")
    running = job is not None and job.process.poll() is None
    st.caption("点击后打开 QQ 音乐官网登录窗口，选择 QQ 或微信登录。完成后自动连接并在本机加密保存；切换账号也使用此入口。")
    if st.button("登录 / 切换 QQ 音乐账号", key="simple_qq_login", disabled=running):
        try:
            st.session_state.simple_qq_login_job = start_login(root)
            st.session_state.pop("simple_qq_login_message", None)
            st.session_state.pop("simple_qq_status_message", None)
            st.rerun()
        except QQMusicConnectionError as exc:
            st.error(str(exc))
    @st.fragment(run_every=2 if st.session_state.get("simple_qq_login_job") else None)
    def progress():
        job = st.session_state.get("simple_qq_login_job")
        if job:
            result = login_result(job)
            if result is None:
                st.info("等待官网登录…请在新打开的浏览器窗口完成登录。关闭该窗口可取消，最长等待 3 分钟。")
                return
            st.session_state.pop("simple_qq_login_job", None)
            if result["ok"]:
                status = result["status"]
                st.session_state.simple_qq_status_message = f"已连接账号 {status['account_hint']} · {status['playlist_count']} 个歌单"
                st.session_state.simple_qq_login_message = (True, "登录完成，" + st.session_state.simple_qq_status_message)
            else:
                st.session_state.simple_qq_login_message = (False, result.get("message", "登录未完成，请重试。"))
            st.rerun()
        message = st.session_state.get("simple_qq_login_message")
        if message:
            (st.success if message[0] else st.warning)(message[1])
    progress()


def _metadata_controls(root, plan):
    st.subheader("QQ 音乐连接")
    _qq_login_controls(root)
    st.divider()
    st.subheader("补充歌曲资料")
    st.caption("复用本机 QQ 音乐登录，自动匹配歌曲并补充元数据、缺失歌词。原始文件不会被修改。")
    status_button, sync_button = st.columns(2)
    if status_button.button("检查 QQ 音乐连接", key="simple_qq_check"):
        try:
            status = connection_status()
            st.session_state.simple_qq_status_message = f"已连接账号 {status['account_hint']} · {status['playlist_count']} 个歌单"
        except (QQMusicConnectionError, OSError) as exc:
            st.error(str(exc))
    if st.session_state.get("simple_qq_status_message"):
        st.caption(st.session_state.simple_qq_status_message)
    if sync_button.button("从 QQ 音乐补充资料", key="simple_qq_sync"):
        progress = st.progress(0, text="正在匹配 QQ 音乐歌曲…")
        try:
            report = enrich_library(plan.tracks, root / "artifacts",
                progress=lambda done,total: progress.progress(done/max(total,1), text=f"正在补充资料 · {done}/{total}"))
            st.session_state.pop("simple_profiles", None)
            lyric_count = sum(profile.lyrics_status == "valid" for profile in _catalog(plan).values())
            st.session_state.simple_qq_message = (
                f"已匹配 {report['matched']}/{report['total']} 首，目前 {lyric_count} 首有可用歌词，"
                f"复用 {report['cached']} 首缓存；未匹配 {report['unmatched']} 首，接口失败 {report['errors']} 首。")
            st.session_state.pop("simple_ai_message", None)
            st.rerun()
        except (QQMusicConnectionError, OSError) as exc:
            st.error(str(exc) + " 已完成的资料会保留，可再次点击继续。")
    if st.session_state.get("simple_qq_message"):
        st.success(st.session_state.simple_qq_message)
    st.divider()
    st.caption("地图按首位署名艺人档案中的关联地区归类，不按歌词语言判断。通过 MusicBrainz 补充并缓存；同名不确定或未收录的艺人保留待补充。")
    if st.button("补充地图地区", key="simple_enrich_regions"):
        progress = st.progress(0, text="正在查询艺人地区…")
        report = enrich_regions([profile.artist for profile in _catalog(plan).values()], root / "artifacts",
                                progress=lambda done,total,name: progress.progress(done/max(total,1),text=f"正在补充地区 · {done}/{total}"))
        st.session_state.simple_region_message = f"地区资料：新增 {report['matched']} 位艺人，复用 {report['cached']} 位；待补充 {report['unknown']} 位，查询失败 {report['errors']} 位。"
        st.rerun()
    if st.session_state.get("simple_region_message"):
        st.success(st.session_state.simple_region_message)


def _ai_controls(root, plan):
    settings = active_settings(root)
    st.subheader("模型连接")
    st.caption("自然语言检索和歌词分析共用此配置。支持兼容 Chat Completions、可返回 JSON 的聊天接口。")
    st.caption("模型配置供产品体验使用，可自行更改。密钥不回显；可选择本机加密保存或仅本次会话使用。")
    if st.session_state.get("simple_model_error"):
        st.warning(st.session_state.simple_model_error)
    st.caption(f"当前：{st.session_state.get('simple_model_origin', '尚未配置')} · {settings.model}")
    st.session_state.setdefault("simple_model_url", settings.api_url)
    st.session_state.setdefault("simple_model_name", settings.model)
    st.text_input("API 地址", key="simple_model_url",
                  help="可填写基础地址，例如 https://api.deepseek.com，或完整的 /chat/completions 地址。")
    st.text_input("模型名称", key="simple_model_name")
    st.text_input("API 密钥", type="password", key="simple_api_key",
                  placeholder="已配置密钥；留空可继续使用" if settings.api_key else "填写服务商提供的 API 密钥",
                  help="填写新密钥可替换旧密钥。已保存的密钥不会显示在输入框中。")
    def candidate():
        return validate(ModelSettings(st.session_state.simple_model_url,
            st.session_state.simple_model_name, st.session_state.simple_api_key.strip() or settings.api_key))

    def apply_config(config, origin):
        st.session_state.simple_model_settings = config
        st.session_state.simple_model_origin = origin
        st.session_state.pop("simple_model_error", None)
        st.session_state.pop("simple_model_test", None)
        st.session_state.simple_model_clear_key = True
        st.session_state.simple_model_message = f"{origin}已启用，检索和歌词分析将使用 {config.model}。"
        st.rerun()

    persist, temporary = st.columns(2)
    if persist.button("保存到本机", key="simple_model_save", type="primary"):
        try:
            config = candidate()
            save_settings(root, config)
            apply_config(config, "本机加密配置")
        except ModelSettingsError as exc:
            st.error(str(exc))
    if temporary.button("仅本次会话使用", key="simple_model_session"):
        try:
            config = candidate()
            if not config.api_key:
                raise ModelSettingsError("请先填写 API 密钥。")
            apply_config(config, "本次会话配置")
        except ModelSettingsError as exc:
            st.error(str(exc))
    st.caption("本机保存使用 Windows 账号加密。关闭网页或重启项目后自动读取；仅本次会话使用不会写入文件。")
    check, remove = st.columns(2)
    if check.button("测试连接", key="simple_model_check"):
        try:
            config = candidate()
            with st.spinner("正在测试模型连接…"):
                test_connection(config)
            st.success(f"测试通过：{config.model} 能返回有效 JSON。请保存或应用配置后使用。")
        except ModelSettingsError as exc:
            st.error(str(exc))
    if remove.button("删除配置", key="simple_model_delete", disabled=not (settings.api_key or config_path(root).exists())):
        try:
            delete_settings(root)
            st.session_state.simple_model_settings = ModelSettings()
            st.session_state.simple_model_origin = "尚未配置"
            st.session_state.simple_model_reset = True
            st.session_state.pop("simple_model_error", None)
            st.session_state.pop("simple_model_test", None)
            st.session_state.simple_model_message = "本机配置和本次会话密钥已清除；当前改用本地检索。环境变量未被修改。"
            st.rerun()
        except ModelSettingsError as exc:
            st.error(str(exc))
    if st.session_state.get("simple_model_message"):
        st.success(st.session_state.simple_model_message)
    st.divider()
    st.subheader("歌词分析")
    st.caption(f"使用已应用的 {settings.model}。点击分析会把有效歌词与歌名发送至该 API；标签缓存在本机，纯音乐及缺失歌词的歌曲会跳过。")
    if st.button("AI 分析歌词", disabled=not bool(settings.api_key), key="simple_analyze_lyrics"):
        progress = st.progress(0, text="正在分析歌词…")
        try:
            instrumental = confirmed_instrumental_ids(plan.tracks, root / "artifacts")
            fallback = {track_id: path for track_id, path in
                platform_lyrics(cached_platform(plan.tracks, root / "artifacts"), root / "artifacts").items()
                if track_id not in instrumental}
            fresh, cached, eligible = analyze_lyrics(
                plan.tracks, Path(plan.source_root), root / "artifacts", api_key=settings.api_key,
                api_url=settings.api_url, model=settings.model, fallback_sources=fallback,
                progress=lambda done,total: progress.progress(done/max(total,1), text=f"正在分析歌词 · {done}/{total}"))
            st.session_state.simple_ai_message = f"歌词分析完成：新分析 {fresh} 首，复用 {cached} 首，共 {eligible} 首有效歌词。"
            st.session_state.pop("simple_profiles", None)
            st.rerun()
        except (LyricAnalysisError, OSError) as exc:
            st.error((str(exc) if isinstance(exc, LyricAnalysisError) else "标签缓存未能写入。") + " 已完成的歌曲会保留，下次可继续。")
    if st.session_state.get("simple_ai_message"):
        st.success(st.session_state.simple_ai_message)


def _dismiss_management():
    st.session_state.simple_edit_library = False


@st.dialog("管理曲境", width="medium", on_dismiss=_dismiss_management)
def _management_dialog(root, plan):
    _management(root, plan)
    st.divider()
    if st.button("返回音乐库", type="primary", key="simple_close_management"):
        _dismiss_management()
        st.rerun()

def render_app(root: Path):
    from .consumer_ui import render_workspace
    st.set_page_config(page_title="曲境 · 我的音乐收藏", page_icon="♪", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(STYLE, unsafe_allow_html=True)
    st.session_state.simple_artifact_dir = root / "artifacts"
    if "simple_pending_source" in st.session_state:
        st.session_state.simple_source = st.session_state.pop("simple_pending_source")
    active_settings(root)
    if st.session_state.pop("simple_model_reset", False):
        st.session_state.simple_model_url = ModelSettings().api_url
        st.session_state.simple_model_name = ModelSettings().model
        st.session_state.simple_api_key = ""
    if st.session_state.pop("simple_model_clear_key", False):
        st.session_state.simple_api_key = ""
    # Hidden Streamlit widgets normally lose their session state. Preserve
    # the session-only credential and source when the management panel closes.
    for key in ("simple_api_key", "simple_source", "simple_model_url", "simple_model_name", "simple_management_tab"):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    if not st.session_state.get("simple_initialized"):
        st.session_state.simple_initialized = True
        saved = root / "artifacts" / "collection_plan.json"
        if saved.is_file():
            try:
                plan = load_plan(saved)
                if plan.tracks and Path(plan.source_root).is_dir():
                    st.session_state.simple_plan = plan
                    st.session_state.simple_source = plan.source_root
            except (OSError, ValueError, KeyError, TypeError):
                st.warning("上次的曲库记录无法读取，请重新导入。")
    plan = st.session_state.get("simple_plan")
    if plan is None:
        _import(root, True)
        return
    if (st.session_state.get("simple_draft_identity") != (plan.analysis_id, plan.source_root) or
            not isinstance(st.session_state.get("simple_draft"), PlaylistDraft)):
        try:
            st.session_state.simple_draft = load_draft(root / "artifacts", plan)
        except (OSError, ValueError, TypeError):
            st.session_state.simple_draft = PlaylistDraft(plan.source_root, plan.analysis_id)
            st.error("上次歌单无法读取，请检查分析目录。")
        st.session_state.simple_draft_identity = plan.analysis_id, plan.source_root
        for key in ("consumer_audio", "consumer_share", "consumer_message", "consumer_download", "consumer_zip_export"):
            st.session_state.pop(key, None)
    profiles = _catalog(plan)
    from .library_import_ui import render_import_receipt
    render_import_receipt(plan, profiles)
    render_workspace(root, plan, profiles, st.session_state.simple_draft, portrait_map(plan))
    if st.session_state.get("simple_edit_library"):
        _management_dialog(root, plan)
