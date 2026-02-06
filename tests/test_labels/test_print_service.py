"""Tests for print service (jobs and agents)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.db.models import PrintAgent, PrintJob, PrintJobStatus, Stock, Tray
from app.labels.print_service import PrintService, get_print_service
from app.labels.schemas import PrintAgentCreate, PrintJobCreate


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def tenant_id():
    """Sample tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def user_id():
    """Sample user ID."""
    return "test-user-456"


@pytest.fixture
def print_service(mock_db, tenant_id, user_id):
    """Create PrintService with mocked dependencies."""
    return PrintService(mock_db, tenant_id, user_id)


class TestPrintServiceInit:
    """Tests for PrintService initialization."""

    def test_creates_with_db_and_tenant(self, mock_db, tenant_id):
        """Should initialize with db and tenant_id."""
        svc = PrintService(mock_db, tenant_id)
        assert svc.db == mock_db
        assert svc.tenant_id == tenant_id
        assert svc.user_id is None

    def test_creates_with_user_id(self, mock_db, tenant_id, user_id):
        """Should accept optional user_id."""
        svc = PrintService(mock_db, tenant_id, user_id)
        assert svc.user_id == user_id


class TestPrintAgentCreate:
    """Tests for agent creation."""

    def test_create_agent_generates_api_key(self, print_service, mock_db):
        """Should generate API key when creating agent."""
        data = PrintAgentCreate(name="Test Agent", label_format="dymo_11352")

        agent, api_key = print_service.create_agent(data)

        # API key should be generated
        assert api_key is not None
        assert len(api_key) > 20  # secrets.token_urlsafe(32) = 43 chars

        # Agent should be added to session
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_agent_sets_tenant(self, print_service, mock_db, tenant_id):
        """Should set tenant_id on created agent."""
        data = PrintAgentCreate(name="Lab Pi")

        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        agent, api_key = print_service.create_agent(data)

        added_agent = mock_db.add.call_args[0][0]
        assert added_agent.tenant_id == tenant_id
        assert added_agent.name == "Lab Pi"


class TestPrintAgentQueries:
    """Tests for agent query methods."""

    def test_get_agent_filters_by_tenant(self, print_service, mock_db, tenant_id):
        """Should filter agents by tenant."""
        agent_id = "agent-123"
        print_service.get_agent(agent_id)

        # Verify filter was called (tenant check happens in filter)
        assert mock_db.query.called

    def test_list_agents_active_only_by_default(self, print_service, mock_db):
        """Should only return active agents by default."""
        print_service.list_agents()

        query = mock_db.query.return_value
        # Multiple filters should be applied
        assert query.filter.called

    def test_list_agents_includes_inactive(self, print_service, mock_db):
        """Should include inactive when requested."""
        print_service.list_agents(include_inactive=True)

        # Should still work but with different filters
        assert mock_db.query.called


class TestPrintAgentOnline:
    """Tests for agent online status."""

    def test_agent_online_when_recently_seen(self, print_service):
        """Agent should be online if seen within threshold."""
        agent = MagicMock(spec=PrintAgent)
        agent.last_seen = datetime.utcnow() - timedelta(seconds=30)

        assert print_service.is_agent_online(agent) is True

    def test_agent_offline_when_not_seen(self, print_service):
        """Agent should be offline if never seen."""
        agent = MagicMock(spec=PrintAgent)
        agent.last_seen = None

        assert print_service.is_agent_online(agent) is False

    def test_agent_offline_when_stale(self, print_service):
        """Agent should be offline if seen too long ago."""
        agent = MagicMock(spec=PrintAgent)
        agent.last_seen = datetime.utcnow() - timedelta(minutes=5)

        assert print_service.is_agent_online(agent) is False


class TestPrintJobCreate:
    """Tests for job creation."""

    def test_create_job_sets_pending(self, print_service, mock_db):
        """Should create job with pending status."""
        data = PrintJobCreate(
            stock_ids=["stock-1", "stock-2"],
            label_format="dymo_11352",
            copies=1,
        )

        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        print_service.create_job(data)

        added_job = mock_db.add.call_args[0][0]
        assert added_job.status == PrintJobStatus.PENDING
        assert added_job.stock_ids == ["stock-1", "stock-2"]

    def test_create_job_sets_user(self, print_service, mock_db, user_id):
        """Should set created_by_id to current user."""
        data = PrintJobCreate(stock_ids=["stock-1"])

        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        print_service.create_job(data)

        added_job = mock_db.add.call_args[0][0]
        assert added_job.created_by_id == user_id


