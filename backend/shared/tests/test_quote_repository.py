from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from shared import models, repository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_quote(
    session: Session,
    quote_id: str,
    *,
    status: models.QuoteStatusEnum = models.QuoteStatusEnum.ISSUED,
    expires_at: datetime,
    created_at: datetime | None = None,
    stake_zen: Decimal = Decimal("1"),
    market_id: str | None = None,
    user_id: str | None = None,
) -> models.Quote:
    payload = {
        "quote_id": quote_id,
        "status": status.value,
        "payload": {"id": quote_id},
        "stake_zen": stake_zen,
        "stake_wei": stake_zen * Decimal(10**18),
        "fx_scaled": 1,
        "zen_usd": float(stake_zen),
        "expires_at": expires_at,
        "market_id": market_id,
        "user_id": user_id,
    }
    if created_at:
        payload["created_at"] = created_at
    return repository.create_quote(session, payload)


def test_expire_stale_quotes_marks_only_issued():
    session = _session()
    now = datetime(2024, 1, 1, tzinfo=UTC)

    expired = _seed_quote(session, "q-expired", expires_at=now - timedelta(seconds=1))
    _seed_quote(
        session,
        "q-future",
        expires_at=now + timedelta(seconds=30),
        status=models.QuoteStatusEnum.ISSUED,
    )
    _seed_quote(
        session,
        "q-consumed",
        expires_at=now - timedelta(seconds=1),
        status=models.QuoteStatusEnum.CONSUMED,
    )
    session.commit()

    changed = repository.expire_stale_quotes(session, now=now)
    session.commit()
    session.refresh(expired)

    assert changed == 1
    assert expired.status == models.QuoteStatusEnum.EXPIRED.value

    statuses = {q.quote_id: q.status for q in session.query(models.Quote).all()}
    assert statuses["q-future"] == models.QuoteStatusEnum.ISSUED.value
    assert statuses["q-consumed"] == models.QuoteStatusEnum.CONSUMED.value


def test_sum_quote_stakes_respects_window_and_filters():
    session = _session()
    now = datetime.now(tz=UTC)
    recent = now - timedelta(seconds=30)
    old = now - timedelta(seconds=400)

    _seed_quote(
        session,
        "q1",
        expires_at=now + timedelta(hours=1),
        created_at=recent,
        stake_zen=Decimal("1.5"),
        market_id="m1",
        user_id="u1",
    )
    _seed_quote(
        session,
        "q2",
        expires_at=now + timedelta(hours=1),
        created_at=old,
        stake_zen=Decimal("2.0"),
        market_id="m1",
        user_id="u1",
    )
    _seed_quote(
        session,
        "q3",
        expires_at=now + timedelta(hours=1),
        created_at=recent,
        stake_zen=Decimal("3.0"),
        market_id="m2",
        user_id="u1",
        status=models.QuoteStatusEnum.CONSUMED,
    )
    session.commit()

    window_sum = repository.sum_quote_stakes(session, market_id="m1", user_id="u1", window_seconds=300, statuses=None)
    # Only q1 is within the window for market m1 + user u1.
    assert window_sum == Decimal("1.5")

    all_status_sum = repository.sum_quote_stakes(
        session, market_id="m2", user_id="u1", window_seconds=300, statuses={models.QuoteStatusEnum.CONSUMED.value}
    )
    assert all_status_sum == Decimal("3.0")
