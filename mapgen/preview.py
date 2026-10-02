"""Render a CompiledMap to PNG: the 512x512 scenario picture and a large, labelled working preview.

The working preview is meant to be iterated against: every node carries its id and zone, colour is by
role/zone kind, lane types are drawn differently, chokepoints are ringed and each cluster's home planet
is marked.
"""
from __future__ import annotations

import io
import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .compiler import CompiledMap

BG = (12, 14, 24)
PANEL = (20, 23, 38)
LANE = (142, 155, 186)
WORMHOLE = (226, 122, 255)
STAR_LANE = (255, 210, 90)
TEXT = (203, 213, 235)

# colour by role, falling back to the zone kind
ROLE = {"star": (255, 245, 180), "home": (255, 215, 0), "chokepoint": (255, 130, 130),
        "pirate": (230, 50, 50), "wormhole": WORMHOLE}
KIND = {"home": (210, 180, 90), "border": (90, 190, 255), "contested": (255, 150, 60),
        "core": (180, 120, 255), "filler": (130, 150, 140), "pirate": (230, 50, 50),
        "custom": (200, 200, 200)}
TIER_SIZE = {"S": 0.75, "M": 1.0, "L": 1.4, "XL": 1.9}   # spread so tier reads at a glance


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow < 10.1
        return ImageFont.load_default()


def colour(n) -> tuple[int, int, int]:
    if n.role in ROLE:
        return ROLE[n.role]
    return KIND.get(n.zone_kind, (200, 200, 200)) if getattr(n, "zone_kind", None) else (200, 200, 200)


def render(m: CompiledMap, size: int, labels: bool = False) -> bytes:
    kinds = {z.id: z.kind for z in m.spec.zones}
    for n in m.nodes:                      # attach the zone kind for colouring
        n.zone_kind = kinds.get(n.zone) if n.zone else None

    pad = size * (0.10 if labels else 0.06)
    xs = [n.pos[0] for n in m.nodes]
    ys = [n.pos[1] for n in m.nodes]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    k = (size - 2 * pad) / span
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    def pt(n):
        return (size / 2 + (n.pos[0] - cx) * k, size / 2 + (n.pos[1] - cy) * k)

    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    w = max(2, round(size / 300))      # lanes must carry across a dark field
    for l in m.lanes:
        a, b = pt(m.nodes[l.a]), pt(m.nodes[l.b])
        if l.type == "wormhole":
            _dashed(d, a, b, WORMHOLE, w + 2, dash=max(5, size // 100))
        elif l.type == "star":
            d.line([a, b], fill=STAR_LANE, width=w + 2)
        else:
            d.line([a, b], fill=LANE, width=w)

    r0 = max(3.0, size / 135)
    label_font = _font(max(8, size // 115))
    for n in m.nodes:
        x, y = pt(n)
        col = colour(n)
        if n.role == "star":
            r = r0 * 2.2
        elif n.role == "home":
            r = r0 * 1.9
        elif n.role == "wormhole":
            r = r0 * 0.9
        else:
            r = r0 * TIER_SIZE.get(n.tier, 1.0)
        if n.role == "wormhole":           # diamond, so fixtures never read as planets
            d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=col)
        else:
            d.ellipse([x - r, y - r, x + r, y + r], fill=col)
        if n.role == "home":               # gold ring + crosshair marks the player's planet
            rr = r + max(2, size / 220)
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(255, 255, 255), width=w)
            d.line([(x - rr * 1.6, y), (x - rr, y)], fill=(255, 255, 255), width=w)
            d.line([(x + rr, y), (x + rr * 1.6, y)], fill=(255, 255, 255), width=w)
        if n.role == "chokepoint":
            rr = r + max(2, size / 250)
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(255, 255, 255), width=w + 1)
        if labels and n.role != "star":
            tag = str(n.id)
            if n.role == "home":
                tag += f" P{n.ownership['player_index']}"
            elif n.zone:
                tag += f" {n.zone}"
            d.text((x + r + 2, y - r - 1), tag, fill=TEXT, font=label_font)
    if labels:
        _legend(d, size, m)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _dashed(d, a, b, col, w, dash):
    length = math.dist(a, b)
    if not length:
        return
    steps = max(1, int(length // dash))
    for i in range(0, steps, 2):
        t0, t1 = i / steps, min(1.0, (i + 1) / steps)
        d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill=col, width=w)


def _legend(d, size, m: CompiledMap):
    f = _font(max(8, size // 95))
    rows = [("home planet (ringed, P#)", ROLE["home"]), ("chokepoint (white ring)", ROLE["chokepoint"]),
            ("pirate", ROLE["pirate"]), ("wormhole fixture (diamond)", WORMHOLE),
            ("border zone", KIND["border"]), ("contested zone", KIND["contested"]),
            ("core zone", KIND["core"]), ("filler", KIND["filler"]),
            ("lane: normal / wormhole (dashed) / star", LANE)]
    pad = size * 0.012
    line_h = size / 52
    d.rectangle([0, 0, size * 0.40, pad * 2 + line_h * (len(rows) + 1.6)], fill=PANEL)
    d.text((pad, pad), f"{m.spec.meta.display_name}  -  {len(m.planets())} planets, "
           f"{len(m.fixtures())} fixtures, {len(m.lanes)} lanes, seed {m.spec.meta.seed}",
           fill=(255, 255, 255), font=f)
    y = pad + line_h * 1.2
    for label, col in rows:
        d.rectangle([pad, y + 2, pad + size / 110, y + 2 + size / 110], fill=col)
        d.text((pad + size / 70, y), label, fill=TEXT, font=f)
        y += line_h
    d.text((pad, y + 2), "labels: node id + zone", fill=TEXT, font=f)


def open_file(path: Path | str) -> bool:
    """Open a rendered preview in the OS viewer. Returns False if that is not possible.

    MAPGEN_NO_OPEN=1 disables it: a viewer holding the PNG open makes the next write fail on Windows,
    and tests must never spawn one.
    """
    if os.environ.get("MAPGEN_NO_OPEN"):
        return False
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))       # noqa: S606 - the path is ours
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except OSError:
        return False
