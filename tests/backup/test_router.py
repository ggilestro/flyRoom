"""Tests for backup API endpoints."""

import json
from datetime import UTC, datetime

from fastapi import status


class TestExportEndpoint:
    """Test export endpoint."""

    def test_export_requires_admin(self, client, regular_user_headers):
        """Test that export requires admin access."""
        response = client.post(
            "/api/admin/backup/export",
            headers=regular_user_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_export_returns_json_file(self, client, admin_headers, db_session):
        """Test that export returns a downloadable JSON file."""
        response = client.post(
            "/api/admin/backup/export",
            headers=admin_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        assert "attachment" in response.headers.get("content-disposition", "")

        # Verify it's valid JSON with expected structure
        data = response.json()
        assert "metadata" in data
        assert "data" in data
        assert "schema_version" in data["metadata"]
        assert "exported_at" in data["metadata"]


class TestValidateEndpoint:
    """Test validate endpoint."""

    def test_validate_requires_admin(self, client, regular_user_headers):
        """Test that validate requires admin access."""
        response = client.post(
            "/api/admin/backup/validate",
            headers=regular_user_headers,
            files={"file": ("backup.json", b"{}", "application/json")},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_validate_invalid_json(self, client, admin_headers):
        """Test validation rejects invalid JSON."""
        response = client.post(
            "/api/admin/backup/validate",
            headers=admin_headers,
            files={"file": ("backup.json", b"not json", "application/json")},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_validate_missing_metadata(self, client, admin_headers):
        """Test validation rejects backup without metadata."""
        backup = json.dumps({"data": {}}).encode()
        response = client.post(
            "/api/admin/backup/validate",
            headers=admin_headers,
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_valid"] is False

    def test_validate_valid_backup(self, client, admin_headers):
        """Test validation accepts valid backup."""
        backup = json.dumps(
            {
                "metadata": {
                    "schema_version": "008",
                    "export_version": "1.0",
                    "exported_at": datetime.now(UTC).isoformat(),
                    "tenant_id": "test",
                    "tenant_name": "Test",
                },
                "data": {"users": [], "stocks": []},
            }
        ).encode()

        response = client.post(
            "/api/admin/backup/validate",
            headers=admin_headers,
            files={"file": ("backup.json", backup, "application/json")},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_valid"] is True


class TestImportEndpoint:
    """Test import endpoint."""

    def test_import_requires_admin(self, client, regular_user_headers):
        """Test that import requires admin access."""
        response = client.post(
            "/api/admin/backup/import",
            headers=regular_user_headers,
            files={"file": ("backup.json", b"{}", "application/json")},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_import_rejects_invalid_backup(self, client, admin_headers):
        """Test import rejects invalid backup files."""
        backup = json.dumps({"data": {}}).encode()  # Missing metadata
        response = client.post(
            "/api/admin/backup/import",
            headers=admin_headers,
            files={"file": ("backup.json", backup, "application/json")},
            data={"conflict_mode": "fail", "dry_run": "false"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_dry_run_does_not_persist(self, client, admin_headers, db_session):
        """Test dry run mode does not persist changes."""
        backup = json.dumps(
            {
                "metadata": {
                    "schema_version": "008",
                    "export_version": "1.0",
                    "exported_at": datetime.now(UTC).isoformat(),
                    "tenant_id": "test",
                    "tenant_name": "Test",
                },
                "data": {"users": [], "stocks": []},
            }
        ).encode()

        response = client.post(
            "/api/admin/backup/import",
            headers=admin_headers,
            files={"file": ("backup.json", backup, "application/json")},
            data={"conflict_mode": "fail", "dry_run": "true"},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True


class TestRoundTrip:
    """Test export then import round-trip."""

    def test_export_import_round_trip(self, client, admin_headers, db_session):
        """Test that exported data can be reimported."""
        # Export
        export_response = client.post(
            "/api/admin/backup/export",
            headers=admin_headers,
        )
        assert export_response.status_code == status.HTTP_200_OK
        backup_data = export_response.content

        # Validate the export
        validate_response = client.post(
            "/api/admin/backup/validate",
            headers=admin_headers,
            files={"file": ("backup.json", backup_data, "application/json")},
        )
        assert validate_response.status_code == status.HTTP_200_OK
        assert validate_response.json()["is_valid"] is True

        # Dry run import
        import_response = client.post(
            "/api/admin/backup/import",
            headers=admin_headers,
            files={"file": ("backup.json", backup_data, "application/json")},
            data={"conflict_mode": "skip", "dry_run": "true"},
        )
        assert import_response.status_code == status.HTTP_200_OK
        assert import_response.json()["success"] is True


# Fixtures would be defined in conftest.py
# These are placeholder docstrings showing what the tests expect

"""
Expected fixtures in conftest.py:

@pytest.fixture
def client():
    '''FastAPI test client.'''
    from app.main import app
    return TestClient(app)

@pytest.fixture
def admin_headers(admin_user):
    '''Headers with admin auth token.'''
    return {"Authorization": f"Bearer {admin_user.token}"}

@pytest.fixture
def regular_user_headers(regular_user):
    '''Headers with regular user auth token.'''
    return {"Authorization": f"Bearer {regular_user.token}"}

@pytest.fixture
def db_session():
    '''Database session for tests.'''
    ...
"""
