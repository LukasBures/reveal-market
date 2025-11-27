from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import FastAPI, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import get_settings
from .logging_utils import setup_logging, start_heartbeat
from .state import StreamState
from .streamer import PriceStreamer

logger = logging.getLogger("reveal_market.price_streamer")


async def _sse_events(pubsub, heartbeat_seconds: int, max_events: int | None = None) -> AsyncGenerator[str, None]:
    try:
        heartbeat = asyncio.create_task(asyncio.sleep(heartbeat_seconds))
        emitted = 0
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=heartbeat_seconds)
            if message and message.get("data"):
                yield f"data: {message['data']}\n\n"
                emitted += 1
                if max_events and emitted >= max_events:
                    break
            if heartbeat.done():
                yield "event: ping\ndata: {}\n\n"
                heartbeat = asyncio.create_task(asyncio.sleep(heartbeat_seconds))
                emitted += 1
                if max_events and emitted >= max_events:
                    break
    finally:
        with suppress(Exception):
            await pubsub.close()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging("reveal_market.price_streamer", settings.log_level)

    state = StreamState(settings)
    streamer = PriceStreamer(state, settings)
    heartbeat_stop = start_heartbeat(logger, "price_streamer", interval_seconds=60)
    sanitized_config = {
        k: v
        for k, v in settings.model_dump().items()
        if not any(secret in k for secret in ["key", "private", "secret", "password"])
    }
    logger.info("service configuration", extra={"event": "service.config", "config": sanitized_config})
    if not settings.cors_allow_origins or settings.cors_allow_origins == ["*"]:
        logger.warning(
            "price-streamer CORS allow_origins is wildcard; set explicit origins for browser clients",
            extra={"event": "cors.unbounded", "scope": "price-streamer"},
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await state.startup()
        await streamer.start()
        logger.info("price-streamer ready", extra={"event": "price_streamer.ready"})
        try:
            yield
        finally:
            heartbeat_stop.set()
            with suppress(Exception):
                await streamer.stop()
                await state.shutdown()

    app = FastAPI(title="Reveal Price Streamer", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        allow_credentials=settings.cors_allow_credentials,
    )

    async def _health_payload() -> dict:
        fx = await state.get_fx()
        stale_markets = state.stale_markets(settings.market_stale_seconds)
        status = "ok"
        if fx.stale or not state.fx_ws_connected:
            status = "stale"
        elif stale_markets:
            status = "degraded"
        return {
            "status": status,
            "fx_zen_usd": str(fx.zen_usd),
            "fx_raw_zen_usd": str(fx.raw_zen_usd or fx.zen_usd),
            "fx_stale": fx.stale,
            "fx_source": fx.source,
            "fx_ws_connected": state.fx_ws_connected,
            "fx_last_error": state.fx_last_error,
            "fx_last_update": state.fx_last_update.isoformat() if state.fx_last_update else None,
            "stale_markets": stale_markets,
            "last_seen": state.snapshot_last_seen(),
        }

    @app.get("/health")
    async def health() -> dict:
        return await _health_payload()

    @app.get("/healthz")
    async def healthz() -> dict:
        return await _health_payload()

    async def _fx_payload() -> dict:
        quote = await state.get_fx()
        now = datetime.now(UTC)
        age_seconds = (now - (quote.fetched_at or now)).total_seconds()
        return {
            "pair": "ZEN/USDC",
            "zen_usd": float(quote.zen_usd),
            "raw_zen_usd": float(quote.raw_zen_usd or quote.zen_usd),
            "source": quote.source,
            "received_at": quote.fetched_at.isoformat(),
            "stale": quote.stale,
            "age_seconds": age_seconds,
        }

    @app.get("/fx/zen-usdc")
    async def fx_quote_usdc() -> dict:
        return await _fx_payload()

    @app.get("/fx/zen-usd")
    async def fx_quote_usd() -> dict:
        return await _fx_payload()

    @app.get("/fx/zen-usdt")
    async def fx_quote_usdt() -> dict:
        return await _fx_payload()

    async def _fx_ws_stream(ws: WebSocket):
        await ws.accept()
        last_sent: datetime | None = None
        try:
            while True:
                fx = await state.get_fx()
                updated_at = state.fx_last_update or fx.fetched_at
                if last_sent is None or (updated_at and updated_at != last_sent):
                    await ws.send_json(
                        {
                            "pair": "ZEN/USDC",
                            "zen_usd": float(fx.zen_usd),
                            "raw_zen_usd": float(fx.raw_zen_usd or fx.zen_usd),
                            "source": fx.source,
                            "received_at": fx.fetched_at.isoformat(),
                            "stale": fx.stale,
                        }
                    )
                    last_sent = updated_at
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("FX websocket error", extra={"event": "fx.ws.stream.error", "error": str(exc)})
        finally:
            with suppress(Exception):
                await ws.close()

    @app.websocket("/fx/zen-usd")
    async def fx_websocket_usd(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app.websocket("/fx/zen-usdc")
    async def fx_websocket_usdc(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app.websocket("/fx/zen-usdt")
    async def fx_websocket_usdt(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/stream")
    async def stream(
        market_id: str = Query(..., description="Market ID to stream"),
        heartbeat: int = Query(15, ge=1),
        max_events: int | None = Query(default=None, ge=1, description="Optional cap on events (for testing)"),
        assets_ids: str | None = Query(
            default=None, description="Comma-separated asset IDs to subscribe to (CLOB market stream)"
        ),
        symbols: str | None = Query(default=None, description="Comma-separated crypto symbols to subscribe (RTDS)"),
    ):
        # Allow on-demand subscription scoping.
        assets: list[str] = []
        if assets_ids:
            assets = [asset.strip() for asset in assets_ids.split(",") if asset.strip()]
        # Default to the requested market_id so websocket streams stay hydrated even without explicit assets_ids.
        if not assets and market_id:
            tokens = state.get_clob_tokens(market_id)
            assets = tokens or [market_id]
        if assets:
            state.subscriptions.add_assets(assets)
        if symbols:
            state.add_rtds_symbols(sym.strip() for sym in symbols.split(","))
        pubsub = await state.subscribe(market_id)
        return StreamingResponse(
            _sse_events(pubsub, heartbeat_seconds=heartbeat, max_events=max_events),
            media_type="text/event-stream",
        )

    @app.websocket("/stream/ws")
    async def stream_ws(
        websocket: WebSocket,
        market_id: str,
        heartbeat: int = 15,
        assets_ids: str | None = None,
        symbols: str | None = None,
    ):
        assets: list[str] = []
        if assets_ids:
            assets = [asset.strip() for asset in assets_ids.split(",") if asset.strip()]
        if not assets and market_id:
            tokens = state.get_clob_tokens(market_id)
            assets = tokens or [market_id]
        if assets:
            state.subscriptions.add_assets(assets)
        if symbols:
            state.add_rtds_symbols(sym.strip() for sym in symbols.split(","))
        pubsub = await state.subscribe(market_id)
        await websocket.accept()
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=heartbeat)
                if message and message.get("data"):
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(str(data))
                else:
                    await websocket.send_json({"event": "ping", "ts": datetime.now(UTC).isoformat()})
        except WebSocketDisconnect:
            return
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("market websocket error", extra={"event": "stream.ws.error", "error": str(exc)})
        finally:
            with suppress(Exception):
                await pubsub.close()
            with suppress(Exception):
                await websocket.close()

    @app.get("/history")
    async def history(
        market_id: str = Query(...),
        outcome: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=settings.history_limit),
    ):
        records = await state.get_history(market_id, str(outcome), limit)
        return {"market_id": market_id, "outcome": outcome, "count": len(records), "data": records}

    @app.get("/subscriptions")
    async def subscriptions():
        return {
            "assets": sorted(state.subscriptions.assets),
            "symbols": sorted(state.rtds_symbols),
            "count": len(state.subscriptions.assets),
            "max": settings.max_subscriptions,
        }

    return app


app = create_app()
