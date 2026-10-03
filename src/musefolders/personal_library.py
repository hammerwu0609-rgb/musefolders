"""Portable, bounded collection imports. Credentials and arbitrary paths are never imported."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import uuid
from copy import deepcopy
from pathlib import Path
from .models import AcousticFeatures, CollectionPlan, TrackEncoding, TrackMetadata
from .qqmusic_catalog import VERSION, cached_platform, choose_candidate, version_tags

MAX_TRACKS = 2000
MAX_BYTES = 5 * 1024 * 1024


def normalize_records(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TRACKS:
        raise ValueError(f"请提供 1–{MAX_TRACKS} 首歌曲。")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("歌曲清单格式不正确。")
        mid = str(row.get('mid') or row.get('songmid') or '').strip()
        if mid and not re.fullmatch(r'[A-Za-z0-9]{1,128}', mid):
            raise ValueError("歌曲 MID 格式不正确。")
        title = str(row.get('title') or row.get('name') or row.get('songname') or '').strip()[:500]
        artist = row.get('artist') or row.get('singers') or row.get('singer') or ''
        if isinstance(artist, list):
            artist = '/'.join(str(s.get('name', '')) if isinstance(s, dict) else str(s) for s in artist)
        if not title:
            raise ValueError("每首歌曲都需要歌名。")
        try:
            duration = float(row.get('duration_seconds') or row.get('interval') or row.get('duration') or 0)
        except (ValueError, TypeError):
            raise ValueError("歌曲时长应为秒数。") from None
        if not math.isfinite(duration) or not 0 <= duration <= 86400:
            raise ValueError("歌曲时长超出范围。")
        album = row.get('album') or ''
        if isinstance(album, dict):
            album = album.get('name', '')
        identity = mid or hashlib.sha256((title+'\0'+str(artist)+'\0'+str(duration)).encode()).hexdigest()
        if identity in seen:
            continue
        seen.add(identity)
        result.append({'mid': mid, 'title': title, 'artist': str(artist)[:500],
                       'album': str(album)[:500], 'duration_seconds': duration,
                       'publish_date': str(row.get('publish_date') or row.get('year') or '')[:40],
                       'language': str(row.get('language') or '')[:60],
                       'version': str(row.get('version') or '')[:100],
                       'genre': str(row.get('genre') or '')[:100]})
    return result


def parse_upload(raw: bytes, filename: str):
    if len(raw) > MAX_BYTES:
        raise ValueError("清单文件最大 5 MB。")
    try:
        text = raw.decode('utf-8-sig')
        if filename.lower().endswith('.csv'):
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get('songs', data.get('tracks'))
        return normalize_records(rows)
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        raise ValueError("请上传 UTF-8 编码的 JSON 或 CSV 歌曲清单。") from None


def playlist_id(text: str) -> int:
    text = text.strip()
    if re.fullmatch(r'\d{1,20}', text):
        return int(text)
    from urllib.parse import urlsplit, parse_qs
    url = urlsplit(text)
    if url.scheme != 'https' or url.hostname not in {'y.qq.com', 'i.y.qq.com'}:
        raise ValueError("请填写 QQ 音乐歌单 ID 或完整的 y.qq.com 歌单链接。")
    for key in ('id', 'disstid'):
        value = parse_qs(url.query).get(key, [''])[0]
        if re.fullmatch(r'\d{1,20}', value):
            return int(value)
    match = re.search(r'/(?:playlist|taoge)/(\d{1,20})(?:\.html)?(?:/|$)', url.path)
    if match:
        return int(match[1])
    raise ValueError("未找到歌单 ID，请复制完整歌单链接。")


def build_personal_plan(rows, root: Path, reference: CollectionPlan, reference_artifacts: Path):
    rows = normalize_records(rows)
    library = root / 'personal_audio'
    library.mkdir(parents=True, exist_ok=True)
    platform = cached_platform(reference.tracks, reference_artifacts)
    mid_tracks = {entry['mid']: reference.track_by_id()[tid] for tid, entry in platform.items() if entry.get('mid')}
    candidates = [{'mid': str(index), 'name': t.metadata.title,
                   'singers': t.metadata.artist.split('/'), 'duration_seconds': t.acoustic.duration_s}
                  for index,t in enumerate(reference.tracks) if Path(t.source_path).is_file()]
    tracks, entries = [], {}
    for row in rows:
        match = mid_tracks.get(row['mid']) if row['mid'] else None
        if match is None:
            candidate, _ = choose_candidate(row, candidates)
            match = reference.tracks[int(candidate['mid'])] if candidate else None
        identity = row['mid'] or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        tid = 'qq-' + identity
        if match and Path(match.source_path).is_file():
            track = deepcopy(match)
            track.track_id = tid
        else:
            # The legacy analysis schema requires a feature container. Zero-confidence
            # values are explicitly unavailable; standard=None excludes all sound maps.
            acoustic = AcousticFeatures(row['duration_seconds'], 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '', '', 0, 0)
            track = TrackEncoding(tid, str(library / (tid+'.missing')), 0, 0, 'qq:'+identity,
                                  TrackMetadata(row['title'], row['artist'], row['album'], row['genre'],
                                                row['publish_date'], row['mid'], 'qqmusic'), acoustic,
                                  warnings=['音频未提供，暂无听感分析'])
        tracks.append(track)
        date = row['publish_date']
        entries[tid] = {**row, 'status': 'matched', 'source_sha256': track.source_sha256,
                        'release_year': int(date[:4]) if re.match(r'^(18|19|20|21)\d{2}', date) else None,
                        'version_tags': list(version_tags(row['title']+' '+row['version']))}
    plan = CollectionPlan('personal-'+uuid.uuid4().hex, str(library), 'quant', [], tracks)
    artifacts = root / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    # Remove stale tags tied to a previous import; no reference demo annotations leak.
    for name in ('user_annotations.json', 'ai_lyrics_tags.json', 'tag_catalog.json'):
        (artifacts / name).unlink(missing_ok=True)
    (artifacts / 'collection_plan.json').write_text(json.dumps(plan.to_dict(), ensure_ascii=False), encoding='utf-8')
    (artifacts / 'platform_catalog.json').write_text(json.dumps({'version':VERSION, 'provider':'qqmusic', 'tracks':entries}, ensure_ascii=False), encoding='utf-8')
    return plan
