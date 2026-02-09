"""Tests for the email invitation system."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.auth.utils import get_password_hash
from app.db.models import (
    Invitation,
    InvitationStatus,
    InvitationType,
    Organization,
    Tenant,
    User,
    UserRole,
    UserStatus,
)
from app.tenants.schemas import InvitationCreate
from app.tenants.service import TenantService


@pytest.fixture
def org(db: Session) -> Organization:
    """Create an organization for tests."""
    organization = Organization(
        id=str(uuid4()),
        name="Test University",
        slug="test-university",
        normalized_name="test university",
        is_active=True,
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture
def tenant_with_org(db: Session, org: Organization) -> Tenant:
    """Create a tenant with organization."""
    tenant = Tenant(
        id=str(uuid4()),
        name="Smith Lab",
        slug="smith-lab",
        organization_id=org.id,
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def tenant_no_org(db: Session) -> Tenant:
    """Create a tenant without organization."""
    tenant = Tenant(
        id=str(uuid4()),
        name="Standalone Lab",
        slug="standalone-lab",
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def admin_user(db: Session, tenant_with_org: Tenant) -> User:
    """Create an admin user."""
    user = User(
        id=str(uuid4()),
        tenant_id=tenant_with_org.id,
        email="admin@test.edu",
        password_hash=get_password_hash("password123"),
        full_name="Dr. Smith",
        role=UserRole.ADMIN,
        status=UserStatus.APPROVED,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def existing_member(db: Session, tenant_with_org: Tenant) -> User:
    """Create an existing member in the tenant."""
    user = User(
        id=str(uuid4()),
        tenant_id=tenant_with_org.id,
        email="existing@test.edu",
        password_hash=get_password_hash("password123"),
        full_name="Existing Member",
        role=UserRole.USER,
        status=UserStatus.APPROVED,
        is_active=True,
        is_email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def service(db: Session, tenant_with_org: Tenant) -> TenantService:
    """Create a TenantService instance."""
    return TenantService(db, tenant_with_org.id)


@pytest.fixture
def service_no_org(db: Session, tenant_no_org: Tenant) -> TenantService:
    """Create a TenantService instance for tenant without org."""
    return TenantService(db, tenant_no_org.id)


# --- Create Invitation Tests ---


@patch("app.email.service.get_email_service")
def test_create_lab_member_invitation(mock_email, db, service, admin_user):
    """Test creating a lab member invitation."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="newmember@test.edu", invitation_type="lab_member")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    assert result.email == "newmember@test.edu"
    assert result.invitation_type == "lab_member"
    assert result.status == "pending"
    assert result.invited_by_name == "Dr. Smith"

    # Verify DB record
    inv = db.query(Invitation).filter(Invitation.email == "newmember@test.edu").first()
    assert inv is not None
    assert inv.invitation_type == InvitationType.LAB_MEMBER
    assert inv.status == InvitationStatus.PENDING
    assert inv.token is not None
    assert len(inv.token) == 64


@patch("app.email.service.get_email_service")
def test_create_new_tenant_invitation(mock_email, db, service, admin_user, org):
    """Test creating a new tenant invitation."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="newpi@test.edu", invitation_type="new_tenant")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    assert result.email == "newpi@test.edu"
    assert result.invitation_type == "new_tenant"
    assert result.status == "pending"

    # Verify org_id is denormalized
    inv = db.query(Invitation).filter(Invitation.email == "newpi@test.edu").first()
    assert inv.organization_id == org.id


@patch("app.email.service.get_email_service")
def test_create_new_tenant_fails_without_org(mock_email, service_no_org):
    """Test that new_tenant invitation fails when tenant has no org."""
    # Need an admin user for the no-org tenant
    data = InvitationCreate(email="someone@test.edu", invitation_type="new_tenant")
    with pytest.raises(ValueError, match="not part of an organization"):
        service_no_org.create_invitation(data, str(uuid4()), "http://localhost")


@patch("app.email.service.get_email_service")
def test_duplicate_pending_invitation_rejected(mock_email, service, admin_user):
    """Test that duplicate pending invitations are rejected."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="duplicate@test.edu", invitation_type="lab_member")
    service.create_invitation(data, admin_user.id, "http://localhost")

    with pytest.raises(ValueError, match="pending invitation already exists"):
        service.create_invitation(data, admin_user.id, "http://localhost")


