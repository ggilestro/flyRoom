"""Tests for stocks module."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Stock, Tag, Tenant, User


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
def test_tag(db: Session, test_tenant: Tenant) -> Tag:
    """Create a test tag."""
    tag = Tag(
        tenant_id=test_tenant.id,
        name="driver",
        color="#FF0000",
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


class TestListStocks:
    """Tests for listing stocks."""

    def test_list_stocks_empty(self, authenticated_client: TestClient):
        """Test listing stocks when none exist."""
        response = authenticated_client.get("/api/stocks")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_stocks_with_data(self, authenticated_client: TestClient, test_stock: Stock):
        """Test listing stocks returns existing stocks."""
        response = authenticated_client.get("/api/stocks")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["stock_id"] == "BL-1234"

    def test_list_stocks_search(self, authenticated_client: TestClient, test_stock: Stock):
        """Test searching stocks by query."""
        response = authenticated_client.get("/api/stocks?query=elav")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1

    def test_list_stocks_search_no_match(self, authenticated_client: TestClient, test_stock: Stock):
        """Test searching stocks with no match."""
        response = authenticated_client.get("/api/stocks?query=nonexistent")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0


class TestCreateStock:
    """Tests for creating stocks."""

    def test_create_stock_success(self, authenticated_client: TestClient):
        """Test successful stock creation."""
        response = authenticated_client.post(
            "/api/stocks",
            json={
                "stock_id": "NEW-001",
                "genotype": "w[*]; UAS-GFP",
                "notes": "New stock",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["stock_id"] == "NEW-001"
        assert data["genotype"] == "w[*]; UAS-GFP"

    def test_create_stock_duplicate_id(self, authenticated_client: TestClient, test_stock: Stock):
        """Test creating stock with duplicate ID fails."""
        response = authenticated_client.post(
            "/api/stocks",
            json={
                "stock_id": "BL-1234",  # Same as test_stock
                "genotype": "Different genotype",
            },
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_create_stock_missing_required(self, authenticated_client: TestClient):
        """Test creating stock without required fields fails."""
        response = authenticated_client.post(
            "/api/stocks",
            json={
                "stock_id": "NEW-002",
                # Missing genotype
            },
        )

        assert response.status_code == 422


class TestGetStock:
    """Tests for getting a single stock."""

    def test_get_stock_success(self, authenticated_client: TestClient, test_stock: Stock):
        """Test getting a stock by ID."""
        response = authenticated_client.get(f"/api/stocks/{test_stock.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["stock_id"] == test_stock.stock_id
        assert data["genotype"] == test_stock.genotype

    def test_get_stock_not_found(self, authenticated_client: TestClient):
        """Test getting nonexistent stock returns 404."""
        response = authenticated_client.get("/api/stocks/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404


class TestUpdateStock:
    """Tests for updating stocks."""

    def test_update_stock_success(self, authenticated_client: TestClient, test_stock: Stock):
        """Test successful stock update."""
        response = authenticated_client.put(
            f"/api/stocks/{test_stock.id}",
            json={
                "external_source": "Another Lab",
                "notes": "Updated notes",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["external_source"] == "Another Lab"
        assert data["notes"] == "Updated notes"


class TestDeleteStock:
    """Tests for deleting stocks."""

    def test_delete_stock_success(
        self, authenticated_client: TestClient, test_stock: Stock, db: Session
    ):
        """Test successful stock deletion (soft delete)."""
        response = authenticated_client.delete(f"/api/stocks/{test_stock.id}")

        assert response.status_code == 204

        # Verify soft delete
        db.refresh(test_stock)
        assert test_stock.is_active is False

    def test_delete_stock_not_found(self, authenticated_client: TestClient):
        """Test deleting nonexistent stock returns 404."""
        response = authenticated_client.delete("/api/stocks/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404


class TestSearchStocksHTML:
    """Tests for the HTMX search endpoint."""

    def test_search_returns_html(self, authenticated_client: TestClient, test_stock: Stock):
        """Test that search endpoint returns HTML content."""
        response = authenticated_client.get("/api/stocks/search?search=elav")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "BL-1234" in response.text

    def test_search_short_query_returns_empty(self, authenticated_client: TestClient):
        """Test that queries under 2 chars return empty response."""
        response = authenticated_client.get("/api/stocks/search?search=a")

        assert response.status_code == 200
        assert response.text == ""

    def test_search_no_results(self, authenticated_client: TestClient, test_stock: Stock):
        """Test search with no matches shows appropriate message."""
        response = authenticated_client.get("/api/stocks/search?search=nonexistent")

        assert response.status_code == 200
        assert "No stocks found" in response.text


class TestTags:
    """Tests for tag operations."""

    def test_list_tags(self, authenticated_client: TestClient, test_tag: Tag):
        """Test listing tags."""
        response = authenticated_client.get("/api/stocks/tags/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "driver"

    def test_create_tag(self, authenticated_client: TestClient):
        """Test creating a tag."""
        response = authenticated_client.post(
            "/api/stocks/tags/",
            json={
                "name": "balancer",
                "color": "#00FF00",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "balancer"
        assert data["color"] == "#00FF00"
