# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""Compares the layout twin with the frames the simulator reports, node by node.

    python -m dedala.twin.calibrate all [folder]        every card in twin/calibration/corpus, or a folder
    python -m dedala.twin.calibrate verbose [folder]    the same, listing every node off by more than a point
    python -m dedala.twin.calibrate compare card.json report.json [components.json]
    python -m dedala.twin.calibrate sizes               every text size in twin/calibration/sizes, against the same cards

A folder holds <key>.card.json, <key>.json (the simulator's report, with frames) and optionally
<key>.components.json.
"""

import glob
import json
import os
import sys

from . import layout

REPOSITORY = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
CALIBRATION = os.environ.get("BENCH_CALIBRATION") or os.path.join(REPOSITORY, "twin", "calibration")

def card_width(report):
    """The width the phone proposed to the card: a Card's content frame plus its padding, since the card's own frame
    is snapped to the pixel grid; for bare content the root frame less the snap offset."""
    frames = report.get("frames") or []
    for frame in frames:
        if "›" not in frame["path"]:
            if frame["view"] == "Card":
                inner = next((f for f in frames if f["path"].count("›") == 1 and f["view"] == "VStack"), None)
                if inner is not None and float(inner["w"]) + 32.0 >= float(frame["w"]) - 0.5:
                    return float(inner["w"]) + 32.0
                return min(float(frame["w"]), float((report.get("size") or [frame["w"]])[0]))
            width = min(float(frame["w"]), float((report.get("size") or [frame["w"]])[0]))
            return width + 2 * min(0.0, float(frame["x"]))
    return float((report.get("size") or [layout.WIDTH])[0])


PROBE_CEILING = 2721.33


def capped(report, twin):
    """The app's probe draws a card no taller than its ceiling and centres the content in it; a twin card past the
    ceiling is compared the same way."""
    theirs = report.get("frames") or []
    mine = twin["frames"]
    if not theirs or not mine or abs(theirs[0]["h"] - PROBE_CEILING) > 0.1 or mine[0]["h"] <= theirs[0]["h"]:
        return mine
    shift = (mine[0]["h"] - theirs[0]["h"]) / 2
    out = [dict(f, y=f["y"] - shift) for f in mine]
    out[0] = dict(mine[0], h=theirs[0]["h"])
    return out


def compare(card, components, report, verbose=True):
    width = card_width(report)
    twin = layout.layout(card, components, float(width), report.get("derived") or {}, report.get("at"), report.get("textSize") or "large")
    theirs = {f["path"]: f for f in report.get("frames") or []}
    mine = {f["path"]: f for f in capped(report, twin)}
    rows = []
    for path, a in theirs.items():
        b = mine.get(path)
        if b is None:
            rows.append((path, a["view"], a, None))
            continue
        rows.append((path, a["view"], a, b))
    extra = [p for p in mine if p not in theirs]
    deltas = []
    for path, view, a, b in rows:
        if b is None:
            if verbose:
                print(f"  MISSING {path[:72]:72} {view:10} app x={a['x']:6.1f} y={a['y']:6.1f} w={a['w']:6.1f} h={a['h']:6.1f}")
            continue
        d = tuple(b[k] - a[k] for k in ("x", "y", "w", "h"))
        deltas.append((path, view, d))
        if verbose and any(abs(v) > 1.0 for v in d):
            print(f"  {path[:72]:72} {view:10} app x={a['x']:6.1f} y={a['y']:6.1f} w={a['w']:6.1f} h={a['h']:6.1f}  twin dx={d[0]:+6.1f} dy={d[1]:+6.1f} dw={d[2]:+6.1f} dh={d[3]:+6.1f}")
    if verbose and extra:
        print("  extra in twin:", ", ".join(p[:60] for p in extra[:8]), "..." if len(extra) > 8 else "")
    size = report.get("size") or [0, 0]
    if verbose:
        print(f"  size app {size[0]}×{size[1]}  twin {twin['size'][0]:.0f}×{twin['size'][1]:.1f}")
    return deltas, len([r for r in rows if r[3] is None]), extra, (size, twin["size"])


def summary(all_deltas):
    import statistics
    by_view = {}
    for path, view, d in all_deltas:
        by_view.setdefault(view, []).append(d)
    print(f"{'view':14} {'n':>4} {'|dx|':>6} {'|dy|':>6} {'|dw|':>6} {'|dh|':>6}   {'dw p95':>7} {'dh p95':>7}")
    for view, ds in sorted(by_view.items(), key=lambda kv: -len(kv[1])):
        cols = list(zip(*ds))
        means = [statistics.mean(abs(v) for v in col) for col in cols]
        p95 = [sorted(abs(v) for v in col)[int(0.95 * (len(col) - 1))] for col in cols]
        print(f"{view:14} {len(ds):4} {means[0]:6.1f} {means[1]:6.1f} {means[2]:6.1f} {means[3]:6.1f}   {p95[2]:7.1f} {p95[3]:7.1f}")
    all_cols = list(zip(*[d for _, _, d in all_deltas]))
    if all_cols:
        print(f"nodes {len(all_deltas)}  within 2pt on every axis: {within(all_deltas, 2) / len(all_deltas):.0%}  within 1pt: {within(all_deltas, 1) / len(all_deltas):.1%}")


def within(deltas, points):
    """How many nodes are within so many points of the phone on every axis."""
    return sum(1 for _, _, d in deltas if all(abs(v) <= points for v in d))


def cards(folder):
    """Each card of a folder that has a report: its key, the card, its components and the report."""
    for card_path in sorted(glob.glob(os.path.join(folder, "*.card.json"))):
        key = os.path.basename(card_path)[: -len(".card.json")]
        report_path = os.path.join(folder, key + ".json")
        if not os.path.exists(report_path):
            continue
        components_path = os.path.join(folder, key + ".components.json")
        components = json.load(open(components_path)) if os.path.exists(components_path) else {}
        yield key, json.load(open(card_path)), components, json.load(open(report_path))


def by_size():
    """Each `sizes/<textSize>.jsonl.gz` holds the phone's reports at that text size for the probes and the corpus:
    the size's name with every node's deltas, per set."""
    import gzip
    for path in sorted(glob.glob(os.path.join(CALIBRATION, "sizes", "*.jsonl.gz")), key=lambda p: list(layout.TEXT_SIZES).index(os.path.basename(p)[:-9])):
        rows = {"probes": [], "corpus": []}
        for line in gzip.open(path, "rt"):
            entry = json.loads(line)
            folder = os.path.join(CALIBRATION, entry["set"])
            components_path = os.path.join(folder, entry["key"] + ".components.json")
            components = json.load(open(components_path)) if os.path.exists(components_path) else {}
            card = json.load(open(os.path.join(folder, entry["key"] + ".card.json")))
            rows[entry["set"]] += compare(card, components, entry["report"], verbose=False)[0]
        yield os.path.basename(path)[:-9], rows


def sizes():
    for size, rows in by_size():
        line = [size.ljust(15)]
        for name, deltas in rows.items():
            line.append(f"{name} {len(deltas)} nodes, {within(deltas, 2) / max(1, len(deltas)):.1%} within 2pt, {within(deltas, 1) / max(1, len(deltas)):.1%} within 1pt")
        print("  ".join(line))


if __name__ == "__main__":
    verb = sys.argv[1] if len(sys.argv) > 1 else "all"
    if verb == "sizes":
        sizes()
        sys.exit()
    if verb == "compare":
        card = json.load(open(sys.argv[2]))
        report = json.load(open(sys.argv[3]))
        components = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else {}
        deltas, missing, extra, sizes = compare(card, components, report)
        summary(deltas)
    else:
        all_deltas = []
        missing_total = 0
        for key, card, components, report in cards(sys.argv[2] if len(sys.argv) > 2 else os.path.join(CALIBRATION, "corpus")):
            print(key)
            deltas, missing, extra, sizes = compare(card, components, report, verbose=verb == "verbose")
            app_h, twin_h = sizes[0][1], sizes[1][1]
            print(f"  height app {app_h} twin {twin_h:.1f}  nodes {len(deltas)} missing {missing} extra {len(extra)}")
            all_deltas += deltas
            missing_total += missing
        summary(all_deltas)
        print("missing nodes", missing_total)
