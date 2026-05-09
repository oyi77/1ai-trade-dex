<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# docs

## Purpose
Project documentation — architecture decision records, API reference, operational runbooks, research notes, and user-facing guides. Docusaurus docs deploy inside the Vercel frontend under `/docs/`.

## Key Files

| File | Description |
|------|-------------|
| `api.md` | REST API endpoint reference — update when adding/changing endpoints |
| `configuration.md` | Environment variable reference and feature flag guide |
| `how-it-works.md` | System overview for non-technical readers |
| `user-guide.md` | End-user dashboard guide |
| `data-sources.md` | Market data source descriptions and update frequencies |
| `mirofish-integration.md` | MiroFish dual-debate system integration guide |
| `SYSTEM_FLOW.md` | End-to-end signal → trade flow diagram |
| `ONBOARDING.md` | New developer onboarding checklist |
| `CHANGELOG.md` | Release history |
| `IMPLEMENTATION_ROADMAP_AGI_ENHANCEMENTS.md` | AGI enhancement roadmap |
| `api-versioning.md` | API versioning policy |
| `fee-calculation.md` | Exchange fee calculation methodology |
| `validation-implementation.md` | Input validation implementation notes |
| `postgresql-migration-plan.md` | Future PostgreSQL migration plan (not yet executed) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `architecture/` | Architecture Decision Records (ADRs) and structural docs (see `architecture/AGENTS.md`) |
| `runbook/` | Operational runbooks — deployment, rollback, incident response (see `runbook/AGENTS.md`) |
| `development/` | Developer guides — testing, local setup |
| `operations/` | Operations guides — deployment, monitoring, reliability, scalability |
| `agi-log/` | AGI experiment and decision logs |
| `audit-reports/` | Security and system audit reports |
| `paper/` | Research papers and academic references |
| `archive/` | Superseded documentation |

## For AI Agents

### Working In This Directory
- **`docs/api.md` must be updated whenever an API endpoint is added, changed, or removed** — it is the authoritative REST API reference.
- **ADRs in `architecture/` are immutable once accepted** — new decisions get new ADR numbers; never edit an accepted ADR's Decision section.
- `CHANGELOG.md` follows Keep a Changelog format — add entries under `[Unreleased]` during development.
- Docusaurus builds from this directory; files must be valid Markdown. Broken links will fail the Vercel build.
- `archive/` is for superseded docs — move, don't delete, when replacing documentation.

### Common Patterns
- New architectural decision: create `architecture/adr-NNN-short-title.md` using the template in `architecture/AGENTS.md`
- New endpoint: add to `docs/api.md` under the appropriate router section
- New env var: add to `docs/configuration.md` and `.env.example` simultaneously

## Dependencies

### Internal
- `../AGENTS.md` — root agent guidance
- `../.env.example` — env var template kept in sync with `configuration.md`

### External
- Docusaurus — static site generator for `/docs/` deployment on Vercel
