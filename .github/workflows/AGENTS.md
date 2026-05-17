<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# .github/workflows

## Purpose
GitHub Actions CI/CD workflow definitions. Contains automated build, test, and deployment pipelines for the PolyEdge project.

## Key Files

| File | Description |
|------|-------------|
| `ci.yml` | Main CI pipeline -- runs backend tests, frontend build, and linting on push/PR |
| `opencode.yml` | OpenCode integration workflow for automated code review |

## For AI Agents

### Working In This Directory
- Workflows trigger on push to `main` and on pull requests
- CI runs `pytest` for backend and `npm test` + `npm run build` for frontend
- Modify workflows with care -- changes affect all contributors
- Use `act` locally to test workflow changes before pushing

## Dependencies

### External
- GitHub Actions runtime
- `actions/checkout`, `actions/setup-python`, `actions/setup-node` -- standard actions
