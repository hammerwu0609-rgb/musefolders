from __future__ import annotations

import copy
import base64
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitWidgetAlreadyInstantiatedError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from musefolders.adapters import LocalFolderAdapter
from musefolders.explore_ui import LABELS as EXPLORE_LABELS, _ensure_draft, _save_draft, render_explorer
from musefolders.playlist_draft import apply_selection
from musefolders.metadata import read_cover_data_uri
from musefolders.playlist_filters import (
    MISSING_VALUE, PlaylistFilters, build_playlist_plan, facet_counts, facet_options,
    filter_tracks, playlist_bytes, relaxation_counts, safe_playlist_name,
)
from musefolders.schemes import TAG_LABELS, VALUE_LABELS, compile_scheme, format_tag_value
from musefolders.service import analyze_library, save_instrument_override, save_plan
from musefolders.taxonomy import key_tag_value, reassign_track, rename_folder

LOGGER = logging.getLogger(__name__)


TEXT = {
    "zh": {
        "title": "曲境", "switch": "切换为英文", "tagline": "探索自己的音乐地图，试听、筛选，再决定如何收藏与整理。",
        "workspace": "工作区", "explore_workspace": "音乐探索", "organize_workspace": "档案与文件夹整理",
        "advanced_tools": "高级工具：档案与全库整理", "send_to_draft": "将筛选结果送入当前歌单",
        "source": "音乐来源文件夹", "browse": "浏览文件夹", "records": "分析档案保存位置",
        "scan": "分析此文件夹", "safe": "原始音乐只读；分析和预览不会改动文件。",
        "ready": "请选择音乐来源文件夹，然后开始分析。", "changed": "来源文件夹已更改，请重新分析。",
        "analyzing": "正在分析", "failed": "分析失败。请检查目录、音频格式和访问权限。",
        "analyzed": "已分析曲目", "duration": "曲库时长", "hours": "小时", "skipped": "跳过的受保护文件",
        "catalog": "逐曲档案", "catalog_help": "每行对应一首歌。流派照原始元数据展示，不代表已核实；曲名、歌手和专辑保持文件原文。",
        "cover": "封面", "basic": "基本信息", "base": "基础编码", "secondary": "二级编码",
        "song": "曲名", "artist": "歌手", "album": "专辑", "release": "发行时间", "genre": "原始流派",
        "local_date": "本地文件创建时间", "date_note": "本地文件创建时间仅供参考，不能证明实际下载日期。",
        "unknown": "未提供", "unknown_artist": "未知歌手", "instrument": "主要声源", "instrument_note": "主要声源为本地模型估计；证据不足时标为待确定，并非正式演奏名单。",
        "instrument_edit": "人工修正主要声源", "instrument_save": "保存主要声源", "instrument_manual": "人工修正",
        "tempo": "节奏", "tempo_unit": "拍／分", "loudness": "响度代理", "loudness_unit": "分贝（数字电平）",
        "key": "调性估计", "mode": "调式估计", "key_uncertain": "待确定", "act": "声音活跃度", "bri": "声音明亮度", "points": "分",
        "key_note": "调性由音频片段自动估计，并非乐理鉴定；证据不足的曲目会标为待确定。",
        "inspect": "查看单曲详情", "listen": "试听", "metadata_note": "原始流派仅来自文件元数据，即使有值也未经过核实。",
        "organize": "文件夹整理", "choose_tags": "勾选用于分类的编码标签（最多三个）",
        "tag_help": "歌曲按所选标签的取值归组，文件夹名直接使用这些标签；未选标签仍保留在逐曲档案中。",
        "need_tags": "请至少勾选一个标签。", "candidate": "预计生成", "folders": "个文件夹", "tracks": "首",
        "many": "当前选择会产生很多文件夹，建议减少勾选的标签。", "confirm": "确认这些分类标签",
        "confirmed": "分类已确认。请检查预览，再决定是否复制音乐。", "not_confirmed": "请先确认当前标签组合。",
        "preview": "文件夹预览", "edit": "人工调整", "export": "生成文件夹", "future": "接口扩展",
        "rename": "修改文件夹名", "save_name": "保存名称", "invalid_name": "文件夹名称无效，请修改后重试。",
        "move": "修正单曲归类", "choose_track": "曲目", "target": "目标文件夹", "save_move": "保存归类",
        "output": "输出目录", "operations": "将复制", "operations_tail": "首音乐到新文件夹；原件不动。",
        "preview_ops": "查看前二十条操作", "source_file": "源文件", "destination": "目标文件",
        "agree": "我已检查分类和复制预览，同意创建文件夹与播放清单", "apply": "创建这些文件夹",
        "done": "复制完成", "export_error": "无法创建文件夹。请检查输出目录、重复文件和访问权限。",
        "save_error": "无法保存修改。请检查分析档案目录的写入权限。",
        "undo_info": "撤销只删除本次记录且未被修改的副本，不会触碰源音乐。", "undo_agree": "确认撤销本次生成", "undo": "撤销",
        "architecture": "逐曲编码和标签先形成平台无关的整理蓝图；当前可复制到本地文件夹。未来取得官方授权后，同一蓝图可驱动云端歌单。",
        "qq": "云端写入目前只有预览能力；尚未接入官方授权、曲目映射或歌单写入接口。",
        "file_failures": "部分音频分析失败，详情已保存至分析档案。", "no_cover": "文件没有内嵌封面",
        "model_missing": "本地乐器模型未能运行；受影响曲目的主要声源显示待确定。",
        "model_coverage": "本地模型给出明确主要声源的曲目：{count} 首；其余保留待确定，可在单曲详情中人工修正。",
        "issue_title": "遇到一个问题", "issue_cause": "原因", "issue_solution": "解决办法", "issue_close": "知道了",
        "custom_title": "按需定制歌单", "custom_intro": "按条件抽取想听的曲目。不同条件可以一起使用；每次调整后立即更新结果。",
        "metadata_layer": "一、基本信息与元数据", "primary_layer": "二、一级编码", "secondary_layer": "三、二级编码",
        "title_search": "曲名包含", "artists_filter": "歌手", "albums_filter": "专辑", "genres_filter": "原始流派", "years_filter": "发行时间",
        "instruments_filter": "主要声源", "keys_filter": "调性", "loudness_filter": "响度等级", "tempo_filter": "节奏等级",
        "act_range": "声音活跃度区间", "bri_range": "声音明亮度区间", "slider_note": "量表为零到十分，来自已有的一百分制编码；两端都包含。",
        "filter_dependency_note": "活跃度会参考节奏和响度，明亮度来自频谱测量；叠加条件可能筛出零首，界面会提示可放宽的条件。",
        "filter_count_note": "每个选项后的数字表示：保持其他筛选条件时，该标签可匹配的曲目数。同一栏目可多选，不同栏目取交集。",
        "matched": "符合条件", "empty_result": "当前条件组合没有匹配的曲目。可以保留一级与二级编码同时筛选，并尝试放宽以下条件：",
        "empty_fallback": "可先放宽一项，再观察匹配数量。", "relax_hint": "放宽“{field}”可得到 {count} 首",
        "undo_filter": "撤销最近一项筛选修改",
        "custom_results": "筛选结果", "custom_name": "歌单名称", "custom_name_default": "我的歌单",
        "custom_name_hint": "最终文件名或文件夹名会清理系统不允许的字符。", "custom_name_error": "请填写有效的歌单名称。",
        "download_playlist": "下载播放清单", "download_note": "播放清单引用原始音乐路径，不复制文件；原文件移动后需要重新生成。",
        "custom_copy": "复制选中曲目到文件夹", "custom_output": "歌单输出位置", "custom_preview": "复制预览",
        "custom_agree": "我已核对筛选结果与目标位置，同意复制这些曲目", "custom_create": "创建此歌单文件夹",
        "custom_created": "歌单文件夹已创建", "custom_duplicate": "相同条件的歌单已创建；更改名称或条件后可再次创建。",
        "custom_undo_agree": "确认撤销本次歌单副本", "custom_undo": "撤销本次歌单副本", "custom_undone": "已撤销本次歌单副本",
        "all_title": "整理全部音乐",
    },
    "en": {
        "title": "MuseFolders", "switch": "Switch to Chinese", "tagline": "Explore your music map, listen and filter, then choose what to save or organize.",
        "workspace": "Workspace", "explore_workspace": "Music exploration", "organize_workspace": "Catalog and folders",
        "advanced_tools": "Advanced tools: catalog and whole-library folders", "send_to_draft": "Send filtered songs to the current playlist",
        "source": "Music source folder", "browse": "Browse folders", "records": "Analysis records folder",
        "scan": "Analyze this folder", "safe": "Original music remains read-only; analysis and preview never change files.",
        "ready": "Choose a music source folder, then start analysis.", "changed": "The source folder changed. Analyze it again.",
        "analyzing": "Analyzing", "failed": "Analysis failed. Check the folder, audio formats, and permissions.",
        "analyzed": "Analyzed tracks", "duration": "Library duration", "hours": "hours", "skipped": "Protected files skipped",
        "catalog": "Track catalog", "catalog_help": "Each row is one track. Genre is shown exactly as embedded metadata, not as a verified finding. Titles, artists, and albums remain unchanged.",
        "cover": "Cover", "basic": "Basic information", "base": "Base encoding", "secondary": "Secondary encoding",
        "song": "Title", "artist": "Artist", "album": "Album", "release": "Release date", "genre": "Raw genre",
        "local_date": "Local file creation time", "date_note": "File creation time is only a proxy; it does not establish the actual download date.",
        "unknown": "Not provided", "unknown_artist": "Unknown artist", "instrument": "Main sound", "instrument_note": "The main sound is a local model estimate, not an official performance credit. Weak evidence is marked uncertain.",
        "instrument_edit": "Correct the main sound", "instrument_save": "Save main sound", "instrument_manual": "User corrected",
        "tempo": "Tempo", "tempo_unit": "BPM", "loudness": "Loudness proxy", "loudness_unit": "dBFS",
        "key": "Estimated key", "mode": "Estimated mode", "key_uncertain": "Uncertain", "act": "ACT", "bri": "BRI", "points": "points",
        "key_note": "Key is estimated from audio excerpts, not musically verified. Weak evidence is marked uncertain.",
        "inspect": "Inspect a track", "listen": "Listen", "metadata_note": "Raw genre comes only from file metadata; a displayed genre is not verified.",
        "organize": "Folder organization", "choose_tags": "Select encoding tags for grouping (up to three)",
        "tag_help": "Tracks are grouped by selected tag values. Folder names use only those tags; unselected tags remain in the catalog.",
        "need_tags": "Select at least one tag.", "candidate": "Estimated output", "folders": "folders", "tracks": "tracks",
        "many": "This selection creates many folders. Consider fewer tags.", "confirm": "Confirm selected tags",
        "confirmed": "Grouping confirmed. Inspect the preview before copying music.", "not_confirmed": "Confirm the current tag selection first.",
        "preview": "Folder preview", "edit": "Manual adjustments", "export": "Create folders", "future": "Future integration",
        "rename": "Rename a folder", "save_name": "Save name", "invalid_name": "Invalid folder name. Change it and try again.",
        "move": "Correct a track assignment", "choose_track": "Track", "target": "Target folder", "save_move": "Save assignment",
        "output": "Output folder", "operations": "Will copy", "operations_tail": "tracks into new folders; originals stay untouched.",
        "preview_ops": "Preview first twenty operations", "source_file": "Source file", "destination": "Destination file",
        "agree": "I reviewed the grouping and copy preview; create folders and playlists", "apply": "Create these folders",
        "done": "Copy complete", "export_error": "Could not create folders. Check the output path, existing files, and permissions.",
        "save_error": "Could not save the change. Check write access to the analysis records folder.",
        "undo_info": "Undo removes only unchanged copies recorded in this run; source music is never touched.", "undo_agree": "Confirm undo", "undo": "Undo",
        "architecture": "Track encodings and tags produce a platform-neutral organization plan. It currently copies to local folders; with official authorization, the same plan could drive cloud playlists.",
        "qq": "Cloud writes are preview-only. Official authorization, track mapping, and playlist-write access are not connected yet.",
        "file_failures": "Some audio files failed analysis; details are in the analysis records.", "no_cover": "No embedded cover art",
        "model_missing": "The local instrument model could not run; affected tracks show an uncertain main sound.",
        "model_coverage": "Tracks with a clear main sound from the local model: {count}. Others remain uncertain and can be corrected in track details.",
        "issue_title": "Something went wrong", "issue_cause": "Cause", "issue_solution": "How to fix it", "issue_close": "Got it",
        "custom_title": "Build a playlist on demand", "custom_intro": "Select the tracks you want. You can combine conditions, and results update as you adjust them.",
        "metadata_layer": "1. Track information and metadata", "primary_layer": "2. Base encodings", "secondary_layer": "3. Secondary encodings",
        "title_search": "Title contains", "artists_filter": "Artists", "albums_filter": "Albums", "genres_filter": "Raw genres", "years_filter": "Release dates",
        "instruments_filter": "Main sounds", "keys_filter": "Keys", "loudness_filter": "Loudness levels", "tempo_filter": "Tempo levels",
        "act_range": "ACT range", "bri_range": "BRI range", "slider_note": "The zero to ten scale maps to existing scores out of one hundred; both endpoints are included.",
        "filter_dependency_note": "ACT incorporates tempo and loudness; BRI uses spectral measurement. Combined conditions may return no tracks, with suggestions to relax them.",
        "filter_count_note": "Each option count shows matches under the other active filters. Select several within a field; different fields are combined.",
        "matched": "Matching tracks", "empty_result": "No tracks match this combination. Base and secondary encodings can be used together; try relaxing:",
        "empty_fallback": "Relax one condition and check the count again.", "relax_hint": "Relax {field} to find {count} tracks",
        "undo_filter": "Undo the latest filter change",
        "custom_results": "Filtered tracks", "custom_name": "Playlist name", "custom_name_default": "My playlist",
        "custom_name_hint": "Characters forbidden in file names are cleaned from the final name.", "custom_name_error": "Enter a valid playlist name.",
        "download_playlist": "Download playlist", "download_note": "The playlist refers to the original files without copying them. Recreate it if files move.",
        "custom_copy": "Copy selected tracks into a folder", "custom_output": "Playlist output location", "custom_preview": "Copy preview",
        "custom_agree": "I checked the results and destination; copy these tracks", "custom_create": "Create this playlist folder",
        "custom_created": "Playlist folder created", "custom_duplicate": "This exact playlist was created already. Change its name or filters to create another.",
        "custom_undo_agree": "Confirm undo of these playlist copies", "custom_undo": "Undo playlist copies", "custom_undone": "Playlist copies undone",
        "all_title": "Organize the whole library",
    },
}

