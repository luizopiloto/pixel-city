// Headless check of js/city.js: builds a city in Node (minimal DOM and
// canvas stand-ins), reports its stats and road connectivity, then runs the
// traffic for a while and reports close calls, stuck cars and step() time.
//
//   node tools/sim.js [seconds=120] [seed=random] [--quiet] [--dump=map.json]
//
// Exits non-zero if the roads are disconnected, traffic gridlocks (over 10% of
// cars stopped for 10 s away from a red light), the hero
// stalls (stopped HERO_STALL s, not parked or at a light), a district has two
// of the same civic building or a building's entrance is blocked.
// DIAG=1 lists stuck cars and what each waits on; DOORS=1 tallies blocked
// entrances by building and blocker. FPS=30 or 20 steps like a slow browser
// (default 60); HERO_STALL sets the stall limit in s (default 30).
'use strict';
const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2).filter(a => !a.startsWith('--'));
const seconds = Number(args[0] || 120);
const seed = args[1] !== undefined ? String(args[1]) : String(Math.floor(Math.random() * 2 ** 31));
const quiet = process.argv.includes('--quiet');

// Minimal browser stand-ins: a canvas context that accepts any call.
const noop = new Proxy(function () {}, { get: () => noop, apply: () => noop, set: () => true });
const el = () => ({
  style: { setProperty() {} }, dataset: {}, classList: { add() {} }, setAttribute() {}, appendChild() {},
  addEventListener() {}, remove() {}, getContext: () => noop, width: 0, height: 0,
  clientWidth: 1600, clientHeight: 900,
});
const root = el();
root.dataset = { pixelCity: '', assets: 'assets/', zoom: '1', seed };
global.window = { devicePixelRatio: 1, matchMedia: () => ({ matches: false }) };
global.location = { search: '' };
global.document = { createElement: el, getElementById: () => null, querySelectorAll: () => [root], hidden: false };
global.Image = class { set src(v) { this.width = 64; this.height = 64; setTimeout(() => this.onload()); } };
global.ResizeObserver = global.IntersectionObserver = class { observe() {} disconnect() {} };
global.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 0);
global.fetch = async url => {                    // assets from disk
  const file = path.join(__dirname, '..', url);
  return fs.existsSync(file) ? { ok: true, json: async () => JSON.parse(fs.readFileSync(file, 'utf8')) } : { ok: false };
};

