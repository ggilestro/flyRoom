"""API router for trays."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import CurrentTenantId, get_db
from app.trays.schemas import (
    TrayCreate,
    TrayDetailResponse,
    TrayListResponse,
    TrayResponse,
    TrayUpdate,
)
from app.trays.service import TrayService

router = APIRouter()


def get_tray_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> TrayService:
    """Get tray service dependency."""
    return TrayService(db, str(tenant_id))


@router.get("", response_model=TrayListResponse)
async def list_trays(
    service: Annotated[TrayService, Depends(get_tray_service)],
    page: int = 1,
    page_size: int = 20,
):
    """List all trays for the current lab."""
    return service.list_trays(page=page, page_size=page_size)


@router.get("/{tray_id}", response_model=TrayDetailResponse)
async def get_tray(
    tray_id: str,
    service: Annotated[TrayService, Depends(get_tray_service)],
):
    """Get tray detail with position information."""
    tray = service.get_tray_detail(tray_id)
    if not tray:
        raise HTTPException(status_code=404, detail="Tray not found")
    return tray


@router.post("", response_model=TrayResponse, status_code=status.HTTP_201_CREATED)
async def create_tray(
    data: TrayCreate,
    service: Annotated[TrayService, Depends(get_tray_service)],
):
    """Create a new tray."""
    try:
        tray = service.create_tray(data)
        return service._tray_to_response(tray)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{tray_id}", response_model=TrayResponse)
async def update_tray(
    tray_id: str,
    data: TrayUpdate,
    service: Annotated[TrayService, Depends(get_tray_service)],
):
    """Update a tray."""
    try:
        tray = service.update_tray(tray_id, data)
        if not tray:
            raise HTTPException(status_code=404, detail="Tray not found")
        return service._tray_to_response(tray)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tray_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tray(
    tray_id: str,
    service: Annotated[TrayService, Depends(get_tray_service)],
):
    """Delete a tray."""
    if not service.delete_tray(tray_id):
        raise HTTPException(status_code=404, detail="Tray not found")


@router.get("/{tray_id}/validate-position")
async def validate_position(
    tray_id: str,
    position: str,
    service: Annotated[TrayService, Depends(get_tray_service)],
):
    """Validate if a position is valid for a tray."""
    is_valid = service.validate_position(tray_id, position)
    return {"valid": is_valid}
