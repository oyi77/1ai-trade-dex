"""Tests for shadow validation job."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from backend.core.shadow_validation import shadow_validation_job


class TestShadowValidationJob:
    """Test shadow validation job functionality."""

    def test_eligible_genome_generates_event(self):
        """Test that eligible genome generates event and evolution log entry."""
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        genome = MagicMock()
        genome.genome_id = "test-genome-1001"
        genome.stage = "SHADOW"
        genome.stage_entered_at = seven_days_ago

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [genome]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch('backend.core.shadow_validation.SessionLocal', return_value=mock_db), \
             patch('backend.core.shadow_validation.DBSessionShadowRunner') as MockRunner, \
             patch('backend.core.event_bus.publish_event') as mock_publish:

            MockRunner.return_value.evaluate_promotion_eligibility.return_value = {
                'total_trades': 50,
                'accuracy': 0.85,
                'days_active': 7.0,
                'eligible': True,
                'reason': 'Meets all promotion criteria'
            }

            shadow_validation_job()

            mock_publish.assert_called_once()
            call_args = mock_publish.call_args[0]

            assert call_args[0] == "genome_ready_for_paper"
            event_data = call_args[1]
            assert event_data["genome_id"] == "test-genome-1001"
            assert event_data["stage"] == "SHADOW"
            assert event_data["target_stage"] == "PAPER"
            mock_db.add.assert_called()
            mock_db.commit.assert_called()

    def test_stale_low_accuracy_genome_killed(self):
        """Test that stale low-accuracy genome is auto-killed to GRAVEYARD."""
        now = datetime.now(timezone.utc)
        eight_days_ago = now - timedelta(days=8)

        genome = MagicMock()
        genome.genome_id = "test-genome-1002"
        genome.stage = "SHADOW"
        genome.stage_entered_at = eight_days_ago

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [genome]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch('backend.core.shadow_validation.SessionLocal', return_value=mock_db), \
             patch('backend.core.shadow_validation.DBSessionShadowRunner') as MockRunner, \
             patch('backend.core.event_bus.publish_event') as _mock_publish2:

            MockRunner.return_value.evaluate_promotion_eligibility.return_value = {
                'total_trades': 10,
                'accuracy': 0.35,
                'days_active': 8.0,
                'eligible': False,
                'reason': 'Accuracy below 60% threshold'
            }

            shadow_validation_job()

            assert genome.stage == "GRAVEYARD"
            assert genome.stage_entered_at is not None

            mock_db.add.assert_called()
            mock_db.commit.assert_called()

    def test_disabled_when_feature_flag_off(self):
        """Test that job is disabled when SHADOW_VALIDATE_ENABLED=False."""
        with patch.object(__import__('backend.config', fromlist=['settings']).settings, 'SHADOW_VALIDATE_ENABLED', False), \
             patch('backend.core.shadow_validation.logger') as mock_logger:
            shadow_validation_job()
            mock_logger.info.assert_called_with("Shadow validation disabled by config")

    def test_no_shadow_genomes(self):
        """Test that job handles no SHADOW genomes gracefully."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch('backend.core.shadow_validation.SessionLocal', return_value=mock_db), \
             patch('backend.core.shadow_validation.logger') as mock_logger:
            shadow_validation_job()
            mock_logger.info.assert_any_call("Found 0 genomes in SHADOW stage")

    def test_genome_without_stage_entered_at(self):
        """Test that genomes without stage_entered_at are skipped."""
        genome = MagicMock()
        genome.genome_id = "test-genome-1003"
        genome.stage_entered_at = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [genome]
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch('backend.core.shadow_validation.SessionLocal', return_value=mock_db), \
             patch('backend.core.shadow_validation.DBSessionShadowRunner') as MockRunner, \
             patch('backend.core.shadow_validation.logger') as mock_logger:

            shadow_validation_job()

            mock_logger.warning.assert_called_with("Genome test-genome-1003 has no stage_entered_at, skipping")
            MockRunner.return_value.evaluate_promotion_eligibility.assert_not_called()
