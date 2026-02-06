"""Tests for backup serializers."""

from datetime import datetime

from app.backup.serializers import (
    deserialize_datetime,
    deserialize_stock,
    deserialize_tag,
    deserialize_tray,
    deserialize_user,
    serialize_datetime,
    serialize_enum,
    serialize_stock,
    serialize_tag,
    serialize_tray,
    serialize_user,
)
from app.db.models import (
    Stock,
    StockOrigin,
    StockVisibility,
    Tag,
    Tray,
    TrayType,
    User,
    UserRole,
    UserStatus,
)


class TestDatetimeSerialization:
    """Test datetime serialization functions."""

    def test_serialize_datetime_with_value(self):
        """Test serializing a datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = serialize_datetime(dt)
        assert result == "2024-01-15T10:30:00"

    def test_serialize_datetime_none(self):
        """Test serializing None datetime."""
        assert serialize_datetime(None) is None

    def test_deserialize_datetime_with_value(self):
        """Test deserializing a datetime string."""
        result = deserialize_datetime("2024-01-15T10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0)

    def test_deserialize_datetime_none(self):
        """Test deserializing None."""
        assert deserialize_datetime(None) is None


class TestEnumSerialization:
    """Test enum serialization."""

    def test_serialize_enum_with_value(self):
        """Test serializing an enum."""
        assert serialize_enum(UserRole.ADMIN) == "admin"
        assert serialize_enum(StockOrigin.REPOSITORY) == "repository"

    def test_serialize_enum_none(self):
        """Test serializing None enum."""
        assert serialize_enum(None) is None


class TestUserSerialization:
    """Test user serialization/deserialization."""

    def test_serialize_user(self):
        """Test serializing a user."""
        user = User(
            id="user-123",
            tenant_id="tenant-456",
            email="test@example.com",
            password_hash="hashed",
            full_name="Test User",
            role=UserRole.ADMIN,
            status=UserStatus.APPROVED,
            is_active=True,
            created_at=datetime(2024, 1, 1),
        )
        result = serialize_user(user)

        assert result["id"] == "user-123"
        assert result["email"] == "test@example.com"
        assert result["role"] == "admin"
        assert result["status"] == "approved"
        assert result["is_active"] is True

    def test_deserialize_user(self):
        """Test deserializing a user."""
        data = {
            "id": "user-123",
            "tenant_id": "old-tenant",
            "email": "test@example.com",
            "password_hash": "hashed",
            "full_name": "Test User",
            "role": "admin",
            "status": "approved",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00",
        }
        # Tenant ID should be overridden
        result = deserialize_user(data, "new-tenant")

        assert result.id == "user-123"
        assert result.tenant_id == "new-tenant"
        assert result.email == "test@example.com"
        assert result.role == UserRole.ADMIN
        assert result.status == UserStatus.APPROVED


class TestTrayRoundTrip:
    """Test tray serialization round-trip."""

    def test_tray_round_trip(self):
        """Test serializing and deserializing a tray."""
        tray = Tray(
            id="tray-123",
            tenant_id="tenant-456",
            name="Test Tray",
            description="A test tray",
            tray_type=TrayType.GRID,
            max_positions=100,
            rows=10,
            cols=10,
        )

        serialized = serialize_tray(tray)
        deserialized = deserialize_tray(serialized, "new-tenant")

        assert deserialized.id == tray.id
        assert deserialized.name == tray.name
        assert deserialized.tray_type == tray.tray_type
        assert deserialized.tenant_id == "new-tenant"


class TestTagRoundTrip:
    """Test tag serialization round-trip."""

    def test_tag_round_trip(self):
        """Test serializing and deserializing a tag."""
        tag = Tag(
            id="tag-123",
            tenant_id="tenant-456",
            name="Important",
            color="#FF0000",
        )

        serialized = serialize_tag(tag)
        deserialized = deserialize_tag(serialized, "new-tenant")

        assert deserialized.id == tag.id
        assert deserialized.name == tag.name
        assert deserialized.color == tag.color
        assert deserialized.tenant_id == "new-tenant"


class TestStockSerialization:
    """Test stock serialization."""

    def test_serialize_stock_full(self):
        """Test serializing a stock with all fields."""
        stock = Stock(
            id="stock-123",
            tenant_id="tenant-456",
            stock_id="BL-1234",
            genotype="w[1118]",
            origin=StockOrigin.REPOSITORY,
            repository_stock_id="1234",
            visibility=StockVisibility.LAB_ONLY,
            is_active=True,
            notes="Test stock",
            external_metadata={"source": "bdsc"},
        )

        result = serialize_stock(stock)

        assert result["id"] == "stock-123"
        assert result["stock_id"] == "BL-1234"
        assert result["origin"] == "repository"
        assert result["visibility"] == "lab_only"
        assert result["external_metadata"] == {"source": "bdsc"}

    def test_deserialize_stock(self):
        """Test deserializing a stock."""
        data = {
            "id": "stock-123",
            "tenant_id": "old-tenant",
            "stock_id": "BL-1234",
            "genotype": "w[1118]",
            "origin": "repository",
            "visibility": "lab_only",
            "is_active": True,
        }

        result = deserialize_stock(data, "new-tenant")

        assert result.id == "stock-123"
        assert result.tenant_id == "new-tenant"
        assert result.origin == StockOrigin.REPOSITORY
        assert result.visibility == StockVisibility.LAB_ONLY


class TestEdgeCases:
    """Test edge cases in serialization."""

    def test_deserialize_with_missing_optional_fields(self):
        """Test deserializing with minimal required fields."""
        data = {
            "id": "user-123",
            "email": "test@example.com",
            "password_hash": "hashed",
            "full_name": "Test",
        }

        result = deserialize_user(data, "tenant-123")
        assert result.role == UserRole.USER
        assert result.status == UserStatus.APPROVED
        assert result.is_active is True

    def test_deserialize_stock_with_none_enums(self):
        """Test deserializing stock with null enum values."""
        data = {
            "id": "stock-123",
            "stock_id": "TEST-1",
            "genotype": "test",
            "origin": None,
            "repository": None,
            "visibility": None,
        }

        result = deserialize_stock(data, "tenant-123")
        assert result.origin == StockOrigin.INTERNAL
        assert result.repository is None
        assert result.visibility == StockVisibility.LAB_ONLY
