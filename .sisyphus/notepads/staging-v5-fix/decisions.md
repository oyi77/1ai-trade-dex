
## Staging V5 - Architectural Decisions

### Decision 1: Direct Key Copy vs Environment Link
**Chosen**: Direct copy of Kalshi private key to local secrets/
```
mkdir -p /home/openclaw/projects/1ai-poly-trader/secrets
cp /home/openclaw/projects/polyedge/secrets/kalshi_private_key.pem /home/openclaw/projects/1ai-poly-trader/secrets/
```

**Rationale**:
- Avoids symlink/environment issues across project boundaries
- Each project has independent, complete secret set
- Cleaner deployment and backup story
- No cross-project dependencies during execution

### Decision 2: Detached Process Management via subprocess.Popen + start_new_session=True
**Chosen**: Python subprocess with process group isolation
```python
subprocess.Popen(
    ['python3', '-m', 'uvicorn', ...],
    start_new_session=True,
    stdout=open('/tmp/staging-v5-api.log', 'w'),
    stderr=subprocess.STDOUT
)
```

**Rationale**:
- Shell background (&) and disown are unreliable across systems
- start_new_session creates new process group (immune to parent termination)
- Stdout/stderr redirection is atomic and reliable
- Can be monitored independently without polling
- No race conditions on startup sequencing

### Decision 3: Sequential Startup with Polling Verification
**Chosen**: Start API first, then bot, poll for 180s with 10s intervals
```
1. Start API (uvicorn on 8101)
2. Sleep 5s
3. Start Bot (orchestrator)
4. Poll for success conditions (120+ seconds)
```

**Rationale**:
- API must be ready before bot connects (if needed)
- Early failure detection without hanging forever
- Allows bot to stabilize before verification
- 120s minimum ensures at least 12+ trade cycles

### Decision 4: Log File Aggregation in /tmp
**Chosen**: Centralized logs in /tmp for easy access
```
/tmp/staging-v5-api.log
/tmp/staging-v5-bot.log
```

**Rationale**:
- Easily accessible for monitoring and debugging
- Persists across restart (within session)
- Simple to tail in monitoring scripts
- Clearable for clean re-runs

### Decision 5: BUY Filter is Working Correctly (0 = Success)
**Chosen**: No code changes - filter working as designed
- Input: 17 non-BUY decisions from copy_trader
- Output: 0 trades (filter applied correctly)
- Action: Monitor, don't fix

**Rationale**:
- Filter logic is: decision == "BUY" AND market_ticker present
- 17 decisions with no BUY = 17 correctly filtered
- System is safe - only BUY decisions produce trades
- Investigation needed on WHY no BUY signals, but filter is correct

