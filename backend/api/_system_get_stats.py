"""Carved verbatim out of ``backend/api/system.py`` — statements moved, no logic changed."""

from ._system_iso import (
    BotStats,
)

from .system import (
    Depends,
    Optional,
    Query,
    Session,
    get_db,
    router,
)

from . import system as _facade

@router.get("/stats", response_model=BotStats)
async def get_stats(db: Session = Depends(get_db), mode: Optional[str] = Query(None)):
    # Read-only: no for_update to avoid lock contention during stats polling
    paper_state = db.query(_facade.BotState).filter_by(mode="paper").first()
    testnet_state = db.query(_facade.BotState).filter_by(mode="testnet").first()
    live_state = db.query(_facade.BotState).filter_by(mode="live").first()

    effective_mode = mode or _facade.settings.TRADING_MODE
    if effective_mode == "all":
        effective_mode = _facade.settings.TRADING_MODE
    if effective_mode == "paper":
        state = paper_state
    elif effective_mode == "testnet":
        state = testnet_state
    else:
        state = live_state

    if not state:
        raise _facade.HTTPException(status_code=404, detail="Bot state not initialized")

    paper_settled_trades = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(_facade.Trade.trading_mode == "paper", _facade.Trade.settled)
        .scalar()
        or 0
    )
    paper_wins = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(_facade.Trade.trading_mode == "paper", _facade.Trade.settled, _facade.Trade.pnl > 0)
        .scalar()
        or 0
    )
    paper_pnl = (
        db.query(_facade.func.sum(_facade.Trade.pnl))
        .filter(_facade.Trade.trading_mode == "paper", _facade.Trade.settled)
        .scalar()
        or 0.0
    )

    paper_open_trades = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(_facade.Trade.trading_mode == "paper", not _facade.Trade.settled)  # noqa: E712
        .scalar()
        or 0
    )

    paper_trades = paper_settled_trades + paper_open_trades
    paper_bankroll = _facade._available_simulated_bankroll(
        paper_state.bankroll if paper_state else None,
        _facade.settings.INITIAL_BANKROLL,
    )
    paper_win_rate = paper_wins / paper_trades if paper_trades > 0 else 0.0

    sync_metadata = None

    (
        live_bankroll,
        live_cached_account_pnl,
        live_cached_trades,
        live_cached_wins,
        live_initial,
    ) = _facade._live_cache_values(live_state)

    # End the read transaction before network I/O so stats polling does not sit
    # idle-in-transaction while waiting on Polymarket profile calls.
    db.rollback()

    # Fetch PUSD balance from CLOB (async, non-blocking)
    pusd_balance = 0.0
    if _facade.settings.POLYMARKET_PRIVATE_KEY:
        try:
            from backend.data.polymarket_clob import clob_from_settings

            async with clob_from_settings(mode="live") as clob:
                pusd_balance = await clob.get_pusd_balance()
        except Exception as e:
            _facade.logger.debug(f"Failed to fetch PUSD balance: {e}")

    if effective_mode == "live" or mode is None:
        live_profile_pnl, live_profile_trade_stats = await _facade.asyncio.gather(
            _facade.fetch_pm_profile_pnl(),
            _facade.fetch_pm_profile_trade_stats(),
        )
        live_profile_traded_count = (
            live_profile_trade_stats.traded_count if live_profile_trade_stats else None
        )
    else:
        live_profile_pnl = None
        live_profile_trade_stats = None
        live_profile_traded_count = None
    live_account_pnl = (
        float(live_profile_pnl)
        if live_profile_pnl is not None
        else live_cached_account_pnl
    )

    # Always query live-mode trades from actual DB for ledger analytics, but do
    # not use that ledger P&L as live account P&L in the dashboard.
    if effective_mode in ("testnet", "live") or mode is None:
        live_settled_trades = (
            db.query(_facade.func.count(_facade.Trade.id))
            .filter(
                (
                    _facade.Trade.trading_mode == effective_mode
                    if mode is not None
                    else _facade.Trade.trading_mode == "live"
                ),
                _facade.Trade.settled,
            )
            .scalar()
            or 0
        )
        live_wins = (
            db.query(_facade.func.count(_facade.Trade.id))
            .filter(
                (
                    _facade.Trade.trading_mode == effective_mode
                    if mode is not None
                    else _facade.Trade.trading_mode == "live"
                ),
                _facade.Trade.settled,
                _facade.Trade.pnl > 0,
            )
            .scalar()
            or 0
        )
        live_ledger_pnl = (
            db.query(_facade.func.sum(_facade.Trade.pnl))
            .filter(
                (
                    _facade.Trade.trading_mode == effective_mode
                    if mode is not None
                    else _facade.Trade.trading_mode == "live"
                ),
                _facade.Trade.settled,
            )
            .scalar()
            or 0.0
        )

        live_open_trades_count = (
            db.query(_facade.func.count(_facade.Trade.id))
            .filter(
                (
                    _facade.Trade.trading_mode == effective_mode
                    if mode is not None
                    else _facade.Trade.trading_mode == "live"
                ),
                not _facade.Trade.settled,  # noqa: E712
            )
            .scalar()
            or 0
        )

        live_trades = live_settled_trades + live_open_trades_count

        live_win_rate = live_wins / live_trades if live_trades > 0 else 0.0
        live_ledger_trades = live_trades
        live_ledger_wins = live_wins
        if live_profile_trade_stats is not None:
            live_trades = live_profile_trade_stats.traded_count
            live_wins = live_profile_trade_stats.winning_count
            live_win_rate = live_profile_trade_stats.win_rate

        orphaned_count = (
            db.query(_facade.func.count(_facade.Trade.id))
            .filter(
                _facade.Trade.trading_mode == (effective_mode if mode is not None else "live"),
                _facade.Trade.result == "orphaned",
            )
            .scalar()
            or 0
        )
        external_imports_count = (
            db.query(_facade.func.count(_facade.Trade.id))
            .filter(
                _facade.Trade.trading_mode == (effective_mode if mode is not None else "live"),
                _facade.Trade.source == "external",
            )
            .scalar()
            or 0
        )

        sync_metadata = _facade.SyncMetadata(
            last_synced_at=live_state.last_sync_at if live_state else None,
            orphaned_count=orphaned_count,
            external_imports_count=external_imports_count,
        )

        if live_state and round(live_ledger_pnl, 2) != round(live_account_pnl, 2):
            _facade.logger.warning(
                f"Stat change detected for {effective_mode}: ledger PnL={live_ledger_pnl} vs live account PnL={live_account_pnl}. "
                f"Orphaned={orphaned_count}, External={external_imports_count}"
            )
    else:
        live_ledger_pnl = live_cached_account_pnl
        live_trades = live_cached_trades
        live_wins = live_cached_wins
        live_win_rate = live_wins / live_trades if live_trades > 0 else 0.0
        live_ledger_trades = live_cached_trades
        live_ledger_wins = live_cached_wins

    testnet_settled_trades = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(
            _facade.Trade.trading_mode == "testnet",
            _facade.Trade.settled,
            _facade.Trade.result.in_(["win", "loss", "closed"]),
        )
        .scalar()
        or 0
    )
    testnet_wins = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(_facade.Trade.trading_mode == "testnet", _facade.Trade.settled, _facade.Trade.pnl > 0)
        .scalar()
        or 0
    )
    testnet_pnl = (
        db.query(_facade.func.sum(_facade.Trade.pnl))
        .filter(_facade.Trade.trading_mode == "testnet", _facade.Trade.settled)
        .scalar()
        or 0.0
    )

    testnet_open_trades = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(_facade.Trade.trading_mode == "testnet", not _facade.Trade.settled)  # noqa: E712
        .scalar()
        or 0
    )

    testnet_trades = testnet_settled_trades + testnet_open_trades
    testnet_bankroll = _facade._available_simulated_bankroll(
        testnet_state.bankroll if testnet_state else None,
        100.0,
    )
    testnet_win_rate = testnet_wins / testnet_trades if testnet_trades > 0 else 0.0

    from backend.core.position_valuation import calculate_position_market_value

    async def calculate_mode_unrealized_pnl(mode: str):
        """Calculate unrealized PnL for a specific mode."""
        result = await calculate_position_market_value(mode, db)

        mode_trades = (
            db.query(_facade.Trade).filter(~_facade.Trade.settled, _facade.Trade.trading_mode == mode).all()
        )

        open_trades_count = len(mode_trades)
        open_exposure_amount = sum((t.size or 0.0) for t in mode_trades)

        return {
            "open_trades": open_trades_count,
            "open_exposure": open_exposure_amount,
            "unrealized_pnl": result["unrealized_pnl"],
            "position_cost": result["position_cost"],
            "position_market_value": result["position_market_value"],
        }

    paper_unrealized, testnet_unrealized, live_unrealized = await _facade.asyncio.gather(
        calculate_mode_unrealized_pnl("paper"),
        calculate_mode_unrealized_pnl("testnet"),
        calculate_mode_unrealized_pnl("live"),
    )

    paper_available_balance = round(paper_bankroll, 2)
    paper_total_balance = round(
        paper_available_balance + paper_unrealized["position_market_value"], 2
    )
    testnet_available_balance = round(testnet_bankroll, 2)
    testnet_total_balance = round(
        testnet_available_balance + testnet_unrealized["position_market_value"], 2
    )
    live_available_balance = round(
        max(0.0, live_bankroll - live_unrealized["position_market_value"]), 2
    )
    live_total_balance = round(live_bankroll, 2)

    # Use effective_mode's values for top-level fields (backward compatibility)
    if effective_mode == "paper":
        mode_unrealized = paper_unrealized
    elif effective_mode == "testnet":
        mode_unrealized = testnet_unrealized
    else:
        mode_unrealized = live_unrealized

    open_trades_count = mode_unrealized["open_trades"]
    open_exposure_amount = mode_unrealized["open_exposure"]
    unrealized_pnl = mode_unrealized["unrealized_pnl"]
    position_cost = mode_unrealized["position_cost"]
    position_market_value = mode_unrealized["position_market_value"]

    settled_trades_count = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(
            _facade.Trade.settled,
            _facade.Trade.trading_mode == effective_mode,
        )
        .scalar()
        or 0
    )
    settled_wins_count = (
        db.query(_facade.func.count(_facade.Trade.id))
        .filter(
            _facade.Trade.settled,
            _facade.Trade.trading_mode == effective_mode,
            _facade.Trade.pnl > 0,
        )
        .scalar()
        or 0
    )

    pnl_source = "botstate"
    if effective_mode == "paper" and paper_pnl == 0 and paper_trades > 0:
        db_pnl = (
            db.query(_facade.func.sum(_facade.Trade.pnl))
            .filter(_facade.Trade.settled.is_(True), _facade.Trade.trading_mode == "paper")
            .scalar()
            or 0.0
        )
        if db_pnl != 0:
            paper_pnl = db_pnl
            pnl_source = "recalculated"
    elif effective_mode == "testnet" and testnet_pnl == 0 and testnet_trades > 0:
        db_pnl = (
            db.query(_facade.func.sum(_facade.Trade.pnl))
            .filter(_facade.Trade.settled.is_(True), _facade.Trade.trading_mode == "testnet")
            .scalar()
            or 0.0
        )
        if db_pnl != 0:
            testnet_pnl = db_pnl
            pnl_source = "recalculated"
    if mode is None:
        # All-mode view uses live external trades (deduplicated from Polymarket API)
        # Do NOT sum across modes — trades are consolidated into 'live' mode only
        display_bankroll = live_bankroll
        display_trades = live_trades
        display_wins = live_wins
        display_win_rate = live_win_rate
        display_pnl = live_account_pnl
        display_available_balance = live_available_balance
        display_total_balance = live_total_balance
        display_realized_pnl = live_ledger_pnl
        display_account_pnl = live_account_pnl
        # Use Polymarket profile counts when available (source of truth for live)
        # Fall back to DB query if profile stats unavailable
        settled_trades_count = (
            live_profile_trade_stats.closed_count
            if live_profile_trade_stats is not None
            else (
                db.query(_facade.func.count(_facade.Trade.id))
                .filter(_facade.Trade.settled, _facade.Trade.trading_mode == "live")
                .scalar()
                or 0
            )
        )
        settled_wins_count = (
            live_profile_trade_stats.winning_count
            if live_profile_trade_stats is not None
            else (
                db.query(_facade.func.count(_facade.Trade.id))
                .filter(_facade.Trade.settled, _facade.Trade.trading_mode == "live", _facade.Trade.pnl > 0)
                .scalar()
                or 0
            )
        )
        open_trades_count = live_unrealized["open_trades"]
        open_exposure_amount = live_unrealized["open_exposure"]
        if live_profile_trade_stats is not None:
            open_trades_count = live_profile_trade_stats.open_position_count
            open_exposure_amount = live_profile_trade_stats.open_position_value
        unrealized_pnl = live_unrealized["unrealized_pnl"]
        position_cost = live_unrealized["position_cost"]
        position_market_value = live_unrealized["position_market_value"]
    elif effective_mode == "paper":
        display_bankroll = paper_bankroll
        display_available_balance = paper_available_balance
        display_total_balance = paper_total_balance
        display_trades = paper_trades
        display_wins = paper_wins
        display_win_rate = paper_win_rate
        display_pnl = paper_pnl
        display_realized_pnl = paper_pnl
        display_account_pnl = paper_pnl
    elif effective_mode == "testnet":
        display_bankroll = testnet_bankroll
        display_available_balance = testnet_available_balance
        display_total_balance = testnet_total_balance
        display_trades = testnet_trades
        display_wins = testnet_wins
        display_win_rate = testnet_win_rate
        display_pnl = testnet_pnl
        display_realized_pnl = testnet_pnl
        display_account_pnl = testnet_pnl
    else:
        display_bankroll = live_bankroll
        display_available_balance = live_available_balance
        display_total_balance = live_total_balance
        display_trades = live_trades
        display_wins = live_wins
        display_win_rate = live_win_rate
        display_pnl = live_account_pnl
        display_realized_pnl = live_ledger_pnl
        display_account_pnl = live_account_pnl

    if effective_mode == "live" and live_profile_trade_stats is not None:
        open_trades_count = live_profile_trade_stats.open_position_count
        open_exposure_amount = live_profile_trade_stats.open_position_value

    return _facade.BotStats(
        bankroll=display_bankroll,
        available_balance=display_available_balance,
        total_balance=display_total_balance,
        total_trades=display_trades,
        winning_trades=display_wins,
        win_rate=display_win_rate,
        total_pnl=display_pnl,
        realized_pnl=display_realized_pnl,
        account_pnl=display_account_pnl,
        is_running=state.is_running,
        last_run=state.last_run,
        initial_bankroll=_facade._initial_bankroll_for_mode(
            effective_mode, live_state or paper_state or testnet_state
        ),
        paper_pnl=paper_pnl,
        paper_bankroll=paper_bankroll,
        paper_trades=paper_trades,
        paper_wins=paper_wins,
        paper_win_rate=paper_win_rate,
        testnet_pnl=testnet_pnl,
        testnet_bankroll=testnet_bankroll,
        testnet_trades=testnet_trades,
        testnet_wins=testnet_wins,
        testnet_win_rate=testnet_win_rate,
        mode="all" if mode is None else effective_mode,
        pnl_source=pnl_source,
        paper={
            "pnl": paper_pnl,
            "realized_pnl": paper_pnl,
            "account_pnl": paper_pnl,
            "bankroll": paper_bankroll,
            "available_balance": paper_available_balance,
            "total_balance": paper_total_balance,
            "trades": paper_trades,
            "wins": paper_wins,
            "win_rate": paper_win_rate,
            "open_trades": paper_unrealized["open_trades"],
            "open_exposure": paper_unrealized["open_exposure"],
            "unrealized_pnl": paper_unrealized["unrealized_pnl"],
            "position_cost": paper_unrealized["position_cost"],
            "position_market_value": paper_unrealized["position_market_value"],
        },
        testnet={
            "pnl": testnet_pnl,
            "realized_pnl": testnet_pnl,
            "account_pnl": testnet_pnl,
            "bankroll": testnet_bankroll,
            "available_balance": testnet_available_balance,
            "total_balance": testnet_total_balance,
            "trades": testnet_trades,
            "wins": testnet_wins,
            "win_rate": testnet_win_rate,
            "open_trades": testnet_unrealized["open_trades"],
            "open_exposure": testnet_unrealized["open_exposure"],
            "unrealized_pnl": testnet_unrealized["unrealized_pnl"],
            "position_cost": testnet_unrealized["position_cost"],
            "position_market_value": testnet_unrealized["position_market_value"],
        },
        live={
            "pnl": live_account_pnl,
            "realized_pnl": live_ledger_pnl,
            "account_pnl": live_account_pnl,
            "bankroll": live_bankroll,
            "available_balance": live_available_balance,
            "total_balance": live_total_balance,
            "trades": live_trades,
            "wins": live_wins,
            "win_rate": live_win_rate,
            "open_trades": live_unrealized["open_trades"],
            "open_exposure": live_unrealized["open_exposure"],
            "unrealized_pnl": live_unrealized["unrealized_pnl"],
            "position_cost": live_unrealized["position_cost"],
            "position_market_value": live_unrealized["position_market_value"],
            "ledger_pnl": live_ledger_pnl,
            "profile_pnl": live_account_pnl,
            "profile_traded_count": live_profile_traded_count,
            "profile_closed_count": (
                live_profile_trade_stats.closed_count
                if live_profile_trade_stats
                else None
            ),
            "profile_winning_count": (
                live_profile_trade_stats.winning_count
                if live_profile_trade_stats
                else None
            ),
            "profile_open_count": (
                live_profile_trade_stats.open_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_stale_open_count": (
                live_profile_trade_stats.stale_open_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_redeemable_count": (
                live_profile_trade_stats.redeemable_position_count
                if live_profile_trade_stats
                else None
            ),
            "profile_open_value": (
                live_profile_trade_stats.open_position_value
                if live_profile_trade_stats
                else None
            ),
            "profile_open_initial_value": (
                live_profile_trade_stats.open_position_initial_value
                if live_profile_trade_stats
                else None
            ),
            "ledger_trades": live_ledger_trades,
            "ledger_wins": live_ledger_wins,
            "ledger_open_trades": live_unrealized["open_trades"],
            "ledger_open_exposure": live_unrealized["open_exposure"],
            "initial_bankroll": live_initial,
        },
        live_ledger_pnl=live_ledger_pnl,
        live_profile_pnl=live_account_pnl,
        live_profile_traded_count=live_profile_traded_count,
        live_ledger_trades=live_ledger_trades,
        live_ledger_wins=live_ledger_wins,
        live_profile_closed_count=(
            live_profile_trade_stats.closed_count if live_profile_trade_stats else None
        ),
        live_profile_winning_count=(
            live_profile_trade_stats.winning_count if live_profile_trade_stats else None
        ),
        live_profile_open_count=(
            live_profile_trade_stats.open_position_count
            if live_profile_trade_stats
            else None
        ),
        live_profile_stale_open_count=(
            live_profile_trade_stats.stale_open_position_count
            if live_profile_trade_stats
            else None
        ),
        live_profile_redeemable_count=(
            live_profile_trade_stats.redeemable_position_count
            if live_profile_trade_stats
            else None
        ),
        active_mode=list(_facade.settings.active_modes_set),
        open_exposure=open_exposure_amount,
        open_trades=open_trades_count,
        settled_trades=settled_trades_count,
        settled_wins=settled_wins_count,
        unrealized_pnl=unrealized_pnl,
        position_cost=position_cost,
        position_market_value=position_market_value,
        pusd_balance=round(pusd_balance, 4),
        sync_metadata=sync_metadata,
    )
