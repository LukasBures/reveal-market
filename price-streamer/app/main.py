from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Query, Response
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

    @app.get("/health")
    async def health() -> dict:
        fx = await state.get_fx()
        return {
            "status": "ok",
            "fx_zen_usd": str(fx.zen_usd),
            "fx_stale": fx.stale,
            "fx_last_update": state.fx_last_update.isoformat() if state.fx_last_update else None,
            "stale_markets": state.stale_markets(),
            "last_seen": {k: v.isoformat() for k, v in state.last_seen.items()},
        }

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
        if assets_ids:
            state.subscriptions.add_assets([asset.strip() for asset in assets_ids.split(",") if asset.strip()])
        if symbols:
            for sym in symbols.split(","):
                trimmed = sym.strip()
                if trimmed:
                    state.rtds_symbols.add(trimmed)
        pubsub = await state.subscribe(market_id)
        return StreamingResponse(
            _sse_events(pubsub, heartbeat_seconds=heartbeat, max_events=max_events),
            media_type="text/event-stream",
        )

    @app.get("/history")
    async def history(
        market_id: str = Query(...),
        outcome: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=settings.history_limit),
    ):
        records = await state.get_history(market_id, str(outcome), limit)
        return {"market_id": market_id, "outcome": outcome, "count": len(records), "data": records}

    return app


app = create_app()
