"""Serialization utilities for backup/restore.

Handles conversion between SQLAlchemy models and JSON-serializable dicts.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    Cross,
    CrossStatus,
    ExternalReference,
    FlipEvent,
    PrintAgent,
    PrintJob,
    PrintJobStatus,
    Stock,
    StockOrigin,
    StockRepository,
    StockTag,
    StockVisibility,
    Tag,
    Tray,
    TrayType,
    User,
    UserRole,
    UserStatus,
)


def serialize_datetime(dt: datetime | None) -> str | None:
    """Convert datetime to ISO 8601 string.

    Args:
        dt: Datetime object or None.

    Returns:
        ISO 8601 formatted string or None.
    """
    if dt is None:
        return None
    return dt.isoformat()


def deserialize_datetime(s: str | None) -> datetime | None:
    """Convert ISO 8601 string to datetime.

    Args:
        s: ISO 8601 formatted string or None.

    Returns:
        Datetime object or None.
    """
    if s is None:
        return None
    return datetime.fromisoformat(s)


def serialize_enum(e: Enum | None) -> str | None:
    """Convert enum to its value string.

    Args:
        e: Enum instance or None.

    Returns:
        Enum value string or None.
    """
    if e is None:
        return None
    return e.value


# --- User Serialization ---


def serialize_user(user: User) -> dict[str, Any]:
    """Serialize a User model to dict.

    Args:
        user: User model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "password_hash": user.password_hash,
        "full_name": user.full_name,
        "role": serialize_enum(user.role),
        "status": serialize_enum(user.status),
        "is_active": user.is_active,
        "created_at": serialize_datetime(user.created_at),
        "last_login": serialize_datetime(user.last_login),
        "password_reset_token": user.password_reset_token,
        "password_reset_token_expires": serialize_datetime(user.password_reset_token_expires),
        "is_email_verified": user.is_email_verified,
        "email_verification_token": user.email_verification_token,
        "email_verification_sent_at": serialize_datetime(user.email_verification_sent_at),
    }


def deserialize_user(data: dict[str, Any], tenant_id: str) -> User:
    """Deserialize dict to User model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID (overrides data value).

    Returns:
        User model instance (not yet added to session).
    """
    return User(
        id=data["id"],
        tenant_id=tenant_id,
        email=data["email"],
        password_hash=data["password_hash"],
        full_name=data["full_name"],
        role=UserRole(data["role"]) if data.get("role") else UserRole.USER,
        status=UserStatus(data["status"]) if data.get("status") else UserStatus.APPROVED,
        is_active=data.get("is_active", True),
        created_at=deserialize_datetime(data.get("created_at")),
        last_login=deserialize_datetime(data.get("last_login")),
        password_reset_token=data.get("password_reset_token"),
        password_reset_token_expires=deserialize_datetime(data.get("password_reset_token_expires")),
        is_email_verified=data.get("is_email_verified", False),
        email_verification_token=data.get("email_verification_token"),
        email_verification_sent_at=deserialize_datetime(data.get("email_verification_sent_at")),
    )


# --- Tray Serialization ---


def serialize_tray(tray: Tray) -> dict[str, Any]:
    """Serialize a Tray model to dict.

    Args:
        tray: Tray model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": tray.id,
        "tenant_id": tray.tenant_id,
        "name": tray.name,
        "description": tray.description,
        "tray_type": serialize_enum(tray.tray_type),
        "max_positions": tray.max_positions,
        "rows": tray.rows,
        "cols": tray.cols,
        "created_at": serialize_datetime(tray.created_at),
    }


def deserialize_tray(data: dict[str, Any], tenant_id: str) -> Tray:
    """Deserialize dict to Tray model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        Tray model instance.
    """
    return Tray(
        id=data["id"],
        tenant_id=tenant_id,
        name=data["name"],
        description=data.get("description"),
        tray_type=TrayType(data["tray_type"]) if data.get("tray_type") else TrayType.NUMERIC,
        max_positions=data.get("max_positions", 100),
        rows=data.get("rows"),
        cols=data.get("cols"),
        created_at=deserialize_datetime(data.get("created_at")),
    )


# --- Tag Serialization ---


def serialize_tag(tag: Tag) -> dict[str, Any]:
    """Serialize a Tag model to dict.

    Args:
        tag: Tag model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": tag.id,
        "tenant_id": tag.tenant_id,
        "name": tag.name,
        "color": tag.color,
    }


