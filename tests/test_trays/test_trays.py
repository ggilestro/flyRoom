"""Tests for trays module."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Stock, Tenant, Tray, TrayType, User


class TestTrayService:
    """Tests for TrayService."""

    def test_list_trays_empty(self, db: Session, test_tenant: Tenant):
        """Test listing trays when none exist."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        result = service.list_trays()
        assert result.items == []
        assert result.total == 0

    def test_list_trays_with_data(self, db: Session, test_tenant: Tenant, test_tray: Tray):
        """Test listing trays returns existing trays."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        result = service.list_trays()
        assert len(result.items) == 1
        assert result.items[0].name == test_tray.name

    def test_get_tray(self, db: Session, test_tenant: Tenant, test_tray: Tray):
        """Test getting a tray by ID."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        result = service.get_tray(test_tray.id)
        assert result is not None
        assert result.name == test_tray.name

    def test_get_tray_not_found(self, db: Session, test_tenant: Tenant):
        """Test getting nonexistent tray."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        result = service.get_tray("nonexistent-id")
        assert result is None

    def test_create_tray_numeric(self, db: Session, test_tenant: Tenant):
        """Test creating a numeric tray."""
        from app.trays.schemas import TrayCreate
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        data = TrayCreate(
            name="New Tray",
            description="A test tray",
            tray_type=TrayType.NUMERIC,
            max_positions=50,
        )
        tray = service.create_tray(data)

        assert tray.name == "New Tray"
        assert tray.tray_type == TrayType.NUMERIC
        assert tray.max_positions == 50

    def test_create_tray_grid(self, db: Session, test_tenant: Tenant):
        """Test creating a grid tray."""
        from app.trays.schemas import TrayCreate
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        data = TrayCreate(
            name="Grid Tray",
            tray_type=TrayType.GRID,
            rows=8,
            cols=12,
        )
        tray = service.create_tray(data)

        assert tray.name == "Grid Tray"
        assert tray.tray_type == TrayType.GRID
        assert tray.rows == 8
        assert tray.cols == 12
        assert tray.max_positions == 96  # 8 * 12

    def test_create_tray_duplicate_name(self, db: Session, test_tenant: Tenant, test_tray: Tray):
        """Test creating tray with duplicate name fails."""
        from app.trays.schemas import TrayCreate
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        data = TrayCreate(name=test_tray.name)  # Same name
        with pytest.raises(ValueError, match="already exists"):
            service.create_tray(data)

    def test_update_tray(self, db: Session, test_tenant: Tenant, test_tray: Tray):
        """Test updating a tray."""
        from app.trays.schemas import TrayUpdate
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        data = TrayUpdate(description="Updated description")
        tray = service.update_tray(test_tray.id, data)

        assert tray.description == "Updated description"

    def test_delete_tray(self, db: Session, test_tenant: Tenant, test_tray: Tray):
        """Test deleting a tray."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        result = service.delete_tray(test_tray.id)
        assert result is True

        # Verify deleted
        assert service.get_tray(test_tray.id) is None

    def test_validate_position_numeric_valid(
        self, db: Session, test_tenant: Tenant, test_tray: Tray
    ):
        """Test validating a valid numeric position."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        assert service.validate_position(test_tray.id, "42") is True

    def test_validate_position_numeric_invalid(
        self, db: Session, test_tenant: Tenant, test_tray: Tray
    ):
        """Test validating an invalid numeric position."""
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)
        assert service.validate_position(test_tray.id, "999") is False

    def test_get_tray_detail_with_positions(
        self, db: Session, test_tenant: Tenant, test_user: User
    ):
        """Test getting tray detail with position information."""
        from uuid import uuid4

        from app.trays.schemas import TrayCreate
        from app.trays.service import TrayService

        service = TrayService(db, test_tenant.id)

        # Create a small tray
        tray_data = TrayCreate(name="Small Tray", max_positions=5)
        tray = service.create_tray(tray_data)

        # Add a stock to position 3
        stock = Stock(
            id=str(uuid4()),
            tenant_id=test_tenant.id,
            stock_id="TEST-001",
            genotype="test",
            tray_id=tray.id,
            position="3",
            created_by_id=test_user.id,
        )
        db.add(stock)
        db.commit()

        # Get tray detail
        detail = service.get_tray_detail(tray.id)

        assert detail is not None
        assert len(detail.positions) == 5
        # Position 3 should have the stock
        pos3 = next(p for p in detail.positions if p.position == "3")
        assert pos3.stock_id == stock.id
        assert pos3.stock_name == "TEST-001"
        # Position 1 should be empty
        pos1 = next(p for p in detail.positions if p.position == "1")
        assert pos1.stock_id is None


class TestTrayRouter:
    """Tests for tray API endpoints."""

    def test_list_trays(self, authenticated_client: TestClient, test_tray: Tray):
        """Test listing trays via API."""
        response = authenticated_client.get("/api/trays")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == test_tray.name

    def test_create_tray(self, authenticated_client: TestClient):
        """Test creating a tray via API."""
        response = authenticated_client.post(
            "/api/trays",
            json={
                "name": "API Tray",
                "description": "Created via API",
                "tray_type": "numeric",
                "max_positions": 100,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "API Tray"

    def test_get_tray(self, authenticated_client: TestClient, test_tray: Tray):
        """Test getting a tray via API."""
        response = authenticated_client.get(f"/api/trays/{test_tray.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_tray.name
        # Should include positions
        assert "positions" in data

    def test_delete_tray(self, authenticated_client: TestClient, test_tray: Tray):
        """Test deleting a tray via API."""
        response = authenticated_client.delete(f"/api/trays/{test_tray.id}")
        assert response.status_code == 204
