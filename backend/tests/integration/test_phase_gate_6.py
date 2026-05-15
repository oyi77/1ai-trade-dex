"""Phase Gate 6 integration test - Final AGI Certification.
Aggregates Tasks 31-34 to verify all benchmarks pass."""

import pytest
import json
from pathlib import Path


class TestPhaseGate6:
    """Verify all Phase 6 benchmarks meet thresholds."""
    
    def test_cross_domain_transfer_threshold(self):
        from backend.evals.benchmarks.cross_domain_transfer import CrossDomainTransferBenchmark
        benchmark = CrossDomainTransferBenchmark()
        result = benchmark.run()
        assert result.score >= 0.60, f"Cross-Domain Transfer {result.score:.2%} < 60%"
    
    def test_few_shot_learning_threshold(self):
        from backend.evals.benchmarks.few_shot_learning import FewShotLearningBenchmark
        benchmark = FewShotLearningBenchmark()
        result = benchmark.run()
        assert result.score >= 0.70, f"Few-Shot Learning {result.score:.2%} < 70%"
    
    def test_causal_reasoning_threshold(self):
        from backend.evals.benchmarks.causal_reasoning import CausalReasoningBenchmark
        benchmark = CausalReasoningBenchmark()
        result = benchmark.run()
        assert result.score >= 0.80, f"Causal Reasoning {result.score:.2%} < 80%"
    
    def test_agi_score_composite_threshold(self):
        from backend.evals.benchmarks.agi_score import AGIScoreBenchmark
        benchmark = AGIScoreBenchmark()
        result = benchmark.run()
        assert result.score >= 0.70, f"AGI-Score {result.score:.2%} < 70%"
    
    def test_all_benchmarks_registered(self):
        try:
            from backend.evals.registry import BenchmarkRegistry
            registry = BenchmarkRegistry()
            registered = ["cross_domain_transfer", "few_shot_learning", "causal_reasoning", "agi_score"]
            for bench_id in registered:
                assert registry.get(bench_id) is not None, f"{bench_id} not registered"
        except ImportError:
            pytest.skip("BenchmarkRegistry not available")
    
    def test_reports_saved(self):
        reports_dir = Path("backend/evals/reports")
        if reports_dir.exists():
            reports = list(reports_dir.glob("*.json"))
            assert len(reports) >= 4, f"Expected at least 4 reports, found {len(reports)}"


def test_phase_gate_6_certification():
    """Verify Phase Gate 6 certification criteria."""
    from backend.evals.certification_checklist import run_certification_check
    results = run_certification_check()
    
    assert results["benchmark_thresholds"]["cross_domain_transfer"] >= 0.60
    assert results["benchmark_thresholds"]["few_shot_learning"] >= 0.70
    assert results["benchmark_thresholds"]["causal_reasoning"] >= 0.80
    assert results["benchmark_thresholds"]["agi_score"] >= 0.70
    assert results["certification_eligible"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
