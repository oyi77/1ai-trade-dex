<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# frontend/public

## Purpose
Static assets served directly by the web server. Contains the PWA manifest, favicon, and app icons used by browsers, mobile devices, and the service worker for offline caching.

## Key Files

| File | Description |
|------|-------------|
| `manifest.json` | PWA web app manifest — app name "PolyEdge Trading Terminal", standalone display mode, dark theme (#0b0e14 background, #1e90ff theme), icon references |
| `favicon.svg` | SVG favicon for browser tabs — scalable vector format |
| `icon-192.png` | PWA icon at 192x192 resolution — used by mobile home screens and splash screens |
| `icon-512.png` | PWA icon at 512x512 resolution — used for app stores and high-DPI displays |

## For AI Agents

### Working In This Directory
- Files here are served at the root URL path (`/favicon.svg`, `/icon-192.png`, etc.)
- The service worker (`src/sw.ts`) caches these assets for offline access
- `manifest.json` is referenced by `index.html` via `<link rel="manifest">`
- New static assets (fonts, images, icons) go here — not in `src/`

### Common Patterns
- Icons should be provided in both PNG (for compatibility) and SVG (for scalability)
- Manifest follows the W3C Web App Manifest specification
- Background color `#0b0e14` matches the app's dark/noir theme

## Dependencies

### Internal
- `../index.html` — references `manifest.json` and `favicon.svg`
- `../src/sw.ts` — service worker caches these static assets

### External
- W3C Web App Manifest specification
