# Use Cases & Worked Examples

This document walks through realistic things you'd actually do with
the Voice Operations Cockpit — not toy "hello world" demos.

For each scenario you'll find:

1. **The story** — what's happening, who's involved, why it matters.
2. **In the cockpit** — exact click-path through the browser UI.
3. **On the phone** — what the caller and dispatcher hear.
4. **From the terminal** — equivalent commands using `curl`, `make`, and `gh`.
5. **From Claude Code** — natural-language prompts that get the same job done when you have Claude Code wired into your workflow.

Use the section that fits your role. A dispatcher will live in the
cockpit. A developer will live in the terminal. An operator owning
both is the target audience for the Claude Code prompts.

---

## Table of contents

| # | Scenario | Type |
|---|---|---|
| 1 | Caller asks for a part | Read tool, no approval |
| 2 | Reschedule a job — approved by voice | Dangerous tool, voice-resolved |
| 3 | Reschedule a job — denied in cockpit | Dangerous tool, cockpit-resolved (deny) |
| 4 | Dispatch a truck — approved in cockpit | Dangerous tool, cockpit-resolved (approve) |
| 5 | Spanish-speaking caller → translate flip | Mode switch, auto |
| 6 | Multi-tool parallel turn | Parts + warranty + schedule in one ask |
| 7 | Safety emergency mid-call | Refusal taxonomy, hangup |
| 8 | Replay a past conversation | Postmortem / training |
| 9 | Watch every tool call in real time | Live observability |
| 10 | Add a new approval phrase to a tool | Operator config change |
| 11 | Add a brand-new tool to the HVAC pack | Developer task |
| 12 | Switch the active vertical | Multi-vertical operator |
| 13 | Investigate a regression after a change | Eval-driven debugging |

---

# 1. Caller asks for a part

> *A homeowner calls because their AC isn't cooling. Aria looks up the part.
> No approval needed — this is a read-only tool.*

### The story

Maria Alvarez, the homeowner at 1402 Elm, dials your Twilio number.
After Aria greets her, she says:

> *"Do you have a 440 volt capacitor for a Carrier 58STA?"*

Aria says *"Let me pull up that part"* (the preamble), invokes
`parts_lookup`, and replies with what's in stock and the price.

This is the simplest case in the system: a read tool fires, no
guardrail blocks, no approval needed.

### In the cockpit

The dispatcher can listen along by opening the conversation in real
time:

1. Open the cockpit at **http://localhost:5173** and sign in.
2. Click **Conversations** in the top nav.
3. The newest row is the live call. Click it.
4. Watch the **Trace** column on the left. As Maria talks, you'll see:
   - `turn.user` — Maria's transcribed question
   - `tool.requested parts_lookup`
   - `guardrail.passed`
   - `tool.executed parts_lookup` (with the matches)
   - `turn.agent` — Aria's response

The right column shows the conversation as **Turns** with role and
latency.

There's no approval to act on — the dispatcher is a passive
observer for read-only flows.

### On the phone

```
[ring]
Aria:   Hi there, how can I help you today?
Maria:  Do you have a 440 volt capacitor for a Carrier 58STA?
Aria:   Let me pull up that part.
        ... (300-500ms pause while parts_lookup runs)
Aria:   Yeah, we've got 12 of part P-CAP-440-A in stock at $28.50 each.
        Do you want me to get one on a truck for you?
```

### From the terminal

To inspect the same call after it ended:

```bash
# list the most recent conversations
curl -s http://localhost:8000/v1/conversations?limit=5 | jq '.conversations[] | {id, vertical, surface, started_at}'

# pick the conversation id and dump the trace
CONV=<paste-id-here>
curl -s http://localhost:8000/v1/conversations/$CONV/trace | jq '.events[] | {ts, kind, payload}'

# or use the operator script for a readable timeline
make trace CONV=$CONV
```

Sample `make trace` output:

