"""Labels module for QR/barcode generation and printing."""

from app.labels.print_service import PrintService
from app.labels.router import router
from app.labels.service import LabelService

__all__ = ["router", "LabelService", "PrintService"]
