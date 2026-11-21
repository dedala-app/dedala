# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Draws a card from the twin's frames as an HTML page: every node at the position the engine computed.

    python -m dedala.twin.paint card.json [components.json] [report.json] > card.html   (the report lends its derived values)
"""

import base64
import html
import json
import math
import os
import re
import sys

from . import glyphs, layout
from .layout import WEIGHTS, line_pitch, resolve, text_of, tracking, truthy

COLORS = {"accent": (0, 122, 255), "primary": (0, 0, 0), "secondary": (60, 60, 67, 0.6), "tertiary": (60, 60, 67, 0.3), "quaternary": (60, 60, 67, 0.18),
          "background": (255, 255, 255), "card": (255, 255, 255), "groupedBackground": (242, 242, 247), "fill": (120, 120, 128, 0.2),
          "secondaryFill": (120, 120, 128, 0.16), "separator": (60, 60, 67, 0.29), "red": (255, 59, 48), "orange": (255, 149, 0), "yellow": (255, 204, 0),
          "green": (52, 199, 89), "mint": (0, 199, 190), "teal": (48, 176, 199), "cyan": (50, 173, 230), "blue": (0, 122, 255), "indigo": (88, 86, 214),
          "purple": (175, 82, 222), "pink": (255, 45, 85), "brown": (162, 132, 94), "gray": (142, 142, 147), "grey": (142, 142, 147), "white": (255, 255, 255),
          "black": (0, 0, 0), "clear": (0, 0, 0, 0)}
GLYPHS = {"airplane": "✈", "star.fill": "★", "star": "☆", "phone.fill": "✆", "phone": "✆", "car.fill": "⛟", "wallet.pass.fill": "▤", "chevron.right": "›",
          "chevron.left": "‹", "chevron.down": "⌄", "checkmark.circle.fill": "✓", "checkmark": "✓", "xmark": "✕", "calendar": "▦", "clock": "◷", "envelope": "✉",
          "envelope.fill": "✉", "lightbulb.fill": "💡", "lightbulb.max.fill": "💡", "lightbulb": "💡", "moon.stars": "☾", "moon.stars.fill": "☾", "sun.max.fill": "☀", "power": "⏻",
          "mappin": "⌖", "location.fill": "➤", "bell.fill": "🔔", "doc.text": "▯", "doc.richtext.fill": "▮", "arrow.right": "→", "arrow.left": "←",
          "plus": "+", "minus": "−", "figure.walk": "🚶", "tram.fill": "🚋", "fork.knife": "🍴", "bed.double.fill": "🛏", "sunrise": "🌅", "faceid": "▣",
          "wrench.and.screwdriver.fill": "🔧", "music.note": "♪", "sportscourt": "▭", "trash": "🗑", "square.and.pencil": "✎", "person.fill": "●",
          "person.crop.circle.fill": "◉", "exclamationmark.triangle.fill": "⚠", "questionmark.circle": "?", "video": "▶", "video.fill": "▶"}


RICH = [(re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"), (re.compile(r"__(.+?)__"), r"<b>\1</b>"), (re.compile(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)"), r"<i>\1</i>"),
        (re.compile(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"), r"<i>\1</i>"), (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"), (re.compile(r"`([^`]*)`"), r"<code>\1</code>")]


LINKISH = re.compile(r"(?<![\w@/])((?:https?://|www\.)[^\s<]+|[\w.+-]+@[\w-]+\.[\w.-]+)")


def rich(text):
    """Inline Markdown the way the phone draws it: bold, italic, code; links and addresses in the accent colour."""
    out = html.escape(text or "")
    for pattern, replacement in RICH:
        out = pattern.sub(replacement, out)
    return LINKISH.sub(r'<span style="color:rgb(0,122,255)">\1</span>', out)


def css_color(value, default="rgb(0,0,0)"):
    if isinstance(value, dict) and value.get("gradient"):
        value = value["gradient"][0] if value["gradient"] else None
    if not isinstance(value, str):
        return default
    if value.startswith("#"):
        return value
    name, _, alpha = value.partition("@")
    base = COLORS.get(name)
    if base is None:
        return default
    r, g, b = base[:3]
    a = float(alpha) if alpha else (base[3] if len(base) > 3 else 1.0)
    return f"rgba({r},{g},{b},{a})"


def gradient(spec):
    colors = [css_color(c) for c in (spec.get("gradient") or [])] or ["rgb(0,122,255)"]
    direction = {"down": "to bottom", "up": "to top", "right": "to right", "left": "to left", "diagonal": "to bottom right"}.get(spec.get("direction") or "down", "to bottom")
    if spec.get("kind") == "radial":
        return f"radial-gradient(circle, {', '.join(colors)})"
    return f"linear-gradient({direction}, {', '.join(colors)})"


class Painter:
    def __init__(self, engine):
        self.engine = engine
        self.parts = []
        self.clip = None
        self.offset = (0.0, 0.0)
        self.cards = 0

    def style(self, box, color):
        node = box.node if isinstance(box.node, dict) else {}
        scope = box.scope
        rules = []
        background = node.get("background")
        if isinstance(background, dict) and "gradient" in background:
            rules.append(f"background:{gradient(resolve(background, scope))}")
        elif isinstance(background, str) and not layout.is_view(background):
            rules.append(f"background:{css_color(resolve(background, scope), 'transparent')}")
        if truthy(node.get("glassEffect")):
            rules.append("background:rgba(120,120,128,0.12)")
        shape = node.get("clipShape") or node.get("cornerRadius")
        if shape is not None:
            shape = resolve(shape, scope)
            if shape == "capsule":
                rules.append("border-radius:999px")
            elif shape == "circle":
                rules.append("border-radius:50%")
            elif isinstance(shape, (int, float)):
                rules.append(f"border-radius:{shape}px")
            rules.append("overflow:hidden")
        if node.get("border") is not None:
            border = resolve(node["border"], scope)
            width = border.get("width", 1) if isinstance(border, dict) else 1
            rules.append(f"box-shadow:inset 0 0 0 {width}px {css_color(border.get('color') if isinstance(border, dict) else border)}")
        if node.get("shadow") is not None and truthy(resolve(node["shadow"], scope)):
            rules.append("box-shadow:0 4px 12px rgba(0,0,0,0.08)")
        if node.get("opacity") is not None:
            rules.append(f"opacity:{resolve(node['opacity'], scope)}")
        if node.get("blur") is not None:
            rules.append(f"filter:blur({resolve(node['blur'], scope)}px)")
        return rules

    def color_of(self, box, inherited):
        node = box.node if isinstance(box.node, dict) else {}
        for key in ("foregroundStyle", "color"):
            if key in node:
                value = resolve(node[key], box.scope)
                if isinstance(value, str) and (value.startswith("#") or value.partition("@")[0] in COLORS):
                    return value
        return inherited

    def div(self, box, rules, inner="", inset=None):
        x, y, w, h = box.frame
        margin = box.extra.get("margin", (0.0,) * 4)
        if inset is not None:
            margin = tuple(a + b for a, b in zip(margin, inset))
        left, top, width, height = x + margin[1], y + margin[0], w - margin[1] - margin[3], h - margin[0] - margin[2]
        if self.clip is not None:
            cx, cy, cw, ch = self.clip
            if left >= cx + cw or top >= cy + ch or left + width <= cx or top + height <= cy:
                return
            insets = (max(0.0, cy - top), max(0.0, left + width - (cx + cw)), max(0.0, top + height - (cy + ch)), max(0.0, cx - left))
            if any(insets):
                rules = rules + [f"clip-path:inset({insets[0]:.1f}px {insets[1]:.1f}px {insets[2]:.1f}px {insets[3]:.1f}px)"]
        base = [f"left:{left - self.offset[0]:.2f}px", f"top:{top - self.offset[1]:.2f}px", f"width:{width:.2f}px", f"height:{height:.2f}px"]
        self.parts.append(f'<div class="n" style="{";".join(base + rules)}">{inner}</div>')

    def font_rules(self, font, scale=1.0):
        size = font["size"] * scale
        family = {"rounded": "SFR", "monospaced": "SFM"}.get(font["design"], "SF")
        rules = [f"font:{'italic ' if font.get('italic') else ''}{WEIGHTS.get(font['weight'], 400)} {size:.2f}px/{max(line_pitch(font), layout.line_height(font) + (layout.number(font.get('lineSpacing')) or 0.0)) * scale:.2f}px {family}",
                 f"letter-spacing:{tracking(size):.2f}px"]
        if font.get("textCase") == "uppercase":
            rules.append("text-transform:uppercase")
        return rules

    def glyph(self, name, size, color, weight="regular"):
        file = glyphs.path(name, weight) or glyphs.path(name + ".fill", weight) or glyphs.path(name.replace(".fill", ""), weight)
        if file:
            dims = glyphs.size(name, weight) or (17.0, 17.0)
            w, h = dims[0] * size / 17, dims[1] * size / 17
            data = base64.b64encode(open(file, "rb").read()).decode()
            mask = f"url(data:image/png;base64,{data}) center/contain no-repeat"
            return f'<span style="display:inline-block;width:{w:.1f}px;height:{h:.1f}px;background:{css_color(color)};-webkit-mask:{mask};mask:{mask}"></span>'
        text = GLYPHS.get(name) or GLYPHS.get(name.replace(".fill", ""))
        if text:
            return f'<span style="font-size:{size * 0.95:.1f}px;line-height:1;color:{css_color(color)}">{text}</span>'
        return f'<span style="display:inline-block;width:{size * 0.8:.0f}px;height:{size * 0.8:.0f}px;border:1.5px solid {css_color(color)};border-radius:{size * 0.2:.0f}px;opacity:0.6"></span>'

    def paint(self, box, inherited="primary"):
        if box is None or box.frame is None:
            return
        node = box.node if isinstance(box.node, dict) else {}
        kind = box.kind
        color = self.color_of(box, inherited)
        rules = self.style(box, color)
        padding = box.extra.get("padding", (0.0,) * 4)
        if box.extra.get("background") is not None:
            self.paint(box.extra["background"], color)
        shape = node.get("clipShape") if node.get("clipShape") is not None else node.get("cornerRadius")
        if shape is not None and (box.children or box.extra.get("overlay") is not None) and kind not in ("Button",):
            shape = resolve(shape, box.scope)
            radius = "999px" if shape == "capsule" else "50%" if shape == "circle" else f"{shape}px" if isinstance(shape, (int, float)) else "0"
            x, y, w, h = box.frame
            margin = box.extra.get("margin", (0.0,) * 4)
            self.parts.append(f'<div class="n" style="left:{x + margin[1] - self.offset[0]:.2f}px;top:{y + margin[0] - self.offset[1]:.2f}px;width:{w - margin[1] - margin[3]:.2f}px;height:{h - margin[0] - margin[2]:.2f}px;overflow:hidden;border-radius:{radius}">')
            outer_offset = self.offset
            self.offset = (x + margin[1], y + margin[0])
            rules = [rule for rule in rules if not rule.startswith("border-radius") and rule != "overflow:hidden"]
            self.paint_body(box, kind, node, color, rules, padding)
            self.offset = outer_offset
            self.parts.append("</div>")
            return
        self.paint_body(box, kind, node, color, rules, padding)

    def paint_body(self, box, kind, node, color, rules, padding):
        if kind == "Card":
            rules += [f"background:{'rgb(255,255,255)' if self.cards else 'rgb(242,242,247)'}", "border-radius:22px"]
            self.div(box, rules)
        elif kind == "Text" or kind == "Link":
            scale = box.extra.get("scales", {}).get(self.engine.proposal_for(box, box.frame[2:]), 1.0) if box.memo else 1.0
            shown, needed = box.lines or (1, 1)
            text_rules = self.font_rules(box.font, scale) + [f"color:{css_color(color if kind == 'Text' else 'accent')}", "white-space:nowrap" if shown == 1 else "white-space:pre-wrap", "overflow:visible",
                                                              f"padding:{padding[0]}px {padding[3]}px {padding[2]}px {padding[1]}px", "box-sizing:border-box"]
            align = node.get("multilineTextAlignment")
            if align in ("center", "trailing"):
                text_rules.append(f"text-align:{'center' if align == 'center' else 'right'}")
            frame = self.engine.mods(box)
            if scale < 1:
                floor = layout.number(box.font.get("minimumScaleFactor")) or 0.0
                text_rules += ["display:block", "white-space:nowrap", *(["overflow:hidden", "text-overflow:ellipsis"] if scale <= floor + 1e-6 else ["overflow:visible"])]
            elif box.extra.get("lines_text") and (needed > shown or shown > 1):
                text_rules += ["white-space:pre"]
                if any(key in frame for key in ("width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight")):
                    name = frame.get("alignment") or "center"
                    text_rules += ["display:flex", f"align-items:{'flex-start' if name.startswith('top') else 'flex-end' if name.startswith('bottom') else 'center'}",
                                   f"justify-content:{'flex-start' if name.endswith('eading') else 'flex-end' if name.endswith('railing') else 'center'}"]
                self.div(box, rules + text_rules, "<span>" + "\n".join(rich(line) for line in box.extra["lines_text"]) + "</span>")
                return
            elif any(key in frame for key in ("width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight")) and needed <= shown:
                name = frame.get("alignment") or "center"
                text_rules += ["display:flex", f"align-items:{'flex-start' if name.startswith('top') else 'flex-end' if name.startswith('bottom') else 'center'}",
                               f"justify-content:{'flex-start' if name.endswith('eading') else 'flex-end' if name.endswith('railing') else 'center'}"]
            elif needed > shown and shown == 1:
                text_rules += ["display:block", "text-overflow:ellipsis"]
            elif needed > shown:
                text_rules += ["display:-webkit-box", f"-webkit-line-clamp:{shown}", "-webkit-box-orient:vertical", "text-overflow:ellipsis"]
            self.div(box, rules + text_rules, rich(box.text))
        elif kind == "Image":
            size = box.font["size"] * layout.IMAGE_SCALE.get(box.font.get("imageScale") or "medium", 1.0)
            if box.extra.get("bitmap"):
                url = resolve(box.value.get("url"), box.scope) if isinstance(box.value, dict) and box.value.get("url") else None
                fit = "cover" if node.get("contentMode") == "fill" else "contain"
                inner = f'<img src="{html.escape(str(url), quote=True)}" style="width:100%;height:100%;object-fit:{fit};display:block">' if url else ""
                self.div(box, rules + ["background:rgba(120,120,128,0.12)", "overflow:hidden"], inner)
            else:
                self.div(box, rules + ["display:flex", "align-items:center", "justify-content:center"], self.glyph(box.extra.get("symbol", ""), size, color, box.font["weight"]))
        elif kind == "Label":
            icon = self.engine.symbol_column(box.extra.get("symbol", ""), box.font)
            title = "\n".join(rich(line) for line in box.extra["lines_text"]) if box.extra.get("lines_text") else rich(box.text)
            inner = (f'<span style="display:inline-flex;width:{icon[0]:.0f}px;justify-content:center;margin-right:{layout.LABEL_GAP:.0f}px">'
                     f'{self.glyph(box.extra.get("symbol", ""), box.font["size"], color, box.font["weight"])}</span><span style="white-space:pre">{title}</span>')
            self.div(box, rules + self.font_rules(box.font) + [f"color:{css_color(color)}", "display:flex", "align-items:center", f"padding:{padding[0]}px {padding[3]}px {padding[2]}px {padding[1]}px"], inner)
        elif kind == "Button":
            style = node.get("style")
            filled = style in ("prominent", "borderedProminent")
            tint = resolve(node.get("tint"), box.scope) if node.get("tint") is not None else "accent"
            if filled:
                rules += [f"background:{css_color(tint)}", "border-radius:999px"]
                label_color = "white"
            elif style in ("glass", "bordered"):
                tinted = node.get("tint") is not None and style == "bordered"
                rules += [f"background:{css_color(tint + '@0.15') if tinted and isinstance(tint, str) and '@' not in tint else 'rgba(120,120,128,0.12)'}", "border-radius:999px"]
                label_color = color if color != "primary" else ("primary" if style == "glass" else tint)
            else:
                label_color = color if color != "primary" else tint
            if node.get("role") == "destructive":
                label_color = "red"
            if node.get("disabled") is not None and truthy(self.engine.bare(node["disabled"], box.scope)):
                rules.append("opacity:0.35")
            pill_w, pill_h = box.extra.get("content", (box.frame[2], box.frame[3]))
            frame_w, frame_h = box.extra.get("framed", (pill_w, pill_h))
            name = self.engine.mods(box).get("alignment") or "center"
            slack = (self.engine.align_y(name, frame_h, pill_h), self.engine.align_x(name, frame_w, pill_w))
            padding = (padding[0] + slack[0], padding[1] + slack[1], padding[2] + (frame_h - pill_h - slack[0]), padding[3] + (frame_w - pill_w - slack[1]))
            if box.children:
                self.div(box, rules, inset=padding)
                for child in box.children:
                    self.paint(child, label_color)
                return
            font = box.font
            size = font.get("controlSize") or "regular"
            if size in ("small", "mini"):
                font = dict(font, size=15.0 if size == "small" else 13.0, style="subheadline" if size == "small" else "footnote")
            inner = ""
            block = ""
            if box.extra.get("symbol") and font.get("labelStyle") != "titleOnly":
                inner += f'<span style="margin-right:{0 if font.get("labelStyle") == "iconOnly" else layout.LABEL_GAP:.0f}px">{self.glyph(box.extra["symbol"], font["size"], label_color, font["weight"])}</span>'
                if (box.lines or (1, 1))[0] > 1:
                    block = "text-align:left;"
            if font.get("labelStyle") != "iconOnly":
                title = "\n".join(rich(line) for line in box.extra["lines_text"]) if box.extra.get("lines_text") and (box.lines or (1, 1))[0] > 1 else rich(box.text)
                inner += f'<span style="{block}white-space:pre">{title}</span>'
            self.div(box, rules + self.font_rules(font) + [f"color:{css_color(label_color)}", "display:flex", "align-items:center", "justify-content:center", "text-align:center", "white-space:nowrap" if (box.lines or (1, 1))[0] == 1 else "white-space:pre-wrap"], inner, inset=padding)
        elif kind == "Divider":
            x, y, w, h = box.frame
            self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:1px;background:rgba(60,60,67,0.29)"></div>')
        elif kind in ("Capsule", "Circle", "Rectangle", "RoundedRectangle", "Ellipse", "Color", "Gradient", "Path"):
            fill = node.get("fill") if kind not in ("Color", "Gradient") else box.value
            if kind == "Gradient":
                rules.append(f"background:{gradient({'gradient': resolve(box.value, box.scope), 'direction': node.get('direction'), 'kind': node.get('kind')})}")
            elif kind == "Path":
                rules.append(f"box-shadow:inset 0 -3px 0 {css_color(resolve(node.get('stroke'), box.scope) if node.get('stroke') else 'accent')}")
            elif fill is not None:
                rules.append(f"background:{css_color(resolve(fill, box.scope), 'rgb(0,122,255)')}")
            elif node.get("stroke") is not None:
                rules.append(f"box-shadow:inset 0 0 0 {resolve(node.get('lineWidth'), box.scope) or 1}px {css_color(resolve(node['stroke'], box.scope))}")
            else:
                rules.append("background:rgb(0,122,255)")
            if kind == "Capsule":
                rules.append("border-radius:999px")
            elif kind in ("Circle", "Ellipse"):
                rules.append("border-radius:50%")
            elif kind == "RoundedRectangle":
                rules.append(f"border-radius:{resolve(box.value, box.scope) or 12}px")
            self.div(box, rules)
        elif kind == "Gauge":
            style = node.get("style")
            value = layout.number(resolve(box.value, box.scope)) or 0.0
            bounds = resolve(node.get("in"), box.scope) or [0, 1]
            low, high = (bounds + [0, 1])[:2] if isinstance(bounds, list) else (0, 1)
            fraction = min(max((value - low) / (high - low), 0.0), 1.0) if high > low else 0.0
            tint = css_color(resolve(node.get("tint"), box.scope) if node.get("tint") is not None else "accent")
            if style in ("circular", "capacity"):
                x, y, w, h = box.frame
                self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:{h:.1f}px;border-radius:50%;background:conic-gradient({tint} {fraction * 360:.0f}deg, rgba(120,120,128,0.2) 0);-webkit-mask:radial-gradient(circle, transparent 59%, black 60%);mask:radial-gradient(circle, transparent 59%, black 60%)"></div>')
                if box.extra.get("current"):
                    self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:{h:.1f}px;display:flex;align-items:center;justify-content:center;{";".join(self.font_rules(dict(box.font, size=17.0, weight="semibold", style=None)))};color:{css_color(color)}">{html.escape(box.extra["current"])}</div>')
            else:
                x, y, w, h = box.frame
                thick = 4.0 if style == "bar" else 16.0
                bar_y = y + (31.0 if box.extra.get("label") is not None else 0.0)
                self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{bar_y:.1f}px;width:{w:.1f}px;height:{thick:.0f}px;border-radius:{thick / 2:.0f}px;background:rgba(120,120,128,0.2)"></div>')
                self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{bar_y:.1f}px;width:{w * fraction:.1f}px;height:{thick:.0f}px;border-radius:{thick / 2:.0f}px;background:{tint}"></div>')
                if box.extra.get("label") is not None:
                    self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y:.1f}px;width:{w:.1f}px;height:31px;display:flex;align-items:center;justify-content:center;{";".join(self.font_rules(dict(box.font)))};color:{css_color(color)}">{rich(box.extra["label"])}</div>')
                if box.extra.get("current") is not None or box.extra.get("bounds"):
                    low_label = text_of(resolve(node.get("min"), box.scope)) if node.get("min") is not None else ""
                    high_label = text_of(resolve(node.get("max"), box.scope)) if node.get("max") is not None else ""
                    self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{bar_y + thick:.1f}px;width:{w:.1f}px;height:31px;display:flex;align-items:center;justify-content:space-between;{";".join(self.font_rules(dict(box.font, size=13.0, style="footnote")))};color:rgba(60,60,67,0.6)"><span>{html.escape(low_label)}</span><span>{html.escape(box.extra.get("current") or "")}</span><span>{html.escape(high_label)}</span></div>')
        elif kind == "Slider":
            x, y, w, h = box.frame
            value = layout.number(resolve(node.get("bind"), box.scope)) or 0.0
            bounds = resolve(node.get("in"), box.scope) or [0, 1]
            low, high = (bounds + [0, 1])[:2] if isinstance(bounds, list) else (0, 1)
            fraction = min(max((value - low) / (high - low), 0.0), 1.0) if high > low else 0.0
            tint = css_color(resolve(node.get("tint"), box.scope) if node.get("tint") is not None else "accent")
            self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y + h / 2 - 2:.1f}px;width:{w:.1f}px;height:4px;border-radius:2px;background:rgba(120,120,128,0.2)"></div>')
            self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y + h / 2 - 2:.1f}px;width:{w * fraction:.1f}px;height:4px;border-radius:2px;background:{tint}"></div>')
            self.parts.append(f'<div class="n" style="left:{x + w * fraction - 13:.1f}px;top:{y + h / 2 - 13:.1f}px;width:26px;height:26px;border-radius:50%;background:white;box-shadow:0 1px 4px rgba(0,0,0,0.25)"></div>')
        elif kind == "Picker":
            labels = box.extra.get("labels") or []
            chosen = box.text
            if node.get("style") in ("segmented", "palette") and labels:
                cells = "".join(f'<span style="flex:1;text-align:center;border-radius:999px;{"background:white;box-shadow:0 1px 3px rgba(0,0,0,0.15);font-weight:600" if l == chosen else ""}">{html.escape(l)}</span>' for l in labels)
                self.div(box, rules + self.font_rules(dict(box.font, size=13.0, style="footnote")) + ["background:rgba(120,120,128,0.12)", "border-radius:999px", "display:flex", "align-items:stretch", "padding:2px", "box-sizing:border-box", "line-height:27px"], cells)
            else:
                self.div(box, rules + self.font_rules(box.font) + ["background:rgba(120,120,128,0.12)", "border-radius:999px", "display:flex", "align-items:center", "justify-content:center"], html.escape(chosen) + ' <span style="opacity:0.5">⌃⌄</span>')
        elif kind == "Toggle":
            x, y, w, h = box.frame
            on = truthy(resolve(node.get("bind"), box.scope))
            self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y:.1f}px;width:{w - 62:.1f}px;height:{h:.1f}px;display:flex;align-items:center;{";".join(self.font_rules(box.font))};color:{css_color(color)}">{rich(box.text)}</div>')
            self.parts.append(f'<div class="n" style="left:{x + w - 62:.1f}px;top:{y:.1f}px;width:62px;height:{h:.1f}px;border-radius:999px;background:{"rgb(52,199,89)" if on else "rgba(120,120,128,0.2)"}"><div style="position:absolute;top:2px;{"right" if on else "left"}:2px;width:{h - 4:.0f}px;height:{h - 4:.0f}px;border-radius:50%;background:white;box-shadow:0 2px 4px rgba(0,0,0,0.2)"></div></div>')
        elif kind == "TextField":
            typed = text_of(resolve(node.get("bind"), box.scope))
            style = text_of(resolve(node.get("style"), box.scope))
            chrome = {"plain": ["padding:0"], "bordered": ["border:1px solid rgba(60,60,67,0.3)", "border-radius:6px", "padding:5px 7px", "background:white"]}.get(
                "bordered" if style == "roundedBorder" else style, ["border-radius:10px", "padding:9px 12px", "background:rgba(120,120,128,0.2)"])
            self.div(box, rules + self.font_rules(box.font) + chrome + ["box-sizing:border-box", "white-space:pre-wrap", "overflow:hidden",
                                                                         f"color:{'rgb(0,0,0)' if typed else 'rgba(60,60,67,0.3)'}"], html.escape(typed or box.text or ""))
        elif kind == "Map":
            radius = layout.number(resolve(node.get("cornerRadius"), box.scope)) or 16
            self.div(box, rules + [f"border-radius:{radius:g}px", "overflow:hidden"], self.map_picture(box))
        elif kind == "Chart":
            self.div(box, rules, self.chart(box))
        elif kind == "ProgressView":
            x, y, w, h = box.frame
            if box.extra.get("determinate"):
                self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y + h - 4:.1f}px;width:{w:.1f}px;height:4px;border-radius:2px;background:rgba(0,122,255,0.25)"></div>')
                self.parts.append(f'<div class="n" style="left:{x:.1f}px;top:{y + h - 4:.1f}px;width:{w * min(max(layout.number(resolve(box.value, box.scope)) or 0, 0), 1):.1f}px;height:4px;border-radius:2px;background:rgb(0,122,255)"></div>')
            else:
                self.div(box, rules + ["border:2px solid rgba(60,60,67,0.3)", "border-top-color:transparent", "border-radius:50%", "box-sizing:border-box"])
        elif kind == "Face":
            face = ("<svg width='100%' height='100%' viewBox='0 0 100 100' preserveAspectRatio='xMidYMid meet'>"
                    "<circle cx='50' cy='50' r='50' fill='#f2c7a0'/><circle cx='35' cy='42' r='6' fill='#3a2a20'/>"
                    "<circle cx='65' cy='42' r='6' fill='#3a2a20'/>"
                    "<path d='M30 62 Q50 80 70 62' stroke='#3a2a20' stroke-width='6' fill='none' stroke-linecap='round'/></svg>")
            self.div(box, rules, face)
        elif kind == "Stepper":
            self.div(box, rules + self.font_rules(box.font) + ["display:flex", "align-items:center", "justify-content:space-between", f"color:{css_color(color)}"],
                     f"<span>{rich(box.text)}</span><span style='background:rgba(120,120,128,0.12);border-radius:8px;width:94px;height:32px;display:inline-flex;align-items:center;justify-content:space-around;font-size:20px'><span>−</span><span style='opacity:0.3'>|</span><span>+</span></span>")
        elif kind == "DatePicker":
            self.div(box, rules + self.font_rules(box.font) + ["display:flex", "align-items:center", "justify-content:space-between", f"color:{css_color(color)}"],
                     f"<span>{html.escape(box.text or '')}</span><span style='background:rgba(120,120,128,0.12);border-radius:8px;padding:6px 11px'>{html.escape(text_of(resolve(node.get('bind'), box.scope))[:10])}</span>")
        else:
            if rules:
                self.div(box, rules)
        outer = self.clip
        if kind in ("ScrollView", "Carousel", "Pages"):
            self.clip = box.frame
        self.cards += kind == "Card"
        for child in box.children:
            self.paint(child, color)
        self.cards -= kind == "Card"
        self.clip = outer
        if box.extra.get("overlay") is not None:
            self.paint(box.extra["overlay"], color)

    PALETTE = ["blue", "orange", "green", "purple", "pink", "teal", "indigo", "yellow", "red", "mint"]

    def map_picture(self, box):
        """A stand-in for Apple Maps: land, a park, water and streets drawn from the place's coordinates, with its pin.
        The phone draws the real map; this only has to read as one."""
        _, _, width, height = box.frame
        value = resolve(box.value, box.scope) if isinstance(box.value, (dict, str)) else box.value
        markers = (value or {}).get("markers") or [] if isinstance(value, dict) else []
        seed = sum(int(abs(layout.number(m.get("lat")) or 0) * 1e4) + int(abs(layout.number(m.get("lon")) or 0) * 1e4) for m in markers) or 7
        def r(i):
            return ((seed * (i + 3) * 2654435761) % 1000) / 1000
        out = [f'<rect width="{width:.0f}" height="{height:.0f}" fill="#f1eee8"/>',
               f'<ellipse cx="{width * (0.15 + 0.2 * r(1)):.0f}" cy="{height * (0.2 + 0.2 * r(2)):.0f}" rx="{width * 0.16:.0f}" ry="{height * 0.28:.0f}" fill="#d3e9c8"/>',
               f'<path d="M{width * 0.62:.0f},{height:.0f} C{width * 0.7:.0f},{height * 0.7:.0f} {width * 0.9:.0f},{height * 0.75:.0f} {width:.0f},{height * 0.55:.0f} L{width:.0f},{height:.0f} Z" fill="#b9dcf4"/>']
        streets = []
        for i in range(5):
            y = height * (0.1 + 0.2 * i + 0.08 * (r(i + 10) - 0.5))
            streets.append(((0, y), (width, y + height * 0.25 * (r(i + 20) - 0.5))))
        for i in range(6):
            x = width * (0.08 + 0.17 * i + 0.06 * (r(i + 30) - 0.5))
            streets.append(((x, 0), (x + width * 0.12 * (r(i + 40) - 0.5), height)))
        for (x1, y1), (x2, y2) in streets:
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#ffffff" stroke-width="4"/>')
        main = ((0, height * 0.62), (width, height * 0.38))
        out.append(f'<line x1="0" y1="{main[0][1]:.0f}" x2="{width:.0f}" y2="{main[1][1]:.0f}" stroke="#e3d9c3" stroke-width="9"/>'
                   f'<line x1="0" y1="{main[0][1]:.0f}" x2="{width:.0f}" y2="{main[1][1]:.0f}" stroke="#fbf3dc" stroke-width="6"/>')
        if markers:
            color = css_color(resolve(markers[0].get("color"), box.scope) if markers[0].get("color") else "red")
            cx, cy = width / 2, height / 2
            out.append(f'<circle cx="{cx:.0f}" cy="{cy + 1:.0f}" r="13" fill="rgba(0,0,0,0.18)"/>'
                       f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="12" fill="{color}" stroke="white" stroke-width="2.5"/>'
                       f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="4" fill="white"/>')
        return f'<svg width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">{"".join(out)}</svg>'

    def chart(self, box):
        """An SVG of the chart's marks, the way Swift Charts lays them out: bars, lines, rules, areas, points, sectors."""
        node = box.node
        scope = box.scope
        x0, y0, width, height = box.frame
        marks = box.value if isinstance(box.value, list) else [box.value]
        specs = []
        for index, mark in enumerate(marks):
            if not isinstance(mark, dict):
                continue
            kind = mark.get("type")
            color = css_color(resolve(mark.get("color"), scope) if mark.get("color") is not None else ("accent" if index == 0 else self.PALETTE[index % len(self.PALETTE)]))
            data = resolve(mark.get("data"), scope) if mark.get("data") is not None else []
            points = []
            for position, row in enumerate(data if isinstance(data, list) else []):
                if not isinstance(row, dict):
                    continue
                xv = row.get(mark.get("x") or "x", position)
                yv = layout.number(row.get(mark.get("y") or "y"))
                if yv is not None:
                    points.append((text_of(xv), yv, row))
            specs.append({"type": kind, "color": color, "points": points, "smooth": truthy(mark.get("smooth")), "inner": layout.number(resolve(mark.get("innerRadius"), scope)) or 0.0,
                          "value": layout.number(resolve(mark.get("value"), scope)) if mark.get("value") is not None else None, "series": mark.get("series")})
        sectors = [spec for spec in specs if spec["type"] == "sector"]
        if sectors:
            spec = sectors[0]
            total = sum(y for _, y, _ in spec["points"]) or 1.0
            radius = min(width, height) / 2
            inner = radius * spec["inner"]
            cx, cy = width / 2, height / 2
            paths = []
            angle = -math.pi / 2
            for index, (_, value, _) in enumerate(spec["points"]):
                sweep = value / total * 2 * math.pi
                gap = 0.03
                a0, a1 = angle + gap / 2, angle + sweep - gap / 2
                angle += sweep
                if a1 <= a0:
                    continue
                large = 1 if a1 - a0 > math.pi else 0
                outer_start = (cx + radius * math.cos(a0), cy + radius * math.sin(a0))
                outer_end = (cx + radius * math.cos(a1), cy + radius * math.sin(a1))
                inner_start = (cx + inner * math.cos(a1), cy + inner * math.sin(a1))
                inner_end = (cx + inner * math.cos(a0), cy + inner * math.sin(a0))
                fill = css_color(self.PALETTE[index % len(self.PALETTE)])
                paths.append(f'<path d="M{outer_start[0]:.1f},{outer_start[1]:.1f} A{radius:.1f},{radius:.1f} 0 {large} 1 {outer_end[0]:.1f},{outer_end[1]:.1f} L{inner_start[0]:.1f},{inner_start[1]:.1f} A{inner:.1f},{inner:.1f} 0 {large} 0 {inner_end[0]:.1f},{inner_end[1]:.1f} Z" fill="{fill}"/>')
            return f'<svg width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">{"".join(paths)}</svg>'
        categories = []
        for spec in specs:
            for label, _, _ in spec["points"]:
                if label not in categories:
                    categories.append(label)
        values = [y for spec in specs for _, y, _ in spec["points"]] + [spec["value"] for spec in specs if spec["value"] is not None]
        domain = resolve(node.get("yDomain"), scope) if node.get("yDomain") is not None else None
        low, high = (domain[0], domain[1]) if isinstance(domain, list) and len(domain) == 2 else (min(0.0, min(values, default=0.0)), max(values, default=1.0) * 1.08 or 1.0)
        show_x = node.get("xAxis", True) is not False
        show_y = node.get("yAxis", True) is not False
        plot_w = width - (34 if show_y else 0)
        plot_h = height - (18 if show_x else 0)
        count = max(1, len(categories))
        slot = plot_w / count
        def px(index): return slot * (index + 0.5)
        def py(value): return plot_h - (value - low) / (high - low) * plot_h if high > low else plot_h
        out = []
        for spec in specs:
            kind, color = spec["type"], spec["color"]
            if kind == "bar":
                bar_w = slot * 0.62
                for label, value, _ in spec["points"]:
                    i = categories.index(label)
                    top = py(value)
                    out.append(f'<rect x="{px(i) - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{max(0.0, py(low) - top):.1f}" rx="3" fill="{color}"/>')
            elif kind in ("line", "area", "point"):
                coords = [(px(categories.index(label)), py(value)) for label, value, _ in spec["points"]]
                if not coords:
                    continue
                if spec["smooth"] and len(coords) > 2:
                    d = f"M{coords[0][0]:.1f},{coords[0][1]:.1f}"
                    for i in range(1, len(coords)):
                        p0 = coords[i - 2] if i >= 2 else coords[i - 1]
                        p1, p2 = coords[i - 1], coords[i]
                        p3 = coords[i + 1] if i + 1 < len(coords) else p2
                        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
                        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
                        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
                else:
                    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
                if kind == "area":
                    out.append(f'<path d="{d} L{coords[-1][0]:.1f},{py(low):.1f} L{coords[0][0]:.1f},{py(low):.1f} Z" fill="{color}" opacity="0.3"/>')
                if kind in ("line", "area"):
                    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>')
                if kind == "point":
                    out += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>' for x, y in coords]
            elif kind == "rule" and spec["value"] is not None:
                out.append(f'<line x1="0" x2="{plot_w:.1f}" y1="{py(spec["value"]):.1f}" y2="{py(spec["value"]):.1f}" stroke="{color}" stroke-width="1.5" stroke-dasharray="4 3"/>')
        if show_x:
            for i, label in enumerate(categories):
                out.append(f'<text x="{px(i):.1f}" y="{height - 4:.1f}" text-anchor="middle" font-family="SF" font-size="11" fill="rgba(60,60,67,0.6)">{html.escape(label)}</text>')
            out.insert(0, f'<line x1="0" x2="{plot_w:.1f}" y1="{plot_h:.1f}" y2="{plot_h:.1f}" stroke="rgba(60,60,67,0.29)" stroke-width="1"/>')
        if show_y:
            for step in range(4):
                value = low + (high - low) * step / 3
                out.append(f'<line x1="0" x2="{plot_w:.1f}" y1="{py(value):.1f}" y2="{py(value):.1f}" stroke="rgba(60,60,67,0.12)" stroke-width="1"/>')
                out.append(f'<text x="{plot_w + 6:.1f}" y="{py(value) + 4:.1f}" font-family="SF" font-size="11" fill="rgba(60,60,67,0.6)">{text_of(round(value, 1))}</text>')
        return f'<svg width="{width:.0f}" height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">{"".join(out)}</svg>'

    def page(self, width, height, dark=False):
        fonts = "".join(f'@font-face{{font-family:"{name}";src:url("file://{os.path.join(layout.FONTS_DIR, layout.FONT_FILES[design])}");font-weight:100 900}}'
                        for name, design in (("SF", "default"), ("SFR", "rounded"), ("SFM", "monospaced")))
        body = "".join(self.parts)
        return (f'<!doctype html><html><head><meta charset="utf-8"><title>Card</title><style>{fonts}'
                f'html,body{{margin:0;background:{"black" if dark else "white"}}}'
                f'#card{{position:relative;width:{width + 16:.0f}px;height:{height + 16:.0f}px;font-family:SF,-apple-system,system-ui;color:black;font-optical-sizing:auto}}'
                f'.n{{position:absolute;box-sizing:border-box}}#card>.n{{margin:0;transform:translate(8px,8px)}}'
                f'</style></head><body><div id="card">{body}</div></body></html>')


def paint(card, components=None, width=layout.WIDTH, derived=None, page=False):
    engine = layout.Engine(card, components, width, derived, page=page)
    result = engine.run()
    painter = Painter(engine)
    painter.paint(engine.root)
    return painter.page(width, result["size"][1]), result


if __name__ == "__main__":
    source = json.load(open(sys.argv[1]))
    components = json.load(open(sys.argv[2])) if len(sys.argv) > 2 and sys.argv[2] else {}
    report = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}
    width = next((float(f["w"]) for f in report.get("frames") or [] if "›" not in f["path"]), float((report.get("size") or [layout.WIDTH])[0]))
    page, _ = paint(source, components, width, report.get("derived") or {})
    print(page)
