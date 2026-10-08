"""Web settings: visitor credentials stay in session; server defaults are immutable."""
from pathlib import Path
import streamlit as st
from .model_settings import ModelSettings, ModelSettingsError, active_settings, validate, defaults, test_connection
from .personal_ui import qq_login, activate, invalidate
from .personal_library import playlist_id
from .qqmusic_web import run, fetch_collection, list_playlists, enrich, WebQQError


def candidate(url, model, key, current):
    """Never forward an existing server credential to a visitor-supplied endpoint."""
    config = validate(ModelSettings(url, model, key))
    if not key.strip():
        if config.api_url != current.api_url:
            raise ModelSettingsError('更换 API 地址时，请同时填写该服务的密钥。')
        config = validate(ModelSettings(config.api_url, config.model, current.api_key))
    if not config.api_key:
        raise ModelSettingsError('请填写 API 密钥。')
    return config


def form_candidate(url, model, key, current, tested=None):
    """Reuse a successfully tested secret only for its unchanged endpoint/model."""
    target = validate(ModelSettings(url, model, key))
    if not key.strip() and tested is not None:
        if (target.api_url, target.model) == (tested.api_url, tested.model):
            return candidate(url, model, '', tested)
    return candidate(url, model, key, current)


def model_controls(root):
    current = active_settings(root)
    st.caption('模型用于理解搜索描述和分析歌词。你填写的配置仅用于本次访问；全站默认模型由服务端配置。')
    st.write('当前模型：' + current.model + (' · 已连接配置' if current.api_key else ' · 未配置'))
    with st.form('web_model_form', clear_on_submit=True):
        url = st.text_input('API 地址', value=current.api_url)
        model = st.text_input('模型名称', value=current.model)
        key = st.text_input('API 密钥', type='password', help='密钥不回显、不写入文件；留空保留当前地址的已有密钥。')
        apply = st.form_submit_button('应用到本次访问', type='primary')
        check = st.form_submit_button('测试连接')
    if apply or check:
        try:
            config = form_candidate(url, model, key, current,
                                    st.session_state.get('web_model_tested'))
            if check:
                from .demo_mode import check_ai_budget
                check_ai_budget()
                test_connection(config)
                st.session_state.web_model_tested = config
                st.success('连接测试通过，密钥已暂存于本次会话；无需再次粘贴，点击应用后使用。')
            else:
                st.session_state.simple_model_settings = config
                st.session_state.simple_model_origin = '本次会话配置'
                st.session_state.pop('web_model_tested', None)
                invalidate()
                st.rerun()
        except (ModelSettingsError, RuntimeError) as exc:
            st.error(str(exc))
    if st.button('恢复服务器默认配置', key='web_model_reset'):
        st.session_state.pop('web_model_tested', None)
        st.session_state.simple_model_settings = defaults()
        st.session_state.simple_model_origin = '服务器默认配置'
        invalidate()
        st.rerun()


def import_rows(root, plan, identifier=None):
    progress = st.progress(0, text='正在读取收藏…')
    rows = run(fetch_collection(identifier, st.session_state.get('web_qq_credential'),
        progress=lambda done,total: progress.progress(min(done/max(total,1),1),text=f'正在读取 · {done}/{total}')))
    activate(rows, root, plan)


def render_management(root: Path, plan):
    source, connection, details, ai = st.tabs(['音乐来源', 'QQ 音乐连接', '歌曲资料', 'AI 设置'])
    with source:
        st.write(f'当前曲库 · {len(plan.tracks)} 首')
        from .library_import_ui import render_import
        render_import(root, False, None)
        st.divider()
        st.caption('通过 QQ 歌单链接或扫码后的收藏导入。歌曲资料不包含音频，暂时只有与演示曲库匹配的歌曲可以站内试听和显示听感。')
        url = st.text_input('QQ 音乐歌单链接 / ID', key='web_playlist_url')
        if st.button('导入歌单', key='web_import_url'):
            try:
                import_rows(root, plan, playlist_id(url))
            except (ValueError, WebQQError) as exc:
                st.error(str(exc))
        if st.session_state.get('personal_import_message'):
            st.info(st.session_state.personal_import_message)
        if st.button('重新体验导入流程', key='web_restart_import'):
            # Drop only visitor state. Shared server music remains untouched.
            for name in ('simple_plan', 'personal_reference_plan', 'personal_import_message',
                         'simple_music_import', 'simple_draft', 'simple_source'):
                st.session_state.pop(name, None)
            st.session_state.simple_initialized = True
            st.session_state.simple_edit_library = False
            st.session_state.personal_active = False
            invalidate()
            st.rerun()
        st.caption('歌单保存在本次访问，可在主界面导出；无需粘贴 JSON 清单。')
    with connection:
        qq_login()
        credential = st.session_state.get('web_qq_credential')
        if credential:
            if st.button('导入我喜欢的歌曲', key='web_import_liked'):
                try:
                    import_rows(root, plan)
                except (ValueError, WebQQError) as exc:
                    st.error(str(exc))
            if st.button('读取我的歌单', key='web_list_playlists'):
                try:
                    st.session_state.web_qq_playlists = run(list_playlists(credential))
                except WebQQError as exc:
                    st.error(str(exc))
            playlists = st.session_state.get('web_qq_playlists', [])
            if playlists:
                selected = st.selectbox('选择歌单', playlists, format_func=lambda p:f"{p['name']} · {p['count']} 首")
                if st.button('导入所选歌单', key='web_import_selected'):
                    try:
                        import_rows(root, plan, selected['id'])
                    except (ValueError, WebQQError) as exc:
                        st.error(str(exc))
    with details:
        st.caption('从 QQ 音乐补充发行时间、语言、版本、流派及歌词，每次最多 30 首，缓存成功结果。')
        if st.button('补充歌曲资料', key='web_enrich'):
            progress = st.progress(0, text='正在补充资料…')
            try:
                report = run(enrich(plan, root/'artifacts', st.session_state.get('web_qq_credential'),
                    progress=lambda done,total:progress.progress(done/max(total,1),text=f'正在补充 · {done}/{total}')))
                invalidate()
                st.session_state.web_enrich_message = f"新增 {report['matched']} 首，复用 {report['cached']} 首，失败 {report['errors']} 首，待继续 {report['remaining']} 首。"
                st.rerun()
            except WebQQError as exc:
                st.error(str(exc))
        if st.session_state.get('web_enrich_message'):
            st.info(st.session_state.web_enrich_message)
    with ai:
        model_controls(root)
