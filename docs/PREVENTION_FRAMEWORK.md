# Prevention Framework: Why AGI Missed [EXEC-1] & How to Prevent Regression

**Document Date:** 2026-05-15  
**Audience:** Future agents, code reviewers, architects  
**Purpose:** Explain why the position consolidation bug slipped through and how to prevent similar issues

---

## Executive Summary

A **critical position consolidation bug [EXEC-1]** was discovered in production: the system opened 15+ duplicate positions on the same market, burning $450+ per incident. This bug slipped past AGI code review because it was a **systems-level architectural issue**, not a local code quality problem.

**Why AGI Missed It:**
1. **Split execution paths** — 3 different `execute()` methods, only 1 had duplicate checks
2. **Implicit assumptions** — No written rule requiring all execute methods to check duplicates
3. **Undefined methods** — Called `_persist_to_db()` without defining it (syntax OK in dynamic Python)
4. **Insufficient tests** — Tests only covered single signal scenarios, not rapid-fire concurrent signals

**How We Fixed It:**
1. Added duplicate position checks to HFT executor and AutoTrader
2. Documented architectural rules in AGENTS.md and ARCHITECTURE.md
3. Created enforcement mechanisms (linting, testing, monitoring)

**Going Forward:**
- Explicit architectural rules prevent AGI from missing implicit patterns
- Static checks catch undefined methods
- Test templates validate cross-file consistency
- Production monitoring alerts on duplicate patterns

---

## The Bug: Position Consolidation [EXEC-1]

### What Happened

**Production Incident (Gemini 3.5 May 31):**
- 15+ buy orders on same market in 1 hour
- Each order: 68 shares @ $0.74 = $50.03
- Total: 1,020 shares, $500+ spent
- **Expected:** 1 consolidated position of 68 shares, $50
- **Loss:** $450+ from unnecessary commissions and slippage

### Root Cause Analysis

```
Signal 1: "Buy Gemini 3.5"  →  HFT executor.execute()
          ↓ [NO duplicate check!]
          Opens Trade #1 (68 shares)

Signal 2: "Buy Gemini 3.5" (15ms later)  →  HFT executor.execute()
          ↓ [NO duplicate check!]
          Opens Trade #2 (68 shares) ← SHOULD HAVE BEEN BLOCKED

Signal 3-15: Same pattern
          ↓
          Opens Trades #3-15
          
Result: 1,020 shares instead of 68
        $500 instead of $50
        LOSS: $450+
```

### The Missing Checks

**HFTExecutor (`backend/core/hft_executor.py`)**
- Line 43-80: `execute()` method
- **Problem:** No query for existing open positions
- **Should have:** `existing = db.query(Trade).filter(..., settled=False).first()`
- **Status:** ✓ FIXED (2026-05-15)

**AutoTrader (`backend/core/auto_trader.py`)**
- Line 30-70: `execute_signal()` method
- **Problem:** No query for existing open positions
- **Should have:** `existing = db.query(Trade).filter(..., settled=False).first()`
- **Status:** ✓ FIXED (2026-05-15)

**StrategyExecutor (`backend/core/strategy_executor.py`)** — Lines 365-377
- **ALREADY HAD** the duplicate check (correct implementation)
- This is why only HFT executor and AutoTrader missed it

### Why Only HFT/AutoTrader?

