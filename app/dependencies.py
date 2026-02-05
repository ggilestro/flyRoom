"""Dependency injection for FastAPI."""

from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.utils import decode_access_token
from app.db.database import SessionLocal
from app.db.models import User, UserRole, UserStatus

security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Get database session.

    Yields:
        Session: SQLAlchemy session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
    access_token: str | None = Cookie(None),
) -> User:
    """Get the current authenticated user from JWT token or cookie.

    Supports both Bearer token (for API clients) and cookie-based auth (for web UI).

    Args:
        request: FastAPI request object.
        credentials: HTTP Bearer token credentials.
        db: Database session.
        access_token: Access token from cookie.

    Returns:
        User: The authenticated user.

    Raises:
        HTTPException: If authentication fails.
    """
    # Try Bearer token first, then fall back to cookie
    token = None
    if credentials is not None:
        token = credentials.credentials
    elif access_token is not None:
        token = access_token

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_access_token(token)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    if user.status != UserStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending approval",
        )

    # Eagerly load tenant for convenience
    _ = user.tenant

    return user


async def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
    access_token: str | None = Cookie(None),
) -> User | None:
    """Get the current user if authenticated, None otherwise.

    Args:
        request: FastAPI request object.
        credentials: HTTP Bearer token credentials.
        db: Database session.
        access_token: Access token from cookie.

    Returns:
        User | None: The authenticated user or None.
    """
    if credentials is None and access_token is None:
        return None

    try:
        return await get_current_user(request, credentials, db, access_token)
    except HTTPException:
        return None


async def get_current_admin_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get the current user and verify they have admin role.

    Args:
        current_user: The authenticated user.

    Returns:
        User: The admin user.

    Raises:
        HTTPException: If user is not an admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_current_tenant_id(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    """Get the tenant ID for the current user.

    Args:
        current_user: The authenticated user.

    Returns:
        UUID: The tenant ID.
    """
    return current_user.tenant_id


# Type aliases for cleaner dependency injection
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
CurrentAdmin = Annotated[User, Depends(get_current_admin_user)]
CurrentAdminUser = CurrentAdmin  # Alias for backwards compatibility
CurrentTenantId = Annotated[UUID, Depends(get_current_tenant_id)]