```
2026-05-08T14:09:16  session.start            {'vertical':'hvac','surface':'phone','mode':'realtime2','persona':'Aria'}
2026-05-08T14:09:23  turn.user                {'transcript_preview':'Do you have a 440 volt capacitor for a Carrier 58STA?',...}
2026-05-08T14:09:23  tool.requested           {'tool':'parts_lookup','args':{'part_description':'capacitor','model_number':'Carrier-58STA'},...}
2026-05-08T14:09:23  guardrail.passed         {'tool':'parts_lookup'}
2026-05-08T14:09:23  tool.executed            {'tool':'parts_lookup','result':{'matches':[...],'total_matches':2}}
2026-05-08T14:09:24  turn.agent               {'transcript_preview':"We've got 12 of part P-CAP-440-A...",'turn_id':'...'}
```

### From Claude Code

```
"Pull up the most recent HVAC phone call and summarize what the
caller asked, which tools fired, and how long the agent's first
response took."
```

Claude Code reads `app.conversations` + `app.tool_calls` +
`app.turns` (via the cockpit's REST endpoints or the operator
scripts) and produces the summary inline.

---

# 2. Reschedule a job — approved by voice

> *Dispatcher Reggie sits next to the cockpit. A customer calls to move
> their appointment. Aria asks for confirmation; Reggie says the magic
> phrase out loud; the schedule updates.*

### The story

James Boone calls about job J-5002 (his Wednesday repair). He wants
to move it to Tuesday at 8am. Aria stages the change but pauses:

> *"I'd like to move job J-5002 to Tuesday at 8am. Reggie, do it?"*

Reggie, listening on speakerphone, says:

> *"Reggie, do it."*

The voice-intent classifier on the edge sees the transcript chunk,
matches the configured phrase exactly, and resolves the approval.
The mutation runs.

### In the cockpit

Reggie can watch the live trace but doesn't have to click anything —
his voice resolves it. To approve via the cockpit instead, see
scenario 4.

To audit afterwards:

1. Open **http://localhost:5173/conversations**.
2. Click the relevant conversation.
3. The trace shows:
   - `tool.requested schedule_move` (status `requested`)
   - `approval.requested` with the phrase `"Reggie, do it"`
   - `approval.resolved` with `decided_via: voice`
   - `tool.executed schedule_move` (the mutation)

### On the phone

```
James:  Can we move my Wednesday job to Tuesday at 8am?
Aria:   Let me pull up the schedule.
        ...
Aria:   Okay, I see job J-5002. I'd like to move it to Tuesday May 7th
        at 8am. Reggie, do it?
Reggie: (on speakerphone, in the room) Reggie, do it.
        ... (150ms pause)
Aria:   Done. Job J-5002 is now Tuesday at 8 a.m. Anything else?
```

### From the terminal

To force-test the voice-approval path against a live session (advanced):

```bash
# while a session is active, simulate the voice classifier's call
CONV=<active-conversation-id>
curl -s -X POST http://localhost:8000/v1/sessions/$CONV/approval-by-voice \
  -H 'content-type: application/json' \
  -d '{"phrase":"Reggie, do it"}'
# {"status":"ok","approval_id":"..."}
```

To run the eval scenario that exercises this same flow in CI:

```bash
cd core
.venv/Scripts/python.exe -m pytest tests/eval/test_hvac_scenarios.py \
  -k "schedule_move_approved" -v
```

### From Claude Code

```
"Show me every approval that was resolved by voice in the last 24
hours, grouped by tool name."
```

```
"In the HVAC pack, change the approval phrase for schedule_move
from 'Reggie, do it' to 'Reggie, ship it'. Update both
approvals.yaml and preambles.yaml so they stay in sync, and run
the eval suite to confirm nothing breaks."
```

The second prompt is a vertical-pack edit + verification cycle:
Claude Code reads `verticals/hvac/approvals.yaml` and
`preambles.yaml`, makes the matching edit, runs `make test-eval`,
and reports the result.

---

# 3. Reschedule a job — denied in cockpit

> *Customer requests a slot Reggie doesn't want to give. Aria stages the
> move; Reggie clicks Deny. The mutation never runs.*

### The story

A different customer wants to move job J-5004 to a slot that conflicts
with another tech's existing route. Aria stages the change. Reggie
glances at the cockpit, sees the conflict, and clicks **Deny**.

