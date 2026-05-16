# Dependency Audit Report

**Date:** 2026-05-17
**Branch:** feature/plugin-system-refactoring
**Auditor:** w2-deps (automated)

---

## Version Comparison

### Core Backend (Pinned)

| Package | Current | Latest | Delta | Risk |
|---------|---------|--------|-------|------|
| fastapi | 0.115.6 | 0.136.1 | +20 minor | LOW |
| starlette | >=0.35.0,<1.0.0 | 1.0.0 | major available | MEDIUM |
| uvicorn | 0.34.0 | 0.47.0 | +13 minor | LOW |
| sqlalchemy | 2.0.36 | 2.0.49 | +13 patch | LOW |
| psycopg2-binary | 2.9.9 | 2.9.12 | +3 patch | LOW |
| pydantic | 2.10.4 | 2.13.4 | +3 minor | LOW |
| pydantic-settings | 2.7.1 | 2.14.1 | +7 minor | LOW |

### Data & Science (Pinned)

| Package | Current | Latest | Delta | Risk |
|---------|---------|--------|-------|------|
| numpy | 1.26.4 | 2.4.5 | **MAJOR** | **HIGH** |
| pandas | 2.2.3 | 3.0.3 | **MAJOR** | **HIGH** |
| scipy | 1.14.1 | 1.17.1 | +3 minor | MEDIUM |
| orjson | 3.10.14 | 3.11.9 | +1 minor | LOW |

### Data Fetching (Pinned/Range)

| Package | Current | Latest | Delta | Risk |
|---------|---------|--------|-------|------|
| aiohttp | 3.11.11 | 3.13.5 | +2 minor | MEDIUM |
| httpx | >=0.26.0,<0.28.0 | 0.28.1 | range ceiling hit | LOW |
| cryptography | >=42.0.0 | 48.0.0 | +6 major | MEDIUM |
| websockets | >=12.0 | 16.0 | +4 major | MEDIUM |

### Scheduling & Utils (Pinned)

| Package | Current | Latest | Delta | Risk |
|---------|---------|--------|-------|------|
| apscheduler | 3.10.4 | 3.11.2 | +1 minor | LOW |
| python-dotenv | 1.0.1 | 1.2.2 | +2 minor | LOW |

### Range-Specified (Not Pinned)

| Package | Spec | Latest | Notes |
|---------|------|--------|-------|
| anthropic | >=0.40.0 | 0.102.0 | Large gap, no pin |
| groq | >=0.4.0 | 1.2.0 | Major available |
| loguru | >=0.7.0 | 0.7.3 | Current |
| structlog | >=24.1.0 | 25.5.0 | +1 year |
| eth-account | >=0.11.0 | 0.13.7 | +2 minor |
| redis | >=5.0.0 | 7.4.0 | **2 majors ahead** |
| arq | >=0.25.0 | 0.28.0 | +3 minor |
| ruff | >=0.3 | 0.15.13 | Very far behind |
| scikit-learn | >=1.3.2 | 1.8.0 | +5 minor |
| pytest | >=8.0 | 9.0.3 | major available |
| pytest-asyncio | >=0.23 | 1.3.0 | major available |
| psutil | >=5.9.0 | 7.2.2 | **2 majors ahead** |
| prometheus-client | >=0.20.0 | 0.25.0 | +5 minor |
| joblib | >=1.3.0 | 1.5.3 | +2 minor |
| cachetools | >=5.3.3 | 7.1.2 | **2 majors ahead** |
| slowapi | >=0.1.9 | 0.1.9 | Current |
| pybreaker | >=1.0.0 | 1.4.1 | +4 minor |
| feedparser | >=6.0.0 | 6.0.12 | Current |

---

## Known CVEs (Current Versions)

### aiohttp 3.11.11 -- ALL FIXED in current version

| CVE/Advisory | Severity | Description | Fixed In |
|--------------|----------|-------------|----------|
| GHSA-27mf-ghqm-j3j8 | Medium | Memory leak with middleware on non-allowed methods | 3.10.11 |
| GHSA-2vrm-gr82-f7m5 | Medium | CRLF injection via multipart content-type header | 3.13.4 |
| GHSA-3wq7-rqq7-wx6j | Medium | Late size enforcement for non-file multipart fields (memory DoS) | 3.13.4 |
| GHSA-45c4-8wx5-qw6w | High | HTTP request smuggling via llhttp parser | 3.8.5 |
| GHSA-54jq-c3m8-4m76 | Low | Brute-force leak of internal static file path components | 3.13.3 |

**Note:** Current version 3.11.11 has fixes for 3.8.5 and 3.10.11 CVEs but is **VULNERABLE** to GHSA-2vrm-gr82-f7m5 and GHSA-3wq7-rqq7-wx6j (fixed in 3.13.4) and GHSA-54jq-c3m8-4m76 (fixed in 3.13.3).

