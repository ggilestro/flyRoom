"""Base plugin interface for external stock center integrations."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class StockImportData(BaseModel):
    """Data model for importing stocks from external sources.

    Attributes:
        external_id: ID in the external system.
        genotype: Genotype string.
        source: Source name.
        metadata: Additional metadata from external source.
    """

    external_id: str
    genotype: str
    source: str
    metadata: dict = {}


class StockPlugin(ABC):
    """Base class for external stock center integrations.

    Subclasses should implement search and get_details methods
    to enable importing stocks from external databases like BDSC.
    """

    name: str = "Base Plugin"
    source_id: str = "unknown"

    @abstractmethod
    async def search(self, query: str, limit: int = 20) -> list[StockImportData]:
        """Search for stocks in external database.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            list[StockImportData]: List of matching stocks.
        """
        pass

    @abstractmethod
    async def get_details(self, external_id: str) -> StockImportData | None:
        """Get detailed info for a specific stock.

        Args:
            external_id: ID in the external system.

        Returns:
            StockImportData | None: Stock data if found.
        """
        pass

    async def validate_connection(self) -> bool:
        """Validate connection to external service.

        Returns:
            bool: True if connection is valid.
        """
        return True
