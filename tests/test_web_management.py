import pytest
from musefolders.model_settings import ModelSettings, ModelSettingsError
from musefolders.web_management import candidate


def test_server_key_cannot_follow_a_visitor_endpoint_change():
    server = ModelSettings('https://api.deepseek.com/chat/completions', 'deepseek-chat', 'server-test-key')
    with pytest.raises(ModelSettingsError):
        candidate('https://other.example/v1', 'other-model', '', server)
    assert server.api_key == 'server-test-key'
    visitor = candidate('https://other.example/v1', 'other-model', 'visitor-test-key', server)
    assert visitor.api_key == 'visitor-test-key'
    assert visitor.api_url == 'https://other.example/v1/chat/completions'


def test_blank_key_keeps_only_the_same_normalized_endpoint():
    server = ModelSettings('https://api.deepseek.com/chat/completions', 'deepseek-chat', 'server-test-key')
    assert candidate('https://api.deepseek.com/', 'deepseek-chat', '', server) == server
    with pytest.raises(ModelSettingsError):
        candidate('https://api.deepseek.com', 'deepseek-chat', '', ModelSettings())