Aria gracefully recovers:

> *"Reggie wasn't able to confirm that move. Can I take a message and
> have him call you back?"*

### In the cockpit

The dispatcher's path:

1. Open **http://localhost:5173/approvals** (or the **Approvals**
   tab from the top nav).
2. A pending row appears:
   ```
   [DANGEROUS] schedule_move
   { "job_id": "J-5004", "new_slot": "2026-05-07T08:00:00Z" }
   conv 1210e2ab · requested 7:14:32 AM
   [ Approve ]   [ Deny ]
   ```
3. Click **Deny**.

The trace updates:
- `approval.resolved` with `decision: denied, decided_via: cockpit`
- `tool_calls.status` becomes `denied` (the mutation never ran)

### On the phone

```
Customer: Can you move my Friday job to Tuesday at 8?
Aria:     Let me check the schedule. ...
Aria:     I see Tuesday at 8 might overlap another route. Reggie, do it?
          ... (Reggie is silent. Cockpit shows the pending approval.
              Reggie clicks Deny.)
Aria:     Reggie wasn't able to confirm that move. Can I take a
          message and have him call you back?
```

### From the terminal

```bash
# list pending approvals
curl -s http://localhost:8000/v1/approvals | jq '.approvals[]'

# deny by approval_id
APPROVAL=<id-from-above>
curl -s -X POST http://localhost:8000/v1/approvals/$APPROVAL/resolve \
  -H 'content-type: application/json' \
  -d '{"decision":"denied","decided_by":"reggie"}'
```

### From Claude Code

```
"Show me approvals denied in the last week along with the job_id
and the customer name. I want to spot patterns in what we're
turning down."
```

Claude Code joins `app.approvals` + `app.tool_calls` (denied) +
`app.conversations` + the HVAC `customers.json` fixture, and prints
a table.

---

# 4. Dispatch a truck — approved in cockpit

> *Aria asks to dispatch Aldo's truck to a repair. Reggie is wearing
> headphones (no speakerphone). He clicks Approve in the cockpit
> instead of saying the phrase aloud.*

### The story

Maria's call from scenario 1 continues. Aria has confirmed the part
is in stock and proposes:

> *"Aldo has an open slot at 11 a.m. Want me to dispatch his truck?
> Reggie, send the truck?"*

Reggie clicks **Approve** in the cockpit.

### In the cockpit

1. Click **Approvals** in the nav.
2. New row:
   ```
   [DANGEROUS] dispatch_truck
   { "job_id": "J-5002", "truck_id": "T-101" }
   ```
3. Click **Approve**.
4. Switch to **Conversations** → click the live row.
5. Watch `tool.executed dispatch_truck` appear in the trace.

### On the phone

```
Aria:   Aldo has an open slot at 11 a.m. Want me to dispatch his
        truck? Reggie, send the truck?
        ... (Reggie clicks Approve)
Aria:   Done. Aldo's on the way; you'll see his truck around 11.
        Anything else, Maria?
```

### From the terminal

```bash
# the same resolve endpoint as scenario 3, with decision=approved
APPROVAL=<id>
curl -s -X POST http://localhost:8000/v1/approvals/$APPROVAL/resolve \
  -H 'content-type: application/json' \
  -d '{"decision":"approved","decided_by":"reggie"}'
```

### From Claude Code

```
"How many trucks did we dispatch this week, by tech? Sum from the
tool_calls table where tool_name = 'dispatch_truck' and
status = 'executed'."
```

---

# 5. Spanish-speaking caller → translate flip

> *Caller starts speaking Spanish. Within 3-4 seconds the cockpit
> auto-flips to translate mode. Reggie hears English; the caller
> hears Spanish.*

### The story

A Spanish-speaking customer calls. Their first sentence is *"Hola,
necesito agendar un servicio."*

The edge's language-ID classifier (transcript-based) sees `es` (or
"unknown" → falls through to the operator's manual flip). Because
the HVAC pack has `auto_translate_non_english: true`, the edge
sends a `mode.switch` to translate. Within ~2 seconds, the OpenAI
session is re-opened against `gpt-realtime-translate`; from here
out, Aria translates between English and Spanish.

