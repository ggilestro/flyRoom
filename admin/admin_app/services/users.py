"""Platform-wide user analytics."""

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.models import Tenant, User


def get_user_analytics(db: Session) -> dict:
    """Aggregate user stats across all tenants."""
    total = db.query(func.count(User.id)).scalar() or 0
    active = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    verified = db.query(func.count(User.id)).filter(User.is_email_verified.is_(True)).scalar() or 0
    admins = (
        db.query(func.count(User.id)).filter(User.role.in_(("admin", "lab_manager"))).scalar() or 0
    )

    # Status breakdown
    status_rows = (
        db.query(User.status, func.count(User.id).label("count")).group_by(User.status).all()
    )
    by_status = {r.status.value if r.status else "unknown": r.count for r in status_rows}

    # Role breakdown
    role_rows = db.query(User.role, func.count(User.id).label("count")).group_by(User.role).all()
    by_role = {r.role.value if r.role else "unknown": r.count for r in role_rows}

    # Per-tenant breakdown
    tenant_rows = (
        db.query(
            Tenant.id,
            Tenant.name,
            Tenant.plan,
            func.count(User.id).label("user_count"),
        )
        .outerjoin(User, User.tenant_id == Tenant.id)
        .group_by(Tenant.id, Tenant.name, Tenant.plan)
        .order_by(func.count(User.id).desc())
        .all()
    )
    per_tenant = [
        {
            "tenant_id": r.id,
            "tenant_name": r.name,
            "plan": r.plan.value if r.plan else "unknown",
            "user_count": r.user_count,
        }
        for r in tenant_rows
    ]

    # Monthly registration
    monthly_rows = (
        db.query(
            func.date_format(User.created_at, "%Y-%m").label("month"),
            func.count(User.id).label("count"),
        )
        .group_by(text("month"))
        .order_by(text("month"))
        .all()
    )
    monthly = [{"month": r.month, "count": r.count} for r in monthly_rows]

    return {
        "total": total,
        "active": active,
        "verified": verified,
        "admins": admins,
        "by_status": by_status,
        "by_role": by_role,
        "per_tenant": per_tenant,
        "monthly": monthly,
    }
