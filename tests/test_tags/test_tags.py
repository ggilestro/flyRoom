"""Tests for the tags API."""

import pytest

from app.tags.schemas import TagCreate, TagResponse, TagUpdate, TagWithCount


class TestTagSchemas:
    """Tests for tag Pydantic schemas."""

    def test_tag_create_valid(self):
        """Test valid tag creation schema."""
        tag = TagCreate(name="GAL4", color="#3b82f6")
        assert tag.name == "GAL4"
        assert tag.color == "#3b82f6"

    def test_tag_create_without_color(self):
        """Test tag creation without color."""
        tag = TagCreate(name="screening")
        assert tag.name == "screening"
        assert tag.color is None

    def test_tag_create_invalid_color(self):
        """Test tag creation with invalid color."""
        with pytest.raises(ValueError):
            TagCreate(name="test", color="invalid")

    def test_tag_create_empty_name(self):
        """Test tag creation with empty name."""
        with pytest.raises(ValueError):
            TagCreate(name="")

    def test_tag_update_partial(self):
        """Test partial tag update."""
        update = TagUpdate(name="new name")
        assert update.name == "new name"
        assert update.color is None

    def test_tag_response(self):
        """Test tag response schema."""
        tag = TagResponse(id="123", name="GAL4", color="#ff0000")
        assert tag.id == "123"
        assert tag.name == "GAL4"
        assert tag.color == "#ff0000"

    def test_tag_with_count(self):
        """Test tag with count schema."""
        tag = TagWithCount(id="123", name="GAL4", color="#ff0000", stock_count=5)
        assert tag.stock_count == 5

    def test_tag_with_count_default(self):
        """Test tag with count defaults to 0."""
        tag = TagWithCount(id="123", name="GAL4")
        assert tag.stock_count == 0
