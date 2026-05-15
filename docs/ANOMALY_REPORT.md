# PolyEdge Codebase Anomaly Report

**Generated**: 2026-05-15  
**Scope**: Backend (`backend/`) and root config  
**Methodology**: Parallel agent exploration + direct AST/grep verification  
**Classification**: 2 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW, 3 INFO

---

## Executive Summary

A non-trivial anomaly was found: **config.py calls `eval()` on environment variables** for `dict`/`list` types (line 79).  
If an attacker can control environment variables, or if a deployment pipeline injects untrusted config, this is **remote code execution**.  
Additionally, `strategy_synthesizer.py:279` calls `exec()` on **LLM-generated strategy code** without sandboxing.  
Both should be treated as exploitable.

---

## CRITICAL

### [CRIT-001] RCE via `eval()` in config.py — Environment Variable Injection

- **File**: `backend/config.py:79`
- **Code**:
  ```python
  elif isinstance(default, (dict, list)):
      try:
          setattr(self, name, eval(env_val))
      except Exception:
          setattr(self, name, default)
  ```
- **Risk**: Any env var typed as `dict` or `list` in config is evaluated with `eval()`.  
  If an attacker controls env vars (e.g., via `.env`, CI/CD, or Docker secrets), they can inject arbitrary Python code.
- **Exploitability**: High. Requires env var control, but config is loaded at startup.
- **Fix**: Replace `eval(env_val)` with `json.loads(env_val)`  
  Or, if users truly need non-JSON literals, restrict to `ast.literal_eval()`.
- **Impact**: System compromise, wallet key theft, unauthorized trades.

### [CRIT-002] RCE via `exec()` on LLM-Generated Strategy Code

- **File**: `backend/core/strategy_synthesizer.py:279`
- **Code**:
  ```python
  exec(compile(code, "<generated>", "exec"), module.__dict__)  # noqa: S102
  ```
- **Risk**: The `StrategySynthesizer` (part of AGI meta-strategy pipeline) compiles and executes **LLM-generated Python code** in the same process.  
  If an LLM is adversarial, or if jailbreaks produce malicious code, arbitrary commands run inside the trading engine.
- **Exploitability**: Moderate-High. AGI autonomy pipeline generates code automatically. A poisoned LLM output or prompt injection can weaponize this.
- **Fix**: **Do NOT exec LLM code in-process.**  
  Options:
  1. Run generated strategy code in a **sandboxed subprocess** (seccomp, gVisor, or restricted Python interpreter).
  2. Use **ast-based static checks** before exec to block imports, network, and file-system access.
  3. Restrict `__builtins__` and override it with a safe dict, but this is not foolproof.
- **Impact**: Full system compromise, wallet key theft, unauthorized trades.

---

## HIGH

### [HIGH-001] SQL Injection via `text()` with String Interpolation

- **Files**:
  - `backend/models/database.py:2002`
  - `backend/models/database.py:2029`
- **Code**:
  ```python
  conn.execute(text(f"ALTER TABLE strategy_proposal ADD COLUMN {col} {col_type}"))
  conn.execute(text(f"ALTER TABLE genome_registry ADD COLUMN {col} {coltype}"))
  ```
- **Risk**: Column names/types are interpolated into raw SQL strings.  
  If these values ever come from user input (e.g., an admin endpoint or AGI-generated schema), arbitrary SQL can be injected.
- **Fix**: Use SQLAlchemy `Column` types or escape identifiers via `sqlalchemy.sql.expression.literal_column()`.  
  Never interpolate into `text()`.
- **Impact**: Database corruption, data exfiltration, or deletion of trades/positions.

### [HIGH-002] Command Injection via `create_subprocess_exec` in Auth Endpoint

- **File**: `backend/api/auth.py:574`
- **Code**:
  ```python
  _proc = await _asyncio.create_subprocess_exec(
      "pm2",
      "restart",
      "polyedge-bot",
      stdout=_asyncio.subprocess.PIPE,
      stderr=_asyncio.subprocess.PIPE,
  )
  ```
