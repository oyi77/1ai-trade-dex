"""AI market analyzer with multi-provider routing for prediction markets."""

import json
import re
import time
from dataclasses import dataclass
from typing import Optional

from backend.ai.logger import get_ai_logger

from backend.ai.llm_router import LLMRouter as _LLMRouter

_router: _LLMRouter | None = None


def _get_router() -> _LLMRouter:
    global _router
    if _router is None:
        _router = _LLMRouter()
    return _router


from loguru import logger
@dataclass
class AIAnalysis:
    probability: float
    confidence: float
    reasoning: str
    provider: str
    cost_usd: float


def _format_research_context(research_items: list) -> str:
    """Format ResearchItem list into an LLM prompt section (max 5 items, 200-char snippets)."""
    if not research_items:
        return ""
    lines = []
    for item in research_items[:5]:
        score = getattr(item, "relevance_score", 0.0)
        title = getattr(item, "title", "")
        content = getattr(item, "content", "")
        source = getattr(item, "source", "")
        snippet = content[:200].strip()
        if len(content) > 200:
            snippet += "..."
        lines.append(f"- [{score:.2f}] {title} ({source}): {snippet}")
    return "\n".join(lines)


def _build_prompt(
    question: str,
    current_price: float,
    volume: float,
    category: str = "",
    context: str = "",
    research_context: str = "",
) -> str:
    prompt = f"""You are a prediction market analyst evaluating whether a market is mispriced.

TASK: Estimate the TRUE probability this event resolves YES based on available facts.

CRITICAL RULES:
1. Think about the ACTUAL LIKELIHOOD of the event, not what the market says.
2. If you genuinely believe the market is correct, say so — return the market price.
3. If you have factual evidence the market is WRONG, give your honest estimate.
4. DO NOT anchor to the market price. The market CAN be wrong, especially on:
   - Events where new information hasn't been priced in yet
   - Low-volume markets with thin liquidity
   - Events with clear factual answers (e.g. "Has X already happened?")
   - Time-bound events near their deadline
5. For sports/games: the market is usually right. Return the market price unless you have strong reason not to.
6. Your CONFIDENCE should reflect how certain you are in YOUR estimate:
   - 0.9+: You have near-certain factual evidence
   - 0.7-0.9: Strong evidence supporting your view
   - 0.5-0.7: Moderate evidence, some uncertainty
   - Below 0.5: Low confidence, mostly guessing — RETURN THE MARKET PRICE INSTEAD

QUESTION: {question}
CURRENT YES PRICE: {current_price:.4f}
24H VOLUME: ${volume:,.0f}"""
    if category:
        prompt += f"\nCATEGORY: {category}"
    if context:
        prompt += f"\nCONTEXT: {context}"
    if research_context:
        prompt += f"\n\nRESEARCH CONTEXT (recent relevant news/facts — use these to inform your estimate):\n{research_context}"
    prompt += """

Respond with EXACTLY these three lines:
PROBABILITY: <your honest estimate, 0.01 to 0.99>
CONFIDENCE: <how sure you are in YOUR estimate, 0.0 to 1.0>
REASONING: <one sentence explaining WHY you agree or disagree with the market>"""
    return prompt


def _extract_number(text: str, keywords: list[str]) -> Optional[float]:
    """Extract a float value associated with any of the given keywords.

    Handles formats like:
      PROBABILITY: 0.35
      Probability = 0.35
      Probability ≈ 0.35
      probability is 0.35
      **Probability**: 0.35
      - Probability: 0.35
      prob: 0.35
    """
    for kw in keywords:
        # Pattern: keyword followed by separator then number
        pattern = (
            rf"(?:\*{{0,2}}){kw}(?:\*{{0,2}})\s*[:=≈~\-–—is]\s*\*{{0,2}}\s*(-?[\d.]+)"
        )
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return max(0.0, min(1.0, float(match.group(1))))
            except ValueError:
                continue
    return None


