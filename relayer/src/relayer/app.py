import asyncio
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from structlog import get_logger
from web3 import Web3
from web3.exceptions import Web3Exception

from .metrics import REQUEST_LATENCY
from .queue import TxQueue
from .schemas import ClaimRequest, CommitRequest
from .service import RelayerService

logger = get_logger()


def create_app(
    relayer_service: RelayerService,
    chain_id: int,
    rpc_url: str,
    bearer_token: str | None = None,
    tx_queue: TxQueue | None = None,
) -> FastAPI:
    app = FastAPI(title="Reveal Relayer", version="0.1.0")

    def get_service() -> RelayerService:
        return relayer_service

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if bearer_token is None:
            return
        expected = f"Bearer {bearer_token}"
        if authorization != expected:
            logger.warning("auth_failed", provided=authorization)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unauthorized",
            )

    @app.middleware("http")
    async def log_requests(request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        status_code = response.status_code
        path = request.url.path
        REQUEST_LATENCY.labels(endpoint=path, status=str(status_code)).observe(duration)
        logger.info(
            "http_request",
            method=request.method,
            path=path,
            status_code=status_code,
            duration_ms=round(duration * 1000, 2),
        )
        return response

    if tx_queue:

        @app.on_event("startup")
        async def start_queue_worker() -> None:
            await tx_queue.start()

        @app.on_event("shutdown")
        async def stop_queue_worker() -> None:
            await tx_queue.stop()

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return await asyncio.to_thread(relayer_service.health)

    @app.post("/commit")
    async def commit(
        req: CommitRequest,
        svc: RelayerService = Depends(get_service),
        _: None = Depends(require_auth),
    ) -> Response | dict[str, str | int]:
        try:
            payload = req.model_dump()
            payload["user"] = Web3.to_checksum_address(payload["user"])
            payload["market"] = Web3.to_checksum_address(payload["market"])
            if tx_queue:
                job_id = await tx_queue.enqueue("commit", payload)
                logger.info("commit_enqueued", job_id=job_id, market=payload["market"], user=payload["user"])
                return JSONResponse(
                    {"jobId": job_id, "status": "queued"},
                    status_code=status.HTTP_202_ACCEPTED,
                )
            return await asyncio.to_thread(svc.commit, payload)
        except ValueError as err:
            logger.warning("commit_invalid_address", error=str(err))
            raise HTTPException(status_code=400, detail="invalid_address") from err
        except (Web3Exception, RuntimeError, OverflowError) as err:
            logger.error("commit_failed", error=str(err))
            raise HTTPException(status_code=500, detail="commit_failed") from err

    @app.post("/claim")
    async def claim(
        req: ClaimRequest,
        svc: RelayerService = Depends(get_service),
        _: None = Depends(require_auth),
    ) -> Response | dict[str, str | int]:
        try:
            payload = req.model_dump()
            payload["user"] = Web3.to_checksum_address(payload["user"])
            payload["market"] = Web3.to_checksum_address(payload["market"])
            if tx_queue:
                job_id = await tx_queue.enqueue("claim", payload)
                logger.info("claim_enqueued", job_id=job_id, market=payload["market"], user=payload["user"])
                return JSONResponse(
                    {"jobId": job_id, "status": "queued"},
                    status_code=status.HTTP_202_ACCEPTED,
                )
            return await asyncio.to_thread(svc.claim, payload)
        except ValueError as err:
            logger.warning("claim_invalid_address", error=str(err))
            raise HTTPException(status_code=400, detail="invalid_address") from err
        except (Web3Exception, RuntimeError, OverflowError) as err:
            logger.error("claim_failed", error=str(err))
            raise HTTPException(status_code=500, detail="claim_failed") from err

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/admin/queue/deadletter")
    async def list_deadletter(_: None = Depends(require_auth)):
        if not tx_queue:
            raise HTTPException(status_code=503, detail="queue_disabled")
        deadletter = await tx_queue.list_deadletter()
        return {"deadletter": deadletter}

    @app.post("/admin/queue/deadletter/{job_id}/replay")
    async def replay_deadletter(job_id: int, _: None = Depends(require_auth)):
        if not tx_queue:
            raise HTTPException(status_code=503, detail="queue_disabled")
        try:
            return await tx_queue.replay_job(job_id)
        except RuntimeError as err:
            if str(err) == "job_not_found":
                raise HTTPException(status_code=404, detail="job_not_found") from err
            if str(err) == "job_not_deadletter":
                raise HTTPException(status_code=400, detail="job_not_deadletter") from err
            raise

    @app.delete("/admin/queue/deadletter/{job_id}")
    async def purge_deadletter(job_id: int, _: None = Depends(require_auth)):
        if not tx_queue:
            raise HTTPException(status_code=503, detail="queue_disabled")
        try:
            return await tx_queue.purge_job(job_id)
        except RuntimeError as err:
            if str(err) == "job_not_found":
                raise HTTPException(status_code=404, detail="job_not_found") from err
            if str(err) == "job_not_deadletter":
                raise HTTPException(status_code=400, detail="job_not_deadletter") from err
            raise

    return app
