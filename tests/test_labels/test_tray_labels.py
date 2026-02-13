"""Tests for tray label printing."""

from datetime import date
from enum import Enum
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.labels.pdf_generator import create_label_pdf, create_label_png
from app.labels.print_service import PrintService
from app.labels.service import LabelService


# Minimal TrayType enum for mocking
class MockTrayType(Enum):
    NUMERIC = "numeric"
    GRID = "grid"
    CUSTOM = "custom"


def _make_tray(
    tray_type="grid",
    name="Tray-A",
    description="Main lab tray",
    rows=5,
    cols=10,
    max_positions=50,
    tray_id="tray-uuid-123",
    tenant_id="tenant-123",
):
    """Create a mock Tray object."""
    tray = MagicMock()
    tray.id = tray_id
    tray.tenant_id = tenant_id
    tray.name = name
    tray.description = description
    tray.tray_type = MockTrayType(tray_type)
    tray.rows = rows
    tray.cols = cols
    tray.max_positions = max_positions
    return tray


class TestGenerateTrayLabelData:
    """Tests for LabelService.generate_tray_label_data."""

    def test_grid_tray_label_data(self):
        """Should map grid tray fields to label positions correctly."""
        db = MagicMock(spec=Session)
        svc = LabelService(db, "tenant-123")
        tray = _make_tray(tray_type="grid", rows=5, cols=10)

        data = svc.generate_tray_label_data(tray)

        assert data["stock_id"] == "Tray-A"  # Tray name in stock_id position
        assert data["genotype"] == "Main lab tray"  # Description in genotype position
        assert data["source_info"] == "Grid 5x10"  # Type info in source position
        assert data["qr_content"] == "flypush://tray/Tray-A"
        assert data["print_date"] == date.today().isoformat()

    def test_numeric_tray_label_data(self):
        """Should show position count for numeric trays."""
        db = MagicMock(spec=Session)
        svc = LabelService(db, "tenant-123")
        tray = _make_tray(tray_type="numeric", rows=None, cols=None, max_positions=100)

        data = svc.generate_tray_label_data(tray)

        assert data["source_info"] == "100 positions"
        assert data["qr_content"] == "flypush://tray/Tray-A"

    def test_tray_without_description(self):
        """Should handle missing description gracefully."""
        db = MagicMock(spec=Session)
        svc = LabelService(db, "tenant-123")
        tray = _make_tray(description=None)

        data = svc.generate_tray_label_data(tray)

        assert data["genotype"] == ""  # Empty string, not None


class TestQrContentOverride:
    """Tests for qr_content parameter in PDF/PNG generation."""

    def test_png_with_qr_content_override(self):
        """Should use custom QR content when provided."""
        png = create_label_png(
            stock_id="Tray-A",
            genotype="Test tray description",
            qr_content="flypush://tray/Tray-A",
        )
        assert isinstance(png, bytes)
        assert len(png) > 0

    def test_png_without_qr_content_falls_back(self):
        """Should fall back to flypush://{stock_id} when qr_content is None."""
        # This just verifies the function works without qr_content (backward compat)
        png = create_label_png(
            stock_id="TEST-001",
            genotype="w[1118]",
        )
        assert isinstance(png, bytes)
        assert len(png) > 0

    def test_pdf_with_qr_content_override(self):
        """Should pass qr_content through to PNG generation."""
        pdf = create_label_pdf(
            stock_id="Tray-B",
            genotype="Description here",
            qr_content="flypush://tray/Tray-B",
        )
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"


class TestTrayJobSentinel:
    """Tests for __TRAY__ sentinel in print service."""

    def test_create_tray_job(self):
        """Should create job with __TRAY__ sentinel in stock_ids."""
        db = MagicMock(spec=Session)
        svc = PrintService(db, "tenant-123", "user-456")

        svc.create_tray_job(tray_id="tray-uuid-123")

        # Verify the job was created with the sentinel
        call_args = db.add.call_args[0][0]
        assert call_args.stock_ids == ["__TRAY__:tray-uuid-123"]
        assert call_args.copies == 1
        db.commit.assert_called_once()

    def test_get_job_labels_tray_sentinel(self):
        """Should resolve __TRAY__ sentinel to tray label data."""
        db = MagicMock(spec=Session)
        svc = PrintService(db, "tenant-123")

        # Mock the job
        mock_job = MagicMock()
        mock_job.id = "job-123"
        mock_job.stock_ids = ["__TRAY__:tray-uuid-123"]
        mock_job.label_format = "dymo_11352"
        mock_job.copies = 1
        mock_job.code_type = "qr"
        db.query.return_value.filter.return_value.first.return_value = mock_job

        # Mock the tray (returned by second query)
        mock_tray = _make_tray()

        def query_side_effect(model):
            """Return different mocks based on query model."""
            result = MagicMock()
            if model.__name__ == "PrintJob":
                result.filter.return_value.first.return_value = mock_job
            elif model.__name__ == "Tray":
                result.filter.return_value.first.return_value = mock_tray
            return result

        db.query.side_effect = query_side_effect

        result = svc.get_job_labels("job-123")

        assert result is not None
        assert len(result.labels) == 1
        assert result.labels[0].stock_id == "Tray-A"
        assert result.labels[0].qr_content == "flypush://tray/Tray-A"

    def test_get_job_labels_tray_not_found(self):
        """Should return None when tray in sentinel doesn't exist."""
        db = MagicMock(spec=Session)
        svc = PrintService(db, "tenant-123")

        mock_job = MagicMock()
        mock_job.id = "job-123"
        mock_job.stock_ids = ["__TRAY__:nonexistent"]
        mock_job.label_format = "dymo_11352"
        mock_job.copies = 1
        mock_job.code_type = "qr"

        def query_side_effect(model):
            result = MagicMock()
            if model.__name__ == "PrintJob":
                result.filter.return_value.first.return_value = mock_job
            elif model.__name__ == "Tray":
                result.filter.return_value.first.return_value = None
            return result

        db.query.side_effect = query_side_effect

        result = svc.get_job_labels("job-123")

        assert result is None
