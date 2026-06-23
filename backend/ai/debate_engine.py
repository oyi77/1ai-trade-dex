"""
Self-Debate Engine (Bull/Bear/Judge) — RA-CR Protocol.

Implements a multi-agent debate for prediction market analysis:
  1. Bull agent argues FOR the market resolving YES (higher probability)
  2. Bear agent argues AGAINST (lower probability)
  3. They debate for 1-2 rounds, responding to each other's arguments
  4. Judge agent synthesizes both sides into a final consensus

Cost routing via LLMRouter:
  - Bull/Bear: cheap model (role="debate_agent" → Groq by default)
  - Judge: smart model (role="judge" → Claude when available, Groq fallback)

References:
  - RA-CR (Retrieval-Augmented Conversational Reasoning) protocol
  - Multi-agent debate for improved LLM factuality
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from backend.ai.llm_router import LLMRouter as _LLMRouter
from backend.ai.probability_utils import clamp_probability

from loguru import logger
import random

# --- Configuration ---
MAX_DEBATE_ROUNDS = 2
MIN_DEBATE_ROUNDS = 1
DEFAULT_MARKET_PRICE = 0.5

# Stance labels
BULL = "bull"
BEAR = "bear"
JUDGE = "judge"

_router: _LLMRouter | None = None


def _get_router() -> _LLMRouter:
    global _router
    if _router is None:
        _router = _LLMRouter()
    return _router


def reset_router() -> None:
    """Reset the cached router (useful for testing)."""
    global _router
    _router = None


# --- Data Classes ---


@dataclass
class DebateArgument:
    """A single argument from a debate agent."""

    stance: str
    round_num: int
    probability: float
    confidence: float
    reasoning: str
    raw_response: str = ""


@dataclass
class SignalVote:
    """A signal's vote in the debate (advisory only)."""

    source: str
    prediction: float
    confidence: float
    reasoning: str
    weight: float = 1.0


@dataclass
class DebateResult:
    """Final result of the Bull/Bear/Judge debate."""

    consensus_probability: float
    confidence: float
    reasoning: str
    bull_arguments: list[DebateArgument] = field(default_factory=list)
    bear_arguments: list[DebateArgument] = field(default_factory=list)
    judge_raw: str = ""
    rounds_completed: int = 0
    latency_ms: float = 0.0
    market_question: str = ""
    market_price: float = 0.0
    data_sources: list[str] = field(default_factory=list)
    signal_votes: list[SignalVote] = field(default_factory=list)
    # Calibration fields (populated by ProbabilityCalibrator after debate)
    calibrated_probability: float | None = None
    brier_score: float | None = None

    def to_transcript_dict(self) -> dict:
        """Serialize the full debate transcript to a JSON-serializable dict.

        Returns a dict with bull/bear arguments per round, judge synthesis,
        metadata, and data sources — suitable for storing in DecisionLog.signal_data.
        """

        def _arg_to_dict(arg: DebateArgument) -> dict:
            return {
                "stance": arg.stance,
                "round": arg.round_num,
                "probability": arg.probability,
                "confidence": arg.confidence,
                "reasoning": arg.reasoning,
                "raw_response": arg.raw_response,
            }

        def _signal_to_dict(sig: SignalVote) -> dict:
            return {
                "source": sig.source,
                "prediction": sig.prediction,
                "confidence": sig.confidence,
                "reasoning": sig.reasoning,
                "weight": sig.weight,
            }

        return {
            "debate_transcript": {
                "bull_arguments": [_arg_to_dict(a) for a in self.bull_arguments],
                "bear_arguments": [_arg_to_dict(a) for a in self.bear_arguments],
                "judge": {
                    "reasoning": self.reasoning,
                    "raw_response": self.judge_raw,
                    "consensus_probability": self.consensus_probability,
                    "calibrated_probability": self.calibrated_probability,
                    "brier_score": self.brier_score,
                    "confidence": self.confidence,
                },
                "rounds_completed": self.rounds_completed,
                "latency_ms": self.latency_ms,
                "signal_votes": [_signal_to_dict(s) for s in self.signal_votes],
            },
            "market_question": self.market_question,
            "market_price": self.market_price,
            "data_sources": self.data_sources,
        }


