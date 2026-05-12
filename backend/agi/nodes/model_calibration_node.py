"""Model calibration AGI node - monitors and triggers model retraining."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class ModelCalibrationNode(BaseAGINode):
    """Checks model calibration and triggers retraining if needed."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="model_calibration",
            version="1.0.0",
            description="Checks model calibration drift and triggers retraining",
            input_keys=["prediction_history", "actual_outcomes"],
            output_keys=["calibration_report", "retrain_triggered"],
            tags=["calibration", "model", "retraining"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.calibration_tracker import CalibrationTracker

        prediction_history = state.get("prediction_history", [])
        actual_outcomes = state.get("actual_outcomes", [])

        if not prediction_history or not actual_outcomes:
            return state.with_error(
                self.manifest().name,
                ValueError("Insufficient data for calibration check")
            )

        try:
            tracker = CalibrationTracker()
            report = tracker.check_calibration(prediction_history, actual_outcomes)
            retrain = report.get("brier_drift", 0) > 0.1
            return state.evolve(
                data={
                    "calibration_report": report,
                    "retrain_triggered": retrain,
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)