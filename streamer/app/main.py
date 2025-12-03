# mypy: ignore-errors
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from time import time
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import get_settings
from .data_streamer import DataStreamer
from .env_presets import PRESETS, get_preset, resolve_mode
from .logging_utils import setup_logging, start_heartbeat
from .metrics import get_metrics
from .price_streamer import PriceStreamer
from .state import StreamState
from .subgraph import SubgraphClient, SubgraphError, SubgraphNotConfiguredError

logger = logging.getLogger("reveal_market.streamer")


def _compute_cors_host_warnings(
    settings, cors_allow_origins: list[str], env_streamer_url: str | None = None
) -> list[dict]:
    """Return a list of host/CORS mismatches for logging and tests."""

    warnings: list[dict] = []
    resolved_public = str(settings.public_base_url).rstrip("/") if settings.public_base_url else ""
    env_url = (env_streamer_url or os.getenv("NEXT_PUBLIC_PRICE_STREAMER_URL") or "").rstrip("/")
    if resolved_public and cors_allow_origins != ["*"] and resolved_public not in cors_allow_origins:
        warnings.append({"reason": "public_not_in_cors", "public": resolved_public, "cors": cors_allow_origins})
    if env_url and resolved_public and env_url != resolved_public:
        warnings.append({"reason": "env_mismatch", "expected": resolved_public, "env": env_url})
    return warnings


async def _sse_events(
    pubsub,
    heartbeat_seconds: int,
    max_events: int | None = None,
    *,
    metrics=None,
    on_close: Callable[[], None] | None = None,
) -> AsyncGenerator[str, None]:
    try:
        effective_heartbeat = min(heartbeat_seconds, 1) if max_events else heartbeat_seconds
        heartbeat = asyncio.create_task(asyncio.sleep(effective_heartbeat))
        emitted = 0
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=effective_heartbeat)
            if message and message.get("data"):
                payload = message["data"]
                yield f"data: {payload}\n\n"
                if metrics:
                    with suppress(Exception):
                        metrics.record_delivery("sse", payload)
                emitted += 1
                if max_events and emitted >= max_events:
                    break
            if heartbeat.done():
                if metrics:
                    with suppress(Exception):
                        metrics.record_drop("sse", "heartbeat")
                yield "event: ping\ndata: {}\n\n"
                heartbeat = asyncio.create_task(asyncio.sleep(effective_heartbeat))
                emitted += 1
                if max_events and emitted >= max_events:
                    break
            elif max_events:
                await asyncio.sleep(0)
    finally:
        with suppress(Exception):
            await pubsub.close()
        if on_close:
            with suppress(Exception):
                on_close()


