# Vertical Scenario Eval Format

Each vertical pack has a `scenarios/` directory of YAML files. The
runner discovers them via `verticals/<name>/scenarios/*.yaml` and runs
them under `make test-eval`.

## Schema

```yaml
id: short_unique_id
description: |
  Plain-language description of what this scenario covers.
vertical: hvac          # required, must match a pack name
surface: phone          # 'phone' | 'browser', default 'browser'
language: en            # BCP-47 starter; can change via 'language' action

# Documentation only; the runner does not currently replay audio.
user_inputs:
  - "Caller: do you have a 440V capacitor?"
  - dispatcher_phrase: "Reggie, do it"

# Drives the runner. Each action either invokes a tool or mutates session state.
actions:
  - kind: tool
    name: parts_lookup
    args:
      part_description: capacitor
  - kind: mode
    mode: translate
  - kind: language
    language: es

# Assertions. The runner records what happened and matches each expected
# entry against the recording.
expected_tool_calls:
  - name: parts_lookup
    args_contains:
      part_description: capacitor

expected_approvals:
  - tool: schedule_move
    decision: approved   # 'approved' | 'denied' | 'timeout'
    via: voice           # 'voice' | 'cockpit' | 'auto'

expected_no_pii: true     # default true; redactor must leave no raw PII
expected_mode: translate  # asserts session mode at end of run
```

## Adding a new scenario

1. Create `verticals/<your-vertical>/scenarios/NN_short_id.yaml`.
2. Use the schema above.
3. Run `make test-eval` to verify it passes.

A scenario regression blocks merge in CI.

## Limitations

- v1 does not replay actual audio fixtures against a recorded OpenAI
  Realtime player. The runner drives the agent core directly using the
  `actions` list, treating each action as ground truth for what the
  model would have asked the agent to do.
- The eval harness does **not** require a running Postgres or Redis;
  it executes tool handlers in-process and tracks invocations in
  memory.
