from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import streamlit as st

from musefolders.lyrics_map import LyricsModelUnavailable


APP_PATH = Path(__file__).resolve().parents[1] / "legacy_app.py"


def test_offline_lyric_search_can_stage_candidates(tmp_path: Path) -> None:
    source = tmp_path / "music"
    source.mkdir()
    audio = source / "Singer - Unrelated.wav"
    _write_tone(audio, 440, 2.0)
    audio.with_suffix(".lrc").write_text(
        "爱情里我们曾经相爱，爱你是我记得的约定。\n"
        "远方的灯火照亮安静街道，我们走过的桥留下许多故事。\n"
        "面对未来的日子，回忆仍然留在心里。", encoding="utf-8")
    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    app.text_input[0].set_value(str(source))
    app.text_input[1].set_value(str(tmp_path / "records"))
    with patch("musefolders.explore_ui.LocalLyricsEmbedder.encode", side_effect=LyricsModelUnavailable("offline")):
        next(button for button in app.button if button.label == "分析此文件夹").click().run(timeout=90)
    next(item for item in app.text_input if item.label == "检索条件").set_value("爱情")
    next(button for button in app.button if button.label == "检索收藏").click().run()
    assert not app.exception
    assert len(app.session_state["local_library_hits"][2]) == 1
    next(button for button in app.button if button.label == "加入候选歌单").click().run()
    assert not app.exception
    assert app.session_state["explore_candidate_ids"]


def test_browse_folder_updates_keyed_input_before_next_render(tmp_path: Path) -> None:
    chosen = tmp_path / "另一个音乐目录"
    chosen.mkdir()
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    with patch("tkinter.Tk"), patch("tkinter.filedialog.askdirectory", return_value=str(chosen)):
        next(button for button in app.button if button.label == "浏览文件夹").click().run()
    assert not app.exception
    assert app.text_input[0].value == str(chosen)


def test_known_folder_picker_failure_has_cause_and_solution() -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    with patch("tkinter.Tk", side_effect=RuntimeError("picker unavailable")):
        next(button for button in app.button if button.label == "浏览文件夹").click().run()
    assert not app.exception
    assert len(app.get("dialog")) == 1
    dialog_text = "\n".join(item.value for item in app.get("markdown"))
    assert "系统文件夹选择窗口未能打开" in dialog_text
    assert "完整路径" in dialog_text


def test_missing_source_explains_cause_and_fix_in_english(tmp_path: Path) -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    app.toggle[0].set_value(True).run()
    app.text_input[0].set_value(str(tmp_path / "missing"))
    next(button for button in app.button if button.label == "Analyze this folder").click().run()
    assert not app.exception
    assert len(app.get("dialog")) == 1
    dialog_text = "\n".join(item.value for item in app.get("markdown"))
    assert "does not exist" in dialog_text
    assert "Check the full path" in dialog_text
    assert not any("\u4e00" <= char <= "\u9fff" for char in dialog_text)


def _write_tone(path: Path, frequency_hz: float, pulse_hz: float) -> None:
    """Create a tiny real WAV so the UI test exercises the audio pipeline."""
    sample_rate = 22_050
    duration_s = 2.0
    frames = array("h")
    for index in range(int(sample_rate * duration_s)):
        second = index / sample_rate
        pulse = 1.0 if (second * pulse_hz) % 1.0 < 0.18 else 0.22
        sample = int(14_000 * pulse * math.sin(2 * math.pi * frequency_hz * second))
        frames.append(sample)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames.tobytes())