### In the cockpit

What Reggie sees:

1. Open the live conversation in **Conversations**.
2. The mode badge at the top of the Talk panel changes from
   **REALTIME-2** to **TRANSLATE**.
3. The trace shows a `mode.switch` event with `mode: translate`.
4. The transcript pane keeps showing English (the side Reggie reads),
   while the caller hears Spanish.

If Reggie wants to flip back manually mid-call, he clicks **Switch
to Realtime**.

### On the phone

```
Caller: Hola, necesito agendar un servicio para mi aire acondicionado.
        ... (cockpit flips to translate ~2s)
Aria:   (in Spanish, reflecting Reggie's reply) Hola — claro, ¿qué
        problema está teniendo?
Reggie: (in English) Ask if their AC is blowing warm air or just nothing.
Aria:   (in Spanish to caller) ¿Su aire acondicionado está soplando
        aire caliente o no sopla nada?
...
```

### From the terminal

To force a mode switch on an active session:

```bash
CONV=<active-id>
curl -s -X POST http://localhost:8000/v1/sessions/$CONV/mode \
  -H 'content-type: application/json' \
  -d '{"mode":"translate"}'
# {"status":"ok","mode":"translate"}

# back to realtime2:
curl -s -X POST http://localhost:8000/v1/sessions/$CONV/mode \
  -H 'content-type: application/json' \
  -d '{"mode":"realtime2"}'
```

To run the translate-flip scenario in CI:

```bash
cd core
.venv/Scripts/python.exe -m pytest \
  tests/eval/test_hvac_scenarios.py -k spanish -v
```

### From Claude Code

```
"How many of last week's calls flipped to translate mode? Show me
which language was detected and how long the call lasted."
```

```
"The HVAC pack auto-flips to translate for any non-English caller.
Add Mandarin (zh) and Vietnamese (vi) to the supported translate
languages in the pack policy.yaml."
```

---

# 6. Multi-tool parallel turn

> *Caller asks three questions in one breath. The model fires three tools
> in parallel, then synthesizes one answer.*

### The story

A caller says:

> *"I have a Lennox unit serial U-LENN-993301 with a bad capacitor.
> Is it still under warranty? Can you check tomorrow's schedule?"*

The model recognizes three things to do at once:

1. `parts_lookup({"model_number": "Lennox-XR15", "part_description": "capacitor"})`
2. `warranty_check({"unit_serial": "U-LENN-993301"})`
3. `schedule_lookup({"start": "2026-05-09", "end": "2026-05-09"})`

All three appear in `response.done.output[]` from the same model
turn. The edge dispatches them in parallel. The core runs them
concurrently. All three results return; the model then composes one
spoken answer.

### In the cockpit

Trace pane during this turn:

```
07:18:42  turn.user           "I have a Lennox unit serial U-LENN-993301..."
07:18:43  tool.requested      parts_lookup
07:18:43  tool.requested      warranty_check
07:18:43  tool.requested      schedule_lookup
07:18:43  guardrail.passed    parts_lookup
07:18:43  guardrail.passed    warranty_check
07:18:43  guardrail.passed    schedule_lookup
07:18:43  tool.executed       parts_lookup     (12 matches)
07:18:43  tool.executed       warranty_check   (covered: true)
07:18:43  tool.executed       schedule_lookup  (3 jobs in window)
07:18:45  turn.agent          "Yeah — that unit's covered under warranty
                              until 2031. We've got the capacitor in stock,
                              and Bea has an open slot tomorrow at 1pm. Want me
                              to book it?"
```

Three `tool.executed` events within ~50 ms of each other.

### On the phone

```
Caller: I have a Lennox unit serial U-LENN-993301 with a bad capacitor.
        Is it still under warranty? Can you check tomorrow's schedule?
Aria:   Let me check those for you.
        ... (~600ms — three tools running in parallel)
Aria:   Yeah — that unit's covered under warranty until 2031. We've got
        the capacitor in stock, and Bea has an open slot tomorrow at
        1pm. Want me to book it?
```

### From the terminal

The eval harness exercises this scenario:

