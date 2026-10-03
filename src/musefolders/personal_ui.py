"""Visitor-scoped collection management, including explicit QR login."""
from pathlib import Path
import json
import shutil
import time
import streamlit as st
from .personal_library import parse_upload, playlist_id, build_personal_plan
from .qqmusic_web import WebQQError, run, new_qr, poll_qr, fetch_collection, list_playlists, enrich


def invalidate():
    for key in ('simple_profiles','simple_results','simple_conditions','simple_summary',
                'simple_card','simple_draft_identity','consumer_audio','consumer_share',
                'consumer_message','consumer_download'):
        st.session_state.pop(key, None)


def activate(rows, root, plan):
    if 'personal_reference_plan' not in st.session_state:
        st.session_state.personal_reference_plan = plan
        folder = root / 'reference_artifacts'
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('platform_catalog.json','artist_regions.json'):
            path = root / 'artifacts' / name
            if path.is_file():
                shutil.copy2(path, folder / name)
    reference = st.session_state.personal_reference_plan
    new = build_personal_plan(rows, root, reference, root / 'reference_artifacts')
    st.session_state.simple_plan = new
    st.session_state.personal_active = True
    st.session_state.personal_lyrics_offset = 0
    st.session_state.pop('personal_enrich_message', None)
    st.session_state.personal_import_message = f'已导入 {len(new.tracks)} 首；其中 {sum(Path(t.source_path).is_file() for t in new.tracks)} 首有可用本地音频。'
    st.session_state.simple_edit_library = False
    invalidate()
    st.rerun()


def qq_login():
    credential = st.session_state.get('web_qq_credential')
    if credential:
        st.success('QQ 音乐已连接 · 账号尾号 '+str(credential.musicid)[-4:])
        if st.button('断开 QQ 音乐连接', key='web_qq_disconnect'):
            for name in ('web_qq_credential','web_qq_qr','web_qq_playlists','web_qq_login_message'):
                st.session_state.pop(name, None)
            st.session_state.pop('web_qq_pick', None)
            st.rerun()
        return
    st.caption('用手机 QQ 扫码并确认。登录凭据仅保存在本次访问的服务器会话中，退出连接后清除。')
    if st.button('生成 / 刷新 QQ 登录二维码', key='web_qq_start'):
        st.session_state.pop('web_qq_qr', None)
        try:
            st.session_state.web_qq_qr = run(new_qr())
            st.session_state.pop('web_qq_login_message', None)
        except WebQQError as exc:
            st.error(str(exc))
    @st.fragment(run_every=3 if st.session_state.get('web_qq_qr') else None)
    def polling():
        saved = st.session_state.get('web_qq_qr')
        if not saved:
            message = st.session_state.get('web_qq_login_message')
            if message:
                st.info(message)
            return
        qr, started = saved
        if time.monotonic()-started > 180:
            st.session_state.pop('web_qq_qr', None)
            st.session_state.web_qq_login_message = '二维码已过期，请重新生成。'
            st.rerun()
        st.image(qr.data, width=220)
        if st.button('取消扫码', key='web_qq_cancel'):
            st.session_state.pop('web_qq_qr', None)
            st.rerun()
        try:
            event, result = run(poll_qr(qr))
        except WebQQError:
            st.warning('暂时无法检查扫码状态，请稍后或重新生成二维码。')
            return
        if event == 'DONE' and result and result.musicid and result.musickey:
            st.session_state.web_qq_credential = result
            st.session_state.pop('web_qq_qr', None)
            st.rerun()
        elif event in {'TIMEOUT','REFUSE'}:
            st.session_state.pop('web_qq_qr', None)
            st.session_state.web_qq_login_message = '二维码已过期。' if event=='TIMEOUT' else '已取消登录。'
            st.rerun()
        st.caption('已扫码，请在手机上确认。' if event=='CONF' else '等待手机 QQ 扫码…')
    polling()


