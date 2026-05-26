import os
from unittest.mock import patch

from sqlalchemy import text

from backend.core.risk_profiles import (
    PRESETS,
    RiskProfile,
    DEFAULT_PROFILE,
    get_profile,
    get_active_profile_name,
    apply_profile,
    list_profiles,
    create_profile,
    update_profile,
    delete_profile,
    seed_presets,
    RiskProfileRow,
)


class TestProfileDefinitions:
    def test_four_presets_exist(self):
        # conservative and crazy were added in Round 12 (AGI risk-tier allocation)
        assert {"safe", "normal", "aggressive", "extreme"}.issubset(set(PRESETS.keys()))
        assert "conservative" in PRESETS
        assert "crazy" in PRESETS

    def test_default_is_normal(self):
        assert DEFAULT_PROFILE == "normal"

    def test_profiles_have_monotonic_risk(self):
        safe = PRESETS["safe"]
        normal = PRESETS["normal"]
        aggressive = PRESETS["aggressive"]
        extreme = PRESETS["extreme"]

        assert (
            safe.kelly_fraction
            < normal.kelly_fraction
            < aggressive.kelly_fraction
            < extreme.kelly_fraction
        )
        assert (
            safe.max_trade_size
            < normal.max_trade_size
            < aggressive.max_trade_size
            < extreme.max_trade_size
        )
        assert (
            safe.max_position_fraction
            < normal.max_position_fraction
            < aggressive.max_position_fraction
            < extreme.max_position_fraction
        )
        assert (
            safe.daily_drawdown_limit_pct
            < normal.daily_drawdown_limit_pct
            < aggressive.daily_drawdown_limit_pct
            < extreme.daily_drawdown_limit_pct
        )

    def test_normal_has_expected_values(self):
        normal = PRESETS["normal"]
        assert normal.kelly_fraction == 0.30
        assert normal.daily_loss_limit == 5.0
        assert normal.max_position_fraction == 0.08
        assert normal.max_total_exposure_fraction == 0.70
        assert normal.daily_drawdown_limit_pct == 0.10
        assert normal.weekly_drawdown_limit_pct == 0.20
        assert normal.slippage_tolerance == 0.02
        assert normal.max_concentration_pct == 0.30


class TestGetProfile:
    def test_get_by_name(self):
        p = get_profile("safe")
        assert p.name == "safe"

    def test_get_default_when_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RISK_PROFILE", None)
            p = get_profile(None)
            assert p.name == DEFAULT_PROFILE

    def test_get_unknown_falls_back(self):
        p = get_profile("nonexistent")
        assert p.name == DEFAULT_PROFILE

    def test_active_profile_from_env(self):
        with patch.dict(os.environ, {"RISK_PROFILE": "aggressive"}):
            name = get_active_profile_name()
            assert name == "aggressive"

    def test_missing_table_falls_back_without_exception_log(self, db):
        db.execute(text("DROP TABLE risk_profiles"))
        db.commit()

        with (
            patch("backend.core.risk_profiles.logger.warning") as warning_mock,
            patch("backend.core.risk_profiles.logger.exception") as exception_mock,
        ):
            profile = get_profile("safe", db=db)

        assert profile.name == "safe"
        warning_mock.assert_called_once()
        exception_mock.assert_not_called()
        assert db.execute(text("SELECT 1")).scalar() == 1


