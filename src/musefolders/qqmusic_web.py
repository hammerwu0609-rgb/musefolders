"""Read-only web adapter. Per-visitor credentials live only in session memory."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
import html
import json
import time
import logging
from pathlib import Path
from .personal_library import MAX_TRACKS, normalize_records
from .qqmusic_catalog import VERSION, version_tags


class WebQQError(RuntimeError):
    pass


def run(operation):
    try:
        return asyncio.run(operation)
    except WebQQError:
        raise
    except Exception as exc:
        # Upstream exceptions may contain request credentials. Never expose them.
        chain=[]
        current=exc
        while current is not None and len(chain)<4:
            chain.append(type(current).__name__)
            current=current.__cause__ or current.__context__
        logging.getLogger(__name__).warning('QQ web request failed (%s)', ' / '.join(chain))
        raise WebQQError('QQ 音乐接口暂时不可用或登录已失效，请重试或重新扫码登录。') from None


def client(credential=None):
    from qqmusic_api import Client
    from qqmusic_api.core import Platform
    from qqmusic_api.core.api_context import ApiContext
    from niquests import AsyncSession
    api=Client(credential=credential, platform=Platform.WEB, rate=3, capacity=3)
    # qqmusic-api-python 0.7.3 has no transport injection argument. Adapt the
    # pinned SDK context to HTTP/1 over IPv4 for container networks without
    # HTTP/3 or IPv6 routes; certificate verification remains enabled.
    session=AsyncSession(multiplexed=False,disable_http2=True,disable_http3=True,
                         disable_ipv6=True,timeout=20,allow_incoming_cookies=False)
    api._session=session
    api._context=ApiContext(credential,platform=Platform.WEB,session=session)
    return api


async def new_qr():
    from qqmusic_api.models.login import QRLoginType
    async with client() as api:
        qr = await asyncio.wait_for(api.login.get_qrcode(QRLoginType.QQ), 25)
        return qr, time.monotonic()


async def poll_qr(qr):
    async with client() as api:
        result = await asyncio.wait_for(api.login.check_qrcode(qr), 25)
        return result.event.name, result.credential


def song_record(song):
    return {'mid': song.mid, 'title': song.title or song.name,
            'artist': '/'.join(s.name for s in song.singer), 'album': song.album.name,
            'duration_seconds': song.interval, 'publish_date': song.time_public}


async def list_playlists(credential):
    async with client(credential) as api:
        response = await asyncio.wait_for(api.user.get_created_songlist(credential.musicid), 30)
        return [{'id': p.id, 'dirid': p.dirid, 'name': p.title, 'count': p.songnum}
                for p in response.playlists if p.id]


async def fetch_collection(identifier=None, credential=None, progress=None):
    """Paginate explicitly, detect truncated/repeated pages instead of claiming success."""
    async with client(credential) as api:
        if identifier is None and not credential:
            raise WebQQError('请先登录，再读取“我喜欢”。')
        euin = credential.encrypt_uin if credential else ''
        if identifier is None and not euin:
            playlists = await list_playlists(credential)
            liked = next((p for p in playlists if p['dirid'] == 201), None)
            if not liked:
                raise WebQQError('未找到“我喜欢”歌单，请刷新歌单列表或使用歌曲清单导入。')
            identifier = liked['id']
        rows, seen = [], set()
        for page in range(1, MAX_TRACKS // 100 + 2):
            request = (api.user.get_fav_song(euin, page=page, num=100) if identifier is None
                       else api.songlist.get_detail(identifier, page=page, num=100))
            response = await asyncio.wait_for(request, 35)
            songs = response.songs
            new = [song for song in songs if song.mid and song.mid not in seen]
            if songs and not new:
                raise WebQQError('接口重复返回同一页，未导入不完整的收藏。请稍后重试。')
            rows.extend(song_record(s) for s in new)
            seen.update(s.mid for s in new)
            if len(rows) > MAX_TRACKS or response.total > MAX_TRACKS:
                raise WebQQError(f'当前演示最多导入 {MAX_TRACKS} 首，请选择较小的歌单。')
            if progress:
                progress(len(rows), response.total)
            if len(rows) >= response.total and not response.hasmore:
                return normalize_records(rows)
            if not songs or not response.hasmore:
                if len(rows) < response.total:
                    raise WebQQError('接口返回的歌曲少于收藏总数，未替换当前曲库。')
                return normalize_records(rows)
        raise WebQQError('歌单分页未完成，请稍后重试。')


async def enrich(plan, artifacts: Path, credential=None, *, batch=30, progress=None):
    """Bounded batches; atomically checkpoint each song and retry partial failures."""
    path = artifacts / 'platform_catalog.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {'version': VERSION, 'provider':'qqmusic', 'tracks':{}}
    pending, cached, no_mid = [], 0, 0
    now = datetime.now(timezone.utc)
    for track in plan.tracks:
        entry = data['tracks'].get(track.track_id, {})
        mid = entry.get('mid') or track.metadata.source_track_id
        if not mid:
            no_mid += 1
            continue
        try:
            fresh = datetime.fromisoformat(entry['web_checked_at']) > now-timedelta(days=30)
        except (KeyError, ValueError, TypeError):
            fresh = False
        if fresh and not entry.get('web_error') and not entry.get('lyrics_error'):
            cached += 1
        else:
            pending.append((track, entry, mid))
    matched = errors = 0
    lyric_dir = artifacts / 'platform_lyrics'
    lyric_dir.mkdir(parents=True, exist_ok=True)
    async with client(credential) as api:
        for index, (track, entry, mid) in enumerate(pending[:batch]):
            try:
                detail = await asyncio.wait_for(api.song.get_detail(mid), 25)
                row = song_record(detail.track)
                row['publish_date'] = next((p.value for p in detail.pub_time if p.value), row['publish_date'])
                row['language'] = '/'.join(p.value for p in detail.lan)
                row['genre'] = '/'.join(p.value for p in detail.genre)
                date = row['publish_date']
                entry = {**entry, **row, 'status':'matched', 'source_sha256':track.source_sha256,
                         'release_year': int(date[:4]) if date[:4].isdigit() else None,
                         'version':detail.track.subtitle,
                         'version_tags':list(version_tags(row['title']+' '+detail.track.subtitle)),
                         'web_checked_at':now.isoformat(), 'web_error':False}
                try:
                    response = await asyncio.wait_for(api.lyric.get_lyric(mid), 25)
                    lyrics = html.unescape(response.lyric)
                    if lyrics.strip():
                        (lyric_dir / (mid+'.lrc')).write_text(lyrics[:200000], encoding='utf-8')
                    entry.update(has_lyrics=bool(lyrics.strip()), lyrics_error=False)
                except Exception:
                    entry.update(lyrics_error=True)
                matched += 1
            except Exception:
                entry = {**entry, 'web_error':True}
                errors += 1
            data['tracks'][track.track_id] = entry
            temporary = path.with_suffix('.pending')
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
            if progress:
                progress(index+1, min(batch, len(pending)))
    return {'matched':matched, 'errors':errors, 'cached':cached, 'no_mid':no_mid,
            'remaining':max(0,len(pending)-batch), 'lyrics_errors':sum(bool(v.get('lyrics_error')) for v in data['tracks'].values())}
