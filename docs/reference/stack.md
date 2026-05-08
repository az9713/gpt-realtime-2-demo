# The Technology Stack — every piece, why it's here

A reference of every technology in the codebase, what it does, and
why we chose it over alternatives.

---

## At a glance

```
┌─ Frontend (browser) ─────────────────────────────────────┐
│  React 18         │ UI rendering                         │
│  TypeScript 5     │ Type safety                          │
│  Vite 5           │ Dev server + bundler                 │
│  Tailwind CSS 3   │ Utility-first styling                │
│  React Router 6   │ Client-side routing                  │
└──────────────────────────────────────────────────────────┘

┌─ Edge (transport, Node.js) ──────────────────────────────┐
│  Node 20          │ Async runtime                        │
│  TypeScript 5     │ Type safety, strict mode             │
│  Fastify 4        │ HTTP server                          │
│  @fastify/websocket  │ WebSocket plug-in                 │
│  ws 8             │ WebSocket client (to OpenAI)         │
│  twilio (SDK)     │ TwiML helpers + signature verify     │
│  undici           │ HTTP/2 client (to core)              │
│  pino             │ Structured JSON logging              │
│  zod              │ Runtime schema validation            │
│  tsx              │ Dev runner with TS + ESM             │
└──────────────────────────────────────────────────────────┘

┌─ Core (agent brain, Python) ─────────────────────────────┐
│  Python 3.11      │ Async runtime                        │
│  FastAPI          │ HTTP server                          │
│  uvicorn          │ ASGI server                          │
│  asyncpg          │ Postgres driver (async)              │
│  psycopg2-binary  │ Postgres driver (sync, for alembic)  │
│  alembic          │ Schema migrations                    │
│  SQLAlchemy core  │ Migration column types only          │
│  pydantic 2       │ Request body validation              │
│  pydantic-settings│ Env-driven settings                  │
│  redis-py         │ Redis client (async)                 │
│  structlog        │ Structured JSON logging              │
│  websockets       │ WebSocket library                    │
│  pyyaml           │ Vertical pack file parsing           │
│  tzdata (Windows) │ IANA tz names for business_hours     │
│  pytest           │ Test runner                          │
│  ruff             │ Linter                               │
│  mypy             │ Type checker (strict)                │
│  black            │ Formatter                            │
└──────────────────────────────────────────────────────────┘

┌─ Storage ────────────────────────────────────────────────┐
│  Postgres 16      │ Durable: conversations, traces, etc. │
│  Redis 7          │ Pub/sub + ephemeral state            │
└──────────────────────────────────────────────────────────┘

┌─ Telephony ──────────────────────────────────────────────┐
│  Twilio Programmable Voice + Media Streams               │
│  cloudflared / ngrok (dev only)                          │
└──────────────────────────────────────────────────────────┘

┌─ AI ─────────────────────────────────────────────────────┐
│  OpenAI gpt-realtime-2   (default)                       │
│  OpenAI gpt-realtime-translate (translate mode)          │
└──────────────────────────────────────────────────────────┘

┌─ Packaging / orchestration ──────────────────────────────┐
│  Docker + docker-compose                                  │
│  GitHub Actions (CI)                                     │
└──────────────────────────────────────────────────────────┘
```

The rest of this doc explains each entry: what it is, why we chose
it, and what it's *not*.

---

## Frontend

### React 18

**What it is.** A library for building UIs out of components. Each
component is a function that returns markup; React renders them and
re-renders when state changes.

**Why we use it.** The cockpit is genuinely interactive: live
transcripts, approval queue updating in real time, mode toggles.
React's component model + hooks (`useState`, `useEffect`) makes the
state-driven UI tractable.

**Alternatives considered.** Svelte is more concise but less
ubiquitous. Vue is a wash. We picked React for hireability and the
ecosystem (Vite, React Router, Tailwind all play well).

**v1 scope.** Function components only. No class components. Hooks
for state. No state-management library — `useState` and React
Router's URL params are enough.

### TypeScript 5

**What it is.** A typed superset of JavaScript. The compiler `tsc`
checks types and erases them at build time — the runtime gets plain
JavaScript.

