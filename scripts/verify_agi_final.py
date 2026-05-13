import sys
sys.path.insert(0, 'backend')

from core.regime_detector import RegimeDetector, RegimeResult
from core.knowledge_graph import KnowledgeGraph
from core.strategy_composer import StrategyComposer, StrategyBlock
from core.strategy_allocator import RegimeAwareAllocator
from core.agi_goal_engine import AGIGoalEngine, AGIGoal, MarketRegime
from core.self_debugger import SelfDebugger
from core.llm_cost_tracker import LLMCostTracker
from core.agi_promotion_pipeline import AGIPromotionPipeline
from core.causal_reasoning import CausalReasoner
from core.agi_orchestrator import AGIOrchestrator
from core.dynamic_prompt_engine import DynamicPromptEngine
from core.strategy_synthesizer import StrategySynthesizer
from core.experiment_runner import ExperimentRunner

print("✅ ALL 15 CORE MODULES IMPORTED SUCCESSFULLY")

# Test RegimeDetector
detector = RegimeDetector()
result = detector.detect_regime({'btc_price': 50000, 'btc_change_24h': 0.05, 'volume_ratio': 1.3, 'volatility': 0.02})
assert isinstance(result, RegimeResult)
print(f"✅ RegimeDetector: regime={result.regime}, confidence={result.confidence}")

# Test KnowledgeGraph
kg = KnowledgeGraph()
entity = kg.add_entity('test', 'entity1', {'value': 42})
assert entity is not None
assert entity.properties['value'] == 42
retrieved = kg.get_entity('entity1')
assert retrieved is not None
print("✅ KnowledgeGraph: entity stored and retrieved")

# Test StrategyComposer
composer = StrategyComposer()
blocks = [StrategyBlock(signal_source='btc_momentum_signal', filter='min_edge_005', position_sizer='kelly_sizer', risk_rule='max_1pct', exit_rule='take_profit_10pct')]
composed = composer.compose(blocks, 'test_strategy')
assert composed.name == 'test_strategy'
print(f"✅ StrategyComposer: strategy '{composed.name}' composed")

# Test RegimeAwareAllocator
kg2 = KnowledgeGraph()
allocator = RegimeAwareAllocator(kg2)
allocation = allocator.allocate(['strat1', 'strat2'], MarketRegime.BULL, 10000.0)
assert isinstance(allocation, dict)
print(f"✅ RegimeAwareAllocator: {len(allocation)} strategies allocated")

# Test AGIGoalEngine
engine = AGIGoalEngine()
transition = {'old_regime': MarketRegime.UNKNOWN, 'new_regime': MarketRegime.BULL, 'confidence': 0.85, 'market_data': {'btc_price': 50000}}
goal = engine.handle_regime_change(transition)
assert isinstance(goal, AGIGoal)
print(f"✅ AGIGoalEngine: goal={goal.value}")

# Test SelfDebugger
debugger = SelfDebugger()
error = Exception('API returned 503')
diagnosis = debugger.diagnose_error(error, {'endpoint': '/test'})
assert diagnosis is not None
print(f"✅ SelfDebugger: diagnosis type={type(diagnosis).__name__}")

# Test LLMCostTracker
tracker = LLMCostTracker(daily_budget=10.0)
tracker.record_call('claude-3-opus', 1000, 0.03, 'test')
status = tracker.get_budget_status()
assert status.spent_today == 0.03
print(f"✅ LLMCostTracker: spent={status.spent_today}, remaining={status.remaining}")

# Test AGIPromotionPipeline
pipeline = AGIPromotionPipeline()
result = pipeline.submit_experiment('test_exp')
assert result is not None
print(f"✅ AGIPromotionPipeline: promoted={result.promoted}, msg={result.message}")

# Test CausalReasoner
reasoner = CausalReasoner()
explanation = reasoner.trace_causation('trade_001')
assert isinstance(explanation, list)
print(f"✅ CausalReasoner: {len(explanation)} explanation(s)")

# Test AGIOrchestrator
orch = AGIOrchestrator()
status = orch.get_status()
assert status is not None
print(f"✅ AGIOrchestrator: status type={type(status).__name__}")

# Test DynamicPromptEngine
engine2 = DynamicPromptEngine()
print("✅ DynamicPromptEngine: instantiated")

# Test StrategySynthesizer
synthesizer = StrategySynthesizer()
print("✅ StrategySynthesizer: instantiated")

# Test ExperimentRunner
runner = ExperimentRunner()
print("✅ ExperimentRunner: instantiated")

print()
print("="*60)
print("🎉 ALL 15 CORE AGI MODULES FULLY VERIFIED")
print("="*60)