# --- Prompt Builders ---


def _build_bull_system() -> str:
    return (
        "You are the BULL advocate in a prediction market debate. "
        "Your job is to argue FOR the event resolving YES — find every reason "
        "the true probability should be HIGHER than the current market price. "
        "Be specific, cite evidence, and quantify your reasoning. "
        "You may be wrong, but argue your best case.\n\n"
        'Respond ONLY with JSON: {"probability": 0.XX, "confidence": 0.XX, "reasoning": "your argument"}'
    )


def _build_bear_system() -> str:
    return (
        "You are the BEAR advocate in a prediction market debate. "
        "Your job is to argue AGAINST the event resolving YES — find every reason "
        "the true probability should be LOWER than the current market price. "
        "Be specific, cite evidence, and quantify your reasoning. "
        "You may be wrong, but argue your best case.\n\n"
        'Respond ONLY with JSON: {"probability": 0.XX, "confidence": 0.XX, "reasoning": "your argument"}'
    )


def _build_judge_system() -> str:
    return (
        "You are the JUDGE in a prediction market debate. "
        "You have read arguments from both a BULL (argues YES) and a BEAR (argues NO). "
        "Your job is to synthesize both perspectives into a single, well-calibrated "
        "probability estimate. Weigh the strength of evidence on each side. "
        "Do NOT simply average — give more weight to stronger arguments.\n\n"
        'Respond ONLY with JSON: {"probability": 0.XX, "confidence": 0.XX, "reasoning": "synthesis"}'
    )


def _build_opening_prompt(
    question: str,
    market_price: float,
    volume: float,
    category: str,
    context: str,
    stance: str,
) -> str:
    """Build the opening prompt for Bull or Bear."""
    direction = (
        "YES (higher probability)" if stance == BULL else "NO (lower probability)"
    )
    prompt = (
        f"MARKET QUESTION: {question}\n"
        f"CURRENT YES PRICE: {market_price:.4f}\n"
        f"24H VOLUME: ${volume:,.0f}\n"
    )
    if category:
        prompt += f"CATEGORY: {category}\n"
    if context:
        prompt += f"CONTEXT: {context}\n"
    prompt += (
        f"\nArgue that this market should resolve {direction}. "
        f"What evidence supports your case?"
    )
    return prompt


def _build_rebuttal_prompt(
    question: str,
    market_price: float,
    stance: str,
    opponent_reasoning: str,
    round_num: int,
) -> str:
    """Build a rebuttal prompt responding to the opponent's argument."""
    opponent = "BEAR" if stance == BULL else "BULL"
    direction = (
        "YES (higher probability)" if stance == BULL else "NO (lower probability)"
    )
    return (
        f"MARKET QUESTION: {question}\n"
        f"CURRENT YES PRICE: {market_price:.4f}\n\n"
        f"Round {round_num}: The {opponent} argued:\n"
        f'"{opponent_reasoning}"\n\n'
        f"Counter their argument. Defend your position that the market "
        f"should resolve {direction}. Address their specific points and "
        f"provide additional evidence for your side."
    )


