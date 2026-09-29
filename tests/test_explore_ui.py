"""Focused interaction contracts for the two primary exploration maps."""

from __future__ import annotations

from types import SimpleNamespace

from musefolders import explore_ui


def test_zodiac_overlay_never_changes_song_points_or_axis_range(monkeypatch) -> None:
    figures = []

    def chart(figure, **_kwargs):
        figures.append(figure)
        return SimpleNamespace(selection=SimpleNamespace(points=[]))

    monkeypatch.setattr(
        explore_ui, "st",
        SimpleNamespace(session_state={}, plotly_chart=chart),
    )
    rows = [
        {"track_id": "one", "x": 21.0, "y": 32.0, "name": "One", "act": 12.0},
        {"track_id": "two", "x": 71.0, "y": 82.0, "name": "Two", "act": 87.0},
    ]
    zodiac = SimpleNamespace(
        status="matched", overlay_nodes=((10.0, 20.0), (60.0, 70.0)),
        overlay_edges=((0, 1),),
    )
    args = dict(color="act", focus_id=None, chart_key="sonic_test",
                labels=explore_ui.LABELS["en"], sonic_axes=True)
    explore_ui._draw_map(rows, zodiac=None, **args)
    explore_ui._draw_map(rows, zodiac=zodiac, **args)

    plain, decorated = figures
    assert tuple(plain.data[0].x) == tuple(decorated.data[0].x)
    assert tuple(plain.data[0].y) == tuple(decorated.data[0].y)
    assert tuple(plain.data[0].marker.color) == tuple(decorated.data[0].marker.color)
    assert tuple(plain.layout.xaxis.range) == (0, 100)
    assert tuple(decorated.layout.xaxis.range) == (0, 100)
    assert tuple(plain.layout.yaxis.range) == (0, 100)
    assert tuple(decorated.layout.yaxis.range) == (0, 100)
    assert len(plain.layout.shapes) == 0
    assert len(decorated.layout.shapes) == 3
    assert all(shape.layer == "below" for shape in decorated.layout.shapes)


def test_theme_island_component_clicks_whole_region_with_json_data(monkeypatch) -> None:
    seen = {}

    def component(name, **definition):
        seen["name"] = name
        seen["definition"] = definition

        def mount(**kwargs):
            seen["data"] = kwargs["data"]
            return SimpleNamespace(clicked="love")

        return mount

    monkeypatch.setattr(
        explore_ui, "st",
        SimpleNamespace(components=SimpleNamespace(v2=SimpleNamespace(component=component))),
    )
    region = SimpleNamespace(theme_id="love", count=2, center=(700.0, 150.0),
                             outline=((690.0, 140.0), (710.0, 140.0), (700.0, 160.0)))
    atlas = SimpleNamespace(regions={"love": region})
    clicked = explore_ui._theme_island_map(atlas, None, explore_ui.LABELS["en"])

    assert clicked == "love"
    assert seen["data"]["regions"][0]["label"] == "Love"
    assert "textContent" in seen["definition"]["js"]
    assert "group.addEventListener('click'" in seen["definition"]["js"]
    assert "<div data-theme-atlas></div>" == seen["definition"]["html"]


def test_dense_points_have_a_separate_picker_without_moving_coordinates() -> None:
    rows = [
        {"track_id": "a", "x": 50.0, "y": 50.0},
        {"track_id": "b", "x": 50.0, "y": 50.0},
        {"track_id": "c", "x": 50.1, "y": 50.1},
        {"track_id": "far", "x": 90.0, "y": 90.0},
    ]
    before = [(item["x"], item["y"]) for item in rows]
    groups = explore_ui.overlap_groups(rows, x_range=(0, 100), y_range=(0, 100))
    assert groups == [["a", "b", "c"]]
    assert [(item["x"], item["y"]) for item in rows] == before


def test_plotly_zoom_uses_saved_level_and_visible_tools(monkeypatch) -> None:
    figures, configs = [], []

    def chart(figure, **kwargs):
        figures.append(figure)
        configs.append(kwargs["config"])
        return SimpleNamespace(selection=SimpleNamespace(points=[]))

    monkeypatch.setattr(explore_ui, "st", SimpleNamespace(
        session_state={"sonic_test_zoom": 2, "sonic_test_center": (50, 50)},
        plotly_chart=chart,
    ))
    explore_ui._draw_map([{"track_id": "a", "x": 50.0, "y": 50.0,
                           "name": "A", "act": 50.0}], color="act", focus_id=None,
                         chart_key="sonic_test", labels=explore_ui.LABELS["en"], sonic_axes=True)
    assert tuple(figures[0].layout.xaxis.range) == (37.5, 62.5)
    assert tuple(figures[0].layout.yaxis.range) == (37.5, 62.5)
    assert configs[0]["displayModeBar"] is True
