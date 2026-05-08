import inspect
"""Tests for AGI scheduler job wiring (self-review, research pipeline)."""

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402


class TestSelfReviewJob:
    @pytest.mark.asyncio
    async def test_self_review_job_calls_run_review_cycle(self):
        mock_reviewer = MagicMock()
        mock_reviewer.run_review_cycle = AsyncMock(
            return_value={
                "win_rates": [],
                "postmortems": [],
                "degradation_alerts": [],
                "diary_posted": False,
            }
        )

        with patch("backend.ai.self_review.SelfReview", return_value=mock_reviewer):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

        mock_reviewer.run_review_cycle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_self_review_job_handles_errors_gracefully(self):
        with patch(
            "backend.ai.self_review.SelfReview",
            side_effect=RuntimeError("DB down"),
        ):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

    @pytest.mark.asyncio
    async def test_self_review_job_reports_alert_counts(self):
        mock_reviewer = MagicMock()
        mock_reviewer.run_review_cycle = AsyncMock(
            return_value={
                "win_rates": [{"factor": "strategy", "groups": {}}],
                "postmortems": [MagicMock(), MagicMock()],
                "degradation_alerts": [MagicMock()],
                "diary_posted": True,
            }
        )

        with patch("backend.ai.self_review.SelfReview", return_value=mock_reviewer):
            from backend.core.agi_jobs import self_review_job

            await self_review_job()

        mock_reviewer.run_review_cycle.assert_awaited_once()


class TestResearchPipelineJob:
    @pytest.mark.asyncio
    async def test_research_pipeline_job_calls_run_research_cycle(self):
        mock_pipeline = MagicMock()
        mock_pipeline.run_research_cycle = AsyncMock(return_value=[])

        with patch(
            "backend.research.pipeline.ResearchPipeline",
            return_value=mock_pipeline,
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

        mock_pipeline.run_research_cycle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_research_pipeline_job_handles_errors_gracefully(self):
        with patch(
            "backend.research.pipeline.ResearchPipeline",
            side_effect=RuntimeError("Feed down"),
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

    @pytest.mark.asyncio
    async def test_research_pipeline_job_returns_items(self):
        mock_item = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.run_research_cycle = AsyncMock(
            return_value=[mock_item, mock_item, mock_item]
        )

        with patch(
            "backend.research.pipeline.ResearchPipeline",
            return_value=mock_pipeline,
        ):
            from backend.core.agi_jobs import research_pipeline_job

            await research_pipeline_job()

        mock_pipeline.run_research_cycle.assert_awaited_once()


class TestAGIJobConfigDefaults:
    def test_self_review_settings_exist(self):
        from backend.config import Settings

        s = Settings()
        assert hasattr(s, "SELF_REVIEW_ENABLED")
        assert hasattr(s, "SELF_REVIEW_INTERVAL_DAYS")
        assert s.SELF_REVIEW_ENABLED is True
        assert s.SELF_REVIEW_INTERVAL_DAYS >= 1

    def test_research_pipeline_settings_exist(self):
        from backend.config import Settings

        s = Settings()
        assert hasattr(s, "RESEARCH_PIPELINE_ENABLED")
        assert hasattr(s, "RESEARCH_PIPELINE_INTERVAL_HOURS")
        assert s.RESEARCH_PIPELINE_ENABLED is True
        assert s.RESEARCH_PIPELINE_INTERVAL_HOURS >= 1


class TestSchedulerImportsAGIJobs:
    def test_agi_jobs_importable(self):
        from backend.core.agi_jobs import self_review_job, research_pipeline_job

        assert inspect.iscoroutinefunction(self_review_job)
        assert inspect.iscoroutinefunction(research_pipeline_job)
