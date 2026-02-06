"""Pydantic schemas for trays."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import TrayType


class TrayBase(BaseModel):
    """Base schema for trays."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    tray_type: TrayType = TrayType.NUMERIC
    max_positions: int = Field(100, ge=1, le=10000)
    rows: int | None = Field(None, ge=1, le=100)
    cols: int | None = Field(None, ge=1, le=100)


class TrayCreate(TrayBase):
    """Schema for creating a tray."""

    pass


class TrayUpdate(BaseModel):
    """Schema for updating a tray."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    tray_type: TrayType | None = None
    max_positions: int | None = Field(None, ge=1, le=10000)
    rows: int | None = Field(None, ge=1, le=100)
    cols: int | None = Field(None, ge=1, le=100)


class FlipStatusCounts(BaseModel):
    """Schema for flip status counts in a tray."""

    ok: int = 0
    warning: int = 0
    critical: int = 0
    never: int = 0


class TrayResponse(TrayBase):
    """Schema for tray response."""

    id: str
    created_at: datetime
    stock_count: int = 0
    flip_counts: FlipStatusCounts = Field(default_factory=FlipStatusCounts)

    model_config = ConfigDict(from_attributes=True)


class TrayListResponse(BaseModel):
    """Schema for paginated tray list response."""

    items: list[TrayResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TrayPositionInfo(BaseModel):
    """Schema for position information in a tray."""

    position: str
    stock_id: str | None = None
    stock_name: str | None = None  # stock.stock_id


class TrayStockInfo(BaseModel):
    """Schema for stock info in tray detail."""

    id: str
    stock_id: str  # User-facing stock identifier
    genotype: str
    position: str | None = None


class TrayDetailResponse(TrayResponse):
    """Schema for tray detail with positions."""

    positions: list[TrayPositionInfo] = Field(default_factory=list)
    stocks: list[TrayStockInfo] = Field(default_factory=list)  # All stocks in this tray
