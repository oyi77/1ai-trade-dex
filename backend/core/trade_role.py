"""Trade role classification — maker/taker/unknown based on order type."""

_MAKER_TYPES = {"limit", "gtc", "gtd"}
_TAKER_TYPES = {"market", "ioc", "fok"}

def classify_trade_role(order_type: str) -> str:
    """Return 'maker', 'taker', or 'unknown' for a given order type string."""
    order_type_lower = (order_type or "").lower()
    if order_type_lower in _MAKER_TYPES:
        return "maker"
    if order_type_lower in _TAKER_TYPES:
        return "taker"
    return "unknown"