### fastapi 0.115.6 -- No active CVEs

| Advisory | Description | Fixed In |
|----------|-------------|----------|
| GHSA-8h2j-cgx8-6xv7 | CSRF vulnerability | 0.65.2 |
| PYSEC-2024-38 | Security issue | 0.109.1 |

Both are patched in 0.115.6. No active vulnerabilities.

### pydantic 2.10.4 -- No active CVEs

All known CVEs (GHSA-5jqp-qgf6-3pvh, GHSA-mr82-8j83-vxmv) affect v1.x only. v2.x is clean.

### uvicorn 0.34.0 -- No active CVEs

All known CVEs (GHSA-33c7-2mpw-hg34, GHSA-f97h-2pfx-f59f) are ancient, fixed in 0.11.7.

### sqlalchemy 2.0.36 -- No active CVEs

All known CVEs are from pre-2.0 era (SQL injection in 1.x). 2.x is clean.

### starlette (pinned range >=0.35.0,<1.0.0)

| Advisory | Severity | Description | Fixed In |
|----------|----------|-------------|----------|
| GHSA-2c2j-9gv5-cj73 | Medium | DoS via large multipart file parsing | 0.47.2 |
| GHSA-7f5h-v6xp-fcq8 | Medium | O(n^2) DoS via Range header in FileResponse | 0.49.1 |

Current range allows vulnerable versions. Should pin minimum to >=0.49.1.

### cryptography (pinned >=42.0.0)

| Advisory | Severity | Description | Fixed In |
|----------|----------|-------------|----------|
| GHSA-39hc-v87j-747x | High | Vulnerable OpenSSL in wheels | 38.0.3 |
| GHSA-79v4-65xg-pq4g | High | Vulnerable OpenSSL in wheels | 44.0.1 |
| GHSA-6vqw-3v5j-54x4 | Medium | NULL pointer deref in pkcs12 | 42.0.4 |

Current floor (42.0.0) is vulnerable to GHSA-79v4-65xg-pq4g (fixed in 44.0.1). **Should raise floor to >=44.0.1.**

### numpy 1.26.4 -- No active CVEs

All known CVEs are from pre-1.19 era. Current version is clean.

### httpx (pinned >=0.26.0,<0.28.0) -- No active CVEs

GHSA-h8pj-cxx2-jfg2 fixed in 0.23.0. Current range is clean.

### Other packages -- No known active CVEs

pandas, scipy, orjson, python-dotenv, apscheduler, redis, psutil, websockets: No CVEs affecting current pinned versions.

---

## Breaking Changes to Watch

### CRITICAL -- Major Version Jumps (Require Careful Migration)

