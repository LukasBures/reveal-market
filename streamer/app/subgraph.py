from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("reveal_market.streamer.subgraph")


class SubgraphError(RuntimeError):
    """Raised when a subgraph request fails or returns errors."""


class SubgraphNotConfiguredError(SubgraphError):
    """Raised when no endpoint is available for the requested data class."""


SubgraphNotConfigured = SubgraphNotConfiguredError


class SubgraphClient:
    """Lightweight GraphQL client for Polymarket subgraphs (Goldsky-backed)."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"content-type": "application/json"}

    def _endpoint_for(self, kind: str) -> str:
        mapping = {
            "markets": self.settings.subgraph_markets_url
            or self.settings.subgraph_trades_url
            or self.settings.subgraph_default_url,
            "orderbook": self.settings.subgraph_markets_url or self.settings.subgraph_default_url,
            "trades": self.settings.subgraph_trades_url
            or self.settings.subgraph_markets_url
            or self.settings.subgraph_default_url,
            "activity": self.settings.subgraph_activity_url or self.settings.subgraph_default_url,
            "positions": self.settings.subgraph_positions_url or self.settings.subgraph_default_url,
            "open_interest": self.settings.subgraph_open_interest_url or self.settings.subgraph_default_url,
            "pnl": self.settings.subgraph_pnl_url or self.settings.subgraph_default_url,
        }
        endpoint = mapping.get(kind) or self.settings.subgraph_default_url
        if not endpoint:
            raise SubgraphNotConfiguredError(f"{kind} subgraph endpoint not configured")
        return str(endpoint)

    async def _execute(self, endpoint: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.settings.subgraph_timeout_seconds, transport=self._transport
        ) as client:
            response = await client.post(
                endpoint, json={"query": query, "variables": variables}, headers=self._headers()
            )
            response.raise_for_status()
        data = response.json()
        errors = data.get("errors")
        if errors:
            raise SubgraphError(str(errors))
        return data.get("data") or {}

    async def _run(self, kind: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        endpoint = self._endpoint_for(kind)
        try:
            return await self._execute(endpoint, query, variables)
        except Exception as exc:
            logger.warning(
                "subgraph query failed",
                extra={"event": "subgraph.query.failed", "kind": kind, "error": str(exc)},
            )
            raise

    async def fetch_markets(
        self,
        *,
        first: int = 20,
        skip: int = 0,
        ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        id_filter = "where: { id_in: $ids }" if ids else ""
        query = f"""
        query Orderbooks($first: Int!, $skip: Int!, $ids: [ID!]) {{
          orderbooks(
            first: $first
            skip: $skip
            {id_filter}
          ) {{
            id
            tradesQuantity
            buysQuantity
            sellsQuantity
            collateralVolume
            scaledCollateralVolume
            collateralBuyVolume
            scaledCollateralBuyVolume
            collateralSellVolume
            scaledCollateralSellVolume
          }}
        }}
        """
        variables = {
            "first": first,
            "skip": skip,
            "ids": ids or None,
        }
        data = await self._run("markets", query, variables)
        return data.get("orderbooks", [])

    async def fetch_trades(
        self,
        *,
        asset_ids: list[str],
        first: int = 50,
        skip: int = 0,
        user: str | None = None,
    ) -> list[dict[str, Any]]:
        if not asset_ids:
            raise SubgraphError("asset_ids required for trades query")
        user_filter = (
            """
              and: [
                { or: [ { maker: $user }, { taker: $user } ] }
              ]
            """
            if user
            else ""
        )
        query = f"""
        query Trades(
          $assets: [String!],
          $first: Int!,
          $skip: Int!,
          $user: String
        ) {{
          orderFilledEvents(
            first: $first
            skip: $skip
            where: {{
              or: [
                {{ makerAssetId_in: $assets }}
                {{ takerAssetId_in: $assets }}
              ]
              {user_filter}
            }}
            orderBy: timestamp
            orderDirection: desc
          ) {{
            id
            transactionHash
            timestamp
            orderHash
            maker
            taker
            makerAssetId
            takerAssetId
            makerAmountFilled
            takerAmountFilled
            fee
          }}
        }}
        """
        variables = {
            "assets": asset_ids or [],
            "first": first,
            "skip": skip,
            "user": user,
        }
        data = await self._run("trades", query, variables)
        return data.get("orderFilledEvents", [])

    async def fetch_positions(
        self,
        *,
        user: str,
        asset_ids: list[str] | None = None,
        first: int = 50,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        asset_filter = "asset_: { id_in: $assetIds }" if asset_ids else ""
        query = f"""
        query Positions($user: String!, $assetIds: [String!], $first: Int!, $skip: Int!) {{
          userBalances(
            first: $first
            skip: $skip
            where: {{
              user: $user
              {asset_filter}
            }}
          ) {{
            id
            user
            balance
            asset {{
              id
              condition
              outcomeIndex
              complement
            }}
          }}
        }}
        """
        variables = {"user": user, "assetIds": asset_ids or None, "first": first, "skip": skip}
        data = await self._run("positions", query, variables)
        return data.get("userBalances", [])

    async def fetch_open_interest(self, *, market_id: str, first: int = 100, skip: int = 0) -> list[dict[str, Any]]:
        query = """
        query OpenInterest($marketId: String!, $first: Int!, $skip: Int!) {
          marketOpenInterests(
            first: $first
            skip: $skip
            where: { id_in: [$marketId] }
          ) {
            id
            amount
            openInterestUSD
            openInterestUsd
          }
        }
        """
        variables = {"marketId": market_id, "first": first, "skip": skip}
        data = await self._run("open_interest", query, variables)
        return data.get("marketOpenInterests", [])

    async def fetch_pnl(
        self, *, user: str, token_ids: list[str] | None = None, first: int = 50, skip: int = 0
    ) -> list[dict[str, Any]]:
        query = """
        query Pnl($user: String!, $tokenIds: [BigInt!], $first: Int!, $skip: Int!) {
          userPositions(
            first: $first
            skip: $skip
            where: { user: $user, tokenId_in: $tokenIds }
            orderBy: tokenId
            orderDirection: asc
          ) {
            id
            user
            tokenId
            amount
            avgPrice
            realizedPnl
            totalBought
          }
        }
        """
        variables = {"user": user, "tokenIds": token_ids or None, "first": first, "skip": skip}
        data = await self._run("pnl", query, variables)
        return data.get("userPositions", [])

    async def fetch_global_open_interest(self, *, first: int = 10, skip: int = 0) -> list[dict[str, Any]]:
        query = """
        query GlobalOpenInterest($first: Int!, $skip: Int!) {
          globalOpenInterests(first: $first, skip: $skip) {
            id
            amount
          }
        }
        """
        data = await self._run("open_interest", query, {"first": first, "skip": skip})
        return data.get("globalOpenInterests", [])

    async def fetch_activity(
        self, *, user: str | None = None, condition: str | None = None, first: int = 50, skip: int = 0
    ) -> dict[str, list[dict[str, Any]]]:
        filters: list[str] = []
        if user:
            filters.append("stakeholder: $user")
        if condition:
            filters.append("condition: $condition")
        where = ""
        if filters:
            where = f"where: {{ {' , '.join(filters)} }}"
        redemption_filters: list[str] = []
        if user:
            redemption_filters.append("redeemer: $user")
        if condition:
            redemption_filters.append("condition: $condition")
        redemption_where = ""
        if redemption_filters:
            redemption_where = f"where: {{ {' , '.join(redemption_filters)} }}"
        query = f"""
        query Activity($user: String, $condition: String, $first: Int!, $skip: Int!) {{
          splits(first: $first, skip: $skip, {where}) {{
            id
            timestamp
            stakeholder
            condition
            amount
          }}
          merges(first: $first, skip: $skip, {where}) {{
            id
            timestamp
            stakeholder
            condition
            amount
          }}
          redemptions(first: $first, skip: $skip, {redemption_where}) {{
            id
            timestamp
            redeemer
            condition
            indexSets
            payout
          }}
        }}
        """
        data = await self._run("activity", query, {"user": user, "condition": condition, "first": first, "skip": skip})
        return {
            "splits": data.get("splits", []),
            "merges": data.get("merges", []),
            "redemptions": data.get("redemptions", []),
        }

    async def fetch_market_data(
        self, *, condition: str | None = None, outcome_index: int | None = None, first: int = 50, skip: int = 0
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if condition:
            filters.append("condition: $condition")
        if outcome_index is not None:
            filters.append("outcomeIndex: $outcomeIndex")
        where = f"where: {{ {' , '.join(filters)} }}" if filters else ""
        query = f"""
        query MarketData($condition: String, $outcomeIndex: BigInt, $first: Int!, $skip: Int!) {{
          marketDatas(first: $first, skip: $skip, {where}) {{
            id
            condition
            outcomeIndex
          }}
        }}
        """
        variables = {
            "condition": condition,
            "outcomeIndex": outcome_index,
            "first": first,
            "skip": skip,
        }
        data = await self._run("orderbook", query, variables)
        return data.get("marketDatas", [])
