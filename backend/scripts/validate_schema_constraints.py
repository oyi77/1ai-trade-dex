#!/usr/bin/env python3
"""
Data Validation Audit Script for Schema Constraints

Scans existing database records for FK and CHECK constraint violations BEFORE
adding actual constraints in Alembic migrations.

This script:
1. Validates 16+ strategy_name columns against strategy_config.strategy_name
2. Validates 50+ enum columns for out-of-domain values
3. Outputs structured report: table, column, invalid_value, row_count
4. Suggests cleanup strategies if violations found

Usage:
    python backend/scripts/validate_schema_constraints.py
"""

import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import (
    SessionLocal,
    Trade,
    StrategyConfig,
    TradeAttempt,
    DecisionLog,
)
from backend.models.outcome_tables import (
    StrategyOutcome,
    StrategyHealthRecord,
    ParamChange,
    MetaLearningRecord,
    EvolutionLineage,
    BlockedSignalCounterfactual,
    ProposalFeedback,
    TradingCalibrationRecord,
)
from backend.models.kg_models import (
    ExperimentRecord,
)

# Valid strategy names from registry
VALID_STRATEGY_NAMES = [
    "agi_orchestrator",
    "bond_scanner",
    "btc_momentum",
    "btc_oracle",
    "cex_pm_leadlag",
    "copy_trader",
    "cross_market_arb",
    "general_scanner",
    "kalshi_arb",
    "line_movement_detector",
    "market_maker",
    "probability_arb",
    "realtime_scanner",
    "universal_scanner",
    "weather_emos",
    "whale_frontrun",
    "whale_pnl_tracker",
]

# Enum domain definitions
ENUM_DOMAINS = {
    # Trade enums
    "trades.direction": ["up", "down"],
    "trades.result": ["pending", "win", "loss", "expired", "push", "closed"],
    "trades.trading_mode": ["paper", "testnet", "live"],
    "trades.market_type": ["btc", "weather"],
    "trades.source": ["bot", "manual", "import"],

    # Signal enums
    "signals.side": ["YES", "NO", "up", "down"],
    "signals.status": ["pending", "filled", "cancelled", "expired"],

    # BotState enums
    "bot_state.mode": ["paper", "testnet", "live"],

    # TradeAttempt enums
    "trade_attempts.status": ["STARTED", "COMPLETED", "FAILED", "REJECTED"],
    "trade_attempts.phase": ["created", "validated", "executed", "settled", "failed"],
    "trade_attempts.mode": ["paper", "testnet", "live"],
    "trade_attempts.direction": ["up", "down", "YES", "NO"],
    "trade_attempts.decision": ["BUY", "SELL", "HOLD", "SKIP"],

    # DecisionLog enums
    "decision_log.decision": ["BUY", "SKIP", "SELL", "HOLD", "ERROR"],
    "decision_log.outcome": ["WIN", "LOSS", "PUSH"],

    # StrategyOutcome enums
    "strategy_outcomes.result": ["win", "loss", "push", "pending"],
    "strategy_outcomes.market_type": ["btc", "weather"],
    "strategy_outcomes.trading_mode": ["paper", "testnet", "live"],
    "strategy_outcomes.direction": ["up", "down", "YES", "NO"],

    # StrategyHealthRecord enums
    "strategy_health.status": ["active", "degraded", "paused", "retired"],

    # ExperimentRecord enums
    "experiment_records.status": ["draft", "shadow", "backtest", "promoted", "retired", "failed"],

    # EvolutionLineage enums
    "evolution_lineage.mutation_type": ["perturbation", "crossover", "random", "gradient"],

    # StrategyConfig enums
    "strategy_config.mode": ["paper", "testnet", "live"],
    "strategy_config.risk_tier": ["safe", "conservative", "moderate", "aggressive", "extreme", "crazy"],
}

# Strategy name column mappings: (Model, column_name)
STRATEGY_COLUMNS = [
    (Trade, "strategy"),
    (StrategyConfig, "strategy_name"),
    (TradeAttempt, "strategy"),
    (DecisionLog, "strategy"),
    (StrategyOutcome, "strategy"),
    (StrategyHealthRecord, "strategy"),
    (ParamChange, "strategy"),
    (MetaLearningRecord, "strategy"),
    (EvolutionLineage, "strategy_name"),
    (BlockedSignalCounterfactual, "strategy"),
    (ExperimentRecord, "strategy_name"),
    (ProposalFeedback, "strategy"),
    (TradingCalibrationRecord, "strategy"),
]


