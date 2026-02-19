"""Collaborator service layer."""

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.collaborators.schemas import (
    CollaboratorInvitationResponse,
    CollaboratorResponse,
    CollaboratorTenantInfo,
    TenantSearchResult,
)
from app.db.models import (
    ADMIN_ROLES,
    Collaborator,
    Invitation,
    InvitationStatus,
    InvitationType,
    Stock,
    StockShare,
    Tenant,
    User,
)

logger = logging.getLogger(__name__)


class CollaboratorService:
    def __init__(self, db: Session, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _get_tenant_admin(self, tenant_id: str) -> User | None:
        """Get the admin user for a tenant."""
        return (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.role.in_(ADMIN_ROLES))
            .first()
        )

    def search_tenants(self, query: str, limit: int = 10) -> list[TenantSearchResult]:
        existing_ids = [
            r[0]
            for r in self.db.query(Collaborator.collaborator_id)
            .filter(Collaborator.tenant_id == self.tenant_id)
            .all()
        ]
        exclude_ids = [self.tenant_id] + existing_ids

        like = f"%{query}%"

        # Search by tenant name, or by any user's full_name or email in that tenant
        matching_tenant_ids_via_users = (
            self.db.query(User.tenant_id)
            .filter(
                or_(
                    User.full_name.ilike(like),
                    User.email.ilike(like),
                ),
            )
            .distinct()
        )

        tenants = (
            self.db.query(Tenant)
            .filter(
                or_(
                    Tenant.name.ilike(like),
                    Tenant.id.in_(matching_tenant_ids_via_users),
                ),
                Tenant.id.notin_(exclude_ids),
                Tenant.is_active.is_(True),
            )
            .limit(limit)
            .all()
        )

        results = []
        for t in tenants:
            admin = self._get_tenant_admin(t.id)
            results.append(
                TenantSearchResult(
                    id=t.id,
                    name=t.name,
                    admin_name=admin.full_name if admin else None,
                    admin_email=admin.email if admin else None,
                    city=t.city,
                    country=t.country,
                )
            )
        return results

    def list_collaborators(self) -> list[CollaboratorResponse]:
        collabs = (
            self.db.query(Collaborator)
            .filter(Collaborator.tenant_id == self.tenant_id)
            .order_by(Collaborator.created_at.desc())
            .all()
        )
        results = []
        for c in collabs:
            t = c.collaborator_tenant
            admin = self._get_tenant_admin(t.id)
            results.append(
                CollaboratorResponse(
                    id=c.id,
                    collaborator=CollaboratorTenantInfo(
                        id=t.id,
                        name=t.name,
                        admin_name=admin.full_name if admin else None,
                        city=t.city,
                        country=t.country,
                    ),
                    created_at=c.created_at,
                )
            )
        return results

    def add_collaborator(self, collaborator_tenant_id: str) -> CollaboratorResponse:
        if collaborator_tenant_id == self.tenant_id:
            raise ValueError("Cannot add yourself as a collaborator")

        target = self.db.query(Tenant).filter(Tenant.id == collaborator_tenant_id).first()
        if not target:
            raise ValueError("Tenant not found")

        existing = (
            self.db.query(Collaborator)
            .filter(
                Collaborator.tenant_id == self.tenant_id,
                Collaborator.collaborator_id == collaborator_tenant_id,
            )
            .first()
        )
        if existing:
            raise ValueError("Already a collaborator")

        collab = Collaborator(
            tenant_id=self.tenant_id,
            collaborator_id=collaborator_tenant_id,
            created_by_id=self.user_id,
        )
        self.db.add(collab)
        self.db.commit()
        self.db.refresh(collab)

        admin = self._get_tenant_admin(target.id)
        return CollaboratorResponse(
            id=collab.id,
            collaborator=CollaboratorTenantInfo(
                id=target.id,
                name=target.name,
                admin_name=admin.full_name if admin else None,
                city=target.city,
                country=target.country,
            ),
            created_at=collab.created_at,
        )

    def remove_collaborator(self, collaborator_id: str) -> bool:
        collab = (
            self.db.query(Collaborator)
            .filter(
                Collaborator.id == collaborator_id,
                Collaborator.tenant_id == self.tenant_id,
            )
            .first()
        )
        if not collab:
            return False

        # Remove all stock shares where our stocks are shared with this collaborator
        self.db.query(StockShare).filter(
            StockShare.shared_with_tenant_id == collab.collaborator_id,
            StockShare.stock_id.in_(
                self.db.query(Stock.id).filter(Stock.tenant_id == self.tenant_id)
            ),
        ).delete(synchronize_session=False)

        self.db.delete(collab)
        self.db.commit()
        return True

    # --- Collaborator invitation methods ---

    def create_invitation(self, email: str, base_url: str) -> CollaboratorInvitationResponse:
        """Create a collaborator invitation and send email."""
        # Check for existing pending invitation
        existing = (
            self.db.query(Invitation)
            .filter(
                Invitation.tenant_id == self.tenant_id,
                Invitation.email == email,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.invitation_type == InvitationType.COLLABORATOR,
            )
            .first()
        )
        if existing:
            raise ValueError(f"A pending invitation already exists for {email}")

        # Check if email already belongs to an existing collaborator
        existing_user = self.db.query(User).filter(User.email == email).first()
        if existing_user:
            existing_collab = (
                self.db.query(Collaborator)
                .filter(
                    Collaborator.tenant_id == self.tenant_id,
                    Collaborator.collaborator_id == existing_user.tenant_id,
                )
                .first()
            )
            if existing_collab:
                raise ValueError(f"{email} is already a collaborator")

        token = secrets.token_hex(32)
        invitation = Invitation(
            tenant_id=self.tenant_id,
            invited_by_id=self.user_id,
            email=email,
            invitation_type=InvitationType.COLLABORATOR,
            token=token,
            status=InvitationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.db.add(invitation)
        self.db.commit()
        self.db.refresh(invitation)

        # Send invitation email
        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        inviter = self.db.query(User).filter(User.id == self.user_id).first()
        inviter_name = inviter.full_name if inviter else "An administrator"
        registration_url = f"{base_url}/register?invitation={token}"

        try:
            from app.email.service import get_email_service

            email_service = get_email_service()
            email_service.send_invitation_email(
                to_email=email,
                invitation_type="collaborator",
                inviter_name=inviter_name,
                tenant_name=tenant.name if tenant else "",
                organization_name=None,
                registration_url=registration_url,
            )
        except Exception as e:
            logger.warning(f"Failed to send collaborator invitation email to {email}: {e}")

        return CollaboratorInvitationResponse(
            id=invitation.id,
            email=invitation.email,
            status=invitation.status.value,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            invited_by_name=inviter_name,
        )

    def list_invitations(self) -> list[CollaboratorInvitationResponse]:
        """List collaborator-type invitations for this tenant, auto-expiring overdue ones."""
        invitations = (
            self.db.query(Invitation)
            .filter(
                Invitation.tenant_id == self.tenant_id,
                Invitation.invitation_type == InvitationType.COLLABORATOR,
            )
            .order_by(Invitation.created_at.desc())
            .all()
        )

        now = datetime.now(UTC)
        result = []
        for inv in invitations:
            if inv.status == InvitationStatus.PENDING:
                expires_at = inv.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if now > expires_at:
                    inv.status = InvitationStatus.EXPIRED
                    self.db.commit()

            inviter = self.db.query(User).filter(User.id == inv.invited_by_id).first()
            result.append(
                CollaboratorInvitationResponse(
                    id=inv.id,
                    email=inv.email,
                    status=inv.status.value,
                    created_at=inv.created_at,
                    expires_at=inv.expires_at,
                    invited_by_name=inviter.full_name if inviter else None,
                )
            )
        return result

    def cancel_invitation(self, invitation_id: str) -> bool:
        """Cancel a pending collaborator invitation."""
        invitation = (
            self.db.query(Invitation)
            .filter(
                Invitation.id == invitation_id,
                Invitation.tenant_id == self.tenant_id,
                Invitation.invitation_type == InvitationType.COLLABORATOR,
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
        """Resend a pending collaborator invitation email and extend expiry."""
        invitation = (
            self.db.query(Invitation)
            .filter(
                Invitation.id == invitation_id,
                Invitation.tenant_id == self.tenant_id,
                Invitation.invitation_type == InvitationType.COLLABORATOR,
                Invitation.status == InvitationStatus.PENDING,
            )
            .first()
        )
        if not invitation:
            return False

        invitation.expires_at = datetime.now(UTC) + timedelta(days=7)
        self.db.commit()

        tenant = self.db.query(Tenant).filter(Tenant.id == self.tenant_id).first()
        inviter = self.db.query(User).filter(User.id == invitation.invited_by_id).first()
        inviter_name = inviter.full_name if inviter else "An administrator"
        registration_url = f"{base_url}/register?invitation={invitation.token}"

        try:
            from app.email.service import get_email_service

            email_service = get_email_service()
            email_service.send_invitation_email(
                to_email=invitation.email,
                invitation_type="collaborator",
                inviter_name=inviter_name,
                tenant_name=tenant.name if tenant else "",
                organization_name=None,
                registration_url=registration_url,
            )
        except Exception as e:
            logger.warning(
                f"Failed to resend collaborator invitation email to {invitation.email}: {e}"
            )

        return True