KNOWN_ISSUES = {
    "zh": {
        "source_state_conflict": ("文件夹输入框创建后，程序又尝试修改它的内部状态。", "刷新页面后重新选择文件夹；如果再次出现，可先手动输入完整路径，再重启软件。"),
        "picker_unavailable": ("系统文件夹选择窗口未能打开；这不是取消选择。", "将音乐文件夹的完整路径手动粘贴到输入框后再分析；若仍失败，请重启软件。"),
        "source_missing": ("指定的音乐来源文件夹不存在，或已被移动、重命名。", "检查路径是否完整，并用“浏览文件夹”重新选择现有目录。"),
        "records_overlap": ("分析档案目录位于音乐来源文件夹内，会把生成的文件混入曲库。", "把分析档案保存位置改为音乐来源文件夹以外的目录，然后重新分析。"),
        "no_audio": ("所选目录中没有找到可分析的音频文件。", "选择包含常见、未加密音频文件的文件夹；受保护的音乐文件无法直接分析。"),
        "all_failed": ("找到了音频文件，但每首都未能成功解码或分析。", "先用一个可正常播放的普通音频文件重试，并检查分析档案中的失败记录。"),
        "access_permission": ("程序无法读取部分音乐文件，或无法写入分析档案。", "检查音乐来源文件夹的读取权限，以及分析档案目录的写入权限和剩余空间，然后重试。"),
        "save_permission": ("程序无法将修改写入分析档案目录。", "检查分析档案保存位置的写入权限和磁盘剩余空间，然后重试。"),
        "output_root": ("输出目录被设为磁盘根目录，无法安全地区分本次生成的文件。", "把输出目录改为磁盘内的具体文件夹，例如“曲境输出”。"),
        "output_overlap": ("输出目录与原始曲库重合，或两者互为上、下级目录。", "选择与音乐来源文件夹完全分离的输出目录，再检查预览。"),
        "output_not_folder": ("输出路径已被一个普通文件占用，不能创建同名文件夹。", "更换输出目录名称，或选择一个尚未被文件占用的位置。"),
        "source_changed": ("音乐文件在分析后被移动、删除或修改，旧预览已不可靠。", "重新分析音乐来源文件夹，确认分类和复制预览后再创建文件夹。"),
    },
    "en": {
        "source_state_conflict": ("The app tried to change the folder input's internal state after creating it.", "Refresh the page and choose the folder again. If it repeats, enter the full path manually and restart the app."),
        "picker_unavailable": ("The system folder picker could not open; this was not a cancellation.", "Paste the full music-folder path into the input and analyze again. Restart the app if the picker still fails."),
        "source_missing": ("The selected music source folder does not exist, or was moved or renamed.", "Check the full path and use Browse folders to select an existing folder."),
        "records_overlap": ("The analysis-records folder is inside the music source, which would mix generated files into the library.", "Move the analysis-records folder outside the music source and analyze again."),
        "no_audio": ("No supported audio files were found in the selected folder.", "Choose a folder with MP3, WAV, FLAC, M4A, OGG, OPUS, or AAC files. Protected music files cannot be analyzed directly."),
        "all_failed": ("Audio files were found, but every file failed decoding or analysis.", "Try one playable MP3 or WAV file first, and inspect the failure records in the analysis folder."),
        "access_permission": ("The app cannot read some music files or write analysis records.", "Check read access to the music folder, and write access and free space for the analysis-records folder, then retry."),
        "save_permission": ("The app cannot write changes to the analysis-records folder.", "Check write permissions and free disk space for that folder, then retry."),
        "output_root": ("The output path is a drive root, so files from this run cannot be safely separated.", "Choose a specific folder on the drive, such as D:\\MuseFolders Output."),
        "output_overlap": ("The output folder overlaps the source library or is its parent or child.", "Choose an output folder entirely separate from the music source, then review the preview again."),
        "output_not_folder": ("An ordinary file already occupies the selected output path.", "Choose another output folder name or a path that is not occupied by a file."),
        "source_changed": ("A music file was moved, deleted, or changed after analysis, so the old preview is no longer reliable.", "Analyze the source folder again, then review the grouping and copy preview before creating folders."),
    },
}