def test_complete_streamlit_flow_reaches_folder_proposals(tmp_path: Path) -> None:
    source = tmp_path / "音乐样本"
    artifacts = tmp_path / "artifacts"
    source.mkdir()
    _write_tone(source / "测试歌手 - 安静晨光.wav", 220, 1.0)
    _write_tone(source / "测试歌手 - 沿途晴光.wav", 660, 2.0)
    _write_tone(source / "测试歌手 - 盛夏脉冲.wav", 1_320, 4.0)
    (source / "受保护曲目.mgg").write_bytes(b"protected-format-placeholder")

    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()

    assert not app.exception
    assert st.get_option("client.toolbarMode") == "minimal"
    assert any("曲境" in item.value for item in app.title)
    assert [button.label for button in app.button] == ["浏览文件夹", "分析此文件夹"]

    app.text_input[0].set_value(str(source))
    app.text_input[1].set_value(str(artifacts))
    next(button for button in app.button if button.label == "分析此文件夹").click().run(timeout=90)

    assert not app.exception
    assert not app.error
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["已分析曲目"] == "3"
    assert metrics["跳过的受保护文件"] == "1"
    assert next(item for item in app.radio if item.label == "候选歌单").value == "find"
    assert any("基础声学地图" in item.value for item in app.caption)
    next(item for item in app.toggle if item.label == "高级工具：档案与全库整理").set_value(True).run()
    assert any(item.value == "逐曲档案" for item in app.subheader)
    assert not app.tabs
    assert any(button.label == "确认这些分类标签" for button in app.button)
    assert "调性" in next(item for item in app.multiselect if item.label.startswith("勾选用于分类")).options
    assert "调性估计" in app.dataframe[0].value.iloc[0]["基础编码"]
    assert "调式估计" in app.dataframe[0].value.iloc[0]["基础编码"]
    assert any("(3)" in option for option in next(item for item in app.multiselect if item.label == "歌手").options)
    assert any(item.label == "下载播放清单" for item in app.get("download_button"))

    next(item for item in app.text_input if item.label == "曲名包含").set_value("安静晨光").run()
    assert not app.exception
    assert {metric.label: metric.value for metric in app.metric}["符合条件"] == "1"
    next(item for item in app.text_input if item.label == "歌单名称").set_value("夜晚歌单").run()
    next(item for item in app.text_input if item.label == "歌单输出位置").set_value(str(tmp_path / "custom_exports")).run()
    next(item for item in app.checkbox if item.label.startswith("我已核对筛选结果")).set_value(True).run()
    next(button for button in app.button if button.label == "创建此歌单文件夹").click().run()
    assert not app.exception
    copied = tmp_path / "custom_exports" / "夜晚歌单" / "测试歌手 - 安静晨光.wav"
    assert copied.is_file()
    assert (copied.parent / "歌单.m3u8").is_file()
    assert not (copied.parent / "测试歌手 - 沿途晴光.wav").exists()
    next(item for item in app.checkbox if item.label == "确认撤销本次歌单副本").set_value(True).run()
    next(button for button in app.button if button.label == "撤销本次歌单副本").click().run()
    assert not app.exception
    assert not copied.exists()
    assert (source / "测试歌手 - 安静晨光.wav").is_file()

    next(item for item in app.multiselect if item.label.startswith("勾选用于分类")).set_value(["key"]).run()
    assert not app.exception
    folder_preview = next(item.value for item in app.dataframe if "文件夹预览" in item.value.columns)
    assert all(name.startswith("调性 ") for name in folder_preview["文件夹预览"])

    next(button for button in app.button if button.label == "确认这些分类标签").click().run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "文件夹预览",
        "人工调整",
        "生成文件夹",
        "接口扩展",
    ]
    folder_cards = [item for item in app.expander if item.label.startswith("📁")]
    assert folder_cards
    assert len(app.get("audio")) == 1

    create_button = next(button for button in app.button if button.label == "创建这些文件夹")
    assert create_button.disabled

    next(item for item in app.text_input if item.label == "输出目录").set_value(str(source)).run()
    assert not app.exception
    assert len(app.get("dialog")) == 1
    dialog_text = "\n".join(item.value for item in app.get("markdown"))
    assert "输出目录与原始曲库重合" in dialog_text
    assert "完全分离的输出目录" in dialog_text
    next(item for item in app.text_input if item.label == "输出目录").set_value(str(tmp_path / "exports")).run()
    assert not app.exception

    next(item for item in app.selectbox if item.label == "人工修正主要声源").set_value("piano").run()
    next(button for button in app.button if button.label == "保存主要声源").click().run()
    assert not app.exception
    assert (artifacts / "instrument_overrides.json").is_file()
    assert any(track.instrument == "piano" and track.instrument_status == "manual"
               for track in app.session_state["plan"].tracks), [
                   (track.instrument, track.instrument_status) for track in app.session_state["plan"].tracks
               ]
    next(button for button in app.button if button.label == "分析此文件夹").click().run(timeout=90)
    assert not app.exception
    assert any(track.instrument == "piano" and track.instrument_status == "manual"
               for track in app.session_state["plan"].tracks)

    next(item for item in app.get("toggle") if item.label == "切换为英文").set_value(True).run()
    assert not app.exception
    assert any(button.label == "Analyze this folder" for button in app.button)
    assert any(item.value == "Track catalog" for item in app.subheader)
    assert all(not any("\u4e00" <= char <= "\u9fff" for char in button.label) for button in app.button)
    assert all(not any("\u4e00" <= char <= "\u9fff" for char in item.value) for item in app.subheader)

    other_source = tmp_path / "other_source"
    other_source.mkdir()
    next(item for item in app.text_input if item.label == "Music source folder").set_value(str(other_source)).run()
    assert not app.exception
    assert any("source folder changed" in item.value for item in app.info)
    assert not app.tabs


