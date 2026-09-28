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
    along u, v; z in px up. (ox, oy) is where the world origin lands.
    `rot` turns everything drawn by 90° × rot about the origin (x, y ->
    -y, x each step), `dz` lifts it by that many px (bobbing)."""

    rot = 0
    dz = 0.0

    def __init__(self, w, h, ox, oy, seed=1):
        self.w, self.h, self.ox, self.oy = w, h, ox, oy
        self.col = np.zeros((h, w, 3), float)
        self.alpha = np.zeros((h, w), float)
        self.depth = np.full((h, w), -1e9)
        self.rng = np.random.default_rng(seed)
        self.grain = self.rng.random((h, w))

    def R(self, x, y):
        for _ in range(self.rot % 4):
            x, y = -y, x
        return x, y

    def _proj(self, x, y, z=0.0):
        return self.ox + (x - y) * HW, self.oy + (x + y) * HH - z - self.dz

    def proj(self, x, y, z=0.0):
        return self._proj(*self.R(x, y), z)

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
        o, e1, e2 = ((*self.R(v[0], v[1]), v[2]) for v in (o, e1, e2))
        self._face(o, e1, e2, shader, tri, light)

    def _face(self, o, e1, e2, shader, tri=False, light=1.0):
        o, e1, e2 = (np.array(v, float) for v in (o, e1, e2))
        if light == "auto":                          # by the (turned) face's facing
            n = np.cross(e1 * [1, 1, 1 / 64], e2 * [1, 1, 1 / 64])
            n = n / (np.linalg.norm(n) or 1)
            light = LIGHT["top"] if abs(n[2]) > 0.9 else (LIGHT["u"] * n[0] ** 2 + LIGHT["v"] * n[1] ** 2) / (n[0] ** 2 + n[1] ** 2 or 1)
        so = np.array(self._proj(*o))
        s1 = np.array(self._proj(*(o + e1))) - so
        s2 = np.array(self._proj(*(o + e2))) - so
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
        color = shader(a, b, xs, ys)
        if color.shape[1] == 4:                      # RGBA: transparent pixels aren't drawn
            inside = inside & (color[:, 3] > 0)
            color = color[:, :3]
        self._write(inside, ys, xs, depth, color * light)

    def blob(self, c, r, ramp_, squash=1.0, jag=0.0, shade=0.0):
        """Shaded sphere (squash < 1 flattens it) at world point c, screen
        radius r px, lit from the upper left."""
        cx, cy = self.proj(*c)
        c = (*self.R(c[0], c[1]), c[2])
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
        """Axis-aligned box: shaders for its +u face, +v face and top. Turned
        by `rot`, it is still axis-aligned; its walls swap on odd turns."""
        (ax, ay), (bx, by) = self.R(x0, y0), self.R(x0 + sx, y0 + sy)
        x0, y0, sx, sy = min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay)
        if self.rot % 2:
            wall_u, wall_v = wall_v, wall_u
        if sz > 0:
            self._face((x0 + sx, y0, z0), (0, sy, 0), (0, 0, sz), wall_u, light=LIGHT["u"])
            self._face((x0, y0 + sy, z0), (sx, 0, 0), (0, 0, sz), wall_v, light=LIGHT["v"])
        self._face((x0, y0, z0 + sz), (sx, 0, 0), (0, sy, 0), top, light=LIGHT["top"])

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
GLASS_BLUE = ramp("#2f4a66", "#3a5876", "#446486", "#527296")
GLASS_GREEN = ramp("#3d5a4a", "#476656", "#517262", "#5d7e6c")


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


def shore_field(sides, corners, seed):
    """Distance from the sand, in tiles, for each pixel of a shore tile
    (shared by the tile and its foam frames), and the tile's rng."""
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
    return d + wobble, rng


def shore(sides, corners=(), seed=1):
    """Water tile with sand on the given sides (n = -u, e = -v, s = +u,
    w = +v, as in the road keys) and outer corners ('ne', 'es', 'sw', 'wn':
    land only diagonally)."""
    h, w = TILE_MASK.shape
    d, rng = shore_field(sides, corners, seed)
    n = value_noise(h, w, 5, rng)
    water = np.array(WATER)[np.clip((n * 2.2).astype(int), 0, 1)]
    col = water.copy()
    col[d < 0.42] = np.array(WATER)[2]                                 # shallows
    col[d < 0.3] = rgb("#7fa6a0")                                     # foam
    col[d < 0.27] = rgb("#7a684a")                                    # wet sand
    col[d < 0.23] = np.where((n[d < 0.23] > 0.55)[:, None], rgb(SAND["light"]), rgb(SAND["base"]))
    col = col + (rng.random((h, w)) - 0.5)[..., None] * 5
    return tile_image(col)


def dune(sides, corners=(), seed=1):
    """Sand tile with grass creeping in from the given sides and outer
    corners (as in shore()): an irregular edge with a shadow line, loose
    sprouts on the sand beyond it."""
    h, w = TILE_MASK.shape
    rng = np.random.default_rng(seed)
    u, v = uv_of_tile()
    d = np.full((h, w), 9.0)
    side = {"n": u, "s": 1 - u, "e": v, "w": 1 - v}
    for k in sides:
        d = np.minimum(d, side[k])
    corner = {"ne": (0, 0), "es": (1, 0), "sw": (1, 1), "wn": (0, 1)}
    for k in corners:
        cu, cv = corner[k]
        d = np.minimum(d, np.hypot(u - cu, v - cv) - 0.02)
    d = d + (value_noise(h, w, 5, rng) - 0.5) * 0.3 + (value_noise(h, w, 2, rng) - 0.5) * 0.1
    sand = np.array(ground(**SAND, seed=seed + 500))[..., :3].astype(float)
    grass = np.array(ground(**GRASS, seed=seed + 600, tufts=18))[..., :3].astype(float)
    reach = 0.34
    patch = (value_noise(h, w, 3, rng) > 0.74) & (d < reach + 0.3)          # grass islands past the edge
    col = np.where(((d < reach) | patch)[..., None], grass, sand)
    rim = (d >= reach) & (d < reach + 0.035)                            # shadow under the grass edge
    col[rim] = col[rim] * 0.86
    for _ in range(70):                                                # sprouts out on the sand
        x, y = rng.integers(3, w - 3), rng.integers(3, h - 3)
        if TILE_MASK[y, x] and TILE_MASK[y - 2, x] and reach < d[y, x] < reach + 0.28 * rng.random():
            col[y, x] = rgb(GRASS["light"]) * 1.1
            col[y - 1, x] = rgb(GRASS["light"]) * 1.2
            col[y, x + 1] = rgb(GRASS["dark"])
    return tile_image(col)


