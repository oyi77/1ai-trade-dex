"""Sensitive data redaction for log output."""


def redact_sensitive(value: str, visible_chars: int = 4) -> str:
    """Redact sensitive strings, showing only first/last N characters.

    Args:
        value: The string to redact.
        visible_chars: Number of characters to show at start and end (default: 4).

    Returns:
        Redacted string in format "xxxx...xxxx" or "***" for short strings.

    Examples:
        >>> redact_sensitive("sk-1234567890abcdef")
        'sk-1...cdef'
        >>> redact_sensitive("short")
        '***'
        >>> redact_sensitive("0x1234567890abcdef1234567890abcdef12345678")
        '0x12...5678'
    """
    if not isinstance(value, str):
        value = str(value)

    # If string is too short, redact completely
    if len(value) <= visible_chars * 2 + 3:
        return "***"

    return f"{value[:visible_chars]}...{value[-visible_chars:]}"
