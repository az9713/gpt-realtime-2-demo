# Running Agents — planner + workers per turn

> **OpenAI guide:** [Running Agents](https://developers.openai.com/api/docs/guides/agents/running-agents)
> **Where it lands:** the agent runtime in `core/src/cockpit_core/agent/`.

---

## What "running an agent" means

An "agent" in OpenAI's framing is a model **plus** the loop that gives
it tools and gives it your output (audio, in this case). To "run an
agent" means to drive that loop for one turn — get input, decide,
maybe call tools, produce output.

In a text chatbot, "one turn" means *one response message*. In a
voice agent, "one turn" is fuzzier: it's the unit between two server-VAD
boundaries — roughly, "one thing the caller said and the agent's full
reply to it."

---

## The planner-worker pattern

A common pattern in agent design:

```
                  ┌──────────────┐
                  │   PLANNER    │
                  │              │
                  │  decides:    │
                  │   - the goal │
                  │   - the      │
                  │     subtasks │
                  │   - the order│
                  └──────┬───────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐      ┌─────────┐      ┌─────────┐
   │WORKER 1 │      │WORKER 2 │      │WORKER 3 │
   │(tool A) │      │(tool B) │      │(tool C) │
   └─────────┘      └─────────┘      └─────────┘
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                  results merged,
                  fed back to planner
                  for synthesis
```

The planner is the LLM. The workers are tool implementations. The
planner decides *what to do next* using the tool descriptions, fires
the tool calls (one or many), reads the results, decides whether to
call more tools or answer.

This codebase implements the **simplest correct version** of this:

- One planner per session = the OpenAI Realtime model.
- One worker per tool name = a Python coroutine in
  `verticals/<name>/tools.py`.
- Coordination = the model emits `function_call` items in
  `response.done`; the edge dispatches each to the core; the core
  runs the corresponding handler; results come back to the model in
  the next turn.

There is **no separate planner agent** in v1. The Realtime model
handles planning natively. The codebase reserves the seam for
multi-agent orchestration in [orchestration.md](orchestration.md);
v1 just doesn't need it yet.

---

## A turn, traced through the codebase

Let's trace one turn from the moment the user finishes speaking to
the moment the agent finishes its reply.

### Step 1 — VAD commits the input buffer

OpenAI's server VAD detects ~500 ms of silence after the user
stopped talking and emits:

```
input_audio_buffer.speech_stopped
input_audio_buffer.committed
```

The model now has the full user utterance and runs.

### Step 2 — The model decides

The model emits one of these:

| Output kind | Meaning |
|---|---|
| `message` (audio + transcript) | Agent answers directly |
| `function_call` | Agent wants to call a tool |
| (multiple of the above) | Agent answers AND calls tools, or calls multiple tools |

In `gpt-realtime-2` GA, all of these arrive embedded in
`response.done.output[]`. There can be more than one entry — the model
can call several tools in parallel before saying anything.

### Step 3 — Edge sees `response.done`, fires tool calls

`edge/src/openai/session.ts`:

```ts
case 'response.done': {
  for (const item of response?.output ?? []) {
    if (item.type === 'function_call') {
      await this.handleFunctionCall(item.call_id, item.name, item.arguments);
    }
  }
  return;
}
```

`handleFunctionCall` then:

1. Parses the JSON arguments string.
2. POSTs to the core's `/v1/sessions/{id}/tool-calls` endpoint.
3. Sends the result back to OpenAI as `conversation.item.create` with
   `item.type: function_call_output`.
4. Sends `response.create` to ask the model to continue.

### Step 4 — Core dispatches

`core/src/cockpit_core/agent/dispatch.py` — `ToolDispatcher.execute`:

```python
async def execute(self, req: ToolCallRequest, ctx: SessionContext) -> ToolCallResult:
    tool = self._registry.get(req.tool_name)             # 1. lookup
    turn = await append_turn(...)                        # 2. persist
    tool_call = await create_tool_call(..., status="requested")
    emit(..., kind="tool.requested", ...)                # 3. trace
    guard = await self._guardrails.before_tool_call(...) # 4. guardrail
    if guard.blocked:
        return ToolCallResult(status="denied", error=guard.reason)
    if tool.blast_radius == "dangerous":
        decision = await self._approvals.request_and_wait(...)  # 5. approval
        if decision != "approved":
            return ToolCallResult(status="denied", error=f"approval {decision}")
    return await self._run_handler(tool, req, ctx, tool_call.id)  # 6. handler
```

Each step writes a row or a trace event. Each trace event ends up in
the cockpit's waterfall:

```
07:14:32  turn.user            "Do you have a 440 volt capacitor for a Carrier 58STA?"
07:14:33  tool.requested       parts_lookup({...})
07:14:33  guardrail.passed     parts_lookup
07:14:33  tool.executed        parts_lookup → 12 matches
07:14:34  turn.agent           "We've got 12 of part P-CAP-440-A in stock at $28.50 each. ..."
```

### Step 5 — Result back to the model, model finishes the turn

The edge POSTs the tool result back over the OpenAI WebSocket as a
`function_call_output`. OpenAI reads it, the model continues
generating, audio frames flow back, the edge transcodes them and
sends them to the surface.

A turn ends when `response.done` arrives without any `function_call`
items left to process. From the surface's perspective: the user heard
a coherent reply.

---

## Concurrency: tool calls in parallel within one turn

A single `response.done` event can carry several function calls.
Example from `verticals/hvac/scenarios/05_multi_tool_parallel.yaml`:

```
User: "I have a Lennox unit serial U-LENN-993301 with a bad capacitor.
       Is it still under warranty? Can you check tomorrow's schedule?"

Model emits, in parallel:
  function_call name=parts_lookup     args={"model_number":"Lennox-XR15", "part_description":"capacitor"}
  function_call name=warranty_check   args={"unit_serial":"U-LENN-993301"}
  function_call name=schedule_lookup  args={"start":"2026-05-08","end":"2026-05-08"}
```

The edge handles these in parallel by firing three core HTTP calls
concurrently and awaiting `Promise.all` (in practice, the JS event
loop and `await this.core.toolCall(...)` inside an async iteration are
sequenced; we kick off the three handlers via `await`-ed parallel
calls). The core happily executes them concurrently because each
tool handler is independent.

When all three results are back, the edge sends three
`function_call_output` items in sequence, then `response.create` —
the model now has all three results and synthesizes the answer.

---

## Per-session runtime state

The agent runtime maintains a small per-session map:

```python
# core/src/cockpit_core/agent/runtime.py
@dataclass
class AgentRuntime:
    pack: VerticalPack
    ctx: SessionContext
    dispatcher: ToolDispatcher

_active: dict[str, AgentRuntime] = {}
```

When `POST /v1/sessions` is called, a new `AgentRuntime` is built and
added to `_active` keyed by conversation ID. When `POST
/v1/sessions/{id}/end` is called, it's popped out. The dispatcher
inside the runtime closes over the vertical's tool registry,
guardrail set, and approval manager.

**This is process-local state.** If you run multiple core replicas
behind a load balancer, the same conversation ID has to land on the
same replica. v1 is single-replica, so this isn't a concern; if it
becomes one, the seam to externalize via Redis is tight (the
`_active` map is the only shared state).

---

## Approvals are part of the run loop

A subtle but important point: the approval gate is **inside** the
dispatcher's `execute()` method (step 5 above), not bolted on around
it. That means:

- The agent loop literally awaits `request_and_wait()` for up to 60
  seconds before returning to the model.
- During that wait, the model is *not* generating — it's blocked on
  the function_call_output reply.
- When the approval resolves, the dispatcher returns the result (or
  the denial), which the edge feeds back to the model, which
  continues.

If the approval times out:

- The dispatcher returns `ToolCallResult(status="denied")`.
- The edge sends `function_call_output` with `{"error": "approval timeout"}`.
- The model gets to respond (e.g., "I wasn't able to confirm with the
  dispatcher. I'll take a message instead.").

This is what makes "voice approvals" feel natural: the conversation
*pauses* during approval, the dispatcher hears the preamble, says the
phrase, and the conversation continues. No callback URLs, no
out-of-band signaling.

---

## Per-turn observability

For each turn, the trace pipeline emits at minimum:

- `turn.user` — full user transcript (PII-redacted)
- `tool.requested` — for each tool the model wants to call
- `guardrail.passed` / `guardrail.blocked` — for each tool
- `approval.requested` / `approval.resolved` — if dangerous
- `tool.executed` / `tool.failed` — for each
- `turn.agent` — full agent transcript

The cost of one tool call (in OpenAI tokens, computed from the
`response.done.usage` field if you ask the API for it) is rolled up
into the conversation's `cost_usd` field.

The cockpit displays this as a vertical timeline on the
`/conversations/<id>` page.

---

## What's notably absent in v1

### A separate "router" or "intent classifier" model

Some agent frameworks put a small classifier in front of the LLM that
decides whether a tool is needed at all. We don't. The Realtime model
itself decides whether to emit a `function_call`. This is faster
(fewer round-trips) and more accurate (the same model that knows the
context decides).

### A planner that emits sub-tasks as JSON

Some agent frameworks have the LLM emit a step-by-step plan
(`["lookup_customer", "check_warranty", "schedule_move"]`) and then
execute each step with a fresh prompt. This is overkill for voice —
the model has a single conversation context and resolves multi-step
intents naturally.

### Long-running background tasks

Some scenarios benefit from "fire-and-forget" workers (e.g. a deploy
that takes 5 minutes; the agent narrates progress while it runs). v1
doesn't have this. The seam is in `cockpit_core.agent.dispatch` — a
"background" blast radius could be added that fires-and-returns
immediately, with a separate channel for completion notifications.

---

## How to verify your agent is running well

1. **Latency budget.** Each phase has a checkpoint:
   first-response p50 under 1.5 s on a local network.
2. **Eval pass rate.** `make test-eval` runs the HVAC scenarios; CI
   blocks merge on regressions.
3. **No silent tool failures.** The `tool_calls` table should never
   have a row with `status='requested'` and `finished_at IS NULL` for
   more than ~30 s. (If you see this, the dispatcher hung; check
   `app.approvals` for an unresolved row.)
4. **Trace volume.** A normal turn produces ~7-12 trace events. Much
   more, and you're emitting too aggressively; much less, and you're
   missing decision points.

---

## Where to read next

- How dangerous tools get held: [guardrails-approvals.md](guardrails-approvals.md).
- The orchestration seam for multi-agent: [orchestration.md](orchestration.md).
- The cockpit's view of all this: [integrations-observability.md](integrations-observability.md).
