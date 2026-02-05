"""Organization service layer."""

import re
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Organization,
    OrganizationJoinRequest,
    OrgJoinRequestStatus,
    Tenant,
)
from app.organizations.schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationSearchResult,
    OrganizationUpdate,
    OrgJoinRequestCreate,
    OrgJoinRequestResponse,
    TenantGeoUpdate,
)


def normalize_name(name: str) -> str:
    """Normalize organization name for duplicate detection.

    Args:
        name: Original organization name.

    Returns:
        str: Normalized name (lowercase, no punctuation, trimmed).
    """
    # Convert to lowercase
    normalized = name.lower()
    # Remove common prefixes/suffixes that cause duplicates
    patterns_to_remove = [
        r"^the\s+",  # "The University" -> "University"
        r"\s+university$",  # Handled separately
        r"\s+college$",
        r"\s+institute$",
    ]
    for pattern in patterns_to_remove:
        normalized = re.sub(pattern, "", normalized)
    # Remove punctuation and extra whitespace
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def slugify(name: str) -> str:
    """Convert name to URL-friendly slug.

    Args:
        name: Organization name.

    Returns:
        str: URL-friendly slug.
    """
    slug = name.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def similarity_score(s1: str, s2: str) -> float:
    """Calculate similarity between two strings.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        float: Similarity score between 0 and 1.
    """
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


class OrganizationService:
    """Service class for organization operations."""

    def __init__(self, db: Session):
        """Initialize organization service.

        Args:
            db: Database session.
        """
        self.db = db

    def list_organizations(self, skip: int = 0, limit: int = 100) -> list[OrganizationResponse]:
        """List all active organizations.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            list[OrganizationResponse]: List of organizations.
        """
        organizations = (
            self.db.query(Organization)
            .filter(Organization.is_active)
            .order_by(Organization.name)
            .offset(skip)
            .limit(limit)
            .all()
        )

        result = []
        for org in organizations:
            lab_count = (
                self.db.query(func.count(Tenant.id))
                .filter(Tenant.organization_id == org.id)
                .scalar()
            )
            result.append(
                OrganizationResponse(
                    id=org.id,
                    name=org.name,
                    slug=org.slug,
                    description=org.description,
                    website=org.website,
                    is_active=org.is_active,
                    created_at=org.created_at,
                    lab_count=lab_count,
                )
            )
        return result

    def get_organization(self, org_id: str) -> OrganizationResponse | None:
        """Get an organization by ID.

        Args:
            org_id: Organization UUID.

        Returns:
            OrganizationResponse | None: Organization if found.
        """
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            return None

        lab_count = (
            self.db.query(func.count(Tenant.id)).filter(Tenant.organization_id == org.id).scalar()
        )
        return OrganizationResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            description=org.description,
            website=org.website,
            is_active=org.is_active,
            created_at=org.created_at,
            lab_count=lab_count,
        )

    def search_organizations(
        self, query: str, limit: int = 10, min_score: float = 0.5
    ) -> list[OrganizationSearchResult]:
        """Search for organizations with fuzzy matching.

        Args:
            query: Search query.
            limit: Maximum number of results.
            min_score: Minimum similarity score (0-1).

        Returns:
            list[OrganizationSearchResult]: Matching organizations sorted by score.
        """
        normalized_query = normalize_name(query)
        organizations = self.db.query(Organization).filter(Organization.is_active).all()

        results = []
        for org in organizations:
            # Check against both name and normalized_name
            score = max(
                similarity_score(query, org.name),
                similarity_score(normalized_query, org.normalized_name),
            )
            if score >= min_score:
                results.append(
                    OrganizationSearchResult(
                        id=org.id,
                        name=org.name,
                        slug=org.slug,
                        similarity_score=score,
                    )
                )

        # Sort by score descending
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        return results[:limit]

    def create_organization(self, data: OrganizationCreate, tenant_id: str) -> Organization:
        """Create a new organization and make the tenant the org admin.

        Args:
            data: Organization creation data.
            tenant_id: Tenant ID of the creating lab (becomes org admin).

        Returns:
            Organization: Created organization.

        Raises:
            ValueError: If organization name/slug already exists.
        """
        slug = slugify(data.name)
        normalized = normalize_name(data.name)

        # Check for duplicate slug
        existing = self.db.query(Organization).filter(Organization.slug == slug).first()
        if existing:
            raise ValueError(f"Organization with slug '{slug}' already exists")

        # Check for similar names
        similar = self.search_organizations(data.name, limit=1, min_score=0.9)
        if similar:
            raise ValueError(
                f"Similar organization exists: '{similar[0].name}'. "
                "Consider joining the existing organization instead."
            )

        org = Organization(
            name=data.name,
            slug=slug,
            normalized_name=normalized,
            description=data.description,
            website=data.website,
        )

        self.db.add(org)
        self.db.flush()  # Get the org ID

        # Make the creating tenant the org admin
        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant:
            tenant.organization_id = org.id
            tenant.is_org_admin = True

        self.db.commit()
        self.db.refresh(org)
        return org

    def update_organization(self, org_id: str, data: OrganizationUpdate) -> Organization | None:
        """Update an organization.

        Args:
            org_id: Organization UUID.
            data: Update data.

        Returns:
            Organization | None: Updated organization if found.
        """
        org = self.db.query(Organization).filter(Organization.id == org_id).first()
        if not org:
            return None

        if data.name:
            org.name = data.name
            org.normalized_name = normalize_name(data.name)
        if data.description is not None:
            org.description = data.description
        if data.website is not None:
            org.website = data.website

        self.db.commit()
        self.db.refresh(org)
        return org