def test_sound_map_can_build_reviewable_playlist_without_model(tmp_path: Path) -> None:
    source = tmp_path / "local_music"
    artifacts = tmp_path / "records"
    source.mkdir()
    for number, frequency in enumerate((220, 230, 240, 250), 1):
        _write_tone(source / f"Artist - Track {number}.wav", frequency, 2.0)

    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    app.text_input[0].set_value(str(source))
    app.text_input[1].set_value(str(artifacts))
    next(button for button in app.button if button.label == "分析此文件夹").click().run(timeout=90)

    assert not app.exception
    assert next(item for item in app.radio if item.label == "候选歌单").value == "find"
    assert any("基础声学地图" in item.value for item in app.caption)
    assert any("不能等同完整声音画像的邻域图" in item.value for item in app.warning)
    for tab_name in ("听感地图", "歌曲主题地图", "流派地图", "演唱语言地图"):
        assert any(tab.label == tab_name for tab in app.tabs)
    assert any("可靠流派类别不足" in item.value for item in app.info)
    assert not any(item.label == "地图着色" for item in app.selectbox)
    next(button for button in app.button if button.label == "按听感找相似").click().run()

    assert not app.exception
    assert any(item.value.startswith("这批发现") for item in app.subheader)
    next(button for button in app.button if button.label == "加入候选").click().run()
    next(item for item in app.radio if item.label == "候选歌单").set_value("review").run()
    kept = next(item for item in app.metric if item.label == "保留曲目")
    assert int(kept.value) >= 1
    assert any(item.label == "从结果中移除" for item in app.multiselect)
    assert not (source / "user_annotations.json").exists()

    next(item for item in app.radio if item.label == "候选歌单").set_value("save").run()
    assert any(item.label == "下载播放清单" for item in app.get("download_button"))
    assert next(item for item in app.text_input if item.label == "歌单名称").value == "我的地图歌单"
    next(item for item in app.radio if item.label == "候选歌单").set_value("find").run()

    next(item for item in app.toggle if item.label == "切换为英文").set_value(True).run()
    assert not app.exception
    assert any(tab.label == "Sound map" for tab in app.tabs)
    assert any(tab.label == "Song theme map" for tab in app.tabs)
    assert any(tab.label == "Genre map" for tab in app.tabs)
    assert any(tab.label == "Vocal language map" for tab in app.tabs)
    assert all(not any("\u4e00" <= char <= "\u9fff" for char in button.label)
               for button in app.button)

    next(button for button in app.button if button.label == "Build song path").click().run()
    assert not app.exception
    assert app.session_state["explore_pending_kind"] == "path"

    next(button for button in app.button if button.label == "Build song blend").click().run()
    assert not app.exception
    assert app.session_state["explore_pending_kind"] == "alchemy"


def test_local_language_scan_survives_missing_theme_model(tmp_path: Path) -> None:
    source = tmp_path / "local_music"
    source.mkdir()
    audio = source / "Singer - Sunrise.wav"
    _write_tone(audio, 440, 2.0)
    audio.with_suffix(".lrc").write_text(
        "[00:01.00]清晨的天空有微风经过窗前，沿着街道轻轻走向远方。\n"
        "[00:04.00]我们记得昨日的故事，也期待明日新的旅程。\n", encoding="utf-8",
    )
    app = AppTest.from_file(str(APP_PATH), default_timeout=90).run()
    app.text_input[0].set_value(str(source))
    app.text_input[1].set_value(str(tmp_path / "records"))
    with patch("musefolders.explore_ui.LocalLyricsEmbedder.encode",
               side_effect=LyricsModelUnavailable("offline")):
        next(button for button in app.button if button.label == "分析此文件夹").click().run(timeout=90)
    assert not app.exception
    local_result = app.session_state["explore_language_result"]
    assert local_result.statuses
    assert "valid" in local_result.statuses.values()
    assert any("本地多语文本模型尚未就绪" in item.value for item in app.warning)
    assert app.session_state["explore_lyrics_result"].model_version == "title-clues-v1"
    assert any(tab.label == "演唱语言地图" for tab in app.tabs)
