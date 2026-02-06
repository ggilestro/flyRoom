"""Service for flip tracking operations."""

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.db.models import FlipEvent, Stock, Tenant, User
from app.flips.schemas import (
    FlipEventCreate,
    FlipEventResponse,
    FlipSettingsResponse,
    FlipSettingsUpdate,
    FlipStatus,
    StockFlipInfo,
    StocksNeedingFlipResponse,
)


class FlipService:
    """Service for managing flip events and status.

    Attributes:
        db: Database session.
        tenant_id: Current tenant ID.
        user_id: Current user ID (optional).
    """

    def __init__(self, db: Session, tenant_id: str, user_id: str | None = None):
        """Initialize flip service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
            user_id: Current user ID.
        """
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _get_tenant(self) -> Tenant | None:
        """Get the current tenant."""
        return self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()

    def record_flip(self, data: FlipEventCreate) -> FlipEventResponse | None:
        """Record a flip event for a stock.

        Args:
            data: Flip event creation data.

        Returns:
            FlipEventResponse if successful, None if stock not found.
        """
        # Verify stock exists and belongs to tenant
        stock = (
            self.db.query(Stock)
            .filter(Stock.id == data.stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )
        if not stock:
            return None

        # Create flip event
        flip_event = FlipEvent(
            stock_id=data.stock_id,
            flipped_by_id=self.user_id,
            notes=data.notes,
        )
        self.db.add(flip_event)
        self.db.commit()
        self.db.refresh(flip_event)

        # Get flipped_by name
        flipped_by_name = None
        if flip_event.flipped_by_id:
            user = self.db.query(User).filter(User.id == flip_event.flipped_by_id).first()
            if user:
                flipped_by_name = user.full_name

        return FlipEventResponse(
            id=flip_event.id,
            stock_id=flip_event.stock_id,
            flipped_by_id=flip_event.flipped_by_id,
            flipped_by_name=flipped_by_name,
            flipped_at=flip_event.flipped_at,
            notes=flip_event.notes,
            created_at=flip_event.created_at,
        )

    def get_flip_history(self, stock_id: str, limit: int = 10) -> list[FlipEventResponse]:
        """Get flip history for a stock.

        Args:
            stock_id: Stock UUID.
            limit: Maximum number of events to return.

        Returns:
            List of flip events, most recent first.
        """
        # Verify stock belongs to tenant
        stock = (
            self.db.query(Stock)
            .filter(Stock.id == stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )
        if not stock:
            return []

        events = (
            self.db.query(FlipEvent)
            .options(joinedload(FlipEvent.flipped_by))
            .filter(FlipEvent.stock_id == stock_id)
            .order_by(FlipEvent.flipped_at.desc())
            .limit(limit)
            .all()
        )

        return [
            FlipEventResponse(
                id=e.id,
                stock_id=e.stock_id,
                flipped_by_id=e.flipped_by_id,
                flipped_by_name=e.flipped_by.full_name if e.flipped_by else None,
                flipped_at=e.flipped_at,
                notes=e.notes,
                created_at=e.created_at,
            )
            for e in events
        ]

    def get_stock_flip_status(self, stock_id: str) -> StockFlipInfo | None:
        """Get flip status for a stock.

        Args:
            stock_id: Stock UUID.

        Returns:
            StockFlipInfo if found, None otherwise.
        """
        stock = (
            self.db.query(Stock)
            .options(joinedload(Stock.flip_events))
            .filter(Stock.id == stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )
        if not stock:
            return None

        return self._calculate_flip_info(stock)

    def _calculate_flip_info(self, stock: Stock) -> StockFlipInfo:
        """Calculate flip info for a stock.

        Args:
            stock: Stock model instance.

        Returns:
            StockFlipInfo with calculated status.
        """
        tenant = self._get_tenant()
        warning_days = tenant.flip_warning_days if tenant else 21
        critical_days = tenant.flip_critical_days if tenant else 31

        # Get most recent flip
        last_flip = None
        if stock.flip_events:
            last_flip = stock.flip_events[0]  # Already ordered by desc

        if last_flip is None:
            return StockFlipInfo(
                stock_id=stock.id,
                stock_display_id=stock.stock_id,
                flip_status=FlipStatus.NEVER,
                days_since_flip=None,
                last_flip_at=None,
                last_flipped_by=None,
            )

        # Calculate days since flip
        now = datetime.utcnow()
        days_since = (now - last_flip.flipped_at).days

        # Determine status
        if days_since >= critical_days:
            status = FlipStatus.CRITICAL
        elif days_since >= warning_days:
            status = FlipStatus.WARNING
        else:
            status = FlipStatus.OK

        # Get flipped_by name
        flipped_by_name = None
        if last_flip.flipped_by_id:
            user = self.db.query(User).filter(User.id == last_flip.flipped_by_id).first()
            if user:
                flipped_by_name = user.full_name

        return StockFlipInfo(
            stock_id=stock.id,
            stock_display_id=stock.stock_id,
            flip_status=status,
            days_since_flip=days_since,
            last_flip_at=last_flip.flipped_at,
            last_flipped_by=flipped_by_name,
        )

    def get_stocks_needing_flip(self) -> StocksNeedingFlipResponse:
        """Get all stocks that need flipping.

        Returns:
            StocksNeedingFlipResponse with categorized stocks.
        """
        # Get all active stocks with their flip events
        stocks = (
            self.db.query(Stock)
            .options(joinedload(Stock.flip_events))
            .filter(Stock.tenant_id == self.tenant_id, Stock.is_active)
            .all()
        )

        warning_stocks = []
        critical_stocks = []
        never_flipped = []

        for stock in stocks:
            info = self._calculate_flip_info(stock)
            if info.flip_status == FlipStatus.CRITICAL:
                critical_stocks.append(info)
            elif info.flip_status == FlipStatus.WARNING:
                warning_stocks.append(info)
            elif info.flip_status == FlipStatus.NEVER:
                never_flipped.append(info)

        return StocksNeedingFlipResponse(
            warning=warning_stocks,
            critical=critical_stocks,
            never_flipped=never_flipped,
        )

    def get_flip_settings(self) -> FlipSettingsResponse | None:
        """Get flip settings for the tenant.

        Returns:
            FlipSettingsResponse if tenant found, None otherwise.
        """
        tenant = self._get_tenant()
        if not tenant:
            return None

        return FlipSettingsResponse(
            flip_warning_days=tenant.flip_warning_days,
            flip_critical_days=tenant.flip_critical_days,
            flip_reminder_enabled=tenant.flip_reminder_enabled,
        )

    def update_flip_settings(self, data: FlipSettingsUpdate) -> FlipSettingsResponse | None:
        """Update flip settings for the tenant.

        Args:
            data: Settings update data.

        Returns:
            Updated FlipSettingsResponse if successful, None if tenant not found.
        """
        tenant = self._get_tenant()
        if not tenant:
            return None

        if data.flip_warning_days is not None:
            tenant.flip_warning_days = data.flip_warning_days
        if data.flip_critical_days is not None:
            tenant.flip_critical_days = data.flip_critical_days
        if data.flip_reminder_enabled is not None:
            tenant.flip_reminder_enabled = data.flip_reminder_enabled

        self.db.commit()
        self.db.refresh(tenant)

        return FlipSettingsResponse(
            flip_warning_days=tenant.flip_warning_days,
            flip_critical_days=tenant.flip_critical_days,
            flip_reminder_enabled=tenant.flip_reminder_enabled,
        )

    def get_stocks_for_reminder(self) -> list[StockFlipInfo]:
        """Get stocks that should trigger reminder emails.

        Returns stocks that are in WARNING or CRITICAL status.

        Returns:
            List of StockFlipInfo for stocks needing attention.
        """
        result = self.get_stocks_needing_flip()
        return result.warning + result.critical


def get_flip_service(db: Session, tenant_id: str, user_id: str | None = None) -> FlipService:
    """Create a flip service instance.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        user_id: User ID (optional).

    Returns:
        FlipService instance.
    """
    return FlipService(db, tenant_id, user_id)