**Why.** Voice agents have a lot of moving parts (event types,
WebSocket message shapes, tool argument schemas). Typing those
prevents whole categories of "I forgot a field" bugs. `tsconfig.json`
is set to `strict: true`, including `noUncheckedIndexedAccess` and
`exactOptionalPropertyTypes` (the latter relaxed in v1 due to
fastify's looser types — see the trade-off in `tsconfig.json`).

### Vite 5

**What it is.** A frontend build tool. Two parts: a fast dev server
that uses native ES modules + on-demand transpilation, and a Rollup-
based production bundler.

**Why.** Vite's dev server starts in 200 ms and reloads modules in
30 ms. Compared to webpack's multi-second cold start, the difference
is night-and-day for actual development.

**Catch.** Vite's dev server requires native ESM in the browser.
For the cockpit (modern Chrome / Firefox), that's fine.

### Tailwind CSS 3

**What it is.** A utility-first CSS library. Instead of writing
`.button-primary { background: …; padding: …; }`, you write
`<button class="bg-emerald-600 px-4 py-2 ...">`.

**Why.** The cockpit's UI is utilitarian. Tailwind keeps the styles
co-located with markup, eliminates the "what to call this CSS class"
decision, and ships a tiny bundle (purged of unused classes).

### React Router 6

**What it is.** Client-side routing for React apps. Maps URL
patterns to components.

**Why.** The cockpit has five top-level routes (Talk, Approvals,
Voicemails, Audit, Conversations) plus a parametric
`/conversations/:id`. React Router handles browser-history state and
lazy-loading.

---

## Edge

### Node.js 20

**What it is.** The JavaScript runtime, server-side. v20 is the
2026-LTS line.

**Why.** The audio plane is a forest of WebSockets and event-loop
work. Node's nonblocking I/O is well-suited; the ecosystem (`ws`,
`@fastify/websocket`, `twilio`) is comprehensive.

**Why not Python or Go for the edge?** Python's `asyncio` is fine
but the WebSocket libraries are more limited. Go would be a strong
alternative — slightly faster, slightly more verbose, much smaller
deployable binary. We chose Node for ecosystem and developer
familiarity. The seam between core and edge is HTTP+WS, so swapping
the edge to Go is a fully self-contained refactor.

### Fastify 4

**What it is.** An HTTP server framework, similar role to Express
but designed for performance and stricter typing.

**Why.** Twilio's signature verification + WebSocket upgrade
handshake + JSON body parsing all need server middleware. Fastify
does these correctly out of the box and is measurably faster than
Express. Strict TypeScript types are first-class.

### `@fastify/websocket`

**What it is.** Fastify plug-in that adds WebSocket route support.

**Why.** Twilio Media Streams arrives as a WebSocket. The browser
talks to the edge as a WebSocket. The plug-in integrates the
WebSocket lifecycle into Fastify's route declarations.

**Note.** We pinned this to v10. The handler signature in v10 is
`(socket, request)`; older versions used `(connection, request)`
where `connection.socket` was the WebSocket. Our code uses the v10
shape.

### `ws` (the library)

**What it is.** A WebSocket implementation for Node. Used as the
**client** to connect *out* to OpenAI's Realtime API.

**Why.** Mature, fast, RFC-6455-correct. Used by Discord, Slack, and
the rest of the Node WebSocket ecosystem.

### `twilio` (Node SDK)

**What it is.** Twilio's official Node library.

**Why we use it (selectively).** We use `twilio.validateRequest` to
verify the X-Twilio-Signature header on inbound webhooks. We do *not*
use the SDK's TwiML builders — we emit TwiML strings directly because
the documents are tiny.

### `undici`

**What it is.** Node's modern HTTP/1.1 + HTTP/2 client.

**Why.** Used for edge-to-core HTTP calls (e.g. `POST /v1/sessions`).
Faster than the old `http` module, simpler than `axios`. Comes
bundled with Node 20.

### `pino`

**What it is.** A fast JSON logger for Node.

**Why.** Structured logs (one JSON object per line) are easy to
query in production. Pino is designed for very high throughput so it
doesn't drag on the edge's hot path.

### `zod`

**What it is.** A TypeScript-first runtime schema validator.

**Why.** Used sparingly — for runtime validation of incoming JSON
that's about to drive critical decisions. Where TypeScript can prove
something at build time, we don't `zod`.

