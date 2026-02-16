from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .service import HedgerService
from .types import CommitEvent

router = APIRouter(prefix="/admin", tags=["admin"])


def get_service(request: Request) -> HedgerService:
    return request.app.state.service  # type: ignore[attr-defined]


def require_writable(service: HedgerService = Depends(get_service)) -> None:
    if service.settings.admin_read_only:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="read_only")


def require_internal_secret(
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
    service: HedgerService = Depends(get_service),
) -> None:
    required = service.settings.admin_internal_secret
    if not required:
        return
    if not internal_secret or internal_secret != required:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")


@router.get("/exposures")
async def exposures(service: HedgerService = Depends(get_service)):
    return {"exposures": await service.exposures()}


@router.post("/commits")
async def ingest_commit(
    commit: CommitEvent,
    service: HedgerService = Depends(get_service),
    _secret: None = Depends(require_internal_secret),
    _write: None = Depends(require_writable),
):
    return await service.ingest_commit(commit)


@router.get("/risk")
async def risk(service: HedgerService = Depends(get_service)):
    snapshots = await service.exposures()
    total_abs = sum([abs(s.net_usd) for s in snapshots], start=Decimal("0"))
    breaches = []
    for snap in snapshots:
        breaches.extend(
            service.risk_engine.check_limits(
                market_id=snap.market_id,
                market_net_usd=snap.net_usd,
                absolute_market_usd=abs(snap.net_usd),
                total_absolute_usd=total_abs,
                coverage_ratio=snap.coverage_ratio,
                float_balance_zen=Decimal("0"),
            )
        )
    return service.risk_engine.report(breaches)


@router.get("/positions")
async def positions(service: HedgerService = Depends(get_service)):
    exposure_list = await service.exposures()
    return {"exposures": exposure_list}


@router.post("/settlements/{market_id}")
async def trigger_settlement(
    market_id: str,
    payload: dict,
    service: HedgerService = Depends(get_service),
    _: None = Depends(require_writable),
):
    return await service.trigger_settlement(market_id, payload)


@router.post("/bridge")
async def bridge_liquidity(
    direction: str,
    amount: Decimal,
    destination: str,
    slippage_bps: int | None = None,
    service: HedgerService = Depends(get_service),
    _: None = Depends(require_writable),
):
    """
    Manually trigger a bridge transfer between USDC and ZEN rails.
    """

    return await service.request_bridge(direction, amount, destination, slippage_bps=slippage_bps)


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
