"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.schemas import (
    ForgotPassword,
    PasswordChange,
    PasswordReset,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
    UserUpdate,
)
from app.auth.service import AuthService, get_auth_service
from app.dependencies import CurrentAdmin, CurrentUser, get_db

router = APIRouter()


class RegisterResponse(BaseModel):
    """Response for registration endpoint."""

    message: str
    token: Token | None = None
    pending_approval: bool = False
    email_verification_required: bool = True


class EmailVerificationRequest(BaseModel):
    """Request to resend verification email."""

    email: str


class EmailVerificationResponse(BaseModel):
    """Response for email verification."""

    message: str
    success: bool = True


class InvitationResponse(BaseModel):
    """Response for invitation link endpoint."""

    invitation_url: str
    token: str


def get_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    """Get auth service dependency."""
    return get_auth_service(db)


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserRegister,
    request: Request,
    service: Annotated[AuthService, Depends(get_service)],
    response: Response,
):
    """Register a new user.

    For PIs: Creates new organization, user becomes admin.
    For members with invitation: Joins organization, auto-approved.
    For members without invitation: Joins organization, pending approval.

    All users must verify their email before logging in.

    Args:
        data: Registration data.
        request: FastAPI request object.
        service: Auth service.
        response: FastAPI response object.

    Returns:
        RegisterResponse: Registration result (always requires email verification).

    Raises:
        HTTPException: If registration fails.
    """
    try:
        # Get base URL for verification email
        base_url = str(request.base_url).rstrip("/")

        user, token, message = service.register(data, base_url)

        # Token will always be None now - user must verify email first
        return RegisterResponse(
            message=message,
            pending_approval=user.status.value == "pending",
            email_verification_required=True,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/verify-email")
async def verify_email(
    token: str,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Verify user's email address.

    Args:
        token: Email verification token from URL.
        service: Auth service.

    Returns:
        EmailVerificationResponse: Verification result.

    Raises:
        HTTPException: If verification fails.
    """
    user, message = service.verify_email(token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return EmailVerificationResponse(message=message, success=True)


@router.post("/resend-verification")
async def resend_verification(
    data: EmailVerificationRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Resend email verification link.

    Args:
        data: Request with user's email.
        request: FastAPI request object.
        service: Auth service.

    Returns:
        EmailVerificationResponse: Result message.
    """
    from app.db.models import User

    # Find user by email
    user = service.db.query(User).filter(User.email == data.email).first()

    if not user:
        # Don't reveal if email exists
        return EmailVerificationResponse(
            message="If an account exists with this email, a verification link has been sent.",
            success=True,
        )

    if user.is_email_verified:
        return EmailVerificationResponse(
            message="This email is already verified. You can log in.",
            success=True,
        )

    # Send verification email
    base_url = str(request.base_url).rstrip("/")
    service.send_verification_email(user, base_url)

    return EmailVerificationResponse(
        message="Verification email sent. Please check your inbox.",
        success=True,
    )


@router.post("/login")
async def login(
    data: UserLogin,
    service: Annotated[AuthService, Depends(get_service)],
    response: Response,
):
    """Login with email and password.

    Args:
        data: Login credentials.
        service: Auth service.
        response: FastAPI response object.

    Returns:
        dict: Login result with token and message.

    Raises:
        HTTPException: If credentials are invalid or account not approved.
    """
    user, token, message = service.login(data)

    if not user or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Set tokens as cookies
    response.set_cookie(
        key="access_token",
        value=token.access_token,
        httponly=True,
        secure=False,  # Set to True in production
        samesite="lax",
        max_age=30 * 60,  # 30 minutes
        path="/",  # Cookie available for all paths
    )
    response.set_cookie(
        key="refresh_token",
        value=token.refresh_token,
        httponly=True,
        secure=False,  # Set to True in production
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days
        path="/",  # Cookie available for all paths
    )

    return {"message": message, "token": token}


@router.post("/logout")
async def logout(response: Response):
    """Logout user by clearing cookies.

    Args:
        response: FastAPI response object.

    Returns:
        RedirectResponse: Redirect to login page.
    """
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Get current user information.

    Args:
        current_user: Current authenticated user.
        service: Auth service.

    Returns:
        UserResponse: User information.
    """
    return service.get_user_response(current_user)


@router.put("/me", response_model=UserResponse)
async def update_profile(
    data: UserUpdate,
    current_user: CurrentUser,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Update current user's profile.

    Args:
        data: Update data.
        current_user: Current authenticated user.
        service: Auth service.

    Returns:
        UserResponse: Updated user information.

    Raises:
        HTTPException: If update fails.
    """
    try:
        user = service.update_profile(
            current_user,
            full_name=data.full_name,
            email=data.email,
        )
        return service.get_user_response(user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    current_user: CurrentUser,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Change current user's password.

    Args:
        data: Password change data.
        current_user: Current authenticated user.
        service: Auth service.

    Returns:
        dict: Success message.

    Raises:
        HTTPException: If password change fails.
    """
    success = service.change_password(
        current_user,
        data.current_password,
        data.new_password,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPassword,
    request: Request,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Request a password reset email.

    Args:
        data: Forgot password data with email.
        request: FastAPI request object.
        service: Auth service.

    Returns:
        dict: Success message (always returns success to prevent email enumeration).
    """
    base_url = str(request.base_url).rstrip("/")
    service.request_password_reset(data.email, base_url)

    # Always return success to prevent email enumeration
    return {"message": "If an account with that email exists, a password reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    data: PasswordReset,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Reset password using a reset token.

    Args:
        data: Password reset data with token and new password.
        service: Auth service.

    Returns:
        dict: Success message.

    Raises:
        HTTPException: If token is invalid or expired.
    """
    success, message = service.reset_password(data.token, data.new_password)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return {"message": message}


@router.get("/invitation-link", response_model=InvitationResponse)
async def get_invitation_link(
    request: Request,
    current_user: CurrentAdmin,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Get the invitation link for the organization.

    Only admins can access this endpoint.

    Args:
        request: FastAPI request object.
        current_user: Current admin user.
        service: Auth service.

    Returns:
        InvitationResponse: Invitation URL and token.
    """
    base_url = str(request.base_url).rstrip("/")
    url = service.get_invitation_link(current_user.tenant, base_url)

    return InvitationResponse(
        invitation_url=url,
        token=current_user.tenant.invitation_token,
    )


@router.post("/invitation-link/regenerate", response_model=InvitationResponse)
async def regenerate_invitation_link(
    request: Request,
    current_user: CurrentAdmin,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Regenerate the invitation link (invalidates old link).

    Only admins can access this endpoint.

    Args:
        request: FastAPI request object.
        current_user: Current admin user.
        service: Auth service.

    Returns:
        InvitationResponse: New invitation URL and token.
    """
    new_token = service.regenerate_invitation_token(current_user.tenant)
    base_url = str(request.base_url).rstrip("/")

    return InvitationResponse(
        invitation_url=f"{base_url}/register?invite={new_token}",
        token=new_token,
    )


@router.get("/pending-users")
async def get_pending_users(
    current_user: CurrentAdmin,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Get list of users pending approval.

    Only admins can access this endpoint.

    Args:
        current_user: Current admin user.
        service: Auth service.

    Returns:
        list: Pending users.
    """
    users = service.get_pending_users(current_user.tenant_id)
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    current_user: CurrentAdmin,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Approve a pending user.

    Only admins can access this endpoint.

    Args:
        user_id: User ID to approve.
        current_user: Current admin user.
        service: Auth service.

    Returns:
        dict: Success message.

    Raises:
        HTTPException: If user not found.
    """
    user = service.approve_user(user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or not pending approval.",
        )
    return {"message": f"User {user.full_name} has been approved."}


@router.post("/users/{user_id}/reject")
async def reject_user(
    user_id: str,
    current_user: CurrentAdmin,
    service: Annotated[AuthService, Depends(get_service)],
):
    """Reject a pending user.

    Only admins can access this endpoint.

    Args:
        user_id: User ID to reject.
        current_user: Current admin user.
        service: Auth service.

    Returns:
        dict: Success message.

    Raises:
        HTTPException: If user not found.
    """
    user = service.reject_user(user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or not pending approval.",
        )
    return {"message": f"User {user.full_name} has been rejected."}
