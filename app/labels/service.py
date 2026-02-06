"""Label service layer."""

import base64
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session, joinedload

from app.db.models import Stock
from app.labels.generators import (
    generate_barcode,
    generate_label_content,
    generate_qr_code,
    get_label_format,
    list_label_formats,
)
from app.labels.pdf_generator import (
    create_batch_label_pdf,
    create_label_pdf,
)
from app.labels.pdf_generator import (
    get_available_formats as get_pdf_formats,
)


class LabelService:
    """Service class for label operations."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize label service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id

    def get_stock(self, stock_id: str) -> Stock | None:
        """Get a stock by ID.

        Args:
            stock_id: Stock UUID.

        Returns:
            Stock | None: Stock if found.
        """
        return (
            self.db.query(Stock)
            .options(joinedload(Stock.tray))
            .filter(Stock.id == stock_id, Stock.tenant_id == self.tenant_id)
            .first()
        )

    def generate_qr(self, stock_id: str, size: int = 200) -> bytes | None:
        """Generate QR code for a stock.

        Args:
            stock_id: Stock UUID.
            size: QR code size in pixels.

        Returns:
            bytes | None: PNG image data if stock found.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return None

        qr_data = f"flypush://{stock.stock_id}"
        return generate_qr_code(qr_data, size=size)

    def generate_barcode(self, stock_id: str) -> bytes | None:
        """Generate barcode for a stock.

        Args:
            stock_id: Stock UUID.

        Returns:
            bytes | None: PNG image data if stock found.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return None

        return generate_barcode(stock.stock_id)

    def generate_label_data(
        self,
        stock_id: str,
        format_name: str = "brother_29mm",
        include_qr: bool = True,
        include_barcode: bool = True,
    ) -> dict | None:
        """Generate full label data for a stock.

        Args:
            stock_id: Stock UUID.
            format_name: Label format name.
            include_qr: Whether to include QR code.
            include_barcode: Whether to include barcode.

        Returns:
            dict | None: Label data if stock found.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return None

        label_format = get_label_format(format_name)
        content = generate_label_content(
            stock_id=stock.stock_id,
            genotype=stock.genotype,
            include_qr=include_qr,
            include_barcode=include_barcode,
        )

        # Convert binary data to base64 for JSON response
        if "qr_code" in content:
            content["qr_code_base64"] = base64.b64encode(content["qr_code"]).decode()
            del content["qr_code"]

        if "barcode" in content:
            content["barcode_base64"] = base64.b64encode(content["barcode"]).decode()
            del content["barcode"]

        # Build source info string for label
        source_info = None
        if stock.origin.value == "repository" and stock.repository:
            source_info = f"{stock.repository.value.upper()} #{stock.repository_stock_id or ''}"
        elif stock.origin.value == "external" and stock.external_source:
            source_info = f"From: {stock.external_source}"
        elif stock.origin.value == "internal":
            source_info = "Internal"

        # Build location string for label
        location_info = None
        if stock.tray:
            location_info = f"{stock.tray.name}"
            if stock.position:
                location_info += f" - {stock.position}"

        return {
            "stock": {
                "id": stock.id,
                "stock_id": stock.stock_id,
                "genotype": stock.genotype,
                "source": source_info,
                "location": location_info,
            },
            "format": label_format,
            "content": content,
        }

    def generate_batch_labels(
        self,
        stock_ids: list[str],
        format_name: str = "brother_29mm",
    ) -> list[dict]:
        """Generate labels for multiple stocks.

        Args:
            stock_ids: List of stock UUIDs.
            format_name: Label format name.

        Returns:
            list[dict]: List of label data.
        """
        labels = []
        for stock_id in stock_ids:
            label = self.generate_label_data(stock_id, format_name)
            if label:
                labels.append(label)
        return labels

    def get_formats(self) -> list[dict]:
        """Get available label formats.

        Returns:
            list[dict]: List of label formats.
        """
        return list_label_formats()

    def _build_stock_label_data(self, stock: Stock, print_date: str | None = None) -> dict:
        """Build label data dict from stock for PDF generation.

        Args:
            stock: Stock model instance.
            print_date: Print date string (defaults to today if None).

        Returns:
            dict: Label data with stock_id, genotype, source_info, location_info, print_date.
        """
        # Default print_date to today
        if print_date is None:
            print_date = date.today().isoformat()

        # Build source info string
        source_info = None
        if stock.origin.value == "repository" and stock.repository:
            source_info = f"{stock.repository.value.upper()} #{stock.repository_stock_id or ''}"
        elif stock.origin.value == "external" and stock.external_source:
            source_info = f"From: {stock.external_source}"
        elif stock.origin.value == "internal":
            source_info = "Internal"

        # Build location string
        location_info = None
        if stock.tray:
            location_info = f"{stock.tray.name}"
            if stock.position:
                location_info += f" - {stock.position}"

        return {
            "stock_id": stock.stock_id,
            "genotype": stock.genotype,
            "source_info": source_info,
            "location_info": location_info,
            "print_date": print_date,
        }

    def generate_pdf(
        self,
        stock_id: str,
        label_format: str = "dymo_11352",
        code_type: Literal["qr", "barcode"] = "qr",
    ) -> bytes | None:
        """Generate a PDF label for a single stock.

        Args:
            stock_id: Stock UUID.
            label_format: Label format name.
            code_type: Type of code to render ("qr" or "barcode").

        Returns:
            bytes | None: PDF file data if stock found.
        """
        stock = self.get_stock(stock_id)
        if not stock:
            return None

        label_data = self._build_stock_label_data(stock)
        return create_label_pdf(
            stock_id=label_data["stock_id"],
            genotype=label_data["genotype"],
            label_format=label_format,
            source_info=label_data["source_info"],
            location_info=label_data["location_info"],
            code_type=code_type,
            print_date=label_data["print_date"],
        )

    def generate_batch_pdf(
        self,
        stock_ids: list[str],
        label_format: str = "dymo_11352",
        code_type: Literal["qr", "barcode"] = "qr",
    ) -> bytes | None:
        """Generate a multi-page PDF with labels for multiple stocks.

        Args:
            stock_ids: List of stock UUIDs.
            label_format: Label format name.
            code_type: Type of code to render ("qr" or "barcode").

        Returns:
            bytes | None: PDF file data, or None if no stocks found.
        """
        labels = []
        for stock_id in stock_ids:
            stock = self.get_stock(stock_id)
            if stock:
                labels.append(self._build_stock_label_data(stock))

        if not labels:
            return None

        return create_batch_label_pdf(labels, label_format=label_format, code_type=code_type)

    def get_pdf_formats(self) -> list[dict]:
        """Get available PDF label formats.

        Returns:
            list[dict]: List of PDF-capable label formats.
        """
        return get_pdf_formats()


def get_label_service(db: Session, tenant_id: str) -> LabelService:
    """Factory function for LabelService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        LabelService: Label service instance.
    """
    return LabelService(db, tenant_id)
