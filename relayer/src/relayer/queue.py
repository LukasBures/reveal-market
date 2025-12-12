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

from .metrics import QUEUE_DEPTH, QUEUE_OUTCOMES
from .service import RelayerService, TxSendError

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
        fee_bump_percent: float = 0.15,
        start_worker: bool = True,
    ) -> None:
        self.sqlite_path = sqlite_path
        self.dsn = dsn
        self.use_postgres = dsn is not None
        self.service = service
        self.poll_seconds = poll_seconds
        self.max_attempts = max_attempts
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
                conn.execute("UPDATE jobs SET status = 'pending' WHERE status = 'running'")
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
                conn.execute("UPDATE jobs SET status = 'pending' WHERE status = 'running'")
        self._update_depth()

    def _enqueue_sync(self, action: str, payload: Mapping[str, Any]) -> int:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            if self.use_postgres:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (action, payload, status, attempts, created_at, updated_at)
                    VALUES (%s, %s, 'pending', 0, %s, %s)
                    RETURNING id
                    """,
                    (action, json.dumps(payload), now, now),
                )
                job_id = int(cur.fetchone()["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (action, payload, status, attempts, created_at, updated_at)
                    VALUES (?, ?, 'pending', 0, ?, ?)
                    """,
                    (action, json.dumps(payload), now, now),
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
                        WHERE id = %s AND status IN ('pending', 'running')
                        RETURNING *
                        """,
                        (now, job_id),
                    )
                row = cur.fetchone()
                return dict(row) if row else None
        with self._lock, self._connect() as conn:
            if job_id is None:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status IN ('pending', 'running') ORDER BY id ASC LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"]) + 1
            if row["status"] not in ("pending", "running"):
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', attempts = ?, updated_at = ? WHERE id = ?",
                (attempts, now, row["id"]),
            )
            row_dict = {k: row[k] for k in row.keys()}
            row_dict["attempts"] = attempts
            return row_dict

    def _process_job_sync(self, job_id: int | None = None) -> dict[str, Any]:
        row = self._reserve_job_sync(job_id)
        if row is None:
            if job_id is None:
                return {"status": "empty"}
            raise RuntimeError(f"job {job_id} not found or not pending")

        attempts = int(row["attempts"])
        payload: dict[str, Any] = json.loads(row["payload"])
        nonce = row.get("nonce")
        bump_factor = (1 + self.fee_bump_percent) ** max(0, attempts - 1)

        try:
            if row["action"] == "commit":
                result = self.service.commit(payload, nonce_override=nonce, bump_factor=bump_factor)
            elif row["action"] == "claim":
                result = self.service.claim(payload, nonce_override=nonce, bump_factor=bump_factor)
            else:
                raise RuntimeError(f"unknown action {row['action']}")

            job_id = int(row["id"])
            tx_hash = cast(str | None, result.get("txHash"))
            nonce_used_raw = result.get("nonce", nonce)
            nonce_used = int(nonce_used_raw) if nonce_used_raw is not None else None
            self._mark_complete(job_id, tx_hash, nonce_used)
            QUEUE_OUTCOMES.labels(action=row["action"], status="succeeded").inc()
            return {"jobId": job_id, "status": "succeeded", "txHash": tx_hash, "nonce": nonce_used}
        except (TxSendError, Web3Exception, ValueError, RuntimeError) as err:
            nonce_to_store = nonce
            if isinstance(err, TxSendError) and err.nonce is not None:
                nonce_to_store = err.nonce
            next_status = "pending" if attempts < self.max_attempts else "deadletter"
            self._mark_failure(row["id"], next_status, attempts, str(err), nonce_to_store)
            QUEUE_OUTCOMES.labels(action=row["action"], status=next_status).inc()
            if next_status == "deadletter":
                logger.error("queue.deadletter", job_id=row["id"], action=row["action"], error=str(err))
            else:
                logger.warning(
                    "queue.retry_scheduled",
                    job_id=row["id"],
                    action=row["action"],
                    attempts=attempts,
                    error=str(err),
                )
            return {"jobId": row["id"], "status": next_status, "nonce": nonce_to_store, "error": str(err)}

    async def process_job(self, job_id: int | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._process_job_sync, job_id)

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

    def _mark_failure(self, job_id: int, status: str, attempts: int, error: str, nonce: int | None) -> None:
        now = int(time.time())
        with self._lock, self._connect() as conn:
            if self.use_postgres:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = %s, attempts = %s, last_error = %s, nonce = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (status, attempts, error, nonce, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, attempts = ?, last_error = ?, nonce = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, attempts, error, nonce, now, job_id),
                )
        self._update_depth()

    async def _run_async(self) -> None:
        try:
            while not self._stop.is_set():
                result = await self.process_job()
                if result.get("status") == "empty":
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                    except TimeoutError:
                        continue
        except asyncio.CancelledError:
            return

    def _update_depth(self) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM jobs WHERE status IN ('pending', 'running')").fetchone()
            depth = int(row["cnt"]) if row else 0
            QUEUE_DEPTH.set(depth)

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
        self._update_depth()
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
        self._update_depth()
        return {"jobId": job_id, "status": "purged"}
