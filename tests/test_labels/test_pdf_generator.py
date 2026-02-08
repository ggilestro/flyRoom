"""Tests for PDF label generation."""

import pytest

from app.labels.pdf_generator import (
    LABEL_SIZES,
    _wrap_text,
    create_batch_label_pdf,
    create_label_pdf,
    get_available_formats,
)


class TestLabelSizes:
    """Tests for label size configuration."""

    def test_dymo_11352_dimensions(self):
        """Dymo 11352 should be 25.4mm x 54mm (width x height)."""
        assert "dymo_11352" in LABEL_SIZES
        assert LABEL_SIZES["dymo_11352"] == (25.4, 54)

    def test_dymo_99010_dimensions(self):
        """Dymo 99010 should be 28x89mm (width x height)."""
        assert "dymo_99010" in LABEL_SIZES
        assert LABEL_SIZES["dymo_99010"] == (28, 89)

    def test_brother_formats_exist(self):
        """Brother formats should be available."""
        assert "brother_29mm" in LABEL_SIZES
        assert "brother_62mm" in LABEL_SIZES


class TestCreateLabelPdf:
    """Tests for single label PDF generation."""

    def test_creates_valid_pdf(self):
        """Should create valid PDF bytes."""
        pdf = create_label_pdf(
            stock_id="TEST-001",
            genotype="w[1118]; P{GAL4-da.G32}",
        )
        assert isinstance(pdf, bytes)
        assert len(pdf) > 0
        # PDF magic bytes
        assert pdf[:4] == b"%PDF"

    def test_with_source_info(self):
        """Should include source info in PDF."""
        pdf = create_label_pdf(
            stock_id="TEST-002",
            genotype="w[1118]",
            source_info="BDSC #3605",
        )
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"

    def test_with_location_info(self):
        """Should include location info in PDF."""
        pdf = create_label_pdf(
            stock_id="TEST-003",
            genotype="w[1118]",
            location_info="Tray A - 15",
        )
        assert isinstance(pdf, bytes)

    def test_different_formats(self):
        """Should work with different label formats."""
        for format_name in LABEL_SIZES.keys():
            pdf = create_label_pdf(
                stock_id="TEST-004",
                genotype="w[1118]",
                label_format=format_name,
            )
            assert isinstance(pdf, bytes)
            assert pdf[:4] == b"%PDF"

    def test_invalid_format_raises(self):
        """Should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Unknown label format"):
            create_label_pdf(
                stock_id="TEST-005",
                genotype="w[1118]",
                label_format="invalid_format",
            )

    def test_long_genotype(self):
        """Should handle long genotypes."""
        long_genotype = "w[1118]; P{UAS-mCD8::GFP.L}LL5; P{GAL4-da.G32}UH1; TM3, Sb[1]"
        pdf = create_label_pdf(
            stock_id="TEST-006",
            genotype=long_genotype,
        )
        assert isinstance(pdf, bytes)


class TestCreateBatchLabelPdf:
    """Tests for batch label PDF generation."""

    def test_creates_multi_page_pdf(self):
        """Should create PDF with multiple pages."""
        labels = [
            {"stock_id": "TEST-001", "genotype": "w[1118]"},
            {"stock_id": "TEST-002", "genotype": "Oregon-R"},
            {"stock_id": "TEST-003", "genotype": "Canton-S"},
        ]
        pdf = create_batch_label_pdf(labels)
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"

    def test_empty_list(self):
        """Should handle empty list."""
        pdf = create_batch_label_pdf([])
        assert isinstance(pdf, bytes)

    def test_with_optional_fields(self):
        """Should include optional fields when provided."""
        labels = [
            {
                "stock_id": "TEST-001",
                "genotype": "w[1118]",
                "source_info": "BDSC #3605",
                "location_info": "Tray A - 1",
            },
            {
                "stock_id": "TEST-002",
                "genotype": "Oregon-R",
                "source_info": None,
                "location_info": None,
            },
        ]
        pdf = create_batch_label_pdf(labels)
        assert isinstance(pdf, bytes)

    def test_different_format(self):
        """Should work with different formats."""
        labels = [
            {"stock_id": "TEST-001", "genotype": "w[1118]"},
        ]
        pdf = create_batch_label_pdf(labels, label_format="dymo_99010")
        assert isinstance(pdf, bytes)


class TestWrapText:
    """Tests for text wrapping utility."""

    def test_short_text_no_wrap(self):
        """Short text should not be wrapped."""
        result = _wrap_text("short", max_chars=20)
        assert result == ["short"]

    def test_long_text_wraps(self):
        """Long text should wrap to multiple lines."""
        text = "This is a long piece of text that needs wrapping"
        result = _wrap_text(text, max_chars=15, max_lines=5)
        assert len(result) > 1

    def test_respects_max_lines(self):
        """Should not exceed max_lines."""
        text = "This is a very long piece of text that needs many lines to display"
        result = _wrap_text(text, max_chars=10, max_lines=3)
        assert len(result) <= 3

    def test_adds_ellipsis_when_truncated(self):
        """Should add ellipsis when text is truncated."""
        text = "This is a very long piece of text that will be truncated"
        result = _wrap_text(text, max_chars=15, max_lines=2)
        assert result[-1].endswith("...")

    def test_breaks_at_semicolon(self):
        """Should prefer breaking at semicolons."""
        text = "w[1118]; P{GAL4-da.G32}UH1; TM3"
        result = _wrap_text(text, max_chars=20, max_lines=3)
        # Should break at semicolon when possible
        assert len(result) >= 1


class TestGetAvailableFormats:
    """Tests for format listing."""

    def test_returns_list(self):
        """Should return list of format dicts."""
        formats = get_available_formats()
        assert isinstance(formats, list)
        assert len(formats) > 0

    def test_format_structure(self):
        """Each format should have required fields."""
        formats = get_available_formats()
        for fmt in formats:
            assert "id" in fmt
            assert "name" in fmt
            assert "width_mm" in fmt
            assert "height_mm" in fmt

    def test_includes_dymo_formats(self):
        """Should include Dymo formats."""
        formats = get_available_formats()
        format_ids = [f["id"] for f in formats]
        assert "dymo_11352" in format_ids
        assert "dymo_99010" in format_ids
