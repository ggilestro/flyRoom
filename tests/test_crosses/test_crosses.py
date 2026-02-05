"""Tests for crosses module."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Cross, CrossStatus, Stock, Tenant, User


@pytest.fixture
def female_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a female parent stock."""
    stock = Stock(
        tenant_id=test_tenant.id,
        stock_id="FEMALE-001",
        genotype="w[1118]; +; +",
        source="Lab",
        created_by_id=test_user.id,
        modified_by_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def male_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a male parent stock."""
    stock = Stock(
        tenant_id=test_tenant.id,
        stock_id="MALE-001",
        genotype="y[1] w[*]; P{UAS-GFP}; +",
        source="Lab",
        created_by_id=test_user.id,
        modified_by_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def test_cross(
    db: Session, test_tenant: Tenant, test_user: User, female_stock: Stock, male_stock: Stock
) -> Cross:
    """Create a test cross."""
    cross = Cross(
        tenant_id=test_tenant.id,
        name="Test Cross",
        parent_female_id=female_stock.id,
        parent_male_id=male_stock.id,
        status=CrossStatus.PLANNED,
        created_by_id=test_user.id,
    )
    db.add(cross)
    db.commit()
    db.refresh(cross)
    return cross


class TestListCrosses:
    """Tests for listing crosses."""

    def test_list_crosses_empty(self, authenticated_client: TestClient):
        """Test listing crosses when none exist."""
        response = authenticated_client.get("/api/crosses")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_crosses_with_data(self, authenticated_client: TestClient, test_cross: Cross):
        """Test listing crosses returns existing crosses."""
        response = authenticated_client.get("/api/crosses")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Test Cross"


class TestCreateCross:
    """Tests for creating crosses."""

    def test_create_cross_success(
        self, authenticated_client: TestClient, female_stock: Stock, male_stock: Stock
    ):
        """Test successful cross creation."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "name": "New Cross",
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "notes": "Test cross",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Cross"
        assert data["status"] == "planned"

    def test_create_cross_same_parent(self, authenticated_client: TestClient, female_stock: Stock):
        """Test creating cross with same stock for both parents fails."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": female_stock.id,
            },
        )

        assert response.status_code == 400
        assert "itself" in response.json()["detail"]

    def test_create_cross_invalid_parent(self, authenticated_client: TestClient):
        """Test creating cross with invalid parent ID fails."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": "00000000-0000-0000-0000-000000000000",
                "parent_male_id": "00000000-0000-0000-0000-000000000001",
            },
        )

        assert response.status_code == 400


class TestCrossStatusTransitions:
    """Tests for cross status transitions."""

    def test_start_cross(self, authenticated_client: TestClient, test_cross: Cross):
        """Test starting a cross (planned -> in_progress)."""
        response = authenticated_client.post(f"/api/crosses/{test_cross.id}/start")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"

    def test_complete_cross(self, authenticated_client: TestClient, test_cross: Cross, db: Session):
        """Test completing a cross."""
        # First start the cross
        test_cross.status = CrossStatus.IN_PROGRESS
        db.commit()

        response = authenticated_client.post(
            f"/api/crosses/{test_cross.id}/complete",
            json={"notes": "Cross successful"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_fail_cross(self, authenticated_client: TestClient, test_cross: Cross, db: Session):
        """Test marking a cross as failed."""
        test_cross.status = CrossStatus.IN_PROGRESS
        db.commit()

        response = authenticated_client.post(
            f"/api/crosses/{test_cross.id}/fail",
            params={"notes": "No offspring"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"


class TestDeleteCross:
    """Tests for deleting crosses."""

    def test_delete_cross_success(
        self, authenticated_client: TestClient, test_cross: Cross, db: Session
    ):
        """Test successful cross deletion."""
        response = authenticated_client.delete(f"/api/crosses/{test_cross.id}")

        assert response.status_code == 204

        # Verify deletion
        deleted = db.query(Cross).filter(Cross.id == test_cross.id).first()
        assert deleted is None
