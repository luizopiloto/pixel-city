"""Draw Pixel City's extra sprites: trees and plants, ground tiles, beach
props, suburb houses and city buildings, in the look of the existing art.

    python3 tools/art.py

A tiny isometric renderer: flat faces (boxes, gable roofs) and blobs
(foliage, rocks) are rasterized in the city's projection (a tile is 128×64,
+u → screen down-right, +v → screen down-left) with a depth buffer, lit from
the upper left, given pixel grain and a soft darker silhouette. Writes PNGs
under assets/art/ and assets/art/manifest.json: per sprite its size, the
ground anchor (world origin, in sprite px) and, for buildings, the footprint
in tiles.
"""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "art"
HW, HH = 64, 32                      # half tile, px
FLOOR = 30                           # px per building floor

# Top faces brightest, +v faces (screen lower-left) lit, +u faces (screen
# lower-right) in shade, as on the existing buildings.
LIGHT = {"top": 1.0, "v": 0.9, "u": 0.74}


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def ramp(*hexes):
    return [rgb(h) for h in hexes]


class Sprite:
    """An RGBA canvas with a depth buffer. World (x, y, z): x, y in tiles
    along u, v; z in px up. (ox, oy) is where the world origin lands."""

    def __init__(self, w, h, ox, oy, seed=1):
        self.w, self.h, self.ox, self.oy = w, h, ox, oy
        self.col = np.zeros((h, w, 3), float)
        self.alpha = np.zeros((h, w), float)
        self.depth = np.full((h, w), -1e9)
        self.rng = np.random.default_rng(seed)
        self.grain = self.rng.random((h, w))

    def proj(self, x, y, z=0.0):
        return self.ox + (x - y) * HW, self.oy + (x + y) * HH - z

    def _write(self, mask, ys, xs, depth, color):
        ys, xs, depth, color = ys[mask], xs[mask], depth[mask], color[mask]
        near = depth >= self.depth[ys, xs] - 1e-6
        ys, xs = ys[near], xs[near]
        self.depth[ys, xs] = depth[near]
        self.col[ys, xs] = color[near]
        self.alpha[ys, xs] = 1.0

    def face(self, o, e1, e2, shader, tri=False, light=1.0):
        """Parallelogram (or triangle o, o+e1, o+e2) in world space. shader(a,
        b, xs, ys) gets face coords a, b in [0, 1) along e1, e2 and the pixel
        coords, and returns N×3 colors."""
        o, e1, e2 = (np.array(v, float) for v in (o, e1, e2))
        so = np.array(self.proj(*o))
        s1 = np.array(self.proj(*(o + e1))) - so
        s2 = np.array(self.proj(*(o + e2))) - so
        det = s1[0] * s2[1] - s1[1] * s2[0]
        if abs(det) < 1e-6:
            return
        corners = [so, so + s1, so + s2, so + s1 + s2]
        x0 = max(0, int(math.floor(min(c[0] for c in corners))))
        x1 = min(self.w, int(math.ceil(max(c[0] for c in corners))) + 1)
        y0 = max(0, int(math.floor(min(c[1] for c in corners))))
        y1 = min(self.h, int(math.ceil(max(c[1] for c in corners))) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        ys, xs = ys.ravel(), xs.ravel()
        px, py = xs + 0.5 - so[0], ys + 0.5 - so[1]
        a = (px * s2[1] - py * s2[0]) / det
        b = (py * s1[0] - px * s1[1]) / det
        inside = (a >= 0) & (b >= 0) & ((a + b <= 1) if tri else ((a < 1) & (b < 1)))
        if not inside.any():
            return
        depth = o[0] + a * e1[0] + b * e2[0] + o[1] + a * e1[1] + b * e2[1]
        color = shader(a, b, xs, ys) * light
        self._write(inside, ys, xs, depth, color)

    def blob(self, c, r, ramp_, squash=1.0, jag=0.0, shade=0.0):
        """Shaded sphere (squash < 1 flattens it) at world point c, screen
        radius r px, lit from the upper left."""
        cx, cy = self.proj(*c)
        x0, x1 = max(0, int(cx - r - 2)), min(self.w, int(cx + r + 3))
        y0, y1 = max(0, int(cy - r * squash - 2)), min(self.h, int(cy + r * squash + 3))
        if x0 >= x1 or y0 >= y1:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        ys, xs = ys.ravel(), xs.ravel()
        dx = (xs + 0.5 - cx) / r
        dy = (ys + 0.5 - cy) / (r * squash)
        d2 = dx * dx + dy * dy
        inside = d2 <= 1.0 - jag * self.grain[ys, xs]
        nz = np.sqrt(np.clip(1 - d2, 0, 1))
        lit = -0.55 * dx - 0.6 * dy + 0.6 * nz + shade + (self.grain[ys, xs] - 0.5) * 0.35
        idx = np.clip(((lit + 0.55) / 1.45 * len(ramp_)).astype(int), 0, len(ramp_) - 1)
        self._write(inside, ys, xs, c[0] + c[1] + nz * r / 64.0, np.array(ramp_)[idx])

    def line(self, p0, p1, color, depth):
        """1-px line in screen space (p0, p1 in px), depth-tested."""
        (x0, y0), (x1, y1) = p0, p1
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.round(np.linspace(x0, x1, n)).astype(int)
        ys = np.round(np.linspace(y0, y1, n)).astype(int)
        ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        xs, ys = xs[ok], ys[ok]
        if not len(xs):
            return
        col = np.repeat(np.asarray(color, float)[None], len(xs), 0)
        self._write(np.ones(len(xs), bool), ys, xs, np.full(len(xs), depth), col)

    def tri2d(self, p0, p1, p2, color, depth):
        """Filled screen-space triangle (px), one color, depth-tested."""
        xs_ = [p0[0], p1[0], p2[0]]
        ys_ = [p0[1], p1[1], p2[1]]
        x0, x1 = max(0, int(min(xs_))), min(self.w, int(max(xs_)) + 1)
        y0, y1 = max(0, int(min(ys_))), min(self.h, int(max(ys_)) + 1)
        if x0 >= x1 or y0 >= y1:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        ys, xs = ys.ravel(), xs.ravel()
        px, py = xs + 0.5, ys + 0.5

        def edge(a, b):
            return (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
        e0, e1, e2 = edge(p0, p1), edge(p1, p2), edge(p2, p0)
        inside = ((e0 >= 0) & (e1 >= 0) & (e2 >= 0)) | ((e0 <= 0) & (e1 <= 0) & (e2 <= 0))
        col = np.repeat(np.asarray(color, float)[None], len(xs), 0)
        self._write(inside, ys, xs, np.full(len(xs), depth), col)

    def box(self, x0, y0, z0, sx, sy, sz, top, wall_v, wall_u):
        """Axis-aligned box: shaders for its +u face, +v face and top."""
        if sz > 0:
            self.face((x0 + sx, y0, z0), (0, sy, 0), (0, 0, sz), wall_u, light=LIGHT["u"])
            self.face((x0, y0 + sy, z0), (sx, 0, 0), (0, 0, sz), wall_v, light=LIGHT["v"])
        self.face((x0, y0, z0 + sz), (sx, 0, 0), (0, sy, 0), top, light=LIGHT["top"])

    def shadow(self, c, rx, ry, k=0.28):
        """Soft translucent ground shadow (an ellipse in screen space) under
        whatever is already drawn; only fills empty pixels."""
        cx, cy = self.proj(*c)
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        d = ((xs + 0.5 - cx) / rx) ** 2 + ((ys + 0.5 - cy) / ry) ** 2
        m = (d <= 1) & (self.alpha == 0)
        self.col[m] = rgb("#14160c")
        self.alpha[m] = k

    def outline(self, k=0.62):
        """Darken the silhouette's edge pixels: a soft outline, not black."""
        a = self.alpha >= 1
        pad = np.pad(a, 1)
        hole = ~pad[:-2, 1:-1] | ~pad[2:, 1:-1] | ~pad[1:-1, :-2] | ~pad[1:-1, 2:]
        self.col[a & hole] *= k

    def image(self):
        out = np.zeros((self.h, self.w, 4), np.uint8)
        out[..., :3] = np.clip(self.col, 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(self.alpha * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(out, "RGBA")


# ---------- shaders ----------

def flat(s, color, grain=6.0):
    c = rgb(color) if isinstance(color, str) else color

    def shader(a, b, xs, ys):
        return c + (s.grain[ys, xs] - 0.5)[:, None] * grain
    return shader


def banded(s, ramp_, bands, axis=1, grain=5.0):
    """Stripes across the face (roof tiles, planks, awnings): `bands` stripes
    along face axis a (0) or b (1), cycling through the ramp."""
    r = np.array(ramp_)

    def shader(a, b, xs, ys):
        t = a if axis == 0 else b
        return r[np.floor(t * bands).astype(int) % len(r)] + (s.grain[ys, xs] - 0.5)[:, None] * grain
    return shader


# ---------- palettes (muted, like the existing sprites) ----------

LEAF = {
    "green": ramp("#222d16", "#2b3a1c", "#364822", "#425628", "#50652f", "#607538"),
    "deep": ramp("#18231a", "#1f2e20", "#283a26", "#31462d", "#3b5335", "#48613e"),
    "olive": ramp("#2c2e12", "#383b16", "#46491b", "#555920", "#656a27", "#777c30"),
    "autumn": ramp("#40241a", "#52301e", "#653e24", "#784d2b", "#8a5c33", "#9b6c3d"),
    "gold": ramp("#453515", "#57441a", "#6a5420", "#7d6527", "#8f762f", "#a08739"),
    "pine": ramp("#132019", "#19291e", "#203324", "#283e2b", "#314a32", "#3b573a"),
    "palm": ramp("#1f2a14", "#29371a", "#344520", "#405426", "#4d632d", "#5b7335"),
}
BARK = ramp("#2a1c14", "#38261b", "#473122", "#573d2b")
PALM_BARK = ramp("#3a2c1e", "#4a3826", "#5b4630", "#6b553a")
ROCK = ramp("#3a3836", "#4a4744", "#5b5753", "#6c6762", "#7d7771", "#8d8680")
FLOWERS = [rgb(h) for h in ("#b9a45c", "#a8676a", "#c7bba0", "#8f6f9a", "#b57a4a")]

WOOD = "#4b3931"
TRIM = "#6c3434"
GLASS = ramp("#356667", "#416b6c", "#467a7b", "#518081")


# ---------- nature ----------

def trunk(s, h, w=0.035):
    s.box(-w, -w, 0, 2 * w, 2 * w, h, flat(s, BARK[3]), flat(s, BARK[2]), flat(s, BARK[1]))


LEAF_SHAPES = [((0, 0), (1, 0)), ((0, 0), (0, 1)), ((0, 0), (1, 1)), ((0, 0), (1, 0), (1, 1)),
               ((0, 0), (-1, 1), (0, 1)), ((0, 0), (1, 0), (0, 1), (1, 1)), ((0, 0), (1, 0), (2, 1))]


def ramp_index(pal, col):
    """Index of the ramp color nearest to col."""
    return int(np.argmin(((pal - col) ** 2).sum(1)))


def leaf_texture(s, rng, mask, pal, cx, cy, r, density=0.2):
    """Leaf marks over a foliage mask. Each mark is one ramp step lighter
    (upper-left of the crown) or darker (lower-right) than the pixel under
    it, so clumps keep their own shading; marks on the edge spill past it
    for a leafy silhouette."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return
    pal = np.array(pal)
    for i in rng.choice(len(xs), int(len(xs) * density)):
        x, y = xs[i], ys[i]
        dx, dy = (x - cx) / r, (y - cy) / r
        lit = -0.6 * dx - 0.75 * dy + (rng.random() - 0.5) * 1.0
        k = ramp_index(pal, s.col[y, x])
        step = (2 if lit > 0.7 else 1) if lit > -0.1 else (-2 if lit < -0.9 else -1)
        k = int(np.clip(k + step, 0, len(pal) - 1))
        d = s.depth[y, x] + 0.002
        for ox, oy in LEAF_SHAPES[rng.integers(len(LEAF_SHAPES))]:
            px, py = x + ox, y + oy
            if 0 <= px < s.w and 0 <= py < s.h and (mask[py, px] or s.alpha[py, px] == 0):
                s.col[py, px] = pal[k]
                s.depth[py, px] = max(s.depth[py, px], d)
                s.alpha[py, px] = 1.0


def crown(s, rng, center, radius, leaf, count, size=1.0, flatness=0.8):
    """Clumpy foliage: shaded clusters in an ellipsoid, then leaf marks."""
    before = s.depth.copy()
    pts = []
    while len(pts) < count:
        p = rng.uniform(-1, 1, 3)
        if (p ** 2).sum() <= 1:
            pts.append(p)
    pts.sort(key=lambda p: p[0] + p[1] + p[2] * 0.3)          # back to front
    for p in pts:
        c = (center[0] + p[0] * radius / 90, center[1] + p[1] * radius / 90, center[2] + p[2] * radius * flatness)
        s.blob(c, (6 + rng.random() * 5) * size, LEAF[leaf], jag=0.1,
               shade=0.22 * (p[2] - 0.3 * (p[0] - p[1])) - 0.05)
    mask = s.depth != before
    cx, cy = s.proj(*center)
    leaf_texture(s, rng, mask, LEAF[leaf], cx, cy - radius * 0.1, radius * 1.05)


def round_tree(leaf="green", size=1.0, seed=1):
    """Deciduous tree: slim trunk and a clumpy crown."""
    s = Sprite(int(90 * size) + 8, int(118 * size) + 8, int(45 * size) + 4, int(108 * size), seed)
    rng = np.random.default_rng(seed)
    th = 24 * size
    trunk(s, th + 14 * size, 0.03 * size + 0.01)
    crown(s, rng, (0, 0, th + 30 * size), 30 * size, leaf, int(44 * size), size)
    s.outline()
    s.shadow((0.05, 0.05, 0), 26 * size, 10 * size)
    return s


def pine_tree(size=1.0, seed=1):
    """Conifer: short trunk and five triangular tiers, each with a sawtooth
    lower edge of hanging bough tips, lit from the left; needle texture."""
    s = Sprite(int(64 * size) + 8, int(132 * size) + 8, int(32 * size) + 4, int(124 * size), seed)
    rng = np.random.default_rng(seed)
    trunk(s, 22 * size, 0.03 * size + 0.01)
    pal = np.array(LEAF["pine"])
    cx, by = s.proj(0, 0, 0)
    tiers = 5
    for k in range(tiers):                               # bottom tier first, upper ones in front
        ybot = by - (16 + k * 19) * size
        ytop = ybot - (31 - k * 2.5) * size
        W = (26 - k * 4.3) * size
        tooth = int(rng.integers(0, 3))
        for y in range(int(ytop), int(ybot) + 4):
            t = min(1.0, max(0.0, (y - ytop) / (ybot - ytop)))
            hw = W * t ** 0.85 + 1
            xs = np.arange(int(cx - hw), int(cx + hw) + 1)
            if y > ybot:                                  # sawtooth tips below the tier
                xs = xs[((xs + tooth) // 3) % 2 == 0]
                xs = xs[np.abs(xs - cx) < hw - (y - ybot) * 1.5]
            if not len(xs):
                continue
            u = (xs - cx) / max(hw, 1)
            lit = -0.75 * u + 0.55 * (1 - t) - 0.25 + (rng.random(len(xs)) - 0.5) * 0.45
            idx = np.clip(((lit + 1.1) / 2.2 * len(pal)).astype(int), 0, len(pal) - 1)
            idx = np.where(y > ybot, np.maximum(idx - 1, 0), idx)
            ys = np.full(len(xs), y)
            ok = (xs >= 0) & (xs < s.w) & (y >= 0) & (y < s.h)
            s._write(ok, ys, xs, np.full(len(xs), 0.2 + k * 0.01), pal[idx])
    tip = by - (16 + (tiers - 1) * 19 + 31 - (tiers - 1) * 2.5) * size
    for d in range(int(4 * size)):                        # pointed top
        s._write(np.array([True]), np.array([int(tip) - d]), np.array([int(cx)]), np.array([0.3]), pal[[4]])
    needles(s, rng, s.depth >= 0.2, LEAF["pine"], trunk_x=cx, top=tip - 6, bottom=by - 10 * size)
    s.outline()
    s.shadow((0.05, 0.05, 0), 22 * size, 9 * size)
    return s


def needles(s, rng, mask, pal, trunk_x, top, bottom, density=0.14):
    """Conifer boughs: light needle strokes on the lit side of each tier,
    angled down and away from the trunk, and darker branch tips drooping
    from each tier's bottom edge."""
    pal = np.array(pal)
    rows = np.arange(s.h)[:, None]
    band = mask & (rows > top) & (rows < bottom)
    ys, xs = np.nonzero(band)
    if not len(xs):
        return
    span = max(1.0, bottom - top)
    snapshot = s.col.copy()

    def stroke(x, y, side, n, k, drop):
        d = s.depth[y, x] + 0.002
        for j in range(n):
            px, py = x + side * j, y + (j + 1) // 2 * drop
            if 0 <= px < s.w and 0 <= py < s.h and (mask[py, px] or s.alpha[py, px] == 0):
                s.col[py, px] = pal[k]
                s.depth[py, px] = max(s.depth[py, px], d)
                s.alpha[py, px] = 1.0
    for i in rng.choice(len(xs), int(len(xs) * density)):
        x, y = xs[i], ys[i]
        side = 1 if x >= trunk_x else -1
        lit = -0.8 * (x - trunk_x) / (span * 0.35) + (rng.random() - 0.5) * 0.9
        k = ramp_index(pal, snapshot[y, x]) + ((2 if lit > 0.6 else 1) if lit > -0.15 else -1)
        stroke(x, y, side, int(rng.integers(2, 4)), int(np.clip(k, 0, len(pal) - 1)), 1)
    # Branch tips under each tier: bottom-edge pixels of the foliage.
    below = np.zeros_like(mask)
    below[:-1] = mask[1:]
    edge = band & ~below
    ys, xs = np.nonzero(edge)
    for i in range(len(xs)):
        if rng.random() < 0.8:
            x, y = xs[i], ys[i]
            side = 1 if x >= trunk_x else -1
            k = int(np.clip(ramp_index(pal, snapshot[y, x]) - 1, 0, len(pal) - 1))
            stroke(x, y, side, int(rng.integers(3, 6)), k, 1)


def palm_tree(size=1.0, seed=1, lean=1):
    """Palm: a curved ringed trunk, a coconut cluster and pinnate fronds:
    each an arching, drooping midrib with thin tapering leaflets on both
    sides, lit from the upper left; two dry fronds hang below."""
    s = Sprite(int(130 * size) + 8, int(140 * size) + 8, int(65 * size) + 4, int(132 * size), seed)
    rng = np.random.default_rng(seed)
    top = (0, 0, 0)
    for k in range(30):
        t = k / 29
        x = lean * 0.14 * t * t * size
        top = (x, -x * 0.3, t * 90 * size)
        s.blob(top, (5.2 - 1.4 * t) * size, PALM_BARK, squash=0.75, shade=0.15 if k % 3 else -0.25)
    s.outline()
    leaf = LEAF["palm"]
    dry = ramp("#4a3a22", "#5e4a2a", "#735c34", "#86703e")

    def frond(ang, reach, rise, droop, pal, dim=0.0):
        """A feather: midrib arching out then down, leaflets angled toward
        the tip filling a tapered blade with a serrated edge."""
        ca, sa = math.cos(ang), math.sin(ang)
        spine = []
        for i in range(21):
            t = i / 20
            d = reach * t
            w = (top[0] + ca * d / 90, top[1] + sa * d / 90,
                 top[2] + rise * math.sin(math.pi * t * 0.8) - droop * t ** 2.2)
            spine.append((np.array(s.proj(*w)), w[0] + w[1] + 0.02, t))
        side_tips = {-1: [], 1: []}
        for i, (p, dep, t) in enumerate(spine):
            q = spine[min(i + 1, 20)][0] - spine[max(i - 1, 0)][0]
            q = q / (np.hypot(*q) or 1)
            L = size * 7.5 * math.sin(math.pi * min(1.0, 0.1 + t * 0.95)) ** 0.8
            L *= 0.8 if i % 2 else 1.0                                   # serration
            for sd in (-1, 1):
                n = np.array([-q[1] * sd, q[0] * sd])
                tip = p + n * L + q * L * 0.45 + np.array([0, L * 0.3])  # toward the tip, a little droop
                side_tips[sd].append(tip)
        for sd in (-1, 1):
            n_up = -0.6 * (-side_tips[sd][10][0] + spine[10][0][0]) - 0.8 * (-side_tips[sd][10][1] + spine[10][0][1])
            lit = 2.0 + (1.6 if n_up < 0 else 0.0) - dim * 4 + 0.6 * (-(ca + sa) * 0.5)
            base = pal[int(np.clip(lit, 0, len(pal) - 1))]
            vein = pal[int(np.clip(lit - 1, 0, len(pal) - 1))]
            for i in range(1, 21):
                (p0, d0, _), (p1, d1, _) = spine[i - 1], spine[i]
                l0, l1 = side_tips[sd][i - 1], side_tips[sd][i]
                s.tri2d(p0, p1, l1, base, d1)
                s.tri2d(p0, l0, l1, base, d1)
                if i % 2 == 0:
                    s.line(p1, l1, vein, d1 + 0.001)                       # leaflet separation
        for i in range(1, 21):
            (p0, d0, _), (p1, d1, _) = spine[i - 1], spine[i]
            s.line(p0, p1, np.minimum(pal[-1] * 1.18 + np.array([12, 10, 0]), 255) * (1 - dim * 0.6),
                   d1 + 0.002)                                               # midrib, yellow-green

    # Dry fronds hanging under the crown, then the coconuts, then the crown.
    for ang in (rng.uniform(0, math.tau), rng.uniform(0, math.tau)):
        frond(ang, 22 * size, 0, 30 * size, dry, 0.1)
    for k in range(4):
        a_ = k / 4 * math.tau + 0.5
        s.blob((top[0] + math.cos(a_) * 0.03, top[1] + math.sin(a_) * 0.03, top[2] - 4 * size), 2.6 * size,
               ramp("#3a2a18", "#4f3a22", "#654a2c", "#7a5c36"))
    n = 8
    order = sorted(((j / n * math.tau + rng.uniform(-0.25, 0.25)) for j in range(n)),
                   key=lambda a_: math.cos(a_) + math.sin(a_))          # back to front
    for ang in order:
        back = math.cos(ang) + math.sin(ang) < -0.3
        frond(ang, rng.uniform(40, 48) * size, rng.uniform(7, 11) * size, rng.uniform(18, 26) * size,
              leaf, 0.12 if back else 0.0)
    s.blob(top, 4.5 * size, leaf, shade=0.1)
    s.shadow((0.08, 0.05, 0), 30 * size, 11 * size)
    return s


def bush(leaf="green", size=1.0, seed=1, flowers=False):
    s = Sprite(int(60 * size) + 8, int(46 * size) + 8, int(30 * size) + 4, int(40 * size), seed)
    rng = np.random.default_rng(seed)
    crown(s, rng, (0, 0, 12 * size), 17 * size, leaf, int(16 * size) + 6, size * 0.9, 0.6)
    if flowers:
        for _ in range(int(18 * size)):
            x = int(s.ox + rng.integers(-16, 16) * size)
            y = int(s.oy - rng.integers(6, 26) * size)
            if s.alpha[y, x] >= 1:
                s.col[y, x] = FLOWERS[rng.integers(len(FLOWERS))]
    s.outline()
    s.shadow((0.04, 0.04, 0), 18 * size, 7 * size)
    return s


def hedge(length=1.0, seed=1):
    """Trimmed hedge along u."""
    s = Sprite(int(64 * length) + 60, int(32 * length) + 60, 30, 34, seed)
    leafy = lambda k: (lambda a, b, xs, ys: np.array(LEAF["deep"])[np.clip(
        (k * 5 + (s.grain[ys, xs] - 0.5) * 3).astype(int), 0, 5)])
    s.box(0, 0, 0, length, 0.18, 16, leafy(0.9), leafy(0.75), leafy(0.55))
    s.outline()
    return s


def rocks(seed=1, size=1.0):
    s = Sprite(int(56 * size) + 8, int(40 * size) + 8, int(28 * size) + 4, int(34 * size), seed)
    rng = np.random.default_rng(seed)
    for _ in range(3):
        c = (rng.uniform(-0.1, 0.1) * size, rng.uniform(-0.1, 0.1) * size, 4 * size)
        s.blob(c, rng.uniform(7, 13) * size, ROCK, squash=0.7, jag=0.12)
    s.outline()
    s.shadow((0.03, 0.03, 0), 18 * size, 6 * size)
    return s


def flower_bed(seed=1, rx=0.22, ry=0.15):
    """Small rounded bed: a low stone rim around soil, packed with leaves and
    flowers. rx, ry: half-size in tiles along u, v."""
    s = Sprite(80, 50, 40, 22, seed)
    rng = np.random.default_rng(seed)
    n, rim = 20, 3
    ring = [(rx * math.cos(2 * math.pi * k / n), ry * math.sin(2 * math.pi * k / n)) for k in range(n)]
    stone = rgb("#9c9284")
    for k in range(n):                                          # rim wall, lit by its facing
        (xa, ya), (xb, yb) = ring[k], ring[(k + 1) % n]
        t = 2 * math.pi * (k + 0.5) / n
        light = 0.62 + 0.3 * max(0.0, 0.45 * math.cos(t) + 0.9 * math.sin(t))
        s.face((xa, ya, 0), (xb - xa, yb - ya, 0), (0, 0, rim), flat(s, stone, 6), light=light)
    for k in range(n):                                          # rim top, then soil inset
        (xa, ya), (xb, yb) = ring[k], ring[(k + 1) % n]
        s.face((0, 0, rim), (xa, ya, 0), (xb, yb, 0), flat(s, stone * 1.12, 5), tri=True)
    for k in range(n):
        (xa, ya), (xb, yb) = ring[k], ring[(k + 1) % n]
        s.face((0, 0, rim), (xa * 0.8, ya * 0.8, 0), (xb * 0.8, yb * 0.8, 0), flat(s, "#3e2c22", 10), tri=True)

    def spot():
        while True:
            x, y = rng.uniform(-0.75, 0.75, 2)
            if x * x + y * y < 0.5:
                return x * rx, y * ry
    for _ in range(26):
        x, y = spot()
        s.blob((x, y, rim + 2), rng.uniform(1.8, 2.6), LEAF["green"], shade=0.1)
    for _ in range(26):
        x, y = spot()
        c = FLOWERS[rng.integers(len(FLOWERS))]
        s.blob((x, y, rim + 3), 1.3, [c * 0.8, c, np.minimum(c * 1.2, 255)])
    s.outline()
    return s


# ---------- ground tiles ----------

TILE_MASK = np.array(Image.open(ROOT / "assets" / "water-tile.png").convert("RGBA"))[..., 3] > 0


def value_noise(h, w, cell, rng):
    """Smooth noise in [0, 1] from a coarse random grid."""
    gh, gw = h // cell + 2, w // cell + 2
    g = rng.random((gh, gw))
    ys, xs = np.mgrid[0:h, 0:w] / cell
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = ys - y0, xs - x0
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    top = g[y0, x0] * (1 - fx) + g[y0, x0 + 1] * fx
    bot = g[y0 + 1, x0] * (1 - fx) + g[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bot * fy


def tile_image(col):
    h, w = TILE_MASK.shape
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
    out[..., 3] = np.where(TILE_MASK, 255, 0)
    return Image.fromarray(out, "RGBA")


def uv_of_tile():
    """Tile coords (u, v) in [0, 1] for each pixel of a 128×65 tile."""
    h, w = TILE_MASK.shape
    ys, xs = np.mgrid[0:h, 0:w]
    px, py = xs + 0.5 - 64, ys + 0.5
    return (py / 32 + px / 64) / 2, (py / 32 - px / 64) / 2


def ground(base, dark, light, seed, tufts=0, dots=None, patches=None):
    h, w = TILE_MASK.shape
    rng = np.random.default_rng(seed)
    n = value_noise(h, w, 9, rng) * 0.6 + value_noise(h, w, 4, rng) * 0.4
    col = np.where((n < 0.38)[..., None], rgb(dark), rgb(base))
    col = np.where((n > 0.66)[..., None], rgb(light), col)
    if patches:
        p = value_noise(h, w, 14, rng)
        col = np.where((p > 0.62)[..., None], rgb(patches), col)
    grain = rng.random((h, w))
    col = col + (grain - 0.5)[..., None] * 5
    for _ in range(tufts):                      # short vertical grass strokes
        x, y = rng.integers(4, w - 4), rng.integers(3, h - 3)
        if TILE_MASK[y, x] and TILE_MASK[y - 2, x]:
            col[y, x] = rgb(light) * 1.08
            col[y - 1, x] = rgb(light) * 1.15
            col[y, x + 1] = rgb(dark)
    for _ in range(len(dots or []) and 26):     # flowers
        x, y = rng.integers(4, w - 4), rng.integers(3, h - 3)
        if TILE_MASK[y, x]:
            col[y, x] = rgb(dots[rng.integers(len(dots))])
    return tile_image(col)


GRASS = dict(base="#545e10", dark="#4c560f", light="#5d6814")
SAND = dict(base="#9c8660", dark="#957f5a", light="#a38c66")
WATER = ramp("#216a78", "#227383", "#2f8191", "#3e92a2")


def shore(sides, corners=(), seed=1):
    """Water tile with sand on the given sides (n = -u, e = -v, s = +u,
    w = +v, as in the road keys) and outer corners ('ne', 'es', 'sw', 'wn':
    land only diagonally)."""
    h, w = TILE_MASK.shape
    rng = np.random.default_rng(seed)
    u, v = uv_of_tile()
    wobble = (value_noise(h, w, 6, rng) - 0.5) * 0.06
    d = np.full((h, w), 9.0)
    side = {"n": u, "s": 1 - u, "e": v, "w": 1 - v}
    for k in sides:
        d = np.minimum(d, side[k])
    corner = {"ne": (0, 0), "es": (1, 0), "sw": (1, 1), "wn": (0, 1)}
    for k in corners:
        cu, cv = corner[k]
        d = np.minimum(d, np.hypot(u - cu, v - cv) - 0.02)
    d = d + wobble
    n = value_noise(h, w, 5, rng)
    water = np.array(WATER)[np.clip((n * 2.2).astype(int), 0, 1)]
    col = water.copy()
    col[d < 0.42] = np.array(WATER)[2]                                 # shallows
    col[d < 0.3] = rgb("#7fa6a0")                                     # foam
    col[d < 0.27] = rgb("#7a684a")                                    # wet sand
    col[d < 0.23] = np.where((n[d < 0.23] > 0.55)[:, None], rgb(SAND["light"]), rgb(SAND["base"]))
    col = col + (rng.random((h, w)) - 0.5)[..., None] * 5
    return tile_image(col)


# ---------- buildings ----------

def wall_shader(s, color, length_px, height_px, floors, windows, door=None, base=None,
                siding="plain", frame=TRIM, stripes=None, glass_door=False, storefront=None,
                window_style="square", floor_h=FLOOR, glass_pal=None, ground_windows=True):
    """A wall: siding texture, floor trims, corner trims, windows (list of
    (a0, a1) spans along the wall, repeated per floor), optional door span
    (a0, a1) on the ground floor, optional base band color."""
    c = rgb(color)
    frame_c = rgb(frame)

    def shader(a, b, xs, ys):
        g = (s.grain[ys, xs] - 0.5)[:, None]
        z = b * height_px
        along = a * length_px
        out = np.repeat(c[None], len(a), 0)
        if siding == "boards":
            out = out * (1 - 0.06 * ((np.floor(along / 3) % 2)[:, None]))
        elif siding == "brick":
            row = np.floor(z / 3)
            off = (row % 2) * 3
            mortar = (np.mod(z, 3) < 0.9) | (np.mod(along + off, 6) < 0.9)
            out = np.where(mortar[:, None], out * 1.18, out * (0.95 + 0.1 * g))
        elif siding == "glass":
            pane = (np.mod(along, 10) < 1.2) | (np.mod(z, floor_h / 2) < 1.2)
            glass = np.array(GLASS)[((xs + ys) // 3 % 4)]
            out = np.where(pane[:, None], out, glass * 0.95)
        if stripes is not None:
            out = np.where((np.floor(along / 5) % 2 == 0)[:, None], rgb(stripes), out)
        out = out + g * 7
        # Windows, per floor (a storefront replaces the ground floor's).
        first = 0 if storefront is None and ground_windows else 1
        for f in range(first, floors if window_style == "square" else 0):
            z0 = f * floor_h + 10
            for a0, a1 in windows:
                inw = (along >= a0 * length_px) & (along < a1 * length_px) & (z >= z0) & (z < z0 + 13)
                if f == 0 and door is not None and a0 < door[1] and a1 > door[0]:
                    continue
                edge = inw & ((along < a0 * length_px + 1) | (along >= a1 * length_px - 1) | (z < z0 + 1) | (z >= z0 + 12))
                glass = np.array(GLASS)[np.where((xs + ys) % 7 < 2, 3, (xs // 2 + ys) % 3)]
                out = np.where(inw[:, None], glass, out)
                out = np.where(edge[:, None], frame_c, out)
                sill = (along >= a0 * length_px - 1) & (along < a1 * length_px + 1) & (z >= z0 - 2) & (z < z0)
                out = np.where(sill[:, None], c * 1.18, out)
        if window_style == "arched":
            # Old-style windows: round arch on top, a cross dividing four
            # panes, cream frame, stone ring around the arch, stone sill.
            stone = rgb("#c9bfae")
            for f in range(first, floors):
                z0 = f * floor_h + 7
                zr = z0 + 12                                     # arch springs here
                for a0, a1 in windows:
                    if f == 0 and door is not None and a0 < door[1] and a1 > door[0]:
                        continue
                    p0, p1 = a0 * length_px, a1 * length_px
                    cx, hw = (p0 + p1) / 2, min((p1 - p0) / 2, 5.5)   # arch fits the floor
                    dx, dz = along - cx, z - zr
                    inw = ((np.abs(dx) < hw) & (z >= z0) & (z < zr)) | ((z >= zr) & (dx * dx + dz * dz < hw * hw))
                    inner = ((np.abs(dx) < hw - 1) & (z >= z0 + 1) & (z < zr)) | \
                            ((z >= zr) & (dx * dx + dz * dz < (hw - 1) ** 2))
                    ring = (z >= zr - 0.5) & (dx * dx + dz * dz < (hw + 1.4) ** 2) & ~inw
                    zmid = (z0 + zr + hw) / 2
                    mull = inner & ((np.abs(dx) < 0.6) | (np.abs(z - zmid) < 0.55))
                    pal = np.array(glass_pal if glass_pal is not None else GLASS)
                    glass = pal[np.where((xs + ys) % 7 < 2, 3, (xs // 2 + ys) % len(pal) % 3)] if glass_pal is None \
                        else pal[(np.floor(along / 2) + np.floor(z / 3)).astype(int) % len(pal)]
                    out = np.where(inw[:, None], frame_c, out)
                    out = np.where(inner[:, None], glass, out)
                    out = np.where(mull[:, None], frame_c, out)
                    out = np.where(ring[:, None], stone, out)
                    sill = (np.abs(dx) < hw + 1) & (z >= z0 - 2) & (z < z0)
                    out = np.where(sill[:, None], stone * 0.95, out)
        if storefront is not None:
            # Big display windows either side of the door, and a sign band.
            spans = [(0.06, door[0] - 0.05), (door[1] + 0.05, 0.94)] if door else [(0.07, 0.93)]
            for a0, a1 in spans:
                p0, p1 = a0 * length_px, a1 * length_px
                inw = (along >= p0) & (along < p1) & (z >= 3) & (z < 20)
                edge = inw & ((along < p0 + 1) | (along >= p1 - 1) | (z < 4) | (z >= 19) |
                              (np.mod(along - p0, 14) < 0.9))
                sheen = np.mod(along + z * 0.8, 11) < 2
                glass = np.where(sheen[:, None], np.array(GLASS)[3] * 1.1, np.array(GLASS)[1] * 0.9)
                out = np.where(inw[:, None], glass, out)
                out = np.where(edge[:, None], rgb("#2e3336"), out)
            # Sign band just above the tents (which slope down from z 30).
            band = (z >= 31) & (z < 38)
            dots = band & (z >= 33) & (z < 36) & (np.mod(along, 4) < 2) & (along > length_px * 0.3) & (along < length_px * 0.7)
            out = np.where(band[:, None], rgb(storefront), out)
            out = np.where(dots[:, None], rgb("#e0d8c8"), out)
            out = np.where(((z >= 30) & (z < 31) | (z >= 38) & (z < 39))[:, None], rgb(storefront) * 0.7, out)
        if door is not None and glass_door:
            # Double glass door: dark frame, center divider, glass with a
            # diagonal sheen, a little taller than the wooden doors.
            d0, d1 = door[0] * length_px, door[1] * length_px
            ind = (along >= d0 - 1) & (along < d1 + 1) & (z < 24)
            edge = ind & ((along < d0 + 1) | (along >= d1 - 1) | (z >= 22) | (np.abs(along - (d0 + d1) / 2) < 0.8))
            sheen = np.mod(along + z * 0.8, 9) < 2
            glass = np.where(sheen[:, None], np.array(GLASS)[3] * 1.12, np.array(GLASS)[1] * 0.92)
            out = np.where(ind[:, None], glass, out)
            out = np.where(edge[:, None], rgb("#2e3336"), out)
        elif door is not None:
            ind = (along >= door[0] * length_px) & (along < door[1] * length_px) & (z < 19)
            edge = ind & ((along < door[0] * length_px + 1) | (along >= door[1] * length_px - 1) | (z >= 18))
            out = np.where(ind[:, None], rgb(WOOD) * (1 + 0.08 * g), out)
            out = np.where(edge[:, None], frame_c, out)
        if base is not None:
            stone = (z < 5)
            out = np.where(stone[:, None], rgb(base) * (0.9 + 0.25 * (s.grain[ys, xs] > 0.6))[:, None], out)
        for f in range(1, floors):                                   # floor trim
            out = np.where((np.abs(z - f * floor_h) < 1)[:, None], c * 0.78, out)
        corner = (along < 1) | (along > length_px - 1) | (z > height_px - 1.2)
        return np.where(corner[:, None], c * 0.72, out)
    return shader


def gable(s, x0, y0, sx, sy, zw, rh, roof, gable_col, axis="u", over=0.07):
    """Gable roof over a footprint, ridge along `axis`, eaves at zw."""
    r = np.array(roof)

    def tiles(a, b, xs, ys):
        rows = np.floor(b * 9).astype(int)
        shade = np.where(np.mod(b * 9, 1) < 0.22, 0.82, 1.0)
        return r[rows % len(r)] * shade[:, None] + (s.grain[ys, xs] - 0.5)[:, None] * 6

    gc = rgb(gable_col)

    def boards(a, b, xs, ys):
        return gc * (1 - 0.1 * (np.floor(xs / 3) % 2))[:, None] + (s.grain[ys, xs] - 0.5)[:, None] * 5

    if axis == "u":
        ym = y0 + sy / 2
        # back slope, front slope (faces +v), gable end at +u
        s.face((x0 - over, ym, zw + rh), (sx + 2 * over, 0, 0), (0, -(sy / 2 + over), -rh - over * 20), tiles, light=0.8)
        s.face((x0 - over, ym, zw + rh), (sx + 2 * over, 0, 0), (0, sy / 2 + over, -rh - over * 20), tiles, light=LIGHT["v"])
        s.face((x0 + sx, y0, zw), (0, sy, 0), (0, sy / 2, rh), boards, tri=True, light=LIGHT["u"])
    else:
        xm = x0 + sx / 2
        s.face((xm, y0 - over, zw + rh), (0, sy + 2 * over, 0), (-(sx / 2 + over), 0, -rh - over * 20), tiles, light=0.8)
        s.face((xm, y0 - over, zw + rh), (0, sy + 2 * over, 0), (sx / 2 + over, 0, -rh - over * 20), tiles, light=LIGHT["u"])
        s.face((x0, y0 + sy, zw), (sx, 0, 0), (sx / 2, 0, rh), boards, tri=True, light=LIGHT["v"])


def house(seed, a=1.2, b=0.9, floors=1, wall="#a47d6a", roof=None, gable_col="#4f3a30",
          axis="u", garage=False, chimney=True, porch=True, base="#6e5a4c", siding="boards"):
    roof = roof or ramp("#6e4c49", "#734c48", "#835d59", "#7d5550")
    s = Sprite(260, 230, 130, 150, seed)
    x0, y0 = -a / 2, -b / 2
    hgt = floors * FLOOR + 4
    lu, lv = b * math.hypot(HW, HH), a * math.hypot(HW, HH)          # face lengths, px
    win_u = [(0.18, 0.36), (0.62, 0.8)] if b > 0.7 else [(0.38, 0.62)]
    win_v = [(0.12, 0.26), (0.38, 0.52), (0.72, 0.86)] if a > 1.1 else [(0.15, 0.32), (0.68, 0.85)]
    door = (0.56, 0.68) if a > 1.1 else (0.42, 0.56)
    s.box(x0, y0, 0, a, b, hgt, flat(s, wall),
          wall_shader(s, wall, lv, hgt, floors, win_v, door, base, siding),
          wall_shader(s, wall, lu, hgt, floors, win_u, None, base, siding))
    if axis == "u":
        gable(s, x0, y0, a, b, hgt, 22 + 4 * b, roof, gable_col, "u")
    else:
        gable(s, x0, y0, a, b, hgt, 22 + 4 * a, roof, gable_col, "v")
    if chimney:
        cx = x0 + a * 0.22
        s.box(cx, y0 + b * 0.2, hgt + 8, 0.1, 0.1, 22, flat(s, "#5c392d"), flat(s, "#6e4c49"), flat(s, "#4b3931"))
    if porch:
        s.box(x0 + a * (door[0] - 0.06), y0 + b, 0, a * (door[1] - door[0] + 0.12), 0.16, 4,
              flat(s, "#8a6751"), flat(s, "#765743"), flat(s, "#5f4646"))
    if garage:
        gx = x0 + a
        s.box(gx, y0 + 0.05, 0, 0.5, b - 0.05, 22, flat(s, "#5b5a5c"),
              garage_door(s, wall, 0.5 * math.hypot(HW, HH)), wall_shader(s, wall, (b - 0.05) * 71.6, 22, 1, [], None, base, siding))
    s.outline(0.7)
    return s, (a + (0.5 if garage else 0), b)


def garage_door(s, wall, length_px):
    c = rgb(wall)

    def shader(a, b, xs, ys):
        along, z = a * length_px, b * 22
        door = (along > 4) & (along < length_px - 4) & (z < 17)
        slat = np.where(np.mod(z, 3) < 1, 0.85, 1.0)
        out = np.where(door[:, None], rgb("#b3afa8") * slat[:, None], c)
        corner = (along < 1) | (along > length_px - 1) | (z > 21)
        return np.where(corner[:, None], c * 0.72, out) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    return shader


def flat_roof(s, x0, y0, sx, sy, z, color, units=2, rng=None):
    """Flat roof with a parapet rim and AC units."""
    c = rgb(color)

    def roofsh(a, b, xs, ys):
        rim = (a < 0.04) | (a > 0.96) | (b < 0.06) | (b > 0.94)
        return np.where(rim[:, None], c * 1.15, c) + (s.grain[ys, xs] - 0.5)[:, None] * 5
    s.face((x0, y0, z), (sx, 0, 0), (0, sy, 0), roofsh)
    rng = rng or np.random.default_rng(1)
    placed = []
    for _ in range(60):                              # units never overlap
        if len(placed) == units:
            break
        ux, uy = x0 + sx * rng.uniform(0.12, 0.72), y0 + sy * rng.uniform(0.12, 0.66)
        if all(abs(ux - px) > 0.22 or abs(uy - py) > 0.22 for px, py in placed):
            placed.append((ux, uy))
    for ux, uy in sorted(placed, key=lambda p: p[0] + p[1]):
        s.box(ux, uy, z, 0.16, 0.16, 7, fan_top(s), flat(s, "#9791a2"), flat(s, "#716f74"))


def fan_top(s):
    def shader(a, b, xs, ys):
        d = np.hypot(a - 0.5, b - 0.5)
        return np.where((d < 0.32)[:, None], rgb("#434343"), rgb("#b3afbd")) + (s.grain[ys, xs] - 0.5)[:, None] * 5
    return shader


def building(seed, kind="apartment", a=1.4, b=1.0, floors=4, wall="#a47d6a", mart=False,
             canopy=False):
    rng = np.random.default_rng(seed)
    s = Sprite(300, 380, 150, 290, seed)
    x0, y0 = -a / 2, -b / 2
    fh = 34 if kind == "brick" else FLOOR               # taller floors fit arched windows
    hgt = floors * fh + 4
    lu, lv = b * 71.6, a * 71.6
    siding = {"apartment": "plain", "brick": "brick", "office": "glass", "shop": "plain"}[kind]
    nwin_v = max(2, int(a * 3))
    nwin_u = max(2, int(b * 3))
    win = lambda n: [((i + 0.28) / n, (i + 0.72) / n) for i in range(n)]
    door = (0.38, 0.62) if kind == "office" else (0.45, 0.55)
    sign = "#3d6a3e" if mart else None
    style = "arched" if kind == "brick" else "square"
    wv = wall_shader(s, wall, lv, hgt, floors, [] if kind == "office" else win(nwin_v), door, None, siding,
                     frame="#e0d8c8" if kind == "brick" else TRIM, glass_door=kind == "office" or mart or canopy,
                     storefront=sign, window_style=style, floor_h=fh)
    wu = wall_shader(s, wall, lu, hgt, floors, [] if kind == "office" else win(nwin_u), None, None, siding,
                     frame="#e0d8c8" if kind == "brick" else TRIM, storefront=sign, window_style=style, floor_h=fh)
    s.box(x0, y0, 0, a, b, hgt, flat(s, wall), wv, wu)
    if kind == "shop":
        awning(s, x0, y0 + b, a, 22, rng.choice(["#8a4a3e", "#3f6f73", "#6a6a2c"]))
    if mart:
        market(s, x0, y0, a, b, door, rng)
    if canopy:
        entrance_canopy(s, x0 + a * (door[0] + door[1]) / 2, y0 + b)
    if kind == "brick":                                   # cornice, then the roof on it
        s.box(x0 - 0.03, y0 - 0.03, hgt - 3, a + 0.06, b + 0.06, 4, flat(s, "#cfc6b6"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
        flat_roof(s, x0, y0, a, b, hgt + 1, "#5b5a5c", units=2, rng=rng)
    elif kind == "office":
        flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=0, rng=rng)
        helipad(s, x0, y0, a, b, hgt)
    else:
        flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=2 + (floors > 4), rng=rng)
    s.outline(0.7)
    return s, (a, b)


def helipad(s, x0, y0, sx, sy, z):
    """Raised square pad centered on the roof: yellow ring, white H, and
    small lights at its corners."""
    side = min(sx, sy) * 0.8
    px, py = x0 + (sx - side) / 2, y0 + (sy - side) / 2
    ring, mark, deck = rgb("#c9a84a"), rgb("#e0d8c8"), rgb("#47474c")

    def top(a, b, xs, ys):
        d = np.hypot(a - 0.5, b - 0.5)
        h = (((np.abs(a - 0.38) < 0.045) | (np.abs(a - 0.62) < 0.045)) & (np.abs(b - 0.5) < 0.18)) | \
            ((np.abs(b - 0.5) < 0.04) & (np.abs(a - 0.5) < 0.12))
        out = np.where(((d > 0.36) & (d < 0.43))[:, None], ring, deck)
        out = np.where(h[:, None], mark, out)
        edge = (a < 0.03) | (a > 0.97) | (b < 0.03) | (b > 0.97)
        out = np.where(edge[:, None], mark * 0.85, out)
        return out + (s.grain[ys, xs] - 0.5)[:, None] * 5
    s.box(px, py, z, side, side, 3, top, flat(s, "#3a3a3e"), flat(s, "#2e2e32"))
    for cx, cy in ((px, py), (px + side, py), (px, py + side), (px + side, py + side)):
        s.box(cx - 0.02, cy - 0.02, z + 3, 0.04, 0.04, 2, flat(s, "#e0a050"), flat(s, "#c98a40"), flat(s, "#b07a38"))


FRUIT = {
    "apple": ramp("#6e2420", "#8e322a", "#a8433a", "#c25a48"),
    "orange": ramp("#7a4418", "#9a5a20", "#b8702a", "#cf8a3a"),
    "banana": ramp("#7a6a22", "#9a8a2e", "#b8a23c", "#cdb850"),
    "green": ramp("#34461c", "#445c22", "#56702a", "#6c8634"),
    "grape": ramp("#35243e", "#46304f", "#584062", "#6c5276"),
    "lemon": ramp("#8a7a26", "#a8963a", "#c2ae4a", "#d6c464"),
}
CRATE = ("#8a6751", "#765743", "#5f4646")


def produce(s, rng, x, y, z, w, d, kind):
    """A heap of fruit filling a w × d (tiles) area at height z."""
    n = int(w * d * 4200) + 6
    pts = sorted(((rng.uniform(0.08, 0.92) * w, rng.uniform(0.08, 0.92) * d, rng.uniform(0, 2)) for _ in range(n)),
                 key=lambda p: p[0] + p[1] + p[2] * 0.01)
    for px, py, pz in pts:
        s.blob((x + px, y + py, z + 1 + pz), 1.35, FRUIT[kind], shade=0.25)


def crate(s, rng, x, y, z, kind, w=0.15, d=0.11, h=5):
    s.box(x, y, z, w, d, h, flat(s, CRATE[0]), banded(s, [rgb(CRATE[1]), rgb(CRATE[1]) * 0.85], 2, axis=1),
          flat(s, CRATE[2]))
    produce(s, rng, x, y, z + h, w, d, kind)


def basket(s, rng, x, y, kind):
    s.blob((x + 0.05, y + 0.05, 3), 4.2, ramp("#5a4128", "#6e5232", "#86683e", "#9c7c4a"), squash=0.7)
    for _ in range(7):
        s.blob((x + 0.05 + rng.uniform(-0.03, 0.03), y + 0.05 + rng.uniform(-0.03, 0.03), 6), 1.7, FRUIT[kind])


def market(s, x0, y0, a, b, door, rng):
    """Ground-floor market: striped tents over both street faces, fruit
    crates on two-tier stands and baskets on the sidewalk in front."""
    green = "#3d6a3e"
    # Crates along the +v face, leaving the door clear: a back row raised on
    # a low stand, a front row on the ground.
    kinds = ["apple", "orange", "banana", "green", "grape", "lemon"]
    k = 0
    xs = [x0 + 0.05 + i * 0.17 for i in range(int((a - 0.1) / 0.17))]
    door_x0, door_x1 = x0 + door[0] * a - 0.06, x0 + door[1] * a + 0.06
    for cx in xs:
        if cx + 0.15 > door_x0 and cx < door_x1:
            continue
        s.box(cx, y0 + b + 0.01, 0, 0.15, 0.1, 5, flat(s, "#5f4646"), flat(s, "#4b3931"), flat(s, "#3e2f29"))
        crate(s, rng, cx, y0 + b + 0.01, 5, kinds[k % len(kinds)])
        crate(s, rng, cx, y0 + b + 0.12, 0, kinds[(k + 3) % len(kinds)], h=4)
        k += 1
    for cy in [y0 + 0.08 + i * 0.2 for i in range(int((b - 0.1) / 0.2))]:
        crate(s, rng, x0 + a + 0.02, cy, 0, kinds[k % len(kinds)], w=0.11, d=0.15)
        k += 1
    basket(s, rng, door_x1 + 0.02, y0 + b + 0.14, "apple")
    basket(s, rng, door_x0 - 0.12, y0 + b + 0.15, "orange")
    awning(s, x0, y0 + b, a, 22, green, depth=0.3)
    awning_u(s, x0 + a, y0, b, 22, green, depth=0.22)


def entrance_canopy(s, cx, y, width=0.32, depth=0.5, z=25):
    """New York–style entrance: a flat fabric canopy from the door out to the
    curb on brass poles, gold-trimmed valance with a building number, a red
    carpet underneath and lamps beside the door."""
    green, gold, brass = rgb("#2b4636"), rgb("#c9a84a"), ("#b8964a", "#a08238", "#86692c")
    x0 = cx - width / 2
    # Carpet from the door to the curb.
    s.face((cx - 0.07, y, 0.4), (0.14, 0, 0), (0, depth, 0),
           lambda a, b, xs, ys: np.where(((a < 0.08) | (a > 0.92))[:, None], gold * 0.8, rgb("#6e2420"))
           + (s.grain[ys, xs] - 0.5)[:, None] * 6)
    # Poles at the canopy's outer corners.
    for px in (x0 + 0.02, x0 + width - 0.02):
        s.box(px - 0.012, y + depth - 0.04, 0, 0.024, 0.024, z, *(flat(s, c) for c in brass))

    def valance(length_px, number=False):
        def shader(a, b, xs, ys):
            along, zz = a * length_px, b * 5
            out = np.repeat(green[None], len(a), 0)
            out = np.where(((zz < 1) | (zz > 4))[:, None], gold, out)               # trim lines
            if number:
                dots = (zz > 1.8) & (zz < 3.2) & (np.abs(along - length_px / 2) < 4) & (np.mod(along, 2) < 1)
                out = np.where(dots[:, None], gold, out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 5
        return shader

    def top(a, b, xs, ys):
        seams = np.mod(a * width * HW, 6) < 1
        return np.where(seams[:, None], green * 0.8, green * 1.1) + (s.grain[ys, xs] - 0.5)[:, None] * 5
    s.box(x0, y, z, width, depth, 5, top, valance(width * 71.6, number=True), valance(depth * 71.6))
    # Lamps either side of the door.
    for lx in (cx - 0.12, cx + 0.12):
        s.blob((lx, y + 0.02, 17), 2.2, ramp("#8a6a2e", "#c9a84a", "#f2c06a", "#f8dc98"), shade=0.3)


def awning_u(s, x, y0, length, z, color, depth=0.22):
    """Striped awning sloping out from the +u wall."""
    c = rgb(color)

    def stripes(a_, b_, xs, ys):
        on = (np.floor(a_ * length * 71.6 / 5) % 2 == 0)
        return np.where(on[:, None], c, rgb("#d8ccb4")) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    s.face((x, y0 + 0.05, z + 8), (0, length - 0.1, 0), (depth, 0, -8), stripes, light=LIGHT["u"])
    s.face((x + depth, y0 + 0.05, z), (0, length - 0.1, 0), (0, 0, 4), stripes, light=LIGHT["u"] * 0.9)


def awning(s, x0, y, length, z, color, depth=0.22):
    """Striped awning sloping out from the +v wall."""
    c = rgb(color)

    def stripes(a_, b_, xs, ys):
        on = (np.floor(a_ * length * 71.6 / 5) % 2 == 0)
        return np.where(on[:, None], c, rgb("#d8ccb4")) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    s.face((x0 + 0.05, y, z + 8), (length - 0.1, 0, 0), (0, depth, -8), stripes, light=LIGHT["v"])
    s.face((x0 + 0.05, y + depth, z), (length - 0.1, 0, 0), (0, 0, 4), stripes, light=LIGHT["v"] * 0.9)


# ---------- diner ----------

# 4×7 pixel letters for signs (legible on a slanted board).
GLYPHS = {
    "D": ["1110", "1001", "1001", "1001", "1001", "1001", "1110"],
    "I": ["111", "010", "010", "010", "010", "010", "111"],
    "N": ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
    "E": ["1111", "1000", "1000", "1110", "1000", "1000", "1111"],
    "R": ["1110", "1001", "1001", "1110", "1010", "1001", "1001"],
    "B": ["1110", "1001", "1001", "1110", "1001", "1001", "1110"],
    "U": ["1001", "1001", "1001", "1001", "1001", "1001", "0110"],
    "G": ["0111", "1000", "1000", "1011", "1001", "1001", "0111"],
    "S": ["0111", "1000", "1000", "0110", "0001", "0001", "1110"],
    "C": ["0111", "1000", "1000", "1000", "1000", "1000", "0111"],
    "H": ["1001", "1001", "1001", "1111", "1001", "1001", "1001"],
    "O": ["0110", "1001", "1001", "1001", "1001", "1001", "0110"],
    "L": ["1000", "1000", "1000", "1000", "1000", "1000", "1111"],
    "A": ["0110", "1001", "1001", "1111", "1001", "1001", "1001"],
    "K": ["1001", "1010", "1100", "1100", "1010", "1001", "1001"],
    "P": ["1110", "1001", "1001", "1110", "1000", "1000", "1000"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "F": ["1111", "1000", "1000", "1110", "1000", "1000", "1000"],
}


def sign_face(s, text, length_px, height_px, board, ink, bulbs):
    """Sign board: text centered in pixel letters, a border of bulbs.
    length_px is the board's width in screen columns (tiles × HW), so each
    letter column lands on its own pixel column."""
    b_, ink_, bulb = rgb(board), rgb(ink), rgb(bulbs)
    widths = [len(GLYPHS[ch][0]) for ch in text]
    tw = sum(widths) + len(text) - 1

    def shader(a, b, xs, ys):
        col = np.floor(a * length_px).astype(int)
        row = np.floor((1 - b) * height_px).astype(int)
        out = np.repeat(b_[None], len(a), 0)
        x0, y0 = (int(length_px) - tw) // 2, (int(height_px) - 7) // 2
        lx, ly = col - x0, row - y0
        off = 0
        for ch, w in zip(text, widths):
            g = GLYPHS[ch]
            cx = lx - off
            off += w + 1
            ok = (cx >= 0) & (cx < w) & (ly >= 0) & (ly < 7)
            bit = np.zeros(len(a), bool)
            idx = np.where(ok)[0]
            bit[idx] = [g[ly[k]][cx[k]] == "1" for k in idx]
            out = np.where(bit[:, None], ink_, out)
        edge = (col <= 0) | (col >= int(length_px) - 1) | (row <= 0) | (row >= int(height_px) - 1)
        dots = edge & ((col + row) % 2 == 0)
        out = np.where(edge[:, None], b_ * 0.7, out)
        out = np.where(dots[:, None], bulb, out)
        return out + (s.grain[ys, xs] - 0.5)[:, None] * 4
    return shader


def diner(seed):
    """Roadside diner: ribbed stainless body, red stripe, window band, glass
    vestibule and a pole sign."""
    s = Sprite(320, 260, 160, 160, seed)
    a, b, h = 1.6, 0.75, 26
    x0, y0 = -a / 2, -b / 2
    steel, red = rgb("#a9a6b2"), rgb("#8a3a32")

    def body(length_px, door=None):
        def shader(a_, b_, xs, ys):
            z, along = b_ * h, a_ * length_px
            out = np.repeat(steel[None], len(a_), 0) * (1 - 0.07 * (np.floor(z / 2) % 2))[:, None]
            out = np.where(((z >= 3) & (z < 7) | (z >= 22) & (z < 24))[:, None], red, out)       # stripes
            win = (z >= 9) & (z < 19) & (along > 3) & (along < length_px - 3)
            glass = np.array(GLASS)[np.where((xs + ys) % 7 < 2, 3, (xs // 2 + ys) % 3)]
            out = np.where(win[:, None], glass, out)
            mull = win & ((np.mod(along - 3, 9) < 1) | (z < 10) | (z >= 18))
            out = np.where(mull[:, None], rgb("#d8d4dc"), out)
            if door is not None:
                d0, d1 = door[0] * length_px, door[1] * length_px
                ind = (along >= d0) & (along < d1) & (z < 20)
                out = np.where(ind[:, None], np.array(GLASS)[1] * 0.9, out)
                out = np.where((ind & ((along < d0 + 1) | (along >= d1 - 1) | (z >= 19)))[:, None], rgb("#2e3336"), out)
            corner = (along < 1) | (along > length_px - 1)
            out = np.where(corner[:, None], steel * 0.75, out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 6
        return shader

    def roof(a_, b_, xs, ys):
        rim = (a_ < 0.03) | (a_ > 0.97) | (b_ < 0.06) | (b_ > 0.94)
        return np.where(rim[:, None], rgb("#d8ccb4"), rgb("#6e6e6e")) + (s.grain[ys, xs] - 0.5)[:, None] * 5
    s.box(x0, y0, 0, a, b, h, roof, body(a * 71.6), body(b * 71.6))
    # Vents on the roof.
    for vx in (x0 + 0.3, x0 + 1.0):
        s.box(vx, y0 + 0.25, h, 0.14, 0.14, 6, fan_top(s), flat(s, "#9791a2"), flat(s, "#716f74"))
    # Glass vestibule in front of the door.
    vx = x0 + a * 0.62
    s.box(vx, y0 + b, 0, 0.26, 0.16, 22, roof, body(0.26 * 71.6, door=(0.25, 0.75)), body(0.16 * 71.6))
    # Pole sign beside the front corner.
    px, py = x0 + a + 0.12, y0 + b - 0.1
    s.box(px - 0.02, py - 0.02, 0, 0.04, 0.04, 56, flat(s, "#716f74"), flat(s, "#8e8897"), flat(s, "#5b5a5c"))
    board_len = 0.5
    s.box(px - board_len / 2, py - 0.03, 56, board_len, 0.06, 17, flat(s, "#6e2420"),
          sign_face(s, "DINER", board_len * HW, 17, "#8a3a32", "#f0d890", "#f2c06a"),
          flat(s, "#6e2420"))
    s.outline(0.7)
    return s, (a, b)


# ---------- fast food ----------

def patio_table(s, x, y, color="#8a3a32"):
    """Round-ish table with a small striped umbrella."""
    s.box(x - 0.04, y - 0.04, 0, 0.08, 0.08, 6, flat(s, "#d8d4dc"), flat(s, "#b3afbd"), flat(s, "#8e8897"))
    s.box(x - 0.008, y - 0.008, 6, 0.016, 0.016, 16, flat(s, "#cfc6b6"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    c, cream = rgb(color), rgb("#d8ccb4")
    segs, r, apex = 8, 0.15, (x, y, 27)
    for k in range(segs):
        a0, a1 = k / segs * math.tau, (k + 1) / segs * math.tau
        p0 = (x + math.cos(a0) * r, y + math.sin(a0) * r, 21)
        p1 = (x + math.cos(a1) * r, y + math.sin(a1) * r, 21)
        col = c if k % 2 else cream
        light = 0.78 + 0.12 * (math.cos((a0 + a1) / 2) + math.sin((a0 + a1) / 2))
        s.face(apex, np.subtract(p0, apex), np.subtract(p1, apex),
               lambda a, b, xs, ys, col=col: col + (s.grain[ys, xs] - 0.5)[:, None] * 6, tri=True, light=light)


def fastfood(seed):
    """Fast-food shop: cream walls with a red stripe, big windows, a red
    mansard roof, a rooftop BURGER sign and a patio with umbrellas."""
    s = Sprite(300, 280, 150, 180, seed)
    a, b, h = 1.3, 0.95, 26
    x0, y0 = -a / 2, -b / 2
    red, yellow, cream = rgb("#8a3a32"), rgb("#c9a84a"), rgb("#d0c4ac")

    def wall(length_px, door=None):
        def shader(a_, b_, xs, ys):
            z, along = b_ * h, a_ * length_px
            out = np.repeat(cream[None], len(a_), 0)
            out = np.where((z < 4)[:, None], red * 0.85, out)                      # base
            out = np.where(((z >= 21) & (z < 24))[:, None], yellow, out)          # stripe
            win = (z >= 6) & (z < 19) & (along > 3) & (along < length_px - 3)
            glass = np.array(GLASS)[np.where((xs + ys) % 7 < 2, 3, (xs // 2 + ys) % 3)]
            out = np.where(win[:, None], glass, out)
            out = np.where((win & ((np.mod(along - 3, 12) < 1) | (z < 7) | (z >= 18)))[:, None], red, out)
            if door is not None:
                d0, d1 = door[0] * length_px, door[1] * length_px
                ind = (along >= d0) & (along < d1) & (z < 20)
                out = np.where(ind[:, None], np.array(GLASS)[1] * 0.9, out)
                out = np.where((ind & ((along < d0 + 1) | (along >= d1 - 1) | (z >= 19) |
                                       (np.abs(along - (d0 + d1) / 2) < 0.8)))[:, None], rgb("#2e3336"), out)
            out = np.where(((along < 1) | (along > length_px - 1))[:, None], cream * 0.72, out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 6
        return shader
    s.box(x0, y0, 0, a, b, h, flat(s, "#6e6e6e"), wall(a * 71.6, door=(0.4, 0.6)), wall(b * 71.6))
    # Mansard: sloped red shingle bands on the visible sides, flat top.
    m, dz, z = 0.09, 10, h

    def shingles(a_, b_, xs, ys):
        rows = np.mod(ys, 3) == 0
        return np.where(rows[:, None], red * 0.78, red) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    BL, BR = (x0, y0 + b, z), (x0 + a, y0 + b, z)
    TL, TR = (x0 + m, y0 + b - m, z + dz), (x0 + a - m, y0 + b - m, z + dz)
    s.face(BL, np.subtract(BR, BL), np.subtract(TL, BL), shingles, tri=True, light=LIGHT["v"])
    s.face(TR, np.subtract(TL, TR), np.subtract(BR, TR), shingles, tri=True, light=LIGHT["v"])
    SB, ST = (x0 + a, y0, z), (x0 + a - m, y0 + m, z + dz)
    s.face(SB, np.subtract(BR, SB), np.subtract(ST, SB), shingles, tri=True, light=LIGHT["u"])
    s.face(TR, np.subtract(ST, TR), np.subtract(BR, TR), shingles, tri=True, light=LIGHT["u"])
    s.face((x0 + m, y0 + m, z + dz), (a - 2 * m, 0, 0), (0, b - 2 * m, 0), flat(s, "#6e6e6e"))
    # Rooftop sign, facing the +v street.
    bl = 0.66
    sx, sy = x0 + (a - bl) / 2, y0 + b / 2
    for px in (sx + 0.1, sx + bl - 0.1):
        s.box(px - 0.015, sy - 0.015, z + dz, 0.03, 0.03, 6, flat(s, "#716f74"), flat(s, "#8e8897"), flat(s, "#5b5a5c"))
    s.box(sx, sy - 0.03, z + dz + 6, bl, 0.06, 15, flat(s, "#6e2420"),
          sign_face(s, "BURGER", bl * HW, 15, "#8a3a32", "#e8c86a", "#f2c06a"), flat(s, "#6e2420"))
    # Patio on the +u side.
    for ty in (y0 + 0.2, y0 + 0.62):
        patio_table(s, x0 + a + 0.24, ty)
    s.outline(0.7)
    return s, (a, b)


# ---------- civic ----------

STONE = "#c9bfae"
SLATE = ramp("#3e4048", "#4e5058", "#55575f", "#5f6169")
STAINED = ramp("#6a3a5a", "#3a5a7a", "#8a6a2a", "#3a6a4a", "#8a3a32", "#5a4a8a")


def pyramid(s, x0, y0, sx, sy, z, h, roof):
    """Pyramid roof (spire, cupola cap) over a footprint."""
    r = np.array(roof)
    apex = (x0 + sx / 2, y0 + sy / 2, z + h)
    c = [(x0, y0 + sy, z), (x0 + sx, y0 + sy, z), (x0 + sx, y0, z), (x0, y0, z)]

    def rows(a, b, xs, ys):
        return r[(ys // 3) % len(r)] + (s.grain[ys, xs] - 0.5)[:, None] * 5
    for i, light in ((2, 0.7), (3, 0.7), (0, LIGHT["v"]), (1, LIGHT["u"])):
        o, q = c[i], c[(i + 1) % 4]
        s.face(o, np.subtract(q, o), np.subtract(apex, o), rows, tri=True, light=light)


def flagpole(s, x, y, h=62, colors=("#3a5a7a", "#d8ccb4", "#3a5a7a")):
    s.box(x - 0.008, y - 0.008, 0, 0.016, 0.016, h, flat(s, "#d8d4dc"), flat(s, "#b3afbd"), flat(s, "#8e8897"))
    s.face((x + 0.01, y, h - 12), (0.17, 0, 0), (0, 0, 9), banded(s, [rgb(c) for c in colors], 3, axis=1), light=0.95)
    s.blob((x, y, h + 1), 1.4, ramp("#8a6a2e", "#c9a84a", "#f2c06a"))


def wall_sign(s, cx, y, z, width, text, board="#2c3548", ink="#e0d8c8", height=11):
    """Sign board mounted on a +v wall (or standing on a roof edge)."""
    s.box(cx - width / 2, y, z, width, 0.03, height, flat(s, board),
          sign_face(s, text, width * HW, height, board, ink, board), flat(s, board))


def column_row(s, x0, x1, y, z, h, n, color="#e0d8c8"):
    for i in range(n):
        x = x0 + (x1 - x0) * i / (n - 1)
        s.box(x - 0.035, y - 0.035, z, 0.07, 0.07, 3, *(flat(s, c) for c in (color, "#cfc6b6", "#b8b0a2")))
        s.box(x - 0.025, y - 0.025, z + 3, 0.05, 0.05, h - 6, flat(s, color), banded(s, [rgb(color), rgb(color) * 0.9], 3, axis=0),
              flat(s, "#b8b0a2"))
        s.box(x - 0.035, y - 0.035, z + h - 3, 0.07, 0.07, 3, *(flat(s, c) for c in (color, "#cfc6b6", "#b8b0a2")))


def cornice(s, x0, y0, a, b, z, color="#cfc6b6"):
    s.box(x0 - 0.03, y0 - 0.03, z - 3, a + 0.06, b + 0.06, 4, flat(s, color), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))


def civic_walls(s, x0, y0, a, b, hgt, floors, fh, wall, siding="plain", win_v=None, win_u=None, door=None,
                style="square", frame="#e0d8c8", glass_pal=None, glass_door=True, ground_windows=True):
    lv, lu = a * 71.6, b * 71.6
    wv = wall_shader(s, wall, lv, hgt, floors, win_v or [], door, None, siding, frame=frame, glass_door=glass_door,
                     window_style=style, floor_h=fh, glass_pal=glass_pal, ground_windows=ground_windows)
    wu = wall_shader(s, wall, lu, hgt, floors, win_u or [], None, None, siding, frame=frame,
                     window_style=style, floor_h=fh, glass_pal=glass_pal, ground_windows=ground_windows)
    s.box(x0, y0, 0, a, b, hgt, flat(s, "#6e6e6e"), wv, wu)


def spans(n, lo=0.28, hi=0.72, skip=()):
    return [((i + lo) / n, (i + hi) / n) for i in range(n) if i not in skip]


def school(seed):
    s = Sprite(360, 320, 180, 220, seed)
    a, b, fh, floors = 1.8, 1.0, 30, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, "#7d4a3e", "brick", spans(6, skip=(2, 3)), spans(3),
                (0.43, 0.57))
    cornice(s, x0, y0, a, b, hgt)
    flat_roof(s, x0, y0, a, b, hgt + 1, "#5b5a5c", units=0)
    # Entrance: two columns and a pediment over the door.
    px0, pw = x0 + a * 0.4, a * 0.2
    column_row(s, px0 + 0.03, px0 + pw - 0.03, y0 + b + 0.16, 0, 30, 2)
    s.box(px0, y0 + b, 30, pw, 0.2, 4, flat(s, "#e0d8c8"), flat(s, "#cfc6b6"), flat(s, "#b8b0a2"))
    gable(s, px0, y0 + b, pw, 0.2, 34, 9, ramp("#cfc6b6", "#c4baa8"), "#e0d8c8", "v", 0.02)
    wall_sign(s, x0 + a / 2, y0 + b - 0.05, hgt + 1, 0.56, "SCHOOL", "#3a5a4a", "#e8e0cc")
    # Bell cupola on the roof.
    cx, cy = x0 + a * 0.5 - 0.1, y0 + b * 0.3
    s.box(cx, cy, hgt + 1, 0.2, 0.2, 13, flat(s, "#e0d8c8"),
          wall_shader(s, "#e0d8c8", 14, 13, 1, [], (0.3, 0.7)), wall_shader(s, "#e0d8c8", 14, 13, 1, [], (0.3, 0.7)))
    pyramid(s, cx - 0.02, cy - 0.02, 0.24, 0.24, hgt + 14, 11, SLATE)
    flagpole(s, x0 - 0.02, y0 + b + 0.1)
    s.outline(0.7)
    return s, (a, b)


def portal_wall(s, length_px, hgt, a0, a1, sill=6):
    """Front wall with a big arched portal between a0 and a1 (fractions of
    the wall): stone archivolt rings, a stained-glass tympanum and studded
    wooden double doors standing on the top step (z = sill)."""
    st, dark = rgb(STONE), rgb("#8e8680")
    wood = rgb("#4f3423")
    p0, p1 = a0 * length_px, a1 * length_px
    cx, hw = (p0 + p1) / 2, (p1 - p0) / 2
    zr = sill + 20                                           # arch springs here

    def shader(a, b, xs, ys):
        along, z = a * length_px, b * hgt
        dx, dz = along - cx, z - zr
        r = np.where(z >= zr, np.hypot(dx, dz), np.abs(dx))
        out = np.repeat(st[None], len(a), 0) * (1 - 0.05 * (np.mod(z, 6) < 1))[:, None]
        inside = (z >= sill) & (r < hw)
        for k, ring in enumerate((hw + 4, hw + 2.5, hw + 1)):        # archivolt, outside in
            band = (z >= sill) & (r < ring) & ~inside
            out = np.where(band[:, None], st * (1.12 if k % 2 == 0 else 0.86), out)
        tymp = inside & (z >= zr)
        pal = np.array(STAINED)
        out = np.where(tymp[:, None], pal[(np.floor(dx / 2) + np.floor(dz / 2)).astype(int) % len(pal)], out)
        out = np.where((tymp & (np.abs(r - hw * 0.55) < 0.6))[:, None], dark, out)       # tracery ring
        doors = inside & (z < zr)
        grain = np.where(np.mod(along, 3) < 1, 0.9, 1.0)
        out = np.where(doors[:, None], wood * grain[:, None], out)
        studs = doors & (np.mod(along - p0, 4) < 1) & (np.mod(z - sill, 5) < 1)
        out = np.where(studs[:, None], rgb("#2a2420"), out)
        out = np.where((doors & (np.abs(dx) < 0.6))[:, None], rgb("#2a1c14"), out)        # door split
        out = np.where((doors & (np.abs(z - zr) < 0.7))[:, None], dark, out)             # lintel
        out = np.where(((along < 1) | (along > length_px - 1))[:, None], st * 0.72, out)
        return out + (s.grain[ys, xs] - 0.5)[:, None] * 6
    return shader


def bell_tower(s, tx, ty, tw, th):
    """Square stone tower: tall arched window, louvred belfry, cornice,
    slate spire and a gold cross."""
    tv = wall_shader(s, STONE, tw * 71.6, th, 2, [(0.34, 0.66)], None, None, "plain", frame="#6e5a4c",
                     window_style="arched", floor_h=40, glass_pal=STAINED, ground_windows=False)
    tu = wall_shader(s, STONE, tw * 71.6, th, 2, [(0.34, 0.66)], None, None, "plain", frame="#6e5a4c",
                     window_style="arched", floor_h=40, glass_pal=STAINED, ground_windows=False)
    s.box(tx, ty, 0, tw, tw, th, flat(s, STONE), tv, tu)
    for o, e1, light in (((tx + 0.08, ty + tw + 0.001, th - 26), (tw - 0.16, 0, 0), LIGHT["v"]),
                         ((tx + tw + 0.001, ty + 0.08, th - 26), (0, tw - 0.16, 0), LIGHT["u"])):
        s.face(o, e1, (0, 0, 12), lambda a_, b_, xs, ys: np.where(
            (np.mod(b_ * 12, 3) < 1)[:, None], rgb("#4a4744"), rgb("#1e1d1c")), light=light)
    cornice(s, tx, ty, tw, tw, th + 1, "#b8b0a2")
    pyramid(s, tx - 0.02, ty - 0.02, tw + 0.04, tw + 0.04, th + 1, 40, SLATE)
    top = th + 41
    gold = (flat(s, "#c9a84a"), flat(s, "#b8964a"), flat(s, "#a08238"))
    s.box(tx + tw / 2 - 0.01, ty + tw / 2 - 0.01, top, 0.02, 0.02, 11, *gold)
    s.box(tx + tw / 2 - 0.04, ty + tw / 2 - 0.01, top + 6, 0.08, 0.02, 2, *gold)


def church(seed):
    """Stone church: nave with stained-glass windows, twin bell towers on
    the front, a big arched portal between them up three steps."""
    s = Sprite(340, 420, 170, 290, seed)
    a, b, hgt = 1.15, 1.45, 44
    x0, y0 = -a / 2, -b / 2
    tw, th = 0.34, 100
    # Nave: stained glass along the side, the portal on the front wall.
    side = wall_shader(s, STONE, b * 71.6, hgt, 1, spans(4, 0.3, 0.7), None, None, "plain", frame="#8e8680",
                       window_style="arched", floor_h=46, glass_pal=STAINED)
    s.box(x0, y0, 0, a, b, hgt, flat(s, STONE), portal_wall(s, a * 71.6, hgt, 0.33, 0.67), side)
    gable(s, x0, y0, a, b, hgt, 38, SLATE, STONE, "v", 0.05)
    # Three steps up to the portal.
    sx0, sw = x0 + tw - 0.02, a - 2 * tw + 0.04
    for k, depth in enumerate((0.36, 0.24, 0.12)):
        s.box(sx0 - 0.04 * (2 - k), y0 + b, 2 * k, sw + 0.08 * (2 - k), depth, 2,
              flat(s, "#d8d0c0"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    # Twin towers flanking the facade, standing slightly proud of it.
    for tx in (x0 - 0.04, x0 + a - tw + 0.04):
        bell_tower(s, tx, y0 + b - tw + 0.07, tw, th)
    s.outline(0.7)
    return s, (a + 0.08, b)


def revolving_door(s, cx, y, r=0.1, h=24, z0=0):
    """Revolving door: a half-octagon glass drum out from a +v wall, bronze
    frames, cap and base, the dark door wings showing through the glass."""
    bronze = rgb("#8a6a3a")
    angs = [k * math.pi / 4 for k in range(5)]                  # 0..180°, out toward +v
    pts = [(cx + r * math.cos(t), y + r * math.sin(t)) for t in angs]
    for k in range(4):
        (xa, ya), (xb, yb) = pts[k], pts[k + 1]
        nx, ny = math.cos((angs[k] + angs[k + 1]) / 2), math.sin((angs[k] + angs[k + 1]) / 2)
        light = 0.7 + 0.25 * max(0.0, 0.6 * nx + 0.8 * ny)
        seg = math.hypot(xb - xa, yb - ya) * 71.6

        def glass(a_, b_, xs, ys, k=k, seg=seg):
            along, z = a_ * seg, b_ * h
            sheen = np.mod(along + z * 0.7 + k * 3, 8) < 1.5
            out = np.where(sheen[:, None], np.array(GLASS)[3] * 1.1, np.array(GLASS)[1] * 0.85)
            wing = (k in (1, 2)) & (np.abs(along - seg * (0.8 if k == 1 else 0.2)) < 0.7)   # door wings inside
            out = np.where(np.atleast_1d(wing)[:, None], rgb("#2e3336"), out)
            frame = (along < 0.8) | (along > seg - 0.8) | (z < 2) | (z > h - 2)
            return np.where(frame[:, None], bronze, out)
        s.face((xa, ya, z0), (xb - xa, yb - ya, 0), (0, 0, h), glass, light=light)
    # Cap: fan of triangles over the drum, bronze.
    for k in range(4):
        (xa, ya), (xb, yb) = pts[k], pts[k + 1]
        s.face((cx, y, z0 + h), (xa - cx, ya - y, 0), (xb - cx, yb - y, 0), flat(s, bronze * 1.15), tri=True)
        s.face((cx, y, z0 + h + 2), (xa - cx, ya - y, 0), (xb - cx, yb - y, 0), flat(s, bronze * 1.25), tri=True)
    for k in range(4):                                          # cap rim
        (xa, ya), (xb, yb) = pts[k], pts[k + 1]
        s.face((xa, ya, z0 + h), (xb - xa, yb - ya, 0), (0, 0, 2), flat(s, bronze * 0.9), light=0.9)


def bank(seed):
    s = Sprite(340, 330, 170, 230, seed)
    a, b, fh, floors = 1.5, 1.1, 34, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, STONE, "plain", spans(5, skip=(1, 2, 3)), spans(3),
                (0.27, 0.73), "arched", "#8e8680", None, glass_door=True)
    for dx in (0.385, 0.615):                              # two revolving doors
        revolving_door(s, x0 + a * dx, y0 + b, z0=6)             # on the top step
    cornice(s, x0, y0, a, b, hgt, "#e0d8c8")
    flat_roof(s, x0, y0, a, b, hgt + 1, "#6e6e6e", units=2)
    # Portico: steps, four columns, an entablature with the name, pediment.
    px0, pw = x0 + 0.24, a - 0.48
    s.box(px0 - 0.04, y0 + b, 0, pw + 0.08, 0.36, 3, flat(s, "#d8d0c0"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    s.box(px0, y0 + b, 3, pw, 0.3, 3, flat(s, "#e0d8c8"), flat(s, "#c9bfae"), flat(s, "#b3a998"))
    column_row(s, px0 + 0.05, px0 + pw - 0.05, y0 + b + 0.22, 6, 50, 4)
    s.box(px0 - 0.02, y0 + b, 56, pw + 0.04, 0.3, 10, flat(s, "#e0d8c8"),
          sign_face(s, "BANK", (pw + 0.04) * HW, 10, "#d8d0c0", "#6e5a3a", "#d8d0c0"), flat(s, "#b3a998"))
    gable(s, px0 - 0.02, y0 + b, pw + 0.04, 0.3, 66, 15, ramp("#cfc6b6", "#c4baa8"), "#e0d8c8", "v", 0.02)
    s.outline(0.7)
    return s, (a, b)


def post_office(seed):
    s = Sprite(320, 280, 160, 200, seed)
    a, b, fh, floors = 1.4, 1.0, 30, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, "#a47d6a", "brick", spans(5), spans(3), (0.43, 0.57))
    cornice(s, x0, y0, a, b, hgt)
    flat_roof(s, x0, y0, a, b, hgt + 1, "#5b5a5c", units=2)
    wall_sign(s, x0 + a * 0.5, y0 + b, 25, 0.36, "POST", "#2c3548", "#e8e0cc", 12)
    # Blue mailbox by the door.
    mx, my = x0 + a * 0.66, y0 + b + 0.1
    s.box(mx, my, 0, 0.08, 0.07, 11, flat(s, "#34486a"), flat(s, "#2c3e5c"), flat(s, "#243350"))
    s.blob((mx + 0.04, my + 0.035, 11), 3.2, ramp("#1f2c44", "#2c3e5c", "#34486a", "#45608a"), squash=0.6)
    flagpole(s, x0 - 0.02, y0 + b + 0.1)
    s.outline(0.7)
    return s, (a, b)


def police(seed):
    s = Sprite(320, 300, 160, 210, seed)
    a, b, fh, floors = 1.4, 1.1, 30, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, "#80848c", "plain", spans(5), spans(3), (0.43, 0.57),
                frame="#2c3548")
    # Navy band at the floor line, the sign on it.
    s.face((x0, y0 + b + 0.001, 26), (a, 0, 0), (0, 0, 6), flat(s, "#2c3548"), light=LIGHT["v"])
    s.face((x0 + a + 0.001, y0, 26), (0, b, 0), (0, 0, 6), flat(s, "#2c3548"), light=LIGHT["u"])
    wall_sign(s, x0 + a * 0.5, y0 + b + 0.002, 24, 0.5, "POLICE", "#2c3548", "#e8e0cc", 12)
    flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=1)
    s.box(x0 + 0.25, y0 + 0.25, hgt, 0.02, 0.02, 40, flat(s, "#b3afbd"), flat(s, "#8e8897"), flat(s, "#716f74"))
    s.blob((x0 + 0.26, y0 + 0.26, hgt + 41), 1.6, ramp("#6a2420", "#a8433a", "#e0605a"))
    # Blue lamps on posts either side of the door.
    for lx in (x0 + a * 0.36, x0 + a * 0.64):
        s.box(lx - 0.01, y0 + b + 0.08, 0, 0.02, 0.02, 18, flat(s, "#3a3a3e"), flat(s, "#2e2e32"), flat(s, "#26262a"))
        s.blob((lx, y0 + b + 0.09, 20), 3, ramp("#1f3558", "#2e4d80", "#4a6fa8", "#7a9ccc"))
    s.outline(0.7)
    return s, (a, b)


def fire_station(seed):
    s = Sprite(340, 340, 170, 250, seed)
    a, b, fh, floors = 1.6, 1.1, 32, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    # Hose tower at the back corner, taller than the station.
    tw, th = 0.34, 118
    civic_walls(s, x0, y0, tw, tw, th, 3, 38, "#7d3a32", "brick", [(0.35, 0.65)], [(0.35, 0.65)],
                glass_door=False, frame="#e0d8c8")
    cornice(s, x0, y0, tw, tw, th, "#cfc6b6")
    flat_roof(s, x0, y0, tw, tw, th + 1, "#5b5a5c", units=0)
    civic_walls(s, x0, y0 + tw, a, b - tw, hgt, floors, fh, "#7d3a32", "brick", spans(4), spans(2),
                None, frame="#e0d8c8", ground_windows=False)
    civic_walls(s, x0 + tw, y0, a - tw, tw, hgt, floors, fh, "#7d3a32", "brick", [], spans(1),
                None, frame="#e0d8c8", ground_windows=False)
    cornice(s, x0, y0 + tw, a, b - tw, hgt)
    cornice(s, x0 + tw, y0, a - tw, tw, hgt)
    flat_roof(s, x0, y0 + tw, a, b - tw, hgt + 1, "#5b5a5c", units=0)
    flat_roof(s, x0 + tw, y0, a - tw, tw, hgt + 1, "#5b5a5c", units=1)
    # Two bay doors on the front: red panels, a row of windows.
    red, cream = rgb("#9a3a30"), rgb("#e0d8c8")

    def bay(a_, b_, xs, ys):
        along, z = a_ * 0.56 * 71.6, b_ * 24
        out = np.repeat(red[None], len(a_), 0) * (1 - 0.08 * (np.mod(z, 5) < 1))[:, None]
        win = (z > 15) & (z < 20) & (np.mod(along, 8) > 1.5)
        out = np.where(win[:, None], np.array(GLASS)[2], out)
        frame = (along < 1.2) | (along > 0.56 * 71.6 - 1.2) | (z > 23)
        out = np.where(frame[:, None], cream, out)
        return out + (s.grain[ys, xs] - 0.5)[:, None] * 6
    for bx in (x0 + 0.18, x0 + 0.86):
        s.face((bx, y0 + b + 0.002, 0), (0.56, 0, 0), (0, 0, 24), bay, light=LIGHT["v"])
    wall_sign(s, x0 + a / 2 + 0.03, y0 + b + 0.003, 26, 0.42, "FIRE", "#e0d8c8", "#9a3a30", 11)
    s.outline(0.7)
    return s, (a, b)


# ---------- beach ----------

def umbrella(seed, color="#8a4a3e"):
    s = Sprite(90, 100, 45, 88, seed)
    s.box(-0.012, -0.012, 0, 0.024, 0.024, 48, flat(s, "#cfc6b6"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    c, cream = rgb(color), rgb("#d8ccb4")
    segs, r = 10, 0.34
    apex = (0, 0, 60)
    for k in range(segs):
        a0, a1 = k / segs * math.tau, (k + 1) / segs * math.tau
        p0 = (math.cos(a0) * r, math.sin(a0) * r, 44)
        p1 = (math.cos(a1) * r, math.sin(a1) * r, 44)
        col = c if k % 2 else cream
        nrm = math.cos((a0 + a1) / 2) + math.sin((a0 + a1) / 2)        # faces the viewer
        light = 0.78 + 0.12 * nrm
        s.face(apex, np.subtract(p0, apex), np.subtract(p1, apex),
               lambda a, b, xs, ys, col=col: col + (s.grain[ys, xs] - 0.5)[:, None] * 6, tri=True, light=light)
    s.outline()
    s.shadow((0.1, 0.1, 0), 22, 9)
    return s


def lounger(seed, color="#3f6f73"):
    """Beach lounger along u: frame on legs, seat, raised backrest at -u."""
    s = Sprite(100, 70, 50, 46, seed)
    frame = ("#cfc6b6", "#bdb3a2", "#a69c8c")
    for x, y in ((-0.3, -0.13), (0.26, -0.13), (-0.3, 0.1), (0.26, 0.1)):
        s.box(x, y, 0, 0.03, 0.03, 7, *(flat(s, c) for c in frame))
    s.box(-0.31, -0.14, 7, 0.6, 0.28, 2, *(flat(s, c) for c in frame))
    fabric = banded(s, [rgb(color), rgb("#d8ccb4")], 7, axis=0)
    s.face((-0.09, -0.12, 9), (0.38, 0, 0), (0, 0.24, 0), fabric)
    s.face((-0.09, -0.12, 9), (-0.2, 0, 14), (0, 0.24, 0), fabric, light=0.8)   # backrest faces the viewer
    s.outline()
    s.shadow((0.02, 0.02, 0), 26, 9)
    return s


def towel(seed, color="#8f6f9a"):
    s = Sprite(80, 40, 40, 20, seed)
    s.face((-0.25, -0.12, 0.5), (0.5, 0, 0), (0, 0.24, 0), banded(s, [rgb(color), rgb("#d8ccb4"), rgb(color) * 0.8], 7, axis=0))
    return s


def lifeguard(seed):
    s = Sprite(120, 150, 60, 130, seed)
    white, red = "#cfc6b6", "#8a4a3e"
    for x, y in ((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2)):
        s.box(x - 0.02, y - 0.02, 0, 0.04, 0.04, 40, flat(s, white), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    s.box(-0.26, -0.26, 40, 0.52, 0.52, 4, flat(s, "#8a6751"), flat(s, "#765743"), flat(s, "#5f4646"))
    s.box(-0.18, -0.18, 44, 0.36, 0.36, 26, flat(s, white),
          wall_shader(s, white, 26, 26, 1, [(0.2, 0.8)], None, None, "boards"),
          wall_shader(s, white, 26, 26, 1, [(0.2, 0.8)], None, None, "boards"))
    gable(s, -0.18, -0.18, 0.36, 0.36, 70, 12, ramp(red, "#7a3f35"), red, "u", 0.05)
    # Ladder: from the sand in front up to the platform's front edge.
    s.face((-0.06, 0.56, 0), (0.12, 0, 0), (0, -0.3, 40), banded(s, [rgb("#8a6751"), rgb("#5f4646")], 10), light=LIGHT["v"])
    s.outline()
    s.shadow((0.1, 0.1, 0), 36, 14)
    return s


def rowboat(seed, color="#3f6f73"):
    s = Sprite(130, 70, 65, 40, seed)
    hull, inner = rgb("#cfc6b6"), rgb("#6b553a")
    L, W, H = 0.42, 0.14, 9
    stripe = lambda a, b, xs, ys: np.where((b > 0.55)[:, None] & (b < 0.8)[:, None], rgb(color), hull) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    # sides
    s.face((-L + 0.12, W, 0), (2 * L - 0.24, 0, 0), (0, 0, H), stripe, light=LIGHT["v"])
    s.face((L - 0.12, W, 0), (0.12, -W, 0), (0, 0, H), stripe, light=0.8)
    s.face((L - 0.12, -W, 0), (0.12, W, 0), (0, 0, H), stripe, light=LIGHT["u"])
    s.face((-L + 0.12, W, 0), (-0.12, -W, 0), (0, 0, H), stripe, light=0.95)
    # inside
    s.face((-L + 0.12, -W, H - 2), (2 * L - 0.24, 0, 0), (0, 2 * W, 0), flat(s, inner), light=0.8)
    s.face((L - 0.12, -W, H - 2), (0.12, W, 0), (0, 2 * W, 0), flat(s, inner), tri=True, light=0.8)
    s.face((-L + 0.12, -W, H - 2), (-0.12, W, 0), (0, 2 * W, 0), flat(s, inner), tri=True, light=0.8)
    s.box(-0.05, -W, H - 3, 0.08, 2 * W, 2, flat(s, "#8a6751"), flat(s, "#765743"), flat(s, "#5f4646"))
    s.outline()
    return s


def beach_hut(seed, stripe="#3f6f73"):
    s = Sprite(160, 150, 80, 110, seed)
    a, b = 0.5, 0.45
    x0, y0 = -a / 2, -b / 2
    s.box(x0, y0, 0, a, b, 26, flat(s, "#d8ccb4"),
          wall_shader(s, "#d8ccb4", a * 71.6, 26, 1, [], (0.35, 0.65), None, "plain", stripes=stripe),
          wall_shader(s, "#d8ccb4", b * 71.6, 26, 1, [(0.3, 0.7)], None, None, "plain", stripes=stripe))
    gable(s, x0, y0, a, b, 26, 14, ramp("#7a3f35", "#8a4a3e"), "#d8ccb4", "u", 0.06)
    s.outline()
    return s


def pier(seed, length=1.0):
    """Wooden pier section along u on posts, sitting on water."""
    s = Sprite(int(64 * length) + 90, int(32 * length) + 80, 45, 40, seed)
    for x in (0.05, length - 0.05):
        for y in (0.02, 0.36):
            s.box(x - 0.025, y - 0.025, -6, 0.05, 0.05, 12, flat(s, "#3e281b"), flat(s, "#4f3423"), flat(s, "#38261b"))
    s.box(0, 0, 6, length, 0.38, 3, banded(s, [rgb("#7c5944"), rgb("#8a6751"), rgb("#6e4c3c")], int(length * 12), axis=0),
          flat(s, "#5f4646"), flat(s, "#4b3931"))
    s.outline(0.75)
    return s


def barrel(seed):
    s = Sprite(40, 50, 20, 40, seed)
    for z in range(0, 14, 2):
        s.blob((0, 0, z + 2), 6, ramp("#4f3423", "#62432d", "#765743", "#8a6751"), squash=0.5, shade=0.2 if z % 6 else -0.3)
    s.outline()
    return s


def buoy(seed):
    s = Sprite(30, 40, 15, 30, seed)
    s.blob((0, 0, 5), 5, ramp("#6a2a24", "#8a3a30", "#a8564a", "#c07060"), squash=0.8)
    s.blob((0, 0, 11), 3, ramp("#9a9488", "#b8b0a2", "#d8ccb4"))
    s.outline()
    return s


# ---------- output ----------

MANIFEST = {}


def save(sprite, rel, **meta):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    img = sprite.image()
    bbox = img.getbbox()
    img = img.crop(bbox)
    img.save(path)
    MANIFEST[rel] = {"size": list(img.size), "anchor": [round(sprite.ox - bbox[0], 1), round(sprite.oy - bbox[1], 1)], **meta}


def save_tile(img, rel):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    MANIFEST[rel] = {"size": list(img.size), "tile": True}


def main():
    # Nature
    save(round_tree("green", 1.0, 3), "nature/trees/oak.png")
    save(round_tree("deep", 0.8, 5), "nature/trees/oak-small.png")
    save(round_tree("autumn", 0.9, 8), "nature/trees/maple.png")
    save(round_tree("gold", 0.85, 13), "nature/trees/birch.png")
    save(round_tree("olive", 0.95, 11), "nature/trees/olive.png")
    save(pine_tree(1.0, 2), "nature/trees/pine.png")
    save(pine_tree(0.7, 4), "nature/trees/pine-small.png")
    save(palm_tree(1.0, 6, 1), "nature/trees/palm.png")
    save(palm_tree(0.8, 9, -1), "nature/trees/palm-small.png")
    save(bush("green", 1.0, 21), "nature/bushes/bush.png")
    save(bush("deep", 0.8, 22), "nature/bushes/bush-small.png")
    save(bush("green", 0.9, 23, flowers=True), "nature/bushes/bush-flowers.png")
    save(bush("olive", 1.1, 24), "nature/bushes/shrub.png")
    save(hedge(1.0, 25), "nature/bushes/hedge.png")
    save(rocks(31, 1.0), "nature/rocks/rocks.png")
    save(rocks(32, 0.7), "nature/rocks/rocks-small.png")
    save(flower_bed(41), "nature/flowers/flower-bed.png")
    # Ground
    save_tile(ground(**GRASS, seed=51), "ground/grass-a.png")
    save_tile(ground(**GRASS, seed=52, tufts=40), "ground/grass-b.png")
    save_tile(ground(**GRASS, seed=53, tufts=20, dots=["#b9a45c", "#a8676a", "#c7bba0", "#8f6f9a"]), "ground/grass-flowers.png")
    save_tile(ground(base="#585e12", dark="#50580f", light="#62681a", seed=54, patches="#5f6418", tufts=10), "ground/grass-dry.png")
    save_tile(ground(base="#4c5810", dark="#43500d", light="#566414", seed=55, tufts=30), "ground/grass-lush.png")
    save_tile(ground(**SAND, seed=61), "ground/sand-a.png")
    save_tile(ground(**SAND, seed=62, tufts=0, patches="#948059"), "ground/sand-b.png")
    save_tile(ground(base="#6a5440", dark="#5e4a38", light="#76604a", seed=63), "ground/dirt.png")
    # Shoreline: every combination of land sides plus the outer corners
    # (land only diagonally) whose two neighboring sides are water: the
    # 47-tile blob set. Named shore-<sides>[-<corners>], e.g. shore-n-es.
    between = {"ne": "ne", "es": "es", "sw": "sw", "wn": "wn"}
    for mask in range(16):
        sides = "".join(k for i, k in enumerate("nesw") if mask >> i & 1)
        free = [c for c in ("ne", "es", "sw", "wn") if not set(between[c]) & set(sides)]
        for cm in range(1 << len(free)):
            corners = [c for i, c in enumerate(free) if cm >> i & 1]
            if not sides and not corners:
                continue
            name = sides + ("-" + "".join(corners) if corners else "")
            save_tile(shore(sides, corners, seed=70 + mask), f"ground/shore-{name}.png")
    # Beach
    save(umbrella(101, "#8a4a3e"), "beach/umbrella-red.png")
    save(umbrella(102, "#3f6f73"), "beach/umbrella-teal.png")
    save(umbrella(103, "#8f7a3a"), "beach/umbrella-gold.png")
    save(lounger(104, "#3f6f73"), "beach/lounger-teal.png")
    save(lounger(105, "#8a4a3e"), "beach/lounger-red.png")
    save(towel(106, "#8f6f9a"), "beach/towel-purple.png")
    save(towel(107, "#3f6f73"), "beach/towel-teal.png")
    save(lifeguard(108), "beach/lifeguard-tower.png")
    save(rowboat(109, "#3f6f73"), "beach/rowboat.png")
    save(beach_hut(110, "#3f6f73"), "beach/hut-teal.png")
    save(beach_hut(111, "#8a4a3e"), "beach/hut-red.png")
    save(pier(112, 1.0), "beach/pier.png")
    save(barrel(113), "beach/barrel.png")
    save(buoy(114), "beach/buoy.png")
    # Suburb houses
    variants = [
        dict(wall="#a47d6a", floors=1, a=1.2, b=0.9, axis="u"),
        dict(wall="#8e9a9c", floors=1, a=1.0, b=0.85, axis="v", roof=ramp("#4e5058", "#55575f", "#5f6169", "#595b63"), gable_col="#3e4048"),
        dict(wall="#a3a07e", floors=2, a=1.1, b=0.9, axis="u", roof=ramp("#7a4a3a", "#834f3e", "#8f5a47", "#88533f"), gable_col="#5a3a2c"),
        dict(wall="#b8a88e", floors=1, a=1.25, b=0.8, axis="u", garage=True),
        dict(wall="#9a8a9e", floors=2, a=1.0, b=0.95, axis="v", roof=ramp("#4e5058", "#55575f", "#5f6169", "#595b63"), gable_col="#3e4048", siding="plain"),
        dict(wall="#b09078", floors=1, a=0.9, b=0.75, axis="v", chimney=False, siding="brick", base=None),
    ]
    for i, v in enumerate(variants):
        spr, (fa, fb) = house(200 + i, **v)
        save(spr, f"houses/house-{i + 1}.png", footprint=[round(fa, 3), round(fb, 3)])
    spr, (fa, fb) = diner(260)
    save(spr, "houses/diner.png", footprint=[fa, fb])
    # City buildings
    bl = [
        ("apartment", dict(a=1.5, b=1.0, floors=4, wall="#a68978")),
        ("apartment", dict(a=1.3, b=1.1, floors=5, wall="#9791a2", mart=True)),
        ("brick", dict(a=1.4, b=1.0, floors=3, wall="#7d4a3e")),
        ("brick", dict(a=1.25, b=1.0, floors=4, wall="#6e4c49", canopy=True)),
        ("office", dict(a=1.3, b=1.1, floors=7, wall="#8e8897")),
        ("shop", dict(a=1.4, b=0.9, floors=2, wall="#ae9282")),
        ("shop", dict(a=1.2, b=0.9, floors=1, wall="#a3a07e")),
    ]
    for i, (kind, kw) in enumerate(bl):
        spr, (fa, fb) = building(300 + i, kind, **kw)
        save(spr, f"buildings/{kind}-{i + 1}.png", footprint=[fa, fb])
    spr, (fa, fb) = fastfood(320)
    save(spr, "buildings/fastfood.png", footprint=[fa, fb])
    # Civic: one of each per district (the generator enforces "unique").
    for name, fn in (("school", school), ("church", church), ("bank", bank), ("post-office", post_office),
                     ("police", police), ("fire-station", fire_station)):
        spr, (fa, fb) = fn(400 + len(name))
        save(spr, f"civic/{name}.png", footprint=[fa, fb], group="civic", unique="district")
    (OUT / "manifest.json").write_text(json.dumps(MANIFEST, indent=1))
    print(len(MANIFEST), "sprites")


if __name__ == "__main__":
    main()
