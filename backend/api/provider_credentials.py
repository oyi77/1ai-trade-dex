"""REST API for provider credentials and configuration.

Allows the admin to add, update, list, and delete market provider config
keys at runtime, without restarting the server or editing ``.env``.

Endpoints:
    GET    /api/v1/provider-credentials                        list all providers
    GET    /api/v1/provider-credentials/{provider_name}        list keys for one provider
    PUT    /api/v1/provider-credentials/{provider_name}/{key}  upsert a key
    DELETE /api/v1/provider-credentials/{provider_name}/{key}  delete a key
    DELETE /api/v1/provider-credentials/{provider_name}        delete all keys for provider
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.auth import require_admin
from backend.models.database import get_db, ProviderCredential
from backend.core.provider_config_store import provider_config

router = APIRouter(prefix="/provider-credentials", tags=["provider_credentials"])


# ────────────────────────────────────── Pydantic schemas ─────────────────────


class CredentialResponse(BaseModel):
    id: int
    provider_name: str
    config_key: str
    config_value: Optional[str]
    is_secret: bool
    description: Optional[str]

    class Config:
        from_attributes = True


class UpsertCredentialRequest(BaseModel):
    config_value: str
    is_secret: bool = False
    description: Optional[str] = None


class ProviderSummary(BaseModel):
    provider_name: str
    key_count: int
    keys: List[str]


# ────────────────────────────────────────────────── Endpoints ─────────────────


@router.get("", response_model=List[ProviderSummary], dependencies=[Depends(require_admin)])
async def list_providers(db: Session = Depends(get_db)) -> List[ProviderSummary]:
    """Return a summary of all configured providers (key names only, no values)."""
    rows = db.query(ProviderCredential).order_by(
        ProviderCredential.provider_name, ProviderCredential.config_key
    ).all()

    by_provider: dict[str, list[str]] = {}
    for row in rows:
        by_provider.setdefault(row.provider_name, []).append(row.config_key)

    return [
        ProviderSummary(provider_name=pname, key_count=len(keys), keys=keys)
        for pname, keys in sorted(by_provider.items())
    ]


@router.get(
    "/{provider_name}",
    response_model=List[CredentialResponse],
    dependencies=[Depends(require_admin)],
)
async def list_provider_keys(
    provider_name: str,
    db: Session = Depends(get_db),
) -> List[CredentialResponse]:
    """Return all config keys for a provider.

    Secret values are masked as ``"***"`` in the response.
    """
    rows = (
        db.query(ProviderCredential)
        .filter_by(provider_name=provider_name)
        .order_by(ProviderCredential.config_key)
        .all()
    )
    return [
        CredentialResponse(
            id=row.id,
            provider_name=row.provider_name,
            config_key=row.config_key,
            config_value="***" if row.is_secret else row.config_value,
            is_secret=row.is_secret,
            description=row.description,
        )
        for row in rows
    ]


@router.put(
    "/{provider_name}/{config_key}",
    response_model=CredentialResponse,
    dependencies=[Depends(require_admin)],
)
async def upsert_credential(
    provider_name: str,
    config_key: str,
    body: UpsertCredentialRequest,
    db: Session = Depends(get_db),
) -> CredentialResponse:
    """Create or update a config key for a provider.

    Set ``is_secret=true`` for private keys, API secrets, etc.
    The value is encrypted at rest using ``WALLET_FERNET_KEY``.
    """
    provider_config.upsert(
        db=db,
        provider_name=provider_name,
        config_key=config_key,
        config_value=body.config_value,
        is_secret=body.is_secret,
        description=body.description,
    )

    row = (
        db.query(ProviderCredential)
        .filter_by(provider_name=provider_name, config_key=config_key)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=500, detail="Credential was not persisted")
    return CredentialResponse(
        id=row.id,
        provider_name=row.provider_name,
        config_key=row.config_key,
        config_value="***" if row.is_secret else row.config_value,
        is_secret=row.is_secret,
        description=row.description,
    )


@router.delete(
    "/{provider_name}/{config_key}",
    dependencies=[Depends(require_admin)],
)
async def delete_credential(
    provider_name: str,
    config_key: str,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a single config key for a provider."""
    n = provider_config.delete(db, provider_name, config_key)
    if n == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No credential found for provider={provider_name!r} key={config_key!r}",
        )
    return {"deleted": n, "provider_name": provider_name, "config_key": config_key}


@router.delete(
    "/{provider_name}",
    dependencies=[Depends(require_admin)],
)
async def delete_provider(
    provider_name: str,
    db: Session = Depends(get_db),
) -> dict:
    """Delete ALL config keys for a provider."""
    n = provider_config.delete(db, provider_name)
    return {"deleted": n, "provider_name": provider_name}
