"""Tests for the FlyBase data loader with multi-repository support."""

import gzip
from pathlib import Path

import pytest

from app.plugins.flybase.data_loader import (
    COLLECTION_TO_REPOSITORY,
    REPOSITORY_NAMES,
    FlyBaseDataLoader,
    get_bdsc_search_url,
    get_flybase_url,
    get_repository_url,
)

# Sample TSV data that mimics FlyBase format with multiple collections
SAMPLE_TSV_HEADER = (
    "FBst\tcollection_short_name\tstock_type_cv\tspecies\tFB_genotype\tdescription\tstock_number"
)
SAMPLE_TSV_ROWS = [
    # BDSC stocks
    "FBst0080563\tBloomington\tliving stock ; FBsv:0000002\tDmel\tw[*]; P{Gr21a-GAL80.1756}attP2\tw[*]; P{y[+t7.7] w[+mC]=Gr21a-GAL80.1756}attP2\t80563",
    "FBst0000001\tBloomington\tliving stock ; FBsv:0000002\tDmel\ty[1] w[67c23]\ty[1] w[67c23]\t1",
    "FBst0099999\tBloomington\tliving stock ; FBsv:0000002\tDmel\tOreR\tOregon-R\t99999",
    # VDRC stocks
    "FBst0100001\tVienna\tliving stock ; FBsv:0000002\tDmel\tw[1118]; P{GD14516}v10004\tw[1118]; P{GD14516}v10004\tv10004",
    "FBst0100002\tVienna\tliving stock ; FBsv:0000002\tDmel\tw[1118]; P{GD1234}v20001\tw[1118]; P{GD1234}v20001\tv20001",
    # Kyoto stock
    "FBst0200001\tKyoto\tliving stock ; FBsv:0000002\tDmel\ty[1] cv[1] v[1] f[1]\ty[1] cv[1] v[1] f[1]\t101001",
    # Unknown collection (should be filtered out)
    "FBst0300001\tUnknown\tliving stock ; FBsv:0000002\tDmel\tsome genotype\tsome description\t999999",
]


@pytest.fixture
def sample_tsv_file(tmp_path: Path) -> Path:
    """Create a sample gzipped TSV file with multiple collections."""
    tsv_content = SAMPLE_TSV_HEADER + "\n" + "\n".join(SAMPLE_TSV_ROWS)
    tsv_path = tmp_path / "test_stocks.tsv.gz"

    with gzip.open(tsv_path, "wt", encoding="utf-8") as f:
        f.write(tsv_content)

    return tsv_path


@pytest.fixture
def data_loader(tmp_path: Path) -> FlyBaseDataLoader:
    """Create a data loader with temporary directory."""
    return FlyBaseDataLoader(data_dir=tmp_path)


