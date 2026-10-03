"""Sourced artist-region metadata for the consumer globe, separate from language."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

API = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = "MuseFolders/0.1 (https://github.com/hammerwu0609-rgb/musefolders)"
# ISO 3166-1 codes, Chinese display names and approximate globe focus coordinates.
REGIONS = {
    'CN': ('156','中国',[104,35]), 'JP': ('392','日本',[138,37]),
    'KR': ('410','韩国',[128,36]), 'US': ('840','美国',[-100,38]),
    'GB': ('826','英国',[-2,54]), 'DE': ('276','德国',[10,51]),
    'FR': ('250','法国',[2,47]), 'SE': ('752','瑞典',[15,62]),
    'NO': ('578','挪威',[10,62]), 'IE': ('372','爱尔兰',[-8,53]),
    'CH': ('756','瑞士',[8,47]), 'BE': ('056','比利时',[4,51]),
    'NL': ('528','荷兰',[5,52]), 'AU': ('036','澳大利亚',[134,-25]),
    'CA': ('124','加拿大',[-106,56]), 'NZ': ('554','新西兰',[174,-41]),
    'IT': ('380','意大利',[12,43]), 'ES': ('724','西班牙',[-4,40]),
    'AT': ('040','奥地利',[14,48]), 'FI': ('246','芬兰',[26,64]),
    'DK': ('208','丹麦',[10,56]), 'IS': ('352','冰岛',[-19,65]),
    'HK': ('344','中国香港',[114.2,22.3]), 'TW': ('158','中国台湾',[121,24]),
    'BR': ('076','巴西',[-52,-14]), 'IN': ('356','印度',[79,22]),
}


def primary_artist(value: str) -> str:
    """Use the first credited artist; collaborations remain explicit in song credits."""
    return re.split(r"/|、|\s+feat\.?\s+", value, flags=re.I)[0].strip()


def _name(value: str) -> str:
    value = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", value)
    return re.sub(r"[^\w]", "", unicodedata.normalize('NFKC', value).casefold())


def _candidate(name: str, candidates: list[dict]) -> dict | None:
    matches = []
    for artist in candidates:
        if not isinstance(artist, dict) or int(artist.get('score', 0)) < 95:
            continue
        names = [artist.get('name',''), artist.get('sort-name','')]
        names.extend(alias.get('name','') for alias in artist.get('aliases',[]) if isinstance(alias,dict))
        if _name(name) and any(_name(str(candidate)) == _name(name) for candidate in names):
            matches.append(artist)
    unique = {artist.get('id'):artist for artist in matches if artist.get('id')}
    if len(unique) != 1:
        return None
    return next(iter(unique.values()))


def choose_artist(name: str, candidates: list[dict]) -> dict | None:
    artist = _candidate(name,candidates)
    if not artist:
        return None
    code = artist.get('country')
    if not code:
        iso = (artist.get('area') or {}).get('iso-3166-1-codes', [])
        code = iso[0] if len(iso) == 1 else None
    if code not in REGIONS:
        return None
    numeric, label, center = REGIONS[code]
    return {'country':numeric, 'label':label, 'center':center,
            'artist':artist['name'], 'mbid':artist['id'],
            'source':f"https://musicbrainz.org/artist/{artist['id']}",
            'fetched_at':datetime.now(timezone.utc).isoformat(), 'basis':'musicbrainz_country'}


def read_regions(artifacts: Path) -> dict:
    path = artifacts / 'artist_regions.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def region_for_artist(regions: dict, credit: str) -> dict:
    primary = primary_artist(credit)
    direct = regions.get(credit, regions.get(primary))
    if isinstance(direct,dict):
        return direct
    # Reuse an already sourced fact for a formatting alias such as
    # やまだ豊 and やまだ豊 (山田豊), without guessing from a language.
    facts = [fact for name,fact in regions.items() if isinstance(fact,dict)
             and _name(name) == _name(primary) and fact.get('source')]
    identities = {(fact.get('source'),fact.get('country')) for fact in facts}
    return facts[0] if facts and len(identities)==1 else {}


def _save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.stem}-{uuid.uuid4().hex}.tmp')
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def enrich_regions(artists, artifacts: Path, *, progress=None, opener=urlopen, delay=1.1) -> dict:
    regions = read_regions(artifacts)
    report = {'matched':0,'cached':0,'unknown':0,'errors':0,'total':0}
    artists = sorted({primary_artist(str(name)) for name in artists if primary_artist(str(name))})
    report['total'] = len(artists)
    try:
        previous = json.loads((artifacts/'artist_regions_audit.json').read_text(encoding='utf-8'))
        audit = previous.get('results', {}) if isinstance(previous,dict) else {}
    except (OSError,ValueError):
        audit = {}
    last_request = 0.
    for index,name in enumerate(artists):
        cached = region_for_artist(regions,name)
        if cached.get('source') and cached.get('country'):
            report['cached'] += 1
            regions[name] = cached
            audit[name] = {'status':'matched','source':cached['source']}
        else:
            try:
                remaining = max(1.0,delay) - (time.monotonic()-last_request)
                if remaining > 0:
                    time.sleep(remaining)
                query_name = re.sub(r'\s*[（(][^）)]*[）)]\s*$','',name).replace('\\','\\\\').replace('"','\\"')
                request = Request(API+'?'+urlencode({'query':f'artist:"{query_name}"','fmt':'json','limit':10}),
                                  headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
                last_request = time.monotonic()
                with opener(request,timeout=15) as response:
                    data = json.load(response)
                candidates = data.get('artists',[]) if isinstance(data,dict) else []
                fact = choose_artist(name,candidates)
                candidate = _candidate(name,candidates)
                if not fact and candidate and re.fullmatch(r'[a-f0-9-]{36}',str(candidate.get('id',''))):
                    # Artist search omits country for some entries. Resolve the
                    # already unique identity via its full artist record.
                    remaining = max(1.0,delay) - (time.monotonic()-last_request)
                    if remaining > 0:
                        time.sleep(remaining)
                    request = Request(API+candidate['id']+'?fmt=json',headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
                    last_request = time.monotonic()
                    with opener(request,timeout=15) as response:
                        detail = json.load(response)
                    if isinstance(detail,dict) and detail.get('id') == candidate['id']:
                        detail['score'] = 100
                        # Identity is resolved by the search, so retain its alias
                        # for matching without inventing a new artist identity.
                        detail['aliases'] = list(detail.get('aliases') or [])+[{'name':name}]
                        fact = choose_artist(name,[detail])
                if fact:
                    regions[name] = fact
                    report['matched'] += 1
                    audit[name] = {'status':'matched','source':fact['source']}
                    _save(artifacts/'artist_regions.json',regions)
                else:
                    report['unknown'] += 1
                    audit[name] = {'status':'unknown','candidates':[
                        {'name':a.get('name'),'id':a.get('id'),'country':a.get('country'),'score':a.get('score')}
                        for a in candidates if isinstance(a,dict)]}
            except (OSError,ValueError,TypeError,KeyError) as exc:
                report['errors'] += 1
                audit[name] = {'status':'request_failed','error_type':type(exc).__name__}
        if progress:
            progress(index+1,len(artists),name)
        _save(artifacts/'artist_regions_audit.json',{'report':report,'results':audit})
    _save(artifacts/'artist_regions.json',regions)
    return report
