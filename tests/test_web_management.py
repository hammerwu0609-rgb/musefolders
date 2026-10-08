import pytest
from musefolders.model_settings import ModelSettings, ModelSettingsError
from musefolders.web_management import candidate, form_candidate


def test_successfully_tested_secret_survives_cleared_form():
    tested = ModelSettings('https://api.deepseek.com/chat/completions', 'deepseek-chat', 'private-test-key')
    assert form_candidate('https://api.deepseek.com', 'deepseek-chat', '', ModelSettings(), tested) == tested
    assert 'private-test-key' not in repr(tested)


def test_tested_secret_cannot_follow_changed_endpoint_or_model():
    tested = ModelSettings('https://api.deepseek.com/chat/completions', 'deepseek-chat', 'private-test-key')
    for url, model in [('https://other.example', 'deepseek-chat'), ('https://api.deepseek.com', 'other-model')]:
        with pytest.raises(ModelSettingsError):
            form_candidate(url, model, '', ModelSettings(), tested)


def test_explicit_replacement_key_wins_over_tested_secret():
    tested = ModelSettings('https://api.deepseek.com/chat/completions', 'deepseek-chat', 'private-test-key')
    assert form_candidate('https://api.deepseek.com', 'deepseek-chat', 'replacement', ModelSettings(), tested).api_key == 'replacement'


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
