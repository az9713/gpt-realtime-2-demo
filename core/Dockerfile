FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into system Python so that a bind-mount of /app
# in dev does not shadow a venv. Editable install picks up code changes
# from the mount automatically.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

# alembic + tests come in via the bind mount in dev.
EXPOSE 8000

CMD ["uvicorn", "cockpit_core.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
