import json
from urllib import error
import pytest
from musefolders import model_settings as ms
from musefolders.intent_assistant import translate_request
from musefolders.ai_lyrics import classify_lyrics

class Response:
    def __init__(self, content):
        self.content = content
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size):
        return json.dumps({"choices": [{"message": {"content": self.content}, "finish_reason": "stop"}]}).encode()


def test_config_normalization_and_validation():
    assert ms.validate(ms.ModelSettings("https://example.com/v1/", " model ", "key")).api_url == "https://example.com/v1/chat/completions"
    assert ms.validate(ms.ModelSettings("http://127.0.0.1:8000/v1", "local", "key")).model == "local"
    for url in ["http://example.com", "https://user:password@example.com", "https://example.com?key=secret", "https://example.com/#secret", "file:///tmp"]:
        with pytest.raises(ms.ModelSettingsError):
            ms.validate(ms.ModelSettings(url, "model", "key"))
    assert "secret-key" not in repr(ms.ModelSettings(api_key="secret-key"))


def test_encrypted_save_reload_delete_and_corruption(tmp_path, monkeypatch):
    # Reversible fake encryption tests persistence independently of Windows DPAPI.
    monkeypatch.setattr(ms, "_crypt", lambda data, decrypt=False: data[::-1])
    config = ms.ModelSettings("https://example.com/v1/chat/completions", "test-model", "synthetic-secret")
    ms.save_settings(tmp_path, config)
    assert b"synthetic-secret" not in ms.config_path(tmp_path).read_bytes()
    assert ms.load_settings(tmp_path) == config
    ms.config_path(tmp_path).write_bytes(b"broken")
    with pytest.raises(ms.ModelSettingsError): ms.load_settings(tmp_path)
    ms.delete_settings(tmp_path)
    assert ms.load_settings(tmp_path) is None


def test_connection_and_service_routing():
    captured = []
    def opener(req, **kwargs):
        captured.append((req.full_url, json.loads(req.data), req.get_header("Authorization")))
        return Response('{"ok":true}')
    config = ms.ModelSettings("https://example.com/v1/chat/completions", "other-model", "synthetic-key")
    ms.test_connection(config, opener=opener)
    assert captured[0][0] == config.api_url
    assert captured[0][1]["model"] == config.model
    assert "thinking" not in captured[0][1]
    assert captured[0][2] == "Bearer synthetic-key"
    def lyric(req, **kwargs):
        captured.append((req.full_url, json.loads(req.data)))
        return Response('{"themes":["爱情"]}')
    assert classify_lyrics("Title", "Lyrics", api_key=config.api_key, api_url=config.api_url, model=config.model, opener=lyric) == ("爱情",)
    def intent(req, **kwargs):
        captured.append((req.full_url, json.loads(req.data)))
        return Response('{"intent":{"themes":["爱情"]},"unsupported":[]}')
    assert translate_request("关于爱情", api_key=config.api_key, consent=True, api_url=config.api_url, model=config.model, opener=intent).themes == ("爱情",)
    for url, body in captured[1:]:
        assert url == config.api_url and body["model"] == config.model
        assert "thinking" not in body


def test_connection_errors_are_actionable_without_secrets():
    config = ms.ModelSettings(api_key="synthetic-secret")
    def fail(req, **kwargs):
        raise error.HTTPError(req.full_url, 401, "synthetic-secret", {}, None)
    with pytest.raises(ms.ModelSettingsError, match="密钥无效") as caught:
        ms.test_connection(config, opener=fail)
    assert "synthetic-secret" not in str(caught.value)
    with pytest.raises(ms.ModelSettingsError, match="有效 JSON"):
        ms.test_connection(config, opener=lambda *a, **kw: Response("invalid"))
