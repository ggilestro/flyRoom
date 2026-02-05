"""Pydantic schemas for crosses."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import CrossStatus


class CrossBase(BaseModel):
    """Base schema for crosses."""

    name: str | None = Field(None, max_length=255)
    parent_female_id: str
    parent_male_id: str
    planned_date: date | None = None
    notes: str | None = None


class CrossCreate(CrossBase):
    """Schema for creating a cross."""

    pass


class CrossUpdate(BaseModel):
    """Schema for updating a cross."""

    name: str | None = Field(None, max_length=255)
    planned_date: date | None = None
    executed_date: date | None = None
    status: CrossStatus | None = None
    notes: str | None = None
    offspring_id: str | None = None


class StockSummary(BaseModel):
    """Brief stock info for cross display."""

    id: str
    stock_id: str
    genotype: str

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
    expected_outcomes: dict | None = None
    notes: str | None
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
