"""Draws the Hakoniwa icon and the animated scene on the top page.

A small town is built from blocks on a board and drawn from above at an angle
(2:1 isometric) as pixel art. Only the ten brand colours are used: a block's
side faces take the next one or two darker steps of the same ramp, so shading
never leaves the palette.

    python tools/make_icon.py

Writes, under docs/images/ and hakoniwa/interface/web/:
  scene.svg   128px town, animated (people walk, boats move, clouds drift)
  build.svg   the same town in pieces that carry a build order (web only): the page shows them one by one
              while a world is being created
  town.png    the same town as a still image (1024px)
  icon.svg    48px simplified town for small sizes (header, favicon)
  icon.png, favicon.png
Standard library only.
"""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# dark purple -> blue -> light aqua. Index 0 is the darkest, 9 the lightest.
P = ["#7400b8", "#6930c3", "#5e60ce", "#5390d9", "#4ea8de", "#48bfe3", "#56cfe1", "#64dfdf", "#72efdd", "#80ffdb"]
RGB = [(int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)) for h in P]


def darker(k, steps):
    return max(0, k - steps)


class Board:
    """Collects items on an n x n board; x runs to the lower right, y to the lower left, z up."""

    def __init__(self, n, size, ox, oy):
        self.n, self.size, self.ox, self.oy = n, size, ox, oy
        self.items = []

    def cube(self, x, y, z, top, left=None, right=None, window=False):
        self.items.append({"kind": "cube", "x": x, "y": y, "z": z, "top": top,
                           "left": darker(top, 1) if left is None else left,
                           "right": darker(top, 2) if right is None else right, "window": window})

    def add(self, kind, x, y, z, **kw):
        self.items.append({"kind": kind, "x": x, "y": y, "z": z, **kw})

    def ground(self, river=(), roads_x=(), roads_y=()):
        for x in range(self.n):
            for y in range(self.n):
                self.cube(x, y, 0, 1, 1, 0)                                           # the box
                if y in river and x not in roads_x:
                    self.cube(x, y, 1, 6 if (x * 2 + y) % 5 == 0 else 5, 4, 3)        # water
                elif x in roads_x or y in roads_y:
                    self.cube(x, y, 1, 2, 2, 1)                                       # road and bridge
                else:
                    self.cube(x, y, 1, 9 if (x + 2 * y) % 5 else 8, 3, 2)             # grass

    def block(self, x0, x1, y0, y1, z0, z1, wall, window_levels=()):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    self.cube(x, y, z, wall, window=z in window_levels)

    def house(self, x, y, floors, wall, roof):
        self.block(x, x, y, y, 2, 1 + floors, wall, window_levels=range(2, 2 + floors))
        self.add("roof", x, y, 2 + floors, colour=roof)

    def tree(self, x, y, leaf=7):
        self.add("pole", x, y, 2, colour=1, height=3)
        self.add("crown", x, y, 2, colour=leaf)

    def screen(self, x, y, z):
        return self.ox + (x - y) * 4, self.oy + (x + y) * 2 - z * 4

    # -- drawing --------------------------------------------------------------
    def pixels(self, item):
        """Pixels of one item as (x, y, palette index), in drawing order."""
        sx, sy = self.screen(item["x"], item["y"], item["z"])
        kind, px = item["kind"], []
        if kind == "cube":
            for row, (a, b) in enumerate(((-2, 1), (-4, 3), (-4, 3), (-2, 1))):       # top diamond
                px += [(sx + c, sy + row, item["top"]) for c in range(a, b + 1)]
            for c in range(-4, 4):                                                    # two faces, 4 px tall
                start = 3 if c in (-4, -3, 2, 3) else 4
                px += [(sx + c, sy + start + i, item["left"] if c < 0 else item["right"]) for i in range(4)]
            if item["window"]:
                lit = min(9, item["top"] + 4)
                px += [(sx - 3, sy + 4, lit), (sx - 3, sy + 5, lit), (sx + 2, sy + 4, darker(lit, 1)), (sx + 2, sy + 5, darker(lit, 1))]
            return px
        if kind == "roof":                                                            # a pyramid on the block below
            k = item["colour"]
            for row, (a, b) in zip(range(2, 8), ((-1, 0), (-2, 1), (-3, 2), (-4, 3), (-4, 3), (-2, 1))):
                px += [(sx + c, sy + row, min(9, k + 2) if row == 2 else (min(9, k + 1) if c < 0 else k)) for c in range(a, b + 1)]
            return px
        base = sy + 6                                                                 # the middle of the tile the item stands on
        k = item.get("colour", 0)
        if kind == "pole":
            px += [(sx + c, base - i, k if c < 0 else darker(k, 1)) for i in range(item["height"]) for c in (-1, 0)]
        elif kind == "crown":                                                         # leaves on top of a trunk
            up = base - 8
            px += [(sx + c, up, min(9, k + 1)) for c in (-1, 0)] + [(sx + c, up + 1, min(9, k + 1)) for c in range(-3, 3)]
            px += [(sx + c, up + r, k if c < 0 else darker(k, 1)) for r in (2, 3, 4) for c in range(-3, 3)]
            px += [(sx + c, up + 5, k if c < 0 else darker(k, 1)) for c in (-1, 0)]
        elif kind == "person":
            px += [(sx + c, base - 2, item.get("head", 0)) for c in (-1, 0)]
            px += [(sx + c, base - i, k) for i in (0, 1) for c in (-1, 0)]
        elif kind == "boat":
            px += [(sx + c, base, 0) for c in range(-3, 3)] + [(sx + c, base - 1, 1) for c in range(-2, 2)]
            px += [(sx - 1, base - i, 9) for i in (2, 3, 4)] + [(sx, base - i, 8) for i in (2, 3)]
        return px

    def render(self, extra=()):
        img = [[None] * self.size for _ in range(self.size)]
        order = lambda it: (it["x"] + it["y"], it["z"], 0 if it["kind"] == "cube" else 1)   # back to front, bottom to top
        for item in sorted(list(self.items) + list(extra), key=order):
            for x, y, k in self.pixels(item):
                if 0 <= x < self.size and 0 <= y < self.size:
                    img[y][x] = k
        return img


