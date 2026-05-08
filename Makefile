SHELL := /bin/bash

.PHONY: help dev up down build logs ps migrate seed seed-hvac tunnel \
        test test-core test-edge test-eval test-e2e replay trace \
        lint lint-core lint-edge lint-frontend fmt clean

help:
	@echo "Voice Operations Cockpit — make targets"
	@echo ""
	@echo "  Dev:"
	@echo "    make dev          docker-compose up with hot reload"
	@echo "    make up           docker-compose up -d (production-style)"
	@echo "    make down         stop everything"
	@echo "    make logs         tail all service logs"
	@echo "    make ps           show service status"
	@echo "    make build        build all images"
	@echo ""
	@echo "  Database:"
	@echo "    make migrate      alembic upgrade head"
	@echo "    make seed-hvac    load HVAC fixtures"
	@echo ""
	@echo "  Tests:"
	@echo "    make test         full suite"
	@echo "    make test-core    Python only"
	@echo "    make test-edge    Node only"
	@echo "    make test-eval    vertical scenario evals"
	@echo "    make test-e2e     end-to-end smoke"
	@echo ""
	@echo "  Operator:"
	@echo "    make tunnel               cloudflared tunnel for Twilio"
	@echo "    make replay CONV=<uuid>   rehydrate a past conversation"
	@echo "    make trace CONV=<uuid>    print trace timeline"
	@echo ""
	@echo "  Code quality:"
	@echo "    make lint         all linters"
	@echo "    make fmt          all formatters"

dev:
	docker compose up

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

migrate:
	docker compose run --rm core alembic upgrade head

seed: seed-hvac

seed-hvac:
	bash scripts/seed-hvac.sh

tunnel:
	bash scripts/tunnel.sh

audit:
	cd core && uv run python ../scripts/audit-divergences.py $(ARGS)

synthesize-eval:
	cd core && uv run python ../scripts/synthesize-eval.py $(CONV)

test: test-core test-edge test-eval

test-core:
	cd core && uv run pytest -q

test-edge:
	cd edge && npm test --silent

test-eval:
	cd core && uv run pytest tests/eval -q

test-e2e:
	bash e2e/run.sh

replay:
	cd core && uv run python ../scripts/replay-conversation.py $(CONV)

trace:
	cd core && uv run python ../scripts/trace-dump.py $(CONV)

lint: lint-core lint-edge lint-frontend

lint-core:
	cd core && uv run ruff check . && uv run mypy --strict src

lint-edge:
	cd edge && npm run lint --silent

lint-frontend:
	cd frontend && npm run lint --silent

fmt:
	cd core && uv run black . && uv run ruff check --fix .
	cd edge && npm run fmt --silent
	cd frontend && npm run fmt --silent

clean:
	docker compose down -v
	rm -rf core/.venv core/__pycache__ core/**/__pycache__
	rm -rf edge/node_modules edge/dist
	rm -rf frontend/node_modules frontend/dist
