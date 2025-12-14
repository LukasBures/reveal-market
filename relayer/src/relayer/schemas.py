from pydantic import BaseModel, Field


class CommitRequest(BaseModel):
    user: str
    market: str
    commitment: str
    nonce: int
    expiry: int
    chain_id: int = Field(..., description="Chain id the CommitAuth was built for")
    ticket_value_wei: int = Field(..., description="Ticket value encoded into the authorization")
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
    salt: str
    merkle_proof: list[str]
    merkle_root: str | None = Field(default=None, description="Optional root for ingest")
    commitments_count: int | None = Field(default=None, description="Optional count for ingest")
    pool_total_yes: int | None = Field(default=None, description="Optional total yes for ingest")
    pool_total_no: int | None = Field(default=None, description="Optional total no for ingest")
    total_escrow: int | None = Field(default=None, description="Optional total escrow for ingest")
    total_liability: int | None = Field(default=None, description="Optional total liability for ingest")
    rake_bps: int | None = Field(default=None, description="Optional rake bps for ingest")
    proof_request_id: str | None = Field(default=None, description="Optional proof request id for ingest")
    event_id: str | None = Field(default=None, description="Optional event/market id for ingest")
