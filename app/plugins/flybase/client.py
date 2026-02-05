"""FlyBase Stock Database plugin implementation.

Provides unified access to all stock centers available in FlyBase data:
- BDSC (Bloomington)
- VDRC (Vienna)
- Kyoto
- NIG-Fly
- KDRC
- FlyORF
- NDSSC
"""

import logging
import re
from pathlib import Path

from app.plugins.base import StockImportData, StockPlugin
from app.plugins.flybase.data_loader import (
    REPOSITORY_NAMES,
    FlyBaseDataLoader,
    get_flybase_url,
    get_repository_url,
)

logger = logging.getLogger(__name__)


class FlyBasePlugin(StockPlugin):
    """Plugin for FlyBase Stock Database integration.

    Provides unified access to all stock centers available in FlyBase data.
    Data is downloaded and cached locally, with automatic refresh.
    """

    name = "FlyBase Stock Database"
    source_id = "flybase"

    def __init__(self, data_dir: Path | None = None):
        """Initialize FlyBase plugin.

        Args:
            data_dir: Directory for storing cached data. Defaults to data/flybase.
        """
        self._data_loader = FlyBaseDataLoader(data_dir=data_dir or Path("data/flybase"))
        # Global index: "repo:stock_num" -> data
        self._global_index: dict[str, dict] = {}
        # Repository-specific index: repo -> {stock_num -> data}
        self._by_repository: dict[str, dict[str, dict]] = {}
        self._loaded = False
        self._data_version: str | None = None

    async def _ensure_loaded(self) -> None:
        """Ensure stock data is loaded into memory."""
        if self._loaded:
            return

        logger.info("Loading FlyBase stock data...")
        self._global_index, self._by_repository = await self._data_loader.load_all_stocks()
        self._loaded = True
        self._data_version = self._get_data_version()

        total = sum(len(stocks) for stocks in self._by_repository.values())
        logger.info(f"Loaded {total} stocks from {len(self._by_repository)} repositories")

    def _get_data_version(self) -> str:
        """Get the data version string from metadata file."""
        try:
            if self._data_loader.metadata_file.exists():
                content = self._data_loader.metadata_file.read_text()
                for line in content.split("\n"):
                    if line.startswith("url="):
                        match = re.search(r"FB(\d{4}_\d{2})", line)
                        if match:
                            return f"FB{match.group(1)}"
        except Exception:
            pass
        return "unknown"

    def _to_stock_import_data(self, stock_data: dict) -> StockImportData:
        """Convert internal stock data to StockImportData.

        Args:
            stock_data: Internal stock dictionary.

        Returns:
            StockImportData: Formatted stock data for import.
        """
        external_id = stock_data["external_id"]
        flybase_id = stock_data.get("flybase_id", "")
        repository = stock_data.get("repository", "bdsc")

        return StockImportData(
            external_id=external_id,
            genotype=stock_data.get("genotype", ""),
            source=repository,  # Use repository as source
            metadata={
                "flybase_id": flybase_id,
                "flybase_url": get_flybase_url(flybase_id) if flybase_id else None,
                "repository": repository,
                "repository_name": REPOSITORY_NAMES.get(repository, repository.upper()),
                "repository_url": get_repository_url(repository, external_id),
                "collection": stock_data.get("collection", ""),
                "species": stock_data.get("species", ""),
                "stock_type": stock_data.get("stock_type", ""),
                "original_description": stock_data.get("description", ""),
                "data_version": self._data_version,
            },
        )

    async def search(
        self, query: str, limit: int = 20, repository: str | None = None
    ) -> list[StockImportData]:
        """Search for stocks across all or specific repository.

        Searches by stock number (exact or prefix match) or genotype (substring).

        Args:
            query: Search query (stock number or genotype text).
            limit: Maximum number of results.
            repository: Optional repository ID to limit search (e.g., 'bdsc', 'vdrc').

        Returns:
            list[StockImportData]: List of matching stocks.
        """
        await self._ensure_loaded()

        if not query or not query.strip():
            return []

        query = query.strip()
        query_lower = query.lower()
        results: list[StockImportData] = []

        # Determine which repositories to search
        if repository:
            repos_to_search = {repository: self._by_repository.get(repository, {})}
        else:
            repos_to_search = self._by_repository

        # First pass: exact stock number match
        for _repo_id, repo_stocks in repos_to_search.items():
            if query in repo_stocks:
                results.append(self._to_stock_import_data(repo_stocks[query]))
                if len(results) >= limit:
                    return results

        # Second pass: stock number prefix match
        for repo_id, repo_stocks in repos_to_search.items():
            if len(results) >= limit:
                break
            for stock_id, data in repo_stocks.items():
                if len(results) >= limit:
                    break
                if stock_id.startswith(query) and stock_id != query:
                    # Skip if already in results
                    if not any(
                        r.external_id == stock_id and r.metadata.get("repository") == repo_id
                        for r in results
                    ):
                        results.append(self._to_stock_import_data(data))

        # Third pass: genotype substring match
        if len(results) < limit:
            for repo_id, repo_stocks in repos_to_search.items():
                if len(results) >= limit:
                    break
                for stock_id, data in repo_stocks.items():
                    if len(results) >= limit:
                        break
                    # Skip if already in results
                    if any(
                        r.external_id == stock_id and r.metadata.get("repository") == repo_id
                        for r in results
                    ):
                        continue
                    genotype = data.get("genotype", "").lower()
                    if query_lower in genotype:
                        results.append(self._to_stock_import_data(data))

        return results

    async def get_details(
        self, external_id: str, repository: str | None = None
    ) -> StockImportData | None:
        """Get detailed info for a stock.

        Args:
            external_id: Stock number.
            repository: Optional repository ID. If not provided, searches all.

        Returns:
            StockImportData | None: Stock data if found.
        """
        await self._ensure_loaded()

        # If repository specified, look there first
        if repository:
            repo_stocks = self._by_repository.get(repository, {})
            if external_id in repo_stocks:
                return self._to_stock_import_data(repo_stocks[external_id])
            return None

        # Otherwise, search all repositories
        for _repo_id, repo_stocks in self._by_repository.items():
            if external_id in repo_stocks:
                return self._to_stock_import_data(repo_stocks[external_id])

        return None

    def _normalize_genotype(self, genotype: str) -> str:
        """Normalize genotype for comparison.

        Args:
            genotype: Raw genotype string.

        Returns:
            Normalized genotype string for matching.
        """
        if not genotype:
            return ""
        # Lowercase, collapse whitespace, strip
        normalized = " ".join(genotype.lower().split())
        # Normalize common variations
        normalized = normalized.replace(";", ",")
        return normalized

    async def find_by_genotype(
        self, genotype: str, max_results: int = 5, repository: str | None = None
    ) -> list[StockImportData]:
        """Find stocks with matching genotype.

        Searches for exact (normalized) matches first, then partial matches.

        Args:
            genotype: Genotype to search for.
            max_results: Maximum number of results to return.
            repository: Optional repository ID to limit search.

        Returns:
            List of matching stocks, sorted by match quality.
        """
        await self._ensure_loaded()

        if not genotype or not genotype.strip():
            return []

        query_normalized = self._normalize_genotype(genotype)
        if not query_normalized:
            return []

        exact_matches = []
        partial_matches = []

        # Determine which repositories to search
        if repository:
            repos_to_search = {repository: self._by_repository.get(repository, {})}
        else:
            repos_to_search = self._by_repository

        for _repo_id, repo_stocks in repos_to_search.items():
            for _stock_id, data in repo_stocks.items():
                stock_genotype = data.get("genotype", "")
                if not stock_genotype:
                    continue

                stock_normalized = self._normalize_genotype(stock_genotype)

                # Exact match (normalized)
                if query_normalized == stock_normalized:
                    exact_matches.append(self._to_stock_import_data(data))
                    if len(exact_matches) >= max_results:
                        return exact_matches

                # Partial match
                elif len(partial_matches) < max_results and (
                    query_normalized in stock_normalized or stock_normalized in query_normalized
                ):
                    partial_matches.append(self._to_stock_import_data(data))

        # Return exact matches first, then partial matches
        results = exact_matches + partial_matches
        return results[:max_results]

    async def validate_connection(self) -> bool:
        """Validate that data can be loaded.

        Returns:
            bool: True if data can be loaded or is cached.
        """
        try:
            await self._ensure_loaded()
            return sum(len(s) for s in self._by_repository.values()) > 0
        except Exception as e:
            logger.error(f"FlyBase plugin validation failed: {e}")
            return False

    async def refresh_data(self) -> int:
        """Force refresh of stock data from FlyBase.

        Returns:
            int: Total number of stocks loaded.
        """
        logger.info("Forcing refresh of FlyBase stock data...")
        self._global_index, self._by_repository = await self._data_loader.load_all_stocks(
            force_refresh=True
        )
        self._loaded = True
        self._data_version = self._get_data_version()
        return sum(len(s) for s in self._by_repository.values())

    async def get_stats(self) -> dict:
        """Get plugin statistics.

        Returns:
            dict: Statistics about loaded data including per-repository counts.
        """
        await self._ensure_loaded()

        repo_stats = self._data_loader.get_repository_stats(self._by_repository)
        total = sum(len(s) for s in self._by_repository.values())

        return {
            "total_stocks": total,
            "data_version": self._data_version,
            "cache_valid": self._data_loader._is_cache_valid(),
            "repositories": repo_stats,
        }

    async def list_repositories(self) -> list[dict]:
        """List available repositories with their stock counts.

        Returns:
            list[dict]: Repository info with id, name, and count.
        """
        await self._ensure_loaded()
        return self._data_loader.get_repository_stats(self._by_repository)

    async def close(self) -> None:
        """Close the plugin and release resources."""
        await self._data_loader.close()
        self._global_index.clear()
        self._by_repository.clear()
        self._loaded = False


# Singleton instance for the plugin
_plugin_instance: FlyBasePlugin | None = None


def get_flybase_plugin() -> FlyBasePlugin:
    """Get the singleton FlyBase plugin instance.

    Returns:
        FlyBasePlugin: The plugin instance.
    """
    global _plugin_instance
    if _plugin_instance is None:
        _plugin_instance = FlyBasePlugin()
    return _plugin_instance


# Backward compatibility alias
def get_bdsc_plugin() -> FlyBasePlugin:
    """Get the FlyBase plugin (backward compatibility alias).

    Returns:
        FlyBasePlugin: The plugin instance.
    """
    return get_flybase_plugin()


# Backward compatibility alias
BDSCPlugin = FlyBasePlugin
