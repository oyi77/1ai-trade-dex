# Research Checklist: Implementing Prediction Market Analysis Insights

**Status**: Ready for implementation  
**Priority**: HIGH (P1)  
**Owner**: AGI Strategy Team  
**Timeline**: 4 weeks

---

## ✅ PHASE 1: IMMEDIATE (Days 1-3)

- [ ] **Review docs**
  - [ ] Read `RESEARCH_SUMMARY.md` (15 min)
  - [ ] Skim `PREDICTION_MARKET_ANALYSIS_REPO_FINDINGS.md` (30 min)
  - [ ] Review top 3 wins in `IMPLEMENTATION_ROADMAP_AGI_ENHANCEMENTS.md` (20 min)

- [ ] **Validate feasibility**
  - [ ] Check if we have `order.created_at` field (for maker/taker classification)
  - [ ] Verify we have resolved market outcomes in BotState.trades
  - [ ] Confirm Polygon RPC access available (for blockchain indexing later)

- [ ] **Create GitHub issues**
  - [ ] [P1] Implement maker/taker role classification
  - [ ] [P1] Add price bucket calibration tracking
  - [ ] [P1] Deploy longshot bias signal
  - [ ] [P2] Blockchain CLOB event indexing
  - [ ] [P2] Parquet backtest storage migration

---

## ✅ PHASE 2: WEEK 1 (Maker/Taker + Longshot Bias)

### Sprint: Maker/Taker Classification

- [ ] **Add TradeRole enum**
  ```python
  # backend/models/trade.py
  class TradeRole(str, Enum):
      MAKER = "maker"
      TAKER = "taker"
      UNKNOWN = "unknown"
  ```

- [ ] **Add role field to Trade model**
  - [ ] Update SQLAlchemy Trade dataclass
  - [ ] Add migration: `alembic revision --autogenerate -m "Add trade role field"`
  - [ ] Run migration: `alembic upgrade head`

- [ ] **Implement role detection**
  - [ ] Create `classify_trade_role()` function in TradeAttempt handler
  - [ ] Compare `trade_attempt.created_at` vs `order_book.fetch_time`
  - [ ] Set trade.role before persisting to BotState

- [ ] **Test role classification**
  - [ ] Write unit tests: 5 test cases (maker fills, taker fills, edge cases)
  - [ ] Validate classification against known trades (manual review 10 trades)
  - [ ] Run pytest: `pytest tests/test_trade_role_classification.py -v`

- [ ] **Add Control Room metrics**
  - [ ] Add "Maker ROI" card to Control Room dashboard
  - [ ] Add "Taker ROI" card
  - [ ] Add "Role Distribution" pie chart (% maker vs taker)

---

### Sprint: Longshot Bias Signal

- [ ] **Implement bias detector**
  ```python
  # backend/signals/market_bias.py
  def compute_longshot_bias(trades, price_threshold=30, window_days=60)
  ```

- [ ] **Add bias feature to AGI ensemble**
  - [ ] Create `LongshotBiasFeature` in feature_generator
  - [ ] Subscribe to market data updates
  - [ ] Call detector every 1 hour or on new resolved trades

- [ ] **Create bias signal**
  - [ ] When bias < 0.97: emit TradeSignal(side='NO', confidence=bias_strength)
  - [ ] When bias > 1.03: emit TradeSignal(side='YES', confidence=bias_strength)
  - [ ] Log signal reasoning to audit trail

- [ ] **Test signal quality**
  - [ ] Backtest longshot bias signal on last 30 days
  - [ ] Compare realized ROI: bias signal vs baseline
  - [ ] Check p-value of edge (should be p < 0.05)

---

## ✅ PHASE 2B: WEEK 2 (Calibration Buckets)

- [ ] **Implement bucket computation**
  ```python
  # backend/analytics/calibration.py
  def compute_calibration_buckets(trades, bucket_width=5, window_days=30)
  ```

- [ ] **Create calibration heatmap**
  - [ ] Generate 5¢ price buckets (0-5, 5-10, ..., 95-100)
  - [ ] For each bucket: predicted_prob, actual_win_rate, error, confidence
  - [ ] Export to CSV for Control Room visualization

- [ ] **Add Control Room calibration card**
  - [ ] 2D heatmap: X=price, Y=error, color=confidence
  - [ ] Table below: price bucket, predicted, actual, trades count
  - [ ] Highlight buckets with >1% error

- [ ] **Add AGI feedback loop**
  - [ ] Before executing AGI trade: look up price bucket calibration
  - [ ] Apply adjustment: `AGI_price += calibration_error * confidence`
  - [ ] Log adjustment to audit trail

- [ ] **Validate accuracy improvement**
  - [ ] A/B test: 50% with calibration adjustment, 50% without
  - [ ] Run for 1-2 weeks
  - [ ] Measure: accuracy delta, ROI delta
  - [ ] Decision: deploy if accuracy improves >0.5%

---

## ✅ PHASE 3: WEEK 3 (Blockchain + Parquet)

### Sprint: Blockchain Event Indexing

- [ ] **Set up Polygon RPC client**
  - [ ] Test RPC endpoint available: `python -c "from web3 import Web3; w3 = Web3(...)"`
  - [ ] Check rate limits (should support ~100 requests/sec)
  - [ ] Store RPC URL in `.env`

- [ ] **Implement CLOB event indexer**
  - [ ] Create `backend/indexers/polymarket_blockchain.py`
  - [ ] Implement `index_clob_events(from_block, to_block)`
  - [ ] Decode OrderFilled event: (maker, taker, amounts, fees)

- [ ] **Add cursor tracking**
  - [ ] Persist last indexed block to `data/.clob_cursor`
  - [ ] Resume from cursor on restart (crash-safe)

- [ ] **Store blockchain trades**
  - [ ] Create `BlockchainTrade` model in database
  - [ ] Insert indexed events with source='blockchain'
  - [ ] Compare vs Data API: should match >99%

- [ ] **Validate blockchain indexing**
  - [ ] Check 100 random trades: blockchain vs Data API
  - [ ] Verify maker/taker addresses match
  - [ ] Check fee recovery accurate

---

### Sprint: Parquet Migration

- [ ] **Set up Parquet storage**
  - [ ] Create `data/trades/` directory
  - [ ] Verify pyarrow + pandas installed

- [ ] **Daily trade snapshot**
  - [ ] Create `backend/jobs/daily_parquet_snapshot.py`
  - [ ] Runs daily at midnight UTC
  - [ ] Exports all resolved trades to `data/trades/YYYY-MM-DD.parquet`

- [ ] **Update backtest engine**
  - [ ] Modify backtest to read from Parquet files
  - [ ] Benchmark: should be 100x faster than SQLite
  - [ ] Run 1 year backtest: <1 second vs current ~100 seconds

- [ ] **Cleanup migration**
  - [ ] Keep SQLite for live ledger (ACID compliance)
  - [ ] Use Parquet only for historical analysis/backtest
  - [ ] Document trade storage architecture

---

## ✅ PHASE 4: WEEK 4 (Temporal + Categories)

- [ ] **Temporal strategy routing**
  - [ ] Compute hourly edge from last 90 days: `returns_by_hour()`
  - [ ] Create `HOURLY_STRATEGY_WEIGHTS` dict (hour → strategy multiplier)
  - [ ] Update AGI position sizing based on hour_et

- [ ] **Category taxonomy**
  - [ ] Import `SUBCATEGORY_PATTERNS` from prediction-market-analysis repo
  - [ ] Map Kalshi markets to categories (Sports/Finance/Politics)
  - [ ] Create `backend/ml/category_specific.py` model router

- [ ] **Category-specific models**
  - [ ] Train 3 separate ensemble models: sports, finance, politics
  - [ ] Route market to category-specific model
  - [ ] Track category-specific accuracy separately

- [ ] **Full integration testing**
  - [ ] End-to-end test: market → category detection → model selection → trade execution
  - [ ] Load test: 1000 market updates/sec should stay <100ms latency
  - [ ] Validate no regression vs baseline

---

## ✅ VALIDATION & HANDOFF

### Before Deployment

- [ ] **Code quality**
  - [ ] All tests passing: `pytest tests/ -v`
  - [ ] Linting clean: `ruff check backend/`
  - [ ] Type checking: `mypy backend/`

- [ ] **Performance**
  - [ ] Maker/taker classification: <1ms per trade
  - [ ] Calibration bucket computation: <100ms for 1000 trades
  - [ ] Longshot bias detector: <50ms per market

- [ ] **Documentation**
  - [ ] Add docstrings to all new functions
  - [ ] Update `docs/api.md` with new endpoints
  - [ ] Add "Calibration Bucketing" section to ARCHITECTURE.md
  - [ ] Update `.env.example` for new env vars

- [ ] **Monitoring**
  - [ ] Add Prometheus metrics for role classification accuracy
  - [ ] Add alert: if calibration error > 5% for bucket
  - [ ] Add alert: if longshot bias detector fails

---

### A/B Testing (Post-Deployment)

- [ ] **Maker/Taker Tracking**
  - [ ] Duration: 2 weeks
  - [ ] Metric: Maker ROI vs Taker ROI differential
  - [ ] Decision threshold: 1.5%+ maker advantage

- [ ] **Calibration Feedback**
  - [ ] Duration: 2 weeks
  - [ ] Metric: AGI accuracy with vs without adjustment
  - [ ] Decision threshold: 0.5%+ improvement

- [ ] **Longshot Bias Signal**
  - [ ] Duration: 1 week
  - [ ] Metric: ROI on trades with bias signal vs without
  - [ ] Decision threshold: 0.5%+ edge, p<0.05

---

## 📊 SUCCESS CRITERIA (End of 4 Weeks)

| Feature | Success Metric | Target | Actual |
|---------|---|---|---|
| Maker/Taker Classification | Role assignment accuracy | 99% | ___ |
| Calibration Buckets | Median bucket error | <0.5% | ___ |
| Longshot Bias Signal | Signal ROI | +0.5-1% | ___ |
| Blockchain Indexing | Event completeness vs Data API | 99% | ___ |
| Parquet Backtest | Query speed improvement | 100x | ___ |
| Temporal Routing | Hour-of-day alpha | +1% | ___ |
| **Overall AGI Accuracy** | **Improvement** | **+2-3%** | ___ |

---

## 🚨 RISKS & MITIGATIONS

| Risk | Probability | Impact | Mitigation |
|------|---|---|---|
| Maker/taker classification unreliable | Medium | High | Validate against 100 manual trades |
| Calibration feedback creates overfitting | Medium | Medium | Use walk-forward validation, 30-day rolling window |
| Blockchain RPC rate limits | Low | High | Implement exponential backoff, cache events |
| Parquet migration breaks backtest | Low | High | Run parallel backtest, verify results match |
| Temporal signals don't generalize | Medium | Medium | Retrain weekly, monitor out-of-sample performance |

---

## 📝 NOTES

- **Start with Week 1 (4-day sprint)**: Maker/taker + longshot bias has highest ROI/effort ratio
- **Parallel Weeks 3**: Blockchain indexing and Parquet can proceed in parallel
- **Validation first**: Before full deployment, A/B test each feature for 1-2 weeks
- **Iterate**: Update calibration curves weekly as new resolved trades arrive

---

**Next Action**: Open GitHub issues for Phase 1 + assign to AGI Strategy team