class OrgJoinRequestService:
    """Service class for organization join request operations."""

    def __init__(self, db: Session, tenant_id: str, user_id: str):
        """Initialize org join request service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
            user_id: Current user ID.
        """
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def create_join_request(self, data: OrgJoinRequestCreate) -> OrganizationJoinRequest:
        """Create a join request to an organization.

        Args:
            data: Join request data.

        Returns:
            OrganizationJoinRequest: Created request.

        Raises:
            ValueError: If tenant already in org or request already pending.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if tenant.organization_id:
            raise ValueError("Lab is already part of an organization")

        # Check for existing pending request
        existing = (
            self.db.query(OrganizationJoinRequest)
            .filter(
                OrganizationJoinRequest.tenant_id == self.tenant_id,
                OrganizationJoinRequest.organization_id == data.organization_id,
                OrganizationJoinRequest.status == OrgJoinRequestStatus.PENDING,
            )
            .first()
        )
        if existing:
            raise ValueError("A pending request to this organization already exists")

        request = OrganizationJoinRequest(
            organization_id=data.organization_id,
            tenant_id=self.tenant_id,
            requested_by_id=self.user_id,
            message=data.message,
        )

        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def _request_to_response(self, request: OrganizationJoinRequest) -> OrgJoinRequestResponse:
        """Convert join request model to response schema."""
        return OrgJoinRequestResponse(
            id=request.id,
            organization_id=request.organization_id,
            organization_name=request.organization.name,
            tenant_id=request.tenant_id,
            tenant_name=request.tenant.name,
            requested_by_name=(request.requested_by.full_name if request.requested_by else None),
            status=request.status,
            message=request.message,
            created_at=request.created_at,
            responded_at=request.responded_at,
            responded_by_name=(request.responded_by.full_name if request.responded_by else None),
        )

    def list_pending_requests(self) -> list[OrgJoinRequestResponse]:
        """List pending join requests for organizations where current tenant is admin.

        Returns:
            list[OrgJoinRequestResponse]: Pending requests.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if not tenant or not tenant.is_org_admin or not tenant.organization_id:
            return []

        requests = (
            self.db.query(OrganizationJoinRequest)
            .filter(
                OrganizationJoinRequest.organization_id == tenant.organization_id,
                OrganizationJoinRequest.status == OrgJoinRequestStatus.PENDING,
            )
            .order_by(OrganizationJoinRequest.created_at.desc())
            .all()
        )
        return [self._request_to_response(r) for r in requests]

    def approve_request(self, request_id: str) -> OrganizationJoinRequest | None:
        """Approve a join request.

        Args:
            request_id: Join request UUID.

        Returns:
            OrganizationJoinRequest | None: Updated request if found.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if not tenant or not tenant.is_org_admin:
            return None

        request = (
            self.db.query(OrganizationJoinRequest)
            .filter(
                OrganizationJoinRequest.id == request_id,
                OrganizationJoinRequest.organization_id == tenant.organization_id,
                OrganizationJoinRequest.status == OrgJoinRequestStatus.PENDING,
            )
            .first()
        )
        if not request:
            return None

        # Update request status
        request.status = OrgJoinRequestStatus.APPROVED
        request.responded_at = datetime.now(UTC)
        request.responded_by_id = self.user_id

        # Add tenant to organization
        requesting_tenant = self.db.query(Tenant).filter(Tenant.id == request.tenant_id).first()
        if requesting_tenant:
            requesting_tenant.organization_id = request.organization_id

        self.db.commit()
        self.db.refresh(request)
        return request

    def reject_request(self, request_id: str) -> OrganizationJoinRequest | None:
        """Reject a join request.

        Args:
            request_id: Join request UUID.

        Returns:
            OrganizationJoinRequest | None: Updated request if found.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if not tenant or not tenant.is_org_admin:
            return None

        request = (
            self.db.query(OrganizationJoinRequest)
            .filter(
                OrganizationJoinRequest.id == request_id,
                OrganizationJoinRequest.organization_id == tenant.organization_id,
                OrganizationJoinRequest.status == OrgJoinRequestStatus.PENDING,
            )
            .first()
        )
        if not request:
            return None

        request.status = OrgJoinRequestStatus.REJECTED
        request.responded_at = datetime.now(UTC)
        request.responded_by_id = self.user_id

        self.db.commit()
        self.db.refresh(request)
        return request


