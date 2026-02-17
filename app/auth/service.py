"""Authentication service layer."""

import logging
import re
import secrets
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.auth.schemas import (
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.auth.utils import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from app.db.models import Tenant, User, UserRole, UserStatus
from app.email.service import get_email_service

logger = logging.getLogger(__name__)


class AuthService:
    """Service class for authentication operations."""

    def __init__(self, db: Session):
        """Initialize auth service.

        Args:
            db: Database session.
        """
        self.db = db

    def _create_slug(self, name: str) -> str:
        """Create a URL-friendly slug from organization name.

        Args:
            name: Organization name.

        Returns:
            str: URL-friendly slug.
        """
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")

        # Ensure uniqueness
        base_slug = slug
        counter = 1
        while self.db.query(Tenant).filter(Tenant.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug

    def _generate_invitation_token(self) -> str:
        """Generate a secure invitation token.

        Returns:
            str: 32-character hex token.
        """
        return secrets.token_hex(32)

    def _generate_verification_token(self) -> str:
        """Generate a secure email verification token.

        Returns:
            str: 32-character hex token.
        """
        return secrets.token_hex(32)

    def send_verification_email(self, user: User, base_url: str) -> bool:
        """Send email verification to user.

        Args:
            user: User to send verification to.
            base_url: Base URL of the application.

        Returns:
            bool: True if email sent successfully.
        """
        # Generate new token
        user.email_verification_token = self._generate_verification_token()
        user.email_verification_sent_at = datetime.now(UTC)
        self.db.commit()

        verification_url = f"{base_url}/verify-email?token={user.email_verification_token}"

        try:
            email_service = get_email_service()
            return email_service.send_verification_email(
                user.email, user.full_name, verification_url
            )
        except Exception as e:
            logger.warning(f"Failed to send verification email to {user.email}: {e}")
            return False

    def verify_email(self, token: str) -> tuple[User | None, str]:
        """Verify user's email address.

        Args:
            token: Email verification token.

        Returns:
            tuple: (User or None, status message).
        """
        user = self.db.query(User).filter(User.email_verification_token == token).first()

        if not user:
            return None, "Invalid verification link."

        # Check if token is expired (24 hours)
        if user.email_verification_sent_at:
            from datetime import timedelta

            sent_at = user.email_verification_sent_at
            # Handle timezone-naive datetime from database
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            expiry = sent_at + timedelta(hours=24)
            if datetime.now(UTC) > expiry:
                return None, "Verification link has expired. Please request a new one."

        # Mark as verified
        user.is_email_verified = True
        user.email_verification_token = None
        user.email_verification_sent_at = None
        self.db.commit()

        return user, "Email verified successfully! You can now log in."

    def _find_tenant_by_name(self, name: str) -> Tenant | None:
        """Find a tenant by name (case-insensitive).

        Args:
            name: Organization name.

        Returns:
            Tenant if found, None otherwise.
        """
        return self.db.query(Tenant).filter(Tenant.name.ilike(name)).first()

    def _find_tenant_by_pi(self, pi_identifier: str) -> tuple[Tenant, User] | None:
        """Find a tenant by PI's name or email.

        Args:
            pi_identifier: PI's full name or email address.

        Returns:
            Tuple of (Tenant, PI User) if found, None otherwise.
        """
        # Try to find by email first (exact match)
        pi_user = (
            self.db.query(User)
            .filter(
                User.email.ilike(pi_identifier),
                User.role == UserRole.ADMIN,
                User.is_active,
            )
            .first()
        )

        if not pi_user:
            # Try to find by full name (case-insensitive)
            pi_user = (
                self.db.query(User)
                .filter(
                    User.full_name.ilike(pi_identifier),
                    User.role == UserRole.ADMIN,
                    User.is_active,
                )
                .first()
            )

        if pi_user:
            tenant = self.db.query(Tenant).filter(Tenant.id == pi_user.tenant_id).first()
            if tenant and tenant.is_active:
                return tenant, pi_user

        return None

    def _find_tenant_by_invitation_token(self, token: str) -> Tenant | None:
        """Find a tenant by invitation token.

        Args:
            token: Invitation token.

        Returns:
            Tenant if found, None otherwise.
        """
        return (
            self.db.query(Tenant).filter(Tenant.invitation_token == token, Tenant.is_active).first()
        )

    def register(self, data: UserRegister, base_url: str = "") -> tuple[User, Token | None, str]:
        """Register a new user.

        Handles four cases:
        1. Email invitation (LAB_MEMBER): Joins tenant, auto-approved
        2. Email invitation (NEW_TENANT): Creates new lab in org, becomes admin
        3. PI registration: Creates new tenant, user becomes admin (approved)
        4. Member with/without tenant invitation token: Joins tenant

        All cases require email verification before login.

        Args:
            data: Registration data.
            base_url: Base URL for verification email.

        Returns:
            tuple: (User, None, status message).
            Token is always None - user must verify email first.

        Raises:
            ValueError: If email exists or organization not found.
        """
        # Check for email invitation token first
        if data.invitation_token:
            from app.tenants.service import TenantService

            invitation = TenantService.validate_invitation_token(self.db, data.invitation_token)
            if invitation:
                # Validate email matches invitation
                if data.email.lower() != invitation.email.lower():
                    raise ValueError("Email address does not match the invitation")

                from app.db.models import InvitationType

                if invitation.invitation_type == InvitationType.LAB_MEMBER:
                    return self._register_invited_member(data, invitation, base_url)
                elif invitation.invitation_type == InvitationType.NEW_TENANT:
                    return self._register_invited_tenant(data, invitation, base_url)

        # Fall through to existing registration paths
        if data.is_pi:
            return self._register_pi(data, base_url)
        else:
            return self._register_member(data, base_url)

    def _register_pi(
        self, data: UserRegister, base_url: str = ""
    ) -> tuple[User, Token | None, str]:
        """Register a PI/team leader and create new lab.

        Each PI creates their own lab within an organization. Multiple PIs
        from the same organization (e.g., university) can each have their own lab.

        Args:
            data: Registration data.
            base_url: Base URL for verification email.

        Returns:
            tuple: Created user, None (no token until verified), and status message.

        Raises:
            ValueError: If email already registered as PI.
        """
        from app.db.models import Organization

        # Check if this email is already registered as a PI
        existing_pi = self.db.query(User).filter(User.email == data.email).first()
        if existing_pi:
            raise ValueError("This email is already registered.")

        # Determine lab name (custom or default to organization name)
        lab_name = data.lab_name if data.lab_name else data.organization

        # Create tenant (lab) with invitation token
        # Slug includes PI name for uniqueness (multiple labs per org allowed)
        slug = self._create_slug(f"{data.organization}-{data.full_name}")
        tenant = Tenant(
            name=lab_name,
            slug=slug,
            is_active=True,
            invitation_token=self._generate_invitation_token(),
            invitation_token_created_at=datetime.now(UTC),
            city=data.city,
            country=data.country,
        )

        # Try to find or create the organization
        org = self.db.query(Organization).filter(Organization.name == data.organization).first()
        if org:
            # Link to existing organization
            tenant.organization_id = org.id
        else:
            # Create new organization and make this lab the admin
            from app.organizations.service import normalize_name, slugify

            new_org = Organization(
                name=data.organization,
                slug=slugify(data.organization),
                normalized_name=normalize_name(data.organization),
                is_active=True,
            )
            self.db.add(new_org)
            self.db.flush()
            tenant.organization_id = new_org.id
            tenant.is_org_admin = True

        self.db.add(tenant)
        self.db.flush()

        # Create admin user (auto-approved but not email verified)
        user = User(
            tenant_id=tenant.id,
            email=data.email,
            password_hash=get_password_hash(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
            status=UserStatus.APPROVED,
            is_active=True,
            is_email_verified=False,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # Send verification email
        if base_url:
            self.send_verification_email(user, base_url)

        return (
            user,
            None,
            "Registration successful! Please check your email to verify your account.",
        )

    def _register_member(
        self, data: UserRegister, base_url: str = ""
    ) -> tuple[User, Token | None, str]:
        """Register a lab member to join existing organization.

        Args:
            data: Registration data.
            base_url: Base URL for verification email.

        Returns:
            tuple: Created user, None (no token until verified), and status message.

        Raises:
            ValueError: If PI not found or email exists.
        """
        tenant = None
        pi_user = None
        auto_approve = False

        # Check invitation token first
        if data.invitation_token:
            tenant = self._find_tenant_by_invitation_token(data.invitation_token)
            if tenant:
                auto_approve = True
                # Regenerate token so the link is single-use
                self.regenerate_invitation_token(tenant)
            else:
                raise ValueError("Invalid or expired invitation link.")

        # If no valid token, find by PI's name or email
        if not tenant:
            result = self._find_tenant_by_pi(data.pi_identifier)
            if not result:
                raise ValueError(
                    f"Could not find a PI with name or email '{data.pi_identifier}'. "
                    "Check the spelling or ask your PI for an invitation link."
                )
            tenant, pi_user = result

        # Check if email already exists in this tenant
        existing_user = (
            self.db.query(User)
            .filter(User.tenant_id == tenant.id, User.email == data.email)
            .first()
        )
        if existing_user:
            raise ValueError("Email already registered in this lab.")

        # Create user (not email verified yet)
        user = User(
            tenant_id=tenant.id,
            email=data.email,
            password_hash=get_password_hash(data.password),
            full_name=data.full_name,
            role=UserRole.USER,
            status=UserStatus.APPROVED if auto_approve else UserStatus.PENDING,
            is_active=True,
            is_email_verified=False,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # Get PI name for messages
        if not pi_user:
            pi_user = (
                self.db.query(User)
                .filter(User.tenant_id == tenant.id, User.role == UserRole.ADMIN)
                .first()
            )
        lab_name = pi_user.full_name if pi_user else tenant.name

        # Send verification email
        if base_url:
            self.send_verification_email(user, base_url)

        if auto_approve:
            return (
                user,
                None,
                "Registration successful! Please check your email to verify your account.",
            )
        else:
            # Notify admin about new member request
            try:
                email_service = get_email_service()
                if pi_user:
                    email_service.send_new_member_notification(
                        admin_email=pi_user.email,
                        admin_name=pi_user.full_name,
                        new_user_name=user.full_name,
                        new_user_email=user.email,
                    )
            except Exception as e:
                logger.warning(f"Failed to send registration emails: {e}")

            # No token for pending users - need both email verification and approval
            return (
                user,
                None,
                (
                    f"Registration submitted! Please check your email to verify your account. "
                    f"Your request to join {lab_name}'s lab is also pending approval."
                ),
            )

    def _register_invited_member(
        self, data: UserRegister, invitation, base_url: str = ""
    ) -> tuple[User, Token | None, str]:
        """Register a user via LAB_MEMBER email invitation.

        Creates user in the invitation's tenant, auto-approved.

        Args:
            data: Registration data.
            invitation: Validated Invitation model.
            base_url: Base URL for verification email.

        Returns:
            tuple: Created user, None, and status message.

        Raises:
            ValueError: If email already exists in the tenant.
        """
        from app.tenants.service import TenantService

        # Check if email already exists in this tenant
        existing_user = (
            self.db.query(User)
            .filter(User.tenant_id == invitation.tenant_id, User.email == data.email)
            .first()
        )
        if existing_user:
            raise ValueError("Email already registered in this lab.")

        # Create user (auto-approved, email pre-verified via invitation)
        user = User(
            tenant_id=invitation.tenant_id,
            email=data.email,
            password_hash=get_password_hash(data.password),
            full_name=data.full_name,
            role=UserRole.USER,
            status=UserStatus.APPROVED,
            is_active=True,
            is_email_verified=True,
        )
        self.db.add(user)

        # Mark invitation as accepted
        TenantService.accept_invitation(self.db, invitation.token)

        self.db.commit()
        self.db.refresh(user)

        return (
            user,
            None,
            "Registration successful! You can now log in.",
        )

    def _register_invited_tenant(
        self, data: UserRegister, invitation, base_url: str = ""
    ) -> tuple[User, Token | None, str]:
        """Register a user via NEW_TENANT email invitation.

        Creates a new lab within the invitation's organization.

        Args:
            data: Registration data.
            invitation: Validated Invitation model.
            base_url: Base URL for verification email.

        Returns:
            tuple: Created user, None, and status message.

        Raises:
            ValueError: If email already registered.
        """
        from app.tenants.service import TenantService

        # Check if email already registered
        existing = self.db.query(User).filter(User.email == data.email).first()
        if existing:
            raise ValueError("This email is already registered.")

        # Determine lab name
        lab_name = (
            data.lab_name if data.lab_name else (data.organization or data.full_name + " Lab")
        )

        # Create tenant (lab) within the org
        slug_base = f"{lab_name}-{data.full_name}" if data.organization else data.full_name
        slug = self._create_slug(slug_base)
        tenant = Tenant(
            name=lab_name,
            slug=slug,
            organization_id=invitation.organization_id,
            is_active=True,
            invitation_token=self._generate_invitation_token(),
            invitation_token_created_at=datetime.now(UTC),
            city=data.city,
            country=data.country,
        )
        self.db.add(tenant)
        self.db.flush()

        # Create admin user (auto-approved, email pre-verified via invitation)
        user = User(
            tenant_id=tenant.id,
            email=data.email,
            password_hash=get_password_hash(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
            status=UserStatus.APPROVED,
            is_active=True,
            is_email_verified=True,
        )
        self.db.add(user)

        # Mark invitation as accepted
        TenantService.accept_invitation(self.db, invitation.token)

        self.db.commit()
        self.db.refresh(user)

        return (
            user,
            None,
            "Registration successful! You can now log in.",
        )

    def login(self, data: UserLogin) -> tuple[User | None, Token | None, str]:
        """Authenticate user and return token.

        Args:
            data: Login credentials.

        Returns:
            tuple: (User or None, Token or None, status message).
        """
        # Find user by email
        user = self.db.query(User).filter(User.email == data.email).first()

        if not user or not verify_password(data.password, user.password_hash):
            return None, None, "Invalid email or password."

        if not user.is_active:
            return None, None, "Your account has been deactivated. Contact your administrator."

        if user.status == UserStatus.PENDING:
            return None, None, "Your account is pending approval from the lab administrator."

        if user.status == UserStatus.REJECTED:
            return None, None, "Your account request was rejected. Contact your administrator."

        if not user.is_email_verified:
            return (
                None,
                None,
                "Please verify your email address before logging in. Check your inbox for the verification link.",
            )

        # Update last login
        user.last_login = datetime.now(UTC)
        self.db.commit()

        # Generate tokens
        token = Token(
            access_token=create_access_token(user.id, user.tenant_id, user.email),
            refresh_token=create_refresh_token(user.id, user.tenant_id, user.email),
        )

        return user, token, "Login successful."

    def get_invitation_link(self, tenant: Tenant, base_url: str) -> str:
        """Get the invitation link for a tenant.

        Args:
            tenant: Tenant model.
            base_url: Base URL of the application.

        Returns:
            str: Full invitation URL.
        """
        if not tenant.invitation_token:
            # Generate new token if none exists
            tenant.invitation_token = self._generate_invitation_token()
            tenant.invitation_token_created_at = datetime.now(UTC)
            self.db.commit()

        return f"{base_url}/register?invite={tenant.invitation_token}"

    def regenerate_invitation_token(self, tenant: Tenant) -> str:
        """Regenerate the invitation token for a tenant.

        Args:
            tenant: Tenant model.

        Returns:
            str: New invitation token.
        """
        tenant.invitation_token = self._generate_invitation_token()
        tenant.invitation_token_created_at = datetime.now(UTC)
        self.db.commit()
        return tenant.invitation_token

    def get_pending_users(self, tenant_id: str) -> list[User]:
        """Get all pending users for a tenant.

        Args:
            tenant_id: Tenant UUID.

        Returns:
            list: Users with pending status.
        """
        return (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.status == UserStatus.PENDING)
            .order_by(User.created_at.desc())
            .all()
        )

    def approve_user(self, user_id: str, tenant_id: str) -> User | None:
        """Approve a pending user.

        Args:
            user_id: User UUID.
            tenant_id: Tenant UUID (for authorization).

        Returns:
            User if approved, None if not found.
        """
        user = (
            self.db.query(User)
            .filter(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.status == UserStatus.PENDING,
            )
            .first()
        )
        if user:
            user.status = UserStatus.APPROVED
            self.db.commit()
            self.db.refresh(user)

            # Send approval notification email
            try:
                email_service = get_email_service()
                email_service.send_approval_email(user.email, user.full_name)
            except Exception as e:
                logger.warning(f"Failed to send approval email to {user.email}: {e}")

        return user

    def reject_user(self, user_id: str, tenant_id: str) -> User | None:
        """Reject a pending user.

        Args:
            user_id: User UUID.
            tenant_id: Tenant UUID (for authorization).

        Returns:
            User if rejected, None if not found.
        """
        user = (
            self.db.query(User)
            .filter(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.status == UserStatus.PENDING,
            )
            .first()
        )
        if user:
            user.status = UserStatus.REJECTED
            self.db.commit()
            self.db.refresh(user)

            # Send rejection notification email
            try:
                email_service = get_email_service()
                email_service.send_rejection_email(user.email, user.full_name)
            except Exception as e:
                logger.warning(f"Failed to send rejection email to {user.email}: {e}")

        return user

    def get_user_response(self, user: User) -> UserResponse:
        """Convert user model to response schema.

        Args:
            user: User model.

        Returns:
            UserResponse: User response schema.
        """
        from app.auth.schemas import TenantInfo, TenantOrgInfo

        tenant_info = None
        if user.tenant:
            org_info = None
            if user.tenant.organization:
                org_info = TenantOrgInfo(
                    id=user.tenant.organization.id,
                    name=user.tenant.organization.name,
                    slug=user.tenant.organization.slug,
                )
            tenant_info = TenantInfo(
                id=user.tenant.id,
                name=user.tenant.name,
                slug=user.tenant.slug,
                organization=org_info,
                is_org_admin=user.tenant.is_org_admin or False,
                city=user.tenant.city,
                country=user.tenant.country,
            )

        return UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            tenant_id=user.tenant_id,
            tenant_name=user.tenant.name if user.tenant else "",
            tenant=tenant_info,
        )

    def change_password(self, user: User, current_password: str, new_password: str) -> bool:
        """Change user's password.

        Args:
            user: User model.
            current_password: Current password.
            new_password: New password.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not verify_password(current_password, user.password_hash):
            return False

        user.password_hash = get_password_hash(new_password)
        self.db.commit()
        return True

    def update_profile(
        self, user: User, full_name: str | None = None, email: str | None = None
    ) -> User:
        """Update user profile.

        Args:
            user: User model.
            full_name: New full name.
            email: New email.

        Returns:
            User: Updated user.

        Raises:
            ValueError: If email already exists.
        """
        if email and email != user.email:
            existing = (
                self.db.query(User)
                .filter(User.tenant_id == user.tenant_id, User.email == email)
                .first()
            )
            if existing:
                raise ValueError("Email already in use")
            user.email = email

        if full_name:
            user.full_name = full_name

        self.db.commit()
        self.db.refresh(user)
        return user

    def request_password_reset(self, email: str, base_url: str) -> bool:
        """Request a password reset for a user.

        Generates a reset token and sends an email with the reset link.
        Always returns True to prevent email enumeration attacks.

        Args:
            email: User's email address.
            base_url: Base URL of the application.

        Returns:
            bool: Always True (to prevent email enumeration).
        """
        from datetime import timedelta

        user = self.db.query(User).filter(User.email == email).first()

        if user and user.is_active:
            # Generate reset token
            token = secrets.token_hex(32)
            user.password_reset_token = token
            user.password_reset_token_expires = datetime.now(UTC) + timedelta(hours=1)
            self.db.commit()

            # Send reset email
            reset_url = f"{base_url}/reset-password?token={token}"
            try:
                email_service = get_email_service()
                email_service.send_password_reset_email(
                    to_email=user.email,
                    full_name=user.full_name,
                    reset_url=reset_url,
                )
            except Exception as e:
                logger.error(f"Failed to send password reset email to {email}: {e}")

        # Always return True to prevent email enumeration
        return True

    def reset_password(self, token: str, new_password: str) -> tuple[bool, str]:
        """Reset a user's password using a reset token.

        Args:
            token: Password reset token.
            new_password: New password to set.

        Returns:
            tuple: (success: bool, message: str)
        """
        user = self.db.query(User).filter(User.password_reset_token == token).first()

        if not user:
            return False, "Invalid or expired reset link."

        if not user.password_reset_token_expires:
            return False, "Invalid or expired reset link."

        # Handle both timezone-aware and naive datetimes from database
        token_expires = user.password_reset_token_expires
        if token_expires.tzinfo is None:
            token_expires = token_expires.replace(tzinfo=UTC)

        if datetime.now(UTC) > token_expires:
            # Clear expired token
            user.password_reset_token = None
            user.password_reset_token_expires = None
            self.db.commit()
            return False, "Reset link has expired. Please request a new one."

        # Update password and clear token
        user.password_hash = get_password_hash(new_password)
        user.password_reset_token = None
        user.password_reset_token_expires = None
        self.db.commit()

        return True, "Password has been reset successfully. You can now log in."

    def validate_reset_token(self, token: str) -> tuple[bool, User | None]:
        """Validate a password reset token.

        Args:
            token: Password reset token.

        Returns:
            tuple: (is_valid: bool, user: User or None)
        """
        user = self.db.query(User).filter(User.password_reset_token == token).first()

        if not user or not user.password_reset_token_expires:
            return False, None

        # Handle both timezone-aware and naive datetimes from database
        token_expires = user.password_reset_token_expires
        if token_expires.tzinfo is None:
            token_expires = token_expires.replace(tzinfo=UTC)

        if datetime.now(UTC) > token_expires:
            return False, None

        return True, user


def get_auth_service(db: Session) -> AuthService:
    """Factory function for AuthService.

    Args:
        db: Database session.

    Returns:
        AuthService: Auth service instance.
    """
    return AuthService(db)
