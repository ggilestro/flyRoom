"""Tests for organizations module."""

import pytest
from sqlalchemy.orm import Session

from app.db.models import Organization, Tenant
from app.organizations.service import normalize_name, similarity_score, slugify


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_normalize_name_lowercase(self):
        """Test normalize_name converts to lowercase."""
        # Note: 'college' gets removed by the pattern
        result = normalize_name("IMPERIAL COLLEGE")
        assert "imperial" in result

    def test_normalize_name_removes_the(self):
        """Test normalize_name removes 'The' prefix."""
        result = normalize_name("The University of Oxford")
        assert "the" not in result.lower().split()

    def test_normalize_name_removes_punctuation(self):
        """Test normalize_name removes punctuation."""
        assert normalize_name("King's College, London") == "kings college london"

    def test_slugify_basic(self):
        """Test basic slugify."""
        assert slugify("Imperial College London") == "imperial-college-london"

    def test_slugify_removes_special(self):
        """Test slugify removes special characters."""
        assert slugify("King's College") == "kings-college"

    def test_similarity_score_identical(self):
        """Test similarity score for identical strings."""
        assert similarity_score("test", "test") == 1.0

    def test_similarity_score_similar(self):
        """Test similarity score for similar strings."""
        score = similarity_score("Imperial College", "Imperial Colleg")
        assert score > 0.9

    def test_similarity_score_different(self):
        """Test similarity score for different strings."""
        score = similarity_score("Oxford", "Cambridge")
        assert score < 0.5


class TestOrganizationService:
    """Tests for OrganizationService."""

    def test_list_organizations_empty(self, db: Session):
        """Test listing organizations when none exist."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        result = service.list_organizations()
        assert result == []

    def test_list_organizations_with_data(self, db: Session, test_organization: Organization):
        """Test listing organizations returns existing organizations."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        result = service.list_organizations()
        assert len(result) == 1
        assert result[0].name == test_organization.name

    def test_get_organization(self, db: Session, test_organization: Organization):
        """Test getting an organization by ID."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        result = service.get_organization(test_organization.id)
        assert result is not None
        assert result.name == test_organization.name

    def test_get_organization_not_found(self, db: Session):
        """Test getting nonexistent organization."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        result = service.get_organization("nonexistent-id")
        assert result is None

    def test_search_organizations(self, db: Session, test_organization: Organization):
        """Test searching organizations."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        # Use exact name to ensure match
        result = service.search_organizations(test_organization.name, limit=10, min_score=0.3)
        assert len(result) == 1
        assert result[0].name == test_organization.name
        assert result[0].similarity_score > 0.5

    def test_search_organizations_no_match(self, db: Session):
        """Test searching organizations with no match."""
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        result = service.search_organizations("nonexistent", min_score=0.9)
        assert result == []

    def test_create_organization_success(self, db: Session, test_tenant: Tenant):
        """Test creating an organization."""
        from app.organizations.schemas import OrganizationCreate
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        data = OrganizationCreate(
            name="New University",
            description="A new university",
        )
        org = service.create_organization(data, test_tenant.id)

        assert org.name == "New University"
        assert org.slug == "new-university"
        # Verify tenant is now org admin
        db.refresh(test_tenant)
        assert test_tenant.organization_id == org.id
        assert test_tenant.is_org_admin is True

    def test_create_organization_duplicate_slug(
        self, db: Session, test_organization: Organization, test_tenant: Tenant
    ):
        """Test creating organization with duplicate slug fails."""
        from app.organizations.schemas import OrganizationCreate
        from app.organizations.service import OrganizationService

        service = OrganizationService(db)
        data = OrganizationCreate(
            name="Test University",  # Same as fixture
        )
        with pytest.raises(ValueError, match="already exists"):
            service.create_organization(data, test_tenant.id)


class TestTenantGeoService:
    """Tests for TenantGeoService."""

    def test_update_geo_info(self, db: Session, test_tenant: Tenant):
        """Test updating tenant geographic info."""
        from app.organizations.schemas import TenantGeoUpdate
        from app.organizations.service import TenantGeoService

        service = TenantGeoService(db, test_tenant.id)
        data = TenantGeoUpdate(
            city="London",
            country="UK",
            latitude=51.5074,
            longitude=-0.1278,
        )
        tenant = service.update_geo_info(data)

        assert tenant.city == "London"
        assert tenant.country == "UK"
        assert tenant.latitude == 51.5074
        assert tenant.longitude == -0.1278
