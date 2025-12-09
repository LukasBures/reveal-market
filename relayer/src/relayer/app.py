from fastapi import Depends, FastAPI, HTTPException
from structlog import get_logger
from web3 import Web3

from .schemas import ClaimRequest, CommitRequest
from .service import RelayerService

logger = get_logger()


def create_app(relayer_service: RelayerService, chain_id: int, rpc_url: str) -> FastAPI:
    app = FastAPI(title="Reveal Relayer", version="0.1.0")

    def get_service() -> RelayerService:
        return relayer_service

    @app.get("/healthz")
    def healthz():
        payload = {
            "status": "ok",
            "relayer": relayer_service.account.address,
            "escrow": relayer_service.escrow.address,
            "chainId": chain_id,
            "rpc": rpc_url,
        }
        logger.info("health_check", **payload)
        return payload

    @app.post("/commit")
    def commit(req: CommitRequest, svc: RelayerService = Depends(get_service)):
        try:
            payload = req.model_dump()
            payload["user"] = Web3.to_checksum_address(payload["user"])
            payload["market"] = Web3.to_checksum_address(payload["market"])
            return svc.commit(payload)
        except ValueError as err:
            logger.warning("commit_invalid_address", error=str(err))
            raise HTTPException(status_code=400, detail="invalid_address") from err
        except Exception as err:  # noqa: BLE001
            logger.error("commit_failed", error=str(err))
            raise HTTPException(status_code=500, detail="commit_failed") from err

    @app.post("/claim")
    def claim(req: ClaimRequest, svc: RelayerService = Depends(get_service)):
        try:
            payload = req.model_dump()
            payload["user"] = Web3.to_checksum_address(payload["user"])
            payload["market"] = Web3.to_checksum_address(payload["market"])
            return svc.claim(payload)
        except ValueError as err:
            logger.warning("claim_invalid_address", error=str(err))
            raise HTTPException(status_code=400, detail="invalid_address") from err
        except Exception as err:  # noqa: BLE001
            logger.error("claim_failed", error=str(err))
            raise HTTPException(status_code=500, detail="claim_failed") from err

    return app
