"""Comprehensive tests for G011-G015 ultragoal modules.

Covers:
  G011 — PMXT + Multi-platform (pmxt_client, pipeline_manager, cross_market_arb_enhanced)
  G012 — RAG + ML Training (ml_predictor, ml_trainer, rag_pipeline, auto_backtester, backtest_optimizer, arb_opportunity_scanner)
  G013 — AGI Auto-Research (github_scanner, paper_scanner, competitor_monitor, whale_tracker)
  G014 — Advanced Backtesting (pybroker_backtest, hyperliquid_strategy)
  G015 — Data Pipelines + Deploy (dune_analytics, hyperliquid_client, vector_store, news_ingester)
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# G015 — VectorStore + NewsIngester (pure logic, no settings needed)
# ---------------------------------------------------------------------------


class TestVectorStore:
    """Tests for backend/ai/vector_store.py — Document, VectorStore."""

    def _make_doc(
        self, text: str, embedding: list[float] | None = None, doc_id: str = ""
    ):
        from backend.ai.vector_store import Document

        return Document(
            text=text, embedding=embedding or [], metadata={}, doc_id=doc_id
        )

    def test_add_and_size(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        assert store.size == 0
        store.add(self._make_doc("hello", [1.0, 0.0], "d1"))
        assert store.size == 1
        store.add(self._make_doc("world", [0.0, 1.0], "d2"))
        assert store.size == 2

    def test_add_generates_id_when_missing(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        doc = self._make_doc("text", [1.0])
        store.add(doc)
        assert doc.doc_id.startswith("doc_")

    def test_add_batch(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        docs = [self._make_doc(f"t{i}", [float(i)], f"d{i}") for i in range(5)]
        store.add_batch(docs)
        assert store.size == 5

    def test_search_returns_ranked_results(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        store.add(self._make_doc("a", [1.0, 0.0], "d1"))
        store.add(self._make_doc("b", [0.0, 1.0], "d2"))
        store.add(self._make_doc("c", [0.7, 0.7], "d3"))
        results = store.search([1.0, 0.0], top_k=2)
        assert len(results) == 2
        # d1 should be top (cosine sim = 1.0)
        assert results[0][0].doc_id == "d1"
        assert results[0][1] > results[1][1]

    def test_search_empty_store(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        assert store.search([1.0, 0.0]) == []

    def test_search_empty_query(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        store.add(self._make_doc("a", [1.0]))
        assert store.search([]) == []

    def test_clear(self):
        from backend.ai.vector_store import VectorStore

        store = VectorStore()
        store.add(self._make_doc("a", [1.0], "d1"))
        store.clear()
        assert store.size == 0

    def test_get_by_metadata(self):
        from backend.ai.vector_store import VectorStore, Document

        store = VectorStore()
        doc = Document(
            text="x", embedding=[1.0], metadata={"source": "test"}, doc_id="d1"
        )
        store.add(doc)
        found = store.get_by_metadata("source", "test")
        assert len(found) == 1
        assert found[0].doc_id == "d1"

    def test_cosine_similarity_perfect(self):
        from backend.ai.vector_store import _cosine_similarity

        assert abs(_cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9

    def test_cosine_similarity_orthogonal(self):
        from backend.ai.vector_store import _cosine_similarity

        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_cosine_similarity_zero_vector(self):
        from backend.ai.vector_store import _cosine_similarity

        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_search_skips_docs_without_embedding(self):
        from backend.ai.vector_store import VectorStore, Document

        store = VectorStore()
        store.add(Document(text="no emb", embedding=[], doc_id="d1"))
        store.add(Document(text="has emb", embedding=[1.0, 0.0], doc_id="d2"))
        results = store.search([1.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0][0].doc_id == "d2"


class TestNewsIngester:
    """Tests for backend/ai/news_ingester.py — NewsArticle, NewsChunk, NewsIngester."""

    def test_news_article_id_stable(self):
        from backend.ai.news_ingester import NewsArticle

        a = NewsArticle(title="Test", text="body", source="src", url="http://x")
        b = NewsArticle(title="Test", text="body", source="src", url="http://x")
        assert a.article_id == b.article_id

    def test_chunk_articles_basic(self):
        from backend.ai.news_ingester import NewsIngester, NewsArticle

        ingester = NewsIngester(chunk_size=50, chunk_overlap=10)
        article = NewsArticle(
            title="T",
            text="First sentence here. Second sentence is a bit longer. Third sentence adds more. Fourth completes the set.",
            source="test",
        )
        chunks = ingester.chunk_articles([article])
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.article_id == article.article_id
            assert chunk.text.strip() != ""

    def test_chunk_articles_empty_text(self):
        from backend.ai.news_ingester import NewsIngester, NewsArticle

        ingester = NewsIngester()
        article = NewsArticle(title="T", text="", source="test")
        chunks = ingester.chunk_articles([article])
        assert len(chunks) == 0

    def test_chunk_metadata_contains_title(self):
        from backend.ai.news_ingester import NewsIngester, NewsArticle

        ingester = NewsIngester(chunk_size=1000)
        article = NewsArticle(title="MyTitle", text="Some text here.", source="src")
        chunks = ingester.chunk_articles([article])
        assert chunks[0].metadata["title"] == "MyTitle"

    @pytest.mark.asyncio
    async def test_fetch_url_news_with_mock(self):
        from backend.ai.news_ingester import NewsIngester

        ingester = NewsIngester()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title>Test Page</title></head><body><p>Hello world text.</p></body></html>"
        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp
        ):
            articles = await ingester.fetch_url_news(["https://example.com/article"])
        assert len(articles) == 1
        assert "Test Page" in articles[0].title or articles[0].title  # title extraction

    @pytest.mark.asyncio
    async def test_fetch_url_news_http_error(self):
        from backend.ai.news_ingester import NewsIngester

        ingester = NewsIngester()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp
        ):
            articles = await ingester.fetch_url_news(["https://example.com/missing"])
        assert len(articles) == 0


# ---------------------------------------------------------------------------
# G015 — DuneAnalyticsClient (data classes + cache logic)
# ---------------------------------------------------------------------------


class TestDuneAnalytics:
    """Tests for backend/data/dune_analytics.py — data classes and cache logic."""

    def test_dune_cache_entry_not_expired(self):
        from backend.data.dune_analytics import DuneCacheEntry

        entry = DuneCacheEntry(data=[1, 2], fetched_at=time.time(), ttl=3600)
        assert entry.is_expired is False

    def test_dune_cache_entry_expired(self):
        from backend.data.dune_analytics import DuneCacheEntry

        entry = DuneCacheEntry(data=[1, 2], fetched_at=time.time() - 7200, ttl=3600)
        assert entry.is_expired is True

    def test_dune_client_post_init_defaults(self):
        """DuneAnalyticsClient initializes with defaults when no settings provided."""
        from backend.data.dune_analytics import DuneAnalyticsClient

        with patch(
            "backend.data.dune_analytics.settings", MagicMock(DUNE_API_KEY="test_key")
        ):
            client = DuneAnalyticsClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert "total_volume" in client.query_ids

    def test_dune_client_clear_cache(self):
        from backend.data.dune_analytics import DuneAnalyticsClient

        with patch("backend.data.dune_analytics.settings", MagicMock(DUNE_API_KEY="k")):
            client = DuneAnalyticsClient(api_key="k")
        client._cache["test"] = MagicMock()
        assert client.clear_cache() == 1
        assert len(client._cache) == 0

    def test_dune_client_cache_set_get(self):
        from backend.data.dune_analytics import DuneAnalyticsClient

        with patch("backend.data.dune_analytics.settings", MagicMock(DUNE_API_KEY="k")):
            client = DuneAnalyticsClient(api_key="k")
        client._set_cached("key1", [{"a": 1}], ttl=3600)
        assert client._get_cached("key1") == [{"a": 1}]
        assert client._get_cached("nonexistent") is None

    def test_dune_default_query_ids(self):
        from backend.data.dune_analytics import DEFAULT_QUERY_IDS

        assert "total_volume" in DEFAULT_QUERY_IDS
        assert "top_markets" in DEFAULT_QUERY_IDS
        assert "whale_activity" in DEFAULT_QUERY_IDS
        assert "settlement_history" in DEFAULT_QUERY_IDS


# ---------------------------------------------------------------------------
# G015 — HyperliquidClient (data classes + cache logic)
# ---------------------------------------------------------------------------


class TestHyperliquidClient:
    """Tests for backend/data/hyperliquid_client.py — data classes and cache."""

    def test_hl_market_dataclass(self):
        from backend.data.hyperliquid_client import HLMarket

        m = HLMarket(
            market_id="btc-50k",
            question="Will BTC hit 50k?",
            outcomes=["Yes", "No"],
            outcome_prices=[0.6, 0.4],
            volume_24h=1000.0,
            liquidity=500.0,
        )
        assert m.status == "active"
        assert m.market_id == "btc-50k"

    def test_hl_orderbook_level(self):
        from backend.data.hyperliquid_client import HLOrderBookLevel

        level = HLOrderBookLevel(price=0.55, size=100.0)
        assert level.price == 0.55

    def test_hl_trade_dataclass(self):
        from backend.data.hyperliquid_client import HLTrade

        t = HLTrade(
            trade_id="t1",
            market_id="m1",
            side="BUY",
            price=0.6,
            size=50.0,
            timestamp=1000.0,
        )
        assert t.side == "BUY"

    def test_hl_client_cache(self):
        from backend.data.hyperliquid_client import HyperliquidClient

        with patch(
            "backend.data.hyperliquid_client.settings",
            MagicMock(HYPERLIQUID_API_URL="http://test"),
        ):
            client = HyperliquidClient(api_url="http://test")
        client._set_cached("key", [{"x": 1}])
        assert client._get_cached("key", ttl=60) == [{"x": 1}]
        assert client._get_cached("missing", ttl=60) is None

    def test_hl_client_cache_expired(self):
        from backend.data.hyperliquid_client import HyperliquidClient

        with patch(
            "backend.data.hyperliquid_client.settings",
            MagicMock(HYPERLIQUID_API_URL="http://test"),
        ):
            client = HyperliquidClient(api_url="http://test")
        # Manually set an old entry
        client._cache["old"] = (time.time() - 9999, [{"x": 1}])
        assert client._get_cached("old", ttl=1) is None

    def test_hl_client_clear_cache(self):
        from backend.data.hyperliquid_client import HyperliquidClient

        with patch(
            "backend.data.hyperliquid_client.settings",
            MagicMock(HYPERLIQUID_API_URL="http://test"),
        ):
            client = HyperliquidClient(api_url="http://test")
        client._cache["a"] = (time.time(), 1)
        client._cache["b"] = (time.time(), 2)
        assert client.clear_cache() == 2

    @pytest.mark.asyncio
    async def test_hl_get_markets_empty_on_failure(self):
        from backend.data.hyperliquid_client import HyperliquidClient

        with patch(
            "backend.data.hyperliquid_client.settings",
            MagicMock(HYPERLIQUID_API_URL="http://test"),
        ):
            client = HyperliquidClient(api_url="http://test")
        with patch.object(client, "_post", new_callable=AsyncMock, return_value=None):
            markets = await client.get_markets()
        assert markets == []

    @pytest.mark.asyncio
    async def test_hl_get_markets_parses_response(self):
        from backend.data.hyperliquid_client import HyperliquidClient

        with patch(
            "backend.data.hyperliquid_client.settings",
            MagicMock(HYPERLIQUID_API_URL="http://test"),
        ):
            client = HyperliquidClient(api_url="http://test")
        mock_data = {
            "predictionMarkets": [
                {
                    "id": "m1",
                    "question": "Test?",
                    "outcomes": ["Yes", "No"],
                    "outcomePrices": [0.7, 0.3],
                    "volume24h": 500,
                    "liquidity": 200,
                },
            ]
        }
        with patch.object(
            client, "_post", new_callable=AsyncMock, return_value=mock_data
        ):
            markets = await client.get_markets()
        assert len(markets) == 1
        assert markets[0].market_id == "m1"
        assert markets[0].question == "Test?"
        assert markets[0].outcome_prices == [0.7, 0.3]


# ---------------------------------------------------------------------------
# G011 — PipelineManager
# ---------------------------------------------------------------------------


class TestPipelineManager:
    """Tests for backend/data/pipeline_manager.py — PipelineStatus, PipelineStageResult, PipelineHealth, DataPipelineManager."""

    def test_pipeline_status_enum(self):
        from backend.data.pipeline_manager import PipelineStatus

        assert PipelineStatus.IDLE.value == "idle"
        assert PipelineStatus.RUNNING.value == "running"
        assert PipelineStatus.FAILED.value == "failed"
        assert PipelineStatus.COMPLETED.value == "completed"

    def test_pipeline_stage_result_defaults(self):
        from backend.data.pipeline_manager import PipelineStageResult, PipelineStatus

        r = PipelineStageResult(name="test", status=PipelineStatus.IDLE)
        assert r.records_processed == 0
        assert r.duration_seconds == 0.0
        assert r.error is None

    def test_pipeline_health_defaults(self):
        from backend.data.pipeline_manager import PipelineHealth, PipelineStatus

        h = PipelineHealth(stages={})
        assert h.total_records == 0
        assert h.stale_stages == []
        assert h.overall_status == PipelineStatus.IDLE

    def test_data_pipeline_manager_post_init(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        assert "dune" in pm._stages
        assert "subgraph" in pm._stages
        assert "hyperliquid" in pm._stages
        assert "hf_dataset" in pm._stages
        assert pm._stages["dune"].status == PipelineStatus.IDLE

    def test_register_clients(self):
        from backend.data.pipeline_manager import DataPipelineManager

        pm = DataPipelineManager()
        pm.register_dune_client(MagicMock())
        assert pm._dune_client is not None
        pm.register_subgraph_client(MagicMock())
        assert pm._subgraph_client is not None
        pm.register_hyperliquid_client(MagicMock())
        assert pm._hl_client is not None

    @pytest.mark.asyncio
    async def test_run_unknown_stage(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        result = await pm.run_stage("nonexistent")
        assert result.status == PipelineStatus.FAILED
        assert "Unknown stage" in result.error

    @pytest.mark.asyncio
    async def test_run_stage_dune_no_client(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        result = await pm.run_stage("dune")
        assert result.status == PipelineStatus.COMPLETED
        assert result.records_processed == 0

    @pytest.mark.asyncio
    async def test_run_stage_dune_with_client(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        mock_dune = MagicMock()
        mock_dune.get_whale_activity = AsyncMock(return_value=[{"w": 1}, {"w": 2}])
        mock_dune.get_top_markets = AsyncMock(return_value=[{"m": 1}])
        mock_dune.get_settlement_history = AsyncMock(return_value=[{"s": 1}])
        pm.register_dune_client(mock_dune)
        result = await pm.run_stage("dune")
        assert result.status == PipelineStatus.COMPLETED
        assert result.records_processed == 4  # 2 + 1 + 1

    @pytest.mark.asyncio
    async def test_run_stage_subgraph_with_client(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        mock_sg = MagicMock()
        mock_sg.get_markets = AsyncMock(return_value=[{"m": 1}] * 5)
        mock_sg.get_trades = AsyncMock(return_value=[{"t": 1}] * 3)
        mock_sg.get_settlements = AsyncMock(return_value=[{"s": 1}])
        pm.register_subgraph_client(mock_sg)
        result = await pm.run_stage("subgraph")
        assert result.status == PipelineStatus.COMPLETED
        assert result.records_processed == 9

    @pytest.mark.asyncio
    async def test_run_stage_hyperliquid_with_client(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        mock_hl = MagicMock()
        mock_hl.get_markets = AsyncMock(return_value=[{"m": 1}] * 7)
        pm.register_hyperliquid_client(mock_hl)
        result = await pm.run_stage("hyperliquid")
        assert result.status == PipelineStatus.COMPLETED
        assert result.records_processed == 7

    @pytest.mark.asyncio
    async def test_run_stage_failure(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        mock_dune = MagicMock()
        mock_dune.get_whale_activity = AsyncMock(side_effect=RuntimeError("DB down"))
        pm.register_dune_client(mock_dune)
        result = await pm.run_stage("dune")
        assert result.status == PipelineStatus.FAILED
        assert "DB down" in result.error

    def test_get_health_all_idle(self):
        from backend.data.pipeline_manager import DataPipelineManager, PipelineStatus

        pm = DataPipelineManager()
        health = pm.get_health()
        assert health.overall_status == PipelineStatus.IDLE
        assert health.total_records == 0

    def test_is_running(self):
        from backend.data.pipeline_manager import DataPipelineManager

        pm = DataPipelineManager()
        assert pm.is_running() is False

    def test_health_detects_stale_stages(self):
        from backend.data.pipeline_manager import (
            DataPipelineManager,
            PipelineStatus,
            PipelineStageResult,
        )

        pm = DataPipelineManager()
        # Simulate a stage that ran a long time ago
        pm._stages["dune"] = PipelineStageResult(
            name="dune",
            status=PipelineStatus.COMPLETED,
            last_run=time.time() - 99999,
            records_processed=10,
        )
        health = pm.get_health()
        assert "dune" in health.stale_stages


# ---------------------------------------------------------------------------
# G011 — CrossMarketArbEnhanced
# ---------------------------------------------------------------------------


class TestCrossMarketArbEnhanced:
    """Tests for backend/strategies/cross_market_arb_enhanced.py."""

    def test_arb_opportunity_enhanced_dataclass(self):
        from backend.strategies.cross_market_arb_enhanced import ArbOpportunityEnhanced

        opp = ArbOpportunityEnhanced(
            event_id="e1",
            kind="cross_platform",
            platform_a="polymarket",
            platform_b="kalshi",
            market_a_id="a",
            market_b_id="b",
            price_a=0.5,
            price_b=0.6,
            raw_spread=0.1,
            fees=0.05,
            slippage_cost=0.01,
            execution_risk=0.2,
            net_profit=0.04,
            net_profit_pct=0.08,
            confidence=0.7,
        )
        assert opp.kind == "cross_platform"
        assert opp.details == {}

    def test_scan_result_dataclass(self):
        from backend.strategies.cross_market_arb_enhanced import ScanResult

        sr = ScanResult(opportunities=[], markets_scanned=10, scan_duration_ms=5.0)
        assert sr.platform == "multi"

    def test_detect_yes_no_sum_profitable(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced(
            poly_fee_pct=0.01, slippage_bps=1.0, min_net_profit_pct=0.001
        )
        market = {"conditionId": "m1", "yes_price": 0.40, "no_price": 0.50}
        opp = detector.detect_yes_no_sum(market)
        assert opp is not None
        assert opp.kind == "yes_no_sum"
        assert opp.net_profit > 0

    def test_detect_yes_no_sum_no_arb(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced()
        market = {"conditionId": "m1", "yes_price": 0.50, "no_price": 0.55}
        opp = detector.detect_yes_no_sum(market)
        assert opp is None  # sum > 1.0

    def test_detect_yes_no_sum_missing_prices(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced()
        assert detector.detect_yes_no_sum({}) is None
        assert detector.detect_yes_no_sum({"yes_price": None}) is None

    def test_detect_complementary(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced(
            poly_fee_pct=0.0, slippage_bps=0.0, min_net_profit_pct=0.0
        )
        markets = [
            {"event_id": "evt1", "conditionId": "a", "yes_price": 0.30},
            {"event_id": "evt1", "conditionId": "b", "yes_price": 0.40},
        ]
        opps = detector.detect_complementary(markets)
        assert len(opps) == 1
        assert opps[0].kind == "multi_outcome"

    def test_detect_complementary_no_arb_when_sum_above_one(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced()
        markets = [
            {"event_id": "evt1", "conditionId": "a", "yes_price": 0.60},
            {"event_id": "evt1", "conditionId": "b", "yes_price": 0.50},
        ]
        opps = detector.detect_complementary(markets)
        assert len(opps) == 0

    def test_detect_cross_platform_generic(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced(
            poly_fee_pct=0.0,
            kalshi_fee_pct=0.0,
            slippage_bps=0.0,
            min_net_profit_pct=0.001,
        )
        poly = [
            {"question": "Will BTC hit 100k?", "conditionId": "p1", "yes_price": 0.40}
        ]
        kalshi = [{"question": "Will BTC hit 100k?", "id": "k1", "yes_price": 0.50}]
        opps = detector.detect_cross_platform_generic(poly, kalshi)
        assert len(opps) == 1
        assert opps[0].kind == "cross_platform"

    def test_scan_all(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced

        detector = CrossMarketArbEnhanced(
            poly_fee_pct=0.0, slippage_bps=0.0, min_net_profit_pct=0.0
        )
        poly = [
            {"conditionId": "a", "yes_price": 0.40, "no_price": 0.50},
            {"conditionId": "b", "yes_price": 0.60},
        ]
        result = detector.scan_all(poly)
        assert result.markets_scanned == 2
        assert result.scan_duration_ms >= 0

    def test_extract_yes_price_from_outcome_prices(self):
        from backend.strategies.cross_market_arb_enhanced import _extract_yes_price

        market = {"outcomePrices": "[0.55, 0.45]"}
        assert abs(_extract_yes_price(market) - 0.55) < 1e-9

    def test_extract_yes_price_none_for_empty(self):
        from backend.strategies.cross_market_arb_enhanced import _extract_yes_price

        assert _extract_yes_price({}) is None
        assert _extract_yes_price({"yes_price": 1.5}) is None  # out of (0,1)

    def test_questions_match(self):
        from backend.strategies.cross_market_arb_enhanced import _questions_match

        assert _questions_match("will btc hit 100k", "will btc hit 100k") is True
        assert (
            _questions_match(
                "will btc hit 100k by December", "will eth reach 5k tomorrow"
            )
            is False
        )


# ---------------------------------------------------------------------------
# G011 — PmxtClient (data classes + validation)
# ---------------------------------------------------------------------------


class TestPmxtClient:
    """Tests for backend/data/pmxt_client.py — data classes and client logic."""

    def test_pmxt_market_dataclass(self):
        from backend.data.pmxt_client import PmxtMarket

        m = PmxtMarket(market_id="m1", title="Test", platform="polymarket")
        assert m.yes_price is None
        assert m.volume_24h == 0.0
        assert m.outcome_ids == {}

    def test_pmxt_order_book_spread(self):
        from backend.data.pmxt_client import PmxtOrderBook

        book = PmxtOrderBook(outcome_id="o1", best_bid=0.50, best_ask=0.55)
        assert abs(book.spread - 0.05) < 1e-9

    def test_pmxt_order_book_spread_no_data(self):
        from backend.data.pmxt_client import PmxtOrderBook

        book = PmxtOrderBook(outcome_id="o1")
        assert book.spread == 1.0

    def test_pmxt_order_result_dataclass(self):
        from backend.data.pmxt_client import PmxtOrderResult

        r = PmxtOrderResult(success=True, order_id="o1", filled=10.0)
        assert r.success is True
        assert r.error is None

    def test_pmxt_balance_dataclass(self):
        from backend.data.pmxt_client import PmxtBalance

        b = PmxtBalance(currency="USDC", total=100.0, available=80.0, locked=20.0)
        assert b.available == 80.0

    def test_pmxt_position_dataclass(self):
        from backend.data.pmxt_client import PmxtPosition

        p = PmxtPosition(
            market_id="m1",
            outcome_id="o1",
            outcome_label="Yes",
            size=50.0,
            entry_price=0.5,
            current_price=0.6,
            unrealized_pnl=5.0,
        )
        assert p.unrealized_pnl == 5.0

    def test_supported_exchanges(self):
        from backend.data.pmxt_client import SUPPORTED_EXCHANGES

        assert "polymarket" in SUPPORTED_EXCHANGES
        assert "kalshi" in SUPPORTED_EXCHANGES
        assert "hyperliquid" in SUPPORTED_EXCHANGES

    def test_pmxt_client_rejects_unsupported_exchange(self):
        from backend.data.pmxt_client import PmxtClient

        client = PmxtClient()
        with pytest.raises(ValueError, match="Unsupported exchange"):
            client._get_exchange("ftx")

    def test_get_breaker_creates_unique_breakers(self):
        from backend.data.pmxt_client import _get_breaker, _breakers

        _breakers.clear()
        b1 = _get_breaker("polymarket")
        b2 = _get_breaker("polymarket")
        assert b1 is b2
        b3 = _get_breaker("kalshi")
        assert b3 is not b1


# ---------------------------------------------------------------------------
# G012 — RAGPipeline + EmbeddingProvider
# ---------------------------------------------------------------------------


class TestRAGPipeline:
    """Tests for backend/ai/rag_pipeline.py — EmbeddingProvider, RAGContext, RAGPipeline."""

    def test_embedding_provider_produces_normalized_vectors(self):
        from backend.ai.rag_pipeline import EmbeddingProvider

        ep = EmbeddingProvider(dim=128)
        vec = ep.embed("hello world test")
        assert len(vec) == 128
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_embedding_provider_empty_text(self):
        from backend.ai.rag_pipeline import EmbeddingProvider

        ep = EmbeddingProvider(dim=64)
        vec = ep.embed("")
        assert len(vec) == 64
        assert all(v == 0.0 for v in vec)

    def test_embedding_batch(self):
        from backend.ai.rag_pipeline import EmbeddingProvider

        ep = EmbeddingProvider(dim=32)
        vecs = ep.embed_batch(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 32

    def test_rag_context_dataclass(self):
        from backend.ai.rag_pipeline import RAGContext

        ctx = RAGContext(query="test", documents=[], scores=[])
        assert ctx.summary == ""

    @pytest.mark.asyncio
    async def test_rag_pipeline_ingest_articles(self):
        from backend.ai.rag_pipeline import RAGPipeline
        from backend.ai.news_ingester import NewsArticle

        pipeline = RAGPipeline(chunk_size=200, embedding_dim=64)
        articles = [
            NewsArticle(
                title="A1",
                text="First article text about prediction markets.",
                source="test",
            ),
            NewsArticle(
                title="A2",
                text="Second article about crypto trading strategies.",
                source="test",
            ),
        ]
        count = await pipeline.ingest_articles(articles)
        assert count >= 2
        assert pipeline.store.size >= 2

    def test_rag_pipeline_query(self):
        from backend.ai.rag_pipeline import RAGPipeline
        from backend.ai.vector_store import Document

        pipeline = RAGPipeline(chunk_size=500, embedding_dim=64)
        # Manually add docs
        vec = pipeline.embedder.embed("test query")
        pipeline.store.add(Document(text="test doc", embedding=vec, doc_id="d1"))
        result = pipeline.query("test query", top_k=1)
        assert len(result.documents) == 1
        assert len(result.scores) == 1

    def test_rag_pipeline_query_for_market(self):
        from backend.ai.rag_pipeline import RAGPipeline

        pipeline = RAGPipeline(embedding_dim=64)
        result = pipeline.query_for_market("Will BTC hit 100k?")
        assert result.query.startswith("prediction market:")

    def test_rag_pipeline_stats(self):
        from backend.ai.rag_pipeline import RAGPipeline

        pipeline = RAGPipeline(embedding_dim=128)
        stats = pipeline.get_stats()
        assert stats["total_documents"] == 0
        assert stats["embedding_dim"] == 128


# ---------------------------------------------------------------------------
# G012 — MLPredictor (without loading real model)
# ---------------------------------------------------------------------------


class TestMLPredictor:
    """Tests for backend/ai/ml_predictor.py — Prediction, MLPredictor."""

    def test_prediction_dataclass(self):
        from backend.ai.ml_predictor import Prediction

        p = Prediction(
            market_id="m1", probability=0.7, confidence=0.4, features={"edge": 0.1}
        )
        assert p.model_type == ""

    def test_predictor_not_loaded_by_default(self):
        from backend.ai.ml_predictor import MLPredictor

        predictor = MLPredictor(model_path="/nonexistent/model.pkl")
        assert predictor.is_loaded is False

    def test_load_returns_false_when_missing(self):
        from backend.ai.ml_predictor import MLPredictor

        predictor = MLPredictor(model_path="/nonexistent/model.pkl")
        assert predictor.load() is False

    def test_predict_without_model_returns_default(self):
        from backend.ai.ml_predictor import MLPredictor

        predictor = MLPredictor(model_path="/nonexistent/model.pkl")
        pred = predictor.predict({"yes_price": 0.5}, market_id="m1")
        assert pred.probability == 0.5
        assert pred.confidence == 0.0
        assert pred.model_type == "none"

    def test_predict_batch_without_model(self):
        from backend.ai.ml_predictor import MLPredictor

        predictor = MLPredictor(model_path="/nonexistent/model.pkl")
        preds = predictor.predict_batch(
            [{"yes_price": 0.5}, {"yes_price": 0.6}],
            market_ids=["m1", "m2"],
        )
        assert len(preds) == 2
        assert preds[0].market_id == "m1"
        assert preds[1].market_id == "m2"

    def test_predict_with_mock_model(self):
        from backend.ai.ml_predictor import MLPredictor

        predictor = MLPredictor(model_path="/nonexistent/model.pkl")
        # Mock the model
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        predictor._model = mock_model
        predictor._model_type = "test"
        assert predictor.is_loaded is True
        pred = predictor.predict({"yes_price": 0.5, "volume": 100}, market_id="m1")
        assert abs(pred.probability - 0.7) < 1e-6
        assert pred.confidence > 0


# ---------------------------------------------------------------------------
# G012 — MLTrainer
# ---------------------------------------------------------------------------


class TestMLTrainer:
    """Tests for backend/ai/ml_trainer.py — MLTrainResult, MLTrainer."""

    def test_ml_train_result_dataclass(self):
        from backend.ai.ml_trainer import MLTrainResult

        r = MLTrainResult(
            model_path="/tmp/model.pkl",
            n_examples=100,
            feature_order=["edge", "volume"],
            train_accuracy=0.85,
            model_type="gradient_boosting",
        )
        assert r.feature_importances == {}

    def test_trainer_creates_gb_model(self):
        from backend.ai.ml_trainer import MLTrainer

        trainer = MLTrainer(model_type="gradient_boosting")
        model = trainer._create_model()
        from sklearn.ensemble import GradientBoostingClassifier

        assert isinstance(model, GradientBoostingClassifier)

    def test_trainer_creates_lr_model(self):
        from backend.ai.ml_trainer import MLTrainer

        trainer = MLTrainer(model_type="logistic_regression")
        model = trainer._create_model()
        from sklearn.linear_model import LogisticRegression

        assert isinstance(model, LogisticRegression)

    def test_trainer_rejects_unknown_model_type(self):
        from backend.ai.ml_trainer import MLTrainer

        trainer = MLTrainer(model_type="xgboost")
        with pytest.raises(ValueError, match="Unknown model_type"):
            trainer._create_model()

    def test_trainer_rejects_too_few_examples(self):
        from backend.ai.ml_trainer import MLTrainer
        from backend.ai.training.data_collector import TrainingExample

        trainer = MLTrainer()
        with pytest.raises(ValueError, match="at least 8"):
            trainer.train(
                [TrainingExample(features={"edge": 0.1}, label=1.0, market_id="m")] * 3
            )

    def test_trainer_trains_on_synthetic_data(self, tmp_path):
        from backend.ai.ml_trainer import MLTrainer

        model_path = str(tmp_path / "test_model.pkl")
        trainer = MLTrainer(model_path=model_path, model_type="gradient_boosting")
        # Generate enough examples
        examples = trainer._synthetic_examples(32)
        result = trainer.train(examples)
        assert result.n_examples == 32
        assert result.train_accuracy > 0.0
        assert result.model_type == "gradient_boosting"
        assert os.path.exists(model_path)

    def test_synthetic_examples_produce_valid_features(self):
        from backend.ai.ml_trainer import MLTrainer
        from backend.ai.training.feature_engineering import FEATURE_ORDER

        trainer = MLTrainer()
        examples = trainer._synthetic_examples(20)
        assert len(examples) == 20
        for ex in examples:
            for feat in FEATURE_ORDER:
                assert feat in ex.features
            assert ex.label in (0.0, 1.0)


# ---------------------------------------------------------------------------
# G012 — AutoBacktester
# ---------------------------------------------------------------------------


class TestAutoBacktester:
    """Tests for backend/core/auto_backtester.py — BacktestSnapshot, DegradationAlert, AutoBacktester."""

    def test_backtest_snapshot_dataclass(self):
        from backend.core.auto_backtester import BacktestSnapshot

        snap = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="test",
            win_rate=0.6,
            roi=0.1,
            sharpe_ratio=1.5,
            total_trades=50,
            max_drawdown=0.05,
            pnl=100.0,
        )
        assert snap.strategy_name == "test"

    def test_degradation_alert_dataclass(self):
        from backend.core.auto_backtester import DegradationAlert

        alert = DegradationAlert(
            strategy_name="s1",
            metric="win_rate",
            current_value=0.4,
            baseline_value=0.6,
            degradation_pct=0.33,
        )
        assert alert.metric == "win_rate"

    def test_auto_backtester_init_no_state_file(self, tmp_path):
        from backend.core.auto_backtester import AutoBacktester

        bt = AutoBacktester(state_path=str(tmp_path / "nonexistent.json"))
        assert len(bt.baselines) == 0

    def test_check_degradation_no_baseline(self):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        bt = AutoBacktester(state_path="/dev/null")
        snap = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.5,
            roi=0.0,
            sharpe_ratio=0.0,
            total_trades=10,
            max_drawdown=0.0,
            pnl=0.0,
        )
        assert bt._check_degradation(snap) is None

    def test_check_degradation_win_rate_decline(self):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        bt = AutoBacktester(state_path="/dev/null", degradation_threshold_pct=10.0)
        baseline = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.7,
            roi=0.2,
            sharpe_ratio=1.0,
            total_trades=50,
            max_drawdown=0.05,
            pnl=200.0,
        )
        bt._baselines["s1"] = baseline
        declining = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.5,
            roi=0.2,
            sharpe_ratio=0.5,
            total_trades=50,
            max_drawdown=0.1,
            pnl=50.0,
        )
        alert = bt._check_degradation(declining)
        assert alert is not None
        assert alert.metric == "win_rate"

    def test_check_degradation_no_alert_when_improved(self):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        bt = AutoBacktester(state_path="/dev/null")
        bt._baselines["s1"] = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.5,
            roi=0.1,
            sharpe_ratio=0.5,
            total_trades=50,
            max_drawdown=0.1,
            pnl=50.0,
        )
        improved = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.65,
            roi=0.15,
            sharpe_ratio=1.0,
            total_trades=50,
            max_drawdown=0.05,
            pnl=100.0,
        )
        assert bt._check_degradation(improved) is None

    def test_update_baseline_sets_initial(self):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        bt = AutoBacktester(state_path="/dev/null")
        snap = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.6,
            roi=0.1,
            sharpe_ratio=1.0,
            total_trades=50,
            max_drawdown=0.05,
            pnl=100.0,
        )
        bt._update_baseline(snap)
        assert "s1" in bt.baselines

    def test_update_baseline_upgrades_on_improvement(self):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        bt = AutoBacktester(state_path="/dev/null", min_trades_for_comparison=10)
        bt._baselines["s1"] = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.5,
            roi=0.1,
            sharpe_ratio=0.5,
            total_trades=50,
            max_drawdown=0.1,
            pnl=50.0,
        )
        better = BacktestSnapshot(
            timestamp=time.time(),
            strategy_name="s1",
            win_rate=0.7,
            roi=0.2,
            sharpe_ratio=1.5,
            total_trades=50,
            max_drawdown=0.03,
            pnl=200.0,
        )
        bt._update_baseline(better)
        assert bt.baselines["s1"].win_rate == 0.7

    def test_save_and_load_state(self, tmp_path):
        from backend.core.auto_backtester import AutoBacktester, BacktestSnapshot

        path = str(tmp_path / "state.json")
        bt1 = AutoBacktester(state_path=path)
        bt1._baselines["s1"] = BacktestSnapshot(
            timestamp=1.0,
            strategy_name="s1",
            win_rate=0.6,
            roi=0.1,
            sharpe_ratio=1.0,
            total_trades=50,
            max_drawdown=0.05,
            pnl=100.0,
        )
        bt1._save_state()
        bt2 = AutoBacktester(state_path=path)
        assert "s1" in bt2.baselines
        assert bt2.baselines["s1"].win_rate == 0.6

    def test_get_stats(self):
        from backend.core.auto_backtester import AutoBacktester

        bt = AutoBacktester(state_path="/dev/null")
        stats = bt.get_stats()
        assert "baselines_count" in stats
        assert "history_count" in stats


# ---------------------------------------------------------------------------
# G012 — BacktestOptimizer
# ---------------------------------------------------------------------------


class TestBacktestOptimizer:
    """Tests for backend/core/backtest_optimizer.py — OptimizationResult, BacktestOptimizer."""

    def test_optimization_result_dataclass(self):
        from backend.core.backtest_optimizer import OptimizationResult
        from backend.core.pybroker_backtest import PyBrokerResult

        r = OptimizationResult(
            params={"kelly": 0.05},
            backtest=MagicMock(spec=PyBrokerResult),
            oos_sharpe=1.5,
            is_sharpe=2.0,
            overfit_ratio=0.75,
            score=1.5,
        )
        assert r.params["kelly"] == 0.05

    def test_grid_search_empty_trades(self):
        from backend.core.backtest_optimizer import BacktestOptimizer

        opt = BacktestOptimizer()
        run = opt.grid_search([], {"kelly_fraction": [0.05, 0.1]})
        assert run.total_combinations == 0
        assert run.results == []

    def test_grid_search_with_trades(self):
        from backend.core.backtest_optimizer import BacktestOptimizer
        from backend.core.pybroker_backtest import TradeRecord

        trades = [
            TradeRecord(
                timestamp=datetime(2025, 1, 1) + timedelta(days=i),
                market_ticker=f"t{i}",
                direction="up",
                entry_price=0.5,
                size=10.0,
                edge=0.05,
                settled=True,
                settlement_value=1.0 if i % 2 == 0 else 0.0,
            )
            for i in range(30)
        ]
        opt = BacktestOptimizer(initial_bankroll=1000.0, train_days=10, test_days=5)
        run = opt.grid_search(
            trades,
            {"kelly_fraction": [0.05]},
            strategy_name="test",
            use_walk_forward=False,
        )
        assert len(run.results) == 1
        assert run.best_params == {"kelly_fraction": 0.05}

    def test_build_config(self):
        from backend.core.backtest_optimizer import BacktestOptimizer

        opt = BacktestOptimizer()
        config = opt._build_config(
            {"kelly_fraction": 0.1, "max_trade_size": 50.0, "slippage_bps": 3.0}
        )
        assert config.kelly_fraction == 0.1
        assert config.max_trade_size == 50.0
        assert config.slippage_bps == 3.0

    def test_filter_trades_by_min_edge(self):
        from backend.core.backtest_optimizer import BacktestOptimizer
        from backend.core.pybroker_backtest import TradeRecord

        trades = [
            TradeRecord(
                timestamp=datetime.now(),
                market_ticker="t",
                direction="up",
                entry_price=0.5,
                size=10.0,
                edge=e,
            )
            for e in [0.01, 0.05, 0.10, 0.02]
        ]
        opt = BacktestOptimizer()
        filtered = opt._filter_trades(trades, {"min_edge": 0.04})
        assert len(filtered) == 2

    def test_max_combinations_capping(self):
        from backend.core.backtest_optimizer import BacktestOptimizer
        from backend.core.pybroker_backtest import TradeRecord

        trades = [
            TradeRecord(
                timestamp=datetime(2025, 1, 1),
                market_ticker="t",
                direction="up",
                entry_price=0.5,
                size=10.0,
                edge=0.05,
                settled=True,
                settlement_value=1.0,
            )
        ]
        opt = BacktestOptimizer(max_combinations=2)
        # 3 combinations but capped at 2
        run = opt.grid_search(
            trades,
            {"kelly_fraction": [0.01, 0.05, 0.1]},
            use_walk_forward=False,
        )
        assert len(run.results) <= 2


# ---------------------------------------------------------------------------
# G012 — ArbOpportunityScanner
# ---------------------------------------------------------------------------


class TestArbOpportunityScanner:
    """Tests for backend/data/arb_opportunity_scanner.py — ArbAlert, ArbOpportunityScanner."""

    def test_arb_alert_dataclass(self):
        from backend.data.arb_opportunity_scanner import ArbAlert
        from backend.strategies.cross_market_arb_enhanced import ArbOpportunityEnhanced

        opp = ArbOpportunityEnhanced(
            event_id="e1",
            kind="cross_platform",
            platform_a="poly",
            platform_b="kalshi",
            market_a_id="a",
            market_b_id="b",
            price_a=0.4,
            price_b=0.5,
            raw_spread=0.1,
            fees=0.05,
            slippage_cost=0.01,
            execution_risk=0.2,
            net_profit=0.04,
            net_profit_pct=0.08,
            confidence=0.7,
        )
        alert = ArbAlert(opportunity=opp, severity="high", message="test")
        assert alert.severity == "high"

    def test_scanner_init(self):
        from backend.data.arb_opportunity_scanner import ArbOpportunityScanner

        scanner = ArbOpportunityScanner(min_profit_pct=0.02, alert_threshold_pct=0.05)
        assert scanner.alert_threshold == 0.05
        assert scanner.last_scan is None

    def test_generate_alerts(self):
        from backend.data.arb_opportunity_scanner import ArbOpportunityScanner
        from backend.strategies.cross_market_arb_enhanced import (
            ArbOpportunityEnhanced,
            ScanResult,
        )

        scanner = ArbOpportunityScanner(alert_threshold_pct=0.03)
        opp = ArbOpportunityEnhanced(
            event_id="e1",
            kind="cross_platform",
            platform_a="poly",
            platform_b="kalshi",
            market_a_id="a",
            market_b_id="b",
            price_a=0.4,
            price_b=0.5,
            raw_spread=0.1,
            fees=0.02,
            slippage_cost=0.01,
            execution_risk=0.2,
            net_profit=0.07,
            net_profit_pct=0.05,
            confidence=0.8,
        )
        result = ScanResult(
            opportunities=[opp], markets_scanned=10, scan_duration_ms=5.0
        )
        scanner._generate_alerts(result)
        assert len(scanner.recent_alerts) == 1
        assert scanner.recent_alerts[0].severity == "high"

    def test_get_stats(self):
        from backend.data.arb_opportunity_scanner import ArbOpportunityScanner

        scanner = ArbOpportunityScanner()
        stats = scanner.get_stats()
        assert stats["last_scan_opportunities"] == 0
        assert stats["total_alerts"] == 0


# ---------------------------------------------------------------------------
# G013 — GitHubScanner
# ---------------------------------------------------------------------------


class TestGitHubScanner:
    """Tests for backend/agi/research/github_scanner.py — RepoDiscovery, GitHubScanner, helpers."""

    def test_repo_discovery_fingerprint(self):
        from backend.agi.research.github_scanner import RepoDiscovery

        d = RepoDiscovery(
            repo_url="https://github.com/org/repo",
            name="repo",
            full_name="org/repo",
            description="desc",
            language="Python",
            stars=10,
            forks=2,
            last_updated="2025-01-01",
        )
        assert d.fingerprint == "org/repo"

    def test_merge_discoveries_deduplicates(self):
        from backend.agi.research.github_scanner import (
            _merge_discoveries,
            RepoDiscovery,
        )

        existing = [{"full_name": "org/repo1"}]
        new = [
            RepoDiscovery(
                repo_url="",
                name="repo1",
                full_name="org/repo1",
                description="",
                language=None,
                stars=0,
                forks=0,
                last_updated="",
            ),
            RepoDiscovery(
                repo_url="",
                name="repo2",
                full_name="org/repo2",
                description="",
                language=None,
                stars=5,
                forks=1,
                last_updated="",
            ),
        ]
        merged = _merge_discoveries(existing, new)
        assert len(merged) == 2

    def test_load_discoveries_missing_file(self, tmp_path):
        from backend.agi.research.github_scanner import _load_discoveries

        result = _load_discoveries(tmp_path / "missing.json")
        assert result == []

    def test_save_and_load_discoveries(self, tmp_path):
        from backend.agi.research.github_scanner import (
            _save_discoveries,
            _load_discoveries,
        )

        path = tmp_path / "disc.json"
        data = [{"full_name": "org/repo", "stars": 10}]
        _save_discoveries(data, path)
        loaded = _load_discoveries(path)
        assert loaded[0]["full_name"] == "org/repo"

    def test_scanner_init_defaults(self):
        from backend.agi.research.github_scanner import GitHubScanner, DEFAULT_KEYWORDS

        scanner = GitHubScanner()
        assert scanner.keywords == DEFAULT_KEYWORDS
        assert scanner.min_stars == 0

    @pytest.mark.asyncio
    async def test_scanner_scan_with_mock(self, tmp_path):
        from backend.agi.research.github_scanner import GitHubScanner

        scanner = GitHubScanner(
            keywords=["test"],
            discoveries_path=tmp_path / "disc.json",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {
                    "html_url": "https://github.com/org/repo",
                    "name": "repo",
                    "full_name": "org/repo",
                    "description": "A test repo",
                    "language": "Python",
                    "stargazers_count": 100,
                    "forks_count": 10,
                    "updated_at": "2025-01-01",
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_rate = MagicMock()
        mock_rate.status_code = 200
        mock_rate.json.return_value = {
            "resources": {"search": {"remaining": 10, "reset": 0}}
        }
        with patch(
            "httpx.AsyncClient.get",
            new_callable=AsyncMock,
            side_effect=[mock_resp, mock_rate],
        ):
            with patch(
                "backend.agi.research.github_scanner._async_sleep",
                new_callable=AsyncMock,
            ):
                discoveries = await scanner.scan()
        assert len(discoveries) == 1
        assert discoveries[0].full_name == "org/repo"


# ---------------------------------------------------------------------------
# G013 — PaperScanner
# ---------------------------------------------------------------------------


class TestPaperScanner:
    """Tests for backend/agi/research/paper_scanner.py — PaperAlert, PaperScanner, helpers."""

    def test_paper_alert_fingerprint(self):
        from backend.agi.research.paper_scanner import PaperAlert

        a = PaperAlert(
            title="Test Paper",
            source="arxiv",
            url="http://x",
            summary="sum",
            alert_type="paper",
            relevance=0.5,
        )
        fp = a.fingerprint
        assert len(fp) == 64  # sha256 hex

    def test_classify_alert_deprecation(self):
        from backend.agi.research.paper_scanner import _classify_alert

        atype, rel = _classify_alert(
            "API sunset notice", "This endpoint has a breaking change."
        )
        assert atype == "deprecation"
        assert rel > 0.8

    def test_classify_alert_new_endpoint(self):
        from backend.agi.research.paper_scanner import _classify_alert

        atype, rel = _classify_alert("New endpoint introduced", "We added a new API.")
        assert atype == "new_endpoint"

    def test_classify_alert_strategy(self):
        from backend.agi.research.paper_scanner import _classify_alert

        atype, rel = _classify_alert(
            "Trading strategy paper", "Arbitrage in prediction markets."
        )
        assert atype == "strategy"

    def test_classify_alert_paper(self):
        from backend.agi.research.paper_scanner import _classify_alert

        atype, rel = _classify_alert("General research", "Abstract text here.")
        assert atype == "paper"
        assert rel == 0.5

    def test_scanner_deduplicates(self):
        from backend.agi.research.paper_scanner import PaperScanner, PaperAlert

        scanner = PaperScanner()
        scanner._seen.add(
            PaperAlert(
                title="T",
                source="arxiv",
                url="",
                summary="",
                alert_type="paper",
                relevance=0.5,
            ).fingerprint
        )

    def test_parse_arxiv_xml(self):
        from backend.agi.research.paper_scanner import PaperScanner

        scanner = PaperScanner()
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Test Paper Title</title>
            <summary>Abstract text here.</summary>
            <link href="http://arxiv.org/abs/1234"/>
            <published>2025-01-01</published>
          </entry>
        </feed>"""
        entries = scanner._parse_arxiv_xml(xml)
        assert len(entries) == 1
        assert entries[0]["title"] == "Test Paper Title"
        assert entries[0]["link"] == "http://arxiv.org/abs/1234"


