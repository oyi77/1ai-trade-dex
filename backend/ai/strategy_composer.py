"""Strategy Composer: AI generates new trading strategy Python code from market observations.

Uses Claude to analyze market data patterns, identify exploitable edges, and generate
complete BaseStrategy subclasses that can be auto-registered and tested in SHADOW mode.
"""

import importlib
import os
import sys
import textwrap
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.database import SessionLocal, StrategyConfig
from backend.models.outcome_tables import StrategyOutcome

from loguru import logger

STRATEGY_TEMPLATE = '''"""Auto-generated strategy by AGI Strategy Composer."""
from loguru import logger
from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult, MarketInfo

class {class_name}(BaseStrategy):
    name = "{strategy_name}"
    description = """{description}"""
    category = "{category}"
    default_params = __DEFAULT_PARAMS__

    def market_filter(self, markets: list[MarketInfo]) -> list[MarketInfo]:
        return [m for m in markets if __MARKET_FILTER__]

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        result = CycleResult(decisions_recorded=0, trades_attempted=0, trades_placed=0)
        params = __MERGE_PARAMS__
        try:
__STRATEGY_BODY__
        except Exception as e:
            result.errors.append(str(e))
            logger.error("[__STRATEGY_NAME__] Cycle error: %s", e)
        return result
'''

MARKET_OBSERVATIONS_PROMPT = """You are a quantitative trading strategy designer for prediction markets (Polymarket).

Given the following market data patterns and existing strategy performance, design ONE new trading strategy.

EXISTING STRATEGIES AND THEIR PERFORMANCE:
{strategy_performance}

MARKET CATEGORIES WITH VOLUME:
{market_categories}

RECENT LOSS PATTERNS (what's NOT working):
{loss_patterns}

DESIGN A STRATEGY THAT:
1. Targets a market category or pattern NOT covered by existing strategies
2. Has clear entry/exit rules based on observable market data
3. Uses conservative position sizing (max 5pct bankroll per trade)

RESPOND IN THIS EXACT FORMAT:
STRATEGY_NAME: [snake_case name, e.g. "funding_rate_arb"]
DESCRIPTION: [1-2 sentences]
CATEGORY: [market category, e.g. "crypto", "politics", "sports"]
DEFAULT_PARAMS: [JSON object, e.g. {"min_edge": 0.05, "max_position_usd": 10.0}]
MARKET_FILTER: [Python expression using 'm' for MarketInfo, e.g. "m.volume > 50000 and 'crypto' in m.category.lower()"]
STRATEGY_BODY: [Python code for run_cycle body, 4-space indented. Use 'ctx' for StrategyContext, 'params' for merged params, 'result' for CycleResult. Import from backend.data or backend.core as needed. Use httpx.AsyncClient for API calls. Return 'result' at end.]
"""


