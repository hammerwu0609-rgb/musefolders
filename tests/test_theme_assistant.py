from __future__ import annotations

import json

import pytest

from musefolders.theme_assistant import (
    MAX_EXCERPT_CHARS,
    ThemeAssistantError,
    preview_theme_request,
    suggest_theme,
)


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps({"choices": [{"message": {"content": json.dumps({
            "themes": ["思念", "成长"], "explanation": "叙述离别后的成长。",
        }, ensure_ascii=False)}}]}).encode("utf-8")


def test_preview_is_bounded_and_uses_distant_sections() -> None:
    lyrics = "\n".join(f"line {index} " + "words " * 30 for index in range(40))
    preview = preview_theme_request(" Song ", lyrics)
    assert preview.title == "Song"
    assert len(preview.lyric_excerpt) <= MAX_EXCERPT_CHARS
    assert "line 0" in preview.lyric_excerpt
    assert "line 19" in preview.lyric_excerpt or "line 18" in preview.lyric_excerpt


def test_explicit_consent_gate_makes_no_request() -> None:
    preview = preview_theme_request("Song", "These are valid song lyrics")
    calls = []

    def opener(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    with pytest.raises(ThemeAssistantError, match="consent"):
        suggest_theme(preview, api_key="not-a-real-key", consent=False, opener=opener)
    assert not calls


def test_selected_excerpt_only_and_no_key_in_error() -> None:
    preview = preview_theme_request("Song", "Only this snippet is provided")
    calls = []

    def opener(outbound, *, timeout):
        calls.append((outbound, timeout))
        return FakeResponse()

    result = suggest_theme(preview, api_key="not-a-real-key", consent=True, opener=opener)
    assert result.themes == ("思念", "成长")
    assert len(calls) == 1
    body = json.loads(calls[0][0].data)
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 256
    assert body["messages"][1]["content"].endswith(preview.lyric_excerpt)
    assert "not-a-real-key" not in calls[0][0].data.decode("utf-8")
