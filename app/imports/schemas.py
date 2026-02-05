"""Pydantic schemas for enhanced import system."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Conflict Detection Schemas ---


class ConflictType(str, Enum):
    """Types of conflicts that can occur during import."""

    COALESCE_CONFLICT = "coalesce_conflict"  # Multiple columns have non-empty values for same field
    GENOTYPE_MISMATCH = "genotype_mismatch"  # Local genotype differs from repository genotype
    DUPLICATE_STOCK = "duplicate_stock"  # Stock ID already exists in database
    MISSING_REQUIRED = "missing_required"  # Required field empty even after coalesce
    VALIDATION_ERROR = "validation_error"  # Data format/validation issues
    LLM_FLAGGED = "llm_flagged"  # Future: LLM detected potential issue
    POTENTIAL_REPOSITORY_MATCH = "potential_repository_match"  # Non-repo stock matches a repository genotype


class RowConflict(BaseModel):
    """A single conflict detected in an import row.

    Attributes:
        conflict_type: The type of conflict.
        field: Which field has the conflict.
        values: Map of source_column -> value for conflicting values.
        message: Human-readable description of the conflict.
        remote_value: For genotype mismatch, the value from the repository.
        detector: Which detection system found this ("rule" or "llm").
        confidence: LLM confidence score (0-1) if applicable.
        suggestion: LLM suggested resolution if applicable.
        reasoning: LLM explanation for the conflict if applicable.
    """

    conflict_type: ConflictType
    field: str
    values: dict[str, str] = Field(default_factory=dict)
    message: str
    remote_value: Optional[str] = None
    detector: str = "rule"
    confidence: Optional[float] = None
    suggestion: Optional[str] = None
    reasoning: Optional[str] = None


class ConflictingRow(BaseModel):
    """A row with one or more conflicts that needs user resolution.

    Attributes:
        row_index: 1-based index of the row in the original file.
        original_row: The original row data from the file.
        transformed_row: The row after applying mappings (before conflict resolution).
        conflicts: List of conflicts detected in this row.
    """

    row_index: int
    original_row: dict = Field(default_factory=dict)
    transformed_row: dict = Field(default_factory=dict)
    conflicts: list[RowConflict] = Field(default_factory=list)


class ConflictResolution(BaseModel):
    """User's resolution for a conflicting row.

    Attributes:
        row_index: Which row this resolution applies to.
        action: The resolution action ("use_value", "skip", "manual").
        field_values: For "use_value"/"manual", the resolved field values.
    """

    row_index: int
    action: str  # "use_value", "skip", "manual"
    field_values: dict[str, str] = Field(default_factory=dict)


class ImportPhase1Result(BaseModel):
    """Result from phase 1 of import (clean rows imported, conflicts returned).

    Attributes:
        imported_count: Number of rows imported successfully.
        imported_stock_ids: List of stock IDs that were imported.
        conflicting_rows: Rows that have conflicts needing resolution.
        conflict_summary: Count of conflicts by type.
        session_id: Session ID for phase 2 (to retrieve conflicting data).
        trays_created: List of tray names that were auto-created.
        metadata_fetched: Number of stocks with metadata fetched.
    """

    imported_count: int = 0
    imported_stock_ids: list[str] = Field(default_factory=list)
    conflicting_rows: list[ConflictingRow] = Field(default_factory=list)
    conflict_summary: dict[str, int] = Field(default_factory=dict)
    session_id: str = ""
    trays_created: list[str] = Field(default_factory=list)
    metadata_fetched: int = 0


class ImportPhase2Request(BaseModel):
    """Request to complete phase 2 of import with user resolutions.

    Attributes:
        session_id: Session ID from phase 1.
        resolutions: User's resolutions for conflicting rows.
    """

    session_id: str
    resolutions: list[ConflictResolution] = Field(default_factory=list)


class ColumnMapping(BaseModel):
    """Mapping from original column to normalized field.

    Attributes:
        original: Original column name from file.
        mapped_to: Normalized field name (or None if unmapped).
        detected_type: What was auto-detected (e.g., "repository name").
    """

    original: str
    mapped_to: Optional[str] = None
    detected_type: Optional[str] = None


# --- Interactive Column Mapping Schemas (V2) ---


class ColumnInfo(BaseModel):
    """Info about a column from the uploaded file.

    Attributes:
        name: Original column name.
        sample_values: First 5 non-empty values from this column.
        auto_detected: Auto-detected mapping field name (if any).
    """

    name: str
    sample_values: list[str] = Field(default_factory=list)
    auto_detected: Optional[str] = None


class UserColumnMapping(BaseModel):
    """User-defined mapping for a column.

    Attributes:
        column_name: Original column name from file.
        target_field: Target field to map to. Use "custom" to store in metadata.
            None or empty string = ignore column.
        custom_key: Optional key name for metadata storage (when target_field="custom").
            If not provided, auto-generates from column name.
    """

    column_name: str
    target_field: Optional[str] = None
    custom_key: Optional[str] = None


class FieldGenerator(BaseModel):
    """Pattern for generating a field from other columns.

    Attributes:
        target_field: Target field to generate (e.g., "stock_id").
        pattern: Pattern with {ColumnName} placeholders.
    """

    target_field: str
    pattern: str


class ImportPreviewV2(BaseModel):
    """Enhanced preview with column info for interactive mapping.

    Attributes:
        columns: List of column info with sample values.
        available_fields: Fields that can be mapped to.
        required_fields: Fields that must be mapped or generated.
        total_rows: Total number of rows in the file.
        sample_rows: Raw sample data rows (first 10 for preview).
        can_import: Whether import can proceed (has required fields).
        validation_warnings: Warning messages.
        tray_column_mapped: Whether tray_name is in user's column mappings.
        stats: Import statistics (populated after user confirms mappings).
    """

    columns: list[ColumnInfo] = Field(default_factory=list)
    available_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    total_rows: int = 0
    sample_rows: list[dict] = Field(default_factory=list)
    can_import: bool = False
    validation_warnings: list[str] = Field(default_factory=list)
    tray_column_mapped: bool = False
    stats: Optional["ImportStats"] = None


class TrayResolution(BaseModel):
    """User's resolution for a tray name conflict.

    Attributes:
        tray_name: Original tray name from CSV.
        action: Resolution action - "use_existing", "create_new", or "skip".
        new_name: For "create_new" action, the new unique name to use.
    """

    tray_name: str
    action: str  # "use_existing", "create_new", "skip"
    new_name: Optional[str] = None


class ImportExecuteV2Request(BaseModel):
    """Execute request with user-defined mappings.

    Attributes:
        column_mappings: User-defined column mappings.
        field_generators: Patterns for generating fields.
        config: Import configuration options.
        tray_resolutions: User's resolutions for tray name conflicts.
    """

    column_mappings: list[UserColumnMapping] = Field(default_factory=list)
    field_generators: list[FieldGenerator] = Field(default_factory=list)
    config: "ImportConfig" = Field(default_factory=lambda: ImportConfig())
    tray_resolutions: list[TrayResolution] = Field(default_factory=list)


class ImportStats(BaseModel):
    """Statistics about import data.

    Attributes:
        total_rows: Total rows in file.
        repository_count: Number of repository stocks detected.
        internal_count: Number of internal stocks detected.
        external_count: Number of external stocks detected.
        repositories_detected: Map of repository names to counts.
        trays_to_create: List of tray names that will be auto-created.
        existing_trays: List of existing tray names found.
    """

    total_rows: int = 0
    repository_count: int = 0
    internal_count: int = 0
    external_count: int = 0
    repositories_detected: dict[str, int] = Field(default_factory=dict)
    trays_to_create: list[str] = Field(default_factory=list)
    existing_trays: list[str] = Field(default_factory=list)


class ImportPreview(BaseModel):
    """Preview response for import validation.

    Attributes:
        columns_detected: Map of original column name to normalized field.
        columns_unmapped: Columns that couldn't be mapped.
        sample_rows: First N rows for preview (normalized).
        raw_sample_rows: First N rows as read from file (original columns).
        stats: Import statistics.
        validation_warnings: List of warning messages.
        validation_errors: List of error messages for invalid rows.
        can_import: Whether import can proceed.
    """

    columns_detected: dict[str, str] = Field(default_factory=dict)
    columns_unmapped: list[str] = Field(default_factory=list)
    sample_rows: list[dict] = Field(default_factory=list)
    raw_sample_rows: list[dict] = Field(default_factory=list)
    stats: ImportStats = Field(default_factory=ImportStats)
    validation_warnings: list[str] = Field(default_factory=list)
    validation_errors: list[dict] = Field(default_factory=list)
    can_import: bool = False


class ImportConfig(BaseModel):
    """Configuration options for import execution.

    Attributes:
        fetch_metadata: Whether to fetch metadata for repository stocks.
        auto_create_trays: Whether to auto-create trays for unknown tray names.
        default_tray_type: Default type for auto-created trays.
        default_tray_max_positions: Default max positions for auto-created trays.
        column_overrides: Manual column mapping overrides.
    """

    fetch_metadata: bool = True
    auto_create_trays: bool = True
    default_tray_type: str = "numeric"
    default_tray_max_positions: int = 100
    column_overrides: dict[str, str] = Field(default_factory=dict)


class ImportExecuteRequest(BaseModel):
    """Request body for execute import.

    Attributes:
        config: Import configuration options.
    """

    config: ImportConfig = Field(default_factory=ImportConfig)


class ImportExecuteResult(BaseModel):
    """Result of import execution.

    Attributes:
        message: Summary message.
        imported_count: Number of stocks imported.
        stock_ids: List of imported stock IDs.
        trays_created: List of auto-created tray names.
        metadata_fetched: Number of stocks with metadata fetched.
        errors: List of row errors (if any skipped).
    """

    message: str
    imported_count: int = 0
    stock_ids: list[str] = Field(default_factory=list)
    trays_created: list[str] = Field(default_factory=list)
    metadata_fetched: int = 0
    errors: list[dict] = Field(default_factory=list)
