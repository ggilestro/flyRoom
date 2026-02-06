"""Business logic for backup/restore operations."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.backup.schemas import (
    BackupFile,
    ConflictMode,
    ExportMetadata,
    ImportResult,
    ValidationIssue,
    ValidationResult,
)
from app.backup.serializers import (
    deserialize_cross,
    deserialize_external_reference,
    deserialize_flip_event,
    deserialize_print_agent,
    deserialize_print_job,
    deserialize_stock,
    deserialize_stock_tag,
    deserialize_tag,
    deserialize_tray,
    deserialize_user,
    export_tenant_data,
)
from app.db.models import (
    Cross,
    ExternalReference,
    FlipEvent,
    PrintAgent,
    PrintJob,
    Stock,
    StockTag,
    Tag,
    Tenant,
    Tray,
    User,
)

logger = logging.getLogger(__name__)

# Current schema version (should match latest alembic revision)
CURRENT_SCHEMA_VERSION = "008"

# Tables in import order (respects foreign key dependencies)
IMPORT_ORDER = [
    "users",
    "trays",
    "tags",
    "stocks",
    "stock_tags",
    "crosses",
    "external_references",
    "print_agents",
    "print_jobs",
    "flip_events",
]


class BackupService:
    """Service for backup and restore operations."""

    def __init__(self, db: Session):
        """Initialize backup service.

        Args:
            db: Database session.
        """
        self.db = db

    def export_tenant(self, tenant: Tenant) -> BackupFile:
        """Export all data for a tenant.

        Args:
            tenant: Tenant model instance.

        Returns:
            BackupFile with metadata and data.
        """
        data = export_tenant_data(self.db, tenant.id)

        record_counts = {table: len(records) for table, records in data.items()}

        metadata = ExportMetadata(
            schema_version=CURRENT_SCHEMA_VERSION,
            export_version="1.0",
            exported_at=datetime.now(UTC),
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            record_counts=record_counts,
        )

        return BackupFile(metadata=metadata, data=data)

    def validate_backup(self, backup_data: dict[str, Any], tenant_id: str) -> ValidationResult:
        """Validate a backup file before import.

        Args:
            backup_data: Parsed JSON backup data.
            tenant_id: Target tenant ID.

        Returns:
            ValidationResult with issues found.
        """
        errors: list[str] = []
        warnings: list[str] = []
        conflicts: list[ValidationIssue] = []

        # Check basic structure
        if "metadata" not in backup_data:
            errors.append("Missing 'metadata' section in backup file")
            return ValidationResult(
                is_valid=False,
                schema_version="unknown",
                current_schema_version=CURRENT_SCHEMA_VERSION,
                schema_compatible=False,
                errors=errors,
            )

        if "data" not in backup_data:
            errors.append("Missing 'data' section in backup file")
            return ValidationResult(
                is_valid=False,
                schema_version="unknown",
                current_schema_version=CURRENT_SCHEMA_VERSION,
                schema_compatible=False,
                errors=errors,
            )

        metadata = backup_data["metadata"]
        data = backup_data["data"]

        # Check schema version
        schema_version = metadata.get("schema_version", "unknown")
        schema_compatible = self._check_schema_compatibility(schema_version)

        if not schema_compatible:
            errors.append(
                f"Schema version '{schema_version}' is not compatible with "
                f"current version '{CURRENT_SCHEMA_VERSION}'"
            )

        # Count records
        record_counts = {table: len(records) for table, records in data.items()}

        # Check for unknown tables
        for table in data.keys():
            if table not in IMPORT_ORDER:
                warnings.append(f"Unknown table '{table}' will be ignored")

        # Check for conflicts with existing data
        conflicts.extend(self._find_conflicts(data, tenant_id))

        # Validate referential integrity within the backup
        ref_errors = self._validate_references(data)
        for ref_error in ref_errors:
            errors.append(ref_error)

        is_valid = len(errors) == 0 and schema_compatible

        return ValidationResult(
            is_valid=is_valid,
            schema_version=schema_version,
            current_schema_version=CURRENT_SCHEMA_VERSION,
            schema_compatible=schema_compatible,
            record_counts=record_counts,
            conflicts=conflicts,
            warnings=warnings,
            errors=errors,
        )

    def import_backup(
        self,
        backup_data: dict[str, Any],
        tenant_id: str,
        conflict_mode: ConflictMode = ConflictMode.FAIL,
        dry_run: bool = False,
    ) -> ImportResult:
        """Import backup data into tenant.

        Args:
            backup_data: Parsed JSON backup data.
            tenant_id: Target tenant ID.
            conflict_mode: How to handle conflicts.
            dry_run: If True, validate without committing.

        Returns:
            ImportResult with counts and any errors.
        """
        records_imported: dict[str, int] = {}
        records_skipped: dict[str, int] = {}
        records_overwritten: dict[str, int] = {}
        errors: list[str] = []
        warnings: list[str] = []

        data = backup_data.get("data", {})

        # Get existing IDs for conflict detection
        existing_ids = self._get_existing_ids(tenant_id)

        # Track ID mappings for skipped records (backup_id -> existing_id)
        # Used to remap foreign key references when records are skipped
        id_mappings: dict[str, str] = {}

        try:
            # Import in dependency order
            for table in IMPORT_ORDER:
                if table not in data:
                    continue

                records = data[table]
                imported, skipped, overwritten, table_errors, mappings = self._import_table(
                    table=table,
                    records=records,
                    tenant_id=tenant_id,
                    existing_ids=existing_ids,
                    conflict_mode=conflict_mode,
                    id_mappings=id_mappings,
                )

                records_imported[table] = imported
                records_skipped[table] = skipped
                records_overwritten[table] = overwritten
                errors.extend(table_errors)
                id_mappings.update(mappings)

                if table_errors and conflict_mode == ConflictMode.FAIL:
                    break

            if dry_run:
                self.db.rollback()
            else:
                if not errors or conflict_mode != ConflictMode.FAIL:
                    self.db.commit()
                else:
                    self.db.rollback()

        except Exception as e:
            self.db.rollback()
            logger.exception("Import failed")
            errors.append(f"Import failed: {str(e)}")

        success = len(errors) == 0 or (
            conflict_mode != ConflictMode.FAIL and not any("failed" in e.lower() for e in errors)
        )

        return ImportResult(
            success=success,
            dry_run=dry_run,
            records_imported=records_imported,
            records_skipped=records_skipped,
            records_overwritten=records_overwritten,
            errors=errors,
            warnings=warnings,
        )

    def _check_schema_compatibility(self, schema_version: str) -> bool:
        """Check if backup schema is compatible with current.

        Args:
            schema_version: Version from backup file.

        Returns:
            True if compatible.
        """
        # For now, require exact match
        # Future: implement migration functions for older versions
        return schema_version == CURRENT_SCHEMA_VERSION

    def _find_conflicts(self, data: dict[str, list[dict]], tenant_id: str) -> list[ValidationIssue]:
        """Find records that conflict with existing data.

        Args:
            data: Backup data by table.
            tenant_id: Target tenant ID.

        Returns:
            List of conflicts found.
        """
        conflicts = []
        existing_ids = self._get_existing_ids(tenant_id)

        # Check each table for ID conflicts
        for table, id_set in existing_ids.items():
            if table not in data:
                continue

            for record in data[table]:
                record_id = record.get("id") or record.get("stock_id")
                if record_id and record_id in id_set:
                    conflicts.append(
                        ValidationIssue(
                            table=table,
                            record_id=record_id,
                            issue_type="duplicate_id",
                            message=(
                                f"{table} record with ID '{record_id}' already exists. "
                                f"Use 'skip' mode to skip duplicates or 'overwrite' mode to replace them."
                            ),
                        )
                    )

        # Check email uniqueness for users (tenant_id + email is unique)
        if "users" in data:
            existing_emails = {
                u.email for u in self.db.query(User.email).filter(User.tenant_id == tenant_id).all()
            }
            for record in data["users"]:
                email = record.get("email")
                if email and email in existing_emails:
                    conflicts.append(
                        ValidationIssue(
                            table="users",
                            record_id=record.get("id"),
                            issue_type="duplicate_email",
                            message=(
                                f"User with email '{email}' already exists in this tenant. "
                                f"Use 'skip' mode to skip this user and remap their records, "
                                f"or 'overwrite' mode to replace the existing user."
                            ),
                        )
                    )

        # Check stock_id uniqueness for stocks
        if "stocks" in data:
            existing_stock_ids = {
                s.stock_id
                for s in self.db.query(Stock.stock_id).filter(Stock.tenant_id == tenant_id).all()
            }
            for record in data["stocks"]:
                stock_id = record.get("stock_id")
                if stock_id and stock_id in existing_stock_ids:
                    conflicts.append(
                        ValidationIssue(
                            table="stocks",
                            record_id=record.get("id"),
                            issue_type="duplicate_stock_id",
                            message=(
                                f"Stock ID '{stock_id}' already exists in this tenant. "
                                f"Use 'skip' mode to skip duplicates or 'overwrite' mode to replace them."
                            ),
                        )
                    )

        return conflicts

    def _validate_references(self, data: dict[str, list[dict]]) -> list[str]:
        """Validate referential integrity within backup data.

        Args:
            data: Backup data by table.

        Returns:
            List of error messages.
        """
        errors = []

        # Collect all IDs by table
        user_ids = {r["id"] for r in data.get("users", [])}
        tray_ids = {r["id"] for r in data.get("trays", [])}
        tag_ids = {r["id"] for r in data.get("tags", [])}
        stock_ids = {r["id"] for r in data.get("stocks", [])}
        print_agent_ids = {r["id"] for r in data.get("print_agents", [])}

        # Validate stock references
        for stock in data.get("stocks", []):
            if stock.get("tray_id") and stock["tray_id"] not in tray_ids:
                errors.append(
                    f"Stock '{stock['id']}' references non-existent tray '{stock['tray_id']}'"
                )
            if stock.get("owner_id") and stock["owner_id"] not in user_ids:
                errors.append(
                    f"Stock '{stock['id']}' references non-existent owner '{stock['owner_id']}'"
                )
            if stock.get("created_by_id") and stock["created_by_id"] not in user_ids:
                errors.append(
                    f"Stock '{stock['id']}' references non-existent creator "
                    f"'{stock['created_by_id']}'"
                )

        # Validate stock_tags references
        for st in data.get("stock_tags", []):
            if st["stock_id"] not in stock_ids:
                errors.append(f"StockTag references non-existent stock '{st['stock_id']}'")
            if st["tag_id"] not in tag_ids:
                errors.append(f"StockTag references non-existent tag '{st['tag_id']}'")

        # Validate crosses references
        for cross in data.get("crosses", []):
            if cross["parent_female_id"] not in stock_ids:
                errors.append(
                    f"Cross '{cross['id']}' references non-existent female parent "
                    f"'{cross['parent_female_id']}'"
                )
            if cross["parent_male_id"] not in stock_ids:
                errors.append(
                    f"Cross '{cross['id']}' references non-existent male parent "
                    f"'{cross['parent_male_id']}'"
                )
            if cross.get("offspring_id") and cross["offspring_id"] not in stock_ids:
                errors.append(
                    f"Cross '{cross['id']}' references non-existent offspring "
                    f"'{cross['offspring_id']}'"
                )

        # Validate external_references
        for ref in data.get("external_references", []):
            if ref["stock_id"] not in stock_ids:
                errors.append(
                    f"ExternalReference '{ref['id']}' references non-existent stock "
                    f"'{ref['stock_id']}'"
                )

        # Validate print_jobs references
        for job in data.get("print_jobs", []):
            if job.get("agent_id") and job["agent_id"] not in print_agent_ids:
                errors.append(
                    f"PrintJob '{job['id']}' references non-existent agent " f"'{job['agent_id']}'"
                )

        # Validate flip_events references
        for event in data.get("flip_events", []):
            if event["stock_id"] not in stock_ids:
                errors.append(
                    f"FlipEvent '{event['id']}' references non-existent stock "
                    f"'{event['stock_id']}'"
                )

        return errors

    def _get_existing_ids(self, tenant_id: str) -> dict[str, set[str]]:
        """Get existing record IDs for conflict detection.

        Args:
            tenant_id: Tenant ID.

        Returns:
            Dict mapping table names to sets of existing IDs.
        """
        existing: dict[str, set[str]] = {}

        # Users
        existing["users"] = {
            u.id for u in self.db.query(User.id).filter(User.tenant_id == tenant_id).all()
        }

        # Trays
        existing["trays"] = {
            t.id for t in self.db.query(Tray.id).filter(Tray.tenant_id == tenant_id).all()
        }

        # Tags
        existing["tags"] = {
            t.id for t in self.db.query(Tag.id).filter(Tag.tenant_id == tenant_id).all()
        }

        # Stocks
        existing["stocks"] = {
            s.id for s in self.db.query(Stock.id).filter(Stock.tenant_id == tenant_id).all()
        }

        # PrintAgents
        existing["print_agents"] = {
            a.id
            for a in self.db.query(PrintAgent.id).filter(PrintAgent.tenant_id == tenant_id).all()
        }

        # PrintJobs
        existing["print_jobs"] = {
            j.id for j in self.db.query(PrintJob.id).filter(PrintJob.tenant_id == tenant_id).all()
        }

        return existing

    def _import_table(
        self,
        table: str,
        records: list[dict],
        tenant_id: str,
        existing_ids: dict[str, set[str]],
        conflict_mode: ConflictMode,
        id_mappings: dict[str, str],
    ) -> tuple[int, int, int, list[str], dict[str, str]]:
        """Import records for a single table.

        Args:
            table: Table name.
            records: List of record dicts.
            tenant_id: Target tenant ID.
            existing_ids: Existing IDs by table.
            conflict_mode: How to handle conflicts.
            id_mappings: Existing ID mappings from previous tables (backup_id -> existing_id).

        Returns:
            Tuple of (imported, skipped, overwritten, errors, new_mappings).
        """
        imported = 0
        skipped = 0
        overwritten = 0
        errors = []
        new_mappings: dict[str, str] = {}

        existing = existing_ids.get(table, set())

        # For users table, also track existing emails to handle unique constraint
        existing_emails: dict[str, str] = {}
        if table == "users":
            existing_user_emails = (
                self.db.query(User.id, User.email).filter(User.tenant_id == tenant_id).all()
            )
            existing_emails = {email: user_id for user_id, email in existing_user_emails}

        for record in records:
            record_id = record.get("id")
            is_conflict = record_id and record_id in existing

            # Check for email conflict in users table
            email_conflict_user_id = None
            if table == "users" and not is_conflict:
                email = record.get("email")
                if email and email in existing_emails:
                    email_conflict_user_id = existing_emails[email]
                    is_conflict = True

            if is_conflict:
                if conflict_mode == ConflictMode.FAIL:
                    if email_conflict_user_id:
                        errors.append(
                            f"Import stopped: User with email '{record.get('email')}' already exists "
                            f"(existing user ID: '{email_conflict_user_id}'). "
                            f"\n\nTo resolve this:\n"
                            f"• Use 'skip' mode to skip duplicate users and import other data "
                            f"(foreign keys will be automatically remapped)\n"
                            f"• Use 'overwrite' mode to replace existing users with backup data"
                        )
                    else:
                        errors.append(
                            f"Import stopped: {table} record '{record_id}' already exists. "
                            f"Use 'skip' mode to skip duplicates or 'overwrite' mode to replace them."
                        )
                    return imported, skipped, overwritten, errors, new_mappings
                elif conflict_mode == ConflictMode.SKIP:
                    skipped += 1
                    # Track the mapping so foreign key references can be remapped
                    existing_record_id = (
                        email_conflict_user_id if email_conflict_user_id else record_id
                    )
                    if record_id and existing_record_id:
                        new_mappings[record_id] = existing_record_id
                    continue
                elif conflict_mode == ConflictMode.OVERWRITE:
                    # Delete the existing record (by ID or by email conflict)
                    delete_id = email_conflict_user_id if email_conflict_user_id else record_id
                    self._delete_existing(table, delete_id)
                    overwritten += 1

            # Remap foreign key references based on previous ID mappings
            record = self._remap_foreign_keys(table, record, id_mappings)

            try:
                model = self._deserialize_record(table, record, tenant_id)
                if model:
                    self.db.add(model)
                    self.db.flush()
                    imported += 1
                    if record_id:
                        existing.add(record_id)
                    # Track email for future conflict detection
                    if table == "users" and record.get("email"):
                        existing_emails[record["email"]] = record_id
            except Exception as e:
                errors.append(f"Failed to import {table} record '{record_id}': {str(e)}")
                if conflict_mode == ConflictMode.FAIL:
                    return imported, skipped, overwritten, errors, new_mappings

        return imported, skipped, overwritten, errors, new_mappings

    def _remap_foreign_keys(self, table: str, record: dict, id_mappings: dict[str, str]) -> dict:
        """Remap foreign key references based on ID mappings from skipped records.

        Args:
            table: Table name.
            record: Record dict.
            id_mappings: Mappings from backup IDs to existing IDs.

        Returns:
            Record dict with remapped foreign keys.
        """
        if not id_mappings:
            return record

        # Make a copy to avoid modifying the original
        record = record.copy()

        # Define ALL foreign key fields that reference users across all tables
        user_fk_fields = [
            "owner_id",
            "created_by_id",
            "modified_by_id",
            "flipped_by_id",
            "requested_by_id",
            "responded_by_id",
            "requester_user_id",
        ]

        # Remap user foreign keys
        for field in user_fk_fields:
            if field in record and record[field] and record[field] in id_mappings:
                old_id = record[field]
                new_id = id_mappings[old_id]
                record[field] = new_id
                logger.debug(f"Remapped {table}.{field}: {old_id} -> {new_id}")

        # For crosses, remap parent and offspring stock references
        if table == "crosses":
            stock_fk_fields = ["parent_female_id", "parent_male_id", "offspring_id"]
            for field in stock_fk_fields:
                if field in record and record[field] and record[field] in id_mappings:
                    old_id = record[field]
                    new_id = id_mappings[old_id]
                    record[field] = new_id
                    logger.debug(f"Remapped {table}.{field}: {old_id} -> {new_id}")

        # For stock_tags, remap stock and tag references
        if table == "stock_tags":
            if "stock_id" in record and record["stock_id"] in id_mappings:
                record["stock_id"] = id_mappings[record["stock_id"]]
            if "tag_id" in record and record["tag_id"] in id_mappings:
                record["tag_id"] = id_mappings[record["tag_id"]]

        # For external_references, remap stock reference
        if table == "external_references":
            if "stock_id" in record and record["stock_id"] in id_mappings:
                record["stock_id"] = id_mappings[record["stock_id"]]

        # For flip_events, remap stock reference
        if table == "flip_events":
            if "stock_id" in record and record["stock_id"] in id_mappings:
                record["stock_id"] = id_mappings[record["stock_id"]]

        # For stocks, remap tray reference
        if table == "stocks":
            if "tray_id" in record and record["tray_id"] and record["tray_id"] in id_mappings:
                record["tray_id"] = id_mappings[record["tray_id"]]

        # For print_jobs, remap agent reference
        if table == "print_jobs":
            if "agent_id" in record and record["agent_id"] and record["agent_id"] in id_mappings:
                record["agent_id"] = id_mappings[record["agent_id"]]

        return record

    def _deserialize_record(self, table: str, record: dict, tenant_id: str) -> Any:
        """Deserialize a record dict to model.

        Args:
            table: Table name.
            record: Record dict.
            tenant_id: Target tenant ID.

        Returns:
            Model instance or None.
        """
        if table == "users":
            return deserialize_user(record, tenant_id)
        elif table == "trays":
            return deserialize_tray(record, tenant_id)
        elif table == "tags":
            return deserialize_tag(record, tenant_id)
        elif table == "stocks":
            return deserialize_stock(record, tenant_id)
        elif table == "stock_tags":
            return deserialize_stock_tag(record)
        elif table == "crosses":
            return deserialize_cross(record, tenant_id)
        elif table == "external_references":
            return deserialize_external_reference(record)
        elif table == "print_agents":
            return deserialize_print_agent(record, tenant_id)
        elif table == "print_jobs":
            return deserialize_print_job(record, tenant_id)
        elif table == "flip_events":
            return deserialize_flip_event(record)
        else:
            return None

    def _delete_existing(self, table: str, record_id: str) -> None:
        """Delete an existing record for overwrite mode.

        Args:
            table: Table name.
            record_id: Record ID to delete.
        """
        model_map = {
            "users": User,
            "trays": Tray,
            "tags": Tag,
            "stocks": Stock,
            "stock_tags": StockTag,
            "crosses": Cross,
            "external_references": ExternalReference,
            "print_agents": PrintAgent,
            "print_jobs": PrintJob,
            "flip_events": FlipEvent,
        }

        model_class = model_map.get(table)
        if model_class:
            if table == "stock_tags":
                # StockTag has composite key
                pass
            else:
                self.db.query(model_class).filter(model_class.id == record_id).delete()