@patch("app.email.service.get_email_service")
def test_existing_member_email_rejected(mock_email, service, admin_user, existing_member):
    """Test that inviting an existing member is rejected."""
    data = InvitationCreate(email="existing@test.edu", invitation_type="lab_member")
    with pytest.raises(ValueError, match="already a member"):
        service.create_invitation(data, admin_user.id, "http://localhost")


# --- List Invitations Tests ---


@patch("app.email.service.get_email_service")
def test_list_invitations(mock_email, db, service, admin_user):
    """Test listing invitations."""
    mock_email.return_value.send_invitation_email.return_value = True

    service.create_invitation(
        InvitationCreate(email="a@test.edu"), admin_user.id, "http://localhost"
    )
    service.create_invitation(
        InvitationCreate(email="b@test.edu"), admin_user.id, "http://localhost"
    )

    result = service.list_invitations()
    assert len(result) == 2
    emails = {r.email for r in result}
    assert "a@test.edu" in emails
    assert "b@test.edu" in emails


@patch("app.email.service.get_email_service")
def test_list_invitations_marks_expired(mock_email, db, service, admin_user, tenant_with_org):
    """Test that listing auto-marks expired invitations."""
    # Create an expired invitation directly
    inv = Invitation(
        tenant_id=tenant_with_org.id,
        invited_by_id=admin_user.id,
        email="expired@test.edu",
        invitation_type=InvitationType.LAB_MEMBER,
        token="expired-token-" + str(uuid4())[:20],
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(inv)
    db.commit()

    result = service.list_invitations()
    assert len(result) == 1
    assert result[0].status == "expired"


# --- Cancel/Resend Tests ---


@patch("app.email.service.get_email_service")
def test_cancel_invitation(mock_email, db, service, admin_user):
    """Test cancelling an invitation."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="cancel@test.edu")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    assert service.cancel_invitation(result.id)

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()
    assert inv.status == InvitationStatus.CANCELLED


def test_cancel_nonexistent_invitation(service):
    """Test cancelling a non-existent invitation returns False."""
    assert not service.cancel_invitation(str(uuid4()))


@patch("app.email.service.get_email_service")
def test_resend_invitation(mock_email, db, service, admin_user):
    """Test resending an invitation extends expiry."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="resend@test.edu")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    # Get original expiry
    inv = db.query(Invitation).filter(Invitation.id == result.id).first()
    original_expiry = inv.expires_at

    assert service.resend_invitation(result.id, "http://localhost")

    db.refresh(inv)
    # Expiry should be extended (new 7-day window)
    assert inv.expires_at >= original_expiry


# --- Token Validation Tests ---


@patch("app.email.service.get_email_service")
def test_validate_invitation_token_valid(mock_email, db, service, admin_user):
    """Test validating a valid token."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="valid@test.edu")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()
    validated = TenantService.validate_invitation_token(db, inv.token)
    assert validated is not None
    assert validated.email == "valid@test.edu"


def test_validate_invitation_token_expired(db, tenant_with_org, admin_user):
    """Test that expired tokens return None."""
    inv = Invitation(
        tenant_id=tenant_with_org.id,
        invited_by_id=admin_user.id,
        email="expired@test.edu",
        invitation_type=InvitationType.LAB_MEMBER,
        token="token-expired-" + str(uuid4())[:20],
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(inv)
    db.commit()

    result = TenantService.validate_invitation_token(db, inv.token)
    assert result is None

    # Should be marked expired in DB
    db.refresh(inv)
    assert inv.status == InvitationStatus.EXPIRED


def test_validate_invitation_token_accepted(db, tenant_with_org, admin_user):
    """Test that accepted tokens return None."""
    inv = Invitation(
        tenant_id=tenant_with_org.id,
        invited_by_id=admin_user.id,
        email="accepted@test.edu",
        invitation_type=InvitationType.LAB_MEMBER,
        token="token-accepted-" + str(uuid4())[:20],
        status=InvitationStatus.ACCEPTED,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.commit()

    result = TenantService.validate_invitation_token(db, inv.token)
    assert result is None


def test_validate_invitation_token_nonexistent(db):
    """Test that nonexistent tokens return None."""
    result = TenantService.validate_invitation_token(db, "nonexistent-token")
    assert result is None


# --- Accept Invitation Tests ---


@patch("app.email.service.get_email_service")
def test_accept_invitation(mock_email, db, service, admin_user):
    """Test accepting an invitation."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="accept@test.edu")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()
    accepted = TenantService.accept_invitation(db, inv.token)
    assert accepted is not None
    assert accepted.status == InvitationStatus.ACCEPTED
    assert accepted.accepted_at is not None


# --- Get Invitation Validation Tests ---


@patch("app.email.service.get_email_service")
def test_get_invitation_validation(mock_email, db, service, admin_user, org, tenant_with_org):
    """Test getting invitation validation data."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="validate@test.edu", invitation_type="new_tenant")
    result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()
    validation = TenantService.get_invitation_validation(db, inv.token)

    assert validation is not None
    assert validation.email == "validate@test.edu"
    assert validation.invitation_type == "new_tenant"
    assert validation.tenant_name == "Smith Lab"
    assert validation.organization_name == "Test University"


# --- Registration via Invitation Tests ---


@patch("app.auth.service.get_email_service")
def test_register_via_lab_member_invitation(mock_email, db, service, admin_user, tenant_with_org):
    """Test registration via LAB_MEMBER invitation creates auto-approved user."""
    mock_email.return_value.send_invitation_email.return_value = True
    mock_email.return_value.send_verification_email.return_value = True

    # Create invitation
    data = InvitationCreate(email="invitee@test.edu")
    with patch("app.email.service.get_email_service", return_value=mock_email.return_value):
        result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()

    # Register with invitation token
    from app.auth.schemas import UserRegister
    from app.auth.service import AuthService

    auth = AuthService(db)
    reg_data = UserRegister(
        full_name="New Invitee",
        email="invitee@test.edu",
        password="securepassword123",
        password_confirm="securepassword123",
        invitation_token=inv.token,
    )
    user, token, message = auth.register(reg_data, "http://localhost")

    assert user is not None
    assert user.tenant_id == tenant_with_org.id
    assert user.role == UserRole.USER
    assert user.status == UserStatus.APPROVED
    assert "successful" in message.lower()

    # Invitation should be accepted
    db.refresh(inv)
    assert inv.status == InvitationStatus.ACCEPTED


@patch("app.auth.service.get_email_service")
def test_register_via_new_tenant_invitation(
    mock_email, db, service, admin_user, org, tenant_with_org
):
    """Test registration via NEW_TENANT invitation creates new lab in org."""
    mock_email.return_value.send_invitation_email.return_value = True
    mock_email.return_value.send_verification_email.return_value = True

    # Create invitation
    data = InvitationCreate(email="newpi@test.edu", invitation_type="new_tenant")
    with patch("app.email.service.get_email_service", return_value=mock_email.return_value):
        result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()

    # Register with invitation token
    from app.auth.schemas import UserRegister
    from app.auth.service import AuthService

    auth = AuthService(db)
    reg_data = UserRegister(
        full_name="New PI",
        email="newpi@test.edu",
        password="securepassword123",
        password_confirm="securepassword123",
        invitation_token=inv.token,
        is_pi=True,
        organization="Test University",
        lab_name="Jones Lab",
    )
    user, token, message = auth.register(reg_data, "http://localhost")

    assert user is not None
    assert user.role == UserRole.ADMIN
    assert user.status == UserStatus.APPROVED

    # User should be in a NEW tenant, not the inviter's tenant
    assert user.tenant_id != tenant_with_org.id

    # New tenant should be in the same org
    new_tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    assert new_tenant is not None
    assert new_tenant.organization_id == org.id
    assert new_tenant.name == "Jones Lab"

    # Invitation should be accepted
    db.refresh(inv)
    assert inv.status == InvitationStatus.ACCEPTED


@patch("app.auth.service.get_email_service")
def test_register_with_wrong_email_fails(mock_email, db, service, admin_user, tenant_with_org):
    """Test that registration with wrong email fails."""
    mock_email.return_value.send_invitation_email.return_value = True

    data = InvitationCreate(email="invited@test.edu")
    with patch("app.email.service.get_email_service", return_value=mock_email.return_value):
        result = service.create_invitation(data, admin_user.id, "http://localhost")

    inv = db.query(Invitation).filter(Invitation.id == result.id).first()

    from app.auth.schemas import UserRegister
    from app.auth.service import AuthService

    auth = AuthService(db)
    reg_data = UserRegister(
        full_name="Wrong Person",
        email="wrong@test.edu",
        password="securepassword123",
        password_confirm="securepassword123",
        invitation_token=inv.token,
    )

    with pytest.raises(ValueError, match="does not match"):
        auth.register(reg_data, "http://localhost")


# --- API Endpoint Tests ---


@patch("app.email.service.get_email_service")
def test_api_create_invitation(mock_email, admin_client, test_admin, test_tenant):
    """Test POST /api/admin/invitations endpoint."""
    mock_email.return_value.send_invitation_email.return_value = True

    response = admin_client.post(
        "/api/admin/invitations",
        json={"email": "api-invite@test.edu", "invitation_type": "lab_member"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "api-invite@test.edu"
    assert data["status"] == "pending"


@patch("app.email.service.get_email_service")
def test_api_list_invitations(mock_email, admin_client, test_admin, test_tenant):
    """Test GET /api/admin/invitations endpoint."""
    mock_email.return_value.send_invitation_email.return_value = True

    # Create one first
    admin_client.post(
        "/api/admin/invitations",
        json={"email": "list@test.edu"},
    )

    response = admin_client.get("/api/admin/invitations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@patch("app.email.service.get_email_service")
def test_api_cancel_invitation(mock_email, admin_client, db, test_admin, test_tenant):
    """Test POST /api/admin/invitations/{id}/cancel endpoint."""
    mock_email.return_value.send_invitation_email.return_value = True

    create_resp = admin_client.post(
        "/api/admin/invitations",
        json={"email": "cancel-api@test.edu"},
    )
    inv_id = create_resp.json()["id"]

    response = admin_client.post(f"/api/admin/invitations/{inv_id}/cancel")
    assert response.status_code == 200


@patch("app.email.service.get_email_service")
def test_api_resend_invitation(mock_email, admin_client, db, test_admin, test_tenant):
    """Test POST /api/admin/invitations/{id}/resend endpoint."""
    mock_email.return_value.send_invitation_email.return_value = True

    create_resp = admin_client.post(
        "/api/admin/invitations",
        json={"email": "resend-api@test.edu"},
    )
    inv_id = create_resp.json()["id"]

    response = admin_client.post(f"/api/admin/invitations/{inv_id}/resend")
    assert response.status_code == 200


def test_api_validate_invitation_token(client, db, test_tenant):
    """Test GET /api/auth/invitation/{token} endpoint."""
    # Create an invitation directly
    inv = Invitation(
        tenant_id=test_tenant.id,
        invited_by_id=None,
        email="validate-api@test.edu",
        invitation_type=InvitationType.LAB_MEMBER,
        token="validate-api-token-" + str(uuid4())[:16],
        status=InvitationStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.commit()

    response = client.get(f"/api/auth/invitation/{inv.token}")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "validate-api@test.edu"
    assert data["invitation_type"] == "lab_member"
    assert data["tenant_name"] == "Test Lab"


def test_api_validate_invalid_token(client):
    """Test GET /api/auth/invitation/{token} with invalid token."""
    response = client.get("/api/auth/invitation/nonexistent-token")
    assert response.status_code == 404
