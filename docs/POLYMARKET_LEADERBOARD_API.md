# Polymarket Leaderboard API - Complete Reference

## 🎯 CURRENT WORKING ENDPOINT

**Base URL:** `https://data-api.polymarket.com/v1/leaderboard`

**HTTP Method:** GET

**Status:** ✅ WORKING (verified May 6, 2026)

---

## 📋 QUERY PARAMETERS

All parameters are **optional** with sensible defaults.

| Parameter | Type | Default | Valid Values | Description |
|-----------|------|---------|--------------|-------------|
| `category` | string | `OVERALL` | `OVERALL`, `POLITICS`, `SPORTS`, `CRYPTO`, `CULTURE`, `MENTIONS`, `WEATHER`, `ECONOMICS`, `TECH`, `FINANCE` | Market category filter |
| `timePeriod` | string | `DAY` | `DAY`, `WEEK`, `MONTH`, `ALL` | Time window for rankings |
| `orderBy` | string | `PNL` | `PNL`, `VOL` | Sort by Profit/Loss or Volume |
| `limit` | integer | `25` | 1-50 | Max traders to return |
| `offset` | integer | `0` | ≥ 0 | Pagination offset |

### Example Query Strings

```
# Top 10 traders by PnL for the month
?timePeriod=MONTH&limit=10

# Top 5 crypto traders this week sorted by volume
?category=CRYPTO&timePeriod=WEEK&orderBy=VOL&limit=5

# All-time top traders with pagination
?timePeriod=ALL&limit=25&offset=0
```

---

## 📤 RESPONSE FORMAT

### Status Codes
- **200 OK** - Success, returns array of trader objects
- **400 Bad Request** - Invalid parameter (e.g., `{"error":"invalid category parameter"}`)
- **404 Not Found** - Endpoint doesn't exist or service unavailable

### Response Body

Array of trader objects (may be empty):

```json
[
  {
    "rank": "1",
    "proxyWallet": "0xbddf61af533ff524d27154e589d2d7a81510c684",
    "userName": "Countryside",
    "xUsername": "twitter_handle_or_empty_string",
    "verifiedBadge": false,
    "vol": 11195566.572048,
    "pnl": 1509979.7499813195,
    "profileImage": "https://polymarket-upload.s3.us-east-2.amazonaws.com/profile-image-XXX.png"
  },
  {
    "rank": "2",
    "proxyWallet": "0x492442eab586f242b53bda933fd5de859c8a3782",
    "userName": "0x492442EaB586F242B53bDa933fD5dE859c8A3782-1766317541188",
    "xUsername": "",
    "verifiedBadge": false,
    "vol": 5131905.086727,
    "pnl": 1139197.1220814437,
    "profileImage": ""
  }
]
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `rank` | string | Leaderboard position (1-indexed) |
| `proxyWallet` | string | 0x-prefixed Ethereum address |
| `userName` | string | Display name (may default to wallet address) |
| `xUsername` | string | Twitter/X handle or empty string |
| `verifiedBadge` | boolean | Whether account is verified |
| `vol` | number | Total trading volume (USDC) |
| `pnl` | number | Profit/Loss in USDC (can be negative) |
| `profileImage` | string | S3 URL to profile pic or empty string |

---

## 🔐 AUTHENTICATION & HEADERS

- **No authentication required** - Public endpoint
- **CORS enabled** - Can be called from browsers
- **Default Content-Type:** `application/json`

### Recommended Headers (for client requests)

```
Accept: application/json
User-Agent: Your-App/1.0
```

---

## ⚡ USAGE EXAMPLES

### Python

```python
import requests

BASE_URL = "https://data-api.polymarket.com/v1/leaderboard"

# Top 10 traders this month
response = requests.get(BASE_URL, params={
    "timePeriod": "MONTH",
    "limit": 10
})
traders = response.json()
for trader in traders:
    print(f"{trader['rank']}. {trader['userName']}: ${trader['pnl']:,.2f}")

