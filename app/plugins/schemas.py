"""Pydantic schemas for plugins API."""

from datetime import datetime

from pydantic import BaseModel, Field


class ExternalStockResult(BaseModel):
    """External stock search result.

    Attributes:
        external_id: ID in the external system (e.g., BDSC stock number).
        genotype: Full genotype string.
        source: Source identifier (e.g., "bdsc").
        metadata: Additional metadata from external source.
    """

    external_id: str
    genotype: str
    source: str
    metadata: dict = Field(default_factory=dict)


class ExternalStockDetails(BaseModel):
    """Detailed info about an external stock.

    Attributes:
        external_id: ID in the external system.
        genotype: Full genotype string.
        source: Source identifier.
        metadata: Additional metadata from external source.
        flybase_url: Link to FlyBase report page.
        source_url: Link to original source page.
    """

    external_id: str
    genotype: str
    source: str
    metadata: dict = Field(default_factory=dict)
    flybase_url: str | None = None
    source_url: str | None = None


class ExternalStockImportItem(BaseModel):
    """Single stock to import from external source.

    Attributes:
        external_id: ID in the external system.
        source: Source identifier.
        stock_id: Optional custom stock ID. If not provided, uses external_id.
        location: Optional location for the imported stock.
        notes: Optional notes for the imported stock.
    """

    external_id: str
    source: str
    stock_id: str | None = None
    location: str | None = None
    notes: str | None = None


class ImportFromExternalRequest(BaseModel):
    """Request to import stocks from external source.

    Attributes:
        stocks: List of stocks to import.
    """

    stocks: list[ExternalStockImportItem]


class ImportFromExternalResult(BaseModel):
    """Result of importing stocks from external source.

    Attributes:
        imported: Number of stocks successfully imported.
        skipped: Number of stocks skipped (e.g., already exist).
        errors: List of error messages for failed imports.
        imported_ids: List of IDs for successfully imported stocks.
    """

    imported: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    imported_ids: list[str] = Field(default_factory=list)


class RepositoryInfo(BaseModel):
    """Information about a stock repository.

    Attributes:
        id: Repository identifier (e.g., 'bdsc', 'vdrc').
        name: Human-readable name.
        count: Number of stocks available.
    """

    id: str
    name: str
    count: int = 0


class PluginSourceInfo(BaseModel):
    """Information about an available plugin source.

    Attributes:
        source_id: Unique identifier for the source.
        name: Human-readable name.
        description: Brief description of the source.
        available: Whether the source is available/connected.
        repositories: List of available repositories (for FlyBase).
    """

    source_id: str
    name: str
    description: str | None = None
    available: bool = True
    repositories: list[RepositoryInfo] = Field(default_factory=list)


class PluginStatsResponse(BaseModel):
    """Statistics for a plugin source.

    Attributes:
        source_id: Source identifier.
        total_stocks: Number of stocks available.
        data_version: Version of the loaded data.
        cache_valid: Whether cached data is still valid.
        last_updated: When data was last updated.
        repositories: Per-repository stock counts.
    """

    source_id: str
    total_stocks: int = 0
    data_version: str | None = None
    cache_valid: bool = False
    last_updated: datetime | None = None
    repositories: list[RepositoryInfo] = Field(default_factory=list)
