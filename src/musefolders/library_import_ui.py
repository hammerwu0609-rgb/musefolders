"""First-use import flow shared by the desktop and visitor demo."""
from pathlib import Path
import streamlit as st

from .audio import SUPPORTED_EXTENSIONS
from .library_import import (MusicImportError, import_cloud_bundle, import_files,
                             import_zip, publish_import)
from .models import CollectionPlan


WELCOME_STYLE = """<style>
.music-welcome{container-type:inline-size;position:relative;isolation:isolate;overflow:hidden;padding:56px 0 22px;border-bottom:1px solid #2c3931;margin-bottom:26px;}
.music-welcome .welcome-record{position:absolute;z-index:-1;top:-88px;right:-12cqi;width:min(32cqi,400px);height:auto;color:#65ba84;opacity:.5;pointer-events:none;}
.music-welcome .eyebrow{color:#31c27c;font-size:12px;letter-spacing:3px;}
.music-welcome h1{font-size:clamp(16px,3.6vw,52px);font-size:clamp(16px,6.4cqi,52px);line-height:1.25;max-width:none;margin:14px 0;white-space:nowrap;}
.music-welcome p{color:#aebfb3;max-width:580px;line-height:1.8;}
.music-step{border-left:2px solid #31c27c;padding:8px 0 8px 18px;margin:18px 0;color:#eef3ef;}
.music-step small{display:block;color:#aebfb3;margin-top:5px;}
@media(max-width:680px){.music-welcome{padding-top:28px;}}
@media(max-width:900px){.music-welcome .welcome-record{width:180px;top:-130px;right:-70px;opacity:.3;}}
</style>"""

WELCOME_RECORD = (
    '<svg class="welcome-record" viewBox="0 0 400 400" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">'
    '<g stroke="currentColor" stroke-width="1" vector-effect="non-scaling-stroke">'
    '<circle cx="200" cy="200" r="190" stroke-width="1.5"/>'
    '<g opacity=".55"><circle cx="200" cy="200" r="178"/>'
    '<circle cx="200" cy="200" r="170"/><circle cx="200" cy="200" r="153"/>'
    '<circle cx="200" cy="200" r="145"/><circle cx="200" cy="200" r="128"/>'
    '<circle cx="200" cy="200" r="120"/></g>'
    '<circle cx="200" cy="200" r="58"/><circle cx="200" cy="200" r="51" opacity=".55"/>'
    '<circle cx="200" cy="200" r="5"/></g></svg>'
)


def activate_import(result, root: Path):
    publish_import(result, root)
    from .personal_ui import invalidate
    invalidate()
    for key in ("simple_card", "simple_draft", "simple_playing", "simple_playlist_name",
                "personal_reference_plan", "personal_import_message"):
        st.session_state.pop(key, None)
    st.session_state.simple_plan = result.plan
    st.session_state.pop("consumer_zip_export", None)
    # The local folder input may already be rendered in this run. Apply its
    # value before creating widgets on the next run, as Streamlit requires.
    st.session_state.simple_pending_source = result.plan.source_root
    st.session_state.simple_music_import = result.report
    st.session_state.personal_active = False
    st.session_state.simple_edit_library = False
    st.rerun()


def _run_import(action, root):
    with st.status("正在导入音乐…", expanded=True) as status:
        progress = st.progress(0, text="正在准备文件…")
        def update(done, total, text):
            progress.progress(min(done / max(total, 1), 1.0),
                              text=f"{text} · {done}/{total}")
        try:
            result = action(update)
            progress.progress(1.0, text=f"已读取 {len(result.plan.tracks)} 首歌曲")
            status.update(label="音乐导入完成", state="complete", expanded=False)
            activate_import(result, root)
        except MusicImportError as exc:
            status.update(label="导入未完成", state="error")
            st.error(str(exc))


def _cloud_package(root):
    bundle = Path(st.session_state.simple_demo_bundle)
    st.subheader("从体验音乐包开始")
    st.write("音乐和资料已准备在云端。点击导入后，它们才会出现在你的音乐库里。")
    st.caption("读取音频、歌词、艺人地区与平台资料，校验歌曲后复用已有听感分析和 AI 标签。")
    if st.button("导入体验音乐包", key="music_import_cloud", type="primary",
                 width="stretch"):
        _run_import(lambda progress: import_cloud_bundle(bundle, root, progress=progress), root)
    package = bundle / "experience.zip"
    if package.is_file():
        with st.expander("也可以下载音乐包，在本地体验"):
            st.caption(f"完整音乐包约 {package.stat().st_size / 1024 / 1024:.0f} MB；在线体验无需下载。")
            st.download_button("下载完整体验音乐包", data=lambda: package.open("rb"),
                               file_name="曲境-体验音乐包.zip", mime="application/zip",
                               key="music_download_package", on_click="ignore")


def _uploads(root):
    uploads = st.file_uploader("选择音乐文件或音乐包", accept_multiple_files=True,
        type=[e.lstrip(".") for e in sorted(SUPPORTED_EXTENSIONS)] + ["lrc", "txt", "zip"],
        max_upload_size=512, key="music_upload")
    st.caption("支持音频、同名 LRC／TXT 歌词和 ZIP 音乐包，总计最大 512 MB。音频与歌词可多选；ZIP 每次选择一个。")
    archives = [upload for upload in uploads if Path(upload.name).suffix.lower() == ".zip"]
    mixed = bool(archives) and len(uploads) != 1
    if mixed:
        st.warning("请只选择一个 ZIP 音乐包，或仅选择音频与歌词文件。")
    reanalyze = False
    if len(archives) == 1 and not mixed:
        reanalyze = st.checkbox("重新分析包内音频", key="music_reanalyze",
                                help="重新测量节奏、明亮度等听感特征，整库可能需要几分钟。已有歌词标签和地区资料继续保留。")
    if st.session_state.get("simple_demo_mode"):
        st.caption("网页版文件保存在本次访问的临时工作区；结束会话或服务重启后可能丢失。")
    else:
        st.caption("文件和分析结果保存在本机，原始文件不会被修改。")
    if st.button("导入音乐", key="music_import_upload", type="primary", disabled=not uploads or mixed):
        if archives:
            _run_import(lambda progress: import_zip(archives[0], root, reanalyze=reanalyze,
                                                    progress=progress), root)
        else:
            _run_import(lambda progress: import_files(uploads, root, progress=progress), root)


