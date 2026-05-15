"""Phase Gate 6 Certification Checklist.

Aggregates benchmark results and verifies that all certifications pass threshold requirements.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from loguru import logger

logger = logger.bind(task="evals", module="certification_checklist")


def run_certification_check(
    reports_dir: str = "backend/evals/reports",
    custom_scores: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """Run certification check across all Phase 6 benchmarks.

    Args:
        reports_dir: Directory to save certification reports
        custom_scores: Optional pre-computed benchmark scores for testing

    Returns:
        Dict with structure:
        {
            "benchmark_thresholds": {
                "cross_domain_transfer": <score>,
                "few_shot_learning": <score>,
                "causal_reasoning": <score>,
                "agi_score": <score>
            },
            "certification_eligible": <bool>,
            "passed_benchmarks": [<list of passed names>],
            "failed_benchmarks": [<list of failed names>],
            "timestamp": <datetime>,
            "details": {<benchmark_name>: {score, passed, metadata}}
        }
    """
    logger.info("Starting Phase Gate 6 certification check")

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    # Import benchmark classes
    from backend.evals.benchmarks.cross_domain_transfer import CrossDomainTransferBenchmark
    from backend.evals.benchmarks.few_shot_learning import FewShotLearningBenchmark
    from backend.evals.benchmarks.causal_reasoning import CausalReasoningBenchmark
    from backend.evals.benchmarks.agi_score import AGIScoreBenchmark

    # Define benchmark specs: (benchmark_class, threshold, key_name)
    benchmarks_specs = [
        (CrossDomainTransferBenchmark, 0.60, "cross_domain_transfer"),
        (FewShotLearningBenchmark, 0.70, "few_shot_learning"),
        (CausalReasoningBenchmark, 0.80, "causal_reasoning"),
        (AGIScoreBenchmark, 0.70, "agi_score"),
    ]

    benchmark_thresholds = {}
    passed_benchmarks = []
    failed_benchmarks = []
    details = {}

    # Run or use provided scores
    if custom_scores:
        logger.info("Using custom benchmark scores for certification")
        for bench_class, threshold, key_name in benchmarks_specs:
            score = custom_scores.get(key_name, 0.0)
            passed = score >= threshold

            benchmark_thresholds[key_name] = score
            if passed:
                passed_benchmarks.append(key_name)
            else:
                failed_benchmarks.append(key_name)

            details[key_name] = {
                "score": score,
                "threshold": threshold,
                "passed": passed
            }
    else:
        # Run each benchmark
        for bench_class, threshold, key_name in benchmarks_specs:
            try:
                logger.info(f"Running {key_name} benchmark")
                benchmark = bench_class(reports_dir=reports_dir)
                result = benchmark.run()

                score = result.score
                passed = result.passed and (score >= threshold)

                benchmark_thresholds[key_name] = score
                if passed:
                    passed_benchmarks.append(key_name)
                else:
                    failed_benchmarks.append(key_name)

                details[key_name] = {
                    "score": score,
                    "threshold": threshold,
                    "passed": passed,
                    "benchmark_id": result.benchmark_id,
                    "metadata": result.metadata if result.metadata else {}
                }

                logger.info(f"{key_name}: {score:.2%} (threshold: {threshold:.0%}) - {'PASS' if passed else 'FAIL'}")

            except Exception as e:
                logger.error(f"Error running {key_name} benchmark: {e}")
                benchmark_thresholds[key_name] = 0.0
                failed_benchmarks.append(key_name)
                details[key_name] = {
                    "score": 0.0,
                    "threshold": threshold,
                    "passed": False,
                    "error": str(e)
                }

    # Determine certification eligibility: all benchmarks must pass
    certification_eligible = len(failed_benchmarks) == 0

    result_dict = {
        "benchmark_thresholds": benchmark_thresholds,
        "certification_eligible": certification_eligible,
        "passed_benchmarks": passed_benchmarks,
        "failed_benchmarks": failed_benchmarks,
        "timestamp": datetime.now().isoformat(),
        "details": details
    }

    # Save certification report
    report_path = reports_path / f"certification_checklist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(report_path, "w") as f:
            json.dump(result_dict, f, indent=2)
        logger.info(f"Certification report saved to {report_path}")
    except Exception as e:
        logger.warning(f"Failed to save certification report: {e}")

    logger.info(
        f"Certification check complete: "
        f"passed={len(passed_benchmarks)}, "
        f"failed={len(failed_benchmarks)}, "
        f"eligible={certification_eligible}"
    )

    return result_dict


class CertificationChecklist:
    """Class interface for certification checklist (for backwards compatibility)."""

    @staticmethod
    def verify_phase_gate_6(
        reports_dir: str = "backend/evals/reports",
        custom_scores: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """Verify Phase Gate 6 certification criteria.

        Alias for run_certification_check() for class-based access.
        """
        return run_certification_check(reports_dir=reports_dir, custom_scores=custom_scores)