def deserialize_tag(data: dict[str, Any], tenant_id: str) -> Tag:
    """Deserialize dict to Tag model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        Tag model instance.
    """
    return Tag(
        id=data["id"],
        tenant_id=tenant_id,
        name=data["name"],
        color=data.get("color"),
    )


# --- Stock Serialization ---


def serialize_stock(stock: Stock) -> dict[str, Any]:
    """Serialize a Stock model to dict.

    Args:
        stock: Stock model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": stock.id,
        "tenant_id": stock.tenant_id,
        "stock_id": stock.stock_id,
        "genotype": stock.genotype,
        "origin": serialize_enum(stock.origin),
        "repository": serialize_enum(stock.repository),
        "repository_stock_id": stock.repository_stock_id,
        "external_source": stock.external_source,
        "original_genotype": stock.original_genotype,
        "tray_id": stock.tray_id,
        "position": stock.position,
        "owner_id": stock.owner_id,
        "visibility": serialize_enum(stock.visibility),
        "hide_from_org": stock.hide_from_org,
        "notes": stock.notes,
        "is_active": stock.is_active,
        "created_at": serialize_datetime(stock.created_at),
        "created_by_id": stock.created_by_id,
        "modified_at": serialize_datetime(stock.modified_at),
        "modified_by_id": stock.modified_by_id,
        "external_metadata": stock.external_metadata,
    }


def deserialize_stock(data: dict[str, Any], tenant_id: str) -> Stock:
    """Deserialize dict to Stock model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        Stock model instance.
    """
    return Stock(
        id=data["id"],
        tenant_id=tenant_id,
        stock_id=data["stock_id"],
        genotype=data["genotype"],
        origin=StockOrigin(data["origin"]) if data.get("origin") else StockOrigin.INTERNAL,
        repository=StockRepository(data["repository"]) if data.get("repository") else None,
        repository_stock_id=data.get("repository_stock_id"),
        external_source=data.get("external_source"),
        original_genotype=data.get("original_genotype"),
        tray_id=data.get("tray_id"),
        position=data.get("position"),
        owner_id=data.get("owner_id"),
        visibility=(
            StockVisibility(data["visibility"])
            if data.get("visibility")
            else StockVisibility.LAB_ONLY
        ),
        hide_from_org=data.get("hide_from_org", False),
        notes=data.get("notes"),
        is_active=data.get("is_active", True),
        created_at=deserialize_datetime(data.get("created_at")),
        created_by_id=data.get("created_by_id"),
        modified_at=deserialize_datetime(data.get("modified_at")),
        modified_by_id=data.get("modified_by_id"),
        external_metadata=data.get("external_metadata"),
    )


# --- StockTag Serialization ---


def serialize_stock_tag(stock_tag: StockTag) -> dict[str, Any]:
    """Serialize a StockTag association to dict.

    Args:
        stock_tag: StockTag model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "stock_id": stock_tag.stock_id,
        "tag_id": stock_tag.tag_id,
    }


def deserialize_stock_tag(data: dict[str, Any]) -> StockTag:
    """Deserialize dict to StockTag model.

    Args:
        data: Dict from backup file.

    Returns:
        StockTag model instance.
    """
    return StockTag(
        stock_id=data["stock_id"],
        tag_id=data["tag_id"],
    )


# --- Cross Serialization ---