class ValidationReport:
    """Collects and formats validation violations."""

    def __init__(self):
        self.fk_violations: List[Dict[str, Any]] = []
        self.enum_violations: List[Dict[str, Any]] = []
        self.total_fk_violations = 0
        self.total_enum_violations = 0

    def add_fk_violation(self, table: str, column: str, invalid_value: str, count: int):
        """Record a foreign key violation."""
        self.fk_violations.append({
            "table": table,
            "column": column,
            "invalid_value": invalid_value,
            "row_count": count,
        })
        self.total_fk_violations += count

    def add_enum_violation(self, table: str, column: str, invalid_value: str, count: int):
        """Record an enum domain violation."""
        self.enum_violations.append({
            "table": table,
            "column": column,
            "invalid_value": invalid_value,
            "row_count": count,
        })
        self.total_enum_violations += count

    def has_violations(self) -> bool:
        """Check if any violations were found."""
        return len(self.fk_violations) > 0 or len(self.enum_violations) > 0

    def format_report(self) -> str:
        """Format the report as structured text."""
        lines = []
        lines.append("=" * 80)
        lines.append("SCHEMA CONSTRAINT VALIDATION REPORT")
        lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append("=" * 80)
        lines.append("")

        # FK violations section
        lines.append("FOREIGN KEY VIOLATIONS (strategy_name columns)")
        lines.append("-" * 80)
        if self.fk_violations:
            lines.append(f"Total violations: {self.total_fk_violations} rows across {len(self.fk_violations)} distinct values")
            lines.append("")
            lines.append(f"{'Table':<30} {'Column':<20} {'Invalid Value':<20} {'Count':>10}")
            lines.append("-" * 80)
            for v in sorted(self.fk_violations, key=lambda x: (-x["row_count"], x["table"])):
                lines.append(f"{v['table']:<30} {v['column']:<20} {v['invalid_value']:<20} {v['row_count']:>10}")
            lines.append("")
            lines.append("CLEANUP STRATEGY:")
            lines.append("  Option 1: SET NULL - Set invalid strategy_name values to NULL")
            lines.append("  Option 2: REPLACE - Replace with 'unknown' or closest valid strategy")
            lines.append("  Option 3: DELETE - Delete rows with invalid strategy_name (DANGEROUS)")
            lines.append("")
        else:
            lines.append("✓ No foreign key violations found")
            lines.append("")

        # Enum violations section
        lines.append("ENUM DOMAIN VIOLATIONS")
        lines.append("-" * 80)
        if self.enum_violations:
            lines.append(f"Total violations: {self.total_enum_violations} rows across {len(self.enum_violations)} distinct values")
            lines.append("")
            lines.append(f"{'Table':<30} {'Column':<20} {'Invalid Value':<20} {'Count':>10}")
            lines.append("-" * 80)
            for v in sorted(self.enum_violations, key=lambda x: (-x["row_count"], x["table"])):
                lines.append(f"{v['table']:<30} {v['column']:<20} {v['invalid_value']:<20} {v['row_count']:>10}")
            lines.append("")
            lines.append("CLEANUP STRATEGY:")
            lines.append("  Option 1: NORMALIZE - Map invalid values to valid enum values")
            lines.append("  Option 2: SET NULL - Set invalid values to NULL (if column allows)")
            lines.append("  Option 3: DELETE - Delete rows with invalid enum values (DANGEROUS)")
            lines.append("")
        else:
            lines.append("✓ No enum domain violations found")
            lines.append("")

        # Summary
        lines.append("=" * 80)
        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Total FK violations: {self.total_fk_violations}")
        lines.append(f"Total enum violations: {self.total_enum_violations}")
        lines.append(f"Total violations: {self.total_fk_violations + self.total_enum_violations}")
        lines.append("")

        if self.has_violations():
            lines.append("⚠️  VIOLATIONS FOUND - Cleanup required before adding constraints")
            lines.append("")
            lines.append("NEXT STEPS:")
            lines.append("1. Review violations above")
            lines.append("2. Create cleanup migration in alembic/versions/")
            lines.append("3. Run cleanup migration")
            lines.append("4. Re-run this validation script")
            lines.append("5. Once clean, proceed with constraint migrations (Tasks 2-3)")
        else:
            lines.append("✅ NO VIOLATIONS - Safe to proceed with constraint migrations")

        lines.append("=" * 80)
        return "\n".join(lines)


