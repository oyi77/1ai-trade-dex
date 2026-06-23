import pytest
from backend.core.risk.market_risk import MarketRiskGrader, RiskGrade


@pytest.fixture
def grader():
    return MarketRiskGrader()


def test_high_quality_market_gets_A(grader):
    market = {
        "question": "Will BTC close above $100k on Friday?",
        "volume": 2_000_000,
        "liquidity": 150_000,
        "spread": 0.005,
        "category": "crypto",
        "time_to_resolution_hours": 200,
        "outcomes_count": 2,
    }
    result = grader.grade_market(market)
    assert result.grade == RiskGrade.A
    assert result.score >= 80


def test_low_quality_market_gets_D_or_F(grader):
    market = {
        "question": "Will the economy arguably reach consensus on substantially effective regulatory policy?",
        "volume": 500,
        "liquidity": 50,
        "spread": 0.30,
        "category": "politics",
        "time_to_resolution_hours": 2,
        "outcomes_count": 2,
    }
    result = grader.grade_market(market)
    assert result.grade in (RiskGrade.D, RiskGrade.F)
    assert result.score < 40


def test_subjective_keyword_detection(grader):
    clean = grader.grade_market(
        {
            "question": "Will BTC reach $100k?",
            "volume": 50_000,
        }
    )
    subjective = grader.grade_market(
        {
            "question": "Will the market effectively reach a substantially reasonable consensus?",
            "volume": 50_000,
        }
    )
    assert (
        subjective.factor_breakdown["resolution_clarity"]
        < clean.factor_breakdown["resolution_clarity"]
    )
    assert any("Subjective" in w for w in subjective.warnings)


def test_category_risk_scoring(grader):
    low_risk = grader.grade_market({"question": "Q", "volume": 0, "category": "sports"})
    high_risk = grader.grade_market(
        {"question": "Q", "volume": 0, "category": "politics"}
    )
    unknown = grader.grade_market(
        {"question": "Q", "volume": 0, "category": "entertainment"}
    )

    assert low_risk.factor_breakdown["category_risk"] == 90.0
    assert high_risk.factor_breakdown["category_risk"] == 20.0
    assert unknown.factor_breakdown["category_risk"] == 50.0
    assert (
        low_risk.factor_breakdown["category_risk"]
        > high_risk.factor_breakdown["category_risk"]
    )


def test_missing_optional_data_defaults(grader):
    result = grader.grade_market(
        {
            "question": "Will X happen?",
            "volume": 50_000,
        }
    )
    assert result.factor_breakdown["liquidity"] == 50.0
    assert result.factor_breakdown["spread"] == 50.0
    assert result.factor_breakdown["time_risk"] == 50.0
    assert result.factor_breakdown["category_risk"] == 50.0


def test_warnings_generated(grader):
    result = grader.grade_market(
        {
            "question": "Will this arguably be a substantially reasonable outcome?",
            "volume": 500,
            "liquidity": 50,
            "spread": 0.25,
            "category": "geopolitical",
            "time_to_resolution_hours": 48,
        }
    )
    _warning_text = " ".join(result.warnings)
    assert any("Subjective" in w for w in result.warnings)
    assert any("liquidity" in w.lower() for w in result.warnings)
    assert any("spread" in w.lower() for w in result.warnings)
    assert any("geopolitical" in w.lower() for w in result.warnings)
