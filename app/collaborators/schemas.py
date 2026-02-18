"""Pydantic schemas for collaborators."""

from datetime import datetime

from pydantic import BaseModel, Field


class CollaboratorTenantInfo(BaseModel):
    id: str
    name: str
    admin_name: str | None = None
    city: str | None = None
    country: str | None = None


class CollaboratorResponse(BaseModel):
    id: str
    collaborator: CollaboratorTenantInfo
    created_at: datetime


class CollaboratorCreate(BaseModel):
    collaborator_tenant_id: str = Field(..., min_length=1)


class TenantSearchResult(BaseModel):
    id: str
    name: str
    admin_name: str | None = None
    admin_email: str | None = None
    city: str | None = None
    country: str | None = None