FOAM_FRAMES = 16


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def foam(sides, corners=(), seed=1):
    """Waves on a shore tile, FOAM_FRAMES frames side by side: a faint swell
    fades in offshore and speeds up toward the sand, its crest thickening
    into foam that breaks white as it arrives, then drains back as thinning
    lace over wet sand. Transparent elsewhere; drawn over the tile every
    frame."""
    h, w = TILE_MASK.shape
    d, _ = shore_field(sides, corners, seed)
    rng = np.random.default_rng(seed + 900)
    lace = value_noise(h, w, 3, rng)
    white, crest, body = rgb("#d6e8e2"), rgb("#b4d4d0"), rgb("#4aa3b3")
    frames = []
    for k in range(FOAM_FRAMES):
        p = k / FOAM_FRAMES
        col, alpha = np.zeros((h, w, 3)), np.zeros((h, w))

        def paint(mask, c, a):
            mask = mask & TILE_MASK
            col[mask] = c
            alpha[mask] = np.maximum(alpha[mask], a)
        if p < 0.7:                                       # rolling in
            r = p / 0.7
            front = 0.62 - 0.38 * r ** 1.4                # slow far out, quicker near the sand
            grow = smoothstep(0.0, 0.45, r)               # the swell fades in ...
            paint((d > front) & (d < front + 0.05 + 0.05 * grow), body, 0.45 * grow)
            if r > 0.2:                                   # ... then its crest foams up
                width = 0.006 + 0.017 * smoothstep(0.2, 0.8, r)
                paint(np.abs(d - front) < width, crest, 0.95 * smoothstep(0.2, 0.5, r))
            if r > 0.55:                                  # and breaks white near the sand
                paint((np.abs(d - front) < 0.012) & (lace > 0.75 - 0.3 * smoothstep(0.55, 0.9, r)), white, 1.0)
        else:                                             # draining back
            q = (p - 0.7) / 0.3
            back = 0.24 + 0.14 * q
            paint((d > 0.2) & (d < back), rgb("#6b5a40"), 0.5 * (1 - q))           # wet sand, drying
            paint((np.abs(d - back) < 0.02) & (lace > 0.35 + 0.4 * q), white, 0.9 * (1 - q))
        out = np.zeros((h, w, 4), np.uint8)
        out[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
        out[..., 3] = (alpha * 255).astype(np.uint8)
        frames.append(Image.fromarray(out, "RGBA"))
    atlas = Image.new("RGBA", (w * FOAM_FRAMES, h))
    for k, f in enumerate(frames):
        atlas.paste(f, (k * w, 0))
    return atlas


def glints(seed=1):
    """Sun glints for open water, 4 frames: a few specks flare and fade."""
    h, w = TILE_MASK.shape
    rng = np.random.default_rng(seed)
    atlas = Image.new("RGBA", (w * 4, h))
    px = atlas.load()
    specks = [(rng.integers(20, w - 20), rng.integers(12, h - 12)) for _ in range(3)]
    for k, level in enumerate([0.5, 1.0, 0.7, 0.3]):
        for x, y in specks:
            a = int(255 * level)
            for dx, dy, f in ((0, 0, 1.0), (-1, 0, 0.6), (1, 0, 0.6), (0, -1, 0.4), (0, 1, 0.4)):
                if level < 0.6 and f < 1:
                    continue
                px[k * w + x + dx, y + dy] = (230, 245, 240, int(a * f))
    return atlas


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
            glass = np.array(glass_pal if glass_pal is not None else GLASS)[((xs + ys) // 3 % 4)]
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
                    # Frame sides 1.2 wall px thick: a wall px is under one screen
                    # px, so a 1 px side could fall between pixel centers.
                    inner = ((np.abs(dx) < hw - 1.2) & (z >= z0 + 1) & (z < zr)) | \
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
        s.face((x0 + sx, y0, zw), (0, sy, 0), (0, sy / 2, rh), boards, tri=True, light="auto")
        if s.rot:                                    # the far end shows once turned
            s.face((x0, y0, zw), (0, sy, 0), (0, sy / 2, rh), boards, tri=True, light="auto")
    else:
        xm = x0 + sx / 2
        s.face((xm, y0 - over, zw + rh), (0, sy + 2 * over, 0), (-(sx / 2 + over), 0, -rh - over * 20), tiles, light=0.8)
        s.face((xm, y0 - over, zw + rh), (0, sy + 2 * over, 0), (sx / 2 + over, 0, -rh - over * 20), tiles, light=LIGHT["u"])
        s.face((x0, y0 + sy, zw), (sx, 0, 0), (sx / 2, 0, rh), boards, tri=True, light="auto")
        if s.rot:
            s.face((x0, y0, zw), (sx, 0, 0), (sx / 2, 0, rh), boards, tri=True, light="auto")


def house(seed, a=1.2, b=0.9, floors=1, wall="#a47d6a", roof=None, gable_col="#4f3a30",
          axis="u", garage=False, chimney=True, porch=True, base="#6e5a4c", siding="boards"):
    roof = roof or ramp("#6e4c49", "#734c48", "#835d59", "#7d5550")
    s = Sprite(260, 230, 130, 150, seed)
    x0, y0 = -(a + (0.5 if garage else 0)) / 2, -b / 2        # origin at the footprint center, garage included
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


def building(seed, kind="apartment", a=1.4, b=1.0, floors=4, wall="#a47d6a", mart=False, helipad=True,
             canopy=False, glass=None, roof_sign=None, awning_col=None, roof_units=None, extra=None):
    rng = np.random.default_rng(seed)
    fh = 34 if kind == "brick" else FLOOR               # taller floors fit arched windows
    # A taller canvas only when needed (the canvas size seeds the texture grain).
    s = Sprite(300, 440, 150, 350, seed) if floors * fh > 240 else Sprite(300, 380, 150, 290, seed)
    x0, y0 = -a / 2, -b / 2
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
                     storefront=sign, window_style=style, floor_h=fh, glass_pal=glass)
    wu = wall_shader(s, wall, lu, hgt, floors, [] if kind == "office" else win(nwin_u), None, None, siding,
                     frame="#e0d8c8" if kind == "brick" else TRIM, storefront=sign, window_style=style, floor_h=fh,
                     glass_pal=glass)
    s.box(x0, y0, 0, a, b, hgt, flat(s, wall), wv, wu)
    if kind == "shop":
        awning(s, x0, y0 + b, a, 22, awning_col or rng.choice(["#8a4a3e", "#3f6f73", "#6a6a2c"]))
    if mart:
        market(s, x0, y0, a, b, door, rng)
    if canopy:
        entrance_canopy(s, x0 + a * (door[0] + door[1]) / 2, y0 + b)
    if kind == "brick":                                   # cornice, then the roof on it
        s.box(x0 - 0.03, y0 - 0.03, hgt - 3, a + 0.06, b + 0.06, 4, flat(s, "#cfc6b6"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
        flat_roof(s, x0, y0, a, b, hgt + 1, "#5b5a5c", units=2, rng=rng)
    elif kind == "office" and helipad:
        flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=0, rng=rng)
        draw_helipad(s, x0, y0, a, b, hgt)
    elif kind == "office":                                # machine room and AC units instead
        flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=0, rng=rng)
        s.box(x0 + 0.12, y0 + 0.12, hgt, 0.42, 0.34, 12, flat(s, "#6e6e6e"), flat(s, "#9791a2"), flat(s, "#716f74"))
        for ux, uy in ((x0 + a - 0.36, y0 + 0.16), (x0 + a - 0.36, y0 + 0.46), (x0 + 0.24, y0 + b - 0.36)):
            s.box(ux, uy, hgt, 0.16, 0.16, 7, fan_top(s), flat(s, "#9791a2"), flat(s, "#716f74"))
    else:
        units = roof_units if roof_units is not None else 0 if roof_sign else 2 + (floors > 4)
        flat_roof(s, x0, y0, a, b, hgt, "#6e6e6e", units=units, rng=rng)
    if roof_sign:                                        # lit board on posts, facing the +v street
        bl = a * 0.72
        sx, sy = x0 + (a - bl) / 2, y0 + b * 0.6
        for px in (sx + 0.1, sx + bl - 0.1):
            s.box(px - 0.015, sy - 0.015, hgt, 0.03, 0.03, 7, flat(s, "#716f74"), flat(s, "#8e8897"), flat(s, "#5b5a5c"))
        s.box(sx, sy - 0.03, hgt + 7, bl, 0.06, 15, flat(s, "#6e2420"),
              sign_face(s, roof_sign, bl * HW, 15, "#8a3a32", "#f0d890", "#f2c06a"), flat(s, "#6e2420"))
    if extra:
        extra(s, x0, y0, a, b, hgt)
    s.outline(0.7)
    return s, (a, b)


def draw_helipad(s, x0, y0, sx, sy, z):
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


def entrance_canopy(s, cx, y, width=0.32, depth=0.34, z=25):
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
    "V": ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "Z": ["1111", "0001", "0010", "0110", "0100", "1000", "1111"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "'": ["1", "1", "0", "0", "0", "0", "0"],
    "7": ["1111", "0001", "0010", "0010", "0100", "0100", "0100"],
    " ": ["00"] * 7,
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
        # Read left to right on screen: a turned sprite's face may run the
        # other way along its own axis.
        if len(a) > 1 and xs[a >= 0.5].mean() < xs[a < 0.5].mean():
            a = 1 - a
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


def lounger(seed, color="#3f6f73", rot=0):
    """Beach lounger along u: frame on legs, seat, raised backrest at -u."""
    s = Sprite(100, 70, 50, 46, seed)
    s.rot = rot
    frame = ("#cfc6b6", "#bdb3a2", "#a69c8c")
    for x, y in ((-0.3, -0.13), (0.26, -0.13), (-0.3, 0.1), (0.26, 0.1)):
        s.box(x, y, 0, 0.03, 0.03, 7, *(flat(s, c) for c in frame))
    s.box(-0.31, -0.14, 7, 0.6, 0.28, 2, *(flat(s, c) for c in frame))
    fabric = banded(s, [rgb(color), rgb("#d8ccb4")], 7, axis=0)
    s.face((-0.29, -0.12, 9), (0.58, 0, 0), (0, 0.24, 0), fabric)
    # Backrest, steep enough to read from every side once turned.
    s.face((-0.15, -0.12, 9), (-0.12, 0, 15), (0, 0.24, 0), fabric, light="auto")
    s.outline()
    s.shadow((0.02, 0.02, 0), 26, 9)
    return s


def towel(seed, color="#8f6f9a", rot=0):
    s = Sprite(80, 40, 40, 20, seed)
    s.rot = rot
    s.face((-0.25, -0.12, 0.5), (0.5, 0, 0), (0, 0.24, 0), banded(s, [rgb(color), rgb("#d8ccb4"), rgb(color) * 0.8], 7, axis=0))
    return s


def lifeguard(seed, rot=0):
    """Lifeguard tower facing +v (turned by rot): hut on stilts, ladder."""
    s = Sprite(120, 150, 60, 130, seed)
    s.rot = rot
    white, red = "#cfc6b6", "#8a4a3e"
    for x, y in ((-0.2, -0.2), (0.2, -0.2), (-0.2, 0.2), (0.2, 0.2)):
        s.box(x - 0.02, y - 0.02, 0, 0.04, 0.04, 40, flat(s, white), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    s.box(-0.26, -0.26, 40, 0.52, 0.52, 4, flat(s, "#8a6751"), flat(s, "#765743"), flat(s, "#5f4646"))
    s.box(-0.18, -0.18, 44, 0.36, 0.36, 26, flat(s, white),
          wall_shader(s, white, 26, 26, 1, [(0.2, 0.8)], None, None, "boards"),
          wall_shader(s, white, 26, 26, 1, [(0.2, 0.8)], None, None, "boards"))
    gable(s, -0.18, -0.18, 0.36, 0.36, 70, 12, ramp(red, "#7a3f35"), red, "u", 0.05)
    # Ladder: from the sand in front up to the platform's front edge.
    s.face((-0.06, 0.56, 0), (0.12, 0, 0), (0, -0.3, 40), banded(s, [rgb("#8a6751"), rgb("#5f4646")], 10), light="auto")
    s.outline()
    s.shadow((0.1, 0.1, 0), 36, 14)
    return s


def ripples(s, rx, ry, p, color="#8ec4cc"):
    """Two rings spreading on the water around an object (ellipse radii rx,
    ry in tiles along u, v, turned with the sprite), fading as they grow."""
    dz, s.dz = s.dz, 0.0
    for q in (p % 1, (p + 0.5) % 1):
        grow = 0.05 + 0.22 * q
        n = 40
        for k in range(n):
            if (k * 7919) % 100 < 100 * q * 0.9:                 # thin out as it fades
                continue
            t = 2 * math.pi * k / n
            x, y = (rx + grow) * math.cos(t), (ry + grow) * math.sin(t)
            px, py = s.proj(x, y, 0)
            X, Y = s.R(x, y)
            s.line((px, py), (px + 1, py), rgb(color), X + Y - 0.3)
    s.dz = dz


def rowboat(seed, color="#3f6f73", rot=0, p=None):
    """Rowboat along u (turned by rot). With a phase p it bobs on ripples."""
    s = Sprite(130, 80, 65, 44, seed)
    s.rot = rot
    if p is not None:
        ripples(s, 0.44, 0.16, p)
        s.dz = 1.2 * math.sin(2 * math.pi * p)
    hull, inner = rgb("#cfc6b6"), rgb("#6b553a")
    L, W, H = 0.42, 0.14, 9
    stripe = lambda a, b, xs, ys: np.where((b > 0.55)[:, None] & (b < 0.8)[:, None], rgb(color), hull) + (s.grain[ys, xs] - 0.5)[:, None] * 6
    # sides, all round (depth hides the far ones)
    s.face((-L + 0.12, W, 0), (2 * L - 0.24, 0, 0), (0, 0, H), stripe, light="auto")
    s.face((-L + 0.12, -W, 0), (2 * L - 0.24, 0, 0), (0, 0, H), stripe, light="auto")
    s.face((L - 0.12, W, 0), (0.12, -W, 0), (0, 0, H), stripe, light="auto")
    s.face((L - 0.12, -W, 0), (0.12, W, 0), (0, 0, H), stripe, light="auto")
    s.face((-L + 0.12, W, 0), (-0.12, -W, 0), (0, 0, H), stripe, light="auto")
    s.face((-L + 0.12, -W, 0), (-0.12, W, 0), (0, 0, H), stripe, light="auto")
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


def pier(seed, length=1.0, rot=0):
    """Wooden pier section along u on posts, sitting on water (turned by
    rot: 1 runs it along v, spanning u in [-0.38, 0])."""
    s = Sprite(int(64 * length) + 90, int(32 * length) + 80, 45, 40, seed)
    s.rot = rot
    if rot % 2:                                          # along v it runs off to the left
        s.ox = s.w - 45
    for x in (0.05, length - 0.05):
        for y in (0.02, 0.36):
            s.box(x - 0.025, y - 0.025, -6, 0.05, 0.05, 12, flat(s, "#3e281b"), flat(s, "#4f3423"), flat(s, "#38261b"))
    s.box(0, 0, 6, length, 0.38, 3, banded(s, [rgb("#7c5944"), rgb("#8a6751"), rgb("#6e4c3c")], int(length * 12), axis=0),
          flat(s, "#5f4646"), flat(s, "#4b3931"))
    s.outline(0.75)
    return s


def ring(s, r, z0, h, shader_for, n=20, cx=0.0, cy=0.0):
    """Round wall: an n-sided prism of radius r from z0, h px tall. Each side
    is lit by its facing; shader_for(k) gives side k's shader."""
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    for k in range(n):
        (xa, ya), (xb, yb) = pts[k], pts[(k + 1) % n]
        t = 2 * math.pi * (k + 0.5) / n
        light = 0.62 + 0.28 * max(0.0, math.sin(t)) + 0.12 * max(0.0, math.cos(t))
        s.face((xa, ya, z0), (xb - xa, yb - ya, 0), (0, 0, h), shader_for(k), light=light)


def disk(s, r, z, shader, n=20, cx=0.0, cy=0.0):
    pts = [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    for k in range(n):
        (xa, ya), (xb, yb) = pts[k], pts[(k + 1) % n]
        s.face((cx, cy, z), (xa, ya, 0), (xb, yb, 0), shader, tri=True)


def lighthouse(seed):
    """Classic lighthouse: stone plinth, a tapering white tower with red
    bands, a gallery with a railing, the lit lantern and a red cap. Returns
    the sprite and the lantern's height in px (the game draws the beam)."""
    s = Sprite(140, 260, 70, 225, seed)
    white, red, stone = rgb("#ddd6c8"), rgb("#8a3a32"), rgb("#9c9284")
    # Plinth: two stone steps.
    ring(s, 0.46, 0, 5, lambda k: flat(s, stone * 0.92, 6))
    disk(s, 0.46, 5, flat(s, stone * 1.05, 6))
    ring(s, 0.36, 5, 5, lambda k: flat(s, stone, 6))
    disk(s, 0.36, 10, flat(s, stone * 1.1, 6))
    # Tower: 10 px rings, narrowing from r0 to r1; bands of 20 px.
    z, h, r0, r1 = 10, 120, 0.27, 0.19
    for i in range(h // 10):
        r = r0 + (r1 - r0) * i / (h // 10 - 1)
        col = red if (i // 2) % 3 == 1 else white
        ring(s, r, z + i * 10, 11, lambda k, col=col: flat(s, col, 5))       # 1 px overlap: no seams
    zt = z + h
    # Door and two small windows, facing the camera (+u +v).
    c45 = math.sqrt(0.5)

    def opening(zb, hgt, width, color):
        rr = r0 + (r1 - r0) * (zb - z) / h + 0.01
        s.face((c45 * rr + c45 * width / 2, c45 * rr - c45 * width / 2, zb), (-c45 * width, c45 * width, 0),
               (0, 0, hgt), flat(s, color, 3), light=0.85)
    opening(10, 16, 0.13, "#4f3423")
    opening(58, 8, 0.07, "#2e3336")
    opening(92, 8, 0.07, "#2e3336")
    # Gallery: a wider deck with a thin railing.
    disk(s, 0.28, zt, flat(s, "#5b5a5c", 4))
    ring(s, 0.28, zt - 3, 3, lambda k: flat(s, "#4a494b", 3))
    ring(s, 0.28, zt + 1, 1, lambda k: flat(s, "#2e3336", 2), n=24)
    for k in range(12):
        t = 2 * math.pi * k / 12
        x, y = 0.27 * math.cos(t), 0.27 * math.sin(t)
        s.box(x - 0.01, y - 0.01, zt, 0.02, 0.02, 7, flat(s, "#2e3336"), flat(s, "#2e3336"), flat(s, "#2e3336"))
    ring(s, 0.28, zt + 6, 1, lambda k: flat(s, "#3e4048", 2), n=24)
    # Lantern: lit glass between dark mullions, then the red cap and vent.
    zl = zt + 2
    glow = ramp("#f2c06a", "#f8dc98", "#fff0c4")

    def glass(k):
        def shader(a, b, xs, ys):
            out = np.array(glow)[np.clip((b * 3).astype(int), 0, 2)]
            return np.where((a < 0.18)[:, None], rgb("#2e3336"), out)
        return shader
    ring(s, 0.14, zl, 14, glass, n=10)
    disk(s, 0.17, zl + 14, flat(s, "#6e2420"))
    for i in range(6):                                           # cap: a stepped cone
        ring(s, 0.16 - i * 0.026, zl + 14 + i * 2, 2, lambda k: flat(s, red, 4), n=12)
    s.blob((0, 0, zl + 28), 2.2, ramp("#2e3336", "#4a494b", "#6e6e6e"))
    s.outline(0.7)
    return s, zl + 7


def marram(seed):
    """Dune grass: a tuft of thin, arching blades, green going straw."""
    s = Sprite(40, 40, 20, 30, seed)
    rng = np.random.default_rng(seed)
    cols = [rgb("#6f7a2a"), rgb("#7f8a36"), rgb("#9a9a5a"), rgb("#b0a870")]
    x0, y0 = s.proj(0, 0)
    for _ in range(16):
        ang = rng.uniform(-1.1, 1.1)
        length = rng.uniform(7, 13)
        c = cols[rng.integers(len(cols))]
        for t in np.linspace(0, 1, 14):
            x = x0 + math.sin(ang) * length * t + ang * 2.5 * t * t
            y = y0 - math.cos(ang) * length * t + 3.5 * t * t * abs(ang)
            xi, yi = int(round(x)), int(round(y))
            s._write(np.array([True]), np.array([yi]), np.array([xi]), np.array([0.01 * t]), c[None] * (0.85 + 0.25 * t))
    s.outline(0.8)
    return s


def creeper(seed, flower="#c77aa0", spread=0.2):
    """Low creeping mat of round leaves (beach morning glory, sea daisy),
    dotted with flowers."""
    s = Sprite(60, 40, 30, 22, seed)
    rng = np.random.default_rng(seed)
    for _ in range(22):
        a, r = rng.uniform(0, 2 * math.pi), spread * math.sqrt(rng.random())
        s.blob((r * math.cos(a), r * math.sin(a), 2), rng.uniform(1.8, 2.8), LEAF["green"], squash=0.6, shade=0.1)
    c = rgb(flower)
    for _ in range(9):
        a, r = rng.uniform(0, 2 * math.pi), spread * 0.9 * math.sqrt(rng.random())
        s.blob((r * math.cos(a), r * math.sin(a), 4), 1.3, [c * 0.8, c, np.minimum(c * 1.25, 255)])
    s.outline(0.85)
    return s


# ---------- parking lot ----------

ASPHALT = dict(base="#4a494d", dark="#444347", light="#504f53")


def concrete_tile(seed, stains=False):
    """Poured concrete in slabs with dark joints, a few oil stains."""
    col = np.array(ground(base="#8e8a84", dark="#86827c", light="#96928c", seed=seed))[..., :3].astype(float)
    u, v = uv_of_tile()
    joint = (np.abs(np.mod(u * 2, 1)) < 0.03) | (np.abs(np.mod(v * 2, 1)) < 0.03)
    col[joint] = col[joint] * 0.82
    if stains:
        rng = np.random.default_rng(seed)
        for _ in range(3):
            cu, cv, r = rng.uniform(0.15, 0.85), rng.uniform(0.15, 0.85), rng.uniform(0.05, 0.1)
            m = np.hypot(u - cu, (v - cv)) < r
            col[m] = col[m] * 0.78
    return tile_image(col)


def lot_tile(seed, lines=None, half=None):
    """Asphalt, with white stall lines every half tile across the given
    axis: lines="u" draws lines parallel to u (stalls side by side along
    v), "v" lines parallel to v. half="lo" / "hi" keeps them to the 0.7 of
    the tile at the low / high end of their length (a stall one car deep)."""
    col = np.array(ground(**ASPHALT, seed=seed))[..., :3].astype(float)
    if lines:
        u, v = uv_of_tile()
        t, d = (v, u) if lines == "u" else (u, v)
        paint = np.abs(np.mod(t * 2 + 0.5, 1) - 0.5) < 0.035
        if half == "lo":
            paint &= d < 0.7
        elif half == "hi":
            paint &= d > 0.3
        col[paint] = rgb("#bdb7a8") + (np.random.default_rng(seed).random((paint.sum(), 1)) - 0.5) * 10
    return tile_image(col)


def fence(seed, rot=0):
    """Low metal railing along u, 1 tile long (turned by rot): posts and
    two rails."""
    s = Sprite(110, 80, 20, 30, seed)              # 1 tile runs 64 px across, 32 down
    s.rot = rot
    if rot % 2:
        s.ox = s.w - 20
    metal = [flat(s, c, 3) for c in ("#8e8897", "#716f74", "#5b5a5c")]
    for k in range(5):
        s.box(k * 0.24, 0, 0, 0.03, 0.03, 11, *metal)
    for z in (4, 9):
        s.box(0, 0, z, 1.0, 0.02, 1.6, *metal)
    s.outline(0.8)
    return s


def park_sign(seed):
    """Pole sign for the parking lot: a blue board reading PARK on two
    posts, facing +v (the street)."""
    s = Sprite(110, 130, 55, 100, seed)
    post = [flat(s, c, 3) for c in ("#8e8897", "#716f74", "#5b5a5c")]
    for x in (-0.16, 0.13):
        s.box(x, -0.015, 0, 0.03, 0.03, 34, *post)
    board = 0.5
    s.box(-board / 2, -0.03, 34, board, 0.06, 16, flat(s, "#2b4a6e"),
          sign_face(s, "PARK", board * HW, 16, "#2f5a88", "#e8eef4", "#e8eef4"), flat(s, "#24405e"))
    s.outline(0.75)
    return s


def gate(seed, arm=1, lift=0.0):
    """Parking boom barrier: a control box at the origin and a striped arm
    along u (+u for arm=1, -u for arm=-1), raised by `lift` in [0, 1]."""
    s = Sprite(110, 110, 55, 70, seed)
    s.box(-0.05, -0.05, 0, 0.1, 0.1, 13, flat(s, "#c9a84a"), flat(s, "#5b5a5c"), flat(s, "#4a494b"))
    s.box(-0.05, -0.05, 13, 0.1, 0.1, 2, flat(s, "#2e3336"), flat(s, "#2e3336"), flat(s, "#2e3336"))
    a = lift * math.radians(84)
    L = 0.44
    e1 = (arm * L * math.cos(a), 0, L * math.sin(a) * 71.6)

    def stripes(aa, bb, xs, ys):
        band = np.floor(aa * 6) % 2 == 0
        return np.where(band[:, None], rgb("#8a3a32"), rgb("#ddd6c8")) + (s.grain[ys, xs] - 0.5)[:, None] * 4
    pivot = (arm * 0.03, -0.012, 11)
    s.face(pivot, e1, (0, 0.024, 0), stripes, light=LIGHT["top"])
    s.face((pivot[0], pivot[1] + 0.024, pivot[2]), e1, (0, 0, -2.5), stripes, light=LIGHT["v"])
    s.outline(0.8)
    return s


# ---------- TV station ----------

TOWER_ORANGE, TOWER_WHITE = rgb("#c05a30"), rgb("#ddd6c8")


TV_PODIUM = (4.6, 4.6, 3)                        # studio podium a × b tiles, floors
TV_R0, TV_H = 1.35, 440                          # tower half-width on the roof, px from roof to top belt
TV_CANVAS = (700, 1180, 350, 900)
TV_DECKS = [(172, 24), (316, 22)]                # observation decks: z above the roof, height
LIFT_R = 0.24                                    # elevator shaft half-width
LIFT_STOP_S, LIFT_SPEED = 3.0, 40.0              # s at each floor, px/s between (8 fps frames)
CABIN_H = 18                                     # cabin height, px


def lift_stops():
    """The cabin's stops, z above the ground: inside the studio, the first
    deck, the top deck (it rides the shaft up and back down through them)."""
    roof = TV_PODIUM[2] * FLOOR + 4 + 2
    return [14, roof + TV_DECKS[0][0] + 2, roof + TV_DECKS[-1][0] - 2]


def lift_schedule():
    """(time, z) keyframes for one round trip, waiting LIFT_STOP_S at each
    stop, easing in and out between them."""
    stops = lift_stops()
    route = stops + stops[-2:0:-1]                 # up, then back down to the start
    keys, t = [], 0.0
    for k, z in enumerate(route):
        keys.append((t, z)); t += LIFT_STOP_S; keys.append((t, z))
        nxt = route[(k + 1) % len(route)]
        t += abs(nxt - z) / LIFT_SPEED
    return keys, t


def lift_z(t):
    keys, total = lift_schedule()
    t %= total
    for (t0, z0), (t1, z1) in zip(keys, keys[1:] + [(total, keys[0][1])]):
        if t0 <= t < t1:
            q = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return z0 + (z1 - z0) * q * q * (3 - 2 * q)
    return keys[0][1]


LIFT_FRAMES = int(round(lift_schedule()[1] * 8))   # one round trip at 8 fps


def tv_front(s):
    """What stands out from the podium's front wall: the entrance canopy on
    its posts and the TV 7 sign (also drawn, for depth, under the LED panels)."""
    a, b, floors = TV_PODIUM
    y0 = -b / 2
    s.box(-0.5, y0 + b, 24, 1.0, 0.34, 4, flat(s, "#2b4a6e"), flat(s, "#24405e"), flat(s, "#1e3650"))   # canopy
    for px in (-0.46, 0.43):
        s.box(px, y0 + b + 0.3, 0, 0.03, 0.03, 24, *(flat(s, c) for c in STEEL))
    bl = 1.3
    s.box(-bl / 2, y0 + b - 0.02, floors * FLOOR + 4 - 30, bl, 0.05, 20, flat(s, "#2b4a6e"),
          sign_face(s, "TV 7", bl * HW, 20, "#2f5a88", "#e8eef4", "#f2c06a"), flat(s, "#24405e"))


def tv_station(seed):
    """TV station: a broad three-floor studio podium filling its block, and
    on its roof a lattice broadcast tower (after the Tokyo Tower) whose
    heavy steel legs rise in orange and white bands, braced and belted, past
    two observation decks to a striped mast: the tallest thing in the city."""
    s = Sprite(*TV_CANVAS, seed)
    rng = np.random.default_rng(seed)
    R0, H = TV_R0, TV_H
    a, b, floors = TV_PODIUM
    roof = floors * FLOOR + 4
    x0, y0 = -a / 2, -b / 2

    # Podium: long window bands, a canopy entrance, dishes on the roof.
    wv = wall_shader(s, "#d8d0c0", a * 71.6, roof, floors, [((i + 0.15) / 20, (i + 0.85) / 20) for i in range(20)],
                     (0.46, 0.54), "#8e8680", "plain", glass_door=True)
    wu = wall_shader(s, "#d8d0c0", b * 71.6, roof, floors, [((i + 0.15) / 20, (i + 0.85) / 20) for i in range(20)],
                     None, "#8e8680", "plain")
    s.box(x0, y0, 0, a, b, roof, flat(s, "#d8d0c0"), wv, wu)
    s.box(x0 - 0.04, y0 - 0.04, roof - 3, a + 0.08, b + 0.08, 5, flat(s, "#cfc6b6"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    flat_roof(s, x0, y0, a, b, roof + 2, "#6e6e6e", units=0, rng=rng)
    tv_front(s)
    for dx, dy in ((1.7, -1.7), (-1.6, 1.4), (1.6, 1.2), (-1.7, -1.5)):   # satellite dishes at the roof corners
        s.box(dx - 0.03, dy - 0.03, roof + 2, 0.06, 0.06, 8, *(flat(s, c) for c in STEEL))
        s.blob((dx, dy, roof + 14), 8, ramp("#9a9488", "#c8c2b6", "#e8e2d6"), squash=0.55, shade=0.2)

    z0r = roof + 2                                     # the tower stands on the roof
    half = lambda z: R0 * max(0.0, 1 - z / H) ** 1.7 + 0.14
    band = lambda z: TOWER_WHITE if int(z // 44) % 2 else TOWER_ORANGE

    def beam(p, q, w, color_at):
        """A steel member from p to q (z above the roof): shaded boxes w tiles thick."""
        n = max(2, int(math.dist((p[0] * 64, p[1] * 64, p[2]), (q[0] * 64, q[1] * 64, q[2])) / 1.5))
        for k in range(n + 1):
            t = k / n
            x, y, z = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t)
            c = color_at(z)
            s.box(x - w / 2, y - w / 2, z0r + z - 1, w, w, 2, flat(s, c * 1.05, 3), flat(s, c * 0.95, 3), flat(s, c * 0.8, 3))

    def strut(p, q, color, thick=2):
        (x, y), (x2, y2) = s.proj(p[0], p[1], z0r + p[2]), s.proj(q[0], q[1], z0r + q[2])
        d = (p[0] + p[1] + q[0] + q[1]) / 2
        for off in range(thick):
            s.line((x + off, y), (x2 + off, y2), color * (1.0 if off == 0 else 0.78), d)

    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for cx, cy in corners:                             # foot plates, then the legs
        s.box(cx * R0 - 0.14 + cx * 0.07, cy * R0 - 0.14 + cy * 0.07, z0r, 0.28, 0.28, 6, flat(s, "#8e8680"),
              flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
        for z in range(0, H, 6):
            w = 0.14 - 0.08 * z / H
            beam((cx * half(z), cy * half(z), z), (cx * half(z + 6), cy * half(z + 6), z + 6), w, band)
    for k in range(4):                                 # arches between the legs
        (ax, ay), (bx, by) = corners[k], corners[(k + 1) % 4]
        prev = None
        for t in np.linspace(0, 1, 21):
            z = 18 + 70 * math.sin(math.pi * t)
            h = half(z)
            pt = (ax * h + (bx - ax) * h * t, ay * h + (by - ay) * h * t, z)
            if prev:
                beam(prev, pt, 0.055, lambda z: TOWER_ORANGE)
            prev = pt
    levels = [88, 112, 134, 154, 172, 188, 204, 218, 232, 246, 260, 274, 288, 302, 316, 330, 346, 362, 378, 394,
              410, 426, H]
    # No bracing where the decks are: struts are drawn as lines with one
    # depth, and would show through the deck walls.
    in_deck = lambda z0, z1: any(z0 < dz + dh + 6 and z1 > dz - 6 for dz, dh in TV_DECKS)
    for z0, z1 in zip(levels, levels[1:]):
        if in_deck(z0, z1):
            continue
        h0, h1 = half(z0), half(z1)
        for k in range(4):
            (ax, ay), (bx, by) = corners[k], corners[(k + 1) % 4]
            A0, B0 = (ax * h0, ay * h0, z0), (bx * h0, by * h0, z0)
            A1, B1 = (ax * h1, ay * h1, z1), (bx * h1, by * h1, z1)
            c = band((z0 + z1) / 2) * 0.92
            strut(A0, B1, c)
            strut(B0, A1, c)
            beam(A1, B1, 0.05 if z1 < 250 else 0.036, band)

    def deck(z, r, h):
        wall = lambda length: wall_shader(s, "#c8c2b6", length, h, 1, [((i + 0.15) / 10, (i + 0.85) / 10) for i in range(10)],
                                          None, None, "plain", glass_pal=GLASS_BLUE, floor_h=h + 20)
        z += z0r
        s.box(-r, -r, z, 2 * r, 2 * r, h, flat(s, "#9c9284"), wall(2 * r * 71.6), wall(2 * r * 71.6))
        s.box(-r - 0.04, -r - 0.04, z + h, 2 * r + 0.08, 2 * r + 0.08, 4, flat(s, "#8e8680"), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
        s.box(-r - 0.02, -r - 0.02, z - 3, 2 * r + 0.04, 2 * r + 0.04, 3, flat(s, "#6e6e6e"), flat(s, "#5b5a5c"), flat(s, "#4a494b"))
    # Panoramic elevator: an open steel frame up the middle from the roof to
    # the top deck (its cabin is drawn by tv_lift, over this sprite).
    top = TV_DECKS[-1][0]
    for cx, cy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        s.box(cx * LIFT_R - 0.012, cy * LIFT_R - 0.012, z0r, 0.024, 0.024, top, *(flat(s, c, 2) for c in STEEL))
    for z in range(0, top, 24):
        for k, (ax, ay) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
            bx, by = ((1, -1), (1, 1), (-1, 1), (-1, -1))[k]
            strut((ax * LIFT_R, ay * LIFT_R, z), (bx * LIFT_R, by * LIFT_R, z), rgb("#8e8897"), thick=1)
    for dz, dh in TV_DECKS:
        deck(dz, half(dz) + (0.1 if dz == TV_DECKS[0][0] else 0.08), dh)

    def well(z):
        """The shaft's opening: a dark hole in a steel collar at height z."""
        R, w = LIFT_R + 0.05, 0.06
        s.face((-LIFT_R, -LIFT_R, z + 0.5), (2 * LIFT_R, 0, 0), (0, 2 * LIFT_R, 0), flat(s, "#1e1e22", 2))
        for x, y, sx, sy in ((-R, -R, 2 * R, w), (-R, R - w, 2 * R, w), (-R, -R, w, 2 * R), (R - w, -R, w, 2 * R)):
            s.box(x, y, z, sx, sy, 5, *(flat(s, c) for c in ("#8e8897", "#716f74", "#5b5a5c")))
    well(z0r)                                          # into the studio
    well(z0r + TV_DECKS[0][0] + TV_DECKS[0][1] + 4)    # through the first deck
    for z in range(H, H + 150, 4):                     # mast, striped, red light on top
        w = 0.1 * (1 - (z - H) / 190)
        s.box(-w / 2, -w / 2, z0r + z, w, w, 4, *(flat(s, band(z - H + 22) * k_) for k_ in (1.0, 0.9, 0.75)))
    s.blob((0, 0, z0r + H + 152), 2.6, ramp("#4a1a16", "#6e2420", "#8a2a20"))   # lamp housing (the game lights it)
    s.tip = z0r + H + 152
    s.outline(0.7)
    return s, (a, b)


# ---------- street furniture ----------

BRONZE = ramp("#3e3226", "#5a4630", "#7a5e3a", "#9a7a4a")
STEEL = ("#8e8897", "#716f74", "#5b5a5c")


def bus_stop_fancy(seed, rot=0):
    """Downtown bus shelter open to +v (turned by rot): glass back and
    sides, a dark roof, a bench, a lit ad panel and a BUS sign pole."""
    s = Sprite(140, 120, 70, 80, seed)
    s.rot = rot
    steel = [flat(s, c, 3) for c in STEEL]
    L, D, H = 0.46, 0.2, 26

    def glass(a_, b_, xs, ys):
        edge = (a_ < 0.04) | (a_ > 0.96) | (b_ < 0.06) | (b_ > 0.94)
        pane = np.array(GLASS)[(xs // 2 + ys) % 3] * 1.08
        return np.where(edge[:, None], rgb("#5b5a5c"), pane)
    for x in (-L / 2, L / 2 - 0.02):                   # posts
        for y in (-D / 2, D / 2 - 0.02):
            s.box(x, y, 0, 0.02, 0.02, H, *steel)
    s.face((-L / 2, -D / 2, 2), (L, 0, 0), (0, 0, H - 4), glass, light="auto")              # back
    s.face((-L / 2, -D / 2, 2), (0, D * 0.8, 0), (0, 0, H - 4), glass, light="auto")        # sides
    s.face((L / 2, -D / 2, 2), (0, D * 0.8, 0), (0, 0, H - 4), glass, light="auto")

    def ad(a_, b_, xs, ys):
        poster = ramp("#c8a050", "#d8b870", "#8a4a3e", "#3f6f73")
        return np.array(poster)[((b_ * 4).astype(int) + (a_ * 2).astype(int)) % 4] * 1.1
    s.face((L / 2 - 0.005, -D / 2 + 0.02, 4), (0, D * 0.6, 0), (0, 0, 16), ad, light="auto")
    s.box(-L / 2 + 0.04, -D / 2 + 0.03, 6, L - 0.08, 0.06, 2, flat(s, "#8a6751"), flat(s, "#765743"), flat(s, "#5f4646"))
    s.box(-L / 2 - 0.02, -D / 2 - 0.02, H, L + 0.04, D + 0.06, 3, flat(s, "#2b4636"), flat(s, "#24392d"), flat(s, "#1e3026"))
    # Sign pole at the curb end.
    s.box(L / 2 + 0.06, D / 2, 0, 0.02, 0.02, 34, *steel)
    s.box(L / 2 - 0.05, D / 2 - 0.005, 34, 0.26, 0.03, 10, flat(s, "#2b4a6e"),
          sign_face(s, "BUS", 0.26 * HW, 10, "#2f5a88", "#e8eef4", "#2f5a88"), flat(s, "#24405e"))
    s.outline(0.75)
    return s


def bus_stop_simple(seed, rot=0):
    """Country bus stop facing +v: a timber lean-to with a bench and a
    pole sign."""
    s = Sprite(120, 110, 60, 75, seed)
    s.rot = rot
    wood = [flat(s, c, 6) for c in ("#8a6751", "#765743", "#5f4646")]
    L, D, H = 0.36, 0.16, 22
    for x in (-L / 2, L / 2 - 0.025):
        s.box(x, -D / 2, 0, 0.025, 0.025, H, *wood)
        s.box(x, D / 2 - 0.025, 0, 0.025, 0.025, H - 5, *wood)
    s.face((-L / 2, -D / 2, 1), (L, 0, 0), (0, 0, H - 2), banded(s, [rgb("#765743"), rgb("#6a4e3e")], 6, axis=1), light="auto")
    s.box(-L / 2 + 0.03, -D / 2 + 0.03, 6, L - 0.06, 0.06, 2, *wood)
    s.face((-L / 2 - 0.03, -D / 2 - 0.03, H + 1), (L + 0.06, 0, 0), (0, D + 0.08, -6),
           banded(s, [rgb("#6e4c49"), rgb("#5a3e3a")], 5, axis=0), light="auto")
    s.box(L / 2 + 0.07, D / 2, 0, 0.018, 0.018, 30, *(flat(s, c, 3) for c in STEEL))
    s.blob((L / 2 + 0.08, D / 2 + 0.01, 32), 4, ramp("#2f5a88", "#3f6a98", "#e8eef4"), squash=1.0)
    s.outline(0.75)
    return s


def vending(seed, color="#8a3a32", rot=0):
    """Drinks vending machine facing +v: coloured cabinet, a lit window of
    bottles, buttons and the pick-up slot."""
    s = Sprite(70, 80, 35, 55, seed)
    s.rot = rot
    c = rgb(color)
    a, b, h = 0.2, 0.14, 24

    def front(a_, b_, xs, ys):
        z, x = b_ * h, a_ * a * 71.6
        out = np.repeat(c[None], len(a_), 0)
        win = (z > 9) & (z < 21) & (x > 1.5) & (x < a * 71.6 - 5)
        rows = np.floor((z - 9) / 3)
        bottles = ramp("#e8e2d6", "#c8402a", "#4a8a4a", "#e0c050")
        out = np.where(win[:, None], np.array(bottles)[((xs // 2) + rows.astype(int)) % 4] * 0.95, out)
        out = np.where((win & (np.mod(z - 9, 3) < 0.8))[:, None], rgb("#dde6e8"), out)
        buttons = (z > 11) & (z < 20) & (x >= a * 71.6 - 4) & (x < a * 71.6 - 2) & (np.mod(z, 2) < 1)
        out = np.where(buttons[:, None], rgb("#e8e2d6"), out)
        slot = (z > 2) & (z < 5) & (x > 3) & (x < a * 71.6 - 6)
        return np.where(slot[:, None], rgb("#1e1e22"), out) + (s.grain[ys, xs] - 0.5)[:, None] * 4
    s.box(-a / 2, -b / 2, 0, a, b, h, flat(s, c * 1.1), front, flat(s, c * 0.9))
    if rot:                                             # the far faces show once turned
        s.face((-a / 2, -b / 2, 0), (a, 0, 0), (0, 0, h), flat(s, c * 0.9), light="auto")
        s.face((-a / 2, -b / 2, 0), (0, b, 0), (0, 0, h), flat(s, c * 0.9), light="auto")
    s.outline(0.75)
    return s


def phone_booth(seed, rot=0):
    """Red phone booth with glazed sides and a PHONE sign, door to +v."""
    s = Sprite(80, 110, 40, 85, seed)
    s.rot = rot
    red = rgb("#8a3a32")
    a, h = 0.2, 40

    def pane(a_, b_, xs, ys):
        z = b_ * h
        bars = (np.mod(a_ * 3, 1) < 0.18) | (np.mod(z, 7) < 1.2) | (z < 6) | (z > h - 8)
        return np.where(bars[:, None], red, np.array(GLASS)[(xs + ys) % 3] * 1.1)
    s.box(-a / 2, -a / 2, 0, a, a, h, flat(s, red), pane, pane)
    if rot:
        s.face((-a / 2, -a / 2, 0), (a, 0, 0), (0, 0, h), pane, light="auto")
        s.face((-a / 2, -a / 2, 0), (0, a, 0), (0, 0, h), pane, light="auto")
    s.box(-a / 2 - 0.01, -a / 2 - 0.01, h, a + 0.02, a + 0.02, 4, flat(s, red * 1.1), flat(s, red * 0.95), flat(s, red * 0.85))
    header = lambda a_, b_, xs, ys: np.where(((b_ > 0.3) & (b_ < 0.7) & (np.mod(xs, 2) == 0))[:, None],
                                             rgb("#e8e2d6"), rgb("#1e1e22"))
    s.box(-a / 2 + 0.02, a / 2, h - 7, a - 0.04, 0.01, 5, flat(s, "#1e1e22"), header, flat(s, "#1e1e22"))
    s.outline(0.75)
    return s


def trash_can(seed, kind="green"):
    """Street bins: a green municipal bin with a lid, a wire basket, or a
    blue and green recycling pair."""
    s = Sprite(60, 60, 30, 42, seed)
    if kind == "green":
        ring(s, 0.07, 0, 12, lambda k: banded(s, [rgb("#3d6a3e"), rgb("#34593a")], 4, axis=0), n=12)
        disk(s, 0.075, 12, flat(s, "#2e4a30"), n=12)
        s.blob((0, 0, 14), 2.2, ramp("#2e4a30", "#3d6a3e", "#4a7a4a"), squash=0.5)
    elif kind == "wire":
        def mesh(k):
            def sh(a_, b_, xs, ys):
                grid = (np.mod(xs, 2) == 0) | (np.mod(ys, 3) == 0)
                return np.where(grid[:, None], rgb("#716f74"), rgb("#3a3a3e"))
            return sh
        ring(s, 0.06, 0, 11, mesh, n=10)
        disk(s, 0.05, 1, flat(s, "#2e2e32"), n=10)
    else:
        for dx, col in ((-0.07, "#2f5a88"), (0.07, "#3d6a3e")):
            s.box(dx - 0.05, -0.05, 0, 0.1, 0.1, 12, flat(s, rgb(col) * 0.8), flat(s, col), flat(s, rgb(col) * 0.85))
            s.box(dx - 0.055, -0.055, 12, 0.11, 0.11, 2, flat(s, rgb(col) * 0.7), flat(s, rgb(col) * 0.8), flat(s, rgb(col) * 0.7))
    s.outline(0.75)
    return s


def statue(seed, kind="figure"):
    """Monuments for squares and parks: a bronze figure with a raised arm,
    or a stone obelisk, on a stepped stone plinth."""
    s = Sprite(90, 150, 45, 120, seed)
    stone = [flat(s, c, 5) for c in ("#d8d0c0", "#bdb3a2", "#a69c8c")]
    s.box(-0.2, -0.2, 0, 0.4, 0.4, 4, *stone)
    s.box(-0.14, -0.14, 4, 0.28, 0.28, 22, *stone)
    s.box(-0.16, -0.16, 26, 0.32, 0.32, 3, *stone)
    if kind == "figure":
        br = [flat(s, BRONZE[k], 4) for k in (3, 2, 1)]        # standing figure, right arm raised
        for dy in (-0.03, 0.02):
            s.box(-0.02, dy, 29, 0.035, 0.035, 11, *br)         # legs
        s.box(-0.035, -0.045, 40, 0.07, 0.1, 13, *br)           # coat
        s.box(-0.02, -0.07, 44, 0.03, 0.03, 8, *br)             # left arm, down
        s.blob((0, 0, 57), 3, BRONZE)                           # head
        for k in range(10):                                     # right arm, up and forward
            s.box(0.0 + k * 0.004, 0.055, 51 + k * 1.3, 0.03, 0.03, 2, *br)
    else:
        for z in range(29, 90, 3):                               # obelisk
            w = 0.1 * (1 - (z - 29) / 80)
            s.box(-w / 2, -w / 2, z, w, w, 3, *stone)
        s.blob((0, 0, 92), 1.6, ramp("#a69c8c", "#d8d0c0", "#e8e2d6"))
    s.outline(0.72)
    return s


def text_bits(text):
    """Pixel-font bitmap (7 rows) of text, one blank column between letters."""
    cols = []
    for ch in text:
        g = GLYPHS[ch]
        cols += [[row[k] == "1" for row in g] for k in range(len(g[0]))] + [[False] * 7]
    return np.array(cols[:-1]).T


def stamp(out, col, row, bits, x0, y0, color, scale=1):
    """Paint bits (scaled) with its top-left at panel px (x0, y0)."""
    bx, by = np.floor((col - x0) / scale).astype(int), np.floor((row - y0) / scale).astype(int)
    ok = (bx >= 0) & (bx < bits.shape[1]) & (by >= 0) & (by < bits.shape[0])
    hit = np.zeros(len(col), bool)
    hit[ok] = bits[by[ok], bx[ok]]
    return np.where(hit[:, None], rgb(color), out)


AD_FRAMES = 48                                   # 3 ads × 16 frames, 2 s each at 8 fps


def led_ad(s, k, t, L, Hp):
    """LED billboard shader for ad k (0 cola, 1 chips, 2 TV show) at local
    phase t in [0, 1), on an L × Hp px panel; TV static on the last frame."""
    def shader(a, b, xs, ys):
        if len(a) > 1 and xs[a >= 0.5].mean() < xs[a < 0.5].mean():          # read left to right
            a = 1 - a
        col, row = a * L, (1 - b) * Hp
        n = len(a)
        sc = 2 if Hp > 50 else 1                                         # letter size
        if t > 0.94:                                                     # static between ads
            g = s.rng.random(n) * 180 + 40
            return np.stack([g, g, g], 1)
        if k == 0:                                                       # COLA
            out = np.repeat(rgb("#b02a24")[None], n, 0)
            wave = np.abs(row - (Hp * 0.72 + 3 * np.sin(col * 0.09 + t * 6.283))) < 1.6
            out = np.where(wave[:, None], rgb("#f0ece4"), out)
            bx = L * 0.2
            body = (np.abs(col - bx) < 5) & (row > Hp * 0.38) & (row < Hp * 0.92)
            neck = (np.abs(col - bx) < 2 + (row - Hp * 0.18) / (Hp * 0.2) * 3) & (row > Hp * 0.18) & (row <= Hp * 0.38)
            cap = (np.abs(col - bx) < 2.2) & (row > Hp * 0.12) & (row <= Hp * 0.18)
            out = np.where((body | neck)[:, None], rgb("#3a1e14"), out)
            out = np.where(((body | neck) & (col - bx > 2) & (col - bx < 3.5))[:, None], rgb("#8a5a3a"), out)
            out = np.where((body & (row > Hp * 0.55) & (row < Hp * 0.7))[:, None], rgb("#f0ece4"), out)
            out = np.where(cap[:, None], rgb("#c8402a"), out)
            out = stamp(out, col, row, text_bits("COLA"), L * 0.4, Hp * 0.22 - 2 * t, "#f0ece4", sc)
        elif k == 1:                                                     # CHIPS
            out = np.repeat(rgb("#e0b040")[None], n, 0)
            bx0, bx1 = L * 0.1, L * 0.34
            zig = Hp * 0.16 + 2 * (np.floor(col / 3) % 2)
            bag = (col > bx0) & (col < bx1) & (row > zig) & (row < Hp * 0.9)
            out = np.where(bag[:, None], rgb("#c8502a"), out)
            out = np.where((bag & (row > Hp * 0.42) & (row < Hp * 0.62))[:, None], rgb("#f0d890"), out)
            for cx, cy, r in ((0.45, 0.72, 5), (0.55, 0.6, 4), (0.5, 0.85, 3.5)):          # chips flying out
                cy = cy - 0.08 * math.sin(t * 6.283 + cx * 9)
                d = np.hypot(col - L * cx, (row - Hp * cy) * 1.3)
                out = np.where((d < r)[:, None], rgb("#e8c86a"), out)
                out = np.where(((d >= r - 1) & (d < r))[:, None], rgb("#a8782a"), out)
            out = stamp(out, col, row, text_bits("CHIPS"), L * 0.58, Hp * 0.2, "#8a2a20", sc)
        else:                                                            # TV show promo
            out = np.repeat(rgb("#1e2a4a")[None], n, 0) * (0.8 + 0.4 * b[:, None])
            beam = np.abs((col - L * (0.3 + 0.2 * math.sin(t * 6.283))) - (row - Hp) * 0.5) < 5
            out = np.where(beam[:, None], out * 1.6, out)
            px = L * 0.22
            head = np.hypot(col - px, row - Hp * 0.42) < 5
            body = (np.hypot((col - px) / 1.6, row - Hp * 0.95) < 9) & (row < Hp)
            out = np.where((head | body)[:, None], rgb("#0e1320"), out)
            out = stamp(out, col, row, text_bits("NEWS 7"), L * 0.4, Hp * 0.18, "#f0ece4", sc)
            live = (col > L * 0.42) & (col < L * 0.42 + 26) & (row > Hp * 0.62) & (row < Hp * 0.62 + 11)
            if int(t * 16) % 4 < 3:
                out = np.where(live[:, None], rgb("#c8402a"), out)
                out = stamp(out, col, row, text_bits("LIVE"), L * 0.42 + 3, Hp * 0.62 + 2, "#f0ece4", 1)
        return np.where(((xs + ys) % 2 == 0)[:, None], out, out * 0.8)       # LED dot pitch
    return shader


def tv_lift(seed, f, depth):
    """Frame f of the elevator cabin riding the tower's shaft, drawn over the
    station: `depth` is the station's own depth buffer, so the studio, legs
    and decks in front hide it (inside the studio it is out of sight)."""
    s = Sprite(*TV_CANVAS, seed)
    s.depth = depth.copy()
    z = lift_z(f / 8)
    r = LIFT_R - 0.04

    def glass(a_, b_, xs, ys):
        frame = (a_ < 0.12) | (a_ > 0.88) | (b_ < 0.1) | (b_ > 0.9)
        rail = np.abs(b_ - 0.45) < 0.06
        pane = np.array(GLASS_BLUE)[(xs // 2 + ys) % 4] * 1.25
        out = np.where(rail[:, None], rgb("#c8c2b6"), pane)
        return np.where(frame[:, None], rgb("#b8964a"), out)
    s.box(-r, -r, z, 2 * r, 2 * r, CABIN_H, flat(s, "#8a6a2e"), glass, glass)
    s.box(-r - 0.01, -r - 0.01, z + CABIN_H, 2 * r + 0.02, 2 * r + 0.02, 3, *(flat(s, c) for c in ("#b8964a", "#a08238", "#86692c")))
    s.alpha[s.depth == depth] = 0                   # keep only the cabin, where it is in front
    return s


def tv_ads(seed, f, side):
    """One frame (f of AD_FRAMES) of a TV station LED panel, drawn over the
    station (same origin): side=True the big wall on the podium's +u side,
    else the front panel by the entrance and the scrolling ticker."""
    s = Sprite(*TV_CANVAS, seed)
    a, b, floors = TV_PODIUM
    x0, y0 = -a / 2, -b / 2
    per = AD_FRAMES // 3
    tv_front(s)                                       # in the depth buffer only: it hides what it covers
    before = s.depth.copy()
    if side:
        k, t = f // per, (f % per) / per
        L, Hp = (b - 1.8) * 71.6, 70
        s.face((x0 + a + 0.005, y0 + 0.9, 16), (0, b - 1.8, 0), (0, 0, Hp), led_ad(s, k, t, L, Hp), light=1.0)
    else:
        g = (f + per) % AD_FRAMES                      # a different ad than the side wall
        k, t = g // per, (g % per) / per
        L, Hp = 1.3 * 71.6, 34
        s.face((x0 + 0.35, y0 + b + 0.005, 8), (1.3, 0, 0), (0, 0, Hp), led_ad(s, k, t, L, Hp), light=1.0)
        bits = text_bits("TV 7 NEWS   ")
        shift = int(f / AD_FRAMES * bits.shape[1] * 3)

        def ticker(a_, b_, xs, ys):
            row = np.clip((7 - b_ * 9).astype(int), 0, 6)
            col = (xs + shift) % bits.shape[1]
            on = bits[row, col] & (b_ > 0.1) & (b_ < 0.88)
            return np.where(on[:, None], rgb("#f2c06a"), rgb("#2a1e14"))
        s.face((0.85, y0 + b + 0.005, 52), (a / 2 - 1.1, 0, 0), (0, 0, 9), ticker, light=1.0)   # right of the sign
    s.alpha[s.depth == before] = 0                    # keep only the panel pixels in front
    return s


# ---------- Cat's: gas station and supermarket ----------

# The mascot for the Cat's sign: a cat-eared girl, dark wavy hair, blue
# eyes, white collar (an original pixel drawing, 20 × 20).
MASCOT = [
    "..K.............K...",
    "..KK...........KK...",
    "..KEK.KKKKKKK.KEK...",
    "..KEEKKKKKKKKKKEEK..",
    ".KKKKKKKHHKKKKKKKK..",
    ".KKKKHKKKKKKKKHKKKK.",
    "KKKKKKKKKKKKKKKKKKK.",
    "KKKSKKSSKKKSSKKSKKK.",
    "KKSSSSSSSSSSSSSSSKK.",
    "KKSLLLSSSSSSLLLSSKK.",
    "KKSWIIWSSSSWIIWSSKK.",
    "KKSIPPISSSSIPPISSKK.",
    "KKSIIIISSSSIIIISSKK.",
    "KKSBSSSSSSSSSSBSSKK.",
    ".KKSSSSSSMSSSSSSKK..",
    ".KKKSSSSSSSSSSSKKKK.",
    "KKK.SSSSSSSSSSS.KKK.",
    "KK..CCCSSSSSCCC..KK.",
    "K...CCCCCCCCCCC...K.",
    "....CCCCCCCCCCC.....",
]
MASCOT_PAL = {"K": "#1e1e28", "H": "#40404e", "E": "#6a5a7a", "S": "#f0d8c8", "B": "#e8a0a0", "W": "#f4f4f4",
              "I": "#3a5a9a", "P": "#1a2a4a", "L": "#1e1e28", "M": "#b0605a", "C": "#f0ece4"}
# "Cat's" in a chunky script: 7 rows, slanted when drawn.
WORD = {
    "C": [".XXXX.", "XX..XX", "XX....", "XX....", "XX....", "XX..XX", ".XXXX."],
    "a": ["......", "......", ".XXXX.", "....XX", ".XXXXX", "XX..XX", ".XXXXX"],
    "t": [".XX...", ".XX...", "XXXXX.", ".XX...", ".XX...", ".XX.XX", "..XXX."],
    "'": ["XX", "XX", "X.", "..", "..", "..", ".."],
    "s": [".....", ".....", ".XXXX", "XX...", ".XXX.", "...XX", "XXXX."],
}


def cats_face(W, H):
    """The Cat's sign face, H rows × W columns: dark board, bulb border, the
    mascot on top, the Cat's wordmark below with a cat tail curling under."""
    img = np.zeros((H, W, 3))
    img[:] = rgb("#efe3c4")
    def put(x, y, c):
        if 0 <= x < W and 0 <= y < H:
            img[y, x] = rgb(c)
    mx, my = (W - 40) // 2, 2                       # mascot, at 2×
    for r, line in enumerate(MASCOT):
        for c, ch in enumerate(line):
            if ch != ".":
                for dy in (0, 1):
                    for dx in (0, 1):
                        put(mx + 2 * c + dx, my + 2 * r + dy, MASCOT_PAL[ch])
    word = "Cat's"
    width = sum(len(WORD[ch][0]) + 1 for ch in word) - 1
    wx, wy = (W - width) // 2 + 1, my + 41
    x = wx
    ink = np.zeros((H, W), bool)
    for ch in word:
        g = WORD[ch]
        for r, line in enumerate(g):
            for c, bit in enumerate(line):
                if bit == "X":
                    xx, yy = x + c + (6 - r) // 3, wy + r            # slanted
                    if 0 <= xx < W and 0 <= yy < H:
                        ink[yy, xx] = True
        x += len(g[0]) + 1
    # Tail: from under the s, sweeping left under the word and curling up.
    end = x - 1
    for k in range(60):
        t = k / 59
        tx = end - t * (width + 2)
        ty = wy + 9 + 1.5 * math.sin(math.pi * t)
        if t > 0.82:                                                 # the curl at the tip
            q = (t - 0.82) / 0.18
            tx -= 2 * math.sin(q * math.pi)
            ty -= 4 * q
        for dy in ((0, 1) if t < 0.7 else (0,)):
            yy, xx = int(round(ty)) + dy, int(round(tx))
            if 0 <= xx < W and 0 <= yy < H:
                ink[yy, xx] = True
    outline = np.zeros_like(ink)
    outline[1:] |= ink[:-1]; outline[:-1] |= ink[1:]; outline[:, 1:] |= ink[:, :-1]; outline[:, :-1] |= ink[:, 1:]
    img[outline & ~ink] = rgb("#5a1e14")
    img[ink] = rgb("#c8402a")
    img[ink & (np.arange(H)[:, None] < wy + 3)] = rgb("#e0604a")
    edge = np.zeros((H, W), bool)                   # bulbs round the edge
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    img[edge] = rgb("#8a2a1a")
    ys, xs = np.nonzero(edge)
    dots = (xs + ys) % 2 == 0
    img[ys[dots], xs[dots]] = rgb("#f8dc98")
    return img


def texture(s, tex):
    """Shader showing an image across a face, read left to right on screen."""
    H, W = tex.shape[:2]

    def shader(a, b, xs, ys):
        if len(a) > 1 and xs[a >= 0.5].mean() < xs[a < 0.5].mean():
            a = 1 - a
        col = np.clip((a * W).astype(int), 0, W - 1)
        row = np.clip(((1 - b) * H).astype(int), 0, H - 1)
        return tex[row, col] + (s.grain[ys, xs] - 0.5)[:, None] * 3
    return shader


def cats_sign(seed):
    """The Cat's pylon: a four-sided lit cabinet on a tall column."""
    s = Sprite(140, 260, 70, 220, seed)
    w, H0, Hc = 0.8, 96, 60
    s.box(-0.14, -0.14, 0, 0.28, 0.28, 6, *(flat(s, c) for c in ("#bdb3a2", "#a69c8c", "#8e8680")))
    s.box(-0.07, -0.07, 6, 0.14, 0.14, H0 - 6, *(flat(s, c, 3) for c in ("#5b5a5c", "#4a494b", "#3e3d3f")))
    face = texture(s, cats_face(int(w * HW), Hc))
    s.box(-w / 2, -w / 2, H0, w, w, Hc, flat(s, "#1a1628"), face, face)
    s.box(-w / 2 - 0.03, -w / 2 - 0.03, H0 + Hc, w + 0.06, w + 0.06, 4, flat(s, "#c8402a"), flat(s, "#a8321f"), flat(s, "#8a2a1a"))
    s.box(-w / 2 - 0.02, -w / 2 - 0.02, H0 - 4, w + 0.04, w + 0.04, 4, flat(s, "#c8402a"), flat(s, "#a8321f"), flat(s, "#8a2a1a"))
    s.outline(0.8)
    return s


def supermarket(seed):
    """Cat's Mart: a wide one-storey supermarket, glass storefront with
    automatic doors, a lit CAT'S MART fascia, AC units on the roof."""
    rng = np.random.default_rng(seed)
    s = Sprite(420, 260, 210, 170, seed)
    a, b, h = 4.0, 1.8, 38
    x0, y0 = -a / 2, -b / 2
    wv = wall_shader(s, "#d8d0c0", a * 71.6, h, 1, [], (0.45, 0.55), "#8e8680", "plain", glass_door=True,
                     storefront="#2a2440", floor_h=h)
    wu = wall_shader(s, "#d8d0c0", b * 71.6, h, 1, [], None, "#8e8680", "plain")
    s.box(x0, y0, 0, a, b, h, flat(s, "#d8d0c0"), wv, wu)
    flat_roof(s, x0, y0, a, b, h, "#6e6e6e", units=4, rng=rng)
    bl = 1.6
    s.box(-bl / 2, y0 + b - 0.01, h, bl, 0.05, 13, flat(s, "#2a2440"),
          sign_face(s, "CAT'S MART", bl * HW, 13, "#2a2440", "#f2c06a", "#f8dc98"), flat(s, "#1a1628"))
    s.outline(0.7)
    return s, (a, b)


def gas_canopy(seed):
    """Fuel canopy over a pump island: four columns, a deep roof with a lit
    brand band, two pumps with screens and hoses on a raised island."""
    s = Sprite(240, 200, 120, 130, seed)
    a, b, h = 1.4, 2.4, 40
    x0, y0 = -a / 2, -b / 2
    # Island along v near the +u edge, two pumps.
    ix = x0 + a - 0.36
    s.box(ix - 0.12, y0 + 0.35, 0, 0.24, b - 0.7, 3, flat(s, "#d8d0c0"), flat(s, "#c9a84a"), flat(s, "#bdb3a2"))
    for py in (y0 + 0.7, y0 + b - 0.9):
        s.box(ix - 0.07, py, 3, 0.14, 0.2, 16, flat(s, "#c8402a"), flat(s, "#d8d0c0"), flat(s, "#b0341f"))
        s.box(ix + 0.071, py + 0.05, 11, 0.001, 0.1, 5, flat(s, "#3a5a9a"), flat(s, "#3a5a9a"), flat(s, "#5aa0d0"))   # screen
        s.box(ix + 0.07, py + 0.15, 6, 0.02, 0.02, 7, flat(s, "#2e3336"), flat(s, "#2e3336"), flat(s, "#2e3336"))    # hose
    for cx, cy in ((x0 + 0.1, y0 + 0.2), (x0 + a - 0.14, y0 + 0.2), (x0 + 0.1, y0 + b - 0.24), (x0 + a - 0.14, y0 + b - 0.24)):
        s.box(cx, cy, 0, 0.05, 0.05, h, *(flat(s, c) for c in ("#d8d0c0", "#bdb3a2", "#a69c8c")))
    band = lambda length: (lambda a_, b_, xs, ys: np.where(((b_ > 0.35) & (b_ < 0.65))[:, None], rgb("#f2c06a"),
                                                          rgb("#2a2440")) + (s.grain[ys, xs] - 0.5)[:, None] * 4)
    s.box(x0 - 0.05, y0 - 0.05, h, a + 0.1, b + 0.1, 8, flat(s, "#bdb3a2"), band(a), band(b))
    s.outline(0.75)
    return s, (a, b)


def cart(seed, rot=0):
    """Shopping cart: wire basket on a frame with small wheels, handle at -u."""
    s = Sprite(50, 44, 25, 30, seed)
    s.rot = rot
    wire = lambda a_, b_, xs, ys: np.where(((xs % 2 == 0) | (ys % 2 == 0))[:, None], rgb("#c8c2b6"), rgb("#6e6e74"))
    s.box(-0.12, -0.07, 4, 0.24, 0.14, 7, wire, wire, wire)
    if rot:
        s.face((-0.12, -0.07, 4), (0.24, 0, 0), (0, 0, 7), wire, light="auto")
        s.face((-0.12, -0.07, 4), (0, 0.14, 0), (0, 0, 7), wire, light="auto")
    s.box(-0.15, -0.07, 10, 0.03, 0.14, 1, *(flat(s, "#c8402a") for _ in range(3)))       # handle
    for x in (-0.1, 0.09):
        for y in (-0.06, 0.05):
            s.box(x, y, 0, 0.02, 0.02, 3, *(flat(s, "#2e3336") for _ in range(3)))
    s.outline(0.85)
    return s


def boxes(seed):
    """A small stack of cardboard boxes."""
    s = Sprite(60, 60, 30, 42, seed)
    rng = np.random.default_rng(seed)
    card = ("#b08a5a", "#9a7648", "#86653c")
    for x, y, z, w, d, h in ((-0.12, -0.08, 0, 0.16, 0.14, 8), (0.05, -0.06, 0, 0.12, 0.12, 7),
                             (-0.09, -0.05, 8, 0.13, 0.11, 7), (-0.02, 0.07, 0, 0.1, 0.1, 5)):
        s.box(x, y, z, w, d, h, *(flat(s, rgb(c) * rng.uniform(0.92, 1.05), 4) for c in card))
    s.outline(0.8)
    return s


def big_dumpster(seed):
    """Big blue trash container with two lids and a side drain."""
    s = Sprite(90, 70, 45, 46, seed)
    blue = ("#3f6a98", "#2f5a88", "#244870")
    s.box(-0.26, -0.15, 2, 0.52, 0.3, 16, *(flat(s, c, 5) for c in blue))
    s.box(-0.27, -0.16, 18, 0.26, 0.32, 2, flat(s, "#2a4a70"), flat(s, "#24405e"), flat(s, "#1e3650"))
    s.box(0.01, -0.16, 18, 0.26, 0.32, 3, flat(s, "#2e5078"), flat(s, "#24405e"), flat(s, "#1e3650"))
    for x in (-0.22, 0.2):
        s.box(x, -0.12, 0, 0.03, 0.24, 2, *(flat(s, "#2e3336") for _ in range(3)))
    s.outline(0.78)
    return s


# ---------- plaza shops: pizza, bistro, cakes, toys ----------

def cutout(tex):
    """RGBA shader showing an H × W × 4 image across a face (alpha 0 = hole),
    read left to right on screen."""
    H, W = tex.shape[:2]

    def shader(a, b, xs, ys):
        if len(a) > 1 and xs[a >= 0.5].mean() < xs[a < 0.5].mean():
            a = 1 - a
        col = np.clip((a * W).astype(int), 0, W - 1)
        row = np.clip(((1 - b) * H).astype(int), 0, H - 1)
        return tex[row, col].astype(float)
    return shader


def pizza_tex(D=30):
    """A pizza seen face on, a slice missing (to the upper right)."""
    t = np.zeros((D, D, 4))
    ys, xs = np.mgrid[0:D, 0:D]
    cx = cy = (D - 1) / 2
    r = np.hypot(xs - cx, ys - cy)
    ang = np.degrees(np.arctan2(-(ys - cy), xs - cx))
    gone = (ang > 15) & (ang < 70)
    disc = (r <= D / 2 - 0.5) & ~gone
    t[disc] = [*rgb("#f0c850"), 255]
    t[disc & (r > D / 2 - 3)] = [*rgb("#c8843a"), 255]                    # crust
    t[disc & (r > D / 2 - 1.5)] = [*rgb("#a0662a"), 255]
    rng = np.random.default_rng(7)
    for _ in range(9):                                                   # pepperoni
        a, rr = rng.uniform(0, 360), rng.uniform(2, D / 2 - 5)
        if 12 < a < 73:
            continue
        px, py = cx + rr * math.cos(math.radians(a)), cy - rr * math.sin(math.radians(a))
        m = (np.hypot(xs - px, ys - py) < 2.2) & disc & (r < D / 2 - 3)
        t[m] = [*rgb("#b0341f"), 255]
    for _ in range(6):                                                   # basil
        a, rr = rng.uniform(0, 360), rng.uniform(2, D / 2 - 5)
        px, py = int(cx + rr * math.cos(math.radians(a))), int(cy - rr * math.sin(math.radians(a)))
        if disc[py, px] and r[py, px] < D / 2 - 3:
            t[py, px] = [*rgb("#3d6a3e"), 255]
    return t


def cake_tex(W=26, H=30):
    """A three-tier cake with drips of icing and a cherry on top."""
    t = np.zeros((H, W, 4))
    def rect(x0, y0, x1, y1, c):
        t[y0:y1, x0:x1] = [*rgb(c), 255]
    rect(1, 18, W - 1, H - 1, "#e8a0b8")                                # bottom tier
    rect(1, 17, W - 1, 20, "#fff4f0")
    for x in range(2, W - 2, 3):
        rect(x, 20, x + 1, 22 + (x % 2), "#fff4f0")                    # drips
    rect(5, 10, W - 5, 18, "#fff4f0")                                   # middle
    rect(5, 9, W - 5, 11, "#e8a0b8")
    rect(9, 3, W - 9, 10, "#e8a0b8")                                    # top
    rect(9, 2, W - 9, 4, "#fff4f0")
    cx = W // 2
    rect(cx - 1, 0, cx + 2, 3, "#c8302a")                               # cherry
    rect(cx + 1, 0, cx + 2, 1, "#3d6a3e")
    rect(1, H - 2, W - 1, H - 1, "#c89aa8")
    return t


def roof_board(s, x0, y0, a, b, hgt, text, board, ink, w=0.9, z=6, tex=None, tex_w=0.5, tex_h=30, tex_dy=0.01):
    """A lit text board on two posts over the front of a roof, facing +v,
    with an optional cut-out picture standing on it."""
    sx, sy = x0 + (a - w) / 2, y0 + b * 0.62
    for px in (sx + 0.1, sx + w - 0.1):
        s.box(px - 0.015, sy - 0.015, hgt, 0.03, 0.03, z, *(flat(s, c) for c in STEEL))
    s.box(sx, sy - 0.03, hgt + z, w, 0.06, 12, flat(s, rgb(board) * 0.8),
          sign_face(s, text, w * HW, 12, board, ink, "#f8dc98"), flat(s, rgb(board) * 0.7))
    if tex is not None:
        s.face((x0 + (a - tex_w) / 2, sy + tex_dy, hgt + z + 12), (tex_w, 0, 0), (0, 0, tex_h), cutout(tex), light=1.0)


def croissant_tex(W=34, H=20):
    """A golden croissant: a crescent of rolled segments, shaded."""
    t = np.zeros((H, W, 4))
    ys, xs = np.mgrid[0:H, 0:W]
    cx, cy = (W - 1) / 2, H * 1.25
    r = np.hypot(xs - cx, (ys - cy) * 1.25)
    ang = np.degrees(np.arctan2(-(ys - cy), xs - cx))                  # 90 at the top
    half = 20 - 13 * np.abs(ang - 90) / 75                             # plump in the middle, tapered tips
    body = (np.abs(r - H * 0.8) < half * 0.5) & (np.abs(ang - 90) < 75)
    seg = np.floor((ang - 18) / 144 * 7) % 2 == 0
    col = np.where(seg[..., None], rgb("#d8943a"), rgb("#c07a2a"))
    col = np.where(((r - H * 0.8) < -half * 0.15)[..., None], col * 1.18, col)    # lit upper edge
    t[..., :3] = np.minimum(col, 255)
    t[..., 3] = np.where(body, 255, 0)
    edge = body & ~(np.roll(body, 1, 0) & np.roll(body, -1, 0) & np.roll(body, 1, 1) & np.roll(body, -1, 1))
    t[edge, :3] = rgb("#7a4a1a")
    return t


def bakery(seed):
    """Bakery: warm cream front, brown awning, a BAKERY board with a big
    croissant standing on it, and a bread rack by the door."""
    def extra(s, x0, y0, a, b, hgt):
        roof_board(s, x0, y0, a, b, hgt, "BAKERY", "#6a4a2a", "#f8e4b0", w=1.0, tex=croissant_tex(), tex_w=0.53, tex_h=20,
                   tex_dy=0.05)
        rx, ry = x0 + a * 0.18, y0 + b + 0.06                            # bread rack outside
        s.box(rx, ry, 0, 0.22, 0.08, 12, *(flat(s, c) for c in ("#8a6751", "#765743", "#5f4646")))
        for k in range(3):
            s.blob((rx + 0.05 + k * 0.06, ry + 0.04, 13), 2.2, ramp("#a8702a", "#c8843a", "#e0a860"), squash=0.6)
    return building(seed, "shop", a=1.2, b=0.9, floors=2, wall="#efe0c0", awning_col="#6a4a2a", roof_units=0, extra=extra)


def pizza_place(seed):
    extra = lambda s, x0, y0, a, b, hgt: roof_board(s, x0, y0, a, b, hgt, "PIZZA", "#3d6a3e", "#f0ece4",
                                                   tex=pizza_tex(), tex_w=0.47, tex_h=30)
    return building(seed, "shop", a=1.4, b=1.0, floors=2, wall="#e8dcc4", awning_col="#b0341f", roof_units=0, extra=extra)


def cake_shop(seed):
    extra = lambda s, x0, y0, a, b, hgt: roof_board(s, x0, y0, a, b, hgt, "CAKES", "#e890b0", "#fff4f0",
                                                   tex=cake_tex(), tex_w=0.41, tex_h=30)
    return building(seed, "shop", a=1.2, b=0.9, floors=2, wall="#f0d0dc", awning_col="#e890b0", roof_units=0, extra=extra)


def bistro(seed):
    """Bistro: dark green front, a BISTRO board over the awning, and on the
    +u side a patio with umbrella tables, planters, a chalkboard and string
    lights between two posts."""
    def extra(s, x0, y0, a, b, hgt):
        s.box(x0 + a * 0.2, y0 + b, 35, a * 0.6, 0.03, 9, flat(s, "#1e2a24"),
              sign_face(s, "BISTRO", a * 0.6 * HW, 9, "#1e2a24", "#f0d890", "#f2c06a"), flat(s, "#1e2a24"))
        px = x0 + a
        s.box(px, y0 + 0.05, 0, 0.55, b - 0.05, 1, flat(s, "#b89a78"), flat(s, "#a0826a"), flat(s, "#8a6e58"))   # deck
        for ty, col in ((y0 + 0.25, "#3d6a3e"), (y0 + b - 0.25, "#8a3a32")):
            patio_table(s, px + 0.28, ty, col)
        for yy in (y0 + 0.07, y0 + b - 0.12):                            # planters
            s.box(px + 0.44, yy, 1, 0.1, 0.1, 5, *(flat(s, c) for c in ("#8a6751", "#765743", "#5f4646")))
            s.blob((px + 0.49, yy + 0.05, 9), 3.2, LEAF["green"], shade=0.1)
        # Chalkboard by the door.
        s.face((x0 + a * 0.72, y0 + b + 0.12, 0), (0.1, 0, 0), (0, -0.04, 10), flat(s, "#2a2e2a"), light=0.95)
        # String lights between two posts at the patio's outer corners.
        for yy in (y0 + 0.03, y0 + b - 0.03):
            s.box(px + 0.52, yy, 0, 0.02, 0.02, 30, *(flat(s, c) for c in ("#5f4646", "#4b3931", "#3e2f29")))
        p0, p1 = s.proj(px + 0.53, y0 + 0.04, 30), s.proj(px + 0.53, y0 + b - 0.02, 30)
        for k in range(15):
            t = k / 14
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t + 4 * math.sin(math.pi * t)
            s.line((x, y), (x, y), rgb("#3e2f29") if k % 2 else rgb("#f8dc98"), px + 0.6 + t)
    return building(seed, "shop", a=1.3, b=0.95, floors=2, wall="#4a6050", awning_col="#8a3a32", extra=extra)


def toy_shop(seed):
    """Toy shop: sunny yellow front, a TOYS board, balloons tied on the roof."""
    def extra(s, x0, y0, a, b, hgt):
        roof_board(s, x0, y0, a, b, hgt, "TOYS", "#3a5a9a", "#f2c06a", w=0.7)
        for k, col in enumerate(("#c8402a", "#3a8a4a", "#3a5a9a", "#e0a040")):
            bx, by = x0 + a * 0.2 + k * 0.05, y0 + b * 0.2 + (k % 2) * 0.05
            top, bot = s.proj(bx, by, hgt + 30 + 3 * k), s.proj(x0 + a * 0.22, y0 + b * 0.22, hgt)
            s.line(bot, top, rgb("#d8d0c0"), bx + by)
            c = rgb(col)
            s.blob((bx, by, hgt + 33 + 3 * k), 3.5, [c * 0.75, c, np.minimum(c * 1.3, 255)], squash=1.15)
    return building(seed, "shop", a=1.3, b=0.95, floors=2, wall="#e8c060", awning_col="#3f6f73", roof_units=0, extra=extra)


KITE_TAIL = 10


def kite(seed, p, colors=("#c8402a", "#f2c06a", "#3a5a9a", "#3a8a4a"), off=(0.5, -0.4)):
    """A diamond kite high over a roof at phase p: it bobs and drifts, its
    tail of bows waves, its line runs down to the roof (the origin is the
    shop's ground point; the line starts at roof height)."""
    s = Sprite(160, 260, 50, 230, seed)
    roof = 64
    ku, kv = off[0] + 0.06 * math.sin(p * math.tau), off[1] + 0.04 * math.cos(p * math.tau)
    kz = 170 + 6 * math.sin(p * math.tau * 2)
    cx, cy = s.proj(ku, kv, kz)
    w, h = 9, 13
    quads = [((0, -h), (w, 0), colors[0]), ((w, 0), (0, h), colors[1]), ((0, h), (-w, 0), colors[2]), ((-w, 0), (0, -h), colors[3])]
    for (ax, ay), (bx, by), col in quads:
        s.tri2d((cx, cy), (cx + ax, cy + ay), (cx + bx, cy + by), rgb(col), 1.0)
    s.line((cx, cy - h), (cx, cy + h), rgb("#5f4646"), 1.1)
    s.line((cx - w, cy), (cx + w, cy), rgb("#5f4646"), 1.1)
    for k in range(KITE_TAIL):                                   # tail with bows
        t = k / KITE_TAIL
        tx = cx - 2 + 5 * math.sin(p * math.tau + k * 0.7)
        ty = cy + h + 3 + k * 4
        s.line((tx, ty), (tx, ty + 3), rgb("#5f4646"), 0.9)
        if k % 2:
            s.line((tx - 2, ty + 1), (tx + 2, ty + 1), rgb(colors[k % 4]), 0.95)
    base = s.proj(0, 0, roof)
    for k in range(40):                                          # the line, sagging
        t = k / 39
        x = base[0] + (cx - base[0]) * t
        y = base[1] + (cy + h - base[1]) * t + 14 * math.sin(math.pi * t)
        s.line((x, y), (x, y), rgb("#d8d0c0"), 0.5)
    return s


def air_dancer(seed, p, color="#c8402a", arms="#f2c06a"):
    """Inflatable tube dancer at phase p: a fan box, a tube swaying more the
    higher it goes, arms flapping, a face near the top."""
    s = Sprite(90, 110, 45, 90, seed)
    s.box(-0.1, -0.1, 0, 0.2, 0.2, 7, *(flat(s, c) for c in ("#5b5a5c", "#4a494b", "#3e3d3f")))
    c = rgb(color)
    pal = [c * 0.7, c * 0.9, c, np.minimum(c * 1.25, 255)]
    top = None
    for k in range(20):
        z = 8 + k * 2.6
        sway = (z - 8) / 52
        dx = 0.12 * sway * math.sin(p * math.tau + z * 0.08) + 0.05 * sway ** 2 * math.sin(p * math.tau * 2)
        s.blob((dx, 0, z), 3.4 - 0.6 * sway, pal, squash=0.9)
        top = (dx, z)
        if k == 12:                                              # arms
            arm = rgb(arms)
            for side in (-1, 1):
                flap = math.sin(p * math.tau * 2 + (side > 0) * math.pi)
                x0, y0 = s.proj(dx, 0, z)
                s.line((x0, y0), (x0 + side * 9, y0 - 6 - 5 * flap), arm, 1.0)
                s.line((x0, y0 + 1), (x0 + side * 9, y0 - 5 - 5 * flap), arm * 0.8, 1.0)
    fx, fy = s.proj(top[0], 0, top[1] - 3)                       # face
    for ex in (-1.5, 1.5):
        s.line((fx + ex, fy), (fx + ex, fy), rgb("#f4f4f4"), 2.0)
    s.line((fx - 1, fy + 2), (fx + 1, fy + 2), rgb("#1e1e28"), 2.0)
    s.outline(0.8)
    return s


# ---------- port ----------

CONTAINER_COLS = ["#9a4a3a", "#3e5a7a", "#4a6a4a", "#b0703a", "#8a8690", "#3f6a6e", "#b89a40", "#6a4a5a", "#c8c0b0"]
CL, CW, CH = 0.62, 0.25, 15                      # container length (along u), width, height px


def ribs(s, color, pitch=2):
    c = rgb(color)
    return lambda a_, b_, xs, ys: np.where((xs % pitch == 0)[:, None], c * 0.82, c) + (s.grain[ys, xs] - 0.5)[:, None] * 4


def container(s, x, y, z, color, along_u=True):
    """One shipping container: corrugated sides between darker corner posts
    and rails, locking bars on the door end (+u / +v), a ribbed roof."""
    L, W = (CL, CW) if along_u else (CW, CL)
    c = rgb(color)

    def side(length_px):
        def sh(a_, b_, xs, ys):
            along, zz = a_ * length_px, b_ * CH
            rib = np.mod(along, 3)
            out = np.where((rib < 1)[:, None], c * 0.8, np.where((rib < 2)[:, None], c * 1.05, c * 0.93))
            rail = (zz < 1.5) | (zz > CH - 1.5) | (along < 1) | (along > length_px - 1)
            return np.where(rail[:, None], c * 0.66, out) + (s.grain[ys, xs] - 0.5)[:, None] * 3
        return sh

    def doors(length_px):
        def sh(a_, b_, xs, ys):
            along, zz = a_ * length_px, b_ * CH
            out = np.repeat((c * 0.95)[None], len(a_), 0)
            bars = (np.mod(along, length_px / 4) < 0.8) & (zz > 1.5) & (zz < CH - 1.5)
            out = np.where(bars[:, None], c * 0.62, out)
            out = np.where((np.abs(along - length_px / 2) < 0.6)[:, None], c * 0.55, out)
            rail = (zz < 1.5) | (zz > CH - 1.5) | (along < 1) | (along > length_px - 1)
            return np.where(rail[:, None], c * 0.66, out)
        return sh
    top = lambda a_, b_, xs, ys: np.where((np.mod(xs + ys, 3) == 0)[:, None], c * 0.95, c * 1.12)
    if along_u:
        s.box(x, y, z, L, W, CH, top, side(L * 71.6), doors(W * 71.6))
    else:
        s.box(x, y, z, L, W, CH, top, doors(L * 71.6), side(W * 71.6))


def container_stack(seed, rows=2, tiers=3, cols=1, rot=0):
    """A block of containers, `cols` along u × `rows` across × `tiers` high,
    some tiers short a box. Turned by rot."""
    s = Sprite(160, 150, 80, 110, seed)
    s.rot = rot
    rng = np.random.default_rng(seed)
    x0, y0 = -cols * CL / 2, -rows * (CW + 0.01) / 2
    for t in range(tiers):
        for r in range(rows):
            for c in range(cols):
                if t and rng.random() < 0.18:
                    continue
                container(s, x0 + c * CL, y0 + r * (CW + 0.01), t * CH, CONTAINER_COLS[rng.integers(len(CONTAINER_COLS))])
    s.outline(0.8)
    return s


def gantry_crane(seed, rot=0, color="#4a6a8e"):
    """Ship-to-shore container crane: a braced portal on four legs with
    hazard stripes, a lattice boom out over the water toward -v (turned by
    rot), forestays from the apex, the operator cab and trolley under the
    boom, a spreader on its cables, the machinery house aft."""
    s = Sprite(280, 320, 140, 260, seed)
    s.rot = rot
    c = rgb(color)
    col = [flat(s, c * k, 3) for k in (1.12, 0.96, 0.8)]
    wh = [flat(s, rgb("#ddd6c8") * k, 3) for k in (1.05, 0.94, 0.8)]

    def leg(a_, b_, xs, ys):
        zz = b_ * 70
        haz = (zz < 8) & (np.mod(xs + ys + zz, 4) < 2)
        return np.where(haz[:, None], rgb("#c8a030"), np.where((zz < 8)[:, None], rgb("#2e3336"), c * 0.96))
    for x in (-0.38, 0.32):
        for y in (-0.32, 0.26):
            s.box(x, y, 0, 0.06, 0.06, 70, flat(s, c), leg, leg)
        s.box(x - 0.02, -0.36, -1, 0.1, 0.72, 4, *(flat(s, "#2e3336") for _ in range(3)))       # bogies
        for z0 in (0, 34):                                              # X bracing on the sides
            for (ya, za, yb, zb) in ((-0.3, z0, 0.28, z0 + 34), (0.28, z0, -0.3, z0 + 34)):
                s.line(s.proj(x + 0.03, ya, za), s.proj(x + 0.03, yb, zb), c * 0.85, x + 0.03)
        s.box(x, -0.32, 34, 0.06, 0.64, 3, *col)
    s.box(-0.4, -0.34, 70, 0.8, 0.68, 7, *col)                        # portal top
    # Boom: a lattice girder (see-through), a walkway on top.
    def truss(length_px, h=9):
        def sh(a_, b_, xs, ys):
            along, zz = a_ * length_px, b_ * h
            chord = (zz < 1.3) | (zz > h - 1.3)
            diag = (np.abs(np.mod(along, 10) - zz * 10 / h) < 0.9) | (np.abs(np.mod(along + 5, 10) - (h - zz) * 10 / h) < 0.9)
            on = chord | diag | (np.mod(along, 10) < 0.8)
            rgb4 = np.concatenate([np.repeat(rgb("#e0dad0")[None], len(a_), 0), np.full((len(a_), 1), 255.0)], 1)
            return rgb4 * on[:, None]
        return sh
    bl = 3.1
    s.face((-0.09, -2.25, 82), (0, bl, 0), (0, 0, 9), truss(bl * 71.6), light="auto")
    s.face((0.09, -2.25, 82), (0, bl, 0), (0, 0, 9), truss(bl * 71.6), light="auto")
    s.face((-0.09, -2.25, 91), (0.18, 0, 0), (0, bl, 0), flat(s, "#c8c2b6", 3), light=1.0)
    apex = 128
    for x in (-0.36, 0.34):                                            # A-frame legs
        s.box(x, 0.06, 76, 0.05, 0.05, apex - 76, *wh)
    s.box(-0.36, 0.06, apex, 0.75, 0.05, 4, *wh)
    for x in (-0.08, 0.08):                                            # forestays to the boom
        for yt in (-2.1, -1.2):
            s.line(s.proj(x, 0.08, apex), s.proj(x, yt, 91), rgb("#9a9488"), yt)
        s.line(s.proj(x, 0.08, apex), s.proj(x, 0.8, 91), rgb("#9a9488"), 0.4)
    s.box(-0.3, 0.3, 76, 0.6, 0.5, 20, flat(s, "#c8c2b6"),
          wall_shader(s, "#ddd6c8", 0.6 * 71.6, 20, 1, spans(3), None, None, "plain"),
          wall_shader(s, "#ddd6c8", 0.5 * 71.6, 20, 1, spans(2), None, None, "plain"))     # machinery house
    ty = -1.35                                                          # trolley, cab, cables, spreader
    s.box(-0.1, ty, 76, 0.2, 0.22, 6, *(flat(s, "#c8a030") for _ in range(3)))
    s.box(0.1, ty + 0.02, 66, 0.14, 0.16, 10, flat(s, "#ddd6c8"),
          lambda a_, b_, xs, ys: np.where((b_ > 0.35)[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.15, rgb("#ddd6c8")),
          lambda a_, b_, xs, ys: np.where((b_ > 0.35)[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.15, rgb("#ddd6c8")))
    for dx in (-0.06, 0.06):
        s.line(s.proj(dx, ty + 0.11, 76), s.proj(dx, ty + 0.11, 42), rgb("#2e3336"), ty)
    s.box(-0.33, ty - 0.02, 38, 0.66, 0.26, 4, *(flat(s, rgb("#c8a030") * k) for k in (1.1, 0.95, 0.8)))
    s.outline(0.8)
    return s


def cargo_ship(seed, hull="#2e3a4a", rot=0):
    """Container ship moored along u (turned by rot): a hull with a red
    boot-top and a white sheer line, a flared bow at -u, container bays with
    hatch covers, the bridge block aft with wings, a mast, a lifeboat and
    the funnel in the company colours."""
    s = Sprite(440, 250, 220, 160, seed)
    s.rot = rot
    rng = np.random.default_rng(seed)
    L, W, H = 3.6, 0.72, 15
    x0, y0 = -L / 2, -W / 2
    hc = rgb(hull)

    def hull_sh(a_, b_, xs, ys):
        zz = b_ * H
        out = np.where((zz < 3)[:, None], rgb("#8a3a32"), hc * (0.95 + 0.1 * (s.grain[ys, xs] - 0.5))[:, None])
        out = np.where(((zz > H - 3) & (zz < H - 1.5))[:, None], rgb("#ddd6c8"), out)
        return out
    s.box(x0 + 0.5, y0, 0, L - 0.5, W, H, flat(s, "#5b5a5c"), hull_sh, hull_sh)
    if rot:
        s.face((x0 + 0.5, y0, 0), (L - 0.5, 0, 0), (0, 0, H), hull_sh, light="auto")
        s.face((x0 + L, y0, 0), (0, W, 0), (0, 0, H), hull_sh, light="auto")
    bow = (x0 - 0.05, 0.0, 0)
    for yy in (y0 + W, y0):
        s.face((x0 + 0.5, yy, 0), np.subtract(bow, (x0 + 0.5, yy, 0)), (0, 0, H + 3), hull_sh, light="auto")
    s.face((x0 + 0.5, y0, H), (0, W, 0), (-0.55, W / 2, 3), flat(s, "#5b5a5c"), tri=True)
    for bay in range(6):                                               # hatch covers and containers
        bx = x0 + 0.62 + bay * 0.4
        s.box(bx - 0.02, y0 + 0.05, H, 0.4, W - 0.1, 2, *(flat(s, c) for c in ("#6a6e74", "#5a5e64", "#4a4e54")))
        for r in range(2):
            for t in range(int(rng.integers(1, 4))):
                container(s, bx, y0 + 0.08 + r * 0.29, H + 2 + t * CH, CONTAINER_COLS[rng.integers(len(CONTAINER_COLS))])
    ax = x0 + L - 0.5                                                   # bridge block
    bw = lambda length, n: (lambda a_, b_, xs, ys: np.where(((np.mod(b_ * 40, 10) > 5) & (np.mod(a_ * n, 1) > 0.2))[:, None],
                                                            np.array(GLASS)[(xs + ys) % 4] * 1.1, rgb("#e0dad0")))
    s.box(ax, y0 + 0.06, H, 0.42, W - 0.12, 40, flat(s, "#d8d2c6"), bw(W, 5), bw(0.42, 3))
    s.box(ax - 0.02, y0 - 0.06, H + 36, 0.3, W + 0.12, 3, *(flat(s, c) for c in ("#d8d2c6", "#c8c2b6", "#b8b2a6")))   # wings
    s.box(ax + 0.02, y0 + 0.04, H + 40, 0.38, W - 0.08, 2, *(flat(s, c) for c in ("#8e8897", "#716f74", "#5b5a5c")))
    s.box(ax + 0.14, -0.01, H + 42, 0.02, 0.02, 14, *(flat(s, "#5b5a5c") for _ in range(3)))                   # mast
    s.box(ax + 0.09, -0.06, H + 52, 0.12, 0.02, 2, *(flat(s, "#716f74") for _ in range(3)))                     # radar
    funnel = lambda a_, b_, xs, ys: np.where(((b_ > 0.45) & (b_ < 0.7))[:, None], rgb("#c8a030"), rgb("#8a3a32"))
    s.box(ax + 0.26, -0.09, H + 42, 0.14, 0.18, 18, flat(s, "#2e3336"), funnel, funnel)
    s.box(ax + 0.08, y0 + W - 0.02, H + 18, 0.24, 0.07, 6, *(flat(s, "#d8702a") for _ in range(3)))            # lifeboat
    s.outline(0.8)
    return s


def warehouse(seed, a=2.4, b=1.3, color="#8e8897"):
    """Warehouse: a concrete plinth, ribbed walls with a colour band, three
    roller doors each over a loading dock with bumpers and a canopy, yellow
    bollards, and a barrel roof with skylight strips and a gutter."""
    s = Sprite(380, 270, 190, 175, seed)
    x0, y0, h = -a / 2, -b / 2, 34
    c = rgb(color)
    band = rgb("#3e5a7a") if seed % 2 else rgb("#8a3a32")

    def wall(length_px, doors):
        def sh(a_, b_, xs, ys):
            along, zz = a_ * length_px, b_ * h
            rib = np.mod(along, 3)
            out = np.where((rib < 1)[:, None], c * 0.84, c)
            out = np.where((zz < 4)[:, None], rgb("#a69c8c"), out)                       # plinth
            out = np.where(((zz > h - 7) & (zz < h - 4))[:, None], band, out)
            for k in range(doors):
                d0 = (k + 0.5) / doors * length_px - 11
                door = (along >= d0) & (along < d0 + 22) & (zz >= 6) & (zz < 26)
                frame = door & ((along < d0 + 1) | (along >= d0 + 21) | (zz >= 25))
                out = np.where(door[:, None], np.where((np.mod(zz, 2) < 1)[:, None], rgb("#bdb3a2"), rgb("#a69c8c")), out)
                out = np.where(frame[:, None], rgb("#5b5a5c"), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 4
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, c), wall(a * 71.6, 3), wall(b * 71.6, 0))
    for k in range(3):                                                  # docks, canopies, bumpers
        dx = x0 + (k + 0.5) / 3 * a - 0.17
        s.box(dx, y0 + b, 0, 0.34, 0.16, 6, *(flat(s, cc) for cc in ("#bdb3a2", "#a69c8c", "#8e8680")))
        s.box(dx - 0.02, y0 + b, 27, 0.38, 0.14, 2, *(flat(s, cc) for cc in ("#6a6e74", "#5a5e64", "#4a4e54")))
        for bx in (dx + 0.03, dx + 0.28):
            s.box(bx, y0 + b + 0.16, 1, 0.03, 0.01, 4, *(flat(s, "#1e1e22") for _ in range(3)))
        s.box(dx + 0.4, y0 + b + 0.2, 0, 0.025, 0.025, 7, *(flat(s, "#c8a030") for _ in range(3)))
    for k in range(8):                                                  # barrel roof with skylights
        t0 = k / 8
        z0, z1 = h + 10 * math.sin(math.pi * t0), h + 10 * math.sin(math.pi * (t0 + 1 / 8))
        base = rgb("#9c9ea8") * (0.84 + 0.22 * (1 - t0))
        roof = lambda a_, b_, xs, ys, base=base, k=k: np.where(((k in (2, 5)) & (np.mod(a_ * a * 71.6, 24) < 10))[:, None],
                                                                np.array(GLASS)[(xs + ys) % 4] * 1.2,
                                                                np.where((np.mod(xs, 3) == 0)[:, None], base * 0.92, base))
        s.face((x0, y0 + b * t0, z0), (a, 0, 0), (0, b / 8, z1 - z0), roof)
    s.box(x0, y0 + b - 0.02, h - 2, a, 0.03, 2, *(flat(s, "#5b5a5c") for _ in range(3)))       # gutter
    s.outline(0.75)
    return s, (a, b)


def customs(seed):
    """Customs house: two stone floors, CUSTOMS over the door, flags."""
    s = Sprite(360, 300, 180, 210, seed)
    a, b, fh, floors = 2.0, 1.3, 32, 2
    x0, y0 = -a / 2, -b / 2
    hgt = floors * fh + 4
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, "#d8d0c0", "plain", spans(7, skip=(3,)), spans(4), (0.43, 0.57),
                "arched", "#8e8680", None)
    cornice(s, x0, y0, a, b, hgt, "#e0d8c8")
    flat_roof(s, x0, y0, a, b, hgt + 1, "#5b5a5c", units=2)
    wall_sign(s, x0 + a * 0.5, y0 + b, 36, 0.62, "CUSTOMS", "#2c3548", "#e8e0cc", 12)
    s.box(x0 + a * 0.4, y0 + b, 0, a * 0.2, 0.2, 3, *(flat(s, c) for c in ("#e0d8c8", "#c9bfae", "#b3a998")))
    for fx in (x0 + 0.1, x0 + a - 0.1):
        flagpole(s, fx, y0 + b + 0.12, 70)
    s.outline(0.7)
    return s, (a, b)


# ---------- industry ----------

def sawtooth_factory(seed, a=3.4, b=1.8, floors=2):
    """Old brick factory (after the Ford plants): long brick walls with tall
    arched windows, a sawtooth roof of north lights, a stair tower."""
    s = Sprite(460, 340, 230, 230, seed)
    fh = 34
    hgt = floors * fh + 4
    x0, y0 = -a / 2, -b / 2
    civic_walls(s, x0, y0, a, b, hgt, floors, fh, "#8a4a3e", "brick", spans(12), spans(6), (0.47, 0.53),
                "arched", "#e0d8c8", None)
    cornice(s, x0, y0, a, b, hgt, "#bdb3a2")
    n = 6
    for k in range(n):                                              # sawtooth: glazed steep side, slate slope
        sx = x0 + k * a / n
        s.face((sx, y0, hgt), (0, b, 0), (0, 0, 16), lambda a_, b_, xs, ys: np.array(GLASS)[(xs + ys) % 4] * 1.1, light=0.9)
        s.face((sx, y0, hgt + 16), (0, b, 0), (a / n, 0, -16), flat(s, "#5b5a5c", 4), light=1.0)
        s.face((sx, y0 + b, hgt), (a / n, 0, 0), (0, 0, 16), flat(s, "#8a4a3e", 6), tri=True, light=LIGHT["v"])
    s.box(x0 + a - 0.45, y0 + b - 0.4, 0, 0.4, 0.4, hgt + 30, flat(s, "#6e3a30"),
          wall_shader(s, "#8a4a3e", 0.4 * 71.6, hgt + 30, 3, spans(1), None, None, "brick", floor_h=30),
          wall_shader(s, "#8a4a3e", 0.4 * 71.6, hgt + 30, 3, spans(1), None, None, "brick", floor_h=30))
    s.outline(0.7)
    return s, (a, b)


def tank(s, x, y, r, h, color="#d8d4dc", top="#bdb3a2", z0=0):
    ring(s, r, z0, h, lambda k: banded(s, [rgb(color), rgb(color) * 0.94], 5, axis=1), n=16, cx=x, cy=y)
    disk(s, r, z0 + h, flat(s, top, 4), n=16, cx=x, cy=y)
    ring(s, r + 0.01, z0 + h - 2, 2, lambda k: flat(s, rgb(color) * 0.8, 2), n=16, cx=x, cy=y)


def pipe(s, p, q, w=0.03, color="#8e8897"):
    """A straight pipe between two points (axis-aligned runs)."""
    (x0, y0, z0), (x1, y1, z1) = p, q
    col = [flat(s, rgb(color) * k, 3) for k in (1.1, 0.95, 0.8)]
    s.box(min(x0, x1) - w / 2, min(y0, y1) - w / 2, min(z0, z1), abs(x1 - x0) + w, abs(y1 - y0) + w,
          max(abs(z1 - z0), w * 64), *col)


def conveyor(s, p, q, w=0.1, boxes="#c8a030"):
    """An inclined belt on trestles from p up to q, with loads on it."""
    band = lambda a_, b_, xs, ys: np.where((np.mod(a_ * 20, 1) < 0.15)[:, None], rgb("#2e3336"), rgb("#4a494b"))
    e1 = np.subtract(q, p)
    s.face(p, e1, (0, w, 0), band, light=1.0)
    s.face((p[0], p[1] + w, p[2] - 2), e1, (0, 0, 2), flat(s, "#716f74", 2), light=LIGHT["v"])
    for t in (0.2, 0.45, 0.7, 0.95):
        x, y, z = p[0] + e1[0] * t, p[1] + e1[1] * t, p[2] + e1[2] * t
        s.box(x - 0.01, y + w / 2 - 0.01, 0, 0.02, 0.02, max(1, z - 1), *(flat(s, c, 2) for c in STEEL))
        s.box(x + 0.02, y + 0.02, z, 0.06, w - 0.04, 4, *(flat(s, rgb(boxes) * k, 3) for k in (1.1, 0.95, 0.8)))


def plant(seed, kind="plant", a=2.4, b=1.5):
    """Factory hall with tanks, pipes and conveyor belts. kind: 'plant'
    (gray process plant), 'cola' (white and red, COLA and a bottle),
    'chips' (yellow, CHIPS and a bag). A concrete plinth, ribbed walls with
    a colour band, a glazed roof monitor, a loading dock under a canopy, a
    pipe rack out to two tanks with catwalks and ladders, a vent stack."""
    s = Sprite(470, 350, 235, 235, seed)
    wall = {"plant": "#9c9ea8", "cola": "#e8e4dc", "chips": "#e0c070"}[kind]
    band = {"plant": "#3e5a7a", "cola": "#b0341f", "chips": "#c8502a"}[kind]
    x0, y0, h = -a / 2, -b / 2, 44
    c = rgb(wall)

    def wall_sh(length_px, dock):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.where((np.mod(along, 3) < 1)[:, None], c * 0.85, c)
            out = np.where((z < 5)[:, None], rgb("#a69c8c"), out)
            out = np.where(((z > 32) & (z < 37))[:, None], rgb(band), out)
            win = (z > 22) & (z < 29) & (np.mod(along, 14) > 3)
            out = np.where(win[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.05, out)
            if dock:
                d0 = length_px * 0.22
                door = (along >= d0) & (along < d0 + 24) & (z >= 6) & (z < 22)
                out = np.where(door[:, None], np.where((np.mod(z, 2) < 1)[:, None], rgb("#bdb3a2"), rgb("#a69c8c")), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 4
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#7a7c86"), wall_sh(a * 71.6, True), wall_sh(b * 71.6, False))
    # Roof monitor: a raised glazed strip along u.
    mw = b * 0.34
    mon = lambda a_, b_, xs, ys: np.where((b_ > 0.25)[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.15, c * 0.8)
    s.box(x0 + 0.2, y0 + (b - mw) / 2, h, a - 0.4, mw, 9, flat(s, "#6e7078"), mon, mon)
    for k in range(2):                                                 # roof vents
        s.box(x0 + 0.35 + k * (a - 0.9), y0 + 0.15, h, 0.2, 0.2, 7, fan_top(s), flat(s, "#9791a2"), flat(s, "#716f74"))
    dx = x0 + a * 0.22                                                  # loading dock and canopy
    s.box(dx - 0.04, y0 + b, 0, 0.42, 0.18, 6, *(flat(s, cc) for cc in ("#bdb3a2", "#a69c8c", "#8e8680")))
    s.box(dx - 0.06, y0 + b, 25, 0.46, 0.2, 2, *(flat(s, cc) for cc in ("#6a6e74", "#5a5e64", "#4a4e54")))
    tc = {"plant": "#d8d4dc", "cola": "#e8e4dc", "chips": "#e0d8c8"}[kind]
    tx = x0 + a + 0.36
    for k, ty in enumerate((y0 + 0.3, y0 + b - 0.32)):                 # tanks with catwalks and ladders
        th = 58 - 10 * k
        tank(s, tx, ty, 0.27, th, tc, "#bdb3a2")
        ring(s, 0.3, th - 1, 1, lambda i: flat(s, "#716f74", 2), n=16, cx=tx, cy=ty)
        s.line(s.proj(tx + 0.19, ty + 0.19, 2), s.proj(tx + 0.19, ty + 0.19, th), rgb("#5b5a5c"), tx + ty + 0.4)
        pipe(s, (tx, ty, th), (tx, ty, th + 8), color="#8e8897")
    for z in (18, 30):                                                  # pipe rack to the tanks
        pipe(s, (x0 + a, y0 + 0.3, z), (tx - 0.27, y0 + 0.3, z), w=0.035, color="#b8964a" if z == 18 else "#8e8897")
        pipe(s, (x0 + a, y0 + b - 0.32, z), (tx - 0.27, y0 + b - 0.32, z), w=0.035, color="#b8964a" if z == 18 else "#8e8897")
    for yy in (y0 + 0.3, y0 + b - 0.32):
        s.box(x0 + a + 0.05, yy - 0.02, 0, 0.03, 0.03, 32, *(flat(s, cc, 2) for cc in STEEL))
    pipe(s, (x0 + a - 0.12, y0 + 0.12, h), (x0 + a - 0.12, y0 + 0.12, h + 30), w=0.07, color="#8e8897")   # vent stack
    s.box(x0 + a - 0.16, y0 + 0.08, h + 30, 0.08, 0.08, 3, *(flat(s, "#5b5a5c") for _ in range(3)))
    conveyor(s, (x0 + a * 0.62, y0 + b + 0.05, 2), (x0 + a - 0.15, y0 + b + 0.05, h - 8),
             boxes={"plant": "#b08a5a", "cola": "#b0341f", "chips": "#e0a040"}[kind])
    if kind in ("cola", "chips"):
        tex = {"cola": bottle_tex(), "chips": bag_tex()}[kind]
        roof_board(s, x0, y0, a, b, h + 9, kind.upper(), "#b0341f" if kind == "cola" else "#c8502a", "#f0ece4",
                   w=1.1, tex=tex, tex_w=0.3, tex_h=26)
    s.outline(0.7)
    return s, (a, b)


def bottle_tex(W=16, H=26):
    t = np.zeros((H, W, 4))
    cx = W // 2
    for y in range(H):
        w = 2 if y < 6 else 3 if y < 9 else 5
        t[y, cx - w:cx + w] = [*rgb("#3a1e14"), 255]
        if 13 < y < 18:
            t[y, cx - w:cx + w] = [*rgb("#f0ece4"), 255]
    t[0:2, cx - 2:cx + 2] = [*rgb("#c8402a"), 255]
    t[8:, cx + 2:cx + 3] = [*rgb("#8a5a3a"), 255]
    return t


def bag_tex(W=18, H=26):
    t = np.zeros((H, W, 4))
    t[2:H - 1, 1:W - 1] = [*rgb("#c8502a"), 255]
    for x in range(1, W - 1):
        t[0:2 + (x % 2), x] = 0
        t[H - 1 - (x % 2):, x] = 0
    t[9:16, 1:W - 1] = [*rgb("#f0d890"), 255]
    for cx, cy in ((6, 12), (11, 13)):
        t[cy - 1:cy + 2, cx - 2:cx + 2] = [*rgb("#e0a040"), 255]
    return t


def chimney(seed, h=120):
    """Tall brick factory chimney: brick courses with iron bands, a ladder
    and a corbelled top (its smoke is chimney_smoke, drawn over everything)."""
    s = Sprite(170, 270, 55, 225, seed)
    for z in range(0, h, 6):
        r = 0.16 - 0.06 * z / h
        band = (z // 6) % 5 == 4
        col = rgb("#4a494b") if band else rgb("#8a4a3e") * (1.0 if (z // 6) % 2 else 0.92)
        ring(s, r, z, 6, lambda k, col=col: flat(s, col, 5), n=12)
    ring(s, 0.13, h, 6, lambda k: flat(s, "#6e3a30", 3), n=12)
    disk(s, 0.12, h + 6, flat(s, "#1e1e22", 2), n=12)
    s.line(s.proj(0.1, 0.1, 4), s.proj(0.07, 0.07, h), rgb("#3e3d3f"), 0.3)
    s.outline(0.8)
    return s


def chimney_smoke(seed, p, h=120):
    """The chimney's smoke at phase p (same origin as chimney): puffs rise,
    drift off and thin out."""
    s = Sprite(170, 270, 55, 225, seed)
    grey = ramp("#8e8a92", "#a8a4ae", "#c4c0c8", "#dcd8e0")
    for k in range(7):
        age = (p + k / 7) % 1
        up = age * 90
        drift = age * 1.1 + 0.08 * math.sin(age * 9 + k)
        r = 4 + 9 * age
        if age > 0.85:
            r *= (1 - age) / 0.15
        if r > 1:
            s.blob((drift, -drift * 0.4, h + 10 + up), r, grey, squash=0.85, shade=0.15)
    return s


def truck(seed, color="#c8402a", rot=0):
    """Semi-truck along u (turned by rot): a cab at +u with windscreen, grille
    and lights, a box trailer with a company stripe, wheels and mudflaps."""
    s = Sprite(150, 96, 75, 64, seed)
    s.rot = rot
    c = rgb(color)
    trailer = lambda a_, b_, xs, ys: np.where(((b_ > 0.55) & (b_ < 0.7))[:, None], c,
                                              np.where((np.mod(xs, 4) == 0)[:, None], rgb("#d0ccc4"), rgb("#e8e4dc")))
    s.box(-0.52, -0.12, 4, 0.8, 0.24, 18, flat(s, "#d8d4cc"), trailer, trailer)
    s.box(-0.52, -0.12, 2, 0.8, 0.24, 2, *(flat(s, "#3e3d3f") for _ in range(3)))        # chassis

    def cab(a_, b_, xs, ys):
        glass = (b_ > 0.55) & (b_ < 0.9) & (a_ > 0.12) & (a_ < 0.88)
        out = np.where(glass[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.1, c)
        return np.where((b_ < 0.15)[:, None], rgb("#2e3336"), out)

    def nose(a_, b_, xs, ys):
        grille = (b_ < 0.45) & (a_ > 0.2) & (a_ < 0.8) & (np.mod(ys, 2) == 0)
        out = np.where(grille[:, None], rgb("#bdb3a2"), cab(a_, b_, xs, ys))
        lights = (b_ > 0.2) & (b_ < 0.35) & ((a_ < 0.15) | (a_ > 0.85))
        return np.where(lights[:, None], rgb("#f2e0a0"), out)
    s.box(0.3, -0.12, 2, 0.24, 0.24, 16, flat(s, c * 1.1), cab, nose)
    if rot:
        s.face((0.3, -0.12, 2), (0.24, 0, 0), (0, 0, 16), cab, light="auto")
        s.face((0.54, -0.12, 2), (0, 0.24, 0), (0, 0, 16), nose, light="auto")
        s.face((-0.52, -0.12, 4), (0.8, 0, 0), (0, 0, 18), trailer, light="auto")
        s.face((-0.52, -0.12, 4), (0, 0.24, 0), (0, 0, 18), flat(s, "#c8c4bc"), light="auto")
    for x in (-0.45, -0.33, 0.12, 0.42):
        for y in (-0.14, 0.12):
            s.box(x, y, 0, 0.08, 0.02, 5, *(flat(s, "#1e1e22") for _ in range(3)))
    s.outline(0.8)
    return s


def workshop(seed, color="#8e8897"):
    """Workshop: a small ribbed shed with two roller doors and a GARAGE board."""
    s = Sprite(220, 180, 110, 120, seed)
    a, b, h = 1.4, 1.0, 28
    x0, y0 = -a / 2, -b / 2

    def front(a_, b_, xs, ys):
        out = ribs(s, color)(a_, b_, xs, ys)
        along, z = a_ * a * 71.6, b_ * h
        for d0 in (a * 71.6 * 0.12, a * 71.6 * 0.55):
            door = (along >= d0) & (along < d0 + 30) & (z < 22)
            out = np.where(door[:, None], np.where((np.mod(z, 2) < 1)[:, None], rgb("#c8c2b6"), rgb("#a69c8c")), out)
        return out
    s.box(x0, y0, 0, a, b, h, flat(s, "#7a7c86"), front, ribs(s, color))
    gable(s, x0, y0, a, b, h, 10, ramp("#6e6e74", "#7a7a80"), color, "u", 0.04)
    wall_sign(s, x0 + a * 0.5, y0 + b, 24, 0.6, "GARAGE", "#c8a030", "#2e3336", 9)
    for k in range(3):                                              # oil drums by the door
        s.box(x0 + a + 0.06, y0 + b - 0.2 - k * 0.12, 0, 0.09, 0.09, 10, *(flat(s, c) for c in ("#3a5a9a", "#2f5a88", "#244870")))
    s.outline(0.75)
    return s, (a, b)


def water_tower(seed):
    """Water tower: a round tank with a conical cap on four braced legs."""
    s = Sprite(140, 220, 70, 190, seed)
    steel = [flat(s, c, 3) for c in ("#8e8897", "#716f74", "#5b5a5c")]
    for x, y in ((-0.22, -0.22), (0.2, -0.22), (0.2, 0.2), (-0.22, 0.2)):
        s.box(x, y, 0, 0.03, 0.03, 80, *steel)
    for z in (26, 54):
        for (ax, ay), (bx, by) in (((-0.21, 0.21), (0.21, 0.21)), ((0.21, -0.21), (0.21, 0.21))):
            p, q = s.proj(ax, ay, z), s.proj(bx, by, z)
            s.line(p, q, rgb("#716f74"), 0.2)
    tank(s, 0, 0, 0.32, 36, "#b8c4cc", "#8e98a0", z0=80)
    for k in range(6):                                              # cone
        ring(s, 0.32 - k * 0.05, 116 + k * 3, 3, lambda i: flat(s, "#8e98a0", 3), n=16)
    s.outline(0.78)
    return s


def cell_tower(seed):
    """Cell tower: a slim lattice mast with antenna panels and dishes."""
    s = Sprite(120, 260, 60, 235, seed)
    steel = [flat(s, c, 2) for c in ("#c8c2b6", "#a69c8c", "#8e8680")]
    for x, y in ((-0.08, -0.08), (0.06, -0.08), (0.06, 0.06), (-0.08, 0.06)):
        s.box(x, y, 0, 0.02, 0.02, 180, *steel)
    for z in range(10, 180, 14):
        p, q = s.proj(-0.07, 0.07, z), s.proj(0.07, 0.07, z + 14)
        s.line(p, q, rgb("#a69c8c"), 0.2)
    for k, (dx, dy) in enumerate(((0.12, 0), (0, 0.12), (-0.12, 0), (0, -0.12))):   # antenna panels
        s.box(dx - 0.02, dy - 0.02, 160, 0.04, 0.04, 16, *(flat(s, "#e8e4dc") for _ in range(3)))
    s.blob((0.1, 0.1, 140), 4, ramp("#9a9488", "#c8c2b6", "#e8e2d6"), squash=0.6)
    s.blob((0, 0, 184), 1.5, ramp("#8a2a20", "#c8402a", "#f07050"))
    s.outline(0.8)
    return s


def dish_antenna(seed, el=42, az=150, R=34, f=19):
    """Big parabolic antenna: a white reflector bowl (radius R px, focal
    length f) tilted up by `el` degrees and turned `az` degrees from +u
    toward +v, shaded panel by panel (white inside, gray behind), a rim, four
    struts to the feed horn at the focus; an azimuth turret and yoke on a
    concrete pad, with a small equipment hut."""
    s = Sprite(200, 210, 100, 165, seed)
    T = 71.6                                            # px per tile along u / v
    conc = [flat(s, c, 4) for c in ("#c8c2b6", "#b3ab9e", "#9c9486")]
    s.box(-0.32, -0.32, 0, 0.64, 0.64, 5, *conc)
    hut = lambda a_, b_, xs, ys: np.where(((a_ > 0.35) & (a_ < 0.65) & (b_ < 0.75))[:, None], rgb("#5b5a5c"), rgb("#d8d4cc"))
    s.box(0.1, -0.3, 5, 0.2, 0.24, 15, flat(s, "#bdb3a2"), hut, flat(s, "#c8c4bc"))
    steel = [flat(s, c, 2) for c in ("#a8a4ae", "#8e8a94", "#76727c")]
    s.box(-0.08, -0.08, 5, 0.16, 0.16, 26, *steel)                     # turret
    s.box(-0.12, -0.12, 31, 0.24, 0.24, 5, *steel)                     # turntable
    e, a = math.radians(el), math.radians(az)
    axis = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    e1 = np.array([-math.sin(a), math.cos(a), 0.0])
    e2 = np.cross(axis, e1)
    V = np.array([0.0, 0.0, 44.0]) + axis * 7                           # the bowl's vertex (px space)
    to_cam = np.array([0.61, 0.61, 0.5]); to_cam /= np.linalg.norm(to_cam)
    L = np.array([0.35, 0.6, 0.72]); L /= np.linalg.norm(L)
    W = lambda P: (P[0] / T, P[1] / T, P[2])                           # px space -> sprite coords
    def pt(r, t):
        return V + e1 * r * math.cos(t) + e2 * r * math.sin(t) + axis * (r * r / (4 * f))
    nr, ns = 7, 32
    inner, back = rgb("#eceae4"), rgb("#9c9aa2")
    for i in range(nr):
        r0, r1 = R * i / nr, R * (i + 1) / nr
        for k in range(ns):
            t0, t1 = 2 * math.pi * k / ns, 2 * math.pi * (k + 1) / ns
            q = [pt(r0, t0), pt(r1, t0), pt(r1, t1), pt(r0, t1)]
            for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
                n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                if np.linalg.norm(n) < 1e-9:
                    continue
                n /= np.linalg.norm(n)
                if np.dot(n, axis) < 0:
                    n = -n                                              # the concave (front) side
                front = np.dot(n, to_cam) > 0
                lit = 0.62 + 0.42 * max(0.0, float(np.dot(n if front else -n, L)))
                col = (inner if front else back) * lit
                if front and (i == nr - 1):
                    col = col * 0.93                                    # a faint band near the rim
                o = W(tri[0])
                s.face(o, np.subtract(W(tri[1]), o), np.subtract(W(tri[2]), o), flat(s, np.minimum(col, 255), 2),
                       tri=True, light=1.0)
    rim = [pt(R, 2 * math.pi * k / 48) for k in range(49)]             # rim edge
    for p0, p1 in zip(rim, rim[1:]):
        a0, a1 = W(p0), W(p1)
        s.line(s.proj(*a0), s.proj(*a1), rgb("#bdb8ae"), a0[0] + a0[1] + 0.01)
    F = V + axis * f                                                    # feed at the focus, on four struts
    for k in range(4):
        rp = W(pt(R * 0.96, math.pi / 4 + k * math.pi / 2))
        s.line(s.proj(*rp), s.proj(*W(F)), rgb("#8e8a94"), (rp[0] + rp[1] + W(F)[0] + W(F)[1]) / 2 + 0.02)
    fw = W(F)
    s.blob(fw, 3.2, ramp("#5b5a5c", "#8e8a94", "#c8c4cc"), shade=0.2)
    # Yoke: two arms up from the turntable to the hub on the bowl's back.
    hub = W(V - axis * 3)
    for side in (-1, 1):
        base = (side * 0.07 * math.sin(a), -side * 0.07 * math.cos(a) * -1, 36)
        a0, a1 = s.proj(*base), s.proj(*hub)
        for dx in (0, 1, 2):
            s.line((a0[0] + dx, a0[1]), (a1[0] + dx, a1[1]), rgb("#8e8a94") * (1.0 if dx else 0.8), hub[0] + hub[1] - 0.3)
    s.blob(hub, 5, ramp("#5b5a5c", "#76727c", "#9c98a2"), shade=0.1)
    s.outline(0.8)
    return s


def barrels(seed):
    """A cluster of oil drums, some blue, some yellow, one on its side."""
    s = Sprite(90, 60, 45, 42, seed)
    rng = np.random.default_rng(seed)
    for x, y in ((-0.1, -0.08), (0.02, -0.08), (-0.04, 0.04), (0.1, 0.02)):
        col = ["#3a5a9a", "#c8a030", "#3a5a9a", "#8a3a32"][rng.integers(4)]
        c = rgb(col)
        ring(s, 0.055, 0, 11, lambda k: banded(s, [c, c * 0.8], 4, axis=1), n=10, cx=x, cy=y)
        disk(s, 0.055, 11, flat(s, c * 1.1, 3), n=10, cx=x, cy=y)
    s.outline(0.8)
    return s


def power_station(seed):
    """Electrical substation: transformers with fins and insulators, a steel
    gantry with lines, all inside a chain-link fence (about 2 × 1.6 tiles)."""
    s = Sprite(320, 220, 160, 150, seed)
    a, b = 2.0, 1.6
    x0, y0 = -a / 2, -b / 2
    s.face((x0, y0, 0.3), (a, 0, 0), (0, b, 0), lambda a_, b_, xs, ys: np.repeat(rgb("#8e8680")[None], len(a_), 0)
           + (s.grain[ys, xs] - 0.5)[:, None] * 12)                 # gravel
    for k in range(3):                                              # transformers
        tx = x0 + 0.3 + k * 0.55
        s.box(tx, y0 + 0.5, 0, 0.36, 0.3, 20, *(flat(s, c) for c in ("#7a8a7a", "#6a7a6a", "#5a6a5a")))
        for f in range(4):
            s.box(tx + 0.36, y0 + 0.52 + f * 0.07, 2, 0.05, 0.02, 16, *(flat(s, "#5a6a5a") for _ in range(3)))
        for ix in (0.08, 0.18, 0.28):
            s.box(tx + ix, y0 + 0.62, 20, 0.02, 0.02, 10, *(flat(s, "#c8b8a0") for _ in range(3)))
            s.blob((tx + ix + 0.01, y0 + 0.63, 31), 1.5, ramp("#8a6a4a", "#c8b8a0", "#e8e2d6"))
    steel = [flat(s, c, 2) for c in STEEL]
    for x in (x0 + 0.15, x0 + a - 0.2):                             # gantry
        s.box(x, y0 + 0.2, 0, 0.04, 0.04, 56, *steel)
        s.box(x, y0 + 1.2, 0, 0.04, 0.04, 56, *steel)
    s.box(x0 + 0.15, y0 + 0.2, 56, a - 0.31, 0.04, 3, *steel)
    s.box(x0 + 0.15, y0 + 1.2, 56, a - 0.31, 0.04, 3, *steel)
    for k in range(3):
        p, q = s.proj(x0 + 0.48 + k * 0.55, y0 + 0.22, 56), s.proj(x0 + 0.48 + k * 0.55, y0 + 0.63, 31)
        s.line(p, q, rgb("#2e3336"), 0.1)
    fence = lambda a_, b_, xs, ys: np.where(((xs + ys) % 3 == 0) | ((xs - ys) % 3 == 0) | (b_ > 0.9), 1, 0)[:, None] * \
        np.concatenate([np.repeat(rgb("#a69c8c")[None], len(a_), 0), np.full((len(a_), 1), 255.0)], 1)
    for o, e in (((x0, y0 + b, 0), (a, 0, 0)), ((x0 + a, y0, 0), (0, b, 0)), ((x0, y0, 0), (a, 0, 0)), ((x0, y0, 0), (0, b, 0))):
        s.face(o, e, (0, 0, 16), fence, light=1.0)
    s.outline(0.85)
    return s, (a, b)


# ---------- nuclear power plant ----------

def cooling_tower(seed, R=1.15, H=170):
    """Hyperbolic cooling tower (radius R tiles at the base, H px tall): a
    dark air-inlet gap at the foot with the raker legs showing, the shell in
    courses with weathering streaks running down from the lip, a darker lip;
    its steam is tower_steam, drawn over everything."""
    s = Sprite(420, 460, 210, 400, seed)
    rng = np.random.default_rng(seed)
    streaks = rng.random(28) < 0.35
    shell = lambda z: R * (0.62 + 0.38 * ((z / H - 0.72) / 0.72) ** 2)
    ring(s, R * 0.97, 0, 12, lambda k: flat(s, "#2a2a2e", 2), n=28)              # the inlet gap, dark inside
    for k in range(14):                                                        # raker legs, in pairs
        a = 2 * math.pi * k / 14
        for da in (-0.05, 0.05):
            x, y = R * math.cos(a + da), R * math.sin(a + da)
            s.line(s.proj(x, y, 0), s.proj(x * 0.99, y * 0.99, 12), rgb("#bdb3a2"), x + y + 0.02)
    for z in range(12, H, 5):
        r = shell(z)
        base = rgb("#d8d4cc") * (1.0 if (z // 5) % 2 else 0.965)
        wear = min(1.0, (H - z) / 60)                                           # streaks fade downward
        def face_sh(k, base=base, wear=wear):
            c = base * (0.86 if streaks[k] and wear < 1 else 1.0) if z > H - 60 else base
            return flat(s, c, 4)
        ring(s, r, z, 6, face_sh, n=28)
    rt = shell(H)
    ring(s, rt + 0.02, H - 4, 5, lambda k: flat(s, "#a69c8c", 3), n=28)       # lip
    disk(s, rt, H + 1, flat(s, "#3a3a3e", 2), n=28)
    s.outline(0.72)
    return s


def tower_steam(seed, p, R=1.15, H=170):
    """The cooling tower's steam at phase p (same origin): white billows
    rising from the mouth and drifting off."""
    s = Sprite(420, 460, 210, 400, seed)
    steam = ramp("#c8c4cc", "#dcd8e0", "#ecebf0", "#f8f8fa")
    for k in range(9):
        age = (p + k / 9) % 1
        up, drift = age * 150, age * 1.6
        r = 14 + 26 * age
        if age > 0.8:
            r *= (1 - age) / 0.2
        ang = k * 2.1
        if r > 2:
            s.blob((drift + 0.2 * math.cos(ang), -drift * 0.5 + 0.2 * math.sin(ang), H + 8 + up), r, steam, squash=0.8, shade=0.25)
    return s


def reactor(seed):
    """Containment building: a concrete apron, a drum with tendon lines, a
    dome in panels with a hatch, an annex with a door toward +v, a vent
    stack in red and white bands."""
    s = Sprite(260, 300, 130, 230, seed)
    R, H = 0.95, 70
    ring(s, R + 0.12, 0, 4, lambda k: flat(s, "#b3ab9e", 4), n=28)
    disk(s, R + 0.12, 4, flat(s, "#c8c2b6", 4), n=28)
    drum = lambda k: (lambda a_, b_, xs, ys: np.where((np.mod(xs, 6) == 0)[:, None], rgb("#c8c0b0"),
                                                      rgb("#dcd4c4") * (0.97 + 0.06 * b_[:, None])))
    ring(s, R, 4, H - 4, drum, n=28)
    ring(s, R + 0.02, H - 3, 4, lambda k: flat(s, "#bdb3a2", 3), n=28)
    for k in range(10):                                        # dome in panels
        t0 = k / 10
        r = R * math.cos(t0 * math.pi / 2)
        tone = rgb("#e4dccc") * (1.0 if k % 3 else 0.95)
        ring(s, max(r, 0.05), H + math.sin(t0 * math.pi / 2) * 46, 5, lambda i, tone=tone: flat(s, tone * (0.97 if i % 4 == 0 else 1.0), 3), n=28)
    s.blob((0, 0, H + 48), 5, ramp("#c8c2b6", "#e0d8c8", "#f0ece4"), squash=0.6)
    s.box(-0.14, R - 0.05, 24, 0.28, 0.06, 18, *(flat(s, c) for c in ("#8e8680", "#76706a", "#6a645e")))   # equipment hatch
    s.box(-0.35, R - 0.02, 4, 0.7, 0.42, 30, flat(s, "#bdb3a2"),
          wall_shader(s, "#d0c8b8", 0.7 * 71.6, 30, 2, spans(3), (0.42, 0.58), None, "plain"),
          wall_shader(s, "#d0c8b8", 0.42 * 71.6, 30, 2, spans(1), None, None, "plain"))
    for z in range(0, 118, 5):                                 # vent stack
        ring(s, 0.09, z, 5, lambda k, z=z: flat(s, "#e0d8c8" if (z // 20) % 2 else "#b0341f", 3), n=10, cx=R + 0.25, cy=-0.3)
    s.outline(0.72)
    return s, (2 * R + 0.24, 2 * R + 0.24)


def atom_tex(W=64, H=40):
    """Sign face: a classic atom (three orbits round a nucleus, electrons)
    over NUCLEAR, dark blue on white with a blue border."""
    t = np.zeros((H, W, 3))
    t[:] = rgb("#f0f2f4")
    ys, xs = np.mgrid[0:H, 0:W]
    cx, cy, A, B = W / 2 - 0.5, 14.5, 17, 6
    ink = np.zeros((H, W), bool)
    for k, ang in enumerate((0, 60, 120)):
        a = math.radians(ang)
        for step in range(360):
            q = math.radians(step)
            x, y = A * math.cos(q), B * math.sin(q)
            px, py = cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) * 0.75 + y * math.cos(a) * 0.75
            ix, iy = int(round(px)), int(round(py))
            if 0 <= ix < W and 0 <= iy < H:
                ink[iy, ix] = True
        q = math.radians(40 + 110 * k)                        # an electron on each orbit
        x, y = A * math.cos(q), B * math.sin(q)
        ex, ey = cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) * 0.75 + y * math.cos(a) * 0.75
        t[(np.hypot(xs - ex, ys - ey) < 1.8)] = rgb("#3a8ac8")
    t[ink] = rgb("#1e3a6a")
    t[np.hypot(xs - cx, ys - cy) < 3] = rgb("#c8402a")        # nucleus
    bits = text_bits("NUCLEAR")
    bx, by = (W - bits.shape[1]) // 2, H - 10
    t[by:by + 7, bx:bx + bits.shape[1]][bits] = rgb("#1e3a6a")
    edge = (xs == 0) | (xs == W - 1) | (ys == 0) | (ys == H - 1)
    t[edge] = rgb("#3a6ab0")
    return t


def atom_sign(seed):
    """The plant's entrance sign: the atom board on two posts on a low
    stone base, facing +v."""
    s = Sprite(140, 130, 70, 100, seed)
    w, z0, h = 1.0, 12, 40
    s.box(-w / 2 - 0.05, -0.08, 0, w + 0.1, 0.16, 5, *(flat(s, c) for c in ("#d8d0c0", "#bdb3a2", "#a69c8c")))
    for x in (-w / 2 + 0.05, w / 2 - 0.08):
        s.box(x, -0.02, 5, 0.03, 0.03, z0, *(flat(s, c, 2) for c in STEEL))
    face = texture(s, atom_tex(int(w * HW), h))
    s.box(-w / 2, -0.03, z0 + 5, w, 0.06, h, flat(s, "#3a6ab0"), face, flat(s, "#3a6ab0"))
    s.outline(0.8)
    return s


def pylon(seed):
    """High-voltage transmission tower: a tapering lattice with two cross
    arms and hanging insulators, wires running off along v."""
    s = Sprite(170, 240, 85, 200, seed)
    H = 130
    half = lambda z: 0.22 * (1 - z / H) + 0.05
    col = rgb("#5e5a64")
    for cx, cy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        p0, p1 = s.proj(cx * half(0), cy * half(0), 0), s.proj(cx * half(H), cy * half(H), H)
        for dx in (0, 1):
            s.line((p0[0] + dx, p0[1]), (p1[0] + dx, p1[1]), col * (1.0 if dx else 0.8), (cx + cy) * 0.1)
    for z0 in range(0, H, 16):                                  # lattice
        z1 = z0 + 16
        for (ax, ay), (bx, by) in (((-1, 1), (1, 1)), ((1, -1), (1, 1))):
            s.line(s.proj(ax * half(z0), ay * half(z0), z0), s.proj(bx * half(z1), by * half(z1), z1), col * 0.9, 0.15)
            s.line(s.proj(bx * half(z0), by * half(z0), z0), s.proj(ax * half(z1), ay * half(z1), z1), col * 0.9, 0.15)
    for z, w in ((96, 0.55), (120, 0.4)):                        # cross arms along u, insulators, wires along v
        for dz in (0, 1, 2):
            s.line(s.proj(-w, 0, z + dz), s.proj(w, 0, z + dz), col * (0.8 if dz == 2 else 1.0), 0.3)
        for x in (-w + 0.05, w - 0.05):
            s.line(s.proj(x, 0, z), s.proj(x, 0, z - 8), rgb("#c8b8a0"), 0.35)
            for d in (-1, 1):
                s.line(s.proj(x, 0, z - 8), s.proj(x, d * 0.9, z - 18), rgb("#2e2d30"), 0.36)
    s.outline(0.85)
    return s


def dry_casks(seed):
    """Dry cask storage: a concrete pad with two rows of tall gray casks."""
    s = Sprite(300, 190, 150, 120, seed)
    a, b = 2.2, 1.2
    x0, y0 = -a / 2, -b / 2
    s.box(x0, y0, 0, a, b, 3, *(flat(s, c) for c in ("#c8c2b6", "#b3ab9e", "#9c9486")))
    for r in range(2):
        for k in range(5):
            cx, cy = x0 + 0.24 + k * 0.43, y0 + 0.3 + r * 0.6
            ring(s, 0.15, 3, 30, lambda i: banded(s, [rgb("#a8a4ae"), rgb("#9c98a2")], 5, axis=1), n=14, cx=cx, cy=cy)
            disk(s, 0.15, 33, flat(s, "#bdb8c2", 3), n=14, cx=cx, cy=cy)
            s.blob((cx, cy, 34), 2, ramp("#716f74", "#8e8a94", "#a8a4ae"), squash=0.5)
    s.outline(0.75)
    return s, (a, b)


def generator_house(seed):
    """Emergency diesel generator house: louvred concrete walls, three
    exhaust stacks, a fuel tank on saddles at its side."""
    s = Sprite(260, 220, 130, 150, seed)
    a, b, h = 1.4, 0.9, 30
    x0, y0 = -a / 2, -b / 2

    def wall(length_px, door):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.repeat(rgb("#c8c2b6")[None], len(a_), 0)
            louv = (z > 12) & (z < 24) & (np.mod(along, 14) > 3) & (np.mod(along, 14) < 11) & (np.mod(z, 2) < 1)
            out = np.where(louv[:, None], rgb("#6e6a64"), out)
            if door:
                d = (np.abs(along - length_px * 0.5) < 6) & (z < 20)
                out = np.where(d[:, None], rgb("#5b5a5c"), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 4
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#b3ab9e"), wall(a * 71.6, True), wall(b * 71.6, False))
    for k in range(3):
        cx = x0 + 0.3 + k * 0.4
        ring(s, 0.05, h, 26, lambda i: flat(s, "#716f74", 3), n=10, cx=cx, cy=y0 + 0.3)
        disk(s, 0.05, h + 26, flat(s, "#2e2e32", 2), n=10, cx=cx, cy=y0 + 0.3)
    for k in range(8):                                        # fuel tank on its side, along v
        t0 = k / 8
        s.face((x0 + a + 0.06 + 0.24 * math.sin(math.pi * t0) * 0, y0 + 0.05, 4 + 16 * math.sin(math.pi * t0)),
               (0, b - 0.1, 0), (0.24 / 8, 0, 16 * (math.sin(math.pi * (t0 + 1 / 8)) - math.sin(math.pi * t0))),
               flat(s, rgb("#d8d4cc") * (0.8 + 0.25 * t0), 3))
    s.box(x0 + a + 0.06, y0 + 0.05, 0, 0.3, b - 0.1, 12, *(flat(s, c) for c in ("#d8d4cc", "#c8c4bc", "#b8b4ac")))
    s.outline(0.75)
    return s, (a, b)


def control_building(seed):
    """Control building: a squat reinforced block, slit windows, a door in
    a recess, antennas on the roof."""
    s = Sprite(260, 220, 130, 160, seed)
    a, b, h = 1.6, 1.2, 38
    x0, y0 = -a / 2, -b / 2

    def wall(length_px, door):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.where((np.mod(z, 10) < 1)[:, None], rgb("#bcb4a4"), rgb("#d0c8b8"))
            slit = (z > 24) & (z < 30) & (np.mod(along, 16) > 6) & (np.mod(along, 16) < 12)
            out = np.where(slit[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4], out)
            if door:
                d = (np.abs(along - length_px * 0.5) < 7) & (z < 18)
                out = np.where(d[:, None], rgb("#5b5a5c"), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 4
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#b3ab9e"), wall(a * 71.6, True), wall(b * 71.6, False))
    s.box(x0 - 0.04, y0 - 0.04, h, a + 0.08, b + 0.08, 4, *(flat(s, c) for c in ("#c8c0b0", "#b3ab9e", "#9c9486")))
    for x, hh in ((x0 + 0.3, 26), (x0 + 0.5, 18)):
        s.box(x, y0 + 0.3, h + 4, 0.02, 0.02, hh, *(flat(s, c, 2) for c in STEEL))
    s.blob((x0 + a - 0.4, y0 + 0.4, h + 12), 5, ramp("#9a9488", "#c8c2b6", "#e8e2d6"), squash=0.55, shade=0.2)
    s.outline(0.72)
    return s, (a, b)


def watchtower(seed):
    """Guard watchtower: four legs, a glazed cab with a roof and a searchlight."""
    s = Sprite(120, 190, 60, 160, seed)
    steel = [flat(s, c, 2) for c in ("#8e8a94", "#716f74", "#5b5a5c")]
    for x, y in ((-0.14, -0.14), (0.11, -0.14), (0.11, 0.11), (-0.14, 0.11)):
        s.box(x, y, 0, 0.03, 0.03, 70, *steel)
    for z in (22, 46):
        s.line(s.proj(-0.13, 0.12, z), s.proj(0.12, 0.12, z + 22), rgb("#716f74"), 0.25)
    cab = lambda a_, b_, xs, ys: np.where(((b_ > 0.35) & (b_ < 0.85))[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.15, rgb("#c8c4bc"))
    s.box(-0.18, -0.18, 70, 0.36, 0.36, 22, flat(s, "#c8c4bc"), cab, cab)
    s.box(-0.22, -0.22, 92, 0.44, 0.44, 3, *(flat(s, c) for c in ("#5b5a5c", "#4a494b", "#3e3d3f")))
    s.blob((0.12, 0.12, 97), 2.5, ramp("#c8a030", "#f2d070", "#fff4c0"))
    s.outline(0.8)
    return s


def rd_lab(seed):
    """R&D lab: two white floors with ribbon windows in blue glass, a glass
    entrance, rooftop plant and a small dish, a LAB sign."""
    s = Sprite(360, 260, 180, 180, seed)
    a, b, h = 2.2, 1.3, 50
    x0, y0 = -a / 2, -b / 2

    def wall(length_px, door):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.repeat(rgb("#e8e6e0")[None], len(a_), 0)
            rib = ((z > 8) & (z < 20)) | ((z > 30) & (z < 42))
            out = np.where(rib[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.15, out)
            out = np.where((rib & (np.mod(along, 12) < 1))[:, None], rgb("#c8c4bc"), out)
            if door:
                d = np.abs(along - length_px * 0.5) < 10
                out = np.where((d & (z < 20))[:, None], np.array(GLASS_BLUE)[1] * 1.2, out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 3
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#d8d6d0"), wall(a * 71.6, True), wall(b * 71.6, False))
    s.box(x0 - 0.03, y0 - 0.03, h, a + 0.06, b + 0.06, 3, *(flat(s, cc) for cc in ("#c8c4bc", "#b8b4ac", "#a8a49c")))
    s.box(-0.3, y0 + b, 20, 0.6, 0.22, 3, *(flat(s, cc) for cc in ("#3a6ab0", "#2f5a98", "#244880")))       # entrance canopy
    for k in range(3):
        s.box(x0 + 0.3 + k * 0.45, y0 + 0.25, h + 3, 0.28, 0.28, 10, fan_top(s), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    s.box(x0 + a - 0.45, y0 + 0.3, h + 3, 0.05, 0.05, 12, *(flat(s, cc) for cc in STEEL))
    s.blob((x0 + a - 0.43, y0 + 0.32, h + 20), 6, ramp("#9a9488", "#c8c2b6", "#e8e2d6"), squash=0.55, shade=0.2)
    s.outline(0.72)
    return s, (a, b)


def guardhouse(seed):
    """Security booth: glazed on every side, a deep flat roof, a light."""
    s = Sprite(90, 100, 45, 70, seed)
    a = 0.36
    glass = lambda a_, b_, xs, ys: np.where(((b_ > 0.35) & (b_ < 0.85) & (np.mod(a_ * 3, 1) > 0.12))[:, None],
                                            np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.2, rgb("#d8d4cc"))
    s.box(-a / 2, -a / 2, 0, a, a, 24, flat(s, "#d8d4cc"), glass, glass)
    s.box(-a / 2 - 0.07, -a / 2 - 0.07, 24, a + 0.14, a + 0.14, 3, *(flat(s, cc) for cc in ("#3a6ab0", "#2f5a98", "#244880")))
    s.blob((0, 0, 29), 1.8, ramp("#c8402a", "#f07050", "#f8c0a0"))
    s.outline(0.8)
    return s


def check_canopy(seed, span=3.0):
    """Checkpoint canopy over the lanes: a flat roof on four posts with a
    SECURITY band on its street side (+v)."""
    s = Sprite(320, 170, 160, 110, seed)
    d = 0.7
    x0, y0 = -span / 2, -d / 2
    for x in (x0 + 0.05, x0 + span - 0.09):
        for y in (y0 + 0.05, y0 + d - 0.09):
            s.box(x, y, 0, 0.04, 0.04, 34, *(flat(s, cc, 2) for cc in STEEL))
    band = lambda length: (lambda a_, b_, xs, ys: np.where(((b_ > 0.3) & (b_ < 0.7))[:, None], rgb("#c8a030"), rgb("#2c3548")))
    s.box(x0, y0, 34, span, d, 12, flat(s, "#c8c4bc"), band(span), band(d))
    for x in (x0 + 0.2, x0 + span - 0.24):                               # yellow bollards
        s.box(x, y0 + d + 0.1, 0, 0.04, 0.04, 8, *(flat(s, "#c8a030") for _ in range(3)))
    s.outline(0.8)
    return s


def turbine_hall(seed, a=4.6, b=1.4):
    """Turbine hall: a tall blue-gray clad hall with a band of high windows,
    a lower annex along its front, roof vents and a glazed monitor, and two
    main transformers with fins and bushings at its +u end."""
    s = Sprite(520, 320, 260, 210, seed)
    x0, y0, h = -a / 2, -b / 2, 56

    def wall(length_px):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.where((np.mod(along, 3) < 1)[:, None], rgb("#a4b0ba"), rgb("#b8c4cc"))
            win = (z > 40) & (z < 50) & (np.mod(along, 12) > 2)
            out = np.where(win[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.1, out)
            out = np.where((z < 4)[:, None], rgb("#a69c8c"), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 3
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#8e98a0"), wall(a * 71.6), wall(b * 71.6))
    s.box(x0 - 0.03, y0 - 0.03, h, a + 0.06, b + 0.06, 3, *(flat(s, c) for c in ("#7a8a96", "#6a7a86", "#5a6a76")))
    mon = lambda a_, b_, xs, ys: np.where((b_ > 0.3)[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.15, rgb("#7a8a96"))
    s.box(x0 + 0.3, y0 + 0.45, h + 3, a - 0.6, 0.5, 8, flat(s, "#6a7a86"), mon, mon)
    for k in range(3):
        s.box(x0 + 0.5 + k * 1.4, y0 + 0.1, h + 3, 0.22, 0.22, 7, fan_top(s), flat(s, "#9791a2"), flat(s, "#716f74"))
    annex = lambda a_, b_, xs, ys: np.where(((np.mod(a_ * a * 71.6, 18) > 4) & (b_ > 0.35) & (b_ < 0.75))[:, None],
                                            np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.05, rgb("#c8ccd0"))
    s.box(x0 + 0.2, y0 + b, 0, a - 0.4, 0.3, 22, flat(s, "#a4b0ba"), annex, flat(s, "#b8c0c6"))
    for k in range(2):                                        # main transformers at the +u end
        tx = x0 + a + 0.12
        ty = y0 + 0.1 + k * 0.62
        s.box(tx, ty, 0, 0.38, 0.5, 22, *(flat(s, c) for c in ("#7a8a7a", "#6a7a6a", "#5a6a5a")))
        for f in range(5):
            s.box(tx + 0.38, ty + 0.04 + f * 0.09, 2, 0.05, 0.03, 18, *(flat(s, "#5a6a5a") for _ in range(3)))
        for ix in (0.08, 0.19, 0.3):
            s.box(tx + ix, ty + 0.22, 22, 0.02, 0.02, 12, *(flat(s, "#c8b8a0") for _ in range(3)))
            s.blob((tx + ix + 0.01, ty + 0.23, 35), 1.6, ramp("#8a6a4a", "#c8b8a0", "#e8e2d6"))
    s.outline(0.72)
    return s, (a, b)


# ---------- hospital ----------

def cross_tex(D=26):
    """A red cross on a white round-cornered board."""
    t = np.zeros((D, D, 4))
    t[1:D - 1, 1:D - 1] = [*rgb("#f4f4f0"), 255]
    t[0, 2:D - 2] = t[D - 1, 2:D - 2] = t[2:D - 2, 0] = t[2:D - 2, D - 1] = [*rgb("#f4f4f0"), 255]
    w = D // 5
    c = D // 2
    t[4:D - 4, c - w:c + w] = [*rgb("#c8302a"), 255]
    t[c - w:c + w, 4:D - 4] = [*rgb("#c8302a"), 255]
    return t


def hospital(seed):
    """Hospital: a long white block of five floors with blue ribbon
    windows, a lobby canopy at the centre of the front, a red EMERGENCY bay
    at the +u end, HOSPITAL on the facade, a red cross board on the roof and
    a helipad."""
    s = Sprite(520, 420, 260, 300, seed)
    a, b, floors, fh = 4.6, 1.6, 5, 28
    h = floors * fh + 4
    x0, y0 = -a / 2, -b / 2
    rng = np.random.default_rng(seed)

    def wall(length_px, doors):
        def sh(a_, b_, xs, ys):
            along, z = a_ * length_px, b_ * h
            out = np.repeat(rgb("#ecebe6")[None], len(a_), 0)
            win = (np.mod(z, fh) > 9) & (np.mod(z, fh) < 20) & (z > fh)
            out = np.where(win[:, None], np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.15, out)
            out = np.where((win & (np.mod(along, 16) < 1))[:, None], rgb("#d0cec8"), out)
            out = np.where((np.mod(z, fh) < 2)[:, None], rgb("#c8c6be"), out)            # floor bands
            out = np.where((z < fh)[:, None] & (np.mod(along, 20) > 4)[:, None] & (z > 4)[:, None] & (z < fh - 4)[:, None],
                           np.array(GLASS_BLUE)[(xs + ys) % 4] * 1.25, out)             # glazed ground floor
            for d0, d1 in doors:
                dd = (along >= d0 * length_px) & (along < d1 * length_px) & (z < fh - 4)
                out = np.where(dd[:, None], np.array(GLASS_BLUE)[1] * 1.35, out)
                out = np.where((dd & (np.abs(along - (d0 + d1) / 2 * length_px) < 0.6))[:, None], rgb("#5b5a5c"), out)
            return out + (s.grain[ys, xs] - 0.5)[:, None] * 3
        return sh
    s.box(x0, y0, 0, a, b, h, flat(s, "#d8d6d0"), wall(a * 71.6, [(0.46, 0.54)]), wall(b * 71.6, [(0.3, 0.7)]))
    s.box(x0 - 0.04, y0 - 0.04, h, a + 0.08, b + 0.08, 4, *(flat(s, c) for c in ("#d8d6d0", "#c8c6be", "#b8b6ae")))
    draw_helipad(s, x0 + a * 0.48, y0, a * 0.36, b, h + 4)          # the helipad
    for k in range(3):                                            # plant at the far end of the roof
        s.box(x0 + a - 0.42, y0 + 0.15 + k * 0.45, h + 4, 0.3, 0.3, 10, fan_top(s), flat(s, "#bdb3a2"), flat(s, "#a69c8c"))
    roof_board(s, x0, y0, a * 0.48, b, h + 4, "HOSPITAL", "#f4f4f0", "#c8302a", w=1.4, tex=cross_tex(), tex_w=0.42, tex_h=26)
    # Lobby canopy at the centre of the front.
    s.box(-0.5, y0 + b, 26, 1.0, 0.36, 4, *(flat(s, c) for c in ("#3a6ab0", "#2f5a98", "#244880")))
    for px in (-0.46, 0.43):
        s.box(px, y0 + b + 0.32, 0, 0.03, 0.03, 26, *(flat(s, c, 2) for c in STEEL))
    # Emergency bay: a red canopy over the +u end of the front.
    ex = x0 + a - 1.1
    band = lambda length: (lambda a_, b_, xs, ys: np.where(((b_ > 0.25) & (b_ < 0.75))[:, None], rgb("#f4f4f0"), rgb("#c8302a")))
    s.box(ex, y0 + b, 24, 0.95, 0.5, 12, flat(s, "#b8b6ae"), band(0.95), band(0.5))
    wall_sign(s, ex + 0.475, y0 + b + 0.5, 25, 0.92, "EMERGENCY", "#c8302a", "#f4f4f0", 10)
    for px in (ex + 0.03, ex + 0.9):
        s.box(px, y0 + b + 0.45, 0, 0.03, 0.03, 24, *(flat(s, c, 2) for c in STEEL))
    s.outline(0.72)
    return s, (a, b)


def ambulance(seed, rot=0):
    """Ambulance van along u (turned by rot): white body, red stripe, a
    light bar on the roof, a dark windscreen at +u."""
    s = Sprite(110, 80, 55, 55, seed)
    s.rot = rot
    white, red = rgb("#f4f4f0"), rgb("#c8302a")
    side = lambda a_, b_, xs, ys: np.where(((b_ > 0.35) & (b_ < 0.52))[:, None], red,
                                           np.where(((b_ > 0.7) & (a_ > 0.8))[:, None], np.array(GLASS)[1], white))
    nose = lambda a_, b_, xs, ys: np.where((b_ > 0.62)[:, None], np.array(GLASS)[(xs + ys) % 4] * 1.1,
                                           np.where(((b_ > 0.35) & (b_ < 0.52))[:, None], red, white))
    s.box(-0.3, -0.12, 3, 0.6, 0.24, 17, flat(s, white * 0.96), side, nose)
    if rot:
        s.face((-0.3, -0.12, 3), (0.6, 0, 0), (0, 0, 17), side, light="auto")
        s.face((0.3, -0.12, 3), (0, 0.24, 0), (0, 0, 17), nose, light="auto")
        s.face((-0.3, -0.12, 3), (0, 0.24, 0), (0, 0, 17), flat(s, white), light="auto")
    s.box(0.12, -0.08, 20, 0.08, 0.16, 3, flat(s, "#3a6ad0"), flat(s, "#c8302a"), flat(s, "#3a6ad0"))
    for x in (-0.22, 0.18):
        for y in (-0.13, 0.11):
            s.box(x, y, 0, 0.07, 0.02, 4, *(flat(s, "#1e1e22") for _ in range(3)))
    s.outline(0.8)
    return s


# ---------- recreation ----------

REC_WOOD = ("#8a6751", "#765743", "#5f4646")
BRICK = ("#8a4a3e", "#7d4a3e", "#6a3a30")


def picnic_table(seed):
    """Wooden picnic table with a bench along each long side."""
    s = Sprite(90, 60, 45, 38, seed)
    wood = [flat(s, c, 6) for c in REC_WOOD]
    for y in (-0.2, 0.14):                                          # benches
        for x in (-0.22, 0.2):
            s.box(x, y + 0.02, 0, 0.02, 0.02, 5, *wood)
        s.box(-0.26, y, 5, 0.52, 0.07, 2, *wood)
    for x in (-0.2, 0.18):                                          # legs
        s.box(x, -0.08, 0, 0.03, 0.18, 9, *wood)
    s.box(-0.28, -0.12, 9, 0.56, 0.24, 2, banded(s, [rgb(c) for c in REC_WOOD[:2]], 5, axis=1), *wood[1:])
    s.outline(0.75)
    return s


def barbecue(seed):
    """Brick barbecue: a waist-high brick stand, dark grate, back chimney."""
    s = Sprite(80, 80, 40, 60, seed)
    brick = [flat(s, c, 8) for c in BRICK]

    def grate(a, b, xs, ys):
        bars = np.mod(a * 12, 1) < 0.4
        return np.where(bars[:, None], rgb("#4a494b"), rgb("#2e2a28")) + (s.grain[ys, xs] - 0.5)[:, None] * 4
    s.box(-0.2, -0.12, 0, 0.4, 0.24, 11, grate, brick[1], brick[2])
    s.box(-0.2, -0.16, 0, 0.4, 0.05, 20, brick[0], brick[1], brick[2])      # back wall
    s.box(-0.07, -0.16, 20, 0.14, 0.06, 9, flat(s, "#5b5a5c"), brick[1], brick[2])  # chimney
    s.blob((0.0, 0.0, 12), 1.6, ramp("#8a3a28", "#c8641c", "#f2a040"))       # embers
    s.outline(0.75)
    return s


def swing_set(seed):
    """Swing set: two posts and a top bar along u, two seats on chains."""
    s = Sprite(120, 90, 60, 68, seed)
    steel = [flat(s, c, 3) for c in ("#3f6f73", "#34595c", "#2a4749")]
    for x in (-0.4, 0.38):
        for y in (-0.12, 0.1):
            s.box(x, y, 0, 0.025, 0.025, 28, *steel)
    s.box(-0.41, -0.01, 28, 0.82, 0.03, 2, *steel)
    for x in (-0.18, 0.14):
        top = s.proj(x + 0.02, 0.0, 28)
        seat = s.proj(x + 0.02, 0.0, 7)
        for dx in (-3, 3):
            s.line((top[0] + dx, top[1]), (seat[0] + dx, seat[1]), rgb("#9791a2"), x + 0.2)
        s.box(x - 0.03, -0.05, 6, 0.1, 0.1, 1, flat(s, "#8a3a32"), flat(s, "#6e2420"), flat(s, "#5a1e1a"))
    s.outline(0.8)
    return s


def slide(seed):
    """Playground slide: a ladder up to a small deck, the chute down +u."""
    s = Sprite(110, 90, 50, 64, seed)
    steel = [flat(s, c, 3) for c in ("#9791a2", "#716f74", "#5b5a5c")]
    for x in (-0.3, -0.12):
        for y in (-0.09, 0.07):
            s.box(x, y, 0, 0.025, 0.025, 18, *steel)
    s.box(-0.31, -0.1, 18, 0.21, 0.2, 2, flat(s, "#c9a84a"), flat(s, "#a88a38"), flat(s, "#86692c"))
    for z in (4, 9, 14):                                          # ladder rungs on the -u side
        s.box(-0.33, -0.08, z, 0.02, 0.16, 1, *steel)
    yellow = rgb("#c8a030")

    def chute(a, b, xs, ys):
        rail = (b < 0.18) | (b > 0.82)
        return np.where(rail[:, None], yellow * 0.8, yellow) + (s.grain[ys, xs] - 0.5)[:, None] * 4
    s.face((-0.1, -0.08, 19), (0.5, 0, -17), (0, 0.16, 0), chute, light=0.95)
    s.box(0.38, -0.08, 0, 0.03, 0.16, 2, *steel)
    s.outline(0.8)
    return s


def seesaw(seed):
    """Seesaw: a red plank tilted over a small pivot, handles at each end."""
    s = Sprite(90, 60, 45, 40, seed)
    s.box(-0.04, -0.04, 0, 0.08, 0.08, 6, flat(s, "#5b5a5c"), flat(s, "#4a494b"), flat(s, "#3e3d3f"))
    red = rgb("#8a3a32")
    s.face((-0.42, -0.04, 1), (0.84, 0, 11), (0, 0.08, 0), flat(s, red, 4), light=0.95)
    s.face((-0.42, 0.04, 1), (0.84, 0, 11), (0, 0, 2), flat(s, red * 0.7, 3), light=0.9)
    for x, z in ((-0.33, 2), (0.33, 10)):
        s.box(x, -0.01, z, 0.02, 0.02, 5, flat(s, "#2e3336"), flat(s, "#2e3336"), flat(s, "#2e3336"))
    s.outline(0.8)
    return s


def fountain(seed, p=0.0):
    """Town square fountain at phase p in [0, 1): round stone basin of
    water, a pedestal with an upper bowl, a bobbing spout on top, droplets
    running down the streams from the bowl and ripples spreading out."""
    s = Sprite(130, 110, 65, 70, seed)
    stone = rgb("#c9bfae")
    ring(s, 0.46, 0, 6, lambda k: flat(s, stone * 0.95, 5), n=24)
    disk(s, 0.46, 6, flat(s, stone * 1.08, 4), n=24)
    water = ramp("#2f8191", "#3e92a2", "#5aa8b4")
    foam = rgb("#b8dce0")

    def pool(z, radius, speed):
        cx, cy = s.proj(0, 0, z)

        def shader(a, b, xs, ys):
            out = np.array(water)[(xs // 3 + ys + int(p * 6)) % 3] + (s.grain[ys, xs] - 0.5)[:, None] * 6
            r = np.hypot(xs + 0.5 - cx, (ys + 0.5 - cy) * 2) / radius        # 0 at the middle, 1 at the rim
            ripple = (np.mod(r - p * speed, 0.5) < 0.045) & (r > 0.3) & (r < 0.95)
            return np.where(ripple[:, None], out * 0.55 + foam * 0.45, out)
        return shader
    disk(s, 0.4, 6.5, pool(6.5, 0.4 * 90.5, 0.5), n=24)
    ring(s, 0.06, 6, 16, lambda k: flat(s, stone, 4), n=10)
    ring(s, 0.18, 22, 3, lambda k: flat(s, stone * 0.92, 4), n=16)
    disk(s, 0.18, 25, flat(s, stone * 1.1, 4), n=16)
    disk(s, 0.14, 25.5, pool(25.5, 0.14 * 90.5, 0.5), n=16)
    bob = math.sin(2 * math.pi * p)
    top = 34 + 1.5 * bob                                        # jet up from the bowl, crowned with spray
    base, crown = s.proj(0, 0, 26), s.proj(0, 0, top)
    for dx in (-0.5, 0.5):
        s.line((base[0] + dx, base[1]), (crown[0] + dx, crown[1]), foam, 0.3)
    s.blob((0, 0, top), 2.0 + 0.3 * bob, ramp("#8ec4cc", "#b8dce0", "#e0f0f0"), squash=1.2)
    rng = np.random.default_rng(seed + int(p * 8))
    for _ in range(4):
        a = rng.uniform(0, 2 * math.pi)
        x, y = s.proj(0.05 * math.cos(a), 0.05 * math.sin(a), top - rng.uniform(1, 5))
        s.line((x, y), (x, y), rgb("#e8f4f4"), 0.31)
    for k in range(6):                                          # water falling from the bowl
        t = 2 * math.pi * k / 6
        x0, y0 = 0.17 * math.cos(t), 0.17 * math.sin(t)
        top, bot = s.proj(x0, y0, 24), s.proj(x0 * 1.3, y0 * 1.3, 7)
        s.line(top, bot, foam, x0 + y0 + 0.2)
        for q in ((p + k * 0.37) % 1, (p + k * 0.37 + 0.5) % 1):   # droplets running down
            x, y = top[0] + (bot[0] - top[0]) * q, top[1] + (bot[1] - top[1]) * q
            s.line((x, y), (x, y + 1), rgb("#e8f4f4"), x0 + y0 + 0.21)
    s.outline(0.75)
    return s


def barrel(seed):
    s = Sprite(40, 50, 20, 40, seed)
    for z in range(0, 14, 2):
        s.blob((0, 0, z + 2), 6, ramp("#4f3423", "#62432d", "#765743", "#8a6751"), squash=0.5, shade=0.2 if z % 6 else -0.3)
    s.outline()
    return s


def buoy(seed, p=None):
    """Red buoy; with a phase p it bobs on ripples."""
    s = Sprite(50, 50, 25, 36, seed)
    if p is not None:
        ripples(s, 0.07, 0.07, p)
        s.dz = 1.5 * math.sin(2 * math.pi * p)
    s.blob((0, 0, 5), 5, ramp("#6a2a24", "#8a3a30", "#a8564a", "#c07060"), squash=0.8)
    s.blob((0, 0, 11), 3, ramp("#9a9488", "#b8b0a2", "#d8ccb4"))
    s.outline()
    return s


# ---------- output ----------

MANIFEST = {}


def save(sprite, rel, mirror=False, **meta):
    """Crop and save a sprite; mirror=True flips it, swapping its u and v."""
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    img, ox = sprite.image(), sprite.ox
    if mirror:
        img, ox = img.transpose(Image.FLIP_LEFT_RIGHT), img.width - sprite.ox
    bbox = img.getbbox()
    img = img.crop(bbox)
    img.save(path)
    MANIFEST[rel] = {"size": list(img.size), "anchor": [round(ox - bbox[0], 1), round(sprite.oy - bbox[1], 1)], **meta}


def save_anim(frames, rel, **meta):
    """Frames of one sprite (same origin) cropped to their joint bounds and
    saved side by side; the manifest gives the frame size and count."""
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    imgs = [f.image() for f in frames]
    boxes = [bb for bb in (im.getbbox() for im in imgs) if bb]   # a frame may be empty (all hidden)
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    w, h = x1 - x0, y1 - y0
    atlas = Image.new("RGBA", (w * len(imgs), h))
    for k, im in enumerate(imgs):
        atlas.paste(im.crop((x0, y0, x1, y1)), (k * w, 0))
    atlas.save(path)
    MANIFEST[rel] = {"size": [w, h], "anchor": [round(frames[0].ox - x0, 1), round(frames[0].oy - y0, 1)],
                     "frames": len(imgs), **meta}


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
            save_tile(foam(sides, corners, seed=70 + mask), f"ground/foam-{name}.png")
    save_tile(shore("", seed=68), "ground/water-a.png")
    save_tile(shore("", seed=69), "ground/water-b.png")
    save_tile(glints(90), "ground/glints.png")
    # Grass-to-sand transition: the same 47 combinations as the shoreline.
    for mask in range(16):
        sides = "".join(k for i, k in enumerate("nesw") if mask >> i & 1)
        free = [c for c in ("ne", "es", "sw", "wn") if not set(c) & set(sides)]
        for cm in range(1 << len(free)):
            corners = [c for i, c in enumerate(free) if cm >> i & 1]
            if not sides and not corners:
                continue
            name = sides + ("-" + "".join(corners) if corners else "")
            save_tile(dune(sides, corners, seed=170 + mask), f"ground/dune-{name}.png")
    # Beach
    save(umbrella(101, "#8a4a3e"), "beach/umbrella-red.png")
    save(umbrella(102, "#3f6f73"), "beach/umbrella-teal.png")
    save(umbrella(103, "#8f7a3a"), "beach/umbrella-gold.png")
    # Turned versions: <name>-r1 .. -r3 (90° steps, x, y -> -y, x).
    turn = lambda k: "" if k == 0 else f"-r{k}"
    for k in range(4):
        save(lounger(104, "#3f6f73", rot=k), f"beach/lounger-teal{turn(k)}.png")
        save(lounger(105, "#8a4a3e", rot=k), f"beach/lounger-red{turn(k)}.png")
        save(lifeguard(108, rot=k), f"beach/lifeguard-tower{turn(k)}.png")        # faces +v, -u, -v, +u
    for k in range(2):
        save(towel(106, "#8f6f9a", rot=k), f"beach/towel-purple{turn(k)}.png")
        save(towel(107, "#3f6f73", rot=k), f"beach/towel-teal{turn(k)}.png")
    save(marram(130), "nature/dune/marram.png")
    # Parking lot: asphalt with stall lines, the fence, animated gates.
    save_tile(lot_tile(160), "ground/lot.png")
    save_tile(concrete_tile(166), "ground/concrete.png")
    save_tile(concrete_tile(167, stains=True), "ground/concrete-b.png")
    save_tile(lot_tile(161, "u"), "ground/lot-lines-u.png")
    save_tile(lot_tile(162, "v"), "ground/lot-lines-v.png")
    for ax in ("u", "v"):
        for hf in ("lo", "hi"):
            save_tile(lot_tile(162, ax, hf), f"ground/lot-lines-{ax}-{hf}.png")
    save(fence(163), "parking/fence.png")
    save(fence(163, rot=1), "parking/fence-r1.png")
    save(park_sign(166), "parking/sign.png")
    save_anim([gate(164, 1, k / 7) for k in range(8)], "parking/gate-l.png", footprint=[0.1, 0.1])
    save_anim([gate(165, -1, k / 7) for k in range(8)], "parking/gate-r.png", footprint=[0.1, 0.1])
    # Street furniture; turned versions -r1..-r3 as for the beach props.
    turns = lambda k: "" if k == 0 else f"-r{k}"
    for k in range(4):
        save(bus_stop_fancy(170, k), f"street/bus-stop{turns(k)}.png")
        save(bus_stop_simple(171, k), f"street/bus-stop-simple{turns(k)}.png")
        save(vending(172, "#8a3a32", k), f"street/vending-red{turns(k)}.png")
        save(vending(173, "#2f5a88", k), f"street/vending-blue{turns(k)}.png")
        save(phone_booth(174, k), f"street/phone-booth{turns(k)}.png")
    for kind in ("green", "wire", "recycle"):
        save(trash_can(175, kind), f"street/bin-{kind}.png")
    save(statue(176, "figure"), "street/statue.png")
    save(statue(177, "obelisk"), "street/obelisk.png")
    # Port.
    turn = lambda k: "" if k == 0 else f"-r{k}"
    for k in range(2):
        for name, (rows, tiers, cols) in (("a", (2, 3, 1)), ("b", (3, 2, 1)), ("c", (2, 2, 2))):
            save(container_stack(200 + ord(name), rows, tiers, cols, k), f"port/stack-{name}{turn(k)}.png")
        save(cargo_ship(210, "#2e3a4a", k), f"port/ship-a{turn(k)}.png")
        save(cargo_ship(211, "#6a2a24", k), f"port/ship-b{turn(k)}.png")
    for k in range(4):
        save(gantry_crane(212, k), f"port/crane{turn(k)}.png")
    for name, (a, b, col) in (("a", (2.4, 1.3, "#8e8897")), ("b", (2.0, 1.2, "#7a8a9a"))):
        spr, (fa, fb) = warehouse(213 + ord(name), a, b, col)
        save(spr, f"port/warehouse-{name}.png", footprint=[fa, fb])
    spr, (fa, fb) = customs(215)
    save(spr, "civic/customs.png", footprint=[fa, fb], group="civic", unique="district")
    # Industry.
    spr, (fa, fb) = sawtooth_factory(220)
    save(spr, "industry/brick-factory.png", footprint=[fa, fb])
    for kind, seed in (("plant", 221), ("cola", 222), ("chips", 223)):
        spr, (fa, fb) = plant(seed, kind)
        save(spr, f"industry/{kind}.png", footprint=[fa, fb])
    save(chimney(224), "industry/chimney.png")
    save_anim([chimney_smoke(224, f / 16) for f in range(16)], "industry/chimney-smoke.png", footprint=[0.3, 0.3])
    for k in range(4):
        save(truck(225, "#c8402a", k), f"industry/truck-red{turn(k)}.png")
        save(truck(226, "#3a5a9a", k), f"industry/truck-blue{turn(k)}.png")
    spr, (fa, fb) = workshop(227)
    save(spr, "industry/workshop.png", footprint=[fa, fb])
    save(water_tower(228), "industry/water-tower.png")
    save(cell_tower(229), "industry/cell-tower.png")
    save(dish_antenna(230), "industry/dish.png")
    save(barrels(231), "industry/barrels.png")
    spr, (fa, fb) = power_station(232)
    save(spr, "industry/power-station.png", footprint=[fa, fb])
    # Nuclear power plant.
    save(cooling_tower(240), "nuclear/cooling-tower.png", footprint=[2.3, 2.3])
    save_anim([tower_steam(240, f / 16) for f in range(16)], "nuclear/steam.png", footprint=[0.1, 0.1])
    spr, (fa, fb) = reactor(241)
    save(spr, "nuclear/reactor.png", footprint=[fa, fb])
    spr, (fa, fb) = turbine_hall(242)
    save(spr, "nuclear/turbine-hall.png", footprint=[fa, fb])
    save(atom_sign(243), "nuclear/sign.png")
    spr, (fa, fb) = rd_lab(244)
    save(spr, "nuclear/lab.png", footprint=[fa, fb])
    spr, (fa, fb) = building(245, "office", a=1.7, b=1.1, floors=4, wall="#c8c4bc", helipad=False, glass=GLASS_BLUE)
    save(spr, "nuclear/office.png", footprint=[fa, fb])
    save(guardhouse(246), "nuclear/guardhouse.png")
    save(check_canopy(247), "nuclear/checkpoint.png")
    save(pylon(248), "nuclear/pylon.png")
    spr, (fa, fb) = dry_casks(249)
    save(spr, "nuclear/casks.png", footprint=[fa, fb])
    spr, (fa, fb) = generator_house(252)
    save(spr, "nuclear/generators.png", footprint=[fa + 0.36, fb])
    spr, (fa, fb) = control_building(253)
    save(spr, "nuclear/control.png", footprint=[fa, fb])
    save(watchtower(254), "nuclear/watchtower.png")
    # Hospital.
    spr, (fa, fb) = hospital(250)
    save(spr, "civic/hospital.png", footprint=[fa, fb])
    save(ambulance(251), "civic/ambulance.png")
    save(ambulance(251, 1), "civic/ambulance-r1.png")
    # Plaza shops.
    for fn, name, seed in ((pizza_place, "pizza", 190), (bistro, "bistro", 191), (cake_shop, "cakes", 192),
                           (toy_shop, "toys", 193), (bakery, "bakery", 198)):
        spr, (fa, fb) = fn(seed)
        save(spr, f"buildings/{name}.png", footprint=[fa, fb])
    save_anim([kite(194, f / 8) for f in range(8)], "fun/kite-a.png", footprint=[0.1, 0.1])
    save_anim([kite(195, (f / 8 + 0.4) % 1, ("#e0a040", "#c8402a", "#e0a040", "#c8402a"), (-0.3, -0.6))
               for f in range(8)], "fun/kite-b.png", footprint=[0.1, 0.1])
    save_anim([air_dancer(196, f / 8) for f in range(8)], "fun/air-dancer.png", footprint=[0.2, 0.2])
    save_anim([air_dancer(197, (f / 8 + 0.5) % 1, "#3a8a4a", "#e8a0b8") for f in range(8)], "fun/air-dancer-b.png",
              footprint=[0.2, 0.2])
    # Cat's gas station and supermarket (the plaza district's 2×2 block).
    save(cats_sign(180), "cats/sign.png")
    spr, (fa, fb) = supermarket(181)
    save(spr, "cats/mart.png", footprint=[fa, fb])
    spr, (fa, fb) = gas_canopy(182)
    save(spr, "cats/canopy.png", footprint=[fa, fb])
    spr, (fa, fb) = building(183, "shop", a=1.2, b=0.9, floors=1, wall="#d8d0c0")
    save(spr, "cats/kiosk.png", footprint=[fa, fb])
    save(cart(184), "cats/cart.png")
    save(cart(184, 1), "cats/cart-r1.png")
    save(boxes(185), "cats/boxes.png")
    save(big_dumpster(186), "cats/dumpster.png")
    # Recreation: suburb BBQ areas and playgrounds, downtown squares.
    save(picnic_table(150), "rec/picnic-table.png")
    save(barbecue(151), "rec/barbecue.png")
    save(swing_set(152), "rec/swing-set.png")
    save(slide(153), "rec/slide.png")
    save(seesaw(154), "rec/seesaw.png")
    save_anim([fountain(155, k / 8) for k in range(8)], "rec/fountain.png", footprint=[0.92, 0.92])
    save(marram(131), "nature/dune/marram-b.png")
    save(creeper(132, "#c77aa0"), "nature/dune/morning-glory.png")
    save(creeper(133, "#d8c060", spread=0.14), "nature/dune/sea-daisy.png")
    spr, lamp = lighthouse(140)
    save(spr, "landmarks/lighthouse.png", footprint=[0.92, 0.92], lamp=[0, -lamp])
    for k in range(4):                                                 # bobbing on ripples
        save_anim([rowboat(109, "#3f6f73", k, f / 8) for f in range(8)], f"beach/rowboat{turn(k)}.png",
                  footprint=[0.84, 0.28] if k % 2 == 0 else [0.28, 0.84])
    save(beach_hut(110, "#3f6f73"), "beach/hut-teal.png")
    save(beach_hut(111, "#8a4a3e"), "beach/hut-red.png")
    save(pier(112, 1.0), "beach/pier.png")
    save(pier(112, 1.0, rot=1), "beach/pier-v.png")                  # along v
    save(barrel(113), "beach/barrel.png")
    save_anim([buoy(114, f / 8) for f in range(8)], "beach/buoy.png", footprint=[0.14, 0.14])
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
        ("office", dict(a=1.3, b=1.1, floors=7, wall="#8e8897", helipad=False)),
        ("office", dict(a=1.3, b=1.1, floors=9, wall="#7d8a96", helipad=False, glass=GLASS_BLUE)),
        ("office", dict(a=1.4, b=1.0, floors=5, wall="#8e8897", helipad=False, glass=GLASS_GREEN)),
        ("brick", dict(a=1.4, b=1.0, floors=5, wall="#8a5a44")),
        ("brick", dict(a=1.3, b=1.0, floors=3, wall="#5f4a52")),
        ("apartment", dict(a=1.4, b=1.0, floors=6, wall="#b8a88e")),
        ("apartment", dict(a=1.2, b=1.0, floors=3, wall="#8a6a78")),
        ("shop", dict(a=1.4, b=0.9, floors=3, wall="#9c8a6e")),
    ]
    for i, (kind, kw) in enumerate(bl):
        spr, (fa, fb) = building(300 + i, kind, **kw)
        save(spr, f"buildings/{kind}-{i + 1}.png", footprint=[fa, fb])
    spr, (fa, fb) = building(330, "apartment", a=1.4, b=1.0, floors=7, wall="#c9b89a", canopy=True, roof_sign="HOTEL")
    save(spr, "buildings/hotel.png", footprint=[fa, fb])
    spr, (fa, fb) = tv_station(340)
    save(spr, "landmarks/tv-station.png", footprint=[fa, fb], tip=[0, -spr.tip])
    save_anim([tv_lift(343, f, spr.depth) for f in range(LIFT_FRAMES)], "landmarks/tv-lift.png", footprint=[0.1, 0.1])
    save_anim([tv_ads(341, f, True) for f in range(AD_FRAMES)], "landmarks/tv-ads-side.png", footprint=[0.1, 0.1])
    save_anim([tv_ads(342, f, False) for f in range(AD_FRAMES)], "landmarks/tv-ads-front.png", footprint=[0.1, 0.1])
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