```bash
cd core
.venv/Scripts/python.exe -m pytest \
  tests/eval/test_hvac_scenarios.py -k multi_tool_parallel -v
```

### From Claude Code

```
"Find conversations where three or more tools fired in the same turn.
For each, show the user transcript and the tool names."
```

---

# 7. Safety emergency mid-call

> *A caller mentions a gas leak. Aria refuses to schedule and tells them
> to call 911.*

### The story

Mid-conversation:

> *"There's a gas smell when the heat kicks on. Should I just shut
> the breaker?"*

The HVAC pack's `policy.yaml` declares this trigger:

```yaml
refusals:
  - id: safety_emergency
    triggers: ["gas leak", "carbon monoxide", "smoke alarm"]
    message: "Please leave the building and call 911 right away."
```

The prompt also explicitly instructs Aria:

> *If a caller mentions a safety emergency (gas leak, carbon monoxide,
> fire), tell them to hang up and call 911 immediately. Do not attempt
> to schedule.*

So Aria responds with the safety message and stops trying to book
or look anything up.

### In the cockpit

The trace:

```
turn.user            "There's a gas smell..."
turn.agent           "Please leave the building and call 911 right away..."
session.end          (caller hangs up)
post_call.executed   summary written
```

No tool calls. No approvals. Just the safety response.

### On the phone

```
Caller: There's a gas smell when the heat kicks on. Should I just
        shut the breaker?
Aria:   That's a safety issue. Please leave the building and call
        911 right away. Do not stay on the line.
        ... (caller hangs up)
```

### From Claude Code

```
"Audit calls from the last month where a safety_emergency refusal
fired. Show the trigger phrase that matched and confirm no tool
calls executed in those conversations."
```

```
"Add 'natural gas' as an additional trigger phrase to the
safety_emergency refusal in verticals/hvac/policy.yaml."
```

---

# 8. Replay a past conversation

> *A customer calls to complain about a tech who showed up at the wrong
> time. The dispatcher needs to find what Aria committed to.*

### The story

Maria from yesterday calls back upset: she expected a tech at 11
a.m., and nobody came until 1 p.m. Reggie needs to know exactly what
Aria said and what tool calls fired during that conversation.

### In the cockpit

1. Open **http://localhost:5173/conversations**.
2. Find Maria's call from yesterday by sorting on **Started** column
   (default DESC).
3. Click the row.
4. Read the **Turns** pane top-to-bottom — full transcript with
   timestamps.
5. Cross-reference against the **Trace** pane — what tools ran,
   what arguments, what results.

If Reggie needs to copy-paste the full conversation into a ticket:

6. Open the operator-script terminal flow below.

### From the terminal

```bash
# find the conversation
curl -s 'http://localhost:8000/v1/conversations?limit=50' \
  | jq '.conversations[] | select(.surface=="phone") | {id,started_at,ended_at}'

# pick the id, then:
CONV=<paste-id>

# readable timeline (turns + tool calls interleaved)
make replay CONV=$CONV

# raw trace dump
make trace CONV=$CONV
```

`make replay` output looks like:

```
# replay 4d2c8e3a-...
  18 turns · 4 tool calls · 47 trace events

2026-05-07T14:09:23Z  [user ] "Hi, my AC isn't cooling..."
2026-05-07T14:09:24Z  [agent] "Sorry to hear that. What's your address?"
2026-05-07T14:09:31Z  [user ] "1402 Elm Street"
2026-05-07T14:09:32Z  [tool ] customer_lookup({'address': '1402 Elm Street'}) -> executed
2026-05-07T14:09:33Z  [agent] "Got you, Maria. Let me check the schedule..."
2026-05-07T14:09:34Z  [tool ] dispatch_truck({'job_id':'J-5002','truck_id':'T-101'}) -> executed
2026-05-07T14:09:35Z  [agent] "Aldo's on his way; he'll be there around 11."
...
```

### From Claude Code

```
"Find Maria Alvarez's most recent call. What time did Aria say the
tech would arrive? When did dispatch_truck fire and which truck
was assigned?"
```

