<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# docs/runbook

## Purpose

Operations runbook for deploying, monitoring, and troubleshooting PolyEdge. Provides step-by-step procedures for deployment, incident response, rollback operations, and system recovery.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Runbook overview and documentation index with links to operational procedures |
| `deployment.md` | Railway backend + Vercel frontend deployment steps with environment variable checklist and pre/post deployment validation |
| `rollback.md` | Git revert, DB migration rollback, and PM2 restart procedures for system recovery |
| `incidents.md` | Alert types, severity levels, triage flows, and postmortem templates for incident response |
| `circuit-breaker-runbook.md` | Circuit breaker behavior documentation, trip conditions, and manual reset procedures |

## For AI Agents

### Working In This Directory
- Documentation follows markdown format with clear navigation structure
- Each operational document includes checklists and step-by-step procedures
- Deployment documentation includes both pre-flight checks and post-deployment validation
- Incident response templates ensure consistent postmortem documentation
- Circuit breaker documentation explains automated and manual reset procedures

### Testing Requirements
- Validate deployment checklists with actual deployment procedures
- Test rollback procedures in staging environment
- Verify incident response flows with simulated alert scenarios
- Confirm circuit breaker reset procedures work as documented

### Common Patterns
- Use consistent table format for documentation links and checklists
- Include command-line examples for deployment and rollback operations
- Document environment variable requirements and validation steps
- Provide clear severity levels for incident classification
- Include both automated and manual procedures for critical operations

## Dependencies

### Internal
- `railway.json` - Railway deployment configuration referenced in deployment.md
- `vercel.json` - Vercel frontend configuration referenced in deployment.md
- `.env.example` - Environment variable template referenced in deployment.md

### External
- `railway.app` - Backend deployment platform
- `vercel.com` - Frontend hosting platform
- `github.com` - Version control and deployment trigger