"""Tests for the FlyBase plugin client with multi-repository support."""

from pathlib import Path

import pytest

from app.plugins.base import StockImportData
from app.plugins.flybase.client import FlyBasePlugin, get_bdsc_plugin

# Sample stock index for testing with multiple repositories
SAMPLE_BY_REPOSITORY = {
    "bdsc": {
        "80563": {
            "external_id": "80563",
            "flybase_id": "FBst0080563",
            "genotype": "w[*]; P{Gr21a-GAL80.1756}attP2",
            "description": "w[*]; P{y[+t7.7] w[+mC]=Gr21a-GAL80.1756}attP2",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Bloomington",
            "repository": "bdsc",
        },
        "1": {
            "external_id": "1",
            "flybase_id": "FBst0000001",
            "genotype": "y[1] w[67c23]",
            "description": "y[1] w[67c23]",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Bloomington",
            "repository": "bdsc",
        },
        "99999": {
            "external_id": "99999",
            "flybase_id": "FBst0099999",
            "genotype": "OreR",
            "description": "Oregon-R",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Bloomington",
            "repository": "bdsc",
        },
    },
    "vdrc": {
        "v10004": {
            "external_id": "v10004",
            "flybase_id": "FBst0100001",
            "genotype": "w[1118]; P{GD14516}v10004",
            "description": "w[1118]; P{GD14516}v10004",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Vienna",
            "repository": "vdrc",
        },
        "v20001": {
            "external_id": "v20001",
            "flybase_id": "FBst0100002",
            "genotype": "w[1118]; P{GD1234}v20001",
            "description": "w[1118]; P{GD1234}v20001",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Vienna",
            "repository": "vdrc",
        },
    },
    "kyoto": {
        "101001": {
            "external_id": "101001",
            "flybase_id": "FBst0200001",
            "genotype": "y[1] cv[1] v[1] f[1]",
            "description": "y[1] cv[1] v[1] f[1]",
            "species": "Dmel",
            "stock_type": "living stock",
            "collection": "Kyoto",
            "repository": "kyoto",
        },
    },
}

# Build global index from repository index
SAMPLE_GLOBAL_INDEX = {}
for repo_id, stocks in SAMPLE_BY_REPOSITORY.items():
    for stock_num, data in stocks.items():
        SAMPLE_GLOBAL_INDEX[f"{repo_id}:{stock_num}"] = data


@pytest.fixture
def flybase_plugin(tmp_path: Path) -> FlyBasePlugin:
    """Create a FlyBase plugin instance with test data."""
    plugin = FlyBasePlugin(data_dir=tmp_path)
    # Pre-populate the indices to avoid network calls
    plugin._global_index = SAMPLE_GLOBAL_INDEX.copy()
    plugin._by_repository = {repo: stocks.copy() for repo, stocks in SAMPLE_BY_REPOSITORY.items()}
    plugin._loaded = True
    plugin._data_version = "FB2025_01"
    return plugin


