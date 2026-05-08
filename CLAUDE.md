# Project Context — Voice Operations Cockpit

This file is the cold-start brief for any new Claude Code session.
Read this first, then `SPEC.md`, then `PLAN.md`. No code has been
written yet; we are at the end of design and the start of build.

---

## What we are building

A **unified voice operations cockpit** on top of OpenAI's GPT-Realtime
API family. One agent core, multiple surfaces (browser + phone), two
modes (Realtime-2 conversational + Realtime-Translate). Verticals are
configurations on a shared platform, not separate apps.

The user's framing: "the entire unified GPT-Realtime voice cockpit
with multiple vertical use cases on it." Specced as a full platform;
v1 ships the HVAC dispatcher vertical only, with the other three
verticals (real-estate, founder-ops, telehealth) described in the spec
as design pressure to keep platform abstractions honest.

---

## Locked-in decisions

| Decision | Choice | Status |
|---|---|---|
| Backend stack | **Hybrid: Python agent core (FastAPI) + Node transport edge (Fastify + ws)** | Locked |
| Telephony provider | **Twilio Media Streams** | Locked |
| v1 vertical(s) | **HVAC dispatcher only** (others designed, not built) | Locked |
| Deployment | **Single-tenant, docker-compose self-host** | Locked |
| Voice-intent classifier | Local small model behind a swap interface | Locked (SPEC §13.1) |
| Audio storage | None in v1; transcripts only | Locked (SPEC §13.2) |
| Approval phrase parsing | Exact match per tool, declared in `approvals.yaml` | Locked (SPEC §13.3) |
| Frontend hosting | Separate container (nginx + built Vite assets) | Locked (SPEC §13.4) |

These are part of the contract. Revisiting any of them requires
updating SPEC.md.

---

## What's in the repo right now

```
gpt-realtime-2_openai/
├── CLAUDE.md         ← this file
├── SPEC.md           ← v0.1, full platform spec, 14 sections
├── PLAN.md           ← v0.1, implementation plan, 9 phases / 41 tasks
└── docs/
    ├── transcript.txt           ← OpenAI launch demo transcript
    └── gpt-realtime-2-docs.txt  ← link list to OpenAI guides
```

**No code has been written.** No `core/`, `edge/`, `frontend/`,
`verticals/`, no docker-compose, no migrations.

---

## Spec at a glance (read SPEC.md for detail)

- **§1 Objective** — small operator (1–10 people) needs phone + browser
  voice agent with real tools, real guardrails, full traces.
- **§2 Architecture** — Three load-bearing shared things: one agent
  core, one conversation store, one observability/guardrails spine.
  Hybrid Python (brain) + Node (audio plane); seam is HTTP for sync
  tool calls + per-session WebSocket for events.
- **§3 Components** — Python core, Node edge, Postgres, Redis,
  observability spine, React/Vite cockpit.
- **§4 Verticals** — Pack directory shape; HVAC built in v1; the other
  three are designed-only.
- **§5 Data model** — `conversations`, `turns`, `tool_calls`,
  `approvals`, `trace_events`. Raw asyncpg, no ORM.
- **§6 Interfaces** — `Agent` and `Tool` Python protocols; edge↔core
  HTTP+WS protocol; trace event JSON schema.
- **§7 Project structure** — directory tree.
- **§8 Commands** — `make dev/test/build/up/migrate/seed/tunnel/replay/trace`.
- **§9 Code style** — black/ruff/mypy strict (Py); strict TS, no `any`
  beyond OpenAI SDK seam; structured JSON logs; no comments by default.
- **§10 Testing strategy** — unit + contract + integration + e2e +
  **vertical scenario evals** (the load-bearing safety layer).
- **§11 Boundaries** — Always / Ask first / Never lists. Critical:
  every tool call goes through guardrail middleware; every dangerous
  tool call requires explicit approval; no PII in logs.
- **§12 Out of scope for v1** — outbound calling, multi-tenant SaaS,
  meeting overlay, OIDC, HIPAA, multi-region.
- **§13 Resolved design decisions** — the four from the table above.
- **§14 Build order** — informational, not contract.

---

## Plan at a glance (read PLAN.md for detail)

9 phases, 41 tasks, all sized S or M. Risk-first ordering.