def serialize_cross(cross: Cross) -> dict[str, Any]:
    """Serialize a Cross model to dict.

    Args:
        cross: Cross model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": cross.id,
        "tenant_id": cross.tenant_id,
        "name": cross.name,
        "parent_female_id": cross.parent_female_id,
        "parent_male_id": cross.parent_male_id,
        "offspring_id": cross.offspring_id,
        "planned_date": serialize_datetime(cross.planned_date),
        "executed_date": serialize_datetime(cross.executed_date),
        "status": serialize_enum(cross.status),
        "expected_outcomes": cross.expected_outcomes,
        "notes": cross.notes,
        "created_at": serialize_datetime(cross.created_at),
        "created_by_id": cross.created_by_id,
    }


def deserialize_cross(data: dict[str, Any], tenant_id: str) -> Cross:
    """Deserialize dict to Cross model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        Cross model instance.
    """
    return Cross(
        id=data["id"],
        tenant_id=tenant_id,
        name=data.get("name"),
        parent_female_id=data["parent_female_id"],
        parent_male_id=data["parent_male_id"],
        offspring_id=data.get("offspring_id"),
        planned_date=deserialize_datetime(data.get("planned_date")),
        executed_date=deserialize_datetime(data.get("executed_date")),
        status=CrossStatus(data["status"]) if data.get("status") else CrossStatus.PLANNED,
        expected_outcomes=data.get("expected_outcomes"),
        notes=data.get("notes"),
        created_at=deserialize_datetime(data.get("created_at")),
        created_by_id=data.get("created_by_id"),
    )


# --- ExternalReference Serialization ---


def serialize_external_reference(ref: ExternalReference) -> dict[str, Any]:
    """Serialize an ExternalReference model to dict.

    Args:
        ref: ExternalReference model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": ref.id,
        "stock_id": ref.stock_id,
        "source": ref.source,
        "external_id": ref.external_id,
        "data": ref.data,
        "fetched_at": serialize_datetime(ref.fetched_at),
    }


def deserialize_external_reference(data: dict[str, Any]) -> ExternalReference:
    """Deserialize dict to ExternalReference model.

    Args:
        data: Dict from backup file.

    Returns:
        ExternalReference model instance.
    """
    return ExternalReference(
        id=data["id"],
        stock_id=data["stock_id"],
        source=data["source"],
        external_id=data["external_id"],
        data=data.get("data"),
        fetched_at=deserialize_datetime(data.get("fetched_at")),
    )


# --- PrintAgent Serialization ---


def serialize_print_agent(agent: PrintAgent) -> dict[str, Any]:
    """Serialize a PrintAgent model to dict.

    Args:
        agent: PrintAgent model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": agent.id,
        "tenant_id": agent.tenant_id,
        "name": agent.name,
        "api_key": agent.api_key,
        "printer_name": agent.printer_name,
        "label_format": agent.label_format,
        "last_seen": serialize_datetime(agent.last_seen),
        "is_active": agent.is_active,
        "created_at": serialize_datetime(agent.created_at),
    }


def deserialize_print_agent(data: dict[str, Any], tenant_id: str) -> PrintAgent:
    """Deserialize dict to PrintAgent model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        PrintAgent model instance.
    """
    return PrintAgent(
        id=data["id"],
        tenant_id=tenant_id,
        name=data["name"],
        api_key=data["api_key"],
        printer_name=data.get("printer_name"),
        label_format=data.get("label_format", "dymo_11352"),
        last_seen=deserialize_datetime(data.get("last_seen")),
        is_active=data.get("is_active", True),
        created_at=deserialize_datetime(data.get("created_at")),
    )


# --- PrintJob Serialization ---


def serialize_print_job(job: PrintJob) -> dict[str, Any]:
    """Serialize a PrintJob model to dict.

    Args:
        job: PrintJob model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "agent_id": job.agent_id,
        "created_by_id": job.created_by_id,
        "status": serialize_enum(job.status),
        "stock_ids": job.stock_ids,
        "label_format": job.label_format,
        "copies": job.copies,
        "code_type": job.code_type,
        "created_at": serialize_datetime(job.created_at),
        "claimed_at": serialize_datetime(job.claimed_at),
        "completed_at": serialize_datetime(job.completed_at),
        "error_message": job.error_message,
    }


