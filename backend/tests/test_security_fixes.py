"""Tests for the 6 CRITICAL security vulnerability fixes (E-01 through E-06)."""

import pytest
import time
from fastapi import HTTPException
from backend.config import settings


# ---------------------------------------------------------------------------
# E-01: require_admin() must raise 403 when ADMIN_API_KEY not set
# ---------------------------------------------------------------------------
class TestRequireAdminNoKey:
    def test_raises_403_when_no_admin_key(self):
        from backend.api.auth import require_admin
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = None
            with pytest.raises(HTTPException) as exc_info:
                require_admin(authorization=None)
            assert exc_info.value.status_code == 403
            assert "ADMIN_API_KEY not configured" in exc_info.value.detail
        finally:
            settings.ADMIN_API_KEY = original

    def test_raises_403_when_admin_key_empty(self):
        from backend.api.auth import require_admin
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = ""
            with pytest.raises(HTTPException) as exc_info:
                require_admin(authorization=None)
            assert exc_info.value.status_code == 403
        finally:
            settings.ADMIN_API_KEY = original

    def test_raises_401_when_wrong_bearer_token(self):
        from backend.api.auth import require_admin
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            with pytest.raises(HTTPException) as exc_info:
                require_admin(authorization="Bearer wrong-key")
            assert exc_info.value.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_passes_with_correct_bearer_token(self):
        from backend.api.auth import require_admin
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            result = require_admin(authorization="Bearer secret-key")
            assert result is None
        finally:
            settings.ADMIN_API_KEY = original


# ---------------------------------------------------------------------------
# E-02: authorize_realtime_access() must check auth tokens
# ---------------------------------------------------------------------------
class TestAuthorizeRealtimeAccess:
    def test_rejects_when_no_admin_key_configured(self):
        from backend.api.auth import authorize_realtime_access
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = None
            assert authorize_realtime_access(token=None, admin_session=None) is False
        finally:
            settings.ADMIN_API_KEY = original

    def test_rejects_when_no_credentials(self):
        from backend.api.auth import authorize_realtime_access
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            assert authorize_realtime_access(token=None, admin_session=None) is False
        finally:
            settings.ADMIN_API_KEY = original

    def test_accepts_valid_bearer_token(self):
        from backend.api.auth import authorize_realtime_access
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            assert authorize_realtime_access(token="secret-key", admin_session=None) is True
        finally:
            settings.ADMIN_API_KEY = original

    def test_rejects_wrong_bearer_token(self):
        from backend.api.auth import authorize_realtime_access
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            assert authorize_realtime_access(token="wrong-key", admin_session=None) is False
        finally:
            settings.ADMIN_API_KEY = original

    def test_accepts_valid_cookie_session(self):
        from backend.api.auth import authorize_realtime_access, _SESSION_STORE
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            _SESSION_STORE["valid-token"] = {"created_at": time.time(), "csrf": "csrf123"}
            assert authorize_realtime_access(token=None, admin_session="valid-token") is True
        finally:
            _SESSION_STORE.pop("valid-token", None)
            settings.ADMIN_API_KEY = original

    def test_rejects_expired_cookie_session(self):
        from backend.api.auth import authorize_realtime_access, _SESSION_STORE, _SESSION_TTL_SECONDS
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            _SESSION_STORE["expired-token"] = {
                "created_at": time.time() - _SESSION_TTL_SECONDS - 1,
                "csrf": "csrf123",
            }
            assert authorize_realtime_access(token=None, admin_session="expired-token") is False
        finally:
            _SESSION_STORE.pop("expired-token", None)
            settings.ADMIN_API_KEY = original


