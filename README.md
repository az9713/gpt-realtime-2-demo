# Voice Operations Cockpit

Unified voice operations cockpit on top of OpenAI's GPT-Realtime API
family. One agent core, multiple surfaces (browser + phone), two modes
(Realtime-2 conversational + Realtime-Translate). v1 ships the HVAC
dispatcher vertical.

See `SPEC.md` for the contract and `PLAN.md` for the build order.

## Stack

- **Core (Python):** FastAPI + asyncpg + alembic. Agent runtime,
  tool registry, guardrails, persistence, observability.
- **Edge (Node + TS):** Fastify + ws. WebRTC signaling, Twilio Media
  Streams, OpenAI Realtime session manager.
- **Frontend (React + Vite + Tailwind):** Cockpit UI — live
  transcripts, approval queue, trace explorer.
- **Storage:** Postgres (durable) + Redis (ephemeral, pub/sub).

## Quick start

```bash
cp .env.example .env
# fill in OPENAI_API_KEY, TWILIO_*, COCKPIT_OPERATOR_PASSWORD
make build
make up
make migrate
make seed-hvac
```

Open http://localhost:5173 and log in with `COCKPIT_OPERATOR_USER` /
`COCKPIT_OPERATOR_PASSWORD`.

## Repo layout

```
core/            Python agent core (FastAPI, asyncpg)
edge/            Node transport edge (Fastify, ws)
frontend/        React cockpit (Vite, Tailwind)
verticals/hvac/  HVAC dispatcher vertical pack
infra/           Postgres init, nginx config
scripts/         Operator scripts (seed, tunnel, replay)
e2e/             End-to-end smoke test
docs/            Reference material
```

## Common commands

```bash
make dev                 # docker-compose up with hot reload
make migrate             # alembic upgrade head
make seed-hvac           # load HVAC fixtures
make tunnel              # cloudflared tunnel for Twilio webhooks
make test                # full test suite
make test-eval           # vertical scenario evals
make replay CONV=<uuid>  # rehydrate a past conversation
make trace CONV=<uuid>   # print trace timeline
```

See `make help` for the full list.

## Operations

Phone setup, common failures, recovery procedures: `docs/ops.md`.