def classify_analysis_error(exc: Exception) -> str | None:
    if isinstance(exc, FileNotFoundError) and str(exc).startswith("音乐目录不存在："):
        return "source_missing"
    if isinstance(exc, PermissionError):
        return "access_permission"
    message = str(exc)
    if isinstance(exc, ValueError):
        if message.startswith("分析档案不能写入源曲库"):
            return "records_overlap"
        if message == "目录中没有可分析的音频文件":
            return "no_audio"
    if isinstance(exc, RuntimeError) and message.startswith("所有音频都分析失败"):
        return "all_failed"
    return None


def classify_output_error(exc: Exception) -> str | None:
    if isinstance(exc, ValueError):
        message = str(exc)
        if message == "输出目录不能是磁盘根目录":
            return "output_root"
        if message == "输出目录不能与源曲库互为上下级目录":
            return "output_overlap"
        if message == "输出路径已经存在且不是文件夹":
            return "output_not_folder"
        if message.startswith(("源文件不在已选曲库内", "源文件在分析后发生变化")):
            return "source_changed"
    return None


def show_known_issue(code: str, language: str) -> None:
    labels = TEXT[language]
    cause, solution = KNOWN_ISSUES[language][code]

    @st.dialog(labels["issue_title"], width="small")
    def issue_dialog() -> None:
        st.markdown(f"**{labels['issue_cause']}**")
        st.write(cause)
        st.markdown(f"**{labels['issue_solution']}**")
        st.write(solution)
        if st.button(labels["issue_close"], key="close_known_issue"):
            st.rerun()

    issue_dialog()


