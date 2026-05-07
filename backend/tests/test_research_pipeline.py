import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.research.models import ResearchItem
from backend.research.pipeline import ResearchPipeline


class TestFingerprint:
    def test_same_input_same_hash(self):
        p = ResearchPipeline()
        fp1 = p._fingerprint("Test Title", "source.com")
        fp2 = p._fingerprint("Test Title", "source.com")
        assert fp1 == fp2

    def test_different_input_different_hash(self):
        p = ResearchPipeline()
        fp1 = p._fingerprint("Test Title", "source.com")
        fp3 = p._fingerprint("Different Title", "source.com")
        assert fp1 != fp3


class TestResearchPipelineInit:
    def test_has_run_research_cycle(self):
        p = ResearchPipeline()
        assert hasattr(p, "run_research_cycle")

    def test_run_research_cycle_is_async(self):
        p = ResearchPipeline()
        assert inspect.iscoroutinefunction(p.run_research_cycle)


def _make_item(
    title="Test Market", content="Some content", source="https://test.com/feed"
) -> ResearchItem:
    p = ResearchPipeline()
    return ResearchItem(
        title=title,
        source=source,
        content=content,
        relevance_score=0.8,
        url="https://test.com",
        fingerprint=p._fingerprint(title, source),
    )


def _set_scores(items, score):
    for item in items:
        item.relevance_score = score
    return items


class TestEntityRegex:
    def test_extracts_multi_word_names(self):
        p = ResearchPipeline()
        entities = p._extract_entities_regex("Donald Trump wins the election")
        assert "Donald Trump" in entities

    def test_extracts_acronyms(self):
        p = ResearchPipeline()
        entities = p._extract_entities_regex("BTC price rises amid NATO summit")
        assert "BTC" in entities
        assert "NATO" in entities

    def test_filters_stopwords(self):
        p = ResearchPipeline()
        entities = p._extract_entities_regex("The Federal Reserve raises rates")
        assert "The" not in entities
        assert "Federal Reserve" in entities

    def test_deduplicates(self):
        p = ResearchPipeline()
        entities = p._extract_entities_regex("Donald Trump said Donald Trump")
        assert entities.count("Donald Trump") == 1

    def test_limits_to_20(self):
        p = ResearchPipeline()
        text = " ".join(f"Entity{chr(65 + i)} Name{chr(65 + i)}" for i in range(25))
        entities = p._extract_entities_regex(text)
        assert len(entities) <= 20

    def test_empty_text(self):
        p = ResearchPipeline()
        entities = p._extract_entities_regex("")
        assert entities == []


class TestExtractKgTriples:
    @pytest.mark.asyncio
    async def test_falls_back_to_regex_when_llm_unavailable(self):
        p = ResearchPipeline()
        item = _make_item(
            title="Donald Trump Federal Reserve Decision",
            content="Federal Reserve chair discusses BTC policy",
        )
        with patch(
            "backend.research.pipeline.ResearchPipeline._extract_kg_triples_llm",
            new_callable=AsyncMock,
            return_value=[],
        ):
            triples = await p.extract_kg_triples(item)

        assert len(triples) > 0
        subjects = [t[0] for t in triples]
        assert any("Donald Trump" in s for s in subjects) or any(
            "Federal Reserve" in s for s in subjects
        )
        for subj, pred, obj, conf in triples:
            assert isinstance(subj, str) and subj
            assert isinstance(pred, str) and pred
            assert isinstance(obj, str) and obj
            assert 0.0 <= conf <= 1.0

    @pytest.mark.asyncio
    async def test_uses_llm_triples_when_available(self):
        p = ResearchPipeline()
        item = _make_item(title="Test Market")
        llm_triples = [("BTC", "affects", "Crypto Markets", 0.9)]
        with patch(
            "backend.research.pipeline.ResearchPipeline._extract_kg_triples_llm",
            new_callable=AsyncMock,
            return_value=llm_triples,
        ):
            triples = await p.extract_kg_triples(item)

        assert triples == llm_triples

    @pytest.mark.asyncio
    async def test_llm_extraction_handles_malformed_response(self):
        p = ResearchPipeline()
        item = _make_item(title="Some Market Event")

        mock_router = MagicMock()
        mock_router.complete_json = AsyncMock(return_value={"triples": ["not a list"]})

        with patch("backend.ai.llm_router.LLMRouter", return_value=mock_router):
            triples = await p._extract_kg_triples_llm(item)

        assert triples == []

    @pytest.mark.asyncio
    async def test_llm_extraction_clamps_confidence(self):
        p = ResearchPipeline()
        item = _make_item(title="Test")

        mock_router = MagicMock()
        mock_router.complete_json = AsyncMock(
            return_value={"triples": [["A", "affects", "B", 5.0]]}
        )

        with patch("backend.ai.llm_router.LLMRouter", return_value=mock_router):
            triples = await p._extract_kg_triples_llm(item)

        assert len(triples) == 1
        assert triples[0][3] == 1.0

    @pytest.mark.asyncio
    async def test_regex_fallback_includes_sourced_from(self):
        p = ResearchPipeline()
        item = _make_item(
            title="Donald Trump Wins",
            source="https://polymarket.com/feed.xml",
        )
        with patch(
            "backend.research.pipeline.ResearchPipeline._extract_kg_triples_llm",
            new_callable=AsyncMock,
            return_value=[],
        ):
            triples = await p.extract_kg_triples(item)

        predicates = [t[1] for t in triples]
        assert "sourced_from" in predicates

    @pytest.mark.asyncio
    async def test_max_10_triples_from_regex(self):
        p = ResearchPipeline()
        text = " ".join(f"Person{chr(65 + i)} Name{chr(65 + i)}" for i in range(15))
        item = _make_item(title=text, content=text)
        with patch(
            "backend.research.pipeline.ResearchPipeline._extract_kg_triples_llm",
            new_callable=AsyncMock,
            return_value=[],
        ):
            triples = await p.extract_kg_triples(item)

        assert len(triples) <= 10


