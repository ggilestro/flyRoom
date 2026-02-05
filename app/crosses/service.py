"""Cross service layer."""

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.crosses.schemas import (
    CrossComplete,
    CrossCreate,
    CrossListResponse,
    CrossResponse,
    CrossSearchParams,
    CrossUpdate,
    StockSummary,
)
from app.db.models import Cross, CrossStatus, Stock


class CrossService:
    """Service class for cross operations."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize cross service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id

    def _stock_to_summary(self, stock: Stock) -> StockSummary:
        """Convert stock to summary."""
        return StockSummary(
            id=stock.id,
            stock_id=stock.stock_id,
            genotype=stock.genotype,
        )

    def _cross_to_response(self, cross: Cross) -> CrossResponse:
        """Convert cross model to response schema.

        Args:
            cross: Cross model.

        Returns:
            CrossResponse: Cross response schema.
        """
        return CrossResponse(
            id=cross.id,
            name=cross.name,
            parent_female=self._stock_to_summary(cross.parent_female),
            parent_male=self._stock_to_summary(cross.parent_male),
            offspring=self._stock_to_summary(cross.offspring) if cross.offspring else None,
            planned_date=cross.planned_date.date() if cross.planned_date else None,
            executed_date=cross.executed_date.date() if cross.executed_date else None,
            status=cross.status,
            expected_outcomes=cross.expected_outcomes,
            notes=cross.notes,
            created_at=cross.created_at,
            created_by_name=cross.created_by.full_name if cross.created_by else None,
        )

    def list_crosses(self, params: CrossSearchParams) -> CrossListResponse:
        """List crosses with filtering and pagination.

        Args:
            params: Search and pagination parameters.

        Returns:
            CrossListResponse: Paginated cross list.
        """
        query = (
            self.db.query(Cross)
            .options(
                joinedload(Cross.parent_female),
                joinedload(Cross.parent_male),
                joinedload(Cross.offspring),
                joinedload(Cross.created_by),
            )
            .filter(Cross.tenant_id == self.tenant_id)
        )

        # Filter by status
        if params.status:
            query = query.filter(Cross.status == params.status)

        # Text search
        if params.query:
            search_term = f"%{params.query}%"
            query = query.filter(
                or_(
                    Cross.name.ilike(search_term),
                    Cross.notes.ilike(search_term),
                )
            )

        # Count total
        total = query.count()

        # Pagination
        offset = (params.page - 1) * params.page_size
        crosses = (
            query.order_by(Cross.created_at.desc()).offset(offset).limit(params.page_size).all()
        )

        pages = (total + params.page_size - 1) // params.page_size

        return CrossListResponse(
            items=[self._cross_to_response(c) for c in crosses],
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    def get_cross(self, cross_id: str) -> Cross | None:
        """Get a cross by ID.

        Args:
            cross_id: Cross UUID.

        Returns:
            Cross | None: Cross if found.
        """
        return (
            self.db.query(Cross)
            .options(
                joinedload(Cross.parent_female),
                joinedload(Cross.parent_male),
                joinedload(Cross.offspring),
                joinedload(Cross.created_by),
            )
            .filter(Cross.id == cross_id, Cross.tenant_id == self.tenant_id)
            .first()
        )

    def create_cross(self, data: CrossCreate, user_id: str) -> Cross:
        """Create a new cross.

        Args:
            data: Cross creation data.
            user_id: Creating user's ID.

        Returns:
            Cross: Created cross.

        Raises:
            ValueError: If parent stocks not found or same stock used for both parents.
        """
        # Validate parents exist and belong to tenant
        female = (
            self.db.query(Stock)
            .filter(Stock.id == data.parent_female_id, Stock.tenant_id == self.tenant_id)
            .first()
        )
        male = (
            self.db.query(Stock)
            .filter(Stock.id == data.parent_male_id, Stock.tenant_id == self.tenant_id)
            .first()
        )

        if not female:
            raise ValueError("Female parent stock not found")
        if not male:
            raise ValueError("Male parent stock not found")
        if female.id == male.id:
            raise ValueError("Cannot cross a stock with itself")

        planned_datetime = None
        if data.planned_date:
            planned_datetime = datetime.combine(data.planned_date, datetime.min.time())

        cross = Cross(
            tenant_id=self.tenant_id,
            name=data.name,
            parent_female_id=data.parent_female_id,
            parent_male_id=data.parent_male_id,
            planned_date=planned_datetime,
            notes=data.notes,
            status=CrossStatus.PLANNED,
            created_by_id=user_id,
        )

        self.db.add(cross)
        self.db.commit()
        self.db.refresh(cross)
        return cross

    def update_cross(self, cross_id: str, data: CrossUpdate) -> Cross | None:
        """Update a cross.

        Args:
            cross_id: Cross UUID.
            data: Update data.

        Returns:
            Cross | None: Updated cross if found.
        """
        cross = self.get_cross(cross_id)
        if not cross:
            return None

        if data.name is not None:
            cross.name = data.name
        if data.planned_date is not None:
            cross.planned_date = datetime.combine(data.planned_date, datetime.min.time())
        if data.executed_date is not None:
            cross.executed_date = datetime.combine(data.executed_date, datetime.min.time())
        if data.status is not None:
            cross.status = data.status
        if data.notes is not None:
            cross.notes = data.notes
        if data.offspring_id is not None:
            # Validate offspring exists
            offspring = (
                self.db.query(Stock)
                .filter(Stock.id == data.offspring_id, Stock.tenant_id == self.tenant_id)
                .first()
            )
            if offspring:
                cross.offspring_id = data.offspring_id

        self.db.commit()
        self.db.refresh(cross)
        return cross

    def start_cross(self, cross_id: str) -> Cross | None:
        """Mark a cross as in progress.

        Args:
            cross_id: Cross UUID.

        Returns:
            Cross | None: Updated cross if found.
        """
        cross = self.get_cross(cross_id)
        if not cross:
            return None

        cross.status = CrossStatus.IN_PROGRESS
        cross.executed_date = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(cross)
        return cross

    def complete_cross(self, cross_id: str, data: CrossComplete) -> Cross | None:
        """Mark a cross as completed.

        Args:
            cross_id: Cross UUID.
            data: Completion data.

        Returns:
            Cross | None: Updated cross if found.
        """
        cross = self.get_cross(cross_id)
        if not cross:
            return None

        cross.status = CrossStatus.COMPLETED
        if not cross.executed_date:
            cross.executed_date = datetime.now(UTC)

        if data.offspring_id:
            offspring = (
                self.db.query(Stock)
                .filter(Stock.id == data.offspring_id, Stock.tenant_id == self.tenant_id)
                .first()
            )
            if offspring:
                cross.offspring_id = data.offspring_id

        if data.notes:
            cross.notes = data.notes

        self.db.commit()
        self.db.refresh(cross)
        return cross

    def fail_cross(self, cross_id: str, notes: str | None = None) -> Cross | None:
        """Mark a cross as failed.

        Args:
            cross_id: Cross UUID.
            notes: Optional failure notes.

        Returns:
            Cross | None: Updated cross if found.
        """
        cross = self.get_cross(cross_id)
        if not cross:
            return None

        cross.status = CrossStatus.FAILED
        if notes:
            cross.notes = notes

        self.db.commit()
        self.db.refresh(cross)
        return cross

    def delete_cross(self, cross_id: str) -> bool:
        """Delete a cross.

        Args:
            cross_id: Cross UUID.

        Returns:
            bool: True if deleted, False if not found.
        """
        cross = self.get_cross(cross_id)
        if not cross:
            return False

        self.db.delete(cross)
        self.db.commit()
        return True

    def get_active_count(self) -> int:
        """Get count of active (non-completed) crosses.

        Returns:
            int: Count of active crosses.
        """
        return (
            self.db.query(Cross)
            .filter(
                Cross.tenant_id == self.tenant_id,
                Cross.status.in_([CrossStatus.PLANNED, CrossStatus.IN_PROGRESS]),
            )
            .count()
        )


def get_cross_service(db: Session, tenant_id: str) -> CrossService:
    """Factory function for CrossService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        CrossService: Cross service instance.
    """
    return CrossService(db, tenant_id)
