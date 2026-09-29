from __future__ import annotations

from types import SimpleNamespace

import pytest

from musefolders.filter_assistant import (FilterAssistantError, parse_filter_response,
                                          suggest_filters)


def _track():
    return SimpleNamespace(
        metadata=SimpleNamespace(title="Real Song", artist="Real Artist", album="Real Album",
                                 genre="blues", year="2020"),
        instrument="voice", tags={"key": "C:major", "loudness": "medium", "tempo": "fast"},
        acoustic=SimpleNamespace(key="C", mode="major", key_confidence=1.0),
    )


def test_model_output_is_only_an_editable_validated_filter():
    result = parse_filter_response({"filters": {
        "genres": ["BLUES", "invented genre"], "instruments": ["voice"],
        "tempo": ["fast"], "bri_range": [6, 10], "delete_files": True,
    }, "unsupported": ["mood"], "explanation": "Proposal only"}, [_track()])
    assert result.filters.genres == frozenset({"blues"})
    assert result.filters.bri_range == (60, 100)
    assert result.filters.instruments == frozenset({"voice"})
    assert "mood" in result.unsupported
    assert "delete_files" in result.unsupported
    assert any("invented genre" in item for item in result.unsupported)


def test_no_network_call_without_consent_or_key():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Network call was attempted")

    with pytest.raises(FilterAssistantError):
        suggest_filters("bright fast songs", [_track()], api_key="secret",
                        consent=False, opener=forbidden)
    with pytest.raises(FilterAssistantError):
        suggest_filters("bright fast songs", [_track()], api_key="",
                        consent=True, opener=forbidden)
