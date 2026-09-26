/*
 * Pixel City: isometric pixel-art city with traffic and a GPS-guided hero car.
 *
 * World space is a (u, v) tile grid; one tile is a 128×64 diamond.
 *   +u → screen down-right, +v → screen down-left.
 * The city is 8×8 blocks of 3×3 tiles on a road grid, generated from a seed.
 *
 * Mount on any element with [data-pixel-city]:
 *   data-assets     asset path (default "assets/")
 *   data-seed       layout seed (default 7)
 *   data-zoom       CSS px per art px (default 2)
 *   data-minimap    id of an element to hold the GPS phone (optional)
 *   data-tiltshift  "off" to disable the tilt-shift blur
 */
(() => {
  const TW = 128, TH = 64, HW = TW / 2, HH = TH / 2;
  const BLOCKS = 8, BLOCK = 3, PITCH = BLOCK + 1;
  const ROAD0 = 1;                          // first road line (after the verge)
  const ROADN = ROAD0 + BLOCKS * PITCH;     // last road line
  const N = ROADN + 2;                      // grid is N × N tiles
  const TOP = 8;                            // headroom above the top tile
  const SLAB = 14;                          // soil edge under the island
  const W = N * TW + 2;
  const H = TOP + N * TH + SLAB + 2;
  const OX = N * HW + 1;

  const iso = (u, v) => [OX + (u - v) * HW, TOP + (u + v) * HH];
  const roadAt = k => ROAD0 + k * PITCH;    // road index → tile

  // Road auto-tiling: authored tiles plus mirrored (u↔v) and 180° rotated
  // variants. Key = open edges: n = -u, e = -v, s = +u, w = +v.
  const ROAD_TILES = {
    ns:   ['road', 0],          nsx: ['crosswalk', 0],
    ew:   ['road', 'm'],        ewx: ['crosswalk', 'm'],
    nesw: ['cross', 0],
    new:  ['tee-nw-ne-sw', 0],  nes: ['tee-nw-ne-sw', 'm'],
    nsw:  ['tee-nw-se-sw', 0],  esw: ['tee-nw-se-sw', 'm'],
    sw:   ['corner-top', 0],    ne:  ['corner-top', 'r'],
    nw:   ['corner-right', 0],  es:  ['corner-right', 'm'],
  };

  /* ---------- sprites ---------- */

  // `base`: bottom corner of the footprint in sprite px. `a`/`b`: footprint
  // in tiles along u / v. Plated sprites include their own pavement.
  const BUILDINGS = {
    tower:   { src: 'building-tower.png',        base: [126, 153],   a: 1.906, b: 1.156 },
    corner:  { src: 'building-corner.png',       base: [110.5, 147], a: 1.664, b: 1.039 },
    house:   { src: 'building-house.png',        base: [118, 154],   a: 1.781, b: 1.062 },
    cafe:    { src: 'building-cafe.png',         base: [118, 134],   a: 1.781, b: 1.062 },
    kiosk:   { src: 'building-modern.png',       base: [90, 114],    a: 1.344, b: 0.656 },
    cottage: { src: 'building-small.png',        base: [90, 135],    a: 1.344, b: 0.656 },
    flats:   { src: 'buildings/corner-bare.png', base: [86, 128],    a: 1.344, b: 0.656 },
    office:  { src: 'buildings/tower-bare.png',  base: [86, 128],    a: 1.344, b: 0.656 },
  };
  const PLATED = ['tower', 'corner', 'house', 'cafe'];
  const BARE = ['kiosk', 'cottage', 'flats', 'office'];

  // Ground contact point of each prop, in sprite pixels.
  const PROP_ANCHORS = {
    'lamp.png': [7, 64], 'lamp-white.png': [20.5, 38],
    'props/bench-ne.png': [12, 21], 'props/bench-nw.png': [18, 24],
    'props/bin.png': [4.5, 14], 'props/bin-gray.png': [5, 16],
    'props/planter-a.png': [8, 11], 'props/planter-b.png': [4, 12],
    'props/dumpster.png': [18, 28],
  };
  const PLANTERS = ['props/planter-a.png', 'props/planter-b.png'];

  /* ---------- layout tuning ---------- */

  // Regular 3×3 blocks, by template.
  const BLOCK_MIX = { twin: 12, row: 8, mixed: 8, plaza: 3, park: 7, canal: 2 };
  // Superblocks, in blocks along u × v.
  const SUPERBLOCKS = [[3, 2], [2, 3], [3, 2], [2, 3]];

  // Old fixed hero route (road-index coords). No longer driven, but
  // superblock placement still avoids it; removing it would change the city.
  const HERO_ROUTE = [[0, 5], [2, 5], [2, 3], [5, 3], [5, 6], [7, 6]];
  // Hero routes: random walks that never turn back or revisit a crossing,
  // ROUTE_EDGES blocks long. At the end the hero parks for PARK_S seconds.
  const ROUTE_EDGES = [16, 24];
  const PARK_S = 5;
  const CURB = 0.48;         // parked hero's offset from the road center
  // The hero is a Supra (not in TYPES). No contact shadow: on this low, long
  // car it looked like a dark block beside it.
  const HERO_TYPE = 'supra';
  const HERO_CELL = [73, 41];
  // One pivot per frame (silhouette center, 5 px down): the car sits at a
  // different height in each render frame.
  const HERO_PIVOT = [
    [36, 26], [36, 26], [36, 26], [36, 27], [36, 28], [36, 28],
    [36, 29], [36, 28], [36, 28], [36, 27], [36, 26], [37, 26],
  ];
  const HERO_GEM_Y = -36; // marker height above the car's ground point

  /* ---------- traffic tuning ---------- */

  const SIGNAL_COUNT = 8;
  const SIGNAL_CYCLE = [                   // seconds per phase
    { u: 'green', v: 'red', t: 6 }, { u: 'amber', v: 'red', t: 1.4 },
    { u: 'red', v: 'red', t: 0.8 }, { u: 'red', v: 'green', t: 6 },
    { u: 'red', v: 'amber', t: 1.4 }, { u: 'red', v: 'red', t: 0.8 },
  ];
  const CYCLE_T = SIGNAL_CYCLE.reduce((s, p) => s + p.t, 0);

  const ROUTE_COUNT = 14;
  const TILES_PER_CAR = 24;  // traffic density along each loop
  const LANE = 0.23;         // lane offset from the road center line
  const TURN = 0.36;         // fillet radius at corners
  const CRUISE = 1.3;        // tiles / s
  const ACCEL = 1.6, DECEL = 3.2;
  const GAP = 0.62;          // following distance
  const TYPES = ['carDefault', 'carSedan', 'carYellow'];

  // Sprite 0000 faces the camera; frames step 30° counter-clockwise.
  // The four iso road directions land on frames 1, 11, 7 and 5.
  const CAR_CELL = [53, 40];
  // Half a car length in tiles: how far the stop line is from the car's center.
  const CAR_HALF = 0.24, HERO_HALF = 0.38;
  const CAR_PIVOT = [26, 32];
  // HD atlases (iso@2x.png): same size on canvas, more detail. Used when the
  // view scale is a multiple of HD so pixels stay sharp.
  const HD = 2;
  // Spinning wheels: wheels.png holds WHEEL_PHASES rows of hub overlays, then
  // the same rows motion-blurred (used above WHEEL_BLUR_SPEED). A car steps
  // one row every 1 / WHEEL_STEPS tiles.
  const WHEEL_PHASES = 4, WHEEL_STEPS = 24, WHEEL_BLUR_SPEED = 0.5;
  // Road bumps: every BUMP_EVERY tiles a moving car hits 1 to BUMP_RUN bumps,
  // BUMP_GAP seconds apart. Each is a small damped bounce, scaled by speed.
  const BUMP_AMP = 2.2, BUMP_EVERY = [1, 3], BUMP_T = 0.6;
  const BUMP_RUN = 3, BUMP_GAP = [0.18, 0.3];
  const bumpLift = car => car.bumps.reduce((sum, b) => b.t < 0 ? sum
    : sum + b.amp * Math.exp(-6 * b.t) * Math.sin(14 * b.t), 0);
  const DIR_ANCHORS = [[0, 1], [90, -1], [180, -5], [270, -7], [360, -11]];

  function frameFor(du, dv) {
    const deg = (Math.atan2(dv, du) * 180 / Math.PI + 360) % 360;
    for (let i = 0; i < DIR_ANCHORS.length - 1; i++) {
      const [a0, f0] = DIR_ANCHORS[i], [a1, f1] = DIR_ANCHORS[i + 1];
      if (deg <= a1) {
        const f = Math.round(f0 + (f1 - f0) * (deg - a0) / (a1 - a0));
        return ((f % 12) + 12) % 12;
      }
    }
    return 1;
  }

  function mulberry32(a) {
    return () => {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // Every tile along a polyline of road-index corners.
  function tilesAlong(corners) {
    const out = [];
    for (let k = 0; k < corners.length - 1; k++) {
      const [a, b] = [corners[k].map(roadAt), corners[k + 1].map(roadAt)];
      const du = Math.sign(b[0] - a[0]), dv = Math.sign(b[1] - a[1]);
      for (let u = a[0], v = a[1]; ; u += du, v += dv) {
        out.push([u, v]);
        if (u === b[0] && v === b[1]) break;
      }
    }
    return out;
  }

  /* ---------- city generation ---------- */

  function generate(rng) {
    const pick = list => list[Math.floor(rng() * list.length)];
    const shuffle = list => {
      for (let i = list.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1));
        [list[i], list[j]] = [list[j], list[i]];
      }
      return list;
    };

    const heroTiles = tilesAlong(HERO_ROUTE);

    // Superblocks: merged block groups that don't touch each other or the
    // old route.
    const supers = [];
    for (const [bw, bh] of SUPERBLOCKS) {
      for (let tries = 0; tries < 200; tries++) {
        const bi = Math.floor(rng() * (BLOCKS - bw + 1));
        const bj = Math.floor(rng() * (BLOCKS - bh + 1));
        const s = { bi, bj, bw, bh,
          u0: roadAt(bi) + 1, u1: roadAt(bi + bw), v0: roadAt(bj) + 1, v1: roadAt(bj + bh) };
        const clash = supers.some(o =>
          bi <= o.bi + o.bw && o.bi <= bi + bw && bj <= o.bj + o.bh && o.bj <= bj + bh);
        const onRoute = heroTiles.some(([u, v]) => u >= s.u0 && u < s.u1 && v >= s.v0 && v < s.v1);
        if (!clash && !onRoute) { supers.push(s); break; }
      }
    }
    const inSuper = (u, v) => supers.some(s => u >= s.u0 && u < s.u1 && v >= s.v0 && v < s.v1);
    const superOfBlock = (bi, bj) =>
      supers.some(s => bi >= s.bi && bi < s.bi + s.bw && bj >= s.bj && bj < s.bj + s.bh);

    const isLine = t => t >= ROAD0 && t <= ROADN && (t - ROAD0) % PITCH === 0;
    const isRoad = (u, v) =>
      u >= ROAD0 && v >= ROAD0 && u <= ROADN && v <= ROADN &&
      (isLine(u) || isLine(v)) && !inSuper(u, v);

    const groundMap = new Map();
    const lots = [], props = [];
    const setGround = (u, v, name, mode = 0) => groundMap.set(u + ',' + v, [name, mode]);
    const pave = (u, v, lu = BLOCK, lv = BLOCK) => {
      for (let du = 0; du < lu; du++) for (let dv = 0; dv < lv; dv++) setGround(u + du, v + dv, 'paving');
    };
    const prop = (src, u, v) => props.push([src, u, v]);
    const nook = (u, v) => {                 // benches in an empty 1.5 × 1.5 cell
      prop('props/bench-ne.png', u + 0.8, v + 0.9);
      prop(pick(PLANTERS), u + 0.35, v + 0.4);
      prop('props/bin-gray.png', u + 1.2, v + 1.25);
    };

    // Intersections with traffic lights: full crossings, spread apart.
    const signals = [];
    const candidates = [];
    for (let i = 1; i < BLOCKS; i++) for (let j = 1; j < BLOCKS; j++) {
      const u = roadAt(i), v = roadAt(j);
      if ([[1, 0], [-1, 0], [0, 1], [0, -1]].every(([du, dv]) => isRoad(u + du, v + dv))) candidates.push([i, j]);
    }
    shuffle(candidates);
    for (const [i, j] of candidates) {
      if (signals.length === SIGNAL_COUNT) break;
      if (signals.some(s => Math.abs(s.i - i) + Math.abs(s.j - j) < 3)) continue;
      signals.push({ i, j, u: roadAt(i), v: roadAt(j), offset: rng() * CYCLE_T });
    }
    const signalAt = new Map(signals.map((s, k) => [s.u + ',' + s.v, k]));

    // Block templates. (u, v) is the block's top tile; offsets are in [0, 3).
    const T = {
      twin(u, v) {
        const p = shuffle([...PLATED]);
        lots.push([p[0], u, u + 3, v, v + 1.5], [p[1], u, u + 3, v + 1.5, v + 3]);
        prop(pick(PLANTERS), u + 0.22, v + 0.4 + rng() * 2.2);
        if (rng() < 0.6) prop('lamp.png', u + 2.8, v + 0.18);
      },
      row(u, v) {
        pave(u, v);
        const empty = rng() < 0.25 ? Math.floor(rng() * 4) : -1;
        [[0, 0], [1.5, 0], [0, 1.5], [1.5, 1.5]].forEach(([qu, qv], k) => {
          if (k === empty) nook(u + qu, v + qv);
          else lots.push([pick(BARE), u + qu, u + qu + 1.5, v + qv, v + qv + 1.5]);
        });
      },
      mixed(u, v) {
        pave(u, v);
        lots.push([pick(PLATED), u, u + 3, v, v + 1.5]);
        lots.push([pick(BARE), u, u + 1.5, v + 1.5, v + 3], [pick(BARE), u + 1.5, u + 3, v + 1.5, v + 3]);
      },
      park(u, v) {
        setGround(u + 1, v + 1, rng() < 0.5 ? 'pond' : 'pool');
        prop('props/bench-nw.png', u + 0.5, v + 1.5);
        prop('props/bench-ne.png', u + 1.5, v + 0.5);
        prop('props/bench-nw.png', u + 2.5, v + 1.5);
        prop('props/bench-ne.png', u + 1.5, v + 2.5);
        for (const [cu, cv] of [[0.3, 0.3], [2.7, 0.3], [0.3, 2.7], [2.7, 2.7]]) prop(pick(PLANTERS), u + cu, v + cv);
        prop('lamp-white.png', u + 2.45, v + 2.2);
        prop('props/bin.png', u + 0.62, v + 2.2);
      },
      canal(u, v) {
        for (let du = 0; du < BLOCK; du++) setGround(u + du, v + 1, 'canal');
        prop('props/bench-ne.png', u + 0.8, v + 0.55);
        prop('props/bench-ne.png', u + 2.1, v + 0.55);
        prop('props/bench-ne.png', u + 1.4, v + 2.5);
        prop(pick(PLANTERS), u + 0.3, v + 2.7);
        prop(pick(PLANTERS), u + 2.7, v + 2.7);
        prop('lamp.png', u + 2.8, v + 0.2);
      },
      plaza(u, v) {
        pave(u, v);
        lots.push([pick(['cafe', 'tower']), u, u + 3, v + 0.25, v + 1.75]);
        prop('props/bench-ne.png', u + 0.7, v + 2.5);
        prop('props/bench-ne.png', u + 2.1, v + 2.5);
        prop('props/bin-gray.png', u + 1.45, v + 2.75);
        prop(pick(PLANTERS), u + 0.3, v + 2.1);
        prop(pick(PLANTERS), u + 2.75, v + 2.1);
        prop('props/dumpster.png', u + 2.75, v + 0.15);
      },
    };

    // Superblock: dense paved downtown in columns and rows of buildings.
    const ROW = 1.25;
    function downtown(s) {
      const lu = s.u1 - s.u0, lv = s.v1 - s.v0;
      pave(s.u0, s.v0, lu, lv);
      const cols = [];
      let rest = lu;
      while (rest >= 1.5) {
        const w = rest >= 2.1 && rng() < 0.55 ? 2.1 : 1.5;
        cols.push(w);
        rest -= w;
      }
      const rows = Math.floor(lv / ROW);
      const v0 = s.v0 + (lv - rows * ROW) / 2;
      for (let r = 0; r < rows; r++) {
        let u = s.u0 + rest / 2;
        const v = v0 + r * ROW;
        for (const w of cols) {
          if (rng() < 0.3) {
            prop(pick(PLANTERS), u + w / 2 - 0.3, v + 0.4);
            prop('props/bench-ne.png', u + w / 2 + 0.2, v + 0.75);
          } else {
            lots.push([w > 2 ? pick(PLATED) : pick(BARE), u, u + w, v, v + ROW]);
          }
          u += w;
        }
      }
    }

    supers.forEach(downtown);
    const free = [];
    for (let bi = 0; bi < BLOCKS; bi++) {
      for (let bj = 0; bj < BLOCKS; bj++) if (!superOfBlock(bi, bj)) free.push([bi, bj]);
    }
    const plan = Object.entries(BLOCK_MIX).flatMap(([k, n]) => Array(n).fill(k));
    while (plan.length < free.length) plan.push('row');
    shuffle(plan);
    free.forEach(([bi, bj], k) => T[plan[k]](roadAt(bi) + 1, roadAt(bj) + 1));

    // Verge along the two camera-facing edges.
    for (let k = 2; k < N - 2; k += 3) {
      prop(pick(PLANTERS), N - 0.5, k + rng());
      prop(pick(PLANTERS), k + rng(), N - 0.5);
    }

    const nearSignal = (u, v) =>
      [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([du, dv]) => signalAt.has((u + du) + ',' + (v + dv)));

    function ground(u, v) {
      if (isRoad(u, v)) {
        let key = '';
        if (isRoad(u - 1, v)) key += 'n';
        if (isRoad(u, v - 1)) key += 'e';
        if (isRoad(u + 1, v)) key += 's';
        if (isRoad(u, v + 1)) key += 'w';
        if ((key === 'ns' || key === 'ew') && nearSignal(u, v)) key += 'x';
        return ROAD_TILES[key];
      }
      return groundMap.get(u + ',' + v) || ['grass', 0];
    }

    // Traffic loops: rectangles on the remaining road grid, either direction.
    const loopOk = loop => tilesAlong([...loop, loop[0]]).every(([u, v]) => isRoad(u, v));
    const routes = [
      [[0, 0], [BLOCKS, 0], [BLOCKS, BLOCKS], [0, BLOCKS]],
      [[0, 0], [0, BLOCKS], [BLOCKS, BLOCKS], [BLOCKS, 0]],
    ];
    for (let tries = 0; routes.length < ROUTE_COUNT && tries < 500; tries++) {
      const i0 = Math.floor(rng() * BLOCKS), j0 = Math.floor(rng() * BLOCKS);
      const i1 = Math.min(BLOCKS, i0 + 1 + Math.floor(rng() * 4));
      const j1 = Math.min(BLOCKS, j0 + 1 + Math.floor(rng() * 4));
      const loop = [[i0, j0], [i1, j0], [i1, j1], [i0, j1]];
      if (loopOk(loop)) routes.push(rng() < 0.5 ? loop : loop.reverse());
    }

    const toTiles = r => r.map(([i, j]) => [roadAt(i), roadAt(j)]);
    return {
      ground, isRoad, lots, props, signals, signalAt, rng, pick,
      routes: routes.map(toTiles),
    };
  }

  /* ---------- lanes ---------- */

  const right = ([du, dv]) => [-dv, du];
  const unit = (p, q) => {
    const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
    return [(q[0] - p[0]) / len, (q[1] - p[1]) / len];
  };

  // Rounded lane corner at p, turning from dIn to dOut (right-hand lane).
  function fillet(out, p, dIn, dOut) {
    const rIn = right(dIn), rOut = right(dOut);
    const c = [p[0] + (rIn[0] + rOut[0]) * LANE, p[1] + (rIn[1] + rOut[1]) * LANE];
    const a = [c[0] - dIn[0] * TURN, c[1] - dIn[1] * TURN];
    const b = [c[0] + dOut[0] * TURN, c[1] + dOut[1] * TURN];
    for (let k = 0; k <= 8; k++) {
      const t = k / 8, m = 1 - t;
      out.push([
        m * m * a[0] + 2 * m * t * c[0] + t * t * b[0],
        m * m * a[1] + 2 * m * t * c[1] + t * t * b[1],
      ]);
    }
  }

  const centers = corners => corners.map(([u, v]) => [u + 0.5, v + 0.5]);

  // Closed rectangle loop.
  function loopLane(corners) {
    const pts = centers(corners), n = pts.length, out = [];
    const dirs = pts.map((p, i) => unit(p, pts[(i + 1) % n]));
    for (let i = 0; i < n; i++) fillet(out, pts[i], dirs[(i - 1 + n) % n], dirs[i]);
    return out;
  }

  // Hero route: pulls out from the curb at `start`, follows the right-hand
  // lane through `corners`, and pulls in to the curb at `end`.
  function routeLane(start, corners, end) {
    const pts = centers([start, ...corners, end]), n = pts.length, out = [];
    const dirs = pts.slice(0, -1).map((p, i) => unit(p, pts[i + 1]));
    const at = (p, d, side, along) => {
      const r = right(d);
      return [p[0] + d[0] * along + r[0] * side, p[1] + d[1] * along + r[1] * side];
    };
    const ease = t => t * t * (3 - 2 * t);
    const PULL = 0.8, K = 8;
    for (let k = 0; k <= K; k++) out.push(at(pts[0], dirs[0], CURB + (LANE - CURB) * ease(k / K), PULL * k / K));
    for (let i = 1; i < n - 1; i++) fillet(out, pts[i], dirs[i - 1], dirs[i]);
    const dl = dirs[n - 2];
    for (let k = 0; k <= K; k++) out.push(at(pts[n - 1], dl, LANE + (CURB - LANE) * ease(k / K), -PULL * (1 - k / K)));
    return out;
  }

  function buildPath(raw, signalAt, ground, half = CAR_HALF, closed = true) {
    // Resample to even spacing so speed is constant along curves.
    const seg = [];
    let total = 0;
    for (let i = 0; i < (closed ? raw.length : raw.length - 1); i++) {
      const p = raw[i], q = raw[(i + 1) % raw.length];
      const len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      seg.push({ p, q, s: total, len });
      total += len;
    }
    const STEP = 0.02, samples = [];
    let j = 0;
    for (let s = 0; s < total; s += STEP) {
      while (seg[j].s + seg[j].len < s) j++;
      const g = seg[j], t = g.len ? (s - g.s) / g.len : 0;
      samples.push([g.p[0] + (g.q[0] - g.p[0]) * t, g.p[1] + (g.q[1] - g.p[1]) * t]);
    }
    const heads = samples.map((p, i) => {
      let a = p, q = samples[(i + 3) % samples.length];
      if (!closed && i + 3 >= samples.length) [a, q] = [samples[samples.length - 4], samples[samples.length - 1]];
      const len = Math.hypot(q[0] - a[0], q[1] - a[1]) || 1;
      return [(q[0] - a[0]) / len, (q[1] - a[1]) / len];
    });
    // Stop lines where the lane enters a crossing with lights; before a
    // crosswalk, the front bumper stops short of the stripes.
    const stops = [];
    const n = samples.length, pathLen = n * STEP;
    const tileOf = p => Math.floor(p[0]) + ',' + Math.floor(p[1]);
    const sigOf = p => signalAt.get(tileOf(p));
    samples.forEach((p, i) => {
      if (!closed && i === 0) return;
      const prev = samples[(i - 1 + n) % n];
      const k = sigOf(p);
      if (k !== undefined && sigOf(prev) !== k) {
        const h = heads[i];
        let s = i * STEP - 0.06;
        const [pu, pv] = [Math.floor(prev[0]), Math.floor(prev[1])];
        if (ground(pu, pv)[0] === 'crosswalk') {
          let e = i - 1;
          for (let m = 0; m < 1.5 / STEP && tileOf(samples[(e - 1 + n) % n]) === pu + ',' + pv; m++) e--;
          s = e * STEP - half - 0.03;
        }
        stops.push({ s: ((s % pathLen) + pathLen) % pathLen, sig: k, axis: Math.abs(h[0]) > Math.abs(h[1]) ? 'u' : 'v' });
      }
    });
    return { samples, heads, stops, total: pathLen, step: STEP, closed };
  }

  /* ---------- rendering helpers ---------- */

  function load(base, src) {
    return new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = () => rej(new Error(`Pixel City: failed to load ${base}${src}`));
      img.src = base + src;
    });
  }

  function drawTile(ctx, img, u, v, mode) {
    const [x, y] = iso(u, v);
    if (!mode) return ctx.drawImage(img, x - HW, y);
    ctx.save();
    if (mode === 'm') {
      ctx.translate(x + HW, y);
      ctx.scale(-1, 1);
    } else {
      ctx.translate(x + HW, y + img.height);
      ctx.rotate(Math.PI);
    }
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  // Soil edge under the two camera-facing sides of the island.
  function drawSlab(ctx) {
    const [lx, ly] = iso(0, N), [bx, by] = iso(N, N), [rx] = iso(N, 0);
    const side = (x0, x1, y0, slope, fill, lip) => {
      for (let x = x0; x < x1; x++) {
        const y = Math.round(y0 + (x - x0) * slope);
        ctx.fillStyle = lip;
        ctx.fillRect(x, y, 1, 2);
        ctx.fillStyle = fill;
        ctx.fillRect(x, y + 2, 1, SLAB - 2);
      }
    };
    side(lx, bx, ly, 0.5, '#5b4a31', '#4d5a1f');
    side(bx, rx, by, -0.5, '#46382a', '#3f4a1a');
  }

  // Floating diamond marker. `spin` in [0, 1) turns it about its vertical axis.
  const GEM_HALF = [0, 1, 2, 3, 4, 5, 6, 6, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1, 0];
  const GEM = {
    lightTop: '#c6f7a0', darkTop: '#6fcf45', lightBot: '#8fe35f', darkBot: '#3f9a2c',
    edge: '#24591b',
  };
  function drawGem(c, cx, bottom, spin) {
    const cos = Math.cos(spin * Math.PI * 2);
    const k = 0.45 + 0.55 * Math.abs(cos);
    const flip = cos < 0;
    const top = bottom - GEM_HALF.length;
    GEM_HALF.forEach((h, row) => {
      const hw = Math.max(0, Math.round(h * k));
      const y = top + row;
      const upper = row < 7;
      const lit = upper ? GEM.lightTop : GEM.lightBot;
      const dark = upper ? GEM.darkTop : GEM.darkBot;
      c.fillStyle = GEM.edge;
      c.fillRect(cx - hw - 1, y, hw * 2 + 3, 1);
      c.fillStyle = flip ? dark : lit;
      c.fillRect(cx - hw, y, hw + 1, 1);
      c.fillStyle = flip ? lit : dark;
      c.fillRect(cx + 1, y, hw, 1);
    });
    c.fillStyle = GEM.edge;
    c.fillRect(cx - 1, top - 1, 3, 1);
    c.fillRect(cx - 1, bottom, 3, 1);
  }

  const overlap = (a, b) =>
    a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];

  // Buckets screen rectangles so overlap queries stay cheap.
  class ScreenHash {
    constructor(cell) { this.cell = cell; this.map = new Map(); }
    keys([x, y, w, h]) {
      const c = this.cell, out = [];
      for (let i = Math.floor(x / c); i <= Math.floor((x + w) / c); i++)
        for (let j = Math.floor(y / c); j <= Math.floor((y + h) / c); j++) out.push(i + ',' + j);
      return out;
    }
    add(item) {
      for (const k of this.keys(item.rect)) {
        if (!this.map.has(k)) this.map.set(k, []);
        this.map.get(k).push(item);
      }
    }
    query(rect) {
      const found = new Set();
      for (const k of this.keys(rect)) {
        for (const it of this.map.get(k) || []) if (overlap(it.rect, rect)) found.add(it);
      }
      return found;
    }
  }

  // Painter's order for footprints that don't intersect.
  const behind = (a, b) => a.box[1] <= b.box[0] || a.box[3] <= b.box[2];
  const depth = o => o.box[0] + o.box[1] + o.box[2] + o.box[3];
  const drawsBefore = (a, b) => behind(a, b) || (!behind(b, a) && depth(a) <= depth(b));
  const byOrder = (a, b) => a.order - b.order;

  // Topological sort over screen-overlapping pairs only.
  function sortStatics(items, hash) {
    const after = items.map(() => []), deg = new Array(items.length).fill(0);
    items.forEach((a, i) => { a.index = i; });
    for (const a of items) {
      for (const b of hash.query(a.rect)) {
        if (b.index <= a.index) continue;
        const [f, s] = drawsBefore(a, b) ? [a, b] : [b, a];
        after[f.index].push(s.index);
        deg[s.index]++;
      }
    }
    const order = [];
    let ready = items.filter((_, i) => !deg[i]);
    while (ready.length) {
      ready.sort((a, b) => depth(a) - depth(b));
      const next = [];
      for (const it of ready) {
        order.push(it);
        for (const k of after[it.index]) if (--deg[k] === 0) next.push(items[k]);
      }
      ready = next;
    }
    if (order.length < items.length) {       // cycle: append the rest by depth
      const seen = new Set(order);
      order.push(...items.filter(it => !seen.has(it)).sort((a, b) => depth(a) - depth(b)));
    }
    order.forEach((it, i) => { it.order = i; });
  }

  /* ---------- mount ---------- */

  /* ---------- hero routes ---------- */

  // Hero routes over the road grid. `planRoute(spot)` returns { path, end }
  // from a parking spot to a new random one.
  function heroPlanner(city) {
  const nodeTile = ([i, j]) => [roadAt(i), roadAt(j)];
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const edgeOk = (a, b) => {
    if (b[0] < 0 || b[1] < 0 || b[0] > BLOCKS || b[1] > BLOCKS) return false;
    const [u0, v0] = nodeTile(a), [u1, v1] = nodeTile(b);
    const du = Math.sign(u1 - u0), dv = Math.sign(v1 - v0);
    for (let u = u0, v = v0; ; u += du, v += dv) {
      if (!city.isRoad(u, v)) return false;
      if (u === u1 && v === v1) return true;
    }
  };
  // A parking spot: mid-block on the edge behind → ahead, facing ahead.
  const spotOn = (behind, ahead) => {
    const d = [Math.sign(ahead[0] - behind[0]), Math.sign(ahead[1] - behind[1])];
    const t = nodeTile(ahead);
    return { behind, ahead, d, tile: [t[0] - d[0] * 2, t[1] - d[1] * 2] };
  };
  function planRoute(from) {
    let best = null;
    for (let attempt = 0; attempt < 300; attempt++) {
      const want = ROUTE_EDGES[0] + Math.floor(city.rng() * (ROUTE_EDGES[1] - ROUTE_EDGES[0] + 1));
      const nodes = [from.ahead], seen = new Set([from.behind.join(','), from.ahead.join(',')]);
      let d = from.d;
      while (nodes.length - 1 < want) {
        const at = nodes[nodes.length - 1];
        const opts = DIRS.filter(o => !(o[0] === -d[0] && o[1] === -d[1]))
          .map(o => [o, [at[0] + o[0], at[1] + o[1]]])
          .filter(([, nx]) => !seen.has(nx.join(',')) && edgeOk(at, nx));
        if (!opts.length) break;
        const straight = opts.find(([o]) => o[0] === d[0] && o[1] === d[1]);
        const [o, nx] = straight && city.rng() < 0.55 ? straight : city.pick(opts);
        nodes.push(nx); seen.add(nx.join(',')); d = o;
      }
      if (!best || nodes.length > best.length) best = nodes;
      if (nodes.length - 1 >= ROUTE_EDGES[0]) break;
    }
    const nodes = best.length > 1 ? best : [from.ahead, ...DIRS.map(o => [from.ahead[0] + o[0], from.ahead[1] + o[1]])
      .filter(nx => edgeOk(from.ahead, nx)).slice(0, 1)];
    const end = spotOn(nodes[nodes.length - 2], nodes[nodes.length - 1]);
    // Lane corners: only the nodes where the route turns.
    const pts = [from.tile, ...nodes.slice(0, -1).map(nodeTile), end.tile];
    const corners = pts.slice(1, -1).filter((p, k) => {
      const a = pts[k], b = pts[k + 2];
      return !((a[0] === p[0] && p[0] === b[0]) || (a[1] === p[1] && p[1] === b[1]));
    });
    return { path: buildPath(routeLane(from.tile, corners, end.tile), city.signalAt, city.ground, HERO_HALF, false), end };
  }
  const firstSpot = (() => {
    for (let tries = 0; tries < 500; tries++) {
      const a = [Math.floor(city.rng() * (BLOCKS + 1)), Math.floor(city.rng() * (BLOCKS + 1))];
      const o = city.pick(DIRS), b = [a[0] + o[0], a[1] + o[1]];
      if (edgeOk(a, b)) return spotOn(a, b);
    }
  })();
    return { planRoute, firstSpot };
  }

  async function mount(root) {
    const base = root.dataset.assets || 'assets/';
    const zoom = Math.max(1, Number(root.dataset.zoom || 2));
    const city = generate(mulberry32(Number(root.dataset.seed || 7)));

    const srcs = new Set([
      ...Object.values(ROAD_TILES).map(([n]) => `tiles/${n}.png`),
      ...['grass', 'paving', 'pond', 'pool', 'canal'].map(n => `tiles/${n}.png`),
      ...Object.values(BUILDINGS).map(b => b.src),
      ...Object.keys(PROP_ANCHORS),
      ...['a', 'b'].flatMap(s => ['red', 'amber', 'green'].map(c => `props/signal-${s}-${c}.png`)),
      ...[...TYPES, HERO_TYPE].flatMap(t => ['iso', 'wheels'].flatMap(n =>
        [`vehicles/${t}/${n}.png`, `vehicles/${t}/${n}@${HD}x.png`])),
    ]);
    const img = {};
    await Promise.all([...srcs].map(async s => { img[s] = await load(base, s); }));

    const canvas = document.createElement('canvas');
    canvas.className = 'pixel-city__canvas';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Isometric pixel city with moving traffic');
    root.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    // Tilt-shift layers (styled in CSS); render() keeps the sharp band on the
    // hero via --tilt-focus.
    const tilt = root.dataset.tiltshift !== 'off';
    if (tilt) {
      root.classList.add('pixel-city--tiltshift');
      const t = document.createElement('div');
      t.className = 'pixel-city__tiltshift';
      t.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 3; i++) t.appendChild(document.createElement('span'));
      root.appendChild(t);
    }
    let tiltFocus = -1;

    const layer = paint => {
      const c = document.createElement('canvas');
      c.width = W;
      c.height = H;
      const g = c.getContext('2d');
      g.imageSmoothingEnabled = false;
      paint(g);
      return c;
    };

    // Ground, painted back to front.
    const groundLayer = layer(g => {
      drawSlab(g);
      for (let d = 0; d < 2 * N - 1; d++) {
        for (let u = 0; u < N; u++) {
          const v = d - u;
          if (v < 0 || v >= N) continue;
          const [name, mode] = city.ground(u, v);
          const src = `tiles/${name}.png`;
          drawTile(g, img[src], u, v, mode);
        }
      }
    });

    // Static sprites: world footprint box + screen rect.
    const statics = [];
    const addStatic = (getImage, x, y, box) => {
      const first = getImage();
      const rect = [Math.round(x), Math.round(y), first.width, first.height];
      const item = { box, rect, draw: c => c.drawImage(getImage(), rect[0], rect[1]) };
      statics.push(item);
      return item;
    };
    const pointBox = (u, v) => [u - 0.05, u + 0.05, v - 0.05, v + 0.05];

    for (const [kind, u0, u1, v0, v1] of city.lots) {
      const b = BUILDINGS[kind];
      const cu = (u0 + u1) / 2, cv = (v0 + v1) / 2;
      const [x, y] = iso(cu + b.a / 2, cv + b.b / 2);
      addStatic(() => img[b.src], x - b.base[0], y - b.base[1],
        [cu - b.a / 2, cu + b.a / 2, cv - b.b / 2, cv + b.b / 2]);
    }
    for (const [src, u, v] of city.props) {
      const [ax, ay] = PROP_ANCHORS[src];
      const [x, y] = iso(u, v);
      addStatic(() => img[src], x - ax, y - ay, pointBox(u, v));
    }

    // Signal heads: one per axis, on the two camera-facing corners.
    let clock = 0;
    const phaseOf = sig => {
      let t = (clock + sig.offset) % CYCLE_T;
      for (const p of SIGNAL_CYCLE) { if (t < p.t) return p; t -= p.t; }
      return SIGNAL_CYCLE[0];
    };
    const light = (k, axis) => phaseOf(city.signals[k])[axis];
    const heads = [];
    city.signals.forEach((sig, k) => {
      for (const [axis, tag, [ax, ay], du, dv] of [
        ['v', 'a', [14.5, 61], 0.96, 0.96],
        ['u', 'b', [7.5, 60], 0.96, 0.04],
      ]) {
        const u = sig.u + du, v = sig.v + dv;
        const [x, y] = iso(u, v);
        const item = addStatic(() => img[`props/signal-${tag}-${light(k, axis)}.png`], x - ax, y - ay, pointBox(u, v));
        heads.push({ item, k, axis, shown: light(k, axis) });
      }
    });

    const hash = new ScreenHash(128);
    statics.forEach(s => hash.add(s));
    sortStatics(statics, hash);

    // Ground and static sprites, baked once; a region is re-baked when a
    // traffic light changes.
    const sceneLayer = layer(g => {
      g.drawImage(groundLayer, 0, 0);
      [...statics].sort(byOrder).forEach(s => s.draw(g));
    });
    const sceneCtx = sceneLayer.getContext('2d');
    sceneCtx.imageSmoothingEnabled = false;
    function rebake(rect) {
      sceneCtx.save();
      sceneCtx.beginPath();
      sceneCtx.rect(...rect);
      sceneCtx.clip();
      sceneCtx.clearRect(...rect);
      sceneCtx.drawImage(groundLayer, 0, 0);
      [...hash.query(rect)].sort(byOrder).forEach(s => s.draw(sceneCtx));
      sceneCtx.restore();
    }

    // Cars: the hero drives planned routes; the others loop.
    const { planRoute, firstSpot } = heroPlanner(city);
    let heroRoute = planRoute(firstSpot);
    const heroPath = heroRoute.path;

    const bumpState = () => ({ bumps: [], nextBump: Math.random() * BUMP_EVERY[1] });
    const hero = { id: 0, type: HERO_TYPE, path: heroPath, s: 0, speed: 0, roll: 0, ...bumpState(), parked: 0,
      pos: heroPath.samples[0], head: heroPath.heads[0], wait: 0, box: null, hero: true };
    const cars = [hero];
    for (const path of city.routes.map(r => buildPath(loopLane(r), city.signalAt, city.ground))) {
      const count = Math.max(1, Math.round(path.total / TILES_PER_CAR));
      for (let c = 0; c < count; c++) {
        for (let tries = 0; tries < 20; tries++) {
          const s = city.rng() * path.total;
          const i = Math.floor(s / path.step);
          const pos = path.samples[i];
          if (cars.some(o => Math.hypot(o.pos[0] - pos[0], o.pos[1] - pos[1]) < 1.2)) continue;
          cars.push({ id: cars.length, type: city.pick(TYPES), path, s, speed: CRUISE, roll: 0, ...bumpState(),
            pos, head: path.heads[i], wait: 0, box: null });
          break;
        }
      }
    }
    // Interpolate between path samples for smooth motion.
    const place = car => {
      const p = car.path, n = p.samples.length;
      const f = car.s / p.step, i = Math.floor(f) % n, t = f - Math.floor(f);
      const j = p.closed ? (i + 1) % n : Math.min(i + 1, n - 1);
      const a = p.samples[i], b = p.samples[j];
      car.pos = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      car.head = p.heads[i];
    };

    // Distance to `o` if it sits in `car`'s lane just ahead, else -1.
    const aheadOf = (car, o) => {
      const du = o.pos[0] - car.pos[0], dv = o.pos[1] - car.pos[1];
      if (Math.abs(du) > 1.5 || Math.abs(dv) > 1.5) return -1;
      const ahead = du * car.head[0] + dv * car.head[1];
      const side = Math.abs(du * car.head[1] - dv * car.head[0]);
      return ahead > 0 && side <= 0.22 ? ahead : -1;
    };

    function step(dt) {
      clock += dt;
      for (const car of cars) {
        let gap = Infinity, atLight = false;
        for (const o of cars) {
          if (o === car || o.parked > 0) continue;     // the parked hero is at the curb
          const ahead = aheadOf(car, o);
          if (ahead < 0) continue;
          const crossing = Math.abs(car.head[0] * o.head[0] + car.head[1] * o.head[1]) < 0.5;
          if (crossing) {
            // Break standoffs: the lower id goes, and nobody waits forever.
            if (car.id < o.id && aheadOf(o, car) >= 0) continue;
            if (car.wait > 3) continue;
          }
          gap = Math.min(gap, ahead - GAP);
        }
        for (const st of car.path.stops) {
          const state = light(st.sig, st.axis);
          if (state === 'green') continue;
          let d = st.s - car.s;
          if (d < -1) d += car.path.total;
          if (d < -0.01 || d > 1.2) continue;
          if (state === 'amber' && d < 0.25) continue;     // too close to stop
          if (d < gap) { gap = d; atLight = true; }
        }
        if (!car.path.closed) gap = Math.min(gap, car.path.total - car.path.step - car.s);
        const target = Math.min(CRUISE, Math.sqrt(2 * DECEL * Math.max(0, gap)));
        car.speed = target > car.speed
          ? Math.min(target, car.speed + ACCEL * dt)
          : Math.max(target, car.speed - DECEL * dt);
        if (gap <= 0) car.speed = 0;
        car.wait = car.speed < 0.05 && !atLight ? car.wait + dt : 0;
        car.roll += car.speed * dt;
        for (const b of car.bumps) b.t += dt;
        car.bumps = car.bumps.filter(b => b.t < BUMP_T);
        if (car.roll >= car.nextBump) {
          const [lo, hi] = BUMP_EVERY, [g0, g1] = BUMP_GAP;
          car.nextBump = car.roll + lo + Math.random() * (hi - lo);
          const run = 1 + Math.floor(Math.random() * BUMP_RUN);
          let t = 0;                                    // negative t: still to come
          for (let i = 0; i < run; i++, t -= g0 + Math.random() * (g1 - g0)) {
            car.bumps.push({ t, amp: BUMP_AMP * (0.6 + 0.4 * Math.random())
              * Math.min(1, car.speed / CRUISE) });
          }
        }
        if (car.path.closed) car.s = (car.s + car.speed * dt) % car.path.total;
        else car.s = Math.min(car.s + car.speed * dt, car.path.total - car.path.step);
        if (car.hero && car.path.total - car.path.step - car.s < 0.02 && car.speed < 0.02) {
          car.parked += dt;
          if (car.parked >= PARK_S) {
            heroRoute = planRoute(heroRoute.end);
            car.path = heroRoute.path; car.s = 0; car.parked = 0; car.speed = 0;
          }
        }
        place(car);
      }
    }

    /* ---------- mini-map ---------- */

    // GPS phone: a pixel-art smartphone whose screen shows a map following the
    // hero, with the route (orange ahead, gray behind), destination pin and
    // car dot. Map scale: MM_HW × MM_HH map px per half tile.
    const MM_HW = 6, MM_HH = 3;
    const PH_W = 96, PH_H = 164;                    // phone body
    const MM_W = PH_W + 2, MM_H = PH_H;             // + side buttons
    const MM_FRAC = 0.25;                           // phone height / container height
    const SX = 7, SY = 16, SW = 84, SH = 134;       // screen rect
    const BAR = 7;                                  // status bar height
    const MM_C = {
      body: '#2b303b', bodyHi: '#454c5a', outline: '#07090d', button: '#1a1e26',
      speaker: '#161a22', lens: '#1d3b5c', home: '#5b6477',
      screen: '#0e1320', status: '#070a11', text: '#c9d1e0',
      grass: '#1b2a25', paving: '#262f3f', water: '#1f3552', lot: '#2c3548', road: '#46526b',
      ahead: '#ff4e00', behind: '#b8c1d3', car: '#ffffff', carEdge: '#0e1320',
    };
    const mmX = (u, v) => 1 + MM_HW * (N + u - v);
    const mmY = (u, v) => 1 + MM_HH * (u + v);
    const canvasOf = (w, h) => {
      const c = document.createElement('canvas');
      c.width = w;
      c.height = h;
      return c;
    };
    const painter = g => (x, y, w, h, color) => { g.fillStyle = color; g.fillRect(x, y, w, h); };
    // Rounded rect with stepped (pixel) corners.
    const roundRect = (px, x, y, w, h, r, color) => {
      for (let row = 0; row < h; row++) {
        const d = row < r ? r - row - 0.5 : row >= h - r ? row - (h - r) + 0.5 : 0;
        const inset = d ? Math.round(r - Math.sqrt(Math.max(0, r * r - d * d))) : 0;
        px(x + inset, y + row, w - 2 * inset, 1, color);
      }
    };

    const mmCanvas = document.createElement('canvas');
    mmCanvas.className = 'pixel-city__minimap';
    mmCanvas.setAttribute('aria-hidden', 'true');
    const mmHost = root.dataset.minimap && document.getElementById(root.dataset.minimap);
    if (mmHost) mmHost.appendChild(mmCanvas);
    else {
      Object.assign(mmCanvas.style, { position: 'absolute', right: '4%', bottom: '6%' });
      root.appendChild(mmCanvas);
    }
    const mctx = mmCanvas.getContext('2d');

    // The whole city at map scale, drawn once.
    const mmMap = (() => {
      const c = canvasOf(Math.ceil(2 * N * MM_HW) + 2, Math.ceil(2 * N * MM_HH) + 2);
      const px = painter(c.getContext('2d'));
      const lotAt = new Set();
      for (const [, u0, u1, v0, v1] of city.lots) {
        for (let u = Math.floor(u0); u < Math.ceil(u1); u++) for (let v = Math.floor(v0); v < Math.ceil(v1); v++) lotAt.add(u + ',' + v);
      }
      for (let u = 0; u < N; u++) {
        for (let v = 0; v < N; v++) {
          const [name] = city.ground(u, v);
          const color = lotAt.has(u + ',' + v) ? MM_C.lot
            : name === 'grass' ? MM_C.grass
            : name === 'paving' ? MM_C.paving
            : ['pond', 'pool', 'canal'].includes(name) ? MM_C.water
            : MM_C.road;
          const cx = mmX(u + 0.5, v + 0.5), cy = mmY(u + 0.5, v + 0.5);
          for (let y = Math.floor(cy - MM_HH); y <= cy + MM_HH; y++) {
            for (let x = Math.floor(cx - MM_HW); x <= cx + MM_HW; x++) {
              if (Math.abs(x + 0.5 - cx) / MM_HW + Math.abs(y + 0.5 - cy) / MM_HH <= 1) px(x, y, 1, 1, color);
            }
          }
        }
      }
      return c;
    })();

    // Phone body, drawn once; the screen is painted over it every frame.
    const mmPhone = (() => {
      const c = canvasOf(MM_W, MM_H);
      const px = painter(c.getContext('2d'));
      px(0, 34, 1, 10, MM_C.button);                // volume
      px(0, 48, 1, 10, MM_C.button);
      px(MM_W - 1, 40, 1, 14, MM_C.button);         // power
      roundRect(px, 1, 0, PH_W, PH_H, 9, MM_C.outline);
      roundRect(px, 2, 1, PH_W - 2, PH_H - 2, 8, MM_C.body);
      px(3, 10, 1, PH_H - 20, MM_C.bodyHi);         // edge highlight
      px(10, 2, PH_W - 18, 1, MM_C.bodyHi);
      roundRect(px, SX - 1, SY - 1, SW + 2, SH + 2, 3, MM_C.outline);
      px(1 + PH_W / 2 - 8, 8, 16, 2, MM_C.speaker);
      px(1 + PH_W / 2 + 12, 7, 3, 3, MM_C.outline);
      px(1 + PH_W / 2 + 13, 8, 1, 1, MM_C.lens);
      px(1 + PH_W / 2 - 12, PH_H - 9, 24, 2, MM_C.home);
      return c;
    })();

    const PIN = [
      '..#####..', '.#ooooo#.', '#oowwwoo#', '#oowwwoo#', '#oowwwoo#', '#ooooooo#',
      '.#ooooo#.', '..#ooo#..', '..#ooo#..', '...#o#...', '...#o#...', '....#....',
    ];
    // 3×5 digits and ':' for the status-bar clock.
    const GLYPHS = {
      0: '111101101101111', 1: '010110010010111', 2: '111001111100111', 3: '111001111001111',
      4: '101101111001001', 5: '111100111001111', 6: '111100111101111', 7: '111001010010010',
      8: '111101111101111', 9: '111101111001111', ':': '000010000010000',
    };
    let mmRoute = null, mmPixels = [];
    function mmRoutePixels(path) {
      const seen = new Map();
      path.samples.forEach(([u, v], i) => {
        const x = Math.round(mmX(u, v)) - 1, y = Math.round(mmY(u, v)) - 1;
        const key = x + ',' + y;
        if (!seen.has(key)) seen.set(key, [x, y, i]);
      });
      return [...seen.values()];
    }
    const mmCam = { x: 0, y: 0, t: -1 };
    function drawMinimap() {
      if (mmRoute !== hero.path) { mmRoute = hero.path; mmPixels = mmRoutePixels(hero.path); }
      // Follow the car, eased like the main camera.
      const hx = mmX(hero.pos[0], hero.pos[1]), hy = mmY(hero.pos[0], hero.pos[1]);
      const k = mmCam.t < 0 ? 1 : 1 - Math.exp(-Math.max(0, clock - mmCam.t) * 2.5);
      mmCam.x += (hx - mmCam.x) * k;
      mmCam.y += (hy - mmCam.y) * k;
      mmCam.t = clock;
      const ox = Math.round(mmCam.x - SW / 2), oy = Math.round(mmCam.y - (BAR + (SH - BAR) * 0.55));

      const d = mmScale;
      mctx.setTransform(1, 0, 0, 1, 0, 0);
      mctx.clearRect(0, 0, mmCanvas.width, mmCanvas.height);
      mctx.imageSmoothingEnabled = false;
      mctx.setTransform(d, 0, 0, d, 0, 0);
      mctx.drawImage(mmPhone, 0, 0);
      const raw = painter(mctx);
      // Screen-clipped fill, in map coordinates.
      const px = (x, y, w, h, color) => {
        const x0 = Math.max(SX, x - ox + SX), y0 = Math.max(SY, y - oy + SY);
        const x1 = Math.min(SX + SW, x - ox + SX + w), y1 = Math.min(SY + SH, y - oy + SY + h);
        if (x1 > x0 && y1 > y0) raw(x0, y0, x1 - x0, y1 - y0, color);
      };
      raw(SX, SY, SW, SH, MM_C.screen);
      const sx0 = Math.max(0, ox), sy0 = Math.max(0, oy);
      const sx1 = Math.min(mmMap.width, ox + SW), sy1 = Math.min(mmMap.height, oy + SH);
      if (sx1 > sx0 && sy1 > sy0) {
        mctx.drawImage(mmMap, sx0, sy0, sx1 - sx0, sy1 - sy0, SX + sx0 - ox, SY + sy0 - oy, sx1 - sx0, sy1 - sy0);
      }
      const n = hero.path.samples.length;
      const at = Math.min(n - 1, Math.floor(hero.s / hero.path.step));
      for (const [x, y, i] of mmPixels) {
        if (x < ox - 2 || y < oy - 2 || x > ox + SW || y > oy + SH) continue;
        px(x, y, 2, 2, i <= at ? MM_C.behind : MM_C.ahead);
      }
      // Destination pin; stays on the screen edge while off-screen.
      const [eu, ev] = hero.path.samples[n - 1];
      const clampTo = (val, lo, hi) => Math.min(hi, Math.max(lo, val));
      const ex = clampTo(Math.round(mmX(eu, ev)), ox + 5, ox + SW - 5);
      const ey = clampTo(Math.round(mmY(eu, ev)), oy + BAR + PIN.length + 1, oy + SH - 2);
      PIN.forEach((row, r) => [...row].forEach((ch, c) => {
        if (ch !== '.') px(ex - (row.length >> 1) + c, ey - PIN.length + 1 + r, 1, 1, ch === '#' ? MM_C.carEdge : ch === 'w' ? MM_C.car : MM_C.ahead);
      }));
      // Car: white dot, blinking orange while parked.
      const cx = Math.round(hx), cy = Math.round(hy);
      px(cx - 3, cy - 3, 6, 6, MM_C.carEdge);
      px(cx - 2, cy - 2, 4, 4, hero.parked > 0 && Math.floor(clock * 3) % 2 ? MM_C.ahead : MM_C.car);
      // Status bar: clock, signal, battery.
      raw(SX, SY, SW, BAR, MM_C.status);
      const now = new Date();
      const time = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
      let tx = SX + 3;
      for (const ch of time) {
        const bits = GLYPHS[ch];
        for (let r = 0; r < 5; r++) for (let c = 0; c < 3; c++) if (bits[r * 3 + c] === '1') raw(tx + c, SY + 1 + r, 1, 1, MM_C.text);
        tx += 4;
      }
      for (let b = 0; b < 4; b++) raw(SX + SW - 22 + b * 2, SY + 5 - b, 1, b + 1, MM_C.text);
      raw(SX + SW - 11, SY + 1, 8, 5, MM_C.text);
      raw(SX + SW - 10, SY + 2, 6, 3, MM_C.status);
      raw(SX + SW - 10, SY + 2, 4, 3, MM_C.text);
      raw(SX + SW - 3, SY + 2, 1, 3, MM_C.text);
      // Round the screen's corners.
      for (const [x, y] of [[SX, SY], [SX + SW - 1, SY], [SX, SY + SH - 1], [SX + SW - 1, SY + SH - 1]]) raw(x, y, 1, 1, MM_C.outline);
    }

    /* ---------- view ---------- */

    // Whole device px per art px keeps pixels sharp.
    const view = { scale: 1, w: 0, h: 0, x: 0, y: 0, camX: 0, camY: 0 };
    let mmScale = 1;
    // Snap motion to device pixels (finer than art pixels) for smoothness.
    const snap = a => Math.round(a * view.scale) / view.scale;
    function resize() {
      const dpr = window.devicePixelRatio || 1;
      const cw = root.clientWidth, ch = root.clientHeight;
      // Phone is MM_FRAC of the container height, drawn sharp then scaled by CSS.
      const mmH = ch * MM_FRAC;
      mmScale = Math.max(1, Math.ceil(mmH * dpr / MM_H));
      mmCanvas.width = MM_W * mmScale;
      mmCanvas.height = MM_H * mmScale;
      mmCanvas.style.width = mmH * MM_W / MM_H + 'px';
      mmCanvas.style.height = mmH + 'px';
      view.scale = Math.max(1, Math.round(zoom * dpr));
      canvas.width = Math.max(1, Math.floor(cw * dpr));
      canvas.height = Math.max(1, Math.floor(ch * dpr));
      canvas.style.width = canvas.width / dpr + 'px';
      canvas.style.height = canvas.height / dpr + 'px';
      view.w = Math.ceil(canvas.width / view.scale);
      view.h = Math.ceil(canvas.height / view.scale);
      ctx.imageSmoothingEnabled = false;
    }

    const heroScreen = () => iso(hero.pos[0], hero.pos[1]);
    function follow(dt) {
      const [tx, ty] = heroScreen();
      const k = dt === Infinity ? 1 : 1 - Math.exp(-dt * 1.2);
      view.camX += (tx - view.camX) * k;
      view.camY += (ty - 40 - view.camY) * k;
      const clamp = (c, size, total) => size >= total
        ? snap((total - size) / 2)
        : snap(Math.min(total - size, Math.max(0, c - size / 2)));
      view.x = clamp(view.camX, view.w, W);
      view.y = clamp(view.camY, view.h, H);
    }

    function drawCar(c, car) {
      const f = frameFor(car.head[0], car.head[1]);
      const [x, y] = iso(car.pos[0], car.pos[1]);
      const px = snap(x), py = snap(y);
      const cell = car.hero ? HERO_CELL : CAR_CELL;
      const pivot = car.hero ? HERO_PIVOT[f] : CAR_PIVOT;
      if (!car.hero) {
        c.fillStyle = 'rgba(20, 22, 30, .28)';             // contact shadow
        c.fillRect(px - 13, py - 1, 26, 3);
        c.fillRect(px - 9, py - 3, 18, 7);
      }
      const k = view.scale % HD ? 1 : HD;
      const sfx = k > 1 ? `@${k}x.png` : '.png';
      const w = cell[0] * k, h = cell[1] * k;
      const phase = Math.floor(car.roll * WHEEL_STEPS) % WHEEL_PHASES
        + (car.speed > WHEEL_BLUR_SPEED ? WHEEL_PHASES : 0);
      const by = snap(y - bumpLift(car));                  // body, on its bump
      c.drawImage(img[`vehicles/${car.type}/iso${sfx}`], f * w, 0, w, h,
        px - pivot[0], by - pivot[1], cell[0], cell[1]);
      c.drawImage(img[`vehicles/${car.type}/wheels${sfx}`], f * w, phase * h, w, h,
        px - pivot[0], by - pivot[1], cell[0], cell[1]);
      return [px - pivot[0], by - pivot[1], cell[0], cell[1] + 4 + (py - by)];
    }

    function render() {
      for (const h of heads) {
        const state = light(h.k, h.axis);
        if (state !== h.shown) {
          h.shown = state;
          rebake(h.item.rect);
        }
      }
      const s = view.scale;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(s, 0, 0, s, -view.x * s, -view.y * s);
      ctx.drawImage(sceneLayer, 0, 0);

      const inView = [view.x - 64, view.y - 64, view.w + 128, view.h + 128];
      const r = 0.2;
      const visible = [];
      for (const car of cars) {
        car.box = [car.pos[0] - r, car.pos[0] + r, car.pos[1] - r, car.pos[1] + r];
        const [x, y] = iso(car.pos[0], car.pos[1]);
        if (overlap([x, y, 1, 1], inView)) visible.push(car);
      }
      visible.sort((a, b) => depth(a) - depth(b));
      for (const car of visible) {
        const rect = drawCar(ctx, car);
        // Redraw whatever stands in front of the car, clipped to it.
        const front = [...hash.query(rect)].filter(st => drawsBefore(car, st)).sort(byOrder);
        if (!front.length) continue;
        ctx.save();
        ctx.beginPath();
        ctx.rect(...rect);
        ctx.clip();
        front.forEach(st => st.draw(ctx));
        ctx.restore();
      }

      // The marker floats above everything so the hero is never lost.
      const [hx, hy] = heroScreen();
      const bob = Math.round(Math.sin(clock * 2.4) * 2);
      drawGem(ctx, snap(hx), snap(hy) + HERO_GEM_Y + bob, (clock * 0.35) % 1);
      if (tilt) {
        const f = Math.round((hy - 20 - view.y) * s / canvas.height * 1000) / 10;
        if (f !== tiltFocus) root.style.setProperty('--tilt-focus', (tiltFocus = f) + '%');
      }
      drawMinimap();
    }

    new ResizeObserver(() => { resize(); follow(Infinity); render(); }).observe(root);

    let onScreen = true;
    new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; }).observe(root);

    const still = window.matchMedia('(prefers-reduced-motion: reduce)');
    let last = performance.now();
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (onScreen && !still.matches && !document.hidden) {
        step(dt);
        follow(dt);
        render();
      }
      requestAnimationFrame(frame);
    }
    resize();
    follow(Infinity);
    render();
    requestAnimationFrame(frame);
  }

  document.querySelectorAll('[data-pixel-city]').forEach(el => {
    mount(el).catch(err => console.error(err));
  });
})();
