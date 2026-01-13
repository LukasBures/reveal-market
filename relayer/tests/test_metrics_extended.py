import asyncio
import time

from relayer.metrics import QUEUE_DEADLETTER_TOTAL
from relayer.queue import TxQueue
from relayer.service import TxSendError


class FailingService:
    def __init__(self):
        self.account = type("acct", (), {"address": "0xrelayer"})
        self.escrow = type("escrow", (), {"address": "0xescrow"})
        self.tx_timeout_seconds = 5

    async def commit(self, _payload, *, nonce_override=None, bump_factor=1.0):
        raise TxSendError("boom", permanent=True)

    async def claim(self, _payload, *, nonce_override=None, bump_factor=1.0):
        raise TxSendError("boom", permanent=True)

    async def lock_batches(self, _payload, *, nonce_override=None, bump_factor=1.0):
        raise TxSendError("boom", permanent=True)

    async def health(self):
        return {
            "status": "ok",
            "relayer": self.account.address,
            "escrow": self.escrow.address,
            "chainId": 1,
            "rpc": "http://localhost",
            "latestBlock": 1,
            "blockAgeSeconds": 0,
            "relayerBalanceWei": 1,
            "issues": [],
            "connected": True,
            "escrowOwner": self.account.address,
        }


def test_metrics_exposes_new_counters():
    assert QUEUE_DEADLETTER_TOTAL is not None


def test_deadletter_total_metric_increments(tmp_path):
    service = FailingService()
    queue = TxQueue(str(tmp_path / "queue.db"), service, start_worker=False)

    before = QUEUE_DEADLETTER_TOTAL.labels(action="commit")._value.get()  # noqa: SLF001
    job_id = queue._enqueue_sync(  # noqa: SLF001
        "commit",
        {
            "commitment": "0x" + "0" * 64,
            "user": "0x0000000000000000000000000000000000000001",
            "market": "0x0000000000000000000000000000000000000002",
            "outcome_id": 0,
            "ticket_value_wei": 1,
            "expiry": int(time.time()) + 60,
        },
    )

    result = asyncio.run(queue.process_job(job_id))
    assert result["status"] == "deadletter"
    after = QUEUE_DEADLETTER_TOTAL.labels(action="commit")._value.get()  # noqa: SLF001
    assert after == before + 1