# ---------------------------------------------------------------------------
# E-03: require_csrf() must reject missing CSRF when cookie present
# ---------------------------------------------------------------------------
class TestRequireCsrf:
    def test_raises_403_when_no_admin_key(self):
        from backend.api.auth import require_csrf
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = None
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(x_csrf_token=None, admin_session=None, authorization=None)
            assert exc_info.value.status_code == 403
        finally:
            settings.ADMIN_API_KEY = original

    def test_passes_with_valid_bearer(self):
        from backend.api.auth import require_csrf
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            result = require_csrf(x_csrf_token=None, admin_session=None, authorization="Bearer secret-key")
            assert result is None
        finally:
            settings.ADMIN_API_KEY = original

    def test_raises_401_when_no_session_no_bearer(self):
        from backend.api.auth import require_csrf
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(x_csrf_token=None, admin_session=None, authorization=None)
            assert exc_info.value.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_raises_403_when_csrf_missing_with_valid_session(self):
        from backend.api.auth import require_csrf, _SESSION_STORE
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            _SESSION_STORE["valid"] = {"created_at": time.time(), "csrf": "expected-csrf"}
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(x_csrf_token=None, admin_session="valid", authorization=None)
            assert exc_info.value.status_code == 403
            assert "CSRF" in exc_info.value.detail
        finally:
            _SESSION_STORE.pop("valid", None)
            settings.ADMIN_API_KEY = original

    def test_raises_403_when_csrf_wrong(self):
        from backend.api.auth import require_csrf, _SESSION_STORE
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            _SESSION_STORE["valid"] = {"created_at": time.time(), "csrf": "expected-csrf"}
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(x_csrf_token="wrong-csrf", admin_session="valid", authorization=None)
            assert exc_info.value.status_code == 403
        finally:
            _SESSION_STORE.pop("valid", None)
            settings.ADMIN_API_KEY = original

    def test_passes_with_valid_csrf(self):
        from backend.api.auth import require_csrf, _SESSION_STORE
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = "secret-key"
            _SESSION_STORE["valid"] = {"created_at": time.time(), "csrf": "expected-csrf"}
            result = require_csrf(x_csrf_token="expected-csrf", admin_session="valid", authorization=None)
            assert result is None
        finally:
            _SESSION_STORE.pop("valid", None)
            settings.ADMIN_API_KEY = original


# ---------------------------------------------------------------------------
# E-04/E-05: Strategy composer validates LLM code through sandbox
# ---------------------------------------------------------------------------
class TestStrategyComposerSandbox:
    def test_sandbox_validator_rejects_dangerous_imports(self):
        from backend.agi.sandbox.sandbox_validator import SandboxValidator
        validator = SandboxValidator()
        code = 'import os\ndef test():\n    return True\n'
        result = validator.validate(code)
        assert result.status == "failed"
        assert "gate1_import_safety" in result.gates_failed

    def test_sandbox_validator_rejects_exec_eval(self):
        from backend.agi.sandbox.sandbox_validator import SandboxValidator
        validator = SandboxValidator()
        code = 'def test():\n    exec("print(1)")\n    return True\n'
        result = validator.validate(code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed

    def test_sandbox_validator_rejects_subprocess(self):
        from backend.agi.sandbox.sandbox_validator import SandboxValidator
        validator = SandboxValidator()
        code = 'import subprocess\ndef test():\n    return True\n'
        result = validator.validate(code)
        assert result.status == "failed"
        assert "gate1_import_safety" in result.gates_failed

    def test_sandbox_validator_passes_safe_code(self):
        from backend.agi.sandbox.sandbox_validator import SandboxValidator
        validator = SandboxValidator()
        code = 'import json\ndef test():\n    return {"ok": True}\n'
        result = validator.validate(code)
        assert result.status == "passed"


# ---------------------------------------------------------------------------
# E-06: RestrictedUnpickler no longer allows pickle/copyreg
# ---------------------------------------------------------------------------
class TestRestrictedUnpickler:
    def test_pickle_not_in_allowed_prefixes(self):
        """Verify pickle and copyreg removed from ALLOWED_PREFIXES."""
        import backend.ai.model_integrity as mi
        source = open(mi.__file__).read()
        allowed_section = source.split("ALLOWED_PREFIXES")[1].split(")")[0]
        assert '"pickle"' not in allowed_section
        assert '"copyreg"' not in allowed_section

    def test_pickle_module_blocked_by_restricted_unpickler(self):
        """Verify the ALLOWED_PREFIXES tuple excludes pickle/copyreg."""
        import inspect
        import backend.ai.model_integrity as mi_mod
        source = inspect.getsource(mi_mod)
        allowed_section = source.split("ALLOWED_PREFIXES")[1].split("find_class")[0]
        assert "pickle" not in allowed_section
        assert "copyreg" not in allowed_section


# ---------------------------------------------------------------------------
# E-01 (extended): require_admin_from_cookie must also deny when no key
# ---------------------------------------------------------------------------
class TestRequireAdminFromCookieNoKey:
    def test_raises_403_when_no_admin_key(self):
        from backend.api.auth import require_admin_from_cookie
        original = settings.ADMIN_API_KEY
        try:
            settings.ADMIN_API_KEY = None
            with pytest.raises(HTTPException) as exc_info:
                require_admin_from_cookie(admin_session=None, x_csrf_token=None, authorization=None)
            assert exc_info.value.status_code == 403
            assert "ADMIN_API_KEY not configured" in exc_info.value.detail
        finally:
            settings.ADMIN_API_KEY = original
