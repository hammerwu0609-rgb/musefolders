import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from musefolders.personal_library import parse_upload, playlist_id, build_personal_plan
from musefolders.models import CollectionPlan
from musefolders.simple_ui import portrait_map
from musefolders.qqmusic_catalog import cached_platform
from musefolders import qqmusic_web as web


def test_portable_import_strips_credentials_paths_and_duplicate_songs():
    rows=parse_upload(json.dumps({'songs':[{'name':'Song','singers':['Singer'],'mid':'abc123',
        'source_path':'C:/secret','cookie':'secret'},{'title':'Song','mid':'abc123'}]}).encode(),'liked.json')
    assert len(rows)==1 and rows[0]['artist']=='Singer'
    assert 'cookie' not in rows[0] and 'source_path' not in rows[0]
    with pytest.raises(ValueError):
        parse_upload(b'[{"title":"Song","mid":"../secret"}]','liked.json')
    with pytest.raises(ValueError):
        parse_upload(b'title,duration_seconds\nSong,NaN\n','liked.csv')


def test_link_parser_does_not_fetch_arbitrary_servers():
    assert playlist_id('https://y.qq.com/n/ryqq/playlist/123')==123
    assert playlist_id('https://y.qq.com/n/yqq/playlist/123.html')==123
    with pytest.raises(ValueError):
        playlist_id('https://evil.example/?id=123')


def test_metadata_only_is_searchable_but_never_fabricates_sound(tmp_path):
    plan=build_personal_plan([{'title':'Song','artist':'Singer','mid':'abc123'}],tmp_path,
                            CollectionPlan('reference',str(tmp_path/'reference'),'quant',[],[]),tmp_path/'reference')
    track=plan.tracks[0]
    assert track.standard is None and track.acoustic.tempo_confidence==0
    assert not Path(track.source_path).exists()
    assert not portrait_map(plan).points
    assert cached_platform(plan.tracks,tmp_path/'artifacts')[track.track_id]['mid']=='abc123'
    from musefolders.tag_catalog import build_track_profiles
    p=build_track_profiles(plan.tracks,platform_metadata=cached_platform(plan.tracks,tmp_path/'artifacts'))[track.track_id]
    assert p.activity is None and p.tempo_bpm is None


def test_each_visitor_has_independent_imports(tmp_path):
    ref=CollectionPlan('ref',str(tmp_path),'quant',[],[])
    a=build_personal_plan([{'title':'A','mid':'a1'}],tmp_path/'a',ref,tmp_path)
    b=build_personal_plan([{'title':'B','mid':'b1'}],tmp_path/'b',ref,tmp_path)
    assert a.source_root!=b.source_root
    assert set(cached_platform(a.tracks,tmp_path/'a'/'artifacts'))=={a.tracks[0].track_id}


def test_pagination_rejects_incomplete_and_repeated_pages(monkeypatch):
    song=NS(mid='a1',title='A',name='A',singer=[],album=NS(name=''),interval=10,time_public='')
    class API:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        @property
        def songlist(self): return self
        async def get_detail(self,*args,**kw):
            return NS(songs=[song],total=2,hasmore=1)
    monkeypatch.setattr(web,'client',lambda credential=None:API())
    with pytest.raises(web.WebQQError,match='重复'):
        asyncio.run(web.fetch_collection(123))
    async def short(*args,**kw): return NS(songs=[song],total=2,hasmore=0)
    API.get_detail=short
    with pytest.raises(web.WebQQError,match='少于'):
        asyncio.run(web.fetch_collection(123))


def test_web_errors_never_expose_credential():
    async def fail(): raise RuntimeError('secret-cookie=private')
    with pytest.raises(web.WebQQError) as error:
        web.run(fail())
    assert 'private' not in str(error.value)