def create_app() -> FastAPI:
    settings = get_settings()
    mode_env = resolve_mode()
    preset = get_preset()
    # Force preset URLs and environment label so we do not rely on ad-hoc env vars and avoid host mismatches.
    settings = settings.model_copy(
        update={
            "environment": mode_env,
            "public_base_url": preset.get("streamer_public"),
            "internal_base_url": preset.get("streamer_internal"),
            "cors_allow_origins": preset.get("api_cors_origins", []),
        },
        deep=True,
    )
    setup_logging("reveal_market.streamer", settings.log_level)

    # Union of preset CORS origins so local + prod both work without extra env tweaks.
    cors_allow_origins = sorted(
        {
            origin.rstrip("/")
            for preset_entry in PRESETS.values()
            for origin in preset_entry.get("api_cors_origins", []) or []
        }
    )
    if mode_env == "prod" and ("*" in cors_allow_origins):
        cors_allow_origins = sorted([o for o in (preset.get("api_cors_origins", []) or []) if o != "*"])
        logger.warning(
            "wildcard CORS overridden in prod",
            extra={"event": "cors.overridden", "origins": cors_allow_origins},
        )
        if not cors_allow_origins:
            raise ValueError("CORS origins must be set in prod mode")
    if not cors_allow_origins:
        raise ValueError("CORS origins resolved to empty list; check presets")

    metrics = get_metrics()
    state = StreamState(settings, metrics=metrics)
    data_streamer = DataStreamer(state, settings, metrics=metrics)
    price_streamer = PriceStreamer(state, settings)
    subgraph_client = SubgraphClient(settings)
    heartbeat_stop = start_heartbeat(logger, "streamer", interval_seconds=60)
    sanitized_config = {
        k: v
        for k, v in settings.model_dump(warnings=False).items()
        if not any(secret in k for secret in ["key", "private", "secret", "password", "token"])
    }
    sanitized_config["cors_allow_origins_resolved"] = cors_allow_origins
    logger.info("service configuration", extra={"event": "service.config", "config": sanitized_config})
    if os.getenv("NEXT_PUBLIC_DISABLE_STREAMER_WS", "").lower() == "true":
        logger.warning(
            "NEXT_PUBLIC_DISABLE_STREAMER_WS is enabled; websocket upgrades will be skipped",
            extra={"event": "stream.ws.disabled_env"},
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await state.startup()
        await data_streamer.start()
        await price_streamer.start()
        logger.info("streamer ready", extra={"event": "streamer.ready"})
        try:
            yield
        finally:
            heartbeat_stop.set()
            with suppress(Exception):
                await data_streamer.stop()
                await price_streamer.stop()
                await state.shutdown()

    app_instance = FastAPI(title="Reveal Price Streamer", version="0.1.0", lifespan=lifespan)
    app_instance.state.cors_origins = cors_allow_origins

    def _acquire_connection() -> None:
        state.active_connections += 1
        if state.active_connections > settings.max_active_connections:
            state.active_connections -= 1
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many connections")

    def _release_connection() -> None:
        state.active_connections = max(0, state.active_connections - 1)

    def _require_access_token(token: str | None):
        if settings.access_token and token != settings.access_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid access token")

    rl_buckets: dict[str, list[float]] = {}

    def _rate_limit(identifier: str):
        if settings.rate_limit_per_minute <= 0:
            return
        now = time()
        bucket = rl_buckets.setdefault(identifier, [])
        # drop entries older than 60s
        rl_buckets[identifier] = [ts for ts in bucket if now - ts < 60]
        bucket = rl_buckets[identifier]
        if len(bucket) >= settings.rate_limit_per_minute:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
        bucket.append(now)

    app_instance.add_middleware(
        cast(Any, CORSMiddleware),
        allow_origins=cors_allow_origins,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        allow_credentials=settings.cors_allow_credentials,
    )
    for warning in _compute_cors_host_warnings(settings, cors_allow_origins):
        logger.warning("streamer host/CORS mismatch", extra={"event": "streamer.host.mismatch", **warning})
    if cors_allow_origins != ["*"]:
        if str(settings.public_base_url).rstrip("/") not in cors_allow_origins:
            logger.error(
                "streamer public_base_url not allowed by CORS",
                extra={
                    "event": "streamer.cors.mismatch",
                    "public_base_url": str(settings.public_base_url),
                    "cors_allow_origins": cors_allow_origins,
                },
            )
            if mode_env == "prod":
                raise ValueError("public_base_url must be whitelisted in CORS")

    async def _health_payload() -> dict:
        fx = await state.get_fx()
        stale_markets = state.stale_markets(settings.market_stale_seconds)
        if stale_markets:
            stale_sample = stale_markets[:50]
            extra = {
                "event": "stream.stale.markets",
                "count": len(stale_markets),
                "threshold_seconds": settings.market_stale_seconds,
                "stale_markets": stale_sample,
            }
            if len(stale_sample) < len(stale_markets):
                extra["stale_markets_omitted"] = len(stale_markets) - len(stale_sample)
            logger.warning(
                "stale markets detected",
                extra=extra,
            )
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
            "stale_count": len(stale_markets),
            "market_stale_threshold_seconds": settings.market_stale_seconds,
            "last_seen": state.snapshot_last_seen(),
        }

    @app_instance.get("/health")
    async def health() -> dict:
        return await _health_payload()

    @app_instance.get("/healthz")
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

    @app_instance.get("/fx/zen-usdc")
    @app_instance.get("/data/fx")
    async def fx_quote_usdc() -> dict:
        return await _fx_payload()

    @app_instance.get("/fx/zen-usd")
    async def fx_quote_usd() -> dict:
        return await _fx_payload()

    @app_instance.get("/fx/zen-usdt")
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

    @app_instance.websocket("/fx/zen-usd")
    async def fx_websocket_usd(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app_instance.websocket("/fx/zen-usdc")
    async def fx_websocket_usdc(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app_instance.websocket("/fx/zen-usdt")
    async def fx_websocket_usdt(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app_instance.websocket("/data/fx/ws")
    async def fx_websocket_data(ws: WebSocket):
        await _fx_ws_stream(ws)

    @app_instance.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app_instance.get("/subgraph/markets")
    @app_instance.get("/data/subgraph/markets")
    async def subgraph_markets(
        first: int = Query(20, ge=1, le=200),
        skip: int = Query(0, ge=0),
        ids: str | None = Query(default=None, description="Comma-separated market ids to filter"),
    ):
        id_list = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
        markets = await _subgraph_query(
            subgraph_client.fetch_markets,
            first=first,
            skip=skip,
            ids=id_list,
        )
        return {"count": len(markets), "data": markets}

    @app_instance.get("/subgraph/trades")
    @app_instance.get("/data/subgraph/trades")
    async def subgraph_trades(
        asset_ids: str = Query(..., description="Comma-separated asset ids to filter (maker/taker asset ids)"),
        first: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
        user: str | None = Query(default=None, description="Optional user address filter"),
    ):
        assets = [item.strip() for item in asset_ids.split(",") if item.strip()]
        if not assets:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="asset_ids required")
        trades = await _subgraph_query(
            subgraph_client.fetch_trades,
            asset_ids=assets,
            first=first,
            skip=skip,
            user=user,
        )
        return {"asset_ids": assets, "count": len(trades), "data": trades}

    @app_instance.get("/subgraph/positions")
    @app_instance.get("/data/subgraph/positions")
    async def subgraph_positions(
        user: str = Query(..., description="User address to query positions for"),
        asset_ids: str | None = Query(default=None, description="Optional comma-separated asset id filter"),
        first: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        assets = [item.strip() for item in asset_ids.split(",") if item.strip()] if asset_ids else None
        positions = await _subgraph_query(
            subgraph_client.fetch_positions,
            user=user,
            asset_ids=assets,
            first=first,
            skip=skip,
        )
        return {"user": user, "asset_ids": assets or [], "count": len(positions), "data": positions}

    @app_instance.get("/subgraph/open-interest")
    @app_instance.get("/data/subgraph/open-interest")
    async def subgraph_open_interest(
        market_id: str = Query(..., description="Market id to query open interest for"),
        first: int = Query(100, ge=1, le=300),
        skip: int = Query(0, ge=0),
    ):
        oi = await _subgraph_query(subgraph_client.fetch_open_interest, market_id=market_id, first=first, skip=skip)
        return {"market_id": market_id, "count": len(oi), "data": oi}

    @app_instance.get("/subgraph/open-interest/global")
    @app_instance.get("/data/subgraph/open-interest/global")
    async def subgraph_global_open_interest(
        first: int = Query(10, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        oi = await _subgraph_query(subgraph_client.fetch_global_open_interest, first=first, skip=skip)
        return {"count": len(oi), "data": oi}

    @app_instance.get("/subgraph/pnl")
    @app_instance.get("/data/subgraph/pnl")
    async def subgraph_pnl(
        user: str = Query(..., description="User address to query PnL for"),
        token_ids: str | None = Query(default=None, description="Optional comma-separated token ids"),
        first: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        tokens = [item.strip() for item in token_ids.split(",") if item.strip()] if token_ids else None
        pnl = await _subgraph_query(
            subgraph_client.fetch_pnl,
            user=user,
            token_ids=tokens,
            first=first,
            skip=skip,
        )
        return {"user": user, "token_ids": tokens or [], "count": len(pnl), "data": pnl}

    @app_instance.get("/subgraph/activity")
    @app_instance.get("/data/subgraph/activity")
    async def subgraph_activity(
        user: str | None = Query(default=None, description="Optional user filter"),
        condition: str | None = Query(default=None, description="Optional condition filter"),
        first: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        activity = await _subgraph_query(
            subgraph_client.fetch_activity, user=user, condition=condition, first=first, skip=skip
        )
        return {"count": sum(len(v) for v in activity.values()), "data": activity}

    @app_instance.get("/subgraph/market-data")
    @app_instance.get("/data/subgraph/market-data")
    async def subgraph_market_data(
        condition: str | None = Query(default=None, description="Optional condition filter"),
        outcome_index: int | None = Query(default=None, description="Optional outcome index filter"),
        first: int = Query(50, ge=1, le=200),
        skip: int = Query(0, ge=0),
    ):
        data = await _subgraph_query(
            subgraph_client.fetch_market_data,
            condition=condition,
            outcome_index=outcome_index,
            first=first,
            skip=skip,
        )
        return {"count": len(data), "data": data}

    @app_instance.websocket("/subgraph/ws/markets")
    @app_instance.websocket("/data/subgraph/ws/markets")
    async def ws_subgraph_markets(websocket: WebSocket, first: int = 20, skip: int = 0, ids: str | None = None):
        id_list = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_markets,
            first=first,
            skip=skip,
            ids=id_list,
        )

    @app_instance.websocket("/subgraph/ws/trades")
    @app_instance.websocket("/data/subgraph/ws/trades")
    async def ws_subgraph_trades(
        websocket: WebSocket,
        asset_ids: str,
        first: int = 50,
        skip: int = 0,
        user: str | None = None,
    ):
        assets = [item.strip() for item in asset_ids.split(",") if item.strip()]
        if not assets:
            await websocket.accept()
            await websocket.send_json({"error": "asset_ids required"})
            await websocket.close()
            return
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_trades,
            asset_ids=assets,
            first=first,
            skip=skip,
            user=user,
        )

    @app_instance.websocket("/subgraph/ws/positions")
    @app_instance.websocket("/data/subgraph/ws/positions")
    async def ws_subgraph_positions(
        websocket: WebSocket,
        user: str,
        asset_ids: str | None = None,
        first: int = 50,
        skip: int = 0,
    ):
        assets = [item.strip() for item in asset_ids.split(",") if item.strip()] if asset_ids else None
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_positions,
            user=user,
            asset_ids=assets,
            first=first,
            skip=skip,
        )

    @app_instance.websocket("/subgraph/ws/open-interest")
    @app_instance.websocket("/data/subgraph/ws/open-interest")
    async def ws_subgraph_open_interest(
        websocket: WebSocket,
        market_id: str,
        first: int = 100,
        skip: int = 0,
    ):
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_open_interest,
            market_id=market_id,
            first=first,
            skip=skip,
        )

    @app_instance.websocket("/subgraph/ws/open-interest/global")
    @app_instance.websocket("/data/subgraph/ws/open-interest/global")
    async def ws_subgraph_global_open_interest(
        websocket: WebSocket,
        first: int = 10,
        skip: int = 0,
    ):
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_global_open_interest,
            first=first,
            skip=skip,
        )

    @app_instance.websocket("/subgraph/ws/pnl")
    @app_instance.websocket("/data/subgraph/ws/pnl")
    async def ws_subgraph_pnl(
        websocket: WebSocket,
        user: str,
        token_ids: str | None = None,
        first: int = 50,
        skip: int = 0,
    ):
        tokens = [item.strip() for item in token_ids.split(",") if item.strip()] if token_ids else None
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_pnl,
            user=user,
            token_ids=tokens,
            first=first,
            skip=skip,
        )

    @app_instance.websocket("/subgraph/ws/activity")
    @app_instance.websocket("/data/subgraph/ws/activity")
    async def ws_subgraph_activity(
        websocket: WebSocket,
        user: str | None = None,
        condition: str | None = None,
        first: int = 50,
        skip: int = 0,
    ):
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_activity,
            user=user,
            condition=condition,
            first=first,
            skip=skip,
        )

    @app_instance.websocket("/subgraph/ws/market-data")
    @app_instance.websocket("/data/subgraph/ws/market-data")
    async def ws_subgraph_market_data(
        websocket: WebSocket,
        condition: str | None = None,
        outcome_index: int | None = None,
        first: int = 50,
        skip: int = 0,
    ):
        await _subgraph_ws_send(
            websocket,
            subgraph_client.fetch_market_data,
            condition=condition,
            outcome_index=outcome_index,
            first=first,
            skip=skip,
        )

    def _require_control_token(control_header: str | None) -> None:
        if settings.control_token and control_header != settings.control_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid control token")

    def _require_cache() -> None:
        if not state.redis:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="cache unavailable")

    async def _subgraph_query(fn, **kwargs):
        try:
            return await fn(**kwargs)
        except SubgraphNotConfiguredError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"subgraph HTTP {exc.response.status_code}",
            ) from exc
        except SubgraphError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("subgraph query failed", extra={"event": "subgraph.query.error", "error": str(exc)})
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="subgraph query failed") from exc

    async def _subgraph_ws_send(ws: WebSocket, fn, **kwargs):
        await ws.accept()
        try:
            data = await fn(**kwargs)
            await ws.send_json({"data": data})
        except SubgraphNotConfiguredError as exc:
            await ws.send_json({"error": str(exc)})
        except httpx.HTTPStatusError as exc:
            await ws.send_json({"error": f"subgraph HTTP {exc.response.status_code}"})
        except SubgraphError as exc:
            await ws.send_json({"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("subgraph ws failed", extra={"event": "subgraph.ws.error", "error": str(exc)})
            await ws.send_json({"error": "subgraph query failed"})
        finally:
            with suppress(Exception):
                await ws.close()

    @app_instance.get("/stream")
    @app_instance.get("/data/stream")
    async def stream(
        request: Request,
        market_id: str = Query(..., description="Market ID to stream"),
        heartbeat: int = Query(15, ge=1),
        max_events: int | None = Query(default=None, ge=1, description="Optional cap on events (for testing)"),
        assets_ids: str | None = Query(
            default=None, description="Comma-separated asset IDs to subscribe to (CLOB market stream)"
        ),
        symbols: str | None = Query(default=None, description="Comma-separated crypto symbols to subscribe (RTDS)"),
        access_token: str | None = Header(default=None, alias="x-access-token"),
    ):
        _require_access_token(access_token)
        connection_id = f"conn-{uuid4().hex}"
        client_id = request.client.host if request and request.client else "unknown"
        _rate_limit(client_id)
        # Allow on-demand subscription scoping.
        assets: list[str] = []
        assets_supplied = bool(assets_ids)
        if assets_ids:
            assets = [asset.strip() for asset in assets_ids.split(",") if asset.strip()]
        # Default to the requested market_id so websocket streams stay hydrated even without explicit assets_ids.
        if not assets and market_id:
            tokens = state.get_clob_tokens(market_id)
            assets = tokens or [market_id]
            if not assets_supplied:
                fallback_target = "clob_tokens" if tokens else "market_id"
                logger.warning(
                    "assets_ids missing; falling back",
                    extra={
                        "event": "stream.assets.fallback",
                        "market_id": market_id,
                        "transport": "sse",
                        "target": fallback_target,
                        "request_id": connection_id,
                    },
                )
                with suppress(Exception):
                    metrics.assets_fallback.labels(transport="sse", target=fallback_target).inc()
        acquired = state.acquire_assets(assets) if assets else []
        if symbols:
            state.add_rtds_symbols(sym.strip() for sym in symbols.split(","))
        _acquire_connection()
        logger.info(
            "stream connection accepted",
            extra={
                "event": "stream.connection.accepted",
                "request_id": connection_id,
                "transport": "sse",
                "market_id": market_id,
                "assets_supplied": assets_supplied,
                "assets": assets,
                "symbols": symbols,
            },
        )
        pubsub = await state.subscribe(market_id)
        return StreamingResponse(
            _sse_events(
                pubsub,
                heartbeat_seconds=heartbeat,
                max_events=max_events,
                metrics=metrics,
                on_close=lambda: (state.release_assets(acquired), _release_connection()),
            ),
            media_type="text/event-stream",
        )

    @app_instance.websocket("/stream/ws")
    async def stream_ws(
        websocket: WebSocket,
        market_id: str,
        heartbeat: int = 15,
        assets_ids: str | None = None,
        symbols: str | None = None,
    ):
        if settings.access_token and websocket.headers.get("x-access-token") != settings.access_token:
            await websocket.accept()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        connection_id = f"conn-{uuid4().hex}"
        client_id = websocket.client.host if websocket.client else "unknown"
        _rate_limit(client_id)
        assets: list[str] = []
        assets_supplied = bool(assets_ids)
        if assets_ids:
            assets = [asset.strip() for asset in assets_ids.split(",") if asset.strip()]
        if not assets and market_id:
            tokens = state.get_clob_tokens(market_id)
            assets = tokens or [market_id]
            if not assets_supplied:
                fallback_target = "clob_tokens" if tokens else "market_id"
                logger.warning(
                    "assets_ids missing; falling back",
                    extra={
                        "event": "stream.assets.fallback",
                        "market_id": market_id,
                        "transport": "ws",
                        "target": fallback_target,
                        "request_id": connection_id,
                    },
                )
                with suppress(Exception):
                    metrics.assets_fallback.labels(transport="ws", target=fallback_target).inc()
        acquired = state.acquire_assets(assets) if assets else []
        if symbols:
            state.add_rtds_symbols(sym.strip() for sym in symbols.split(","))
        pubsub = await state.subscribe(market_id)
        await websocket.accept()
        _acquire_connection()
        logger.info(
            "ws stream connection accepted",
            extra={
                "event": "stream.connection.accepted",
                "request_id": connection_id,
                "transport": "ws",
                "market_id": market_id,
                "assets_supplied": assets_supplied,
                "assets": assets,
                "symbols": symbols,
            },
        )
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=heartbeat)
                if message and message.get("data"):
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(str(data))
                    with suppress(Exception):
                        metrics.record_delivery("ws", data)
                else:
                    with suppress(Exception):
                        metrics.record_drop("ws", "heartbeat")
                    await websocket.send_json({"event": "ping", "ts": datetime.now(UTC).isoformat()})
        except WebSocketDisconnect:
            return
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning(
                "market websocket error",
                extra={"event": "stream.ws.error", "error": str(exc), "request_id": connection_id},
            )
        finally:
            with suppress(Exception):
                await pubsub.close()
            with suppress(Exception):
                await websocket.close()
            with suppress(Exception):
                state.release_assets(acquired)
            _release_connection()

    @app_instance.websocket("/data/stream/ws")
    async def data_stream_ws(
        websocket: WebSocket,
        market_id: str,
        heartbeat: int = 15,
        assets_ids: str | None = None,
        symbols: str | None = None,
    ):
        await stream_ws(websocket, market_id, heartbeat, assets_ids, symbols)

    @app_instance.get("/clob/latest")
    @app_instance.get("/data/clob/latest")
    async def clob_latest(
        market_id: str = Query(..., description="Market id to fetch the latest cached tick for"),
        outcome: str = Query("0", description="Outcome index or channel (e.g., meta, trades)"),
    ):
        _require_cache()
        payload = await state.get_latest(market_id, outcome)
        if not payload:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no cached tick")
        return {"market_id": market_id, "outcome": outcome, "data": payload}

    @app_instance.get("/clob/book")
    @app_instance.get("/data/clob/book")
    async def clob_book(market_id: str = Query(..., description="Market id to fetch order book snapshot for")):
        _require_cache()
        payload = await state.get_latest(market_id, "meta")
        if not payload:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order book not available")
        return {"market_id": market_id, "data": payload}

    @app_instance.get("/history")
    @app_instance.get("/data/clob/history")
    async def history(
        market_id: str = Query(...),
        outcome: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=settings.history_limit),
    ):
        records = await state.get_history(market_id, str(outcome), limit)
        return {"market_id": market_id, "outcome": outcome, "count": len(records), "data": records}

    @app_instance.get("/subscriptions")
    async def subscriptions():
        return {
            "assets": sorted(state.subscriptions.assets),
            "symbols": sorted(state.rtds_symbols),
            "count": len(state.subscriptions.assets),
            "max": settings.max_subscriptions,
        }

    @app_instance.get("/dashboard")
    async def dashboard():
        fx = await _fx_payload()
        stale_markets = state.stale_markets(settings.market_stale_seconds)
        last_published = {k: v.isoformat() for k, v in state.last_published.items()}
        return {
            "fx": fx,
            "fx_ws_connected": state.fx_ws_connected,
            "subscriptions": {
                "assets": sorted(state.subscriptions.assets),
                "symbols": sorted(state.rtds_symbols),
                "count": len(state.subscriptions.assets),
                "max": settings.max_subscriptions,
            },
            "stale_markets": stale_markets,
            "last_seen": state.snapshot_last_seen(),
            "last_published": last_published,
        }

    @app_instance.get("/control/subscriptions")
    async def control_subscriptions(
        request: Request,
        control_token: str | None = Header(default=None, alias="x-control-token"),
    ):
        _require_control_token(control_token)
        if request.client:
            _rate_limit(request.client.host)
        stale = state.stale_markets(settings.market_stale_seconds)
        return {
            "assets": sorted(state.subscriptions.assets),
            "symbols": sorted(state.rtds_symbols),
            "count": len(state.subscriptions.assets),
            "max": settings.max_subscriptions,
            "stale_markets": stale,
            "last_seen": state.snapshot_last_seen(),
            "last_published": {k: v.isoformat() for k, v in state.last_published.items()},
        }

    @app_instance.post("/control/subscriptions")
    async def control_add_subscriptions(
        assets_ids: list[str] = Query(default_factory=list),
        symbols: list[str] = Query(default_factory=list),
        control_token: str | None = Header(default=None, alias="x-control-token"),
    ):
        _require_control_token(control_token)
        # rate limit by control caller if available
        _rate_limit("control")
        added_assets = state.acquire_assets(assets_ids or [])
        if symbols:
            state.add_rtds_symbols(symbols)
        logger.info(
            "control add subscriptions",
            extra={
                "event": "control.subscriptions.add",
                "assets_added": added_assets,
                "symbols_added": symbols or [],
                "count": len(state.subscriptions.assets),
            },
        )
        return {
            "added_assets": added_assets,
            "assets": sorted(state.subscriptions.assets),
            "symbols": sorted(state.rtds_symbols),
            "count": len(state.subscriptions.assets),
        }

    @app_instance.delete("/control/subscriptions")
    async def control_remove_subscriptions(
        assets_ids: list[str] = Query(default_factory=list),
        symbols: list[str] = Query(default_factory=list),
        control_token: str | None = Header(default=None, alias="x-control-token"),
    ):
        _require_control_token(control_token)
        _rate_limit("control")
        if assets_ids:
            state.force_remove_assets(assets_ids)
        if symbols:
            for sym in symbols:
                state.rtds_symbols.discard(sym)
        logger.info(
            "control remove subscriptions",
            extra={
                "event": "control.subscriptions.remove",
                "assets_removed": assets_ids or [],
                "symbols_removed": symbols or [],
                "count": len(state.subscriptions.assets),
            },
        )
        return {
            "assets": sorted(state.subscriptions.assets),
            "symbols": sorted(state.rtds_symbols),
            "count": len(state.subscriptions.assets),
        }

    return app_instance


app = create_app()
