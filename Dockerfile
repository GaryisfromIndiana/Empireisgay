FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir . && pip install --no-cache-dir redis gunicorn

# Copy application
COPY . .

# Run database init + seed on startup, then launch with gunicorn
CMD ["sh", "-c", "python -c 'from db.engine import init_db; init_db()' && python seed.py || echo 'Seed skipped'; exec gunicorn 'web.app:create_app()' --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 4 --timeout 600 --preload --access-logfile -"]
