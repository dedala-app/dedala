# SPDX-FileCopyrightText: 2023-2025 Kyle-Ye
# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""A layout twin of the app's card renderer: every node's frame, measured with the phone's fonts.

layout(card, components, width) lays a card out the way the phone does and returns the
frames the phone would report, so a card can be checked before it is sent.
"""

import bisect
import gzip
import json
import struct
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from functools import lru_cache

import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.varLib.models import normalizeLocation, piecewiseLinearMap
from fontTools.varLib.varStore import VarStoreInstancer

from .. import native
from .hyphenate import Hyphenator


HERE = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.environ.get("BENCH_FONTS") or os.path.join(HERE, "fonts")
FONT_FILES = {"default": "SFUI.ttf", "italic": "SFUIItalic.ttf", "rounded": "SFUIRounded.ttf", "monospaced": "SFUIMono.ttf", "serif": "NewYork.ttf"}
STYLE_NAMES = ("largeTitle", "title", "title2", "title3", "headline", "body", "callout", "subheadline", "footnote", "caption", "caption2")
TEXT_SIZES = {
    "xSmall": ((31, 38), (25, 31), (19, 24), (17, 22), (14, 19), (14, 19), (13, 18), (12, 16), (12, 16), (11, 13), (11, 13)),
    "small": ((32, 39), (26, 32), (20, 25), (18, 23), (15, 20), (15, 20), (14, 19), (13, 18), (12, 16), (11, 13), (11, 13)),
    "medium": ((33, 40), (27, 33), (21, 26), (19, 24), (16, 21), (16, 21), (15, 20), (14, 19), (12, 16), (11, 13), (11, 13)),
    "large": ((34, 41), (28, 34), (22, 28), (20, 25), (17, 22), (17, 22), (16, 21), (15, 20), (13, 18), (12, 16), (11, 13)),
    "xLarge": ((36, 43), (30, 36), (24, 30), (22, 28), (19, 24), (19, 24), (18, 23), (17, 22), (15, 20), (14, 19), (13, 18)),
    "xxLarge": ((38, 46), (32, 38), (26, 32), (24, 30), (21, 26), (21, 26), (20, 25), (19, 24), (17, 22), (16, 21), (15, 20)),
    "xxxLarge": ((40, 48), (34, 41), (28, 34), (26, 32), (23, 29), (23, 29), (22, 28), (21, 26), (19, 24), (18, 23), (17, 22)),
    "accessibility1": ((44, 52), (38, 46), (34, 41), (31, 38), (28, 34), (28, 34), (26, 32), (25, 31), (23, 29), (22, 27), (20, 25)),
    "accessibility2": ((48, 57), (43, 51), (39, 47), (37, 44), (33, 40), (33, 40), (32, 39), (30, 36), (27, 33), (26, 32), (24, 29)),
    "accessibility3": ((52, 61), (48, 57), (44, 52), (43, 51), (40, 48), (40, 48), (38, 46), (36, 43), (33, 40), (32, 39), (29, 35)),
    "accessibility4": ((56, 66), (53, 61), (50, 59), (49, 58), (47, 51), (47, 56), (44, 52), (42, 50), (38, 46), (37, 44), (34, 41)),
    "accessibility5": ((60, 70), (58, 68), (56, 66), (55, 65), (53, 62), (53, 62), (51, 60), (49, 58), (44, 52), (43, 51), (40, 48)),
}
GAUGE_ROWS = {
    "xSmall": (25.84, 22.38, 25.71), "small": (27.33, 23.62, 26.95), "medium": (29.15, 25.19, 29.19), "large": (30.98, 26.77, 31.10),
    "xLarge": (34.62, 29.92, 35.58), "xxLarge": (38.26, 33.07, 39.40), "xxxLarge": (41.91, 36.21, 42.88),
    "accessibility1": (51.02, 44.09, 53.09), "accessibility2": (59.80, 51.63, 62.29), "accessibility3": (72.55, 62.65, 75.65),
    "accessibility4": (84.97, 73.34, 89.00), "accessibility5": (95.57, 82.45, 100.78),
}
GRAPHICAL_CALENDAR = {
    "xSmall": 409.0, "small": 411.0, "medium": 413.333, "large": 416.667, "xLarge": 423.667, "xxLarge": 430.333, "xxxLarge": 433.333,
    "accessibility1": 438.333, "accessibility2": 498.333, "accessibility3": 506.333, "accessibility4": 514.667, "accessibility5": 521.667,
}
STYLES = {}
WEIGHTS = {"ultraLight": 100, "thin": 200, "light": 300, "regular": 400, "medium": 500, "semibold": 600, "bold": 700, "heavy": 800, "black": 900}
CONTROL = {"mini": 0.65, "small": 0.88, "regular": 1.0, "large": 1.0, "extraLarge": 1.0}
SYMBOLS = {"airplane": (1.235, 1.16), "car.fill": (1.39, 1.08), "star.fill": (1.29, 1.22), "lightbulb.fill": (0.9, 1.31), "wallet.pass.fill": (1.06, 1.22)}
EXPORTED = {}
GLYPH_SIZES = os.path.join(os.environ.get("BENCH_GLYPHS") or os.path.join(HERE, "glyphs"), "sizes.json")
if os.path.exists(GLYPH_SIZES):
    for name, entry in json.load(open(GLYPH_SIZES)).items():
        if entry.get("regular"):
            EXPORTED[name] = tuple(entry["regular"])
            SYMBOLS[name] = ((entry["regular"][0] - 1 / 3) / 17, (entry["regular"][1] - 1 / 3) / 17)
def vertical_metrics():
    """Ascent, descent and cap height of the system font as fractions of the point size, from the phone's own font file."""
    path = os.path.join(FONTS_DIR, FONT_FILES["default"])
    if not os.path.exists(path):
        return 1950 / 2048, 494 / 2048, 1443 / 2048
    tt = TTFont(path, lazy=True)
    upem = tt["head"].unitsPerEm
    return tt["hhea"].ascent / upem, -tt["hhea"].descent / upem, tt["OS/2"].sCapHeight / upem


ASCENT, DESCENT, CAP_HEIGHT = vertical_metrics()


def use_fonts(folder):
    """Lays out with the fonts in this folder from now on, named as FONT_FILES names them: the phone's own, sent to
    the agent."""
    global FONTS_DIR, ASCENT, DESCENT, CAP_HEIGHT
    FONTS_DIR = folder
    Fonts.faces.clear()
    Fonts.tables.clear()
    Fonts.exact.clear()
    for cached in (advance, advance_shaped, emoji_spans, shaped_prefix_widths):
        cached.cache_clear()
    ASCENT, DESCENT, CAP_HEIGHT = vertical_metrics()
PIXEL = 1 / 3


def fixed_axes(value) -> tuple[bool, bool]:
    """The axes a `fixedSize` holds: true or neither string both, an object
    each axis it sets."""
    if isinstance(value, dict):
        return (truthy(value.get("horizontal")), truthy(value.get("vertical")))
    if value in ("horizontal", "vertical"):
        return (value == "horizontal", value == "vertical")
    return (truthy(value), truthy(value))


class SymbolGlyphs:
    """Every symbol's layout numbers in pixels at each measured point size, per weight and image scale, as CoreUI hands
    them to SwiftUI: the image's width and height, the glyph's baseline offset, and its alignment rect's y, width and
    height. Symbol rendering is hinted, so none of these scale with the point size. Apple's data: the catalog stays
    out of the repository, named by BENCH_SYMBOLS, and serves only to calibrate."""

    def __init__(self, path):
        raw = gzip.open(path).read()
        length = struct.unpack_from("<I", raw, 0)[0]
        header = json.loads(raw[4:4 + length])
        self.names = {name: index for index, name in enumerate(header["names"])}
        self.weights = {weight: index for index, weight in enumerate(header["weights"])}
        self.scales = {scale: index for index, scale in enumerate(header["scales"])}
        self.sizes = header["sizes"]
        self.reference = header["reference"]
        self.values = header["values"]
        self.data = raw[4 + length:]
        self.row = 2 * self.values + self.values * len(self.sizes)
        self.cache = {}

    def pixels(self, name, weight, scale, size):
        """The values at this size, measured, or interpolated between the two nearest sizes measured."""
        key = (name, weight, scale, size)
        if key not in self.cache:
            self.cache[key] = self.lookup(name, weight, scale, size)
        return self.cache[key]

    def lookup(self, name, weight, scale, size):
        index = self.names.get(name)
        if index is None:
            index = self.names.get(name.replace(".fill", "")) if name.endswith(".fill") else self.names.get(name + ".fill")
        if index is None:
            return None
        row = (index * len(self.weights) + self.weights.get(weight, self.weights["regular"])) * len(self.scales) + self.scales.get(scale, 1)
        at = row * self.row
        base = struct.unpack_from("<" + "h" * self.values, self.data, at)

        def measured(position):
            residual = struct.unpack_from("<" + "b" * self.values, self.data, at + 2 * self.values + self.values * position)
            z = self.sizes[position]
            return [round(base[k] * z / self.reference) + residual[k] for k in range(self.values)]

        if size in self.sizes:
            return measured(self.sizes.index(size))
        below = max((i for i, z in enumerate(self.sizes) if z < size), default=None)
        above = min((i for i, z in enumerate(self.sizes) if z > size), default=None)
        if below is None or above is None:
            edge = below if above is None else above
            return [round(v * size / self.sizes[edge]) for v in measured(edge)]
        low, high = measured(below), measured(above)
        t = (size - self.sizes[below]) / (self.sizes[above] - self.sizes[below])
        return [round(low[k] + (high[k] - low[k]) * t) for k in range(self.values)]


CATALOG = os.environ.get("BENCH_SYMBOLS")
GLYPHS = SymbolGlyphs(CATALOG) if CATALOG and os.path.exists(CATALOG) else None
PADDING_SIZES = (8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
                 38, 39, 40, 44, 48, 50, 56, 60, 64, 72, 80, 96)
PADDING = {
    "small": (2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 8, 8, 8, 8, 9, 10, 10, 11, 12, 13, 15, 16, 20),
    "medium": (2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 7, 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 9, 10, 10, 10, 10, 12, 13, 13, 15, 16, 17, 19, 21, 25),
    "large": (3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7, 7, 8, 8, 8, 9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12, 13, 13, 14, 15, 16, 17, 19, 20, 22, 24, 27, 32),
}


def symbol_padding(scale, size):
    """The pixels a symbol image keeps above and below its alignment rect: the same for every symbol and weight."""
    row = PADDING.get(scale, PADDING["medium"])
    if size in PADDING_SIZES:
        return row[PADDING_SIZES.index(size)]
    nearest = min(range(len(PADDING_SIZES)), key=lambda i: abs(PADDING_SIZES[i] - size))
    return round(row[nearest] * size / PADDING_SIZES[nearest])


class MeasuredSymbols:
    """Symbols the phone measured, per point size, weight and scale: the image's width and height and its baseline from
    the bottom in pixels as UIImage hands them, and the aspect SwiftUI keeps for the symbol made resizable. The rest of
    what SwiftUI reads follows from the padding, which depends on the scale and the size only."""

    def __init__(self):
        self.sizes = {}
        self.wanted = set()

    def add(self, name, size, weight, scale, values):
        self.sizes[(name, weight, scale, float(size))] = tuple(values)

    def pixels(self, name, weight, scale, size):
        measured = self.sizes.get((name, weight, scale, float(size)))
        if measured is None:
            self.wanted.add((name, float(size)))
            return None
        width, height, baseline, *rest = measured
        pad = symbol_padding(scale, size)
        inner = height - 2 * pad
        aspect = rest[0] if rest and rest[0] else None
        return [width, height, baseline - pad, pad, round(aspect * inner) if aspect else width - 2 * pad, inner]


MEASURED = MeasuredSymbols()


def symbol_pixels(name, font):
    """A symbol's (image width, image height, baseline offset, alignment y, alignment width, alignment height) in pixels:
    measured on the phone, else from the catalog when there is one."""
    weight, scale, size = font["weight"], font.get("imageScale") or "medium", font["size"]
    measured = MEASURED.pixels(name, weight, scale, size)
    if measured is not None or GLYPHS is None:
        return measured
    return GLYPHS.pixels(name, weight, scale, size)


LABEL_GAP = 8.0
EMPTY_TEXT_HEIGHT = 14.0
EMPTY_TEXT_ASCENT = 11.46
BUTTON_SIZES = {"mini": "small", "small": "small", "regular": "regular", "large": "large", "extraLarge": "large"}
SYMBOL = (1.25, 1.17)
IMAGE_SCALE = {"small": 0.8, "medium": 1.0, "large": 1.27}
DEFAULT_FONT = {"size": 17, "weight": "regular", "design": "default", "italic": False, "style": "body"}
TEXT_SIZE = "large"


def set_text_size(name):
    """The phone's text size, as the app reports it: each text style's point size and line height at that size."""
    global TEXT_SIZE
    TEXT_SIZE = name if name in TEXT_SIZES else "large"
    STYLES.clear()
    for style, (size, leading) in zip(STYLE_NAMES, TEXT_SIZES[TEXT_SIZE]):
        STYLES[style] = (size, "semibold" if style == "headline" else "regular", leading)
    DEFAULT_FONT["size"] = STYLES["body"][0]


set_text_size("large")


def scaled(value):
    """UIFontMetrics' body scaling at the phone's text size: the value times the body's line pitch over its default 22
    points, to the pixel. Controls size their tracks, spinners and padding with it."""
    return round(value * STYLES["body"][2] / 22 * 3) / 3


def styled(style, weight=None):
    """A text style's font at the phone's text size."""
    size, own, _ = STYLES[style]
    return {"size": float(size), "weight": weight or own, "design": "default", "italic": False, "style": style}
CARD_WIDTHS = (348.0, 395.0)
WIDTH = CARD_WIDTHS[0]
CONTROL_WIDTHS = {"Toggle": 59.0, "Stepper": 102.0}
# A List is drawn twelve rows deep by the check, as on the phone; the rest scroll.
LIST_PROBED_ROWS = 12
# What a ForEach or List keeps for itself; the rest applies to each row.
LOOP_OWN = {"ForEach", "List", "as", "index", "content", "onMove", "hidden", "visible", "state"}


def push_into(pushed, content):
    if isinstance(content, list):
        return [push_into(pushed, child) for child in content]
    if isinstance(content, dict):
        return {**pushed, **content}
    if isinstance(content, str):
        return {**pushed, "Text": content}
    return content
FIXED = {"Toggle": 28, "Slider": 31, "Stepper": 32, "TextField": 34, "Chart": 160, "Map": 180, "Pages": 220, "Divider": 1 / 3}


CLOCK = None


def now(tz=None):
    """The moment the card is laid out for: the phone's capture time when a report carries one, else now."""
    moment = CLOCK or datetime.now(timezone.utc)
    return moment.astimezone(tz) if tz is not None else moment


