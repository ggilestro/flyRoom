"""Flip tracking API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models import UserRole
from app.flips.schemas import (
    FlipEventCreate,
    FlipEventResponse,
    FlipSettingsResponse,
    FlipSettingsUpdate,
    StockFlipInfo,
    StocksNeedingFlipResponse,
)
from app.flips.service import FlipService, get_flip_service


def _get_db():
    """Late import to avoid circular imports."""
    from app.dependencies import get_db

    return get_db


def _get_current_user():
    """Late import to avoid circular imports."""
    from app.dependencies import get_current_user

    return get_current_user


router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(_get_db())],
    current_user=Depends(_get_current_user()),
) -> FlipService:
    """Get flip service dependency."""
    return get_flip_service(db, str(current_user.tenant_id), str(current_user.id))


def get_admin_service(
    db: Annotated[Session, Depends(_get_db())],
    current_user=Depends(_get_current_user()),
) -> FlipService:
    """Get flip service for admin-only operations."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return get_flip_service(db, str(current_user.tenant_id), str(current_user.id))


@router.post("/record", response_model=FlipEventResponse)
async def record_flip(
    data: FlipEventCreate,
    service: Annotated[FlipService, Depends(get_service)],
):
    """Record a flip event for a stock.

    Args:
        data: Flip event data.
        service: Flip service.

    Returns:
        FlipEventResponse: Created flip event.

    Raises:
        HTTPException: If stock not found.
    """
    result = service.record_flip(data)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )
    return result


@router.get("/stock/{stock_id}/history", response_model=list[FlipEventResponse])
async def get_flip_history(
    stock_id: str,
    service: Annotated[FlipService, Depends(get_service)],
    limit: int = Query(10, ge=1, le=100),
):
    """Get flip history for a stock.

    Args:
        stock_id: Stock UUID.
        service: Flip service.
        limit: Maximum events to return.

    Returns:
        list[FlipEventResponse]: Flip history, most recent first.
    """
    return service.get_flip_history(stock_id, limit=limit)


@router.get("/stock/{stock_id}/status", response_model=StockFlipInfo)
async def get_flip_status(
    stock_id: str,
    service: Annotated[FlipService, Depends(get_service)],
):
    """Get flip status for a stock.

    Args:
        stock_id: Stock UUID.
        service: Flip service.

    Returns:
        StockFlipInfo: Stock flip status.

    Raises:
        HTTPException: If stock not found.
    """
    result = service.get_stock_flip_status(stock_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )
    return result


@router.get("/needing-flip", response_model=StocksNeedingFlipResponse)
async def get_stocks_needing_flip(
    service: Annotated[FlipService, Depends(get_service)],
):
    """Get all stocks that need flipping.

    Returns stocks categorized by urgency:
    - warning: Approaching critical threshold
    - critical: Past critical threshold
    - never_flipped: Never been flipped

    Args:
        service: Flip service.

    Returns:
        StocksNeedingFlipResponse: Categorized stocks.
    """
    return service.get_stocks_needing_flip()


@router.get("/settings", response_model=FlipSettingsResponse)
async def get_flip_settings(
    service: Annotated[FlipService, Depends(get_service)],
):
    """Get flip tracking settings for the tenant.

    Args:
        service: Flip service.

    Returns:
        FlipSettingsResponse: Current settings.

    Raises:
        HTTPException: If tenant not found.
    """
    result = service.get_flip_settings()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return result


@router.put("/settings", response_model=FlipSettingsResponse)
async def update_flip_settings(
    data: FlipSettingsUpdate,
    service: Annotated[FlipService, Depends(get_admin_service)],
):
    """Update flip tracking settings (admin only).

    Args:
        data: Settings update data.
        service: Flip service.

    Returns:
        FlipSettingsResponse: Updated settings.

    Raises:
        HTTPException: If tenant not found or not admin.
    """
    result = service.update_flip_settings(data)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return result


@router.post("/send-reminders")
async def send_flip_reminders(
    x_cron_secret: Annotated[str | None, Header()] = None,
):
    """Trigger flip reminder emails (for cron jobs).

    This endpoint is meant to be called by an external cron job
    (e.g., Monday mornings) to send reminder emails.

    Args:
        x_cron_secret: Secret key for authentication.

    Returns:
        dict: Number of emails sent.

    Raises:
        HTTPException: If secret key is invalid.
    """
    from app.config import get_settings

    settings = get_settings()

    # Check for cron secret if configured
    expected_secret = getattr(settings, "cron_secret_key", None)
    if expected_secret and x_cron_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cron secret",
        )

    # Import here to avoid circular imports
    from app.scheduler.flip_reminders import send_all_flip_reminders

    result = send_all_flip_reminders()
    return result
