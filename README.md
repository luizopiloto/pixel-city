# Pixel City

An isometric pixel-art city with animated traffic and a hero car driving
random routes, followed by the camera and a GPS phone mini-map.

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
| `data-seed` | `7` | City layout seed. |
| `data-assets` | `assets/` | Path to the assets folder. |
| `data-tiltshift` | on | `"off"` removes the tilt-shift blur. |
| `data-minimap` | — | Id of an element to hold the GPS phone. Without it, the phone sits in the bottom-right corner. |

The "Standalone preview only" rules at the end of `css/style.css` make
`index.html` fill the window; drop them when embedding.

## Run locally

```bash
python3 -m http.server 8080
```

Then open http://localhost:8080.

## Assets

`tools/bake.py` builds the sprites the page uses (tiles, props, buildings,
vehicle atlases and wheel animations) from the source images in `assets/`.
Re-run it after changing a source image:

```bash
python3 tools/bake.py
```

## License

MIT