def third(value):
    return math.ceil(value * 3 - 1e-6) / 3


def pixel(value):
    """The nearest pixel at 3x."""
    return math.floor(value * 3 + 0.5) / 3


INSTANCES = {"ultraLight": "Ultralight", "thin": "Thin", "light": "Light", "regular": "Regular", "medium": "Medium", "semibold": "Semibold", "bold": "Bold", "heavy": "Heavy", "black": "Black"}
PRECISION = 64


class Advances:
    """A variable font's glyph advances at one location, interpolated in floating point the way CoreText does;
    HarfBuzz rounds them to whole font units, which the phone's lines show it does not."""

    def __init__(self, path, variations):
        self.tt = TTFont(path, lazy=True)
        axes = {a.axisTag: (a.minValue, a.defaultValue, a.maxValue) for a in self.tt["fvar"].axes}
        location = normalizeLocation(variations, axes)
        if "avar" in self.tt:
            segments = self.tt["avar"].segments
            location = {tag: piecewiseLinearMap(value, segments[tag]) if segments.get(tag) else value for tag, value in location.items()}
        self.hvar = self.tt["HVAR"].table
        self.instancer = VarStoreInstancer(self.hvar.VarStore, self.tt["fvar"].axes, location)
        self.order = self.tt.getGlyphOrder()
        self.hmtx = self.tt["hmtx"]
        self.cache = {}

    def __call__(self, gid):
        if gid not in self.cache:
            name = self.order[gid]
            index = self.hvar.AdvWidthMap.mapping[name] if self.hvar.AdvWidthMap else gid
            self.cache[gid] = self.hmtx[name][0] + self.instancer[index]
        return self.cache[gid]


def positions(font, buffer, size):
    """Each shaped glyph's advance in points: HarfBuzz's kerning and tracking on top of the exact base advance."""
    exact = Fonts.exact[id(font)]
    unit = size / font.face.upem
    return [(position.x_advance - font.get_glyph_h_advance(info.codepoint)) / PRECISION * unit + exact(info.codepoint) * unit
            for info, position in zip(buffer.glyph_infos, buffer.glyph_positions)]


class Fonts:
    """The phone's fonts: each weight at the named instance's coordinates, the optical size at the point size, tracking from the font's own table."""
    faces = {}
    tables = {}
    exact = {}

    @classmethod
    def file(cls, design, italic=False):
        return "italic" if italic and design == "default" else design if design in FONT_FILES else "default"

    @classmethod
    def table(cls, name):
        if name not in cls.tables:
            tt = TTFont(os.path.join(FONTS_DIR, FONT_FILES[name]), lazy=True)
            axes = {axis.axisTag for axis in tt["fvar"].axes} if "fvar" in tt else set()
            ranges = {axis.axisTag: (axis.minValue, axis.maxValue) for axis in tt["fvar"].axes} if "fvar" in tt else {}
            instances = {}
            if "fvar" in tt:
                for instance in tt["fvar"].instances:
                    if instance.coordinates.get("wdth", 100.0) == 100.0:
                        instances.setdefault(tt["name"].getDebugName(instance.subfamilyNameID), instance.coordinates)
            track = None
            if "trak" in tt:
                for value, entry in tt["trak"].horizData.items():
                    if value == 0.0:
                        track = sorted((float(size), units) for size, units in entry.items())
            cls.tables[name] = {"axes": axes, "ranges": ranges, "instances": instances, "track": track, "upem": tt["head"].unitsPerEm,
                                "cmap": frozenset(tt.getBestCmap() or ())}
        return cls.tables[name]

    @classmethod
    def cmap(cls, name):
        """The code points the file has a glyph for; anything else the phone draws from a fallback font."""
        return cls.table(name)["cmap"]

    @classmethod
    def font(cls, design, weight, size, italic=False):
        name = cls.file(design, italic)
        low, high = cls.table(name)["ranges"].get("opsz", (size, size))
        opsz = min(max(size, low), high)
        key = (name, weight, size, opsz)
        if key in cls.faces:
            return cls.faces[key]
        table = cls.table(name)
        font = hb.Font(hb.Face(hb.Blob.from_file_path(os.path.join(FONTS_DIR, FONT_FILES[name]))))
        font.scale = (table["upem"] * PRECISION, table["upem"] * PRECISION)
        variations = {}
        instance = table["instances"].get(INSTANCES.get(weight, "Regular")) or table["instances"].get("Regular") or {}
        if "wght" in table["axes"]:
            variations["wght"] = instance.get("wght", WEIGHTS.get(weight, 400))
        if "opsz" in table["axes"]:
            variations["opsz"] = opsz
        if variations:
            font.set_variations(variations)
        cls.faces[key] = font
        cls.exact[id(font)] = Advances(os.path.join(FONTS_DIR, FONT_FILES[name]), variations)
        return font


def tabular_digit(weight, size, design="default", italic=False):
    """The advance of a digit in a monospaced-digit font, with its tracking: the font's tabular figures."""
    scale = 1.0
    font = Fonts.font(design, weight, size, italic)
    buffer = hb.Buffer()
    buffer.add_str("0")
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"tnum": True})
    return positions(font, buffer, size)[0] * scale + tracking(size, design)


def with_tabular_digits(text, cum, weight, size, design="default", italic=False, extra=0.0):
    """cum[] with every digit given the tabular advance: digits neither kern nor vary, the runs between them shape on their own."""
    digit = tabular_digit(weight, size, design, italic)
    if digit is None or not any(ch.isdigit() for ch in text):
        return cum if cum is not None else prefix_widths(text, design, weight, size, italic, extra)
    out = [0.0]
    position = 0
    while position < len(text):
        if text[position].isdigit():
            out.append(out[-1] + digit + extra)
            position += 1
            continue
        end = position
        while end < len(text) and not text[end].isdigit():
            end += 1
        part = prefix_widths(text[position:end], design, weight, size, italic, extra)
        base = out[-1]
        out.extend(base + part[i] for i in range(1, end - position + 1))
        position = end
    return out


TRACK_REFERENCE = 12.0


def track_units(track, size):
    """The font's `trak` value at a size, interpolated between its entries and truncated to whole units as CoreText does."""
    if size <= track[0][0]:
        units = track[0][1]
    elif size >= track[-1][0]:
        units = track[-1][1]
    else:
        units = next(ua + (ub - ua) * (size - a) / (b - a) for (a, ua), (b, ub) in zip(track, track[1:]) if a <= size <= b)
    return int(units)


def tracking(size, design="default"):
    """The system's letter spacing for a font at a point size, per glyph: the font's `trak` value at that size less its value
    at 12 points, which is what the phone applies (zero for SF, whose table is zero at 12; the rounded and serif files are not)."""
    if design == "monospaced":
        return 0.0
    table = Fonts.table(Fonts.file(design))
    track = table["track"]
    if not track:
        return 0.0
    return (track_units(track, size) - track_units(track, TRACK_REFERENCE)) * size / table["upem"]


@lru_cache(maxsize=100000)
def advance(text, design, weight, size, italic, tabular=False):
    if not text:
        return 0.0
    if tabular:
        return prefix_widths(text, design, weight, size, italic, 0.0, True)[-1]
    return advance_shaped(text, design, weight, size, italic)


@lru_cache(maxsize=100000)
def advance_shaped(text, design, weight, size, italic):
    if not text:
        return 0.0
    if emoji_spans(text, design, italic):
        return prefix_widths(text, design, weight, size, italic, 0.0)[-1]
    scale = 1.0
    font = Fonts.font(design, weight, size, italic)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True})
    return sum(positions(font, buffer, size)) * scale + tracking(size, design) * len(text)


