# Guardrails & Approvals — voice "yes, proceed" + queue for high-risk ops

> **OpenAI guide:** [Guardrails & Approvals](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
> **Where it lands:** the heart of the cockpit's safety story.

---

## The two distinct things this page covers

People conflate them all the time, so let's separate them up front.

| Concern | Lives where | Decides what |
|---|---|---|
| **Guardrails** | `core/src/cockpit_core/guardrails/` | Should this input/output/tool-call happen at all? |
| **Approvals** | `core/src/cockpit_core/agent/approvals.py` | This dangerous tool needs a human yes — block until I get one. |

A guardrail is a *policy filter* (e.g. "redact PII from transcripts,
always"). An approval is a *human-in-the-loop checkpoint* on
specifically-dangerous actions ("you can move the schedule, but only
if Reggie says so").

Both run for every tool call. They serve different purposes.

---

# Part 1 — Guardrails

## What a guardrail is

A function that runs at one of three hook points:

1. **Pre-call** — before user input goes to the model. Can mutate or
   block. Used for input filtering (e.g. PII redaction before logs,
   safety classifiers).
2. **Tool-call** — before a tool executes. Can block. Used for
   policy enforcement that's tool-specific (e.g. "only allow
   schedule_move on Tuesdays").
3. **Post-call** — before agent output is shown/spoken. Can mutate.
   Used for output filtering (PII redaction in transcripts, refusal
   taxonomy enforcement).

The contract:

```python
class GuardrailRunner:
    async def before_user_input(self, ctx: SessionContext, text: str) -> str: ...
    async def before_tool_call(self, ctx: SessionContext, tool: Tool, req: ToolCallRequest) -> GuardrailDecision: ...
    async def after_agent_output(self, ctx: SessionContext, text: str) -> str: ...
```

Each hook is composable: you register multiple in priority order, each
one mutates the value (or returns a `GuardrailDecision`), the next
sees the previous's output.

## What's wired up in v1

### PII redactor (`core/src/cockpit_core/guardrails/pii.py`)

Regex-driven, conservative. Redacts:

- Emails (`jane.doe@example.com` → `[email]`)
- Phone numbers (`(512) 555-0102` → `[phone]`)
- US SSNs (`123-45-6789` → `[ssn]`)
- Credit-card-shaped digit runs (`4111 1111 1111 1111` → `[card]`)

Applied in `after_agent_output`, so transcripts persisted to
`turns.transcript` and trace event payloads are PII-clean. False
positives are preferred over leaking PII into logs.

### Tool-call hook framework

`GuardrailRunner.before_tool_call` runs every registered `tool_hook`.
A hook returns a `GuardrailDecision`:

```python
@dataclass
class GuardrailDecision:
    blocked: bool = False
    reason: str | None = None
```

If any hook returns `blocked=True`, the tool call is short-circuited
to status `failed`/`denied` with the reason recorded. The blocked
event lands in `trace_events` so the cockpit shows it.

v1 ships *no* enabled tool hooks by default. The framework is in
place; verticals add their own.

## How to add a guardrail

In `verticals/<name>/post_call.py` (or a sibling file the loader picks
up — extending the loader to register guardrails per vertical is a
tiny change), define an async function with the right shape:

```python
from cockpit_core.agent.contract import SessionContext, Tool, ToolCallRequest
from cockpit_core.guardrails.middleware import GuardrailDecision

async def block_after_hours(
    ctx: SessionContext, tool: Tool, req: ToolCallRequest
) -> GuardrailDecision:
    from datetime import datetime
    now = datetime.utcnow()
    if tool.name == "dispatch_truck" and not (8 <= now.hour < 18):
        return GuardrailDecision(blocked=True, reason="dispatching is restricted to 8a-6p")
    return GuardrailDecision()
```

Wire it into the runner at session start. (The vertical loader
exposes a hook for this; it's currently a no-op pass-through. Adding
custom hooks is one of the planned post-v1 enhancements.)

## What good guardrails look like

- **Cheap.** Run on every tool call without a noticeable latency hit.
- **Idempotent.** Running twice is no different from running once.
- **Honest about uncertainty.** A safety classifier should err on the
  side of blocking; a PII redactor should err on the side of
  redacting.
- **Trace-friendly.** Always emit a `guardrail.blocked` /
  `guardrail.passed` event; the cockpit operator wants to see this.
- **Boring.** A guardrail that fails opaquely or has subtle
  side-effects in tools is the worst kind of bug — silent unsafety.

---

# Part 2 — Approvals

## The mechanism in one sentence

When a tool with `blast_radius: "dangerous"` is requested, the
dispatcher creates an `approvals` row, blocks for up to 60 seconds,
and resolves on either a spoken phrase (matched exactly) or a
cockpit click — whichever happens first.

## The state machine

Five legal states:

```
       ┌─────────────┐
       │  requested  │
       └──────┬──────┘
              │
   ┌──────────┼──────────────────┐
   │          │                  │
   ▼          ▼                  ▼
┌────────┐ ┌────────┐       ┌─────────┐
│approved│ │ denied │       │ timeout │
└────────┘ └────────┘       └─────────┘
   │          │                  │
   ▼          ▼                  ▼
(tool runs)  (no-op,           (no-op,
              status=denied)   status=denied)
```

Illegal transitions: any → any except via the resolve path. The
implementation explicitly rejects double-resolution:

```python
if existing.resolved_at is not None:
    raise IllegalApprovalTransition(
        f"approval {approval_id} already resolved as {existing.decision}"
    )
```

This matters when both a voice phrase and a cockpit click race —
whichever lands first wins; the second gets a 409.

## The two resolution paths

### Voice resolution

The voice-intent classifier on the edge listens for spoken phrases
(via the OpenAI transcript stream — v1 uses transcript-based exact
matching, not raw audio classification). When the classifier sees a
phrase that matches the *currently pending* tool's preamble, it
calls the core's `POST /v1/sessions/{id}/approval-by-voice`
endpoint. The approval manager checks that there's a pending
approval, that the phrase matches exactly (case- and
whitespace-normalized), and resolves.

For HVAC's `schedule_move`, the configured phrase is *"Reggie, do
it"*. The dispatcher hears Aria say *"…to ten o'clock — okay to move
this?"* and replies *"Reggie, do it."* The classifier matches; the
approval resolves.

```yaml
# verticals/hvac/approvals.yaml
tools:
  schedule_move:
    phrase: "Reggie, do it"
    timeout_seconds: 60
  dispatch_truck:
    phrase: "Reggie, send the truck"
    timeout_seconds: 60
```

Why exact-match and not fuzzy intent matching? Because false
approvals on dangerous actions are unacceptable. The spec calls this
out:

> Approval-on-voice phrase parsing: **exact phrase per tool**. Each
> tool in `approvals.yaml` declares its own approval phrase. No
> fuzzy intent matching in v1 — false approvals are unacceptable on
> dangerous actions.

The phrase for each vertical/tool combination should be:

- Distinctive (the dispatcher won't say it accidentally)
- Easy to remember and pronounce clearly
- Different per tool (so a dispatcher can't approve A and accidentally
  trigger B)

### Cockpit click

The cockpit subscribes to the Redis approvals channel. When a tool
fires `approval.requested`, the row appears in the Approvals queue
within ~500 ms. The dispatcher clicks **Approve** or **Deny**, which
calls `POST /v1/approvals/{id}/resolve` with the decision.

If both paths race, the database constraint is the tiebreaker:

```sql
UPDATE app.approvals
   SET resolved_at = $2, decision = $3, decided_by = $4, decided_via = $5
 WHERE id = $1 AND resolved_at IS NULL
```

The `WHERE resolved_at IS NULL` clause ensures only the first wins.
The second resolution attempt sees zero rows updated and returns
`false` (the API returns 409).

## The timeout

If neither voice nor cockpit resolves within `timeout_seconds`
(default 60), the approval is auto-marked `timeout` and the tool
call goes to `denied`. This is critical because:

- Without it, a hung approval would block the agent forever, and the
  caller would hear silence indefinitely.
- The agent gets a clean denial it can react to:
  *"I wasn't able to confirm with the dispatcher. Want me to take a
  message instead?"*

The timeout is configurable per tool in `approvals.yaml`. For very
high-stakes actions you might extend it; for routine ones you might
shorten.

## Where the wait actually happens

```python
# core/src/cockpit_core/agent/approvals.py

loop = asyncio.get_running_loop()
fut: asyncio.Future[ApprovalDecision] = loop.create_future()
self._waiters[approval.id] = fut

try:
    decision = await asyncio.wait_for(fut, timeout=timeout_seconds)
except TimeoutError:
    await self._resolve(...)  # mark timeout
    return "timeout"
```

This is process-local state. The `_waiters` map lives in memory in
the core process. If the core restarts mid-approval, all in-flight
approvals are stranded — Redis still publishes the resolve event,
but no waiter receives it, and the agent's await raises a timeout.

Two implications:

- v1 is single-replica core. Multi-replica needs the waiter map
  externalized.
- Restarts during active calls are observable. If you restart the
  core mid-approval, the caller hears the timeout response.

For v1 (single-tenant self-host) this is acceptable. The seam to
fix it is small: replace `_waiters` with a Redis BLPOP / pub/sub
indirection.

## What you see in the cockpit

The Approvals tab (`/approvals`) polls `GET /v1/approvals` every
second AND subscribes to the per-session Redis channels. New
pending approvals appear as cards:

```
┌──────────────────────────────────────────────────────────┐
│  [DANGEROUS]  schedule_move                              │
│                                                          │
│  {                                                       │
│    "job_id": "J-5001",                                   │
│    "new_slot": "2026-05-08T10:00:00Z"                    │
│  }                                                       │
│                                                          │
│  conv 1210e2ab · requested 7:14:32 AM                    │
│                                                          │
│              [ Approve ]   [ Deny ]                      │
└──────────────────────────────────────────────────────────┘
```

The dispatcher reads what's about to happen, clicks Approve. The
card disappears; the conversation in the Talk view continues; Aria
speaks the result.

---

## How the two combine into a guarantee

The platform's safety contract:

1. Every tool call passes through the guardrail middleware.
2. Every dangerous tool call passes through the approval state
   machine before execution.
3. Both paths emit trace events.

These run *unconditionally* — there is no `developer_mode` flag, no
"trusted client" exception. From the spec:

> Bypass the guardrail layer with a "developer mode" flag. **Never.**

If you add a new tool with `blast_radius: dangerous` it is approval-gated by
construction. If you forget to wire its approval phrase, the cockpit's
load-time validation catches it (or the tool times out on every call,
which you'll notice).

---

## Pitfalls and how this codebase avoids them

| Pitfall | Avoided by |
|---|---|
| Bypassing approval via a "test" code path | The dispatcher is the *only* path to tool execution. Tests use the same path; they just configure `decision_for_dangerous` in the eval harness. |
| Race conditions between voice + click | The DB `WHERE resolved_at IS NULL` clause is the tiebreaker; explicit `IllegalApprovalTransition` for double-resolve attempts. |
| Stale phrase matches across tools | Pending approvals are a stack per conversation; only the most recent is checked. |
| Operators forgetting to approve | 60s default timeout → tool denied → agent gracefully recovers. |
| PII leaking into trace logs | All transcripts pass through `PIIRedactor` in `after_agent_output` before persistence. |
| The cockpit being unreachable | The voice phrase path still works as long as the edge + core are up; cockpit is an alternate input, not a primary one. |

---

## Where to read next

- How tool calls flow through the dispatcher: [running-agents.md](running-agents.md).
- The trace pipeline that records all this: [integrations-observability.md](integrations-observability.md).
- The eval scenarios that test approval flows:
  [eval-format.md](../eval-format.md) and `verticals/hvac/scenarios/`.
