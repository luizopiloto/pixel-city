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
 *   data-zoom       CSS px per art px (default 1)
 *   data-minimap    id of an element to hold the GPS phone (optional)
 *   data-tiltshift  "off" to disable the tilt-shift blur
 */
(() => {
  const TW = 128, TH = 64, HW = TW / 2, HH = TH / 2;
  const BLOCK = 3, PITCH = BLOCK + 1;
  const ROAD0 = 1;                          // first road line (after the verge)
  const TOP = 8;                            // headroom above the top tile
  const SLAB = 14;                          // soil edge under the island
  // World size in tiles (NU × NV) and in px (W × H), set per generated city
  // by setWorld(). OX is the screen x of tile (0, 0)'s top corner.
  let NU = 0, NV = 0, W = 0, H = 0, OX = 0;
  function setWorld(nu, nv) {
    NU = nu;
    NV = nv;
    W = (nu + nv) * HW + 2;
    H = TOP + (nu + nv) * HH + SLAB + 2;
    OX = nv * HW + 1;
  }

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
  // in tiles along u / v. Dressed sprites keep the lamps, benches and tables
  // of the plated originals, without their pavement pad (tools/bake.py).
  const BUILDINGS = {
    tower:   { src: 'buildings/tower-dressed.png',  base: [126, 153],   a: 1.906, b: 1.156 },
    corner:  { src: 'buildings/corner-dressed.png', base: [110.5, 147], a: 1.664, b: 1.039 },
    house:   { src: 'buildings/house-dressed.png',  base: [118, 154],   a: 1.781, b: 1.062 },
    cafe:    { src: 'buildings/cafe-dressed.png',   base: [118, 134],   a: 1.781, b: 1.062 },
    kiosk:   { src: 'building-modern.png',       base: [90, 114],    a: 1.344, b: 0.656 },
    cottage: { src: 'building-small.png',        base: [90, 135],    a: 1.344, b: 0.656 },
    flats:   { src: 'buildings/corner-bare.png', base: [86, 128],    a: 1.344, b: 0.656 },
    office:  { src: 'buildings/tower-bare.png',  base: [86, 128],    a: 1.344, b: 0.656 },
  };
  const DRESSED = ['tower', 'corner', 'house', 'cafe'];
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

  // Downtown: a compact random blob of DOWNTOWN_CELLS block cells, with
  // SUPER_COUNT superblocks (3×2 / 2×3 cells merged, inner roads removed)
  // and one long block (1×2, 1×3, 2×1 or 3×1 merged) per CELLS_PER_LONG
  // downtown cells, mostly 1×2 / 2×1; suburbs get one per SUBURB_PER_LONG.
  const DOWNTOWN_CELLS = 256, SUPER_COUNT = 8, CELLS_PER_LONG = 7, SUBURB_PER_LONG = 6;
  // Sea around the island: empty lattice cells on the two back sides (-u,
  // -v) and the two camera-facing ones (+u, +v), where the beach is wider.
  const SEA_BACK = 2, SEA_FRONT = 4;
  const LOOSE_BOATS = 4;     // rowboats out at sea (besides those moored at piers)
  const LONG_SHAPES = [[1, 2], [1, 2], [1, 2], [2, 1], [2, 1], [2, 1], [1, 3], [3, 1]];
  const SUBURB_SHAPES = [[1, 2], [1, 3], [2, 1], [3, 1]];
  // 2×2 squares: buildings around a recreation area (a grass town square
  // downtown, a BBQ area or a playground in suburbs).
  const DOWNTOWN_SQUARES = [3, 5], SUBURB_PER_SQUARE = 25;
  // Districts attached to downtown's sides: [type, min cells, max cells].
  const DISTRICTS = { suburb: [40, 60], park: [22, 36], plaza: [22, 32] };
  // Civic landmarks each district type may get: at most one of each per
  // district (the manifest tags them unique: "district").
  const CIVIC = {
    downtown: ['bank', 'police', 'fire-station', 'church'],
    suburb: ['school', 'church', 'post-office', 'fire-station'],
    plaza: ['post-office', 'bank', 'police'],
    park: [],
  };
  const HOUSES = [1, 2, 3, 4, 5, 6].map(n => `houses/house-${n}.png`);
  const PLAZA_BUILDINGS = ['buildings/shop-6.png', 'buildings/shop-7.png', 'buildings/fastfood.png',
    'buildings/apartment-1.png', 'buildings/apartment-2.png'];
  const DOWNTOWN_ART = ['buildings/shop-7.png', 'buildings/brick-3.png', 'buildings/brick-4.png', 'buildings/office-8.png'];
  const CANOPY = 0.38;                             // brick-4's entrance canopy, out from its front
  const HELIPAD_ODDS = 0.2;                        // glass offices with the helipad roof (office-5)
  const TREES = ['oak', 'oak-small', 'maple', 'birch', 'olive', 'pine', 'pine-small'].map(n => `nature/trees/${n}.png`);
  const CITY_TREES = ['oak', 'oak-small', 'maple', 'birch'].map(n => `nature/trees/${n}.png`);
  const BUSHES = ['bush', 'bush-small', 'bush-flowers', 'shrub'].map(n => `nature/bushes/${n}.png`);
  const GRASSES = ['grass-a', 'grass-a', 'grass-b', 'grass-lush', 'grass-flowers'].map(n => `art/ground/${n}`);
  // Regular 3×3 blocks, by template (relative weights).
  const BLOCK_MIX = { twin: 12, row: 8, mixed: 8, plaza: 3, park: 7, canal: 2 };
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

  const CELLS_PER_SIGNAL = 8;              // one signalised crossing per this many cells
  const SIGNAL_CYCLE = [                   // seconds per phase
    { u: 'green', v: 'red', t: 6 }, { u: 'amber', v: 'red', t: 1.4 },
    { u: 'red', v: 'red', t: 0.8 }, { u: 'red', v: 'green', t: 6 },
    { u: 'red', v: 'amber', t: 1.4 }, { u: 'red', v: 'red', t: 0.8 },
  ];
  const CYCLE_T = SIGNAL_CYCLE.reduce((s, p) => s + p.t, 0);

  const CELLS_PER_ROUTE = 4.5;             // one traffic loop per this many cells
  const TILES_PER_CAR = 24;  // traffic density along each loop
  const LANE = 0.23;         // lane offset from the road center line
  const TURN = 0.36;         // fillet radius at corners
  const CRUISE = 1.3;        // tiles / s
  const ACCEL = 1.6, DECEL = 3.2;
  const GAP = 0.62;          // following distance
  const CROSS_MARGIN = 0.8;  // s of slack needed to cross ahead of another car
  const PATIENCE = 3;        // s stopped (not at a light) before a car stops giving way to a stopped car
  const PULL = 0.8;          // hero's pull-out/pull-in length along the road
  const TYPES = ['carDefault', 'carSedan', 'carYellow'];

  // Sprite 0000 faces the camera; frames step 30° counter-clockwise.
  // The four iso road directions land on frames 1, 11, 7 and 5.
  const CAR_CELL = [53, 40];
  // Half a car length in tiles: how far the stop line is from the car's center.
  const CAR_HALF = 0.24, HERO_HALF = 0.38;
  const CAR_HALF_W = 0.12, HERO_HALF_W = 0.15;   // half widths, in tiles
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

  function generate(rng, art = {}) {
    const pick = list => list[Math.floor(rng() * list.length)];
    const shuffle = list => {
      for (let i = list.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1));
        [list[i], list[j]] = [list[j], list[i]];
      }
      return list;
    };
    const key = (a, b) => a + ',' + b;
    const NB4 = [[1, 0], [-1, 0], [0, 1], [0, -1]];

    // Downtown: grow a blob of cells from the center. Frontier cells with
    // more filled neighbors are likelier (compact shape); a smooth random
    // field biases growth into lobes, so the outline is irregular.
    const GRID = 72;
    const field = (() => {
      const g = [], n = GRID / 6 + 2;
      for (let a = 0; a < n; a++) { g.push([]); for (let b = 0; b < n; b++) g[a].push(rng()); }
      return (ci, cj) => {
        const x = ci / 6, y = cj / 6, x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0;
        const top = g[x0][y0] * (1 - fx) + g[x0 + 1][y0] * fx;
        const bot = g[x0][y0 + 1] * (1 - fx) + g[x0 + 1][y0 + 1] * fx;
        return top * (1 - fy) + bot * fy;
      };
    })();
    const cells = new Map();                     // 'i,j' → { i, j, type, sup }
    const filled = (ci, cj) => cells.has(key(ci, cj));
    const fill = (ci, cj, type, district = 0) => cells.set(key(ci, cj), { i: ci, j: cj, type, district, sup: -1 });
    fill(GRID >> 1, GRID >> 1, 'downtown');
    while (cells.size < DOWNTOWN_CELLS) {
      const front = new Map();
      for (const c of cells.values()) {
        for (const [di, dj] of NB4) {
          const ni = c.i + di, nj = c.j + dj;
          if (ni < 1 || nj < 1 || ni >= GRID - 1 || nj >= GRID - 1 || filled(ni, nj)) continue;
          const n = NB4.filter(([a, b]) => filled(ni + a, nj + b)).length;
          front.set(key(ni, nj), [ni, nj, n * n * (0.25 + field(ni, nj))]);
        }
      }
      const opts = [...front.values()];
      let r = rng() * opts.reduce((t, o) => t + o[2], 0);
      const [ni, nj] = opts.find(o => (r -= o[2]) <= 0) || opts[opts.length - 1];
      fill(ni, nj, 'downtown');
    }
    // Districts: blobs grown outward from downtown's sides, each from a
    // seed cell on the outline facing its direction.
    const center = GRID >> 1;
    const kinds = shuffle(['suburb', 'park', 'plaza', ...(rng() < 0.6 ? ['suburb'] : [])]);
    const sides = shuffle([[1, 0], [-1, 0], [0, 1], [0, -1]]);
    const districts = [{ type: 'downtown' }];
    kinds.forEach((type, k) => {
      const [dx, dy] = sides[k % sides.length];
      const id = districts.length;
      let seed = null, best = -Infinity;
      for (const c of cells.values()) for (const [di, dj] of NB4) {
        const ni = c.i + di, nj = c.j + dj;
        if (filled(ni, nj)) continue;
        const score = (ni - center) * dx + (nj - center) * dy + rng() * 3;
        if (score > best) { best = score; seed = [ni, nj]; }
      }
      if (!seed) return;
      districts.push({ type });
      fill(seed[0], seed[1], type, id);
      const [lo, hi] = DISTRICTS[type];
      const target = lo + Math.floor(rng() * (hi - lo + 1));
      for (let n = 1; n < target; n++) {
        const front = new Map();
        for (const c of cells.values()) {
          if (c.district !== id) continue;
          for (const [di, dj] of NB4) {
            const ni = c.i + di, nj = c.j + dj;
            if (ni < 1 || nj < 1 || ni >= GRID - 1 || nj >= GRID - 1 || filled(ni, nj)) continue;
            const own = NB4.filter(([a, b]) => { const o = cells.get(key(ni + a, nj + b)); return o && o.district === id; }).length;
            const far = Math.hypot(ni - seed[0], nj - seed[1]);
            front.set(key(ni, nj), [ni, nj, own * own * (0.25 + field(ni, nj)) * Math.exp(-far / 5)]);
          }
        }
        const opts = [...front.values()];
        if (!opts.length) break;
        let r = rng() * opts.reduce((t, o) => t + o[2], 0);
        const [ni, nj] = opts.find(o => (r -= o[2]) <= 0) || opts[opts.length - 1];
        fill(ni, nj, type, id);
      }
    });
    for (let again = true; again;) {             // fill enclosed gaps with a neighbor's district
      again = false;
      for (let ci = 1; ci < GRID - 1; ci++) for (let cj = 1; cj < GRID - 1; cj++) {
        const around = NB4.map(([a, b]) => cells.get(key(ci + a, cj + b))).filter(Boolean);
        if (!filled(ci, cj) && around.length >= 3) {
          fill(ci, cj, around[0].type, around[0].district);
          again = true;
        }
      }
    }
    // Crop the lattice to the cells in use, plus the sea around them.
    const all = [...cells.values()];
    const mi = Math.min(...all.map(c => c.i)) - SEA_BACK, mj = Math.min(...all.map(c => c.j)) - SEA_BACK;
    const cropped = new Map();
    for (const c of all) { c.i -= mi; c.j -= mj; cropped.set(key(c.i, c.j), c); }
    cells.clear();
    for (const [k, c] of cropped) cells.set(k, c);
    const IU = Math.max(...all.map(c => c.i)) + 1 + SEA_FRONT, IV = Math.max(...all.map(c => c.j)) + 1 + SEA_FRONT;
    const cellAt = (ci, cj) => cells.get(key(ci, cj));
    const nu = roadAt(IU) + 2, nv = roadAt(IV) + 2;

    // Merged blocks (their inner roads removed): first the 3×2 / 2×3
    // superblocks, kept apart from each other, then the long 1×2 … 3×1
    // blocks, which may sit beside other merged blocks but never overlap.
    const supers = [];
    function merge(count, shapes, apart, type = 'downtown', district = -1, kind = 'block') {
      for (let tries = 0, placed = 0; placed < count && tries < 4000; tries++) {
        const [bw, bh] = shapes[Math.floor(rng() * shapes.length)];
        const bi = Math.floor(rng() * (IU - bw + 1)), bj = Math.floor(rng() * (IV - bh + 1));
        let ok = true;
        for (let a = bi - 1; a <= bi + bw && ok; a++) for (let b = bj - 1; b <= bj + bh && ok; b++) {
          const c = cellAt(a, b), inside = a >= bi && a < bi + bw && b >= bj && b < bj + bh;
          if (inside && (!c || c.type !== type || c.sup >= 0 || (district >= 0 && c.district !== district))) ok = false;
          if (apart && c && c.sup >= 0) ok = false;
        }
        if (!ok) continue;
        const k = supers.length;
        for (let a = bi; a < bi + bw; a++) for (let b = bj; b < bj + bh; b++) cellAt(a, b).sup = k;
        supers.push({ type, kind, district: cellAt(bi, bj).district, bi, bj, bw, bh, u0: roadAt(bi) + 1, u1: roadAt(bi + bw), v0: roadAt(bj) + 1, v1: roadAt(bj + bh) });
        placed++;
      }
    }
    merge(SUPER_COUNT, [[3, 2], [2, 3]], true);
    merge(1, [[1, 2], [2, 1]], true, 'downtown', -1, 'parking');
    merge(DOWNTOWN_SQUARES[0] + Math.floor(rng() * (DOWNTOWN_SQUARES[1] - DOWNTOWN_SQUARES[0] + 1)), [[2, 2]], true,
      'downtown', -1, 'square');
    const typed = (t, d = -1) => [...cells.values()].filter(c => c.type === t && (d < 0 || c.district === d)).length;
    merge(Math.round(typed('downtown') / CELLS_PER_LONG), LONG_SHAPES, false);
    districts.forEach((d, id) => {
      if (d.type !== 'suburb') return;
      merge(Math.max(1, Math.round(typed('suburb', id) / SUBURB_PER_SQUARE)), [[2, 2]], false, 'suburb', id, 'square');
      merge(Math.round(typed('suburb', id) / SUBURB_PER_LONG), SUBURB_SHAPES, false, 'suburb', id);
    });

    // Roads: a segment between two lattice nodes exists when a cell beside
    // it is part of the city, unless both sides are the same superblock.
    const roadSet = new Set();
    const sameSuper = (a, b) => a && b && ((a.sup >= 0 && a.sup === b.sup) ||
      (a.type === 'park' && b.type === 'park' && a.district === b.district));
    for (let j = 0; j <= IV; j++) for (let i = 0; i < IU; i++) {     // along u
      const a = cellAt(i, j - 1), b = cellAt(i, j);
      if ((a || b) && !sameSuper(a, b)) {
        for (let u = roadAt(i); u <= roadAt(i + 1); u++) roadSet.add(key(u, roadAt(j)));
      }
    }
    for (let i = 0; i <= IU; i++) for (let j = 0; j < IV; j++) {     // along v
      const a = cellAt(i - 1, j), b = cellAt(i, j);
      if ((a || b) && !sameSuper(a, b)) {
        for (let v = roadAt(j); v <= roadAt(j + 1); v++) roadSet.add(key(roadAt(i), v));
      }
    }
    const isRoad = (u, v) => roadSet.has(key(u, v));
    const junction = (u, v) => isRoad(u, v) && NB4.filter(([du, dv]) => isRoad(u + du, v + dv)).length >= 3;

    // Land: cells, roads and superblock interiors, plus a one-tile verge.
    const core = new Set(roadSet);
    for (const c of cells.values()) {
      for (let du = 0; du < BLOCK; du++) for (let dv = 0; dv < BLOCK; dv++) {
        core.add(key(roadAt(c.i) + 1 + du, roadAt(c.j) + 1 + dv));
      }
    }
    for (const sb of supers) for (let u = sb.u0; u < sb.u1; u++) for (let v = sb.v0; v < sb.v1; v++) core.add(key(u, v));
    // Merged interiors (parks): the road-line tiles between their cells.
    for (let j = 0; j <= IV; j++) for (let i = 0; i < IU; i++) {
      if (cellAt(i, j - 1) && cellAt(i, j)) for (let u = roadAt(i) + 1; u < roadAt(i + 1); u++) core.add(key(u, roadAt(j)));
    }
    for (let i = 0; i <= IU; i++) for (let j = 0; j < IV; j++) {
      if (cellAt(i - 1, j) && cellAt(i, j)) for (let v = roadAt(j) + 1; v < roadAt(j + 1); v++) core.add(key(roadAt(i), v));
    }
    for (let i = 1; i < IU; i++) for (let j = 1; j < IV; j++) {
      if (cellAt(i - 1, j - 1) && cellAt(i, j - 1) && cellAt(i - 1, j) && cellAt(i, j)) core.add(key(roadAt(i), roadAt(j)));
    }
    const land = new Set(core);
    for (const k of core) {
      const [u, v] = k.split(',').map(Number);
      for (let du = -1; du <= 1; du++) for (let dv = -1; dv <= 1; dv++) land.add(key(u + du, v + dv));
    }
    const inCity = (u, v) => land.has(key(u, v));
    const sea = new Set();                         // filled in by the waterfront below
    const isLand = (u, v) => u >= 0 && v >= 0 && u < nu && v < nv;        // every tile has ground
    const isWater = (u, v) => sea.has(key(u, v));

    const groundMap = new Map();
    const lots = [], props = [];
    const setGround = (u, v, name, mode = 0) => groundMap.set(key(u, v), [name, mode]);
    const pave = (u, v, lu = BLOCK, lv = BLOCK) => {
      for (let du = 0; du < lu; du++) for (let dv = 0; dv < lv; dv++) setGround(u + du, v + dv, 'paving');
    };
    const prop = (src, u, v) => props.push([src, u, v]);
    // A few trees in (u0, v0, lu, lv), clear of the props already there and of `keep`.
    const trees = (u0, v0, lu, lv, count, keep = () => false) => {
      const near = props.filter(([, pu, pv]) => pu > u0 - 0.5 && pu < u0 + lu + 0.5 && pv > v0 - 0.5 && pv < v0 + lv + 0.5);
      scatter(u0, v0, lu, lv, count, CITY_TREES,
        (tu, tv) => keep(tu, tv) || near.some(([, pu, pv]) => Math.hypot(pu - tu, pv - tv) < 0.45), 0.8);
    };
    const nook = (u, v) => {                 // benches in an empty 1.5 × 1.5 cell
      prop('props/bench-ne.png', u + 0.8, v + 0.9);
      prop(pick(PLANTERS), u + 0.35, v + 0.4);
      prop('props/bin-gray.png', u + 1.2, v + 1.25);
    };

    // Intersections with traffic lights: full crossings, spread apart.
    const signals = [];
    const candidates = [];
    for (let i = 1; i < IU; i++) for (let j = 1; j < IV; j++) {
      const u = roadAt(i), v = roadAt(j);
      const around = [cellAt(i - 1, j - 1), cellAt(i, j - 1), cellAt(i - 1, j), cellAt(i, j)];
      const busy = around.every(c => c && (c.type === 'downtown' || c.type === 'plaza'));
      if (busy && NB4.every(([du, dv]) => isRoad(u + du, v + dv))) candidates.push([i, j]);
    }
    shuffle(candidates);
    const signalCount = Math.round(cells.size / CELLS_PER_SIGNAL);
    for (const [i, j] of candidates) {
      if (signals.length === signalCount) break;
      if (signals.some(sg => Math.abs(sg.i - i) + Math.abs(sg.j - j) < 3)) continue;
      signals.push({ i, j, u: roadAt(i), v: roadAt(j), offset: rng() * CYCLE_T });
    }
    const signalAt = new Map(signals.map((sg, k) => [key(sg.u, sg.v), k]));

    const fp = name => (art[name] && art[name].footprint) || [1, 1];
    const artLot = (name, cu, cv, district) => {
      const [a, b] = fp(name);
      lots.push(['art:' + name, cu - a / 2, cu + a / 2, cv - b / 2, cv + b / 2, district]);
    };
    const artProp = (name, u, v) => props.push(['art/' + name, u, v]);

    // Block templates. (u, v) is the block's top tile; offsets are in [0, 3).
    const T = {
      twin(u, v) {
        // Back building against the block's back edge, front one on the
        // street, so the back one's entrance faces open ground.
        const p = shuffle([...DRESSED]), b0 = BUILDINGS[p[0]].b, b1 = BUILDINGS[p[1]].b;
        lots.push([p[0], u, u + 3, v + 0.06, v + 0.06 + b0], [p[1], u, u + 3, v + 2.94 - b1, v + 2.94]);
        prop(pick(PLANTERS), u + 0.22, v + 0.4 + rng() * 2.2);
        if (rng() < 0.6) prop('lamp.png', u + 2.8, v + 0.18);
        for (const su of [u, u + 2.44]) if (rng() < 0.6) trees(su, v + 1.1, 0.56, 0.8, 1);   // beside the gap
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
        const back = pick(DRESSED), b0 = BUILDINGS[back].b;
        lots.push([back, u, u + 3, v + 0.06, v + 0.06 + b0]);
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
        const water = (tu, tv) => tu > u + 0.8 && tu < u + 2.2 && tv > v + 0.8 && tv < v + 2.2;
        trees(u, v, 3, 3, 2 + (rng() < 0.5), water);
      },
      canal(u, v) {
        for (let du = 0; du < BLOCK; du++) setGround(u + du, v + 1, 'canal');
        prop('props/bench-ne.png', u + 0.8, v + 0.55);
        prop('props/bench-ne.png', u + 2.1, v + 0.55);
        prop('props/bench-ne.png', u + 1.4, v + 2.5);
        prop(pick(PLANTERS), u + 0.3, v + 2.7);
        prop(pick(PLANTERS), u + 2.7, v + 2.7);
        prop('lamp.png', u + 2.8, v + 0.2);
        trees(u, v, 3, 0.95, 1);                                     // one on each bank
        trees(u, v + 2.05, 3, 0.95, 1);
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

    // Superblock: dense paved downtown in columns and rows of buildings,
    // with ALLEY-wide paved alleys between rows so every entrance (on each
    // building's +v front) opens onto open ground.
    const ROW = 1.25, ALLEY = 0.5;
    function downtown(sb) {
      const lu = sb.u1 - sb.u0, lv = sb.v1 - sb.v0;
      pave(sb.u0, sb.v0, lu, lv);
      const cols = [];
      let rest = lu;
      while (rest >= 1.5) {
        const w = rest >= 2.1 && rng() < 0.55 ? 2.1 : 1.5;
        cols.push(w);
        rest -= w;
      }
      const rows = Math.floor((lv + ALLEY) / (ROW + ALLEY));
      const v0 = sb.v0 + (lv - rows * ROW - (rows - 1) * ALLEY) / 2;
      for (let r = 0; r < rows; r++) {
        let u = sb.u0 + rest / 2;
        const v = v0 + r * (ROW + ALLEY);
        for (const w of cols) {
          if (rng() < 0.3) {
            prop(pick(PLANTERS), u + w / 2 - 0.3, v + 0.4);
            prop('props/bench-ne.png', u + w / 2 + 0.2, v + 0.75);
          } else {
            lots.push([w > 2 ? pick(DRESSED) : pick(BARE), u, u + w, v, v + ROW]);
          }
          u += w;
        }
      }
    }

    // Parking lot (a 1×2 or 2×1 downtown block): stalls either side of an
    // aisle, a low fence all round and, on the +v street, a two-lane
    // entrance with a boom gate per lane. Some stalls hold parked cars; the
    // hero starts in one, and `lead` is its way out: along the aisle, out
    // through the exit lane, right onto the street (to -u).
    let parking = null;
    function parkingLot(sb) {
      const { u0, u1, v0, v1 } = sb, alongV = sb.bh > sb.bw, eu = u0 + 1;      // eu: the entrance column
      for (let u = u0; u < u1; u++) for (let v = v0; v < v1; v++) {
        const lane = alongV ? u === eu : v === v0 + 1 || (u === eu && v === v0 + 2);
        setGround(u, v, lane ? 'art/ground/lot' : alongV ? 'art/ground/lot-lines-u' : 'art/ground/lot-lines-v');
      }
      const stalls = [];                            // { u, v, toAisle }
      if (alongV) {
        for (let k = 0; k < (v1 - v0) * 2; k++) {
          const v = v0 + k * 0.5 + 0.25;
          stalls.push({ u: u0 + 0.5, v, toAisle: [1, 0] }, { u: u0 + 2.5, v, toAisle: [-1, 0] });
        }
      } else {
        for (let k = 0; k < (u1 - u0) * 2; k++) {
          const u = u0 + k * 0.5 + 0.25;
          stalls.push({ u, v: v0 + 0.5, toAisle: [0, 1] });
          if (u < eu || u > eu + 1) stalls.push({ u, v: v0 + 2.5, toAisle: [0, -1] });   // not the driveway
        }
      }
      const hs = alongV ? stalls.find(t => t.u === u0 + 0.5 && t.v === v0 + 0.75)
        : stalls.find(t => t.v === v0 + 0.5 && t.u === u0 + 4.25);
      const cars = [];
      for (const t of stalls) {
        if (t === hs || rng() > 0.45) continue;
        const flip = rng() < 0.35 ? -1 : 1;           // most park nose to the aisle
        cars.push({ u: t.u, v: t.v, head: [t.toAisle[0] * flip, t.toAisle[1] * flip], type: pick(TYPES) });
      }
      const lead = [];
      if (alongV) {
        lead.push([hs.u - 0.1, hs.v]);
        fillet(lead, [eu + 0.5, hs.v - LANE], [1, 0], [0, 1]);                // into the aisle
      } else {
        lead.push([hs.u, hs.v - 0.1]);
        fillet(lead, [hs.u + LANE, v0 + 1.5], [0, 1], [-1, 0]);               // into the aisle
        fillet(lead, [eu + 0.5, v0 + 1.5], [-1, 0], [0, 1]);                  // into the driveway
      }
      fillet(lead, [eu + 0.5, v1 + 0.5], [0, 1], [-1, 0]);                    // out, right onto the street
      // Fence round the edge, open at the entrance; a gate on each lane.
      for (let u = u0; u < u1; u++) {
        props.push(['art/parking/fence.png', u, v0 + 0.02, [u, u + 1, v0 + 0.02, v0 + 0.05]]);
        if (u !== eu) props.push(['art/parking/fence.png', u, v1 - 0.06, [u, u + 1, v1 - 0.06, v1 - 0.03]]);
      }
      for (let v = v0; v < v1; v++) {
        props.push(['art/parking/fence-r1.png', u0 + 0.05, v, [u0 + 0.02, u0 + 0.05, v, v + 1]]);
        props.push(['art/parking/fence-r1.png', u1 - 0.01, v, [u1 - 0.04, u1 - 0.01, v, v + 1]]);
      }
      props.push(['art/parking/gate-l.png', eu + 0.06, v1 - 0.1], ['art/parking/gate-r.png', eu + 0.94, v1 - 0.1]);
      parking = { cars, lead, behind: [sb.bi + 1, sb.bj + sb.bh], ahead: [sb.bi, sb.bj + sb.bh] };
    }

    // Town square (2×2 downtown): a row of buildings along its back edge
    // facing in and one along its street edge, around a grass square with a
    // fountain, corner trees, benches, lamps and flower beds.
    function townSquare({ u0, u1, v0, v1 }) {
      const lu = u1 - u0, cu = u0 + lu / 2, cv = v0 + (v1 - v0) / 2;
      pave(u0, v0, lu, v1 - v0);
      const cols = [];
      let rest = lu;
      while (rest >= 1.5) {
        const w = rest >= 2.1 && rng() < 0.55 ? 2.1 : 1.5;
        cols.push(w);
        rest -= w;
      }
      for (const v of [v0, v1 - ROW]) {
        let u = u0 + rest / 2;
        for (const w of cols) {
          lots.push([w > 2 ? pick(DRESSED) : pick(BARE), u, u + w, v, v + ROW]);
          u += w;
        }
      }
      for (let u = u0 + 1; u < u1 - 1; u++) for (let v = v0 + 2; v < v1 - 2; v++) setGround(u, v, pick(GRASSES));
      setGround(Math.floor(cu), Math.floor(cv), 'paving');
      artProp('rec/fountain.png', cu, cv);
      prop('props/bench-nw.png', cu - 1.25, cv);
      prop('props/bench-nw.png', cu + 1.25, cv);
      prop('props/bench-ne.png', cu, cv - 0.95);
      prop('props/bench-ne.png', cu, cv + 0.95);
      for (const [a, b] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
        artProp(pick(CITY_TREES), cu + a * 2.05, cv + b * 1.05);
        if (rng() < 0.6) artProp('nature/flowers/flower-bed.png', cu + a * 1.1, cv + b * 1.05);
      }
      prop('lamp-white.png', cu - 2.3, cv);
      prop('lamp-white.png', cu + 2.3, cv);
    }

    supers.filter(sb => sb.type === 'downtown')
      .forEach(sb => (sb.kind === 'square' ? townSquare : sb.kind === 'parking' ? parkingLot : downtown)(sb));

    // Art sprites (assets/art, see tools/art.py) stand at their footprint
    // center: lots as ['art:<name>', u0, u1, v0, v1, district], props as
    // ['art/<name>', u, v].
    // Trees and bushes spread over an area, kept apart and off `blocked`.
    function scatter(u0, v0, lu, lv, count, names, blocked = () => false, gap = 0.45) {
      const spots = [];
      for (let tries = 0; spots.length < count && tries < count * 12; tries++) {
        const u = u0 + 0.2 + rng() * (lu - 0.4), v = v0 + 0.2 + rng() * (lv - 0.4);
        if (blocked(u, v) || spots.some(([a, b]) => Math.hypot(a - u, b - v) < gap)) continue;
        spots.push([u, v]);
        artProp(pick(names), u, v);
      }
    }
    const grassy = (u, v, lu = BLOCK, lv = BLOCK) => {
      for (let du = 0; du < lu; du++) for (let dv = 0; dv < lv; dv++) setGround(u + du, v + dv, pick(GRASSES));
    };

    // Houses along a street at `front` (their +v side, where entrances are),
    // in 1.5-wide slots across lu: the diner or a wide house takes two.
    // Returns the backmost house edge; backyards go behind it.
    function houseRow(u0, lu, front, district, diner) {
      const n = Math.floor(lu / 1.5), pad = (lu - n * 1.5) / 2;
      const narrow = HOUSES.filter(h => fp(h)[0] <= 1.3);
      let back = front;
      for (let k = 0; k < n;) {
        const wide = (diner && k === 0) || (k + 1 < n && rng() < (n === 2 ? 0.2 : 0.12));
        const name = wide ? (diner && k === 0 ? 'houses/diner.png' : 'houses/house-4.png') : pick(narrow);
        const [a, b] = fp(name);
        const slot = wide ? 3 : 1.5, su = u0 + pad + k * 1.5;
        const cu = su + slot / 2 + (rng() - 0.5) * Math.max(0, slot - a - 0.2);
        const cv = front - (name === 'houses/diner.png' ? 1.25 : 0.5) - b / 2 - rng() * 0.2;
        artLot(name, cu, cv, district);
        back = Math.min(back, cv - b / 2);
        if (rng() < 0.35 && !wide) {                  // at an outer front corner, inside the lot
          const side = k === 0 ? -1 : k === n - 1 ? 1 : rng() < 0.5 ? -1 : 1;
          const fu = Math.min(Math.max(cu + side * 0.62, su + 0.3), su + slot - 0.3);
          artProp('nature/flowers/flower-bed.png', fu, cv + b / 2 + 0.2);
        }
        k += wide ? 2 : 1;
      }
      return back;
    }
    // Suburb long block: rows of houses every PITCH tiles, each facing its
    // +v street or the backyard strip in front of it.
    function suburbBlock(sb) {
      const lu = sb.u1 - sb.u0, lv = sb.v1 - sb.v0, rows = Math.round((lv + 1) / PITCH);
      grassy(sb.u0, sb.v0, lu, lv);
      for (let r = 0; r < rows; r++) {
        const front = sb.v1 - r * PITCH, top = r === rows - 1 ? sb.v0 : front - PITCH;
        const back = houseRow(sb.u0, lu, front, sb.district, false);
        const count = Math.round((2 + rng() * 3) * lu / BLOCK);
        if (back - top > 0.6) scatter(sb.u0, top, lu, back - top - 0.15, count, [...TREES, ...BUSHES], () => false, 0.55);
      }
    }

    // Suburb square (2×2): houses along the street and a second row facing
    // in, around a shared BBQ area (patio, picnic tables, barbecues) or a
    // playground (sand pad, swings, slide, seesaw, benches), with trees.
    function suburbSquare(sb) {
      const { u0, u1, v0, v1 } = sb, lu = u1 - u0;
      grassy(u0, v0, lu, v1 - v0);
      const back = houseRow(u0, lu, v1, sb.district, false);
      houseRow(u0, lu, v0 + 2.3, sb.district, false);
      const m0 = Math.ceil(v0 + 2.75), m1 = Math.floor(back - 0.15);       // middle, whole tiles
      if (m1 - m0 < 1) return;
      const cu = u0 + lu / 2, cv = (m0 + m1) / 2;
      const bbq = rng() < 0.5;
      for (let u = u0 + 2; u < u1 - 2; u++) for (let v = m0; v < m1; v++) {
        setGround(u, v, bbq ? 'paving' : 'art/ground/sand-b');
      }
      if (bbq) {
        artProp('rec/picnic-table.png', cu - 0.7, cv - 0.35);
        artProp('rec/picnic-table.png', cu + 0.7, cv - 0.35);
        if (m1 - m0 > 1) artProp('rec/picnic-table.png', cu, cv + 0.55);
        artProp('rec/barbecue.png', u0 + 1.5, cv);
        if (rng() < 0.5) artProp('rec/barbecue.png', u1 - 1.5, cv);
      } else {
        artProp('rec/swing-set.png', cu - 0.6, cv - 0.3);
        artProp('rec/slide.png', cu + 0.9, cv - 0.25);
        if (m1 - m0 > 1) artProp('rec/seesaw.png', cu - 0.3, cv + 0.6);
        prop('props/bench-nw.png', u0 + 1.5, cv);
        prop('props/bench-nw.png', u1 - 1.5, cv);
      }
      for (const u of [u0 + 0.55, u1 - 0.55]) artProp(pick(TREES), u, cv + (rng() - 0.5) * 0.8);
    }

    // Civic landmarks first: each district gets at most one of each kind
    // its type allows, on its own (non-merged) cells.
    const free = [...cells.values()].filter(c => c.sup < 0);
    districts.forEach((d, id) => {
      const mine = shuffle(free.filter(c => c.district === id));
      const names = shuffle([...CIVIC[d.type]]).slice(0, Math.max(0, Math.min(CIVIC[d.type].length, Math.floor(mine.length / 8))));
      names.forEach((name, k) => { if (mine[k]) mine[k].civic = `civic/${name}.png`; });
      if (d.type === 'suburb') { const c = mine[names.length]; if (c) c.diner = true; }
      if (d.type === 'plaza') {                         // the most enclosed cell is the square
        const own = c => NB4.filter(([a, b]) => { const o = cellAt(c.i + a, c.j + b); return o && o.district === id; }).length;
        const sq = mine.filter(c => !c.civic).sort((a, b) => own(b) - own(a))[0];
        if (sq) sq.square = true;
      }
    });
    function civicCell(c, u, v, ground) {
      if (ground === 'paving') pave(u, v); else grassy(u, v);
      artLot(c.civic, u + 1.5, v + 1.5, c.district);
      const [a, b] = fp(c.civic);
      const off = (uu, vv) => Math.abs(uu - u - 1.5) < a / 2 + 0.25 && Math.abs(vv - v - 1.5) < b / 2 + 0.25;
      scatter(u, v, 3, 3, ground === 'paving' ? 2 : 4, ground === 'paving' ? ['nature/trees/oak-small.png'] : TREES, off, 0.6);
    }

    // Downtown blocks: the template mix, plus a share of the new buildings.
    const downtownFree = free.filter(c => c.type === 'downtown' && !c.civic);
    const mix = Object.entries(BLOCK_MIX), total = mix.reduce((t, [, w]) => t + w, 0);
    const plan = mix.flatMap(([k, w]) => Array(Math.round(w / total * downtownFree.length)).fill(k));
    while (plan.length < downtownFree.length) plan.push('row');
    shuffle(plan);
    downtownFree.forEach((c, k) => T[plan[k]](roadAt(c.i) + 1, roadAt(c.j) + 1));
    const DOOR = 0.4;                               // clear strip in front of every entrance
    const footprint = lot => {
      if (lot[0].startsWith('art:')) return [lot[1], lot[2], lot[3], lot[4]];
      const b = BUILDINGS[lot[0]], cu = (lot[1] + lot[2]) / 2, cv = (lot[3] + lot[4]) / 2;
      return [cu - b.a / 2, cu + b.a / 2, cv - b.b / 2, cv + b.b / 2];
    };
    const coversDoor = (r, self) => lots.some(o => {  // does rect r cover another building's entrance?
      if (o === self) return false;
      const f = footprint(o), cu = (f[0] + f[1]) / 2, w = Math.min(f[1] - f[0], 0.9);
      return r[0] < cu + w / 2 && r[1] > cu - w / 2 && r[2] < f[3] + DOOR && r[3] > f[3];
    });
    for (const lot of lots) {                       // swap some bare lots for new buildings
      const onStreet = Math.abs((lot[4] - ROAD0) % PITCH) < 0.01;      // front edge on the block's +v road
      if (onStreet && BARE.includes(lot[0]) && lot[2] - lot[1] >= 1.5 && lot[4] - lot[3] >= 1.25 && rng() < 0.35) {
        let name = pick(DOWNTOWN_ART);
        if (name === 'buildings/office-8.png' && rng() < HELIPAD_ODDS) name = 'buildings/office-5.png';
        const [a, b] = fp(name), out = name === 'buildings/brick-4.png' ? CANOPY : 0;
        if (a <= lot[2] - lot[1] + 0.05 && b + out <= lot[4] - lot[3] + 0.05) {
          // At the street edge of its lot (canopy included), leaving the back
          // row's entrances clear.
          const cu = (lot[1] + lot[2]) / 2, front = lot[4] - 0.08 - out;
          const r = [cu - a / 2, cu + a / 2, front - b, front];
          if (!coversDoor(r, lot)) lot.splice(0, 5, 'art:' + name, ...r);
        }
      }
    }

    supers.filter(sb => sb.type === 'suburb').forEach(sb => (sb.kind === 'square' ? suburbSquare : suburbBlock)(sb));
    for (const c of free) {
      const u = roadAt(c.i) + 1, v = roadAt(c.j) + 1;
      if (c.type === 'downtown') { if (c.civic) civicCell(c, u, v, 'paving'); continue; }
      if (c.type === 'suburb') {
        if (c.civic) { civicCell(c, u, v, 'grass'); continue; }
        grassy(u, v);
        const back = houseRow(u, BLOCK, v + BLOCK, c.district, c.diner);
        if (back - v > 0.6) scatter(u, v, 3, back - v - 0.15, 2 + Math.floor(rng() * 3), [...TREES, ...BUSHES], () => false, 0.55);
        continue;
      }
      if (c.type === 'plaza') {
        if (c.civic) { civicCell(c, u, v, 'paving'); continue; }
        pave(u, v);
        if (c.square) {                             // the district's square: fountain, benches, trees
          setGround(u + 1, v + 1, 'pool');
          for (const [cu, cv] of [[0.4, 0.4], [2.6, 0.4], [0.4, 2.6], [2.6, 2.6]]) artProp('nature/trees/oak-small.png', u + cu, v + cv);
          prop('props/bench-ne.png', u + 1.5, v + 0.55);
          prop('props/bench-nw.png', u + 0.55, v + 1.5);
          prop('props/bench-ne.png', u + 1.5, v + 2.5);
          prop('props/bench-nw.png', u + 2.5, v + 1.5);
          prop('lamp-white.png', u + 0.9, v + 0.9);
          prop('lamp-white.png', u + 2.2, v + 2.2);
          continue;
        }
        // One building facing the street, a small square behind it.
        const name = pick(PLAZA_BUILDINGS), [a, b] = fp(name);
        const cv = v + 3 - 0.55 - b / 2;
        artLot(name, u + 1.5 - (name === 'buildings/fastfood.png' ? 0.3 : 0), cv, c.district);
        const yard = cv - b / 2 - 0.3 - v;
        if (yard > 0.5) {
          prop('props/bench-ne.png', u + 1.0, v + yard * 0.5);
          prop(pick(PLANTERS), u + 0.35, v + 0.3);
          prop(pick(PLANTERS), u + 2.65, v + 0.3);
          artProp('nature/trees/oak-small.png', u + 2.1, v + yard * 0.45);
          if (rng() < 0.5) prop('lamp-white.png', u + 1.6, v + 0.25);
        }
        continue;
      }
    }

    // Parks: one region per park district, grass, groves, ponds and a path.
    districts.forEach((d, id) => {
      if (d.type !== 'park') return;
      const tiles = [];
      for (const c of cells.values()) {
        if (c.district !== id) continue;
        for (let u = roadAt(c.i); u <= roadAt(c.i) + BLOCK + 1; u++) for (let v = roadAt(c.j); v <= roadAt(c.j) + BLOCK + 1; v++) {
          if (!isRoad(u, v) && !groundMap.has(key(u, v))) tiles.push([u, v]);
        }
      }
      const inPark = new Set(tiles.map(([u, v]) => key(u, v)));
      for (const [u, v] of tiles) setGround(u, v, rng() < 0.2 ? 'art/ground/grass-flowers' : pick(['art/ground/grass-lush', 'art/ground/grass-a', 'art/ground/grass-b']));
      const water = new Set();
      for (let k = 0, n = 1 + Math.floor(tiles.length / 90); k < n; k++) {
        const [u, v] = pick(tiles);
        if (NB4.every(([a, b]) => inPark.has(key(u + a, v + b)))) { setGround(u, v, rng() < 0.6 ? 'pond' : 'pool'); water.add(key(u, v)); }
      }
      // A dirt path wandering across the park.
      const path = new Set();
      let [pu, pv] = pick(tiles), dir = pick(NB4);
      for (let k = 0; k < tiles.length / 3; k++) {
        if (!water.has(key(pu, pv))) { setGround(pu, pv, 'art/ground/dirt'); path.add(key(pu, pv)); }
        if (rng() < 0.25) dir = pick(NB4);
        if (!inPark.has(key(pu + dir[0], pv + dir[1]))) { dir = pick(NB4); continue; }
        pu += dir[0]; pv += dir[1];
        if (k % 7 === 3) prop(rng() < 0.5 ? 'props/bench-ne.png' : 'props/bench-nw.png', pu + 0.5, pv + 0.2);
      }
      const species = shuffle([...TREES]).slice(0, 3);
      for (const [u, v] of tiles) {
        const k = key(u, v);
        if (water.has(k) || path.has(k)) continue;
        const dense = field(u / 4 + 3, v / 4 + 3);
        const n = rng() < dense * 1.1 ? 1 + Math.floor(rng() * 2 * dense + rng()) : (rng() < 0.12 ? 1 : 0);
        scatter(u, v, 1, 1, n, rng() < 0.85 ? species : BUSHES, () => false, 0.5);
        if (rng() < 0.03) artProp(rng() < 0.5 ? 'nature/rocks/rocks.png' : 'nature/rocks/rocks-small.png', u + rng(), v + rng());
      }
    });

    // Planters along the camera-facing verge.
    for (const k of land) {
      if (core.has(k)) continue;
      const [u, v] = k.split(',').map(Number);
      if ((!inCity(u + 1, v) || !inCity(u, v + 1)) && rng() < 0.3) prop(pick(PLANTERS), u + 0.5, v + 0.5);
    }

    // Waterfront: the city is an island. Sand rings its land, wider and busier
    // on the two camera-facing sides (+u, +v); sea fills the rest of the
    // world. Beach width and busyness follow `front`: 1 where the beach lies
    // +u or +v of the land nearest it, 0 where it lies -u or -v.
    let lighthouse = null;
    {
      const dist = new Map(), from = new Map();     // tiles from the city's land, and which land tile
      let queue = [...land].map(k => k.split(',').map(Number));
      for (const [u, v] of queue) { dist.set(key(u, v), 0); from.set(key(u, v), [u, v]); }
      for (let d = 1; queue.length; d++) {
        const next = [];
        for (const [u, v] of queue) for (const [du, dv] of NB4) {
          const a = u + du, b = v + dv, k = key(a, b);
          if (a < 0 || b < 0 || a >= nu || b >= nv || dist.has(k)) continue;
          dist.set(k, d);
          from.set(k, from.get(key(u, v)));
          next.push([a, b]);
        }
        queue = next;
      }
      const facing = new Map();                     // raw front-ness, smoothed below
      for (const [k, d] of dist) {
        if (!d) continue;
        const [u, v] = k.split(',').map(Number), [su, sv] = from.get(k);
        facing.set(k, Math.max(0, Math.max(u - su, v - sv) / Math.hypot(u - su, v - sv)));
      }
      const front = (u, v) => {                     // averaged over a 7×7 patch, so the width eases round corners
        let t = 0, n = 0;
        for (let a = -3; a <= 3; a++) for (let b = -3; b <= 3; b++) {
          const f = facing.get(key(u + a, v + b));
          if (f !== undefined) { t += f; n++; }
        }
        return n ? t / n : 0;
      };
      let sand = [];
      for (const [k, d] of dist) {
        if (!d) continue;
        const [u, v] = k.split(',').map(Number), f = front(u, v);
        const width = 1.4 + 6.6 * f * f + (field(u / 2.5, v / 2.5) - 0.5) * 2.4;
        if (d === 1 || d <= width) sand.push([u, v, f, d, width]);
        else sea.add(k);
      }
      // Sand only along open water: in a narrow gap between parts of the
      // city, sand farther from the sea than the beach is wide would be an
      // enclosed sandbox, so it becomes grass with a few trees instead.
      const toSea = new Map();
      let edge = sand.filter(([u, v]) => NB4.some(([a, b]) => sea.has(key(u + a, v + b))));
      edge.forEach(([u, v]) => toSea.set(key(u, v), 1));
      const isSand = new Set(sand.map(([u, v]) => key(u, v)));
      for (let d = 2; edge.length; d++) {
        const next = [];
        for (const [u, v] of edge) for (const [a, b] of NB4) {
          const k = key(u + a, v + b);
          if (isSand.has(k) && !toSea.has(k)) { toSea.set(k, d); next.push(k.split(',').map(Number)); }
        }
        edge = next;
      }
      sand = sand.filter(([u, v, , , width]) => {
        if ((toSea.get(key(u, v)) || Infinity) <= Math.max(2, width) + 2) {
          setGround(u, v, rng() < 0.7 ? 'art/ground/sand-a' : 'art/ground/sand-b');
          return true;
        }
        setGround(u, v, pick(GRASSES));
        if (rng() < 0.22) artProp(pick(rng() < 0.6 ? TREES : BUSHES), u + 0.2 + rng() * 0.6, v + 0.2 + rng() * 0.6);
        return false;
      });
      // Grass meeting sand: dune tiles with grass creeping in from the green
      // sides and corners (as for the shoreline below).
      const sandy = new Set(sand.map(([u, v]) => key(u, v)));
      const green = (u, v) => u >= 0 && v >= 0 && u < nu && v < nv && !sandy.has(key(u, v)) && !sea.has(key(u, v));
      const dune = new Set();
      for (const [u, v] of sand) {
        const n = green(u - 1, v), e = green(u, v - 1), so = green(u + 1, v), w = green(u, v + 1);
        const sides = (n ? 'n' : '') + (e ? 'e' : '') + (so ? 's' : '') + (w ? 'w' : '');
        const corners = (!n && !e && green(u - 1, v - 1) ? 'ne' : '') + (!e && !so && green(u + 1, v - 1) ? 'es' : '') +
          (!so && !w && green(u + 1, v + 1) ? 'sw' : '') + (!w && !n && green(u - 1, v + 1) ? 'wn' : '');
        if (!sides && !corners) continue;
        setGround(u, v, `art/ground/dune-${sides}${corners ? '-' + corners : ''}`);
        dune.add(key(u, v));
      }
      // Sea tiles: shoreline autotiles where they touch sand (sides n = -u,
      // e = -v, s = +u, w = +v; corners where only the diagonal is dry).
      const wet = (u, v) => u < 0 || v < 0 || u >= nu || v >= nv || sea.has(key(u, v));
      for (const k of sea) {
        const [u, v] = k.split(',').map(Number);
        const n = !wet(u - 1, v), e = !wet(u, v - 1), so = !wet(u + 1, v), w = !wet(u, v + 1);
        const sides = (n ? 'n' : '') + (e ? 'e' : '') + (so ? 's' : '') + (w ? 'w' : '');
        const corners = (!n && !e && !wet(u - 1, v - 1) ? 'ne' : '') + (!e && !so && !wet(u + 1, v - 1) ? 'es' : '') +
          (!so && !w && !wet(u + 1, v + 1) ? 'sw' : '') + (!w && !n && !wet(u - 1, v + 1) ? 'wn' : '');
        setGround(u, v, sides || corners ? `art/ground/shore-${sides}${corners ? '-' + corners : ''}`
          : rng() < 0.5 ? 'art/ground/water-a' : 'art/ground/water-b');
      }
      // Offshore distance, for buoys and boats.
      const depth = new Map();
      let ring = [...sea].filter(k => { const [u, v] = k.split(',').map(Number); return NB4.some(([a, b]) => !wet(u + a, v + b)); });
      ring.forEach(k => depth.set(k, 1));
      for (let d = 2; ring.length; d++) {
        const next = [];
        for (const k of ring) {
          const [u, v] = k.split(',').map(Number);
          for (const [a, b] of NB4) { const q = key(u + a, v + b); if (sea.has(q) && !depth.has(q)) { depth.set(q, d); next.push(q); } }
        }
        ring = next;
      }

      const taken = new Set();
      const take = (u, v, r = 0) => { for (let a = -r; a <= r; a++) for (let b = -r; b <= r; b++) taken.add(key(u + a, v + b)); };
      const beachProp = (name, u, v, box) => props.push(['art/' + name, u, v, ...(box ? [box] : [])]);
      const shoreline = ([u, v]) => NB4.some(([a, b]) => sea.has(key(u + a, v + b)));
      // Turned versions of a beach sprite: <name>-r1 .. -r3, 90° steps.
      const turned = (name, k) => (k ? name.replace('.png', `-r${k}.png`) : name);
      // Which way the water is from a beach point, and which way open sea is
      // from a sea tile: [du, dv] toward the neighbor nearest the sea / the
      // deepest neighbor. `turnToward` maps a direction to the turn (0-3) that points
      // a sprite drawn toward +u that way (each turn: +u -> +v -> -u -> -v).
      const seaward = (pu, pv) => {             // by how the sea distance slopes, over 2 tiles each way
        const u = Math.floor(pu), v = Math.floor(pv);
        const T = (a, b) => (sea.has(key(a, b)) ? 0 : toSea.get(key(a, b)));
        const t0 = T(u, v) ?? 1;
        let gu = 0, gv = 0;
        for (let r = 1; r <= 2; r++) {
          gu += (T(u - r, v) ?? t0 + r) - (T(u + r, v) ?? t0 + r);
          gv += (T(u, v - r) ?? t0 + r) - (T(u, v + r) ?? t0 + r);
        }
        if (Math.abs(gu) > 1.25 * Math.abs(gv)) return [Math.sign(gu), 0];
        if (Math.abs(gv) > 1.25 * Math.abs(gu)) return [0, Math.sign(gv)];
        return rng() < 0.5 ? [Math.sign(gu) || 1, 0] : [0, Math.sign(gv) || 1];   // a diagonal coast: either
      };
      const offshore = (u, v) => {
        let best = [0, 1], d = -1;
        for (const [a, b] of NB4) {
          const n = depth.get(key(u + a, v + b)) ?? -1;
          if (n > d) [d, best] = [n, [a, b]];
        }
        return best;
      };
      const turnToward = ([a, b]) => (a > 0 ? 0 : b > 0 ? 1 : a < 0 ? 2 : 3);
      // The lighthouse: on the front shore tile lowest on screen.
      const tip = sand.filter(t => t[2] > 0.5 && shoreline(t)).sort((a, b) => b[0] + b[1] - a[0] - a[1])[0];
      if (tip) {
        const [u, v] = tip;
        lighthouse = [u + 0.5, v + 0.5];
        artLot('landmarks/lighthouse.png', u + 0.5, v + 0.5, 0);
        take(u, v, 1);
        beachProp('nature/rocks/rocks.png', u + 0.2, v + 1.4);
        beachProp('nature/rocks/rocks-small.png', u + 1.3, v + 0.3);
      }
      // Piers straight out to sea from the front beach, a rowboat alongside.
      const piers = [];
      for (const [u, v, f] of shuffle(sand.filter(t => t[2] > 0.6 && shoreline(t)))) {
        if (piers.length >= 3 || taken.has(key(u, v)) || piers.some(([a, b]) => Math.abs(a - u) + Math.abs(b - v) < 14)) continue;
        for (const [du, dv, name] of [[1, 0, 'beach/pier.png'], [0, 1, 'beach/pier-v.png']]) {
          if (![1, 2, 3, 4, 5].every(k => sea.has(key(u + du * k, v + dv * k)) &&
            sea.has(key(u + du * k + dv, v + dv * k + du)) && sea.has(key(u + du * k - dv, v + dv * k - du)))) continue;
          for (let k = 0; k < 4; k++) {
            // Sections from their origin corner: along u they span v + [0, 0.38],
            // along v (turned) u - [0.38, 0].
            const pu = du ? u + 0.7 + k : u + 0.69, pv = dv ? v + 0.7 + k : v + 0.31;
            take(u + du * (k + 1), v + dv * (k + 1), 1);
            beachProp(name, pu, pv, du ? [pu, pu + 1, pv, pv + 0.38] : [pu - 0.38, pu, pv, pv + 1]);
          }
          beachProp(turned('beach/rowboat.png', (du ? 0 : 1) + 2 * (rng() < 0.5)),        // moored alongside
            u + du * 3.2 + dv * 0.9, v + dv * 3.2 + du * 0.9);
          piers.push([u, v]);
          take(u, v, 1);
          break;
        }
      }
      // Beach life: busy in front, sparse at the back.
      let guard = [];
      for (const [u, v, f, d] of shuffle(sand)) {
        if (taken.has(key(u, v))) continue;
        const cu = u + 0.3 + rng() * 0.4, cv = v + 0.3 + rng() * 0.4;
        if (f < 0.45) {
          const r = rng();
          if (r < 0.05) beachProp(pick(['nature/rocks/rocks.png', 'nature/rocks/rocks-small.png']), cu, cv);
          else if (r < 0.08) beachProp(pick(['nature/trees/palm-small.png', 'nature/trees/pine-small.png']), cu, cv);
          else continue;
          take(u, v);
          continue;
        }
        const r = rng();
        if (shoreline([u, v]) && r < 0.08 && !guard.some(([a, b]) => Math.abs(a - u) + Math.abs(b - v) < 12)) {
          // Facing the sea: the sprite faces +v, turned ones -u, -v, +u.
          const k = sea.has(key(u, v + 1)) ? 0 : sea.has(key(u - 1, v)) ? 1 : sea.has(key(u, v - 1)) ? 2 : 3;
          beachProp(turned('beach/lifeguard-tower.png', k), u + 0.5, v + 0.5);
          guard.push([u, v]);
          take(u, v, 1);
        } else if (d <= 2 && r < 0.12) {
          beachProp(pick(['nature/trees/palm.png', 'nature/trees/palm-small.png']), cu, cv);
          take(u, v);
        } else if (d <= 2 && r < 0.16) {
          beachProp(pick(['beach/hut-teal.png', 'beach/hut-red.png']), u + 0.5, v + 0.5);
          if (rng() < 0.6) beachProp('beach/barrel.png', u + 0.95, v + 0.2);
          take(u, v, 1);
        } else if (d > 1 && r < 0.1 + 0.22 * f) {            // umbrella with a lounger or a towel
          const au = u + 0.15 + rng() * 0.35, av = v + 0.15 + rng() * 0.35;
          beachProp(pick(['beach/umbrella-red.png', 'beach/umbrella-teal.png', 'beach/umbrella-gold.png']), au, av);
          // Loungers put their feet toward the water, towels lie toward it.
          const seat = pick(['beach/lounger-teal.png', 'beach/lounger-red.png', 'beach/towel-purple.png', 'beach/towel-teal.png']);
          const su = au + 0.28 + rng() * 0.12, sv = av + 0.22 + rng() * 0.12, k = turnToward(seaward(su, sv));
          beachProp(turned(seat, seat.includes('towel') ? k % 2 : k), su, sv);
          take(u, v);
        } else if (d > 1 && r < 0.14 + 0.28 * f) {           // just a towel
          beachProp(turned(pick(['beach/towel-purple.png', 'beach/towel-teal.png']), turnToward(seaward(cu, cv)) % 2), cu, cv);
          take(u, v);
        }
      }
      // Low dune plants: thick along the grass edge, thinning toward the sea.
      const DUNE_PLANTS = ['marram', 'marram', 'marram-b', 'morning-glory', 'morning-glory', 'sea-daisy']
        .map(n => `nature/dune/${n}.png`);
      for (const [u, v, , d] of sand) {
        if (taken.has(key(u, v))) continue;
        const chance = dune.has(key(u, v)) ? 0.7 : d === 2 ? 0.3 : d === 3 ? 0.1 : 0.03;
        for (let n = 0; n < 2 && rng() < chance; n++) beachProp(pick(DUNE_PLANTS), u + 0.15 + rng() * 0.7, v + 0.15 + rng() * 0.7);
      }
      // Buoys marking the swimming area, and a few boats off the front
      // beach pointing out to sea (moored ones lie along their pier).
      let boats = 0;
      for (const k of shuffle([...sea])) {
        const [u, v] = k.split(',').map(Number), d = depth.get(k), f = front(u, v);
        if (f < 0.5 || taken.has(k)) continue;
        if (d === 3 && rng() < 0.22) beachProp('beach/buoy.png', u + 0.5, v + 0.5);
        else if (d >= 4 && d <= 6 && boats < LOOSE_BOATS && rng() < 0.0025) {
          beachProp(turned('beach/rowboat.png', turnToward(offshore(u, v)) % 2 + 2 * (rng() < 0.5)), u + 0.5, v + 0.5);
          take(u, v, 2);
          boats++;
        }
      }
    }

    // Entrances: every building's door is on its +v front. Keep a clear
    // DOOR-deep strip in front of it, and (new sprites) any part drawn
    // outside the footprint, free of props; count buildings that
    // intrude on another's entrance (tools/sim.js fails on any).
    const EXTRA = {                                  // sprite ground beyond the footprint: [-u, +u, -v, +v]
      'buildings/brick-4.png': [0, 0, 0, CANOPY], 'houses/diner.png': [0, 0.18, 0, 0],
      'buildings/fastfood.png': [0, 0.34, 0, 0], 'buildings/apartment-2.png': [0, 0.22, 0, 0.3],
      'civic/church.png': [0.04, 0.04, 0, 0.36], 'civic/bank.png': [0, 0, 0, 0.36],
    };
    const keepouts = [], doors = [];
    for (const lot of lots) {
      const f = footprint(lot), cu = (f[0] + f[1]) / 2, w = Math.min(f[1] - f[0], 0.9);
      const name = lot[0].slice(4), x = EXTRA[name] || [0, 0, 0, 0];
      const door = [cu - w / 2, cu + w / 2, f[3] + (x[3] > 0.2 ? x[3] : 0), f[3] + Math.max(x[3], 0) + DOOR];
      doors.push([lot, door]);
      keepouts.push(door);
      if (lot[0].startsWith('art:')) keepouts.push([f[0] - x[0], f[1] + x[1], f[2] - x[2], f[3] + x[3]]);
    }
    const inside = (r, u, v) => u > r[0] && u < r[1] && v > r[2] && v < r[3];
    for (let k = props.length - 1; k >= 0; k--) {
      if (keepouts.some(r => inside(r, props[k][1], props[k][2]))) props.splice(k, 1);
    }
    const blocked = [];
    for (const [lot, d] of doors) {
      for (const other of lots) {
        if (other === lot) continue;
        const f = footprint(other);
        if (f[0] < d[1] - 0.01 && f[1] > d[0] + 0.01 && f[2] < d[3] - 0.01 && f[3] > d[2] + 0.01) { blocked.push([lot, other]); break; }
      }
    }
    const blockedDoors = blocked.length;

    const nearSignal = (u, v) => NB4.some(([du, dv]) => signalAt.has(key(u + du, v + dv)));

    function ground(u, v) {
      if (isRoad(u, v)) {
        let k = '';
        if (isRoad(u - 1, v)) k += 'n';
        if (isRoad(u, v - 1)) k += 'e';
        if (isRoad(u + 1, v)) k += 's';
        if (isRoad(u, v + 1)) k += 'w';
        if ((k === 'ns' || k === 'ew') && nearSignal(u, v)) k += 'x';
        return ROAD_TILES[k];
      }
      if (!isLand(u, v)) return null;
      return groundMap.get(key(u, v)) || ['grass', 0];
    }

    // Traffic loops: random rectangles on the road lattice, either direction.
    const loopOk = loop => tilesAlong([...loop, loop[0]]).every(([u, v]) => isRoad(u, v));
    const routes = [];
    const routeCount = Math.round(cells.size / CELLS_PER_ROUTE);
    for (let tries = 0; routes.length < routeCount && tries < 20000; tries++) {
      const i0 = Math.floor(rng() * IU), j0 = Math.floor(rng() * IV);
      const i1 = Math.min(IU, i0 + 1 + Math.floor(rng() * 4));
      const j1 = Math.min(IV, j0 + 1 + Math.floor(rng() * 4));
      const loop = [[i0, j0], [i1, j0], [i1, j1], [i0, j1]];
      if (loopOk(loop)) routes.push(rng() < 0.5 ? loop : loop.reverse());
    }

    const toTiles = r => r.map(([i, j]) => [roadAt(i), roadAt(j)]);
    return {
      ground, isRoad, isLand, isWater, lighthouse, parking, junction, lots, props, signals, signalAt, rng, pick,
      routes: routes.map(toTiles), NU: nu, NV: nv, IU, IV, cells: cells.size,
      districts: districts.map(d => d.type), blockedDoors, blocked,
      cellList: [...cells.values()].map(c => [c.i, c.j, c.type, c.sup >= 0]),
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

  // Hero route: pulls out from the curb at `start` (or follows `lead`, a
  // way out ending in the lane at `start`), follows the right-hand lane
  // through `corners`, and pulls in to the curb at `end`.
  function routeLane(start, corners, end, lead = null) {
    const pts = centers([start, ...corners, end]), n = pts.length, out = [];
    const dirs = pts.slice(0, -1).map((p, i) => unit(p, pts[i + 1]));
    const at = (p, d, side, along) => {
      const r = right(d);
      return [p[0] + d[0] * along + r[0] * side, p[1] + d[1] * along + r[1] * side];
    };
    const ease = t => t * t * (3 - 2 * t);
    const K = 8;
    if (lead) out.push(...lead);
    else for (let k = 0; k <= K; k++) out.push(at(pts[0], dirs[0], CURB + (LANE - CURB) * ease(k / K), PULL * k / K));
    for (let i = 1; i < n - 1; i++) fillet(out, pts[i], dirs[i - 1], dirs[i]);
    const dl = dirs[n - 2];
    for (let k = 0; k <= K; k++) out.push(at(pts[n - 1], dl, LANE + (CURB - LANE) * ease(k / K), -PULL * (1 - k / K)));
    return out;
  }

  function buildPath(raw, signalAt, ground, half = CAR_HALF, closed = true, junction = () => false) {
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
    // Samples inside a junction (for "don't block the box").
    const box = Uint8Array.from(samples, p => (junction(Math.floor(p[0]), Math.floor(p[1])) ? 1 : 0));
    return { samples, heads, stops, total: pathLen, step: STEP, closed, box };
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

  /* ---------- loading screen ---------- */

  // 4×7 pixel letters for the loading text.
  const FONT = {
    L: ['1000', '1000', '1000', '1000', '1000', '1000', '1111'],
    O: ['0110', '1001', '1001', '1001', '1001', '1001', '0110'],
    A: ['0110', '1001', '1001', '1111', '1001', '1001', '1001'],
    D: ['1110', '1001', '1001', '1001', '1001', '1001', '1110'],
    I: ['111', '010', '010', '010', '010', '010', '111'],
    N: ['10001', '11001', '11001', '10101', '10011', '10011', '10001'],
    G: ['0111', '1000', '1000', '1011', '1001', '1001', '0111'],
  };
  const textWidth = t => [...t].reduce((w, ch) => w + FONT[ch][0].length + 1, -1);

  // Overlay shown while the city is built: the hero Supra spinning in the
  // middle with "LOADING" and animated dots. Returns { finish } to fade it
  // out; ?loading in the URL keeps it up.
  function showLoading(root, base, zoom) {
    const el = document.createElement('div');
    el.className = 'pixel-city__loading';
    el.setAttribute('role', 'status');
    el.innerHTML = '<span class="pixel-city__sr">Loading city…</span>';
    const c = document.createElement('canvas');
    c.setAttribute('aria-hidden', 'true');
    el.appendChild(c);
    root.appendChild(el);
    const g = c.getContext('2d');
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const t0 = performance.now();
    let car = null, done = false, k = 1;
    const size = () => {
      const dpr = window.devicePixelRatio || 1;
      c.width = Math.max(1, Math.floor(root.clientWidth * dpr));
      c.height = Math.max(1, Math.floor(root.clientHeight * dpr));
      k = Math.max(1, Math.round(zoom * dpr));
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(root);
    const hd = k % HD === 0;
    load(base, `vehicles/${HERO_TYPE}/iso${hd ? `@${HD}x` : ''}.png`).then(im => { car = im; }, () => {});
    function draw(now) {
      if (done) return;
      const t = (now - t0) / 1000;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, c.width, c.height);
      g.imageSmoothingEnabled = false;
      const cx = Math.round(c.width / 2), cy = Math.round(c.height / 2);
      const [cw, ch] = HERO_CELL, a = hd ? HD : 1;
      if (car) {
        const f = still ? 1 : Math.floor(t * 9) % 12;                // frames step 30° around
        g.fillStyle = 'rgba(0, 0, 0, 0.35)';                          // ground shadow
        g.beginPath();
        g.ellipse(cx, cy + 6 * k, 30 * k, 9 * k, 0, 0, Math.PI * 2);
        g.fill();
        const [px, py] = HERO_PIVOT[f];                               // per-frame ground point
        g.drawImage(car, f * cw * a, 0, cw * a, ch * a, cx - px * k, cy + 4 * k - py * k, cw * k, ch * k);
      }
      const word = 'LOADING', w = textWidth(word);
      const dots = still ? 3 : Math.floor(t / 0.35) % 4;
      let x = cx - Math.round((w + 7) / 2) * k;
      const y = cy + 24 * k;
      g.fillStyle = '#d8d0c2';
      for (const ch of word) {
        FONT[ch].forEach((row, r) => [...row].forEach((bit, q) => {
          if (bit === '1') g.fillRect(x + q * k, y + r * k, k, k);
        }));
        x += (FONT[ch][0].length + 1) * k;
      }
      for (let d = 0; d < dots; d++) g.fillRect(x + d * 2 * k, y + 6 * k, k, k);
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
    const hold = new URLSearchParams(location.search).has('loading');
    return {
      // Fade out once shown for at least 0.8 s.
      async finish() {
        if (hold) return;
        const wait = 800 - (performance.now() - t0);
        if (wait > 0) await new Promise(r => setTimeout(r, wait));
        el.classList.add('pixel-city__loading--done');
        el.addEventListener('transitionend', () => { done = true; ro.disconnect(); el.remove(); }, { once: true });
        setTimeout(() => { if (!done) { done = true; ro.disconnect(); el.remove(); } }, 1000);
      },
    };
  }

  const nextFrame = () => new Promise(r => requestAnimationFrame(() => r()));

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
  // Soil edge under a land tile's camera-facing sides that border the void
  // (sw: its +v side, se: its +u side), clipped to [xMin, xMax).
  function drawSlab(ctx, u, v, sw, se, xMin = -Infinity, xMax = Infinity, wet = false) {
    const [tx, ty] = iso(u, v);
    const side = (x0, x1, y0, slope, fill, lip) => {
      for (let x = Math.max(x0, Math.floor(xMin)); x < Math.min(x1, Math.ceil(xMax)); x++) {
        const y = Math.round(y0 + (x - x0) * slope);
        ctx.fillStyle = lip;
        ctx.fillRect(x, y, 1, 2);
        ctx.fillStyle = fill;
        ctx.fillRect(x, y + 2, 1, SLAB - 2);
      }
    };
    if (sw) side(tx - HW, tx, ty + HH, 0.5, wet ? '#1d5663' : '#5b4a31', wet ? '#3e92a2' : '#4d5a1f');
    if (se) side(tx, tx + HW, ty + TH, -0.5, wet ? '#174651' : '#46382a', wet ? '#2f8191' : '#3f4a1a');
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

  // Two cars whose footprints overlap: order them along the axis where they
  // overlap least (side by side → across the road, nose to tail → along it).
  function carBefore(a, b) {
    const ou = Math.min(a.box[1], b.box[1]) - Math.max(a.box[0], b.box[0]);
    const ov = Math.min(a.box[3], b.box[3]) - Math.max(a.box[2], b.box[2]);
    if (ou <= 0 || ov <= 0) return drawsBefore(a, b);
    return ou < ov ? a.pos[0] < b.pos[0] : a.pos[1] < b.pos[1];
  }

  // Topological sort over neighboring pairs only; returns the drawing order.
  function paintOrder(items, neighbors, before) {
    const after = items.map(() => []), deg = new Array(items.length).fill(0);
    items.forEach((a, i) => { a.index = i; });
    for (const a of items) {
      for (const b of neighbors(a)) {
        if (b.index <= a.index || items[b.index] !== b) continue;
        const [f, s] = before(a, b) ? [a, b] : [b, a];
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
    return order;
  }

  /* ---------- mount ---------- */

  /* ---------- hero routes ---------- */

  // Hero routes over the road grid. `planRoute(spot)` returns { path, end }
  // from a parking spot to a new random one.
  function heroPlanner(city) {
  const nodeTile = ([i, j]) => [roadAt(i), roadAt(j)];
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const edgeOk = (a, b) => {
    if (b[0] < 0 || b[1] < 0 || b[0] > city.IU || b[1] > city.IV) return false;
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
    return { path: buildPath(routeLane(from.tile, corners, end.tile, from.lead), city.signalAt, city.ground, HERO_HALF, false,
      city.junction), end };
  }
  const firstSpot = (() => {
    for (let tries = 0; tries < 500; tries++) {
      const a = [Math.floor(city.rng() * (city.IU + 1)), Math.floor(city.rng() * (city.IV + 1))];
      const o = city.pick(DIRS), b = [a[0] + o[0], a[1] + o[1]];
      if (edgeOk(a, b)) return spotOn(a, b);
    }
  })();
    // The first route leaves the parking lot, if the city has one.
    const start = city.parking && edgeOk(city.parking.behind, city.parking.ahead)
      ? { ...spotOn(city.parking.behind, city.parking.ahead), lead: city.parking.lead } : firstSpot;
    return { planRoute, firstSpot: start };
  }

  async function mount(root) {
    const base = root.dataset.assets || 'assets/';
    const zoom = Math.max(1, Number(root.dataset.zoom || 1));
    const loading = showLoading(root, base, zoom);
    // Startup runs in phases with a frame between each, so the loading
    // animation keeps moving. ?debug logs how long each phase took.
    const debug = new URLSearchParams(location.search).has('debug');
    let mark = performance.now();
    const phase = async name => {
      if (debug) console.log(`pixel-city: ${name} ${(performance.now() - mark).toFixed(0)} ms`);
      await nextFrame();
      mark = performance.now();
    };

    // Sprites drawn by tools/art.py, described by their manifest.
    const art = await fetch(base + 'art/manifest.json').then(r => (r.ok ? r.json() : {}), () => ({}));
    const srcs = new Set([
      ...Object.keys(art).map(k => 'art/' + k),
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
    await phase('images');
    // A new city on every load, unless data-seed pins one.
    const urlSeed = new URLSearchParams(location.search).get('seed');
    const seed = root.dataset.seed ? Number(root.dataset.seed)
      : urlSeed ? Number(urlSeed) : Math.floor(Math.random() * 2 ** 31);
    const city = generate(mulberry32(seed), art);
    setWorld(city.NU, city.NV);
    if (debug) console.log(`pixel-city: seed ${seed}, ${city.cells} cells, ${city.NU}×${city.NV} tiles`);
    await phase('generate');

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

    // Tiles whose diamond (and slab) overlaps a screen rect, back to front.
    function forTiles([x, y, w, h], fn) {
      const uv = (px, py) => [((px - OX) / HW + (py - TOP) / HH) / 2, ((py - TOP) / HH - (px - OX) / HW) / 2];
      const pts = [uv(x, y), uv(x + w, y), uv(x, y + h), uv(x + w, y + h)];
      const u0 = Math.max(0, Math.floor(Math.min(...pts.map(p => p[0]))) - 1);
      const u1 = Math.min(NU - 1, Math.ceil(Math.max(...pts.map(p => p[0]))) + 1);
      const v0 = Math.max(0, Math.floor(Math.min(...pts.map(p => p[1]))) - 1);
      const v1 = Math.min(NV - 1, Math.ceil(Math.max(...pts.map(p => p[1]))) + 1);
      for (let d = u0 + v0; d <= u1 + v1; d++) {
        for (let u = Math.max(u0, d - v1); u <= Math.min(u1, d - v0); u++) {
          const v = d - u;
          const [tx, ty] = iso(u, v);
          if (tx + HW + 1 < x || tx - HW - 1 > x + w || ty + TH + SLAB + 1 < y || ty > y + h) continue;
          fn(u, v);
        }
      }
    }
    function drawGround(g, rect) {
      forTiles(rect, (u, v) => {
        const gr = city.ground(u, v);
        if (!gr) return;
        const sw = !city.isLand(u, v + 1), se = !city.isLand(u + 1, v);
        if (sw || se) drawSlab(g, u, v, sw, se, rect[0], rect[0] + rect[2], city.isWater(u, v));
        drawTile(g, img[gr[0].startsWith('art/') ? gr[0] + '.png' : `tiles/${gr[0]}.png`], u, v, gr[1]);
      });
    }

    // Moving water, drawn every frame between a chunk's ground and its
    // sprites: waves rolling onto every shore tile (their phase drifts slowly
    // along the coast, so neighbors mostly agree) and glints on open water.
    const WAVE_S = 3.2, ANIM_FPS = 8;
    function drawWaves(g, rect) {
      const t = clock / WAVE_S;
      forTiles(rect, (u, v) => {
        if (!city.isWater(u, v)) return;
        const name = city.ground(u, v)[0], [x, y] = iso(u, v);
        let atlas, f;
        if (name.startsWith('art/ground/shore-')) {
          atlas = img['art/ground/foam-' + name.slice(17) + '.png'];
          const frames = atlas ? atlas.width / 128 : 1;     // frames side by side in the atlas
          f = Math.floor((t + (u + v) * 0.012) * frames) % frames;
        } else {
          const h = ((u * 73856093) ^ (v * 19349663)) >>> 0;          // each tile glints now and then
          f = Math.floor(t * 5 + (h % 97)) % 40;
          if (f >= 4) return;
          atlas = img['art/ground/glints.png'];
        }
        if (atlas) g.drawImage(atlas, f * 128, 0, 128, atlas.height, x - HW, y, 128, atlas.height);
      });
    }

    await phase('ground');

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
      const cu = (u0 + u1) / 2, cv = (v0 + v1) / 2;
      if (kind.startsWith('art:')) {                     // anchored at the footprint center
        const name = kind.slice(4), m = art[name], [a, b] = m.footprint || [1, 1];
        const [x, y] = iso(cu, cv);
        addStatic(() => img['art/' + name], x - m.anchor[0], y - m.anchor[1],
          [cu - a / 2, cu + a / 2, cv - b / 2, cv + b / 2]);
        continue;
      }
      const b = BUILDINGS[kind];
      const [x, y] = iso(cu + b.a / 2, cv + b.b / 2);
      addStatic(() => img[b.src], x - b.base[0], y - b.base[1],
        [cu - b.a / 2, cu + b.a / 2, cv - b.b / 2, cv + b.b / 2]);
    }
    // Animated sprites (a manifest `frames` count, frames side by side) are
    // drawn every frame instead of baked; see render().
    const animated = [], gates = [];
    for (const [src, u, v, box] of city.props) {
      const m = src.startsWith('art/') ? art[src.slice(4)] : null;
      const [ax, ay] = m ? m.anchor : PROP_ANCHORS[src];
      const [x, y] = iso(u, v);
      if (m && m.frames > 1) {
        const [a, b] = m.footprint || [0.1, 0.1], [w, h] = m.size;
        const item = { src, frames: m.frames, rect: [Math.round(x - ax), Math.round(y - ay), w, h],
          box: [u - a / 2, u + a / 2, v - b / 2, v + b / 2] };
        if (src.includes('parking/gate')) {            // raised as the hero comes near: open 0..1
          Object.assign(item, { pos: [u, v], open: 0 });
          item.frameOf = () => Math.round(item.open * (item.frames - 1));
          gates.push(item);
        }
        animated.push(item);
        continue;
      }
      addStatic(() => img[src], x - ax, y - ay, box || pointBox(u, v));
    }
    // Cars parked in the lot: the car sprite's first wheel frame, baked.
    for (const pc of city.parking ? city.parking.cars : []) {
      const f = frameFor(pc.head[0], pc.head[1]), [x, y] = iso(pc.u, pc.v);
      const px = Math.round(x), py = Math.round(y), [cw, ch] = CAR_CELL;
      const rx = px - CAR_PIVOT[0], ry = py - CAR_PIVOT[1];
      const [hu, hv] = pc.head.map(Math.abs);
      const du = hu * CAR_HALF + hv * CAR_HALF_W, dv = hv * CAR_HALF + hu * CAR_HALF_W;
      statics.push({ box: [pc.u - du, pc.u + du, pc.v - dv, pc.v + dv], rect: [rx, ry, cw, ch + 4], draw: c => {
        c.fillStyle = 'rgba(20, 22, 30, .28)';
        c.fillRect(px - 13, py - 1, 26, 3);
        c.fillRect(px - 9, py - 3, 18, 7);
        c.drawImage(img[`vehicles/${pc.type}/iso.png`], f * cw, 0, cw, ch, rx, ry, cw, ch);
        c.drawImage(img[`vehicles/${pc.type}/wheels.png`], f * cw, 0, cw, ch, rx, ry, cw, ch);
      } });
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
    paintOrder(statics, a => hash.query(a.rect), drawsBefore).forEach((it, i) => { it.order = i; });
    await phase('statics');

    // The baked scene (ground + static sprites) lives in CHUNK_W × CHUNK_H
    // chunks, drawn when first needed and kept in a small LRU cache; a traffic
    // light change repaints just its rect in the chunks already drawn.
    // The cache holds at least CHUNK_CAP chunks, and always the visible ones
    // plus the ring around them, so prebaking a neighbor never evicts another.
    const CHUNK_W = 1024, CHUNK_H = 512, CHUNK_CAP = 24;
    let chunkCap = CHUNK_CAP;
    const chunks = new Map();
    let chunkTick = 0;
    // A chunk that shows water bakes its ground and its sprites apart, so
    // the waves can go between them; any other bakes both together.
    function paintRegion(g, rect, ground = true, sprites = true) {
      g.save();
      g.beginPath();
      g.rect(...rect);
      g.clip();
      g.clearRect(...rect);
      if (ground) drawGround(g, rect);
      if (sprites) [...hash.query(rect)].sort(byOrder).forEach(st => st.draw(g));
      g.restore();
    }
    const layer = (i, j) => {
      const cv = document.createElement('canvas');
      cv.width = CHUNK_W;
      cv.height = CHUNK_H;
      const g = cv.getContext('2d');
      g.imageSmoothingEnabled = false;
      g.translate(-i * CHUNK_W, -j * CHUNK_H);
      return { canvas: cv, g };
    };
    function chunk(i, j) {
      const key = i + ',' + j;
      let c = chunks.get(key);
      if (!c) {
        const t0 = performance.now(), rect = [i * CHUNK_W, j * CHUNK_H, CHUNK_W, CHUNK_H];
        let wet = false;
        forTiles(rect, (u, v) => { wet = wet || city.isWater(u, v); });
        c = { ...layer(i, j), i, j, wet };
        if (wet && hash.query(rect).size) c.top = layer(i, j);
        paintRegion(c.g, rect, true, !wet);
        if (c.top) paintRegion(c.top.g, rect, false, true);
        chunks.set(key, c);
        if (debug) console.log(`pixel-city: chunk ${key} ${(performance.now() - t0).toFixed(1)} ms, ${chunks.size} cached`);
        if (chunks.size > chunkCap) {                      // drop the least recently used
          let old = null;
          for (const o of chunks.values()) if (o !== c && (!old || o.used < old.used)) old = o;
          chunks.delete(old.i + ',' + old.j);
        }
      }
      c.used = chunkTick;
      return c;
    }
    const chunkRange = ([x, y, w, h]) => [
      Math.floor(x / CHUNK_W), Math.floor((x + w - 1) / CHUNK_W),
      Math.floor(y / CHUNK_H), Math.floor((y + h - 1) / CHUNK_H)];
    function rebake(rect) {
      const [i0, i1, j0, j1] = chunkRange(rect);
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
        const c = chunks.get(i + ',' + j);
        if (!c) continue;
        paintRegion(c.g, rect, true, !c.wet);
        if (c.top) paintRegion(c.top.g, rect, false, true);
      }
    }
    // Draw the visible chunks (baking any missing), then bake at most one
    // neighbor ahead of time so panning into it doesn't stall.
    function drawScene(g, rect) {
      chunkTick++;
      const [i0, i1, j0, j1] = chunkRange(rect);
      chunkCap = Math.max(CHUNK_CAP, (i1 - i0 + 3) * (j1 - j0 + 3));
      const shown = [];
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
        const c = chunk(i, j);
        g.drawImage(c.canvas, i * CHUNK_W, j * CHUNK_H);
        shown.push(c);
      }
      if (shown.some(c => c.wet)) {
        drawWaves(g, rect);
        for (const c of shown) if (c.top) g.drawImage(c.top.canvas, c.i * CHUNK_W, c.j * CHUNK_H);
      }
      for (let i = i0 - 1; i <= i1 + 1; i++) for (let j = j0 - 1; j <= j1 + 1; j++) {
        if (!chunks.has(i + ',' + j) && i >= 0 && j >= 0 && i * CHUNK_W < W && j * CHUNK_H < H) {
          chunk(i, j);
          return;
        }
      }
    }

    // Cars: the hero drives planned routes; the others loop.
    const { planRoute, firstSpot } = heroPlanner(city);
    let heroRoute = planRoute(firstSpot);
    const heroPath = heroRoute.path;

    const bumpState = () => ({ bumps: [], nextBump: Math.random() * BUMP_EVERY[1] });
    // Starting in the parking lot, the hero waits a moment in its stall.
    const hero = { id: 0, type: HERO_TYPE, path: heroPath, s: 0, speed: 0, roll: 0, ...bumpState(), parked: 0,
      hold: firstSpot.lead ? PARK_S + 3 : 0,
      pos: heroPath.samples[0], head: heroPath.heads[0], box: null, hero: true };
    const cars = [hero];
    for (const path of city.routes.map(r => buildPath(loopLane(r), city.signalAt, city.ground, CAR_HALF, true, city.junction))) {
      const count = Math.max(1, Math.round(path.total / TILES_PER_CAR));
      for (let c = 0; c < count; c++) {
        for (let tries = 0; tries < 20; tries++) {
          const s = city.rng() * path.total;
          const i = Math.floor(s / path.step);
          const pos = path.samples[i];
          if (cars.some(o => Math.hypot(o.pos[0] - pos[0], o.pos[1] - pos[1]) < 1.2)) continue;
          cars.push({ id: cars.length, type: city.pick(TYPES), path, s, speed: CRUISE, roll: 0, ...bumpState(),
            pos, head: path.heads[i], box: null });
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

    // Distance to `o` if it sits on `car`'s path within 1.5 tiles, else -1.
    const aheadOf = (car, o) => {
      const du = o.pos[0] - car.pos[0], dv = o.pos[1] - car.pos[1];
      if (Math.abs(du) > 1.6 || Math.abs(dv) > 1.6) return -1;
      if (du * car.head[0] + dv * car.head[1] <= 0) return -1;
      for (let d = 0.1; d <= 1.5; d += 0.1) {
        const p = pointAhead(car, d);
        if (Math.hypot(p[0] - o.pos[0], p[1] - o.pos[1]) <= 0.22) return d;
      }
      return -1;
    };

    // True if the cars `car` would wait on (starting with `first`) lead back
    // to it, and `car` is the one to go so the loop can't deadlock: the
    // lowest id among the cars that are only yielding right of way (`kind`
    // 'yield'), never one held by a car physically in its path ('body'),
    // unless every car in the loop is.
    function breaksLoop(car, first, kind) {
      const loop = [[car, kind]];
      for (let c = first, i = 0; c && i < 64; c = c.blocker, i++) {
        if (c === car) {
          const yielding = loop.filter(([, k]) => k === 'yield');
          const pool = yielding.length ? yielding : loop;
          return pool.some(([c2]) => c2 === car) && car.id === Math.min(...pool.map(([c2]) => c2.id));
        }
        loop.push([c, c.blockKind]);
      }
      return false;
    }

    const halfL = c => c.hero ? HERO_HALF : CAR_HALF;
    const halfW = c => c.hero ? HERO_HALF_W : CAR_HALF_W;

    // Seconds to cover `d` tiles from speed `v`, accelerating up to CRUISE.
    function arriveTime(v, d) {
      if (d <= 0) return 0;
      const dAcc = (CRUISE * CRUISE - v * v) / (2 * ACCEL);
      if (d <= dAcc) return (Math.sqrt(v * v + 2 * ACCEL * d) - v) / ACCEL;
      return (CRUISE - v) / ACCEL + (d - dAcc) / CRUISE;
    }

    // Sample index / point / heading on the car's path `d` tiles ahead.
    function indexAhead(car, d) {
      const p = car.path, n = p.samples.length;
      const i = Math.floor((car.s + d) / p.step);
      return p.closed ? ((i % n) + n) % n : Math.max(0, Math.min(n - 1, i));
    }
    const pointAhead = (car, d) => car.path.samples[indexAhead(car, d)];
    const headAhead = (car, d) => car.path.heads[indexAhead(car, d)];

    // Who goes first at each conflict between two cars' paths, decided once
    // when the conflict appears and kept until it's gone, so priority can't
    // flip while both are slowing down. A car goes first if it can clear the
    // conflict CROSS_MARGIN s before the other arrives; otherwise a moving
    // car beats a stopped one (a waiting car lets the whole stream pass),
    // then the earlier arrival goes, then the lower id. Kept, except when the
    // car given way to has since stopped short of the conflict: queued behind
    // a light or another car, or too far to reach it before the other clears
    // it. Then the other goes, instead of waiting out that queue.
    const conflicts = new Map();
    function winner(car, o, t, s, zoneC, zoneO) {
      const key = car.id < o.id ? car.id + ',' + o.id : o.id + ',' + car.id;
      let c = conflicts.get(key);
      if (!c) {
        const reachC = arriveTime(car.speed, t - zoneC), clearC = arriveTime(car.speed, t + zoneC);
        const reachO = arriveTime(o.speed, s - zoneO), clearO = arriveTime(o.speed, s + zoneO);
        const slowC = car.speed < 0.5 * CRUISE, slowO = o.speed < 0.5 * CRUISE;
        const first = clearC + CROSS_MARGIN < reachO ? car
          : clearO + CROSS_MARGIN < reachC ? o
          : slowC !== slowO ? (slowC ? o : car)
          : Math.abs(reachC - reachO) > 0.1 ? (reachC < reachO ? car : o)
          : car.id < o.id ? car : o;
        conflicts.set(key, c = { first });
      }
      if (c.first === o && o.speed < 0.05 && s - zoneO > 0.3) {
        const held = o.atLight || (o.blocker && o.blocker !== car);
        if ((held && s - zoneO > 0.8) || arriveTime(0, s - zoneO) > arriveTime(car.speed, t + zoneC) + CROSS_MARGIN) c.first = car;
      }
      c.seen = true;
      return c.first;
    }

    // [distance the car may still drive before yielding to crossing or
    // merging traffic (Infinity if it needn't), the car it yields to].
    // Each car's path sampled every 0.1 tiles from 0.6 behind to 3 ahead,
    // once per step (car.probe), with its bounding box for quick rejects.
    function probe(car) {
      const pts = [];
      let u0 = Infinity, u1 = -Infinity, v0 = Infinity, v1 = -Infinity;
      for (let k = -6; k <= 30; k++) {
        const p = pointAhead(car, k / 10);
        pts.push([k / 10, p]);
        u0 = Math.min(u0, p[0]); u1 = Math.max(u1, p[0]); v0 = Math.min(v0, p[1]); v1 = Math.max(v1, p[1]);
      }
      car.probe = { pts, mine: pts.slice(7, 23), box: [u0, u1, v0, v1] };   // mine: 0.1 .. 1.6 ahead
    }

    function crossGap(car) {
      let gap = Infinity, who = null;
      const { mine } = car.probe;
      let mu0 = Infinity, mu1 = -Infinity, mv0 = Infinity, mv1 = -Infinity;
      for (const [, p] of mine) {
        mu0 = Math.min(mu0, p[0]); mu1 = Math.max(mu1, p[0]); mv0 = Math.min(mv0, p[1]); mv1 = Math.max(mv1, p[1]);
      }
      for (const o of nearby(car)) {
        if (o === car || o.parked > 0 || o.atLight) continue;
        const [ou0, ou1, ov0, ov1] = o.probe.box;
        if (ou0 > mu1 + 0.3 || ou1 < mu0 - 0.3 || ov0 > mv1 + 0.3 || ov1 < mv0 - 0.3) continue;
        // Conflict point: the first point on the car's path that o's path
        // comes within 0.3 of, t ahead of the car and s ahead of o (negative:
        // o is already over it).
        let t = 0, s = 0, best = 0.3;
        const theirs = o.probe.pts;
        for (const [tc, p] of mine) {
          for (const [so, q] of theirs) {
            const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
            if (d < best) [best, t, s] = [d, tc, so];
          }
          if (t) break;
        }
        if (!t) continue;
        const h = headAhead(car, t), g = headAhead(o, s);
        const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
        // Paths that end up in the same lane: a merge unless the cars are
        // already in it (then it's plain following, handled by aheadOf).
        const merge = Math.abs(dot(h, g)) >= 0.7;
        if (merge && dot(car.head, o.head) >= 0.7) continue;
        const zoneC = merge ? halfL(car) + halfL(o) + 0.15 : halfL(car) + halfW(o) + 0.2;
        const zoneO = merge ? zoneC : halfL(o) + halfW(car) + 0.2;
        if (s < -zoneO) continue;                         // o has cleared it
        // Patience: in a standstill the car that has waited longest goes.
        if (car.stuck > PATIENCE && o.speed < 0.05 && !(o.stuck >= car.stuck)) continue;
        const first = winner(car, o, t, s, zoneC, zoneO);
        if (t < zoneC - 0.15) continue;                   // well inside it: clear it
        const yields = s < zoneO || first === o;          // o is in it, or goes first
        if (yields && t - zoneC < gap && !breaksLoop(car, o, 'yield')) [gap, who] = [t - zoneC, o];
      }
      return [gap, who];
    }

    // The hero pulling out from the curb waits for the lane behind to clear.
    function mergeGap(car) {
      if (!car.hero || car.s > PULL || car.speed > 0.2) return [Infinity, null];
      const h = car.head;
      for (const o of nearby(car)) {
        if (o === car || h[0] * o.head[0] + h[1] * o.head[1] < 0.5 || breaksLoop(car, o, 'yield')) continue;
        const du = o.pos[0] - car.pos[0], dv = o.pos[1] - car.pos[1];
        const back = -(du * h[0] + dv * h[1]), side = Math.abs(du * h[1] - dv * h[0]);
        if (back < -halfL(car) || back > 3 || side > 0.5) continue;
        const tO = arriveTime(o.speed, back - GAP);
        if (tO < arriveTime(0, PULL - car.s) + CROSS_MARGIN) return [0, o];
      }
      return [Infinity, null];
    }

    // Cars bucketed by BUCKET-tile squares each step, so a car only checks
    // the cars in its own and the eight surrounding buckets (all interactions
    // reach at most 3.5 tiles).
    const BUCKET = 4;
    let buckets = new Map();
    const bucketKey = (u, v) => Math.floor(u / BUCKET) + ',' + Math.floor(v / BUCKET);
    function nearby(car) {
      const bu = Math.floor(car.pos[0] / BUCKET), bv = Math.floor(car.pos[1] / BUCKET), out = [];
      for (let a = bu - 1; a <= bu + 1; a++) for (let b = bv - 1; b <= bv + 1; b++) {
        const list = buckets.get(a + ',' + b);
        if (list) for (const o of list) out.push(o);
      }
      return out;
    }

    // Don't block the box: a car doesn't enter a junction if the slow or
    // stopped car ahead leaves no room to stop beyond it; it waits before
    // the junction instead, so crossing traffic keeps flowing. Returns the
    // distance it may drive (Infinity if unconstrained).
    function boxGap(car) {
      const p = car.path, pts = car.probe.pts;
      if (p.box[indexAhead(car, 0)]) return [Infinity, null];      // in one already: clear it
      let dIn = -1, dOut = -1;
      for (let k = 7; k < pts.length; k++) {                        // 0.1 .. 3.0 ahead
        const inBox = p.box[indexAhead(car, pts[k][0])];
        if (dIn < 0 && inBox) dIn = pts[k][0];
        else if (dIn >= 0 && !inBox) { dOut = pts[k][0]; break; }
      }
      if (dIn < 0 || dOut < 0 || dIn - halfL(car) < -0.05) return [Infinity, null];
      // Nearest slow car on the path within 3 tiles.
      let lead = Infinity, who = null;
      for (const o of nearby(car)) {
        if (o === car || o.parked > 0 || o.speed > 0.3 || breaksLoop(car, o, 'yield')) continue;
        for (let k = 7; k < pts.length && pts[k][0] < lead; k++) {
          const q = pts[k][1];
          if (Math.abs(q[0] - o.pos[0]) < 0.22 && Math.abs(q[1] - o.pos[1]) < 0.22) { lead = pts[k][0]; who = o; break; }
        }
      }
      return lead - GAP < dOut + halfL(car) ? [dIn - halfL(car) - 0.05, who] : [Infinity, null];
    }

    const GATE_S = 0.7;                               // s for a gate arm to swing up or down
    function step(dt) {
      clock += dt;
      for (const g of gates) {
        const near = Math.hypot(hero.pos[0] - g.pos[0], hero.pos[1] - g.pos[1]) < 1.6;
        g.open = Math.min(1, Math.max(0, g.open + (near ? dt : -dt) / GATE_S));
      }
      buckets = new Map();
      for (const car of cars) {
        const k = bucketKey(car.pos[0], car.pos[1]);
        if (!buckets.has(k)) buckets.set(k, []);
        buckets.get(k).push(car);
        probe(car);
      }
      for (const c of conflicts.values()) c.seen = false;
      for (const car of cars) {
        let gap = Infinity, atLight = false, blocker = null;
        for (const o of nearby(car)) {
          if (o === car || o.parked > 0) continue;     // the parked hero is at the curb
          const ahead = aheadOf(car, o);
          if (ahead < 0 || ahead - GAP >= gap || breaksLoop(car, o, 'body')) continue;
          gap = ahead - GAP;
          blocker = o;
        }
        // The binding constraint and whom it waits on: body (a car in the
        // way) or yield (right of way, a merge or a junction hold), which
        // the loop breaker may override.
        const [cross, yieldTo] = crossGap(car);
        car.yielding = cross < Infinity;
        let kind = 'body';
        if (cross < gap) [gap, blocker, kind] = [cross, yieldTo, 'yield'];
        const [merge, mergeWho] = mergeGap(car);
        if (merge < gap) [gap, blocker, kind] = [merge, mergeWho, 'yield'];
        const [held, lead] = boxGap(car);
        if (held < gap) [gap, blocker, kind] = [held, lead, 'yield'];
        car.blocker = gap < 0.05 ? blocker : null;
        car.blockKind = kind;
        for (const st of car.path.stops) {
          const state = light(st.sig, st.axis);
          if (state === 'green') continue;
          let d = st.s - car.s;
          if (d < -1) d += car.path.total;
          if (d < -0.01 || d > 1.2) continue;
          if (state === 'amber' && d < 0.25) continue;     // too close to stop
          if (d < gap) { gap = d; atLight = true; }
        }
        car.atLight = atLight;
        if (!car.path.closed) gap = Math.min(gap, car.path.total - car.path.step - car.s);
        if (car.hold > 0) { car.hold -= dt; gap = 0; }
        const target = Math.min(CRUISE, Math.sqrt(2 * DECEL * Math.max(0, gap)));
        car.speed = target > car.speed
          ? Math.min(target, car.speed + ACCEL * dt)
          : Math.max(target, car.speed - DECEL * dt);
        if (gap <= 0) car.speed = 0;
        car.stuck = car.speed < 0.01 && !car.atLight && !(car.parked > 0) ? (car.stuck || 0) + dt : 0;
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
      for (const [key, c] of conflicts) if (!c.seen) conflicts.delete(key);
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
      grass: '#1b2a25', dirt: '#2e2a22', paving: '#262f3f', water: '#1f3552', sand: '#3a3527', lot: '#2c3548', road: '#46526b',
      ahead: '#ff4e00', behind: '#b8c1d3', car: '#ffffff', carEdge: '#0e1320',
    };
    const mmX = (u, v) => 1 + MM_HW * (NV + u - v);
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
      const c = canvasOf(Math.ceil((NU + NV) * MM_HW) + 2, Math.ceil((NU + NV) * MM_HH) + 2);
      const px = painter(c.getContext('2d'));
      const lotAt = new Set();
      for (const [, u0, u1, v0, v1] of city.lots) {
        for (let u = Math.floor(u0); u < Math.ceil(u1); u++) for (let v = Math.floor(v0); v < Math.ceil(v1); v++) lotAt.add(u + ',' + v);
      }
      for (let u = 0; u < NU; u++) {
        for (let v = 0; v < NV; v++) {
          const gr = city.ground(u, v);
          if (!gr) continue;                             // off the island
          const name = gr[0];
          const color = lotAt.has(u + ',' + v) ? MM_C.lot
            : name.includes('grass') ? MM_C.grass
            : name.includes('dirt') ? MM_C.dirt
            : name === 'paving' ? MM_C.paving
            : ['pond', 'pool', 'canal'].includes(name) || /water|shore/.test(name) ? MM_C.water
            : name.includes('sand') ? MM_C.sand
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
    // ?look=u,v pins the camera on a tile (for checking parts of the city).
    const look = (new URLSearchParams(location.search).get('look') || '').split(',').map(Number);
    function follow(dt) {
      const [tx, ty] = look.length === 2 && look.every(Number.isFinite) ? iso(look[0], look[1]) : heroScreen();
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
      drawScene(ctx, [view.x, view.y, view.w, view.h]);

      const inView = [view.x - 64, view.y - 64, view.w + 128, view.h + 128];
      // Animated sprites (the fountains), then whatever stands in front of
      // them redrawn over them, clipped, as for cars below.
      for (const a of animated) {
        if (!overlap(a.rect, inView)) continue;
        const [x, y, w, h] = a.rect, f = a.frameOf ? a.frameOf() : Math.floor(clock * ANIM_FPS) % a.frames;
        ctx.drawImage(img[a.src], f * w, 0, w, h, x, y, w, h);
        const front = [...hash.query(a.rect)].filter(st => drawsBefore(a, st)).sort(byOrder);
        if (!front.length) continue;
        ctx.save();
        ctx.beginPath();
        ctx.rect(...a.rect);
        ctx.clip();
        front.forEach(st => st.draw(ctx));
        ctx.restore();
      }
      const visible = [];
      for (const car of cars) {
        // Footprint box: the car's length along its heading, width across.
        const [l, w] = car.hero ? [HERO_HALF, HERO_HALF_W] : [CAR_HALF, CAR_HALF_W];
        const [hu, hv] = car.head.map(Math.abs);
        const du = hu * l + hv * w, dv = hv * l + hu * w;
        car.box = [car.pos[0] - du, car.pos[0] + du, car.pos[1] - dv, car.pos[1] + dv];
        const [x, y] = iso(car.pos[0], car.pos[1]);
        if (overlap([x, y, 1, 1], inView)) visible.push(car);
      }
      const near = a => visible.filter(b =>
        Math.abs(a.pos[0] - b.pos[0]) < 1.5 && Math.abs(a.pos[1] - b.pos[1]) < 1.5);
      for (const car of paintOrder(visible, near, carBefore)) {
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

      drawBeam(ctx);
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

    // Lighthouse beam: two opposite wedges of light turning at lamp height,
    // and a glow on the lantern that flares as a beam sweeps toward the camera.
    const LAMP = (art['landmarks/lighthouse.png'] || {}).lamp || [0, -139];
    function drawBeam(c) {
      if (!city.lighthouse) return;
      const [bx, by] = iso(...city.lighthouse), x = bx + LAMP[0], y = by + LAMP[1];
      if (!overlap([x - 520, y - 300, 1040, 600], [view.x, view.y, view.w, view.h])) return;
      const L = 7, spread = 0.14;
      const at = (du, dv) => [x + (du - dv) * HW, y + (du + dv) * HH];
      c.save();
      c.globalCompositeOperation = 'screen';
      let facing = 0;
      for (const a of [clock * 0.8, clock * 0.8 + Math.PI]) {
        const du = Math.cos(a), dv = Math.sin(a);
        facing = Math.max(facing, (du + dv) / Math.SQRT2);
        const [ex, ey] = at(du * L, dv * L);
        const grad = c.createLinearGradient(x, y, ex, ey);
        grad.addColorStop(0, 'rgba(255, 236, 170, 0.34)');
        grad.addColorStop(1, 'rgba(255, 236, 170, 0)');
        c.fillStyle = grad;
        c.beginPath();
        c.moveTo(x, y);
        c.lineTo(...at((du - dv * spread) * L, (dv + du * spread) * L));
        c.lineTo(...at((du + dv * spread) * L, (dv - du * spread) * L));
        c.closePath();
        c.fill();
      }
      const r = 5 + 9 * Math.max(0, facing);
      const glow = c.createRadialGradient(x, y, 0, x, y, r);
      glow.addColorStop(0, `rgba(255, 244, 200, ${0.35 + 0.5 * Math.max(0, facing)})`);
      glow.addColorStop(1, 'rgba(255, 236, 170, 0)');
      c.fillStyle = glow;
      c.fillRect(x - r, y - r, 2 * r, 2 * r);
      c.restore();
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
    await phase('scene');
    // Test hook (tools/sim.js): hands the running city to a callback.
    if (typeof root.__pixelCityHook === 'function') root.__pixelCityHook({ city, cars, step, seed });
    resize();
    follow(Infinity);
    render();
    requestAnimationFrame(frame);
    loading.finish();
  }

  document.querySelectorAll('[data-pixel-city]').forEach(el => {
    mount(el).catch(err => console.error(err));
  });
})();
