from enum import Enum

from pydantic import BaseModel, Field


class PartyRole(str, Enum):
    ISSUER = "ISSUER"
    BILL_TO = "BILL_TO"
    REMIT_TO = "REMIT_TO"
    BANK_BENEFICIARY = "BANK_BENEFICIARY"
    OTHER = "OTHER"


class Party(BaseModel):
    role: PartyRole = Field(description="Canonical party role")
    name: str = Field(min_length=1, description="Party name used for sanctions search")
    address: str = Field(default="", description="Full address string if available")
    country: str = Field(default="", description="Country name or code if available")
    registration_number: str = Field(default="", description="Business or registration identifier")
    tax_id: str = Field(default="", description="Tax identifier such as VAT/GST/TPS")
    account_number: str = Field(default="", description="Bank account number if available")
    swift: str = Field(default="", description="SWIFT/BIC code if available")
    iban: str = Field(default="", description="IBAN if available")
    account_holder: str = Field(default="", description="Bank account holder name")
    phone: str = Field(default="", description="Phone number")
    email: str = Field(default="", description="Email address")


class SearchRequest(BaseModel):
    invoice_number: str = Field(min_length=1, description="Invoice number")
    invoice_date: str = Field(min_length=1, description="Invoice date, preferably YYYY-MM-DD")
    currency: str = Field(min_length=1, description="Invoice currency")
    total_amount: float = Field(ge=0, description="Total invoice amount")
    parties: list[Party] = Field(min_length=1, description="Parties extracted from invoice")


class MatchCandidate(BaseModel):
    subject_id: str = Field(description="Matched sanctions subject id")
    matched_party_role: PartyRole = Field(description="Which invoice party produced this match")

    sanction_name: str = Field(description="Matched sanctions subject primary name")
    source_system: str = Field(description="Source system such as OFAC, UN, UK, EU")
    source_dataset: str = Field(description="Source dataset name")

    matched_on: list[str] = Field(description="Match fields contributing to this candidate")
    matched_details: str = Field(default="", description="Compact summary of matched field values")

    base_score: float = Field(description="Base score before country bonus")
    country_bonus: float = Field(description="Country-based bonus score")
    final_score: float = Field(description="Final score after bonus")

    subject_type: str = Field(default="", description="Canonical subject type if available")


class SearchResponse(BaseModel):
    invoice_number: str = Field(description="Echoed invoice number")
    party_count: int = Field(description="Number of parties in request")
    hit_count: int = Field(description="Number of returned candidates")
    candidates: list[MatchCandidate] = Field(description="Matched candidate list")