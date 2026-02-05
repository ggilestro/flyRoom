"""Imports module for CSV/Excel import."""

from app.imports.conflict_detectors import (
    CompositeDetector,
    ConflictDetector,
    DetectionContext,
    RuleBasedDetector,
    get_conflict_detector,
)
from app.imports.parsers import (
    REPOSITORY_ALIASES,
    infer_origin,
    normalize_repository,
    parse_csv,
    parse_excel,
    parse_tags,
    validate_import_data,
)
from app.imports.router import router
from app.imports.schemas import (
    ConflictingRow,
    ConflictResolution,
    ConflictType,
    ImportConfig,
    ImportExecuteRequest,
    ImportExecuteResult,
    ImportPhase1Result,
    ImportPhase2Request,
    ImportPreview,
    ImportStats,
    RowConflict,
)

__all__ = [
    "router",
    "parse_csv",
    "parse_excel",
    "validate_import_data",
    "normalize_repository",
    "infer_origin",
    "parse_tags",
    "REPOSITORY_ALIASES",
    "ImportPreview",
    "ImportStats",
    "ImportConfig",
    "ImportExecuteRequest",
    "ImportExecuteResult",
    # Conflict detection
    "ConflictType",
    "RowConflict",
    "ConflictingRow",
    "ConflictResolution",
    "ImportPhase1Result",
    "ImportPhase2Request",
    "DetectionContext",
    "ConflictDetector",
    "RuleBasedDetector",
    "CompositeDetector",
    "get_conflict_detector",
]
