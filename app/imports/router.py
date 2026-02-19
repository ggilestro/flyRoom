"""Imports API routes."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.models import (
    ADMIN_ROLES,
    Stock,
    StockOrigin,
    StockRepository,
    Tag,
    Tray,
    TrayType,
)
from app.dependencies import CurrentTenantId, CurrentUser, get_db
from app.imports.conflict_detectors import (
    DetectionContext,
    RepositoryMatch,
    get_conflict_detector,
)
from app.imports.parsers import (
    AVAILABLE_FIELDS,
    REQUIRED_FIELDS_ONE_OF,
    ImportResult,
    apply_field_generators,
    apply_user_mappings,
    build_column_mapping,
    generate_csv_template,
    generate_stock_id,
    get_column_info,
    normalize_repository,
    normalize_rows,
    parse_csv,
    parse_csv_raw,
    parse_excel,
    parse_excel_raw,
    parse_tags,
    validate_import_data,
    validate_required_fields,
)
from app.imports.schemas import (
    ColumnInfo,
    ImportConfig,
    ImportExecuteResult,
    ImportPhase1Result,
    ImportPreview,
    ImportPreviewV2,
    ImportStats,
    TrayResolution,
)
from app.stocks.service import StockService

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Session Storage for Two-Phase Import ---
# In-memory storage with TTL for conflicting rows between phase 1 and phase 2.
# For production multi-instance deployments, consider using Redis instead.

_import_sessions: dict[str, dict] = {}
_SESSION_TTL_MINUTES = 30


def _create_import_session(
    tenant_id: str,
    conflicting_rows: list[dict],
    config: ImportConfig,
    column_mappings: list[dict],
) -> str:
    """Create a new import session for phase 2.

    Args:
        tenant_id: The tenant ID.
        conflicting_rows: Rows that need conflict resolution.
        config: Import configuration.
        column_mappings: User column mappings.

    Returns:
        Session ID.
    """
    session_id = str(uuid.uuid4())
    _import_sessions[session_id] = {
        "tenant_id": tenant_id,
        "conflicting_rows": conflicting_rows,
        "config": config.model_dump(),
        "column_mappings": column_mappings,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=_SESSION_TTL_MINUTES),
    }
    _cleanup_expired_sessions()
    return session_id


def _get_import_session(session_id: str, tenant_id: str) -> dict | None:
    """Get an import session by ID.

    Args:
        session_id: The session ID.
        tenant_id: The tenant ID (for security check).

    Returns:
        Session data or None if not found/expired/wrong tenant.
    """
    _cleanup_expired_sessions()
    session = _import_sessions.get(session_id)
    if not session:
        return None
    if session["tenant_id"] != tenant_id:
        return None
    if datetime.utcnow() > session["expires_at"]:
        del _import_sessions[session_id]
        return None
    return session


def _delete_import_session(session_id: str) -> None:
    """Delete an import session."""
    _import_sessions.pop(session_id, None)


def _cleanup_expired_sessions() -> None:
    """Remove expired sessions."""
    now = datetime.utcnow()
    expired = [sid for sid, data in _import_sessions.items() if now > data["expires_at"]]
    for sid in expired:
        del _import_sessions[sid]


def _parse_file_raw(file: UploadFile) -> tuple[list[str], list[dict]]:
    """Parse uploaded file into raw columns and rows.

    Args:
        file: Uploaded file.

    Returns:
        tuple: (columns, raw_rows).

    Raises:
        HTTPException: If file format is unsupported.
    """
    filename = file.filename or ""
    if filename.endswith(".csv"):
        return parse_csv_raw(file.file)
    elif filename.endswith((".xlsx", ".xls")):
        return parse_excel_raw(file.file)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Use CSV or Excel (.xlsx)",
        )


def _compute_stats(rows: list[dict], tenant_id: str, db: Session) -> ImportStats:
    """Compute import statistics from normalized rows.

    Args:
        rows: Normalized row dictionaries.
        tenant_id: Tenant ID.
        db: Database session.

    Returns:
        ImportStats: Computed statistics.
    """
    stats = ImportStats(total_rows=len(rows))

    # Count origins and repositories
    repo_counts: dict[str, int] = {}
    tray_names: set[str] = set()

    for row in rows:
        origin = row.get("origin", "internal")
        if origin == "repository":
            stats.repository_count += 1
            repo = row.get("repository", "unknown")
            repo_counts[repo] = repo_counts.get(repo, 0) + 1
        elif origin == "external":
            stats.external_count += 1
        else:
            stats.internal_count += 1

        # Collect tray names
        tray_name = row.get("tray_name")
        if tray_name:
            tray_names.add(tray_name)

    stats.repositories_detected = repo_counts

    # Check which trays exist
    if tray_names:
        existing_trays = (
            db.query(Tray.name).filter(Tray.tenant_id == tenant_id, Tray.name.in_(tray_names)).all()
        )
        existing_names = {t.name for t in existing_trays}
        stats.existing_trays = sorted(existing_names)
        stats.trays_to_create = sorted(tray_names - existing_names)

    return stats


@router.get("/template")
async def download_template(template_type: str = "basic"):
    """Download CSV import template.

    Args:
        template_type: Type of template (basic, repository, full).

    Returns:
        Response: CSV file.
    """
    if template_type not in ("basic", "repository", "full"):
        template_type = "basic"

    content = generate_csv_template(template_type)
    filename = f"flyroom_import_template_{template_type}.csv"

    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/preview")
async def preview_import(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> ImportPreview:
    """Preview import file with column detection and validation.

    Parses the file, detects column mappings, normalizes data,
    and returns a preview with statistics.

    Args:
        file: Uploaded CSV or Excel file.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        ImportPreview: Preview with column mappings and sample data.
    """
    # Parse raw data
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        return ImportPreview(
            validation_warnings=["File is empty or has no data rows"],
            can_import=False,
        )

    # Build column mapping
    column_map, unmapped = build_column_mapping(columns)

    # Normalize rows
    normalized_rows = normalize_rows(raw_rows, column_map)

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_ids = {s.stock_id for s in existing}

    # Validate
    validation = validate_import_data(normalized_rows, existing_ids)

    # Compute statistics
    stats = _compute_stats(validation.valid_rows, str(tenant_id), db)

    # Build warnings
    warnings = []
    if unmapped:
        warnings.append(f"Unmapped columns (will be ignored): {', '.join(unmapped)}")
    if "stock_id" not in column_map.values():
        warnings.append("No 'stock_id' column detected - required for import")
    if "genotype" not in column_map.values():
        warnings.append("No 'genotype' column detected - required for import")
    if stats.trays_to_create:
        warnings.append(
            f"Will auto-create {len(stats.trays_to_create)} new tray(s): {', '.join(stats.trays_to_create)}"
        )

    # Can import if we have valid rows and required columns
    can_import = (
        validation.valid_count > 0
        and "stock_id" in column_map.values()
        and "genotype" in column_map.values()
    )

    return ImportPreview(
        columns_detected=column_map,
        columns_unmapped=unmapped,
        sample_rows=normalized_rows[:5],
        raw_sample_rows=raw_rows[:5],
        stats=stats,
        validation_warnings=warnings,
        validation_errors=validation.errors[:10],  # First 10 errors
        can_import=can_import,
    )


@router.post("/validate")
async def validate_import(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> ImportResult:
    """Validate import file without importing.

    Args:
        file: Uploaded CSV or Excel file.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        ImportResult: Validation results.

    Raises:
        HTTPException: If file format is not supported.
    """
    # Determine file type
    filename = file.filename or ""
    if filename.endswith(".csv"):
        rows = parse_csv(file.file)
    elif filename.endswith((".xlsx", ".xls")):
        rows = parse_excel(file.file)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Use CSV or Excel (.xlsx)",
        )

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_ids = {s.stock_id for s in existing}

    # Validate
    return validate_import_data(rows, existing_ids)


async def _fetch_repository_metadata(
    repository_stock_id: str, repository: str | None = None
) -> dict | None:
    """Fetch metadata from FlyBase plugin.

    Args:
        repository_stock_id: Stock number.
        repository: Optional repository hint (e.g., 'bdsc', 'vdrc').

    Returns:
        dict | None: Metadata dict including genotype if found.
    """
    try:
        from app.plugins.flybase.client import get_flybase_plugin

        plugin = get_flybase_plugin()
        stock_data = await plugin.get_details(repository_stock_id, repository=repository)
        if stock_data:
            # Combine top-level fields with metadata for conflict detection
            # The genotype is at the top level, not inside metadata
            result = dict(stock_data.metadata) if stock_data.metadata else {}
            result["genotype"] = stock_data.genotype
            return result
    except Exception as e:
        logger.warning(f"Failed to fetch metadata for {repository_stock_id}: {e}")
    return None


# Backward compatibility alias
async def _fetch_bdsc_metadata(repository_stock_id: str) -> dict | None:
    """Fetch metadata from BDSC (backward compatibility).

    Args:
        repository_stock_id: BDSC stock number.

    Returns:
        dict | None: Metadata dict including genotype if found.
    """
    return await _fetch_repository_metadata(repository_stock_id, repository="bdsc")


async def _find_repository_matches(genotype: str) -> list[RepositoryMatch]:
    """Search all repositories for matching genotypes.

    Args:
        genotype: Genotype to search for.

    Returns:
        List of RepositoryMatch objects.
    """
    matches = []

    try:
        from app.plugins.flybase.client import get_flybase_plugin

        plugin = get_flybase_plugin()
        # Search across all repositories
        all_matches = await plugin.find_by_genotype(genotype, max_results=5)
        for stock_data in all_matches:
            matches.append(
                RepositoryMatch(
                    repository=stock_data.metadata.get("repository", "unknown"),
                    stock_id=stock_data.external_id,
                    genotype=stock_data.genotype,
                    metadata=stock_data.metadata or {},
                )
            )
    except Exception as e:
        logger.warning(f"Failed to search repositories for genotype matches: {e}")

    return matches


def _get_or_create_tray(
    db: Session,
    tenant_id: str,
    tray_name: str,
    config: ImportConfig,
    created_trays: dict[str, Tray],
    tray_resolutions: dict[str, TrayResolution] | None = None,
    tray_column_mapped: bool = True,
) -> Tray | None:
    """Get existing tray or create a new one, respecting user resolutions.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        tray_name: Tray name.
        config: Import configuration.
        created_trays: Cache of already-created trays.
        tray_resolutions: User's resolutions for tray conflicts (tray_name -> resolution).
        tray_column_mapped: Whether tray_name was explicitly mapped by user.

    Returns:
        Tray | None: Tray object or None if skipped/can't create.
    """
    # If tray column wasn't explicitly mapped, don't auto-create trays
    if not tray_column_mapped:
        return None

    # Check cache first
    if tray_name in created_trays:
        return created_trays[tray_name]

    # Check if there's a resolution for this tray
    resolution = tray_resolutions.get(tray_name) if tray_resolutions else None

    # Check database for existing tray
    existing_tray = (
        db.query(Tray).filter(Tray.tenant_id == tenant_id, Tray.name == tray_name).first()
    )

    if existing_tray:
        # Tray exists - handle according to resolution
        if resolution:
            if resolution.action == "skip":
                # Don't assign to any tray
                return None
            elif resolution.action == "create_new" and resolution.new_name:
                # Create a new tray with the specified name instead
                return _create_new_tray(db, tenant_id, resolution.new_name, config, created_trays)
            # Default: use_existing - fall through to return existing
        created_trays[tray_name] = existing_tray
        return existing_tray

    # Tray doesn't exist - create if allowed
    if not config.auto_create_trays:
        return None

    return _create_new_tray(db, tenant_id, tray_name, config, created_trays)


def _create_new_tray(
    db: Session,
    tenant_id: str,
    tray_name: str,
    config: ImportConfig,
    created_trays: dict[str, Tray],
) -> Tray:
    """Create a new tray with the given name.

    Args:
        db: Database session.
        tenant_id: Tenant ID.
        tray_name: Tray name.
        config: Import configuration.
        created_trays: Cache of already-created trays.

    Returns:
        Tray: The created tray.
    """
    # Check cache first (in case we already created it with this name)
    if tray_name in created_trays:
        return created_trays[tray_name]

    tray_type = TrayType.NUMERIC
    if config.default_tray_type == "grid":
        tray_type = TrayType.GRID
    elif config.default_tray_type == "custom":
        tray_type = TrayType.CUSTOM

    tray = Tray(
        tenant_id=tenant_id,
        name=tray_name,
        tray_type=tray_type,
        max_positions=config.default_tray_max_positions,
    )
    db.add(tray)
    db.flush()  # Get ID without full commit

    created_trays[tray_name] = tray
    return tray


def _parse_origin(origin_str: str | None) -> StockOrigin:
    """Parse origin string to enum.

    Args:
        origin_str: Origin string.

    Returns:
        StockOrigin: Parsed enum value.
    """
    if not origin_str:
        return StockOrigin.INTERNAL

    origin_lower = origin_str.lower()
    if origin_lower == "repository":
        return StockOrigin.REPOSITORY
    elif origin_lower == "external":
        return StockOrigin.EXTERNAL
    return StockOrigin.INTERNAL


def _parse_repository(repo_str: str | None) -> StockRepository | None:
    """Parse repository string to enum.

    Args:
        repo_str: Repository string.

    Returns:
        StockRepository | None: Parsed enum value or None.
    """
    if not repo_str:
        return None

    normalized = normalize_repository(repo_str)
    if not normalized:
        return None

    # Map to enum
    try:
        return StockRepository(normalized)
    except ValueError:
        return StockRepository.OTHER


@router.post("/execute")
async def execute_import(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
    fetch_metadata: bool = Form(True),
    auto_create_trays: bool = Form(True),
) -> ImportExecuteResult:
    """Import stocks from file.

    Args:
        file: Uploaded CSV or Excel file.
        db: Database session.
        current_user: Current user.
        tenant_id: Current tenant ID.
        fetch_metadata: Whether to fetch metadata for repository stocks.
        auto_create_trays: Whether to auto-create trays.

    Returns:
        ImportExecuteResult: Import results.

    Raises:
        HTTPException: If file format is not supported or validation fails.
    """
    config = ImportConfig(
        fetch_metadata=fetch_metadata,
        auto_create_trays=auto_create_trays,
    )

    # Parse file
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows in file",
        )

    # Build mapping and normalize
    column_map, _ = build_column_mapping(columns)
    rows = normalize_rows(raw_rows, column_map)

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_ids = {s.stock_id for s in existing}

    # Validate
    result = validate_import_data(rows, existing_ids)

    if result.valid_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "No valid rows to import",
                "errors": result.errors[:20],
            },
        )

    # Get existing tags for the tenant
    existing_tags = {
        t.name.lower(): t for t in db.query(Tag).filter(Tag.tenant_id == str(tenant_id)).all()
    }

    # Tray cache
    created_trays: dict[str, Tray] = {}
    trays_created_names: list[str] = []

    # Import valid rows
    created_stocks = []
    metadata_fetched = 0

    for row in result.valid_rows:
        # Handle tags (supports comma and semicolon separators)
        tags = []
        tag_names = parse_tags(row.get("tags"))
        for tag_name in tag_names:
            tag_lower = tag_name.lower()
            if tag_lower in existing_tags:
                tags.append(existing_tags[tag_lower])
            else:
                # Create new tag
                new_tag = Tag(
                    tenant_id=str(tenant_id),
                    name=tag_name,
                )
                db.add(new_tag)
                db.flush()
                existing_tags[tag_lower] = new_tag
                tags.append(new_tag)

        # Try to fetch metadata - if successful, we know the repository
        external_metadata = None
        origin = _parse_origin(row.get("origin"))
        repository = (
            _parse_repository(row.get("repository")) if origin == StockOrigin.REPOSITORY else None
        )

        if config.fetch_metadata and row.get("repository_stock_id"):
            # Try to fetch from any repository
            repo_hint = row.get("repository")
            external_metadata = await _fetch_repository_metadata(
                row["repository_stock_id"], repository=repo_hint
            )
            if external_metadata:
                # We successfully fetched, use the repository from metadata
                metadata_fetched += 1
                origin = StockOrigin.REPOSITORY
                fetched_repo = external_metadata.get("repository", repo_hint or "bdsc")
                try:
                    repository = StockRepository(fetched_repo)
                except ValueError:
                    repository = StockRepository.OTHER

        # Handle tray assignment
        tray_id = None
        position = row.get("position")
        tray_name = row.get("tray_name")

        if tray_name:
            tray = _get_or_create_tray(db, str(tenant_id), tray_name, config, created_trays)
            if tray:
                tray_id = tray.id

        # Track newly created trays
        for name in created_trays:
            if name not in trays_created_names:
                trays_created_names.append(name)

        # Create stock
        stock = Stock(
            tenant_id=str(tenant_id),
            stock_id=row["stock_id"],
            genotype=row["genotype"],
            origin=origin,
            repository=repository,
            repository_stock_id=row.get("repository_stock_id"),
            external_source=row.get("external_source"),
            notes=row.get("notes"),
            tray_id=tray_id,
            position=position,
            external_metadata=external_metadata,
            created_by_id=current_user.id,
            modified_by_id=current_user.id,
            tags=tags,
        )
        db.add(stock)
        created_stocks.append(stock)

    db.commit()

    # Determine actually created trays (ones that didn't exist before)
    # Simplify by just returning the unique tray names we processed
    new_trays = list(set(trays_created_names))

    return ImportExecuteResult(
        message=f"Successfully imported {len(created_stocks)} stocks",
        imported_count=len(created_stocks),
        stock_ids=[s.stock_id for s in created_stocks],
        trays_created=new_trays if config.auto_create_trays else [],
        metadata_fetched=metadata_fetched,
        errors=result.errors[:20] if result.error_count > 0 else [],
    )


# --- Interactive Column Mapping Endpoints (V2) ---


@router.post("/preview-v2")
async def preview_import_v2(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> ImportPreviewV2:
    """Preview import file with column info for interactive mapping.

    Returns all columns with sample values and auto-detected mappings,
    allowing users to manually assign or override mappings.

    Args:
        file: Uploaded CSV or Excel file.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        ImportPreviewV2: Preview with column info and available fields.
    """
    # Parse raw data
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        return ImportPreviewV2(
            validation_warnings=["File is empty or has no data rows"],
            can_import=False,
        )

    # Get column info with samples and auto-detection
    column_info = get_column_info(columns, raw_rows)

    # Check if at least one of the required fields is auto-detected
    auto_detected_fields = {c["auto_detected"] for c in column_info if c["auto_detected"]}
    has_required = any(f in auto_detected_fields for f in REQUIRED_FIELDS_ONE_OF)

    # Build warnings
    warnings = []
    if not has_required:
        warnings.append(
            "Each row needs either a repository stock ID (e.g., BDSC#) OR a genotype. "
            "Please map at least one of these fields."
        )

    # Note about stock_id being optional
    if "stock_id" not in auto_detected_fields:
        warnings.append("No stock_id column detected - IDs will be auto-generated if not mapped.")

    # can_import is True if we have rows (validation happens at import time)
    can_import = len(raw_rows) > 0

    return ImportPreviewV2(
        columns=[ColumnInfo(**c) for c in column_info],
        available_fields=AVAILABLE_FIELDS,
        required_fields=REQUIRED_FIELDS_ONE_OF,  # Show which fields satisfy the requirement
        total_rows=len(raw_rows),
        sample_rows=raw_rows[:10],
        can_import=can_import,
        validation_warnings=warnings,
    )


@router.post("/validate-mappings")
async def validate_mappings(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    mappings_json: Annotated[str, Form(description="JSON-encoded column mappings")],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
) -> ImportPreviewV2:
    """Validate user mappings and return stats including tray information.

    This endpoint is called after the user completes column mapping (step 2)
    to determine if a tray configuration step is needed.

    Args:
        file: Uploaded CSV or Excel file.
        mappings_json: JSON string containing column_mappings and field_generators.
        db: Database session.
        tenant_id: Current tenant ID.

    Returns:
        ImportPreviewV2: Preview with stats including tray_column_mapped and tray lists.
    """
    import json

    # Parse the mappings JSON
    try:
        mappings_data = json.loads(mappings_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON in mappings: {e}",
        )

    column_mappings = mappings_data.get("column_mappings", [])
    field_generators = mappings_data.get("field_generators", [])

    # Parse file
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        return ImportPreviewV2(
            validation_warnings=["File is empty or has no data rows"],
            can_import=False,
        )

    # Apply field generators first
    if field_generators:
        raw_rows = apply_field_generators(raw_rows, field_generators)

    # Apply user mappings
    rows, metadata_keys = apply_user_mappings(raw_rows, column_mappings)

    # Check if tray_name is mapped
    tray_column_mapped = any(m.get("target_field") == "tray_name" for m in column_mappings)

    # Compute statistics including tray info
    stats = _compute_stats(rows, str(tenant_id), db)

    # Get column info for display
    column_info = get_column_info(columns, raw_rows[:10])

    # Determine if import can proceed
    has_repo_id = any(row.get("repository_stock_id") for row in rows)
    has_genotype = any(row.get("genotype") for row in rows)
    can_import = has_repo_id or has_genotype

    return ImportPreviewV2(
        columns=[ColumnInfo(**c) for c in column_info],
        available_fields=AVAILABLE_FIELDS,
        required_fields=REQUIRED_FIELDS_ONE_OF,
        total_rows=len(rows),
        sample_rows=raw_rows[:10],
        can_import=can_import,
        validation_warnings=[],
        tray_column_mapped=tray_column_mapped,
        stats=stats,
    )


@router.post("/execute-v2")
async def execute_import_v2(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    mappings_json: Annotated[str, Form(description="JSON-encoded ImportExecuteV2Request")],
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
) -> ImportExecuteResult:
    """Execute import with user-defined column mappings.

    Args:
        file: Uploaded CSV or Excel file.
        mappings_json: JSON string containing column mappings and config.
        db: Database session.
        current_user: Current user.
        tenant_id: Current tenant ID.

    Returns:
        ImportExecuteResult: Import results.

    Raises:
        HTTPException: If validation fails or required fields are missing.
    """
    import json

    # Parse the mappings JSON
    try:
        mappings_data = json.loads(mappings_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON in mappings: {e}",
        )

    # Extract components
    column_mappings = mappings_data.get("column_mappings", [])
    field_generators = mappings_data.get("field_generators", [])
    config_data = mappings_data.get("config", {})
    config = ImportConfig(**config_data)

    # Parse file
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows in file",
        )

    # Apply field generators first (adds generated fields to rows)
    if field_generators:
        raw_rows = apply_field_generators(raw_rows, field_generators)

    # Apply user mappings
    rows, metadata_keys = apply_user_mappings(raw_rows, column_mappings)

    # Validate that at least one required field is mapped
    if rows:
        first_row = rows[0]
        has_repo_id = bool(first_row.get("repository_stock_id"))
        has_genotype = bool(first_row.get("genotype"))

        if not has_repo_id and not has_genotype:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each row must have either a repository stock ID or a genotype. "
                "Please map at least one of these fields.",
            )

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_ids = {s.stock_id for s in existing}

    # Validate (this will also auto-generate stock_ids if missing)
    result = validate_import_data(rows, existing_ids)

    if result.valid_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "No valid rows to import",
                "errors": result.errors[:20],
            },
        )

    # Get existing tags for the tenant
    existing_tags = {
        t.name.lower(): t for t in db.query(Tag).filter(Tag.tenant_id == str(tenant_id)).all()
    }

    # Tray cache
    created_trays: dict[str, Tray] = {}
    trays_created_names: list[str] = []

    # Import valid rows
    created_stocks = []
    metadata_fetched = 0

    for row in result.valid_rows:
        # Handle tags (supports comma and semicolon separators)
        tags = []
        tag_names = parse_tags(row.get("tags"))
        for tag_name in tag_names:
            tag_lower = tag_name.lower()
            if tag_lower in existing_tags:
                tags.append(existing_tags[tag_lower])
            else:
                new_tag = Tag(
                    tenant_id=str(tenant_id),
                    name=tag_name,
                )
                db.add(new_tag)
                db.flush()
                existing_tags[tag_lower] = new_tag
                tags.append(new_tag)

        # Try to fetch metadata - if successful, we know the repository
        external_metadata = None
        origin = _parse_origin(row.get("origin"))
        repository = (
            _parse_repository(row.get("repository")) if origin == StockOrigin.REPOSITORY else None
        )

        if config.fetch_metadata and row.get("repository_stock_id"):
            repo_hint = row.get("repository")
            fetched_metadata = await _fetch_repository_metadata(
                row["repository_stock_id"], repository=repo_hint
            )
            if fetched_metadata:
                external_metadata = fetched_metadata
                metadata_fetched += 1
                origin = StockOrigin.REPOSITORY
                fetched_repo = external_metadata.get("repository", repo_hint or "bdsc")
                try:
                    repository = StockRepository(fetched_repo)
                except ValueError:
                    repository = StockRepository.OTHER

        # Handle tray assignment
        tray_id = None
        position = row.get("position")
        tray_name = row.get("tray_name")

        if tray_name:
            tray = _get_or_create_tray(db, str(tenant_id), tray_name, config, created_trays)
            if tray:
                tray_id = tray.id

        # Track newly created trays
        for name in created_trays:
            if name not in trays_created_names:
                trays_created_names.append(name)

        # Merge user metadata if present
        user_metadata = row.get("_user_metadata")
        if user_metadata:
            if external_metadata:
                external_metadata.update(user_metadata)
            else:
                external_metadata = user_metadata

        # Create stock
        stock = Stock(
            tenant_id=str(tenant_id),
            stock_id=row["stock_id"],
            genotype=row["genotype"],
            origin=origin,
            repository=repository,
            repository_stock_id=row.get("repository_stock_id"),
            external_source=row.get("external_source"),
            notes=row.get("notes"),
            tray_id=tray_id,
            position=position,
            external_metadata=external_metadata,
            created_by_id=current_user.id,
            modified_by_id=current_user.id,
            tags=tags,
        )
        db.add(stock)
        created_stocks.append(stock)

    db.commit()

    new_trays = list(set(trays_created_names))

    return ImportExecuteResult(
        message=f"Successfully imported {len(created_stocks)} stocks",
        imported_count=len(created_stocks),
        stock_ids=[s.stock_id for s in created_stocks],
        trays_created=new_trays if config.auto_create_trays else [],
        metadata_fetched=metadata_fetched,
        errors=result.errors[:20] if result.error_count > 0 else [],
    )


# --- Two-Phase Import Endpoints ---


@router.post("/execute-v2-phase1")
async def execute_import_v2_phase1(
    file: Annotated[UploadFile, File(description="CSV or Excel file")],
    mappings_json: Annotated[str, Form(description="JSON-encoded ImportExecuteV2Request")],
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
) -> ImportPhase1Result:
    """Phase 1: Import clean rows immediately, return conflicts for review.

    This endpoint:
    1. Applies user mappings to all rows
    2. Detects conflicts (coalesce, genotype mismatch, duplicates, etc.)
    3. Imports rows with NO conflicts immediately
    4. Returns conflicting rows for user resolution in phase 2

    Args:
        file: Uploaded CSV or Excel file.
        mappings_json: JSON string containing column mappings and config.
        db: Database session.
        current_user: Current user.
        tenant_id: Current tenant ID.

    Returns:
        ImportPhase1Result with imported count and conflicting rows.
    """
    import json

    # Parse the mappings JSON
    try:
        mappings_data = json.loads(mappings_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON in mappings: {e}",
        )

    column_mappings = mappings_data.get("column_mappings", [])
    field_generators = mappings_data.get("field_generators", [])
    config_data = mappings_data.get("config", {})
    config = ImportConfig(**config_data)

    # Extract tray resolutions and check if tray column is mapped
    tray_resolutions_data = mappings_data.get("tray_resolutions", [])
    tray_resolutions_lookup: dict[str, TrayResolution] = {
        tr["tray_name"]: TrayResolution(**tr) for tr in tray_resolutions_data
    }
    tray_column_mapped = any(m.get("target_field") == "tray_name" for m in column_mappings)

    # Handle "delete all before import" option
    deleted_count = 0
    if config.delete_all_before_import:
        if current_user.role not in ADMIN_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin users can delete all stocks before import",
            )
        stock_service = StockService(db, str(tenant_id))
        deleted_count = stock_service.delete_all_stocks_hard()
        logger.info(
            "User %s hard-deleted %d stocks for tenant %s before import",
            current_user.id,
            deleted_count,
            tenant_id,
        )

    # Parse file
    columns, raw_rows = _parse_file_raw(file)

    if not raw_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows in file",
        )

    # Apply field generators first
    if field_generators:
        raw_rows = apply_field_generators(raw_rows, field_generators)

    # Apply user mappings (with coalesce logic)
    rows, metadata_keys = apply_user_mappings(raw_rows, column_mappings)

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_stock_ids = {s.stock_id for s in existing}

    # Fetch remote metadata and auto-set repository/origin
    # Fetch metadata from FlyBase repositories
    remote_metadata: dict[str, dict] = {}
    if config.fetch_metadata:
        for row in rows:
            repo_stock_id = row.get("repository_stock_id")
            if repo_stock_id and repo_stock_id not in remote_metadata:
                # Try to fetch from any repository
                repo_hint = row.get("repository")
                metadata = await _fetch_repository_metadata(repo_stock_id, repository=repo_hint)
                if metadata:
                    remote_metadata[repo_stock_id] = metadata
                    # Use the repository from metadata, or keep the hint
                    fetched_repo = metadata.get("repository", repo_hint or "bdsc")
                    row["repository"] = fetched_repo
                    row["origin"] = "repository"

    # Search for repository matches for non-repository stocks
    repository_matches: dict[int, list[RepositoryMatch]] = {}
    for i, row in enumerate(rows, start=1):
        origin = row.get("origin", "").lower()
        has_repo_id = bool(row.get("repository_stock_id"))
        genotype = row.get("genotype")

        # Only search for stocks not already identified as repository stocks
        if origin != "repository" and not has_repo_id and genotype:
            matches = await _find_repository_matches(genotype)
            if matches:
                repository_matches[i] = matches

    # Build detection context
    context = DetectionContext(
        existing_stock_ids=existing_stock_ids,
        column_mappings=column_mappings,
        remote_metadata=remote_metadata,
        all_rows=rows,
        repository_matches=repository_matches,
    )

    # Detect conflicts using the extensible detector
    detector = get_conflict_detector()
    conflicting_rows_data = await detector.detect_all(rows, context)

    # Separate clean rows from conflicting rows
    conflicting_indices = {cr.row_index for cr in conflicting_rows_data}
    clean_rows = [(i, row) for i, row in enumerate(rows, start=1) if i not in conflicting_indices]

    # Auto-generate stock IDs for clean rows if missing
    for idx, row in clean_rows:
        if not row.get("stock_id"):
            row["stock_id"] = generate_stock_id(row, idx, "IMP")

    # Validate clean rows
    clean_row_dicts = [row for _, row in clean_rows]
    if clean_row_dicts:
        validation_result = validate_import_data(
            clean_row_dicts, existing_stock_ids, auto_generate_stock_id=False
        )
        # Filter to only valid rows
        valid_rows = validation_result.valid_rows
    else:
        valid_rows = []

    # Import valid clean rows
    created_stocks = []
    metadata_fetched = 0
    trays_created_names: list[str] = []
    created_trays: dict[str, Tray] = {}

    # Get existing tags for the tenant
    existing_tags = {
        t.name.lower(): t for t in db.query(Tag).filter(Tag.tenant_id == str(tenant_id)).all()
    }

    for row in valid_rows:
        # Handle tags
        tags = []
        tag_names = parse_tags(row.get("tags"))
        for tag_name in tag_names:
            tag_lower = tag_name.lower()
            if tag_lower in existing_tags:
                tags.append(existing_tags[tag_lower])
            else:
                new_tag = Tag(tenant_id=str(tenant_id), name=tag_name)
                db.add(new_tag)
                db.flush()
                existing_tags[tag_lower] = new_tag
                tags.append(new_tag)

        # Get origin and repository - use values already set during metadata fetch
        repo_stock_id = row.get("repository_stock_id")
        external_metadata = remote_metadata.get(repo_stock_id) if repo_stock_id else None

        if external_metadata:
            # We fetched from a repository
            origin = StockOrigin.REPOSITORY
            fetched_repo = external_metadata.get("repository", "bdsc")
            try:
                repository = StockRepository(fetched_repo)
            except ValueError:
                repository = StockRepository.OTHER
        else:
            # Parse from row data
            origin = _parse_origin(row.get("origin"))
            repository = (
                _parse_repository(row.get("repository"))
                if origin == StockOrigin.REPOSITORY
                else None
            )

        # Handle tray assignment (only if tray_name column was explicitly mapped)
        tray_id = None
        position = row.get("position")
        tray_name = row.get("tray_name")

        if tray_name and tray_column_mapped:
            tray = _get_or_create_tray(
                db,
                str(tenant_id),
                tray_name,
                config,
                created_trays,
                tray_resolutions=tray_resolutions_lookup,
                tray_column_mapped=tray_column_mapped,
            )
            if tray:
                tray_id = tray.id

        for name in created_trays:
            if name not in trays_created_names:
                trays_created_names.append(name)
        if external_metadata:
            metadata_fetched += 1

        # Merge user metadata
        user_metadata = row.get("_user_metadata")
        if user_metadata:
            if external_metadata:
                external_metadata = {**external_metadata, **user_metadata}
            else:
                external_metadata = user_metadata

        # Create stock
        stock = Stock(
            tenant_id=str(tenant_id),
            stock_id=row["stock_id"],
            genotype=row.get("genotype", ""),
            origin=origin,
            repository=repository,
            repository_stock_id=row.get("repository_stock_id"),
            external_source=row.get("external_source"),
            notes=row.get("notes"),
            tray_id=tray_id,
            position=position,
            external_metadata=external_metadata,
            created_by_id=current_user.id,
            modified_by_id=current_user.id,
            tags=tags,
        )
        db.add(stock)
        created_stocks.append(stock)
        # Add to existing IDs so phase 2 knows about them
        existing_stock_ids.add(row["stock_id"])

    db.commit()

    # Build conflict summary
    conflict_summary: dict[str, int] = {}
    for cr in conflicting_rows_data:
        for conflict in cr.conflicts:
            ctype = conflict.conflict_type.value
            conflict_summary[ctype] = conflict_summary.get(ctype, 0) + 1

    # Create session for phase 2 if there are conflicts
    session_id = ""
    if conflicting_rows_data:
        # Store raw conflicting row data for phase 2
        conflicting_raw = [
            {
                "row_index": cr.row_index,
                "original_row": cr.original_row,
                "transformed_row": cr.transformed_row,
                "conflicts": [c.model_dump() for c in cr.conflicts],
            }
            for cr in conflicting_rows_data
        ]
        session_id = _create_import_session(
            str(tenant_id), conflicting_raw, config, column_mappings
        )

    return ImportPhase1Result(
        imported_count=len(created_stocks),
        imported_stock_ids=[s.stock_id for s in created_stocks],
        conflicting_rows=conflicting_rows_data,
        conflict_summary=conflict_summary,
        session_id=session_id,
        trays_created=trays_created_names if config.auto_create_trays else [],
        metadata_fetched=metadata_fetched,
        deleted_count=deleted_count,
    )


@router.post("/execute-v2-phase2")
async def execute_import_v2_phase2(
    request_json: Annotated[str, Form(description="JSON-encoded ImportPhase2Request")],
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    tenant_id: CurrentTenantId,
) -> ImportExecuteResult:
    """Phase 2: Import resolved conflicts.

    This endpoint:
    1. Retrieves conflicting rows from session storage
    2. Applies user resolutions
    3. Imports resolved rows
    4. Cleans up session

    Args:
        request_json: JSON string containing session_id and resolutions.
        db: Database session.
        current_user: Current user.
        tenant_id: Current tenant ID.

    Returns:
        ImportExecuteResult with import results.
    """
    import json

    try:
        request_data = json.loads(request_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}",
        )

    session_id = request_data.get("session_id", "")
    resolutions = request_data.get("resolutions", [])

    # Get session data
    session = _get_import_session(session_id, str(tenant_id))
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import session not found or expired. Please start over.",
        )

    config = ImportConfig(**session["config"])
    conflicting_rows = session["conflicting_rows"]
    column_mappings = session.get("column_mappings", [])

    # Check if tray column was explicitly mapped
    tray_column_mapped = any(m.get("target_field") == "tray_name" for m in column_mappings)

    # Extract tray resolutions from the request (if any)
    tray_resolutions_data = request_data.get("tray_resolutions", [])
    tray_resolutions_lookup: dict[str, TrayResolution] = {
        tr["tray_name"]: TrayResolution(**tr) for tr in tray_resolutions_data
    }

    # Build resolution lookup: row_index -> resolution
    resolution_lookup = {r["row_index"]: r for r in resolutions}

    # Get existing stock IDs
    existing = db.query(Stock.stock_id).filter(Stock.tenant_id == str(tenant_id)).all()
    existing_stock_ids = {s.stock_id for s in existing}

    # Get existing tags
    existing_tags = {
        t.name.lower(): t for t in db.query(Tag).filter(Tag.tenant_id == str(tenant_id)).all()
    }

    # Tray cache
    created_trays: dict[str, Tray] = {}
    trays_created_names: list[str] = []

    created_stocks = []
    skipped_count = 0
    errors = []

    for conflict_row in conflicting_rows:
        row_index = conflict_row["row_index"]
        row = conflict_row["transformed_row"]
        resolution = resolution_lookup.get(row_index)

        if not resolution:
            # No resolution provided - skip
            skipped_count += 1
            continue

        action = resolution.get("action", "skip")
        if action == "skip":
            skipped_count += 1
            continue

        # Apply resolved field values
        field_values = resolution.get("field_values", {})

        # First handle special flags before applying other fields
        # Handle flag for attention - append note
        if field_values.get("_flag_note"):
            existing_notes = row.get("notes") or ""
            if existing_notes:
                row["notes"] = existing_notes + "\n\n" + field_values["_flag_note"]
            else:
                row["notes"] = field_values["_flag_note"]

        # Handle flag tag
        flag_tag = field_values.get("_flag_tag")
        if flag_tag:
            row_tags = row.get("tags") or ""
            if row_tags:
                row["tags"] = row_tags + "," + flag_tag
            else:
                row["tags"] = flag_tag

        # Now apply other field values, skipping internal fields
        for field, value in field_values.items():
            # Skip internal UI state fields
            if field.startswith("_"):
                continue
            row[field] = value

        # Generate stock_id if missing
        if not row.get("stock_id"):
            row["stock_id"] = generate_stock_id(row, row_index, "IMP")

        # Check for duplicate after resolution
        if row["stock_id"] in existing_stock_ids:
            errors.append(
                {
                    "row": row_index,
                    "errors": [f"Stock ID '{row['stock_id']}' already exists"],
                }
            )
            continue

        # Validate required fields
        field_errors = validate_required_fields(row)
        if field_errors:
            errors.append({"row": row_index, "errors": field_errors})
            continue

        # Handle tags
        tags = []
        tag_names = parse_tags(row.get("tags"))
        for tag_name in tag_names:
            tag_lower = tag_name.lower()
            if tag_lower in existing_tags:
                tags.append(existing_tags[tag_lower])
            else:
                new_tag = Tag(tenant_id=str(tenant_id), name=tag_name)
                db.add(new_tag)
                db.flush()
                existing_tags[tag_lower] = new_tag
                tags.append(new_tag)

        # Parse origin and repository
        origin = _parse_origin(row.get("origin"))
        repository = (
            _parse_repository(row.get("repository")) if origin == StockOrigin.REPOSITORY else None
        )

        # Handle tray (only if tray_name column was explicitly mapped)
        tray_id = None
        position = row.get("position")
        tray_name = row.get("tray_name")

        if tray_name and tray_column_mapped:
            tray = _get_or_create_tray(
                db,
                str(tenant_id),
                tray_name,
                config,
                created_trays,
                tray_resolutions=tray_resolutions_lookup,
                tray_column_mapped=tray_column_mapped,
            )
            if tray:
                tray_id = tray.id

        for name in created_trays:
            if name not in trays_created_names:
                trays_created_names.append(name)

        # Get user metadata and handle preserved original genotype
        external_metadata = row.get("_user_metadata") or {}

        # If original genotype was preserved to metadata, add it
        original_genotype = row.get("_original_genotype")
        if original_genotype:
            external_metadata["original_genotype_from_import"] = original_genotype

        # Clean up internal fields
        external_metadata = external_metadata if external_metadata else None

        # Create stock
        stock = Stock(
            tenant_id=str(tenant_id),
            stock_id=row["stock_id"],
            genotype=row.get("genotype", ""),
            origin=origin,
            repository=repository,
            repository_stock_id=row.get("repository_stock_id"),
            external_source=row.get("external_source"),
            notes=row.get("notes"),
            tray_id=tray_id,
            position=position,
            external_metadata=external_metadata,
            created_by_id=current_user.id,
            modified_by_id=current_user.id,
            tags=tags,
        )
        db.add(stock)
        created_stocks.append(stock)
        existing_stock_ids.add(row["stock_id"])

    db.commit()

    # Clean up session
    _delete_import_session(session_id)

    message = f"Imported {len(created_stocks)} stocks"
    if skipped_count > 0:
        message += f", skipped {skipped_count}"

    return ImportExecuteResult(
        message=message,
        imported_count=len(created_stocks),
        stock_ids=[s.stock_id for s in created_stocks],
        trays_created=trays_created_names if config.auto_create_trays else [],
        metadata_fetched=0,  # Metadata was fetched in phase 1
        errors=errors[:20],
    )
