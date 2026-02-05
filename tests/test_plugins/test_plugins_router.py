"""Tests for the plugins API router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.plugins.base import StockImportData
from app.plugins.router import router


@pytest.fixture
def mock_flybase_plugin():
    """Create a mock FlyBase plugin."""
    plugin = MagicMock()
    plugin.name = "FlyBase Stock Database"
    plugin.source_id = "flybase"

    # Mock search
    plugin.search = AsyncMock(
        return_value=[
            StockImportData(
                external_id="80563",
                genotype="w[*]; P{Gr21a-GAL80.1756}attP2",
                source="bdsc",
                metadata={
                    "flybase_id": "FBst0080563",
                    "flybase_url": "https://flybase.org/reports/FBst0080563",
                    "repository": "bdsc",
                    "repository_name": "Bloomington Drosophila Stock Center",
                    "repository_url": "https://bdsc.indiana.edu/Home/Search?presearch=80563",
                    "species": "Dmel",
                },
            ),
            StockImportData(
                external_id="v10004",
                genotype="w[1118]; P{GD14516}v10004",
                source="vdrc",
                metadata={
                    "flybase_id": "FBst0100001",
                    "flybase_url": "https://flybase.org/reports/FBst0100001",
                    "repository": "vdrc",
                    "repository_name": "Vienna Drosophila Resource Center",
                    "repository_url": "https://stockcenter.vdrc.at/control/product/~product_id=10004",
                    "species": "Dmel",
                },
            ),
        ]
    )

    # Mock get_details
    plugin.get_details = AsyncMock(
        return_value=StockImportData(
            external_id="80563",
            genotype="w[*]; P{Gr21a-GAL80.1756}attP2",
            source="bdsc",
            metadata={
                "flybase_id": "FBst0080563",
                "flybase_url": "https://flybase.org/reports/FBst0080563",
                "repository": "bdsc",
                "repository_name": "Bloomington Drosophila Stock Center",
                "repository_url": "https://bdsc.indiana.edu/Home/Search?presearch=80563",
                "species": "Dmel",
                "data_version": "FB2025_01",
            },
        )
    )

    # Mock get_stats
    plugin.get_stats = AsyncMock(
        return_value={
            "total_stocks": 188797,
            "data_version": "FB2025_01",
            "cache_valid": True,
            "repositories": [
                {"id": "bdsc", "name": "Bloomington Drosophila Stock Center", "count": 91288},
                {"id": "vdrc", "name": "Vienna Drosophila Resource Center", "count": 38371},
                {"id": "kyoto", "name": "Kyoto Stock Center", "count": 26204},
            ],
        }
    )

    # Mock list_repositories
    plugin.list_repositories = AsyncMock(
        return_value=[
            {"id": "bdsc", "name": "Bloomington Drosophila Stock Center", "count": 91288},
            {"id": "vdrc", "name": "Vienna Drosophila Resource Center", "count": 38371},
            {"id": "kyoto", "name": "Kyoto Stock Center", "count": 26204},
        ]
    )

    # Mock refresh_data
    plugin.refresh_data = AsyncMock(return_value=188797)

    return plugin


@pytest.fixture
def app(mock_flybase_plugin):
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(router, prefix="/api/plugins")

    with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
        yield app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestSourcesEndpoint:
    """Tests for /sources endpoint."""

    def test_list_sources(self, client, mock_flybase_plugin):
        """Test listing available sources."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/sources")

        assert response.status_code == 200
        sources = response.json()
        assert len(sources) >= 1
        assert any(s["source_id"] == "flybase" for s in sources)

        # Check that repositories are included
        flybase_source = next(s for s in sources if s["source_id"] == "flybase")
        assert "repositories" in flybase_source
        assert len(flybase_source["repositories"]) > 0