class TestFlyBaseDataLoader:
    """Tests for FlyBaseDataLoader class."""

    def test_parse_stocks_tsv(self, data_loader: FlyBaseDataLoader, sample_tsv_file: Path):
        """Test parsing a TSV file."""
        rows = list(data_loader.parse_stocks_tsv(sample_tsv_file))

        assert len(rows) == 7
        assert rows[0]["FBst"] == "FBst0080563"
        assert rows[0]["stock_number"] == "80563"
        assert rows[0]["collection_short_name"] == "Bloomington"

    def test_filter_stocks_all_supported(
        self, data_loader: FlyBaseDataLoader, sample_tsv_file: Path
    ):
        """Test filtering to only supported collections."""
        raw_stocks = data_loader.parse_stocks_tsv(sample_tsv_file)
        filtered_stocks = list(data_loader.filter_stocks_by_collection(raw_stocks))

        # Should filter out the Unknown collection
        assert len(filtered_stocks) == 6
        collections = {s["collection_short_name"] for s in filtered_stocks}
        assert "Unknown" not in collections
        assert "Bloomington" in collections
        assert "Vienna" in collections
        assert "Kyoto" in collections

    def test_filter_stocks_specific_collection(
        self, data_loader: FlyBaseDataLoader, sample_tsv_file: Path
    ):
        """Test filtering to a specific collection."""
        raw_stocks = data_loader.parse_stocks_tsv(sample_tsv_file)
        vdrc_stocks = list(data_loader.filter_stocks_by_collection(raw_stocks, collection="Vienna"))

        assert len(vdrc_stocks) == 2
        for stock in vdrc_stocks:
            assert stock["collection_short_name"] == "Vienna"

    def test_transform_stock_record(self, data_loader: FlyBaseDataLoader):
        """Test transforming a TSV row to internal format with repository info."""
        row = {
            "stock_number": "80563",
            "FBst": "FBst0080563",
            "FB_genotype": "w[*]; P{Gr21a-GAL80.1756}attP2",
            "description": "w[*]; P{y[+t7.7] w[+mC]=Gr21a-GAL80.1756}attP2",
            "species": "Dmel",
            "stock_type_cv": "living stock ; FBsv:0000002",
            "collection_short_name": "Bloomington",
        }

        result = data_loader.transform_stock_record(row)

        assert result["external_id"] == "80563"
        assert result["flybase_id"] == "FBst0080563"
        assert result["genotype"] == "w[*]; P{Gr21a-GAL80.1756}attP2"
        assert result["species"] == "Dmel"
        assert result["collection"] == "Bloomington"
        assert result["repository"] == "bdsc"

    def test_transform_stock_record_vdrc(self, data_loader: FlyBaseDataLoader):
        """Test transforming a VDRC stock record."""
        row = {
            "stock_number": "v10004",
            "FBst": "FBst0100001",
            "FB_genotype": "w[1118]; P{GD14516}v10004",
            "description": "w[1118]; P{GD14516}v10004",
            "species": "Dmel",
            "stock_type_cv": "living stock ; FBsv:0000002",
            "collection_short_name": "Vienna",
        }

        result = data_loader.transform_stock_record(row)

        assert result["external_id"] == "v10004"
        assert result["collection"] == "Vienna"
        assert result["repository"] == "vdrc"

    def test_transform_stock_record_fallback_genotype(self, data_loader: FlyBaseDataLoader):
        """Test that description is used when FB_genotype is empty."""
        row = {
            "stock_number": "1",
            "FBst": "FBst0000001",
            "FB_genotype": "",
            "description": "y[1] w[67c23]",
            "species": "Dmel",
            "stock_type_cv": "living stock",
            "collection_short_name": "Bloomington",
        }

        result = data_loader.transform_stock_record(row)

        assert result["genotype"] == "y[1] w[67c23]"

    def test_build_stock_index(self, data_loader: FlyBaseDataLoader, sample_tsv_file: Path):
        """Test building indices from parsed stocks."""
        raw_stocks = data_loader.parse_stocks_tsv(sample_tsv_file)
        filtered_stocks = data_loader.filter_stocks_by_collection(raw_stocks)
        global_index, by_repository = data_loader.build_stock_index(filtered_stocks)

        # Check repository index
        assert "bdsc" in by_repository
        assert "vdrc" in by_repository
        assert "kyoto" in by_repository
        assert len(by_repository["bdsc"]) == 3
        assert len(by_repository["vdrc"]) == 2
        assert len(by_repository["kyoto"]) == 1

        # Check specific stocks
        assert "80563" in by_repository["bdsc"]
        assert "v10004" in by_repository["vdrc"]
        assert "101001" in by_repository["kyoto"]

        # Check data structure
        assert by_repository["bdsc"]["80563"]["external_id"] == "80563"
        assert by_repository["bdsc"]["80563"]["repository"] == "bdsc"
        assert by_repository["vdrc"]["v10004"]["repository"] == "vdrc"

    def test_get_repository_stats(self, data_loader: FlyBaseDataLoader, sample_tsv_file: Path):
        """Test getting repository statistics."""
        raw_stocks = data_loader.parse_stocks_tsv(sample_tsv_file)
        filtered_stocks = data_loader.filter_stocks_by_collection(raw_stocks)
        _, by_repository = data_loader.build_stock_index(filtered_stocks)

        stats = data_loader.get_repository_stats(by_repository)

        # Should be sorted by count descending
        assert stats[0]["id"] == "bdsc"
        assert stats[0]["count"] == 3

        # Find VDRC in stats
        vdrc_stats = next((s for s in stats if s["id"] == "vdrc"), None)
        assert vdrc_stats is not None
        assert vdrc_stats["count"] == 2
        assert vdrc_stats["name"] == "Vienna Drosophila Resource Center"

    def test_cache_file_path(self, data_loader: FlyBaseDataLoader, tmp_path: Path):
        """Test cache file path property."""
        assert data_loader.cache_file == tmp_path / "flybase_stocks.tsv.gz"

    def test_is_cache_valid_no_file(self, data_loader: FlyBaseDataLoader):
        """Test cache validity when no file exists."""
        assert data_loader._is_cache_valid() is False


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_flybase_url(self):
        """Test FlyBase URL generation."""
        url = get_flybase_url("FBst0080563")
        assert url == "https://flybase.org/reports/FBst0080563"

    def test_get_repository_url_bdsc(self):
        """Test BDSC URL generation."""
        url = get_repository_url("bdsc", "80563")
        assert "bdsc.indiana.edu" in url
        assert "80563" in url

    def test_get_repository_url_vdrc(self):
        """Test VDRC URL generation."""
        url = get_repository_url("vdrc", "10004")
        assert "vdrc.at" in url
        assert "10004" in url

    def test_get_repository_url_kyoto(self):
        """Test Kyoto URL generation."""
        url = get_repository_url("kyoto", "101001")
        assert "kyotofly" in url
        assert "101001" in url

    def test_get_repository_url_unknown(self):
        """Test URL generation for unknown repository falls back to FlyBase."""
        url = get_repository_url("unknown", "12345")
        assert "flybase.org" in url
        assert "12345" in url

    def test_get_bdsc_search_url_backward_compat(self):
        """Test backward compatibility BDSC search URL."""
        url = get_bdsc_search_url("80563")
        assert "bdsc.indiana.edu" in url
        assert "80563" in url


class TestCollectionMappings:
    """Tests for collection to repository mappings."""

    def test_collection_to_repository_mapping(self):
        """Test that all expected collections are mapped."""
        expected = {
            "Bloomington": "bdsc",
            "Vienna": "vdrc",
            "Kyoto": "kyoto",
            "NIG-Fly": "nig",
            "KDRC": "kdrc",
            "FlyORF": "flyorf",
            "NDSSC": "ndssc",
        }

        for collection, repo in expected.items():
            assert COLLECTION_TO_REPOSITORY.get(collection) == repo

    def test_repository_names(self):
        """Test that all repositories have full names."""
        expected_repos = ["bdsc", "vdrc", "kyoto", "nig", "kdrc", "flyorf", "ndssc"]

        for repo in expected_repos:
            assert repo in REPOSITORY_NAMES
            assert len(REPOSITORY_NAMES[repo]) > 0