1. **Historical:** StrategyExecutor was the original execution path
2. **Evolution:** HFT executor was added later as a parallel path (but check wasn't copied)
3. **AutoTrader:** Added as another specialized path (also missed the check)
4. **Result:** 3 separate execution paths, only 1 had validation

---

## Why AGI Missed This (4 Root Causes)

### Root Cause #1: Split Execution Paths (Architectural Gap)

**The Problem:**
```
execute() is in 3 different classes:
  ✓ StrategyExecutor.execute()  — HAS duplicate check
  ✗ HFTExecutor.execute()       — NO duplicate check  
  ✗ AutoTrader.execute_signal() — NO duplicate check
```

**Why AGI Missed It:**
- AGI validated each file/method independently
- No cross-file invariant checking
- No knowledge that these are parallel paths needing same rule
- Code review was "file-by-file" not "system-by-system"

**Lesson:** AGI is good at local consistency, bad at global patterns

**Fix:** Explicit architectural rules that apply across files:
```
Rule 1: All execute*() methods MUST check for duplicate positions
  Location: AGENTS.md, ARCHITECTURE.md
  Enforcement: Grep-based linting, mypy, tests, monitoring
```

---

### Root Cause #2: Undefined Method Not Caught (Incomplete Refactoring)

**The Problem:**
```python
# HFT executor calls:
await self._persist_to_db(execution)

# But _persist_to_db() is NEVER defined anywhere!
# This would crash at runtime if this code path executed
```

**Why AGI Missed It:**
1. **Python is dynamic** — Syntax is valid even if method doesn't exist
2. **No type hints** — If code was typed (`self._persist_to_db()` has type signature), mypy would catch it
3. **Not executed in tests** — Code path never hit during unit tests, so runtime error never happened
4. **No strict checking** — No `mypy --strict` in CI to catch undefined references

**Lesson:** Dynamic languages hide bugs that static languages would catch immediately

**Fix:** Enable strict type checking:
```bash
# In CI pipeline:
mypy --strict backend/core/hft_executor.py
mypy --strict backend/core/auto_trader.py
```

---

### Root Cause #3: Insufficient Test Coverage (Missing Scenario)

**The Problem:**

Tests covered:
- ✓ Single signal → single execution
- ✓ Risk validation logic
- ✓ Database record creation

Tests did NOT cover:
- ✗ Rapid-fire signals (15 signals in 60 seconds)
- ✗ Same market duplicates (2 signals on same market)
- ✗ Concurrent execution (signals arriving in parallel)
- ✗ Real-world load patterns (what actually happens in production)

**Why AGI Missed It:**
- Tests were "happy path" only
- No stress/chaos testing
- No production pattern simulation
- AGI tests what's written, not what should be tested

**Lesson:** Test suite only covers written scenarios, not real-world behavior

**Fix:** Add mandatory test template:
```python
@pytest.mark.parametrize("executor_class", [HFTExecutor, AutoTrader, StrategyExecutor])
def test_duplicate_position_blocked(executor_class):
    # First signal on market: succeeds
    result1 = executor_class.execute(signal, 1000)
    assert result1.success
    
    # Second signal on SAME market: BLOCKED
    result2 = executor_class.execute(signal, 1000)
    assert not result2.success
    assert "duplicate" in result2.error.lower()
```

---

### Root Cause #4: Missing Architectural Rules (No Explicit Intent)

**The Problem:**

The requirement "all execute() methods must check for duplicates" was:
- ✗ Never written down
- ✗ Not in code comments
- ✗ Not in architecture docs
- ✗ Not in test requirements
- ✗ Only implicit in developer knowledge

**Why AGI Missed It:**
- AGI validates what's specified
- Can't infer implicit architectural intent
- No linting rule to enforce it
- No test assertion requiring it

**Lesson:** Implicit assumptions are invisible to automation

**Fix:** Make rules explicit and enforceable:
```markdown
# In AGENTS.md:
## Architectural Rules & Invariants

### Rule 1: Execution Path Consistency
Every class with execute*() method MUST:
  1. Check for existing open position on same market
  2. Return rejected/cancelled if duplicate found
  3. Log the blocked duplicate attempt
  4. Document why this check is needed

Applies to:
  - HFTExecutor.execute()
  - AutoTrader.execute_signal()
  - StrategyExecutor.execute()

Testing:
  - Mandatory test template in this document
  
Enforcement:
  - Grep-based linting check
  - mypy strict type checking
  - pytest parametrized tests
```

---

## Prevention Framework: How to Prevent Regression

### 1. Architectural Rules (AGENTS.md)

**What's Documented:**
- Rule 1: Execution Path Consistency
- Implementation pattern (exact code template)
- Test template (parametrized, applies to all executors)
- Static checks (grep, mypy, linting)
- Production monitoring (alerts for duplication patterns)

**Why It Works:**
- Rules are explicit (not implicit)
- Template prevents copy-paste errors
- Tests are mandatory and parametrized
- Monitoring catches issues in production

---

### 2. Static Analysis Checks (CI/CD)

**Check: All execute*() methods have duplicate validation**
```bash
# In GitHub Actions workflow:
for file in $(find backend/core -name "*.py" -exec grep -l "def execute" {} \;); do
  if ! grep -q "existing.*Trade\|duplicate" "$file"; then
    echo "FAIL: $file missing duplicate position check"
    exit 1
  fi
done
```

**Check: Strict type checking catches undefined methods**
```bash
mypy --strict backend/core/hft_executor.py
mypy --strict backend/core/auto_trader.py
mypy --strict backend/core/strategy_executor.py
```

**Check: All execute*() methods pass duplicate position tests**
```bash
pytest -k duplicate_position -v
```

---

### 3. Test Templates (pytest)

**Mandatory test for EVERY executor class:**

```python
@pytest.mark.parametrize("executor_class", [
    HFTExecutor,
    AutoTrader,
    StrategyExecutor
])
def test_duplicate_position_blocked(executor_class):
    """
    Verify: Duplicate positions on same market are blocked
    Regression guard: Prevents [EXEC-1] from happening again
    """
    # Setup
    signal_1 = HFTSignal(market_id="gemini_may_31", outcome="Yes", size=68)
    signal_2 = HFTSignal(market_id="gemini_may_31", outcome="Yes", size=68)
    bankroll = 1000
    
    # First execution on market: succeeds
    result1 = executor_class.execute(signal_1, bankroll)
    assert result1.success, f"First execution should succeed, got {result1.error}"
    
    # Second execution on SAME market: blocked
    result2 = executor_class.execute(signal_2, bankroll)
    assert not result2.success, "Second execution should be blocked as duplicate"
    assert "duplicate" in result2.error.lower(), f"Error should mention duplicate, got: {result2.error}"
    
    # Position count: should be 1, not 2
    positions = db.query(Trade).filter(
        Trade.market_id == "gemini_may_31",
        Trade.settled == False
    ).count()
    assert positions == 1, f"Should have 1 position, have {positions}"
```

---

### 4. Production Monitoring (Runtime Alerts)

**Alert 1: High Duplication Rate**
```python
# Monitor duplicate trading rate per market
trades_per_market = group_by_market(recent_trades_last_60s)
for market, trades in trades_per_market.items():
    if len(trades) > 3:  # >3 trades on same market in 60s
        alert(
            level="critical",
            message=f"HIGH_DUPLICATION: {market} has {len(trades)} trades in 60s",
            action="Review signal generation and position consolidation"
        )
```

**Alert 2: Undefined Method Errors**
```python
# Catch any AttributeError in execute paths
if "AttributeError" in log_line and ("execute" in log_line or "_persist_to_db" in log_line):
    alert(
        level="critical",
        message="Undefined method in execute path - critical bug detected",
        action="Immediately rollback and investigate"
    )
```

**Alert 3: Duplicate Blocking Rate**
```python
# Normal: ~0 duplicates blocked per hour
# Alert: >1 duplicate blocked per hour (indicates rapid signal burst)
duplicate_blocks_per_hour = count_cancelled_for_duplicate(timedelta(hours=1))
if duplicate_blocks_per_hour > 1:
    alert(
        level="warning",
        message=f"Signal burst detected: {duplicate_blocks_per_hour} duplicates blocked in last hour",
        action="Review signal generation (debate engine, multiple strategies firing)"
    )
```

---

## Key Takeaways for Future Agents

### What AGI Is Good At
- ✓ Local code quality (syntax, style, logic in one file)
- ✓ Finding obvious bugs (undefined variables, type errors)
- ✓ Refactoring individual modules
- ✓ Running existing test suites
- ✓ Code consistency within a file

### What AGI Cannot Do Alone
- ✗ Systems-level invariants (rules across multiple files)
- ✗ Architectural patterns (parallel paths needing same logic)
- ✗ Implicit assumptions (things not written down)
- ✗ Production load patterns (real-world stress testing)
- ✗ Domain knowledge (financial correctness vs code correctness)

### What You (Human) Must Do
1. **Make architecture explicit** — Write down rules, don't assume they're understood
2. **Enforce with static analysis** — grep, mypy, linting catch what humans miss
3. **Test like production** — Not just happy path, but concurrent, rapid-fire, stress
4. **Monitor in production** — Bugs slip through despite careful review; catch them at runtime
5. **Document for future agents** — This document itself is the prevention!

---

## References

- **Fixed Bug:** `backend/core/hft_executor.py` (+37 lines, 2026-05-15)
- **Fixed Bug:** `backend/core/auto_trader.py` (+30 lines, 2026-05-15)
- **Rules Documentation:** `AGENTS.md` (Architectural Rules section)
- **Architecture:** `ARCHITECTURE.md` (Execution Path Invariants section)
- **Commit:** `6750c65` - Mark position consolidation [EXEC-1] as FIXED
- **Tracking:** `IMPLEMENTATION_GAPS.md` (now lists [EXEC-1] as Fixed)

---

**Last Updated:** 2026-05-15 | **Status:** ✓ Prevention framework implemented