class FolderPickerError(RuntimeError):
    """A picker failure is distinct from the user cancelling the picker."""


def choose_local_folder(initial: str) -> str | None:
    """Open a native picker when the app runs on the user's own desktop."""
    root = None
    try:
        from tkinter import Tk, filedialog
        root = Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=initial if Path(initial).is_dir() else str(Path.home()), parent=root)
        return chosen or None
    except Exception as exc:
        raise FolderPickerError("Native folder picker could not open") from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                LOGGER.warning("Could not close native folder picker", exc_info=True)


@st.cache_data(show_spinner=False)
def cover_for(path: str, modified_ns: int) -> str | None:
    return read_cover_data_uri(Path(path))


def date_for(timestamp_ns: int, missing: str) -> str:
    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M") if timestamp_ns else missing


def artist_for(track, t: dict[str, str]) -> str:
    return t["unknown_artist"] if track.metadata.artist in {"", "未知艺人"} else track.metadata.artist


def track_row(track, t: dict[str, str], language: str) -> dict[str, str | None]:
    values = VALUE_LABELS[language]
    sep = "：" if language == "zh" else ": "
    basic = "\n".join([
        f"{t['song']}{sep}{track.metadata.title}", f"{t['artist']}{sep}{artist_for(track, t)}",
        f"{t['album']}{sep}{track.metadata.album or t['unknown']}",
        f"{t['release']}{sep}{track.metadata.year or t['unknown']}",
        f"{t['genre']}{sep}{track.metadata.genre or t['unknown']}",
        f"{t['local_date']}{sep}{date_for(track.source_ctime_ns, t['unknown'])}",
    ])
    key = format_tag_value("key", track.tags.get("key", key_tag_value(track.acoustic)), language)
    mode = format_tag_value("tonality", track.tags.get("tonality", "uncertain"), language)
    base = "\n".join([
        f"{t['instrument']}{sep}{values.get(track.instrument, values['unknown'])}" +
        (f" ({t['instrument_manual']})" if track.instrument_status == "manual" else ""),
        f"{t['key']}{sep}{key}",
        f"{t['mode']}{sep}{mode}",
        f"{t['loudness']}{sep}{track.acoustic.rms_dbfs:.1f} {t['loudness_unit']}",
        f"{t['tempo']}{sep}{track.acoustic.tempo_bpm:.1f} {t['tempo_unit']}",
    ])
    secondary = "\n".join([
        f"{t['act']}{sep}{track.standard.agitation:.1f}/100 {t['points']} ({values[track.tags['agitation']]})",
        f"{t['bri']}{sep}{track.standard.brightness:.1f}/100 {t['points']} ({values[track.tags['brightness']]})",
    ])
    return {t["cover"]: cover_for(track.source_path, track.source_mtime_ns),
            t["basic"]: basic, t["base"]: base, t["secondary"]: secondary}


