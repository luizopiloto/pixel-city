# Pixel City

An isometric pixel-art city with animated traffic and a hero car driving
random routes, followed by the camera and a GPS phone mini-map.

Every load builds a new island city: an irregular downtown of about 256
blocks (with merged superblocks, long blocks and town squares with
fountains, a TV tower and a parking lot) and suburb, park and plaza
districts around it; on the north coast a port (quay cranes, container
yards, cargo ships, warehouses, customs) and an industrial district
(factories with smoking chimneys, the Cola and Chips works, truck parks),
and a nuclear power plant on its own block; the island is ringed by
beaches, piers and a lighthouse. The hero starts in a downtown parking
lot. Other cars roam the streets on endless random routes, lighter in the
suburbs; every 4-way crossing touching downtown or the plaza district has
traffic lights on a green wave, and every 4-way crossing has crosswalks.
Waves roll onto the shore, boats and
buoys bob, the fountains play and the lighthouse beam turns; with
`prefers-reduced-motion` everything holds still.

**Live demo:** https://luizopiloto.github.io/pixel-city/

## Embed

```html
<link rel="stylesheet" href="css/style.css">
<div class="pixel-city" data-pixel-city data-assets="assets/" data-zoom="1"></div>
<script src="js/city.js"></script>
```

The container defaults to 16:9 at full width; size it however you need.

| Option | Default | Description |
| --- | --- | --- |
| `data-zoom` | `1` | CSS pixels per art pixel (on high-DPI screens each art pixel still covers whole device pixels). Read once, on load. |
| `data-seed` | random | Pins the city layout. Without it, every page load builds a new city. |
| `data-assets` | `assets/` | Path to the assets folder. |
| `data-tiltshift` | on | `"off"` removes the tilt-shift blur. |
| `data-quality` | adapts | `"high"`, `"medium"` or `"low"` pins the quality tier (see below). |
| `data-minimap` | — | Id of an element to hold the GPS phone. Without it, the phone sits in the bottom-right corner. |

The "Standalone preview only" rules at the end of `css/style.css` make
`index.html` fill the window; drop them when embedding.

## Quality tiers

The page adapts to the device, once: when frames keep coming late (over a
quarter of them, two 2 s windows in a row, judged against the display's own
refresh rate and never faster than 60 fps) it drops a tier. It never climbs
back, so it settles instead of switching back and forth, and it remembers the
tier for the next visit (a week).

- **high**: drawn at full display resolution, tilt-shift blur and colour grade.
- **medium**: no tilt-shift blur; on dense (2× or 3×) screens the canvas is
  drawn at a whole fraction of the display resolution and stretched sharp by
  CSS (a 3× phone fills a ninth of the pixels).
- **low**: drawn at art-pixel resolution, no blur or colour grade, 30 fps
  (every other frame on 60 Hz and faster displays).

It starts at medium on touch screens and dense displays, high otherwise;
those devices also bake the scene in half-size chunks, so each bake is a
shorter hitch. Chunks around the view are baked ahead, toward where the camera
is heading, in the time left after a frame is painted.

## KDE Plasma wallpaper

`plasma-wallpaper/` is a KDE Plasma 6 wallpaper plugin, **Web Paper**, that
shows a web page as the desktop background: Pixel City by default. It pauses
while a maximized or full-screen window covers the screen, keeps the page's
cache and storage between sessions (per screen), retries if the page fails to
load, and keeps the page from opening dialogs, windows or other sites, asking
for permissions or downloading (details in
[its README](plasma-wallpaper/README.md)).

**Needs** Plasma 6 (Qt 6.8 or newer, as in Plasma 6.4 and later) and Qt
WebEngine for QML:

| Distribution | Package |
| --- | --- |
| Arch, Manjaro, CachyOS | `qt6-webengine` |
| Debian, Ubuntu, KDE neon | `qml6-module-qtwebengine` |
| Fedora | `qt6-qtwebengine` |

**Install:**

1. Get the files: `git clone https://github.com/luizopiloto/pixel-city.git`
   (or download the repository as a ZIP from GitHub and unpack it).
2. From the repository folder, install the plugin for your user:

   ```bash
   kpackagetool6 --type Plasma/Wallpaper --install plasma-wallpaper
   ```

   It goes to `~/.local/share/plasma/wallpapers/com.luiz.webpaper/`.
3. Right-click the desktop, **Configure Desktop and Wallpaper…**, set
   **Wallpaper type** to **Web Paper** and **Apply**. If it isn't in the
   list, restart Plasma: `systemctl --user restart plasma-plasmashell`.

**Settings** (on the same page): the URL, zoom (pixel art stays sharp at
100%, 200%, 300%), a reload interval, and pausing under maximized or
full-screen windows. Pixel City's switches go in the URL, e.g.
`https://luizopiloto.github.io/pixel-city/?quality=low` on a weak machine or
`?seed=123` for the same city every time.

**Update** after pulling new changes, then restart Plasma to load them:

```bash
kpackagetool6 --type Plasma/Wallpaper --upgrade plasma-wallpaper
systemctl --user restart plasma-plasmashell
```

**Uninstall** (pick another wallpaper first):
`kpackagetool6 --type Plasma/Wallpaper --remove com.luiz.webpaper`

If the wallpaper stays black, check that the Qt WebEngine package above is
installed and look for errors with
`journalctl --user -b | grep -i -e webpaper -e webengine`.

## Run locally

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080. URL switches for checking things:

- `?seed=123`: build that city (the seed is logged with `?debug`)
- `?look=u,v`: pin the camera on tile (u, v) instead of following the hero
- `?loading`: keep the loading screen up
- `?debug`: log startup phase times, the seed and chunk bakes
- `?quality=high|medium|low`: pin the quality tier
- `?perf`: an overlay of where frame time goes (per-section ms, chunk bakes,
  late and dropped frames, run totals, the canvas size and scale)

`node tools/sim.js [seconds] [seed]` runs the real `js/city.js` headless:
it reports the city (cells, size, lights, cars, districts),
checks that every road is connected, that no district has two of the same
civic building and that no building's entrance is blocked, then runs the
traffic to count close calls, stopped and stuck cars, `step()` time, the
hero's longest stall and the cars per block downtown and in the suburbs.
It exits non-zero on any failure, including gridlock (over 10% of cars
stuck for 10 s away from a red light) or the hero stalling for over 30 s.
Options:

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
