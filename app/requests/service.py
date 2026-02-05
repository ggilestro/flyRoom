"""Stock request service layer."""

from datetime import UTC, datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Stock,
    StockRequest,
    StockRequestStatus,
    StockVisibility,
)
from app.requests.schemas import (
    StockRequestCreate,
    StockRequestListResponse,
    StockRequestResponse,
    StockRequestStats,
)


class StockRequestService:
    """Service class for stock request operations."""

    def __init__(self, db: Session, tenant_id: str, user_id: str):
        """Initialize stock request service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
            user_id: Current user ID.
        """
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _request_to_response(self, request: StockRequest) -> StockRequestResponse:
        """Convert request model to response schema."""
        return StockRequestResponse(
            id=request.id,
            stock_id=request.stock_id,
            stock_name=request.stock.stock_id,
            stock_genotype=request.stock.genotype,
            requester_user_id=request.requester_user_id,
            requester_user_name=(
                request.requester_user.full_name if request.requester_user else None
            ),
            requester_tenant_id=request.requester_tenant_id,
            requester_tenant_name=request.requester_tenant.name,
            owner_tenant_id=request.owner_tenant_id,
            owner_tenant_name=request.owner_tenant.name,
            status=request.status,
            message=request.message,
            response_message=request.response_message,
            created_at=request.created_at,
            updated_at=request.updated_at,
            responded_at=request.responded_at,
            responded_by_name=(request.responded_by.full_name if request.responded_by else None),
        )

    def create_request(self, data: StockRequestCreate) -> StockRequest:
        """Create a stock request.

        Args:
            data: Request creation data.

        Returns:
            StockRequest: Created request.

        Raises:
            ValueError: If stock not found, not public, or request already exists.
        """
        # Get the stock
        stock = self.db.query(Stock).filter(Stock.id == data.stock_id).first()
        if not stock:
            raise ValueError("Stock not found")

        # Can't request own stock
        if stock.tenant_id == self.tenant_id:
            raise ValueError("Cannot request your own stock")

        # Stock must be public for cross-lab requests
        if stock.visibility != StockVisibility.PUBLIC:
            raise ValueError("Stock is not available for requests")

        # Check for existing pending request
        existing = (
            self.db.query(StockRequest)
            .filter(
                StockRequest.stock_id == data.stock_id,
                StockRequest.requester_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .first()
        )
        if existing:
            raise ValueError("You already have a pending request for this stock")

        request = StockRequest(
            stock_id=data.stock_id,
            requester_user_id=self.user_id,
            requester_tenant_id=self.tenant_id,
            owner_tenant_id=stock.tenant_id,
            message=data.message,
        )

        self.db.add(request)
        self.db.commit()
        self.db.refresh(request)
        return request

    def list_outgoing_requests(
        self, status: StockRequestStatus | None = None, page: int = 1, page_size: int = 20
    ) -> StockRequestListResponse:
        """List requests made by this lab.

        Args:
            status: Optional status filter.
            page: Page number.
            page_size: Items per page.

        Returns:
            StockRequestListResponse: Paginated request list.
        """
        query = (
            self.db.query(StockRequest)
            .options(
                joinedload(StockRequest.stock),
                joinedload(StockRequest.requester_user),
                joinedload(StockRequest.requester_tenant),
                joinedload(StockRequest.owner_tenant),
                joinedload(StockRequest.responded_by),
            )
            .filter(StockRequest.requester_tenant_id == self.tenant_id)
        )

        if status:
            query = query.filter(StockRequest.status == status)

        total = query.count()
        offset = (page - 1) * page_size
        requests = (
            query.order_by(StockRequest.created_at.desc()).offset(offset).limit(page_size).all()
        )

        pages = (total + page_size - 1) // page_size

        return StockRequestListResponse(
            items=[self._request_to_response(r) for r in requests],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def list_incoming_requests(
        self, status: StockRequestStatus | None = None, page: int = 1, page_size: int = 20
    ) -> StockRequestListResponse:
        """List requests for stocks owned by this lab.

        Args:
            status: Optional status filter.
            page: Page number.
            page_size: Items per page.

        Returns:
            StockRequestListResponse: Paginated request list.
        """
        query = (
            self.db.query(StockRequest)
            .options(
                joinedload(StockRequest.stock),
                joinedload(StockRequest.requester_user),
                joinedload(StockRequest.requester_tenant),
                joinedload(StockRequest.owner_tenant),
                joinedload(StockRequest.responded_by),
            )
            .filter(StockRequest.owner_tenant_id == self.tenant_id)
        )

        if status:
            query = query.filter(StockRequest.status == status)

        total = query.count()
        offset = (page - 1) * page_size
        requests = (
            query.order_by(StockRequest.created_at.desc()).offset(offset).limit(page_size).all()
        )

        pages = (total + page_size - 1) // page_size

        return StockRequestListResponse(
            items=[self._request_to_response(r) for r in requests],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def get_request(self, request_id: str) -> StockRequest | None:
        """Get a request by ID (if user has access).

        Args:
            request_id: Request UUID.

        Returns:
            StockRequest | None: Request if found and user has access.
        """
        return (
            self.db.query(StockRequest)
            .options(
                joinedload(StockRequest.stock),
                joinedload(StockRequest.requester_user),
                joinedload(StockRequest.requester_tenant),
                joinedload(StockRequest.owner_tenant),
                joinedload(StockRequest.responded_by),
            )
            .filter(
                StockRequest.id == request_id,
                or_(
                    StockRequest.requester_tenant_id == self.tenant_id,
                    StockRequest.owner_tenant_id == self.tenant_id,
                ),
            )
            .first()
        )

    def approve_request(
        self, request_id: str, response_message: str | None = None
    ) -> StockRequest | None:
        """Approve a stock request (owner only).

        Args:
            request_id: Request UUID.
            response_message: Optional response message.

        Returns:
            StockRequest | None: Updated request if found.
        """
        request = (
            self.db.query(StockRequest)
            .filter(
                StockRequest.id == request_id,
                StockRequest.owner_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .first()
        )
        if not request:
            return None

        request.status = StockRequestStatus.APPROVED
        request.response_message = response_message
        request.responded_at = datetime.now(UTC)
        request.responded_by_id = self.user_id

        self.db.commit()
        self.db.refresh(request)
        return request

    def reject_request(
        self, request_id: str, response_message: str | None = None
    ) -> StockRequest | None:
        """Reject a stock request (owner only).

        Args:
            request_id: Request UUID.
            response_message: Optional response message.

        Returns:
            StockRequest | None: Updated request if found.
        """
        request = (
            self.db.query(StockRequest)
            .filter(
                StockRequest.id == request_id,
                StockRequest.owner_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .first()
        )
        if not request:
            return None

        request.status = StockRequestStatus.REJECTED
        request.response_message = response_message
        request.responded_at = datetime.now(UTC)
        request.responded_by_id = self.user_id

        self.db.commit()
        self.db.refresh(request)
        return request

    def fulfill_request(self, request_id: str) -> StockRequest | None:
        """Mark an approved request as fulfilled (owner only).

        Args:
            request_id: Request UUID.

        Returns:
            StockRequest | None: Updated request if found.
        """
        request = (
            self.db.query(StockRequest)
            .filter(
                StockRequest.id == request_id,
                StockRequest.owner_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.APPROVED,
            )
            .first()
        )
        if not request:
            return None

        request.status = StockRequestStatus.FULFILLED

        self.db.commit()
        self.db.refresh(request)
        return request

    def cancel_request(self, request_id: str) -> StockRequest | None:
        """Cancel a pending request (requester only).

        Args:
            request_id: Request UUID.

        Returns:
            StockRequest | None: Updated request if found.
        """
        request = (
            self.db.query(StockRequest)
            .filter(
                StockRequest.id == request_id,
                StockRequest.requester_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .first()
        )
        if not request:
            return None

        request.status = StockRequestStatus.CANCELLED

        self.db.commit()
        self.db.refresh(request)
        return request

    def get_stats(self) -> StockRequestStats:
        """Get request statistics for this lab.

        Returns:
            StockRequestStats: Request statistics.
        """
        pending_incoming = (
            self.db.query(func.count(StockRequest.id))
            .filter(
                StockRequest.owner_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .scalar()
        )

        pending_outgoing = (
            self.db.query(func.count(StockRequest.id))
            .filter(
                StockRequest.requester_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.PENDING,
            )
            .scalar()
        )

        approved_outgoing = (
            self.db.query(func.count(StockRequest.id))
            .filter(
                StockRequest.requester_tenant_id == self.tenant_id,
                StockRequest.status == StockRequestStatus.APPROVED,
            )
            .scalar()
        )

        fulfilled_total = (
            self.db.query(func.count(StockRequest.id))
            .filter(
                or_(
                    StockRequest.owner_tenant_id == self.tenant_id,
                    StockRequest.requester_tenant_id == self.tenant_id,
                ),
                StockRequest.status == StockRequestStatus.FULFILLED,
            )
            .scalar()
        )

        return StockRequestStats(
            pending_incoming=pending_incoming,
            pending_outgoing=pending_outgoing,
            approved_outgoing=approved_outgoing,
            fulfilled_total=fulfilled_total,
        )


def get_stock_request_service(db: Session, tenant_id: str, user_id: str) -> StockRequestService:
    """Factory function for StockRequestService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        user_id: User ID.

    Returns:
        StockRequestService: Stock request service instance.
    """
    return StockRequestService(db, tenant_id, user_id)
