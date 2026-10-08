import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from musefolders.demo_mode import prepare_workspace, DemoBudget, portable_playlist_bytes
from musefolders.intent_assistant import IntentAssistantError


def bundle(root):
    source=root/'bundle'
    (source/'audio').mkdir(parents=True)
    (source/'audio/one.mp3').write_bytes(b'audio')
    (source/'collection_plan.json').write_text(json.dumps({'source_root':'audio','tracks':[{'source_path':'audio/one.mp3'}]}),encoding='utf-8')
    (source/'user_annotations.json').write_text('{}',encoding='utf-8')
    return source


def test_demo_workspaces_are_independent_and_sources_shared(tmp_path):
    source=bundle(tmp_path)
    first=prepare_workspace(source,tmp_path/'first')
    second=prepare_workspace(source,tmp_path/'second')
    one=json.loads((first/'artifacts/collection_plan.json').read_text(encoding='utf-8'))
    two=json.loads((second/'artifacts/collection_plan.json').read_text(encoding='utf-8'))
    assert one==two
    assert Path(one['tracks'][0]['source_path']).is_file()
    (first/'artifacts/user_annotations.json').write_text('{"changed":true}',encoding='utf-8')
    assert (second/'artifacts/user_annotations.json').read_text()=='{}'
    assert (source/'user_annotations.json').read_text()=='{}'


def test_demo_rejects_path_traversal(tmp_path):
    source=bundle(tmp_path)
    (source/'collection_plan.json').write_text(json.dumps({'tracks':[{'source_path':'../private.mp3'}]}),encoding='utf-8')
    with pytest.raises(ValueError,match='Invalid'):
        prepare_workspace(source,tmp_path/'guest')


def test_shared_budget_prevents_session_and_global_bursts():
    budget=DemoBudget()
    session=[]
    for stamp in range(5):budget.acquire(session,now=stamp,hourly=6)
    with pytest.raises(IntentAssistantError,match='每分钟'):
        budget.acquire(session,now=10,hourly=6)
    budget.acquire([],now=10,hourly=6)
    with pytest.raises(IntentAssistantError,match='本小时'):
        budget.acquire([],now=11,hourly=6)
    budget.acquire(session,now=3605,hourly=6)
    assert session==[3605]


def test_cloud_export_has_no_server_path():
    track=SimpleNamespace(source_path='/tmp/private-server/audio/song.mp3',metadata=SimpleNamespace(title='Song',artist='Artist'),acoustic=SimpleNamespace(duration_s=120))
    text=portable_playlist_bytes([track]).decode('utf-8-sig')
    assert '/tmp/' not in text and 'Song - Artist' in text and 'song.mp3' in text
