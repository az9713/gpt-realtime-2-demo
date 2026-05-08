# Voice Operations Cockpit — Documentation

A self-hostable platform that turns OpenAI's GPT-Realtime models into a working
**voice agent** — one that answers phone calls, runs on a browser cockpit,
calls real tools, and gates dangerous actions behind human approval.

This documentation is written for someone with **no prior background** in
voice AI, telephony, WebRTC, or distributed systems. Every term is defined
the first time it appears; every "obvious" technical assumption is spelled
out. If something feels too dense, jump back to [key concepts](overview/key-concepts.md).

## Where to start

| If you want to… | Read this |
|---|---|
| Understand what this thing is and why it exists | [overview/what-is-this.md](overview/what-is-this.md) |
| See realistic worked examples (UI clicks, terminal, Claude Code) | [use-cases.md](use-cases.md) |
| Look up a term you saw in code or another doc | [overview/key-concepts.md](overview/key-concepts.md) |
| See the whole architecture in one diagram | [architecture/system-design.md](architecture/system-design.md) |
| Understand the GPT-Realtime model itself | [reference/gpt-realtime-2.md](reference/gpt-realtime-2.md) |
| See which Realtime models we use (and which we don't) | [reference/realtime-models-in-use.md](reference/realtime-models-in-use.md) |
| Know how phone calls actually reach the agent | [reference/twilio-integration.md](reference/twilio-integration.md) |
| Identify every technology used and why | [reference/stack.md](reference/stack.md) |

## The ten concept docs

OpenAI ships ten guides for building real-time voice agents. Each one
maps to a specific concern in this codebase. Read them in order if you
want a guided tour, or jump straight to whichever sounds relevant.

| OpenAI guide | What it solves in this app | Where to read |
|---|---|---|
| voice-agents | The cockpit's primary loop — "do this for me" | [concepts/voice-agents.md](concepts/voice-agents.md) |
| realtime-conversations | Shared session memory (call → browser handoff) | [concepts/realtime-conversations.md](concepts/realtime-conversations.md) |
| realtime-webrtc | Browser cockpit + future meeting overlay | [concepts/realtime-webrtc.md](concepts/realtime-webrtc.md) |
| realtime-websocket | Phone bridge (Twilio/SIP) — telephony forces WS | [concepts/realtime-websocket.md](concepts/realtime-websocket.md) |
| realtime-models-prompting | Persona, preambles, "stay quiet until…" mode | [concepts/realtime-models-prompting.md](concepts/realtime-models-prompting.md) |
| running-agents | Each turn dispatches planner + workers behind the voice | [concepts/running-agents.md](concepts/running-agents.md) |
| orchestration | Specialist sub-agents coordinated by the planner | [concepts/orchestration.md](concepts/orchestration.md) |
| guardrails-approvals | Spoken "yes, proceed" + queue for high-risk ops | [concepts/guardrails-approvals.md](concepts/guardrails-approvals.md) |
| integrations-observability | One dashboard: latency, costs, traces, evals | [concepts/integrations-observability.md](concepts/integrations-observability.md) |
| translate (Realtime-Translate) | Meeting Companion mode — same core, swapped model | [concepts/translate-mode.md](concepts/translate-mode.md) |

## Operational docs (already in the repo)

These are not part of this learning path; they're operator-facing.

- [`SPEC.md`](../SPEC.md) — the platform contract.
- [`PLAN.md`](../PLAN.md) — the implementation plan, 9 phases / 41 tasks.
- [`docs/ops.md`](ops.md) — operations runbook (recovery procedures).
- [`docs/eval-format.md`](eval-format.md) — scenario eval YAML schema.
- [`README.md`](../README.md) — install, build, run.