class TestApplyProfile:
    def test_apply_safe(self):
        from backend.config import settings

        original_kelly = settings.KELLY_FRACTION
        original_concentration = settings.MAX_CONCENTRATION_PCT

        profile = apply_profile("safe")
        assert profile.name == "safe"
        assert settings.KELLY_FRACTION == PRESETS["safe"].kelly_fraction
        assert settings.MAX_POSITION_FRACTION == PRESETS["safe"].max_position_fraction
        assert settings.MAX_CONCENTRATION_PCT == PRESETS["safe"].max_concentration_pct
        assert (
            settings.DAILY_DRAWDOWN_LIMIT_PCT
            == PRESETS["safe"].daily_drawdown_limit_pct
        )

        settings.KELLY_FRACTION = original_kelly
        settings.MAX_CONCENTRATION_PCT = original_concentration

    def test_apply_sets_env_var(self):
        with patch.dict(os.environ, {}, clear=False):
            apply_profile("extreme")
            assert os.environ.get("RISK_PROFILE") == "extreme"

            os.environ.pop("RISK_PROFILE", None)


class TestDBBackedProfiles:
    def test_seed_creates_rows(self, db):
        seed_presets(db=db)
        rows = db.query(RiskProfileRow).all()
        names = {r.name for r in rows}
        assert "safe" in names
        assert "normal" in names
        assert "aggressive" in names
        assert "extreme" in names

    def test_seed_idempotent(self, db):
        seed_presets(db=db)
        seed_presets(db=db)
        count = db.query(RiskProfileRow).count()
        # conservative and crazy were added in Round 12; total is now 6
        assert count == len(PRESETS)

    def test_create_custom_profile(self, db):
        seed_presets(db=db)
        custom = RiskProfile(
            name="custom1",
            display_name="Custom 1",
            kelly_fraction=0.4,
            min_edge_threshold=0.2,
            max_trade_size=15.0,
            max_position_fraction=0.12,
            max_total_exposure_fraction=0.8,
            daily_loss_limit=10.0,
            daily_drawdown_limit_pct=0.15,
            weekly_drawdown_limit_pct=0.25,
            slippage_tolerance=0.025,
            auto_approve_min_confidence=0.4,
            max_concentration_pct=0.45,
        )
        result = create_profile(custom, db=db)
        assert result.name == "custom1"

        fetched = get_profile("custom1", db=db)
        assert fetched.kelly_fraction == 0.4
        assert fetched.max_concentration_pct == 0.45

    def test_update_profile(self, db):
        seed_presets(db=db)
        updated = update_profile(
            "safe", {"kelly_fraction": 0.15, "max_trade_size": 5.0, "max_concentration_pct": 0.25}, db=db
        )
        assert updated.kelly_fraction == 0.15
        assert updated.max_trade_size == 5.0
        assert updated.max_concentration_pct == 0.25

    def test_delete_custom_profile(self, db):
        seed_presets(db=db)
        custom = RiskProfile(
            name="temp_profile",
            display_name="Temp",
            kelly_fraction=0.3,
            min_edge_threshold=0.3,
            max_trade_size=8.0,
            max_position_fraction=0.08,
            max_total_exposure_fraction=0.7,
            daily_loss_limit=5.0,
            daily_drawdown_limit_pct=0.1,
            weekly_drawdown_limit_pct=0.2,
            slippage_tolerance=0.02,
            auto_approve_min_confidence=0.5,
        )
        create_profile(custom, db=db)
        assert delete_profile("temp_profile", db=db) is True

    def test_cannot_delete_preset(self, db):
        assert delete_profile("safe", db=db) is False

    def test_list_profiles(self, db):
        seed_presets(db=db)
        all_profiles = list_profiles(db=db)
        assert len(all_profiles) >= 4
        assert "safe" in all_profiles
        assert "normal" in all_profiles

    def test_list_profiles_missing_table_returns_presets_without_exception_log(
        self, db
    ):
        db.execute(text("DROP TABLE risk_profiles"))
        db.commit()

        with (
            patch("backend.core.risk_profiles.logger.warning") as warning_mock,
            patch("backend.core.risk_profiles.logger.exception") as exception_mock,
        ):
            all_profiles = list_profiles(db=db)

        assert set(PRESETS).issubset(all_profiles)
        warning_mock.assert_called_once()
        exception_mock.assert_not_called()
        assert db.execute(text("SELECT 1")).scalar() == 1