def deserialize_print_job(data: dict[str, Any], tenant_id: str) -> PrintJob:
    """Deserialize dict to PrintJob model.

    Args:
        data: Dict from backup file.
        tenant_id: Target tenant ID.

    Returns:
        PrintJob model instance.
    """
    return PrintJob(
        id=data["id"],
        tenant_id=tenant_id,
        agent_id=data.get("agent_id"),
        created_by_id=data.get("created_by_id"),
        status=PrintJobStatus(data["status"]) if data.get("status") else PrintJobStatus.PENDING,
        stock_ids=data.get("stock_ids", []),
        label_format=data.get("label_format", "dymo_11352"),
        copies=data.get("copies", 1),
        code_type=data.get("code_type", "qr"),
        created_at=deserialize_datetime(data.get("created_at")),
        claimed_at=deserialize_datetime(data.get("claimed_at")),
        completed_at=deserialize_datetime(data.get("completed_at")),
        error_message=data.get("error_message"),
    )


# --- FlipEvent Serialization ---


def serialize_flip_event(event: FlipEvent) -> dict[str, Any]:
    """Serialize a FlipEvent model to dict.

    Args:
        event: FlipEvent model instance.

    Returns:
        JSON-serializable dict.
    """
    return {
        "id": event.id,
        "stock_id": event.stock_id,
        "flipped_by_id": event.flipped_by_id,
        "flipped_at": serialize_datetime(event.flipped_at),
        "notes": event.notes,
        "created_at": serialize_datetime(event.created_at),
    }


def deserialize_flip_event(data: dict[str, Any]) -> FlipEvent:
    """Deserialize dict to FlipEvent model.

    Args:
        data: Dict from backup file.

    Returns:
        FlipEvent model instance.
    """
    return FlipEvent(
        id=data["id"],
        stock_id=data["stock_id"],
        flipped_by_id=data.get("flipped_by_id"),
        flipped_at=deserialize_datetime(data.get("flipped_at")),
        notes=data.get("notes"),
        created_at=deserialize_datetime(data.get("created_at")),
    )


# --- Bulk Export ---


def export_tenant_data(db: Session, tenant_id: str) -> dict[str, list[dict[str, Any]]]:
    """Export all data for a tenant in dependency order.

    Args:
        db: Database session.
        tenant_id: Tenant ID to export.

    Returns:
        Dict mapping table names to lists of serialized records.
    """
    data: dict[str, list[dict[str, Any]]] = {}

    # 1. Users
    users = db.query(User).filter(User.tenant_id == tenant_id).all()
    data["users"] = [serialize_user(u) for u in users]

    # 2. Trays
    trays = db.query(Tray).filter(Tray.tenant_id == tenant_id).all()
    data["trays"] = [serialize_tray(t) for t in trays]

    # 3. Tags
    tags = db.query(Tag).filter(Tag.tenant_id == tenant_id).all()
    data["tags"] = [serialize_tag(t) for t in tags]

    # 4. Stocks
    stocks = db.query(Stock).filter(Stock.tenant_id == tenant_id).all()
    data["stocks"] = [serialize_stock(s) for s in stocks]
    stock_ids = {s.id for s in stocks}

    # 5. StockTags (filtered by stocks in this tenant)
    stock_tags = db.query(StockTag).filter(StockTag.stock_id.in_(stock_ids)).all()
    data["stock_tags"] = [serialize_stock_tag(st) for st in stock_tags]

    # 6. Crosses
    crosses = db.query(Cross).filter(Cross.tenant_id == tenant_id).all()
    data["crosses"] = [serialize_cross(c) for c in crosses]

    # 7. ExternalReferences (filtered by stocks in this tenant)
    external_refs = (
        db.query(ExternalReference).filter(ExternalReference.stock_id.in_(stock_ids)).all()
    )
    data["external_references"] = [serialize_external_reference(r) for r in external_refs]

    # 8. PrintAgents
    print_agents = db.query(PrintAgent).filter(PrintAgent.tenant_id == tenant_id).all()
    data["print_agents"] = [serialize_print_agent(a) for a in print_agents]

    # 9. PrintJobs
    print_jobs = db.query(PrintJob).filter(PrintJob.tenant_id == tenant_id).all()
    data["print_jobs"] = [serialize_print_job(j) for j in print_jobs]

    # 10. FlipEvents (filtered by stocks in this tenant)
    flip_events = db.query(FlipEvent).filter(FlipEvent.stock_id.in_(stock_ids)).all()
    data["flip_events"] = [serialize_flip_event(e) for e in flip_events]

    return data
