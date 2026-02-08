"""SQLAlchemy database models."""

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def generate_uuid() -> str:
    """Generate a UUID string for primary keys.

    Returns:
        str: UUID as 36-character string.
    """
    return str(uuid4())


class UserRole(str, enum.Enum):
    """User role enumeration."""

    ADMIN = "admin"
    USER = "user"


class UserStatus(str, enum.Enum):
    """User approval status enumeration."""

    PENDING = "pending"  # Awaiting admin approval
    APPROVED = "approved"  # Approved and can use system
    REJECTED = "rejected"  # Rejected by admin


class CrossStatus(str, enum.Enum):
    """Cross status enumeration."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class OrgJoinRequestStatus(str, enum.Enum):
    """Organization join request status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TrayType(str, enum.Enum):
    """Tray type enumeration."""

    NUMERIC = "numeric"  # Simple numbered positions (1, 2, 3...)
    GRID = "grid"  # Grid positions (A1, A2, B1...)
    CUSTOM = "custom"  # User-defined position names


class StockOrigin(str, enum.Enum):
    """Stock origin type enumeration."""

    REPOSITORY = "repository"  # From a public stock center (BDSC, VDRC, etc.)
    INTERNAL = "internal"  # Created/generated in our lab
    EXTERNAL = "external"  # Received from another lab/researcher


class StockRepository(str, enum.Enum):
    """Public Drosophila stock repositories."""

    BDSC = "bdsc"  # Bloomington Drosophila Stock Center (USA)
    VDRC = "vdrc"  # Vienna Drosophila Resource Center (Austria)
    KYOTO = "kyoto"  # Kyoto DGRC (Japan)
    NIG = "nig"  # National Institute of Genetics NIG-Fly (Japan)
    DGRC = "dgrc"  # Drosophila Genomics Resource Center (Indiana)
    FLYORF = "flyorf"  # FlyORF Zurich ORFeome
    TRIP = "trip"  # Transgenic RNAi Project (Harvard)
    EXELIXIS = "exelixis"  # Exelixis Collection (Harvard)
    OTHER = "other"  # Other repository


class StockVisibility(str, enum.Enum):
    """Stock visibility level enumeration."""

    LAB_ONLY = "lab_only"  # Only visible within this lab
    ORGANIZATION = "organization"  # Visible to all labs in same org
    PUBLIC = "public"  # Visible to all users (for exchange)


class StockRequestStatus(str, enum.Enum):
    """Stock request status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class PrintJobStatus(str, enum.Enum):
    """Print job status enumeration."""

    PENDING = "pending"  # Waiting for agent to pick up
    CLAIMED = "claimed"  # Agent has claimed the job
    PRINTING = "printing"  # Currently printing
    COMPLETED = "completed"  # Successfully printed
    FAILED = "failed"  # Print failed
    CANCELLED = "cancelled"  # User cancelled


class FlipStatus(str, enum.Enum):
    """Stock flip status enumeration based on days since last flip."""

    OK = "ok"  # Recently flipped, within warning threshold
    WARNING = "warning"  # Approaching critical threshold
    CRITICAL = "critical"  # Past critical threshold, needs immediate attention
    NEVER = "never"  # Never been flipped


class Organization(Base):
    """Organization model representing a parent entity for labs.

    Attributes:
        id: Primary key UUID.
        name: Organization name (e.g., "Imperial College London").
        slug: URL-friendly identifier.
        normalized_name: Lowercase, stripped name for duplicate detection.
        description: Optional description.
        website: Optional website URL.
        is_active: Whether the organization is active.
        created_at: Creation timestamp.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    tenants: Mapped[list["Tenant"]] = relationship("Tenant", back_populates="organization")
    join_requests: Mapped[list["OrganizationJoinRequest"]] = relationship(
        "OrganizationJoinRequest",
        back_populates="organization",
        foreign_keys="OrganizationJoinRequest.organization_id",
    )


