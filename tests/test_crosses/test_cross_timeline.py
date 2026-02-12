"""Tests for cross timeline features (flip/virgin collection tracking, genotype suggestions)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.db.models import Cross, CrossStatus, Stock, Tenant, User


@pytest.fixture
def female_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a female parent stock."""
    stock = Stock(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        stock_id="BL-001",
        genotype="w[1118]; P{GAL4-da.G32}UH1/CyO",
        shortname="da-GAL4; CyO",
        original_genotype="w[1118]; P{w[+mW.hs]=GAL4-da.G32}UH1, Pw[+mC]=UAS-2xEGFP",
        notes="Driver line",
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
        stock_id="BL-002",
        genotype="w[*]; P{UAS-mCD8::GFP.L}Ptp4E[LL03]",
        shortname="UAS-mCD8-GFP",
        notes="Responder line",
        created_by_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def test_cross(
    db: Session, test_tenant: Tenant, test_user: User, female_stock: Stock, male_stock: Stock
) -> Cross:
    """Create a test cross with timeline fields."""
    cross = Cross(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        name="Test Timeline Cross",
        parent_female_id=female_stock.id,
        parent_male_id=male_stock.id,
        status=CrossStatus.PLANNED,
        flip_days=5,
        virgin_collection_days=12,
        target_genotype="w; da-GAL4/UAS-mCD8-GFP",
        created_by_id=test_user.id,
    )
    db.add(cross)
    db.commit()
    db.refresh(cross)
    return cross


class TestCreateCrossWithTimeline:
    """Tests for creating crosses with timeline fields."""

    def test_create_cross_with_timeline_fields(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Test creating a cross with flip_days, virgin_collection_days, and target_genotype."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "name": "Timeline Cross",
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
                "target_genotype": "w; UAS-GFP/CyO; da-GAL4/+",
                "flip_days": 7,
                "virgin_collection_days": 14,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["target_genotype"] == "w; UAS-GFP/CyO; da-GAL4/+"
        assert data["flip_days"] == 7
        assert data["virgin_collection_days"] == 14

    def test_create_cross_default_timeline(
        self,
        authenticated_client: TestClient,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Test that default timeline values (5 and 12) are used when not specified."""
        response = authenticated_client.post(
            "/api/crosses",
            json={
                "parent_female_id": female_stock.id,
                "parent_male_id": male_stock.id,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["flip_days"] == 5
        assert data["virgin_collection_days"] == 12
        assert data["target_genotype"] is None


class TestTimelineComputation:
    """Tests for timeline computation logic."""

    def test_timeline_upcoming(
        self,
        db: Session,
        authenticated_client: TestClient,
        test_cross: Cross,
    ):
        """Test timeline computation shows positive days for upcoming events."""
        # Start the cross (sets executed_date to now)
        test_cross.status = CrossStatus.IN_PROGRESS
        test_cross.executed_date = datetime.now()
        db.commit()

        response = authenticated_client.get(f"/api/crosses/{test_cross.id}")
        assert response.status_code == 200
        data = response.json()

        # Flip should be ~5 days away
        assert data["days_until_flip"] is not None
        assert data["days_until_flip"] >= 4  # Allow small rounding
        assert data["flip_overdue"] is False
        assert data["flip_due_date"] is not None

        # Virgin collection should be ~12 days away
        assert data["days_until_virgin_collection"] is not None
        assert data["days_until_virgin_collection"] >= 11
        assert data["virgin_collection_overdue"] is False

    def test_timeline_overdue(
        self,
        db: Session,
        authenticated_client: TestClient,
        test_cross: Cross,
    ):
        """Test timeline computation shows negative days for overdue events."""
        # Set executed_date to 10 days ago (flip overdue, virgin collection upcoming)
        test_cross.status = CrossStatus.IN_PROGRESS
        test_cross.executed_date = datetime.now() - timedelta(days=10)
        db.commit()

        response = authenticated_client.get(f"/api/crosses/{test_cross.id}")
        assert response.status_code == 200
        data = response.json()

        # Flip was due 5 days after start, so 5 days overdue
        assert data["days_until_flip"] < 0
        assert data["flip_overdue"] is True

        # Virgin collection is 12 days after start, so 2 days remaining
        assert data["days_until_virgin_collection"] is not None
        assert data["days_until_virgin_collection"] >= 1
        assert data["virgin_collection_overdue"] is False

    def test_timeline_only_for_in_progress(
        self,
        authenticated_client: TestClient,
        test_cross: Cross,
    ):
        """Test that timeline fields are null for non-in-progress crosses."""
        # Cross is PLANNED status by default
        response = authenticated_client.get(f"/api/crosses/{test_cross.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["flip_due_date"] is None
        assert data["virgin_collection_due_date"] is None
        assert data["days_until_flip"] is None
        assert data["days_until_virgin_collection"] is None
        assert data["flip_overdue"] is False
        assert data["virgin_collection_overdue"] is False


class TestUpdateTimeline:
    """Tests for updating timeline fields."""

    def test_update_timeline_fields(
        self,
        authenticated_client: TestClient,
        test_cross: Cross,
    ):
        """Test updating flip_days, virgin_collection_days, and target_genotype."""
        response = authenticated_client.put(
            f"/api/crosses/{test_cross.id}",
            json={
                "flip_days": 3,
                "virgin_collection_days": 10,
                "target_genotype": "w; UAS-GFP/+; da-GAL4/+",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["flip_days"] == 3
        assert data["virgin_collection_days"] == 10
        assert data["target_genotype"] == "w; UAS-GFP/+; da-GAL4/+"


class TestSuggestGenotypes:
    """Tests for the AI genotype suggestion endpoint."""

    @patch("app.llm.service.get_llm_service")
    def test_suggest_genotypes_success(
        self,
        mock_get_llm,
        authenticated_client: TestClient,
    ):
        """Test successful genotype suggestion via LLM."""
        mock_llm = mock_get_llm.return_value
        mock_llm.configured = True
        mock_llm.ask = AsyncMock(
            return_value=(
                "REASONING:\n"
                "da-GAL4 is on chr 3, UAS-mCD8-GFP is on chr 2.\n"
                "CyO is a chr 2 balancer.\n\n"
                "GENOTYPES:\n"
                "w; UAS-mCD8-GFP/CyO; da-GAL4/+\n"
                "w; UAS-mCD8-GFP/+; da-GAL4/+\n"
                "w; CyO/+; da-GAL4/+"
            )
        )

        response = authenticated_client.post(
            "/api/crosses/suggest-genotypes",
            json={
                "female": {
                    "genotype": "w[1118]; P{GAL4-da.G32}UH1/CyO",
                    "shortname": "da-GAL4; CyO",
                },
                "male": {
                    "genotype": "w[*]; P{UAS-mCD8::GFP.L}Ptp4E[LL03]",
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["suggestions"]) == 3
        assert data["reasoning"] is not None
        assert "chr 2" in data["reasoning"]

    @patch("app.llm.service.get_llm_service")
    def test_suggest_genotypes_not_configured(
        self,
        mock_get_llm,
        authenticated_client: TestClient,
    ):
        """Test suggest-genotypes returns 400 when LLM is not configured."""
        mock_llm = mock_get_llm.return_value
        mock_llm.configured = False

        response = authenticated_client.post(
            "/api/crosses/suggest-genotypes",
            json={
                "female": {"genotype": "w[1118]"},
                "male": {"genotype": "Oregon-R"},
            },
        )

        assert response.status_code == 400
        assert "not configured" in response.json()["detail"]

    @patch("app.llm.service.get_llm_service")
    def test_suggest_genotypes_llm_error(
        self,
        mock_get_llm,
        authenticated_client: TestClient,
    ):
        """Test suggest-genotypes returns 500 on LLM error."""
        mock_llm = mock_get_llm.return_value
        mock_llm.configured = True
        mock_llm.ask = AsyncMock(side_effect=ValueError("API error"))

        response = authenticated_client.post(
            "/api/crosses/suggest-genotypes",
            json={
                "female": {"genotype": "w[1118]"},
                "male": {"genotype": "Oregon-R"},
            },
        )

        assert response.status_code == 500
        assert "Failed to generate" in response.json()["detail"]


class TestStockSummaryIncludesShortname:
    """Test that StockSummary includes shortname in cross responses."""

    def test_stock_summary_has_shortname(
        self,
        authenticated_client: TestClient,
        test_cross: Cross,
    ):
        """Test that cross response includes parent stock shortnames."""
        response = authenticated_client.get(f"/api/crosses/{test_cross.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["parent_female"]["shortname"] == "da-GAL4; CyO"
        assert data["parent_male"]["shortname"] == "UAS-mCD8-GFP"


class TestCrossReminders:
    """Tests for cross reminder retrieval."""

    def test_get_reminders_due_crosses(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Test that reminders are returned for crosses due within 1 day."""
        from app.crosses.service import get_cross_service

        # Create a cross started 5 days ago (flip is due today)
        cross = Cross(
            id=str(uuid4()),
            tenant_id=test_tenant.id,
            name="Due Cross",
            parent_female_id=female_stock.id,
            parent_male_id=male_stock.id,
            status=CrossStatus.IN_PROGRESS,
            executed_date=datetime.now() - timedelta(days=5),
            flip_days=5,
            virgin_collection_days=12,
            created_by_id=test_user.id,
        )
        db.add(cross)
        db.commit()

        service = get_cross_service(db, test_tenant.id)
        reminders = service.get_crosses_needing_reminders()

        # Should have a flip reminder (due today = 0 days)
        flip_reminders = [r for r in reminders if r.event_type == "flip"]
        assert len(flip_reminders) >= 1
        assert flip_reminders[0].days_until <= 1

    def test_get_reminders_excludes_not_due(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        female_stock: Stock,
        male_stock: Stock,
    ):
        """Test that reminders are NOT returned for crosses not yet due."""
        from app.crosses.service import get_cross_service

        # Cross started today — flip in 5 days, not due yet
        cross = Cross(
            id=str(uuid4()),
            tenant_id=test_tenant.id,
            name="Not Due Cross",
            parent_female_id=female_stock.id,
            parent_male_id=male_stock.id,
            status=CrossStatus.IN_PROGRESS,
            executed_date=datetime.now(),
            flip_days=5,
            virgin_collection_days=12,
            created_by_id=test_user.id,
        )
        db.add(cross)
        db.commit()

        service = get_cross_service(db, test_tenant.id)
        reminders = service.get_crosses_needing_reminders()

        # Should have no reminders (flip in 5 days, vc in 12 days)
        assert len(reminders) == 0