### `tsx`

**What it is.** A Node loader that runs TypeScript and ESM directly,
no separate build step.

**Why.** `tsx watch src/server.ts` is the dev command; it watches the
source tree and restarts on changes. Faster than `ts-node-dev`,
matches Node 20's ESM semantics.

---

## Core

### Python 3.11

**What it is.** The Python version we target. 3.11 has materially
better startup time and async performance than 3.10.

**Why.** Python is where data, ML, and backend engineers already
work. The OpenAI Python SDK lives here, FastAPI lives here, asyncpg
lives here. Most of the iteration on this codebase will happen in
Python.

### FastAPI

**What it is.** An async HTTP framework with built-in OpenAPI
generation and pydantic-driven request validation.

**Why.** FastAPI's pydantic integration is the cleanest way to write
typed HTTP endpoints in Python. The auto-generated `/docs` page is a
useful interactive reference. Performance is fine for our load (one
core request per tool call).

### uvicorn

**What it is.** An ASGI server (the Python async server interface).

**Why.** Standard pairing with FastAPI. `uvicorn --reload` watches
the source tree and restarts on edits, matching `tsx watch` on the
edge.

### asyncpg

**What it is.** A non-ORM Postgres driver written for asyncio.
Materially faster than psycopg2 for async workloads.

**Why.** The agent runtime is async-first. The volume isn't enormous
but the latency budget is tight; raw asyncpg + hand-written SQL is
the right tier of abstraction.

**Why not SQLAlchemy ORM?** ORMs add a translation layer that costs
both performance and clarity. Our schema is five tables; the SQL is
straightforward. The cost of ORM isn't earned.

### psycopg2-binary

**What it is.** The synchronous Postgres driver.

**Why.** Alembic uses SQLAlchemy core, which uses psycopg2 by
default. We don't use psycopg2 in the agent runtime — only in
migrations.

### alembic

**What it is.** Python's standard schema-migration tool.

**Why.** Forward-only migrations, scripted, version-controlled. Same
shape as Rails or Django migrations. Alembic is the de-facto choice
for SQLAlchemy-aware Python apps.

### SQLAlchemy core (declared, used minimally)

**What it is.** SQLAlchemy's lower-level expression language. Used
only to declare migration column types (`sa.Text()`, `sa.Numeric(10, 4)`,
`postgresql.JSONB()`).

**Why.** Alembic uses these internally. The core *runtime* doesn't
import SQLAlchemy — only `core/alembic/versions/*.py` does.

### pydantic 2

**What it is.** A library for type-driven data validation. Define a
class with type annotations; pydantic generates a parser.

**Why.** FastAPI uses it for request bodies. The dispatcher uses it
for `ToolCallRequest` / `ToolCallResult` shapes. v2 is materially
faster than v1.

### pydantic-settings

**What it is.** Env-variable-driven configuration via pydantic.

**Why.** Settings are a class with type-checked fields and defaults.
`get_settings()` returns a singleton. Test code can monkey-patch
overrides.

### redis-py (async)

**What it is.** The standard Python Redis client; we use the
`redis.asyncio` import for async support.

**Why.** Pub/sub for cockpit notifications, plus future ephemeral
state (rate-limiting, audio buffers). The async API integrates
cleanly with FastAPI's event loop.

### structlog

**What it is.** A structured logging library for Python.

**Why.** Like pino on the edge: one JSON object per line, easy to
query in production. We configure it with stdout + JSON renderer.

### pyyaml

**What it is.** YAML parser.

**Why.** Vertical packs use YAML for non-code files
(`pack.yaml`, `policy.yaml`, `approvals.yaml`, `preambles.yaml`).
Eval scenarios use YAML.

### tzdata (Windows-only)

**What it is.** A Python package shipping the IANA timezone database
as data files for `zoneinfo` to read.

**Why.** Phase 4 (voicemail / business hours) uses
`zoneinfo.ZoneInfo("America/Chicago")` etc. On Linux containers the
system zoneinfo files are present; on Windows hosts they're not, and
`zoneinfo` errors with `ZoneInfoNotFoundError`. The pyproject marks
`tzdata` as a Windows-only dependency
(`tzdata>=2024.2; sys_platform == 'win32'`) so dev runs on Windows
hosts and CI on Linux both succeed.