```
"Compare what Aria committed to in Maria's call yesterday with the
actual tech arrival time we have in the post-call summary. Did we
miss the window?"
```

---

# 9. Watch every tool call in real time

> *Reggie wants a heads-up display while a call is in progress: which
> tools are running, how long they take, what the model is about to do.*

### The story

Power-user mode. Reggie keeps the cockpit open on a second monitor.
He's not driving the call (Aria is); he's just monitoring.

### In the cockpit

1. Open **http://localhost:5173/conversations**.
2. As soon as a call starts, the new row appears at the top with
   "live" in the **Ended** column.
3. Click the row.
4. The trace pane updates in real time via Redis pub/sub — you'll
   see events appear as they happen, with sub-second latency.
5. Color coding:
   - green = read tool / safe step
   - amber = approval-related event
   - orange = mode switch
   - rose = guardrail block / tool failure
   - blue = user turn
   - emerald = agent turn

### From the terminal

To watch trace events as they happen via Redis:

```bash
# subscribe to a per-session channel (you need the conv id)
docker compose exec redis redis-cli SUBSCRIBE session:<conv-id>

# or all approval events across all conversations
docker compose exec redis redis-cli SUBSCRIBE approvals
```

To tail the structured logs of all services:

```bash
docker compose logs -f core edge
```

### From Claude Code

```
"Show me a real-time stream of tool calls firing right now across
all active conversations. Format as a single line per event:
timestamp, conversation id (8 char), tool name, status."
```

```
"Alert me if any tool call takes more than 2 seconds to execute.
Watch the trace for the next 10 minutes."
```

---

# 10. Add a new approval phrase to a tool

> *Reggie wants the approval phrase for `dispatch_truck` to be different
> in his deployment. He prefers 'Reggie, send the truck' to be 'Reggie,
> roll the truck' to match what he says naturally.*

### The story

This is an operator config change, not a code change. The phrase
lives in `verticals/hvac/approvals.yaml`. The preamble (what Aria
says before the tool) lives in `verticals/hvac/preambles.yaml`. They
have to match — the preamble *is* the dispatcher's cue.

### In the cockpit

Cockpit doesn't expose this; it's a config file change. Skip to the
terminal section.

### From the terminal

Edit two files; restart the core; verify with the eval suite.

```bash
# 1. update the approval phrase
cat > /tmp/approvals.yaml.patch <<'EOF'
tools:
  schedule_move:
    phrase: "Reggie, do it"
    timeout_seconds: 60
  dispatch_truck:
    phrase: "Reggie, roll the truck"     # was: "Reggie, send the truck"
    timeout_seconds: 60
EOF
mv /tmp/approvals.yaml.patch verticals/hvac/approvals.yaml

# 2. update the matching preamble so Aria says the same phrase
sed -i 's/"Reggie, send the truck"/"Reggie, roll the truck"/' \
  verticals/hvac/preambles.yaml

# 3. restart the core (loaded packs are read at session-start, so
#    new sessions pick up changes)
docker compose restart core

# 4. verify the eval suite still passes
cd core
.venv/Scripts/python.exe -m pytest tests/eval -q
```

### From Claude Code

```
"In the HVAC vertical pack, change the approval phrase for the
dispatch_truck tool to 'Reggie, roll the truck'. Update both
verticals/hvac/approvals.yaml and verticals/hvac/preambles.yaml so
they stay in sync, then run the HVAC eval suite to make sure
nothing broke."
```

That single prompt is a complete operator change. Claude Code:
1. reads both files,
2. makes the matching edit,
3. runs `make test-eval`,
4. reports pass/fail.

---

# 11. Add a brand-new tool to the HVAC pack

> *We want a new read-only tool: `tech_availability(date)` that returns
> which techs are off, on call, etc.*

### The story

A developer task. Add a new tool to the HVAC pack and verify it works
end-to-end without modifying the platform.

### In the cockpit

Cockpit doesn't expose this. Developer flow only.

### From the terminal

Three files to touch:

```bash
# 1. add the handler + Tool descriptor in verticals/hvac/tools.py
#    (open in your editor — example below)

# 2. (optional) add a preamble in verticals/hvac/preambles.yaml

# 3. write a unit test in core/tests/test_hvac_tools.py

# verify
cd core
.venv/Scripts/python.exe -m pytest tests/test_hvac_tools.py -v
```

Example diff for `verticals/hvac/tools.py`:

```python
async def tech_availability_handler(req, _ctx):
    state = sandbox.load_state()
    date = str(req.args.get("date", ""))
    out = []
    for tech in {j.get("tech_id") for j in state.jobs}:
        jobs_today = [j for j in state.jobs if j.get("tech_id") == tech and j["scheduled_at"][:10] == date]
        out.append({"tech_id": tech, "scheduled_count": len(jobs_today)})
    return {"date": date, "availability": out}

TOOLS = [
    # ... existing tools ...
    Tool(
        name="tech_availability",
        description="Show how busy each tech is on a given date.",
        schema={
            "type": "object",
            "properties": {"date": {"type": "string", "description": "ISO date YYYY-MM-DD"}},
            "required": ["date"],
        },
        blast_radius="read",
        handler=tech_availability_handler,
    ),
]
```

Then the prompt in `verticals/hvac/prompt.md` can mention the new tool
under "Tool guidance":

```markdown
- `tech_availability` to show how loaded a given day is across techs.
```

Restart the core; the next session picks up the new tool registry.

### From Claude Code

```
"Add a new read-only tool to the HVAC vertical pack called
'tech_availability' that takes a date parameter and returns a list
of {tech_id, scheduled_count} for that date. Update tools.py with
the handler and Tool descriptor, add a preamble 'Checking who's
free that day' in preambles.yaml, mention it in prompt.md, and
write a unit test that exercises it against the fixture data.
Run the test suite to confirm everything passes."
```

This single prompt is a small but realistic feature. Claude Code:
1. Reads existing `tools.py` to understand the patterns,
2. Reads `sandbox.py` to understand the data,
3. Adds the handler + Tool entry,
4. Updates `preambles.yaml` and `prompt.md`,
5. Writes a pytest test,
6. Runs `pytest`,
7. Reports success.

---

# 12. Switch the active vertical

> *Same deployment, two verticals. By time of day, route to a different
> one.*

### The story

The same operator runs an HVAC business and (later) a moonlighting
real-estate brokerage. They have two Twilio numbers, each routed to a
different vertical.

### In the cockpit

When starting a browser session, the operator can pick a vertical
in the URL or via the talk page. v1 hardcodes `vertical=hvac` in the
talk page; for multi-vertical setups, you'd parameterize that.

### From the terminal

Phone-number → vertical mapping is in `.env`:

```bash
# .env
PHONE_VERTICAL_MAP=+15125550150=hvac,+15125550151=realestate
```

Restart the edge so it re-reads the env:

```bash
docker compose restart edge
```

To explicitly create a session against a specific vertical via REST:

```bash
curl -s -X POST http://localhost:8000/v1/sessions \
  -H 'content-type: application/json' \
  -d '{"surface":"browser","vertical":"realestate"}' | jq
```

### From Claude Code

```
"Add a new vertical called 'realestate' to verticals/realestate/.
The persona is 'Aria the broker assistant'. Add three read-only
tools: listing_lookup, broker_calendar, contact_lookup — backed by
JSON fixtures like the HVAC pack. Add one dangerous tool:
schedule_showing with the approval phrase 'Reggie, book it'. Write
five eval scenarios. Stub the data fixtures with realistic-looking
sample rows. Confirm the pack loader accepts the new vertical and
that all evals pass."
```

That's a substantial scaffold prompt. Claude Code mirrors the HVAC
pack's structure. Expect 10-15 minutes of work delivered in one
go.

---

# 13. Investigate a regression after a change

> *After a tweak to the HVAC prompt, one of the eval scenarios starts
> failing. Track down what changed.*

### The story

A non-engineer edited `verticals/hvac/prompt.md` to make Aria
"more concise." The next CI run shows
`schedule_move_approved` failing.

### In the cockpit

Cockpit doesn't help here directly. Use the eval harness +
operator scripts.

### From the terminal