class TestPostKgTriples:
    @pytest.mark.asyncio
    async def test_posts_triples_to_bigbrain(self):
        p = ResearchPipeline()
        item = _make_item(title="Donald Trump Decision")

        mock_brain = MagicMock()
        mock_brain.add_kg_triple = AsyncMock(
            return_value={"success": True, "triple_id": "t1"}
        )

        with (
            patch(
                "backend.research.pipeline.ResearchPipeline.extract_kg_triples",
                new_callable=AsyncMock,
                return_value=[("Donald Trump", "mentioned_in", "Decision", 0.6)],
            ),
            patch("backend.clients.bigbrain.BigBrainClient", return_value=mock_brain),
        ):
            posted = await p._post_kg_triples([item])

        assert posted == 1
        mock_brain.add_kg_triple.assert_called_once_with(
            "Donald Trump", "mentioned_in", "Decision", 0.6
        )

    @pytest.mark.asyncio
    async def test_handles_kg_api_failure_gracefully(self):
        p = ResearchPipeline()
        item = _make_item(title="Test Market")

        mock_brain = MagicMock()
        mock_brain.add_kg_triple = AsyncMock(side_effect=ConnectionError("down"))

        with (
            patch(
                "backend.research.pipeline.ResearchPipeline.extract_kg_triples",
                new_callable=AsyncMock,
                return_value=[("A", "affects", "B", 0.5)],
            ),
            patch("backend.clients.bigbrain.BigBrainClient", return_value=mock_brain),
        ):
            posted = await p._post_kg_triples([item])

        assert posted == 0

    @pytest.mark.asyncio
    async def test_handles_bigbrain_init_failure(self):
        p = ResearchPipeline()
        item = _make_item(title="Test Market")

        with patch(
            "backend.clients.bigbrain.BigBrainClient",
            side_effect=RuntimeError("import fail"),
        ):
            posted = await p._post_kg_triples([item])

        assert posted == 0

    @pytest.mark.asyncio
    async def test_counts_only_successful_posts(self):
        p = ResearchPipeline()
        item = _make_item(title="Multi Triple Test")

        call_count = 0

        async def alternating_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                return {"success": False, "error": "fail"}
            return {"success": True, "triple_id": f"t{call_count}"}

        mock_brain = MagicMock()
        mock_brain.add_kg_triple = AsyncMock(side_effect=alternating_response)

        with (
            patch(
                "backend.research.pipeline.ResearchPipeline.extract_kg_triples",
                new_callable=AsyncMock,
                return_value=[
                    ("A", "affects", "B", 0.5),
                    ("C", "related_to", "D", 0.6),
                    ("E", "mentioned_in", "F", 0.7),
                ],
            ),
            patch("backend.clients.bigbrain.BigBrainClient", return_value=mock_brain),
        ):
            posted = await p._post_kg_triples([item])

        assert posted == 2


class TestRunResearchCycleKgIntegration:
    @pytest.mark.asyncio
    async def test_kg_failure_does_not_crash_cycle(self):
        p = ResearchPipeline()

        with (
            patch.object(
                p,
                "_fetch_rss_feeds",
                new_callable=AsyncMock,
                return_value=[_make_item(title="Test Item")],
            ),
            patch.object(
                p,
                "_search_bigbrain",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                p,
                "_score_items",
                new_callable=AsyncMock,
                side_effect=lambda items: _set_scores(items, 0.8),
            ),
            patch.object(
                p,
                "_post_kg_triples",
                new_callable=AsyncMock,
                side_effect=RuntimeError("KG down"),
            ),
        ):
            result = await p.run_research_cycle()

        assert len(result) == 1
        assert result[0].title == "Test Item"
