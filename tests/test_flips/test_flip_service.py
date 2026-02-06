"""Tests for flip tracking module."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import FlipEvent, Stock, Tenant, User
from app.flips.schemas import FlipEventCreate, FlipSettingsUpdate, FlipStatus
from app.flips.service import FlipService


@pytest.fixture
def test_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a test stock."""
    stock = Stock(
        tenant_id=test_tenant.id,
        stock_id="BL-1234",
        genotype="w[1118]; P{GAL4-elav.L}3",
        notes="Test stock",
        created_by_id=test_user.id,
        modified_by_id=test_user.id,
        owner_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def flip_service(db: Session, test_tenant: Tenant, test_user: User) -> FlipService:
    """Create a flip service for testing."""
    return FlipService(db, test_tenant.id, test_user.id)


class TestRecordFlip:
    """Tests for recording flip events."""

    def test_record_flip_success(self, flip_service: FlipService, test_stock: Stock, db: Session):
        """Test successfully recording a flip event."""
        data = FlipEventCreate(stock_id=test_stock.id, notes="Routine flip")
        result = flip_service.record_flip(data)

        assert result is not None
        assert result.stock_id == test_stock.id
        assert result.notes == "Routine flip"
        assert result.flipped_by_name is not None

    def test_record_flip_stock_not_found(self, flip_service: FlipService):
        """Test recording flip for nonexistent stock returns None."""
        data = FlipEventCreate(stock_id="00000000-0000-0000-0000-000000000000", notes="Test")
        result = flip_service.record_flip(data)

        assert result is None

    def test_record_flip_without_notes(self, flip_service: FlipService, test_stock: Stock):
        """Test recording flip without notes."""
        data = FlipEventCreate(stock_id=test_stock.id)
        result = flip_service.record_flip(data)

        assert result is not None
        assert result.notes is None


class TestGetFlipHistory:
    """Tests for flip history retrieval."""

    def test_get_flip_history_empty(self, flip_service: FlipService, test_stock: Stock):
        """Test getting history for stock with no flips."""
        result = flip_service.get_flip_history(test_stock.id)

        assert result == []

    def test_get_flip_history_with_events(
        self, flip_service: FlipService, test_stock: Stock, db: Session, test_user: User
    ):
        """Test getting history with flip events."""
        # Create some flip events with explicit timestamps
        from datetime import datetime, timedelta

        base_time = datetime.utcnow()
        for i in range(3):
            event = FlipEvent(
                stock_id=test_stock.id,
                flipped_by_id=test_user.id,
                notes=f"Flip {i}",
                flipped_at=base_time + timedelta(hours=i),  # Each flip is 1 hour later
            )
            db.add(event)
        db.commit()

        result = flip_service.get_flip_history(test_stock.id)

        assert len(result) == 3
        # Should be ordered most recent first (Flip 2 was the most recent)
        assert result[0].notes == "Flip 2"

    def test_get_flip_history_limit(
        self, flip_service: FlipService, test_stock: Stock, db: Session, test_user: User
    ):
        """Test history respects limit parameter."""
        # Create 5 flip events
        for i in range(5):
            event = FlipEvent(
                stock_id=test_stock.id,
                flipped_by_id=test_user.id,
                notes=f"Flip {i}",
            )
            db.add(event)
        db.commit()

        result = flip_service.get_flip_history(test_stock.id, limit=3)

        assert len(result) == 3

    def test_get_flip_history_stock_not_found(self, flip_service: FlipService):
        """Test getting history for nonexistent stock returns empty."""
        result = flip_service.get_flip_history("00000000-0000-0000-0000-000000000000")

        assert result == []


class TestGetStockFlipStatus:
    """Tests for flip status calculation."""

    def test_flip_status_never(self, flip_service: FlipService, test_stock: Stock):
        """Test stock with no flips returns NEVER status."""
        result = flip_service.get_stock_flip_status(test_stock.id)

        assert result is not None
        assert result.flip_status == FlipStatus.NEVER
        assert result.days_since_flip is None
        assert result.last_flip_at is None

    def test_flip_status_ok(
        self, flip_service: FlipService, test_stock: Stock, db: Session, test_user: User
    ):
        """Test stock recently flipped returns OK status."""
        # Create a recent flip (5 days ago)
        event = FlipEvent(
            stock_id=test_stock.id,
            flipped_by_id=test_user.id,
            flipped_at=datetime.utcnow() - timedelta(days=5),
        )
        db.add(event)
        db.commit()

        result = flip_service.get_stock_flip_status(test_stock.id)

        assert result is not None
        assert result.flip_status == FlipStatus.OK
        assert result.days_since_flip == 5

    def test_flip_status_warning(
        self,
        flip_service: FlipService,
        test_stock: Stock,
        db: Session,
        test_user: User,
        test_tenant: Tenant,
    ):
        """Test stock at warning threshold returns WARNING status."""
        # Create a flip 25 days ago (default warning is 21 days)
        event = FlipEvent(
            stock_id=test_stock.id,
            flipped_by_id=test_user.id,
            flipped_at=datetime.utcnow() - timedelta(days=25),
        )
        db.add(event)
        db.commit()

        result = flip_service.get_stock_flip_status(test_stock.id)

        assert result is not None
        assert result.flip_status == FlipStatus.WARNING
        assert result.days_since_flip == 25

    def test_flip_status_critical(
        self, flip_service: FlipService, test_stock: Stock, db: Session, test_user: User
    ):
        """Test stock at critical threshold returns CRITICAL status."""
        # Create a flip 35 days ago (default critical is 31 days)
        event = FlipEvent(
            stock_id=test_stock.id,
            flipped_by_id=test_user.id,
            flipped_at=datetime.utcnow() - timedelta(days=35),
        )
        db.add(event)
        db.commit()

        result = flip_service.get_stock_flip_status(test_stock.id)

        assert result is not None
        assert result.flip_status == FlipStatus.CRITICAL
        assert result.days_since_flip == 35

    def test_flip_status_stock_not_found(self, flip_service: FlipService):
        """Test status for nonexistent stock returns None."""
        result = flip_service.get_stock_flip_status("00000000-0000-0000-0000-000000000000")

        assert result is None


class TestGetStocksNeedingFlip:
    """Tests for getting stocks needing flip."""

    def test_no_stocks_needing_flip(
        self, flip_service: FlipService, test_stock: Stock, db: Session, test_user: User
    ):
        """Test when all stocks are recently flipped."""
        # Create a recent flip
        event = FlipEvent(
            stock_id=test_stock.id,
            flipped_by_id=test_user.id,
            flipped_at=datetime.utcnow() - timedelta(days=5),
        )
        db.add(event)
        db.commit()

        result = flip_service.get_stocks_needing_flip()

        assert len(result.warning) == 0
        assert len(result.critical) == 0
        assert len(result.never_flipped) == 0

    def test_stocks_never_flipped(self, flip_service: FlipService, test_stock: Stock):
        """Test stocks with no flip history are in never_flipped."""
        result = flip_service.get_stocks_needing_flip()

        assert len(result.never_flipped) == 1
        assert result.never_flipped[0].stock_id == test_stock.id

    def test_categorization_by_status(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        flip_service: FlipService,
    ):
        """Test stocks are correctly categorized."""
        # Create 3 stocks with different flip ages
        ok_stock = Stock(
            tenant_id=test_tenant.id,
            stock_id="OK-001",
            genotype="genotype1",
            created_by_id=test_user.id,
            modified_by_id=test_user.id,
            owner_id=test_user.id,
        )
        warning_stock = Stock(
            tenant_id=test_tenant.id,
            stock_id="WARN-001",
            genotype="genotype2",
            created_by_id=test_user.id,
            modified_by_id=test_user.id,
            owner_id=test_user.id,
        )
        critical_stock = Stock(
            tenant_id=test_tenant.id,
            stock_id="CRIT-001",
            genotype="genotype3",
            created_by_id=test_user.id,
            modified_by_id=test_user.id,
            owner_id=test_user.id,
        )
        db.add_all([ok_stock, warning_stock, critical_stock])
        db.commit()

        # Add flip events
        db.add(
            FlipEvent(
                stock_id=ok_stock.id,
                flipped_by_id=test_user.id,
                flipped_at=datetime.utcnow() - timedelta(days=5),
            )
        )
        db.add(
            FlipEvent(
                stock_id=warning_stock.id,
                flipped_by_id=test_user.id,
                flipped_at=datetime.utcnow() - timedelta(days=25),
            )
        )
        db.add(
            FlipEvent(
                stock_id=critical_stock.id,
                flipped_by_id=test_user.id,
                flipped_at=datetime.utcnow() - timedelta(days=40),
            )
        )
        db.commit()

        result = flip_service.get_stocks_needing_flip()

        assert len(result.warning) == 1
        assert result.warning[0].stock_display_id == "WARN-001"
        assert len(result.critical) == 1
        assert result.critical[0].stock_display_id == "CRIT-001"


class TestFlipSettings:
    """Tests for flip settings management."""

    def test_get_settings(self, flip_service: FlipService):
        """Test getting flip settings."""
        result = flip_service.get_flip_settings()

        assert result is not None
        assert result.flip_warning_days == 21  # Default
        assert result.flip_critical_days == 31  # Default
        assert result.flip_reminder_enabled is True  # Default

    def test_update_settings(self, flip_service: FlipService, test_tenant: Tenant, db: Session):
        """Test updating flip settings."""
        data = FlipSettingsUpdate(
            flip_warning_days=14,
            flip_critical_days=28,
            flip_reminder_enabled=False,
        )
        result = flip_service.update_flip_settings(data)

        assert result is not None
        assert result.flip_warning_days == 14
        assert result.flip_critical_days == 28
        assert result.flip_reminder_enabled is False

        # Verify persisted
        db.refresh(test_tenant)
        assert test_tenant.flip_warning_days == 14

    def test_update_partial_settings(self, flip_service: FlipService):
        """Test partial update of settings."""
        data = FlipSettingsUpdate(flip_warning_days=10)
        result = flip_service.update_flip_settings(data)

        assert result is not None
        assert result.flip_warning_days == 10
        assert result.flip_critical_days == 31  # Unchanged


class TestFlipAPI:
    """Tests for flip API endpoints."""

    def test_record_flip_api(self, authenticated_client: TestClient, test_stock: Stock):
        """Test POST /api/flips/record endpoint."""
        response = authenticated_client.post(
            "/api/flips/record",
            json={"stock_id": test_stock.id, "notes": "API test flip"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["stock_id"] == test_stock.id
        assert data["notes"] == "API test flip"

    def test_get_flip_history_api(self, authenticated_client: TestClient, test_stock: Stock):
        """Test GET /api/flips/stock/{id}/history endpoint."""
        response = authenticated_client.get(f"/api/flips/stock/{test_stock.id}/history")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_flip_status_api(self, authenticated_client: TestClient, test_stock: Stock):
        """Test GET /api/flips/stock/{id}/status endpoint."""
        response = authenticated_client.get(f"/api/flips/stock/{test_stock.id}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["flip_status"] == "never"

    def test_get_stocks_needing_flip_api(self, authenticated_client: TestClient):
        """Test GET /api/flips/needing-flip endpoint."""
        response = authenticated_client.get("/api/flips/needing-flip")

        assert response.status_code == 200
        data = response.json()
        assert "warning" in data
        assert "critical" in data
        assert "never_flipped" in data

    def test_get_settings_api(self, authenticated_client: TestClient):
        """Test GET /api/flips/settings endpoint."""
        response = authenticated_client.get("/api/flips/settings")

        assert response.status_code == 200
        data = response.json()
        assert "flip_warning_days" in data
        assert "flip_critical_days" in data
        assert "flip_reminder_enabled" in data

    def test_update_settings_api_requires_admin(self, authenticated_client: TestClient):
        """Test PUT /api/flips/settings requires admin role."""
        response = authenticated_client.put(
            "/api/flips/settings",
            json={"flip_warning_days": 14},
        )

        # Regular user should get 403
        assert response.status_code == 403

    def test_update_settings_api_admin(self, admin_client: TestClient):
        """Test PUT /api/flips/settings with admin."""
        response = admin_client.put(
            "/api/flips/settings",
            json={"flip_warning_days": 14, "flip_critical_days": 28},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["flip_warning_days"] == 14
        assert data["flip_critical_days"] == 28


class TestStockResponseFlipStatus:
    """Tests for flip status in stock API responses."""

    def test_stock_list_includes_flip_status(
        self, authenticated_client: TestClient, test_stock: Stock
    ):
        """Test that stock list includes flip status fields."""
        response = authenticated_client.get("/api/stocks")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        stock = data["items"][0]
        assert "flip_status" in stock
        assert "days_since_flip" in stock

    def test_stock_detail_includes_flip_status(
        self, authenticated_client: TestClient, test_stock: Stock
    ):
        """Test that stock detail includes flip status fields."""
        response = authenticated_client.get(f"/api/stocks/{test_stock.id}")

        assert response.status_code == 200
        data = response.json()
        assert "flip_status" in data
        assert "days_since_flip" in data
        assert "last_flip_at" in data
