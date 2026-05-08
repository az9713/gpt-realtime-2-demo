# Orchestration — specialist sub-agents under one planner

> **OpenAI guide:** [Orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
> **Where it lands:** the seam reserved in the agent runtime; v1 ships a
> single-agent topology by design.

---

## What orchestration buys you

Single-agent designs work great until they don't. The pain points
that push teams toward multi-agent:

- **Tool overload.** When a vertical exposes 50+ tools, the model's
  attention starts to slip. Tool descriptions stop being read carefully;
  wrong tools get called.
- **Specialty knowledge.** A "deploy" agent benefits from a different
  prompt than a "CRM lookup" agent — different vocabulary, different
  caution levels.
- **Cost separation.** Some sub-tasks are fine on a smaller, cheaper
  model. A planner agent on `gpt-realtime-2` can hand a known-pattern
  sub-task to a cheaper text model and pay 1/10 the price.
- **Governance.** A "production-deploy" sub-agent can have its own
  approval policy and audit trail, separate from chat agents.

The "planner + specialist workers" pattern (also called multi-agent
orchestration) addresses all four:

```
                ┌─────────────────────┐
                │   PLANNER AGENT     │
                │   (gpt-realtime-2)  │
                │   - holds the call  │
                │   - decides routing │
                └──────────┬──────────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  CRM agent  │    │ Deploy agent│    │ Lookup agent│
│  (gpt-4.1)  │    │ (gpt-4.1)   │    │ (gpt-4.1)   │
│  CRUDs CRM  │    │ Runs CI/CD  │    │ Reads docs  │
└─────────────┘    └─────────────┘    └─────────────┘
```

The planner stays close to the user, fast and conversational. The
specialists run on whatever cadence the work needs — milliseconds
for a CRM lookup, minutes for a deploy.

---

## Why v1 of this app uses a single agent

A multi-agent topology is more complex and you should only adopt it
when the simpler topology is genuinely failing. v1 ships a single
agent because:

1. **HVAC has 7 tools.** Tool overload doesn't apply.
2. **One persona.** Aria is the dispatcher, full stop. There's no
   second persona to hand off to.
3. **No long-running tasks in v1.** Every HVAC tool returns in under
   a second. Background workers aren't needed.
4. **One approval policy.** All dangerous tools share the same
   approval pattern (phrase or click).

So in v1, the planner *is* the model and the workers *are* the tool
handlers. Orchestration is implicit.

---

## Where the seam is, for when you need it

The agent runtime is structured so multi-agent orchestration can land
without rewriting the platform. The relevant seams:

### 1. The dispatcher is one method on one class

`core/src/cockpit_core/agent/dispatch.py`:

```python
class ToolDispatcher:
    async def execute(self, req: ToolCallRequest, ctx: SessionContext) -> ToolCallResult:
        ...
```

You can swap this for a `RoutingDispatcher` that:

- Reads a `routing.yaml` mapping tool names → specialist agents.
- For tools routed to a specialist, opens an HTTP request to that
  specialist's API (or a local in-process call), forwards the args,
  awaits the result.
- For tools handled locally, falls through to the existing path.

The `Tool` contract doesn't change. The `ToolCallRequest` /
`ToolCallResult` contract doesn't change. Tests don't change.

### 2. Specialists are just another vertical

A "specialist" is a self-contained agent with its own tools, prompt,
and policies. The vertical pack format already supports this:

```
verticals/
├── hvac/                ← the planner pack (talks to the caller)
└── _specialists/
    ├── crm_lookup/      ← specialist pack (no surfaces, just tools)
    │   ├── pack.yaml
    │   ├── prompt.md
    │   └── tools.py
    └── deploy/
        ├── pack.yaml
        └── tools.py
```

The planner's tools call into the specialist's API; the specialist's
tools do the actual work.

### 3. Background tasks via Redis Streams or a queue

For long-running work (a deploy, a long EHR query) the dispatcher
gains a fourth blast-radius value: `background`. A `background` tool
returns immediately with a task ID. The agent narrates the kickoff
("Starting the deploy. I'll let you know when it's done."). When the
task completes, a worker process publishes to the conversation's
Redis channel; the cockpit and the agent both subscribe; the agent
gets a synthetic `tool.executed` event and can speak the result.

This is **out of scope for v1** but the channel pattern is already
in place for approvals and traces — adding a third channel for
background-task completion is small.

---

## Patterns the platform already supports today

Even without a true multi-agent topology, you can do a lot:

### Tool that delegates to another LLM

Any tool handler is just a Python coroutine. It can call the OpenAI
chat-completions API (or an Anthropic API, or a local model) inside
itself. From the planner's perspective it looks like one tool;
internally it might be a multi-LLM pipeline.

```python
async def deep_research_handler(req, ctx):
    # 1. Call a smaller model to extract entities from the question.
    entities = await openai_chat("gpt-4.1-mini", ...)
    # 2. Call a search API for each entity.
    docs = await asyncio.gather(*[search_for(e) for e in entities])
    # 3. Call a summarizer model to compose a final answer.
    summary = await openai_chat("gpt-4.1", ...)
    return {"summary": summary, "sources": docs}
```

This is a "specialist sub-agent" pattern in everything but name. The
planner doesn't need to know.

### Multiple verticals on one deployment

The cockpit's `POST /v1/sessions` accepts a `vertical` parameter. A
single deployment can serve multiple verticals, each with its own
prompt and tool registry, simply by routing inbound calls
differently. Twilio's `PHONE_VERTICAL_MAP` env var maps phone numbers
to verticals at the edge; the cockpit's frontend can let the operator
pick a vertical when starting a browser session.

### Mode switching

The `gpt-realtime-translate` model is itself a specialist (a
specialist *translator*) accessed by mode-switching. From the
platform's perspective it's the same WebSocket contract; the model
behind it is different. See [translate-mode.md](translate-mode.md).

---

## When to actually go multi-agent

Don't go multi-agent for the elegance of the diagram. The following
are real signals:

| Signal | Action |
|---|---|
| Tool registry > 25 tools, model often picks the wrong one | Split by domain into 2-3 specialist packs |
| One sub-task takes > 5 s and the user hears dead air | Make it a `background` tool with progress narration |
| Different tools need different approval policies | Already handled by per-tool `blast_radius` + `approvals.yaml` — no multi-agent required |
| You want the planner on a fast small model and workers on a smarter model | Multi-agent makes sense |
| You want different audit trails per sub-task | Multi-agent + separate `app.conversations` rows per specialist |

Until at least two of these are true, single-agent + good prompts +
good tool descriptions is faster to build, cheaper to run, and easier
to debug.

---

## How orchestration interacts with approvals

If you do go multi-agent, approvals get more interesting:

- The planner gates "should I delegate this?" decisions.
- Each specialist gates its own dangerous tools.
- The approval state machine is per-tool-call, not per-agent, so
  there's no extra coordination — but the *cockpit operator* might
  see two approval rows pop up for one user request.

The cockpit's approval queue UI shows tool name + args + conversation
ID; if a specialist's tool resolves, the planner's pending tool
unblocks too because the dispatcher's `await` returns. The data flow
is:

```
Planner: tool_call("deploy")    [blast_radius: dangerous → approval gate 1]
   ↓ after operator approves
Specialist 'deploy' agent: tool_call("write_db")   [also dangerous → approval gate 2]
   ↓ after operator approves
Specialist completes
   ↓
Planner's deploy() handler returns
   ↓
Planner narrates result.
```

Two approvals per user request. That's a UX cost. For most cases,
collapsing both into one (the planner's) is the right call — let the
specialist trust the planner's gate.

---

## Where to read next

- The single-agent path that v1 actually uses: [running-agents.md](running-agents.md).
- Approval mechanics in detail: [guardrails-approvals.md](guardrails-approvals.md).
- The platform's view of "specialists are just verticals":
  [voice-agents.md](voice-agents.md).
