"""Tenant list, detail, and update operations."""

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import Cross, Stock, Tenant, User


def list_tenants(
    db: Session,
    *,
    page: int = 1,
    per_page: int = 25,
    search: str | None = None,
    plan: str | None = None,
    status: str | None = None,
    country: str | None = None,
) -> dict:
    """Paginated, filterable tenant list."""
    q = (
        db.query(
            Tenant.id,
            Tenant.name,
            Tenant.slug,
            Tenant.city,
            Tenant.country,
            Tenant.plan,
            Tenant.subscription_status,
            Tenant.is_active,
            Tenant.created_at,
            Tenant.trial_ends_at,
            func.count(func.distinct(User.id)).label("user_count"),
            func.count(func.distinct(Stock.id)).label("stock_count"),
        )
        .outerjoin(User, User.tenant_id == Tenant.id)
        .outerjoin(Stock, Stock.tenant_id == Tenant.id)
        .group_by(Tenant.id)
    )

    if search:
        q = q.filter(or_(Tenant.name.ilike(f"%{search}%"), Tenant.slug.ilike(f"%{search}%")))
    if plan:
        q = q.filter(Tenant.plan == plan)
    if status:
        q = q.filter(Tenant.subscription_status == status)
    if country:
        q = q.filter(Tenant.country == country)

    total = q.count()
    rows = q.order_by(Tenant.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "tenants": [
            {
                "id": r.id,
                "name": r.name,
                "slug": r.slug,
                "city": r.city,
                "country": r.country,
                "plan": r.plan.value if r.plan else None,
                "subscription_status": (
                    r.subscription_status.value if r.subscription_status else None
                ),
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "trial_ends_at": r.trial_ends_at.isoformat() if r.trial_ends_at else None,
                "user_count": r.user_count,
                "stock_count": r.stock_count,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 1,
    }


def get_tenant_detail(db: Session, tenant_id: str) -> dict | None:
    """Single tenant with aggregated counts."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return None

    user_count = db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0
    stock_count = db.query(func.count(Stock.id)).filter(Stock.tenant_id == tenant_id).scalar() or 0
    cross_count = db.query(func.count(Cross.id)).filter(Cross.tenant_id == tenant_id).scalar() or 0

    users = (
        db.query(
            User.id,
            User.email,
            User.full_name,
            User.role,
            User.status,
            User.is_active,
            User.is_email_verified,
            User.created_at,
            User.last_login,
        )
        .filter(User.tenant_id == tenant_id)
        .order_by(User.created_at)
        .all()
    )

    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "city": tenant.city,
        "country": tenant.country,
        "latitude": tenant.latitude,
        "longitude": tenant.longitude,
        "plan": tenant.plan.value if tenant.plan else None,
        "subscription_status": (
            tenant.subscription_status.value if tenant.subscription_status else None
        ),
        "is_active": tenant.is_active,
        "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        "max_users_override": tenant.max_users_override,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "user_count": user_count,
        "stock_count": stock_count,
        "cross_count": cross_count,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role.value if u.role else None,
                "status": u.status.value if u.status else None,
                "is_active": u.is_active,
                "is_email_verified": u.is_email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
            }
            for u in users
        ],
    }


def update_tenant(db: Session, tenant_id: str, data: dict) -> dict | None:
    """Update allowed fields on a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return None

    allowed = {"plan", "subscription_status", "is_active", "trial_ends_at", "max_users_override"}
    for key, value in data.items():
        if key not in allowed:
            continue
        if key == "trial_ends_at" and isinstance(value, str):
            value = datetime.fromisoformat(value) if value else None
        if key == "max_users_override" and value == "":
            value = None
        setattr(tenant, key, value)

    db.commit()
    db.refresh(tenant)
    return get_tenant_detail(db, tenant_id)


def get_countries(db: Session) -> list[str]:
    """Distinct country values for filter dropdown."""
    rows = (
        db.query(Tenant.country)
        .filter(Tenant.country.isnot(None), Tenant.country != "")
        .distinct()
        .order_by(Tenant.country)
        .all()
    )
    return [r.country for r in rows]
