"""Tags API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import StockTag, Tag
from app.dependencies import CurrentTenantId, get_db
from app.tags.schemas import TagCreate, TagResponse, TagUpdate, TagWithCount

router = APIRouter()


@router.get("", response_model=list[TagWithCount])
async def list_tags(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> list[TagWithCount]:
    """List all tags for the current tenant with stock counts.

    Args:
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        list[TagWithCount]: List of tags with stock counts.
    """
    # Query tags with stock count
    results = (
        db.query(
            Tag,
            func.count(StockTag.stock_id).label("stock_count"),
        )
        .outerjoin(StockTag, Tag.id == StockTag.tag_id)
        .filter(Tag.tenant_id == tenant_id)
        .group_by(Tag.id)
        .order_by(Tag.name)
        .all()
    )

    return [
        TagWithCount(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            stock_count=count,
        )
        for tag, count in results
    ]


@router.get("/{tag_id}", response_model=TagWithCount)
async def get_tag(
    tag_id: str,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> TagWithCount:
    """Get a specific tag by ID.

    Args:
        tag_id: Tag ID.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        TagWithCount: Tag with stock count.

    Raises:
        HTTPException: If tag not found.
    """
    result = (
        db.query(
            Tag,
            func.count(StockTag.stock_id).label("stock_count"),
        )
        .outerjoin(StockTag, Tag.id == StockTag.tag_id)
        .filter(Tag.id == tag_id, Tag.tenant_id == tenant_id)
        .group_by(Tag.id)
        .first()
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    tag, count = result
    return TagWithCount(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        stock_count=count,
    )


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> TagResponse:
    """Create a new tag.

    Args:
        data: Tag creation data.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        TagResponse: Created tag.

    Raises:
        HTTPException: If tag name already exists.
    """
    # Check for duplicate name
    existing = (
        db.query(Tag)
        .filter(
            Tag.tenant_id == tenant_id,
            func.lower(Tag.name) == data.name.lower(),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tag '{data.name}' already exists",
        )

    tag = Tag(
        tenant_id=str(tenant_id),
        name=data.name,
        color=data.color,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)

    return TagResponse.model_validate(tag)


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    data: TagUpdate,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> TagResponse:
    """Update a tag.

    Args:
        tag_id: Tag ID.
        data: Tag update data.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        TagResponse: Updated tag.

    Raises:
        HTTPException: If tag not found or name conflict.
    """
    tag = (
        db.query(Tag)
        .filter(
            Tag.id == tag_id,
            Tag.tenant_id == tenant_id,
        )
        .first()
    )

    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    # Check for name conflict if name is being changed
    if data.name and data.name.lower() != tag.name.lower():
        existing = (
            db.query(Tag)
            .filter(
                Tag.tenant_id == tenant_id,
                func.lower(Tag.name) == data.name.lower(),
                Tag.id != tag_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tag '{data.name}' already exists",
            )
        tag.name = data.name

    if data.color is not None:
        tag.color = data.color

    db.commit()
    db.refresh(tag)

    return TagResponse.model_validate(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: str,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> None:
    """Delete a tag.

    This removes the tag from all stocks that use it.

    Args:
        tag_id: Tag ID.
        db: Database session.
        tenant_id: Current tenant ID.

    Raises:
        HTTPException: If tag not found.
    """
    tag = (
        db.query(Tag)
        .filter(
            Tag.id == tag_id,
            Tag.tenant_id == tenant_id,
        )
        .first()
    )

    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    db.delete(tag)
    db.commit()


@router.post("/{tag_id}/merge/{target_id}", response_model=TagResponse)
async def merge_tags(
    tag_id: str,
    target_id: str,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> TagResponse:
    """Merge one tag into another.

    All stocks with the source tag will be given the target tag,
    then the source tag is deleted.

    Args:
        tag_id: Source tag ID (will be deleted).
        target_id: Target tag ID (will receive stocks).
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        TagResponse: The target tag.

    Raises:
        HTTPException: If either tag not found.
    """
    if tag_id == target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot merge a tag into itself",
        )

    source = (
        db.query(Tag)
        .filter(
            Tag.id == tag_id,
            Tag.tenant_id == tenant_id,
        )
        .first()
    )
    target = (
        db.query(Tag)
        .filter(
            Tag.id == target_id,
            Tag.tenant_id == tenant_id,
        )
        .first()
    )

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source tag not found",
        )
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target tag not found",
        )

    # Get stock IDs that have the source tag but not the target tag
    source_stock_ids = {
        st.stock_id for st in db.query(StockTag).filter(StockTag.tag_id == tag_id).all()
    }
    target_stock_ids = {
        st.stock_id for st in db.query(StockTag).filter(StockTag.tag_id == target_id).all()
    }

    # Add target tag to stocks that only have source tag
    for stock_id in source_stock_ids - target_stock_ids:
        db.add(StockTag(stock_id=stock_id, tag_id=target_id))

    # Delete source tag (cascades to stock_tags)
    db.delete(source)
    db.commit()
    db.refresh(target)

    return TagResponse.model_validate(target)