- **Risk**: The endpoint restarts `polyedge-bot` via `pm2`. If the binary path or service name is somehow controlled, or if the service name collides with user input, this could lead to arbitrary command execution or a DoS loop.
- **Fix**: Hard-code the absolute path to `pm2`, sanitize/whitelist the service name, and add rate-limiting.
- **Impact**: Process restarts, potential denial of service.

### [HIGH-003] Insecure JSON Parsing with `json.loads()` on Untrusted Data

- **Files**: Widely distributed (30+ files)
- **Code** (typical):
  ```python
  clob_token_ids = json.loads(clob_token_ids)
  prices = json.loads(prices)
  ```
- **Risk**: Many `json.loads()` calls ingest data from **external APIs** (Polymarket, Kalshi, Coingecko) without schema validation. A malformed payload can crash the strategy executor or corrupt downstream data.
- **Fix**: Wrap all external `json.loads()` with **schema validation** (Pydantic `BaseModel`, `voluptuous`, or `jsonschema`).
- **Impact**: Service crashes, incorrect trade data, potential type confusion bugs.

---

## MEDIUM

### [MED-001] `# type: ignore` and `# noqa` Suppress Safety Checks

- **Files**:
  - `backend/config.py:1232–1233`
  - `backend/core/distributed_lock.py:110, 118`
- **Details**:
  ```python
  MAX_TRADES_PER_SCAN: int = int(os.getenv("MAX_TRADES_PER_SCAN", "10"))  # type: ignore[assignment]
  from backend.config import settings  # type: ignore
  import redis  # type: ignore
  ```
- **Risk**: Type suppressions hide bugs during migration or refactoring. `distributed_lock.py` suppressing `redis` import at top-level could mask deployment issues.
- **Fix**: Remove unnecessary `# type: ignore` comments. Add missing dependency stubs. Fix the underlying type errors.

### [MED-002] `try/except` with `Exception` as Backtest Gate

- **File**: `backend/core/strategy_synthesizer.py:266–273`
- **Code**:
  ```python
  try:
      ...
  except Exception as e:
      logger.warning("[StrategySynthesizer] Backtest gate skipped for '%s'...")
      return {"passed": True, "reason": f"skipped:{e}", ...}
  ```
- **Risk**: A broad `except Exception` silently treats **any** backtest failure as a pass. A real bug (e.g., syntax error, import error, division by zero) would be masked.
- **Fix**: Narrow exception types to expected cases (e.g., `NoHistoricalDataError`, `MissingDataError`). Let unexpected exceptions propagate and trigger alerts.

### [MED-003] Potential JSON-Injection / Data Integrity Risk via `eval()` Fallback

- **File**: `backend/config.py:79` (same as CRIT-001, related context)
- **Details**: Even if env inputs are trusted, `eval()` prevents proper serialization. If config is ever sent over a network (REST API response, dashboard config), `eval()` results can contain non-serializable types.
- **Fix**: Use `json.loads()` or `ast.literal_eval()` for deterministic parsing.

### [MED-004] Missing Lock Around State Mutation in `scheduler.py`

- **File**: `backend/core/scheduler.py:248`
- **Code**:
  ```python
  def load_scheduler_state(sched: AsyncIOScheduler) -> int:
      restored = 0
      try:
          from backend.models.database import SessionLocal
  ```
- **Risk**: The scheduler state is loaded without explicit concurrency control. Multiple async tasks may call this simultaneously during hot-reloads or AGI promotion events.
- **Fix**: Add an `asyncio.Lock` guard around `sched.add_job()` and state mutations.

---

## LOW

### [LOW-001] `AGI_HEALTH_CHECK_ENABLED` and `AGI_HEALTH_CHECK_INTERVAL_MINUTES` Hardcoded vs Config

- **Finding**: The `.env.example` sets `AGI_HEALTH_CHECK_ENABLED=True` and `AGI_HEALTH_CHECK_INTERVAL_MINUTES=15`. The code reads from config. No anomaly per se, but if `AGI_HEALTH_CHECK_ENABLED` is disabled accidentally, strategies with <30% win rate may not be auto-killed, violating AGENTS.md governance rule.
- **Recommendation**: Add a startup warning log if `AGI_HEALTH_CHECK_ENABLED` is set to `False` in any non-test deployment.

