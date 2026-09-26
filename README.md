# Pixel City

Isometric pixel-art city with animated traffic, built to be embedded in a
landing page. It renders only the city: the host page owns background, layout
and copy.

## Embed

```html
<link rel="stylesheet" href="css/style.css">
<div class="pixel-city" data-pixel-city data-assets="assets/" data-zoom="2"></div>
<script src="js/city.js"></script>
```

The container defaults to 16:9 at full width; size it however the host page
needs. It shows a pixel-sharp window onto the city (whole-number scale, never
smoothed) that pans to follow the hero car. Options on the container:

- `data-zoom="1"`: CSS pixels per art pixel (default 2). Read once, on mount;
  `index.html` sets it to 1 on screens up to 980px wide before loading the
  script.
- `data-seed="…"`: a different layout (default 7)
- `data-tiltshift="off"`: drop the miniature tilt-shift effect (on by
  default).
- `data-minimap="some-id"`: id of an element to hold the GPS phone. Without
  it the phone sits near the container's bottom-right corner (inset 4% of
  the width from the right, 6% of the height from the bottom).

`css/style.css` also draws a vignette over the canvas (`.pixel-city::after`)
and keeps the phone above it. The "Standalone preview only" rules at the
bottom make `index.html` fill the window and can be dropped in the host page.

## How it works

- 8×8 city blocks of 3×3 tiles on a road grid (35×35 tiles of 128×64). Four
  groups of 2×3 / 3×2 blocks are merged into dense downtown superblocks, with
  their inner roads removed. Other blocks come from seeded templates: twin
  buildings, rows of small buildings, mixed, plaza, park with pond, canal.
- Roads are auto-tiled from their neighbours, using the authored tiles plus
  mirrored/rotated variants.
- Each building's footprint is measured in sprite pixels and centred in its
  lot, so bases stay parallel to the grid.
- **Hero car**: a white Supra (`HERO_TYPE`) marked by a floating diamond.
  It drives generated routes (`heroPlanner`): a walk along existing roads
  that never turns back or revisits a crossing, 16–24 block edges long
  (`ROUTE_EDGES`). At the destination, mid-block, it pulls over with its
  kerb-side wheels up on the kerb (`CURB`), waits `PARK_S` seconds (5) and
  pulls out on a new route from there. Routes are random on each page load.
  `HERO_ROUTE` is no longer driven or drawn; it is kept only because the
  superblock placement avoids it, and removing it would change the city.
- Other cars follow closed lane loops (right-hand traffic) with rounded
  corners. Each frame picks one of the 12 directional sprites from the car's
  heading; frames 1 / 5 / 7 / 11 match the four iso road directions.
- Cars keep a following distance, yield at crossings and stop at signalised
  intersections. Where the tile before the crossing is a crosswalk, they stop
  with the front bumper before the stripes (`CAR_HALF`, `HERO_HALF`: half a
  car length in tiles). Other cars pass the parked hero.
- **GPS phone**: a 98×164 pixel-art smartphone (status bar with the local
  time, signal, battery) whose screen shows a zoomed map (`MM_HW` × `MM_HH`
  map px per half tile) following the hero with the same easing as the main
  camera. The route is orange ahead and grey behind; the destination pin
  stays on the screen edge while the spot is off-screen; the car dot blinks
  while parked. Sized to exactly 25% of the container height (`MM_FRAC`) and
  scales smoothly: drawn at the next whole device px per art px, then
  scaled down by the browser; independent of `data-zoom`.
- **Tilt-shift**: three stacked `backdrop-filter` blur layers (1, 2.5 and
  5px) in `.pixel-city__tiltshift`, each masked to start further from a sharp
  band, plus `saturate(1.3) contrast(1.06)` on the canvas. `render()` keeps
  the band on the hero through `--tilt-focus` (% of height). Tune the blur
  and band sizes in `css/style.css`. Drawn under the vignette and the phone.
