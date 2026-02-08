"""Stock service layer."""

from datetime import datetime

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    FlipEvent,
    Stock,
    StockVisibility,
    Tag,
    Tenant,
    Tray,
)
from app.stocks.schemas import (
    OwnerInfo,
    StockCreate,
    StockListResponse,
    StockResponse,
    StockScope,
    StockSearchParams,
    StockUpdate,
    TagCreate,
    TagResponse,
    TenantInfo,
    TrayInfo,
)


class StockService:
    """Service class for stock operations."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize stock service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id
        # Cache tenant's organization_id for visibility filtering
        self._org_id = None
        # Cache flip settings
        self._flip_warning_days = None
        self._flip_critical_days = None

    @property
    def organization_id(self) -> str | None:
        """Get current tenant's organization ID (cached)."""
        if self._org_id is None:
            tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
            self._org_id = tenant.organization_id if tenant else ""
        return self._org_id if self._org_id else None

    def _get_flip_settings(self) -> tuple[int, int]:
        """Get flip warning and critical days settings (cached)."""
        if self._flip_warning_days is None:
            tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
            if tenant:
                self._flip_warning_days = tenant.flip_warning_days
                self._flip_critical_days = tenant.flip_critical_days
            else:
                self._flip_warning_days = 21
                self._flip_critical_days = 31
        return self._flip_warning_days, self._flip_critical_days

    def _calculate_flip_status(
        self, stock: Stock
    ) -> tuple[str | None, int | None, datetime | None]:
        """Calculate flip status for a stock.

        Args:
            stock: Stock model with flip_events loaded.

        Returns:
            Tuple of (flip_status, days_since_flip, last_flip_at).
        """
        # Check if flip_events relationship is loaded
        if not hasattr(stock, "flip_events") or stock.flip_events is None:
            # Load flip events if not loaded
            last_flip = (
                self.db.query(FlipEvent)
                .filter(FlipEvent.stock_id == stock.id)
                .order_by(FlipEvent.flipped_at.desc())
                .first()
            )
        else:
            last_flip = stock.flip_events[0] if stock.flip_events else None

        if last_flip is None:
            return "never", None, None

        warning_days, critical_days = self._get_flip_settings()
        now = datetime.utcnow()
        days_since = (now - last_flip.flipped_at).days

        if days_since >= critical_days:
            status = "critical"
        elif days_since >= warning_days:
            status = "warning"
        else:
            status = "ok"

        return status, days_since, last_flip.flipped_at

    def _stock_to_response(self, stock: Stock, include_tenant: bool = False) -> StockResponse:
        """Convert stock model to response schema.

        Args:
            stock: Stock model.
            include_tenant: Whether to include tenant info (for cross-lab views).

        Returns:
            StockResponse: Stock response schema.
        """
        tray_info = None
        if stock.tray:
            tray_info = TrayInfo(id=stock.tray.id, name=stock.tray.name)

        owner_info = None
        if stock.owner:
            owner_info = OwnerInfo(id=stock.owner.id, full_name=stock.owner.full_name)

        tenant_info = None
        if include_tenant and stock.tenant:
            tenant_info = TenantInfo(
                id=stock.tenant.id,
                name=stock.tenant.name,
                city=stock.tenant.city,
                country=stock.tenant.country,
            )

        # Calculate flip status
        flip_status, days_since_flip, last_flip_at = self._calculate_flip_status(stock)

        return StockResponse(
            id=stock.id,
            stock_id=stock.stock_id,
            genotype=stock.genotype,
            origin=stock.origin,
            repository=stock.repository,
            repository_stock_id=stock.repository_stock_id,
            external_source=stock.external_source,
            original_genotype=stock.original_genotype,
            notes=stock.notes,
            is_active=stock.is_active,
            created_at=stock.created_at,
            modified_at=stock.modified_at,
            created_by_name=stock.created_by.full_name if stock.created_by else None,
            modified_by_name=stock.modified_by.full_name if stock.modified_by else None,
            tags=[TagResponse(id=t.id, name=t.name, color=t.color) for t in stock.tags],
            tray=tray_info,
            position=stock.position,
            owner=owner_info,
            visibility=stock.visibility,
            hide_from_org=stock.hide_from_org,
            tenant=tenant_info,
            flip_status=flip_status,
            days_since_flip=days_since_flip,
            last_flip_at=last_flip_at,
        )

    def _build_visibility_filter(self, scope: StockScope):
        """Build SQLAlchemy filter for visibility scope.

        Args:
            scope: Visibility scope.

        Returns:
            SQLAlchemy filter clause.
        """
        if scope == StockScope.LAB:
            # Only stocks from current lab
            return Stock.tenant_id == self.tenant_id
        elif scope == StockScope.ORGANIZATION:
            # Stocks from current lab OR
            # (org/public visibility AND same org AND not hidden from org)
            if not self.organization_id:
                # No org, fall back to lab only
                return Stock.tenant_id == self.tenant_id
            # Get all tenant IDs in same organization
            org_tenant_ids = (
                self.db.query(Tenant.id)
                .filter(Tenant.organization_id == self.organization_id)
                .all()
            )
            org_tenant_ids = [t[0] for t in org_tenant_ids]
            return or_(
                Stock.tenant_id == self.tenant_id,
                and_(
                    Stock.tenant_id.in_(org_tenant_ids),
                    Stock.visibility.in_([StockVisibility.ORGANIZATION, StockVisibility.PUBLIC]),
                    not Stock.hide_from_org,
                ),
            )
        else:  # PUBLIC
            # All public stocks from any lab
            return or_(
                Stock.tenant_id == self.tenant_id,
                Stock.visibility == StockVisibility.PUBLIC,
            )

    def list_stocks(self, params: StockSearchParams) -> StockListResponse:
        """List stocks with filtering and pagination.

        Args:
            params: Search and pagination parameters.

        Returns:
            StockListResponse: Paginated stock list.
        """
        query = (
            self.db.query(Stock)
            .options(
                joinedload(Stock.tags),
                joinedload(Stock.created_by),
                joinedload(Stock.modified_by),
                joinedload(Stock.tray),
                joinedload(Stock.owner),
                joinedload(Stock.tenant),
                joinedload(Stock.flip_events),
            )
            .filter(self._build_visibility_filter(params.scope))
            .filter(Stock.is_active == params.is_active)
        )

        # Exclude current tenant's stocks (for exchange/browse)
        if params.exclude_own:
            query = query.filter(Stock.tenant_id != self.tenant_id)

        # Text search
        if params.query:
            search_term = f"%{params.query}%"
            query = query.filter(
                or_(
                    Stock.stock_id.ilike(search_term),
                    Stock.genotype.ilike(search_term),
                    Stock.notes.ilike(search_term),
                )
            )

        # Filter by origin
        if params.origin:
            query = query.filter(Stock.origin == params.origin)

        # Filter by repository
        if params.repository:
            query = query.filter(Stock.repository == params.repository)

        # Filter by tray
        if params.tray_id:
            query = query.filter(Stock.tray_id == params.tray_id)

        # Filter by owner
        if params.owner_id:
            query = query.filter(Stock.owner_id == params.owner_id)

        # Filter by visibility level
        if params.visibility:
            query = query.filter(Stock.visibility == params.visibility)

        # Filter by tags (only for lab scope - tags are tenant-specific)
        if params.tag_ids and params.scope == StockScope.LAB:
            query = query.filter(Stock.tags.any(Tag.id.in_(params.tag_ids)))

        # Count total before pagination
        total = query.count()

        # Dynamic sorting
        sort_field = params.sort_by or "modified_at"

        # For last_flip_at, we need to join with FlipEvent table
        if sort_field == "last_flip_at":
            # Add subquery for last flip date
            # Note: FlipEvent doesn't have tenant_id, so we join through Stock
            last_flip_subq = (
                self.db.query(FlipEvent.stock_id, func.max(FlipEvent.flipped_at).label("last_flip"))
                .join(Stock, FlipEvent.stock_id == Stock.id)
                .filter(Stock.tenant_id == self.tenant_id)
                .group_by(FlipEvent.stock_id)
                .subquery()
            )

            query = query.outerjoin(last_flip_subq, Stock.id == last_flip_subq.c.stock_id)
            sort_column = last_flip_subq.c.last_flip
        else:
            # Regular column sorting
            sort_column_map = {
                "stock_id": Stock.stock_id,
                "genotype": Stock.genotype,
                "repository": Stock.repository,
                "created_at": Stock.created_at,
                "modified_at": Stock.modified_at,
            }
            sort_column = sort_column_map.get(sort_field, Stock.modified_at)

        # Apply sort order
        if params.sort_order == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Pagination
        offset = (params.page - 1) * params.page_size
        stocks = query.offset(offset).limit(params.page_size).all()

        pages = (total + params.page_size - 1) // params.page_size

        # Include tenant info for non-lab scopes
        include_tenant = params.scope != StockScope.LAB

        return StockListResponse(
            items=[self._stock_to_response(s, include_tenant=include_tenant) for s in stocks],
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    def get_stock(self, stock_id: str, allow_cross_tenant: bool = False) -> Stock | None:
        """Get a stock by ID.

        Args:
            stock_id: Stock UUID.
            allow_cross_tenant: If True, allow fetching public stocks from other tenants.

        Returns:
            Stock | None: Stock if found.
        """
        query = (
            self.db.query(Stock)
            .options(
                joinedload(Stock.tags),
                joinedload(Stock.created_by),
                joinedload(Stock.modified_by),
                joinedload(Stock.tray),
                joinedload(Stock.owner),
                joinedload(Stock.tenant),
                joinedload(Stock.flip_events),
            )
            .filter(Stock.id == stock_id)
        )

        if allow_cross_tenant:
            # Allow if own stock OR public stock
            query = query.filter(
                or_(
                    Stock.tenant_id == self.tenant_id,
                    Stock.visibility == StockVisibility.PUBLIC,
                )
            )
        else:
            query = query.filter(Stock.tenant_id == self.tenant_id)

        return query.first()

    def get_stock_by_stock_id(self, stock_id: str) -> Stock | None:
        """Get a stock by its human-readable stock_id.

        Args:
            stock_id: Human-readable stock ID.

        Returns:
            Stock | None: Stock if found.
        """
        return (
            self.db.query(Stock)
            .filter(Stock.stock_id == stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )

    def create_stock(self, data: StockCreate, user_id: str) -> Stock:
        """Create a new stock.

        Args:
            data: Stock creation data.
            user_id: Creating user's ID.

        Returns:
            Stock: Created stock.

        Raises:
            ValueError: If stock_id already exists or invalid tray/position.
        """
        # Check for duplicate stock_id
        existing = self.get_stock_by_stock_id(data.stock_id)
        if existing:
            raise ValueError(f"Stock ID '{data.stock_id}' already exists")

        # Validate tray and position if provided
        if data.tray_id:
            tray = (
                self.db.query(Tray)
                .filter(Tray.id == data.tray_id, Tray.tenant_id == self.tenant_id)
                .first()
            )
            if not tray:
                raise ValueError("Tray not found")
            # Position validation can be added here if needed

        # Get tags
        tags = []
        if data.tag_ids:
            tags = (
                self.db.query(Tag)
                .filter(Tag.id.in_(data.tag_ids), Tag.tenant_id == self.tenant_id)
                .all()
            )

        # Owner defaults to creator
        owner_id = data.owner_id if data.owner_id else user_id

        stock = Stock(
            tenant_id=self.tenant_id,
            stock_id=data.stock_id,
            genotype=data.genotype,
            origin=data.origin,
            repository=data.repository,
            repository_stock_id=data.repository_stock_id,
            external_source=data.external_source,
            original_genotype=data.original_genotype,
            notes=data.notes,
            tray_id=data.tray_id,
            position=data.position,
            owner_id=owner_id,
            visibility=data.visibility,
            hide_from_org=data.hide_from_org,
            created_by_id=user_id,
            modified_by_id=user_id,
            tags=tags,
        )

        self.db.add(stock)
        self.db.commit()
        self.db.refresh(stock)
        return stock

    def update_stock(self, stock_id: str, data: StockUpdate, user_id: str) -> Stock | None:
        """Update a stock.

        Args:
            stock_id: Stock UUID.
            data: Update data.
            user_id: Updating user's ID.

        Returns:
            Stock | None: Updated stock if found.

        Raises:
            ValueError: If new stock_id already exists or invalid tray.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return None

        # Check for duplicate stock_id if changing
        if data.stock_id and data.stock_id != stock.stock_id:
            existing = self.get_stock_by_stock_id(data.stock_id)
            if existing:
                raise ValueError(f"Stock ID '{data.stock_id}' already exists")
            stock.stock_id = data.stock_id

        if data.genotype is not None:
            stock.genotype = data.genotype
        if data.origin is not None:
            stock.origin = data.origin
        if data.repository is not None:
            stock.repository = data.repository
        if data.repository_stock_id is not None:
            stock.repository_stock_id = data.repository_stock_id
        if data.external_source is not None:
            stock.external_source = data.external_source
        if data.original_genotype is not None:
            stock.original_genotype = data.original_genotype
        if data.notes is not None:
            stock.notes = data.notes

        # Update tray and position
        if data.tray_id is not None:
            if data.tray_id:
                tray = (
                    self.db.query(Tray)
                    .filter(Tray.id == data.tray_id, Tray.tenant_id == self.tenant_id)
                    .first()
                )
                if not tray:
                    raise ValueError("Tray not found")
            stock.tray_id = data.tray_id if data.tray_id else None
        if data.position is not None:
            stock.position = data.position if data.position else None

        # Update owner
        if data.owner_id is not None:
            stock.owner_id = data.owner_id if data.owner_id else None

        # Update visibility
        if data.visibility is not None:
            stock.visibility = data.visibility
        if data.hide_from_org is not None:
            stock.hide_from_org = data.hide_from_org

        # Update tags if provided
        if data.tag_ids is not None:
            tags = (
                self.db.query(Tag)
                .filter(Tag.id.in_(data.tag_ids), Tag.tenant_id == self.tenant_id)
                .all()
            )
            stock.tags = tags

        stock.modified_by_id = user_id
        self.db.commit()
        self.db.refresh(stock)
        return stock

    def delete_stock(self, stock_id: str, user_id: str) -> bool:
        """Soft delete a stock.

        Args:
            stock_id: Stock UUID.
            user_id: Deleting user's ID.

        Returns:
            bool: True if deleted, False if not found.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return False

        stock.is_active = False
        stock.modified_by_id = user_id
        self.db.commit()
        return True

    def restore_stock(self, stock_id: str, user_id: str) -> bool:
        """Restore a soft-deleted stock.

        Args:
            stock_id: Stock UUID.
            user_id: Restoring user's ID.

        Returns:
            bool: True if restored, False if not found.
        """
        stock = (
            self.db.query(Stock)
            .filter(Stock.id == stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )
        if not stock:
            return False

        stock.is_active = True
        stock.modified_by_id = user_id
        self.db.commit()
        return True

    # Tag operations

    def list_tags(self) -> list[TagResponse]:
        """List all tags for the tenant.

        Returns:
            list[TagResponse]: List of tags.
        """
        tags = self.db.query(Tag).filter(Tag.tenant_id == self.tenant_id).order_by(Tag.name).all()
        return [TagResponse(id=t.id, name=t.name, color=t.color) for t in tags]

    def create_tag(self, data: TagCreate) -> Tag:
        """Create a new tag.

        Args:
            data: Tag creation data.

        Returns:
            Tag: Created tag.

        Raises:
            ValueError: If tag name already exists.
        """
        existing = (
            self.db.query(Tag)
            .filter(Tag.tenant_id == self.tenant_id, Tag.name == data.name)
            .first()
        )
        if existing:
            raise ValueError(f"Tag '{data.name}' already exists")

        tag = Tag(
            tenant_id=self.tenant_id,
            name=data.name,
            color=data.color,
        )
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def delete_tag(self, tag_id: str) -> bool:
        """Delete a tag.

        Args:
            tag_id: Tag UUID.

        Returns:
            bool: True if deleted, False if not found.
        """
        tag = self.db.query(Tag).filter(Tag.id == tag_id, Tag.tenant_id == self.tenant_id).first()
        if not tag:
            return False

        self.db.delete(tag)
        self.db.commit()
        return True

    def get_stats(self) -> dict:
        """Get stock statistics for dashboard.

        Returns:
            dict: Statistics.
        """
        total_stocks = (
            self.db.query(func.count(Stock.id))
            .filter(Stock.tenant_id == self.tenant_id, Stock.is_active)
            .scalar()
        )

        total_tags = (
            self.db.query(func.count(Tag.id)).filter(Tag.tenant_id == self.tenant_id).scalar()
        )

        return {
            "total_stocks": total_stocks,
            "total_tags": total_tags,
        }

    # Bulk operations

    def bulk_update_visibility(self, data, user_id: str):
        """Bulk update stock visibility.

        Args:
            data: BulkVisibilityUpdate with stock_ids and visibility.
            user_id: User performing the update.

        Returns:
            dict: Update results with counts.
        """
        from app.stocks.schemas import BulkUpdateResponse

        updated_count = 0
        errors = []

        for stock_id in data.stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                stock.visibility = data.visibility
                stock.modified_by_id = user_id
                updated_count += 1
            else:
                errors.append(f"Stock {stock_id} not found")

        self.db.commit()
        return BulkUpdateResponse(
            updated_count=updated_count, failed_count=len(errors), errors=errors
        )

    def bulk_add_tags(self, data, user_id: str):
        """Bulk add tags to stocks.

        Args:
            data: BulkTagsUpdate with stock_ids and tag_ids.
            user_id: User performing the update.

        Returns:
            dict: Update results with counts.
        """
        from app.stocks.schemas import BulkUpdateResponse

        updated_count = 0
        errors = []

        # Get tags once
        tags = (
            self.db.query(Tag)
            .filter(Tag.id.in_(data.tag_ids), Tag.tenant_id == self.tenant_id)
            .all()
        )

        if not tags:
            return BulkUpdateResponse(
                updated_count=0, failed_count=len(data.stock_ids), errors=["No valid tags found"]
            )

        for stock_id in data.stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                # Add tags that don't already exist on this stock
                existing_tag_ids = {t.id for t in stock.tags}
                new_tags = [t for t in tags if t.id not in existing_tag_ids]
                stock.tags.extend(new_tags)
                stock.modified_by_id = user_id
                updated_count += 1
            else:
                errors.append(f"Stock {stock_id} not found")

        self.db.commit()
        return BulkUpdateResponse(
            updated_count=updated_count, failed_count=len(errors), errors=errors
        )

    def bulk_remove_tags(self, data, user_id: str):
        """Bulk remove tags from stocks.

        Args:
            data: BulkTagsUpdate with stock_ids and tag_ids.
            user_id: User performing the update.

        Returns:
            dict: Update results with counts.
        """
        from app.stocks.schemas import BulkUpdateResponse

        updated_count = 0
        errors = []

        for stock_id in data.stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                # Remove specified tags
                stock.tags = [t for t in stock.tags if t.id not in data.tag_ids]
                stock.modified_by_id = user_id
                updated_count += 1
            else:
                errors.append(f"Stock {stock_id} not found")

        self.db.commit()
        return BulkUpdateResponse(
            updated_count=updated_count, failed_count=len(errors), errors=errors
        )

    def bulk_change_tray(self, data, user_id: str):
        """Bulk change tray for stocks.

        Args:
            data: BulkTrayUpdate with stock_ids and tray_id.
            user_id: User performing the update.

        Returns:
            dict: Update results with counts.
        """
        from app.stocks.schemas import BulkUpdateResponse

        updated_count = 0
        errors = []

        # Validate tray if provided
        if data.tray_id:
            tray = (
                self.db.query(Tray)
                .filter(Tray.id == data.tray_id, Tray.tenant_id == self.tenant_id)
                .first()
            )
            if not tray:
                return BulkUpdateResponse(
                    updated_count=0, failed_count=len(data.stock_ids), errors=["Tray not found"]
                )

        for stock_id in data.stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                stock.tray_id = data.tray_id
                stock.modified_by_id = user_id
                updated_count += 1
            else:
                errors.append(f"Stock {stock_id} not found")

        self.db.commit()
        return BulkUpdateResponse(
            updated_count=updated_count, failed_count=len(errors), errors=errors
        )

    def bulk_change_owner(self, data, user_id: str):
        """Bulk change owner for stocks.

        Args:
            data: BulkOwnerUpdate with stock_ids and owner_id.
            user_id: User performing the update.

        Returns:
            dict: Update results with counts.
        """
        from app.stocks.schemas import BulkUpdateResponse

        updated_count = 0
        errors = []

        for stock_id in data.stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                stock.owner_id = data.owner_id
                stock.modified_by_id = user_id
                updated_count += 1
            else:
                errors.append(f"Stock {stock_id} not found")

        self.db.commit()
        return BulkUpdateResponse(
            updated_count=updated_count, failed_count=len(errors), errors=errors
        )


def get_stock_service(db: Session, tenant_id: str) -> StockService:
    """Factory function for StockService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        StockService: Stock service instance.
    """
    return StockService(db, tenant_id)
