"""AI providers mixin — web search, AI/LLM config, multi-agent debate."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AIProvidersMixin:
    """AI provider settings: web search, AI/LLM config, LLM routing, multi-agent debate."""

    # Web search settings
    WEBSEARCH_ENABLED: bool = True
    WEBSEARCH_PROVIDER: str = "tavily"
    WEBSEARCH_FALLBACK_PROVIDER: str = "duckduckgo"
    WEBSEARCH_MAX_RESULTS: int = 5
    WEBSEARCH_TIMEOUT_SECONDS: float = 15.0
    WEBSEARCH_MIN_CONFIDENCE: float = 0.5

    # API keys
    TAVILY_API_KEY: Optional[str] = None
    EXA_API_KEY: Optional[str] = None
    SERPER_API_KEY: Optional[str] = None
    CRW_API_KEY: Optional[str] = None
    MIROFISH_API_KEY: Optional[str] = None

    # AI / LLM configuration
    AI_ENABLED: bool = True
    AI_PROVIDER: str = "groq"
    AI_DAILY_BUDGET_USD: float = 1.0
    AI_LOG_ALL_CALLS: bool = True
    AI_MODEL: Optional[str] = None
    AI_API_KEY: Optional[str] = None
    AI_BASE_URL: Optional[str] = None
    AI_SIGNAL_WEIGHT: float = 0.30

    # LLM routing
    LLM_DEFAULT_PROVIDER: str = "groq"
    LLM_DEBATE_PROVIDER: str = "groq"
    LLM_JUDGE_PROVIDER: str = "groq"
    ANTHROPIC_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: str = ""
    LLM_OPENAI_API_KEY: Optional[str] = None
    LLM_OPENAI_BASE_URL: Optional[str] = None
    LLM_OPENAI_MODEL: str = "auto/best-chat"

    # LLM models
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
    GEMINI_MODEL: str = "gemini-1.5-pro"

    # Multi-agent debate
    MULTI_AGENT_DEBATE_ENABLED: bool = True
    DEBATE_TIMEOUT_SECONDS: float = 10.0
    BULL_AGENT_ENABLED: bool = True
    BEAR_AGENT_ENABLED: bool = True
    RESEARCH_AGENT_ENABLED: bool = True
