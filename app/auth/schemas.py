"""Pydantic schemas for authentication."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserRegisterPI(BaseModel):
    """Schema for PI/team leader registration (creates new organization).

    Attributes:
        organization: Organization/lab name (creates new tenant).
        full_name: User's full name.
        email: User's email address.
        password: User's password.
        password_confirm: Password confirmation.
    """

    organization: str = Field(..., min_length=2, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    password_confirm: str

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Validate that passwords match."""
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class UserRegisterMember(BaseModel):
    """Schema for lab member registration (joins existing organization).

    Attributes:
        organization: Organization/lab name to join.
        full_name: User's full name.
        email: User's email address.
        password: User's password.
        password_confirm: Password confirmation.
        invitation_token: Optional invitation token for direct join.
    """

    organization: str = Field(..., min_length=2, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    password_confirm: str
    invitation_token: str | None = None

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Validate that passwords match."""
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class UserRegister(BaseModel):
    """Schema for user registration (unified form).

    Attributes:
        organization: Organization name (e.g., Harvard, Imperial College London).
        full_name: User's full name.
        email: User's email address.
        password: User's password.
        password_confirm: Password confirmation.
        is_pi: Whether registering as PI/team leader.
        pi_identifier: PI's name or email (for members joining a lab).
        invitation_token: Optional invitation token for direct join.
        lab_name: Custom lab name (PI only, optional).
        city: Lab city (PI only, optional).
        country: Lab country (PI only, optional).
    """

    organization: str | None = Field(None, min_length=2, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    password_confirm: str
    is_pi: bool = False
    pi_identifier: str | None = Field(None, min_length=2, max_length=255)
    invitation_token: str | None = None
    lab_name: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    country: str | None = Field(None, max_length=100)

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Validate that passwords match."""
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v

    @field_validator("organization")
    @classmethod
    def organization_required_for_pi(cls, v: str | None, info) -> str | None:
        """Validate organization is provided for PI registration."""
        if info.data.get("is_pi") and not v:
            raise ValueError("Organization is required for PI registration")
        return v

    @field_validator("pi_identifier")
    @classmethod
    def pi_identifier_required_for_member(cls, v: str | None, info) -> str | None:
        """Validate PI identifier is provided for member registration (unless using invite)."""
        is_pi = info.data.get("is_pi", False)
        has_invite = info.data.get("invitation_token")
        if not is_pi and not has_invite and not v:
            raise ValueError("PI's name or email is required to join a lab")
        return v


class UserLogin(BaseModel):
    """Schema for user login.

    Attributes:
        email: User's email address.
        password: User's password.
    """

    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT token response.

    Attributes:
        access_token: JWT access token.
        refresh_token: JWT refresh token.
        token_type: Token type (always "bearer").
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Schema for token refresh request.

    Attributes:
        refresh_token: JWT refresh token.
    """

    refresh_token: str


class TenantOrgInfo(BaseModel):
    """Organization info nested in tenant."""

    id: str
    name: str
    slug: str


class TenantInfo(BaseModel):
    """Tenant info for user response."""

    id: str
    name: str
    slug: str
    organization: TenantOrgInfo | None = None
    is_org_admin: bool = False
    city: str | None = None
    country: str | None = None


class UserResponse(BaseModel):
    """Schema for user response.

    Attributes:
        id: User's UUID.
        email: User's email.
        full_name: User's full name.
        role: User's role.
        tenant_id: Tenant's UUID.
        tenant_name: Tenant's name.
        tenant: Full tenant info including organization.
    """

    id: str
    email: str
    full_name: str
    role: str
    tenant_id: str
    tenant_name: str
    tenant: TenantInfo | None = None

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    """Schema for updating user profile.

    Attributes:
        full_name: New full name.
        email: New email.
    """

    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None


class PasswordChange(BaseModel):
    """Schema for changing password.

    Attributes:
        current_password: Current password.
        new_password: New password.
        new_password_confirm: New password confirmation.
    """

    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
    new_password_confirm: str

    @field_validator("new_password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Validate that passwords match."""
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class ForgotPassword(BaseModel):
    """Schema for forgot password request.

    Attributes:
        email: User's email address.
    """

    email: EmailStr


class PasswordReset(BaseModel):
    """Schema for password reset.

    Attributes:
        token: Password reset token.
        new_password: New password.
        new_password_confirm: New password confirmation.
    """

    token: str
    new_password: str = Field(..., min_length=8, max_length=100)
    new_password_confirm: str

    @field_validator("new_password_confirm")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Validate that passwords match."""
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v
