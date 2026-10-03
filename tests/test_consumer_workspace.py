import json
import pytest

from musefolders.consumer_workspace import parse_command, payload, edit_playlist, archive_playlist, saved_playlists, switch_playlist
from musefolders.playlist_draft import PlaylistDraft, apply_selection
from musefolders.tag_catalog import build_track_profiles
from musefolders.simple_ui import portrait_map
from musefolders.models import CollectionPlan, TrackEncoding, TrackMetadata, AcousticFeatures, StandardScores


def fixture_plan(root):
    tracks = []
    for index in range(2):
        path = root / f'{index}.mp3'
        path.write_bytes(b'test')
        acoustic = AcousticFeatures(120,80,.8,-15,8,1000,3000,.1,.1,2,.6,'C','major',.8,30)
        tracks.append(TrackEncoding(str(index),str(path),4,0,f'hash-{index}',TrackMetadata(f'歌曲{index}','歌手'),acoustic,
                                    standard=StandardScores(20,'quiet',30,40,50,60)))
    return CollectionPlan('test-analysis',str(root),'quant',[],tracks)


@pytest.mark.parametrize('text,expected', [
    ('关于爱情的歌', ('search','关于爱情的歌','')),
    ('找睡前听的歌，建一个「今晚」歌单', ('create','睡前听的歌','今晚')),
    ('把搜索结果建成「爱情」歌单', ('create','','爱情')),
    ('创建一个关于爱情的歌单', ('create','爱情','新歌单')),
    ('把搜索结果加入歌单', ('add','','')),
    ('把 Caravan 加入歌单', ('add','Caravan','')),
    ('从歌单移除Caravan', ('remove','Caravan','')),
    ('把Caravan从歌单移除', ('remove','Caravan','')),
])
def test_command_preserves_search_and_playlist_intent(text, expected):
    assert parse_command(text) == expected


def test_saved_playlist_switch_keeps_previous_and_rejects_paths(tmp_path):
    plan = fixture_plan(tmp_path)
    first = PlaylistDraft(plan.source_root, plan.analysis_id, name='第一张')
    apply_selection(first, plan, [plan.tracks[0].track_id], 'add', 'test')
    archive_playlist(tmp_path, first)
    identity = saved_playlists(tmp_path, plan)[0]['id']
    second = PlaylistDraft(plan.source_root, plan.analysis_id, name='第二张')
    apply_selection(second, plan, [plan.tracks[1].track_id], 'add', 'test')
    loaded = switch_playlist(tmp_path, plan, second, identity)
    assert loaded.name == '第一张' and loaded.items[0].track_id == plan.tracks[0].track_id
    assert {p['name'] for p in saved_playlists(tmp_path, plan)} == {'第一张','第二张'}
    with pytest.raises(ValueError):
        switch_playlist(tmp_path, plan, second, '../../data')


def test_payload_uses_sourced_regions_and_omits_paths(tmp_path):
    plan = fixture_plan(tmp_path)
    profiles = build_track_profiles(plan.tracks)
    draft = PlaylistDraft(plan.source_root,plan.analysis_id)
    p = payload(plan, profiles, draft, portrait_map(plan), tmp_path)
    assert all(t['country'] is None for t in p['tracks'])
    assert plan.source_root not in json.dumps(p)
    artist = profiles[plan.tracks[0].track_id].artist
    (tmp_path/'artist_regions.json').write_text(json.dumps({artist:{'country':'392','label':'日本'}}))
    assert payload(plan, profiles, draft, portrait_map(plan),tmp_path)['tracks'][0]['country'] is None
    (tmp_path/'artist_regions.json').write_text(json.dumps({artist:{'country':'392','label':'日本','source':'https://example.com/artist'}}))
    assert payload(plan, profiles, draft, portrait_map(plan),tmp_path)['tracks'][0]['country'] == '392'


def test_playlist_action_validates_track_and_move(tmp_path):
    plan = fixture_plan(tmp_path)
    draft = PlaylistDraft(plan.source_root,plan.analysis_id)
    with pytest.raises(ValueError):
        edit_playlist(draft,plan,{'kind':'add','id':'missing'})
    with pytest.raises(ValueError):
        edit_playlist(draft,plan,{'kind':'move','id':plan.tracks[0].track_id,'offset':100})


def test_map_supports_primary_credit_in_collaboration(tmp_path):
    plan=fixture_plan(tmp_path)
    plan.tracks[0].metadata.artist='First/Second'
    (tmp_path/'artist_regions.json').write_text(json.dumps({'First':{'country':'392','label':'日本','source':'https://musicbrainz.org/artist/example'}}))
    profiles=build_track_profiles(plan.tracks)
    draft=PlaylistDraft(plan.source_root,plan.analysis_id)
    value=payload(plan,profiles,draft,portrait_map(plan),tmp_path)
    assert value['tracks'][0]['country']=='392'
    assert value['regions']==[{'id':'392','name':'日本','center':[138,37]}]
