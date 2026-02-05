"""FlyBase stock data loader for multi-repository support.

Downloads and parses bulk stock data from FlyBase for fast local lookup.
Supports all stock centers available in FlyBase data.
"""

import csv
import gzip
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# FlyBase data URL pattern
FLYBASE_STOCKS_BASE_URL = "https://s3ftp.flybase.org/releases/current/precomputed_files/stocks/"
FLYBASE_STOCKS_FILENAME_PATTERN = re.compile(r"stocks_FB\d{4}_\d{2}\.tsv\.gz")

# Default cache settings
DEFAULT_DATA_DIR = Path("data/flybase")
DEFAULT_CACHE_MAX_AGE = timedelta(days=30)

# Collection to repository ID mapping
COLLECTION_TO_REPOSITORY = {
    "Bloomington": "bdsc",
    "Vienna": "vdrc",
    "Kyoto": "kyoto",
    "NIG-Fly": "nig",
    "KDRC": "kdrc",
    "FlyORF": "flyorf",
    "NDSSC": "ndssc",
}

# Repository full names
REPOSITORY_NAMES = {
    "bdsc": "Bloomington Drosophila Stock Center",
    "vdrc": "Vienna Drosophila Resource Center",
    "kyoto": "Kyoto Stock Center",
    "nig": "NIG-Fly Stock Center",
    "kdrc": "Korean Drosophila Resource Center",
    "flyorf": "FlyORF",
    "ndssc": "National Drosophila Species Stock Center",
}

# Repository URLs for stock lookup
REPOSITORY_URLS = {
    "bdsc": "https://bdsc.indiana.edu/Home/Search?presearch={stock_number}",
    "vdrc": "https://stockcenter.vdrc.at/control/product/~VIEW_INDEX=vdrc_catalog_view_index/~VIEW_SIZE=10/~product_id={stock_number}",
    "kyoto": "https://kyotofly.kit.jp/cgi-bin/stocks/search_res_det.cgi?DB_NUM=1&DESSION={stock_number}",
    "nig": "https://shigen.nig.ac.jp/fly/nigfly/stock?STOCK_ID={stock_number}",
    "kdrc": "https://kdrc.cnu.ac.kr/stock/view/{stock_number}",
    "flyorf": "https://www.flyorf.ch/stocks/{stock_number}",
    "ndssc": "https://www.drosophila-speciesstock.com/stock/{stock_number}",
}


