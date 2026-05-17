<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# polyedge-docs

## Purpose
Docusaurus-based documentation site for PolyEdge. Deployed at `https://polyedge.aitradepulse.com/docs/`. Contains user-facing guides, API reference, strategy documentation, admin docs, and static assets (paper PDFs, pitch deck).

## Key Files

| File | Description |
|------|-------------|
| `docusaurus.config.ts` | Docusaurus site configuration -- theme, navbar, footer, plugins |
| `sidebars.ts` | Sidebar navigation structure |
| `package.json` | Node.js dependencies and scripts |
| `tsconfig.json` | TypeScript configuration |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `docs/` | Documentation content (Markdown files) |
| `src/` | React components, pages, and CSS |
| `static/` | Static assets -- images, paper PDFs, pitch deck |
| `build/` | Generated build output (do NOT edit) |

## For AI Agents

### Working In This Directory
- Run `npm install` then `npm start` for local dev server
- Build with `npm run build` -- output goes to `build/`
- `onBrokenLinks: 'throw'` means broken links will fail the build
- Route base path is `/` (docs served at root of the site)
- Dark mode is the default theme with `respectPrefersColorScheme: true`
- Prism supports: python, bash, json, yaml, docker syntax highlighting

### Testing Requirements
- `npm run build` must succeed (catches broken links)
- Verify new pages appear in sidebar navigation

## Dependencies

### External
- `@docusaurus/core` -- Static site generator
- `@docusaurus/preset-classic` -- Standard preset
- `prism-react-renderer` -- Code syntax highlighting
- Node.js 18+
