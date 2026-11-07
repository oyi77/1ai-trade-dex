"""Nexus Intelligence signal receiver.

Nexus (1ai-tracker) owns screening and emits only ``SIGNAL`` verdicts; this
module is the trade-dex side of that boundary. It authenticates the caller,
validates the payload before doing any work, and enqueues signals durably.

Execution is deliberately absent: no memecoin DEX adapter exists in this repo
yet — the queue handler stays fail-closed.
"""

import hmac
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.config import settings
from backend.models.database import SessionLocal, JobQueue

logger = logging.getLogger("nexus_router")

SUPPORTED_NETWORKS = {"solana", "ethereum", "bsc", "base"}
MIN_CONFIDENCE = 0.5
NETWORK_ALIASES = {
    "sol": "solana",
    "eth": "ethereum",
    "bnb": "bsc",
}

router = APIRouter(prefix="/nexus", tags=["Nexus Intelligence"])


class NexusSignal(BaseModel):
    model_config = ConfigDict(extra="allow")

    token_address: Optional[str] = Field(default=None)
    network: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None)
    entry_price: Optional[float] = Field(default=None)
    risk_params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: Optional[dict[str, Any]] = Field(default=None)
    deliver: bool = Field(default=False)


def _normalize_network(raw: Any) -> str:
    if not isinstance(raw, str):
        return "solana"
    norm = raw.strip().lower()
    if norm in SUPPORTED_NETWORKS:
        return norm
    return NETWORK_ALIASES.get(norm, norm)


def _coerce_tracker_body(body: dict[str, Any]) -> NexusSignal:
    """Map a tracker SniperPayload wrapper into a canonical NexusSignal."""
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be an object")

    # High-conviction gate: accept tracker's own verdict when supplied.
    decision = body.get("decision")
    if isinstance(decision, dict) and decision.get("status") not in (None, "SIGNAL"):
        raise HTTPException(
            status_code=422,
            detail=f"Tracker verdict is not SIGNAL: {decision.get('status')!r}",
        )

    contract = payload.get("contract") or payload.get("token_address")
    if not contract or len(str(contract)) < 8:
        raise HTTPException(
            status_code=422,
            detail=f"token_address/contract required (got {contract!r})",
        )

    chain = payload.get("chain")
    network = _normalize_network(chain)
    if network not in SUPPORTED_NETWORKS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported network '{chain}' → normalized '{network}'",
        )

    confidence = body.get("confidence", body.get("score", 0.75))
    # High conviction gate: only signals scoring at least 0.75 are persisted.
    if not isinstance(confidence, (int, float)):
        raise HTTPException(status_code=422, detail="confidence must be numeric")
    if confidence < 0.75:
        raise HTTPException(
            status_code=422,
            detail=f"Confidence {confidence} below high-conviction 0.75",
        )
    if confidence < MIN_CONFIDENCE:
        raise HTTPException(
            status_code=422,
            detail=f"Confidence {confidence!r} below floor {MIN_CONFIDENCE}",
        )

    deliver = bool(body.get("deliver", False))

    risk_params: dict[str, Any] = {
        "source": "1ai-tracker.meme/sniper",
        "ticker": payload.get("ticker"),
        "ageMinutes": payload.get("ageMinutes"),
        "security": payload.get("security"),
        "distribution": payload.get("distribution"),
        "momentum": payload.get("momentum"),
    }

    metadata: dict[str, Any] = {
        "source_payload": payload,
        "deliver": deliver,
    }

    return NexusSignal(
        token_address=str(contract),
        network=network,
        confidence=float(confidence),
        entry_price=payload.get("momentum", {}).get("marketCap") if isinstance(payload.get("momentum"), dict) else None,
        risk_params=risk_params,
        metadata=metadata,
    )


def require_nexus_key(
    authorization: str | None = Header(None),
    x_nexus_key: str | None = Header(None, alias="X-Nexus-Key"),
) -> None:
    raw = getattr(settings, "NEXUS_INBOUND_API_KEYS", None)
    if raw is None:
        raw = os.getenv("NEXUS_INBOUND_API_KEYS")
    configured = [key.strip() for key in str(raw or "").split(",") if key.strip()]
    if not configured:
        raise HTTPException(
            status_code=403,
            detail="Nexus inbound access denied — NEXUS_INBOUND_API_KEYS not configured",
        )

    bearer = ""
    if authorization and authorization.startswith("Bearer "):
        bearer = authorization[len("Bearer "):].strip()
    presented = bearer or (x_nexus_key or "").strip()
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — send Authorization: Bearer <nexus key>",
        )
    if not any(hmac.compare_digest(presented, key) for key in configured):
        raise HTTPException(status_code=401, detail="Unauthorized — invalid Nexus key")


def _enqueue_nexus_signal(signal: NexusSignal) -> str:
    payload_dict = {
        "token_address": signal.token_address,
        "network": signal.network,
        "confidence": signal.confidence,
        "entry_price": signal.entry_price,
        "risk_params": signal.risk_params,
        "metadata": signal.metadata,
    }
    idempotency_key = f"nexus:{signal.network}:{signal.token_address}"
    session = SessionLocal()
    try:
        existing = (
            session.query(JobQueue)
            .filter(
                JobQueue.job_type == "nexus_signal",
                JobQueue.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            return str(existing.id)

        job = JobQueue(
            job_type="nexus_signal",
            payload=payload_dict,
            status="pending",
            idempotency_key=idempotency_key,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return str(job.id)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post("/signal", dependencies=[Depends(require_nexus_key)])
async def receive_nexus_signal(request: Request) -> dict[str, Any]:
    """Accept either flat NexusSignal JSON or tracker-style {payload, deliver}."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Tracker-style: has a nested "payload" dict with "contract"
    if "payload" in body and isinstance(body["payload"], dict):
        signal = _coerce_tracker_body(body)
    else:
        # Flat style: validate directly via Pydantic
        try:
            signal = NexusSignal(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # Explicit network support gate (flat + tracker)
    if signal.network not in SUPPORTED_NETWORKS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported network '{signal.network}'",
        )

    # Final gate on confidence
    if signal.confidence < MIN_CONFIDENCE:
        raise HTTPException(
            status_code=422,
            detail=f"Confidence {signal.confidence:.2f} below floor {MIN_CONFIDENCE:.2f}",
        )

    import asyncio
    job_id = await asyncio.to_thread(_enqueue_nexus_signal, signal)
    logger.info(
        "Nexus signal received: token=%s network=%s confidence=%.2f job=%s",
        signal.token_address,
        signal.network,
        signal.confidence,
        job_id,
    )
    return {"status": "received", "job_id": job_id}
