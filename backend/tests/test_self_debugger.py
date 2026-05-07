
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.self_debugger import (
    SelfDebugger,
    DiagnosisResult,
    RecoveryResult,
)
from backend.models.kg_models import Base, DecisionAuditLog


def make_debugger_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    debugger = SelfDebugger(session=session)
    return debugger, session, engine


class TestSelfDebuggerDiagnose:
    def test_diagnose_404_error(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("API 404: Not Found")
        result = debugger.diagnose_error(error)
        assert result.error_type == "api_404"
        assert result.recoverable is True
        assert "alternate endpoint" in result.suggestion

    def test_diagnose_503_error(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("503 Service Unavailable")
        result = debugger.diagnose_error(error)
        assert result.error_type == "api_503"
        assert result.recoverable is True
        assert "backoff" in result.suggestion.lower() or "circuit" in result.suggestion.lower()

    def test_diagnose_timeout(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("Request timed out after 30s")
        result = debugger.diagnose_error(error)
        assert result.error_type == "timeout"
        assert result.recoverable is True
        assert "retry" in result.suggestion.lower() or "reduced" in result.suggestion.lower()

    def test_diagnose_rate_limit(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("429 Rate limit exceeded")
        result = debugger.diagnose_error(error)
        assert result.error_type == "rate_limit"
        assert result.recoverable is True
        assert "backoff" in result.suggestion.lower() or "jitter" in result.suggestion.lower()

    def test_diagnose_auth_failure(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("401 Unauthorized: Invalid token")
        result = debugger.diagnose_error(error)
        assert result.error_type == "auth_failure"
        assert result.recoverable is True
        assert "refresh" in result.suggestion.lower() or "token" in result.suggestion.lower()

    def test_diagnose_malformed_response(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("Failed to parse JSON response")
        result = debugger.diagnose_error(error)
        assert result.error_type == "malformed_response"
        assert result.recoverable is True
        assert "parser" in result.suggestion.lower() or "alternate" in result.suggestion.lower()

    def test_diagnose_unknown_error(self):
        debugger, _, _ = make_debugger_session()
        error = Exception("Something weird happened")
        result = debugger.diagnose_error(error)
        assert result.recoverable is False
        assert "escalate" in result.suggestion.lower() or "human" in result.suggestion.lower()


class TestSelfDebuggerRecovery:
    def test_recovery_succeeds_for_recoverable(self):
        debugger, _, _ = make_debugger_session()
        diagnosis = DiagnosisResult(
            error_type="api_404",
            recoverable=True,
            suggestion="Retry with alternate endpoint",
        )
        result = debugger.attempt_recovery(diagnosis)
        assert result.success is True
        assert result.attempts == 1

    def test_recovery_escalates_after_max_attempts(self):
        debugger, _, _ = make_debugger_session()
        diagnosis = DiagnosisResult(
            error_type="api_404",
            recoverable=True,
            suggestion="Retry",
        )
        _result1 = debugger.attempt_recovery(diagnosis)
        _result2 = debugger.attempt_recovery(diagnosis)
        _result3 = debugger.attempt_recovery(diagnosis)
        result4 = debugger.attempt_recovery(diagnosis)
        assert result4.success is False
        assert result4.action_taken == "escalated_to_human"
        assert result4.attempts == 4

    def test_recovery_escalates_unrecoverable(self):
        debugger, _, _ = make_debugger_session()
        diagnosis = DiagnosisResult(
            error_type="unknown",
            recoverable=False,
            suggestion="Escalate to human",
        )
        result = debugger.attempt_recovery(diagnosis)
        assert result.success is False
        assert result.action_taken == "escalated_to_human"

    def test_recovery_creates_audit_log(self):
        debugger, session, _ = make_debugger_session()
        diagnosis = DiagnosisResult(
            error_type="timeout",
            recoverable=True,
            suggestion="Retry with reduced timeout",
        )
        debugger.attempt_recovery(diagnosis)
        audit = session.query(DecisionAuditLog).filter_by(decision_type="recovery_attempt").first()
        assert audit is not None
        assert "timeout" in str(audit.input_data)


class TestSelfDebuggerReportUnrecoverable:
    def test_report_creates_audit_entry(self):
        debugger, session, _ = make_debugger_session()
        error = Exception("Critical failure")
        diagnosis = DiagnosisResult(
            error_type="critical",
            recoverable=False,
            suggestion="Call human",
        )
        debugger.report_unrecoverable(error, diagnosis)
        audit = session.query(DecisionAuditLog).filter_by(decision_type="unrecoverable_error").first()
        assert audit is not None
        assert "Critical failure" in str(audit.input_data) or "critical" in str(audit.input_data)


class TestDiagnosisResult:
    def test_creation(self):
        d = DiagnosisResult(
            error_type="test",
            recoverable=True,
            suggestion="Do something",
            context={"key": "val"},
        )
        assert d.error_type == "test"
        assert d.recoverable is True
        assert d.suggestion == "Do something"
        assert d.context["key"] == "val"


class TestRecoveryResult:
    def test_creation(self):
        r = RecoveryResult(success=True, action_taken="retried", attempts=2)
        assert r.success is True
        assert r.action_taken == "retried"
        assert r.attempts == 2
