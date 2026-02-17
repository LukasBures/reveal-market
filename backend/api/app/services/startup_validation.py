"""Startup validation for required secrets in production."""

from __future__ import annotations

import logging

from shared.logging import log_event

from app.runtime import is_production, logger, settings


def validate_required_secrets() -> None:
    """Fail fast when required secrets are missing in production."""

    if not is_production:
        return
    missing: list[str] = []
    if not settings.internal_api_secret:
        missing.append("RM_INTERNAL_API_SECRET")
    if not settings.pricing_signer_private_key:
        missing.append("RM_PRICING_SIGNER_PRIVATE_KEY")
    if not settings.authorization_signer_private_key:
        missing.append("RM_AUTHORIZATION_SIGNER_PRIVATE_KEY")
    if settings.relayer_base_url is None:
        missing.append("RM_RELAYER_BASE_URL")
    if settings.rpc_url is None:
        missing.append("RM_RPC_URL")
    if missing:
        log_event(
            logger,
            logging.ERROR,
            event="startup.validation.failed",
            message="missing required secrets for production",
            missing=missing,
        )
        raise RuntimeError(f"missing required secrets for production: {', '.join(missing)}")
