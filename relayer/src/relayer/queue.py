import asyncio
import contextlib
import json
import sqlite3
import threading
import time
from collections.abc import Mapping
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from structlog import get_logger
from web3.exceptions import Web3Exception

from .metrics import (
    FEE_BUMP_FACTOR,
    QUEUE_DEADLETTER_DEPTH,
    QUEUE_DEADLETTER_TOTAL,
    QUEUE_DEPTH,
    QUEUE_ERROR_REASONS,
    QUEUE_OLDEST_BACKLOG_AGE_SECONDS,
    QUEUE_OUTCOMES,
)
from .service import IngestDeliveryError, RelayerService, TxSendError

logger = get_logger()


class TxQueue:
    def __init__(
        self,
        sqlite_path: str,
        service: RelayerService,
        *,
        dsn: str | None = None,
        poll_seconds: float = 1.0,
        max_attempts: int = 5,
        max_payload_bytes: int = 131072,
        fee_bump_percent: float = 0.15,
        start_worker: bool = True,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.dsn = dsn
        self.use_postgres = dsn is not None
        self.service = service
        self.poll_seconds = poll_seconds
        self.max_attempts = max_attempts
        self.max_payload_bytes = max_payload_bytes
        self.fee_bump_percent = fee_bump_percent
        self._lock = threading.Lock()
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._init_db()
        self._start_worker_flag = start_worker

    async def start(self) -> None:
        if not self._start_worker_flag:
            return
        if self._worker and not self._worker.done():
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._run_async())

    async def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_pg(self) -> psycopg.Connection:
        if not self.dsn:
            raise RuntimeError("Postgres DSN not configured")
        return psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)  # type: ignore[arg-type]

    def _connect(self):
        return self._connect_pg() if self.use_postgres else self._connect_sqlite()

    def _init_db(self) -> None:
        with self._connect() as conn:
            if self.use_postgres:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id BIGSERIAL PRIMARY KEY,
                        action TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL,
                        last_error TEXT,
                        tx_hash TEXT,
                        nonce BIGINT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
            else:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL,
                        last_error TEXT,
                        tx_hash TEXT,
                        nonce INTEGER,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
        self._update_depth()

    def _enqueue_sync(self, action: str, payload: Mapping[str, Any]) -> int:
        now = int(time.time())
        payload_json = json.dumps(payload)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise ValueError("payload_too_large")
        with self._lock, self._connect() as conn:
            if self.use_postgres:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (action, payload, status, attempts, created_at, updated_at)
                    VALUES (%s, %s, 'pending', 0, %s, %s)
                    RETURNING id
                    """,
                    (action, payload_json, now, now),
                )
                job_id = int(cur.fetchone()["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (action, payload, status, attempts, created_at, updated_at)
                    VALUES (?, ?, 'pending', 0, ?, ?)
                    """,
                    (action, payload_json, now, now),
                )
                job_id = int(cur.lastrowid)
        self._update_depth()
        return job_id

    async def enqueue(self, action: str, payload: Mapping[str, Any]) -> int:
        return await asyncio.to_thread(self._enqueue_sync, action, payload)

    async def enqueue_and_process(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        job_id = await self.enqueue(action, payload)
        result = await self.process_job(job_id)
        if result.get("status") == "empty":
            raise RuntimeError("queue_empty_after_enqueue")
        return result

    def _reserve_job_sync(self, job_id: int | None = None) -> dict[str, Any] | None:
        now = int(time.time())
        if self.use_postgres:
            with self._lock, self._connect() as conn:
                if job_id is None:
                    cur = conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'running', attempts = attempts + 1, updated_at = %s
                        WHERE id = (
                            SELECT id FROM jobs
                            WHERE status = 'pending'
                            ORDER BY id
                            FOR UPDATE SKIP LOCKED
                            LIMIT 1
                        )
                        RETURNING *
                        """,
                        (now,),
                    )
                else:
                    cur = conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'running', attempts = attempts + 1, updated_at = %s
                        WHERE id = %s AND status = 'pending'
                        RETURNING *
                        """,
                        (now, job_id),
                    )
                row = cur.fetchone()
                return dict(row) if row else None
        with self._lock, self._connect() as conn:
            target_id: int | None = None
            if job_id is None:
                row = conn.execute("SELECT id FROM jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1").fetchone()
                if row is None:
                    return None
                target_id = int(row["id"])
            else:
                target_id = int(job_id)

            updated = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, target_id),
            )
            if int(updated.rowcount or 0) != 1:
                return None
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (target_id,)).fetchone()
            if claimed is None:
                return None
            return {k: claimed[k] for k in claimed.keys()}

    async def process_job(self, job_id: int | None = None) -> dict[str, Any]:
        row = await asyncio.to_thread(self._reserve_job_sync, job_id)
        if row is None:
            if job_id is None:
                return {"status": "empty"}
            raise RuntimeError(f"job {job_id} not found or not pending")

        attempts = int(row["attempts"])
        payload: dict[str, Any] = json.loads(row["payload"])
        nonce = row.get("nonce")
        bump_factor = (1 + self.fee_bump_percent) ** max(0, attempts - 1)
        try:
            FEE_BUMP_FACTOR.set(bump_factor)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("relayer.metrics.fee_bump_update_failed", error=str(exc))
        summary = self._payload_summary(row["action"], payload)
        logger.info(
            "queue.job.start",
            job_id=row["id"],
            action=row["action"],
            attempts=attempts,
            bump_factor=round(bump_factor, 4),
            nonce_override=nonce,
            **summary,
        )

        tx_hash: str | None = None
        nonce_used: int | None = int(nonce) if nonce is not None else None
        try:
            # Drop stale commit authorizations so the queue does not get stuck retrying expired jobs.
            if row["action"] == "commit":
                expiry = payload.get("expiry")
                if expiry is not None and int(expiry) < int(time.time()):
                    await asyncio.to_thread(
                        self._mark_failure,
                        row["id"],
                        "deadletter",
                        attempts,
                        "commit_expired",
                        nonce,
                    )
                    QUEUE_OUTCOMES.labels(action=row["action"], status="deadletter").inc()
                    logger.warning(
                        "queue.commit.expired",
                        job_id=row["id"],
                        now=int(time.time()),
                        **summary,
                    )
                    return {"jobId": row["id"], "status": "deadletter", "error": "commit_expired"}

            if row["action"] == "commit":
                result = await self.service.commit(payload, nonce_override=nonce, bump_factor=bump_factor)
            elif row["action"] == "claim":
                result = await self.service.claim(payload, nonce_override=nonce, bump_factor=bump_factor)
            elif row["action"] == "lock_batches":
                result = await self.service.lock_batches(payload, nonce_override=nonce, bump_factor=bump_factor)
            else:
                raise RuntimeError(f"unknown action {row['action']}")

            job_id = int(row["id"])
            tx_hash = cast(str | None, result.get("txHash"))
            if tx_hash and not str(tx_hash).startswith("0x"):
                tx_hash = f"0x{tx_hash}"
            nonce_used_raw = result.get("nonce", nonce)
            nonce_used = int(nonce_used_raw) if nonce_used_raw is not None else None
            if row["action"] == "commit" and hasattr(self.service, "push_commit_ingest"):
                await self.service.push_commit_ingest(payload, tx_hash=tx_hash)
            if row["action"] == "claim" and hasattr(self.service, "push_settlement_ingest"):
                await self.service.push_settlement_ingest(payload, tx_hash=tx_hash)
            if row["action"] == "lock_batches" and hasattr(self.service, "push_settlement_ingest"):
                await self.service.push_settlement_ingest(payload, tx_hash=tx_hash)
            await asyncio.to_thread(self._mark_complete, job_id, tx_hash, nonce_used)
            QUEUE_OUTCOMES.labels(action=row["action"], status="succeeded").inc()
            logger.info(
                "queue.job.succeeded",
                job_id=job_id,
                action=row["action"],
                tx_hash=tx_hash,
                nonce=nonce_used,
                attempts=attempts,
                **summary,
            )
            return {"jobId": job_id, "status": "succeeded", "txHash": tx_hash, "nonce": nonce_used}
        except (TxSendError, IngestDeliveryError, Web3Exception, ValueError, RuntimeError) as err:
            nonce_to_store = nonce_used if nonce_used is not None else nonce
            if isinstance(err, TxSendError) and err.nonce is not None:
                nonce_to_store = err.nonce
            permanent = isinstance(err, TxSendError) and getattr(err, "permanent", False)
            if isinstance(err, IngestDeliveryError):
                next_status = "deadletter"
            else:
                next_status = "deadletter" if permanent else "pending" if attempts < self.max_attempts else "deadletter"
            logger.warning(
                "queue.job.error",
                job_id=row["id"],
                action=row["action"],
                attempts=attempts,
                next_status=next_status,
                error=str(err),
                nonce=nonce_to_store,
                tx_hash=tx_hash,
                **summary,
            )
            await asyncio.to_thread(
                self._mark_failure,
                row["id"],
                next_status,
                attempts,
                str(err),
                nonce_to_store,
                tx_hash,
            )
            QUEUE_OUTCOMES.labels(action=row["action"], status=next_status).inc()
            QUEUE_ERROR_REASONS.labels(action=row["action"], reason=self._error_reason(err)).inc()
            if next_status == "deadletter":
                logger.error(
                    "queue.deadletter",
                    job_id=row["id"],
                    action=row["action"],
                    attempts=attempts,
                    error=str(err),
                    nonce=nonce_to_store,
                    tx_hash=tx_hash,
                    **summary,
                )
                QUEUE_DEADLETTER_TOTAL.labels(action=row["action"]).inc()
            else:
                logger.warning(
                    "queue.retry_scheduled",
                    job_id=row["id"],
                    action=row["action"],
                    attempts=attempts,
                    error=str(err),
                    nonce=nonce_to_store,
                    tx_hash=tx_hash,
                    next_status=next_status,
                    **summary,
                )
            return {
                "jobId": row["id"],
                "status": next_status,
                "txHash": tx_hash,
                "nonce": nonce_to_store,
                "error": str(err),
            }

    def _mark_complete(self, job_id: int, tx_hash: str | None, nonce: int | None) -> None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            if self.use_postgres:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'succeeded', tx_hash = %s, nonce = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (tx_hash, nonce, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'succeeded', tx_hash = ?, nonce = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (tx_hash, nonce, now, job_id),
                )
        self._update_depth()

    def _mark_failure(
        self,
        job_id: int,
        status: str,
        attempts: int,
        error: str,
        nonce: int | None,
        tx_hash: str | None = None,
    ) -> None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            if self.use_postgres:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = %s, attempts = %s, last_error = %s, nonce = %s,
                        tx_hash = COALESCE(%s, tx_hash), updated_at = %s
                    WHERE id = %s
                    """,
                    (status, attempts, error, nonce, tx_hash, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, attempts = ?, last_error = ?, nonce = ?,
                        tx_hash = COALESCE(?, tx_hash), updated_at = ?
                    WHERE id = ?
                    """,
                    (status, attempts, error, nonce, tx_hash, now, job_id),
                )
        self._update_depth()

    async def _run_async(self) -> None:
        while not self._stop.is_set():
            try:
                result = await self.process_job()
                if result.get("status") == "empty":
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                    except TimeoutError:
                        continue
            except asyncio.CancelledError:
                return
            except Exception as err:
                logger.exception("queue.worker.error", error=str(err))
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    continue

    def _get_queue_stats_sync(self) -> dict[str, Any]:
        now = int(time.time())
        query = """
            SELECT
                SUM(CASE WHEN status IN ('pending', 'running') THEN 1 ELSE 0 END) AS depth,
                SUM(CASE WHEN status = 'deadletter' THEN 1 ELSE 0 END) AS deadletter,
                MIN(CASE WHEN status IN ('pending', 'running') THEN created_at ELSE NULL END) AS oldest_backlog
            FROM jobs
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(query).fetchone()
        if not row:
            return {"depth": 0, "deadletter": 0, "oldestBacklogAgeSeconds": None}
        depth = int(row["depth"] or 0)
        deadletter = int(row["deadletter"] or 0)
        oldest_backlog_raw = row["oldest_backlog"]
        oldest_backlog_age = None
        if oldest_backlog_raw is not None:
            oldest_backlog_age = max(0, now - int(oldest_backlog_raw))
        return {
            "depth": depth,
            "deadletter": deadletter,
            "oldestBacklogAgeSeconds": oldest_backlog_age,
        }

    async def get_stats(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_queue_stats_sync)

    def _update_depth(self) -> None:
        stats = self._get_queue_stats_sync()
        QUEUE_DEPTH.set(stats["depth"])
        QUEUE_DEADLETTER_DEPTH.set(stats["deadletter"])
        oldest_backlog_age = stats["oldestBacklogAgeSeconds"]
        QUEUE_OLDEST_BACKLOG_AGE_SECONDS.set(oldest_backlog_age or 0)

    def _list_deadletter_sync(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, action, attempts, last_error, nonce, payload, updated_at
                FROM jobs WHERE status = 'deadletter' ORDER BY id ASC
                """
            ).fetchall()
            return [
                {
                    "jobId": int(row["id"]),
                    "action": row["action"],
                    "attempts": int(row["attempts"]),
                    "last_error": row["last_error"],
                    "nonce": row["nonce"],
                    "payload": json.loads(row["payload"]),
                    "updated_at": int(row["updated_at"]),
                }
                for row in rows
            ]

    async def list_deadletter(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_deadletter_sync)

    def _get_job_sync(self, job_id: int) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = (
                conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
                if self.use_postgres
                else conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            )
            if row is None:
                raise RuntimeError("job_not_found")
            return {
                "jobId": int(row["id"]),
                "status": row["status"],
                "txHash": row["tx_hash"],
                "nonce": row["nonce"],
                "error": row["last_error"],
                "attempts": row["attempts"],
            }

    async def get_job(self, job_id: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    async def replay_job(self, job_id: int) -> dict[str, Any]:
        def _replay():
            with self._lock, self._connect() as conn:
                row = (
                    conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
                    if self.use_postgres
                    else conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
                )
                if row is None:
                    raise RuntimeError("job_not_found")
                if row["status"] != "deadletter":
                    raise RuntimeError("job_not_deadletter")
                if self.use_postgres:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'pending', attempts = 0, last_error = NULL, updated_at = %s
                        WHERE id = %s
                        """,
                        (int(time.time()), job_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'pending', attempts = 0, last_error = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (int(time.time()), job_id),
                    )

        await asyncio.to_thread(_replay)
        await asyncio.to_thread(self._update_depth)
        return {"jobId": job_id, "status": "pending"}

    async def purge_job(self, job_id: int) -> dict[str, Any]:
        def _purge():
            with self._lock, self._connect() as conn:
                row = (
                    conn.execute("SELECT status FROM jobs WHERE id = %s", (job_id,)).fetchone()
                    if self.use_postgres
                    else conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
                )
                if row is None:
                    raise RuntimeError("job_not_found")
                if row["status"] != "deadletter":
                    raise RuntimeError("job_not_deadletter")
                if self.use_postgres:
                    conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
                else:
                    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

        await asyncio.to_thread(_purge)
        await asyncio.to_thread(self._update_depth)
        return {"jobId": job_id, "status": "purged"}

    def _payload_summary(self, action: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Surface small identifying fields in logs for tracing."""

        summary: dict[str, Any] = {}
        if action == "commit":
            summary["user"] = payload.get("user")
            summary["market"] = payload.get("market")
            summary["outcome_id"] = payload.get("outcome_id")
            summary["event_id"] = payload.get("event_id") or payload.get("market_id")
            summary["ticket_value_wei"] = payload.get("ticket_value_wei")
            summary["expiry"] = payload.get("expiry")
        elif action == "claim":
            summary["user"] = payload.get("user")
            summary["market"] = payload.get("market")
            summary["ticket_id"] = payload.get("ticket_id")
            summary["outcome_id"] = payload.get("outcome_id")
            summary["amount"] = payload.get("amount")
        elif action == "lock_batches":
            summary["market"] = payload.get("market")
            summary["event_id"] = payload.get("event_id") or payload.get("market_id")
            tickets = payload.get("tickets")
            if isinstance(tickets, list):
                summary["ticket_count"] = len(tickets)
            if payload.get("batch_roots"):
                summary["batch_count"] = len(payload.get("batch_roots") or [])
        return summary

    @staticmethod
    def _error_reason(err: Exception) -> str:
        if isinstance(err, TxSendError):
            return err.kind or "tx_send_error"
        return err.__class__.__name__
