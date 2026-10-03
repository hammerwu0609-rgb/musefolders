import json
from types import SimpleNamespace

import pytest

from musefolders.intent_assistant import IntentAssistantError, translate_request


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(self.payload, ensure_ascii=False)}}]}, ensure_ascii=False).encode("utf-8")


def test_ai_request_sends_only_query_and_validates_result():
    seen = []
    def open_request(outbound, timeout):
        seen.append((outbound, timeout))
        return FakeResponse({"intent": {"themes": ["暗恋"], "tempo_max": 95}, "unsupported": []})
    intent = translate_request("找暗恋、慢一点的歌", api_key="test-key", consent=True, opener=open_request)
    assert intent.themes == ("暗恋",) and intent.tempo_max == 95
    sent = json.loads(seen[0][0].data)
    assert sent["messages"][1]["content"] == "找暗恋、慢一点的歌"
    assert "C:\\" not in json.dumps(sent)
    assert "Bearer test-key" == seen[0][0].get_header("Authorization")


def test_ai_rejects_unsupported_and_bad_schema():
    def unsupported(*_args, **_kwargs):
        return FakeResponse({"intent": {"themes": ["爱情"]}, "unsupported": ["适合夜晚"]})
    with pytest.raises(IntentAssistantError, match="夜晚"):
        translate_request("适合夜晚的爱情歌", api_key="key", consent=True, opener=unsupported)
    def invalid(*_args, **_kwargs):
        return FakeResponse({"intent": {"themes": ["爱情"], "private_path": "x"}, "unsupported": []})
    with pytest.raises(IntentAssistantError, match="词表"):
        translate_request("爱情", api_key="key", consent=True, opener=invalid)
    with pytest.raises(IntentAssistantError, match="启用"):
        translate_request("爱情", api_key="key", consent=False, opener=invalid)


def test_ai_accepts_bedtime_scene_with_theme_and_explicit_constraints():
    def response(outbound, timeout):
        system = json.loads(outbound.data)["messages"][0]["content"]
        assert "Scene preferences are supported" in system
        return FakeResponse({"intent": {"scene": "睡前", "themes": ["爱情"], "tempo_max": 100}, "unsupported": []})
    intent = translate_request("睡前听的爱情歌，速度不超过100BPM", api_key="key", consent=True, opener=response)
    assert intent.scene == "睡前" and intent.themes == ("爱情",) and intent.tempo_max == 100
    assert any("场景偏好" in condition for condition in intent.conditions())