def playlist_filters_from_state() -> PlaylistFilters:
    state = st.session_state
    act = tuple(state.get("playlist_act_range", (0.0, 10.0)))
    bri = tuple(state.get("playlist_bri_range", (0.0, 10.0)))
    return PlaylistFilters(
        title_query=state.get("playlist_title_query", ""),
        artists=frozenset(state.get("playlist_artists", [])),
        albums=frozenset(state.get("playlist_albums", [])),
        genres=frozenset(state.get("playlist_genres", [])),
        years=frozenset(state.get("playlist_years", [])),
        instruments=frozenset(state.get("playlist_instruments", [])),
        keys=frozenset(state.get("playlist_keys", [])),
        loudness=frozenset(state.get("playlist_loudness", [])),
        tempo=frozenset(state.get("playlist_tempo", [])),
        act_range=(act[0] * 10, act[1] * 10),
        bri_range=(bri[0] * 10, bri[1] * 10),
    )


def filter_option_label(field: str, value: str, count: int, language: str, missing: str) -> str:
    if value == MISSING_VALUE:
        label = missing
    elif field == "keys":
        label = format_tag_value("key", value, language)
    elif field in {"instruments", "loudness", "tempo"}:
        label = VALUE_LABELS[language].get(value, value)
    else:
        label = value
    return f"{label} ({count})"


st.set_option("client.toolbarMode", "minimal")
st.set_page_config(page_title="MuseFolders" if st.session_state.get("english_mode") else "曲境", page_icon="🎧", layout="wide")
with st.sidebar:
    english = st.toggle("Switch to Chinese" if st.session_state.get("english_mode") else "切换为英文", key="english_mode")
language = "en" if english else "zh"
t = TEXT[language]
issue_code = None
# Apply a directory chosen on the previous run before the keyed input exists.
# Streamlit forbids changing a widget's session-state value after creation.
pending_source = st.session_state.pop("pending_source_folder", None)
if pending_source:
    try:
        st.session_state.source_folder = pending_source
    except StreamlitWidgetAlreadyInstantiatedError:
        LOGGER.exception("Folder input state conflict")
        issue_code = "source_state_conflict"
st.title(f"🎧 {t['title']}")
st.caption(t["tagline"])

with st.sidebar:
    st.header(t["source"])
    if "source_folder" not in st.session_state:
        st.session_state.source_folder = str((ROOT.parent / "音乐samples").resolve())
    source_text = st.text_input(t["source"], key="source_folder")
    if st.button(t["browse"]):
        try:
            chosen = choose_local_folder(source_text)
            if chosen:
                st.session_state.pending_source_folder = chosen
                st.rerun()
        except FolderPickerError:
            LOGGER.exception("Native folder picker failed")
            issue_code = "picker_unavailable"
    with st.expander(t["records"]):
        artifacts_text = st.text_input(t["records"], value=str((ROOT / "artifacts").resolve()), key="records_folder")
    scan = st.button(t["scan"], type="primary", width="stretch")
    st.info(t["safe"])

if scan:
    bar = st.progress(0.0)
    def update(done: int, total: int, name: str) -> None:
        bar.progress(done / max(total, 1), text=f"{t['analyzing']} {min(done + 1, total)}/{total}: {name}")
    try:
        plan, evidence = analyze_library(Path(source_text), Path(artifacts_text), naming_mode="quant",
                                         scheme_id="custom", progress=update, language=language)
        st.session_state.plan = plan
        st.session_state.evidence = evidence
        st.session_state.committed_signature = None
        st.session_state.last_manifest = None
        for field in ("title_query", "artists", "albums", "genres", "years", "instruments", "keys",
                      "loudness", "tempo", "act_range", "bri_range"):
            st.session_state.pop(f"playlist_{field}", None)
        st.session_state.pop("playlist_filter_snapshot", None)
        st.session_state.pop("playlist_last_filter_change", None)
        bar.progress(1.0)
    except Exception as exc:
        LOGGER.exception("Music analysis failed")
        issue_code = classify_analysis_error(exc)
        if issue_code is None:
            st.error(t["failed"])

if issue_code is not None:
    show_known_issue(issue_code, language)
    st.stop()

plan = st.session_state.get("plan")
if plan is None:
    st.info(t["ready"])
    st.stop()
if Path(source_text).resolve() != Path(plan.source_root):
    st.info(t["changed"])
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric(t["analyzed"], len(plan.tracks))
m2.metric(t["duration"], f"{sum(x.acoustic.duration_s for x in plan.tracks) / 3600:.1f} {t['hours']}")
m3.metric(t["skipped"], len(plan.unsupported_files))

advanced_tools = st.toggle(t["advanced_tools"], key="advanced_tools")
if not advanced_tools:
    render_explorer(plan, Path(artifacts_text), language, ROOT)
    st.stop()

st.subheader(t["catalog"])
st.caption(t["catalog_help"])
rows = [track_row(track, t, language) for track in plan.tracks]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", row_height=142,
             column_config={t["cover"]: st.column_config.ImageColumn(t["cover"], width="small"),
                            t["basic"]: st.column_config.TextColumn(t["basic"], width="large"),
                            t["base"]: st.column_config.TextColumn(t["base"], width="medium"),
                            t["secondary"]: st.column_config.TextColumn(t["secondary"], width="medium")})
st.caption(t["date_note"])
st.caption(t["instrument_note"])
st.caption(t["key_note"])
st.caption(t["model_coverage"].format(count=sum(track.instrument_status == "model_estimate" for track in plan.tracks)))
if any(track.instrument_status == "unavailable" for track in plan.tracks):
    st.warning(t["model_missing"])
if plan.failures:
    st.warning(t["file_failures"])