### [LOW-002] `WALLET_FERNET_KEY` Empty in `.env.example`

- **File**: `.env.example:1151`
- **Finding**: `WALLET_FERNET_KEY=` is empty. The app may silently skip wallet encryption if no key is provided, leaving private keys unencrypted.
- **Recommendation**: Add a startup assertion that `WALLET_FERNET_KEY` is set in production, or refuse to start if wallet-related features are enabled without it.

### [LOW-003] `except Exception:` Without Specific Logging in `auth.py`

- **File**: `backend/api/auth.py:583`
- **Code**:
  ```python
  except Exception as _e:
      logger.warning(f"Could not restart polyedge-bot: {_e}")
  ```
- **Risk**: Broad exception swallowing. Any failure to restart (including OOM, missing `pm2`, or permission denied) is only logged as `warning`.
- **Fix**: Use `logger.exception()` for richer stack traces, or limit the `except` to `subprocess.SubprocessError`.

---

## INFO (Observations)

### [INFO-001] `json.loads()` from database `json.loads(self.fitness_json)` — Trusted?

- **Files**: Many ORM property methods (e.g., `backend/models/database.py:381–421`)
- **Finding**: `json.loads()` is used to deserialize JSON columns from the **database**, which is internal/trusted. No direct risk unless DB is compromised. Marked as INFO.

### [INFO-002] `pickle` replaced by `joblib`

- **File**: `backend/ai/training/model_trainer.py:60`
- **Comment**: `# Security: joblib.dump() replaces pickle.dump() — avoids RCE`
- **Finding**: Good security awareness. Note that `joblib` itself may still use `pickle` under the hood for some types, but it's an improvement over raw `pickle`.

### [INFO-003] `redis.eval()` Used for Atomic Lock Release

- **File**: `backend/core/distributed_lock.py:211`
- **Code**:
  ```python
  result = self._redis_client.eval(lua, 1, self._key, self._token)
  ```
- **Finding**: This is a standard Redis Lua atomic check-and-delete pattern. It is **correct** and **safe** for lock management. No anomaly.

---

## Positive Findings (No Anomalies)

| Check | Result |
|---|---|
| Bare `except: pass` in backend | **NONE FOUND** — good hygiene |
| `TODO`/`FIXME`/`HACK` in source | **NONE FOUND** — clean production code |
| Raw `subprocess.call(shell=True)` | **NONE FOUND** — uses `create_subprocess_exec` (safe list syntax) |
| `os.system()` in production code | **NONE FOUND** (only in tests) |

---

## Remediation Priority

| Priority | ID | Remediation | Effort |
|---|---|---|---|
| **P0** | CRIT-001 | Replace `eval()` with `ast.literal_eval()` or `json.loads()` in config.py | 1 hour |
| **P0** | CRIT-002 | Sandbox `exec()` in strategy synthesizer (subprocess or AST restrictions) | 1–2 days |
| **P1** | HIGH-001 | Use SQLAlchemy column types OR escape identifiers in migrations | 2 hours |
| **P1** | HIGH-002 | Sanitize `pm2 restart` params or harden auth endpoint | 30 min |
| **P1** | HIGH-003 | Add Pydantic schema validation for external API JSON payloads | 3–5 hours |
| **P2** | MED-004 | Add `asyncio.Lock` around scheduler state mutations | 1 hour |
| **P2** | MED-001 | Remove unnecessary `# type: ignore` / `# noqa` suppressions | 1 hour |
| **P2** | MED-002 | Narrow `except Exception` in strategy synthesizer to specific errors | 30 min |

---

## Verification Evidence

- All findings were verified by direct `read` of source files.  
- Grep searches were cross-validated with AST-grep where applicable.  
- No findings rely solely on agent inference without file reads.

---

*End of report.*