class TestSearchEndpoint:
    """Tests for /search endpoint."""

    def test_search_valid_query(self, client, mock_flybase_plugin):
        """Test search with valid query."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/search?query=80563&source=flybase")

        assert response.status_code == 200
        results = response.json()
        assert len(results) >= 1
        mock_flybase_plugin.search.assert_called_once()

    def test_search_with_repository_filter(self, client, mock_flybase_plugin):
        """Test search with repository filter."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/search?query=test&source=flybase&repository=vdrc")

        assert response.status_code == 200
        mock_flybase_plugin.search.assert_called_with("test", limit=20, repository="vdrc")

    def test_search_legacy_bdsc_source(self, client, mock_flybase_plugin):
        """Test search with legacy 'bdsc' source ID."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/search?query=80563&source=bdsc")

        assert response.status_code == 200
        # Should automatically filter to bdsc repository
        mock_flybase_plugin.search.assert_called_with("80563", limit=20, repository="bdsc")

    def test_search_missing_query(self, client):
        """Test search without query parameter."""
        response = client.get("/api/plugins/search?source=flybase")

        assert response.status_code == 422  # Validation error

    def test_search_invalid_source(self, client):
        """Test search with invalid source."""
        response = client.get("/api/plugins/search?query=test&source=invalid")

        assert response.status_code == 404


class TestDetailsEndpoint:
    """Tests for /details endpoint."""

    def test_get_details_existing_stock(self, client, mock_flybase_plugin):
        """Test getting details for existing stock."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/details/flybase/80563")

        assert response.status_code == 200
        details = response.json()
        assert details["external_id"] == "80563"
        assert details["genotype"] == "w[*]; P{Gr21a-GAL80.1756}attP2"
        assert details["flybase_url"] is not None
        assert details["source_url"] is not None

    def test_get_details_with_repository_hint(self, client, mock_flybase_plugin):
        """Test getting details with repository hint."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/details/flybase/80563?repository=bdsc")

        assert response.status_code == 200
        mock_flybase_plugin.get_details.assert_called_with("80563", repository="bdsc")

    def test_get_details_nonexistent_stock(self, client, mock_flybase_plugin):
        """Test getting details for nonexistent stock."""
        mock_flybase_plugin.get_details = AsyncMock(return_value=None)

        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/details/flybase/99999999")

        assert response.status_code == 404

    def test_get_details_invalid_source(self, client):
        """Test getting details with invalid source."""
        response = client.get("/api/plugins/details/invalid/12345")

        assert response.status_code == 404


class TestStatsEndpoint:
    """Tests for /sources/{source}/stats endpoint."""

    def test_get_source_stats(self, client, mock_flybase_plugin):
        """Test getting source statistics."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/sources/flybase/stats")

        assert response.status_code == 200
        stats = response.json()
        assert stats["source_id"] == "flybase"
        assert stats["total_stocks"] == 188797
        assert stats["data_version"] == "FB2025_01"
        assert "repositories" in stats
        assert len(stats["repositories"]) > 0


class TestRepositoriesEndpoint:
    """Tests for /sources/{source}/repositories endpoint."""

    def test_list_repositories(self, client, mock_flybase_plugin):
        """Test listing repositories."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/sources/flybase/repositories")

        assert response.status_code == 200
        repos = response.json()
        assert len(repos) >= 3

        # Check structure
        assert all("id" in r for r in repos)
        assert all("name" in r for r in repos)
        assert all("count" in r for r in repos)


class TestImportEndpoint:
    """Tests for /import endpoint.

    Note: These tests are limited because the import endpoint requires
    database and authentication dependencies. Full integration tests
    should be done separately.
    """

    def test_import_requires_auth(self, client):
        """Test that import endpoint requires authentication.

        Note: This test verifies the endpoint exists but actual auth
        testing requires full app setup with auth dependencies.
        """
        # Without proper auth setup, this will fail with 401/422
        response = client.post(
            "/api/plugins/import", json={"stocks": [{"external_id": "80563", "source": "bdsc"}]}
        )

        # Should fail due to missing authentication
        assert response.status_code in [401, 422, 500]


class TestBackwardCompatibility:
    """Tests for backward compatibility with 'bdsc' source ID."""

    def test_bdsc_source_maps_to_flybase(self, client, mock_flybase_plugin):
        """Test that 'bdsc' source maps to flybase plugin."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/search?query=80563&source=bdsc")

        assert response.status_code == 200
        # Verify it searched with bdsc repository filter
        mock_flybase_plugin.search.assert_called_with("80563", limit=20, repository="bdsc")

    def test_vdrc_source_maps_to_flybase(self, client, mock_flybase_plugin):
        """Test that 'vdrc' source maps to flybase plugin."""
        with patch("app.plugins.router.get_flybase_plugin", return_value=mock_flybase_plugin):
            response = client.get("/api/plugins/search?query=v10004&source=vdrc")

        assert response.status_code == 200
        mock_flybase_plugin.search.assert_called_with("v10004", limit=20, repository="vdrc")
