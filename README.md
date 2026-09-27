# Pixel City

An isometric pixel-art city with animated traffic and a hero car driving
random routes, followed by the camera and a GPS phone mini-map.

Every load builds a new island city: an irregular downtown of about 256
blocks (with merged superblocks, long blocks and town squares with
fountains) and suburb, park and plaza districts around it, ringed by
beaches, piers and a lighthouse. Waves roll onto the shore, boats and
buoys bob, the fountains play and the lighthouse beam turns; with
`prefers-reduced-motion` everything holds still.

**Live demo:** https://luizopiloto.github.io/pixel-city/

## Embed

```html
<link rel="stylesheet" href="css/style.css">
<div class="pixel-city" data-pixel-city data-assets="assets/" data-zoom="2"></div>
<script src="js/city.js"></script>
```

The container defaults to 16:9 at full width; size it however you need.

| Option | Default | Description |
| --- | --- | --- |
| `data-zoom` | `2` | CSS pixels per art pixel. Read once, on load. |
| `data-seed` | random | Pins the city layout. Without it, every page load builds a new city. |
| `data-assets` | `assets/` | Path to the assets folder. |
| `data-tiltshift` | on | `"off"` removes the tilt-shift blur. |
| `data-minimap` | — | Id of an element to hold the GPS phone. Without it, the phone sits in the bottom-right corner. |

The "Standalone preview only" rules at the end of `css/style.css` make
`index.html` fill the window; drop them when embedding.

## Run locally

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080. URL switches for checking things:

- `?seed=123`: build that city (the seed is logged with `?debug`)
- `?look=u,v`: pin the camera on tile (u, v) instead of following the hero
- `?loading`: keep the loading screen up
- `?debug`: log startup phase times, the seed and chunk bakes

`node tools/sim.js [seconds] [seed]` runs the real `js/city.js` headless:
it reports the city (cells, size, lights, traffic loops, cars, districts),
checks that every road is connected, that no district has two of the same
civic building and that no building's entrance is blocked, then runs the
traffic to count close calls, stuck cars, `step()` time and the hero's
longest stall. It exits non-zero on any failure, including gridlock or the
hero stalling for over 30 s. Options:

- `--quiet`: hide the page's own console errors
- `--dump=map.json`: write the ground, lots and cells for inspection
- `FPS=30` or `FPS=20`: step like a slower browser (default 60)
- `HERO_STALL=10`: a stricter stall limit in seconds
- `DIAG=1`: list the stuck cars and what each waits on
- `DOORS=1`: tally blocked entrances by building

## Assets

Two scripts write the sprites the page loads; re-run the one you changed.

`tools/bake.py` cuts tiles, props, buildings, vehicle atlases and wheel
animations from the source images in `assets/`:

```bash
python3 tools/bake.py
```

`tools/art.py` draws the rest in the city's projection and palette
(Python with NumPy and Pillow): ground, shoreline, dune and foam tiles,
trees and plants, houses, city and civic buildings, beach props, the
lighthouse and the playground, BBQ and fountain pieces. They go in
`assets/art/` with a `manifest.json` giving each sprite's size, ground
anchor and footprint. Sprites with a `frames` count are animations with
their frames side by side, drawn every frame instead of baked, and
`<name>-r1` to `-r3` are the same prop turned by 90° steps.

```bash
rm -rf assets/art && python3 tools/art.py
```

## License

MIT
