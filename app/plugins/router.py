"""API routes for external stock plugins."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.plugins.flybase.client import FlyBasePlugin, get_flybase_plugin
from app.plugins.schemas import (
    ExternalStockDetails,
    ExternalStockResult,
    ImportFromExternalRequest,
    ImportFromExternalResult,
    PluginSourceInfo,
    PluginStatsResponse,
    RepositoryInfo,
)

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)

# Backward compatibility: map 'bdsc' source to flybase
SOURCE_ALIASES = {
    "bdsc": "flybase",
    "vdrc": "flybase",
    "kyoto": "flybase",
    "nig": "flybase",
    "kdrc": "flybase",
    "flyorf": "flybase",
    "ndssc": "flybase",
}


def _get_db():
    """Get database session (late import to avoid circular dependency)."""
    from app.db.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Session = Depends(_get_db),
    access_token: str | None = Cookie(None),
):
    """Get current user (late import to avoid circular dependency)."""
    from app.auth.utils import decode_access_token
    from app.db.models import User, UserStatus

    token = None
    if credentials is not None:
        token = credentials.credentials
    elif access_token is not None:
        token = access_token

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_access_token(token)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    if user.status != UserStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval",
        )

    return user


def _resolve_source(source: str) -> tuple[str, str | None]:
    """Resolve source ID and optional repository.

    Args:
        source: Source identifier (e.g., 'flybase', 'bdsc', 'vdrc').

    Returns:
        tuple: (resolved_source, repository_filter)
            - If source is a repository ID, returns ('flybase', repository_id)
            - If source is 'flybase', returns ('flybase', None)
    """
    if source in SOURCE_ALIASES:
        return SOURCE_ALIASES[source], source if source != "flybase" else None
    return source, None


def get_plugin(source: str) -> tuple[FlyBasePlugin, str | None]:
    """Get plugin instance by source ID.

    Args:
        source: Source identifier.

    Returns:
        tuple: (plugin_instance, repository_filter)

    Raises:
        HTTPException: If source is not found.
    """
    resolved_source, repository = _resolve_source(source)

    if resolved_source == "flybase":
        return get_flybase_plugin(), repository

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Unknown source: {source}",
    )


@router.get("/sources", response_model=list[PluginSourceInfo])
async def list_sources() -> list[PluginSourceInfo]:
    """List available plugin sources.

    Returns:
        list[PluginSourceInfo]: Available sources with repository info.
    """
    plugin = get_flybase_plugin()

    # Get repository stats
    try:
        stats = await plugin.get_stats()
        repos = [
            RepositoryInfo(id=r["id"], name=r["name"], count=r["count"])
            for r in stats.get("repositories", [])
        ]
    except Exception as e:
        logger.warning(f"Failed to get repository stats: {e}")
        repos = []

    return [
        PluginSourceInfo(
            source_id="flybase",
            name=plugin.name,
            description="Import stocks from FlyBase Stock Database (BDSC, VDRC, Kyoto, NIG-Fly, KDRC, FlyORF, NDSSC)",
            available=True,
            repositories=repos,
        )
    ]


@router.get("/sources/{source}/stats", response_model=PluginStatsResponse)
async def get_source_stats(source: str) -> PluginStatsResponse:
    """Get statistics for a plugin source.

    Args:
        source: Source identifier.

    Returns:
        PluginStatsResponse: Source statistics including per-repository counts.
    """
    plugin, _ = get_plugin(source)
    stats = await plugin.get_stats()

    repos = [
        RepositoryInfo(id=r["id"], name=r["name"], count=r["count"])
        for r in stats.get("repositories", [])
    ]

    return PluginStatsResponse(
        source_id="flybase",
        total_stocks=stats.get("total_stocks", 0),
        data_version=stats.get("data_version"),
        cache_valid=stats.get("cache_valid", False),
        repositories=repos,
    )


@router.get("/sources/{source}/repositories", response_model=list[RepositoryInfo])
async def list_repositories(source: str) -> list[RepositoryInfo]:
    """List available repositories for a source.

    Args:
        source: Source identifier.

    Returns:
        list[RepositoryInfo]: Available repositories with stock counts.
    """
    plugin, _ = get_plugin(source)
    repos = await plugin.list_repositories()

    return [RepositoryInfo(id=r["id"], name=r["name"], count=r["count"]) for r in repos]


@router.post("/sources/{source}/refresh")
async def refresh_source_data(
    source: str,
    current_user=Depends(_get_current_user),
) -> dict:
    """Force refresh of source data.

    Args:
        source: Source identifier.
        current_user: Current authenticated user (required).

    Returns:
        dict: Refresh result.
    """
    plugin, _ = get_plugin(source)
    count = await plugin.refresh_data()
    return {"status": "ok", "stocks_loaded": count}


@router.get("/search", response_model=list[ExternalStockResult])
async def search_external(
    query: str = Query(..., min_length=1, description="Search query"),
    source: str = Query("flybase", description="Source to search"),
    repository: str | None = Query(None, description="Repository to filter (e.g., bdsc, vdrc)"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
) -> list[ExternalStockResult]:
    """Search for stocks in external source.

    Args:
        query: Search query (stock number or genotype).
        source: Source identifier (flybase, or legacy: bdsc, vdrc, etc.).
        repository: Optional repository filter when using flybase source.
        limit: Maximum number of results.

    Returns:
        list[ExternalStockResult]: Matching stocks.
    """
    plugin, resolved_repository = get_plugin(source)

    # Use explicit repository param if provided, otherwise use resolved from source
    search_repository = repository or resolved_repository

    try:
        results = await plugin.search(query, limit=limit, repository=search_repository)
        return [
            ExternalStockResult(
                external_id=r.external_id,
                genotype=r.genotype,
                source=r.source,
                metadata=r.metadata,
            )
            for r in results
        ]
    except Exception as e:
        logger.error(f"Search error for source {source}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Search failed: {str(e)}",
        )


@router.get("/details/{source}/{external_id}", response_model=ExternalStockDetails)
async def get_external_details(
    source: str,
    external_id: str,
    repository: str | None = Query(None, description="Repository hint"),
) -> ExternalStockDetails:
    """Get detailed info for an external stock.

    Args:
        source: Source identifier.
        external_id: External stock ID.
        repository: Optional repository hint for faster lookup.

    Returns:
        ExternalStockDetails: Stock details.

    Raises:
        HTTPException: If stock not found.
    """
    plugin, resolved_repository = get_plugin(source)
    search_repository = repository or resolved_repository

    try:
        result = await plugin.get_details(external_id, repository=search_repository)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stock {external_id} not found in {source}",
            )

        return ExternalStockDetails(
            external_id=result.external_id,
            genotype=result.genotype,
            source=result.source,
            metadata=result.metadata,
            flybase_url=result.metadata.get("flybase_url"),
            source_url=result.metadata.get("repository_url"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Details error for {source}/{external_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to get details: {str(e)}",
        )


@router.post("/import", response_model=ImportFromExternalResult)
async def import_from_external(
    request: ImportFromExternalRequest,
    db: Session = Depends(_get_db),
    current_user=Depends(_get_current_user),
) -> ImportFromExternalResult:
    """Import stocks from external source.

    Args:
        request: Import request with list of stocks.
        db: Database session.
        current_user: Current authenticated user.

    Returns:
        ImportFromExternalResult: Import results.
    """
    from app.db.models import ExternalReference, Stock

    result = ImportFromExternalResult()
    tenant_id = current_user.tenant_id

    for item in request.stocks:
        try:
            # Get plugin for this source
            plugin, repository = get_plugin(item.source)

            # Get full stock details
            stock_data = await plugin.get_details(item.external_id, repository=repository)
            if stock_data is None:
                result.errors.append(f"Stock {item.external_id} not found in {item.source}")
                continue

            # Determine repository from metadata
            actual_repository = stock_data.metadata.get("repository", item.source)

            # Determine stock_id to use
            stock_id = item.stock_id or f"{actual_repository.upper()}-{item.external_id}"

            # Check if stock already exists
            existing = (
                db.query(Stock)
                .filter(
                    Stock.tenant_id == str(tenant_id),
                    Stock.stock_id == stock_id,
                )
                .first()
            )

            if existing:
                result.skipped += 1
                result.errors.append(f"Stock {stock_id} already exists")
                continue

            # Create the stock
            stock = Stock(
                tenant_id=str(tenant_id),
                stock_id=stock_id,
                genotype=stock_data.genotype,
                origin="repository",
                repository=actual_repository,
                repository_stock_id=item.external_id,
                original_genotype=stock_data.genotype,
                notes=item.notes,
                created_by_id=current_user.id,
                external_metadata={
                    "source": "flybase",
                    "repository": actual_repository,
                    "flybase_id": stock_data.metadata.get("flybase_id"),
                    "flybase_url": stock_data.metadata.get("flybase_url"),
                    "repository_url": stock_data.metadata.get("repository_url"),
                    "data_version": stock_data.metadata.get("data_version"),
                    "imported_at": datetime.utcnow().isoformat(),
                },
            )
            db.add(stock)
            db.flush()  # Get stock ID

            # Also create an ExternalReference record
            ref = ExternalReference(
                stock_id=stock.id,
                source=f"flybase:{actual_repository}",
                external_id=item.external_id,
                data=stock_data.metadata,
            )
            db.add(ref)

            result.imported += 1
            result.imported_ids.append(stock.id)

        except HTTPException as e:
            result.errors.append(f"Error importing {item.external_id}: {e.detail}")
        except Exception as e:
            logger.error(f"Error importing {item.external_id}: {e}")
            result.errors.append(f"Error importing {item.external_id}: {str(e)}")

    # Commit all successful imports
    if result.imported > 0:
        db.commit()

    return result