selected_track = st.selectbox(t["inspect"], plan.tracks, key="inspect_track",
                              format_func=lambda item: f"{item.metadata.title} — {artist_for(item, t)}")
left, right = st.columns([1, 5])
with left:
    cover = cover_for(selected_track.source_path, selected_track.source_mtime_ns)
    if cover:
        st.image(base64.b64decode(cover.split(",", 1)[1]), width="stretch")
    else:
        st.caption(t["no_cover"])
with right:
    detail = track_row(selected_track, t, language)
    for group in ("basic", "base", "secondary"):
        st.markdown(f"**{t[group]}**\n\n" + detail[t[group]].replace("\n", "  \n"))
    st.caption(t["metadata_note"])
    st.audio(selected_track.source_path)

instrument_options = ["unknown", "voice", "piano", "guitar", "strings", "wind", "percussion", "synthesizer"]
corrected_instrument = st.selectbox(t["instrument_edit"], instrument_options,
                                    index=instrument_options.index(selected_track.instrument),
                                    key=f"instrument-{selected_track.track_id}",
                                    format_func=lambda value: VALUE_LABELS[language][value])
if st.button(t["instrument_save"]):
    # Streamlit can return a deserialized copy from a selectbox. Update the
    # canonical item in the plan, not the widget value.
    corrected_track = plan.track_by_id()[selected_track.track_id]
    previous = (corrected_track.instrument, corrected_track.instrument_status, corrected_track.instrument_score)
    corrected_track.instrument = corrected_instrument
    corrected_track.instrument_status = "manual"
    corrected_track.instrument_score = 0.0
    corrected_track.tags["instrument"] = corrected_instrument
    try:
        save_instrument_override(corrected_track, Path(artifacts_text))
        save_plan(plan, Path(artifacts_text))
        st.session_state.committed_signature = None
        st.rerun()
    except (OSError, ValueError) as exc:
        LOGGER.exception("Could not save instrument correction")
        corrected_track.instrument, corrected_track.instrument_status, corrected_track.instrument_score = previous
        corrected_track.tags["instrument"] = previous[0]
        if isinstance(exc, OSError):
            show_known_issue("save_permission", language)
            st.stop()
        else:
            st.error(t["save_error"])

st.divider()
st.subheader(t["custom_title"])
st.caption(t["custom_intro"])
st.caption(t["filter_count_note"])
playlist_keys = tuple(f"playlist_{field}" for field in (
    "title_query", "artists", "albums", "genres", "years", "instruments", "keys",
    "loudness", "tempo", "act_range", "bri_range",
))
restore_filter = st.session_state.pop("playlist_filter_restore", None)
if restore_filter and restore_filter[0] in playlist_keys:
    st.session_state[restore_filter[0]] = restore_filter[1]
    st.session_state.playlist_last_filter_change = None
current_filter_state = {key: st.session_state.get(key) for key in playlist_keys}
previous_filter_state = st.session_state.get("playlist_filter_snapshot")
if previous_filter_state and not restore_filter:
    changed_fields = [key for key in playlist_keys
                      if current_filter_state[key] != previous_filter_state.get(key)]
    if changed_fields:
        latest = changed_fields[-1]
        st.session_state.playlist_last_filter_change = (latest, previous_filter_state.get(latest))
current_filters = playlist_filters_from_state()
filter_fields = {
    "artists": "artists_filter", "albums": "albums_filter", "genres": "genres_filter",
    "years": "years_filter", "instruments": "instruments_filter", "keys": "keys_filter",
    "loudness": "loudness_filter", "tempo": "tempo_filter",
}

with st.expander(t["metadata_layer"], expanded=True):
    st.caption(t["metadata_note"])
    st.text_input(t["title_search"], key="playlist_title_query")
    for field in ("artists", "albums", "genres", "years"):
        counts = facet_counts(plan.tracks, current_filters, field)
        st.multiselect(
            t[filter_fields[field]], facet_options(plan.tracks, field), key=f"playlist_{field}",
            format_func=lambda value, group=field, options=counts: filter_option_label(
                group, value, options.get(value, 0), language, t["unknown"]),
        )

with st.expander(t["primary_layer"], expanded=True):
    for field in ("instruments", "keys", "loudness", "tempo"):
        counts = facet_counts(plan.tracks, current_filters, field)
        st.multiselect(
            t[filter_fields[field]], facet_options(plan.tracks, field), key=f"playlist_{field}",
            format_func=lambda value, group=field, options=counts: filter_option_label(
                group, value, options.get(value, 0), language, t["unknown"]),
        )

with st.expander(t["secondary_layer"], expanded=True):
    st.caption(t["slider_note"])
    st.caption(t["filter_dependency_note"])
    st.slider(t["act_range"], min_value=0.0, max_value=10.0, value=(0.0, 10.0), step=0.1,
              key="playlist_act_range")
    st.slider(t["bri_range"], min_value=0.0, max_value=10.0, value=(0.0, 10.0), step=0.1,
              key="playlist_bri_range")

filters = playlist_filters_from_state()
st.session_state.playlist_filter_snapshot = {key: st.session_state.get(key) for key in playlist_keys}
selected = filter_tracks(plan.tracks, filters)
st.metric(t["matched"], len(selected))
if not selected:
    suggestions = relaxation_counts(plan.tracks, filters)
    if suggestions:
        lines = [t["relax_hint"].format(field=t[filter_fields.get(field, {"title_query": "title_search",
                        "act_range": "act_range", "bri_range": "bri_range"}.get(field, field))], count=count)
                 for field, count in sorted(suggestions.items(), key=lambda item: -item[1])[:4]]
        st.info(t["empty_result"] + "\n\n" + "  \n".join(lines))
    else:
        st.info(t["empty_result"] + " " + t["empty_fallback"])
    if st.session_state.get("playlist_last_filter_change") and st.button(
            t["undo_filter"], key="playlist_undo_filter"):
        st.session_state.playlist_filter_restore = st.session_state.playlist_last_filter_change
        st.rerun()
else:
    st.subheader(t["custom_results"])
    st.dataframe(pd.DataFrame([{
        t["song"]: track.metadata.title, t["artist"]: artist_for(track, t),
        t["album"]: track.metadata.album or t["unknown"],
        t["instrument"]: VALUE_LABELS[language].get(track.instrument, t["key_uncertain"]),
        t["key"]: format_tag_value("key", track.tags.get("key", key_tag_value(track.acoustic)), language),
        t["loudness"]: VALUE_LABELS[language].get(track.tags.get("loudness", "uncertain"), t["key_uncertain"]),
        t["tempo"]: VALUE_LABELS[language].get(track.tags.get("tempo", "uncertain"), t["key_uncertain"]),
        t["act"]: f"{track.standard.agitation / 10:.1f}/10" if track.standard else t["key_uncertain"],
        t["bri"]: f"{track.standard.brightness / 10:.1f}/10" if track.standard else t["key_uncertain"],
    } for track in selected]), hide_index=True, width="stretch")

st.caption(t["send_to_draft"])
draft = _ensure_draft(plan, Path(artifacts_text), EXPLORE_LABELS[language])
draft_buttons = st.columns(3)
for column, mode, label in zip(draft_buttons, ("add", "intersect", "replace"),
                               ("add_candidates", "intersect_candidates", "replace_candidates")):
    if column.button(EXPLORE_LABELS[language][label], disabled=not selected,
                     key=f"catalog_to_draft_{mode}"):
        apply_selection(draft, plan, [track.track_id for track in selected], mode, "catalog_filter")
        draft.filters = filters.to_dict()
        _save_draft(Path(artifacts_text), draft, EXPLORE_LABELS[language])
        st.success(f"{EXPLORE_LABELS[language]['current_draft']}: {len(draft.items)}")

playlist_name = st.text_input(t["custom_name"], value=t["custom_name_default"], key="custom_playlist_name")
try:
    clean_playlist_name = safe_playlist_name(playlist_name)
except ValueError:
    clean_playlist_name = None
    st.warning(t["custom_name_error"])
st.caption(t["custom_name_hint"])
st.caption(t["download_note"])
st.download_button(
    t["download_playlist"], data=playlist_bytes(selected) if selected else b"",
    file_name=f"{clean_playlist_name or 'playlist'}.m3u8", mime="audio/x-mpegurl",
    disabled=not selected or clean_playlist_name is None, key="custom_playlist_download",
)

if selected and clean_playlist_name is not None:
    with st.expander(t["custom_copy"]):
        custom_output_text = st.text_input(
            t["custom_output"], value=str((ROOT / "output" / "Custom Playlists").resolve()),
            key="custom_playlist_output",
        )
        custom_plan = build_playlist_plan(plan, selected, clean_playlist_name, filters, language)
        custom_adapter = LocalFolderAdapter(Path(custom_output_text))
        copy_signature = (
            plan.analysis_id, tuple(track.track_id for track in selected), clean_playlist_name,
            str(custom_adapter.output_root), filters.to_dict(),
        )
        if st.session_state.get("custom_preview_signature") != copy_signature:
            st.session_state.custom_preview_signature = copy_signature
            st.session_state.custom_playlist_agree = False
        try:
            custom_operations = custom_adapter.preview(custom_plan)
        except Exception as exc:
            LOGGER.exception("Could not preview custom playlist output")
            known = classify_output_error(exc)
            if known:
                cause, solution = KNOWN_ISSUES[language][known]
                st.warning(f"{t['issue_cause']}: {cause}  \n{t['issue_solution']}: {solution}")
            else:
                st.error(t["export_error"])
        else:
            st.write(f"{t['custom_preview']}: {len(custom_operations)} {t['tracks']}")
            st.dataframe(pd.DataFrame([{t["source_file"]: item.source, t["destination"]: item.destination}
                                       for item in custom_operations[:20]]), hide_index=True, width="stretch")
            duplicate = (
                st.session_state.get("custom_last_signature") == copy_signature
                and Path(st.session_state.get("custom_last_manifest", "")).is_file()
            )
            if duplicate:
                st.info(t["custom_duplicate"])
            agreed = st.checkbox(t["custom_agree"], key="custom_playlist_agree")
            if st.button(t["custom_create"], type="primary", disabled=not agreed or duplicate,
                         key="custom_playlist_create"):
                try:
                    result = custom_adapter.apply(custom_plan)
                    st.session_state.custom_last_manifest = result["manifest"]
                    st.session_state.custom_last_output_root = str(custom_adapter.output_root)
                    st.session_state.custom_last_signature = copy_signature
                    st.success(f"{t['custom_created']}: {result['copied']}")
                except Exception as exc:
                    LOGGER.exception("Could not create custom playlist folder")
                    known = classify_output_error(exc)
                    if known:
                        show_known_issue(known, language)
                        st.stop()
                    st.error(t["export_error"])

custom_manifest = st.session_state.get("custom_last_manifest")
if custom_manifest and Path(custom_manifest).is_file():
    st.caption(t["undo_info"])
    undo_custom_agreed = st.checkbox(t["custom_undo_agree"], key="custom_playlist_undo_agree")
    if st.button(t["custom_undo"], disabled=not undo_custom_agreed, key="custom_playlist_undo"):
        try:
            undo_adapter = LocalFolderAdapter(Path(st.session_state.custom_last_output_root))
            result = undo_adapter.rollback(Path(custom_manifest))
            st.session_state.custom_last_manifest = None
            st.session_state.custom_last_signature = None
            st.success(f"{t['custom_undone']}: {result['removed_copies']}")
        except Exception:
            LOGGER.exception("Could not undo custom playlist folder")
            st.error(t["export_error"])

