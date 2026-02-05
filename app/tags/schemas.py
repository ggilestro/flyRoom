"""Pydantic schemas for tags."""

from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    """Schema for creating a tag."""

    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagUpdate(BaseModel):
    """Schema for updating a tag."""

    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class TagResponse(BaseModel):
    """Schema for tag response."""

    id: str
    name: str
    color: str | None = None

    model_config = {"from_attributes": True}


class TagWithCount(TagResponse):
    """Schema for tag with stock count."""

    stock_count: int = 0