def _build_judge_prompt(
    question: str,
    market_price: float,
    volume: float,
    category: str,
    context: str,
    bull_args: list[DebateArgument],
    bear_args: list[DebateArgument],
) -> str:
    """Build the final Judge prompt with full debate transcript."""
    prompt = (
        f"MARKET QUESTION: {question}\n"
        f"CURRENT YES PRICE: {market_price:.4f}\n"
        f"24H VOLUME: ${volume:,.0f}\n"
    )
    if category:
        prompt += f"CATEGORY: {category}\n"
    if context:
        prompt += f"CONTEXT: {context}\n"

    prompt += "\n--- DEBATE TRANSCRIPT ---\n"

    max_rounds = max(
        (a.round_num for a in bull_args + bear_args),
        default=0,
    )

    for r in range(1, max_rounds + 1):
        prompt += f"\n=== ROUND {r} ===\n"
        round_args = []
        for arg in bull_args:
            if arg.round_num == r:
                round_args.append(("BULL", arg))
        for arg in bear_args:
            if arg.round_num == r:
                round_args.append(("BEAR", arg))
        # Randomize order to avoid anchoring bias
        random.shuffle(round_args)
        for label, arg in round_args:
            prompt += (
                f"\n{label} (prob={arg.probability:.2f}, conf={arg.confidence:.2f}):\n"
                f"{arg.reasoning}\n"
            )

    prompt += (
        "\n--- END TRANSCRIPT ---\n\n"
        "Synthesize both sides. Which arguments are strongest? "
        "What is the TRUE probability this event resolves YES? "
        "Do NOT simply average the two positions."
    )
    return prompt


# --- Response Parsing ---


def _extract_number(text: str, keywords: list[str]) -> float | None:
    """Extract a float value associated with any keyword."""
    for kw in keywords:
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


