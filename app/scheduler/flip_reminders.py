"""Flip reminder email scheduler."""

import logging
from typing import Any

from app.db.database import SessionLocal
from app.db.models import Tenant, User, UserRole
from app.email.service import get_email_service
from app.flips.service import get_flip_service

logger = logging.getLogger(__name__)


def send_all_flip_reminders() -> dict[str, Any]:
    """Send flip reminder emails to all tenants with reminders enabled.

    This function is called by the cron endpoint to send weekly
    reminder emails about stocks that need flipping.

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
        # Get all tenants with flip reminders enabled
        tenants = db.query(Tenant).filter(Tenant.flip_reminder_enabled, Tenant.is_active).all()

        for tenant in tenants:
            try:
                result = _send_tenant_reminder(db, email_service, tenant)
                results["tenants_processed"] += 1
                results["emails_sent"] += result["emails_sent"]
            except Exception as e:
                logger.error(f"Error sending reminder for tenant {tenant.id}: {e}")
                results["errors"].append({"tenant_id": tenant.id, "error": str(e)})

    finally:
        db.close()

    return results


def _send_tenant_reminder(db, email_service, tenant: Tenant) -> dict[str, int]:
    """Send flip reminder emails for a single tenant.

    Args:
        db: Database session.
        email_service: Email service instance.
        tenant: Tenant to send reminders for.

    Returns:
        dict: Number of emails sent.
    """
    # Get flip service for this tenant
    flip_service = get_flip_service(db, tenant.id)

    # Get stocks needing attention
    needing_flip = flip_service.get_stocks_needing_flip()
    stocks = needing_flip.warning + needing_flip.critical

    if not stocks:
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
            success = email_service.send_flip_reminder_email(
                to_email=admin.email,
                user_name=admin.full_name,
                stocks=stocks,
                tenant_name=tenant.name,
            )
            if success:
                emails_sent += 1
        except Exception as e:
            logger.error(f"Error sending flip reminder to {admin.email}: {e}")

    return {"emails_sent": emails_sent}
