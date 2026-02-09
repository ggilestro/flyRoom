"""Pydantic schemas for tenant administration."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models import UserRole


class UserInvite(BaseModel):
    """Schema for inviting a new user."""

    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    role: UserRole = UserRole.USER


class UserUpdateAdmin(BaseModel):
    """Schema for admin updating a user."""

    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserListResponse(BaseModel):
    """Schema for user list item."""

    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationInfo(BaseModel):
    """Schema for organization info in tenant response."""

    id: str
    name: str
    slug: str


class TenantResponse(BaseModel):
    """Schema for tenant information."""

    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    user_count: int
    stock_count: int
    # New organization fields
    organization: OrganizationInfo | None = None
    is_org_admin: bool = False
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    model_config = ConfigDict(from_attributes=True)


class InvitationCreate(BaseModel):
    """Schema for creating an email invitation."""

    email: EmailStr
    invitation_type: str = Field(default="lab_member", pattern="^(lab_member|new_tenant)$")


class InvitationResponse(BaseModel):
    """Schema for invitation list response."""

    id: str
    email: str
    invitation_type: str
    status: str
    created_at: datetime
    expires_at: datetime
    invited_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InvitationValidation(BaseModel):
    """Schema for validating an invitation token (public endpoint)."""

    email: str
    invitation_type: str
    tenant_name: str
    organization_name: str | None = None


class TenantUpdate(BaseModel):
    """Schema for updating tenant."""

    name: str | None = Field(None, min_length=2, max_length=255)