def personal_management(root: Path, plan):
    source, connect, details = st.tabs(['导入收藏','QQ 音乐连接','补全资料'])
    with source:
        st.caption('导入后切换到你的收藏。资料清单不包含音频；没有音频的歌曲可在 QQ 音乐打开，暂不参与听感星图和氛围分析。')
        uploaded = st.file_uploader('歌曲清单（JSON / CSV）', type=['json','csv'], max_upload_size=5, key='personal_upload')
        st.caption('字段：title、artist、mid、album、duration_seconds。MID 可选，补全 QQ 资料需要 MID。支持 qqmusic-mcp 导出的 liked.json / liked.csv。')
        st.download_button('下载 CSV 模板', 'title,artist,mid,album,duration_seconds\n晴天,周杰伦,0039MnYb0qxYhV,叶惠美,269\n'.encode('utf-8-sig'), '收藏导入模板.csv', 'text/csv')
        if st.button('导入歌曲清单', disabled=uploaded is None, key='personal_import_file'):
            try:
                activate(parse_upload(uploaded.getvalue(), uploaded.name), root, plan)
            except ValueError as exc:
                st.error(str(exc))
        with st.expander('也可以粘贴 JSON 歌曲清单'):
            pasted=st.text_area('歌曲 JSON',height=120,max_chars=300000,key='personal_paste',placeholder='[{"title":"晴天","artist":"周杰伦","mid":"0039MnYb0qxYhV"}]')
            if st.button('导入粘贴的清单',disabled=not pasted.strip(),key='personal_import_paste'):
                try:
                    activate(parse_upload(pasted.encode('utf-8'),'songs.json'),root,plan)
                except ValueError as exc:
                    st.error(str(exc))
        url = st.text_input('QQ 音乐歌单链接 / ID', key='personal_playlist_url', placeholder='粘贴完整歌单链接或数字 ID')
        if st.button('读取并导入这个歌单', key='personal_import_url'):
            try:
                identifier = playlist_id(url)
                progress = st.progress(0, text='正在读取歌单…')
                rows = run(fetch_collection(identifier, st.session_state.get('web_qq_credential'),
                    lambda done,total: progress.progress(min(done/max(total,1),1), text=f'正在读取 · {done}/{total}')))
                activate(rows, root, plan)
            except (ValueError, WebQQError) as exc:
                st.error(str(exc))
        if st.session_state.get('personal_active'):
            rows = [{'mid':t.metadata.source_track_id, 'title':t.metadata.title, 'artist':t.metadata.artist,
                     'album':t.metadata.album,'duration_seconds':t.acoustic.duration_s} for t in plan.tracks]
            from .qqmusic_catalog import cached_platform
            records = cached_platform(plan.tracks, root/'artifacts')
            rows = [{**row, **{k:v for k,v in records.get(t.track_id,{}).items() if k in ('mid','title','artist','album','duration_seconds','language','genre','publish_date','version')}}
                    for row,t in zip(rows,plan.tracks)]
            st.download_button('导出我的收藏资料', json.dumps({'songs':rows}, ensure_ascii=False,indent=2).encode(), '我的收藏.json','application/json')
            if st.button('返回固定演示曲库', key='personal_restore'):
                from .demo_mode import prepare_workspace
                bundle = st.session_state.get('simple_demo_bundle')
                if bundle:
                    prepare_workspace(Path(bundle), root)
                st.session_state.simple_plan = st.session_state.personal_reference_plan
                st.session_state.personal_active = False
                st.session_state.pop('personal_import_message', None)
                st.session_state.simple_edit_library = False
                invalidate()
                st.rerun()
    with connect:
        qq_login()
        credential = st.session_state.get('web_qq_credential')
        if credential:
            if st.button('导入“我喜欢”全部收藏', key='web_qq_liked'):
                try:
                    progress = st.progress(0,text='正在读取收藏…')
                    rows = run(fetch_collection(credential=credential, progress=lambda done,total: progress.progress(min(done/max(total,1),1),text=f'正在读取 · {done}/{total}')))
                    activate(rows,root,plan)
                except (WebQQError,ValueError) as exc:
                    st.error(str(exc))
            if st.button('读取我的歌单列表', key='web_qq_list'):
                try:
                    st.session_state.web_qq_playlists = run(list_playlists(credential))
                except WebQQError as exc:
                    st.error(str(exc))
            lists = st.session_state.get('web_qq_playlists', [])
            if lists:
                chosen = st.selectbox('选择要导入的歌单', lists, format_func=lambda p:f"{p['name']} · {p['count']} 首", key='web_qq_pick')
                if st.button('导入所选歌单',key='web_qq_import_selected'):
                    try:
                        activate(run(fetch_collection(chosen['id'],credential)),root,plan)
                    except (WebQQError,ValueError) as exc:
                        st.error(str(exc))
    with details:
        if st.session_state.get('personal_import_message'):
            st.info(st.session_state.personal_import_message)
        st.caption('补全发行时间、语言、版本、流派和歌词。每次最多 30 首，完成结果缓存 30 天；失败可重试。')
        if st.button('从 QQ 音乐补全资料',key='web_qq_enrich'):
            progress=st.progress(0,text='正在补全资料…')
            try:
                report=run(enrich(plan,root/'artifacts',st.session_state.get('web_qq_credential'),progress=lambda done,total:progress.progress(done/max(total,1),text=f'正在补全 · {done}/{total}')))
                invalidate()
                st.session_state.personal_enrich_message=f"新增 {report['matched']} 首，复用 {report['cached']} 首；失败 {report['errors']} 首，歌词失败 {report['lyrics_errors']} 首，待继续 {report['remaining']} 首，缺少 MID {report['no_mid']} 首。"
                st.rerun()
            except WebQQError as exc:
                st.error(str(exc))
        if st.session_state.get('personal_enrich_message'):
            st.info(st.session_state.personal_enrich_message)
        st.caption('地图地区由艺人档案补充，不根据歌曲语言猜测。')
        if st.button('补充音乐星球地区',key='web_qq_regions'):
            from .artist_regions import enrich_regions
            progress=st.progress(0,text='正在读取艺人地区…')
            report=enrich_regions([t.metadata.artist for t in plan.tracks],root/'artifacts',progress=lambda done,total,name:progress.progress(done/max(total,1),text=f'正在补充 · {done}/{total}'))
            st.success(f"新增 {report['matched']} 位，缓存 {report['cached']} 位，待补充 {report['unknown']} 位。")
        st.caption('有歌词后，可交给已配置的模型生成主题标签。')
        if st.button('AI 分析收藏歌词',key='web_qq_lyrics'):
            from .ai_lyrics import analyze_lyrics, LyricAnalysisError
            from .model_settings import active_settings
            from .qqmusic_catalog import cached_platform, platform_lyrics
            from .demo_mode import check_ai_budget
            settings=active_settings(root)
            if not settings.api_key:
                st.warning('请先在服务器配置模型密钥。')
            else:
                # One batch counts against the shared budget per eligible song, not just
                # per click. Slice the batch so public users cannot trigger 2000 calls.
                offset=st.session_state.get('personal_lyrics_offset',0)
                batch=plan.tracks[offset:offset+5]
                try:
                    for _ in batch:
                        check_ai_budget()
                    fresh,cached,eligible=analyze_lyrics(batch,Path(plan.source_root),root/'artifacts',api_key=settings.api_key,api_url=settings.api_url,model=settings.model,fallback_sources=platform_lyrics(cached_platform(plan.tracks,root/'artifacts'),root/'artifacts'))
                    st.session_state.personal_lyrics_offset = offset+len(batch) if offset+len(batch)<len(plan.tracks) else 0
                    invalidate()
                    st.success(f'本批新分析 {fresh} 首，缓存 {cached} 首；再次点击继续下一批。')
                except (LyricAnalysisError,RuntimeError) as exc:
                    st.warning(str(exc))