- Car positions are interpolated between path samples, and the camera and
  sprites snap to device pixels rather than art pixels, so motion stays
  smooth while every art pixel stays square and sharp.
- Ground, buildings and props are baked once in depth order. Each frame, only
  the sprites standing in front of a car are redrawn over it.

## Assets

`tools/bake.py` slices the source sheets into `assets/tiles/`,
`assets/props/` (including the three traffic-light states), `assets/buildings/` and one scaled
12-frame atlas per vehicle (`assets/vehicles/<type>/iso.png`, plus
`iso@2x.png` and the wheel overlays). Re-run it after changing a source sheet:

```bash
python3 tools/bake.py
```

The traffic cars' `iso.png` come from the 315×250 renders in each
`assets/vehicles/<type>/` folder at `CAR_SCALE` (0.34), in 53×40 cells. The
Supra's `iso.png` was made by hand from `supraWhite_0000–0011.png`:

1. rotate frames 1 and 7 by 7.1° and frames 5 and 11 by −7.1° (Pillow,
   counter-clockwise) about the image centre (the renders use a higher
   camera than the city, which put the straight-road frames at ±33.7°
   against the roads' ±26.6°);
2. resize the whole frame to 1/2.3 (137×109) with bicubic filtering;
3. crop all 12 frames to the same box, 73×41 at (32, 28);
4. make alpha binary at 128.

Every vehicle also has `iso@2x.png`, baked by `bake.py` (`HD`; the Supra's
through `supra_atlas`, with the steps above): the same cells at twice the
resolution, drawn at the same size on canvas. `city.js` uses it when the
view scale (device px per art px) is even, as at the default zoom 2, so each
atlas pixel covers whole device pixels and cars show more of the renders'
detail; otherwise it falls back to `iso.png`.

Wheels turn while a car moves. `bake.py` also writes `wheels.png` and
`wheels@2x.png` per vehicle: the same 12 cells, one row per rotation phase
(`WHEEL_PHASES`, 4), holding only the repainted wheel hubs. Each hub gets
dark notches (`WHEEL_SPOKES`: 3 on the traffic cars, 5 on the Supra's
5-spoke rims) turned a quarter notch per row, clockwise in frames that move
right on screen and counter-clockwise in those that move left. Traffic car
hubs are found automatically (`find_wheels`: the light hub a tyre encloses,
or a small hubcap on the sedan's plain black wheels); the Supra's outline
runs into its tyres, so its wheels are listed by hand (`SUPRA_WHEELS`).
`city.js` adds each car's travelled distance to `car.roll` and draws the
overlay row for it, one row every 1/`WHEEL_STEPS` (24) tiles: slower than a
real wheel, so every step reads instead of flickering. A second set of rows
repeats the phases with motion blur (each hub pixel averages the notches over
the last half notch of rotation, `WHEEL_BLUR`); cars use it above
`WHEEL_BLUR_SPEED` (0.5 tiles/s), so wheels turn sharp again as a car slows
to a stop.

Cars also hit small random road bumps: every 1–3 tiles of driving
(`BUMP_EVERY`, random per car), a run of 1, 2 or 3 bumps (`BUMP_RUN`),
0.18–0.3 s apart (`BUMP_GAP`). Each bump pops the body and wheels up
(peaking near 0.56 × `BUMP_AMP` art px, scaled by speed and a random
60–100%) and settles with a small damped dip over `BUMP_T` (0.6 s);
overlapping bumps add up. The contact shadow stays on
the road, and stopped cars don't bump.

`HERO_CELL` (73×41) in `js/city.js` matches the Supra's atlas. `HERO_PIVOT`
has one pivot per frame (the frame's silhouette centre, 5 px down), since
the renders put the car at a different height in each frame and a single
pivot left it riding toward the far kerb. Recompute it if the atlas changes.

## Run locally

```bash
python3 -m http.server 8080
```
