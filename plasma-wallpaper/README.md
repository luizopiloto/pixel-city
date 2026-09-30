# Web Paper (Plasma 6 wallpaper)

A KDE Plasma 6 wallpaper plugin that shows a web page, by default
[Pixel City](https://luizopiloto.github.io/pixel-city/).

- Pauses the page while a maximized or full-screen window covers the screen
  (same virtual desktop and activity), so it costs no CPU or GPU there; it
  picks up again when the window goes. An option in the settings.
- Keeps the page's storage and HTTP cache on disk, so it opens faster and
  Pixel City remembers the quality tier it chose. Each screen's wallpaper has
  its own profile (`webpaper-<id>`, the id kept in that wallpaper's settings):
  two profiles with one name in the same process clash and lose their data.
- Retries every 30 s if the page fails to load (no network yet at login).
- Muted, no scroll bars.
- Locked down for a desktop background: no browser context menu, no
  alert/confirm/prompt, file, color or login dialogs, no tooltips, no new
  windows, no navigating from a dropped file, and the page can't leave the
  configured site (redirects still work). Every permission request (camera,
  microphone, location, notifications, screen sharing…) is denied, and
  downloads are refused.

Settings: URL, zoom (pixel art stays sharp at 100%, 200%, 300%), reload
interval, pause under windows. Pixel City's own switches go in the URL:
`?quality=low` on a weak machine, `?seed=123` for the same city every time.

Needs Plasma 6 with Qt 6.8 or newer, and Qt WebEngine for QML (`qt6-webengine` on Arch,
`qml6-module-qtwebengine` on Debian/Ubuntu, `qt6-qtwebengine` on Fedora).
Full install, update and uninstall steps are in the
[main README](../README.md#kde-plasma-wallpaper).

## Install / update

```bash
kpackagetool6 --type Plasma/Wallpaper --install plasma-wallpaper    # first time
kpackagetool6 --type Plasma/Wallpaper --upgrade plasma-wallpaper    # after changes
```

Run these from the repository folder. Then right-click the desktop,
**Configure Desktop and Wallpaper…**, and set **Wallpaper type** to **Web
Paper**. After an upgrade, restart Plasma to load the new code:
`systemctl --user restart plasma-plasmashell`.