class TestFlyBasePluginSearch:
    """Tests for FlyBase plugin search functionality."""

    @pytest.mark.asyncio
    async def test_search_exact_stock_number_bdsc(self, flybase_plugin: FlyBasePlugin):
        """Test searching by exact BDSC stock number."""
        results = await flybase_plugin.search("80563")

        assert len(results) == 1
        assert results[0].external_id == "80563"
        assert results[0].source == "bdsc"
        assert "Gr21a" in results[0].genotype

    @pytest.mark.asyncio
    async def test_search_exact_stock_number_vdrc(self, flybase_plugin: FlyBasePlugin):
        """Test searching by exact VDRC stock number."""
        results = await flybase_plugin.search("v10004")

        assert len(results) == 1
        assert results[0].external_id == "v10004"
        assert results[0].source == "vdrc"

    @pytest.mark.asyncio
    async def test_search_all_repositories(self, flybase_plugin: FlyBasePlugin):
        """Test searching across all repositories."""
        results = await flybase_plugin.search("w[1118]")

        # Should find VDRC stocks with w[1118]
        assert len(results) >= 2
        sources = {r.source for r in results}
        assert "vdrc" in sources

    @pytest.mark.asyncio
    async def test_search_specific_repository(self, flybase_plugin: FlyBasePlugin):
        """Test searching within a specific repository."""
        results = await flybase_plugin.search("w", repository="vdrc")

        # Should only find VDRC stocks
        for r in results:
            assert r.source == "vdrc"

    @pytest.mark.asyncio
    async def test_search_stock_number_prefix(self, flybase_plugin: FlyBasePlugin):
        """Test searching by stock number prefix."""
        results = await flybase_plugin.search("9999")

        assert len(results) == 1
        assert results[0].external_id == "99999"

    @pytest.mark.asyncio
    async def test_search_genotype_substring(self, flybase_plugin: FlyBasePlugin):
        """Test searching by genotype substring."""
        results = await flybase_plugin.search("Gr21a")

        assert len(results) == 1
        assert results[0].external_id == "80563"

    @pytest.mark.asyncio
    async def test_search_case_insensitive_genotype(self, flybase_plugin: FlyBasePlugin):
        """Test case-insensitive genotype search."""
        results = await flybase_plugin.search("orer")  # lowercase

        assert len(results) == 1
        assert results[0].external_id == "99999"

    @pytest.mark.asyncio
    async def test_search_no_results(self, flybase_plugin: FlyBasePlugin):
        """Test search with no matches."""
        results = await flybase_plugin.search("nonexistent")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_empty_query(self, flybase_plugin: FlyBasePlugin):
        """Test search with empty query."""
        results = await flybase_plugin.search("")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, flybase_plugin: FlyBasePlugin):
        """Test that search respects the limit parameter."""
        # Add more stocks to the index
        for i in range(100, 150):
            flybase_plugin._by_repository["bdsc"][str(i)] = {
                "external_id": str(i),
                "flybase_id": f"FBst{i:07d}",
                "genotype": f"test genotype {i}",
                "species": "Dmel",
                "collection": "Bloomington",
                "repository": "bdsc",
            }

        results = await flybase_plugin.search("test genotype", limit=5)

        assert len(results) <= 5


