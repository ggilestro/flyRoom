"""Tenant admin API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import CurrentAdminUser, CurrentTenantId, get_db
from app.tenants.schemas import (
    TenantResponse,
    TenantUpdate,
    UserInvite,
    UserListResponse,
    UserUpdateAdmin,
)
from app.tenants.service import TenantService, get_tenant_service

router = APIRouter()


def get_service(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: CurrentTenantId,
    _admin: CurrentAdminUser,  # Ensures only admins can access
) -> TenantService:
    """Get tenant service dependency (admin only)."""
    return get_tenant_service(db, str(tenant_id))


@router.get("/tenant", response_model=TenantResponse)
async def get_tenant_info(
    service: Annotated[TenantService, Depends(get_service)],
):
    """Get current tenant information.

    Args:
        service: Tenant service.

    Returns:
        TenantResponse: Tenant information.

    Raises:
        HTTPException: If tenant not found.
    """
    info = service.get_tenant_info()
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return info


@router.put("/tenant", response_model=TenantResponse)
async def update_tenant(
    data: TenantUpdate,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Update tenant information.

    Args:
        data: Update data.
        service: Tenant service.

    Returns:
        TenantResponse: Updated tenant information.

    Raises:
        HTTPException: If tenant not found.
    """
    service.update_tenant(name=data.name)
    info = service.get_tenant_info()
    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    return info


@router.get("/users", response_model=list[UserListResponse])
async def list_users(
    service: Annotated[TenantService, Depends(get_service)],
):
    """List all users in the tenant.

    Args:
        service: Tenant service.

    Returns:
        list[UserListResponse]: List of users.
    """
    return service.list_users()


@router.post("/users", response_model=UserListResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    data: UserInvite,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Invite a new user to the tenant.

    Args:
        data: User invitation data.
        service: Tenant service.

    Returns:
        UserListResponse: Created user (password will be sent separately).

    Raises:
        HTTPException: If invitation fails.
    """
    try:
        user, temp_password = service.invite_user(data)
        # In production, send email with temp_password
        # For now, return user info (password should be communicated securely)
        return UserListResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login=user.last_login,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/users/{user_id}", response_model=UserListResponse)
async def get_user(
    user_id: str,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Get a user by ID.

    Args:
        user_id: User UUID.
        service: Tenant service.

    Returns:
        UserListResponse: User information.

    Raises:
        HTTPException: If user not found.
    """
    user = service.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserListResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
    )


@router.put("/users/{user_id}", response_model=UserListResponse)
async def update_user(
    user_id: str,
    data: UserUpdateAdmin,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Update a user.

    Args:
        user_id: User UUID.
        data: Update data.
        service: Tenant service.

    Returns:
        UserListResponse: Updated user information.

    Raises:
        HTTPException: If update fails.
    """
    try:
        user = service.update_user(user_id, data)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserListResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login=user.last_login,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Deactivate a user.

    Args:
        user_id: User UUID.
        service: Tenant service.

    Raises:
        HTTPException: If user not found.
    """
    if not service.deactivate_user(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    service: Annotated[TenantService, Depends(get_service)],
):
    """Reset a user's password.

    Args:
        user_id: User UUID.
        service: Tenant service.

    Returns:
        dict: New temporary password.

    Raises:
        HTTPException: If user not found.
    """
    temp_password = service.reset_user_password(user_id)
    if not temp_password:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    # In production, send email with temp_password
    return {"temporary_password": temp_password}