def _parse_agent_response(response: str) -> tuple[float, float, str] | None:
    """Parse PROBABILITY/CONFIDENCE/REASONING from an agent response.

    Tries JSON first, then keyword extraction, then fallback.
    Returns None if all parse strategies fail.
    """
    # Strategy 1: JSON object
    start = response.find("{")
    if start != -1:
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(response, start)
            prob = float(data.get("probability", data.get("prob", -1)))
            conf = float(data.get("confidence", data.get("conf", -1)))
            reasoning = str(data.get("reasoning", data.get("reason", response)))
            if prob >= 0:
                prob = max(0.01, min(0.99, prob))
                conf = max(0.0, min(1.0, conf)) if conf >= 0 else 0.5
                return (prob, conf, reasoning)
        except (ValueError, KeyError, TypeError):
            logger.debug("debate_engine: failed to parse LLM JSON response, falling back to keyword extraction")

    # Strategy 2: Keyword extraction
    prob = _extract_number(
        response,
        ["probability", "prob", "true_probability", "estimated probability"],
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
        next_kw = re.search(
            r"\n\s*(?:PROBABILITY|CONFIDENCE):", reasoning, re.IGNORECASE
        )
        if next_kw:
            reasoning = reasoning[: next_kw.start()].strip()

    if prob is not None:
        if conf is None:
            conf = 0.5
        return (prob, conf, reasoning or response[:500])

    # Strategy 3: Fallback — parse failure, drop the signal
    logger.warning("[debate_engine] Parse failed, dropping signal")
    return None


# --- Core Engine ---


async def _call_agent(
    prompt: str,
    system: str,
    role: str,
) -> str | None:
    """Call an LLM agent via the router."""
    try:
        router = _get_router()
        result = await router.complete(prompt, role=role, system=system)
        if not result:
            return None
        # If response doesn't contain structured data, extract via second call
        if _parse_agent_response(result) is None:
            extract_prompt = (
                f"Extract the probability estimate from this analysis and respond ONLY with JSON:\n"
                f'{{"probability": 0.XX, "confidence": 0.XX, "reasoning": "1 sentence summary"}}\n\n'
                f"Analysis:\n{result[:1000]}"
            )
            extracted = await router.complete(extract_prompt, role=role, max_tokens=150)
            if extracted and _parse_agent_response(extracted) is not None:
                return extracted
        return result
    except Exception as e:
        logger.error(
            f"[debate_engine._call_agent] {type(e).__name__}: "
            f"LLM call failed for role={role}: {e}"
        )
        return None


def update_debate_with_signals(
    debate_result: DebateResult,
    signal_votes: list[SignalVote],
) -> DebateResult:
    """
    Integrate external signal votes into debate result (advisory only).

    Signals participate as advisory votes with equal weight (1.0).
    They do NOT override the debate consensus - they are added to the transcript
    for transparency and logged for audit purposes.

    Args:
        debate_result: Original debate result from run_debate()
        signal_votes: List of external signal votes (e.g., MiroFish)

    Returns:
        Updated DebateResult with signal_votes appended
    """
    if not signal_votes:
        return debate_result

    debate_result.signal_votes = signal_votes

    for sig in signal_votes:
        source_label = sig.source or "unknown"
        logger.info(
            "[debate_engine.update_debate_with_signals] signal=%s pred=%.3f conf=%.2f weight=%.1f",
            source_label,
            sig.prediction,
            sig.confidence,
            sig.weight,
        )

    return debate_result


def _parse_argument(
    response: str | None, stance: str, round_num: int
) -> DebateArgument | None:
    """Parse an agent response into a DebateArgument, or None if unparseable."""
    if not response:
        return None
    parsed = _parse_agent_response(response)
    if parsed is None:
        return None
    prob, conf, reasoning = parsed
    return DebateArgument(
        stance=stance,
        round_num=round_num,
        probability=prob,
        confidence=conf,
        reasoning=reasoning,
        raw_response=response,
    )


async def _run_opening_round(
    question: str, market_price: float, volume: float, category: str, context: str
) -> tuple[list[DebateArgument], list[DebateArgument]] | None:
    """Run Round 1: parallel Bull and Bear opening arguments. Returns None if both fail."""
    bull_prompt = _build_opening_prompt(
        question, market_price, volume, category, context, BULL
    )
    bear_prompt = _build_opening_prompt(
        question, market_price, volume, category, context, BEAR
    )

    bull_response, bear_response = await asyncio.gather(
        _call_agent(bull_prompt, _build_bull_system(), role="debate_agent"),
        _call_agent(bear_prompt, _build_bear_system(), role="debate_agent"),
    )

    if bull_response is None and bear_response is None:
        logger.warning("[debate_engine] Both Bull and Bear agents failed in Round 1")
        return None

    bull_args: list[DebateArgument] = []
    bear_args: list[DebateArgument] = []
    bull_arg = _parse_argument(bull_response, BULL, 1)
    if bull_arg:
        bull_args.append(bull_arg)
    bear_arg = _parse_argument(bear_response, BEAR, 1)
    if bear_arg:
        bear_args.append(bear_arg)
    return bull_args, bear_args


async def _run_rebuttals(
    question: str,
    market_price: float,
    rounds: int,
    bull_args: list[DebateArgument],
    bear_args: list[DebateArgument],
) -> None:
    """Run Round 2+: Bull and Bear rebuttals, appending to existing argument lists."""
    for round_num in range(2, rounds + 1):
        if bear_args:
            prompt = _build_rebuttal_prompt(
                question, market_price, BULL, bear_args[-1].reasoning, round_num
            )
            resp = await _call_agent(prompt, _build_bull_system(), role="debate_agent")
            arg = _parse_argument(resp, BULL, round_num)
            if arg:
                bull_args.append(arg)

        if bull_args:
            prompt = _build_rebuttal_prompt(
                question, market_price, BEAR, bull_args[-1].reasoning, round_num
            )
            resp = await _call_agent(prompt, _build_bear_system(), role="debate_agent")
            arg = _parse_argument(resp, BEAR, round_num)
            if arg:
                bear_args.append(arg)


async def _synthesize_judge(
    question: str,
    market_price: float,
    volume: float,
    category: str,
    context: str,
    bull_args: list[DebateArgument],
    bear_args: list[DebateArgument],
) -> tuple[float, float, str, str]:
    """Run Judge synthesis. Returns (prob, conf, reasoning, raw_response)."""
    judge_prompt = _build_judge_prompt(
        question, market_price, volume, category, context, bull_args, bear_args
    )
    judge_response = await _call_agent(
        judge_prompt, _build_judge_system(), role="judge"
    )

    judge_parsed = _parse_agent_response(judge_response) if judge_response else None
    if judge_parsed is not None:
        prob, conf, reasoning = judge_parsed
        return prob, conf, reasoning, judge_response or ""

    if judge_response:
        logger.warning("[debate_engine] Judge response unparseable, falling back to weighted average")
    else:
        logger.warning("[debate_engine] Judge agent failed, falling back to weighted average")

    all_args = bull_args + bear_args
    if not all_args:
        return 0.5, 0.0, "No arguments available", ""

    total_weight = sum(a.confidence for a in all_args)
    if total_weight > 0:
        prob = sum(a.probability * a.confidence for a in all_args) / total_weight
    else:
        prob = sum(a.probability for a in all_args) / len(all_args)

    reasoning = (
        "Judge unavailable. Consensus derived from weighted average of "
        f"{len(bull_args)} bull and {len(bear_args)} bear arguments."
    )
    return prob, 0.3, reasoning, judge_response or ""


async def run_debate(
    question: str,
    market_price: float,
    volume: float = 0.0,
    category: str = "",
    context: str = "",
    max_rounds: int = MAX_DEBATE_ROUNDS,
    data_sources: list[str] | None = None,
    signal_votes: list[SignalVote] | None = None,
) -> DebateResult | None:
    """Run a Bull/Bear/Judge debate on a prediction market question.

    Protocol (RA-CR):
      1. Bull and Bear each make opening arguments (Round 1)
      2. Each rebuts the other's argument (Round 2, if max_rounds >= 2)
      3. Judge synthesizes the full transcript into a consensus
    """
    start_time = time.time()
    rounds = max(MIN_DEBATE_ROUNDS, min(MAX_DEBATE_ROUNDS, max_rounds))

    opening = await _run_opening_round(question, market_price, volume, category, context)
    if opening is None:
        return None
    bull_args, bear_args = opening

    await _run_rebuttals(question, market_price, rounds, bull_args, bear_args)

    rounds_completed = max(
        (a.round_num for a in bull_args + bear_args), default=0,
    )

    consensus_prob, consensus_conf, consensus_reasoning, judge_raw = (
        await _synthesize_judge(
            question, market_price, volume, category, context, bull_args, bear_args
        )
    )

    consensus_prob = clamp_probability(consensus_prob)
    consensus_conf = max(0.0, min(1.0, consensus_conf))
    latency_ms = (time.time() - start_time) * 1000

    # Calibrate the raw consensus probability using historical outcomes
    calibrated_prob = consensus_prob
    brier_score = None
    try:
        from backend.ai.probability_calibrator import get_calibrator
        from backend.db.utils import get_db_session

        calibrator = get_calibrator()
        with get_db_session() as cal_db:
            calibrated_prob, brier_score = calibrator.calibrate(
                "judge", consensus_prob, cal_db
            )
    except Exception:
        logger.debug("[debate_engine] Calibration skipped (no DB or no data)")

    logger.info(
        "[debate_engine] question=%s price=%.3f consensus=%.3f calibrated=%.3f conf=%.2f "
        "rounds=%d bull=%d bear=%d latency=%.0fms",
        question[:60], market_price, consensus_prob, calibrated_prob, consensus_conf,
        rounds_completed, len(bull_args), len(bear_args), latency_ms,
    )

    return DebateResult(
        consensus_probability=consensus_prob,
        confidence=consensus_conf,
        reasoning=consensus_reasoning,
        bull_arguments=bull_args,
        bear_arguments=bear_args,
        judge_raw=judge_raw,
        rounds_completed=rounds_completed,
        latency_ms=latency_ms,
        market_question=question,
        market_price=market_price,
        data_sources=data_sources or [],
        signal_votes=signal_votes or [],
        calibrated_probability=calibrated_prob,
        brier_score=brier_score,
    )
