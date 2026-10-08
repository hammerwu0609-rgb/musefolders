from pathlib import Path
from streamlit.testing.v1 import AppTest
from musefolders.service import analyze_library
from musefolders.simple_ui import portrait_map
from musefolders.astrology import build_zodiac
from test_app import _write_tone


def app_for(root):
    source = root / "music"
    source.mkdir()
    tone = source / "Singer - Memory.wav"
    _write_tone(tone, 440, 2)
    tone.with_suffix(".lrc").write_text(
        "爱情里我们曾经相爱，爱你是我记得的约定。\n远方的灯火照亮安静街道，我们走过的桥留下许多故事。\n面对未来的日子，回忆仍然留在心里。",encoding="utf-8")
    analyze_library(source, root / "artifacts")
    code = f'''from pathlib import Path
import streamlit as st
from musefolders.simple_ui import render_app, portrait_map, _catalog
from musefolders.consumer_ui import dispatch
root = Path({str(root)!r})
if st.session_state.get("_test_action"):
    plan = st.session_state.simple_plan
    dispatch(st.session_state.pop("_test_action"), plan, _catalog(plan), root, portrait_map(plan))
render_app(root)
'''
    return AppTest.from_string(code,default_timeout=60).run()


def test_simple_search_playlist_and_profile(tmp_path):
    app = app_for(tmp_path)
    assert not app.exception
    point = portrait_map(app.session_state["simple_plan"]).points[0]
    track = app.session_state["simple_plan"].tracks[0]
    assert point.x == max(0,min(100,(track.acoustic.tempo_bpm-60)/120*100))
    assert point.y == track.standard.brightness
    assert not app.radio
    assert not app.tabs and not app.sidebar.text_input
    app.session_state['_test_action'] = {"kind": "query", "text": "关于爱情的歌"}
    app.run()
    assert not app.exception
    assert len(app.session_state["simple_results"][2]) == 1
    app.session_state['_test_action'] = {"kind": "add", "id": track.track_id}
    app.run()
    assert not app.exception
    assert len(app.session_state["simple_draft"].items) == 1
    app.session_state['_test_action'] = {"kind": "export"}
    app.run()
    assert not app.exception
    app.session_state['_test_action'] = {"kind": "remove", "id": track.track_id}
    app.run()
    # Deletion now excludes the recording across sources while retaining undo provenance.
    draft = app.session_state["simple_draft"]
    assert not [item for item in draft.items if item.content_id not in draft.excluded]
    assert build_zodiac(portrait_map(app.session_state['simple_plan']), [track]).status == 'seed'
    app.session_state['_test_action'] = {"kind": "query", "text": "把搜索结果建成「爱情收藏」歌单"}
    app.run()
    assert not app.exception and app.session_state['simple_draft'].name == '爱情收藏'
    assert len(app.session_state['simple_draft'].items) == 1


def test_import_empty_and_invalid_directory(tmp_path):
    code = f"from pathlib import Path\nfrom musefolders.simple_ui import render_app\nrender_app(Path({str(tmp_path)!r}))"
    app = AppTest.from_string(code).run()
    assert not app.exception and not app.radio
    next(b for b in app.button if b.key == "simple_import").click().run()
    assert app.warning
    app.text_input[0].set_value(str(tmp_path/"missing"))
    next(b for b in app.button if b.key == "simple_import").click().run()
    assert not app.exception and app.error


def test_qq_connection_controls_and_failure(tmp_path, monkeypatch):
    import musefolders.simple_ui as ui
    monkeypatch.setattr(ui, "connection_status", lambda: {"account_hint": "***1234", "playlist_count": 2})
    app = app_for(tmp_path)
    app.session_state['_test_action'] = {"kind": "manage"}
    app.run()
    next(b for b in app.button if b.label == "检查 QQ 音乐连接").click().run()
    assert not app.exception and any("***1234" in caption.value for caption in app.caption)
    def fail(*args, **kwargs):
        raise ui.QQMusicConnectionError("QQ 音乐登录已失效")
    monkeypatch.setattr(ui, "enrich_library", fail)
    next(b for b in app.button if b.label == "从 QQ 音乐补充资料").click().run()
    assert not app.exception and any("登录已失效" in message.value for message in app.error)


def test_hidden_settings_keep_session_only_credential_and_source(tmp_path):
    app = app_for(tmp_path)
    app.session_state['_test_action'] = {'kind':'manage'}
    app.run()
    original_source = app.session_state['simple_plan'].source_root
    next(field for field in app.text_input if field.key == 'simple_api_key').set_value('test-session-only').run()
    next(button for button in app.button if button.label == '返回音乐库').click().run()
    app.run()
    assert not app.exception
    assert app.session_state['simple_api_key'] == 'test-session-only'
    assert app.session_state['simple_source'] == original_source


def test_model_settings_save_restart_test_and_delete(tmp_path, monkeypatch):
    from musefolders import model_settings as ms
    from musefolders import simple_ui as ui
    monkeypatch.setattr(ms, "_crypt", lambda data, decrypt=False: data[::-1])
    monkeypatch.setattr(ui, "test_connection", lambda config: None)
    app = app_for(tmp_path)
    app.session_state['_test_action'] = {'kind': 'manage'}
    app.run()
    app.text_input(key='simple_model_url').set_value('https://example.com/v1')
    app.text_input(key='simple_model_name').set_value('custom-model')
    app.text_input(key='simple_api_key').set_value('synthetic-secret')
    app.button(key='simple_model_check').click().run()
    assert not app.exception and any('测试通过' in item.value for item in app.success)
    app.button(key='simple_model_save').click().run()
    assert not app.exception
    assert app.session_state['simple_model_settings'].model == 'custom-model'
    assert app.session_state['simple_api_key'] == ''
    assert ms.load_settings(tmp_path).api_key == 'synthetic-secret'
    # A new browser session loads the saved credential automatically.
    code = f"from pathlib import Path\nfrom musefolders.simple_ui import render_app\nrender_app(Path({str(tmp_path)!r}))"
    fresh = AppTest.from_string(code,default_timeout=60).run()
    assert not fresh.exception
    assert fresh.session_state['simple_model_settings'].api_key == 'synthetic-secret'
    fresh.session_state['simple_edit_library'] = True
    fresh.run()
    fresh.button(key='simple_model_delete').click().run()
    assert not fresh.exception
    assert not fresh.session_state['simple_model_settings'].api_key
    assert ms.load_settings(tmp_path) is None
