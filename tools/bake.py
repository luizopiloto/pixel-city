"""Build the sprites used by js/city.js from the source images in assets/.

    python3 tools/bake.py

Writes assets/tiles/, assets/props/, assets/buildings/ and, per vehicle,
iso.png, iso@2x.png and the wheel overlays.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "assets"

# Crops are the connected components of each sheet (x, y, w, h).
TILES = {
    "road":         ("street-1.png", (230, 204, 128, 65)),   # straight along u, dashed, curbs both sides
    "crosswalk":    ("street-1.png", (227, 308, 128, 65)),   # straight along u with zebra
    "cross":        ("street-2.png", (39, 108, 129, 65)),    # 4-way
    "tee-nw-ne-sw": ("street-2.png", (222, 25, 128, 65)),    # T, curb on SE edge
    "tee-nw-se-sw": ("street-2.png", (221, 115, 129, 65)),   # T, curb on NE edge
    "corner-top":   ("street-2.png", (220, 203, 129, 65)),   # open SW + SE
    "corner-right": ("street-2.png", (38, 202, 129, 65)),    # open NW + SW
    "grass":        ("grass.png", (58, 256, 129, 65)),
    "pond":         ("grass.png", (219, 38, 129, 65)),       # round pond
    "pool":         ("grass.png", (58, 38, 129, 65)),        # square pond
    "canal":        ("grass.png", (53, 137, 129, 65)),       # water along u, banks NE + SW
    "paving":       ("floor-walls.png", (4, 275, 128, 65)),
}

PROPS = {
    "bench-ne":   ("props.png", (128, 100, 22, 21)),
    "bench-nw":   ("props.png", (112, 114, 22, 24)),
    "bin":        ("props.png", (164, 182, 9, 14)),
    "bin-gray":   ("props.png", (161, 224, 10, 16)),
    "planter-a":  ("props.png", (131, 257, 12, 11)),
    "planter-b":  ("props.png", (152, 269, 8, 12)),
    "dumpster":   ("props.png", (120, 172, 26, 28)),
}

LAMPS = {
    "red":   {"ba371a", "a2341c", "e85b3b"},
    "amber": {"9e581c", "894e1c", "d6833b"},
    "green": {"4b6822", "3d571a", "759744"},
}
LAMP_OFF = {"ba371a": "3b2a2a", "a2341c": "342526", "e85b3b": "4a3030",
            "9e581c": "3b3128", "894e1c": "342b24", "d6833b": "4a3a2c",
            "4b6822": "2c3527", "3d571a": "283023", "759744": "33402d"}

# Unplated variants of the corner block and the glass tower.
BUILDINGS = {
    "corner-bare": ("buildings-2.png", (21, 226, 128, 128)),
    "tower-bare":  ("buildings-2.png", (229, 251, 128, 120)),
}

VEHICLES = ["carDefault", "carSedan", "carYellow"]
CAR_BOX = (78, 54, 234, 172)      # common crop over all 12 frames
CAR_SCALE = 0.34
# iso@2x.png: the same cells at twice the resolution, for more detail.
HD = 2

# Hero Supra, from the renders supraWhite_0000-0011.png. Their camera is
# higher than the city's, so the four straight-road frames are rotated to
# match the roads. Then scaled, cropped and given binary alpha. Only
# iso@2x.png is baked; the 1x iso.png was made by hand the same way.
SUPRA_TURN = {1: 7.1, 7: 7.1, 5: -7.1, 11: -7.1}
SUPRA_SIZE = (137, 109)
SUPRA_BOX = (32, 28, 73, 41)      # x, y, w, h at 1x


def crop(sheet, box):
    x, y, w, h = box
    return Image.open(A / sheet).convert("RGBA").crop((x, y, x + w, y + h))


def hexof(px):
    return "%02x%02x%02x" % px[:3]


def signal_states(src):
    im = Image.open(A / src).convert("RGBA")
    for state in LAMPS:
        out = im.copy()
        px = out.load()
        for y in range(out.height):
            for x in range(out.width):
                p = px[x, y]
                h = hexof(p)
                if p[3] and h in LAMP_OFF and h not in LAMPS[state]:
                    c = LAMP_OFF[h]
                    px[x, y] = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)
        yield state, out


def car_atlas(kind, k=1):
    cw = round((CAR_BOX[2] - CAR_BOX[0]) * CAR_SCALE) * k
    ch = round((CAR_BOX[3] - CAR_BOX[1]) * CAR_SCALE) * k
    atlas = Image.new("RGBA", (cw * 12, ch))
    for f in range(12):
        src = Image.open(A / "vehicles" / kind / f"{kind}_{f:04d}.png").convert("RGBA")
        small = src.crop(CAR_BOX).convert("RGBa").resize((cw, ch), Image.LANCZOS).convert("RGBA")
        px = small.load()
        for y in range(ch):
            for x in range(cw):
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, 255 if a >= 120 else 0)
        atlas.paste(small, (f * cw, 0))
    return atlas, cw, ch


def supra_atlas(k):
    x, y, w, h = (v * k for v in SUPRA_BOX)
    atlas = Image.new("RGBA", (w * 12, h))
    for f in range(12):
        src = Image.open(A / "vehicles" / "supra" / f"supraWhite_{f:04d}.png").convert("RGBA")
        if f in SUPRA_TURN:
            src = src.rotate(SUPRA_TURN[f], resample=Image.BICUBIC,
                             center=(src.width / 2, src.height / 2))
        size = (SUPRA_SIZE[0] * k, SUPRA_SIZE[1] * k)
        small = src.convert("RGBa").resize(size, Image.BICUBIC).convert("RGBA")
        small = small.crop((x, y, x + w, y + h))
        small.putalpha(small.getchannel("A").point(lambda a: 255 if a >= 128 else 0))
        atlas.paste(small, (f * w, 0))
    return atlas


# Wheel animation: wheels.png / wheels@2x.png hold repainted wheel hubs, one
# row per rotation phase, in the same cells as the vehicle's atlas. Each hub
# gets WHEEL_SPOKES dark notches that turn in the car's direction of travel.
WHEEL_PHASES = 4
# A second set of rows adds motion blur over WHEEL_BLUR of a notch period.
WHEEL_BLUR = 0.5
WHEEL_SPOKES = {"carDefault": 3, "carSedan": 3, "carYellow": 3, "supra": 5}
# Hub radius as a fraction of the listed ellipse (the Supra lists the tire).
WHEEL_HUB = {"carDefault": 1.0, "carSedan": 1.0, "carYellow": 1.0, "supra": 0.75}
# Screen direction of travel per frame: +1 right (clockwise wheels), -1 left.
WHEEL_TURN = [0, 1, 1, 1, 1, 1, 0, -1, -1, -1, -1, -1]
DARK = 80                         # luma below this counts as tire

# The Supra's wheels, listed by hand since its outline merges with the tires:
# (cx, cy, rx, ry) per frame, in iso@2x.png px.
SUPRA_WHEELS = {
    1: [(28.7, 47.5, 5.4, 7.5), (75.0, 69.7, 5.8, 8.7)],
    2: [(24.4, 50.3, 8.7, 9.6), (98.2, 66.7, 8.3, 10.0)],
    3: [(32.8, 60.5, 9.6, 9.2), (114.5, 60.5, 10.4, 9.2)],
    4: [(50.7, 66.3, 9.2, 10.0), (122.3, 50.0, 8.3, 9.6)],
    5: [(72.0, 68.0, 5.5, 8.3), (116.0, 45.0, 5.4, 7.5)],
    7: [(73.9, 68.3, 5.4, 8.3), (27.8, 45.8, 5.4, 7.9)],
    8: [(23.8, 50.0, 7.9, 9.6), (96.7, 66.5, 8.3, 10.0)],
    9: [(30.2, 60.5, 10.4, 9.2), (112.3, 60.5, 10.0, 9.2)],
    10: [(49.2, 66.3, 9.2, 9.6), (120.8, 49.8, 8.8, 9.6)],
    11: [(71.8, 68.8, 5.4, 9.6), (115.7, 45.8, 5.0, 7.9)],
}


def luma(p):
    return (p[0] * 299 + p[1] * 587 + p[2] * 114) / 1000


def find_wheels(fr):
    """Wheel hubs of a traffic car frame, as (cx, cy, rx, ry) ellipses.

    Tires are dark blobs near the bottom of the car. The hub is the area a
    tire encloses; if there's none, a small hub is placed at the blob's center.
    """
    w, h = fr.size
    px = fr.load()
    top, bot = fr.getchannel("A").getbbox()[1::2]
    ring = {(x, y) for y in range(h) for x in range(w) if px[x, y][3] and luma(px[x, y]) < 150}
    wheels = []
    while ring:
        stack = [ring.pop()]
        blob = set()
        while stack:
            x, y = stack.pop()
            blob.add((x, y))
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in ring:
                    ring.remove(q)
                    stack.append(q)
        xs, ys = [p[0] for p in blob], [p[1] for p in blob]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if not (len(blob) >= 30 and bw >= 9 and bh >= 9 and 0.6 < bw / bh < 1.7
                and (y1 + 1 - top) / (bot - top) > 0.8):
            continue
        # Hub: pixels inside the tire that the outside can't reach.
        outside, stack = set(), [(x0 - 1, y0 - 1)]
        while stack:
            x, y = stack.pop()
            if (x, y) in outside or (x, y) in blob or not (x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1):
                continue
            outside.add((x, y))
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        hole = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
                if (x, y) not in blob and (x, y) not in outside]
        if len(hole) >= 4:
            hx, hy = [p[0] for p in hole], [p[1] for p in hole]
            wheels.append((y1, (sum(hx) / len(hx) + 0.5, sum(hy) / len(hy) + 0.5,
                               (max(hx) - min(hx) + 1) / 2, (max(hy) - min(hy) + 1) / 2)))
            continue
        for d in (3, 2, 1):
            core = [(x, y) for x, y in blob
                    if all((x + dx, y + dy) in blob for dx in (-d, 0, d) for dy in (-d, 0, d))]
            if core:
                break
        if core:
            cx = sum(p[0] for p in core) / len(core) + 0.5
            cy = sum(p[1] for p in core) / len(core) + 0.5
            wheels.append((y1, (cx, cy, 3.0, 3.0)))
    # Keep the lowest two; a license plate or grille can look like a wheel.
    return [wh for _, wh in sorted(wheels, reverse=True)[:2]]


def median_color(cols):
    cols = sorted(cols, key=luma)
    return cols[len(cols) // 2] if cols else None


def wheel_atlas(kind, atlas, cw, ch, wheels, k):
    """Overlay rows for `atlas` (cells cw x ch) at resolution k (1 or HD)."""
    import math
    out = Image.new("RGBA", (cw * 12, ch * WHEEL_PHASES * 2))
    spokes, hub = WHEEL_SPOKES[kind], WHEEL_HUB[kind]
    period = 2 * math.pi / spokes
    src = atlas.load()
    dst = out.load()
    for f in range(12):
        for cx, cy, rx, ry in wheels.get(f, []):
            cx, cy, rx, ry = (v * k / HD for v in (cx, cy, rx, ry))
            inner, ring = [], []
            span = 2 if hub >= 1 else 1       # where to sample the tire color
            for y in range(int(cy - ry * span), int(cy + ry * span) + 1):
                for x in range(int(cx - rx * span), int(cx + rx * span) + 1):
                    if not (0 <= x < cw and 0 <= y < ch):
                        continue
                    qx, qy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                    r = math.hypot(qx, qy)
                    p = src[f * cw + x, y]
                    if r < hub and p[3]:
                        inner.append((x, y, math.atan2(qy, qx)))
                    elif r < span and p[3] and luma(p) < DARK:
                        ring.append(p)
            if not inner:
                continue
            tire = median_color(ring) or (30, 30, 34, 255)
            light = median_color([src[f * cw + x, y] for x, y, _ in inner
                                  if luma(src[f * cw + x, y]) >= DARK])
            if light is None:             # plain black wheel: add a hubcap
                light = tuple(min(255, c + 60) for c in tire[:3]) + (255,)
            def notch(a, turn):
                return math.cos(spokes * (a - turn)) > 0.55
            n = 12                            # samples across the blur arc
            for ph in range(WHEEL_PHASES):
                turn = WHEEL_TURN[f] * period * ph / WHEEL_PHASES
                trail = -WHEEL_TURN[f] * period * WHEEL_BLUR
                for x, y, a in inner:
                    dst[f * cw + x, ph * ch + y] = tire if notch(a, turn) else light
                    t = sum(notch(a, turn + trail * i / (n - 1)) for i in range(n)) / n
                    dst[f * cw + x, (WHEEL_PHASES + ph) * ch + y] = tuple(
                        round(l + (d - l) * t) for l, d in zip(light[:3], tire[:3])) + (255,)
    return out


def save_wheels(kind, atlas, hd, cw, ch, wheels):
    d = A / "vehicles" / kind
    wheel_atlas(kind, atlas.convert("RGBA"), cw, ch, wheels, 1).save(d / "wheels.png")
    wheel_atlas(kind, hd.convert("RGBA"), cw * HD, ch * HD, wheels, HD).save(d / f"wheels@{HD}x.png")
    print(kind, "wheels", {f: len(w) for f, w in wheels.items() if w})


def main():
    (A / "tiles").mkdir(exist_ok=True)
    (A / "props").mkdir(exist_ok=True)
    (A / "buildings").mkdir(exist_ok=True)
    for name, (sheet, box) in BUILDINGS.items():
        crop(sheet, box).save(A / "buildings" / f"{name}.png")
    for name, (sheet, box) in TILES.items():
        crop(sheet, box).save(A / "tiles" / f"{name}.png")
    for name, (sheet, box) in PROPS.items():
        crop(sheet, box).save(A / "props" / f"{name}.png")
    for src, tag in (("traffic-light.png", "a"), ("traffic-light-2.png", "b")):
        for state, im in signal_states(src):
            im.save(A / "props" / f"signal-{tag}-{state}.png")
    for kind in VEHICLES:
        atlas, cw, ch = car_atlas(kind)
        atlas.save(A / "vehicles" / kind / "iso.png")
        hd = car_atlas(kind, HD)[0]
        hd.save(A / "vehicles" / kind / f"iso@{HD}x.png")
        wheels = {f: find_wheels(hd.crop((f * cw * HD, 0, (f + 1) * cw * HD, ch * HD)))
                  for f in range(12)}
        save_wheels(kind, atlas, hd, cw, ch, wheels)
    print("car cell", cw, ch)
    hd = supra_atlas(HD)
    hd.save(A / "vehicles" / "supra" / f"iso@{HD}x.png")
    atlas = Image.open(A / "vehicles" / "supra" / "iso.png").convert("RGBA")
    save_wheels("supra", atlas, hd, SUPRA_BOX[2], SUPRA_BOX[3], SUPRA_WHEELS)


if __name__ == "__main__":
    main()
