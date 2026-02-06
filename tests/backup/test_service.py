"""Tests for backup service."""

from unittest.mock import MagicMock

from app.backup.schemas import ConflictMode
from app.backup.service import CURRENT_SCHEMA_VERSION, IMPORT_ORDER, BackupService


class TestSchemaCompatibility:
    """Test schema version compatibility checking."""

    def test_compatible_schema(self):
        """Test that matching schema versions are compatible."""
        db = MagicMock()
        service = BackupService(db)
        assert service._check_schema_compatibility(CURRENT_SCHEMA_VERSION) is True

    def test_incompatible_schema(self):
        """Test that different schema versions are incompatible."""
        db = MagicMock()
        service = BackupService(db)
        assert service._check_schema_compatibility("001") is False
        assert service._check_schema_compatibility("unknown") is False


class TestValidation:
    """Test backup validation."""

    def test_validate_missing_metadata(self):
        """Test validation fails with missing metadata."""
        db = MagicMock()
        service = BackupService(db)

        result = service.validate_backup({"data": {}}, "tenant-123")

        assert result.is_valid is False
        assert any("metadata" in e.lower() for e in result.errors)

    def test_validate_missing_data(self):
        """Test validation fails with missing data section."""
        db = MagicMock()
        service = BackupService(db)

        result = service.validate_backup({"metadata": {}}, "tenant-123")

        assert result.is_valid is False
        assert any("data" in e.lower() for e in result.errors)

    def test_validate_incompatible_schema(self):
        """Test validation fails with incompatible schema."""
        db = MagicMock()
        service = BackupService(db)

        backup = {
            "metadata": {"schema_version": "001"},
            "data": {},
        }
        result = service.validate_backup(backup, "tenant-123")

        assert result.is_valid is False
        assert result.schema_compatible is False

    def test_validate_unknown_tables_warning(self):
        """Test validation warns about unknown tables."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        service = BackupService(db)

        backup = {
            "metadata": {"schema_version": CURRENT_SCHEMA_VERSION},
            "data": {"unknown_table": []},
        }
        result = service.validate_backup(backup, "tenant-123")

        assert any("unknown_table" in w for w in result.warnings)

    def test_validate_valid_backup(self):
        """Test validation passes for valid backup."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        service = BackupService(db)

        backup = {
            "metadata": {"schema_version": CURRENT_SCHEMA_VERSION},
            "data": {
                "users": [],
                "stocks": [],
            },
        }
        result = service.validate_backup(backup, "tenant-123")

        assert result.is_valid is True
        assert result.schema_compatible is True


class TestReferenceValidation:
    """Test referential integrity validation within backup."""

    def test_validate_stock_with_missing_tray(self):
        """Test validation catches missing tray reference."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        service = BackupService(db)

        data = {
            "trays": [],
            "stocks": [
                {
                    "id": "stock-1",
                    "stock_id": "TEST-1",
                    "genotype": "test",
                    "tray_id": "missing-tray",
                }
            ],
        }
        errors = service._validate_references(data)

        assert any("tray" in e.lower() for e in errors)

    def test_validate_stock_tags_with_missing_stock(self):
        """Test validation catches missing stock reference in stock_tags."""
        db = MagicMock()
        service = BackupService(db)

        data = {
            "stocks": [],
            "tags": [{"id": "tag-1"}],
            "stock_tags": [{"stock_id": "missing-stock", "tag_id": "tag-1"}],
        }
        errors = service._validate_references(data)

        assert any("stock" in e.lower() for e in errors)

    def test_validate_cross_with_missing_parents(self):
        """Test validation catches missing parent stocks in crosses."""
        db = MagicMock()
        service = BackupService(db)

        data = {
            "stocks": [{"id": "stock-1"}],
            "crosses": [
                {
                    "id": "cross-1",
                    "parent_female_id": "stock-1",
                    "parent_male_id": "missing-stock",
                }
            ],
        }
        errors = service._validate_references(data)

        assert any("male parent" in e.lower() for e in errors)


class TestImportOrder:
    """Test import order respects foreign keys."""

    def test_import_order_has_required_tables(self):
        """Test import order includes all expected tables."""
        required = ["users", "trays", "tags", "stocks", "stock_tags", "crosses"]
        for table in required:
            assert table in IMPORT_ORDER

    def test_users_before_stocks(self):
        """Test users are imported before stocks (for created_by_id)."""
        assert IMPORT_ORDER.index("users") < IMPORT_ORDER.index("stocks")

    def test_trays_before_stocks(self):
        """Test trays are imported before stocks (for tray_id)."""
        assert IMPORT_ORDER.index("trays") < IMPORT_ORDER.index("stocks")

    def test_stocks_before_crosses(self):
        """Test stocks are imported before crosses (for parent_id)."""
        assert IMPORT_ORDER.index("stocks") < IMPORT_ORDER.index("crosses")

    def test_tags_before_stock_tags(self):
        """Test tags are imported before stock_tags."""
        assert IMPORT_ORDER.index("tags") < IMPORT_ORDER.index("stock_tags")

    def test_stocks_before_flip_events(self):
        """Test stocks are imported before flip_events."""
        assert IMPORT_ORDER.index("stocks") < IMPORT_ORDER.index("flip_events")


class TestConflictModes:
    """Test conflict mode handling."""

    def test_fail_mode_stops_on_conflict(self):
        """Test fail mode stops import on first conflict."""
        db = MagicMock()
        # Simulate existing user
        db.query.return_value.filter.return_value.all.return_value = [MagicMock(id="existing-user")]
        service = BackupService(db)

        backup = {
            "metadata": {"schema_version": CURRENT_SCHEMA_VERSION},
            "data": {
                "users": [
                    {
                        "id": "existing-user",
                        "email": "test@test.com",
                        "password_hash": "x",
                        "full_name": "Test",
                    }
                ]
            },
        }

        result = service.import_backup(backup, "tenant-123", conflict_mode=ConflictMode.FAIL)

        assert result.success is False
        assert "conflict" in result.errors[0].lower()