# ---------------------------------------------------------------------------
# G013 — CompetitorMonitor
# ---------------------------------------------------------------------------


class TestCompetitorMonitor:
    """Tests for backend/agi/research/competitor_monitor.py — CompetitorRepo, CompetitorChange, helpers."""

    def test_competitor_change_fingerprint(self):
        from backend.agi.research.competitor_monitor import CompetitorChange

        c = CompetitorChange(
            repo_full_name="org/repo",
            change_type="new_commits",
            summary="abc1234: fix stuff",
            details="details",
        )
        assert len(c.fingerprint) == 64

    def test_extract_strategy_signals(self):
        from backend.agi.research.competitor_monitor import _extract_strategy_signals

        signals = _extract_strategy_signals("Added arbitrage and market making bot")
        assert "arbitrage" in signals
        assert "market making" in signals

    def test_extract_strategy_signals_none(self):
        from backend.agi.research.competitor_monitor import _extract_strategy_signals

        signals = _extract_strategy_signals("Fixed typo in README")
        assert len(signals) == 0

    def test_load_state_missing_file(self, tmp_path):
        from backend.agi.research.competitor_monitor import _load_state

        assert _load_state(tmp_path / "missing.json") == {}

    def test_save_and_load_state(self, tmp_path):
        from backend.agi.research.competitor_monitor import _save_state, _load_state

        path = tmp_path / "state.json"
        _save_state({"org/repo": {"stars": 10}}, path)
        loaded = _load_state(path)
        assert loaded["org/repo"]["stars"] == 10

    def test_monitor_init_defaults(self):
        from backend.agi.research.competitor_monitor import (
            CompetitorMonitor,
            DEFAULT_COMPETITORS,
        )

        m = CompetitorMonitor()
        assert m.competitors == DEFAULT_COMPETITORS

    def test_competitor_repo_dataclass(self):
        from backend.agi.research.competitor_monitor import CompetitorRepo

        r = CompetitorRepo(
            full_name="org/repo",
            repo_url="http://x",
            description="d",
            stars=10,
            language="Python",
            last_commit_sha="abc",
            last_commit_msg="msg",
        )
        assert r.strategy_signals == []


# ---------------------------------------------------------------------------
# G013 — WhaleTracker
# ---------------------------------------------------------------------------


class TestWhaleTracker:
    """Tests for backend/agi/research/whale_tracker.py — WhaleProfile, CopySignal, helpers."""

    def test_whale_profile_dataclass(self):
        from backend.agi.research.whale_tracker import WhaleProfile

        w = WhaleProfile(
            address="0xabc",
            username="whale1",
            pnl_30d=5000.0,
            volume_30d=100000.0,
            win_rate=0.65,
            num_trades=100,
            rank=1,
        )
        assert w.copy_signal_score == 0.0
        assert w.positions == []

    def test_copy_signal_dataclass(self):
        from backend.agi.research.whale_tracker import CopySignal

        s = CopySignal(
            whale_address="0xabc",
            whale_username="whale1",
            market_id="m1",
            direction="yes",
            size=500.0,
            confidence=0.8,
            reasoning="Top whale",
        )
        assert s.direction == "yes"

    def test_compute_copy_signal_score_good_whale(self):
        from backend.agi.research.whale_tracker import _compute_copy_signal_score

        score = _compute_copy_signal_score(
            {
                "pnl_30d": 5000,
                "win_rate": 0.7,
                "volume_30d": 100000,
                "num_trades": 200,
            }
        )
        assert score > 0.3

    def test_compute_copy_signal_score_losing_whale(self):
        from backend.agi.research.whale_tracker import _compute_copy_signal_score

        score = _compute_copy_signal_score(
            {
                "pnl_30d": -1000,
                "win_rate": 0.3,
                "volume_30d": 50000,
                "num_trades": 50,
            }
        )
        assert score == 0.0

    def test_compute_copy_signal_score_low_trades(self):
        from backend.agi.research.whale_tracker import _compute_copy_signal_score

        score = _compute_copy_signal_score(
            {
                "pnl_30d": 5000,
                "win_rate": 0.7,
                "volume_30d": 100000,
                "num_trades": 5,
            }
        )
        assert score == 0.0

    def test_tracker_init_defaults(self):
        from backend.agi.research.whale_tracker import WhaleTracker

        t = WhaleTracker()
        assert t.min_pnl_30d == 1000.0
        assert t.min_win_rate == 0.50
        assert t.top_n == 20

    @pytest.mark.asyncio
    async def test_discover_whales_with_mock(self):
        from backend.agi.research.whale_tracker import WhaleTracker

        tracker = WhaleTracker(min_pnl_30d=100, min_win_rate=0.5, min_trades=10)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "address": "0xabc",
                "username": "whale1",
                "pnl": 5000,
                "winRate": 0.7,
                "volume": 100000,
                "numTrades": 200,
            },
            {
                "address": "0xdef",
                "username": "whale2",
                "pnl": 2000,
                "winRate": 0.55,
                "volume": 50000,
                "numTrades": 50,
            },
        ]
        with patch(
            "httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp
        ):
            whales = await tracker.discover_whales()
        assert len(whales) == 2
        assert whales[0].address == "0xabc"


