"""Subscription plan configuration and helpers."""

from app.db.models import PlanTier, SubscriptionStatus

# Max users per plan (None = unlimited)
PLAN_LIMITS: dict[PlanTier, int | None] = {
    PlanTier.FREE: 2,
    PlanTier.LIGHT: 5,
    PlanTier.PRO: None,
    PlanTier.LIFE: None,
}

# Max stocks per plan (None = unlimited)
PLAN_STOCK_LIMITS: dict[PlanTier, int | None] = {
    PlanTier.FREE: 500,
    PlanTier.LIGHT: None,
    PlanTier.PRO: None,
    PlanTier.LIFE: None,
}

PLAN_DISPLAY_NAMES: dict[PlanTier, str] = {
    PlanTier.FREE: "Free",
    PlanTier.LIGHT: "Light",
    PlanTier.PRO: "Pro",
    PlanTier.LIFE: "Life",
}

# Multi-currency pricing (yearly and monthly equivalents)
# Free tier has no price; Life tier is legacy (contact-only)
PLAN_PRICES: dict[PlanTier, dict[str, dict[str, int]] | None] = {
    PlanTier.FREE: None,
    PlanTier.LIGHT: {
        "GBP": {"yearly": 220, "monthly": 18},
        "EUR": {"yearly": 240, "monthly": 20},
        "USD": {"yearly": 300, "monthly": 25},
    },
    PlanTier.PRO: {
        "GBP": {"yearly": 440, "monthly": 37},
        "EUR": {"yearly": 480, "monthly": 40},
        "USD": {"yearly": 600, "monthly": 50},
    },
    PlanTier.LIFE: None,
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "GBP": "\u00a3",
    "EUR": "\u20ac",
    "USD": "$",
}


def get_max_users(
    plan: PlanTier,
    subscription_status: SubscriptionStatus,
    override: int | None = None,
) -> int | None:
    """Return the effective max-user limit for a tenant.

    Args:
        plan: The tenant's plan tier.
        subscription_status: The tenant's subscription status.
        override: Optional per-tenant manual override.

    Returns:
        int | None: Max users allowed, or None for unlimited.
    """
    if override is not None:
        return override
    # Trialing tenants get unlimited (Pro-level) access
    if subscription_status == SubscriptionStatus.TRIALING:
        return None
    return PLAN_LIMITS.get(plan)


def check_user_limit(
    plan: PlanTier,
    subscription_status: SubscriptionStatus,
    current_count: int,
    override: int | None = None,
) -> None:
    """Raise ValueError if adding another user would exceed the plan limit.

    Args:
        plan: The tenant's plan tier.
        subscription_status: The tenant's subscription status.
        current_count: Current number of users in the tenant.
        override: Optional per-tenant manual override.

    Raises:
        ValueError: If user limit would be exceeded.
    """
    limit = get_max_users(plan, subscription_status, override)
    if limit is not None and current_count >= limit:
        plan_name = PLAN_DISPLAY_NAMES.get(plan, plan.value)
        raise ValueError(
            f"Your {plan_name} plan allows a maximum of {limit} users. "
            "Please upgrade your plan or contact support to add more members."
        )
