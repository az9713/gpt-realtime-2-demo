# Realtime Models & Prompting — persona, preambles, "stay quiet until…"

> **OpenAI guide:** [Realtime Models & Prompting](https://developers.openai.com/api/docs/guides/realtime-models-prompting)
> **Where it lands:** the vertical pack — prompt.md, preambles.yaml,
> approvals.yaml.

---

## Why prompting matters more for voice agents

Text models can be terse, formal, or weird; the user reads at their
own pace and tolerates a lot. Voice agents can't. The persona is heard,
not read. Pauses, interruptions, and tone all go directly to the
caller's emotional reaction. Get it wrong and people hang up.

That makes prompting for voice **a product surface, not a config
detail**. The cockpit treats it accordingly:

- The persona, voice instructions, and refusal wording live in
  `verticals/<name>/prompt.md` — version-controlled, reviewed.
- Per-tool preambles ("Let me pull up that part") live in
  `preambles.yaml` so they're cheap to A/B and adjust.
- Approval-resolution phrases live in `approvals.yaml` because they
  are part of the safety contract.

---

## Three layers of "what the model sees"

When the edge opens an OpenAI Realtime WebSocket and sends
`session.update`, the model receives:

```
┌────────────────────────────────────────────────────────┐
│  1. The system prompt (instructions)                  │
│     ──────────────────────────────                     │
│     One block of text from prompt.md.                  │
│     Persona, tone, scope, behavioral rules.            │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│  2. The tool registry (tools)                         │
│     ──────────────────────────                         │
│     Array of typed tool descriptors.                   │
│     For each tool: name, description, JSON schema.     │
│     The model uses these to decide when to call which. │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│  3. The conversation buffer (live)                    │
│     ─────────────────────────────                      │
│     User audio + agent audio + tool calls + outputs    │
│     interleaved as the conversation proceeds.          │
│     Persists for the lifetime of the WebSocket.        │
└────────────────────────────────────────────────────────┘
```

You write (1) and (2). OpenAI manages (3).

The third layer is the live "scratch memory" discussed in
[realtime-conversations.md](realtime-conversations.md) — durable
state lives in Postgres; the WebSocket-scoped scratch is for the
model's working memory only.

---

## Layer 1 — the system prompt

The HVAC pack's `prompt.md` is the system prompt. It looks like this:

```markdown
# Aria — HVAC dispatcher

You are **Aria**, the dispatcher for a small HVAC company. ...

## Behavior

- Greet callers concisely. State the company name only if the caller
  asks who they reached.
- Ask one question at a time. Wait for the answer before asking the next.
- When you are about to call a tool, narrate **what** you are about
  to do in one short sentence — never the underlying tool name.
- For dangerous actions (rescheduling, dispatching a truck), state
  what you intend to do and **wait** for the dispatcher's
  confirmation phrase before executing.
- Never quote a price or commit to a job time without dispatcher approval.

## Tool guidance

- `parts_lookup` for any "do you have part X" question.
- `truck_inventory` when checking what's already loaded on a specific
  truck before rolling it.
- ...
```

A few patterns to notice:

### "Do" rules, not "don't" rules

Voice agents tend to over-comply with negative instructions and
become evasive. Aria's prompt is mostly affirmative ("Greet callers
concisely. Ask one question at a time."). When you do need a "don't,"
it should be specific and rare ("Never quote a price without dispatcher
approval").

### The persona has a *job*

"You are Aria, the dispatcher for a small HVAC company" is a much
richer prompt than "You are a helpful assistant." It tells the model
what kind of conversational moves are appropriate (an HVAC dispatcher
asks about model numbers and addresses; doesn't make small talk; takes
callbacks if the caller wants billing).

### Tool narration is mandated, but tool *names* are forbidden

This is a small but load-bearing rule:

> When you are about to call a tool, narrate **what** you are about to
> do in one short sentence — never the underlying tool name.

Without this, you get awkward responses like "Calling
warranty_check tool now." With it, you get "Let me look up the
warranty." That single rule does more for the felt experience than
any voice-tuning option.

### The caller-safety carve-out is at the top

> If a caller mentions a safety emergency (gas leak, carbon monoxide,
> fire), tell them to hang up and call 911 immediately. Do not attempt
> to schedule.

For HVAC this is uncontroversial. For other verticals (telehealth,
elder-care) the carve-outs are denser; they live in `policy.yaml`'s
`refusals` block as well, so the policy is enforced at multiple layers.

---

## Layer 2 — the tool registry

In `verticals/hvac/tools.py` each tool is a Python `Tool` dataclass:

```python
Tool(
    name="parts_lookup",
    description="Look up parts by model number and/or description.",
    schema={
        "type": "object",
        "properties": {
            "model_number":     {"type": "string", "description": "HVAC unit model number"},
            "part_description": {"type": "string", "description": "free-text description"},
        },
        "required": [],
    },
    blast_radius="read",
    handler=parts_lookup_handler,
),
```

When the edge opens an OpenAI session, the registry serializes to:

```json
{
  "type": "function",
  "name": "parts_lookup",
  "description": "Look up parts by model number and/or description.",
  "parameters": {
    "type": "object",
    "properties": {
      "model_number":     {"type": "string", "description": "..."},
      "part_description": {"type": "string", "description": "..."}
    },
    "required": []
  }
}
```

The model uses `description` as the *primary* signal for when to call
each tool. So tool descriptions matter. **Write them as instructions to
the model, not to the developer.** Compare:

> ❌ "Returns parts matching the given criteria from the catalog table."
>
> ✅ "Look up parts by model number and/or description. Use this for any
>     'do you have part X' question."

The second tells the model *when* to use the tool. The first describes
the implementation, which the model doesn't care about.

---

## Preambles — buying time during tool calls

A tool call takes 50–500 ms. During that time, if the model is
silent, the caller hears dead air and assumes something broke.

The fix is a **preamble**: a short phrase the model says *before*
invoking the tool. Configured in `verticals/hvac/preambles.yaml`:

```yaml
preambles:
  parts_lookup:    "Let me pull up that part."
  truck_inventory: "Checking what's on the truck."
  warranty_check:  "Let me look up the warranty."
  schedule_lookup: "Pulling up the schedule."
  customer_lookup: "Looking up the account."
  schedule_move:   "Reggie, do it"
  dispatch_truck:  "Reggie, send the truck"
```

The vertical pack loader reads this file, attaches each preamble to
its `Tool`'s `preamble` field, and the prompt instructs Aria to use
them: *"narrate what you are about to do in one short sentence."*

Two non-obvious uses:

- **Preambles for dangerous tools double as approval phrases.**
  `schedule_move`'s preamble is *"Reggie, do it"* — that's the literal
  string the dispatcher must say to resolve the approval. This is by
  design (see [guardrails-approvals.md](guardrails-approvals.md)).
- **A/B testing preambles is cheap.** Changing `"Let me pull up that
  part."` → `"One moment."` is one YAML edit and a session restart.
  No prompt-rewriting required.

---

## "Stay quiet until …" mode

Sometimes you want the model to *not* speak — to listen passively
until something specific happens. Examples:

- Translate mode: the model only speaks when there's something to
  translate. (See [translate-mode.md](translate-mode.md).)
- A meeting overlay: the model takes notes silently and only speaks
  when called on by name.
- A telehealth intake: the model waits while the caller fills out
  symptoms aloud, then summarizes only when prompted.

The mechanism is two-fold:

1. **The system prompt** sets the policy: "Do not speak unless the
   user addresses you by name" or similar.
2. **`output_modalities`** can be set to `["text"]` to suppress
   audio entirely while still letting the model think.

Translate mode in this codebase uses (1) by switching to the
`gpt-realtime-translate` model, which is purpose-built to relay user
speech as translated speech without taking conversational initiative.
The cockpit's mode switcher tears down the active OpenAI session and
opens a new one against the translate model, with the same
conversation ID.

---

## How the prompt actually arrives at the model

Walking the path:

```
Edge opens OpenAI WS
   │
   ▼
Edge calls core: GET session config (POST /v1/sessions earlier returned this)
   │
   ▼
Edge sends session.update event:
   {
     "type": "session.update",
     "session": {
       "type": "realtime",
       "model": "gpt-realtime-2",
       "instructions": "<prompt.md content>",
       "output_modalities": ["audio"],
       "tools": [<every Tool from registry, serialized>],
       "audio": {
         "input":  { "format": ..., "turn_detection": {"type":"semantic_vad"},
                     "transcription": {"model":"whisper-1"} },
         "output": { "format": ..., "voice": "alloy" }
       }
     }
   }
```

`session.update` is *one* event. You can send another later in the
session to change instructions or tools mid-conversation, which is
how mode switches and persona changes work.

---

## Voice selection

OpenAI offers a small set of voices for the Realtime API: alloy,
ash, ballad, coral, echo, sage, shimmer, verse, marin, … (the list
grows; check the docs for the current set).

The default in this codebase is `alloy`, set via `OPENAI_VOICE` env
var and surfaced through `audio.output.voice` in `session.update`.

Choosing a voice for a vertical is a UX decision, not a technical
one. For an HVAC dispatcher, a calm, professional voice fits. For a
medical-intake nurse, slower and softer. Try a few; commit one in
`pack.yaml` if the operator has a preference.

---

## Why prompts live in YAML/Markdown, not Python

Two reasons.

### Prompts are data, not code

Treating prompts as code means you bake the wording into your build,
your tests, your code review process. That sounds disciplined but it
makes iteration slow — every wording tweak is a code change.

Treating prompts as data lets you:

- Edit them without touching the platform.
- Diff and review them like content (because they are content).
- A/B them, version them, swap them per-deployment.
- Show them to non-engineers (operations, customer service, legal).

### Verticals can ship prompts independently

A vertical pack (`verticals/<name>/`) is a directory of YAML and
Markdown files plus one Python file (`tools.py`). A small operator
running this stack on their own server can fork the HVAC pack, edit
`prompt.md`, and have a customized agent without rebuilding the
platform.

This is the same pattern as Kubernetes Helm charts or Terraform
modules: the *configuration* travels with the *use case*, not with
the engine.

---

## Tips for writing voice-agent prompts

Things we've learned from this build:

1. **Lead with the persona.** The first sentence sets everything else.
   "You are Aria, the dispatcher for a small HVAC company" is better
   than "You are a helpful AI."
2. **Be explicit about pacing.** "Ask one question at a time" prevents
   the model from rattling off three questions while the caller is
   still answering the first.
3. **Disclose uncertainty.** "If you are not sure who is calling, ask
   their name and address" stops the model from inventing a customer
   ID.
4. **Pin the format of preambles.** The prompt should require *"one
   short sentence — never the underlying tool name"* explicitly, or
   the model will sometimes say "Calling parts_lookup."
5. **Forbid speculation about prices/timelines without data.**
   Prevents the agent from comforting the caller with made-up
   commitments.
6. **Reserve the bottom of the prompt for safety overrides.** Things
   like "If a caller mentions chest pain, immediately tell them to
   call 911" should be the last things the model reads — that's where
   recency biases attention.
7. **Don't over-constrain humor or warmth.** Voice agents that read
   from a script sound like they're reading from a script. A loose
   tonal direction ("calm, friendly, professional. Confident but never
   brash.") works better than a list of forbidden words.

---

## Where to read next

- For how the agent actually runs each turn under the prompt:
  [running-agents.md](running-agents.md).
- For how dangerous tools get held: [guardrails-approvals.md](guardrails-approvals.md).
- For the model itself: [reference/gpt-realtime-2.md](../reference/gpt-realtime-2.md).