def _qq_initial(root):
    from .personal_ui import qq_login
    from .web_management import import_rows
    from .personal_library import playlist_id
    from .qqmusic_web import WebQQError
    plan = CollectionPlan("empty", str(root), "quant", [], [])
    st.caption("导入 QQ 收藏资料；资料本身不包含音频。需要站内试听时，可先导入体验包或自己的音乐文件。")
    url = st.text_input("QQ 音乐歌单链接 / ID", key="empty_qq_url")
    if st.button("导入 QQ 歌单", key="empty_qq_import"):
        try:
            import_rows(root, plan, playlist_id(url))
        except (ValueError, WebQQError) as exc:
            st.error(str(exc))
    qq_login()
    if st.session_state.get("web_qq_credential") and st.button("导入我喜欢的歌曲", key="empty_qq_liked"):
        try:
            import_rows(root, plan)
        except (ValueError, WebQQError) as exc:
            st.error(str(exc))


def render_import(root, initial, folder_controls):
    cloud = st.session_state.get("simple_demo_mode", False)
    if initial:
        st.markdown(WELCOME_STYLE, unsafe_allow_html=True)
        st.markdown('<section class="music-welcome">' + WELCOME_RECORD +
                    '<div class="eyebrow">MUSEFOLDERS · 曲境</div>'
                    '<h1>让模糊的曲库，变成清晰的曲境</h1>'
                    '<p>你的音乐库还是空的。亲手导入音乐，再从地区、听感和歌词故事中，找到此刻想听的歌。</p></section>',
                    unsafe_allow_html=True)
        intro, controls = st.columns([.85, 1.15], gap="large")
        with intro:
            st.markdown('<div class="music-step">01 · 导入音乐<small>体验云端音乐包，或带来自己的收藏。</small></div>'
                        '<div class="music-step">02 · 读取与解析<small>音频、歌词与歌曲资料，在这里汇合。</small></div>'
                        '<div class="music-step">03 · 开始探索<small>音乐星球、听感空间、主题河流与歌单。</small></div>',
                        unsafe_allow_html=True)
        with controls:
            _source_controls(root, cloud, folder_controls)
    else:
        _source_controls(root, cloud, folder_controls)


def _source_controls(root, cloud, folder_controls):
    if cloud:
        _cloud_package(root)
        with st.expander("导入自己的音乐文件"):
            _uploads(root)
        if st.session_state.get("simple_plan") is None:
            with st.expander("从 QQ 音乐导入收藏"):
                _qq_initial(root)
    else:
        folder, upload = st.tabs(["本地文件夹", "音乐文件 / 音乐包"])
        with folder:
            folder_controls(root)
        with upload:
            _uploads(root)


def render_import_receipt(plan, profiles):
    report = st.session_state.get("simple_music_import")
    if not report:
        return
    cached = report.get("cached", 0)
    measured = report.get("measured", 0)
    description = f"已导入 {len(plan.tracks)} 首歌曲"
    if cached:
        description += f" · 复用 {cached} 首已有听感分析"
    if measured:
        description += f" · 新解析 {measured} 首音频"
    st.success(description)
    with st.expander("查看本次导入结果"):
        from .artist_regions import read_regions, region_for_artist
        from .qqmusic_catalog import cached_platform
        from .ai_lyrics import lyric_labels
        from .model_settings import active_settings
        artifacts = st.session_state.simple_artifact_dir
        settings = active_settings(artifacts.parent)
        regions = read_regions(artifacts)
        covered = sum(bool(region_for_artist(regions, p.artist).get("country"))
                      for p in profiles.values())
        from .qqmusic_catalog import platform_lyrics
        from .user_annotations import confirmed_instrumental_ids
        platform = cached_platform(plan.tracks, artifacts)
        instrumental = confirmed_instrumental_ids(plan.tracks, artifacts)
        fallback = {tid: path for tid, path in platform_lyrics(platform, artifacts).items()
                    if tid not in instrumental}
        ai = lyric_labels(plan.tracks, Path(plan.source_root), artifacts,
                          fallback_sources=fallback, api_url=settings.api_url, model=settings.model)
        st.write(f"可用歌词 {sum(p.lyrics_status == 'valid' for p in profiles.values())} 首；"
                 f"读取 LRC 文件 {report.get('lyrics_files', 0)} 份。")
        st.write(f"AI 歌词标签 {len(ai)} 首 · 地区资料 {covered} 首 · 平台匹配 {len(platform)} 首。")
        if report.get("failed") or report.get("unsupported"):
            st.warning(f"{report.get('failed', 0)} 个文件分析失败，{report.get('unsupported', 0)} 个受保护文件跳过。")
        st.caption("地区和主题来自已有资料及实际歌词；未收录的信息保留待补充。")
    if st.button("收起导入结果", key="music_dismiss_receipt"):
        st.session_state.pop("simple_music_import", None)
        st.rerun()
