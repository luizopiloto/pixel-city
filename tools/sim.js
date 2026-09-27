// Headless check of js/city.js: builds a city in Node (minimal DOM and
// canvas stand-ins), reports its stats and road connectivity, then runs the
// traffic for a while and reports close calls, stuck cars and step() time.
//
//   node tools/sim.js [seconds=120] [seed=random] [--quiet] [--dump=map.json]
//
// Exits non-zero if the roads are disconnected or traffic gridlocks.
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
root.dataset = { pixelCity: '', assets: 'assets/', zoom: '2', seed };
global.window = { devicePixelRatio: 1, matchMedia: () => ({ matches: false }) };
global.location = { search: '' };
global.document = { createElement: el, getElementById: () => null, querySelectorAll: () => [root], hidden: false };
global.Image = class { set src(v) { this.width = 64; this.height = 64; setTimeout(() => this.onload()); } };
global.ResizeObserver = global.IntersectionObserver = class { observe() {} disconnect() {} };
global.requestAnimationFrame = cb => setTimeout(() => cb(performance.now()), 0);

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
  const dump = process.argv.find(a => a.startsWith('--dump='));
  if (dump) {                                  // ground names per tile, for a map image
    const grid = [];
    for (let u = 0; u < city.NU; u++) {
      const row = [];
      for (let v = 0; v < city.NV; v++) { const g = city.ground(u, v); row.push(g ? (city.isRoad(u, v) ? 'road' : g[0]) : ''); }
      grid.push(row);
    }
    fs.writeFileSync(dump.slice(7), JSON.stringify({ NU: city.NU, NV: city.NV, grid, lots: city.lots }));
  }
  console.log(`seed ${usedSeed}: ${city.cells} cells, ${city.NU}×${city.NV} tiles, ${city.signals.length} lights, ` +
    `${city.routes.length} loops, ${cars.length} cars, roads ${connected ? 'connected' : `DISCONNECTED (${seen.size}/${roads.length})`}`);

  // Traffic: close calls between crossing cars, gridlock, step() time.
  const hero = cars[0], dt = 1 / 60, close = new Set();
  let events = 0, minCross = 9, routes = 0, wasParked = false, total = 0, worst = 0;
  for (let f = 0; f < seconds * 60; f++) {
    const t0 = performance.now();
    step(dt);
    const ms = performance.now() - t0;
    total += ms;
    if (f > 60) worst = Math.max(worst, ms);
    const parked = hero.parked > 0;
    if (parked && !wasParked) routes++;
    wasParked = parked;
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
  const avg = cars.reduce((t, c) => t + c.speed, 0) / cars.length;
  const gridlock = stopped > cars.length * 0.3;
  console.log(`  ${seconds}s: close calls ${events}, closest crossing ${minCross.toFixed(2)}, ` +
    `${stopped} stopped, avg speed ${avg.toFixed(2)}, hero routes ${routes}, ` +
    `step ${(total / (seconds * 60)).toFixed(3)} ms avg / ${worst.toFixed(2)} ms worst${gridlock ? ', GRIDLOCK' : ''}`);
  process.exitCode = connected && !gridlock ? 0 : 1;
  process.exit();
};

const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'city.js'), 'utf8');
if (quiet) console.error = () => {};
eval(src);
