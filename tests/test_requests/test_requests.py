"""Tests for stock requests module."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.auth.utils import get_password_hash
from app.db.models import (
    Stock,
    StockRequestStatus,
    StockVisibility,
    Tenant,
    User,
    UserRole,
    UserStatus,
)


@pytest.fixture
def second_tenant(db: Session) -> Tenant:
    """Create a second test tenant for cross-lab tests."""
    tenant = Tenant(
        id=str(uuid4()),
        name="Second Lab",
        slug="second-lab",
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def second_user(db: Session, second_tenant: Tenant) -> User:
    """Create a user in the second tenant."""
    user = User(
        id=str(uuid4()),
        tenant_id=second_tenant.id,
        email="second@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Second User",
        role=UserRole.USER,
        status=UserStatus.APPROVED,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def public_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a public stock for request tests."""
    stock = Stock(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        stock_id="PUBLIC-001",
        genotype="w[*]; UAS-GFP",
        visibility=StockVisibility.PUBLIC,
        created_by_id=test_user.id,
        owner_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@pytest.fixture
def private_stock(db: Session, test_tenant: Tenant, test_user: User) -> Stock:
    """Create a private stock for request tests."""
    stock = Stock(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        stock_id="PRIVATE-001",
        genotype="w[*]; UAS-RFP",
        visibility=StockVisibility.LAB_ONLY,
        created_by_id=test_user.id,
        owner_id=test_user.id,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


class TestStockRequestService:
    """Tests for StockRequestService."""

    def test_create_request_success(
        self, db: Session, second_tenant: Tenant, second_user: User, public_stock: Stock
    ):
        """Test creating a stock request."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(
            stock_id=public_stock.id,
            message="Would like to request this stock",
        )
        request = service.create_request(data)

        assert request.stock_id == public_stock.id
        assert request.requester_tenant_id == second_tenant.id
        assert request.owner_tenant_id == public_stock.tenant_id
        assert request.status == StockRequestStatus.PENDING

    def test_create_request_own_stock_fails(
        self, db: Session, test_tenant: Tenant, test_user: User, public_stock: Stock
    ):
        """Test requesting own stock fails."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, test_tenant.id, test_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)

        with pytest.raises(ValueError, match="Cannot request your own stock"):
            service.create_request(data)

    def test_create_request_private_stock_fails(
        self, db: Session, second_tenant: Tenant, second_user: User, private_stock: Stock
    ):
        """Test requesting private stock fails."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=private_stock.id)

        with pytest.raises(ValueError, match="not available"):
            service.create_request(data)

    def test_create_request_duplicate_pending_fails(
        self, db: Session, second_tenant: Tenant, second_user: User, public_stock: Stock
    ):
        """Test creating duplicate pending request fails."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)

        # First request succeeds
        service.create_request(data)

        # Second request fails
        with pytest.raises(ValueError, match="already have a pending"):
            service.create_request(data)

    def test_list_outgoing_requests(
        self, db: Session, second_tenant: Tenant, second_user: User, public_stock: Stock
    ):
        """Test listing outgoing requests."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        service.create_request(data)

        result = service.list_outgoing_requests()
        assert result.total == 1
        assert result.items[0].stock_id == public_stock.id

    def test_list_incoming_requests(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        second_tenant: Tenant,
        second_user: User,
        public_stock: Stock,
    ):
        """Test listing incoming requests."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        # Create request from second tenant
        requester_service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        requester_service.create_request(data)

        # Check incoming for owner
        owner_service = StockRequestService(db, test_tenant.id, test_user.id)
        result = owner_service.list_incoming_requests()
        assert result.total == 1
        assert result.items[0].requester_tenant_name == second_tenant.name

    def test_approve_request(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        second_tenant: Tenant,
        second_user: User,
        public_stock: Stock,
    ):
        """Test approving a request."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        # Create request
        requester_service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        request = requester_service.create_request(data)

        # Approve as owner
        owner_service = StockRequestService(db, test_tenant.id, test_user.id)
        approved = owner_service.approve_request(request.id, "Approved!")

        assert approved.status == StockRequestStatus.APPROVED
        assert approved.response_message == "Approved!"

    def test_reject_request(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        second_tenant: Tenant,
        second_user: User,
        public_stock: Stock,
    ):
        """Test rejecting a request."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        # Create request
        requester_service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        request = requester_service.create_request(data)

        # Reject as owner
        owner_service = StockRequestService(db, test_tenant.id, test_user.id)
        rejected = owner_service.reject_request(request.id, "Sorry, unavailable")

        assert rejected.status == StockRequestStatus.REJECTED
        assert rejected.response_message == "Sorry, unavailable"

    def test_fulfill_request(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        second_tenant: Tenant,
        second_user: User,
        public_stock: Stock,
    ):
        """Test fulfilling an approved request."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        # Create and approve request
        requester_service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        request = requester_service.create_request(data)

        owner_service = StockRequestService(db, test_tenant.id, test_user.id)
        owner_service.approve_request(request.id)

        # Fulfill
        fulfilled = owner_service.fulfill_request(request.id)
        assert fulfilled.status == StockRequestStatus.FULFILLED

    def test_cancel_request(
        self, db: Session, second_tenant: Tenant, second_user: User, public_stock: Stock
    ):
        """Test cancelling a pending request."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        request = service.create_request(data)

        cancelled = service.cancel_request(request.id)
        assert cancelled.status == StockRequestStatus.CANCELLED

    def test_get_stats(
        self,
        db: Session,
        test_tenant: Tenant,
        test_user: User,
        second_tenant: Tenant,
        second_user: User,
        public_stock: Stock,
    ):
        """Test getting request statistics."""
        from app.requests.schemas import StockRequestCreate
        from app.requests.service import StockRequestService

        # Create a request
        requester_service = StockRequestService(db, second_tenant.id, second_user.id)
        data = StockRequestCreate(stock_id=public_stock.id)
        requester_service.create_request(data)

        # Check stats for owner
        owner_service = StockRequestService(db, test_tenant.id, test_user.id)
        stats = owner_service.get_stats()
        assert stats.pending_incoming == 1
        assert stats.pending_outgoing == 0

        # Check stats for requester
        requester_stats = requester_service.get_stats()
        assert requester_stats.pending_incoming == 0
        assert requester_stats.pending_outgoing == 1
