"""API router for stock requests."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import StockRequestStatus
from app.dependencies import CurrentTenantId, CurrentUser, get_db
from app.requests.schemas import (
    StockRequestCreate,
    StockRequestListResponse,
    StockRequestRespond,
    StockRequestResponse,
    StockRequestStats,
)
from app.requests.service import StockRequestService

router = APIRouter()


def get_request_service(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
) -> StockRequestService:
    """Get stock request service dependency."""
    return StockRequestService(db, str(tenant_id), current_user.id)


@router.post("", response_model=StockRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    data: StockRequestCreate,
    service: Annotated[StockRequestService, Depends(get_request_service)],
):
    """Create a stock request."""
    try:
        request = service.create_request(data)
        return service._request_to_response(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/outgoing", response_model=StockRequestListResponse)
async def list_outgoing_requests(
    service: Annotated[StockRequestService, Depends(get_request_service)],
    status: StockRequestStatus | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """List requests made by this lab."""
    return service.list_outgoing_requests(status=status, page=page, page_size=page_size)


@router.get("/incoming", response_model=StockRequestListResponse)
async def list_incoming_requests(
    service: Annotated[StockRequestService, Depends(get_request_service)],
    status: StockRequestStatus | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """List requests for stocks owned by this lab."""
    return service.list_incoming_requests(status=status, page=page, page_size=page_size)


@router.get("/stats", response_model=StockRequestStats)
async def get_request_stats(
    service: Annotated[StockRequestService, Depends(get_request_service)],
):
    """Get request statistics for this lab."""
    return service.get_stats()


@router.get("/{request_id}", response_model=StockRequestResponse)
async def get_request(
    request_id: str,
    service: Annotated[StockRequestService, Depends(get_request_service)],
):
    """Get a stock request by ID."""
    request = service.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return service._request_to_response(request)


@router.put("/{request_id}/approve", response_model=StockRequestResponse)
async def approve_request(
    request_id: str,
    service: Annotated[StockRequestService, Depends(get_request_service)],
    data: StockRequestRespond | None = None,
):
    """Approve a stock request (owner lab only)."""
    response_message = data.response_message if data else None
    request = service.approve_request(request_id, response_message)
    if not request:
        raise HTTPException(
            status_code=404, detail="Request not found or you don't have permission"
        )
    return service._request_to_response(request)


@router.put("/{request_id}/reject", response_model=StockRequestResponse)
async def reject_request(
    request_id: str,
    service: Annotated[StockRequestService, Depends(get_request_service)],
    data: StockRequestRespond | None = None,
):
    """Reject a stock request (owner lab only)."""
    response_message = data.response_message if data else None
    request = service.reject_request(request_id, response_message)
    if not request:
        raise HTTPException(
            status_code=404, detail="Request not found or you don't have permission"
        )
    return service._request_to_response(request)


@router.put("/{request_id}/fulfill", response_model=StockRequestResponse)
async def fulfill_request(
    request_id: str,
    service: Annotated[StockRequestService, Depends(get_request_service)],
):
    """Mark an approved request as fulfilled (owner lab only)."""
    request = service.fulfill_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found or not in approved status")
    return service._request_to_response(request)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(
    request_id: str,
    service: Annotated[StockRequestService, Depends(get_request_service)],
):
    """Cancel a pending request (requester lab only)."""
    if not service.cancel_request(request_id):
        raise HTTPException(status_code=404, detail="Request not found or not in pending status")
