"""Extensible conflict detection system for import.

This module provides a pluggable architecture for detecting conflicts
during stock import. It supports rule-based detection now and is designed
to accommodate LLM-based detection in the future.

Example usage:
    detector = get_conflict_detector()
    conflicts = await detector.detect_all(rows, context)
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.imports.schemas import ConflictingRow, ConflictType, RowConflict


@dataclass
class RepositoryMatch:
    """A potential match from a repository.

    Attributes:
        repository: Repository name (e.g., "bdsc").
        stock_id: Repository stock ID.
        genotype: Repository genotype.
        metadata: Additional metadata.
    """

    repository: str
    stock_id: str
    genotype: str
    metadata: dict = field(default_factory=dict)


@dataclass
class DetectionContext:
    """Context passed to all detectors.

    Attributes:
        existing_stock_ids: Set of stock IDs already in the database.
        column_mappings: User-defined column mappings.
        remote_metadata: Map of repository_stock_id -> fetched metadata.
        all_rows: All rows for cross-row analysis (e.g., duplicate detection).
        coalesce_fields: Fields that have multiple columns mapped (coalesce).
        repository_matches: Map of row_index -> list of potential repository matches.
    """

    existing_stock_ids: set[str] = field(default_factory=set)
    column_mappings: list[dict] = field(default_factory=list)
    remote_metadata: dict[str, dict] = field(default_factory=dict)
    all_rows: list[dict] = field(default_factory=list)
    coalesce_fields: list[str] = field(default_factory=list)
    repository_matches: dict[int, list[RepositoryMatch]] = field(default_factory=dict)


class ConflictDetector(Protocol):
    """Protocol for conflict detection strategies.

    Implementations must provide a detect method that analyzes a single row
    and returns a list of detected conflicts.
    """

    async def detect(
        self,
        row: dict,
        row_index: int,
        context: DetectionContext,
    ) -> list[RowConflict]:
        """Detect conflicts in a single row.

        Args:
            row: The transformed row data.
            row_index: 1-based index of the row.
            context: Detection context with additional data.

        Returns:
            List of detected conflicts (empty if no conflicts).
        """
        ...


class RuleBasedDetector:
    """Rule-based conflict detection using deterministic rules.

    Detects:
    - Coalesce conflicts (multiple non-empty values for same field)
    - Genotype mismatches (local vs remote)
    - Duplicate stock IDs
    - Missing required fields
    - Validation errors
    """

    async def detect(
        self,
        row: dict,
        row_index: int,
        context: DetectionContext,
    ) -> list[RowConflict]:
        """Detect conflicts using rule-based logic."""
        conflicts = []

        # Check for coalesce conflicts (already detected in apply_user_mappings)
        conflicts.extend(self._check_coalesce_conflicts(row, row_index))

        # Check for genotype mismatch with remote data
        conflicts.extend(self._check_genotype_mismatch(row, row_index, context))

        # Check for duplicate stock IDs
        conflicts.extend(self._check_duplicate_stock(row, row_index, context))

        # Check for missing required fields
        conflicts.extend(self._check_missing_required(row, row_index))

        # Check for potential repository matches (non-repo stocks)
        conflicts.extend(self._check_repository_matches(row, row_index, context))

        return conflicts

    def _check_coalesce_conflicts(self, row: dict, row_index: int) -> list[RowConflict]:
        """Check for coalesce conflicts (multiple values for same field)."""
        conflicts = []

        # Coalesce conflicts are tracked in _coalesce_conflicts by apply_user_mappings
        coalesce_conflicts = row.get("_coalesce_conflicts", [])
        for conflict_data in coalesce_conflicts:
            field_name = conflict_data.get("field", "unknown")
            columns = conflict_data.get("columns", {})

            conflicts.append(
                RowConflict(
                    conflict_type=ConflictType.COALESCE_CONFLICT,
                    field=field_name,
                    values=columns,
                    message=f"Multiple values found for '{field_name}': " f"choose which to use",
                    detector="rule",
                )
            )

        return conflicts

    def _check_genotype_mismatch(
        self, row: dict, row_index: int, context: DetectionContext
    ) -> list[RowConflict]:
        """Check if local genotype differs from repository genotype."""
        conflicts = []

        repo_stock_id = row.get("repository_stock_id")
        local_genotype = row.get("genotype")

        if not repo_stock_id or not local_genotype:
            return conflicts

        # Check if we have remote metadata for this stock
        remote_data = context.remote_metadata.get(repo_stock_id)
        if not remote_data:
            return conflicts

        remote_genotype = remote_data.get("genotype") or remote_data.get("FB_genotype")
        if not remote_genotype:
            return conflicts

        # Compare genotypes (case-insensitive, whitespace-normalized)
        local_normalized = " ".join(local_genotype.lower().split())
        remote_normalized = " ".join(remote_genotype.lower().split())

        if local_normalized != remote_normalized:
            conflicts.append(
                RowConflict(
                    conflict_type=ConflictType.GENOTYPE_MISMATCH,
                    field="genotype",
                    values={"local": local_genotype},
                    remote_value=remote_genotype,
                    message=f"Genotype differs from repository data for " f"stock {repo_stock_id}",
                    detector="rule",
                )
            )

        return conflicts

    def _check_duplicate_stock(
        self, row: dict, row_index: int, context: DetectionContext
    ) -> list[RowConflict]:
        """Check if stock ID already exists in database."""
        conflicts = []

        stock_id = row.get("stock_id")
        if not stock_id:
            return conflicts

        if stock_id in context.existing_stock_ids:
            conflicts.append(
                RowConflict(
                    conflict_type=ConflictType.DUPLICATE_STOCK,
                    field="stock_id",
                    values={"stock_id": stock_id},
                    message=f"Stock ID '{stock_id}' already exists in database",
                    detector="rule",
                )
            )

        return conflicts

    def _check_missing_required(self, row: dict, row_index: int) -> list[RowConflict]:
        """Check for missing required fields."""
        conflicts = []

        # Must have either repository_stock_id OR genotype
        has_repo_id = bool(row.get("repository_stock_id"))
        has_genotype = bool(row.get("genotype"))

        if not has_repo_id and not has_genotype:
            conflicts.append(
                RowConflict(
                    conflict_type=ConflictType.MISSING_REQUIRED,
                    field="genotype/repository_stock_id",
                    values={},
                    message="Row must have either a repository stock ID or a genotype",
                    detector="rule",
                )
            )

        return conflicts

    def _check_repository_matches(
        self, row: dict, row_index: int, context: DetectionContext
    ) -> list[RowConflict]:
        """Check if non-repository stock matches a repository genotype."""
        conflicts = []

        # Only check stocks not already marked as repository
        origin = row.get("origin", "").lower()
        if origin == "repository":
            return conflicts

        # Check if we already have a repository_stock_id (already identified as repo)
        if row.get("repository_stock_id"):
            return conflicts

        # Check if we have pre-fetched matches for this row
        matches = context.repository_matches.get(row_index, [])
        if not matches:
            return conflicts

        # Report the matches as a potential conflict
        # Take the best match (first one, which should be exact match if exists)
        best_match = matches[0]

        conflicts.append(
            RowConflict(
                conflict_type=ConflictType.POTENTIAL_REPOSITORY_MATCH,
                field="origin",
                values={
                    "repository": best_match.repository.upper(),
                    "repository_stock_id": best_match.stock_id,
                    "match_genotype": best_match.genotype,
                },
                remote_value=best_match.genotype,
                message=f"Genotype matches {best_match.repository.upper()} stock #{best_match.stock_id}. "
                f"Consider converting to repository stock.",
                detector="rule",
                suggestion=f"Convert to {best_match.repository.upper()} #{best_match.stock_id}",
            )
        )

        return conflicts


class LLMDetector:
    """Future: LLM-powered conflict detection.

    This detector will use an LLM to:
    - Perform fuzzy genotype matching (understand notation differences)
    - Detect semantic duplicates (functionally identical stocks)
    - Suggest resolutions with confidence scores and reasoning
    - Flag data quality issues

    Currently a placeholder that returns no conflicts.
    """

    def __init__(self, client: object | None = None):
        """Initialize LLM detector.

        Args:
            client: LLM client (e.g., Anthropic client). None for now.
        """
        self.client = client

    async def detect(
        self,
        row: dict,
        row_index: int,
        context: DetectionContext,
    ) -> list[RowConflict]:
        """Detect conflicts using LLM analysis.

        Currently returns empty list - to be implemented when LLM
        integration is added.
        """
        # Future implementation:
        # - Fuzzy genotype matching
        # - Semantic duplicate detection
        # - Data quality assessment
        # - Smart resolution suggestions with confidence scores
        return []


class CompositeDetector:
    """Combines multiple detectors into a single detection pipeline.

    Runs all registered detectors and aggregates their results.
    Conflicts from different detectors are combined per row.
    """

    def __init__(self, detectors: list[ConflictDetector]):
        """Initialize with list of detectors.

        Args:
            detectors: List of detector instances to run.
        """
        self.detectors = detectors

    async def detect(
        self,
        row: dict,
        row_index: int,
        context: DetectionContext,
    ) -> list[RowConflict]:
        """Run all detectors and combine results."""
        all_conflicts = []
        for detector in self.detectors:
            conflicts = await detector.detect(row, row_index, context)
            all_conflicts.extend(conflicts)
        return all_conflicts

    async def detect_all(
        self,
        rows: list[dict],
        context: DetectionContext,
    ) -> list[ConflictingRow]:
        """Detect conflicts in all rows.

        Args:
            rows: List of transformed row dictionaries.
            context: Detection context.

        Returns:
            List of ConflictingRow for rows that have conflicts.
        """
        conflicting_rows = []

        for i, row in enumerate(rows, start=1):
            conflicts = await self.detect(row, i, context)
            if conflicts:
                conflicting_rows.append(
                    ConflictingRow(
                        row_index=i,
                        original_row=row.get("_original_row", row),
                        transformed_row=row,
                        conflicts=conflicts,
                    )
                )

        return conflicting_rows


def get_conflict_detector(enable_llm: bool = False) -> CompositeDetector:
    """Factory function to create the conflict detector.

    This is the main entry point for getting a conflict detector.
    Easy to extend later to add LLM detection.

    Args:
        enable_llm: Whether to enable LLM-based detection (future).

    Returns:
        CompositeDetector configured with appropriate detectors.
    """
    detectors: list[ConflictDetector] = [RuleBasedDetector()]

    # Future: Add LLM detector if enabled
    # if enable_llm:
    #     from app.config import settings
    #     if settings.llm_api_key:
    #         detectors.append(LLMDetector(client=get_llm_client()))

    return CompositeDetector(detectors)
