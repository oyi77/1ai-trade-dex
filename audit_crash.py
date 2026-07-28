#!/usr/bin/env python3
"""Lightning-fast crash audit: test all mutable endpoints with 3 minimal payloads."""
import os, sys, warnings, re
warnings.filterwarnings("ignore")

os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("REDIS_ENABLED", "False")
os.environ.setdefault("POLYMARKET_WS_ENABLED", "False")
os.environ.setdefault("POLYMARKET_USER_WS_ENABLED", "False")
os.environ.setdefault("LOG_LEVEL", "ERROR")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

import time
t0 = time.time()
from fastapi.testclient import TestClient
from backend.api.main import app
t1 = time.time()
print(f"App loaded: {t1-t0:.1f}s")

client = TestClient(app)

# ─── Enumerate routes ────────────────────────────────────────────────

routes = set()
for r in app.routes:
    if hasattr(r, "path"):
        for m in (getattr(r, "methods", None) or {"GET"}):
            routes.add((m, r.path))
    elif hasattr(r, "original_router"):
        ctx = getattr(r, "include_context", None)
        prefix = getattr(ctx, "prefix", "") if ctx else ""
        for sub in getattr(r.original_router, "routes", []):
            for m in (getattr(sub, "methods", None) or {"GET"}):
                fp = prefix + getattr(sub, "path", "")
                routes.add((m, fp.rstrip("/") if fp != "/" else "/"))

all_routes = sorted(routes, key=lambda x: x[1])
mutable = [(m, p) for m, p in all_routes if m in ("POST", "PUT", "PATCH")]
deletable = [(m, p) for m, p in all_routes if m == "DELETE"]
path_params = [(m, p) for m, p in all_routes if "{" in p]

print(f"Total: {len(all_routes)} | Mutable: {len(mutable)} | DELETE: {len(deletable)} | Path params: {len(path_params)}")

# ─── Test all mutable endpoints ──────────────────────────────────────
payloads = [("", "empty"), ("not json", "raw"), ("{}", "{}")]
errors = 0
total = 0

for m, p in mutable:
    for body, label in payloads:
        total += 1
        try:
            resp = client.request(m, p, data=body, headers={"Content-Type": "application/json"}, timeout=2)
            s = resp.status_code
            if s == 500:
                errors += 1
                print(f"💥 {m} {p[:60]} | {label} | 500")
            elif s not in (200, 201, 204, 400, 401, 403, 404, 409, 422):
                print(f"❌ {m} {p[:60]} | {label} | {s}")
        except Exception as e:
            print(f"⚠️  {m} {p[:60]} | {label} | {str(e)[:50]}")

# ─── Test DELETE ──────────────────────────────────────────────────────
for m, p in deletable:
    inj_p = re.sub(r"\{[^}]+\}", "99999", p)
    total += 1
    try:
        resp = client.request("DELETE", inj_p, timeout=2)
        s = resp.status_code
        if s == 500:
            errors += 1
            print(f"💥 DELETE {p[:60]} | 500")
    except:
        pass

# ─── Test path injection on GET ───────────────────────────────────────
for inj, label in [("../../../etc/passwd", "traversal"), ("1;DROP", "sqli")]:
    for m, p in path_params:
        inj_p = re.sub(r"\{[^}]+\}", inj, p)
        total += 1
        try:
            resp = client.request("GET", inj_p, timeout=2)
            s = resp.status_code
            if s == 500:
                errors += 1
                print(f"💥 GET {p[:50]} | {label} | 500")
        except:
            pass

print(f"\n{'='*50}")
print(f"RESULTS: {total} tests, {errors} crashes")
print(f"VERDICT: {'PASS' if errors == 0 else 'FAIL'}")