def _parse_ai_response(response: str) -> tuple[float, float, str]:
    """Parse PROBABILITY/CONFIDENCE/REASONING from an LLM response.

    Tries in order:
    1. JSON object with probability/confidence keys
    2. Flexible keyword extraction (handles many LLM output formats)
    3. Fallback defaults
    """
    # Strategy 1: JSON object
    start = response.find("{")
    if start != -1:
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(response, start)
            prob = float(
                data.get(
                    "probability", data.get("prob", data.get("true_probability", -1))
                )
            )
            conf = float(data.get("confidence", data.get("conf", -1)))
            reasoning = str(
                data.get(
                    "reasoning", data.get("reason", data.get("explanation", response))
                )
            )
            if prob >= 0:
                prob = max(0.0, min(1.0, prob))
                conf = max(0.0, min(1.0, conf)) if conf >= 0 else 0.5
                return (prob, conf, reasoning)
        except (ValueError, KeyError, TypeError):
            pass

    # Strategy 2: Flexible keyword extraction
    prob = _extract_number(
        response,
        [
            "probability",
            "prob",
            "true_probability",
            "true probability",
            "estimated probability",
        ],
    )
    conf = _extract_number(
        response, ["confidence", "conf", "confidence level", "certainty"]
    )

    reasoning = ""
    reasoning_match = re.search(
        r"REASONING:\s*(.+)", response, re.IGNORECASE | re.DOTALL
    )
    if reasoning_match:
        reasoning = reasoning_match.group(1).strip()
        # Trim at next keyword if present
        next_kw = re.search(
            r"\n\s*(?:PROBABILITY|CONFIDENCE):", reasoning, re.IGNORECASE
        )
        if next_kw:
            reasoning = reasoning[: next_kw.start()].strip()

    if prob is not None:
        # If we found probability but not confidence, assume moderate confidence
        if conf is None:
            conf = 0.5
        return (prob, conf, reasoning or response[:500])

    # Strategy 3: REMOVED — blind decimal fallback was producing unreliable
    # probabilities (picking arbitrary numbers from reasoning text).
    # Better to return a clear failure signal so callers can skip.

    return (0.5, 0.0, response)


async def _call_groq(prompt: str) -> Optional[str]:
    start_time = time.time()
    try:
        from backend.config import settings

        router = _get_router()
        system = (
            "You are a prediction market analyst. "
            "Estimate the TRUE probability based on facts, not the market price. "
            "If you have strong factual evidence the market is wrong, give your honest estimate. "
            "If you are unsure, return the market price with low confidence. "
            "Always respond with EXACTLY three lines:\n"
            "PROBABILITY: <number>\nCONFIDENCE: <number>\nREASONING: <one sentence>\n"
            "Never include any other text."
        )
        result = await router.complete(prompt, role="default", system=system)
        latency_ms = (time.time() - start_time) * 1000

        ai_logger = get_ai_logger()
        ai_logger.log_call(
            provider="groq",
            model=settings.GROQ_MODEL,
            prompt=prompt,
            response=result or "",
            latency_ms=latency_ms,
            tokens_used=0,
            call_type="market_analysis",
            success=bool(result),
        )

        return result or None

    except Exception as e:
        logger.error(f"Groq market analysis failed: {e}")
        latency_ms = (time.time() - start_time) * 1000
        try:
            from backend.config import settings

            ai_logger = get_ai_logger()
            ai_logger.log_call(
                provider="groq",
                model=settings.GROQ_MODEL,
                prompt=prompt,
                response="",
                latency_ms=latency_ms,
                tokens_used=0,
                call_type="market_analysis",
                success=False,
                error=str(e),
            )
        except Exception as log_err:
            logger.debug(f"Failed to log Groq error to database: {log_err}")
        return None