def cloud_pixels(cx, cy, rows):
    return [(cx + dx + i, cy + dy, 9 if dy == 0 else 8) for dx, dy, w in rows for i in range(w)]


# ---------------------------------------------------------------- the big town (128px, 16 x 16 cells)
def town():
    b = Board(16, 128, 64, 46)
    b.ground(river=(10, 11), roads_x=(8,), roads_y=(4,))

    b.block(3, 5, 6, 8, 2, 2, 2)                                   # tower: a plinth, a shaft that gets lighter, a spire
    for z, k in zip(range(3, 11), (2, 3, 3, 4, 4, 5, 5, 6)):
        b.cube(4, 7, z, k, window=z % 2 == 1)
    b.add("pole", 4, 7, 11, colour=8, height=6)

    b.block(11, 13, 0, 2, 2, 3, 4, window_levels=(2, 3))           # hall with a dome
    b.block(11, 13, 0, 2, 4, 4, 2)
    b.cube(12, 1, 5, 3)
    b.add("roof", 12, 1, 6, colour=1)

    b.block(1, 2, 0, 1, 2, 6, 3, window_levels=(2, 4, 6))          # block of flats
    b.block(1, 2, 0, 1, 7, 7, 1)

    for x, y, floors, wall, roof in [(10, 6, 1, 4, 1), (12, 6, 2, 3, 0), (14, 6, 1, 5, 2), (1, 8, 1, 5, 1), (13, 8, 1, 4, 0),
                                     (5, 1, 2, 4, 0), (6, 2, 1, 5, 2), (2, 13, 2, 3, 1), (5, 14, 1, 4, 0), (10, 13, 1, 5, 1),
                                     (13, 14, 1, 3, 0), (14, 12, 1, 4, 2), (0, 5, 1, 4, 0), (15, 1, 1, 5, 1)]:
        b.house(x, y, floors, wall, roof)
    for x, y, leaf in [(0, 3, 7), (6, 0, 6), (10, 2, 7), (15, 3, 6), (6, 6, 7), (11, 8, 6), (15, 9, 7), (0, 9, 6), (6, 9, 7),
                       (2, 6, 6), (0, 12, 7), (4, 12, 6), (6, 13, 7), (12, 12, 6), (15, 15, 7), (0, 15, 6), (11, 15, 7),
                       (3, 2, 7), (14, 9, 6), (10, 9, 7), (3, 15, 7), (15, 13, 6)]:
        b.tree(x, y, leaf)
    return b