def validate_strategy_fk(db: Session, report: ValidationReport):
    """Validate all strategy_name foreign key references."""
    print("Validating strategy_name foreign key references...")

    # Get valid strategy names from strategy_config
    valid_strategies = set(
        row[0] for row in db.query(StrategyConfig.strategy_name).all()
    )

    # If no strategies in DB, use hardcoded list
    if not valid_strategies:
        valid_strategies = set(VALID_STRATEGY_NAMES)
        print(f"  Using hardcoded strategy list: {len(valid_strategies)} strategies")
    else:
        print(f"  Found {len(valid_strategies)} strategies in strategy_config")

    # Check each strategy column
    for model, column_name in STRATEGY_COLUMNS:
        table_name = model.__tablename__
        column = getattr(model, column_name)

        # Query for distinct invalid values
        invalid_values = (
            db.query(column, func.count(column))
            .filter(column.isnot(None))
            .filter(~column.in_(valid_strategies))
            .group_by(column)
            .all()
        )

        for invalid_value, count in invalid_values:
            print(f"  ⚠️  {table_name}.{column_name}: '{invalid_value}' ({count} rows)")
            report.add_fk_violation(table_name, column_name, invalid_value, count)

    print(f"  Found {report.total_fk_violations} FK violations\n")


def validate_enum_domains(db: Session, report: ValidationReport):
    """Validate all enum column domains."""
    print("Validating enum column domains...")

    # Map table.column to (Model, column_name)
    enum_checks = {
        "trades.direction": (Trade, "direction"),
        "trades.result": (Trade, "result"),
        "trades.trading_mode": (Trade, "trading_mode"),
        "trades.market_type": (Trade, "market_type"),
        "trades.source": (Trade, "source"),
        "trade_attempts.status": (TradeAttempt, "status"),
        "trade_attempts.phase": (TradeAttempt, "phase"),
        "trade_attempts.mode": (TradeAttempt, "mode"),
        "trade_attempts.direction": (TradeAttempt, "direction"),
        "trade_attempts.decision": (TradeAttempt, "decision"),
        "decision_log.decision": (DecisionLog, "decision"),
        "decision_log.outcome": (DecisionLog, "outcome"),
        "strategy_outcomes.result": (StrategyOutcome, "result"),
        "strategy_outcomes.market_type": (StrategyOutcome, "market_type"),
        "strategy_outcomes.trading_mode": (StrategyOutcome, "trading_mode"),
        "strategy_outcomes.direction": (StrategyOutcome, "direction"),
        "strategy_health.status": (StrategyHealthRecord, "status"),
        "experiment_records.status": (ExperimentRecord, "status"),
        "evolution_lineage.mutation_type": (EvolutionLineage, "mutation_type"),
    }

    for table_col, (model, column_name) in enum_checks.items():
        if table_col not in ENUM_DOMAINS:
            continue

        valid_values = set(ENUM_DOMAINS[table_col])
        column = getattr(model, column_name)
        table_name = model.__tablename__

        # Query for distinct invalid values
        invalid_values = (
            db.query(column, func.count(column))
            .filter(column.isnot(None))
            .filter(~column.in_(valid_values))
            .group_by(column)
            .all()
        )

        for invalid_value, count in invalid_values:
            print(f"  ⚠️  {table_name}.{column_name}: '{invalid_value}' ({count} rows)")
            report.add_enum_violation(table_name, column_name, invalid_value, count)

    print(f"  Found {report.total_enum_violations} enum violations\n")


def main():
    """Run validation and generate report."""
    print("=" * 80)
    print("SCHEMA CONSTRAINT VALIDATION AUDIT")
    print("=" * 80)
    print()

    db = SessionLocal()
    report = ValidationReport()

    try:
        # Run validations
        validate_strategy_fk(db, report)
        validate_enum_domains(db, report)

        # Generate report
        report_text = report.format_report()
        print(report_text)

        # Save report to evidence directory
        evidence_dir = ".sisyphus/evidence"
        os.makedirs(evidence_dir, exist_ok=True)
        report_path = os.path.join(evidence_dir, "task-1-validation-report.txt")

        with open(report_path, "w") as f:
            f.write(report_text)

        print(f"\n📄 Report saved to: {report_path}")

        # Exit with error code if violations found
        if report.has_violations():
            sys.exit(1)
        else:
            sys.exit(0)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    finally:
        db.close()


if __name__ == "__main__":
    main()
