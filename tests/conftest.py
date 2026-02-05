"""Pytest configuration and fixtures."""

import os
from collections.abc import Generator
from uuid import uuid4

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["DEBUG"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.utils import get_password_hash
from app.db.models import (
    Base,
    Organization,
    Tenant,
    Tray,
    TrayType,
    User,
    UserRole,
    UserStatus,
)

# Use in-memory SQLite for testing
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""
    # Import here to ensure env vars are set
    from app.dependencies import get_db
    from app.main import app

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_tenant(db: Session) -> Tenant:
    """Create a test tenant."""
    tenant = Tenant(
        id=str(uuid4()),
        name="Test Lab",
        slug="test-lab",
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def test_user(db: Session, test_tenant: Tenant) -> User:
    """Create a test user."""
    user = User(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        email="test@example.com",
        password_hash=get_password_hash("testpassword123"),
        full_name="Test User",
        role=UserRole.USER,
        status=UserStatus.APPROVED,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_admin(db: Session, test_tenant: Tenant) -> User:
    """Create a test admin user."""
    admin = User(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        email="admin@example.com",
        password_hash=get_password_hash("adminpassword123"),
        full_name="Admin User",
        role=UserRole.ADMIN,
        status=UserStatus.APPROVED,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@pytest.fixture
def authenticated_client(client: TestClient, test_user: User) -> TestClient:
    """Create an authenticated test client."""
    from app.dependencies import get_current_user
    from app.main import app

    def override_get_current_user():
        return test_user

    app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def admin_client(client: TestClient, test_admin: User) -> TestClient:
    """Create an admin-authenticated test client."""
    from app.dependencies import get_current_user
    from app.main import app

    def override_get_current_user():
        return test_admin

    app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def test_organization(db: Session) -> Organization:
    """Create a test organization."""
    org = Organization(
        id=str(uuid4()),
        name="Test University",
        slug="test-university",
        normalized_name="test university",
        description="A test organization",
        is_active=True,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def test_tenant_with_org(db: Session, test_organization: Organization) -> Tenant:
    """Create a test tenant with organization."""
    tenant = Tenant(
        id=str(uuid4()),
        name="Org Lab",
        slug="org-lab",
        organization_id=test_organization.id,
        is_org_admin=True,
        city="London",
        country="UK",
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def test_tray(db: Session, test_tenant: Tenant) -> Tray:
    """Create a test tray."""
    tray = Tray(
        id=str(uuid4()),
        tenant_id=test_tenant.id,
        name="Tray A",
        description="Test tray",
        tray_type=TrayType.NUMERIC,
        max_positions=100,
    )
    db.add(tray)
    db.commit()
    db.refresh(tray)
    return tray
