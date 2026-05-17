<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# polyedge-docs/static

## Purpose
Static assets served by the Docusaurus site. Contains images, research paper PDFs, and the pitch deck.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `img/` | Site images -- logo, favicon, social card, illustrations |
| `paper/` | Research paper PDFs and abstract video |
| `pitchdeck/` | Pitch deck HTML and PDF |

## Key Files

| File | Description |
|------|-------------|
| `.nojekyll` | Prevents GitHub Pages Jekyll processing |

## For AI Agents

### Working In This Directory
- Files here are served at the site root (e.g., `/docs/img/logo.svg`)
- Referenced by `docusaurus.config.ts` for favicon, social card, etc.
- Keep file sizes reasonable for web delivery
