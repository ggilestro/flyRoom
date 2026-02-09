"""Tenant service layer for admin operations."""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.utils import get_password_hash
from app.db.models import Invitation, InvitationStatus, InvitationType, Stock, Tenant, User
from app.tenants.schemas import (
    InvitationCreate,
    InvitationResponse,
    InvitationValidation,
    OrganizationInfo,
    TenantResponse,
    UserInvite,
    UserListResponse,
    UserUpdateAdmin,
)

logger = logging.getLogger(__name__)


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

    # --- Invitation Methods ---

    def create_invitation(
        self, data: InvitationCreate, invited_by_id: str, base_url: str
    ) -> InvitationResponse:
        """Create and send an email invitation.

        Args:
            data: Invitation data (email, type).
            invited_by_id: ID of the admin sending the invitation.
            base_url: Base URL for building the registration link.

        Returns:
            InvitationResponse: Created invitation.

        Raises:
            ValueError: If validation fails.
        """
        tenant = self.get_tenant()
        if not tenant:
            raise ValueError("Tenant not found")

        inv_type = InvitationType(data.invitation_type)

        # NEW_TENANT requires tenant to be in an organization
        if inv_type == InvitationType.NEW_TENANT and not tenant.organization_id:
            raise ValueError(
                "Cannot invite for new tenant: your lab is not part of an organization"
            )

        # Check for duplicate pending invitation
        existing = (
            self.db.query(Invitation)
            .filter(
                Invitation.tenant_id == self.tenant_id,
                Invitation.email == data.email,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.invitation_type == inv_type,
            )
            .first()
        )
        if existing:
            raise ValueError(f"A pending invitation already exists for {data.email}")

        # For LAB_MEMBER, check email not already a member
        if inv_type == InvitationType.LAB_MEMBER:
            existing_user = (
                self.db.query(User)
                .filter(User.tenant_id == self.tenant_id, User.email == data.email)
                .first()
            )
            if existing_user:
                raise ValueError(f"{data.email} is already a member of this lab")

        # Create invitation
        token = secrets.token_hex(32)
        invitation = Invitation(
            tenant_id=self.tenant_id,
            invited_by_id=invited_by_id,
            email=data.email,
            invitation_type=inv_type,
            token=token,
            status=InvitationStatus.PENDING,
            organization_id=tenant.organization_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.db.add(invitation)
        self.db.commit()
        self.db.refresh(invitation)

        # Send invitation email
        inviter = self.db.query(User).filter(User.id == invited_by_id).first()
        inviter_name = inviter.full_name if inviter else "An administrator"
        org_name = tenant.organization.name if tenant.organization else None
        registration_url = f"{base_url}/register?invitation={token}"

        try:
            from app.email.service import get_email_service

            email_service = get_email_service()
            email_service.send_invitation_email(
                to_email=data.email,
                invitation_type=data.invitation_type,
                inviter_name=inviter_name,
                tenant_name=tenant.name,
                organization_name=org_name,
                registration_url=registration_url,
            )
        except Exception as e:
            logger.warning(f"Failed to send invitation email to {data.email}: {e}")

        return InvitationResponse(
            id=invitation.id,
            email=invitation.email,
            invitation_type=invitation.invitation_type.value,
            status=invitation.status.value,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            invited_by_name=inviter_name,
        )

    def list_invitations(self) -> list[InvitationResponse]:
        """List all invitations for the tenant, marking expired ones.

        Returns:
            list[InvitationResponse]: List of invitations.
        """
        invitations = (
            self.db.query(Invitation)
            .filter(Invitation.tenant_id == self.tenant_id)
            .order_by(Invitation.created_at.desc())
            .all()
        )

        now = datetime.now(UTC)
        result = []
        for inv in invitations:
            # Auto-expire pending invitations past their expiry
            expires_at = inv.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if inv.status == InvitationStatus.PENDING and now > expires_at:
                inv.status = InvitationStatus.EXPIRED
                self.db.commit()

            inviter = self.db.query(User).filter(User.id == inv.invited_by_id).first()
            result.append(
                InvitationResponse(
                    id=inv.id,
                    email=inv.email,
                    invitation_type=inv.invitation_type.value,
                    status=inv.status.value,
                    created_at=inv.created_at,
                    expires_at=inv.expires_at,
                    invited_by_name=inviter.full_name if inviter else None,
                )
            )
        return result

    def cancel_invitation(self, invitation_id: str) -> bool:
        """Cancel a pending invitation.

        Args:
            invitation_id: Invitation UUID.

        Returns:
            bool: True if cancelled, False if not found.
        """
        invitation = (
            self.db.query(Invitation)
            .filter(
                Invitation.id == invitation_id,
                Invitation.tenant_id == self.tenant_id,
                Invitation.status == InvitationStatus.PENDING,
            )
            .first()
        )
        if not invitation:
            return False

        invitation.status = InvitationStatus.CANCELLED
        self.db.commit()
        return True

    def resend_invitation(self, invitation_id: str, base_url: str) -> bool:
        """Resend a pending invitation email and extend expiry.

        Args:
            invitation_id: Invitation UUID.
            base_url: Base URL for building the registration link.

        Returns:
            bool: True if resent, False if not found.
        """
        invitation = (
            self.db.query(Invitation)
            .filter(
                Invitation.id == invitation_id,
                Invitation.tenant_id == self.tenant_id,
                Invitation.status == InvitationStatus.PENDING,
            )
            .first()
        )
        if not invitation:
            return False

        # Extend expiry
        invitation.expires_at = datetime.now(UTC) + timedelta(days=7)
        self.db.commit()

        # Resend email
        tenant = self.get_tenant()
        inviter = self.db.query(User).filter(User.id == invitation.invited_by_id).first()
        inviter_name = inviter.full_name if inviter else "An administrator"
        org_name = tenant.organization.name if tenant and tenant.organization else None
        registration_url = f"{base_url}/register?invitation={invitation.token}"

        try:
            from app.email.service import get_email_service

            email_service = get_email_service()
            email_service.send_invitation_email(
                to_email=invitation.email,
                invitation_type=invitation.invitation_type.value,
                inviter_name=inviter_name,
                tenant_name=tenant.name if tenant else "",
                organization_name=org_name,
                registration_url=registration_url,
            )
        except Exception as e:
            logger.warning(f"Failed to resend invitation email to {invitation.email}: {e}")

        return True

    # --- Static methods for registration flow ---

    @staticmethod
    def validate_invitation_token(db: Session, token: str) -> Invitation | None:
        """Find a pending, non-expired invitation by token.

        Args:
            db: Database session.
            token: Invitation token.

        Returns:
            Invitation | None: Valid invitation if found.
        """
        invitation = (
            db.query(Invitation)
            .filter(
                Invitation.token == token,
                Invitation.status == InvitationStatus.PENDING,
            )
            .first()
        )
        if not invitation:
            return None

        # Check expiry
        expires_at = invitation.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            invitation.status = InvitationStatus.EXPIRED
            db.commit()
            return None

        return invitation

    @staticmethod
    def accept_invitation(db: Session, token: str) -> Invitation | None:
        """Mark an invitation as accepted.

        Args:
            db: Database session.
            token: Invitation token.

        Returns:
            Invitation | None: Accepted invitation if found.
        """
        invitation = TenantService.validate_invitation_token(db, token)
        if not invitation:
            return None

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(UTC)
        db.commit()
        return invitation

    @staticmethod
    def get_invitation_validation(db: Session, token: str) -> InvitationValidation | None:
        """Get invitation details for the registration page.

        Args:
            db: Database session.
            token: Invitation token.

        Returns:
            InvitationValidation | None: Invitation details if valid.
        """
        invitation = TenantService.validate_invitation_token(db, token)
        if not invitation:
            return None

        tenant = db.query(Tenant).filter(Tenant.id == invitation.tenant_id).first()
        if not tenant:
            return None

        from app.db.models import Organization

        org_name = None
        if invitation.organization_id:
            org = (
                db.query(Organization).filter(Organization.id == invitation.organization_id).first()
            )
            org_name = org.name if org else None

        return InvitationValidation(
            email=invitation.email,
            invitation_type=invitation.invitation_type.value,
            tenant_name=tenant.name,
            organization_name=org_name,
        )


def get_tenant_service(db: Session, tenant_id: str) -> TenantService:
    """Factory function for TenantService.

    Args:
        db: Database session.
        tenant_id: Tenant ID.

    Returns:
        TenantService: Tenant service instance.
    """
    return TenantService(db, tenant_id)