TOWN_BOATS = [({"kind": "boat", "x": 2, "y": 10, "z": 2}, (4, 2), 4, 14), ({"kind": "boat", "x": 13, "y": 11, "z": 2}, (-4, -2), 3, 11)]
TOWN_WALKERS = [   # item, pixel move per cell, cells, seconds
    ({"kind": "person", "x": 8, "y": 1, "z": 2, "colour": 9}, (-4, 2), 2, 6),
    ({"kind": "person", "x": 8, "y": 6, "z": 2, "colour": 8}, (-4, 2), 3, 9),
    ({"kind": "person", "x": 8, "y": 13, "z": 2, "colour": 9}, (-4, 2), 2, 5),
    ({"kind": "person", "x": 2, "y": 4, "z": 2, "colour": 9}, (4, 2), 4, 10),
    ({"kind": "person", "x": 14, "y": 4, "z": 2, "colour": 7}, (-4, -2), 4, 12),
    ({"kind": "person", "x": 9, "y": 14, "z": 2, "colour": 0, "head": 1}, (4, 2), 2, 7),
]
TOWN_CLOUDS = [(8, 14, [(2, 0, 6), (0, 1, 11), (1, 2, 8)]), (96, 20, [(1, 0, 6), (0, 1, 10)]), (40, 4, [(1, 0, 5), (0, 1, 8)])]


# ---------------------------------------------------------------- the small icon (48px, 5 x 5 cells)
def small():
    b = Board(5, 48, 24, 20)
    b.ground(river=(3,), roads_x=(2,))
    for z, k in zip(range(2, 6), (2, 3, 4, 5)):
        b.cube(1, 1, z, k, window=z % 2 == 1)
    b.add("pole", 1, 1, 6, colour=8, height=4)
    b.house(3, 0, 1, 4, 0)
    b.house(4, 2, 1, 5, 1)
    b.house(0, 4, 1, 4, 0)
    b.tree(0, 2, 7)
    b.tree(4, 4, 6)
    return b


# ---------------------------------------------------------------- output
def rects(img):
    """Pixels as SVG rects, merging runs of one colour in a row."""
    out = []
    for y, row in enumerate(img):
        x = 0
        while x < len(row):
            k = row[x]
            if k is None:
                x += 1
                continue
            w = 1
            while x + w < len(row) and row[x + w] == k:
                w += 1
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="1" fill="{P[k]}"/>')
            x += w
    return "".join(out)


