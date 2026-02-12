"""Cross timeline reminder email scheduler."""

import logging
from typing import Any

from app.crosses.service import get_cross_service
from app.db.database import SessionLocal
from app.db.models import Tenant, User, UserRole
from app.email.service import get_email_service

logger = logging.getLogger(__name__)


def send_all_cross_reminders() -> dict[str, Any]:
    """Send cross timeline reminder emails to all active tenants.

    This function is called by the cron endpoint to send reminders
    about crosses needing vial flips or virgin collection.

    Returns:
        dict: Summary of emails sent.
    """
    db = SessionLocal()
    email_service = get_email_service()
    results = {
        "tenants_processed": 0,
        "emails_sent": 0,
        "errors": [],
    }

    try:
        tenants = db.query(Tenant).filter(Tenant.is_active).all()

        for tenant in tenants:
            try:
                result = _send_tenant_cross_reminders(db, email_service, tenant)
                results["tenants_processed"] += 1
                results["emails_sent"] += result["emails_sent"]
            except Exception as e:
                logger.error(f"Error sending cross reminder for tenant {tenant.id}: {e}")
                results["errors"].append({"tenant_id": tenant.id, "error": str(e)})

    finally:
        db.close()

    return results


def _send_tenant_cross_reminders(db, email_service, tenant: Tenant) -> dict[str, int]:
    """Send cross timeline reminder emails for a single tenant.

    Args:
        db: Database session.
        email_service: Email service instance.
        tenant: Tenant to send reminders for.

    Returns:
        dict: Number of emails sent.
    """
    cross_service = get_cross_service(db, tenant.id)
    reminders = cross_service.get_crosses_needing_reminders()

    if not reminders:
        return {"emails_sent": 0}

    # Get admin users for this tenant
    admins = (
        db.query(User)
        .filter(
            User.tenant_id == tenant.id,
            User.role == UserRole.ADMIN,
            User.is_active,
        )
        .all()
    )

    if not admins:
        logger.warning(f"No admin users found for tenant {tenant.id}")
        return {"emails_sent": 0}

    emails_sent = 0

    for admin in admins:
        try:
            success = email_service.send_cross_reminder_email(
                to_email=admin.email,
                user_name=admin.full_name,
                reminders=reminders,
                tenant_name=tenant.name,
            )
            if success:
                emails_sent += 1
        except Exception as e:
            logger.error(f"Error sending cross reminder to {admin.email}: {e}")

    return {"emails_sent": emails_sent}
