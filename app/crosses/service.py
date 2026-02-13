"""Cross service layer."""

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.crosses.schemas import (
    CrossComplete,
    CrossCreate,
    CrossListResponse,
    CrossReminderInfo,
    CrossResponse,
    CrossSearchParams,
    CrossUpdate,
    StockSummary,
)
from app.db.models import Cross, CrossOutcomeType, CrossStatus, Stock, StockOrigin

logger = logging.getLogger(__name__)


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
        """Convert stock to summary.

        Args:
            stock: Stock model instance.

        Returns:
            StockSummary: Brief stock info.
        """
        return StockSummary(
            id=stock.id,
            stock_id=stock.stock_id,
            genotype=stock.genotype,
            shortname=stock.shortname,
            original_genotype=stock.original_genotype,
            notes=stock.notes,
            is_placeholder=stock.is_placeholder,
        )

    def _compute_timeline(self, cross: Cross) -> dict:
        """Compute timeline fields for an in-progress cross.

        Args:
            cross: Cross model instance.

        Returns:
            dict: Timeline fields (flip_due_date, days_until_flip, etc.)
        """
        result = {
            "flip_due_date": None,
            "virgin_collection_due_date": None,
            "days_until_flip": None,
            "days_until_virgin_collection": None,
            "flip_overdue": False,
            "virgin_collection_overdue": False,
        }

        if cross.status != CrossStatus.IN_PROGRESS or not cross.executed_date:
            return result

        today = date.today()
        exec_date = (
            cross.executed_date.date()
            if isinstance(cross.executed_date, datetime)
            else cross.executed_date
        )

        if cross.flip_days is not None:
            flip_due = exec_date + timedelta(days=cross.flip_days)
            result["flip_due_date"] = flip_due
            result["days_until_flip"] = (flip_due - today).days
            result["flip_overdue"] = result["days_until_flip"] < 0

        if cross.virgin_collection_days is not None:
            vc_due = exec_date + timedelta(days=cross.virgin_collection_days)
            result["virgin_collection_due_date"] = vc_due
            result["days_until_virgin_collection"] = (vc_due - today).days
            result["virgin_collection_overdue"] = result["days_until_virgin_collection"] < 0

        return result

    def _cross_to_response(self, cross: Cross) -> CrossResponse:
        """Convert cross model to response schema.

        Args:
            cross: Cross model.

        Returns:
            CrossResponse: Cross response schema.
        """
        timeline = self._compute_timeline(cross)

        return CrossResponse(
            id=cross.id,
            name=cross.name,
            parent_female=self._stock_to_summary(cross.parent_female),
            parent_male=self._stock_to_summary(cross.parent_male),
            offspring=self._stock_to_summary(cross.offspring) if cross.offspring else None,
            planned_date=cross.planned_date.date() if cross.planned_date else None,
            executed_date=cross.executed_date.date() if cross.executed_date else None,
            status=cross.status,
            outcome_type=cross.outcome_type,
            expected_outcomes=cross.expected_outcomes,
            notes=cross.notes,
            target_genotype=cross.target_genotype,
            flip_days=cross.flip_days,
            virgin_collection_days=cross.virgin_collection_days,
            flip_due_date=timeline["flip_due_date"],
            virgin_collection_due_date=timeline["virgin_collection_due_date"],
            days_until_flip=timeline["days_until_flip"],
            days_until_virgin_collection=timeline["days_until_virgin_collection"],
            flip_overdue=timeline["flip_overdue"],
            virgin_collection_overdue=timeline["virgin_collection_overdue"],
            created_at=cross.created_at,
            created_by_name=cross.created_by.full_name if cross.created_by else None,
        )

    def _generate_offspring_stock_id(self) -> str:
        """Generate sequential CX-NNN stock ID for cross offspring.

        Returns:
            str: Next available CX-NNN stock ID.
        """
        # Find the highest existing CX- number for this tenant
        max_id = (
            self.db.query(func.max(Stock.stock_id))
            .filter(
                Stock.tenant_id == self.tenant_id,
                Stock.stock_id.like("CX-%"),
            )
            .scalar()
        )

        if max_id:
            try:
                num = int(max_id.split("-")[1]) + 1
            except (IndexError, ValueError):
                num = 1
        else:
            num = 1

        return f"CX-{num:03d}"

    def _create_offspring_stock(self, cross: Cross, user_id: str) -> Stock:
        """Create a placeholder offspring stock for a cross.

        Args:
            cross: Cross with parents loaded.
            user_id: Creating user's ID.

        Returns:
            Stock: Created placeholder stock.
        """
        stock_id = self._generate_offspring_stock_id()
        female_sid = cross.parent_female.stock_id if cross.parent_female else "?"
        male_sid = cross.parent_male.stock_id if cross.parent_male else "?"

        offspring = Stock(
            tenant_id=self.tenant_id,
            stock_id=stock_id,
            genotype=cross.target_genotype or "TBD",
            origin=StockOrigin.INTERNAL,
            is_placeholder=True,
            notes=f"Cross offspring: {female_sid} x {male_sid}",
            created_by_id=user_id,
        )
        self.db.add(offspring)
        self.db.flush()  # Get the ID without committing
        return offspring

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
            target_genotype=data.target_genotype,
            flip_days=data.flip_days,
            virgin_collection_days=data.virgin_collection_days,
            outcome_type=data.outcome_type,
            status=CrossStatus.PLANNED,
            created_by_id=user_id,
        )

        self.db.add(cross)
        self.db.flush()

        # Auto-create placeholder offspring for intermediate/new_stock outcomes
        if data.outcome_type != CrossOutcomeType.EPHEMERAL and data.target_genotype:
            # Need parents loaded for stock ID generation in notes
            cross.parent_female = female
            cross.parent_male = male
            offspring = self._create_offspring_stock(cross, user_id)
            cross.offspring_id = offspring.id

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
        if data.target_genotype is not None:
            cross.target_genotype = data.target_genotype
        if data.flip_days is not None:
            cross.flip_days = data.flip_days
        if data.virgin_collection_days is not None:
            cross.virgin_collection_days = data.virgin_collection_days
        if data.offspring_id is not None:
            # Validate offspring exists
            offspring = (
                self.db.query(Stock)
                .filter(Stock.id == data.offspring_id, Stock.tenant_id == self.tenant_id)
                .first()
            )
            if offspring:
                cross.offspring_id = data.offspring_id

        # Handle outcome_type transitions
        if data.outcome_type is not None:
            old_outcome = cross.outcome_type or CrossOutcomeType.EPHEMERAL
            cross.outcome_type = data.outcome_type

            if (
                data.outcome_type == CrossOutcomeType.EPHEMERAL
                and old_outcome != CrossOutcomeType.EPHEMERAL
            ):
                # Deactivate placeholder offspring when switching to ephemeral
                if cross.offspring and cross.offspring.is_placeholder:
                    cross.offspring.is_active = False
                    cross.offspring_id = None
            elif data.outcome_type != CrossOutcomeType.EPHEMERAL and not cross.offspring_id:
                # Auto-create offspring if switching to intermediate/new_stock
                genotype = data.target_genotype or cross.target_genotype
                if genotype:
                    cross.target_genotype = genotype
                    offspring = self._create_offspring_stock(cross, cross.created_by_id)
                    cross.offspring_id = offspring.id

        # Update placeholder offspring genotype if target_genotype changed
        if data.target_genotype is not None and cross.offspring and cross.offspring.is_placeholder:
            cross.offspring.genotype = data.target_genotype

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

        # Confirm placeholder offspring (make it a real stock)
        if cross.offspring and cross.offspring.is_placeholder:
            cross.offspring.is_placeholder = False

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

        # Deactivate placeholder offspring
        if cross.offspring and cross.offspring.is_placeholder:
            cross.offspring.is_active = False

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

    def get_crosses_needing_reminders(self) -> list[CrossReminderInfo]:
        """Get in-progress crosses with flip or virgin collection due within 1 day or overdue.

        Returns up to 3 days overdue to avoid spamming for long-forgotten crosses.

        Returns:
            list[CrossReminderInfo]: Crosses needing reminders.
        """
        today = date.today()
        reminders: list[CrossReminderInfo] = []

        crosses = (
            self.db.query(Cross)
            .options(
                joinedload(Cross.parent_female),
                joinedload(Cross.parent_male),
            )
            .filter(
                Cross.tenant_id == self.tenant_id,
                Cross.status == CrossStatus.IN_PROGRESS,
                Cross.executed_date.isnot(None),
            )
            .all()
        )

        for cross in crosses:
            exec_date = (
                cross.executed_date.date()
                if isinstance(cross.executed_date, datetime)
                else cross.executed_date
            )

            # Check flip reminder
            if cross.flip_days is not None:
                flip_due = exec_date + timedelta(days=cross.flip_days)
                days_until = (flip_due - today).days
                # Remind if due within 1 day or overdue up to 3 days
                if -3 <= days_until <= 1:
                    reminders.append(
                        CrossReminderInfo(
                            cross_id=cross.id,
                            cross_name=cross.name,
                            female_stock_id=cross.parent_female.stock_id,
                            male_stock_id=cross.parent_male.stock_id,
                            event_type="flip",
                            due_date=flip_due,
                            days_until=days_until,
                        )
                    )

            # Check virgin collection reminder
            if cross.virgin_collection_days is not None:
                vc_due = exec_date + timedelta(days=cross.virgin_collection_days)
                days_until = (vc_due - today).days
                if -3 <= days_until <= 1:
                    reminders.append(
                        CrossReminderInfo(
                            cross_id=cross.id,
                            cross_name=cross.name,
                            female_stock_id=cross.parent_female.stock_id,
                            male_stock_id=cross.parent_male.stock_id,
                            event_type="virgin_collection",
                            due_date=vc_due,
                            days_until=days_until,
                        )
                    )

        return reminders


def get_cross_service(db: Session, tenant_id: str) -> CrossService:
    """Factory function for CrossService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        CrossService: Cross service instance.
    """
    return CrossService(db, tenant_id)
