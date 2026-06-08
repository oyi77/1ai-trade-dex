from groq import AsyncGroq
from anthropic import AsyncAnthropic
"""
AI Parameter Optimizer for PolyEdge Trading Bot.

Analyzes trading performance and suggests parameter adjustments using AI providers.
"""

import json
import re
from sqlalchemy.orm import Session

from loguru import logger
from backend.ai.custom import get_custom_client
from backend.core.llm_cost_tracker import LLMCostTracker
from backend.models.database import Trade


class ParameterOptimizer:
    """
    Analyzes trading bot performance and uses AI to suggest parameter improvements.

    Supports multiple AI providers:
    - Groq (default, fast)
    - Claude (high quality)
    - Custom/OpenAI-compatible (OmniRoute)
    - Math-based fallback (no AI required)
    """

    def __init__(self, settings):
        """
        Initialize optimizer with settings.

        Args:
            settings: Application settings object (from backend.config)
        """
        self.settings = settings

    def analyze_performance(self, db: Session, trade_limit: int = 100) -> dict:
        """
        Compute trading statistics from recent trades.

        Args:
            db: Database session
            trade_limit: Number of recent trades to analyze

        Returns:
            dict with keys: win_rate, total_trades, pnl, avg_win_edge,
                          avg_loss_edge, top_strategy
        """

        trades = (
            db.query(Trade).order_by(Trade.timestamp.desc()).limit(trade_limit).all()
        )
        total_trades = len(trades)
        settled_trades = [t for t in trades if t.result in ("win", "loss")]
        wins = [t for t in settled_trades if t.result == "win"]
        losses = [t for t in settled_trades if t.result == "loss"]
        win_rate = len(wins) / len(settled_trades) if settled_trades else 0.0
        total_pnl = sum(t.pnl or 0.0 for t in settled_trades)

        avg_win_edge = (
            sum(t.edge_at_entry or 0.0 for t in wins) / len(wins) if wins else 0.0
        )
        avg_loss_edge = (
            sum(t.edge_at_entry or 0.0 for t in losses) / len(losses) if losses else 0.0
        )

        strategy_counts = {}
        for t in trades:
            s = t.strategy or "unknown"
            strategy_counts[s] = strategy_counts.get(s, 0) + 1
        top_strategy = (
            max(strategy_counts, key=lambda k: strategy_counts[k])
            if strategy_counts
            else "unknown"
        )

        return {
            "win_rate": win_rate,
            "total_trades": total_trades,
            "pnl": total_pnl,
            "avg_win_edge": avg_win_edge,
            "avg_loss_edge": avg_loss_edge,
            "top_strategy": top_strategy,
        }

    def build_prompt(self, analysis: dict) -> str:
        """
        Build AI prompt for parameter suggestions.

        Args:
            analysis: Performance metrics from analyze_performance()

        Returns:
            str: Prompt for AI provider
        """
        kelly = self.settings.KELLY_FRACTION
        edge = self.settings.MIN_EDGE_THRESHOLD
        max_size = self.settings.MAX_TRADE_SIZE
        daily_limit = self.settings.DAILY_LOSS_LIMIT

        return f"""You are a trading parameter optimizer. Analyze this trading bot's performance data and suggest parameter adjustments.

Current parameters:
- Kelly Fraction: {kelly}
- Min Edge Threshold: {edge}
- Max Trade Size: {max_size}
- Daily Loss Limit: {daily_limit}

Recent performance (last {analysis["total_trades"]} trades):
- Win rate: {analysis["win_rate"]:.1%}
- Total PNL: ${analysis["pnl"]:.2f}
- Avg edge of winning trades: {analysis["avg_win_edge"]:.3f}
- Avg edge of losing trades: {analysis["avg_loss_edge"]:.3f}
- Most active strategy: {analysis["top_strategy"]}

Provide specific numerical suggestions in JSON format:
{{
  "kelly_fraction": <number>,
  "min_edge_threshold": <number>,
  "max_trade_size": <number>,
  "daily_loss_limit": <number>,
  "reasoning": "<2-3 sentence explanation>",
  "confidence": "<low|medium|high>"
}}"""

    def parse_suggestions(self, raw: str) -> dict:
        """
        Extract JSON from AI response.

        Args:
            raw: Raw text response from AI

        Returns:
            dict: Parsed suggestion parameters
        """
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(raw)

    def get_suggestions_fallback(self, analysis: dict) -> dict:
        """
        Math-based parameter suggestions (no AI required).

        Args:
            analysis: Performance metrics from analyze_performance()

        Returns:
            dict with suggestions, analysis, ai_provider="unavailable"
        """
        kelly = self.settings.KELLY_FRACTION
        edge = self.settings.MIN_EDGE_THRESHOLD
        max_size = self.settings.MAX_TRADE_SIZE
        daily_limit = self.settings.DAILY_LOSS_LIMIT

        suggested_kelly = kelly
        suggested_edge = edge
        suggested_max_size = max_size
        suggested_daily_limit = daily_limit
        confidence = "low"
        reasoning = "AI provider unavailable. Suggestions based on performance math."

        if analysis["total_trades"] >= 10:
            if analysis["win_rate"] > 0.6:
                suggested_kelly = min(kelly * 1.1, 0.25)
                suggested_max_size = min(max_size * 1.1, 150.0)
                confidence = "medium"
                reasoning = f"Win rate of {analysis['win_rate']:.1%} is strong. Slightly increasing Kelly and max trade size."
            elif analysis["win_rate"] < 0.4:
                suggested_kelly = max(kelly * 0.8, 0.05)
                suggested_edge = min(edge * 1.2, 0.10)
                suggested_max_size = max(max_size * 0.8, 25.0)
                confidence = "medium"
                reasoning = f"Win rate of {analysis['win_rate']:.1%} is weak. Reducing position sizing and raising edge threshold."

        return {
            "suggestions": {
                "kelly_fraction": round(suggested_kelly, 4),
                "min_edge_threshold": round(suggested_edge, 4),
                "max_trade_size": round(suggested_max_size, 2),
                "daily_loss_limit": round(suggested_daily_limit, 2),
                "reasoning": reasoning,
                "confidence": confidence,
            },
            "analysis": analysis,
            "ai_provider": "unavailable",
            "raw_response": "",
        }

    async def get_suggestions(self, db: Session) -> dict:
        """
        Main entry point: Get AI-powered parameter suggestions.

        Args:
            db: Database session

        Returns:
            dict with keys: status, suggestions, analysis, ai_provider, raw_response
        """
        # 1. Analyze performance
        analysis = self.analyze_performance(db)

        # 2. Try AI providers in order
        ai_provider = getattr(self.settings, "AI_PROVIDER", "groq")

        # --- OmniRoute / Custom (OpenAI-compatible) ---
        if ai_provider in ("omniroute", "custom"):

            custom = get_custom_client()
            if custom:
                try:
                    prompt = self.build_prompt(analysis)
                    suggestions, raw = custom.suggest_params(prompt)
                    return {
                        "status": "ok",
                        "suggestions": suggestions,
                        "analysis": analysis,
                        "ai_provider": f"{ai_provider}/{custom.model}",
                        "raw_response": raw,
                    }
                except Exception as e:
                    logger.warning(f"{ai_provider} AI suggest failed: {e}")

        # --- Groq ---
        if ai_provider == "groq" or (
            ai_provider in ("omniroute", "custom") and not get_custom_client()
        ):
            groq_key = getattr(self.settings, "GROQ_API_KEY", None)
            if groq_key:
                try:

                    model = (
                        getattr(self.settings, "AI_MODEL", None)
                        or "llama-3.1-70b-versatile"
                    )
                    client = AsyncGroq(api_key=groq_key)
                    prompt = self.build_prompt(analysis)
                    response = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=400,
                        temperature=0.2,
                    )
                    raw = response.choices[0].message.content.strip()
                    tokens = response.usage.total_tokens if response.usage else 0
                    try:

                        cost_tracker = LLMCostTracker()
                        cost_per_1k = 0.0002  # Groq approximate cost
                        cost_tracker.record_call(
                            model,
                            tokens,
                            cost_per_1k * max(tokens, 1) / 1000,
                            "optimizer",
                        )
                    except Exception as ct_err:
                        logger.debug(f"Cost tracking failed: {ct_err}")
                    suggestions = self.parse_suggestions(raw)
                    return {
                        "status": "ok",
                        "suggestions": suggestions,
                        "analysis": analysis,
                        "ai_provider": f"groq/{model}",
                        "raw_response": raw,
                    }
                except Exception as e:
                    logger.warning(f"Groq AI suggest failed: {e}")

        # --- Claude ---
        if ai_provider == "claude":
            claude_key = getattr(self.settings, "ANTHROPIC_API_KEY", None)
            if claude_key:
                try:

                    model = (
                        getattr(self.settings, "AI_MODEL", None)
                        or "claude-3-5-haiku-20241022"
                    )
                    client = AsyncAnthropic(api_key=claude_key)
                    prompt = self.build_prompt(analysis)
                    message = await client.messages.create(
                        model=model,
                        max_tokens=400,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    raw = message.content[0].text.strip()
                    tokens = message.usage.input_tokens + message.usage.output_tokens
                    try:

                        cost_tracker = LLMCostTracker()
                        cost_per_1k = 0.015  # Claude approximate cost
                        cost_tracker.record_call(
                            model,
                            tokens,
                            cost_per_1k * max(tokens, 1) / 1000,
                            "optimizer",
                        )
                    except Exception as ct_err:
                        logger.debug(f"Cost tracking failed: {ct_err}")
                    suggestions = self.parse_suggestions(raw)
                    return {
                        "status": "ok",
                        "suggestions": suggestions,
                        "analysis": analysis,
                        "ai_provider": f"claude/{model}",
                        "raw_response": raw,
                    }
                except Exception as e:
                    logger.warning(f"Claude AI suggest failed: {e}")

        # --- Fallback: Math-based suggestions ---
        return {
            "status": "ok",
            **self.get_suggestions_fallback(analysis),
        }
