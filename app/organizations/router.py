"""API router for organizations."""

import json
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models import UserRole
from app.dependencies import CurrentTenantId, CurrentUser, get_db
from app.organizations.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationSearchResult,
    OrganizationUpdate,
    OrgJoinRequestCreate,
    OrgJoinRequestResponse,
    TenantGeoUpdate,
    TenantLabelSettingsResponse,
    TenantLabelSettingsUpdate,
)
from app.organizations.service import (
    OrganizationService,
    OrgJoinRequestService,
    TenantGeoService,
)

router = APIRouter()


def get_org_service(
    db: Annotated[Session, Depends(get_db)],
) -> OrganizationService:
    """Get organization service dependency."""
    return OrganizationService(db)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    service: Annotated[OrganizationService, Depends(get_org_service)],
    skip: int = 0,
    limit: int = 100,
):
    """List all organizations."""
    return service.list_organizations(skip=skip, limit=limit)


@router.get("/search", response_model=list[OrganizationSearchResult])
async def search_organizations(
    q: str,
    service: Annotated[OrganizationService, Depends(get_org_service)],
    limit: int = 10,
):
    """Search organizations with fuzzy matching.

    Args:
        q: Search query.
        limit: Maximum results.
    """
    return service.search_organizations(query=q, limit=limit)


# University search helpers (for registration autocomplete)


def _load_local_universities() -> list[dict]:
    """Load local universities fallback data."""
    data_file = Path(__file__).parent.parent / "data" / "universities.json"
    if data_file.exists():
        with open(data_file) as f:
            return json.load(f)
    return []


def _search_local_universities(query: str, country: str | None = None) -> list[dict]:
    """Search local universities data."""
    universities = _load_local_universities()
    query_lower = query.lower()

    results = []
    for uni in universities:
        name_match = query_lower in uni["name"].lower()
        country_match = not country or country.lower() in uni["country"].lower()

        if name_match and country_match:
            results.append(uni)

    return results[:20]


@router.get("/universities/search")
async def search_universities(
    q: str = Query(..., min_length=2, description="University name search query"),
    country: str | None = Query(None, description="Country to filter by"),
):
    """Proxy endpoint for university search to avoid CORS issues.

    Uses the Hipo Universities API with local fallback.
    """
    url = f"https://universities.hipolabs.com/search?name={q}"
    if country:
        url += f"&country={country}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.HTTPError, httpx.ConnectError):
            # Fall back to local data
            return _search_local_universities(q, country)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    service: Annotated[OrganizationService, Depends(get_org_service)],
):
    """Get an organization by ID."""
    org = service.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    service: Annotated[OrganizationService, Depends(get_org_service)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Create a new organization (lab admin only).

    The creating lab becomes the organization admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only lab admins can create organizations")

    try:
        org = service.create_organization(data, str(tenant_id))
        return service.get_organization(org.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    data: OrganizationUpdate,
    service: Annotated[OrganizationService, Depends(get_org_service)],
    current_user: CurrentUser,
):
    """Update an organization (org admin only)."""
    tenant = current_user.tenant
    if not tenant.is_org_admin or tenant.organization_id != org_id:
        raise HTTPException(
            status_code=403, detail="Only organization admins can update the organization"
        )

    org = service.update_organization(org_id, data)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return service.get_organization(org_id)


# Join Request endpoints


@router.post(
    "/join-requests", response_model=OrgJoinRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_join_request(
    data: OrgJoinRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Request to join an organization (lab admin only)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403, detail="Only lab admins can request to join organizations"
        )

    service = OrgJoinRequestService(db, str(tenant_id), current_user.id)
    try:
        request = service.create_join_request(data)
        return service._request_to_response(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/join-requests/pending", response_model=list[OrgJoinRequestResponse])
async def list_pending_join_requests(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """List pending join requests for your organization (org admin only)."""
    service = OrgJoinRequestService(db, str(tenant_id), current_user.id)
    return service.list_pending_requests()


@router.put("/join-requests/{request_id}/approve", response_model=OrgJoinRequestResponse)
async def approve_join_request(
    request_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Approve a join request (org admin only)."""
    service = OrgJoinRequestService(db, str(tenant_id), current_user.id)
    request = service.approve_request(request_id)
    if not request:
        raise HTTPException(
            status_code=404, detail="Request not found or you don't have permission"
        )
    return service._request_to_response(request)


@router.put("/join-requests/{request_id}/reject", response_model=OrgJoinRequestResponse)
async def reject_join_request(
    request_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Reject a join request (org admin only)."""
    service = OrgJoinRequestService(db, str(tenant_id), current_user.id)
    request = service.reject_request(request_id)
    if not request:
        raise HTTPException(
            status_code=404, detail="Request not found or you don't have permission"
        )
    return service._request_to_response(request)


# Tenant geographic info endpoints


@router.put("/tenant/geo")
async def update_tenant_geo(
    data: TenantGeoUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Update lab geographic information (admin only)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403, detail="Only lab admins can update geographic information"
        )

    service = TenantGeoService(db, str(tenant_id))
    tenant = service.update_geo_info(data)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "city": tenant.city,
        "country": tenant.country,
        "latitude": tenant.latitude,
        "longitude": tenant.longitude,
    }


# Tenant label settings endpoints


@router.get("/tenant/label-settings", response_model=TenantLabelSettingsResponse)
async def get_tenant_label_settings(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
):
    """Get tenant label/print settings."""
    from app.db.models import Tenant

    tenant = db.query(Tenant).filter(Tenant.id == str(tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantLabelSettingsResponse(
        default_label_format=tenant.default_label_format,
        default_code_type=tenant.default_code_type,
        default_copies=tenant.default_copies,
    )


@router.put("/tenant/label-settings", response_model=TenantLabelSettingsResponse)
async def update_tenant_label_settings(
    data: TenantLabelSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Update tenant label/print settings (admin only)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only lab admins can update label settings")

    from app.db.models import Tenant

    tenant = db.query(Tenant).filter(Tenant.id == str(tenant_id)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.default_label_format = data.default_label_format
    tenant.default_code_type = data.default_code_type
    tenant.default_copies = data.default_copies
    db.commit()
    db.refresh(tenant)

    return TenantLabelSettingsResponse(
        default_label_format=tenant.default_label_format,
        default_code_type=tenant.default_code_type,
        default_copies=tenant.default_copies,
    )


@router.post("/tenant/leave")
async def leave_organization(
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
):
    """Remove lab from its organization (admin only)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only lab admins can leave organizations")

    service = TenantGeoService(db, str(tenant_id))
    try:
        service.leave_organization()
        return {"message": "Successfully left organization"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
