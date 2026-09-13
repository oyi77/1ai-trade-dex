"""Carved verbatim out of ``backend/core/wallet/bankroll_reconciliation.py`` — statements moved, no logic changed."""

from __future__ import annotations

from ._bankroll_reconciliation_bankrollreconciliationreport import (
    BankrollReconciliationReport,
)

from .bankroll_reconciliation import (
    Iterable,
    Session,
)

from . import bankroll_reconciliation as _facade

async def reconcile_bot_state(
    db: Session,
    modes: Iterable[str] = ("paper", "testnet", "live"),
    apply: bool = False,
    commit: bool = False,
    source: str = "runtime_reconcile",
) -> list[BankrollReconciliationReport]:
    """Reconcile BotState caches for selected modes.

    Set apply=False for dry-run reporting. When apply=True, callers may either
    commit themselves or pass commit=True for an atomic commit here.
    """

    reports: list[_facade.BankrollReconciliationReport] = []
    pm_portfolio_value: _facade.Optional[float] = None
    mode_list = tuple(modes)
    if "live" in mode_list:
        pm_portfolio_value = await _facade._fetch_clob_pusd_balance()

    previous_live_update_permission = db.info.get("allow_live_financial_update")
    db.info["allow_live_financial_update"] = True
    try:
        db.expire_all()
        for mode in mode_list:
            state = db.query(_facade.BotState).filter_by(mode=mode).first()
            if not state:
                _facade.logger.warning("No BotState found for mode=%s", mode)
                continue

            report = _facade._build_report(
                db=db,
                state=state,
                mode=mode,
                source=source,
                applied=apply,
                pm_portfolio_value=pm_portfolio_value if mode == "live" else None,
            )
            reports.append(report)

            if apply and report.has_drift:
                old_state = _facade._snapshot_state(state, mode)
                update_values = _facade._mode_update_values(
                    state,
                    mode,
                    report.new_bankroll,
                    report.new_total_pnl,
                    report.new_trade_count,
                    report.new_win_count,
                )
                if mode == "live":
                    if report.pm_portfolio_value is None:
                        update_values["last_live_sync_error"] = (
                            "PM total equity unavailable"
                        )
                    else:
                        update_values["last_live_sync_error"] = None
                db.execute(
                    _facade.update(_facade.BotState)
                    .where(_facade.BotState.id == state.id, _facade.BotState.mode == mode)
                    .values(**update_values)
                )
                db.flush()
                db.refresh(state)
                _facade.log_audit_event(
                    db=db,
                    event_type="BOTSTATE_RECONCILED",
                    entity_type="BOT_STATE",
                    entity_id=mode,
                    old_value=old_state,
                    new_value={
                        **_facade._snapshot_state(state, mode),
                        "report": report.to_dict(),
                    },
                    user_id=source,
                )
                try:
                    from backend.models.database import TransactionEvent

                    delta = report.new_bankroll - report.old_bankroll
                    event = TransactionEvent(
                        type="reconciliation_adjustment",
                        amount=delta,
                        balance_after=report.new_bankroll,
                        context={
                            "mode": mode,
                            "old_bankroll": report.old_bankroll,
                            "new_bankroll": report.new_bankroll,
                            "old_total_pnl": report.old_total_pnl,
                            "new_total_pnl": report.new_total_pnl,
                            "source": source,
                        },
                        note=f"Reconciliation {mode}: bankroll ${report.old_bankroll:.2f} → ${report.new_bankroll:.2f}",
                    )
                    db.add(event)
                except Exception as e:
                    _facade.logger.debug(
                        f"[reconciliation] TransactionEvent recording failed: {e}"
                    )
                _facade.logger.warning(
                    "BotState reconciled ({}): bankroll ${:.2f} -> ${:.2f}, pnl ${:.2f} -> ${:.2f}",
                    mode,
                    report.old_bankroll,
                    report.new_bankroll,
                    report.old_total_pnl,
                    report.new_total_pnl,
                )
            elif report.has_drift:
                _facade.logger.warning(
                    "BotState drift detected ({}): bankroll ${:.2f} -> ${:.2f}, pnl ${:.2f} -> ${:.2f}",
                    mode,
                    report.old_bankroll,
                    report.new_bankroll,
                    report.old_total_pnl,
                    report.new_total_pnl,
                )

        if apply and commit:
            db.commit()
            db.expire_all()
        return reports
    except Exception:
        if apply:
            db.rollback()
        _facade.logger.exception("BotState reconciliation failed")
        raise
    finally:
        if previous_live_update_permission is None:
            db.info.pop("allow_live_financial_update", None)
        else:
            db.info["allow_live_financial_update"] = previous_live_update_permission
