"""Nexus Intelligence signal receiver.

Continuously receiving and validating Nexus screening signals.
This module is auth-gated and strictly fails closed if the execution
adapter is not yet fully installed.
"""

import hmac
import logging
import os
import uuid
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings

logger = logging.getLogger("nexus_router")

SUPPORTED_NETWORKS = {"solana", "ethereum", "bsc", "base"}
MIN_CONFIDENCE = 0.5

router = APIRouter(prefix="/nexus", tags=["Nexus Intelligence"])


class NexusSignal(BaseModel):
    token_address: str = Field(..., min_length=8, max_length=128)
    network: str = Field(..., description="solana | ethereum | bsc | base")
    confidence: float = Field(..., ge=0.0, le=1.0)
    entry_price: float | None = Field(default=None, gt=0)
    risk_params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        bearer = authorization[len("Bearer ") :].strip()
    presented = bearer or (x_nexus_key or "").strip()
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized — send Authorization: Bearer <nexus key>",
        )
    if not any(hmac.compare_digest(presented, key) for key in configured):
        raise HTTPException(status_code=401, detail="Unauthorized — invalid Nexus key")


def _enqueue_nexus_signal(signal: NexusSignal) -> str:
    """Persist a Nexus screening verdict into the durable job queue."""
    from backend.models.database import SessionLocal, JobQueue

    payload = {
        "token_address": signal.token_address,
        "network": signal.network.lower(),
        "confidence": signal.confidence,
        "entry_price": signal.entry_price,
        "risk_params": signal.risk_params,
        "metadata": signal.metadata,
    }
    idempotency_key = f"nexus:{signal.network.lower()}:{signal.token_address}"
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
            payload=payload,
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
async def receive_nexus_signal(signal: NexusSignal) -> dict[str, Any]:
    if signal.network.lower() not in SUPPORTED_NETWORKS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported network '{signal.network}'",
        )
    if signal.confidence < MIN_CONFIDENCE:
        raise HTTPException(
            status_code=422,
            detail=f"Confidence {signal.confidence:.2f} below floor {MIN_CONFIDENCE:.2f}",
        )

    job_id = await asyncio.to_thread(_enqueue_nexus_signal, signal)

    logger.info(
        "Nexus signal received: token=%s network=%s confidence=%.2f job=%s",
        signal.token_address,
        signal.network,
        signal.confidence,
        job_id,
    )
    return {"status": "received", "job_id": job_id}