class TestFlyBasePluginGetDetails:
    """Tests for FlyBase plugin get_details functionality."""

    @pytest.mark.asyncio
    async def test_get_details_existing_stock_bdsc(self, flybase_plugin: FlyBasePlugin):
        """Test getting details for an existing BDSC stock."""
        result = await flybase_plugin.get_details("80563")

        assert result is not None
        assert result.external_id == "80563"
        assert result.genotype == "w[*]; P{Gr21a-GAL80.1756}attP2"
        assert result.source == "bdsc"
        assert result.metadata["flybase_id"] == "FBst0080563"
        assert result.metadata["repository"] == "bdsc"
        assert "flybase.org" in result.metadata["flybase_url"]
        assert "bdsc.indiana.edu" in result.metadata["repository_url"]

    @pytest.mark.asyncio
    async def test_get_details_existing_stock_vdrc(self, flybase_plugin: FlyBasePlugin):
        """Test getting details for an existing VDRC stock."""
        result = await flybase_plugin.get_details("v10004")

        assert result is not None
        assert result.external_id == "v10004"
        assert result.source == "vdrc"
        assert result.metadata["repository"] == "vdrc"
        assert "vdrc.at" in result.metadata["repository_url"]

    @pytest.mark.asyncio
    async def test_get_details_with_repository_hint(self, flybase_plugin: FlyBasePlugin):
        """Test getting details with repository hint."""
        result = await flybase_plugin.get_details("v10004", repository="vdrc")

        assert result is not None
        assert result.source == "vdrc"

    @pytest.mark.asyncio
    async def test_get_details_nonexistent_stock(self, flybase_plugin: FlyBasePlugin):
        """Test getting details for a nonexistent stock."""
        result = await flybase_plugin.get_details("99999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_details_wrong_repository(self, flybase_plugin: FlyBasePlugin):
        """Test getting details with wrong repository returns None."""
        result = await flybase_plugin.get_details("80563", repository="vdrc")

        assert result is None


class TestFlyBasePluginMetadata:
    """Tests for FlyBase plugin metadata handling."""

    @pytest.mark.asyncio
    async def test_metadata_contains_required_fields(self, flybase_plugin: FlyBasePlugin):
        """Test that metadata contains all required fields."""
        result = await flybase_plugin.get_details("80563")

        assert result is not None
        metadata = result.metadata

        assert "flybase_id" in metadata
        assert "flybase_url" in metadata
        assert "repository" in metadata
        assert "repository_name" in metadata
        assert "repository_url" in metadata
        assert "species" in metadata
        assert "data_version" in metadata

    @pytest.mark.asyncio
    async def test_get_stats(self, flybase_plugin: FlyBasePlugin):
        """Test getting plugin statistics."""
        stats = await flybase_plugin.get_stats()

        assert stats["total_stocks"] == 6  # 3 BDSC + 2 VDRC + 1 Kyoto
        assert stats["data_version"] == "FB2025_01"
        assert "repositories" in stats
        assert len(stats["repositories"]) > 0

    @pytest.mark.asyncio
    async def test_list_repositories(self, flybase_plugin: FlyBasePlugin):
        """Test listing available repositories."""
        repos = await flybase_plugin.list_repositories()

        assert len(repos) > 0
        # Find BDSC
        bdsc = next((r for r in repos if r["id"] == "bdsc"), None)
        assert bdsc is not None
        assert bdsc["count"] == 3


class TestFlyBasePluginValidation:
    """Tests for FlyBase plugin validation."""

    @pytest.mark.asyncio
    async def test_validate_connection_with_data(self, flybase_plugin: FlyBasePlugin):
        """Test validation when data is loaded."""
        result = await flybase_plugin.validate_connection()

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_connection_empty_index(self, flybase_plugin: FlyBasePlugin):
        """Test validation with empty index."""
        flybase_plugin._by_repository = {}

        result = await flybase_plugin.validate_connection()

        assert result is False


class TestFlyBasePluginFindByGenotype:
    """Tests for find_by_genotype functionality."""

    @pytest.mark.asyncio
    async def test_find_by_genotype_exact_match(self, flybase_plugin: FlyBasePlugin):
        """Test finding by exact genotype."""
        results = await flybase_plugin.find_by_genotype("OreR")

        assert len(results) >= 1
        assert any(r.external_id == "99999" for r in results)

    @pytest.mark.asyncio
    async def test_find_by_genotype_partial_match(self, flybase_plugin: FlyBasePlugin):
        """Test finding by partial genotype match."""
        results = await flybase_plugin.find_by_genotype("w[1118]")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_find_by_genotype_specific_repository(self, flybase_plugin: FlyBasePlugin):
        """Test finding by genotype in specific repository."""
        results = await flybase_plugin.find_by_genotype("w[1118]", repository="vdrc")

        for r in results:
            assert r.source == "vdrc"


class TestStockImportDataFormat:
    """Tests for StockImportData format."""

    @pytest.mark.asyncio
    async def test_stock_import_data_is_valid_pydantic(self, flybase_plugin: FlyBasePlugin):
        """Test that returned data is valid StockImportData."""
        result = await flybase_plugin.get_details("80563")

        assert isinstance(result, StockImportData)
        # Test serialization works
        data_dict = result.model_dump()
        assert "external_id" in data_dict
        assert "genotype" in data_dict
        assert "source" in data_dict
        assert "metadata" in data_dict


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_get_bdsc_plugin_alias(self):
        """Test that get_bdsc_plugin returns FlyBasePlugin."""
        # Reset singleton for testing
        import app.plugins.flybase.client as client_module

        client_module._plugin_instance = None

        plugin = get_bdsc_plugin()
        assert isinstance(plugin, FlyBasePlugin)

    def test_flybase_plugin_attributes(self, flybase_plugin: FlyBasePlugin):
        """Test FlyBasePlugin has expected attributes."""
        assert flybase_plugin.name == "FlyBase Stock Database"
        assert flybase_plugin.source_id == "flybase"
