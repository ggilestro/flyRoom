"""Pydantic schemas for stock requests."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import StockRequestStatus


class StockRequestCreate(BaseModel):
    """Schema for creating a stock request."""

    stock_id: str
    message: str | None = None


class StockRequestRespond(BaseModel):
    """Schema for responding to a stock request."""

    response_message: str | None = None


class StockRequestResponse(BaseModel):
    """Schema for stock request response."""

    id: str
    stock_id: str
    stock_name: str  # stock.stock_id
    stock_genotype: str
    requester_user_id: str | None = None
    requester_user_name: str | None = None
    requester_tenant_id: str
    requester_tenant_name: str
    owner_tenant_id: str
    owner_tenant_name: str
    status: StockRequestStatus
    message: str | None = None
    response_message: str | None = None
    created_at: datetime
    updated_at: datetime
    responded_at: datetime | None = None
    responded_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StockRequestListResponse(BaseModel):
    """Schema for paginated stock request list."""

    items: list[StockRequestResponse]
    total: int
    page: int
    page_size: int
    pages: int


class StockRequestStats(BaseModel):
    """Schema for stock request statistics."""

    pending_incoming: int
    pending_outgoing: int
    approved_outgoing: int
    fulfilled_total: int
