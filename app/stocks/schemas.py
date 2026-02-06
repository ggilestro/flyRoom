"""Pydantic schemas for stocks."""

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import StockOrigin, StockRepository, StockVisibility


class StockScope(str, enum.Enum):
    """Stock search scope enumeration."""

    LAB = "lab"  # Only stocks from current lab
    ORGANIZATION = "organization"  # Stocks visible within organization
    PUBLIC = "public"  # All public stocks


class TagBase(BaseModel):
    """Base schema for tags."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagCreate(TagBase):
    """Schema for creating a tag."""

    pass


class TagResponse(TagBase):
    """Schema for tag response."""

    id: str

    model_config = ConfigDict(from_attributes=True)


class TrayInfo(BaseModel):
    """Schema for tray info in stock response."""

    id: str
    name: str


class OwnerInfo(BaseModel):
    """Schema for owner info in stock response."""

    id: str
    full_name: str


class TenantInfo(BaseModel):
    """Schema for tenant info in stock response (for cross-lab visibility)."""

    id: str
    name: str
    city: str | None = None
    country: str | None = None


class StockBase(BaseModel):
    """Base schema for stocks."""

    stock_id: str = Field(..., min_length=1, max_length=100)
    genotype: str = Field(..., min_length=1)
    # Origin tracking
    origin: StockOrigin = StockOrigin.INTERNAL
    repository: StockRepository | None = None  # Only if origin=repository
    repository_stock_id: str | None = Field(None, max_length=50)
    external_source: str | None = Field(None, max_length=255)  # Only if origin=external
    original_genotype: str | None = None  # Original from repository
    notes: str | None = None


class StockCreate(StockBase):
    """Schema for creating a stock."""

    tag_ids: list[str] = Field(default_factory=list)
    tray_id: str | None = None
    position: str | None = Field(None, max_length=20)
    owner_id: str | None = None  # Defaults to created_by_id
    visibility: StockVisibility = StockVisibility.LAB_ONLY
    hide_from_org: bool = False


class StockUpdate(BaseModel):
    """Schema for updating a stock."""

    stock_id: str | None = Field(None, min_length=1, max_length=100)
    genotype: str | None = Field(None, min_length=1)
    # Origin tracking
    origin: StockOrigin | None = None
    repository: StockRepository | None = None
    repository_stock_id: str | None = Field(None, max_length=50)
    external_source: str | None = Field(None, max_length=255)
    original_genotype: str | None = None
    notes: str | None = None
    tag_ids: list[str] | None = None
    tray_id: str | None = None
    position: str | None = Field(None, max_length=20)
    owner_id: str | None = None
    visibility: StockVisibility | None = None
    hide_from_org: bool | None = None


class StockResponse(StockBase):
    """Schema for stock response."""

    id: str
    is_active: bool
    created_at: datetime
    modified_at: datetime
    created_by_name: str | None = None
    modified_by_name: str | None = None
    tags: list[TagResponse] = Field(default_factory=list)
    # Physical location
    tray: TrayInfo | None = None
    position: str | None = None
    owner: OwnerInfo | None = None
    visibility: StockVisibility = StockVisibility.LAB_ONLY
    hide_from_org: bool = False
    # For cross-lab visibility
    tenant: TenantInfo | None = None
    # Flip tracking
    flip_status: str | None = None  # ok, warning, critical, never
    days_since_flip: int | None = None
    last_flip_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StockListResponse(BaseModel):
    """Schema for paginated stock list response."""

    items: list[StockResponse]
    total: int
    page: int
    page_size: int
    pages: int


class StockSearchParams(BaseModel):
    """Schema for stock search parameters."""

    query: str | None = None
    tag_ids: list[str] | None = None
    origin: StockOrigin | None = None
    repository: StockRepository | None = None
    tray_id: str | None = None
    owner_id: str | None = None
    visibility: StockVisibility | None = None
    scope: StockScope = StockScope.LAB
    is_active: bool = True
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