st.divider()
st.subheader(t["all_title"])
st.caption(t["tag_help"])
selectable = ["instrument", "tonality", "key", "loudness", "tempo", "agitation", "brightness"]
tag_keys = st.multiselect(t["choose_tags"], selectable, default=["agitation"], max_selections=3,
                          format_func=lambda key: TAG_LABELS[language][key])
valid = bool(tag_keys)
if not valid:
    st.warning(t["need_tags"])
else:
    draft_folders, _ = compile_scheme(copy.deepcopy(plan.tracks), "custom", tag_keys=tag_keys,
                                      naming_mode="quant", language=language)
    st.write(f"{t['candidate']}: {len(draft_folders)} {t['folders']}")
    st.dataframe(pd.DataFrame([{t["preview"]: folder.name, t["tracks"]: len(folder.track_ids)}
                               for folder in draft_folders]), hide_index=True, width="stretch")
    if len(draft_folders) > max(12, len(plan.tracks) // 3):
        st.warning(t["many"])

signature = (plan.analysis_id, tuple(tag_keys), language)
if st.button(t["confirm"], type="primary", disabled=not valid):
    try:
        plan.folders, plan.tag_keys = compile_scheme(plan.tracks, "custom", tag_keys=tag_keys,
                                                    naming_mode="quant", language=language)
        plan.scheme_id, plan.naming_mode, plan.language = "custom", "quant", language
        save_plan(plan, Path(artifacts_text))
        st.session_state.committed_signature = signature
        st.success(t["confirmed"])
    except (OSError, ValueError) as exc:
        LOGGER.exception("Could not confirm grouping")
        if isinstance(exc, OSError):
            show_known_issue("save_permission", language)
            st.stop()
        else:
            st.error(t["save_error"])
if st.session_state.get("committed_signature") != signature:
    st.info(t["not_confirmed"])
    st.stop()

tabs = st.tabs([t["preview"], t["edit"], t["export"], t["future"]])
track_map = plan.track_by_id()
with tabs[0]:
    for folder in plan.folders:
        with st.expander(f"📁 {folder.name} · {len(folder.track_ids)} {t['tracks']}"):
            st.caption(folder.explanation)
            st.dataframe(pd.DataFrame([{t["song"]: track_map[tid].metadata.title,
                                        t["artist"]: artist_for(track_map[tid], t)} for tid in folder.track_ids]),
                         hide_index=True, width="stretch")

with tabs[1]:
    st.subheader(t["rename"])
    for folder in plan.folders:
        col1, col2 = st.columns([5, 1])
        new_name = col1.text_input(folder.name, value=folder.name, key=f"rename-{folder.folder_id}")
        if col2.button(t["save_name"], key=f"save-{folder.folder_id}"):
            try:
                rename_folder(plan.tracks, plan.folders, folder.folder_id, new_name)
                save_plan(plan, Path(artifacts_text))
                st.rerun()
            except (ValueError, KeyError, OSError) as exc:
                LOGGER.exception("Could not rename folder")
                if isinstance(exc, OSError):
                    show_known_issue("save_permission", language)
                    st.stop()
                else:
                    st.error(t["invalid_name"])
    st.subheader(t["move"])
    chosen_track = st.selectbox(t["choose_track"], plan.tracks, key="edit_track",
                                format_func=lambda item: f"{item.metadata.title} — {artist_for(item, t)}")
    chosen_folder = st.selectbox(t["target"], plan.folders, key="edit_folder", format_func=lambda item: item.name)
    if st.button(t["save_move"]):
        try:
            reassign_track(plan.tracks, plan.folders, chosen_track.track_id, chosen_folder.folder_id, "quant", language)
            save_plan(plan, Path(artifacts_text))
            st.rerun()
        except (OSError, ValueError, KeyError) as exc:
            LOGGER.exception("Could not change track assignment")
            if isinstance(exc, OSError):
                show_known_issue("save_permission", language)
                st.stop()
            else:
                st.error(t["save_error"])

with tabs[2]:
    output_text = st.text_input(t["output"], value=str((ROOT / "output" / "MuseFolders").resolve()))
    adapter = LocalFolderAdapter(Path(output_text))
    try:
        operations = adapter.preview(plan)
        st.session_state.pop("last_output_issue_signature", None)
        st.write(f"{t['operations']} **{len(operations)}** {t['operations_tail']}")
        with st.expander(t["preview_ops"]):
            st.dataframe(pd.DataFrame([{t["source_file"]: item.source, t["destination"]: item.destination}
                                       for item in operations[:20]]), hide_index=True, width="stretch")
        agreed = st.checkbox(t["agree"])
        if st.button(t["apply"], type="primary", disabled=not agreed):
            result = adapter.apply(plan)
            st.session_state.last_manifest = result["manifest"]
            st.success(f"{t['done']}: {result['copied']}")
    except Exception as exc:
        LOGGER.exception("Could not preview or create output folders")
        output_issue = classify_output_error(exc)
        if output_issue is None:
            st.error(t["export_error"])
        else:
            output_signature = (output_issue, str(adapter.output_root), plan.analysis_id, language)
            if st.session_state.get("last_output_issue_signature") != output_signature:
                st.session_state.last_output_issue_signature = output_signature
                show_known_issue(output_issue, language)
            else:
                st.error(t["export_error"])
    manifest = st.session_state.get("last_manifest")
    if manifest:
        st.caption(t["undo_info"])
        undo_agreed = st.checkbox(t["undo_agree"])
        if st.button(t["undo"], disabled=not undo_agreed):
            try:
                result = adapter.rollback(Path(manifest))
                st.session_state.last_manifest = None
                st.success(f"{t['undo']}: {result['removed_copies']}")
            except Exception:
                LOGGER.exception("Could not undo generated folders")
                st.error(t["export_error"])

with tabs[3]:
    st.write(t["architecture"])
    st.info(t["qq"])