MARKDOWN = [(re.compile(r"\*\*(.+?)\*\*"), r"\1"), (re.compile(r"__(.+?)__"), r"\1"), (re.compile(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)"), r"\1"),
            (re.compile(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"), r"\1"), (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"), (re.compile(r"`([^`]*)`"), r"\1")]


def plain(text):
    for pattern, replacement in MARKDOWN:
        text = pattern.sub(replacement, text)
    return text


INLINE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]*)`|\[([^\]]+)\]\([^)]*\)|(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")


def styled_runs(text):
    """The plain text of an inline-markdown string and the runs the phone draws bold, italic or in code."""
    out = []
    runs = []
    position = 0
    for match in INLINE.finditer(text):
        out.append(text[position:match.start()])
        inner = next(group for group in match.groups() if group is not None)
        start = sum(len(part) for part in out)
        kind = "bold" if match.group(1) is not None or match.group(2) is not None else "code" if match.group(3) is not None else "link" if match.group(4) is not None else "italic"
        if kind != "link":
            runs.append((start, start + len(inner), kind))
        out.append(inner)
        position = match.end()
    out.append(text[position:])
    return "".join(out), runs


def run_font(font, kind):
    if kind == "bold":
        heavier = {"ultraLight": "semibold", "thin": "semibold", "light": "semibold", "regular": "semibold", "medium": "semibold", "semibold": "bold", "bold": "heavy", "heavy": "black", "black": "black"}
        return dict(font, weight=heavier.get(font["weight"], "semibold"))
    if kind == "italic":
        return dict(font, italic=True)
    if kind == "code":
        return dict(font, design="monospaced")
    return font


def line_height(font):
    return third(font["size"] * 1.1935)


def text_gap(font):
    """SwiftUI's spacing between two texts in a stack: the lower text's line height less its ascent and descent, rounded up to the pixel."""
    return third(max(0.0, line_pitch(font) - line_height(font)))


def line_pitch(font):
    """The distance between two lines of a text: the text style's line height, else the font's own (ascent plus descent, no leading)."""
    style = font.get("style")
    if style in STYLES:
        return STYLES[style][2] * font["size"] / STYLES[style][0]
    return font["size"] * (ASCENT + DESCENT)


# MARK: spacing preferences (SwiftUI's Spacing, as in OpenSwiftUI's Spacing.swift, Text+Spacing.swift, ResolvedImage.swift, Spacer.swift)

TOP, BOTTOM, LEFT, RIGHT = "top", "bottom", "left", "right"
DEFAULT_SPACING = {("edgeBelowText", TOP): ("d", 0.0), ("edgeAboveText", BOTTOM): ("d", 0.0), ("edgeRightText", LEFT): ("d", 0.0), ("edgeLeftText", RIGHT): ("d", 0.0)}
ZERO_SPACING = {(None, edge): ("d", 0.0) for edge in (TOP, BOTTOM, LEFT, RIGHT)}
SPACER_V = {("textBaseline", TOP): ("d", 0.0), ("textBaseline", BOTTOM): ("d", 0.0), (None, TOP): ("d", 0.0), (None, BOTTOM): ("d", 0.0)}
SPACER_H = {("leftTextBaseline", LEFT): ("d", 0.0), ("rightTextBaseline", RIGHT): ("d", 0.0), (None, LEFT): ("d", 0.0), (None, RIGHT): ("d", 0.0)}
STACK_DEFAULT = 8.0


def text_metrics(font):
    """SwiftUI's TextMetrics for a font: ascend, descend and the leading its style adds."""
    size = font["size"]
    return (size * ASCENT, size * DESCENT, line_pitch(font) - size * (ASCENT + DESCENT))


def text_spacing(font, lines=1):
    """A Text's spacing preferences: text-to-text metrics, baselines, and what an edge keeps from text on either side."""
    ascend, descend, leading = text_metrics(font)
    metrics = (ascend, descend, leading)
    line = ascend + descend
    default_text_spacing = third(line * 0.1)
    default_line_spacing = line + default_text_spacing
    return {
        ("textToText", TOP): ("bottom", metrics),
        ("textToText", BOTTOM): ("top", metrics),
        ("textBaseline", BOTTOM): ("d", -descend),
        ("textBaseline", TOP): ("d", -ascend),
        ("edgeAboveText", TOP): ("d", default_line_spacing - ascend),
        ("edgeBelowText", BOTTOM): ("d", max(default_line_spacing - font["size"] * CAP_HEIGHT, default_text_spacing + descend)),
    }


def symbol_spacing(name, font, height):
    """An SF Symbol image's preferences: it touches text, and keeps its baseline offset from other views."""
    px = symbol_pixels(name, font)
    if px is None:
        return DEFAULT_SPACING
    offset = px[2] / 3
    return {
        ("textToText", TOP): ("d", 0.0),
        ("textToText", BOTTOM): ("d", 0.0),
        ("edgeAboveText", TOP): ("d", offset),
        ("edgeBelowText", BOTTOM): ("d", offset + 1.0),
        ("textBaseline", BOTTOM): ("d", -offset),
        ("textBaseline", TOP): ("d", -(height - offset)),
    }


def spacing_rank(value):
    kind, payload = value
    if kind == "d":
        return (0, payload)
    return (1 if kind == "top" else 2, sum(payload))


def incorporate(minima, other, edges):
    """Merge another view's preferences on some edges, the larger value winning per key."""
    for key, value in other.items():
        if key[1] in edges:
            current = minima.get(key)
            if current is None or spacing_rank(value) > spacing_rank(current):
                minima[key] = value
    return minima


def reset_spacing(minima, edges):
    """What padding or a frame leaves of a view's preferences on the edges it touches: the default view's."""
    minima = {key: value for key, value in minima.items() if key[1] not in edges}
    for edge, category in ((TOP, "edgeBelowText"), (LEFT, "edgeRightText"), (BOTTOM, "edgeAboveText"), (RIGHT, "edgeLeftText")):
        if edge in edges:
            minima[(category, edge)] = ("d", 0.0)
    return minima


def text_to_text(top, bottom):
    """Spacing.TextMetrics.spacing: the lower text's leading, rounded up to the pixel."""
    return third(bottom[2])


def value_distance(a, b):
    if a[0] == "d" and b[0] == "d":
        return a[1] + b[1]
    if a[0] == "d":
        return a[1]
    if b[0] == "d":
        return b[1]
    if a[0] == "top" and b[0] == "bottom":
        return text_to_text(a[1], b[1])
    if a[0] == "bottom" and b[0] == "top":
        return text_to_text(b[1], a[1])
    return None


def spacing_distance(before, after, axis):
    """Spacing.distanceToSuccessorView: the largest distance two neighbours agree on through a shared category, else
    their plain minimums, else None and the stack's own default."""
    far, near = (BOTTOM, TOP) if axis == "v" else (RIGHT, LEFT)
    if len(before) >= len(after):
        source, from_edge, to_edge, target = after, near, far, before
    else:
        source, from_edge, to_edge, target = before, far, near, after
    best = None
    for (category, edge), value in source.items():
        if category is None or edge != from_edge:
            continue
        other = target.get((category, to_edge))
        if other is None:
            continue
        distance = value_distance(value, other)
        if distance is not None and (best is None or distance > best):
            best = distance
    if best is not None:
        return best
    plain = [v[1] for v in (source.get((None, from_edge)), target.get((None, to_edge))) if v is not None and v[0] == "d"]
    return max(plain) if plain else None


FIT_EPSILON = 0.0002
SCALE_STEPS = 20
SCALE_PRECISION = 0.01


def scaled_size(size, factor):
    """UIFont fontScaledByScaleFactor: the point size scaled and rounded to the nearest quarter point."""
    return math.floor(size * factor * 4 + 0.5) / 4


LINK = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|https?://\S+|www\.\S+")


def linked(text):
    """Whether the phone's markdown rendering gives the text a link: an email address or a web address inside it."""
    return bool(LINK.search(text))
PUSH_OUT_MAX_REMAINDER = 10
PUSH_OUT_MIN_RAGGEDNESS = 0.6
HYPHEN = "-"
HYPHENATION_ATTEMPTS = 3
HYPHENATION_LANGUAGE = os.environ.get("BENCH_LANG") or "en_US"


class Boundaries:
    """A text's boundaries of one kind, as the phone's ICU finds them (native.py), addressed by Python string index."""

    def __init__(self, kind):
        self.kind = kind
        self.points = (0,)

    def setText(self, text):
        self.points = native.breaks(self.kind, text)

    def preceding(self, index):
        at = bisect.bisect_left(self.points, index) - 1
        return self.points[at] if at >= 0 else -1

    def following(self, index):
        at = bisect.bisect_right(self.points, index)
        return self.points[at] if at < len(self.points) else -1

    def __iter__(self):
        return iter(self.points[1:])


class Breaks:
    """Unicode line, word and grapheme boundaries, as ICU, the library the phone's text system uses, finds them."""
    line = Boundaries(native.LINE)
    word = Boundaries(native.WORD)
    character = Boundaries(native.GRAPHEME)

    @classmethod
    def iterators(cls):
        return cls.line, cls.word

    @classmethod
    def clusters(cls, text):
        """The extended grapheme clusters of a text as (start, end) ranges."""
        points = native.breaks(native.GRAPHEME, text)
        return [(start, end) for start, end in zip(points, points[1:]) if end > start]


EMOJI_TRACK = [(9.0, 124), (13.0, 116), (16.0, 114), (17.0, 112), (20.0, 110), (32.0, 106), (36.0, 102), (40.0, 100), (48.0, 70), (64.0, 60), (80.0, 62), (96.0, 64), (160.0, 70)]
EMOJI_UPEM = 800.0
KEYCAP = "⃣"
EMOJI_PRESENTATION_SELECTOR = "️"


def emoji_width(size, extra=0.0):
    """The advance of any Apple Color Emoji glyph at a point size: the font's one-em advance drawn a quarter larger up
    to 16 points and easing back to its own size by 24, with the font's `trak` value at the nominal size, rounded to
    the point. Every emoji, flag and joined sequence is one glyph of this width; the phone's lines show it at every
    quarter point from 6 to 40 and beyond."""
    enlarged = size * 1.25 if size <= 16.0 else 20.0 + (size - 16.0) / 2 if size <= 24.0 else size
    return math.floor(enlarged * (1.0 + track_units(EMOJI_TRACK, size) / EMOJI_UPEM) + 0.5) + extra


def is_emoji(cp):
    return native.is_emoji(cp)


@lru_cache(maxsize=20000)
def emoji_spans(text, design, italic):
    """The grapheme clusters the phone draws with Apple Color Emoji: a cluster whose base has the Unicode Emoji
    property and no glyph in the text's own font, or asks for emoji presentation with a variation selector, or is a
    keycap sequence."""
    if not any(ord(ch) >= 0x203c for ch in text):
        return ()
    glyphs = Fonts.cmap(Fonts.file(design, italic))
    spans = []
    for start, end in Breaks.clusters(text):
        cluster = text[start:end]
        base = ord(cluster[0])
        if KEYCAP in cluster or (is_emoji(base) and (base not in glyphs or EMOJI_PRESENTATION_SELECTOR in cluster)):
            spans.append((start, end))
    return tuple(spans)


TAB_STOP = 28.0


def with_tabs(text, design, weight, size, italic, extra, tabular):
    """cum[] for a paragraph with tabs: each tab advances to the next default tab stop, 28 points apart."""
    cum = [0.0]
    first = True
    for segment in text.split("\t"):
        if not first:
            cum.append(math.floor(cum[-1] / TAB_STOP + 1) * TAB_STOP)
        first = False
        part = prefix_widths(segment, design, weight, size, italic, extra, tabular)
        cum += [cum[-1] + w for w in part[1:]]
    return cum


def prefix_widths(text, design, weight, size, italic, extra, tabular=False):
    """cum[i]: the typeset width of text[:i], from one shaping of the whole paragraph as CoreText does it, with
    tabs, tabular digits and emoji clusters each measured their own way."""
    if "\t" in text:
        return with_tabs(text, design, weight, size, italic, extra, tabular)
    if tabular:
        return with_tabular_digits(text, None, weight, size, design, italic, extra)
    spans = emoji_spans(text, design, italic)
    if not spans:
        return shaped_prefix_widths(text, design, weight, size, italic, extra)
    cum = [0.0] * (len(text) + 1)
    position = 0
    total = 0.0
    for start, end in spans + ((len(text), len(text)),):
        if start > position:
            part = shaped_prefix_widths(text[position:start], design, weight, size, italic, extra)
            for i in range(1, start - position + 1):
                cum[position + i] = total + part[i]
            total += part[-1]
        if end > start:
            total += emoji_width(size, extra)
            for i in range(start + 1, end + 1):
                cum[i] = total
        position = end
    return cum


@lru_cache(maxsize=20000)
def shaped_prefix_widths(text, design, weight, size, italic, extra):
    """cum[] for a run of the text's own font: HarfBuzz shapes it whole, the font's exact advances replace the
    rounded ones, and the system's tracking is added per character."""
    cum = [0.0] * (len(text) + 1)
    if not text:
        return cum
    scale = 1.0
    font = Fonts.font(design, weight, size, italic)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True})
    per_cluster = {}
    for info, width in zip(buffer.glyph_infos, positions(font, buffer, size)):
        per_cluster[info.cluster] = per_cluster.get(info.cluster, 0.0) + width * scale
    starts = sorted(per_cluster)
    spacing = tracking(size, design) + extra
    total = 0.0
    for index, cluster in enumerate(starts):
        following = starts[index + 1] if index + 1 < len(starts) else len(text)
        total += per_cluster[cluster]
        for i in range(cluster + 1, following + 1):
            cum[i] = total + spacing * i
    return cum


def styled_prefix_widths(text, font, runs):
    """cum[] for a paragraph whose runs differ in weight, slant or design, each run shaped with its own font."""
    cum = [0.0] * (len(text) + 1)
    position = 0
    total = 0.0
    pieces = []
    for start, end, kind in sorted(runs):
        if start > position:
            pieces.append((position, start, font))
        pieces.append((start, end, run_font(font, kind)))
        position = end
    if position < len(text):
        pieces.append((position, len(text), font))
    for start, end, piece_font in pieces:
        part = prefix_widths(text[start:end], piece_font["design"], piece_font["weight"], piece_font["size"], piece_font["italic"], piece_font.get("tracking") or 0)
        for i in range(1, end - start + 1):
            cum[start + i] = total + part[i]
        total += part[-1]
    return cum


def hyphenated_width(text, start, at, font, span):
    """The width of a line hyphenated at `at`, typeset again on its own: the hyphen kerns with the last letter, which
    no longer kerns with the letter that follows it in the text."""
    args = (font["design"], font["weight"], font["size"], font["italic"])
    if font.get("runs") or font.get("tabular"):
        return span(start, at) + advance(text[at - 1] + HYPHEN, *args) - advance(text[at - 1], *args)
    return advance(text[start:at] + HYPHEN, *args) + (font.get("tracking") or 0) * (at - start + 1)


def paragraph_lines(text, font, width):
    """The line ranges of one paragraph at a width, the way UIFoundation's first-fit typesetter breaks it:
    a cluster fit, the Unicode break before it, a single short last word pulled down when the two
    lines come out more even, and a character break when a word has no break at all."""
    runs = [(a, b, kind) for a, b, kind in font.get("runs") or () if b > a and a < len(text)]
    if runs:
        cum = styled_prefix_widths(text, font, runs)
    else:
        cum = prefix_widths(text, font["design"], font["weight"], font["size"], font["italic"], font.get("tracking") or 0, bool(font.get("tabular")))
    line_breaks, word_breaks = Breaks.iterators()
    line_breaks.setText(text)
    word_breaks.setText(text)
    end = len(text)
    lines = []
    start = 0

    def span(a, b):
        return cum[b] - cum[a]

    def preceding(index):
        position = line_breaks.preceding(index)
        return None if position < 0 or position <= start or position >= index else position

    def hyphenated(index):
        word_start = max(word_breaks.preceding(index), 0, start)
        word_end = word_breaks.following(word_start)
        if word_end < 0 or word_end > end:
            word_end = end
        if word_end <= word_start or index - 1 >= word_end:
            return None
        word = text[word_start:word_end]
        for attempt in range(HYPHENATION_ATTEMPTS):
            location = Hyphenator.before(word, index - attempt - word_start, HYPHENATION_LANGUAGE)
            if location is None or word_start + location <= start:
                return None
            at = word_start + location
            if hyphenated_width(text, start, at, font, span) <= width:
                return at
        return None

    def single_word(at):
        if not text[at].isalnum():
            return False
        position = at
        while True:
            boundary = word_breaks.following(position)
            if boundary < 0 or boundary >= end:
                return True
            before = text[boundary - 1]
            if before == "_" or not before.isalnum():
                return not any(c.isalnum() for c in text[boundary:])
            position = boundary

    while start < end:
        fit = start
        while fit < end and span(start, fit + 1) <= width + FIT_EPSILON:
            fit += 1
        if fit >= end:
            lines.append((start, end))
            break
        if fit == start:
            fit = start + 1
        adjusted = fit
        while adjusted < end and text[adjusted] in "             　" and text[adjusted] != "\t":
            adjusted += 1
        index = adjusted + 1
        if adjusted >= end:
            lines.append((start, end))
            break
        at = preceding(index)
        if at is None:
            at = hyphenated(index)
            if at is None:
                lines.append((start, fit))
                start = fit
                continue
            lines.append((start, at, True))
            start = at
            continue
        if start == 0 and end - at <= PUSH_OUT_MAX_REMAINDER and single_word(at):
            pulled = preceding(at)
            if pulled is not None and span(at, end) > 0 and span(pulled, end) > 0:
                original = span(start, at) / span(at, end)
                candidate = span(start, pulled) / span(pulled, end)
                if candidate >= PUSH_OUT_MIN_RAGGEDNESS and abs(1 - candidate) <= abs(1 - original):
                    at = pulled
        lines.append((start, at))
        start = at
    return cum, lines


def text_lines(text, font, width, strings=None):
    """The widths of the lines a text takes at a width (None: one line per paragraph); `strings` collects each line's text."""
    args = (font["design"], font["weight"], font["size"], font["italic"])
    extra = font.get("tracking") or 0
    lines = []
    offset = 0
    for paragraph in text.split("\n"):
        runs = [(a - offset, b - offset, kind) for a, b, kind in font.get("runs") or () if b > offset and a < offset + len(paragraph)]
        runs = [(max(0, a), min(len(paragraph), b), kind) for a, b, kind in runs]
        paragraph_font = dict(font, runs=runs)
        offset += len(paragraph) + 1
        if width is None or width == math.inf:
            if runs:
                lines.append(styled_prefix_widths(paragraph, font, runs)[-1])
            else:
                lines.append(advance(paragraph, *args, bool(font.get("tabular"))) + extra * max(0, len(paragraph) - 2))
            if strings is not None:
                strings.append(paragraph)
            continue
        cum, ranges = paragraph_lines(paragraph, paragraph_font, width)
        if not ranges:
            lines.append(0.0)
            if strings is not None:
                strings.append("")
        for a, b, *hyphen in ranges:
            lines.append(cum[b] - cum[a] + (advance(HYPHEN, *args) if hyphen else 0.0))
            if strings is not None:
                strings.append(paragraph[a:b].rstrip() + (HYPHEN if hyphen else ""))
    return lines


def truncated_width(text, font, width):
    """The width of a line cut with an ellipsis: the longest prefix that fits beside it."""
    args = (font["design"], font["weight"], font["size"], font["italic"])
    dots = advance("…", *args)
    best = (0.0, "…")
    for end in range(1, len(text) + 1):
        w = advance(text[:end].rstrip(), *args)
        if w + dots > width:
            break
        best = (w + dots, text[:end].rstrip() + "…")
    return best


class Scope:
    def __init__(self, layers, path="", probes=True):
        self.layers = layers
        self.path = path
        self.probes = probes

    def with_values(self, values):
        return Scope(self.layers + [values], self.path, self.probes)

    def child(self, label):
        return Scope(self.layers, self.path + f" › {label}.", self.probes)

    def lookup(self, name):
        for layer in reversed(self.layers):
            if name in layer:
                return layer[name], True
        return None, False


# MARK: expressions

TOKEN = re.compile(r"\s*(?:(\d+\.?\d*)|('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")|\$?([A-Za-z_][A-Za-z0-9_]*)|(==|!=|<=|>=|&&|\|\||[-+*/%<>!?:.,()\[\]]))")


def tokenize(source):
    tokens = []
    position = 0
    while position < len(source):
        match = TOKEN.match(source, position)
        if not match or match.end() == position:
            if source[position:].strip() == "":
                break
            raise ValueError(f"bad expression at {source[position:]!r}")
        position = match.end()
        number, string, name, op = match.groups()
        if number is not None:
            tokens.append(("num", float(number)))
        elif string is not None:
            tokens.append(("str", re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), string[1:-1])))
        elif name is not None:
            tokens.append(("name", name))
        else:
            tokens.append(("op", op))
    return tokens


class Parser:
    def __init__(self, tokens, scope):
        self.tokens = tokens
        self.i = 0
        self.scope = scope

    def peek(self, kind=None, value=None):
        if self.i >= len(self.tokens):
            return None
        kind_, value_ = self.tokens[self.i]
        if kind and kind_ != kind:
            return None
        if value is not None and value_ != value:
            return None
        return self.tokens[self.i]

    def take(self, kind=None, value=None):
        token = self.peek(kind, value)
        if token is None:
            raise ValueError("unexpected token")
        self.i += 1
        return token

    def expression(self):
        condition = self.or_()
        if self.peek("op", "?"):
            self.take()
            then = self.expression()
            self.take("op", ":")
            otherwise = self.expression()
            return then if truthy(condition) else otherwise
        return condition

    def or_(self):
        left = self.and_()
        while self.peek("op", "||"):
            self.take()
            right = self.and_()
            left = left if truthy(left) else right
        return left

    def and_(self):
        left = self.equality()
        while self.peek("op", "&&"):
            self.take()
            right = self.equality()
            left = right if truthy(left) else left
        return left

    def equality(self):
        left = self.comparison()
        while self.peek("op", "==") or self.peek("op", "!="):
            op = self.take()[1]
            right = self.comparison()
            left = equal(left, right) if op == "==" else not equal(left, right)
        return left

    def comparison(self):
        left = self.additive()
        while any(self.peek("op", o) for o in ("<", "<=", ">", ">=")):
            op = self.take()[1]
            right = self.additive()
            left = compare(op, left, right)
        return left

    def additive(self):
        left = self.multiplicative()
        while self.peek("op", "+") or self.peek("op", "-"):
            op = self.take()[1]
            right = self.multiplicative()
            if op == "+":
                if isinstance(left, str) or isinstance(right, str):
                    left = text_of(left) + text_of(right)
                elif isinstance(left, list) and isinstance(right, list):
                    left = left + right
                else:
                    left = (number(left) or 0) + (number(right) or 0)
            else:
                left = (number(left) or 0) - (number(right) or 0)
        return left

    def multiplicative(self):
        left = self.unary()
        while any(self.peek("op", o) for o in ("*", "/", "%")):
            op = self.take()[1]
            right = self.unary()
            a, b = number(left) or 0, number(right) or 0
            left = a * b if op == "*" else (a / b if b else None) if op == "/" else (math.fmod(a, b) if b else None)
        return left

    def unary(self):
        if self.peek("op", "!"):
            self.take()
            return not truthy(self.unary())
        if self.peek("op", "-"):
            self.take()
            return -(number(self.unary()) or 0)
        return self.postfix()

    def postfix(self):
        value = self.primary()
        while True:
            if self.peek("op", "."):
                self.take()
                name = self.take("name")[1]
                if isinstance(value, list):
                    value = float(len(value)) if name in ("count", "length") else None
                elif isinstance(value, str) and name == "length":
                    value = float(len(value))
                else:
                    value = value.get(name) if isinstance(value, dict) else None
            elif self.peek("op", "["):
                self.take()
                index = self.expression()
                self.take("op", "]")
                if isinstance(value, list) and isinstance(index, (int, float)) and 0 <= int(index) < len(value):
                    value = value[int(index)]
                elif isinstance(value, dict):
                    value = value.get(text_of(index))
                else:
                    value = None
            else:
                return value

    def primary(self):
        token = self.take()
        kind, value = token
        if kind == "num":
            return value
        if kind == "str":
            return value
        if kind == "op" and value == "(":
            inner = self.expression()
            self.take("op", ")")
            return inner
        if kind == "op" and value == "[":
            items = []
            while not self.peek("op", "]"):
                items.append(self.expression())
                if self.peek("op", ","):
                    self.take()
            self.take("op", "]")
            return items
        if kind == "name":
            if value in ("true", "false"):
                return value == "true"
            if value in ("null", "nil"):
                return None
            if self.peek("op", "("):
                self.take()
                args = []
                while not self.peek("op", ")"):
                    args.append(self.expression())
                    if self.peek("op", ","):
                        self.take()
                self.take("op", ")")
                return call(value, args)
            found, known = self.scope.lookup(value)
            return found
        raise ValueError(f"unexpected {value!r}")


def truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, list)):
        return len(value) > 0
    return True


def equal(left, right):
    """`==` as the phone has it: by number when both read as one and are not both text."""
    a, b = number(left), number(right)
    if a is not None and b is not None and not (isinstance(left, str) and isinstance(right, str)):
        return a == b
    return type(left) is type(right) and left == right


def identical(left, right):
    """The same JSON value: 2 and 2.0 are, 2 and "2" are not, nor true and 1."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def compare(op, left, right):
    """An order between two numbers, two dates or two texts; nothing between anything else."""
    a, b = number(left), number(right)
    if a is None or b is None:
        a, b = parse_date(left), parse_date(right)
    if (a is None or b is None) and isinstance(left, str) and isinstance(right, str):
        a, b = left, right
    if a is None or b is None:
        return None
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def number(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def text_of(value):
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        if float(value).is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(text_of(v) for v in value)
    return json.dumps(value, ensure_ascii=False)


LOCAL = None


def set_time_zone(name=None, offset=None):
    """The phone's time zone, as the app reports it: its name, and its offset from UTC in seconds for a machine
    whose time zone database lacks the name; this machine's own when the phone said neither."""
    global LOCAL
    LOCAL = None
    if name:
        try:
            LOCAL = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    if LOCAL is None and isinstance(offset, (int, float)):
        LOCAL = timezone(timedelta(seconds=offset))
    if LOCAL is None:
        LOCAL = datetime.now().astimezone().tzinfo


set_time_zone(os.environ.get("BENCH_TZ"))


def parse_date(value):
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return date.astimezone(LOCAL) if date.tzinfo else date.replace(tzinfo=LOCAL)
    return None


def call(name, args):
    a = args + [None] * 3
    if name == "format":
        value, spec = number(a[0]), text_of(a[1]) or "number"
        kind, _, digits = spec.partition(":")
        if value is None:
            return text_of(a[0])
        if kind == "number":
            return f"{value:,.{int(digits) if digits else 0 if value.is_integer() else 1}f}".replace(",", " ")
        if kind == "percent":
            return f"{value * 100:.0f} %"
        if kind == "currency":
            code, _, places = digits.partition(":")
            symbol = {"EUR": "€", "USD": "US$", "GBP": "£", "SEK": "kr", "DKK": "kr", "NOK": "kr", "CHF": "CHF", "JPY": "¥"}.get(code or "EUR", code or "EUR")
            shown = int(places) if places else 0 if value.is_integer() else 2
            return f"{value:,.{shown}f}".replace(",", "\u202f").replace(".", ",") + "\u00a0" + symbol
        if kind == "compact":
            for unit, name in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
                if abs(value) >= unit:
                    scaled = value / unit
                    return f"{scaled:.0f}{name}" if abs(scaled) >= 10 else f"{scaled:.1f}{name}".replace(".0", "")
            return text_of(value)
        if kind == "duration":
            return f"{int(value // 3600)}:{int(value % 3600 // 60):02d}:{int(value % 60):02d}" if value >= 3600 else f"{int(value // 60)}:{int(value % 60):02d}"
        if kind == "bytes":
            return f"{value / 1e6:.1f} MB" if value >= 1e6 else f"{value / 1e3:.0f} kB"
        return text_of(value)
    if name == "date":
        date = parse_date(a[0])
        if not date:
            return text_of(a[0])
        style = text_of(a[1]) or "datetime"
        return {"time": date.strftime("%H:%M").lstrip("0"), "date": date.strftime("%-d %b %Y"), "datetime": date.strftime("%-d %b %Y, %H:%M").lstrip("0"),
                "weekday": date.strftime("%A"), "day": date.strftime("%a %-d"), "month": date.strftime("%B"), "dayMonth": date.strftime("%-d %b"),
                "monthYear": date.strftime("%b %Y"), "relative": "in 2 hours"}.get(style, date.strftime("%-d %b %Y, %H:%M"))
    if name in ("count", "len"):
        return float(len(a[0])) if isinstance(a[0], (list, dict, str)) else 0.0
    if name in ("sum", "avg", "min", "max"):
        listed = name in ("sum", "avg") or len(args) == 1 or (len(args) == 2 and isinstance(args[1], str))
        if listed:
            key = a[1] if isinstance(a[1], str) else None
            values = [number(item.get(key) if key and isinstance(item, dict) else None if key else item) for item in (a[0] if isinstance(a[0], list) else [])]
        else:
            values = [number(value) for value in args]
        values = [v for v in values if v is not None]
        if not values:
            return 0.0 if name == "sum" else None
        return {"sum": sum(values), "avg": sum(values) / len(values), "min": min(values), "max": max(values)}[name]
    if name == "round":
        factor = 10 ** (number(a[1]) or 0)
        scaled = (number(a[0]) or 0) * factor
        return math.copysign(math.floor(abs(scaled) + 0.5), scaled) / factor
    if name == "abs":
        return abs(number(a[0]) or 0)
    if name == "clamp":
        value = number(a[0]) or 0
        low, high = number(a[1]), number(a[2]) if len(args) > 2 else None
        return min(max(value, value if low is None else low), value if high is None else high)
    if name == "upper":
        return text_of(a[0]).upper()
    if name == "lower":
        return text_of(a[0]).lower()
    if name == "join":
        return (a[1] if isinstance(a[1], str) else ", ").join(text_of(v) for v in (a[0] if isinstance(a[0], list) else []))
    if name == "pluck":
        return [item.get(text_of(a[1])) if isinstance(item, dict) else None for item in (a[0] if isinstance(a[0], list) else [])]
    if name == "contains":
        if isinstance(a[0], list):
            return any(identical(item, a[1]) for item in a[0])
        needle = text_of(a[1]).lower()
        return bool(needle) and needle in text_of(a[0]).lower()
    if name == "filter":
        items = a[0] if isinstance(a[0], list) else []
        return [item for item in items if isinstance(item, dict) and (truthy(item.get(a[1])) if a[2] is None else item.get(a[1]) == a[2])]
    if name == "find":
        items = a[0] if isinstance(a[0], list) else []
        return next((item for item in items if isinstance(item, dict) and (truthy(item.get(a[1])) if a[2] is None else item.get(a[1]) == a[2])), None)
    if name == "now":
        return now(timezone.utc).isoformat()
    if name == "until":
        return "in 2 h"
    if name == "ago":
        date = parse_date(a[0])
        if not date:
            return ""
        seconds = (now(date.tzinfo) - date).total_seconds()
        if seconds < 60:
            return "just now"
        for unit, span in (("min.", 60), ("hr.", 3600)):
            if seconds < span * (60 if unit == "min." else 24):
                return f"{int(seconds // span)} {unit} ago"
        days = int(seconds // 86400)
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            return f"{days // 7} wk. ago"
        if days < 365:
            return f"{days // 30} mo. ago"
        return f"{days // 365} yr. ago"
    if name == "isToday":
        date = parse_date(a[0])
        return bool(date and date.date() == now(date.tzinfo).date())
    if name == "isPast":
        date = parse_date(a[0])
        return bool(date and date <= now(date.tzinfo))
    if name == "string":
        return text_of(a[0])
    if name == "number":
        return number(a[0])
    if name in ("org", "markdown"):
        from dedala import orgtree

        tree = orgtree.parse(text_of(a[0]), name)
        return orgtree.select(tree, a[1]) if isinstance(a[1], str) else tree
    return None


def evaluate(source, scope):
    try:
        parser = Parser(tokenize(source), scope)
        value = parser.expression()
        return value
    except (ValueError, IndexError, TypeError, AttributeError):
        return None


REFERENCE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[[0-9]+\])*")
INTERPOLATION = re.compile(r"\$\{([^}]*)\}|\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)")


def resolve(value, scope, known_only=False):
    """A value with its expressions evaluated: `$name`, `${expr}`, or text with them inside."""
    if isinstance(value, str):
        if "$" not in value:
            return value
        whole = INTERPOLATION.fullmatch(value)
        if whole:
            source = whole.group(1) if whole.group(1) is not None else whole.group(2)
            result = evaluate(source, scope)
            if known_only and result is None:
                return value
            return result

        def replace(match):
            source = match.group(1) if match.group(1) is not None else match.group(2)
            return text_of(evaluate(source, scope))

        return INTERPOLATION.sub(replace, value)
    if isinstance(value, list):
        return [resolve(v, scope, known_only) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, scope, known_only) for k, v in value.items()}
    return value


def is_view(value):
    if isinstance(value, dict):
        return any(key[:1].isupper() for key in value)
    if isinstance(value, list):
        return any(is_view(v) for v in value)
    return False


# MARK: boxes

PUSHED = {"padding", "background", "frame", "width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight", "cornerRadius", "overlay", "clipShape", "opacity", "offset", "margin", "fixedSize", "aspectRatio", "layoutPriority", "border", "shadow"}
MODIFIERS = {"font", "fontWeight", "fontDesign", "bold", "italic", "foregroundStyle", "color", "lineLimit", "lineSpacing", "multilineTextAlignment",
             "minimumScaleFactor", "monospacedDigit", "monospaced", "textCase", "tracking", "contentTransition", "symbolRenderingMode", "symbolVariant",
             "symbolEffect", "imageScale", "tint", "controlSize", "labelStyle", "aspectRatio", "frame", "width", "height", "minWidth", "maxWidth",
             "minHeight", "maxHeight", "fixedSize", "layoutPriority", "padding", "background", "glassEffect", "clipShape", "cornerRadius", "border",
             "overlay", "shadow", "margin", "opacity", "scale", "rotation", "offset", "blur", "saturation", "grayscale", "zIndex", "onTap", "disabled",
             "transition", "accessibilityLabel", "modifiers"}
OWN_SURFACES = {"Card", "Carousel", "ScrollView", "Pages"}


class UnknownView(ValueError):
    """A view the twin has no measure for: the card cannot be checked, rather than laid out with a hole where the phone
    draws its unknown-view mark."""


class Box:
    __slots__ = ("kind", "node", "value", "children", "path", "probed", "font", "scope", "extra", "memo", "frame", "text", "lines", "shaped")

    def __init__(self, kind, node, value, path, probed, font, scope):
        self.kind = kind
        self.node = node
        self.value = value
        self.children = []
        self.path = path
        self.probed = probed
        self.font = font
        self.scope = scope
        self.extra = {}
        self.memo = {}
        self.frame = None
        self.text = None
        self.lines = None
        self.shaped = None


class Engine:
    def __init__(self, card, components=None, width=WIDTH, derived=None, page=False):
        self.card = card
        self.page = page
        self.components = components or {}
        self.width = width
        self.derived = derived or {}
        self.frames = []
        self.texts = []
        self.images = []
        self.problems = []

    # MARK: building

    def build(self):
        data = self.card.get("data") or {}
        self.stores = self.card.get("stores") or {}
        state = self.card.get("state") or {}
        if isinstance(state, dict):
            state = {k: resolve(v, Scope([self.stores, data])) if isinstance(v, str) and "$" in v else v for k, v in state.items()}
        layers = [self.stores, data, self.derived, state]
        scope = Scope([layer for layer in layers if isinstance(layer, dict)])
        view = self.card.get("view") if self.page else self.surfaced(self.card.get("view"))
        return self.make(view, scope, dict(DEFAULT_FONT))

    def surfaced(self, view):
        if not isinstance(view, dict):
            return view
        kind = next((key for key in view if key[:1].isupper()), "")
        if kind == "ScrollView" and view.get("axis") != "horizontal":
            inner = {k: v for k, v in view.items() if k not in ("ScrollView", "axis", "paging")}
            inner["VStack"] = view["ScrollView"]
            inner.setdefault("alignment", "leading")
            return self.surfaced(inner)
        items = view.get(kind) if isinstance(view.get(kind), list) else [view[kind]] if kind in view else []
        if self.is_surface(view) or kind in ("VStack", "HStack", "Group") and items and all(self.is_surface(item) for item in items):
            return view
        inner = {k: v for k, v in view.items() if k != "padding"}
        return {"Card": [inner]}

    def is_surface(self, node):
        if not isinstance(node, dict):
            return False
        if ("ForEach" in node or "List" in node) and "content" in node:
            return self.is_surface(node["content"])
        if "If" in node:
            return all(self.is_surface(node[key]) for key in ("then", "else") if key in node)
        names = OWN_SURFACES | set(self.components) | {"background", "glassEffect"}
        return any(key in names for key in node)

    def items(self, value, scope):
        if value is None:
            return []
        if isinstance(value, list):
            out = []
            for index, child in enumerate(value):
                out += self.expand(child, scope.child(str(index + 1)))
            return out
        return self.expand(value, scope.child("1"))

    def expand(self, node, scope):
        if not isinstance(node, dict) or "state" in node:
            return [(node, scope)]
        if self.hidden(node, scope):
            return []
        if "ForEach" in node or "List" in node:
            source = node["ForEach"] if "ForEach" in node else node["List"]
            if isinstance(source, str) and not source.startswith("$"):
                resolved = evaluate(source, scope)
            else:
                resolved = resolve(source, scope)
            if isinstance(resolved, dict):
                resolved = [{"key": k, "value": v} for k, v in sorted(resolved.items())]
            elements = resolved if isinstance(resolved, list) else []
            if "List" in node:
                elements = elements[:LIST_PROBED_ROWS]
            pushed = {k: v for k, v in node.items() if k not in LOOP_OWN}
            name = node.get("as") or "item"
            index_name = node.get("index") or "index"
            out = []
            for index, element in enumerate(elements):
                inner = scope.with_values({name: element, index_name: float(index)})
                inner = Scope(inner.layers, inner.path + f"ForEach[{index}]", inner.probes)
                out += self.items(push_into(pushed, node.get("content")) if pushed else node.get("content"), inner)
            return out
        if "If" in node:
            condition = node["If"]
            holds = truthy(self.bare(condition, scope))
            branch = node.get("then") if holds else node.get("else")
            inner = Scope(scope.layers, scope.path + ("If(then)" if holds else "If(else)"), scope.probes)
            return self.items(branch, inner)
        return [(node, scope)]

    def input_button(self, node, scope):
        """A Photo or Dictate input as the phone draws it: a bordered button
        with its symbol, under the picture once one is taken."""
        kind = "Photo" if "Photo" in node else "Dictate"
        rest = {key: value for key, value in node.items() if key not in (kind, "bind", "source", "append")}
        symbol = ("camera" if kind == "Photo" else "mic")
        button = {"Button": node[kind], "symbol": symbol, "style": "bordered", **rest}
        bound = resolve(node.get("bind"), scope) if node.get("bind") else None
        if kind == "Photo" and isinstance(bound, dict) and (bound.get("local") or bound.get("blobs") or bound.get("path")):
            return {"VStack": [{"Rectangle": {}, "frame": {"height": 220, "maxWidth": "infinity"}}, button], "spacing": 8, "alignment": "leading"}
        return button

    def hidden(self, node, scope):
        if "hidden" in node and truthy(self.bare(node["hidden"], scope)):
            return True
        if "visible" in node and not truthy(self.bare(node["visible"], scope)):
            return True
        return False

    def bare(self, value, scope):
        """A condition as the phone reads it: an expression written bare
        (`count(items) == 0`, `$a && !$b`), a reference or a `${…}`."""
        if isinstance(value, str) and "${" not in value and not REFERENCE.fullmatch(value):
            return evaluate(value, scope)
        return resolve(value, scope)

    def font_for(self, node, font, scope):
        font = dict(font)
        value = node.get("font")
        if value is not None:
            value = resolve(value, scope)
            if isinstance(value, (int, float)):
                font.update(size=float(value), weight="regular", design="default", style=None)
            elif isinstance(value, dict):
                font.update(size=float(value.get("size") or 17), weight=value.get("weight") or "regular", design=value.get("design") or "default", style=None)
            elif isinstance(value, str):
                parts = value.split(".")
                if parts[0] in STYLES:
                    size, weight, _ = STYLES[parts[0]]
                    font.update(size=float(size), weight=weight, style=parts[0], design="default", italic=False)
                    for part in parts[1:]:
                        if part in WEIGHTS:
                            font["weight"] = part
                        elif part in ("rounded", "serif", "monospaced", "default"):
                            font["design"] = part
                        elif part == "italic":
                            font["italic"] = True
        if "fontWeight" in node:
            font["weight"] = resolve(node["fontWeight"], scope) or font["weight"]
        if "fontDesign" in node:
            font["design"] = resolve(node["fontDesign"], scope) or font["design"]
        if truthy(resolve(node.get("bold"), scope)):
            font["weight"] = "semibold"
        if truthy(resolve(node.get("italic"), scope)):
            font["italic"] = True
        if truthy(resolve(node.get("monospaced"), scope)):
            font["design"] = "monospaced"
        for key in ("lineLimit", "minimumScaleFactor", "textCase", "tracking", "labelStyle", "controlSize", "imageScale", "monospacedDigit", "lineSpacing"):
            if key in node:
                font[key] = resolve(node[key], scope)
        return font

    def make(self, node, scope, font):
        if node is None:
            return None
        if isinstance(node, dict) and ("Photo" in node or "Dictate" in node):
            node = self.input_button(node, scope)
        if isinstance(node, (bool, int, float)):
            return self.text_box(text_of(node), {}, scope.path, False, font, scope)
        if isinstance(node, str):
            value = resolve(node, scope)
            if isinstance(value, (dict, list)) and node.startswith("$"):
                return self.make(value, scope, font)
            return self.text_box(text_of(value), {}, scope.path + "Text", scope.probes, font, scope)
        if isinstance(node, list):
            box = Box("VStack", {"spacing": 12, "alignment": "leading"}, node, scope.path, False, font, scope)
            box.children = [self.make(child, inner, font) for child, inner in self.items(node, scope)]
            return box
        if not isinstance(node, dict):
            return None
        node = dict(node)
        if "state" in node:
            declared = node.pop("state")
            if isinstance(declared, dict):
                scope = scope.with_values({k: v for k, v in declared.items() if not scope.lookup(k)[1]})
        if self.hidden(node, scope):
            return None
        if "ForEach" in node or "List" in node or "If" in node:
            box = Box("Group", node, None, scope.path, False, font, scope)
            box.children = [self.make(child, inner, font) for child, inner in self.items(node, scope)]
            return box
        keys = sorted(key for key in node if key[:1].isupper())
        if not keys:
            return None
        kind = keys[0]
        font = self.font_for(node, font, scope)
        path = scope.path + kind
        scope = Scope(scope.layers, path, scope.probes)
        probed = scope.probes and kind != "Spacer"
        value = node.get(kind)
        if kind in self.components:
            box = Box(kind, node, value, path, probed, font, scope)
            box.children = [self.component(self.components[kind], value, scope, path, font)]
            return box
        if kind == "Text":
            box = self.text_node(value, node, path, probed, font, scope)
        else:
            box = Box(kind, node, value, path, probed, font, scope)
            self.fill(box, scope, font)
        for key in ("overlay", "background"):
            layer = node.get(key)
            if is_view(layer):
                made = self.make(layer, scope.child(key), font)
                if made is not None:
                    box.extra[key] = made
        return box

    def component(self, definition, value, scope, path, font):
        props = dict(definition.get("props") or {})
        if isinstance(value, dict):
            resolved = {k: (resolve(v, scope, known_only=True) if is_view(v) else resolve(v, scope)) for k, v in value.items()}
        else:
            resolved = resolve(value, scope)
        if isinstance(resolved, dict):
            props.update(resolved)
        elif resolved is not None:
            props["value"] = resolved
        body = definition.get("body")
        if isinstance(body, dict) and definition.get("state"):
            body = dict(body)
            body["state"] = {**definition["state"], **(body.get("state") or {})}
        inner = Scope([self.stores, props], path + " › ", scope.probes)
        return self.make(body, inner, font)

    def text_node(self, value, node, path, probed, font, scope):
        if isinstance(value, dict):
            if "timer" in value or "countdown" in value:
                date = parse_date(resolve(value.get("timer", value.get("countdown")), scope))
                seconds = 0.0
                if date:
                    delta = (date - now(date.tzinfo)).total_seconds()
                    seconds = max(0.0, delta) if "countdown" in value else max(0.0, -delta)
                string = f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{int(seconds % 60):02d}" if seconds >= 3600 else f"{int(seconds // 60)}:{int(seconds % 60):02d}"
            elif "date" in value:
                string = call("date", [resolve(value["date"], scope), {"time": "time", "relative": "relative", "offset": "relative"}.get(value.get("style"), "date")])
                if value.get("style") in ("relative", "offset"):
                    string = "2 hours"
                elif value.get("style") == "timer":
                    string = "0:00:00"
            elif "number" in value:
                string = call("format", [resolve(value["number"], scope), value.get("format") or "number"])
            else:
                string = ""
        else:
            string = text_of(resolve(value, scope))
        return self.text_box(string, node, path, probed, font, scope)

    def text_box(self, string, node, path, probed, font, scope):
        box = Box("Text", node, string, path, probed, font, scope)
        if font.get("textCase") == "uppercase":
            string = string.upper()
        elif font.get("textCase") == "lowercase":
            string = string.lower()
        box.text, runs = styled_runs(string)
        if runs:
            box.font = dict(box.font, runs=runs)
        if font.get("monospacedDigit"):
            box.font = dict(box.font, tabular=True)
        return box

    def fill(self, box, scope, font):
        kind, node, value = box.kind, box.node, box.value
        children = lambda v, inner=scope, f=font: [b for b in (self.make(child, s, f) for child, s in self.items(v, inner)) if b is not None]
        if kind == "Group":
            pushed = {k: v for k, v in node.items() if k in MODIFIERS or k in PUSHED}
            if pushed:
                box.node = {k: v for k, v in node.items() if k not in pushed}
                pushed["_pushed"] = True
                value = [dict(pushed, **child) if isinstance(child, dict) else dict(pushed, Text=child) for child in (value if isinstance(value, list) else [value])]
            box.children = children(value)
        elif kind in ("VStack", "HStack", "ZStack", "GlassGroup", "Columns"):
            box.children = children(value)
        elif kind == "Card":
            box.children = children(value)
        elif kind == "Section":
            parts = []
            if value is not None:
                title = styled("title3", "bold")
                parts.append(self.text_box(text_of(resolve(value, scope)), {}, box.path + " › title", False, title, scope))
            parts += children(node.get("content"))
            if node.get("footer") is not None:
                foot = styled("footnote")
                parts.append(self.text_box(text_of(resolve(node["footer"], scope)), {}, box.path + " › footer", False, foot, scope))
            box.children = parts
        elif kind == "DisclosureGroup":
            flag = node.get("expanded")
            box.extra["expanded"] = truthy(resolve(flag, scope)) if isinstance(flag, str) and flag.startswith("$") else False
            box.children = children(node.get("content"))
        elif kind == "Grid":
            rows = []
            for row, inner in self.items(value, scope):
                if isinstance(row, list):
                    cells = [b for b in (self.make(cell, s, font) for cell, s in self.items(row, inner)) if b is not None]
                    rows.append(("row", cells))
                else:
                    made = self.make(row, inner, font)
                    if made is not None:
                        rows.append(("span", [made]))
            box.extra["rows"] = rows
            box.children = [cell for _, cells in rows for cell in cells]
        elif kind == "Carousel":
            box.children = children(value, scope)
        elif kind in ("ScrollView", "Pages"):
            quiet = Scope(scope.layers, scope.path, False)
            box.children = children(value, quiet)
        elif kind == "Label":
            parts = value if isinstance(value, list) else [value.get("title") if isinstance(value, dict) else value, value.get("symbol") if isinstance(value, dict) else None]
            box.text = plain(text_of(resolve(parts[0], scope)))
            box.extra["symbol"] = text_of(resolve(parts[1], scope)) if len(parts) > 1 else ""
        elif kind == "Image":
            if isinstance(value, dict) and ("url" in value or "asset" in value):
                box.extra["bitmap"] = True
            else:
                box.extra["symbol"] = text_of(resolve(value if not isinstance(value, dict) else value.get("symbol"), scope))
            box.extra["resizable"] = truthy(resolve(node.get("resizable"), scope)) if node.get("resizable") is not None else False
        elif kind in ("Button", "Menu"):
            if is_view(value):
                box.children = [self.make(value, scope, font)]
            else:
                box.text = plain(text_of(resolve(value, scope)))
                box.extra["symbol"] = text_of(resolve(node.get("symbol"), scope)) if node.get("symbol") else ""
                if kind == "Menu" and not box.text and box.extra["symbol"]:
                    box.font = dict(box.font, labelStyle="iconOnly")
        elif kind in ("Toggle", "Stepper", "Link", "TextField", "Slider", "DatePicker", "TextEditor"):
            box.text = plain(text_of(resolve(value, scope)))
        elif kind == "File":
            shown = resolve(value, scope)
            box.text = plain(text_of(shown.get("text") if isinstance(shown, dict) else shown))
            box.extra["height"] = number(resolve(node.get("height"), scope))
        elif kind == "Picker":
            options = resolve(node.get("options"), scope) or []
            labels = [text_of(o.get("label") or o.get("value")) if isinstance(o, dict) else text_of(o) for o in options]
            box.extra["labels"] = labels
            chosen = resolve(node.get("bind"), scope)
            box.text = text_of(chosen) if chosen is not None else (labels[0] if labels else "")
        elif kind == "Gauge":
            box.extra["label"] = text_of(resolve(node.get("label"), scope)) if node.get("label") is not None else None
            box.extra["current"] = text_of(resolve(node.get("current"), scope)) if node.get("current") is not None else None
            box.extra["bounds"] = node.get("min") is not None or node.get("max") is not None
        elif kind == "ProgressView":
            box.extra["determinate"] = resolve(value, scope) is not None
            box.extra["label"] = text_of(resolve(node.get("label"), scope)) if node.get("label") is not None else None
        elif kind == "Face":
            box.extra["size"] = number(resolve(value, scope) if not isinstance(value, dict) else value.get("size")) or 56

    # MARK: measuring

    def spacing(self, box, default=8.0):
        value = resolve(box.node.get("spacing"), box.scope) if "spacing" in box.node else None
        return float(value) if isinstance(value, (int, float)) else default

    PADDED_BUTTONS = ("bordered", "borderedProminent", "glass", "prominent")

    def gap(self, box, a, b, axis):
        """The distance between two neighbours in a stack, from their spacing preferences; the stack's default of 8 when they share none."""
        distance = spacing_distance(self.preferences(a), self.preferences(b), axis)
        return STACK_DEFAULT if distance is None else max(0.0, distance)

    def preferences(self, box):
        """A view's spacing preferences after its modifiers, memoized on the box."""
        if box.kind == "Spacer":
            return SPACER_H if box.extra.get("axis") == "h" else SPACER_V
        if "spacing" not in box.extra:
            minima = dict(self.own_preferences(box))
            node = box.node if isinstance(box.node, dict) else {}
            edges = set()
            if "padding" in node:
                top, leading, bottom, trailing = self.pads(resolve(node["padding"], box.scope))
                edges |= {edge for edge, inset in ((TOP, top), (LEFT, leading), (BOTTOM, bottom), (RIGHT, trailing)) if inset}
            frame = self.mods(box)
            if any(frame.get(name) is not None for name in ("height", "minHeight", "maxHeight", "idealHeight")):
                edges |= {TOP, BOTTOM}
            if any(frame.get(name) is not None for name in ("width", "minWidth", "maxWidth", "idealWidth")):
                edges |= {LEFT, RIGHT}
            box.extra["spacing"] = reset_spacing(minima, edges) if edges else minima
        return box.extra["spacing"]

    def own_preferences(self, box):
        kind = box.kind
        if kind in ("Text", "Link"):
            return text_spacing(box.font)
        if kind == "Label":
            return self.row_preferences([("symbol", box.extra.get("symbol", "")), ("text", None)], box)
        if kind in ("Button", "Menu"):
            if box.node.get("style") in self.PADDED_BUTTONS:
                return DEFAULT_SPACING
            if box.children:
                return self.preferences(box.children[0])
            if box.extra.get("symbol") and box.font.get("labelStyle") != "titleOnly":
                return self.row_preferences([("symbol", box.extra["symbol"]), ("text", None)], box)
            return text_spacing(box.font)
        if kind == "Image":
            if box.extra.get("bitmap") or box.extra.get("resizable"):
                return DEFAULT_SPACING
            name = box.extra.get("symbol", "")
            return symbol_spacing(name, box.font, self.symbol_size(name, box.font)[1])
        if kind == "Spacer":
            return SPACER_H if box.extra.get("axis") == "h" else SPACER_V
        if kind in ("VStack", "Group", "Section"):
            return self.stack_preferences([kid for kid in box.children if kid is not None], "v")
        if kind == "HStack":
            return self.stack_preferences([kid for kid in box.children if kid is not None], "h")
        if kind == "ZStack":
            minima = {}
            for kid in box.children:
                if kid is not None:
                    incorporate(minima, self.preferences(kid), {TOP, BOTTOM, LEFT, RIGHT})
            return minima
        if kind == "Grid":
            rows = [self.stack_preferences(cells, "h") for _, cells in box.extra.get("rows", [])]
            return self.stack_preferences(rows, "v", raw=True)
        if kind in self.components and box.children and box.children[0] is not None:
            return self.preferences(box.children[0])
        return DEFAULT_SPACING

    def row_preferences(self, parts, box):
        """A label's preferences: its icon and title side by side."""
        minima = []
        for what, name in parts:
            if what == "symbol" and name:
                minima.append(symbol_spacing(name, box.font, self.symbol_size(name, box.font)[1]))
            elif what == "text":
                minima.append(text_spacing(box.font))
        return self.stack_preferences(minima, "h", raw=True)

    def stack_preferences(self, kids, axis, raw=False):
        """StackLayout.spacing: every child's preferences on the cross edges, the first child's at the start, the last child's at the end."""
        if not kids:
            return dict(ZERO_SPACING)
        minima = {}
        for index, kid in enumerate(kids):
            edges = {LEFT, RIGHT} if axis == "v" else {TOP, BOTTOM}
            if index == 0:
                edges.add(TOP if axis == "v" else LEFT)
            if index == len(kids) - 1:
                edges.add(BOTTOM if axis == "v" else RIGHT)
            incorporate(minima, kid if raw else self.preferences(kid), edges)
        return minima

    def measure(self, box, pw, ph):
        """Memoised per proposal; the text details of the proposal measured last stay on the box."""
        key = (pw, ph)
        if key in box.memo:
            kept = box.extra.get("by_key", {}).get(key)
            if kept is not None:
                box.extra["lines_text"], box.lines, box.extra["cut_lines"], box.extra["scale"], box.extra["content"], box.extra["framed"] = kept
            return box.memo[key]
        box.extra["scale"] = 1.0
        box.extra.pop("cut_lines", None)
        size = self.measure_modified(box, pw, ph)
        box.memo[key] = size
        box.extra.setdefault("scales", {})[key] = box.extra.get("scale", 1.0)
        box.extra.setdefault("by_key", {})[key] = (box.extra.get("lines_text"), box.lines, box.extra.get("cut_lines"), box.extra.get("scale", 1.0), box.extra.get("content"), box.extra.get("framed"))
        return size

    def mods(self, box):
        node = box.node
        scope = box.scope
        frame = dict(resolve(node.get("frame"), scope) or {}) if isinstance(node.get("frame"), dict) else {}
        for name in ("width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight"):
            if name in node:
                frame[name] = resolve(node[name], scope)
        for extra in node.get("modifiers") or []:
            if isinstance(extra, dict):
                for name, value in extra.items():
                    if name == "frame" and isinstance(value, dict):
                        frame.update(resolve(value, scope))
                    elif name in ("width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight"):
                        frame[name] = resolve(value, scope)
        return frame

    def length(self, value):
        if value == "infinity":
            return math.inf
        return float(value) if isinstance(value, (int, float)) else None

    def pads(self, value):
        if isinstance(value, bool):
            return (16.0,) * 4 if value else (0.0,) * 4
        if isinstance(value, (int, float)):
            return (float(value),) * 4
        if isinstance(value, dict):
            h = value.get("horizontal", value.get("h"))
            v = value.get("vertical", value.get("v"))
            return (float(value.get("top", v) or 0), float(value.get("leading", h) or 0), float(value.get("bottom", v) or 0), float(value.get("trailing", h) or 0))
        return (0.0,) * 4

    def measure_modified(self, box, pw, ph):
        """The node's size with its modifiers in the app's order: frame, then padding, then margin."""
        node = box.node
        scope = box.scope
        frame = self.mods(box)
        fixed_w = self.length(frame.get("width"))
        fixed_h = self.length(frame.get("height"))
        min_w, max_w = self.length(frame.get("minWidth")), self.length(frame.get("maxWidth"))
        min_h, max_h = self.length(frame.get("minHeight")), self.length(frame.get("maxHeight"))
        margin = self.pads(resolve(node.get("margin"), scope)) if "margin" in node else (0.0,) * 4
        padding = self.pads(resolve(node.get("padding"), scope)) if "padding" in node else (0.0,) * 4
        for extra in node.get("modifiers") or []:
            if isinstance(extra, dict) and "padding" in extra:
                p = self.pads(resolve(extra["padding"], scope))
                padding = tuple(a + b for a, b in zip(padding, p))
        fix_w, fix_h = fixed_axes(resolve(node.get("fixedSize"), scope)) if "fixedSize" in node else (False, False)
        ratio = resolve(node.get("aspectRatio"), scope) if "aspectRatio" in node else None
        pad_w = padding[1] + padding[3] + margin[1] + margin[3]
        pad_h = padding[0] + padding[2] + margin[0] + margin[2]

        frame_pw = None if pw is None else max(0.0, pw - pad_w)
        frame_ph = None if ph is None else max(0.0, ph - pad_h)
        content_pw = fixed_w if fixed_w is not None else (None if frame_pw is None else self.clamp(frame_pw, min_w, max_w))
        content_ph = fixed_h if fixed_h is not None else (None if frame_ph is None else self.clamp(frame_ph, min_h, max_h))
        if fix_w:
            content_pw = None
        if fix_h:
            content_ph = None
        r = float(ratio) if isinstance(ratio, (int, float)) and ratio else None
        if r:
            if content_pw not in (None, math.inf) and (content_ph is None or content_ph == math.inf or content_pw / r <= content_ph):
                content_ph = content_pw / r
            elif content_ph not in (None, math.inf):
                content_pw = content_ph * r
        cw, chh = self.intrinsic(box, content_pw, content_ph)
        if r and content_pw not in (None, math.inf):
            cw, chh = content_pw, content_pw / r
            if box.kind == "Image" and box.extra.get("resizable") and not box.extra.get("bitmap"):
                cw, chh = self.fitted(self.symbol_aspect(box.extra.get("symbol", ""), box.font), cw, third(chh))
        fw = self.framed(cw, fixed_w, min_w, max_w, frame_pw)
        fh = self.framed(chh, fixed_h, min_h, max_h, frame_ph)
        if (content_pw is None and cw > fw + 1e-6) or (content_ph is None and chh > fh + 1e-6):
            cw, chh = self.intrinsic(box, fw if content_pw is None else content_pw, fh if content_ph is None else content_ph)
        box.extra["padding"] = padding
        box.extra["margin"] = margin
        box.extra["content"] = (cw, chh)
        box.extra["framed"] = (fw, fh)
        return (fw + pad_w, fh + pad_h)

    def framed(self, child, fixed, low, high, proposal):
        if fixed is not None:
            return fixed
        if low is None and high is None:
            return child
        if high == math.inf and proposal == math.inf:
            return math.inf
        if high is not None and proposal not in (None, math.inf):
            return self.clamp(proposal, low, high) if high == math.inf else self.clamp(max(child, min(proposal, high)), low, high)
        return self.clamp(child, low, high)

    @staticmethod
    def clamp(value, low, high):
        if low is not None:
            value = max(value, low)
        if high is not None and high != math.inf:
            value = min(value, high)
        return value

    def symbol_aspect(self, name, font):
        """A resizable symbol keeps its alignment rect's proportions, as SwiftUI's Image.LayoutMetrics has it."""
        px = symbol_pixels(name, font)
        if px and px[5]:
            return px[4] / px[5]
        w, h = self.symbol_size(name, font)
        return w / h if h else 1.0

    @staticmethod
    def fitted(aspect, pw, ph):
        """The largest size of this aspect inside a proposal; a missing side follows the other."""
        if pw in (None, math.inf) and ph in (None, math.inf):
            return (100.0, 100.0 / aspect)
        if ph in (None, math.inf):
            return (pw, pw / aspect)
        if pw in (None, math.inf):
            return (ph * aspect, ph)
        if pw / aspect <= ph:
            return (pw, pw / aspect)
        return (ph * aspect, ph)

    def symbol_size(self, name, font):
        px = symbol_pixels(name, font)
        if px:
            return (px[0] / 3, px[1] / 3)
        size = font["size"] * IMAGE_SCALE.get(font.get("imageScale") or "medium", 1.0)
        wf, hf = SYMBOLS.get(name) or SYMBOLS.get(name.replace(".fill", "")) or SYMBOLS.get(name + ".fill") or SYMBOL
        return (third(size * wf), third(size * hf))

    def symbol_column(self, name, font):
        """The room a label gives its icon: the symbol image with its margins."""
        return self.symbol_size(name, font)

    def symbol_baseline(self, name, font, height):
        """A symbol's baseline from its top: the phone places it on the text baseline."""
        px = symbol_pixels(name, font)
        if px:
            return height - (px[2] + px[3]) / 3
        return height * 0.85

    def text_field_size(self, box, node, font, pw):
        """A plain field holding text is that text's height plus 5/3 of a point, one showing its placeholder is the
        placeholder's height rounded up to the point and never under 22 points; a filled one adds 12 and 9 points of
        padding around it; `lines` reserves that many lines, and a vertical field is a full line pitch for every line
        typed, one when empty."""
        filled = text_of(resolve(node.get("style"), box.scope)) != "plain"
        inset_w, inset_h = (24.0, 18.0) if filled else (0.0, 0.0)
        full = pw if pw not in (None, math.inf) else 200.0
        lines = number(resolve(node.get("lines"), box.scope))
        reserved = max(1, int(lines)) if lines else 1
        _, h = self.text_size(box, "\n".join(["X"] * reserved), font, None)
        vertical = bool(lines) or truthy(resolve(node.get("multiline"), box.scope))
        typed = text_of(resolve(node.get("bind"), box.scope))
        count = len(text_lines(typed, font, max(0.0, full - inset_w))) if typed and vertical else 1
        if vertical and not lines:
            h = count * line_pitch(font)
        elif lines:
            h = max(h, min(count, 8) * line_pitch(font))
        elif not truthy(resolve(node.get("secure"), box.scope)):
            h = h + 5 / 3 if typed else max(math.ceil(h - 1e-6), 22.0)
        return (full, h + inset_h)

    def text_size(self, box, text, font, pw, limit=None):
        single = line_height(font)
        pitch = max(line_pitch(font), font["size"] * (ASCENT + DESCENT) + (number(font.get("lineSpacing")) or 0.0))
        limit = limit if limit is not None else font.get("lineLimit")
        scale = font.get("minimumScaleFactor")
        if text == "":
            return (0.0, EMPTY_TEXT_HEIGHT)
        strings = []
        box.extra.pop("cut_lines", None)
        lines = text_lines(text, font, pw, strings)
        needed = len(lines)
        if limit and needed > int(limit):
            shown = int(limit)
            position = 0
            for line in strings[: shown - 1]:
                position = text.find(line, position) + len(line) if line and text.find(line, position) >= 0 else position
            rest = text[position:].lstrip()
            cut_width, cut_text = truncated_width(rest, font, pw if pw not in (None, math.inf) else lines[shown - 1])
            if linked(text):
                box.extra["pitched"] = True
                if shown > 1:
                    cut_width = max(cut_width, lines[shown - 1])
                    if pw not in (None, math.inf):
                        cut_width = min(cut_width, pw)
            lines = lines[: shown - 1] + [cut_width]
            box.extra["cut_lines"] = strings[: shown - 1] + [cut_text]
            strings = box.extra["cut_lines"]
        elif limit:
            lines = lines[: int(limit)]
            strings = strings[: int(limit)]
        box.extra["lines_text"] = strings
        if scale and isinstance(scale, (int, float)) and 0 < scale < 1 and pw not in (None, math.inf) and limit:
            factor = self.scale_to_fit(text, font, pw, int(limit), float(scale))
            if factor < 1:
                shrunk = {k: v for k, v in font.items() if k != "minimumScaleFactor"}
                shrunk["size"] = scaled_size(font["size"], factor)
                box.extra["scale"] = factor
                return self.text_size(box, text, shrunk, pw, limit)
        width = max(lines) if lines else 0.0
        if pw not in (None, math.inf):
            width = min(width, pw)
        height = font["size"] * (ASCENT + DESCENT) + pitch * (len(lines) - 1)
        if box.extra.pop("pitched", False):
            height = pitch * len(lines)
        box.lines = (len(lines), needed)
        return (third(width), third(height))

    def scale_to_fit(self, text, font, pw, limit, minimum):
        """UIFoundation's search for a text's scale factor (NSExtendedStringDrawing boundingRectWithSize:options:context:):
        a bisection between the minimum and 1, each step's font size floored to a quarter point, stopping once a fit
        is found and the bracket is under a hundredth, at most twenty steps; the minimum when nothing above it fits."""
        width = pw

        def oversized(factor):
            trial = {k: v for k, v in font.items() if k != "minimumScaleFactor"}
            trial["size"] = scaled_size(font["size"], factor)
            if limit == 1:
                return text_lines(text, trial, None)[0] > width
            return len(text_lines(text, trial, width)) > limit

        if not oversized(1.0):
            return 1.0
        if oversized(minimum):
            return minimum
        low, high = minimum, 1.0
        bracket = high - low
        found = False
        for _ in range(SCALE_STEPS):
            middle = high - bracket * 0.5
            fits = not oversized(middle)
            if fits:
                low = middle
            else:
                high = middle
            found = found or fits
            bracket = high - low
            if found and bracket < SCALE_PRECISION:
                break
        return low

    def intrinsic(self, box, pw, ph):
        kind = box.kind
        font = box.font
        node = box.node
        if kind == "Text":
            size = self.text_size(box, box.shaped or box.text, font, pw)
            if ph is not None and ph != math.inf and size[1] > ph + 1 / 3:
                pitch = max(line_pitch(font), font["size"] * (ASCENT + DESCENT) + (number(font.get("lineSpacing")) or 0.0))
                shown = max(1, int((ph + 1e-6) // pitch))
                if shown < (box.lines or (1, 1))[0]:
                    size = self.text_size(box, box.shaped or box.text, font, pw, limit=shown)
            return size
        if kind == "Label":
            style = font.get("labelStyle")
            icon = self.symbol_column(box.extra.get("symbol", ""), font)
            if style == "iconOnly":
                return icon
            tw, th = self.text_size(box, box.text, font, None if pw is None else max(0.0, pw - icon[0] - LABEL_GAP))
            if style == "titleOnly":
                return (tw, th)
            text_baseline = font["size"] * ASCENT
            icon_baseline = self.symbol_baseline(box.extra.get("symbol", ""), font, icon[1])
            shift = max(0.0, icon_baseline - text_baseline)
            icon_shift = max(0.0, text_baseline - icon_baseline)
            return (third(icon[0] + LABEL_GAP + tw), max(th + shift, icon[1] + icon_shift))
        if kind == "QRCode":
            framed = any(node.get(k) is not None for k in ("width", "height", "maxWidth", "maxHeight")) or isinstance(node.get("frame"), dict)
            if not framed:
                return (160.0, 160.0)
            side = min(v for v in (pw, ph, 10_000.0) if v not in (None, math.inf))
            return (side, side)
        if kind == "Image":
            if box.extra.get("bitmap"):
                w = pw if pw not in (None, math.inf) else 100.0
                return (w, w * 2 / 3)
            if box.extra.get("resizable"):
                return self.fitted(self.symbol_aspect(box.extra.get("symbol", ""), font), pw, ph)
            return self.symbol_size(box.extra.get("symbol", ""), font)
        if kind in ("Button", "Menu"):
            style = node.get("style")
            size = BUTTON_SIZES.get(font.get("controlSize") or "regular", "regular")
            if size == "small" and not box.children:
                font = dict(font, size=float(STYLES["subheadline"][0]), style="subheadline")
            label_style = font.get("labelStyle")
            if box.children:
                cw, chh = self.measure(box.children[0], pw, ph)
            elif box.extra.get("symbol") and label_style == "iconOnly":
                cw, chh = self.symbol_size(box.extra["symbol"], font)
            elif box.extra.get("symbol") and label_style != "titleOnly":
                icon = self.symbol_column(box.extra["symbol"], font)
                pad_w = {"small": 20, "large": 40}.get(size, 24) + 2
                tw, th = self.text_size(box, box.text, font, None if pw is None else max(0.0, pw - icon[0] - LABEL_GAP - pad_w))
                cw, chh = third(icon[0] + LABEL_GAP + tw), max(th, icon[1])
            else:
                pad_w = {"small": 20, "large": 40}.get(size, 24)
                padded = style in ("bordered", "borderedProminent", "glass", "prominent")
                cw, chh = self.text_size(box, box.text, font, None if pw is None else max(0.0, pw - (pad_w if padded else 0)))
            if style in ("bordered", "borderedProminent", "glass", "prominent"):
                pad = {"small": (10, 5), "large": (20, 15)}.get(size, (12, 7))
                w, h = cw + 2 * pad[0], chh + 2 * pad[1]
            else:
                w, h = cw, chh
            fills = (node.get("maxWidth") == "infinity") or (isinstance(node.get("frame"), dict) and node["frame"].get("maxWidth") == "infinity")
            if fills and pw not in (None, math.inf):
                w = pw
            return (w, h)
        if kind in FIXED and kind not in ("Divider",):
            if kind == "TextField" and text_of(resolve(node.get("style"), box.scope)) not in ("bordered", "roundedBorder"):
                return self.text_field_size(box, node, font, pw)
            if kind == "TextField" and number(resolve(node.get("lines"), box.scope)):
                full = pw if pw not in (None, math.inf) else 200.0
                return (full, self.text_field_size(box, dict(node, style="plain"), font, pw)[1] + 8.0)
            if kind == "TextField" and truthy(resolve(node.get("multiline"), box.scope)):
                full = pw if pw not in (None, math.inf) else 200.0
                typed = text_of(resolve(node.get("bind"), box.scope))
                if typed:
                    return (full, max(30.0, len(text_lines(typed, font, full - 14)) * line_pitch(font) + 8))
                return (full, 30.0)
            full = pw if pw not in (None, math.inf) else 200.0
            if kind == "TextField":
                return (full, max(float(FIXED[kind]), self.text_field_size(box, dict(node, style="plain"), font, pw)[1] + 8.0))
            if kind in CONTROL_WIDTHS and box.text:
                _, th = self.text_size(box, box.text, font, max(0.0, full - CONTROL_WIDTHS[kind]))
                return (full, max(float(FIXED[kind]), th))
            return (full, float(FIXED[kind]))
        if kind == "Divider":
            return (pw if pw not in (None, math.inf) else 0.0, 1 / 3)
        if kind == "Spacer":
            given = number(resolve(box.value, box.scope)) if not isinstance(box.value, dict) else None
            minimum = given if given is not None else box.extra.get("least", 0.0)
            axis = box.extra.get("axis")
            along_w = max(minimum, pw) if pw is not None else minimum
            along_h = max(minimum, ph) if ph is not None else minimum
            if axis == "h":
                return (along_w, 0.0)
            if axis == "v":
                return (0.0, along_h)
            return (along_w, along_h)
        if kind == "Picker":
            style = node.get("style")
            full = pw if pw not in (None, math.inf) else 200.0
            if style in ("segmented", "palette"):
                return (full, 31.0)
            if style in ("wheel", "inline"):
                return (full, 216.0)
            tw, th = self.text_size(box, box.text, font, None)
            chevron = self.symbol_size("chevron.up.chevron.down", dict(font, imageScale="small"))[0]
            return (third(tw + 28 + chevron), line_height(font) + 14)
        if kind == "DatePicker":
            style = node.get("style")
            full = pw if pw not in (None, math.inf) else 200.0
            if style == "graphical":
                return (full, GRAPHICAL_CALENDAR[TEXT_SIZE])
            if style == "wheel":
                return (full, 216.0)
            return (full, line_height(font) + 14 if node.get("components") == "date" else line_pitch(font) + 14)
        if kind == "Gauge":
            style = node.get("style")
            full = pw if pw not in (None, math.inf) else 200.0
            if style in ("circular", "capacity"):
                return (58.0, 58.0)
            if style == "bar":
                return (full, 4.0)
            label, current, bounds = GAUGE_ROWS[TEXT_SIZE]
            h = scaled(16)
            if box.extra.get("label") is not None:
                h += label
            if box.extra.get("bounds"):
                h += bounds
            elif box.extra.get("current") is not None:
                h += current
            return (full, h)
        if kind == "ProgressView":
            full = pw if pw not in (None, math.inf) else 200.0
            if not box.extra.get("determinate"):
                return (scaled(20), scaled(20))
            h = 4.0
            if box.extra.get("label") is not None:
                h += line_height(font) + 4
            return (full, h)
        if kind == "Link":
            return self.text_size(box, box.text, font, pw)
        if kind == "Face":
            size = float(box.extra.get("size") or 56)
            return (size, size)
        if kind == "Said":
            return (pw if pw not in (None, math.inf) else 200.0, 44.0)
        if kind == "TextEditor":
            full = pw if pw not in (None, math.inf) else 200.0
            wanted = number(resolve(node.get("height"), box.scope))
            typed = text_of(resolve(node.get("bind"), box.scope))
            grown = max(200.0, len(text_lines(typed, font, full - 14)) * line_pitch(font) + 16) if typed else 200.0
            return (full, float(wanted) if wanted else grown)
        if kind == "File":
            full = pw if pw not in (None, math.inf) else 200.0
            wanted = box.extra.get("height")
            if wanted:
                return (full, float(wanted))
            if box.text:
                return (full, max(44.0, min(4000.0, len(text_lines(box.text, font, full)) * line_pitch(font))))
            return (full, 300.0)
        if kind in ("Circle", "Capsule", "Rectangle", "Ellipse", "RoundedRectangle", "Path", "Color", "Gradient"):
            w = pw if pw is not None else 10.0
            h = ph if ph is not None else 10.0
            if kind == "Circle" and ph is None and pw not in (None, math.inf):
                h = w
            return (w, h)
        if kind in ("VStack", "Card", "Section", "GlassGroup", "HStack", "ZStack", "Group", "DisclosureGroup", "Columns", "Grid", "ScrollView", "Carousel", "Pages"):
            return self.container(box, pw, ph)
        if kind in self.components:
            if box.children and box.children[0] is not None:
                return self.measure(box.children[0], pw, ph)
            return (0.0, 0.0)
        raise UnknownView(f"{kind} at {box.path} is not a view the twin knows, nor a component of this card")

    def container(self, box, pw, ph):
        kind = box.kind
        node = box.node
        kids = [k for k in box.children if k is not None]
        if kind == "Card":
            inner_pw = None if pw is None else max(0.0, pw - 32)
            w, h = self.stack(box, kids, inner_pw, None, "v", self.spacing(box, 12.0))
            return (pw if pw not in (None, math.inf) else w + 32, h + 32)
        if kind == "Section":
            w, h = self.stack(box, kids, pw, None, "v", 10.0)
            return (pw if pw not in (None, math.inf) else w, h)
        if kind == "DisclosureGroup":
            row = line_height(box.font) + 8
            if not box.extra.get("expanded"):
                return (pw if pw not in (None, math.inf) else 200.0, row)
            w, h = self.stack(box, kids, pw, None, "v", 10.0)
            box.extra["content_size"] = (w, h)
            return (pw if pw not in (None, math.inf) else w, row + 8 + h)
        if kind == "VStack":
            return self.stack(box, kids, pw, ph, "v", None)
        if kind == "HStack":
            return self.stack(box, kids, pw, ph, "h", None)
        if kind == "GlassGroup":
            return self.stack(box, kids, pw, ph, "h", self.spacing(box, 12.0))
        if kind == "Group":
            return self.stack(box, kids, pw, ph, "v", None)
        if kind == "ZStack":
            w = h = 0.0
            for kid in kids:
                kw, kh = self.measure(kid, pw, ph)
                w, h = max(w, kw), max(h, kh)
            return (w, h)
        if kind == "Columns":
            spacing = self.spacing(box, 12.0)
            full = pw if pw not in (None, math.inf) else 300.0
            min_width = resolve(node.get("minWidth"), box.scope) if node.get("minWidth") is not None else None
            if isinstance(min_width, (int, float)) and min_width > 0:
                count = max(1, int((full + spacing) // (min_width + spacing)))
            else:
                count = max(1, int(number(resolve(node.get("count"), box.scope)) or 2))
            column = (full - spacing * (count - 1)) / count
            rows = [kids[i:i + count] for i in range(0, len(kids), count)]
            heights = [max((self.measure(kid, column, None)[1] for kid in row), default=0.0) for row in rows]
            box.extra["columns"] = (count, column, heights)
            return (full, math.ceil(sum(heights) + spacing * max(0, len(rows) - 1) - 1e-6))
        if kind == "Grid":
            return self.grid(box, pw, ph)
        if kind == "ScrollView":
            spacing = self.spacing(box, 12.0)
            if node.get("axis") == "horizontal":
                w, h = self.stack(box, kids, None, ph, "h", spacing)
                return (pw if pw not in (None, math.inf) else w, h)
            w, h = self.stack(box, kids, pw, None, "v", spacing)
            return (w, h if ph in (None, math.inf) else min(h, ph))
        if kind == "Carousel":
            fraction = number(resolve(node.get("pageWidth"), box.scope)) or 0.85
            full = pw if pw not in (None, math.inf) else 300.0
            h = self.measure(kids[0], full * fraction, None)[1] if kids else 0.0
            return (full, h)
        if kind == "Pages":
            full = pw if pw not in (None, math.inf) else 300.0
            return (full, 220.0)
        return (0.0, 0.0)

    def stack(self, box, kids, pw, ph, axis, spacing):
        """SwiftUI's stack: children sized least flexible first, each offered an equal share of what is left."""
        for kid in kids:
            if kid.kind == "Spacer":
                kid.extra["axis"] = axis
                kid.extra["least"] = spacing if spacing is not None else 8.0
        explicit = isinstance(box.node, dict) and "spacing" in box.node
        given = self.spacing(box) if explicit else None
        gaps = [given if explicit else spacing if spacing is not None else self.gap(box, a, b, axis) for a, b in zip(kids, kids[1:])]
        box.extra["gaps"] = gaps
        total_gap = sum(gaps)
        main = pw if axis == "h" else ph
        cross = ph if axis == "h" else pw
        sizes = [None] * len(kids)
        if main is None or main == math.inf or not kids:
            for index, kid in enumerate(kids):
                sizes[index] = self.measure(kid, (None, cross) if axis == "h" else (cross, None))[0] if False else self.measure(kid, *((None, cross) if axis == "h" else (cross, None)))
        else:
            order = []
            minimums = {}
            for index, kid in enumerate(kids):
                low = self.measure(kid, *((0.0, cross) if axis == "h" else (cross, 0.0)))
                high = self.measure(kid, *((math.inf, cross) if axis == "h" else (cross, math.inf)))
                fixed = fixed_axes(resolve(kid.node.get("fixedSize"), kid.scope))[0] if isinstance(kid.node, dict) else False
                lo = 0.0 if axis == "h" and kid.kind == "Text" and not fixed else low[0] if axis == "h" else min(low[1], line_pitch(kid.font)) if kid.kind == "Text" else low[1]
                hi = high[0] if axis == "h" else high[1]
                minimums[index] = lo
                priority = number(resolve(kid.node.get("layoutPriority"), kid.scope)) or 0.0 if isinstance(kid.node, dict) else 0.0
                if kid.kind == "Spacer":
                    priority = -math.inf
                flexibility = hi - lo
                order.append((-priority, flexibility, -lo if flexibility == math.inf else 0.0, index))
            order.sort()
            groups = {}
            for key in order:
                groups.setdefault(key[0], []).append(key[3])
            tiers = [group for _, group in sorted(groups.items())]
            remaining = main - total_gap - sum(minimums[index] for group in tiers[1:] for index in group)
            for tier, group in enumerate(tiers):
                if tier:
                    remaining += sum(minimums[index] for index in group)
                left = len(group)
                for index in group:
                    share = max(0.0, remaining / left)
                    if kids[index].kind == "Spacer":
                        along = max(share, minimums[index])
                        sizes[index] = (along, 0.0) if axis == "h" else (0.0, along)
                        kids[index].memo[(along, cross) if axis == "h" else (cross, along)] = sizes[index]
                    else:
                        sizes[index] = self.measure(kids[index], *((share, cross) if axis == "h" else (cross, share)))
                    remaining -= sizes[index][0] if axis == "h" else sizes[index][1]
                    left -= 1
        box.extra["sizes"] = sizes
        if axis == "h":
            alignment = resolve(box.node.get("alignment"), box.scope) if isinstance(box.node, dict) else None
            if alignment in ("firstTextBaseline", "lastTextBaseline"):
                baselines = [self.baseline(kid, size, alignment == "lastTextBaseline") for kid, size in zip(kids, sizes)]
                top = max((b for b in baselines if b is not None), default=0.0)
                height = max((s[1] + (top - b if b is not None else 0.0) for s, b in zip(sizes, baselines)), default=0.0)
                return (sum(s[0] for s in sizes) + total_gap, height)
            return (sum(s[0] for s in sizes) + total_gap, max((s[1] for s in sizes), default=0.0))
        return (max((s[0] for s in sizes), default=0.0), sum(s[1] for s in sizes) + total_gap)

    def grid(self, box, pw, ph):
        node = box.node
        rows = box.extra["rows"]
        h_spacing = number(resolve(node.get("hSpacing"), box.scope)) if node.get("hSpacing") is not None else 8.0
        v_spacing = number(resolve(node.get("vSpacing"), box.scope)) if node.get("vSpacing") is not None else third(text_metrics(box.font)[2])
        columns = max((len(cells) for kind, cells in rows if kind == "row"), default=1)
        widths = [0.0] * columns
        lows = [0.0] * columns
        for kind, cells in rows:
            if kind != "row":
                continue
            for index, cell in enumerate(cells):
                widths[index] = max(widths[index], self.measure(cell, None, None)[0])
                lows[index] = max(lows[index], self.measure(cell, 0.0, None)[0])
        full = pw if pw not in (None, math.inf) else None
        total = sum(widths) + h_spacing * (columns - 1)
        if full is not None and total > full:
            remaining = full - h_spacing * (columns - 1)
            order = sorted(range(columns), key=lambda i: widths[i] - lows[i])
            left = columns
            for index in order:
                share = max(0.0, remaining / left)
                width = 0.0
                for kind, cells in rows:
                    if kind == "row" and index < len(cells):
                        width = max(width, self.measure(cells[index], share, None)[0])
                widths[index] = width
                remaining -= width
                left -= 1
            total = sum(widths) + h_spacing * (columns - 1)
        spans = [self.measure(cells[0], full, None)[0] for kind, cells in rows if kind != "row"]
        if spans and max(spans) > total:
            extra = (max(spans) - total) / columns
            widths = [w + extra for w in widths]
            total = max(spans)
        heights = []
        for kind, cells in rows:
            if kind == "row":
                heights.append(max((self.measure(cell, widths[i], None)[1] for i, cell in enumerate(cells)), default=0.0))
            else:
                heights.append(self.measure(cells[0], total, None)[1])
        box.extra["grid"] = (widths, heights, h_spacing, v_spacing)
        return (total, sum(heights) + v_spacing * max(0, len(rows) - 1))

    # MARK: placing

    def align_x(self, name, outer_w, inner_w):
        if name in ("leading", "topLeading", "bottomLeading"):
            return 0.0
        if name in ("trailing", "topTrailing", "bottomTrailing"):
            return outer_w - inner_w
        return (outer_w - inner_w) / 2

    def align_y(self, name, outer_h, inner_h):
        if name in ("top", "topLeading", "topTrailing"):
            return 0.0
        if name in ("bottom", "bottomLeading", "bottomTrailing"):
            return outer_h - inner_h
        return (outer_h - inner_h) / 2

    def place(self, box, x, y, pw, ph):
        if box is None:
            return
        w, h = self.measure(box, pw, ph)
        box.frame = (x, y, w, h)
        if box.probed:
            rx, ry, rw, rh = x, y, w, h
            if isinstance(box.node, dict) and box.node.get("_pushed"):
                top, leading, bottom, trailing = box.extra.get("padding", (0.0,) * 4)
                rx, ry, rw, rh = x + leading, y + top, w - leading - trailing, h - top - bottom
            self.frames.append({"path": box.path, "view": box.kind, "x": rx, "y": ry, "w": rw, "h": rh, **({"text": box.text} if box.kind == "Text" else {})})
        if isinstance(box.node, dict) and box.node.get("offset") is not None:
            shift = resolve(box.node["offset"], box.scope)
            if isinstance(shift, dict):
                x += number(shift.get("x")) or 0.0
                y += number(shift.get("y")) or 0.0
        if box.kind == "Text" and box.probed:
            self.texts.append(box)
        if box.kind == "Image" and box.probed and box.extra.get("symbol"):
            self.images.append({"path": box.path, "symbol": box.extra["symbol"], "size": box.font["size"] * IMAGE_SCALE.get(box.font.get("imageScale") or "medium", 1.0)})
        margin = box.extra.get("margin", (0.0,) * 4)
        padding = box.extra.get("padding", (0.0,) * 4)
        cw, chh = box.extra.get("content", (w, h))
        frame = self.mods(box)
        inner_w = w - margin[1] - margin[3]
        inner_h = h - margin[0] - margin[2]
        content_w = cw
        content_h = chh
        alignment = frame.get("alignment") or ("topLeading" if box.kind in ("ScrollView", "Carousel", "Pages") else "center")
        fw, fh = box.extra.get("framed", (inner_w - padding[1] - padding[3], inner_h - padding[0] - padding[2]))
        ox = x + margin[1] + padding[1] + self.align_x(alignment, fw, content_w)
        oy = y + margin[0] + padding[0] + self.align_y(alignment, fh, content_h)
        self.place_content(box, ox, oy, content_w, content_h)
        for key in ("overlay", "background"):
            layer = box.extra.get(key)
            if layer is not None:
                lw, lh = self.measure(layer, inner_w, inner_h)
                name = box.node.get("overlayAlignment") or "center"
                self.place(layer, x + margin[1] + self.align_x(name, inner_w, lw), y + margin[0] + self.align_y(name, inner_h, lh), inner_w, inner_h)

    def place_content(self, box, x, y, w, h):
        kind = box.kind
        node = box.node
        kids = [k for k in box.children if k is not None]
        if kind in self.components:
            if kids:
                self.place(kids[0], x, y, w, h)
            return
        if kind in ("Button", "Menu") and kids:
            kw, kh = self.measure(kids[0], w, h)
            self.place(kids[0], x + (w - kw) / 2, y + (h - kh) / 2, w, h)
            return
        if kind == "Card":
            self.place_stack(box, kids, x + 16, y + 16, w - 32, h - 32, "v", "leading", "center")
            return
        if kind == "Section":
            self.place_stack(box, kids, x, y, w, h, "v", "leading", "center")
            return
        if kind == "DisclosureGroup":
            if box.extra.get("expanded") and kids:
                cw, chh = box.extra.get("content_size", (w, h))
                self.place_stack(box, kids, x + (w - cw) / 2, y + line_height(box.font) + 16, cw, chh, "v", "leading", "center")
            return
        if kind in ("VStack", "Group"):
            self.place_stack(box, kids, x, y, w, h, "v", resolve(node.get("alignment"), box.scope) or ("center" if kind == "Group" else "leading"), "center")
            return
        if kind in ("HStack", "GlassGroup"):
            self.place_stack(box, kids, x, y, w, h, "h", "leading", resolve(node.get("alignment"), box.scope) or "center")
            return
        if kind == "ZStack":
            name = resolve(node.get("alignment"), box.scope) or "center"
            for kid in kids:
                kw, kh = self.measure(kid, w, h)
                self.place(kid, x + self.align_x(name, w, kw), y + self.align_y(name, h, kh), w, h)
            return
        if kind == "Columns":
            count, column, heights = box.extra.get("columns", (2, w, []))
            spacing = self.spacing(box, 12.0)
            cy = y
            for row_index, row in enumerate([kids[i:i + count] for i in range(0, len(kids), count)]):
                for col, kid in enumerate(row):
                    self.place(kid, x + col * (column + spacing), cy, column, None)
                cy += heights[row_index] + spacing if row_index < len(heights) else 0
            return
        if kind == "Grid":
            widths, heights, hs, vs = box.extra.get("grid", ([], [], 8.0, 2.0))
            cy = y
            for row_index, (row_kind, cells) in enumerate(box.extra["rows"]):
                if row_kind == "row":
                    cx = x
                    for col, cell in enumerate(cells):
                        cw, chh = self.measure(cell, widths[col], None)
                        self.place(cell, cx, cy + (heights[row_index] - chh) / 2, widths[col], None)
                        cx += widths[col] + hs
                else:
                    self.place(cells[0], x, cy, w, None)
                cy += heights[row_index] + vs
            return
        if kind == "ScrollView":
            if node.get("axis") == "horizontal":
                self.place_stack(box, kids, x, y, w, h, "h", "leading", "top")
            else:
                self.place_stack(box, kids, x, y, w, h, "v", "leading", "center")
            return
        if kind == "Carousel":
            fraction = number(resolve(node.get("pageWidth"), box.scope)) or 0.85
            spacing = self.spacing(box, 12.0)
            cx = x
            for index, kid in enumerate(kids):
                page = w * fraction
                kw = self.measure(kid, page, None if index == 0 else h)[0]
                self.place(kid, cx + max(0.0, (page - kw) / 2), y, page, None if index == 0 else h)
                cx += page + spacing
            return
        if kind == "Pages":
            for kid in kids:
                self.place(kid, x, y, w, h)
            return

    def place_stack(self, box, kids, x, y, w, h, axis, h_align, v_align):
        sizes = box.extra.get("sizes")
        gaps = box.extra.get("gaps", [])
        if sizes is None or len(sizes) != len(kids):
            return
        if axis == "v":
            cy = y
            for index, (kid, size) in enumerate(zip(kids, sizes)):
                if size is None:
                    continue
                self.place(kid, x + self.align_x(h_align, w, size[0]), cy, *self.proposal_for(kid, size))
                cy += size[1] + (gaps[index] if index < len(gaps) else 0)
        else:
            cx = x
            baselines = None
            if v_align in ("firstTextBaseline", "lastTextBaseline"):
                baselines = [self.baseline(kid, size, v_align == "lastTextBaseline") for kid, size in zip(kids, sizes)]
                top = max((b for b in baselines if b is not None), default=0.0)
            for index, (kid, size) in enumerate(zip(kids, sizes)):
                if size is None:
                    continue
                if baselines is not None and baselines[index] is not None:
                    dy = top - baselines[index]
                else:
                    dy = self.align_y(v_align, h, size[1])
                self.place(kid, cx, y + dy, *self.proposal_for(kid, size))
                cx += size[0] + (gaps[index] if index < len(gaps) else 0)

    def baseline(self, box, size, last):
        top = box.extra.get("padding", (0.0,) * 4)[0]
        if box.kind in ("Text", "Label", "Link", "Button", "Menu") and size is not None:
            factor = box.extra.get("scales", {}).get(self.proposal_for(box, size), 1.0)
            single = line_height(box.font) * factor
            text_baseline = box.font["size"] * factor * ASCENT
            if box.kind == "Text" and not (box.shaped or box.text):
                single, text_baseline = EMPTY_TEXT_HEIGHT, EMPTY_TEXT_ASCENT
            if box.kind == "Label" and box.extra.get("symbol") and box.font.get("labelStyle") != "titleOnly":
                icon = self.symbol_size(box.extra["symbol"], box.font)
                text_baseline = max(text_baseline, self.symbol_baseline(box.extra["symbol"], box.font, icon[1]))
            if last:
                return size[1] - box.extra.get("padding", (0.0,) * 4)[2] - single + text_baseline
            return top + text_baseline
        if box.kind == "Image" and size is not None:
            return top + self.symbol_baseline(box.extra.get("symbol", ""), box.font, size[1] - top - box.extra.get("padding", (0.0,) * 4)[2])
        return None

    def proposal_for(self, kid, size):
        for key, value in kid.memo.items():
            if value == size:
                return key
        return size

    def run(self):
        root = self.build()
        self.root = root
        if root is None:
            return {"size": [self.width, 0], "frames": [], "texts": []}
        w, h = self.measure(root, self.width, None)
        self.place(root, 0.0, 0.0, self.width, None)
        texts = []
        for box in self.texts:
            shown, needed = box.lines or (1, 1)
            texts.append({"path": box.path, "text": box.text, "lines": shown, "needed": needed, "cut": needed > shown})
        return {"size": [self.width, h], "frames": self.frames, "texts": texts, "images": self.images}


def layout(card, components=None, width=WIDTH, derived=None, at=None, text_size="large"):
    global CLOCK
    CLOCK = parse_date(at) if at else None
    set_text_size(text_size)
    return Engine(card, components, width, derived).run()


if __name__ == "__main__":
    source = json.load(open(sys.argv[1]))
    components = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
    result = layout(source, components)
    print("size", result["size"])
    for f in result["frames"]:
        print(f"{f['path'][:70]:70} {f['view']:10} x={f['x']:6.1f} y={f['y']:6.1f} w={f['w']:6.1f} h={f['h']:6.1f}")
