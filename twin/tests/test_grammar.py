# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The twin against the language's grammar (plugin/dedala/grammar.json, kept equal to the app by its tests): every
view is measured, and every modifier either changes what the twin lays out, is known not to change the layout on the
phone, or is listed as a gap. A name added to the grammar fails here until it is placed in one of the three."""

import json
from pathlib import Path

import pytest

from dedala.twin import layout

GRAMMAR = json.loads((Path(__file__).resolve().parents[2] / "plugin" / "dedala" / "grammar.json").read_text())

LONG = "The quick brown fox jumps over the lazy dog while the band plays on and on into the night"
CHILDREN = [{"Text": "One"}, {"Text": "Two"}]
VIEWS = {
    "Section": {"Section": "Title", "content": CHILDREN},
    "Grid": {"Grid": [CHILDREN]},
    "DisclosureGroup": {"DisclosureGroup": "More", "content": CHILDREN},
    "Spacer": {"Spacer": {}},
    "Divider": {"Divider": {}},
    "Label": {"Label": ["Flight", "airplane"]},
    "Image": {"Image": "airplane"},
    "Color": {"Color": "blue"},
    "Gradient": {"Gradient": ["blue", "red"]},
    "Path": {"Path": [[0, 0], [1, 1]]},
    "Chart": {"Chart": [{"x": "a", "y": 1}]},
    "Map": {"Map": {"lat": 59.33, "lon": 18.07}},
    "Gauge": {"Gauge": 0.4, "label": "Disk"},
    "ProgressView": {"ProgressView": 0.4},
    "Link": {"Link": "Open", "url": "https://example.org"},
    "Menu": {"Menu": "More", "actions": []},
    "Picker": {"Picker": "Pick", "options": ["a", "b"]},
    "Slider": {"Slider": 0.5},
    "QRCode": {"QRCode": "https://example.org"},
    "Face": {"Face": 56},
    "Said": {"Said": "m1"},
    "List": {"List": ["Flight", "Hotel"], "as": "it", "content": {"Text": "${it}"}},
    "File": {"File": {"text": "* Brief\nWith Marta.", "name": "brief.org"}},
    "TextEditor": {"TextEditor": "Write", "bind": "$draft"},
}
SHAPES = ("Circle", "Capsule", "Rectangle", "Ellipse", "RoundedRectangle")
EMPTY = {"Spacer"}

TEXT = {"Text": "Flight 1457"}
PARAGRAPH = {"Text": LONG}
SYMBOL = {"Image": "airplane"}
BOX = {"Rectangle": {}}
BESIDE = {"HStack": [{"Text": LONG}, {"Text": LONG}]}
AFFECT_LAYOUT = {
    "font": (TEXT, "title"),
    "fontWeight": (TEXT, "black"),
    "fontDesign": (TEXT, "monospaced"),
    "bold": (TEXT, True),
    "italic": (TEXT, True),
    "monospaced": (TEXT, True),
    "monospacedDigit": (TEXT, True),
    "textCase": (TEXT, "uppercase"),
    "tracking": (TEXT, 2),
    "lineLimit": (PARAGRAPH, 1),
    "lineSpacing": (PARAGRAPH, 10),
    "minimumScaleFactor": ({"Text": LONG, "lineLimit": 1}, 0.5),
    "imageScale": (SYMBOL, "large"),
    "controlSize": ({"Button": "Go", "style": "bordered"}, "small"),
    "labelStyle": ({"Label": ["Flight", "airplane"]}, "iconOnly"),
    "aspectRatio": (BOX, 2),
    "frame": (TEXT, {"width": 200}),
    "width": (TEXT, 200),
    "height": (TEXT, 80),
    "minWidth": (TEXT, 200),
    "maxWidth": (TEXT, "infinity"),
    "minHeight": (TEXT, 80),
    "maxHeight": (PARAGRAPH, 30),
    "fixedSize": ({"Text": LONG, "width": 100}, True),
    "layoutPriority": (BESIDE, None),
    "padding": (TEXT, 8),
    "margin": (TEXT, 8),
    "background": (TEXT, "blue"),
    "glassEffect": (TEXT, True),
    "overlay": (TEXT, {"Text": "9"}),
    "offset": ({"HStack": [TEXT]}, {"x": 5, "y": 5}),
}
NO_LAYOUT = {
    "accessibilityLabel": "read aloud only",
    "blur": "drawn over the same frame",
    "border": "a stroke the app overlays on the view",
    "clip": "the app's name for the step that applies clipShape and cornerRadius, not a key it reads",
    "clipShape": "clips the drawing, not the frame",
    "color": "an alias of foregroundStyle",
    "contentTransition": "how a change animates",
    "cornerRadius": "clips the drawing, not the frame",
    "disabled": "dims the control",
    "foregroundStyle": "a colour",
    "grayscale": "drawn over the same frame",
    "multilineTextAlignment": "moves lines inside the text's own frame",
    "onTap": "an action",
    "opacity": "drawn over the same frame",
    "saturation": "drawn over the same frame",
    "shadow": "drawn outside the frame, taking no room",
    "symbolEffect": "an animation",
    "symbolRenderingMode": "colours of the same glyph",
    "tint": "a colour",
    "transition": "how the view arrives and leaves",
    "zIndex": "the drawing order",
}
GAPS = {
    "truncationMode": "the twin measures a cut line as cut at its tail: the middle-cut line of the calib-vocab probe is 1.3 pt off",
    "symbolVariant": "the phone draws another symbol (heart as heart.fill), the twin measures the one named",
    "scale": "drawn larger or smaller over the same layout frame: the twin does not see what the drawing then covers",
    "rotation": "drawn turned over the same layout frame: the twin does not see what the drawing then covers",
}


def sample(view):
    if view in VIEWS:
        return VIEWS[view]
    if view in GRAMMAR["containers"]:
        return {view: CHILDREN}
    if view in SHAPES:
        return {view: {}}
    return {view: "Flight"}


def frames(view):
    engine = layout.Engine({"view": view}, {}, 348.0)
    engine.run()
    found = []

    def walk(box):
        if box.frame is None:
            return
        found.append((box.path, box.kind, tuple(round(v, 3) for v in box.frame)))
        for layer in ("overlay", "background"):
            if layer in box.extra:
                walk(box.extra[layer])
        for child in box.children or []:
            if child is not None:
                walk(child)

    walk(engine.root)
    return found


def with_modifier(node, name, value):
    if name == "layoutPriority":
        return {"HStack": [node["HStack"][0], dict(node["HStack"][1], layoutPriority=1)]}
    return dict(node, **{name: value})


@pytest.fixture(autouse=True)
def default_text_size():
    layout.set_text_size("large")


@pytest.mark.parametrize("view", GRAMMAR["views"])
def test_every_view_of_the_grammar_is_measured(view):
    kinds = {"Group", "Text"} if view == "List" else {"Button"} if view in ("Photo", "Dictate") else {view}
    box = next(frame for path, kind, frame in frames({"VStack": [sample(view)]}) if kind in kinds)
    assert view in EMPTY or box[2] > 0 and box[3] > 0


@pytest.mark.parametrize("view", GRAMMAR["containers"])
def test_every_container_lays_its_children_out(view):
    texts = [frame for path, kind, frame in frames(sample(view)) if kind == "Text"]
    assert len(texts) == len(CHILDREN)
    assert all(frame[2] > 0 and frame[3] > 0 for frame in texts)


def test_a_view_the_twin_does_not_know_is_an_error_not_an_empty_box():
    with pytest.raises(layout.UnknownView, match="Sparkline"):
        layout.layout({"view": {"VStack": [{"Text": "Hi"}, {"Sparkline": [1, 2, 3]}]}})


def test_a_component_is_not_an_unknown_view():
    components = {"Sparkline": {"props": {}, "body": {"Text": "▁▂▃"}}}
    assert layout.layout({"view": {"VStack": [{"Sparkline": {}}]}}, components)["frames"]


def test_every_modifier_of_the_grammar_is_placed():
    placed = [set(AFFECT_LAYOUT), set(NO_LAYOUT), set(GAPS)]
    assert set(GRAMMAR["modifiers"]) == set().union(*placed)
    assert sum(len(names) for names in placed) == len(GRAMMAR["modifiers"])


@pytest.mark.parametrize("name", AFFECT_LAYOUT)
def test_a_layout_modifier_changes_what_the_twin_lays_out(name):
    node, value = AFFECT_LAYOUT[name]
    assert frames({"VStack": [with_modifier(node, name, value)]}) != frames({"VStack": [node]})


@pytest.mark.parametrize("name", [*NO_LAYOUT, *GAPS])
def test_the_other_modifiers_leave_the_layout_alone(name):
    for node in (TEXT, PARAGRAPH, SYMBOL, {"Label": ["Flight", "heart"]}, {"Button": "Go", "style": "bordered"}):
        inside = {"VStack": [dict(node, **{name: "middle" if name == "truncationMode" else "fill" if name == "symbolVariant" else 2})]}
        assert frames(inside) == frames({"VStack": [node]})


def test_a_group_hands_its_children_every_modifier_but_the_two_the_twin_does_not_read():
    assert set(GRAMMAR["modifiers"]) - layout.MODIFIERS - layout.PUSHED == {"clip", "truncationMode"}


def test_what_is_written_on_a_loop_applies_to_each_row():
    texts = [frame for path, kind, frame in frames({"VStack": [{"ForEach": ["a", "b"], "as": "n", "content": {"Text": "$n"}, "padding": 20}]}) if kind == "Text"]
    plain = [frame for path, kind, frame in frames({"VStack": [{"ForEach": ["a", "b"], "as": "n", "content": {"Text": "$n"}}]}) if kind == "Text"]
    assert len(texts) == 2 and texts[0][3] >= plain[0][3] + 40