class TestPrintJobClaim:
    """Tests for job claiming."""

    def test_claim_job_sets_agent(self, print_service, mock_db, tenant_id):
        """Should set agent_id when claiming."""
        job = MagicMock(spec=PrintJob)
        job.status = PrintJobStatus.PENDING
        job.tenant_id = tenant_id

        agent = MagicMock(spec=PrintAgent)
        agent.tenant_id = tenant_id

        mock_db.query.return_value.filter.return_value.first.side_effect = [job, agent]

        print_service.claim_job("job-123", "agent-456")

        assert job.agent_id == "agent-456"
        assert job.status == PrintJobStatus.CLAIMED
        assert job.claimed_at is not None

    def test_claim_fails_if_not_pending(self, print_service, mock_db):
        """Should not claim job that's not pending."""
        job = MagicMock(spec=PrintJob)
        job.status = PrintJobStatus.COMPLETED

        mock_db.query.return_value.filter.return_value.first.return_value = job

        result = print_service.claim_job("job-123", "agent-456")

        assert result is None


class TestPrintJobComplete:
    """Tests for job completion."""

    def test_complete_job_success(self, print_service, mock_db):
        """Should mark job completed on success."""
        job = MagicMock(spec=PrintJob)
        job.agent_id = "agent-456"
        job.status = PrintJobStatus.PRINTING

        mock_db.query.return_value.filter.return_value.first.return_value = job

        print_service.complete_job("job-123", "agent-456", success=True)

        assert job.status == PrintJobStatus.COMPLETED
        assert job.completed_at is not None
        assert job.error_message is None

    def test_complete_job_failure(self, print_service, mock_db):
        """Should mark job failed with error message."""
        job = MagicMock(spec=PrintJob)
        job.agent_id = "agent-456"
        job.status = PrintJobStatus.PRINTING

        mock_db.query.return_value.filter.return_value.first.return_value = job

        print_service.complete_job(
            "job-123", "agent-456", success=False, error_message="Printer offline"
        )

        assert job.status == PrintJobStatus.FAILED
        assert job.error_message == "Printer offline"


class TestGetJobLabels:
    """Tests for getting label data for a job."""

    def test_get_job_labels_builds_label_data(self, print_service, mock_db):
        """Should build label data from stocks."""
        # Mock job
        job = MagicMock(spec=PrintJob)
        job.id = "job-123"
        job.stock_ids = ["stock-1", "stock-2"]
        job.label_format = "dymo_11352"
        job.copies = 1
        job.code_type = "qr"

        # Mock stocks
        stock1 = MagicMock(spec=Stock)
        stock1.stock_id = "TEST-001"
        stock1.genotype = "w[1118]"
        stock1.origin = MagicMock()
        stock1.origin.value = "internal"
        stock1.repository = None
        stock1.tray = None

        stock2 = MagicMock(spec=Stock)
        stock2.stock_id = "TEST-002"
        stock2.genotype = "Oregon-R"
        stock2.origin = MagicMock()
        stock2.origin.value = "repository"
        stock2.repository = MagicMock()
        stock2.repository.value = "bdsc"
        stock2.repository_stock_id = "3605"
        stock2.tray = MagicMock(spec=Tray)
        stock2.tray.name = "Tray A"
        stock2.position = "15"

        mock_db.query.return_value.filter.return_value.first.return_value = job
        mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = [
            stock1,
            stock2,
        ]

        result = print_service.get_job_labels("job-123")

        assert result is not None
        assert result.job_id == "job-123"
        assert len(result.labels) == 2


class TestPrintServiceFactory:
    """Tests for factory function."""

    def test_factory_creates_service(self, mock_db):
        """Factory should create PrintService."""
        svc = get_print_service(mock_db, "tenant-123", "user-456")
        assert isinstance(svc, PrintService)
        assert svc.tenant_id == "tenant-123"
        assert svc.user_id == "user-456"
