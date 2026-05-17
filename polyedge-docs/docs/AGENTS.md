<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# polyedge-docs/docs

## Purpose
Documentation content for the Docusaurus site. All Markdown files that become pages on the deployed site. Organized by topic: getting started, architecture, strategies, admin, dashboard, configuration, API reference, and research.

## Key Files

| File | Description |
|------|-------------|
| `intro.md` | Landing page / introduction |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `getting-started/` | Quick start guides for traders and developers |
| `architecture/` | System architecture, data flow, deployment, job queue |
| `strategies/` | Individual strategy documentation (9 strategies) |
| `admin/` | Admin panel documentation (14 pages) |
| `dashboard/` | Dashboard tab documentation (13 pages) |
| `configuration/` | Environment variables, feature flags, risk settings |
| `api-reference/` | REST API endpoint reference (12 pages) |
| `research/` | Research notes and pitch deck |

## For AI Agents

### Working In This Directory
- Each subdirectory has a `_category_.json` for sidebar ordering
- Follow Docusaurus frontmatter conventions for page metadata
- `onBrokenLinks: 'throw'` -- all internal links must resolve
- Use relative links between docs pages
- Run `npm run build` from `polyedge-docs/` to verify no broken links

### Common Patterns
- Each `.md` file becomes a route under `/docs/`
- Sidebar order controlled by `_category_.json` in each directory
- Code blocks use language tags (```python, ```bash, ```json)
