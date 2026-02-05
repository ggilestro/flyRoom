"""Pydantic schemas for organizations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import OrgJoinRequestStatus


class OrganizationBase(BaseModel):
    """Base schema for organizations."""

    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = None
    website: str | None = Field(None, max_length=255)


class OrganizationCreate(OrganizationBase):
    """Schema for creating an organization."""

    pass


class OrganizationUpdate(BaseModel):
    """Schema for updating an organization."""

    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    website: str | None = Field(None, max_length=255)


class OrganizationResponse(OrganizationBase):
    """Schema for organization response."""

    id: str
    slug: str
    is_active: bool
    created_at: datetime
    lab_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class OrganizationSearchResult(BaseModel):
    """Schema for organization search results (fuzzy matching)."""

    id: str
    name: str
    slug: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class OrgJoinRequestCreate(BaseModel):
    """Schema for creating an organization join request."""

    organization_id: str
    message: str | None = None


class OrgJoinRequestResponse(BaseModel):
    """Schema for organization join request response."""

    id: str
    organization_id: str
    organization_name: str
    tenant_id: str
    tenant_name: str
    requested_by_name: str | None = None
    status: OrgJoinRequestStatus
    message: str | None = None
    created_at: datetime
    responded_at: datetime | None = None
    responded_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TenantGeoUpdate(BaseModel):
    """Schema for updating tenant geographic information."""

    city: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