async def _call_claude(prompt: str) -> Optional[str]:
    start_time = time.time()
    try:
        from backend.config import settings

        router = _get_router()
        model = getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

        if "claude" not in router.providers:
            logger.warning("ANTHROPIC_API_KEY not configured")
            return None

        result = await router.complete(prompt, role="claude_escalation")
        latency_ms = (time.time() - start_time) * 1000

        ai_logger = get_ai_logger()
        ai_logger.log_call(
            provider="claude",
            model=model,
            prompt=prompt,
            response=result or "",
            latency_ms=latency_ms,
            tokens_used=0,
            call_type="market_analysis",
            success=bool(result),
        )

        return result or None

    except Exception as e:
        logger.error(f"Claude market analysis failed: {e}")
        latency_ms = (time.time() - start_time) * 1000
        try:
            from backend.config import settings

            model = getattr(settings, "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
            ai_logger = get_ai_logger()
            ai_logger.log_call(
                provider="claude",
                model=model,
                prompt=prompt,
                response="",
                latency_ms=latency_ms,
                tokens_used=0,
                call_type="market_analysis",
                success=False,
                error=str(e),
            )
        except Exception as log_err:
            logger.debug(f"Failed to log Claude error to database: {log_err}")
        return None


async def check_ai_budget() -> dict:
    """Return current AI spend vs daily budget."""
    from backend.config import settings

    ai_logger = get_ai_logger()
    stats = ai_logger.get_daily_stats()
    spent = stats.get("total_cost_usd", 0.0)
    limit = settings.AI_DAILY_BUDGET_USD
    remaining = max(0.0, limit - spent)

    return {
        "spent_today": spent,
        "limit": limit,
        "remaining": remaining,
        "can_call": spent < limit,
    }


async def analyze_market(
    question: str,
    current_price: float,
    volume: float,
    category: str = "",
    context: str = "",
    research_items: list | None = None,
) -> Optional[AIAnalysis]:
    """Analyze a market: screen with Groq, escalate to Claude if edge > 5%."""
    budget = await check_ai_budget()
    if not budget["can_call"]:
        logger.warning(
            f"AI daily budget exceeded (${budget['spent_today']:.4f} / ${budget['limit']:.2f})"
        )
        return None

    research_text = ""
    if research_items is None:
        try:
            from backend.research.storage import ResearchStorage

            storage = ResearchStorage()
            fetched = await storage.get_for_market(question, limit=5)
            research_text = _format_research_context(fetched)
        except Exception as e:
            logger.debug(
                f"[market_analyzer.analyze_market] {type(e).__name__}: research fetch failed: {e}"
            )
    else:
        research_text = _format_research_context(research_items)

    prompt = _build_prompt(
        question,
        current_price,
        volume,
        category,
        context,
        research_context=research_text,
    )

    groq_response = await _call_groq(prompt)
    if groq_response is None:
        return None

    groq_prob, groq_conf, groq_reasoning = _parse_ai_response(groq_response)
    if groq_conf == 0.0 and groq_prob == 0.5:
        logger.warning(
            f"Failed to parse Groq response (first 200 chars): {groq_response[:200]}"
        )
        return None

    groq_edge = abs(groq_prob - current_price)

    if groq_edge <= 0.05:
        ai_logger = get_ai_logger()
        daily_stats = ai_logger.get_daily_stats()
        cost = daily_stats.get("total_cost_usd", 0.0)
        return AIAnalysis(
            probability=groq_prob,
            confidence=groq_conf,
            reasoning=groq_reasoning,
            provider="groq",
            cost_usd=cost,
        )

    budget = await check_ai_budget()
    if not budget["can_call"]:
        logger.warning(
            "Budget exhausted before Claude escalation, returning Groq result"
        )
        return AIAnalysis(
            probability=groq_prob,
            confidence=groq_conf,
            reasoning=groq_reasoning,
            provider="groq",
            cost_usd=budget["spent_today"],
        )

    claude_response = await _call_claude(prompt)
    if claude_response is None:
        return AIAnalysis(
            probability=groq_prob,
            confidence=groq_conf,
            reasoning=groq_reasoning,
            provider="groq",
            cost_usd=budget["spent_today"],
        )

    claude_prob, claude_conf, claude_reasoning = _parse_ai_response(claude_response)
    if claude_conf == 0.0 and claude_prob == 0.5:
        return AIAnalysis(
            probability=groq_prob,
            confidence=groq_conf,
            reasoning=groq_reasoning,
            provider="groq",
            cost_usd=budget["spent_today"],
        )

    final_budget = await check_ai_budget()
    return AIAnalysis(
        probability=claude_prob,
        confidence=claude_conf,
        reasoning=claude_reasoning,
        provider="claude",
        cost_usd=final_budget["spent_today"],
    )