class FlyBaseDataLoader:
    """Loads and caches stock data from FlyBase bulk files.

    Supports multiple stock center collections from FlyBase data.

    Attributes:
        data_dir: Directory for storing cached data files.
        cache_max_age: Maximum age of cached data before refresh.
    """

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        cache_max_age: timedelta = DEFAULT_CACHE_MAX_AGE,
    ):
        """Initialize the data loader.

        Args:
            data_dir: Directory for storing cached data files.
            cache_max_age: Maximum age of cached data before refresh.
        """
        self.data_dir = Path(data_dir)
        self.cache_max_age = cache_max_age
        self._http_client: httpx.AsyncClient | None = None

    @property
    def cache_file(self) -> Path:
        """Path to the cached gzipped TSV file."""
        return self.data_dir / "flybase_stocks.tsv.gz"

    @property
    def metadata_file(self) -> Path:
        """Path to cache metadata file."""
        return self.data_dir / "cache_metadata.txt"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _is_cache_valid(self) -> bool:
        """Check if cached data is still valid.

        Returns:
            bool: True if cache exists and is within max age.
        """
        if not self.cache_file.exists():
            return False

        try:
            cache_mtime = datetime.fromtimestamp(self.cache_file.stat().st_mtime)
            cache_age = datetime.now() - cache_mtime
            return cache_age < self.cache_max_age
        except OSError:
            return False

    async def _find_stocks_file_url(self) -> str:
        """Find the current stocks file URL from FlyBase.

        Returns:
            str: URL to the stocks TSV.gz file.

        Raises:
            RuntimeError: If file URL cannot be determined.
        """
        client = await self._get_client()

        try:
            # Try to fetch directory listing
            response = await client.get(FLYBASE_STOCKS_BASE_URL)
            if response.status_code == 200:
                # Parse HTML for .tsv.gz links
                content = response.text
                matches = FLYBASE_STOCKS_FILENAME_PATTERN.findall(content)
                if matches:
                    # Use the most recent file (last in sorted order)
                    latest_file = sorted(matches)[-1]
                    return f"{FLYBASE_STOCKS_BASE_URL}{latest_file}"
        except httpx.HTTPError as e:
            logger.warning(f"Could not fetch FlyBase directory listing: {e}")

        # Fallback: Try common release patterns
        current_year = datetime.now().year
        for month in range(12, 0, -1):
            for year in [current_year, current_year - 1]:
                filename = f"stocks_FB{year}_{month:02d}.tsv.gz"
                url = f"{FLYBASE_STOCKS_BASE_URL}{filename}"
                try:
                    response = await client.head(url)
                    if response.status_code == 200:
                        return url
                except httpx.HTTPError:
                    continue

        raise RuntimeError("Could not find FlyBase stocks file URL")

    async def download_stocks_file(self, force: bool = False) -> Path:
        """Download the stocks TSV file from FlyBase.

        Args:
            force: Force download even if cache is valid.

        Returns:
            Path: Path to the downloaded file.

        Raises:
            RuntimeError: If download fails.
        """
        if not force and self._is_cache_valid():
            logger.info("Using cached FlyBase data")
            return self.cache_file

        self._ensure_data_dir()
        client = await self._get_client()

        url = await self._find_stocks_file_url()
        logger.info(f"Downloading FlyBase stocks from {url}")

        try:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Write to cache file
            self.cache_file.write_bytes(response.content)

            # Save metadata
            self.metadata_file.write_text(f"url={url}\ndownloaded={datetime.now().isoformat()}")

            logger.info(f"Downloaded {len(response.content)} bytes to {self.cache_file}")
            return self.cache_file

        except httpx.HTTPError as e:
            raise RuntimeError(f"Failed to download FlyBase stocks: {e}") from e

    def parse_stocks_tsv(self, path: Path | None = None) -> Iterator[dict]:
        """Parse the gzipped TSV file and yield stock records.

        Args:
            path: Path to the TSV.gz file. Uses cache_file if not specified.

        Yields:
            dict: Stock data dictionaries.
        """
        if path is None:
            path = self.cache_file

        if not path.exists():
            raise FileNotFoundError(f"Stocks file not found: {path}")

        with gzip.open(path, "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            yield from reader

    def filter_stocks_by_collection(
        self, stocks: Iterator[dict], collection: str | None = None
    ) -> Iterator[dict]:
        """Filter stock records by collection name.

        Args:
            stocks: Iterator of stock dictionaries.
            collection: Collection name to filter by. If None, include all
                collections defined in COLLECTION_TO_REPOSITORY.

        Yields:
            dict: Filtered stock data.
        """
        valid_collections = set(COLLECTION_TO_REPOSITORY.keys())

        for stock in stocks:
            stock_collection = stock.get("collection_short_name", "")
            if stock_collection not in valid_collections:
                continue
            if collection is None or stock_collection == collection:
                yield stock

    def transform_stock_record(self, row: dict) -> dict:
        """Transform a FlyBase TSV row into our internal format.

        Args:
            row: Raw row from TSV file.

        Returns:
            dict: Transformed stock data with repository info.
        """
        stock_number = row.get("stock_number", "").strip()
        flybase_id = row.get("FBst", "").strip()
        collection = row.get("collection_short_name", "").strip()

        # Map collection to repository ID
        repository = COLLECTION_TO_REPOSITORY.get(collection, "other")

        # Use FB_genotype if available, fall back to description
        genotype = row.get("FB_genotype", "").strip()
        if not genotype:
            genotype = row.get("description", "").strip()

        return {
            "external_id": stock_number,
            "flybase_id": flybase_id,
            "genotype": genotype,
            "description": row.get("description", "").strip(),
            "species": row.get("species", "").strip(),
            "stock_type": row.get("stock_type_cv", "").strip(),
            "collection": collection,
            "repository": repository,
        }

    def build_stock_index(
        self, stocks: Iterator[dict]
    ) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
        """Build indices of stocks by stock number and repository.

        Args:
            stocks: Iterator of stock dictionaries.

        Returns:
            tuple: (global_index, by_repository_index)
                - global_index: stock_number -> stock_data
                - by_repository_index: repository -> {stock_number -> stock_data}
        """
        global_index: dict[str, dict] = {}
        by_repository: dict[str, dict[str, dict]] = {}

        for stock in stocks:
            transformed = self.transform_stock_record(stock)
            stock_number = transformed.get("external_id")
            repository = transformed.get("repository", "other")

            if not stock_number:
                continue

            # Add to global index with repository prefix for uniqueness
            # e.g., "bdsc:80563" or for VDRC "vdrc:v10004"
            global_key = f"{repository}:{stock_number}"
            global_index[global_key] = transformed

            # Add to repository-specific index
            if repository not in by_repository:
                by_repository[repository] = {}
            by_repository[repository][stock_number] = transformed

        return global_index, by_repository

    async def load_all_stocks(
        self, force_refresh: bool = False
    ) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
        """Load and index all stocks from all supported collections.

        This is the main entry point for loading stock data.

        Args:
            force_refresh: Force download of fresh data.

        Returns:
            tuple: (global_index, by_repository_index)
        """
        await self.download_stocks_file(force=force_refresh)

        # Parse and filter to supported collections
        raw_stocks = self.parse_stocks_tsv()
        filtered_stocks = self.filter_stocks_by_collection(raw_stocks)

        # Build indices
        return self.build_stock_index(filtered_stocks)

    async def load_bdsc_stocks(self, force_refresh: bool = False) -> dict[str, dict]:
        """Load and index only BDSC stocks (backward compatibility).

        Args:
            force_refresh: Force download of fresh data.

        Returns:
            dict: Stock number -> stock data mapping for BDSC only.
        """
        _, by_repository = await self.load_all_stocks(force_refresh)
        return by_repository.get("bdsc", {})

    def get_repository_stats(self, by_repository: dict[str, dict[str, dict]]) -> list[dict]:
        """Get statistics for each repository.

        Args:
            by_repository: Repository index from build_stock_index.

        Returns:
            list[dict]: List of repository stats with id, name, and count.
        """
        stats = []
        for repo_id in COLLECTION_TO_REPOSITORY.values():
            repo_stocks = by_repository.get(repo_id, {})
            stats.append(
                {
                    "id": repo_id,
                    "name": REPOSITORY_NAMES.get(repo_id, repo_id.upper()),
                    "count": len(repo_stocks),
                }
            )
        # Sort by count descending
        stats.sort(key=lambda x: x["count"], reverse=True)
        return stats


def get_flybase_url(flybase_id: str) -> str:
    """Generate FlyBase report URL.

    Args:
        flybase_id: FlyBase stock ID (e.g., FBst0080563).

    Returns:
        str: FlyBase report URL.
    """
    return f"https://flybase.org/reports/{flybase_id}"


def get_repository_url(repository: str, stock_number: str) -> str:
    """Generate repository-specific stock URL.

    Args:
        repository: Repository ID (e.g., 'bdsc', 'vdrc').
        stock_number: Stock number.

    Returns:
        str: Repository-specific stock URL.
    """
    url_template = REPOSITORY_URLS.get(repository)
    if url_template:
        return url_template.format(stock_number=stock_number)
    # Fallback to FlyBase search
    return f"https://flybase.org/search/stocks/{stock_number}"


# Backward compatibility alias
def get_bdsc_search_url(stock_number: str) -> str:
    """Generate BDSC search URL (backward compatibility).

    Args:
        stock_number: BDSC stock number.

    Returns:
        str: BDSC search URL.
    """
    return get_repository_url("bdsc", stock_number)
