"""Stocks API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.models import StockOrigin, StockRepository, StockVisibility
from app.dependencies import CurrentTenantId, CurrentUser, get_db
from app.stocks.schemas import (
    StockCreate,
    StockListResponse,
    StockResponse,
    StockScope,
    StockSearchParams,
    StockUpdate,
    TagCreate,
    TagResponse,
)
from app.stocks.service import StockService, get_stock_service

router = APIRouter()

# Templates for HTML responses
templates = Jinja2Templates(directory="app/templates")


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> StockService:
    """Get stock service dependency."""
    return get_stock_service(db, str(tenant_id))


@router.get("", response_model=StockListResponse)
async def list_stocks(
    service: Annotated[StockService, Depends(get_service)],
    query: str | None = Query(None, description="Search query"),
    tag_ids: str | None = Query(None, description="Comma-separated tag IDs"),
    origin: StockOrigin | None = Query(None, description="Filter by origin type"),
    repository: StockRepository | None = Query(None, description="Filter by repository"),
    tray_id: str | None = Query(None, description="Filter by tray ID"),
    owner_id: str | None = Query(None, description="Filter by owner user ID"),
    visibility: StockVisibility | None = Query(None, description="Filter by visibility"),
    scope: StockScope = Query(StockScope.LAB, description="Visibility scope"),
    is_active: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List stocks with filtering and pagination.

    Args:
        service: Stock service.
        query: Search query.
        tag_ids: Comma-separated tag IDs.
        origin: Filter by stock origin (repository, internal, external).
        repository: Filter by repository (bdsc, vdrc, etc.).
        tray_id: Filter by tray ID.
        owner_id: Filter by owner user ID.
        visibility: Filter by visibility level.
        scope: Visibility scope (lab, organization, public).
        is_active: Filter by active status.
        page: Page number.
        page_size: Items per page.

    Returns:
        StockListResponse: Paginated stock list.
    """
    params = StockSearchParams(
        query=query,
        tag_ids=tag_ids.split(",") if tag_ids else None,
        origin=origin,
        repository=repository,
        tray_id=tray_id,
        owner_id=owner_id,
        visibility=visibility,
        scope=scope,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return service.list_stocks(params)


@router.post("", response_model=StockResponse, status_code=status.HTTP_201_CREATED)
async def create_stock(
    data: StockCreate,
    service: Annotated[StockService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Create a new stock.

    Args:
        data: Stock creation data.
        service: Stock service.
        current_user: Current user.

    Returns:
        StockResponse: Created stock.

    Raises:
        HTTPException: If creation fails.
    """
    try:
        stock = service.create_stock(data, current_user.id)
        return service._stock_to_response(stock)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# Repository metadata endpoint - must be before /{stock_id} routes
@router.get("/repository-metadata/{repository}/{repo_stock_id}")
async def get_repository_metadata(
    repository: StockRepository,
    repo_stock_id: str,
):
    """Fetch metadata from a stock repository.

    Args:
        repository: Repository name (bdsc, vdrc, etc.).
        repo_stock_id: Stock ID in the repository.

    Returns:
        dict: Repository metadata including genotype.

    Raises:
        HTTPException: If repository not supported or stock not found.
    """
    if repository == StockRepository.BDSC:
        try:
            from app.plugins.bdsc.client import get_bdsc_plugin

            plugin = get_bdsc_plugin()
            stock_data = await plugin.get_details(repo_stock_id)
            if stock_data:
                return {
                    "found": True,
                    "genotype": stock_data.genotype,
                    "metadata": stock_data.metadata,
                }
            return {"found": False, "message": f"Stock {repo_stock_id} not found in BDSC"}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch BDSC metadata: {e}",
            )
    else:
        return {
            "found": False,
            "message": f"Repository {repository.value} metadata lookup not yet supported",
        }


@router.get("/search", response_class=HTMLResponse)
async def search_stocks_html(
    request: Request,
    service: Annotated[StockService, Depends(get_service)],
    search: str = Query("", description="Search query from navbar"),
):
    """Search stocks and return HTML for HTMX dropdown.

    If there's exactly one result with an exact stock_id match,
    returns HX-Redirect header to navigate directly to that stock.
    This enables barcode scanner workflow where scanning auto-navigates.

    Args:
        request: FastAPI request object.
        service: Stock service.
        search: Search query string.

    Returns:
        HTMLResponse: Rendered search results partial, or redirect for exact match.
    """
    query = search.strip()
    if not query or len(query) < 2:
        # Return empty/hidden state for short queries
        return HTMLResponse("")

    # Search with a reasonable limit for dropdown
    limit = 10
    params = StockSearchParams(
        query=query,
        page=1,
        page_size=limit,
    )
    result = service.list_stocks(params)

    # Check for exact match - if single result with exact stock_id, redirect
    if result.total == 1 and len(result.items) == 1:
        stock = result.items[0]
        if stock.stock_id.lower() == query.lower():
            # Exact match - redirect directly to stock page
            return HTMLResponse(
                content="",
                headers={"HX-Redirect": f"/stocks/{stock.id}"},
            )

    return templates.TemplateResponse(
        request,
        "components/search_results.html",
        {
            "stocks": result.items,
            "total": result.total,
            "limit": limit,
            "query": query,
        },
    )


@router.get("/{stock_id}", response_model=StockResponse)
async def get_stock(
    stock_id: str,
    service: Annotated[StockService, Depends(get_service)],
):
    """Get a stock by ID.

    Args:
        stock_id: Stock UUID.
        service: Stock service.

    Returns:
        StockResponse: Stock details.

    Raises:
        HTTPException: If stock not found.
    """
    stock = service.get_stock(stock_id)
    if not stock:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )
    return service._stock_to_response(stock)


@router.put("/{stock_id}", response_model=StockResponse)
async def update_stock(
    stock_id: str,
    data: StockUpdate,
    service: Annotated[StockService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Update a stock.

    Args:
        stock_id: Stock UUID.
        data: Update data.
        service: Stock service.
        current_user: Current user.

    Returns:
        StockResponse: Updated stock.

    Raises:
        HTTPException: If update fails.
    """
    try:
        stock = service.update_stock(stock_id, data, current_user.id)
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stock not found",
            )
        return service._stock_to_response(stock)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{stock_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stock(
    stock_id: str,
    service: Annotated[StockService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Soft delete a stock.

    Args:
        stock_id: Stock UUID.
        service: Stock service.
        current_user: Current user.

    Raises:
        HTTPException: If stock not found.
    """
    if not service.delete_stock(stock_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )


@router.post("/{stock_id}/restore", response_model=StockResponse)
async def restore_stock(
    stock_id: str,
    service: Annotated[StockService, Depends(get_service)],
    current_user: CurrentUser,
):
    """Restore a soft-deleted stock.

    Args:
        stock_id: Stock UUID.
        service: Stock service.
        current_user: Current user.

    Returns:
        StockResponse: Restored stock.

    Raises:
        HTTPException: If stock not found.
    """
    if not service.restore_stock(stock_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stock not found",
        )
    stock = service.get_stock(stock_id)
    return service._stock_to_response(stock)


# Tag endpoints


@router.get("/tags/", response_model=list[TagResponse])
async def list_tags(
    service: Annotated[StockService, Depends(get_service)],
):
    """List all tags.

    Args:
        service: Stock service.

    Returns:
        list[TagResponse]: List of tags.
    """
    return service.list_tags()


@router.post("/tags/", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    service: Annotated[StockService, Depends(get_service)],
):
    """Create a new tag.

    Args:
        data: Tag creation data.
        service: Stock service.

    Returns:
        TagResponse: Created tag.

    Raises:
        HTTPException: If creation fails.
    """
    try:
        tag = service.create_tag(data)
        return TagResponse(id=tag.id, name=tag.name, color=tag.color)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: str,
    service: Annotated[StockService, Depends(get_service)],
):
    """Delete a tag.

    Args:
        tag_id: Tag UUID.
        service: Stock service.

    Raises:
        HTTPException: If tag not found.
    """
    if not service.delete_tag(tag_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )
