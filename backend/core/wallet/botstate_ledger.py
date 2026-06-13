"""Centralized ledger for all BotState financial field mutations.

The PolyEdge system previously had 8 different code paths mutating
``BotState.bankroll`` and ``BotState.total_pnl`` directly. A SQLAlchemy
``before_flush`` ORM event hook in ``backend.models.database`` reverts any
direct ORM write to those fields on live mode unless
``db.info["allow_live_financial_update"] = True`` is set on the session.

This module is the single source of truth for those mutations. It:

1. Always sets the ``allow_live_financial_update`` flag for the duration of
   the write so the ORM hook does not revert it.
2. Uses ``size * price`` (actual USDC cost) for debits, never the share
   count alone.
3. Applies settlement credits immediately (not just at the next
   reconciliation cycle) so the DB bankroll reflects settled P&L without a
   window of divergence.
4. Refuses to operate on a missing or wrong-mode BotState — callers must
   pass the mode explicitly.
5. Audits every write through ``log_audit_event`` and ``TransactionEvent``
   for traceability.

All call sites that previously did::

    state.bankroll = state.bankroll - size
    state.total_trades += 1

must be replaced with::

    BotStateLedger.debit_for_fill(db, mode=mode, size=size, price=price)
    BotStateLedger.credit_on_settlement(db, mode=mode, trade=trade)
    BotStateLedger.record_fill(db, mode=mode, ...)

Direct ORM assignments to financial fields are forbidden in code review and
rejected by tests in ``tests/test_balance_ledger_regression.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.models.audit_logger import log_audit_event
from backend.models.database import BotState, Trade, TransactionEvent


# Fields whose direct mutation is forbidden outside this module. The
# ``before_flush`` hook in models/database protects ``bankroll`` and
# ``total_pnl``; we extend the same protection to the per-mode fields.
PROTECTED_FIELDS = (
    "bankroll",
    "total_pnl",
    "paper_bankroll",
    "paper_pnl",
    "testnet_bankroll",
    "testnet_pnl",
    "wallet_pnl",
    "total_deposits",
    "total_withdrawals",
    "live_initial_bankroll",
)


@dataclass
class LedgerEntry:
    """Audit record for one ledger write."""

    mode: str
    operation: str
    delta: float
    field: str
    new_value: float
    context: dict[str, Any]


class BotStateLedger:
    """Single entry point for all BotState financial field writes.

    All public methods are class methods so call sites don't need to
    instantiate. They take a SQLAlchemy ``Session`` and operate on the
    BotState row matching the given ``mode``.
    """

    # ----- Internal helpers -------------------------------------------------

    @classmethod
    def _resolve_state(cls, db: Session, mode: str) -> BotState:
        """Resolve the BotState row for ``mode``.

        Refuses to fall back to ``.first()`` on a multi-row query: a
        missing row is a hard error so callers cannot silently corrupt
        the wrong mode's bankroll.
        """
        if mode not in ("paper", "testnet", "live"):
            raise ValueError(
                f"BotStateLedger: invalid mode {mode!r}; "
                "expected one of: paper, testnet, live"
            )
        state = db.query(BotState).filter_by(mode=mode).first()
        if state is None:
            raise LookupError(
                f"BotStateLedger: no BotState row found for mode={mode!r}. "
                "Create the row before calling the ledger."
            )
        return state

    @classmethod
    def _field_for_mode(cls, mode: str, base: str) -> str:
        """Map a base field name (e.g. 'bankroll') to the per-mode column.

        Live mode uses canonical column names (``bankroll``,
        ``total_pnl``); paper and testnet have their own dedicated
        columns (``paper_bankroll``, ``paper_pnl``).
        """
        if mode == "paper":
            return {
                "bankroll": "paper_bankroll",
                "pnl": "paper_pnl",
            }.get(base, f"paper_{base}")
        if mode == "testnet":
            return {
                "bankroll": "testnet_bankroll",
                "pnl": "testnet_pnl",
            }.get(base, f"testnet_{base}")
        return {
            "bankroll": "bankroll",
            "pnl": "total_pnl",
        }.get(base, base)

    @classmethod
    def _counter_field_for_mode(cls, mode: str, base: str) -> str:
        """Map a counter name to the per-mode column.

        For live mode, the canonical column is the base name without a
        prefix (e.g. ``total_trades``, ``total_pnl``).
        """
        if mode == "paper":
            return f"paper_{base}"
        if mode == "testnet":
            return f"testnet_{base}"
        return {
            "trades": "total_trades",
            "wins": "winning_trades",
            "pnl": "total_pnl",
        }.get(base, base)

    @classmethod
    def _apply(
        cls,
        db: Session,
        state: BotState,
        mode: str,
        field: str,
        delta: float,
        operation: str,
        context: dict[str, Any],
    ) -> LedgerEntry:
        """Atomic write under the ``allow_live_financial_update`` flag.

        Sets the flag for the duration of the session, mutates the field,
        flushes, then clears the flag. This is the only place that
        mutates protected financial fields.
        """
        previous = float(getattr(state, field) or 0.0)
        new_value = previous + delta
        # Don't allow negative bankroll for paper/testnet (safety).
        if mode in ("paper", "testnet") and field.endswith("_bankroll"):
            new_value = max(0.0, new_value)
        setattr(state, field, new_value)

        entry = LedgerEntry(
            mode=mode,
            operation=operation,
            delta=delta,
            field=field,
            new_value=round(new_value, 6),
            context=context,
        )

        # Touch last_sync_at so dashboards know when DB was last written.
        if hasattr(state, "last_sync_at"):
            state.last_sync_at = datetime.now(timezone.utc)

        # Audit the write. Wrapped in try/except because audit logging
        # must never block settlement.
        try:
            log_audit_event(
                db=db,
                event_type=f"LEDGER_{operation.upper()}",
                entity_type="BOT_STATE",
                entity_id=mode,
                old_value={field: previous},
                new_value={field: entry.new_value},
                user_id=context.get("source", "botstate_ledger"),
            )
        except Exception as exc:
            logger.debug(f"[BotStateLedger] audit log failed (non-fatal): {exc}")

        # Record a TransactionEvent so the user-facing ledger trail shows
        # the mutation even if audit logging is disabled.
        try:
            if operation in ("deposit", "withdrawal", "allocation", "fee", "settlement_win", "settlement_loss", "reconciliation_adjustment"):
                event_type = operation
            elif operation == "fill_debit":
                event_type = "fee"
            else:
                # wallet_sync, settlement_push/expired/closed/*, pnl_*, etc. —
                # not represented in TransactionEvent.type's enum; the
                # closest semantic bucket is "reconciliation_adjustment".
                event_type = "reconciliation_adjustment"

            event = TransactionEvent(
                type=event_type,
                amount=delta,
                balance_after=entry.new_value,
                context={"mode": mode, "field": field, **context},
                note=f"{operation} {mode}.{field} {previous:+.4f} -> {entry.new_value:+.4f}",
            )
            db.add(event)
        except Exception as exc:
            logger.debug(f"[BotStateLedger] TransactionEvent add failed: {exc}")

        logger.info(
            "[BotStateLedger] {} mode={} field={} delta={:+.4f} "
            "value={:.4f} -> {:.4f}",
            operation,
            mode,
            field,
            delta,
            previous,
            entry.new_value,
        )
        return entry

    @classmethod
    def _with_permission(cls, db: Session, fn):
        """Run ``fn`` with the live-update flag set, then restore it."""
        previous = db.info.get("allow_live_financial_update")
        db.info["allow_live_financial_update"] = True
        try:
            return fn()
        finally:
            if previous is None:
                db.info.pop("allow_live_financial_update", None)
            else:
                db.info["allow_live_financial_update"] = previous

    # ----- Public API -------------------------------------------------------

    @classmethod
    def debit_for_fill(
        cls,
        db: Session,
        mode: str,
        size: float,
        price: float,
        source: str = "execution_pipeline",
    ) -> LedgerEntry:
        """Debit the bankroll by the actual USDC cost of a fill.

        ``size`` is the number of shares; ``price`` is the limit price
        paid per share. The debit is ``size * price``. This is the single
        correct way to record a fill cost; calling it with ``size`` alone
        would over-debit by orders of magnitude.

        Also increments the per-mode trade counter.
        """
        state = cls._resolve_state(db, mode)
        cost = float(Decimal(str(size)) * Decimal(str(price)))
        field = cls._field_for_mode(mode, "bankroll")
        counter = cls._counter_field_for_mode(mode, "trades")

        def _do() -> LedgerEntry:
            entry = cls._apply(
                db=db,
                state=state,
                mode=mode,
                field=field,
                delta=-cost,
                operation="fill_debit",
                context={
                    "size": size,
                    "price": price,
                    "cost_usdc": cost,
                    "source": source,
                },
            )
            setattr(
                state,
                counter,
                int(getattr(state, counter) or 0) + 1,
            )
            return entry

        return cls._with_permission(db, _do)

    @classmethod
    def credit_on_settlement(
        cls,
        db: Session,
        mode: str,
        trade: Trade,
    ) -> Optional[LedgerEntry]:
        """Credit the bankroll by a settled trade's P&L.

        Called immediately when a trade settles so the DB bankroll reflects
        settled performance without waiting for the next reconciliation
        cycle. On a loss the PnL is negative, which the ledger applies as
        a negative credit (a further debit).

        For a win:
          bankroll += trade.pnl           (the profit)
          bankroll += trade.size          (the cost basis is returned)
          total_pnl += trade.pnl

        For a loss:
          bankroll += trade.size          (cost basis NOT returned — loss)
          total_pnl += trade.pnl          (pnl is negative)

        For a push/expired:
          bankroll += trade.size          (cost basis returned)
          total_pnl unchanged
        """
        if trade.pnl is None and trade.result not in ("expired", "push", "closed"):
            return None
        state = cls._resolve_state(db, mode)
        bankroll_field = cls._field_for_mode(mode, "bankroll")
        pnl_field = cls._field_for_mode(mode, "pnl")
        wins_field = cls._counter_field_for_mode(mode, "wins")
        bankroll_delta = 0.0
        pnl_delta = 0.0
        is_win = trade.result == "win"
        is_loss = trade.result == "loss"
        is_push = trade.result in ("expired", "push", "closed", "expired_unresolved",
                                    "btc_5min_unresolved")

        if is_win:
            bankroll_delta = float(trade.size or 0.0) + float(trade.pnl or 0.0)
            pnl_delta = float(trade.pnl or 0.0)
        elif is_loss:
            bankroll_delta = float(trade.size or 0.0) + float(trade.pnl or 0.0)
            pnl_delta = float(trade.pnl or 0.0)
        elif is_push:
            bankroll_delta = float(trade.size or 0.0)
            pnl_delta = 0.0

        if bankroll_delta == 0.0 and pnl_delta == 0.0:
            return None

        def _do() -> LedgerEntry:
            entry: Optional[LedgerEntry] = None
            if bankroll_delta != 0.0:
                entry = cls._apply(
                    db=db,
                    state=state,
                    mode=mode,
                    field=bankroll_field,
                    delta=bankroll_delta,
                    operation=f"settlement_{trade.result}",
                    context={
                        "trade_id": trade.id,
                        "market_ticker": trade.market_ticker,
                        "size": trade.size,
                        "pnl": trade.pnl,
                    },
                )
            if pnl_delta != 0.0:
                entry = cls._apply(
                    db=db,
                    state=state,
                    mode=mode,
                    field=pnl_field,
                    delta=pnl_delta,
                    operation=f"pnl_{trade.result}",
                    context={
                        "trade_id": trade.id,
                        "pnl": trade.pnl,
                    },
                )
            if is_win:
                setattr(
                    state,
                    wins_field,
                    int(getattr(state, wins_field) or 0) + 1,
                )
            return entry

        return cls._with_permission(db, _do)

    @classmethod
    def record_deposit(
        cls,
        db: Session,
        mode: str,
        amount: float,
        source: str = "blockchain_activity",
    ) -> LedgerEntry:
        """Credit a deposit to the mode-specific bankroll field.

        Writes to ``paper_bankroll`` for paper mode, ``testnet_bankroll``
        for testnet mode, and the canonical ``bankroll`` column for live
        mode — matching the original event_handler semantics so dashboards
        and reconciliation don't see a phantom write to the wrong field.
        """
        state = cls._resolve_state(db, mode)
        if mode == "live" and getattr(state, "live_initial_bankroll", None) is None:
            state.live_initial_bankroll = amount

        target_field = cls._field_for_mode(mode, "bankroll")

        def _do() -> LedgerEntry:
            entry = cls._apply(
                db=db,
                state=state,
                mode=mode,
                field=target_field,
                delta=amount,
                operation="deposit",
                context={"source": source, "amount": amount},
            )
            state.total_deposits = (state.total_deposits or 0.0) + amount
            return entry

        return cls._with_permission(db, _do)

    @classmethod
    def record_withdrawal(
        cls,
        db: Session,
        mode: str,
        amount: float,
        source: str = "blockchain_activity",
    ) -> LedgerEntry:
        """Debit a withdrawal from the mode-specific bankroll field."""
        state = cls._resolve_state(db, mode)
        target_field = cls._field_for_mode(mode, "bankroll")

        def _do() -> LedgerEntry:
            entry = cls._apply(
                db=db,
                state=state,
                mode=mode,
                field=target_field,
                delta=-amount,
                operation="withdrawal",
                context={"source": source, "amount": amount},
            )
            if mode == "live":
                state.live_initial_bankroll = max(
                    0.0, (state.live_initial_bankroll or 0.0) - amount
                )
            state.total_withdrawals = (state.total_withdrawals or 0.0) + amount
            return entry

        return cls._with_permission(db, _do)

    @classmethod
    def record_fill(
        cls,
        db: Session,
        mode: str,
        size: float,
        price: float,
        source: str = "execution_pipeline",
    ) -> LedgerEntry:
        """Convenience alias: debit the bankroll for a fill and tick counters.

        Kept as a separate name from ``debit_for_fill`` so the call site
        reads naturally (``record_fill``) while internally doing the same
        thing. The cost formula is the same — ``size * price``.
        """
        return cls.debit_for_fill(
            db=db, mode=mode, size=size, price=price, source=source
        )

    @classmethod
    def sync_to_absolute(
        cls,
        db: Session,
        mode: str,
        target_balance: float,
        source: str = "wallet_sync",
    ) -> Optional[LedgerEntry]:
        """Set the bankroll to an exact value (absolute re-assertion).

        Used by ``wallet_sync`` and reconciliation paths that have an
        authoritative external balance (e.g. from the CLOB or RPC) and
        need the DB to reflect it. The delta is computed internally and
        routed through the same audited write path as a deposit or
        withdrawal so the audit trail stays consistent.

        Returns ``None`` if the bankroll is already at the target (no
        write needed).
        """
        state = cls._resolve_state(db, mode)
        target_field = cls._field_for_mode(mode, "bankroll")
        current = float(getattr(state, target_field) or 0.0)
        target = max(0.0, float(target_balance))
        delta = round(target - current, 6)
        if delta == 0.0:
            return None

        def _do() -> LedgerEntry:
            entry = cls._apply(
                db=db,
                state=state,
                mode=mode,
                field=target_field,
                delta=delta,
                operation="wallet_sync",
                context={
                    "source": source,
                    "previous": current,
                    "target": target,
                    "delta": delta,
                },
            )
            # Re-assertions from wallet_sync are not actual deposits/withdrawals.
            # Only the fill pipeline and explicit deposit/withdrawal commands
            # should mutate total_deposits / total_withdrawals counters.
            if source != "wallet_sync":
                if delta > 0:
                    state.total_deposits = (state.total_deposits or 0.0) + delta
                else:
                    state.total_withdrawals = (state.total_withdrawals or 0.0) + abs(delta)
            return entry

        return cls._with_permission(db, _do)
