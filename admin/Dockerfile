FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (mariadb-client for SQL dumps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmariadb-dev \
    pkg-config \
    mariadb-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (separate step for Docker layer caching)
RUN pip install --no-cache-dir \
    "fastapi>=0.104.0" \
    "uvicorn[standard]>=0.24.0" \
    "sqlalchemy>=2.0.0" \
    "pymysql>=1.1.0" \
    "jinja2>=3.1.0" \
    "itsdangerous>=2.1.0" \
    "bcrypt>=4.0.0" \
    "python-multipart>=0.0.6" \
    "pydantic-settings>=2.0.0" \
    "httpx>=0.25.0" \
    "boto3>=1.34.0" \
    "cryptography>=42.0.0"

# Copy admin application code
COPY admin/admin_app/ ./admin_app/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

CMD ["uvicorn", "admin_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
