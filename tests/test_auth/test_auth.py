"""Tests for authentication module."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Tenant, User, UserStatus


class TestRegister:
    """Tests for user registration."""

    def test_register_pi_success(self, client: TestClient, db: Session):
        """Test PI registration creates tenant and admin user."""
        response = client.post(
            "/api/auth/register",
            json={
                "organization": "Harvard",
                "full_name": "Dr. John Smith",
                "email": "john@harvard.edu",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": True,
            },
        )

        if response.status_code != 201:
            print(f"Response: {response.json()}")
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert data["token"]["access_token"] is not None
        assert data["pending_approval"] is False

        # Verify tenant was created with slug including PI name
        tenant = db.query(Tenant).filter(Tenant.slug == "harvard-dr-john-smith").first()
        assert tenant is not None
        assert tenant.name == "Harvard"
        assert tenant.invitation_token is not None

        # Verify user was created as admin and approved
        user = db.query(User).filter(User.email == "john@harvard.edu").first()
        assert user is not None
        assert user.role.value == "admin"
        assert user.status == UserStatus.APPROVED

    def test_register_multiple_pis_same_org(self, client: TestClient, db: Session):
        """Test multiple PIs from same organization can each create their own lab."""
        # First PI
        response1 = client.post(
            "/api/auth/register",
            json={
                "organization": "MIT",
                "full_name": "Dr. Alice Jones",
                "email": "alice@mit.edu",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": True,
            },
        )
        assert response1.status_code == 201

        # Second PI from same organization
        response2 = client.post(
            "/api/auth/register",
            json={
                "organization": "MIT",
                "full_name": "Dr. Bob Wilson",
                "email": "bob@mit.edu",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": True,
            },
        )
        assert response2.status_code == 201

        # Both should have their own tenants
        tenants = db.query(Tenant).filter(Tenant.name == "MIT").all()
        assert len(tenants) == 2

    def test_register_member_pending_by_pi_name(
        self, client: TestClient, db: Session, test_admin: User
    ):
        """Test member registration by PI name without invitation is pending."""
        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Jane Member",
                "email": "jane@example.com",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": False,
                "pi_identifier": test_admin.full_name,
            },
        )

        if response.status_code != 201:
            print(f"Response: {response.json()}")
        assert response.status_code == 201
        data = response.json()
        assert data["pending_approval"] is True
        assert data["token"] is None

        # Verify user is pending
        user = db.query(User).filter(User.email == "jane@example.com").first()
        assert user is not None
        assert user.status == UserStatus.PENDING

    def test_register_member_pending_by_pi_email(
        self, client: TestClient, db: Session, test_admin: User
    ):
        """Test member registration by PI email without invitation is pending."""
        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Bob Member",
                "email": "bob@example.com",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": False,
                "pi_identifier": test_admin.email,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["pending_approval"] is True

    def test_register_member_with_invitation(
        self, client: TestClient, db: Session, test_tenant: Tenant
    ):
        """Test member registration with invitation is auto-approved."""
        # Set invitation token on tenant
        test_tenant.invitation_token = "test-invite-token-123"
        db.commit()

        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Jane Invited",
                "email": "jane.invited@example.com",
                "password": "securepassword123",
                "password_confirm": "securepassword123",
                "is_pi": False,
                "invitation_token": "test-invite-token-123",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["pending_approval"] is False
        assert data["token"] is not None

        # Verify user is approved
        user = db.query(User).filter(User.email == "jane.invited@example.com").first()
        assert user is not None
        assert user.status == UserStatus.APPROVED

    def test_register_password_mismatch(self, client: TestClient):
        """Test registration fails when passwords don't match."""
        response = client.post(
            "/api/auth/register",
            json={
                "organization": "Test Lab",
                "full_name": "Jane Doe",
                "email": "jane@test.com",
                "password": "password123",
                "password_confirm": "different123",
                "is_pi": True,
            },
        )

        assert response.status_code == 422  # Validation error

    def test_register_short_password(self, client: TestClient):
        """Test registration fails with short password."""
        response = client.post(
            "/api/auth/register",
            json={
                "organization": "Test Lab",
                "full_name": "Jane Doe",
                "email": "jane@test.com",
                "password": "short",
                "password_confirm": "short",
                "is_pi": True,
            },
        )

        assert response.status_code == 422


class TestLogin:
    """Tests for user login."""

    def test_login_success(self, client: TestClient, test_user: User):
        """Test successful login returns tokens."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "test@example.com",
                "password": "testpassword123",
            },
        )

        if response.status_code != 200:
            print(f"Login response: {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token"]["access_token"] is not None

    def test_login_wrong_password(self, client: TestClient, test_user: User):
        """Test login fails with wrong password."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "test@example.com",
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    def test_login_nonexistent_user(self, client: TestClient):
        """Test login fails for nonexistent user."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "anypassword",
            },
        )

        assert response.status_code == 401

    def test_login_pending_user(self, client: TestClient, db: Session, test_tenant: Tenant):
        """Test login fails for pending user."""
        from uuid import uuid4

        from app.auth.utils import get_password_hash

        # Create a pending user
        pending_user = User(
            id=str(uuid4()),
            tenant_id=test_tenant.id,
            email="pending@example.com",
            password_hash=get_password_hash("testpassword123"),
            full_name="Pending User",
            status=UserStatus.PENDING,
            is_active=True,
        )
        db.add(pending_user)
        db.commit()

        response = client.post(
            "/api/auth/login",
            json={
                "email": "pending@example.com",
                "password": "testpassword123",
            },
        )

        assert response.status_code == 401
        assert "pending approval" in response.json()["detail"]


class TestCurrentUser:
    """Tests for current user endpoint."""

    def test_get_current_user(self, authenticated_client: TestClient, test_user: User):
        """Test getting current user info."""
        response = authenticated_client.get("/api/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["full_name"] == test_user.full_name

    def test_get_current_user_unauthenticated(self, client: TestClient):
        """Test getting current user without auth fails."""
        response = client.get("/api/auth/me")

        assert response.status_code == 401
