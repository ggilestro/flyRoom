"""SQL dump export via mariadb-dump subprocess."""

import gzip
import subprocess
from collections.abc import Generator

from admin_app.config import settings


def stream_sql_dump(compress: bool = False) -> Generator[bytes, None, None]:
    """Stream a mariadb-dump as bytes. Optionally gzip-compressed."""
    cmd = [
        "mariadb-dump",
        f"--host={settings.db_host}",
        f"--user={settings.db_user}",
        f"--password={settings.db_password}",
        "--skip-ssl",
        "--single-transaction",
        "--routines",
        "--triggers",
        settings.db_name,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if compress:
        import io

        buf = io.BytesIO()
        gz = gzip.GzipFile(fileobj=buf, mode="wb")
        for chunk in iter(lambda: proc.stdout.read(8192), b""):  # type: ignore[union-attr]
            gz.write(chunk)
            buf.seek(0)
            data = buf.read()
            if data:
                yield data
            buf.seek(0)
            buf.truncate()
        gz.close()
        buf.seek(0)
        remaining = buf.read()
        if remaining:
            yield remaining
    else:
        for chunk in iter(lambda: proc.stdout.read(8192), b""):  # type: ignore[union-attr]
            yield chunk

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr else b""  # type: ignore[union-attr]
        raise RuntimeError(f"mariadb-dump failed: {stderr.decode()}")