class TenantGeoService:
    """Service for tenant geographic information."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize tenant geo service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id

    def update_geo_info(self, data: TenantGeoUpdate) -> Tenant | None:
        """Update tenant geographic information.

        Args:
            data: Geographic update data.

        Returns:
            Tenant | None: Updated tenant if found.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if not tenant:
            return None

        if data.city is not None:
            tenant.city = data.city
        if data.country is not None:
            tenant.country = data.country
        if data.latitude is not None:
            tenant.latitude = data.latitude
        if data.longitude is not None:
            tenant.longitude = data.longitude

        self.db.commit()
        self.db.refresh(tenant)
        return tenant

    def leave_organization(self) -> bool:
        """Remove tenant from its organization.

        Returns:
            bool: True if successful.
        """
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        if not tenant or not tenant.organization_id:
            return False

        # Can't leave if you're the only org admin
        if tenant.is_org_admin:
            other_admins = (
                self.db.query(Tenant)
                .filter(
                    Tenant.organization_id == tenant.organization_id,
                    Tenant.is_org_admin,
                    Tenant.id != tenant.id,
                )
                .count()
            )
            if other_admins == 0:
                raise ValueError(
                    "Cannot leave organization: you are the only admin. "
                    "Assign another admin first."
                )

        tenant.organization_id = None
        tenant.is_org_admin = False
        self.db.commit()
        return True


def get_organization_service(db: Session) -> OrganizationService:
    """Factory function for OrganizationService.

    Args:
        db: Database session.

    Returns:
        OrganizationService: Organization service instance.
    """
    return OrganizationService(db)


def get_org_join_request_service(
    db: Session, tenant_id: str, user_id: str
) -> OrgJoinRequestService:
    """Factory function for OrgJoinRequestService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        user_id: User ID.

    Returns:
        OrgJoinRequestService: Join request service instance.
    """
    return OrgJoinRequestService(db, tenant_id, user_id)


def get_tenant_geo_service(db: Session, tenant_id: str) -> TenantGeoService:
    """Factory function for TenantGeoService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        TenantGeoService: Tenant geo service instance.
    """
    return TenantGeoService(db, tenant_id)
