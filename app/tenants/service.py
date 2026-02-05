"""Tenant service layer for admin operations."""

import secrets

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.utils import get_password_hash
from app.db.models import Stock, Tenant, User
from app.tenants.schemas import (
    OrganizationInfo,
    TenantResponse,
    UserInvite,
    UserListResponse,
    UserUpdateAdmin,
)


class TenantService:
    """Service class for tenant administration operations."""

    def __init__(self, db: Session, tenant_id: str):
        """Initialize tenant service.

        Args:
            db: Database session.
            tenant_id: Current tenant ID.
        """
        self.db = db
        self.tenant_id = tenant_id

    def get_tenant(self) -> Tenant | None:
        """Get current tenant.

        Returns:
            Tenant | None: Tenant if found.
        """
        return self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()

    def get_tenant_info(self) -> TenantResponse | None:
        """Get tenant information with counts.

        Returns:
            TenantResponse | None: Tenant info if found.
        """
        tenant = self.get_tenant()
        if not tenant:
            return None

        user_count = (
            self.db.query(func.count(User.id)).filter(User.tenant_id == self.tenant_id).scalar()
        )

        stock_count = (
            self.db.query(func.count(Stock.id))
            .filter(Stock.tenant_id == self.tenant_id, Stock.is_active)
            .scalar()
        )

        org_info = None
        if tenant.organization:
            org_info = OrganizationInfo(
                id=tenant.organization.id,
                name=tenant.organization.name,
                slug=tenant.organization.slug,
            )

        return TenantResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            user_count=user_count,
            stock_count=stock_count,
            organization=org_info,
            is_org_admin=tenant.is_org_admin,
            city=tenant.city,
            country=tenant.country,
            latitude=tenant.latitude,
            longitude=tenant.longitude,
        )

    def update_tenant(self, name: str | None = None) -> Tenant | None:
        """Update tenant information.

        Args:
            name: New tenant name.

        Returns:
            Tenant | None: Updated tenant if found.
        """
        tenant = self.get_tenant()
        if not tenant:
            return None

        if name:
            tenant.name = name

        self.db.commit()
        self.db.refresh(tenant)
        return tenant

    def list_users(self) -> list[UserListResponse]:
        """List all users in the tenant.

        Returns:
            list[UserListResponse]: List of users.
        """
        users = (
            self.db.query(User)
            .filter(User.tenant_id == self.tenant_id)
            .order_by(User.created_at.desc())
            .all()
        )

        return [
            UserListResponse(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role.value,
                is_active=u.is_active,
                created_at=u.created_at,
                last_login=u.last_login,
            )
            for u in users
        ]

    def get_user(self, user_id: str) -> User | None:
        """Get a user by ID.

        Args:
            user_id: User UUID.

        Returns:
            User | None: User if found.
        """
        return (
            self.db.query(User).filter(User.id == user_id, User.tenant_id == self.tenant_id).first()
        )

    def invite_user(self, data: UserInvite) -> tuple[User, str]:
        """Invite a new user to the tenant.

        Args:
            data: User invitation data.

        Returns:
            tuple: Created user and temporary password.

        Raises:
            ValueError: If email already exists.
        """
        # Check if email exists in tenant
        existing = (
            self.db.query(User)
            .filter(User.tenant_id == self.tenant_id, User.email == data.email)
            .first()
        )
        if existing:
            raise ValueError("Email already exists in this organization")

        # Generate temporary password
        temp_password = secrets.token_urlsafe(12)

        user = User(
            tenant_id=self.tenant_id,
            email=data.email,
            password_hash=get_password_hash(temp_password),
            full_name=data.full_name,
            role=data.role,
            is_active=True,
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        return user, temp_password

    def update_user(self, user_id: str, data: UserUpdateAdmin) -> User | None:
        """Update a user.

        Args:
            user_id: User UUID.
            data: Update data.

        Returns:
            User | None: Updated user if found.

        Raises:
            ValueError: If email already in use.
        """
        user = self.get_user(user_id)
        if not user:
            return None

        if data.email and data.email != user.email:
            existing = (
                self.db.query(User)
                .filter(User.tenant_id == self.tenant_id, User.email == data.email)
                .first()
            )
            if existing:
                raise ValueError("Email already in use")
            user.email = data.email

        if data.full_name:
            user.full_name = data.full_name
        if data.role is not None:
            user.role = data.role
        if data.is_active is not None:
            user.is_active = data.is_active

        self.db.commit()
        self.db.refresh(user)
        return user

    def deactivate_user(self, user_id: str) -> bool:
        """Deactivate a user.

        Args:
            user_id: User UUID.

        Returns:
            bool: True if deactivated, False if not found.
        """
        user = self.get_user(user_id)
        if not user:
            return False

        user.is_active = False
        self.db.commit()
        return True

    def reset_user_password(self, user_id: str) -> str | None:
        """Reset a user's password.

        Args:
            user_id: User UUID.

        Returns:
            str | None: New temporary password if user found.
        """
        user = self.get_user(user_id)
        if not user:
            return None

        temp_password = secrets.token_urlsafe(12)
        user.password_hash = get_password_hash(temp_password)
        self.db.commit()

        return temp_password


def get_tenant_service(db: Session, tenant_id: str) -> TenantService:
    """Factory function for TenantService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        TenantService: Tenant service instance.
    """
    return TenantService(db, tenant_id)
