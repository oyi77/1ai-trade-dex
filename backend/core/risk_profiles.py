"""Dynamic risk profiles per ADR-005.

Profiles are stored in DB (risk_profiles table). Four operator-selectable
presets (safe, normal, aggressive, extreme) are seeded on first boot.
Profiles are fully editable at runtime via REST API — no code changes needed.
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, Optional

from sqlalchemy import Column, String, Float, Boolean
from sqlalchemy.orm import Session

from backend.models.database import Base, SessionLocal

from loguru import logger
class RiskProfileRow(Base):
    __tablename__ = "risk_profiles"

    name = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    kelly_fraction = Column(Float, nullable=False, default=0.3)
    min_edge_threshold = Column(Float, nullable=False, default=0.3)
    max_trade_size = Column(Float, nullable=False, default=8.0)
    max_position_fraction = Column(Float, nullable=False, default=0.08)
    max_total_exposure_fraction = Column(Float, nullable=False, default=0.7)
    daily_loss_limit = Column(Float, nullable=False, default=5.0)
    daily_loss_limit_pct = Column(Float, nullable=False, default=0.10)
    daily_drawdown_limit_pct = Column(Float, nullable=False, default=0.1)
    weekly_drawdown_limit_pct = Column(Float, nullable=False, default=0.2)
    slippage_tolerance = Column(Float, nullable=False, default=0.02)
    auto_approve_min_confidence = Column(Float, nullable=False, default=0.5)
    is_preset = Column(Boolean, nullable=False, default=False)


@dataclass(frozen=True)
class RiskProfile:
    name: str
    display_name: str
    kelly_fraction: float
    min_edge_threshold: float
    max_trade_size: float
    max_position_fraction: float
    max_total_exposure_fraction: float
    daily_loss_limit: float
    daily_drawdown_limit_pct: float
    weekly_drawdown_limit_pct: float
    slippage_tolerance: float
    auto_approve_min_confidence: float
    daily_loss_limit_pct: float = 0.10
    daily_loss_floor_pct: float = -0.10
    weekly_loss_floor_pct: float = -0.20
    longshot_no_bias_weight: float = 0.10
    is_preset: bool = False

    def to_row(self) -> RiskProfileRow:
        return RiskProfileRow(
            name=self.name,
            display_name=self.display_name,
            kelly_fraction=self.kelly_fraction,
            min_edge_threshold=self.min_edge_threshold,
            max_trade_size=self.max_trade_size,
            max_position_fraction=self.max_position_fraction,
            max_total_exposure_fraction=self.max_total_exposure_fraction,
            daily_loss_limit=self.daily_loss_limit,
            daily_loss_limit_pct=self.daily_loss_limit_pct,
            daily_drawdown_limit_pct=self.daily_drawdown_limit_pct,
            weekly_drawdown_limit_pct=self.weekly_drawdown_limit_pct,
            slippage_tolerance=self.slippage_tolerance,
            auto_approve_min_confidence=self.auto_approve_min_confidence,
            is_preset=self.is_preset,
        )


PRESETS: Dict[str, RiskProfile] = {
    "safe": RiskProfile(
        name="safe", display_name="Safe", is_preset=True,
        kelly_fraction=0.10, min_edge_threshold=0.40, max_trade_size=3.0,
        max_position_fraction=0.03, max_total_exposure_fraction=0.30,
        daily_loss_limit=2.0, daily_drawdown_limit_pct=0.05,
        weekly_drawdown_limit_pct=0.10, slippage_tolerance=0.01,
        auto_approve_min_confidence=0.70,
        daily_loss_limit_pct=0.05,
        longshot_no_bias_weight=0.05,
    ),
    # conservative sits between safe and normal — suitable for strategies that
    # have passed paper validation but haven't yet proven live performance.
    "conservative": RiskProfile(
        name="conservative", display_name="Conservative", is_preset=True,
        kelly_fraction=0.20, min_edge_threshold=0.35, max_trade_size=5.0,
        max_position_fraction=0.05, max_total_exposure_fraction=0.50,
        daily_loss_limit=3.0, daily_drawdown_limit_pct=0.07,
        weekly_drawdown_limit_pct=0.15, slippage_tolerance=0.015,
        auto_approve_min_confidence=0.60,
        daily_loss_limit_pct=0.07,
        longshot_no_bias_weight=0.07,
    ),
    "normal": RiskProfile(
        name="normal", display_name="Normal", is_preset=True,
        kelly_fraction=0.30, min_edge_threshold=0.30, max_trade_size=8.0,
        max_position_fraction=0.08, max_total_exposure_fraction=0.70,
        daily_loss_limit=5.0, daily_drawdown_limit_pct=0.10,
        weekly_drawdown_limit_pct=0.20, slippage_tolerance=0.02,
        auto_approve_min_confidence=0.50,
        daily_loss_limit_pct=0.10,
        longshot_no_bias_weight=0.10,
    ),
    "aggressive": RiskProfile(
        name="aggressive", display_name="Aggressive", is_preset=True,
        kelly_fraction=0.50, min_edge_threshold=0.15, max_trade_size=20.0,
        max_position_fraction=0.15, max_total_exposure_fraction=0.85,
        daily_loss_limit=15.0, daily_drawdown_limit_pct=0.20,
        weekly_drawdown_limit_pct=0.35, slippage_tolerance=0.03,
        auto_approve_min_confidence=0.35,
        daily_loss_limit_pct=0.20,
        longshot_no_bias_weight=0.12,
    ),
    "extreme": RiskProfile(
        name="extreme", display_name="Extreme", is_preset=True,
        kelly_fraction=0.80, min_edge_threshold=0.05, max_trade_size=50.0,
        max_position_fraction=0.25, max_total_exposure_fraction=0.95,
        daily_loss_limit=40.0, daily_drawdown_limit_pct=0.40,
        weekly_drawdown_limit_pct=0.60, slippage_tolerance=0.05,
        auto_approve_min_confidence=0.20,
        daily_loss_limit_pct=0.40,
        daily_loss_floor_pct=-0.40, weekly_loss_floor_pct=-0.60,
        longshot_no_bias_weight=0.15,
    ),
    # crazy tier is for unlimited paper experimentation only. BankrollAllocator
    # caps live allocation at 1% of bankroll for crazy-tier strategies.
    # FronttestValidator skips the 14-day minimum gate for crazy-tier.
    "crazy": RiskProfile(
        name="crazy", display_name="Crazy (Experimental)", is_preset=True,
        kelly_fraction=1.00, min_edge_threshold=0.01, max_trade_size=100.0,
        max_position_fraction=0.50, max_total_exposure_fraction=1.00,
        daily_loss_limit=100.0, daily_drawdown_limit_pct=0.80,
        weekly_drawdown_limit_pct=0.95, slippage_tolerance=0.10,
        auto_approve_min_confidence=0.10,
        daily_loss_limit_pct=0.80,
        daily_loss_floor_pct=-0.80, weekly_loss_floor_pct=-0.95,
        longshot_no_bias_weight=0.20,
    ),
}

DEFAULT_PROFILE = "normal"

# Maximum fraction of total bankroll that BankrollAllocator may assign to a
# single strategy, keyed by risk_tier.  Tiers not listed fall back to the
# "moderate" cap.  "crazy" is intentionally capped at 1% for live trading;
# paper/shadow experiments are uncapped by design.
RISK_TIER_MAX_ALLOCATION: Dict[str, float] = {
    "safe":         0.50,
    "conservative": 0.30,
    "moderate":     0.20,
    "aggressive":   0.15,
    "extreme":      0.05,
    "crazy":        0.01,
}


def seed_presets(db: Optional[Session] = None) -> None:
    _owned = db is None
    db = db or SessionLocal()
    try:
        for name, profile in PRESETS.items():
            existing = db.query(RiskProfileRow).filter_by(name=name).first()
            if not existing:
                db.add(profile.to_row())
        db.commit()
    except Exception as e:
        logger.warning("[risk_profiles] Seed failed: %s", e)
        logger.exception("[risk_profiles] Seed failed")
        try:
            db.rollback()
        except Exception:
            logger.exception("[risk_profiles] Rollback failed during seed")
    finally:
        if _owned:
            db.close()


def get_active_profile_name() -> str:
    return os.environ.get("RISK_PROFILE", DEFAULT_PROFILE)


def get_profile(name: Optional[str] = None, db: Optional[Session] = None) -> RiskProfile:
    key = name or get_active_profile_name()
    _owned = db is None
    db = db or SessionLocal()
    try:
        row = db.query(RiskProfileRow).filter_by(name=key).first()
        if row:
            return _row_to_profile(row)
    except Exception:
        logger.exception("[risk_profiles] Failed to get profile from database")
    finally:
        if _owned:
            db.close()

    preset = PRESETS.get(key)
    if preset:
        return preset
    logger.warning("[risk_profiles] Unknown profile '%s', falling back to '%s'", key, DEFAULT_PROFILE)
    return PRESETS[DEFAULT_PROFILE]


def list_profiles(db: Optional[Session] = None) -> Dict[str, RiskProfile]:
    _owned = db is None
    db = db or SessionLocal()
    result: Dict[str, RiskProfile] = {}
    try:
        rows = db.query(RiskProfileRow).all()
        for row in rows:
            result[row.name] = _row_to_profile(row)
    except Exception:
        logger.exception("[risk_profiles] Failed to list profiles from database")
    finally:
        if _owned:
            db.close()

    for name, preset in PRESETS.items():
        if name not in result:
            result[name] = preset

    return result


def create_profile(profile: RiskProfile, db: Optional[Session] = None) -> RiskProfile:
    _owned = db is None
    db = db or SessionLocal()
    try:
        existing = db.query(RiskProfileRow).filter_by(name=profile.name).first()
        if existing:
            raise ValueError(f"profile '{profile.name}' already exists")
        db.add(profile.to_row())
        db.commit()
        return profile
    except Exception:
        logger.exception("[risk_profiles] Failed to create profile")
        db.rollback()
        raise
    finally:
        if _owned:
            db.close()


def update_profile(name: str, updates: dict, db: Optional[Session] = None) -> RiskProfile:
    _owned = db is None
    db = db or SessionLocal()
    try:
        row = db.query(RiskProfileRow).filter_by(name=name).first()
        if not row:
            preset = PRESETS.get(name)
            if preset:
                row = preset.to_row()
                db.add(row)
            else:
                raise ValueError(f"profile '{name}' not found")

        for key, value in updates.items():
            if key == "name":
                continue
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)

        db.commit()
        return _row_to_profile(row)
    except Exception:
        logger.exception("[risk_profiles] Failed to update profile '%s'", name)
        db.rollback()
        raise
    finally:
        if _owned:
            db.close()


def delete_profile(name: str, db: Optional[Session] = None) -> bool:
    if name in PRESETS:
        return False
    _owned = db is None
    db = db or SessionLocal()
    try:
        row = db.query(RiskProfileRow).filter_by(name=name).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
    except Exception:
        logger.exception("[risk_profiles] Failed to delete profile '%s'", name)
        db.rollback()
        return False
    finally:
        if _owned:
            db.close()


def apply_profile(name: Optional[str] = None, db: Optional[Session] = None) -> RiskProfile:
    from backend.config import settings

    profile = get_profile(name, db=db)
    settings.KELLY_FRACTION = profile.kelly_fraction
    settings.MIN_EDGE_THRESHOLD = profile.min_edge_threshold
    settings.MAX_TRADE_SIZE = profile.max_trade_size
    settings.MAX_POSITION_FRACTION = profile.max_position_fraction
    settings.MAX_TOTAL_EXPOSURE_FRACTION = profile.max_total_exposure_fraction
    settings.DAILY_LOSS_LIMIT = profile.daily_loss_limit
    settings.DAILY_LOSS_LIMIT_PCT = profile.daily_loss_limit_pct
    settings.DAILY_DRAWDOWN_LIMIT_PCT = profile.daily_drawdown_limit_pct
    settings.WEEKLY_DRAWDOWN_LIMIT_PCT = profile.weekly_drawdown_limit_pct
    settings.SLIPPAGE_TOLERANCE = profile.slippage_tolerance
    settings.AUTO_APPROVE_MIN_CONFIDENCE = profile.auto_approve_min_confidence
    settings.DAILY_LOSS_FLOOR_PCT = profile.daily_loss_floor_pct
    settings.WEEKLY_LOSS_FLOOR_PCT = profile.weekly_loss_floor_pct
    settings.LONGSHOT_NO_BIAS_WEIGHT = profile.longshot_no_bias_weight

    _persist_profile_name(profile.name)

    logger.info("[risk_profiles] Applied profile '%s' to runtime settings", profile.display_name)
    return profile


def _row_to_profile(row: RiskProfileRow) -> RiskProfile:
    return RiskProfile(
        name=row.name,
        display_name=row.display_name,
        kelly_fraction=row.kelly_fraction,
        min_edge_threshold=row.min_edge_threshold,
        max_trade_size=row.max_trade_size,
        max_position_fraction=row.max_position_fraction,
        max_total_exposure_fraction=row.max_total_exposure_fraction,
        daily_loss_limit=row.daily_loss_limit,
        daily_loss_limit_pct=row.daily_loss_limit_pct,
        daily_drawdown_limit_pct=row.daily_drawdown_limit_pct,
        weekly_drawdown_limit_pct=row.weekly_drawdown_limit_pct,
        slippage_tolerance=row.slippage_tolerance,
        auto_approve_min_confidence=row.auto_approve_min_confidence,
        is_preset=row.is_preset,
    )


def _persist_profile_name(name: str) -> None:
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        lines: list[str] = []
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()

        found = False
        for i, line in enumerate(lines):
            if line.startswith("RISK_PROFILE="):
                lines[i] = f"RISK_PROFILE={name}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith("\n"):
                lines.append("\n")
            lines.append(f"RISK_PROFILE={name}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)
        os.environ["RISK_PROFILE"] = name
    except Exception as e:
        logger.exception("[risk_profiles] Failed to persist RISK_PROFILE to .env")
        logger.warning("[risk_profiles] Failed to persist RISK_PROFILE to .env: %s", e)
