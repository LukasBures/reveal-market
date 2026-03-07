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
    # Item 2: relayer webhook secret must be set so fabricated settlement
    # confirmations cannot be POSTed to the webhook endpoint.
    if not settings.relayer_webhook_secret:
        missing.append("RM_RELAYER_WEBHOOK_SECRET")
    if missing:
        log_event(
            logger,
            logging.ERROR,
            event="startup.validation.failed",
            message="missing required secrets for production",
            missing=missing,
        )
        raise RuntimeError(f"missing required secrets for production: {', '.join(missing)}")

    # Item 3: rate limiting must be enabled so pricing/commit endpoints cannot
    # be abused. The prod preset sets this to True; warn loudly if overridden.
    if not settings.rate_limit_enabled:
        log_event(
            logger,
            logging.WARNING,
            event="startup.validation.rate_limit_disabled",
            message=(
                "RM_RATE_LIMIT_ENABLED is False in production — "
                "pricing and commit endpoints are unprotected against abuse"
            ),
        )
