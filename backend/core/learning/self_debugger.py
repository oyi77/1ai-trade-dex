"""DEPRECATED: Use backend.core.self_debugger instead.

DEPRECATED: Use backend.core.self_debugger instead.
This module will be removed in a future release.


This module will be removed in a future release.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.models.kg_models import Base, DecisionAuditLog


class DiagnosisResult:
    def __init__(
        self,
        error_type: str,
        recoverable: bool,
        suggestion: str,
        context: dict[str, Any] | None = None,
    ):
        self.error_type = error_type
        self.recoverable = recoverable
        self.suggestion = suggestion
        self.context = context or {}


class RecoveryResult:
    def __init__(self, success: bool, action_taken: str, attempts: int = 1):
        self.success = success
        self.action_taken = action_taken
        self.attempts = attempts


class SelfDebugger:
    @property
    def MAX_RECOVERY_ATTEMPTS(self):
        from backend.config import settings

        return settings.SELF_DEBUGGER_MAX_RECOVERY_ATTEMPTS

    def __init__(
        self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"
    ):
        self._recovery_attempts: dict[str, int] = {}
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True

    def close(self):
        if self._owns_session:
            self._session.close()

    def diagnose_error(
        self, error: Exception, context: dict[str, Any] | None = None
    ) -> DiagnosisResult:
        error_type = type(error).__name__
        error_msg = str(error).lower()

        if "404" in error_msg or "not found" in error_msg:
            return DiagnosisResult(
                error_type="api_404",
                recoverable=True,
                suggestion="Retry with alternate endpoint (e.g., /v1/markets → /v2/markets)",
                context=context,
            )
        elif "503" in error_msg or "service unavailable" in error_msg:
            return DiagnosisResult(
                error_type="api_503",
                recoverable=True,
                suggestion="Exponential backoff with circuit breaker reset",
                context=context,
            )
        elif "timeout" in error_msg or "timed out" in error_msg:
            return DiagnosisResult(
                error_type="timeout",
                recoverable=True,
                suggestion="Retry with reduced timeout, skip non-critical calls",
                context=context,
            )
        elif "429" in error_msg or "rate limit" in error_msg:
            return DiagnosisResult(
                error_type="rate_limit",
                recoverable=True,
                suggestion="Exponential backoff with jitter",
                context=context,
            )
        elif "401" in error_msg or "unauthorized" in error_msg or "auth" in error_msg:
            return DiagnosisResult(
                error_type="auth_failure",
                recoverable=True,
                suggestion="Refresh token and retry",
                context=context,
            )
        elif "malformed" in error_msg or "parse" in error_msg or "json" in error_msg:
            return DiagnosisResult(
                error_type="malformed_response",
                recoverable=True,
                suggestion="Try alternate parser (JSON vs Python repr)",
                context=context,
            )
        else:
            return DiagnosisResult(
                error_type=error_type,
                recoverable=False,
                suggestion="Unknown error, escalate to human",
                context=context,
            )

    def attempt_recovery(self, diagnosis: DiagnosisResult) -> RecoveryResult:
        error_key = diagnosis.error_type
        self._recovery_attempts[error_key] = (
            self._recovery_attempts.get(error_key, 0) + 1
        )
        attempts = self._recovery_attempts[error_key]

        if attempts > self.MAX_RECOVERY_ATTEMPTS:
            self._report_escalation(diagnosis, "Max recovery attempts exceeded")
            return RecoveryResult(
                success=False, action_taken="escalated_to_human", attempts=attempts
            )

        if not diagnosis.recoverable:
            self._report_escalation(diagnosis, "Unrecoverable error")
            return RecoveryResult(
                success=False, action_taken="escalated_to_human", attempts=attempts
            )

        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="SelfDebugger",
            decision_type="recovery_attempt",
            input_data={"error_type": diagnosis.error_type, "attempt": attempts},
            output_data={"action": diagnosis.suggestion, "success": True},
            confidence=0.8,
            reasoning=f"Recovery attempt {attempts} for {diagnosis.error_type}",
        )
        self._session.add(audit)
        self._session.commit()

        return RecoveryResult(
            success=True, action_taken=diagnosis.suggestion, attempts=attempts
        )

    def report_unrecoverable(self, error: Exception, diagnosis: DiagnosisResult):
        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="SelfDebugger",
            decision_type="unrecoverable_error",
            input_data={"error_type": diagnosis.error_type, "error_msg": str(error)},
            output_data={"escalated": True},
            confidence=1.0,
            reasoning=f"Unrecoverable error reported: {diagnosis.suggestion}",
        )
        self._session.add(audit)
        self._session.commit()

    def _report_escalation(self, diagnosis: DiagnosisResult, reason: str):
        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="SelfDebugger",
            decision_type="escalation",
            input_data={"error_type": diagnosis.error_type, "reason": reason},
            output_data={"escalated_to": "human"},
            confidence=1.0,
            reasoning=f"Escalated to human: {reason}",
        )
        self._session.add(audit)
        self._session.commit()
