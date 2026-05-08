#!/usr/bin/env bash
# End-to-end smoke test (Phase 9 Task 41).
#
# Brings up the full stack via docker-compose, runs migrations, seeds
# HVAC, then runs an in-process scenario suite that exercises the
# agent core through its HTTP API. Twilio is mocked at the WebSocket
# boundary; OpenAI Realtime is also mocked.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "[e2e] bringing up stack"
docker compose up -d postgres redis

echo "[e2e] waiting for postgres"
for _ in {1..30}; do
  if docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-cockpit}" -d "${POSTGRES_DB:-cockpit}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[e2e] running migrations"
docker compose run --rm core uv run alembic upgrade head

echo "[e2e] running scenario evals"
docker compose run --rm core uv run pytest tests/eval -q

echo "[e2e] tearing down"
docker compose down

echo "[e2e] OK"
