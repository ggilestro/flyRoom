"""Tray service layer."""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Tray, Stock, TrayType
from app.trays.schemas import (
    TrayCreate,
    TrayUpdate,
    TrayResponse,
    TrayListResponse,
    TrayPositionInfo,
    TrayDetailResponse,
    TrayStockInfo,
)


class TrayService:
    """Service class for tray operations."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize tray service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id

    def _tray_to_response(self, tray: Tray) -> TrayResponse:
        """Convert tray model to response schema.

        Args:
            tray: Tray model.

        Returns:
            TrayResponse: Tray response schema.
        """
        stock_count = (
            self.db.query(func.count(Stock.id))
            .filter(Stock.tray_id == tray.id, Stock.is_active == True)
            .scalar()
        )
        return TrayResponse(
            id=tray.id,
            name=tray.name,
            description=tray.description,
            tray_type=tray.tray_type,
            max_positions=tray.max_positions,
            rows=tray.rows,
            cols=tray.cols,
            created_at=tray.created_at,
            stock_count=stock_count,
        )

    def list_trays(
        self, page: int = 1, page_size: int = 20
    ) -> TrayListResponse:
        """List all trays for the tenant.

        Args:
            page: Page number.
            page_size: Items per page.

        Returns:
            TrayListResponse: Paginated tray list.
        """
        query = (
            self.db.query(Tray)
            .filter(Tray.tenant_id == self.tenant_id)
        )

        total = query.count()
        offset = (page - 1) * page_size
        trays = (
            query.order_by(Tray.name)
            .offset(offset)
            .limit(page_size)
            .all()
        )

        pages = (total + page_size - 1) // page_size

        return TrayListResponse(
            items=[self._tray_to_response(t) for t in trays],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    def get_tray(self, tray_id: str) -> Optional[Tray]:
        """Get a tray by ID.

        Args:
            tray_id: Tray UUID.

        Returns:
            Tray | None: Tray if found.
        """
        return (
            self.db.query(Tray)
            .filter(Tray.id == tray_id, Tray.tenant_id == self.tenant_id)
            .first()
        )

    def get_tray_detail(self, tray_id: str) -> Optional[TrayDetailResponse]:
        """Get tray with position details.

        Args:
            tray_id: Tray UUID.

        Returns:
            TrayDetailResponse | None: Tray detail if found.
        """
        tray = self.get_tray(tray_id)
        if not tray:
            return None

        # Get stocks in this tray
        stocks = (
            self.db.query(Stock)
            .filter(Stock.tray_id == tray_id, Stock.is_active == True)
            .all()
        )

        # Build position map
        position_map = {s.position: s for s in stocks if s.position}

        # Generate all positions based on tray type
        positions = []
        if tray.tray_type == TrayType.GRID and tray.rows and tray.cols:
            # Generate grid positions (A1, A2, ... B1, B2, ...)
            for row in range(tray.rows):
                row_letter = chr(ord('A') + row)
                for col in range(1, tray.cols + 1):
                    pos = f"{row_letter}{col}"
                    stock = position_map.get(pos)
                    positions.append(TrayPositionInfo(
                        position=pos,
                        stock_id=stock.id if stock else None,
                        stock_name=stock.stock_id if stock else None,
                    ))
        else:
            # Numeric positions
            for i in range(1, tray.max_positions + 1):
                pos = str(i)
                stock = position_map.get(pos)
                positions.append(TrayPositionInfo(
                    position=pos,
                    stock_id=stock.id if stock else None,
                    stock_name=stock.stock_id if stock else None,
                ))

        stock_count = len(stocks)

        # Build list of all stocks in this tray
        stock_list = [
            TrayStockInfo(
                id=s.id,
                stock_id=s.stock_id,
                genotype=s.genotype or "",
                position=s.position,
            )
            for s in stocks
        ]

        return TrayDetailResponse(
            id=tray.id,
            name=tray.name,
            description=tray.description,
            tray_type=tray.tray_type,
            max_positions=tray.max_positions,
            rows=tray.rows,
            cols=tray.cols,
            created_at=tray.created_at,
            stock_count=stock_count,
            positions=positions,
            stocks=stock_list,
        )

    def create_tray(self, data: TrayCreate) -> Tray:
        """Create a new tray.

        Args:
            data: Tray creation data.

        Returns:
            Tray: Created tray.

        Raises:
            ValueError: If tray name already exists.
        """
        # Check for duplicate name
        existing = (
            self.db.query(Tray)
            .filter(Tray.tenant_id == self.tenant_id, Tray.name == data.name)
            .first()
        )
        if existing:
            raise ValueError(f"Tray '{data.name}' already exists")

        # For grid type, calculate max_positions from rows*cols
        max_positions = data.max_positions
        if data.tray_type == TrayType.GRID and data.rows and data.cols:
            max_positions = data.rows * data.cols

        tray = Tray(
            tenant_id=self.tenant_id,
            name=data.name,
            description=data.description,
            tray_type=data.tray_type,
            max_positions=max_positions,
            rows=data.rows,
            cols=data.cols,
        )

        self.db.add(tray)
        self.db.commit()
        self.db.refresh(tray)
        return tray

    def update_tray(self, tray_id: str, data: TrayUpdate) -> Optional[Tray]:
        """Update a tray.

        Args:
            tray_id: Tray UUID.
            data: Update data.

        Returns:
            Tray | None: Updated tray if found.

        Raises:
            ValueError: If new name already exists.
        """
        tray = self.get_tray(tray_id)
        if not tray:
            return None

        # Check for duplicate name if changing
        if data.name and data.name != tray.name:
            existing = (
                self.db.query(Tray)
                .filter(Tray.tenant_id == self.tenant_id, Tray.name == data.name)
                .first()
            )
            if existing:
                raise ValueError(f"Tray '{data.name}' already exists")
            tray.name = data.name

        if data.description is not None:
            tray.description = data.description
        if data.tray_type is not None:
            tray.tray_type = data.tray_type
        if data.max_positions is not None:
            tray.max_positions = data.max_positions
        if data.rows is not None:
            tray.rows = data.rows
        if data.cols is not None:
            tray.cols = data.cols

        # Recalculate max_positions for grid type
        if tray.tray_type == TrayType.GRID and tray.rows and tray.cols:
            tray.max_positions = tray.rows * tray.cols

        self.db.commit()
        self.db.refresh(tray)
        return tray

    def delete_tray(self, tray_id: str) -> bool:
        """Delete a tray (removes tray_id from stocks first).

        Args:
            tray_id: Tray UUID.

        Returns:
            bool: True if deleted, False if not found.
        """
        tray = self.get_tray(tray_id)
        if not tray:
            return False

        # Remove tray reference from stocks
        (
            self.db.query(Stock)
            .filter(Stock.tray_id == tray_id)
            .update({"tray_id": None, "position": None})
        )

        self.db.delete(tray)
        self.db.commit()
        return True

    def validate_position(self, tray_id: str, position: str) -> bool:
        """Validate that a position is valid for a tray.

        Args:
            tray_id: Tray UUID.
            position: Position string.

        Returns:
            bool: True if valid.
        """
        tray = self.get_tray(tray_id)
        if not tray:
            return False

        if tray.tray_type == TrayType.GRID and tray.rows and tray.cols:
            # Position should be like "A1", "B12", etc.
            if len(position) < 2:
                return False
            row_letter = position[0].upper()
            try:
                col_num = int(position[1:])
            except ValueError:
                return False
            row_num = ord(row_letter) - ord('A')
            return 0 <= row_num < tray.rows and 1 <= col_num <= tray.cols
        else:
            # Numeric position
            try:
                pos_num = int(position)
                return 1 <= pos_num <= tray.max_positions
            except ValueError:
                return False


def get_tray_service(db: Session, tenant_id: str) -> TrayService:
    """Factory function for TrayService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        TrayService: Tray service instance.
    """
    return TrayService(db, tenant_id)
