from pydantic import BaseModel, Field


class CommitRequest(BaseModel):
    user: str
    market: str
    commitment: str
    nonce: int
    expiry: int
    signature: str
    ticket_value_wei: int | None = Field(
        None, description="Optional explicit ticket value if different from default ticket size"
    )


class ClaimRequest(BaseModel):
    market: str
    user: str
    ticket_id: int
    outcome_id: int
    amount: int
    salt: str
    merkle_proof: list[str]
