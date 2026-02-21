from pydantic import BaseModel, Field, model_validator


class CommitRequest(BaseModel):
    user: str
    market: str
    commitment: str
    nonce: int
    expiry: int
    chain_id: int = Field(..., description="Chain id the CommitAuth was built for")
    ticket_value_wei: int = Field(..., description="Ticket value encoded into the authorization")
    amount_wei: int | None = Field(default=None, description="Net amount used in commitment hashing")
    payout_wei: int | None = Field(default=None, description="Payout amount used in commitment hashing")
    signature: str
    event_id: str | None = Field(default=None, description="Optional market/event identifier for ingest")
    market_id: str | None = Field(default=None, description="Optional market id for ingest")
    outcome_id: int | None = Field(default=None, description="Outcome id for ingest")
    salt: str | None = Field(default=None, description="Commitment salt for ingest")
    ticket_id: int | None = Field(default=None, description="Leaf index/ticket id for ingest")
    merkle_path: list[str] | None = Field(default=None, description="Merkle proof for ingest (optional)")


class ClaimRequest(BaseModel):
    market: str
    user: str
    ticket_id: int
    outcome_id: int
    amount: int
    payout: int
    salt: str
    merkle_proof: list[str] = Field(..., max_length=64, description="Merkle siblings (bounded)")
    merkle_root: str | None = Field(default=None, description="Optional root for ingest")
    batch_roots: list[str] | None = Field(default=None, description="Optional batch roots for ingest")
    batch_counts: list[int] | None = Field(default=None, description="Optional batch counts for ingest")
    commitments_count: int | None = Field(default=None, description="Optional count for ingest")
    pool_total_yes: int | None = Field(default=None, description="Optional total yes for ingest")
    pool_total_no: int | None = Field(default=None, description="Optional total no for ingest")
    total_escrow: int | None = Field(default=None, description="Optional total escrow for ingest")
    total_liability: int | None = Field(default=None, description="Optional total liability for ingest")
    rake_bps: int | None = Field(default=None, description="Optional rake bps for ingest")
    proof_request_id: str | None = Field(default=None, description="Optional proof request id for ingest")
    event_id: str | None = Field(default=None, description="Optional event/market id for ingest")


class LockTicket(BaseModel):
    ticket_id: int = Field(..., description="Ticket id/leaf index")
    outcome_id: int = Field(..., description="Outcome id for leaf hashing")
    amount: int = Field(..., description="Net amount used in the Poseidon leaf")
    payout: int = Field(..., description="Payout amount used in the Poseidon leaf")
    user: str = Field(..., description="User address for leaf hashing")
    salt: str = Field(..., description="Salt for leaf hashing")
    leaf: str | None = Field(default=None, description="Optional precomputed commitment leaf")


class LockBatchesRequest(BaseModel):
    market: str
    tickets: list[LockTicket] = Field(..., max_length=256, description="Bounded ticket list for batch locking")
    relayer_sig: str | None = Field(default=None, description="Optional relayer signature")
    event_id: str | None = Field(default=None, description="Optional event/market id for ingest")
    market_id: str | None = Field(default=None, description="Optional market id for ingest")

    @model_validator(mode="after")
    def _require_market_identifier(self) -> "LockBatchesRequest":
        if not (self.event_id or self.market_id):
            raise ValueError("event_id or market_id required")
        return self