#### numpy 1.26.4 -> 2.4.5 (HIGH RISK)
- **ABI break** -- compiled extensions must be rebuilt
- Type promotion rules changed
- Many deprecated APIs removed
- `numpy.string_` removed, use `numpy.bytes_`
- `numpy.bool` removed, use Python `bool`
- Random module API changes
- **Recommendation:** Stay on 1.26.x unless numpy 2.x features are needed. If upgrading, follow [numpy-2-migration-guide](https://numpy.org/devdocs/numpy_2_0_migration_guide.html).

#### pandas 2.2.3 -> 3.0.3 (HIGH RISK)
- **Copy-on-Write is now default** (no more SettingWithCopyWarning)
- Dedicated string dtype by default (object -> StringDtype)
- Datetime resolution inference changes
- Many deprecated APIs from 2.x removed
- **Recommendation:** Upgrade to pandas 2.3 first, resolve all deprecation warnings, then move to 3.0.

#### starlette (range -> 1.0.0) (MEDIUM RISK)
- Starlette 1.0.0 is a new major release
- Current range cap (<1.0.0) prevents accidental upgrade
- **Recommendation:** Keep range constraint until starlette 1.x stabilizes. Raise minimum to >=0.49.1 for CVE fixes.

### MODERATE -- Minor Version Gaps

#### fastapi 0.115.6 -> 0.136.1 (LOW RISK)
- Backward compatible within 0.x series
- FastAPI 0.136.1 explicitly updates Pydantic v2 code for deprecations
- No breaking API changes reported
- **Recommendation:** Safe to upgrade. FastAPI follows semver within 0.x with backward compatibility.

#### uvicorn 0.34.0 -> 0.47.0 (LOW RISK)
- Minor features and bug fixes only
- No breaking changes in release notes
- **Recommendation:** Safe to upgrade.

#### pydantic 2.10.4 -> 2.13.4 (LOW RISK)
- Bug fixes and minor improvements
- v2.13.0 includes some non-breaking changes per pydantic versioning policy
- FastAPI 0.136.1 already updated for pydantic 2.13 deprecations
- **Recommendation:** Safe to upgrade alongside fastapi.

#### pydantic-settings 2.7.1 -> 2.14.1 (LOW RISK)
- Tied to pydantic version
- **Recommendation:** Upgrade with pydantic.

#### aiohttp 3.11.11 -> 3.13.5 (MEDIUM RISK)
- Security fixes in 3.13.3 and 3.13.4 are critical
- New features: `max_headers`, `dns_cache_max_size` parameters
- Bug fixes for cookie parsing, proxy auth
- **Recommendation:** Upgrade promptly for security fixes.

#### scipy 1.14.1 -> 1.17.1 (LOW RISK)
- Minor releases, backward compatible
- **Recommendation:** Safe to upgrade.

#### cryptography >=42.0.0 -> >=44.0.1 (LOW RISK)
- Raise floor version for OpenSSL vulnerability fix
- **Recommendation:** Change minimum to >=44.0.1.

### LOW RISK -- Patch/Minor Gaps

| Package | Current -> Latest | Notes |
|---------|-------------------|-------|
| sqlalchemy | 2.0.36 -> 2.0.49 | Bug fixes only, safe |
| psycopg2-binary | 2.9.9 -> 2.9.12 | Patch fixes, safe |
| orjson | 3.10.14 -> 3.11.9 | Minor features, safe |
| python-dotenv | 1.0.1 -> 1.2.2 | Minor features, safe |
| apscheduler | 3.10.4 -> 3.11.2 | Minor features, safe |

---

## Recommended Upgrade Path

**Order matters due to dependency chains.** Upgrade in phases:

### Phase 1: Security Patches (Do First -- Low Risk)
1. **aiohttp** 3.11.11 -> 3.13.5 (security: CRLF injection, memory DoS)
2. **starlette** raise floor to >=0.49.1 (security: DoS via Range header)
3. **cryptography** raise floor to >=44.0.1 (security: vulnerable OpenSSL)
4. **sqlalchemy** 2.0.36 -> 2.0.49 (bug fixes, safe)

### Phase 2: Core Stack (Low-Medium Risk)
5. **pydantic** 2.10.4 -> 2.13.4 (before fastapi, since fastapi depends on it)
6. **pydantic-settings** 2.7.1 -> 2.14.1 (with pydantic)
7. **fastapi** 0.115.6 -> 0.136.1 (after pydantic, already adapted for 2.13)
8. **uvicorn** 0.34.0 -> 0.47.0 (with fastapi)

### Phase 3: Utility Packages (Low Risk)
9. **psycopg2-binary** 2.9.9 -> 2.9.12
10. **orjson** 3.10.14 -> 3.11.9
11. **python-dotenv** 1.0.1 -> 1.2.2
12. **apscheduler** 3.10.4 -> 3.11.2
13. **scipy** 1.14.1 -> 1.17.1

### Phase 4: Major Version Migrations (High Risk -- Plan Carefully)
14. **pandas** 2.2.3 -> 2.3.x first, then evaluate 3.0.x
15. **numpy** 1.26.4 -> evaluate need for 2.x (only if pandas 3.0 or scipy 1.17 requires it)

### Deferred (Monitor)
- **httpx** 0.28.1 just hit the range ceiling; update range to <0.29.0 when ready
- **redis** 7.4.0 is 2 majors ahead of floor; evaluate when upgrading Redis server
- **psutil** 7.2.2 is 2 majors ahead; evaluate when needed
- **cachetools** 7.1.2 is 2 majors ahead; evaluate when needed

---

## Risk Assessment Summary

| Risk Level | Packages |
|------------|----------|
| **HIGH** | numpy (1.x -> 2.x ABI break), pandas (2.x -> 3.x API changes) |
| **MEDIUM** | aiohttp (security gaps in current), starlette (CVE in range), cryptography (CVE in floor), scipy (3 minor versions), websockets (4 majors ahead) |
| **LOW** | fastapi, uvicorn, sqlalchemy, pydantic, pydantic-settings, psycopg2-binary, orjson, python-dotenv, apscheduler, httpx |

---

## Immediate Actions Required

1. **aiohttp 3.11.11 has 2 unpatched CVEs** (CRLF injection, memory DoS) -- upgrade to 3.13.5
2. **starlette range allows vulnerable versions** -- raise floor to >=0.49.1
3. **cryptography floor is too low** -- raise to >=44.0.1
4. Everything else can be upgraded on a regular cadence

---

*Generated by automated dependency audit. CVE data sourced from OSV database. Version data from PyPI.*
