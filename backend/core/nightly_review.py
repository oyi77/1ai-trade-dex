"""Nightly review — writes daily markdown logs with calibration and improvement plans."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import SessionLocal, Trade, StrategyConfig, BotState, for_update

logger = logging.getLogger("trading_bot.nightly_review")


class NightlyReviewWriter:
    """Generates nightly AGI review reports as markdown files."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or settings.AGI_NIGHTLY_REVIEW_OUTPUT_DIR

    def generate(self, db: Optional[Session] = None) -> Optional[str]:
        _owned = db is None
        db = db or SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            date_str = now.strftime("%Y-%m-%d")

            lines = [
                f"# AGI Nightly Review — {date_str}\n",
                f"Generated: {now.isoformat()}\n",
            ]

            lines.extend(self._section_summary(db, now))
            lines.extend(self._section_strategy_metrics(db, now))
            lines.extend(self._section_calibration(db))
            lines.extend(self._section_improvement_plan(db))

            content = "\n".join(lines)

            os.makedirs(self.output_dir, exist_ok=True)
            path = os.path.join(self.output_dir, f"{date_str}.md")

            with open(path, "w") as f:
                f.write(content)

            logger.info("[NightlyReview] Written to %s", path)

            # TODO: Wire NightlyReview output into KnowledgeGraph (Wave 10)
            # Publish event for KnowledgeGraph integration
            from backend.core.event_bus import publish_event
            publish_event("nightly_review_complete", {
                "date": date_str,
                "file_path": path
            })

            return path
        except Exception as e:
            logger.error("[NightlyReview] Failed: %s", e)
            return None
        finally:
            if _owned:
                db.close()

    def _section_summary(self, db: Session, now: datetime) -> list[str]:
        from datetime import timedelta

        lines = ["\n## Daily Summary\n"]
        try:
            from backend.config import settings

            for mode in settings.active_modes_set:
                bot = for_update(db, db.query(BotState).filter(
                    BotState.mode == mode
                )).first()
                if bot:
                    lines.append(f"### Mode: {mode}")
                    lines.append(f"- **Bankroll**: ${bot.bankroll or 0:.2f}")
                    lines.append(f"- **Total PnL**: ${bot.total_pnl or 0:.2f}")
                    lines.append(f"- **Total Trades**: {bot.total_trades or 0}")

            yesterday = now - timedelta(days=1)
            recent = (
                db.query(Trade)
                .filter(Trade.timestamp >= yesterday, Trade.settled.is_(True))
                .all()
            )
            wins = sum(1 for t in recent if t.result == "win")
            losses = sum(1 for t in recent if t.result == "loss")
            total = wins + losses
            wr = wins / total if total > 0 else 0.0
            pnl = sum(t.pnl or 0.0 for t in recent)

            lines.append(f"- **Last 24h Trades**: {total} ({wins}W/{losses}L)")
            lines.append(f"- **Last 24h Win Rate**: {wr:.0%}")
            lines.append(f"- **Last 24h PnL**: ${pnl:.2f}")
        except Exception as e:
            lines.append(f"- Error: {e}")
        return lines

    def _section_strategy_metrics(self, db: Session, now: datetime) -> list[str]:
        from datetime import timedelta

        lookback_days = settings.AGI_NIGHTLY_REVIEW_LOOKBACK_DAYS
        lines = [f"\n## Strategy Performance ({lookback_days}-day)\n"]
        try:
            week_ago = now - timedelta(days=lookback_days)
            configs = db.query(StrategyConfig).all()
            for cfg in configs:
                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == cfg.strategy_name,
                        Trade.timestamp >= week_ago,
                        Trade.settled.is_(True),
                    )
                    .all()
                )
                settled = [t for t in trades if t.result in ("win", "loss")]
                if not settled:
                    continue
                wins = sum(1 for t in settled if t.result == "win")
                wr = wins / len(settled)
                pnl = sum(t.pnl or 0.0 for t in settled)
                enabled = "enabled" if cfg.enabled else "disabled"
                lines.append(
                    f"- **{cfg.strategy_name}** ({enabled}): "
                    f"{len(settled)} trades, WR={wr:.0%}, PnL=${pnl:.2f}"
                )
            if len(lines) == 1:
                lines.append("- No strategy data this period")
        except Exception as e:
            lines.append(f"- Error: {e}")
        return lines

    def _section_calibration(self, db: Session) -> list[str]:
        lines = ["\n## Model Calibration\n"]
        try:
            from backend.core.trading_calibration import TradingCalibration

            cal = TradingCalibration()
            summary = cal.summary()
            if summary:
                for strategy, metrics in summary.items():
                    if isinstance(metrics, dict):
                        n = metrics.get("total", 0)
                        if n > 0:
                            brier = metrics.get("brier", "N/A")
                            lines.append(f"- **{strategy}**: n={n}, Brier={brier}")
            if len(lines) == 1:
                lines.append("- No calibration data yet")
        except Exception as e:
            lines.append(f"- Calibration unavailable: {e}")
        return lines

    def _section_improvement_plan(self, db: Session) -> list[str]:
        lines = ["\n## Improvement Plan\n"]
        try:
            from backend.models.database import StrategyProposal

            pending = (
                db.query(StrategyProposal)
                .filter(StrategyProposal.status == "pending")
                .order_by(StrategyProposal.created_at.desc())
                .limit(5)
                .all()
            )
            if pending:
                for p in pending:
                    lines.append(
                        f"- Proposal #{p.id}: {p.strategy_name} — "
                        f"{p.expected_impact or 'no impact desc'} [{p.admin_decision}]"
                    )
            else:
                lines.append("- No pending proposals")

            disabled = db.query(StrategyConfig).filter(StrategyConfig.enabled == False).all()
            if disabled:
                lines.append(f"\n### Disabled Strategies ({len(disabled)})\n")
                for d in disabled:
                    lines.append(f"- {d.strategy_name}")
        except Exception as e:
            lines.append(f"- Error: {e}")
        return lines


nightly_review_writer = NightlyReviewWriter()
