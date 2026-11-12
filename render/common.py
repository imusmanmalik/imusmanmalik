"""Shared pieces for the profile SVGs: pinned fonts, text as outlines, palette, GitHub API."""

import hashlib
import io
import json
import os
import subprocess
import urllib.request
import zipfile

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fonts")
LOGIN = "imusmanmalik"

# Pinned releases. Both fonts are under the SIL Open Font License.
FONT_ZIPS = {
    "inter": (
        "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip",
        "ff970a5d4561a04f102a7cb781adbd6ac4e9b6c460914c7a101f15acb7f7d1a4",
    ),
    "jetbrains-mono": (
        "https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip",
        "6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf",
    ),
}
FAMILIES = {
    "sans": ("inter", "extras/ttf/Inter-Regular.ttf"),
    "sans-med": ("inter", "extras/ttf/Inter-Medium.ttf"),
    "mono": ("jetbrains-mono", "fonts/ttf/JetBrainsMono-Regular.ttf"),
    "mono-med": ("jetbrains-mono", "fonts/ttf/JetBrainsMono-Medium.ttf"),
}

THEMES = {
    "light": {
        "ink": "#1f2328",
        "muted": "#59636e",
        "faint": "#818b98",
        "line": "#d1d9e0",
        "link": "#c0c8d0",
        "cell": "#f6f8fa",
        "blank": "#eef1f4",
        "led": "#1a7f37",
        "own": "#0969da",
        "sec": "#9a6700",
    },
    "dark": {
        "ink": "#e6edf3",
        "muted": "#9198a1",
        "faint": "#7d8590",
        "line": "#30363d",
        "link": "#3d444d",
        "cell": "#151b23",
        "blank": "#10151c",
        "led": "#3fb950",
        "own": "#4493f8",
        "sec": "#d29922",
    },
}


def font_path(family):
    archive, member = FAMILIES[family]
    path = os.path.join(CACHE, archive, member)
    if os.path.exists(path):
        return path
    url, sha256 = FONT_ZIPS[archive]
    with urllib.request.urlopen(url) as resp:
        blob = resp.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != sha256:
        raise RuntimeError(f"{url} has sha256 {digest}, expected {sha256}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for _, name in FAMILIES.values():
            if name in zf.namelist():
                zf.extract(name, os.path.join(CACHE, archive))
    return path


class Fonts:
    """Shapes text with HarfBuzz and emits it as reusable glyph outlines."""

    def __init__(self, sizes):
        self.sizes = sizes
        self.hb = {}
        self.tt = {}
        self.upem = {}
        self.defs = {}
        for family in FAMILIES:
            path = font_path(family)
            self.hb[family] = hb.Font(hb.Face(hb.Blob.from_file_path(path)))
            self.tt[family] = TTFont(path)
            self.upem[family] = self.tt[family]["head"].unitsPerEm

    def shape(self, style, text):
        family, size, track = self.sizes[style]
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        features = {"kern": True, "liga": False, "calt": False}
        if family.startswith("sans"):
            # Tailed l, so "llm-d" does not read as "IIm-d".
            features["cv05"] = True
        if text.replace(".", "").replace(",", "").isdigit():
            features["tnum"] = True
        hb.shape(self.hb[family], buf, features)
        scale = size / self.upem[family]
        glyphs = []
        x = 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            glyphs.append((info.codepoint, x + pos.x_offset * scale))
            x += pos.x_advance * scale + track
        return glyphs, (x - track) if glyphs else 0.0

    def width(self, style, text):
        return self.shape(style, text)[1]

    def _ref(self, family, gid):
        ref = f"{family}-{gid}"
        if ref not in self.defs:
            tt = self.tt[family]
            glyph_set = tt.getGlyphSet()
            pen = SVGPathPen(glyph_set)
            # Flip y once in the def so each <use> only needs translate and scale.
            glyph_set[tt.getGlyphName(gid)].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
            self.defs[ref] = pen.getCommands()
        return ref

    def text(self, style, text, x, y, cls, anchor="start"):
        family, size, _ = self.sizes[style]
        glyphs, width = self.shape(style, text)
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        scale = size / self.upem[family]
        uses = []
        for gid, gx in glyphs:
            ref = self._ref(family, gid)
            if self.defs[ref]:
                uses.append(f'<use href="#{ref}" transform="translate({x + gx:.2f} {y:.2f}) scale({scale:.5f})"/>')
        return f'<g class="{cls}">' + "".join(uses) + "</g>", width

    def defs_svg(self):
        return "".join(f'<path id="{ref}" d="{d}"/>' for ref, d in sorted(self.defs.items()) if d)


def token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    return subprocess.run(["gh", "auth", "token"], check=True, capture_output=True, text=True).stdout.strip()


def graphql(query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"]))
    return body["data"]


def write_svg(name, theme, svg):
    os.makedirs(ASSETS, exist_ok=True)
    path = os.path.join(ASSETS, f"{name}-{theme}.svg")
    with open(path, "w", encoding="ascii") as fh:
        fh.write(svg)
    return path
