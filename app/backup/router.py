"""Admin-only API endpoints for backup/restore."""

import json
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.backup.schemas import (
    ConflictMode,
    ImportResult,
    ValidationResult,
)
from app.backup.service import BackupService
from app.dependencies import CurrentAdmin, DbSession

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/export")
async def export_backup(
    admin: CurrentAdmin,
    db: DbSession,
) -> Response:
    """Export tenant database as JSON file download.

    This endpoint exports all data for the current tenant including:
    - Users
    - Trays
    - Tags
    - Stocks
    - Stock-Tag associations
    - Crosses
    - External references
    - Print agents
    - Print jobs
    - Flip events

    The export file includes schema version metadata for future-proofing.

    Args:
        admin: Current admin user (dependency ensures admin access).
        db: Database session.

    Returns:
        JSON file download with backup data.
    """
    service = BackupService(db)
    tenant = admin.tenant

    backup = service.export_tenant(tenant)

    # Generate filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{tenant.slug}_backup_{timestamp}.json"

    # Serialize to JSON
    content = backup.model_dump_json(indent=2)

    logger.info(
        f"Exported backup for tenant {tenant.id} ({tenant.name}): "
        f"{backup.metadata.record_counts}"
    )

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/validate", response_model=ValidationResult)
async def validate_backup(
    admin: CurrentAdmin,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Backup JSON file")],
) -> ValidationResult:
    """Validate a backup file without importing.

    Checks:
    - File structure and format
    - Schema version compatibility
    - Referential integrity within backup
    - Conflicts with existing data

    Args:
        admin: Current admin user.
        db: Database session.
        file: Uploaded backup JSON file.

    Returns:
        ValidationResult with any issues found.
    """
    # Read and parse file
    try:
        content = await file.read()
        backup_data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON file: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}",
        )

    service = BackupService(db)
    result = service.validate_backup(backup_data, admin.tenant_id)

    return result


@router.post("/import", response_model=ImportResult)
async def import_backup(
    admin: CurrentAdmin,
    db: DbSession,
    file: Annotated[UploadFile, File(description="Backup JSON file")],
    conflict_mode: Annotated[
        ConflictMode,
        Form(description="How to handle conflicts: fail, skip, or overwrite"),
    ] = ConflictMode.FAIL,
    dry_run: Annotated[
        bool,
        Form(description="Validate without importing"),
    ] = False,
) -> ImportResult:
    """Import data from a backup file.

    This endpoint imports all data from a backup file into the current tenant.
    The import respects foreign key dependencies and imports in the correct order.

    Conflict Modes:
    - fail: Stop on first conflict (default, safest)
    - skip: Skip conflicting records, import the rest
    - overwrite: Replace existing records with backup data

    Args:
        admin: Current admin user.
        db: Database session.
        file: Uploaded backup JSON file.
        conflict_mode: How to handle conflicting records.
        dry_run: If True, validate without committing changes.

    Returns:
        ImportResult with counts and any errors.
    """
    # Read and parse file
    try:
        content = await file.read()
        backup_data = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON file: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read file: {str(e)}",
        )

    # Validate first
    service = BackupService(db)
    validation = service.validate_backup(backup_data, admin.tenant_id)

    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Backup file validation failed",
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )

    # Perform import
    result = service.import_backup(
        backup_data=backup_data,
        tenant_id=admin.tenant_id,
        conflict_mode=conflict_mode,
        dry_run=dry_run,
    )

    if not result.success:
        logger.warning(f"Import failed for tenant {admin.tenant_id}: {result.errors}")
    else:
        action = "validated (dry run)" if dry_run else "imported"
        logger.info(f"Backup {action} for tenant {admin.tenant_id}: " f"{result.records_imported}")

    return result
