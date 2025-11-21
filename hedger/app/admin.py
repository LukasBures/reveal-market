from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .service import HedgerService
from .types import CommitEvent

router = APIRouter(prefix="/admin", tags=["admin"])


def get_service(request: Request) -> HedgerService:
    return request.app.state.service  # type: ignore[attr-defined]


@router.get("/exposures")
async def exposures(service: HedgerService = Depends(get_service)):
    return {"exposures": await service.exposures()}


@router.post("/commits")
async def ingest_commit(commit: CommitEvent, service: HedgerService = Depends(get_service)):
    return await service.ingest_commit(commit)


@router.get("/risk")
async def risk(service: HedgerService = Depends(get_service)):
    snapshots = await service.exposures()
    total_abs = sum([abs(s.net_usd) for s in snapshots], start=Decimal("0"))
    breaches = []
    lp_utilization = await service.vault_client.current_utilization()
    for snap in snapshots:
        breaches.extend(
            service.risk_engine.check_limits(
                market_id=snap.market_id,
                market_net_usd=snap.net_usd,
                absolute_market_usd=abs(snap.net_usd),
                total_absolute_usd=total_abs,
                coverage_ratio=snap.coverage_ratio,
                lp_utilization=lp_utilization,
                float_balance_zen=Decimal("0"),
            )
        )
    return service.risk_engine.report(breaches)


@router.get("/positions")
async def positions(service: HedgerService = Depends(get_service)):
    exposures = await service.exposures()
    utilization = await service.vault_client.current_utilization()
    return {
        "exposures": exposures,
        "lp_utilization": utilization,
    }


@router.post("/settlements/{market_id}")
async def trigger_settlement(market_id: str, payload: dict, service: HedgerService = Depends(get_service)):
    return await service.trigger_settlement(market_id, payload)


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
