"""Pydantic schemas for backup/restore functionality."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConflictMode(str, Enum):
    """How to handle conflicting records during import."""

    FAIL = "fail"  # Stop import on first conflict
    SKIP = "skip"  # Skip conflicting records
    OVERWRITE = "overwrite"  # Overwrite existing records


class ExportMetadata(BaseModel):
    """Metadata embedded in backup files."""

    schema_version: str = Field(description="Database schema version (alembic revision)")
    export_version: str = Field(default="1.0", description="Backup format version")
    exported_at: datetime = Field(description="When the export was created")
    tenant_id: str = Field(description="ID of the exported tenant")
    tenant_name: str = Field(description="Name of the exported tenant")
    record_counts: dict[str, int] = Field(
        default_factory=dict, description="Count of records per table"
    )


class BackupFile(BaseModel):
    """Complete backup file structure."""

    metadata: ExportMetadata
    data: dict[str, list[dict[str, Any]]] = Field(description="Table name -> list of records")


class ImportRequest(BaseModel):
    """Request body for import endpoint."""

    conflict_mode: ConflictMode = Field(
        default=ConflictMode.FAIL, description="How to handle conflicting records"
    )
    dry_run: bool = Field(default=False, description="Validate without importing")


class ValidationIssue(BaseModel):
    """A single validation issue found during import validation."""

    table: str = Field(description="Table name")
    record_id: str | None = Field(default=None, description="Record ID if applicable")
    issue_type: str = Field(description="Type of issue (conflict, missing_ref, etc.)")
    message: str = Field(description="Human-readable issue description")


class ValidationResult(BaseModel):
    """Result of backup file validation."""

    is_valid: bool = Field(description="Whether the file can be imported")
    schema_version: str = Field(description="Schema version in backup file")
    current_schema_version: str = Field(description="Current database schema version")
    schema_compatible: bool = Field(description="Whether schemas are compatible")
    record_counts: dict[str, int] = Field(
        default_factory=dict, description="Count of records per table"
    )
    conflicts: list[ValidationIssue] = Field(
        default_factory=list, description="Conflicting records found"
    )
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings")
    errors: list[str] = Field(default_factory=list, description="Fatal errors preventing import")


class ImportResult(BaseModel):
    """Result of an import operation."""

    success: bool = Field(description="Whether import completed successfully")
    dry_run: bool = Field(description="Whether this was a dry run")
    records_imported: dict[str, int] = Field(
        default_factory=dict, description="Count of records imported per table"
    )
    records_skipped: dict[str, int] = Field(
        default_factory=dict, description="Count of records skipped per table"
    )
    records_overwritten: dict[str, int] = Field(
        default_factory=dict, description="Count of records overwritten per table"
    )
    errors: list[str] = Field(default_factory=list, description="Errors encountered during import")
    warnings: list[str] = Field(default_factory=list, description="Warnings during import")