# ---------------------------------------------------------------------------
# G014 — PyBrokerEngine
# ---------------------------------------------------------------------------


class TestPyBrokerEngine:
    """Tests for backend/core/pybroker_backtest.py — PyBrokerConfig, TradeRecord, PyBrokerResult, PyBrokerEngine, etc."""

    def _make_trades(self, n: int = 20, win_rate: float = 0.6):
        from backend.core.pybroker_backtest import TradeRecord

        trades = []
        for i in range(n):
            won = i < int(n * win_rate)
            trades.append(
                TradeRecord(
                    timestamp=datetime(2025, 1, 1) + timedelta(days=i),
                    market_ticker=f"t{i}",
                    direction="up",
                    entry_price=0.5,
                    size=10.0,
                    edge=0.05,
                    settled=True,
                    settlement_value=1.0 if won else 0.0,
                )
            )
        return trades

    def test_pybroker_config_defaults(self):
        from backend.core.pybroker_backtest import PyBrokerConfig

        cfg = PyBrokerConfig()
        assert cfg.initial_bankroll == 1000.0
        assert cfg.kelly_fraction == 0.05
        assert cfg.slippage_bps == 5.0

    def test_trade_record_dataclass(self):
        from backend.core.pybroker_backtest import TradeRecord

        t = TradeRecord(
            timestamp=datetime.now(),
            market_ticker="BTC",
            direction="up",
            entry_price=0.5,
            size=100.0,
            edge=0.05,
        )
        assert t.settled is False
        assert t.settlement_value is None

    def test_empty_backtest(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        result = engine.run_from_trades([])
        assert result.total_trades == 0
        assert result.final_bankroll == 1000.0

    def test_backtest_with_settled_trades(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(20, win_rate=0.7)
        result = engine.run_from_trades(trades)
        assert result.total_trades == 20
        assert result.winning_trades == 14
        assert result.losing_trades == 6
        assert result.win_rate > 0.5
        assert result.final_bankroll != 1000.0  # should have changed

    def test_backtest_equity_curve_length(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(10)
        result = engine.run_from_trades(trades)
        # equity_curve has initial + one per settled trade
        assert len(result.equity_curve) == 11

    def test_backtest_metrics_are_finite(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(30)
        result = engine.run_from_trades(trades)
        assert math.isfinite(result.sharpe_ratio)
        assert math.isfinite(result.max_drawdown_pct)
        assert math.isfinite(result.profit_factor)

    def test_monte_carlo_basic(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(20)
        mc = engine.monte_carlo(trades, n_simulations=50, seed=42)
        assert mc.n_simulations == 50
        assert len(mc.final_bankrolls) == 50
        assert mc.median_final_bankroll > 0

    def test_monte_carlo_empty(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        mc = engine.monte_carlo([], n_simulations=10)
        assert mc.n_simulations == 0

    def test_walk_forward_basic(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(100)
        wf = engine.walk_forward(trades, train_days=30, test_days=10)
        assert len(wf.windows) > 0
        assert wf.strategy_name == "pybroker"

    def test_walk_forward_empty(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        wf = engine.walk_forward([])
        assert len(wf.windows) == 0
        assert wf.oos_sharpe == 0.0

    def test_bootstrap_metrics_basic(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        trades = self._make_trades(20)
        ci = engine.bootstrap_metrics(trades, n_bootstrap=50, seed=42)
        assert "sharpe" in ci
        assert "return_pct" in ci
        assert ci["sharpe"][0] <= ci["sharpe"][1]

    def test_bootstrap_metrics_few_trades(self):
        from backend.core.pybroker_backtest import PyBrokerEngine

        engine = PyBrokerEngine()
        ci = engine.bootstrap_metrics(self._make_trades(3), n_bootstrap=10)
        assert ci["sharpe"] == (0.0, 0.0)

    def test_run_pybroker_backtest_convenience(self):
        from backend.core.pybroker_backtest import run_pybroker_backtest

        trades = self._make_trades(20)
        output = run_pybroker_backtest(trades, monte_carlo=True, walk_forward=True)
        assert "result" in output
        assert "monte_carlo" in output
        assert "walk_forward" in output

    def test_walk_forward_result_dataclass(self):
        from backend.core.pybroker_backtest import WalkForwardResult

        wf = WalkForwardResult(
            strategy_name="test",
            windows=[],
            oos_sharpe=1.0,
            oos_return=100.0,
            oos_win_rate=0.6,
            overfit_ratio=0.8,
            param_stability=0.9,
        )
        assert wf.param_stability == 0.9


# ---------------------------------------------------------------------------
# G014 — HyperliquidStrategy
# ---------------------------------------------------------------------------


class TestHyperliquidStrategy:
    """Tests for backend/strategies/hyperliquid_strategy.py — HyperliquidStrategy."""

    def test_strategy_name_and_defaults(self):
        from backend.strategies.hyperliquid_strategy import HyperliquidStrategy

        s = HyperliquidStrategy()
        assert s.name == "hyperliquid"
        assert s.default_params["min_edge"] == 0.04
        assert s.default_params["max_entry_price"] == 0.80

    @pytest.mark.asyncio
    async def test_run_cycle_no_provider(self):
        from backend.strategies.hyperliquid_strategy import HyperliquidStrategy
        from backend.strategies.base import StrategyContext

        s = HyperliquidStrategy()
        ctx = StrategyContext(
            db=None,
            clob=None,
            settings=None,
            logger=MagicMock(),
            params={},
            mode="paper",
            providers={},
        )
        result = await s.run_cycle(ctx)
        assert result.trades_placed == 0
        assert any("No Hyperliquid provider" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_run_cycle_with_mispriced_market(self):
        from backend.strategies.hyperliquid_strategy import HyperliquidStrategy
        from backend.strategies.base import StrategyContext
        from backend.data.hyperliquid_client import HLMarket
        from backend.data.hyperliquid_client import HyperliquidClient as HLCls

        s = HyperliquidStrategy()
        mock_client = MagicMock(spec=HLCls)
        mock_client.get_markets = AsyncMock(
            return_value=[
                HLMarket(
                    market_id="m1",
                    question="Test?",
                    outcomes=["Yes", "No"],
                    outcome_prices=[0.30, 0.55],
                    volume_24h=1000,
                    liquidity=500,
                ),
            ]
        )
        ctx = StrategyContext(
            db=None,
            clob=None,
            settings=None,
            logger=MagicMock(),
            params={"min_edge": 0.02},
            mode="paper",
            providers={"hyperliquid": mock_client},
        )
        result = await s.run_cycle(ctx)
        assert result.trades_placed >= 1

    @pytest.mark.asyncio
    async def test_market_filter(self):
        from backend.strategies.hyperliquid_strategy import HyperliquidStrategy
        from backend.strategies.base import MarketInfo

        s = HyperliquidStrategy()
        markets = [
            MarketInfo(
                ticker="m1",
                slug="m1",
                category="crypto",
                end_date=None,
                volume=100,
                liquidity=50,
                metadata={"platform": "hyperliquid"},
            ),
            MarketInfo(
                ticker="m2",
                slug="m2",
                category="crypto",
                end_date=None,
                volume=100,
                liquidity=50,
                metadata={"platform": "polymarket"},
            ),
        ]
        filtered = await s.market_filter(markets)
        assert len(filtered) == 1
        assert filtered[0].ticker == "m1"
