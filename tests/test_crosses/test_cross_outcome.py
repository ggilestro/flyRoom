"""Tests for cross outcome type feature (ephemeral, intermediate, new_stock)."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.db.models import Stock, Tenant, User


@pytest.fixture
def female_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a female parent stock."""
    stock = Stock(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        stock_id="F-001",
        genotype="w[1118]; P{GAL4-da.G32}UH1/CyO",
        created_by_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def male_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a male parent stock."""
    stock = Stock(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        stock_id="M-001",
        genotype="w[*]; P{UAS-mCD8::GFP.L}Ptp4E[LL03]",
        created_by_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


class TestEphemeralCross:
    """Tests for ephemeral outcome crosses."""

    def test_create_ephemeral_no_offspring(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Ephemeral cross should NOT auto-create offspring stock."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "ephemeral",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["outcome_type"] == "ephemeral"
        assert data["offspring"] is None


class TestIntermediateCross:
    """Tests for intermediate outcome crosses."""

    def test_create_intermediate_auto_creates_offspring(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Intermediate cross should auto-create placeholder offspring stock."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["outcome_type"] == "intermediate"
        assert data["offspring"] is not None
        assert data["offspring"]["stock_id"] == "CX-001"
        assert data["offspring"]["is_placeholder"] is True
        assert data["offspring"]["genotype"] == "w; da-GAL4/UAS-mCD8-GFP"

    def test_intermediate_without_genotype_fails(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Intermediate cross without target_genotype should return 422."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
            },
        )

        assert response.status_code == 422


class TestNewStockCross:
    """Tests for new_stock outcome crosses."""

    def test_create_new_stock_auto_creates_offspring(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """New stock cross should auto-create placeholder offspring stock."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "new_stock",
                "target_genotype": "w; UAS-GFP/CyO; da-GAL4/TM3",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["outcome_type"] == "new_stock"
        assert data["offspring"] is not None
        assert data["offspring"]["is_placeholder"] is True


class TestOffspringInSearch:
    """Test that placeholder offspring appear in stock search."""

    def test_offspring_appears_in_stock_search(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Placeholder offspring should be findable via stock search."""
        # Create intermediate cross
        create_resp = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )
        assert create_resp.status_code == 201

        # Search for the offspring stock by CX- prefix
        search_resp = authenticated_client.get("/api/stocks?query=CX-001")
        assert search_resp.status_code == 200
        data = search_resp.json()
        assert data["total"] >= 1
        cx_stocks = [s for s in data["items"] if s["stock_id"] == "CX-001"]
        assert len(cx_stocks) == 1
        assert cx_stocks[0]["is_placeholder"] is True


class TestCrossLifecycle:
    """Tests for cross lifecycle affecting offspring state."""

    def test_complete_cross_confirms_offspring(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Completing a cross should set offspring is_placeholder=False."""
        # Create intermediate cross
        create_resp = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )
        assert create_resp.status_code == 201
        cross_id = create_resp.json()["id"]

        # Start the cross
        start_resp = authenticated_client.post(f"/api/crosses/{cross_id}/start")
        assert start_resp.status_code == 200

        # Complete the cross
        complete_resp = authenticated_client.post(
            f"/api/crosses/{cross_id}/complete",
            json={},
        )
        assert complete_resp.status_code == 200
        data = complete_resp.json()
        assert data["offspring"]["is_placeholder"] is False

    def test_fail_cross_deactivates_offspring(
        self,
        db: Session,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Failing a cross should set offspring is_active=False."""
        # Create intermediate cross
        create_resp = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )
        assert create_resp.status_code == 201
        cross_data = create_resp.json()
        offspring_id = cross_data["offspring"]["id"]
        cross_id = cross_data["id"]

        # Fail the cross
        fail_resp = authenticated_client.post(f"/api/crosses/{cross_id}/fail")
        assert fail_resp.status_code == 200

        # Verify offspring is deactivated
        offspring = db.query(Stock).filter(Stock.id == offspring_id).first()
        assert offspring is not None
        assert offspring.is_active is False
        assert offspring.is_placeholder is True  # Still flagged as placeholder


class TestOutcomeTypeTransitions:
    """Tests for changing outcome type on existing crosses."""

    def test_change_ephemeral_to_intermediate_creates_offspring(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Changing outcome from ephemeral to intermediate should create offspring."""
        # Create ephemeral cross with a genotype
        create_resp = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "ephemeral",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )
        assert create_resp.status_code == 201
        cross_id = create_resp.json()["id"]
        assert create_resp.json()["offspring"] is None

        # Update to intermediate
        update_resp = authenticated_client.put(
            f"/api/crosses/{cross_id}",
            json={"outcome_type": "intermediate"},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["outcome_type"] == "intermediate"
        assert data["offspring"] is not None
        assert data["offspring"]["is_placeholder"] is True

    def test_change_intermediate_to_ephemeral_deactivates_offspring(
        self,
        db: Session,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Changing outcome from intermediate to ephemeral should deactivate offspring."""
        # Create intermediate cross
        create_resp = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "outcome_type": "intermediate",
                "target_genotype": "w; da-GAL4/UAS-mCD8-GFP",
            },
        )
        assert create_resp.status_code == 201
        cross_data = create_resp.json()
        offspring_id = cross_data["offspring"]["id"]
        cross_id = cross_data["id"]

        # Switch to ephemeral
        update_resp = authenticated_client.put(
            f"/api/crosses/{cross_id}",
            json={"outcome_type": "ephemeral"},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["offspring"] is None  # Unlinked

        # Verify offspring is deactivated
        offspring = db.query(Stock).filter(Stock.id == offspring_id).first()
        assert offspring is not None
        assert offspring.is_active is False


class TestSequentialStockIds:
    """Tests for sequential CX-NNN stock ID generation."""

    def test_sequential_stock_id_generation(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Should generate CX-001, CX-002, CX-003 sequentially."""
        ids = []
        for i in range(3):
            resp = authenticated_client.post(
                "/api/crosses",
                json={
                    "parent_female_id": female_stock.id,
                    "parent_male_id": male_stock.id,
                    "outcome_type": "intermediate",
                    "target_genotype": f"genotype-{i + 1}",
                },
            )
            assert resp.status_code == 201
            ids.append(resp.json()["offspring"]["stock_id"])

        assert ids == ["CX-001", "CX-002", "CX-003"]