class Tenant(Base):
    """Tenant model representing a lab/organization.

    Attributes:
        id: Primary key UUID.
        name: Lab/organization name.
        slug: URL-friendly identifier.
        organization_id: Optional FK to parent organization.
        is_org_admin: Whether this lab can manage org settings/approve joins.
        city: Lab city for geographic location.
        country: Lab country for geographic location.
        latitude: Optional latitude for mapping.
        longitude: Optional longitude for mapping.
        is_active: Whether the tenant is active.
        created_at: Creation timestamp.
        invitation_token: Token for direct join links.
        invitation_token_created_at: When the invitation token was created.
    """

    __tablename__ = "tenants"
    __table_args__ = (Index("ix_tenants_organization_id", "organization_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    organization_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    is_org_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    invitation_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    invitation_token_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Label/print settings (admin-configured defaults for this tenant)
    default_label_format: Mapped[str] = mapped_column(
        String(50), default="dymo_11352", server_default="dymo_11352"
    )
    default_code_type: Mapped[str] = mapped_column(String(20), default="qr", server_default="qr")
    default_copies: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    default_orientation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Flip tracking settings
    flip_warning_days: Mapped[int] = mapped_column(Integer, default=21, server_default="21")
    flip_critical_days: Mapped[int] = mapped_column(Integer, default=31, server_default="31")
    flip_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="tenants"
    )
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    stocks: Mapped[list["Stock"]] = relationship(
        "Stock", back_populates="tenant", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", back_populates="tenant", cascade="all, delete-orphan"
    )
    crosses: Mapped[list["Cross"]] = relationship(
        "Cross", back_populates="tenant", cascade="all, delete-orphan"
    )
    trays: Mapped[list["Tray"]] = relationship(
        "Tray", back_populates="tenant", cascade="all, delete-orphan"
    )
    join_requests: Mapped[list["OrganizationJoinRequest"]] = relationship(
        "OrganizationJoinRequest",
        back_populates="tenant",
        foreign_keys="OrganizationJoinRequest.tenant_id",
    )


class User(Base):
    """User model.

    Attributes:
        id: Primary key UUID.
        tenant_id: Foreign key to tenant.
        email: User email (unique per tenant).
        password_hash: Hashed password.
        full_name: User's full name.
        role: User role (admin/user).
        is_active: Whether the user is active.
        created_at: Creation timestamp.
        last_login: Last login timestamp.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        Index("ix_users_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]), default=UserRole.USER
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, values_callable=lambda x: [e.value for e in x]), default=UserStatus.PENDING
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    password_reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Email verification
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verification_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")
    created_stocks: Mapped[list["Stock"]] = relationship(
        "Stock",
        back_populates="created_by",
        foreign_keys="Stock.created_by_id",
    )
    modified_stocks: Mapped[list["Stock"]] = relationship(
        "Stock",
        back_populates="modified_by",
        foreign_keys="Stock.modified_by_id",
    )
    created_crosses: Mapped[list["Cross"]] = relationship("Cross", back_populates="created_by")
    owned_stocks: Mapped[list["Stock"]] = relationship(
        "Stock",
        back_populates="owner",
        foreign_keys="Stock.owner_id",
    )


class OrganizationJoinRequest(Base):
    """Organization join request model.

    Attributes:
        id: Primary key UUID.
        organization_id: FK to organization being requested to join.
        tenant_id: FK to lab requesting to join.
        requested_by_id: FK to user who made the request.
        status: Request status (pending, approved, rejected).
        message: Optional message from requester.
        created_at: Creation timestamp.
        responded_at: When the request was responded to.
        responded_by_id: FK to user who responded.
    """

    __tablename__ = "organization_join_requests"
    __table_args__ = (
        Index("ix_org_join_requests_org_id", "organization_id"),
        Index("ix_org_join_requests_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[OrgJoinRequestStatus] = mapped_column(
        Enum(OrgJoinRequestStatus, values_callable=lambda x: [e.value for e in x]),
        default=OrgJoinRequestStatus.PENDING,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="join_requests",
        foreign_keys=[organization_id],
    )
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="join_requests",
        foreign_keys=[tenant_id],
    )
    requested_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[requested_by_id])
    responded_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[responded_by_id])


class Tray(Base):
    """Tray model for physical stock location organization.

    Attributes:
        id: Primary key UUID.
        tenant_id: FK to tenant.
        name: Tray name (unique per tenant).
        description: Optional description.
        tray_type: Type of tray (numeric, grid, custom).
        max_positions: Maximum number of positions.
        rows: Number of rows (for grid type).
        cols: Number of columns (for grid type).
        created_at: Creation timestamp.
    """

    __tablename__ = "trays"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tray_tenant_name"),
        Index("ix_trays_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tray_type: Mapped[TrayType] = mapped_column(
        Enum(TrayType, values_callable=lambda x: [e.value for e in x]), default=TrayType.NUMERIC
    )
    max_positions: Mapped[int] = mapped_column(Integer, default=100)
    rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="trays")
    stocks: Mapped[list["Stock"]] = relationship("Stock", back_populates="tray")


class Stock(Base):
    """Stock model for fly stocks.

    Attributes:
        id: Primary key UUID.
        tenant_id: Foreign key to tenant (lab).
        stock_id: Human-readable stock ID (e.g., "BL-1234").
        genotype: Full genotype string.

        Origin/Source fields:
        origin: Where the stock came from (repository, internal, external).
        repository: Public repository if origin=repository (BDSC, VDRC, etc.).
        repository_stock_id: Stock ID in the public repository.
        external_source: Lab/researcher name if origin=external.
        original_genotype: Original genotype from repository (before modifications).

        Physical location:
        tray_id: FK to tray for physical location.
        position: Position within tray (e.g., "42" or "A3").

        Ownership and visibility:
        owner_id: FK to user who maintains the stock.
        visibility: Visibility level (lab_only, organization, public).
        hide_from_org: Override to hide from org even if visibility allows.

        Metadata:
        notes: Additional notes.
        is_active: Whether the stock is active (soft delete).
        created_at: Creation timestamp.
        created_by_id: Foreign key to user who created record.
        modified_at: Last modification timestamp.
        modified_by_id: Foreign key to user who last modified.
        external_metadata: JSON for storing repository-specific data.
    """

    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "stock_id", name="uq_stock_tenant_stock_id"),
        Index("ix_stocks_tenant_id", "tenant_id"),
        Index("ix_stocks_genotype", "genotype", mysql_length=100),
        Index("ix_stocks_tray_id", "tray_id"),
        Index("ix_stocks_visibility", "visibility"),
        Index("ix_stocks_origin", "origin"),
        Index("ix_stocks_repository", "repository"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    stock_id: Mapped[str] = mapped_column(String(100), nullable=False)
    genotype: Mapped[str] = mapped_column(Text, nullable=False)

    # Origin/Source tracking
    origin: Mapped[StockOrigin] = mapped_column(
        Enum(StockOrigin, values_callable=lambda x: [e.value for e in x]),
        default=StockOrigin.INTERNAL,
    )
    repository: Mapped[StockRepository | None] = mapped_column(
        Enum(StockRepository, values_callable=lambda x: [e.value for e in x]), nullable=True
    )  # Only set if origin=repository
    repository_stock_id: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # e.g., "3605" for BDSC#3605
    external_source: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Lab/researcher name if origin=external
    original_genotype: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Original genotype from repository (before any local modifications)

    # Physical location
    tray_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("trays.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Ownership and visibility
    owner_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[StockVisibility] = mapped_column(
        Enum(StockVisibility, values_callable=lambda x: [e.value for e in x]),
        default=StockVisibility.LAB_ONLY,
    )
    hide_from_org: Mapped[bool] = mapped_column(Boolean, default=False)

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    modified_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    external_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="stocks")
    tray: Mapped[Optional["Tray"]] = relationship("Tray", back_populates="stocks")
    owner: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="owned_stocks",
        foreign_keys=[owner_id],
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="created_stocks",
        foreign_keys=[created_by_id],
    )
    modified_by: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="modified_stocks",
        foreign_keys=[modified_by_id],
    )
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary="stock_tags", back_populates="stocks")
    external_references: Mapped[list["ExternalReference"]] = relationship(
        "ExternalReference", back_populates="stock", cascade="all, delete-orphan"
    )
    stock_requests: Mapped[list["StockRequest"]] = relationship(
        "StockRequest", back_populates="stock", cascade="all, delete-orphan"
    )
    # Crosses where this stock is a parent
    crosses_as_female: Mapped[list["Cross"]] = relationship(
        "Cross",
        back_populates="parent_female",
        foreign_keys="Cross.parent_female_id",
    )
    crosses_as_male: Mapped[list["Cross"]] = relationship(
        "Cross",
        back_populates="parent_male",
        foreign_keys="Cross.parent_male_id",
    )
    crosses_as_offspring: Mapped[list["Cross"]] = relationship(
        "Cross",
        back_populates="offspring",
        foreign_keys="Cross.offspring_id",
    )
    flip_events: Mapped[list["FlipEvent"]] = relationship(
        "FlipEvent",
        back_populates="stock",
        cascade="all, delete-orphan",
        order_by="FlipEvent.flipped_at.desc()",
    )


class Tag(Base):
    """Tag model for categorizing stocks.

    Attributes:
        id: Primary key UUID.
        tenant_id: Foreign key to tenant.
        name: Tag name.
        color: Hex color code.
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tag_tenant_name"),
        Index("ix_tags_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="tags")
    stocks: Mapped[list["Stock"]] = relationship(
        "Stock", secondary="stock_tags", back_populates="tags"
    )


class StockTag(Base):
    """Association table for Stock-Tag many-to-many relationship."""

    __tablename__ = "stock_tags"

    stock_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("stocks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Cross(Base):
    """Cross model for tracking fly crosses.

    Attributes:
        id: Primary key UUID.
        tenant_id: Foreign key to tenant.
        name: Optional cross name.
        parent_female_id: Foreign key to female parent stock.
        parent_male_id: Foreign key to male parent stock.
        offspring_id: Foreign key to offspring stock (when completed).
        planned_date: Planned date for cross.
        executed_date: Actual execution date.
        status: Cross status.
        expected_outcomes: JSON field for predicted genotypes (future).
        notes: Additional notes.
        created_at: Creation timestamp.
        created_by_id: Foreign key to user who created.
    """

    __tablename__ = "crosses"
    __table_args__ = (Index("ix_crosses_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_female_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    parent_male_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="RESTRICT"), nullable=False
    )
    offspring_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="SET NULL"), nullable=True
    )
    planned_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[CrossStatus] = mapped_column(
        Enum(CrossStatus, values_callable=lambda x: [e.value for e in x]),
        default=CrossStatus.PLANNED,
    )
    expected_outcomes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="crosses")
    parent_female: Mapped["Stock"] = relationship(
        "Stock",
        back_populates="crosses_as_female",
        foreign_keys=[parent_female_id],
    )
    parent_male: Mapped["Stock"] = relationship(
        "Stock",
        back_populates="crosses_as_male",
        foreign_keys=[parent_male_id],
    )
    offspring: Mapped[Optional["Stock"]] = relationship(
        "Stock",
        back_populates="crosses_as_offspring",
        foreign_keys=[offspring_id],
    )
    created_by: Mapped[Optional["User"]] = relationship("User", back_populates="created_crosses")


class ExternalReference(Base):
    """External reference model for linking stocks to external databases.

    Attributes:
        id: Primary key UUID.
        stock_id: Foreign key to stock.
        source: Source database (e.g., "bdsc", "flybase", "vdrc").
        external_id: ID in the external system.
        data: Cached external data.
        fetched_at: When the data was fetched.
    """

    __tablename__ = "external_references"
    __table_args__ = (UniqueConstraint("stock_id", "source", name="uq_extref_stock_source"),)

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    stock_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    stock: Mapped["Stock"] = relationship("Stock", back_populates="external_references")


class StockRequest(Base):
    """Stock request model for cross-lab stock sharing.

    Attributes:
        id: Primary key UUID.
        stock_id: FK to requested stock.
        requester_user_id: FK to user making the request.
        requester_tenant_id: FK to lab making the request.
        owner_tenant_id: FK to lab that owns the stock.
        status: Request status (pending, approved, rejected, fulfilled, cancelled).
        message: Optional message from requester.
        response_message: Optional response from owner.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        responded_at: When the request was responded to.
        responded_by_id: FK to user who responded.
    """

    __tablename__ = "stock_requests"
    __table_args__ = (
        Index("ix_stock_requests_stock_id", "stock_id"),
        Index("ix_stock_requests_requester_tenant_id", "requester_tenant_id"),
        Index("ix_stock_requests_owner_tenant_id", "owner_tenant_id"),
        Index("ix_stock_requests_status", "status"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    stock_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    requester_user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requester_tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    owner_tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[StockRequestStatus] = mapped_column(
        Enum(StockRequestStatus, values_callable=lambda x: [e.value for e in x]),
        default=StockRequestStatus.PENDING,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    stock: Mapped["Stock"] = relationship("Stock", back_populates="stock_requests")
    requester_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[requester_user_id]
    )
    requester_tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[requester_tenant_id])
    owner_tenant: Mapped["Tenant"] = relationship("Tenant", foreign_keys=[owner_tenant_id])
    responded_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[responded_by_id])


class PrintAgent(Base):
    """Print agent model representing a local print client.

    Print agents run on lab machines (e.g., Raspberry Pi) and poll
    the server for print jobs, then print via local CUPS.

    Attributes:
        id: Primary key UUID.
        tenant_id: FK to tenant that owns this agent.
        name: User-friendly name (e.g., "Lab Pi", "John's Desktop").
        api_key: Secret key for agent authentication.
        printer_name: CUPS printer name configured on the agent.
        label_format: Default label format for this agent.
        last_seen: Last time agent checked in.
        is_active: Whether the agent is enabled.
        created_at: Creation timestamp.
    """

    __tablename__ = "print_agents"
    __table_args__ = (
        Index("ix_print_agents_tenant_id", "tenant_id"),
        Index("ix_print_agents_api_key", "api_key"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    printer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    label_format: Mapped[str] = mapped_column(String(50), default="dymo_11352")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    poll_interval: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    log_level: Mapped[str] = mapped_column(String(10), default="INFO", server_default="INFO")
    available_printers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", backref="print_agents")
    print_jobs: Mapped[list["PrintJob"]] = relationship(
        "PrintJob", back_populates="agent", foreign_keys="PrintJob.agent_id"
    )


class PrintJob(Base):
    """Print job model for queued label printing.

    Print jobs are created by users and picked up by print agents.

    Attributes:
        id: Primary key UUID.
        tenant_id: FK to tenant.
        agent_id: FK to agent that claimed/printed this job (nullable).
        created_by_id: FK to user who created the job.
        status: Job status (pending, claimed, printing, completed, failed).
        stock_ids: JSON list of stock UUIDs to print.
        label_format: Label format to use.
        copies: Number of copies per label.
        created_at: Creation timestamp.
        claimed_at: When an agent claimed the job.
        completed_at: When printing completed.
        error_message: Error message if failed.
    """

    __tablename__ = "print_jobs"
    __table_args__ = (
        Index("ix_print_jobs_tenant_id", "tenant_id"),
        Index("ix_print_jobs_status", "status"),
        Index("ix_print_jobs_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("print_agents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[PrintJobStatus] = mapped_column(
        Enum(PrintJobStatus, values_callable=lambda x: [e.value for e in x]),
        default=PrintJobStatus.PENDING,
    )
    stock_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    label_format: Mapped[str] = mapped_column(String(50), default="dymo_11352")
    copies: Mapped[int] = mapped_column(Integer, default=1)
    code_type: Mapped[str] = mapped_column(String(20), default="qr")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", backref="print_jobs")
    agent: Mapped[Optional["PrintAgent"]] = relationship(
        "PrintAgent", back_populates="print_jobs", foreign_keys=[agent_id]
    )
    created_by: Mapped[Optional["User"]] = relationship("User")


class FlipEvent(Base):
    """Flip event model for tracking when stocks are transferred to fresh food.

    Attributes:
        id: Primary key UUID.
        stock_id: FK to stock that was flipped.
        flipped_by_id: FK to user who performed the flip.
        flipped_at: When the flip was performed.
        notes: Optional notes about the flip.
        created_at: Record creation timestamp.
    """

    __tablename__ = "flip_events"
    __table_args__ = (
        Index("ix_flip_events_stock_id", "stock_id"),
        Index("ix_flip_events_flipped_at", "flipped_at"),
    )

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=generate_uuid)
    stock_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False
    )
    flipped_by_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    flipped_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    stock: Mapped["Stock"] = relationship("Stock", back_populates="flip_events")
    flipped_by: Mapped[Optional["User"]] = relationship("User")
