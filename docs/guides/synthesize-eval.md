# Synthesize an eval scenario from a real call

Goal: take a past conversation that exhibited interesting behavior
(good or bad) and turn it into a runnable YAML scenario under
`verticals/<vertical>/scenarios/`. The result is a self-passing eval
that pins that behavior so it doesn't regress.

Time: ~2 minutes per scenario.

---

## Prerequisites

- The cockpit stack is running with Postgres reachable.
- You have a conversation ID for a call you'd like to capture as an
  eval. Find one via the cockpit's `/conversations` page or:

```bash
curl -s http://localhost:8000/v1/conversations?limit=20 | jq '.conversations[].id'
```

---

## Steps

### 1. Run the synthesizer

```bash
make synthesize-eval CONV=<uuid>
# or:
python scripts/synthesize-eval.py <uuid>
```

Default output path:
`verticals/<vertical>/scenarios/replay_<short-uuid>.yaml`

Override with `--out`:

```bash
python scripts/synthesize-eval.py <uuid> --out verticals/hvac/scenarios/maria-callback.yaml
```

Sample output:

```
wrote scenario: verticals/hvac/scenarios/replay_4d2c8e3a.yaml
```

### 2. Inspect what it captured

The synthesizer reads:

| Source | Becomes |
|---|---|
| `app.conversations.{vertical, surface, mode, language}` | Top-level scenario fields |
| `app.turns` where `role='user'` | `user_inputs` array (transcripts only — for documentation; the runner doesn't replay them) |
| Initial `mode != 'realtime2'` | A leading `actions: [{kind: mode, mode: ...}]` action |
| Initial `language != 'en'` | A leading `actions: [{kind: language, language: ...}]` action |
| `app.tool_calls` where `status='executed'` | One `{kind: tool, name, args}` action per call, plus `expected_tool_calls` entries |
| `app.tool_calls` with `blast_radius='dangerous' AND approval_id IS NOT NULL` | An `expected_approvals` entry with `decision='approved'` (or `'denied'` if the call wasn't executed) |

Open the file. It should look like:

```yaml
id: replay_4d2c8e3a
description: |
  Synthesized from real conversation 4d2c8e3a-...
  Surface: phone; mode: realtime2; started: 2026-05-08T...
vertical: hvac
surface: phone
language: en
user_inputs:
  - Hi, my AC isn't cooling.
  - Tomorrow at 11 if possible.
actions:
  - kind: tool
    name: schedule_lookup
    args: { start: "2026-05-09", end: "2026-05-09" }
  - kind: tool
    name: schedule_move
    args: { job_id: J-5001, new_slot: "2026-05-09T11:00:00Z" }
expected_tool_calls:
  - { name: schedule_lookup, args_contains: {} }
  - { name: schedule_move, args_contains: { job_id: J-5001 } }
expected_approvals:
  - { tool: schedule_move, decision: approved, via: auto }
expected_no_pii: true
expected_mode: realtime2
```

### 3. Hand-edit if you want to relax assertions

The auto-generated YAML is conservative — it asserts every executed
tool call. Often you want a looser eval:

- Trim `args_contains` down to the fields that matter (e.g. just
  `job_id`, not the literal timestamp).
- Drop `expected_approvals` if you don't care which path resolved the
  approval.
- Edit `id` and `description` to be human-readable.

### 4. Run the new scenario alone

```bash
cd core
.venv/Scripts/python.exe -m pytest tests/eval -k replay_4d2c8e3a -v
```

If it passes, you've captured the behavior. Commit the YAML.

If it fails, your eval is asserting something the runner can't
reproduce — usually because the agent's tool sequence depends on a
fixture that isn't deterministic, or because you trimmed
`args_contains` too aggressively. Adjust the YAML and rerun.

### 5. Add to the regression net

Once the new scenario passes, it's part of the suite:

```bash
make test-eval
```

CI runs `make test-eval` on every PR — your scenario now blocks
merges that would regress it.

---

## When this is most useful

- **A user reported a bug.** Find the conversation in the trace
  explorer; synthesize it into a scenario; reproduce locally;
  fix the bug; the scenario now serves as a regression test.
- **A new tool just shipped.** Run a few real calls through the
  cockpit; synthesize them into scenarios so the next change to that
  tool doesn't silently break the call paths you tested.
- **You're refactoring the dispatcher.** Bulk-synthesize the last
  N production calls (script around `synthesize-eval.py`); your
  refactor now has a real-call regression net.

---

## What v1 doesn't do

- **Re-transcribe stored audio.** SPEC §13.2 — v1 doesn't store audio.
  The synthesizer reads transcripts from `app.turns` directly. If
  audit_transcripts is on for the vertical, the whisper transcripts
  are the canonical source the synthesizer prefers.
- **Capture timing assertions.** `expected_tool_calls` doesn't
  include latency budgets. If you want to assert "first response under
  1.5 s," you'd add that as a separate scenario field — out of scope
  in v1.
- **Auto-detect ideal vs. broken behavior.** Whatever happened in the
  source conversation becomes the asserted expected behavior. If the
  agent did something wrong, fix it before synthesizing — or
  synthesize it and use the scenario as a regression target ("the bug
  shouldn't recur after my fix").

---

## Verification

After running and committing:

- [ ] The YAML file exists under `verticals/<vertical>/scenarios/`.
- [ ] `make test-eval` runs the new scenario and it passes.
- [ ] The scenario id and description are human-readable.
- [ ] `args_contains` only includes fields that matter.

---

## Troubleshooting

**Symptom:** `synthesize-eval` exits with `conversation not found`.
**Cause:** UUID typo; no row in `app.conversations` with that id.
**Fix:** `curl -s http://localhost:8000/v1/conversations?limit=20 | jq` to get a real id.

**Symptom:** Scenario synthesizes but fails on `make test-eval` with
"expected tool ... not found."
**Cause:** Likely the args you captured don't match the registry's
JSON schema (e.g. you captured `args: {start: "2026-05-09T..."}` but
the tool expects `args: {start: "2026-05-09"}`).
**Fix:** Trim `args_contains` to the truly-meaningful fields, or
edit the args in the synthesized scenario file.

**Symptom:** Scenario synthesizes but `actions` are empty even though
the conversation had tool calls.
**Cause:** The tool calls were `status='requested'` (e.g. timed out
on approval), not `'executed'`. The synthesizer only includes
executed tool calls in `actions`.
**Fix:** This is by design — only successfully executed tools are
captured. If you want a scenario that asserts a denial, hand-edit the
YAML to add `expected_approvals: [{tool: ..., decision: denied}]`.

---

## Where to read next

- The eval YAML schema and runner: [eval-format.md](../eval-format.md).
- The whisper-feature concept that made this possible:
  [reference/realtime-models-in-use.md](../reference/realtime-models-in-use.md).
- All eval scenarios: `verticals/hvac/scenarios/*.yaml`.
