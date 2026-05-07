import pytest
from unittest.mock import MagicMock
from backend.ai.sentiment_analyzer import SentimentAnalyzer, SentimentResult

POSITIVE_JSON = '{"score": 0.6, "label": "positive", "confidence": 0.9}'


def _make_mock_client(response: str):
    client = MagicMock()
    client.complete = MagicMock(return_value=response)
    return client


@pytest.mark.asyncio
async def test_analyze_positive():
    client = _make_mock_client(POSITIVE_JSON)
    analyzer = SentimentAnalyzer(client=client)
    result = await analyzer.analyze("Markets are booming today!")
    assert isinstance(result, SentimentResult)
    assert result.score == pytest.approx(0.6)
    assert result.label == "positive"
    assert result.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_analyze_batch_order():
    # Map prompt substring -> response so order doesn't matter
    response_map = {
        "good news": '{"score": 0.6, "label": "positive", "confidence": 0.9}',
        "bad news": '{"score": -0.3, "label": "negative", "confidence": 0.7}',
        "meh news": '{"score": 0.0, "label": "neutral", "confidence": 0.5}',
    }

    def side_effect(prompt):
        for key, val in response_map.items():
            if key in prompt:
                return val
        return '{"score": 0.0, "label": "neutral", "confidence": 0.0}'

    client = MagicMock()
    client.complete = MagicMock(side_effect=side_effect)
    analyzer = SentimentAnalyzer(client=client)

    texts = ["good news", "bad news", "meh news"]
    results = await analyzer.analyze_batch(texts)

    assert len(results) == 3
    labels = {r.label for r in results}
    assert "positive" in labels
    assert "negative" in labels
    assert "neutral" in labels


@pytest.mark.asyncio
async def test_analyze_parse_failure_returns_neutral():
    client = MagicMock()
    client.complete = MagicMock(return_value="not valid json {{{{")
    analyzer = SentimentAnalyzer(client=client)
    result = await analyzer.analyze("some text")
    assert result.label == "neutral"
    assert result.score == 0.0
    assert result.confidence == 0.0