def loose(px):
    seen = {}
    for x, y, k in px:
        seen[(x, y)] = k
    return "".join(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{P[k]}"/>' for (x, y), k in seen.items())


def svg_open(size, label):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" role="img" aria-label="{label}">'


def with_clouds(img, clouds):
    for cloud in clouds:
        for x, y, k in cloud_pixels(*cloud):
            if 0 <= y < len(img) and 0 <= x < len(img) and img[y][x] is None:
                img[y][x] = k
    return img


def scene_svg(b):
    css, back, front = [], [], []
    for i, cloud in enumerate(TOWN_CLOUDS):
        css.append(f".c{i}{{animation:c{i} {30 + i * 11}s steps({12 + i * 4}) infinite alternate}}@keyframes c{i}{{to{{transform:translateX({12 + i * 4}px)}}}}")
        back.append(f'<g class="c{i}">{loose(cloud_pixels(*cloud))}</g>')
    for i, (item, (dx, dy), cells, secs) in enumerate(TOWN_BOATS + TOWN_WALKERS):
        css.append(f".m{i}{{animation:m{i} {secs}s steps({cells * 2}) infinite alternate}}@keyframes m{i}{{to{{transform:translate({dx * cells}px,{dy * cells}px)}}}}")
        front.append(f'<g class="m{i}">{loose(b.pixels(item))}</g>')
    tx, ty = b.screen(4, 7, 11)
    css.append(".light{animation:light 2.4s steps(2) infinite}@keyframes light{50%{opacity:0}}")
    front.append(f'<rect class="light" x="{tx - 1}" y="{ty}" width="2" height="1" fill="{P[9]}"/>')
    css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    label = "A small town in a box, seen from above: people walk, boats move on the river"
    return svg_open(b.size, label) + "<style>" + "".join(css) + "</style>" + "".join(back) + rects(b.render()) + "".join(front) + "</svg>\n"


def run_rects(pixels):
    """Pixels (later ones win) as SVG rects, merging runs of one colour in a row."""
    seen = {}
    for x, y, k in pixels:
        seen[(x, y)] = k
    out, done = [], set()
    for (x, y) in sorted(seen, key=lambda q: (q[1], q[0])):
        if (x, y) in done:
            continue
        k, w = seen[(x, y)], 1
        while seen.get((x + w, y)) == k:
            w += 1
        done.update((x + i, y) for i in range(w))
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="1" fill="{P[k]}"/>')
    return "".join(out)


def build_svg(b):
    """The town in pieces, each with a place in the build order (--o). Painting order stays back to front; the page
    reveals pieces up to a moving count: the empty box, the ground, the buildings floor by floor, trees, then people."""
    paint = lambda it: (it["x"] + it["y"], it["z"], 0 if it["kind"] == "cube" else 1)
    n2 = b.n * b.n * 2
    ground, things = b.items[:n2], sorted(b.items[n2:], key=paint)
    bands = 2 * b.n - 1
    parts = []                                                   # (build order, svg), in painting order
    for z in (0, 1):                                             # the box, then its surface, one diagonal row at a time
        for band in range(bands):
            px = [q for it in ground if it["z"] == z and it["x"] + it["y"] == band for q in b.pixels(it)]
            parts.append((z * bands + band, run_rects(px)))
    n_ground = 2 * bands
    rise = sorted(range(len(things)), key=lambda i: ((0 if things[i]["kind"] in ("cube", "roof") else 1), things[i]["z"], things[i]["x"] + things[i]["y"]))
    rank = {i: r for r, i in enumerate(rise)}                    # buildings rise floor by floor, then the trees
    for i, it in enumerate(things):
        parts.append((n_ground + rank[i], run_rects(b.pixels(it))))
    n_things = len(things)
    css, movers = [], []
    for i, (item, (dx, dy), cells, secs) in enumerate(TOWN_BOATS + TOWN_WALKERS):
        css.append(f".m{i}{{animation:m{i} {secs}s steps({cells * 2}) infinite alternate}}@keyframes m{i}{{to{{transform:translate({dx * cells}px,{dy * cells}px)}}}}")
        movers.append((n_ground + n_things + i, f'<g class="m{i}">{loose(b.pixels(item))}</g>'))
    total = n_ground + n_things + len(movers)
    clouds = "".join(f'<g class="c{i}">{loose(cloud_pixels(*c))}</g>' for i, c in enumerate(TOWN_CLOUDS))
    for i in range(len(TOWN_CLOUDS)):
        css.append(f".c{i}{{animation:c{i} {30 + i * 11}s steps({12 + i * 4}) infinite alternate}}@keyframes c{i}{{to{{transform:translateX({12 + i * 4}px)}}}}")
    css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    body = "".join(f'<g class="b" style="--o:{o}">{svg}</g>' for o, svg in parts + movers)
    head = svg_open(b.size, "A town in a box being built").replace("<svg ", f'<svg data-ground="{n_ground}" data-things="{n_things}" data-total="{total}" ')
    return head + "<style>" + "".join(css) + "</style>" + clouds + body + "</svg>\n"


def png(img, scale):
    size = len(img) * scale
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        row = img[y // scale]
        for x in range(size):
            k = row[x // scale]
            raw += bytes((0, 0, 0, 0)) if k is None else bytes((*RGB[k], 255))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    big, little = town(), small()
    still = with_clouds(big.render([m[0] for m in TOWN_BOATS + TOWN_WALKERS]), TOWN_CLOUDS)
    icon = little.render()
    for folder in ("docs/images", "hakoniwa/interface/web"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
        (ROOT / folder / "scene.svg").write_text(scene_svg(big))
        (ROOT / folder / "icon.svg").write_text(svg_open(little.size, "Hakoniwa") + rects(icon) + "</svg>\n")
    (ROOT / "hakoniwa/interface/web/build.svg").write_text(build_svg(big))
    (ROOT / "docs/images/town.png").write_bytes(png(still, 8))
    (ROOT / "docs/images/icon.png").write_bytes(png(icon, 8))
    (ROOT / "hakoniwa/interface/web/favicon.png").write_bytes(png(icon, 2))
    used = sorted({k for row in still for k in row if k is not None})
    print(f"written: town uses {len(used)} of the {len(P)} palette colours, nothing else")
