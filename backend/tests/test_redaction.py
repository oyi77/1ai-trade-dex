"""Minimal tests for backend.utils.redaction."""

from backend.utils.redaction import redact_sensitive


class TestRedactSensitive:
    def test_typical_sensitive_values(self):
        """Strings long enough to show first/last N chars get ellipsis format."""
        # API key-like
        result = redact_sensitive("sk-1234567890abcdef")
        assert result == "sk-1...cdef"

        # Wallet address-like
        result = redact_sensitive("0x1234567890abcdef1234567890abcdef12345678")
        assert result == "0x12...5678"

    def test_short_string_fully_redacted(self):
        """Strings <= visible_chars*2+3 (11 for default=4) return '***'."""
        assert redact_sensitive("short") == "***"
        assert redact_sensitive("12345678901") == "***"  # 11 chars = 4*2+3

    def test_non_string_input_cast(self):
        """Non-string values are cast to str before redaction."""
        # Large enough number to not trigger the "***" short-string path
        result = redact_sensitive(1234567890123456)
        assert result == "1234...3456"
