"""Crosses API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.crosses.schemas import (
    CrossComplete,
    CrossCreate,
    CrossListResponse,
    CrossResponse,
    CrossSearchParams,
    CrossUpdate,
)
from app.crosses.service import CrossService, get_cross_service
from app.db.models import CrossStatus
from app.dependencies import CurrentTenantId, CurrentUser, get_db

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> CrossService:
    """Get cross service dependency."""
    return get_cross_service(db, str(tenant_id))


@router.get("", response_model=CrossListResponse)
async def list_crosses(
    service: Annotated[CrossService, Depends(get_service)],
    query: str | None = Query(None, description="Search query"),
    status: CrossStatus | None = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List crosses with filtering and pagination.

    Args:
        service: Cross service.
        query: Search query.
        status: Filter by status.
        page: Page number.
        page_size: Items per page.

    Returns:
        CrossListResponse: Paginated cross list.
    """
    params = CrossSearchParams(
        query=query,
        status=status,
        page=page,
        page_size=page_size,
    )
    return service.list_crosses(params)


@router.post("", response_model=CrossResponse, status_code=status.HTTP_201_CREATED)
async def create_cross(
    data: CrossCreate,
    service: Annotated[CrossService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Create a new cross (plan).

    Args:
        data: Cross creation data.
        service: Cross service.
        current_user: Current user.

    Returns:
        CrossResponse: Created cross.

    Raises:
        HTTPException: If creation fails.
    """
    try:
        cross = service.create_cross(data, current_user.id)
        return service._cross_to_response(cross)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/{cross_id}", response_model=CrossResponse)
async def get_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Get a cross by ID.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Returns:
        CrossResponse: Cross details.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.get_cross(cross_id)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.put("/{cross_id}", response_model=CrossResponse)
async def update_cross(
    cross_id: str,
    data: CrossUpdate,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Update a cross.

    Args:
        cross_id: Cross UUID.
        data: Update data.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.update_cross(cross_id, data)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/start", response_model=CrossResponse)
async def start_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Mark a cross as in progress.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.start_cross(cross_id)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/complete", response_model=CrossResponse)
async def complete_cross(
    cross_id: str,
    data: CrossComplete,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Mark a cross as completed.

    Args:
        cross_id: Cross UUID.
        data: Completion data.
        service: Cross service.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.complete_cross(cross_id, data)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.post("/{cross_id}/fail", response_model=CrossResponse)
async def fail_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
    notes: str | None = None,
):
    """Mark a cross as failed.

    Args:
        cross_id: Cross UUID.
        service: Cross service.
        notes: Optional failure notes.

    Returns:
        CrossResponse: Updated cross.

    Raises:
        HTTPException: If cross not found.
    """
    cross = service.fail_cross(cross_id, notes)
    if not cross:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
    return service._cross_to_response(cross)


@router.delete("/{cross_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cross(
    cross_id: str,
    service: Annotated[CrossService, Depends(get_service)],
):
    """Delete a cross.

    Args:
        cross_id: Cross UUID.
        service: Cross service.

    Raises:
        HTTPException: If cross not found.
    """
    if not service.delete_cross(cross_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cross not found",
        )