class StrategyComposer:
    async def compose_new_strategy(self, db: Optional[Session] = None) -> Optional[dict]:
        """Analyze market data and generate a new strategy. Returns metadata dict or None."""
        _owned = db is None
        write_db = db or SessionLocal()
        read_db = SessionLocal()
        try:
            try:
                prompt = self._build_prompt(read_db)
            finally:
                read_db.close()

            strategy_code = await self._generate_with_claude(prompt)
            if not strategy_code:
                return None

            result = self._validate_and_register(strategy_code, write_db)
            return result
        except Exception as e:
            logger.error("[StrategyComposer] Failed: %s", e)
            return None
        finally:
            if _owned:
                write_db.close()

    def _build_prompt(self, db: Session) -> str:
        outcomes = db.query(StrategyOutcome).all()
        strategy_perf = {}
        for o in outcomes:
            if o.strategy not in strategy_perf:
                strategy_perf[o.strategy] = {"total": 0, "wins": 0, "pnl": 0.0}
            strategy_perf[o.strategy]["total"] += 1
            if o.result == "win":
                strategy_perf[o.strategy]["wins"] += 1
            strategy_perf[o.strategy]["pnl"] += o.pnl or 0.0

        perf_text = ""
        for name, s in strategy_perf.items():
            wr = s["wins"] / s["total"] if s["total"] > 0 else 0.0
            perf_text += f"\n  {name}: {s['total']} trades, {wr:.0%} WR, ${s['pnl']:.2f} PnL"

        loss_patterns = []
        losses = [o for o in outcomes if o.result != "win"][-20:]
        for loss in losses:
            loss_patterns.append(
                f"  {loss.strategy} on {loss.market_ticker}: edge={loss.edge_at_entry}, conf={loss.confidence}, dir={loss.direction}"
            )

        categories = set(o.market_type for o in outcomes if o.market_type)

        return MARKET_OBSERVATIONS_PROMPT.replace("{strategy_performance}", perf_text or "No data yet").replace("{market_categories}", "\n".join(f"  - {c}" for c in categories) or "crypto, politics, sports").replace("{loss_patterns}", "\n".join(loss_patterns[-10:]) or "No losses recorded yet")

    async def _generate_with_claude(self, prompt: str) -> Optional[dict]:
        try:
            from backend.ai.claude import ClaudeAnalyzer
            from backend.config import settings

            analyzer = ClaudeAnalyzer()
            client = analyzer._get_client()

            message = await client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            response = message.content[0].text
            return self._parse_response(response)
        except Exception as e:
            logger.error("[StrategyComposer] Claude generation failed: %s", e)
            return None

    def _parse_response(self, response: str) -> Optional[dict]:
        import re
        import json

        try:
            name = re.search(r"STRATEGY_NAME:\s*(.+)", response)
            desc = re.search(r"DESCRIPTION:\s*(.+?)(?=\n[A-Z_]+:|$)", response, re.DOTALL)
            cat = re.search(r"CATEGORY:\s*(.+)", response)
            params = re.search(r"DEFAULT_PARAMS:\s*(\{.+?\})", response, re.DOTALL)
            filt = re.search(r"MARKET_FILTER:\s*(.+?)(?=\n[A-Z_]+:|$)", response, re.DOTALL)
            body = re.search(r"STRATEGY_BODY:\s*(.+?)(?=\n[A-Z_]+:|$)", response, re.DOTALL)

            if not all([name, desc, cat, params, filt, body]):
                logger.warning("[StrategyComposer] Failed to parse all fields from response")
                return None

            strategy_name = name.group(1).strip()
            description = desc.group(1).strip()
            category = cat.group(1).strip()
            default_params = json.loads(params.group(1).strip())
            market_filter = filt.group(1).strip()
            _strategy_body = textwrap.indent(body.group(1).strip(), "            ")

            class_name = "".join(w.capitalize() for w in strategy_name.split("_"))

            code = STRATEGY_TEMPLATE.format(
                class_name=class_name,
                strategy_name=strategy_name,
                description=description,
                category=category,
            )
            code = code.replace("__STRATEGY_NAME__", strategy_name)
            code = code.replace("__DEFAULT_PARAMS__", repr(default_params))
            code = code.replace("__MARKET_FILTER__", market_filter)
            code = code.replace("__MERGE_PARAMS__", "{**self.default_params, **(ctx.params or {})}")
            code = code.replace("__STRATEGY_BODY__", textwrap.indent(body.group(1).strip(), "            "))

            return {
                "strategy_name": strategy_name,
                "class_name": class_name,
                "category": category,
                "description": description,
                "default_params": default_params,
                "code": code,
            }
        except Exception as e:
            logger.error("[StrategyComposer] Parse failed: %s", e)
            return None

    def _validate_and_register(self, strategy: dict, db: Session) -> Optional[dict]:
        strategy_name = strategy["strategy_name"]
        code = strategy["code"]

        try:
            compile(code, f"<{strategy_name}>", "exec")
        except SyntaxError as e:
            logger.error("[StrategyComposer] Generated code has syntax error: %s", e)
            return None

        # E-05: Validate LLM-generated code through SandboxValidator before writing to disk
        from backend.agi.sandbox.sandbox_validator import SandboxValidator
        validator = SandboxValidator()
        validation_result = validator.validate(code)
        if not validation_result.passed:
            logger.error(
                "[StrategyComposer] LLM code failed sandbox validation: %s",
                validation_result.errors,
            )
            return None

        existing = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_name == strategy_name
        ).first()
        if existing:
            logger.info("[StrategyComposer] Strategy '%s' already exists, skipping", strategy_name)
            return None

        from backend.strategies.registry import STRATEGY_REGISTRY
        if strategy_name in STRATEGY_REGISTRY:
            logger.info("[StrategyComposer] Strategy '%s' already registered", strategy_name)
            return None

        strategies_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies")
        filepath = os.path.join(strategies_dir, f"{strategy_name}.py")

        if os.path.exists(filepath):
            logger.info("[StrategyComposer] File '%s' already exists", filepath)
            return None

        with open(filepath, "w") as f:
            f.write(code)

        # E-04: Run code through SandboxManager before exec_module() for runtime isolation
        try:
            import asyncio as _asyncio
            from backend.agi.sandbox.sandbox_manager import SandboxManager
            sandbox = SandboxManager()
            try:
                _asyncio.get_running_loop()
                # Already in async context — use thread pool to avoid deadlock
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    sandbox_result = pool.submit(
                        _asyncio.run, sandbox.execute_code(code)
                    ).result(timeout=10)
            except RuntimeError:
                # No running event loop
                sandbox_result = _asyncio.run(sandbox.execute_code(code))

            if not sandbox_result.passed:
                logger.error(
                    "[StrategyComposer] LLM code failed sandbox execution: %s",
                    sandbox_result.errors,
                )
                os.remove(filepath)
                return None
        except Exception as sandbox_err:
            logger.error("[StrategyComposer] Sandbox execution error: %s, removing file", sandbox_err)
            os.remove(filepath)
            return None

        try:
            spec = importlib.util.spec_from_file_location(
                f"backend.strategies.{strategy_name}", filepath
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"backend.strategies.{strategy_name}"] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error("[StrategyComposer] Module load failed: %s, removing file", e)
            os.remove(filepath)
            return None

        if strategy_name not in STRATEGY_REGISTRY:
            logger.error("[StrategyComposer] Strategy did not auto-register, removing file")
            os.remove(filepath)
            return None

        import json
        db.add(StrategyConfig(
            strategy_name=strategy_name,
            enabled=True,
            interval_seconds=300,
            mode="shadow",
            params=json.dumps(strategy["default_params"]),
        ))
        db.commit()

        logger.info(
            "[StrategyComposer] Created & registered '%s' in SHADOW mode at %s",
            strategy_name, filepath,
        )

        return {
            "strategy_name": strategy_name,
            "category": strategy["category"],
            "description": strategy["description"],
            "filepath": filepath,
            "mode": "shadow",
        }
