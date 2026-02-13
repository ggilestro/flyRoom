"""Pydantic schemas for crosses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import CrossOutcomeType, CrossStatus


class CrossBase(BaseModel):
    """Base schema for crosses."""

    name: str | None = Field(None, max_length=255)
    parent_female_id: str
    parent_male_id: str
    planned_date: date | None = None
    notes: str | None = None


class CrossCreate(CrossBase):
    """Schema for creating a cross."""

    target_genotype: str | None = None
    flip_days: int = Field(5, ge=1, le=30)
    virgin_collection_days: int = Field(12, ge=1, le=60)
    outcome_type: CrossOutcomeType = CrossOutcomeType.EPHEMERAL

    @model_validator(mode="after")
    def validate_outcome_requires_genotype(self) -> "CrossCreate":
        """Require target_genotype when outcome is intermediate or new_stock."""
        if self.outcome_type != CrossOutcomeType.EPHEMERAL and not self.target_genotype:
            raise ValueError("target_genotype is required for intermediate or new_stock outcomes")
        return self


class CrossUpdate(BaseModel):
    """Schema for updating a cross."""

    name: str | None = Field(None, max_length=255)
    planned_date: date | None = None
    executed_date: date | None = None
    status: CrossStatus | None = None
    notes: str | None = None
    offspring_id: str | None = None
    target_genotype: str | None = None
    flip_days: int | None = Field(None, ge=1, le=30)
    virgin_collection_days: int | None = Field(None, ge=1, le=60)
    outcome_type: CrossOutcomeType | None = None


class StockSummary(BaseModel):
    """Brief stock info for cross display."""

    id: str
    stock_id: str
    genotype: str
    shortname: str | None = None
    original_genotype: str | None = None
    notes: str | None = None
    is_placeholder: bool = False

    model_config = ConfigDict(from_attributes=True)


class CrossResponse(BaseModel):
    """Schema for cross response."""

    id: str
    name: str | None
    parent_female: StockSummary
    parent_male: StockSummary
    offspring: StockSummary | None = None
    planned_date: date | None
    executed_date: date | None
    status: CrossStatus
    outcome_type: CrossOutcomeType | None = CrossOutcomeType.EPHEMERAL
    expected_outcomes: dict | None = None
    notes: str | None
    target_genotype: str | None = None
    flip_days: int | None = None
    virgin_collection_days: int | None = None
    # Computed timeline fields (only for in_progress crosses)
    flip_due_date: date | None = None
    virgin_collection_due_date: date | None = None
    days_until_flip: int | None = None
    days_until_virgin_collection: int | None = None
    flip_overdue: bool = False
    virgin_collection_overdue: bool = False
    created_at: datetime
    created_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CrossListResponse(BaseModel):
    """Schema for paginated cross list response."""

    items: list[CrossResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CrossSearchParams(BaseModel):
    """Schema for cross search parameters."""

    query: str | None = None
    status: CrossStatus | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class CrossComplete(BaseModel):
    """Schema for marking a cross as completed."""

    offspring_id: str | None = None
    notes: str | None = None


class ParentStockInfo(BaseModel):
    """Rich context about a parent stock for LLM genotype prediction."""

    genotype: str
    original_genotype: str | None = None
    shortname: str | None = None
    notes: str | None = None
    chromosome_info: str | None = None


class SuggestGenotypesRequest(BaseModel):
    """Request body for suggest-genotypes endpoint."""

    female: ParentStockInfo
    male: ParentStockInfo


class SuggestGenotypesResponse(BaseModel):
    """Response body for suggest-genotypes endpoint."""

    suggestions: list[str]
    reasoning: str | None = None


class CrossReminderInfo(BaseModel):
    """Info about a cross needing a timeline reminder."""

    cross_id: str
    cross_name: str | None
    female_stock_id: str
    male_stock_id: str
    event_type: str  # "flip" or "virgin_collection"
    due_date: date
    days_until: int  # negative = overdue
