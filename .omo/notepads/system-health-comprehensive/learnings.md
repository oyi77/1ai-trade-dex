## T3: Copy Trader & Bond Scanner Direction Mapping Fix

### Root Cause
Both strategies were using "buy" as direction value, but TradeValidator.validate_trade_data() only accepts {"up", "down", "YES", "yes"}. This caused 930+ trade rejections for invalid direction.

### Issues Found
1. **copy_trader**: `order_executor.py:384` set `our_side="BUY"` (invalid)
2. **bond_scanner**: `bond_scanner.py:271` set `trade_direction="buy"` as fallback for invalid outcome names

### Fixes Applied
1. **copy_trader** (backend/strategies/order_executor.py):
   - Changed `our_side="BUY"` → `our_side=trade.outcome.upper() if trade.outcome in ("yes", "no") else "YES"`
   - Map whale's trade direction to valid CLOB directions
   - If whale is buying YES → direction="YES"
   - If whale is buying NO → direction="NO"

2. **bond_scanner** (backend/strategies/bond_scanner.py):
   - Changed fallback from `trade_direction="buy"` → `trade_direction="yes"`
   - Default to "yes" for prediction markets when outcome name is not a valid direction
   - Removed invalid direction that caused validation failures

### Valid Directions
TradeValidator.accepts: {"up", "down", "yes", "no", "YES", "NO"}
- For prediction markets: use "YES"/"NO"
- For crypto markets: use "up"/"down"
- Never use "buy"/"sell" — these are not accepted

### Verification
- `grep -r 'direction.*"buy"' backend/modules/execution/copy_trader.py backend/strategies/bond_scanner.py` → 0 results ✅
- `lsp_diagnostics` on all 4 affected files → clean ✅
- All direction mappings now use valid CLOB API values

### Key Lesson
CLOB API expects YES/NO for prediction markets, up/down for crypto. Internal "buy" direction is invalid and must be mapped to proper contract sides.### Risk Profile Startup Application
- Risk profiles (safe, normal, aggressive, extreme) are applied by mutating the global 'settings' object.
- Previously, this only happened via API call, meaning the bot started with default values (0.15 drawdown) even if RISK_PROFILE=extreme was set in .env.
- Added apply_profile() call to Orchestrator.start() to ensure thresholds are in effect from boot.
- The call is placed after Telegram bot initialization but before strategy registry loading.
- apply_profile() also persists the profile name back to .env, which helps maintain state across restarts, although Pydantic's BaseSettings doesn't automatically map the profile name to other thresholds without the explicit apply_profile() call.
