"""Authentication: bcrypt password check + itsdangerous session cookies."""

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from admin_app.config import settings

_serializer = URLSafeTimedSerializer(settings.admin_secret_key)

SESSION_MAX_AGE = 86400  # 24 hours


def verify_password(plain: str, hashed: str) -> bool:
    """Check plain password against bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    """Hash a plain password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def create_session_token(username: str) -> str:
    """Create a signed session token."""
    return _serializer.dumps({"user": username})


def validate_session_token(token: str) -> str | None:
    """Validate session token. Returns username or None."""
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None