| Phase | Tasks | What lands |
|---|---|---|
| 1 Foundation | 1–6 | Repo + DB + skeletons (core, edge, frontend) |
| 2 Browser end-to-end | 7–12 | First voice loop with one trivial tool over WebRTC |
| 3 Persistence + observability | 13–16 | Conversation lifecycle + traces + cockpit views |
| 4 Approvals + guardrails | 17–22 | Middleware + state machine + voice classifier + queue UI |
| 5 Phone bridge | 23–26 | Twilio Media Streams + inbound routing |
| 6 HVAC vertical | 27–32 | Pack loader + tools + prompt + seed data |
| 7 Translate mode | 33–35 | Mode switch + auto-detect (parallel with 8) |
| 8 Eval harness | 36–38 | Scenario YAML + HVAC suite + CI gates |
| 9 Polish + ship | 39–41 | Operator scripts + README + E2E smoke |

The plan ends with a **human-approval checkbox** that is intentionally
left unchecked. The user has not yet formally signed off on the plan.

---

## Where we are right now

1. ✅ Spec written and confirmed (`SPEC.md` v0.1).
2. ✅ Plan written (`PLAN.md` v0.1).
3. ⬜ Plan awaiting final human approval.
4. ⬜ Implementation has not started. No code exists.

**Next decision point** — once the user approves the plan, choose
between:

- `agent-skills:incremental-implementation` — one task at a time,
  human reviews each.
- `superpowers:execute-plan` — batched execution with review
  checkpoints between phases.

The user has not yet picked between these.

---

## How to work with this user

Observations from the design conversation. Treat as guidance, not
rigid rules.

- **They push back on narrowing scope inappropriately.** I once
  suggested specing only the HVAC vertical "to keep scope manageable."
  They correctly pointed out the whole thesis is *one* unified
  platform with multiple verticals on top, and asked for the full
  spec. Don't shrink the vision unprompted — surface tradeoffs and
  let them decide.
- **They ask "what does X mean?" when jargon shows up.** When they
  encountered "voice-intent classifier", "S3-compatible blob store",
  "approval-on-voice phrase parsing", "frontend hosting", they asked
  for plain-language explanations. Default to plain English; ground
  abstract terms in their concrete scenario (HVAC dispatcher).
- **They're comfortable accepting recommended defaults** once the
  reasoning is clear. Don't over-elaborate; recommend, explain
  briefly, ask.
- **They invoke skills explicitly via `/skill-name` and follow
  skill-driven workflows.** Use the right skill for the right phase
  (`agent-skills:spec`, `agent-skills:planning-and-task-breakdown`,
  next will likely be implementation skills).
- **They want substance over ceremony.** Long, well-structured
  documents are welcome when warranted (the spec is 14 sections); they
  don't want padding or hand-waving.

---

## Conversation history (compressed)

1. User asked me to read `docs/`. I summarized the OpenAI launch demo
   transcript and the link list of OpenAI guides.
2. User asked for project ideas showcasing the GPT-Realtime features
   plus agentic capabilities. I proposed seven distinct projects
   (meeting companion, personal ops, phone concierge, devops copilot,
   stream co-host, field-service headset, observability lab).
3. User asked if one project could combine most/all features. I
   proposed the **Voice Operations Cockpit** with three load-bearing
   shared things (one agent core, one conversation store, one
   observability/guardrails spine).
4. User asked for real-life use cases. I gave four: real-estate
   brokerage, HVAC dispatcher, solo SaaS founder, multilingual
   telehealth intake.
5. I suggested specing only the HVAC vertical for scope reasons. User
   pushed back: spec the entire platform with multiple verticals.
6. User confirmed they want the full platform built. I invoked
   `agent-skills:spec`, asked four scoping questions, locked in
   choices, and wrote `SPEC.md` v0.1.
7. User asked for plain-language explanations of the four open
   questions in §13. I explained each tied to the HVAC scenario.
   User said "go with defaults"; I converted §13 to "Resolved Design
   Decisions."
8. User asked to run the planning skill. I invoked
   `agent-skills:planning-and-task-breakdown` and wrote `PLAN.md` v0.1
   with 9 phases / 41 tasks.
9. User asked for this memory file.

---

## Useful commands once code exists (planned, not yet implemented)

```
make dev          # docker compose up with hot-reload
make migrate      # alembic upgrade head
make seed         # load HVAC fixtures
make tunnel       # cloudflared tunnel for Twilio webhooks
make test         # full suite
make test-eval    # vertical scenario evals
make replay CONV=<uuid>
make trace CONV=<uuid>
```

---

## Key references

- OpenAI announcement: https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/
- OpenAI realtime docs (link list in `docs/gpt-realtime-2-docs.txt`).
- Twilio Media Streams (the chosen telephony bridge protocol).

---

## When in doubt

Read `SPEC.md` for *what* and *why*; read `PLAN.md` for *how* and *in
what order*. If something contradicts the spec, the spec wins — update
the plan, not the spec, unless the user has explicitly approved a spec
change.