```bash
# 1. run the failing scenario verbosely
cd core
.venv/Scripts/python.exe -m pytest \
  tests/eval/test_hvac_scenarios.py::test_scenario_passes[02_schedule_move_approved] \
  -v -s

# 2. inspect the specific scenario file
cat ../verticals/hvac/scenarios/02_schedule_move_approved.yaml

# 3. inspect what tools the eval expected vs. what fired
#    (the test failure message lists missing expected_tool_calls)

# 4. roll back the prompt change to confirm causation
git diff HEAD~1 verticals/hvac/prompt.md
git checkout HEAD~1 -- verticals/hvac/prompt.md
.venv/Scripts/python.exe -m pytest tests/eval -k schedule_move_approved -v

# 5. if rollback fixes it, the prompt change is the cause
git diff verticals/hvac/prompt.md
```

### From Claude Code

```
"The 02_schedule_move_approved eval scenario is failing on main.
Diagnose why: run the failing test with -v -s, read the scenario
yaml, read the current prompt.md, and identify the cause. If it's
a prompt regression, propose a minimal edit that keeps the
'be concise' intent but restores the failing behavior. Don't
commit — just show me the proposed diff."
```

Claude Code:
1. Runs `pytest -v -s` and captures the failure.
2. Reads the scenario YAML to understand what was expected.
3. Reads the prompt to find what changed.
4. Proposes a fix and shows the diff for human review.

---

## Appendix — common command quick-reference

### Cockpit URLs

| URL | What it shows |
|---|---|
| `/` | Live talk surface (one button: Talk / Stop) |
| `/approvals` | Pending approval queue |
| `/conversations` | List of recent conversations |
| `/conversations/<id>` | Trace + turns for one conversation |

### Terminal one-liners

```bash
# health checks
curl -s http://localhost:8000/healthz | jq
curl -s http://localhost:8080/healthz | jq

# list recent conversations
curl -s http://localhost:8000/v1/conversations?limit=10 | jq

# pending approvals across all sessions
curl -s http://localhost:8000/v1/approvals | jq

# end an active session early
curl -s -X POST http://localhost:8000/v1/sessions/<id>/end

# tail logs live
docker compose logs -f core edge

# run a specific eval
cd core && .venv/Scripts/python.exe -m pytest tests/eval -k <name>

# rebuild + redeploy
docker compose build && docker compose up -d
```

### Make targets

| Target | Effect |
|---|---|
| `make dev` | docker compose up (foreground) |
| `make up` / `make down` | start / stop the stack |
| `make ps` | container status |
| `make logs` | follow all logs |
| `make migrate` | run alembic upgrade head |
| `make seed-hvac` | load HVAC fixtures |
| `make tunnel` | expose edge port via cloudflared |
| `make test` | full suite (core + edge + evals) |
| `make test-eval` | scenario evals only |
| `make replay CONV=<uuid>` | text replay of a conversation |
| `make trace CONV=<uuid>` | trace event timeline |

### Claude Code prompt patterns

These work well as starting points:

> *"Show me X about the conversation store. Group by Y."* — analytics
> queries against `app.conversations`/`turns`/`tool_calls`/`approvals`.

> *"Add a new \[tool|guardrail|approval phrase|vertical] to the HVAC
> pack. Make sure tests pass."* — config / minor feature work.

> *"Diagnose why scenario X is failing."* — eval-driven debugging.

> *"Watch the live trace for the next N minutes and alert me on Y."* —
> live observability.

> *"Compare what the agent committed to with what actually happened."* —
> postmortem / quality auditing.

The pattern that doesn't work: *"answer this incoming call"* — that's
the runtime, not a Claude Code task. The runtime is the cockpit + edge
+ core; Claude Code is for everything around it.

---

## Where to read next

- For the underlying mechanics: [concepts/voice-agents.md](concepts/voice-agents.md).
- For how approvals work in detail: [concepts/guardrails-approvals.md](concepts/guardrails-approvals.md).
- For the data model behind these queries: [concepts/realtime-conversations.md](concepts/realtime-conversations.md).
- For the operations runbook: [ops.md](ops.md).