### pytest, ruff, mypy, black

The testing/lint/format stack. `pytest` runs unit + integration tests
with `pytest-asyncio` for async tests. `ruff` is a fast linter. `mypy
--strict` is the type checker. `black` is the formatter (line length
100).

These are dev-only deps in `pyproject.toml`'s `[project.optional-dependencies].dev`.

---

## Storage

### Postgres 16

**What it is.** The relational database.

**Why.** Best-in-class for our access patterns: small relational
tables, JSONB for flexible event payloads, mature operations story.
v16 has incremental performance wins over older versions but no
breaking changes from our point of view.

**Schema lives in the `app` schema.** Keeps cockpit data clearly
separated if Postgres is shared with other apps.

### Redis 7

**What it is.** An in-memory key-value store with built-in pub/sub.

**Why.** We use it for:

1. **Pub/sub** — push approval and trace events to the cockpit
   in real time.
2. (Future) **Ephemeral session state** — active session registry,
   audio ring buffer, rate-limit tokens.

Postgres holds durable state. Redis holds *index over* durable state
plus genuinely ephemeral things.

---

## Telephony

### Twilio Programmable Voice + Media Streams

See [reference/twilio-integration.md](twilio-integration.md) for the
full walkthrough. In short: phone numbers, TwiML, and a WebSocket
that streams μ-law audio.

### cloudflared (preferred) / ngrok (fallback)

**What they are.** Tunnels that expose a local port to a public URL.

**Why.** Twilio's webhooks need to reach your edge over the public
internet. In dev, you don't have a public IP. A tunnel solves this.

`make tunnel` runs `cloudflared tunnel --url http://localhost:8080`
(or ngrok if cloudflared isn't installed). Cloudflared is preferred
because it's free without a daily limit.

---

## AI

### OpenAI gpt-realtime-2

The model. See [reference/gpt-realtime-2.md](gpt-realtime-2.md) for
deep details.

### OpenAI gpt-realtime-translate

The translate-mode sibling. Same WebSocket protocol; different
model. See [concepts/translate-mode.md](../concepts/translate-mode.md).

---

## Packaging / orchestration

### Docker

**What it is.** A container runtime. Each service runs in its own
container with its own filesystem, network, and process tree.

**Why.** Five services need to start together with the right network
configuration. Docker + docker-compose makes this one command:
`docker compose up`.

**Why not Kubernetes?** v1 is single-tenant, single-host. K8s would
be heavy weight for one operator on one VM. The seams are clean
enough that a future K8s deployment is straightforward — each
service has its own image and exposes its own port.

### docker-compose

**What it is.** Docker's multi-container orchestration tool. Reads a
YAML file describing services and runs them all.

**Why.** Five services + healthchecks + dependency ordering = one
file. v1 stays self-host-friendly with this.

### GitHub Actions

**What it is.** GitHub's hosted CI service.

**Why.** PR-on-merge gates: linting, type-checking, unit tests,
integration tests, vertical scenario evals. Workflow is in
`.github/workflows/ci.yml` and runs on every PR.

A nightly E2E workflow in `.github/workflows/nightly.yml` brings up
the full docker-compose stack and runs the eval suite end-to-end.

---

## A note on what's *not* used

| Thing we deliberately don't use | Why not |
|---|---|
| Kubernetes | v1 is single-host self-host |
| LangChain / LangGraph | Direct, observable, debuggable agent runtime is preferred |
| An ORM (SQLAlchemy ORM, Django ORM) | Five-table schema; ORM cost not earned |
| GraphQL | REST is enough; cockpit calls 5 endpoints |
| gRPC | Edge ↔ core is HTTP+JSON; works fine |
| A meeting bot SDK | v1 doesn't ship a meeting overlay |
| OpenTelemetry exporter (yet) | Trace pipeline lands in Postgres in v1; OTLP sink is a clean extension |
| A vector database | No long-term memory in v1; "memory" is per-session prompt |

Each of these has a rationale on the spec that protects scope. Adding
any of them is fine in a future version, but justifying their cost
against v1 use cases is hard.

---

## Where to read next

- The architecture that ties them all together: [architecture/system-design.md](../architecture/system-design.md).
- The full SPEC: [SPEC.md](../../SPEC.md).