# Specific category with pagination
response = requests.get(BASE_URL, params={
    "category": "CRYPTO",
    "timePeriod": "WEEK",
    "orderBy": "VOL",
    "limit": 25,
    "offset": 0
})
```

### JavaScript/TypeScript

```typescript
const BASE_URL = 'https://data-api.polymarket.com/v1/leaderboard';

async function getLeaderboard(options = {}) {
  const params = new URLSearchParams({
    timePeriod: options.timePeriod || 'DAY',
    category: options.category || 'OVERALL',
    orderBy: options.orderBy || 'PNL',
    limit: options.limit || 25,
    offset: options.offset || 0,
  });

  const response = await fetch(`${BASE_URL}?${params}`);
  return response.json();
}

// Usage
const topTraders = await getLeaderboard({
  timePeriod: 'MONTH',
  limit: 10
});
```

### cURL

```bash
# Month-long leaderboard
curl -s "https://data-api.polymarket.com/v1/leaderboard?timePeriod=MONTH&limit=10" | jq .

# Crypto markets, this week, sorted by volume
curl -s "https://data-api.polymarket.com/v1/leaderboard?category=CRYPTO&timePeriod=WEEK&orderBy=VOL&limit=5" | jq .

# All-time rankings with pagination
curl -s "https://data-api.polymarket.com/v1/leaderboard?timePeriod=ALL&limit=50&offset=100" | jq .
```

---

## 🚨 ERROR HANDLING

### Invalid Parameter Example

**Request:**
```
GET https://data-api.polymarket.com/v1/leaderboard?category=INVALID_CATEGORY
```

**Response (400):**
```json
{
  "error": "invalid category parameter"
}
```

### Limit Exceeded

- If `limit > 50`, Polymarket returns 50 records (capped silently)
- If `offset` is out of range, returns empty array `[]`

---

## 🔄 MIGRATION GUIDE (from old endpoints)

### ❌ OLD (NO LONGER WORKS)
```
https://data-api.polymarket.com/leaderboard?window=30d
https://polymarket.com/_next/data/build-{ID}/en/leaderboard.json
```

### ✅ NEW (USE THIS)
```
https://data-api.polymarket.com/v1/leaderboard?timePeriod=MONTH
```

**Key Changes:**
1. Path: `/leaderboard` → `/v1/leaderboard` (API versioning)
2. Parameter: `window=30d` → `timePeriod=MONTH` (enum-based)
3. Response: Direct JSON array (no Next.js wrapper)
4. No build ID required - stable URL structure

---

## 📊 RESPONSE SIZE & PERFORMANCE

- **Max records per request:** 50
- **Response size (max):** ~50KB for 50 traders
- **Pagination:** Use `offset` parameter for pages beyond first 50

**Efficient pagination pattern:**
```javascript
async function fetchAllLeaderboard(category = 'OVERALL') {
  const limit = 50;
  let offset = 0;
  let allTraders = [];
  
  while (true) {
    const response = await fetch(
      `https://data-api.polymarket.com/v1/leaderboard?category=${category}&limit=${limit}&offset=${offset}`
    );
    const batch = await response.json();
    
    if (batch.length === 0) break; // No more data
    
    allTraders.push(...batch);
    offset += limit;
  }
  
  return allTraders;
}
```

---

## 🔗 OFFICIAL DOCUMENTATION

- **Polymarket Data API Docs:** https://docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings
- **OpenAPI Spec:** https://data-api.polymarket.com/api-spec/data-openapi.yaml

---

## 📝 NOTES FOR INTEGRATION

1. **Caching:** Data updates frequently; consider caching for 1-5 minutes
2. **Rate Limiting:** No documented limits, but be respectful (max 1-2 req/sec)
3. **Fallback:** If endpoint returns 404, try alternative at `gamma-api.polymarket.com` (rarely needed)
4. **Timezone:** All rankings appear to be UTC-based
5. **Fields:** `profileImage` may be empty; gracefully handle empty strings
6. **Sorting:** `rank` field reflects the final sorted position, always trust it

