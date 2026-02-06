"""Schemas for flip tracking system."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FlipStatus(str, Enum):
    """Stock flip status based on days since last flip."""

    OK = "ok"  # Recently flipped, within warning threshold
    WARNING = "warning"  # Approaching critical threshold
    CRITICAL = "critical"  # Past critical threshold, needs immediate attention
    NEVER = "never"  # Never been flipped


class FlipEventCreate(BaseModel):
    """Schema for recording a flip event."""

    stock_id: str = Field(..., description="Stock UUID to record flip for")
    notes: str | None = Field(None, max_length=500, description="Optional notes")


class FlipEventResponse(BaseModel):
    """Schema for flip event response."""

    id: str
    stock_id: str
    flipped_by_id: str | None
    flipped_by_name: str | None = None
    flipped_at: datetime
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StockFlipInfo(BaseModel):
    """Schema for stock flip status information."""

    stock_id: str
    stock_display_id: str  # Human-readable stock ID (e.g., "BL-1234")
    flip_status: FlipStatus
    days_since_flip: int | None
    last_flip_at: datetime | None
    last_flipped_by: str | None


class FlipSettingsResponse(BaseModel):
    """Schema for flip settings response."""

    flip_warning_days: int
    flip_critical_days: int
    flip_reminder_enabled: bool


class FlipSettingsUpdate(BaseModel):
    """Schema for updating flip settings."""

    flip_warning_days: int | None = Field(None, ge=1, le=365)
    flip_critical_days: int | None = Field(None, ge=1, le=365)
    flip_reminder_enabled: bool | None = None


class StocksNeedingFlipResponse(BaseModel):
    """Schema for stocks needing flip response."""

    warning: list[StockFlipInfo]
    critical: list[StockFlipInfo]
    never_flipped: list[StockFlipInfo]
