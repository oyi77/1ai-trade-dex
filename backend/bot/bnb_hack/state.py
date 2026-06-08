from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class Position:
    token: str
    entry_time: datetime
    entry_price: float
    amount_token: float
    amount_usdc: float
    take_profit: float
    stop_loss: float


@dataclass
class BotState:
    positions: Dict[str, Position] = field(default_factory=dict)
    total_pnl_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0
    in_cooldown: bool = False
    cooldown_until: Optional[datetime] = None
