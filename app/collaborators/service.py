"""Collaborator service layer."""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.collaborators.schemas import (
    CollaboratorResponse,
    CollaboratorTenantInfo,
    TenantSearchResult,
)
from app.db.models import Collaborator, Stock, StockShare, Tenant, User, UserRole


class CollaboratorService:
    def __init__(self, db: Session, tenant_id: str, user_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    def _get_tenant_admin(self, tenant_id: str) -> User | None:
        """Get the admin user for a tenant."""
        return (
            self.db.query(User)
            .filter(User.tenant_id == tenant_id, User.role == UserRole.ADMIN)
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
