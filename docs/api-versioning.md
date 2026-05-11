# API Versioning Strategy

## Overview

The PolyEdge API uses URL-based versioning with header-based negotiation support. All API endpoints are prefixed with `/api/v1/`.

## Version Detection

The API supports two methods for version negotiation:

### 1. URL Prefix (Recommended)
```
GET /api/v1/health
GET /api/v1/dashboard
POST /api/v1/admin/login
```

### 2. Accept-Version Header
```bash
curl -H "Accept-Version: v1" http://localhost:8100/api/health
```

## Current Version: v1

All endpoints are available under `/api/v1/`:

- `/api/v1/health` - System health check
- `/api/v1/dashboard` - Dashboard data
- `/api/v1/admin/*` - Admin endpoints
- `/api/v1/signals` - Trading signals
- `/api/v1/trades` - Trade history
- `/api/v1/markets/*` - Market data
- `/api/v1/wallets/*` - Wallet management
- `/api/v1/settings/*` - Settings management
- `/api/v1/analytics/*` - Analytics data
- `/api/v1/brain/*` - AI brain endpoints
- `/api/v1/proposals/*` - Proposal management
- `/api/v1/activities/*` - Activity logs
- `/api/v1/errors/*` - Error tracking

## Backward Compatibility

The versioning middleware ensures backward compatibility:

- Requests without version prefix default to `v1`
- The `X-API-Version` response header indicates the version used
- Invalid versions return `400 Bad Request`

## Response Headers

All API responses include:
```
X-API-Version: v1
```

## Frontend Integration

The frontend API client automatically uses `/api/v1/` prefix:

```typescript
// frontend/src/api.ts
export const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: 15000,
})
```

## Future Versions

When introducing breaking changes:

1. Create new router modules with version suffix (e.g., `trading_v2.py`)
2. Register routers with new prefix: `app.include_router(trading_v2_router, prefix="/api/v2")`
3. Update `SUPPORTED_VERSIONS` in `backend/api/versioning.py`
4. Maintain old version for deprecation period
5. Document migration guide

## Migration from Unversioned API

Old endpoints (without version prefix) are automatically routed to v1:

```
/api/health → /api/v1/health (automatic)
/api/dashboard → /api/v1/dashboard (automatic)
```

Frontend clients should update to use explicit `/api/v1/` prefix for clarity.
