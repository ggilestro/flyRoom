"""Labels API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import CurrentTenantId, get_db
from app.labels.service import LabelService, get_label_service

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> LabelService:
    """Get label service dependency."""
    return get_label_service(db, str(tenant_id))


@router.get("/formats")
async def list_formats(
    service: Annotated[LabelService, Depends(get_service)],
):
    """List available label formats.

    Args:
        service: Label service.

    Returns:
        list[dict]: Available label formats.
    """
    return service.get_formats()


@router.get("/stock/{stock_id}/qr")
async def get_stock_qr(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
    size: int = Query(200, ge=50, le=500),
):
    """Get QR code for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.
        size: QR code size in pixels.

    Returns:
        Response: PNG image.

    Raises:
        HTTPException: If stock not found.
    """
    qr_data = service.generate_qr(stock_id, size=size)
    if not qr_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return Response(
        content=qr_data,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=qr_{stock_id}.png"},
    )


@router.get("/stock/{stock_id}/barcode")
async def get_stock_barcode(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
):
    """Get barcode for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.

    Returns:
        Response: PNG image.

    Raises:
        HTTPException: If stock not found.
    """
    barcode_data = service.generate_barcode(stock_id)
    if not barcode_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return Response(
        content=barcode_data,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=barcode_{stock_id}.png"},
    )


@router.get("/stock/{stock_id}/label")
async def get_stock_label(
    stock_id: str,
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("brother_29mm", description="Label format"),
    include_qr: bool = Query(True),
    include_barcode: bool = Query(True),
):
    """Get full label data for a stock.

    Args:
        stock_id: Stock UUID.
        service: Label service.
        format: Label format name.
        include_qr: Whether to include QR code.
        include_barcode: Whether to include barcode.

    Returns:
        dict: Label data with base64-encoded images.

    Raises:
        HTTPException: If stock not found or invalid format.
    """
    try:
        label_data = service.generate_label_data(
            stock_id,
            format_name=format,
            include_qr=include_qr,
            include_barcode=include_barcode,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    if not label_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )

    return label_data


@router.post("/batch")
async def generate_batch_labels(
    stock_ids: list[str],
    service: Annotated[LabelService, Depends(get_service)],
    format: str = Query("brother_29mm", description="Label format"),
):
    """Generate labels for multiple stocks.

    Args:
        stock_ids: List of stock UUIDs.
        service: Label service.
        format: Label format name.

    Returns:
        list[dict]: List of label data.
    """
    try:
        return service.generate_batch_labels(stock_ids, format_name=format)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
