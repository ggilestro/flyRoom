"""Automated database backup service — dump, encrypt, upload to Cloudflare R2."""

import base64
import gzip
import io
import logging
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta

import boto3
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from admin_app.config import settings
from app.db.models import BackupLog

logger = logging.getLogger(__name__)

NONCE_SIZE = 12  # bytes


def _get_encryption_key() -> bytes:
    """Decode the base64 encryption key from settings. Raises if missing."""
    raw = settings.backup_encryption_key
    if not raw:
        raise RuntimeError(
            "BACKUP_ENCRYPTION_KEY is not set — refusing to create unencrypted backup"
        )
    key = base64.urlsafe_b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def _get_s3_client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    if not settings.r2_endpoint_url:
        raise RuntimeError("R2_ENDPOINT_URL is not configured")
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
    )


def _encrypt(data: bytes) -> bytes:
    """Encrypt data with AES-256-GCM. Returns nonce + ciphertext (tag appended)."""
    key = _get_encryption_key()
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)  # ciphertext includes tag
    return nonce + ciphertext


def _decrypt(data: bytes) -> bytes:
    """Decrypt nonce-prefixed AES-256-GCM ciphertext."""
    key = _get_encryption_key()
    nonce = data[:NONCE_SIZE]
    ciphertext = data[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def run_backup(db: Session) -> dict:
    """Run a full database backup: dump → gzip → encrypt → upload to R2.

    Returns the backup log entry as a dict.
    """
    started = time.monotonic()
    filename = f"flyroom_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.sql.gz.enc"

    try:
        # 1. mariadb-dump → bytes
        cmd = [
            "mariadb-dump",
            f"--host={settings.db_host}",
            f"--user={settings.db_user}",
            f"--password={settings.db_password}",
            "--single-transaction",
            "--routines",
            "--triggers",
            settings.db_name,
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"mariadb-dump failed: {proc.stderr.decode()}")

        sql_bytes = proc.stdout

        # 2. Gzip compress
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(sql_bytes)
        compressed = buf.getvalue()

        # 3. Encrypt
        encrypted = _encrypt(compressed)

        # 4. Upload to R2
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=settings.r2_bucket_name,
            Key=filename,
            Body=encrypted,
            ContentType="application/octet-stream",
        )

        duration = time.monotonic() - started

        # 5. Log success
        log = BackupLog(
            filename=filename,
            size_bytes=len(encrypted),
            duration_seconds=round(duration, 2),
            status="success",
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        logger.info("Backup completed: %s (%d bytes, %.1fs)", filename, len(encrypted), duration)
        return _log_to_dict(log)

    except Exception as exc:
        duration = time.monotonic() - started
        log = BackupLog(
            filename=filename,
            size_bytes=0,
            duration_seconds=round(duration, 2),
            status="failed",
            error_message=str(exc)[:2000],
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        logger.error("Backup failed: %s", exc)
        return _log_to_dict(log)


def prune_old_backups(db: Session) -> int:
    """Delete R2 objects and DB log entries older than retention period.

    Returns number of entries pruned.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.backup_retention_days)
    old_logs = db.query(BackupLog).filter(BackupLog.created_at < cutoff).all()

    if not old_logs:
        return 0

    pruned = 0
    try:
        s3 = _get_s3_client()
    except RuntimeError:
        s3 = None

    for log in old_logs:
        # Try to delete from R2 (best-effort)
        if s3 and log.status == "success":
            try:
                s3.delete_object(Bucket=settings.r2_bucket_name, Key=log.filename)
            except Exception as exc:
                logger.warning("Failed to delete R2 object %s: %s", log.filename, exc)
        db.delete(log)
        pruned += 1

    db.commit()
    logger.info("Pruned %d old backup log(s)", pruned)
    return pruned


def list_backups(db: Session) -> list[dict]:
    """Return all backup log entries, newest first."""
    logs = db.query(BackupLog).order_by(BackupLog.created_at.desc()).all()
    return [_log_to_dict(log) for log in logs]


def download_backup(filename: str) -> bytes:
    """Download a backup from R2 and decrypt it, returning .sql.gz content."""
    s3 = _get_s3_client()
    resp = s3.get_object(Bucket=settings.r2_bucket_name, Key=filename)
    encrypted = resp["Body"].read()
    return _decrypt(encrypted)


def _log_to_dict(log: BackupLog) -> dict:
    return {
        "id": log.id,
        "filename": log.filename,
        "size_bytes": log.size_bytes,
        "duration_seconds": log.duration_seconds,
        "status": log.status,
        "error_message": log.error_message,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
