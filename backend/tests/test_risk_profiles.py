import os
from unittest.mock import patch

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
        assert set(PRESETS.keys()) == {"safe", "normal", "aggressive", "extreme"}

    def test_default_is_normal(self):
        assert DEFAULT_PROFILE == "normal"

    def test_profiles_have_monotonic_risk(self):
        safe = PRESETS["safe"]
        normal = PRESETS["normal"]
        aggressive = PRESETS["aggressive"]
        extreme = PRESETS["extreme"]

        assert safe.kelly_fraction < normal.kelly_fraction < aggressive.kelly_fraction < extreme.kelly_fraction
        assert safe.max_trade_size < normal.max_trade_size < aggressive.max_trade_size < extreme.max_trade_size
        assert safe.max_position_fraction < normal.max_position_fraction < aggressive.max_position_fraction < extreme.max_position_fraction
        assert safe.daily_drawdown_limit_pct < normal.daily_drawdown_limit_pct < aggressive.daily_drawdown_limit_pct < extreme.daily_drawdown_limit_pct

    def test_normal_has_expected_values(self):
        normal = PRESETS["normal"]
        assert normal.kelly_fraction == 0.30
        assert normal.daily_loss_limit == 5.0
        assert normal.max_position_fraction == 0.08
        assert normal.max_total_exposure_fraction == 0.70
        assert normal.daily_drawdown_limit_pct == 0.10
        assert normal.weekly_drawdown_limit_pct == 0.20
        assert normal.slippage_tolerance == 0.02


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


class TestApplyProfile:
    def test_apply_safe(self):
        from backend.config import settings
        original_kelly = settings.KELLY_FRACTION

        profile = apply_profile("safe")
        assert profile.name == "safe"
        assert settings.KELLY_FRACTION == PRESETS["safe"].kelly_fraction
        assert settings.MAX_POSITION_FRACTION == PRESETS["safe"].max_position_fraction
        assert settings.DAILY_DRAWDOWN_LIMIT_PCT == PRESETS["safe"].daily_drawdown_limit_pct

        settings.KELLY_FRACTION = original_kelly

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
        assert count == 4

    def test_create_custom_profile(self, db):
        seed_presets(db=db)
        custom = RiskProfile(
            name="custom1", display_name="Custom 1",
            kelly_fraction=0.4, min_edge_threshold=0.2, max_trade_size=15.0,
            max_position_fraction=0.12, max_total_exposure_fraction=0.8,
            daily_loss_limit=10.0, daily_drawdown_limit_pct=0.15,
            weekly_drawdown_limit_pct=0.25, slippage_tolerance=0.025,
            auto_approve_min_confidence=0.4,
        )
        result = create_profile(custom, db=db)
        assert result.name == "custom1"

        fetched = get_profile("custom1", db=db)
        assert fetched.kelly_fraction == 0.4

    def test_update_profile(self, db):
        seed_presets(db=db)
        updated = update_profile("safe", {"kelly_fraction": 0.15, "max_trade_size": 5.0}, db=db)
        assert updated.kelly_fraction == 0.15
        assert updated.max_trade_size == 5.0

    def test_delete_custom_profile(self, db):
        seed_presets(db=db)
        custom = RiskProfile(
            name="temp_profile", display_name="Temp",
            kelly_fraction=0.3, min_edge_threshold=0.3, max_trade_size=8.0,
            max_position_fraction=0.08, max_total_exposure_fraction=0.7,
            daily_loss_limit=5.0, daily_drawdown_limit_pct=0.1,
            weekly_drawdown_limit_pct=0.2, slippage_tolerance=0.02,
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