root.__pixelCityHook = ({ city, cars, step, seed: usedSeed }) => {
  // City stats and road connectivity (flood fill over road tiles).
  const roads = [];
  for (let u = 0; u < city.NU; u++) for (let v = 0; v < city.NV; v++) if (city.isRoad(u, v)) roads.push([u, v]);
  const seen = new Set([roads[0].join(',')]), stack = [roads[0]];
  while (stack.length) {
    const [u, v] = stack.pop();
    for (const [du, dv] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const k = (u + du) + ',' + (v + dv);
      if (!seen.has(k) && city.isRoad(u + du, v + dv)) { seen.add(k); stack.push([u + du, v + dv]); }
    }
  }
  const connected = seen.size === roads.length;
  // Civic landmarks: at most one of each per district.
  const civic = new Map();
  let duplicates = 0;
  for (const [kind, , , , , district] of city.lots) {
    if (!kind.startsWith('art:civic/')) continue;
    const k = district + ':' + kind;
    if (civic.has(k)) duplicates++;
    civic.set(k, (civic.get(k) || 0) + 1);
  }
  const dump = process.argv.find(a => a.startsWith('--dump='));
  if (dump) {                                  // ground names per tile, for a map image
    const grid = [];
    for (let u = 0; u < city.NU; u++) {
      const row = [];
      for (let v = 0; v < city.NV; v++) { const g = city.ground(u, v); row.push(g ? (city.isRoad(u, v) ? 'road' : g[0]) : ''); }
      grid.push(row);
    }
    fs.writeFileSync(dump.slice(7), JSON.stringify({ NU: city.NU, NV: city.NV, grid, lots: city.lots, cells: city.cellList }));
  }
  console.log(`seed ${usedSeed}: ${city.cells} cells, ${city.NU}×${city.NV} tiles, ${city.signals.length} lights, ` +
    `${city.routes.length} loops, ${cars.length} cars, roads ${connected ? 'connected' : `DISCONNECTED (${seen.size}/${roads.length})`}` +
    `, districts ${city.districts.join('/')}, ${civic.size} civic${duplicates ? `, ${duplicates} DUPLICATE civic` : ''}` +
    `, ${city.blockedDoors ? `${city.blockedDoors} BLOCKED entrances` : 'entrances clear'}`);

  // Traffic: close calls between crossing cars, gridlock, step() time.
  const hero = cars[0], dt = 1 / Number(process.env.FPS || 60), close = new Set();   // FPS=20: a slow browser
  let events = 0, minCross = 9, routes = 0, wasParked = false, total = 0, worst = 0;
  let stall = 0, worstStall = 0, stallAt = null;           // hero stopped, not parked or at a light
  for (let f = 0; f < seconds / dt; f++) {
    const t0 = performance.now();
    step(dt);
    const ms = performance.now() - t0;
    total += ms;
    if (f > 60) worst = Math.max(worst, ms);
    const parked = hero.parked > 0;
    if (parked && !wasParked) routes++;
    wasParked = parked;
    if (hero.speed < 0.01 && !parked && !hero.atLight && !(hero.hold > 0)) {
      stall += dt;
      if (stall > worstStall) {
        worstStall = stall;
        const b = hero.blocker;
        stallAt = `${hero.pos.map(n => n.toFixed(2))} s ${hero.s.toFixed(2)} waiting on ${b ? `car ${b.id} (${b.blockKind}, ` +
          `at ${b.pos.map(n => n.toFixed(2))}, its blocker ${b.blocker ? b.blocker.id : '-'})` : '-'} as ${hero.blockKind}`;
      }
    } else stall = 0;
    if (f % 2) continue;
    for (let i = 0; i < cars.length; i++) for (let j = i + 1; j < cars.length; j++) {
      const a = cars[i], b = cars[j];
      if (a.parked > 0 || b.parked > 0) continue;
      const du = a.pos[0] - b.pos[0], dv = a.pos[1] - b.pos[1];
      if (Math.abs(du) > 1 || Math.abs(dv) > 1) continue;
      if (Math.abs(a.head[0] * b.head[0] + a.head[1] * b.head[1]) >= 0.5) continue;
      const d = Math.hypot(du, dv), k = i + ',' + j;
      minCross = Math.min(minCross, d);
      if (d < 0.3) { if (!close.has(k)) { close.add(k); events++; } } else if (d > 0.6) close.delete(k);
    }
  }
  const stopped = cars.filter(c => c.speed < 0.01 && !c.parked).length;
  // Stuck: stopped over 10 s and not at a red light (waiting at one is normal).
  const stuck = cars.filter(c => c.stuck > 10).length;
  if (process.env.DOORS) {                     // which entrances are blocked, and by what
    const tally = new Map();
    for (const [lot, by] of city.blocked) {
      const k = `${lot[0]} (${(lot[4] - lot[3]).toFixed(2)} deep lot) <- ${by[0]}`;
      tally.set(k, (tally.get(k) || 0) + 1);
    }
    [...tally].sort((a, b) => b[1] - a[1]).slice(0, 15).forEach(([k, n]) => console.log(`  ${n} × ${k}`));
  }
  if (process.env.DIAG) {                      // who is stuck, and on whom
    for (const c of cars.filter(c => c.speed < 0.01 && !c.parked)) {
      const b = c.blocker;
      console.log(`  car ${c.id} at ${c.pos.map(n => n.toFixed(2))} head ${c.head.map(n => n.toFixed(1))} ` +
        `light ${c.atLight} yield ${c.yielding} blockKind ${c.blockKind} blocker ${b ? b.id : '-'}` +
        (b ? ` (at ${b.pos.map(n => n.toFixed(2))}, speed ${b.speed.toFixed(2)})` : ''));
    }
  }
  const avg = cars.reduce((t, c) => t + c.speed, 0) / cars.length;
  const gridlock = stuck > cars.length * 0.1;
  const HERO_STALL = Number(process.env.HERO_STALL || 30), stalled = worstStall > HERO_STALL;
  console.log(`  ${seconds}s: close calls ${events}, closest crossing ${minCross.toFixed(2)}, ` +
    `${stopped} stopped (${stuck} stuck), avg speed ${avg.toFixed(2)}, hero routes ${routes}, ` +
    `step ${(total * dt / seconds).toFixed(3)} ms avg / ${worst.toFixed(2)} ms worst${gridlock ? ', GRIDLOCK' : ''}` +
    `, hero's longest stall ${worstStall.toFixed(1)} s${stalled ? ` STALLED at ${stallAt}` : ''}`);
  process.exitCode = connected && !gridlock && !stalled && !duplicates && !city.blockedDoors ? 0 : 1;
  process.exit();
};

const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'city.js'), 'utf8');
if (quiet) console.error = () => {};
eval(src);
