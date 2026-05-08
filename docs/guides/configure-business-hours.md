# Configure business hours (enable voicemail overflow)

Goal: turn voicemail mode on for a vertical, so calls outside the
configured window are answered with a recorded greeting instead of
the agent.

Time: ~5 minutes. No code changes; pure operator config.

---

## Prerequisites

- The cockpit stack is running (`make up`) and you can dial the Twilio
  number successfully today (i.e. agent mode works).
- You know your operator's local timezone in IANA format
  (`America/Chicago`, `Europe/London`, `Asia/Tokyo`, etc. — see
  <https://en.wikipedia.org/wiki/List_of_tz_database_time_zones>).
- You can edit the vertical pack on disk (or via PR review).

---

## Steps

### 1. Add `voicemail` to the vertical's `modes` list

```yaml
# verticals/<your-vertical>/pack.yaml

modes:
  - realtime2
  - translate
  - voicemail        # ← add this
```

Without this, the core's `create_session` returns 400 when the edge
attempts to start a voicemail-mode session.

### 2. Declare the business window

```yaml
business_hours:
  tz: America/Chicago        # IANA timezone
  open: "09:00"              # local time, 24h
  close: "17:00"             # local time, 24h
  days: [1, 2, 3, 4, 5]      # ISO weekday: 1=Mon, 7=Sun
```

Some patterns:

```yaml
# 24/7 except Sunday
business_hours:
  tz: America/Chicago
  open: "00:00"
  close: "23:59"
  days: [1, 2, 3, 4, 5, 6]

# Overnight on-call window — open from 22:00 to 06:00
business_hours:
  tz: America/Chicago
  open: "22:00"
  close: "06:00"          # window wraps midnight
  days: [1, 2, 3, 4, 5, 6, 7]
```

Notes:
- **`days` is ISO weekday.** Monday is 1, Sunday is 7.
- **`tz` must be IANA.** On Windows containers you may need
  `tzdata` installed (the cockpit core image already includes it via
  `pyproject.toml`'s platform marker).

### 3. Write the greeting

```yaml
voicemail_greeting: voicemail.md
```

```markdown
<!-- verticals/<your-vertical>/voicemail.md -->
You've reached the after-hours line. Our office is closed right now.
Please leave a message after the tone — your name, the address, and
a phone number. The dispatcher will call you back when we open.
```

The text is read by Twilio's TTS (`<Say voice="alice">`). Keep it
concise — every second of greeting is a second the caller waits
before the tone.

### 4. Restart the core

```bash
docker compose restart core
```

Vertical packs are loaded on session start. A core restart guarantees
the next call sees the new config. No edge restart needed.

### 5. Verify the predicate

```bash
# Confirm the predicate sees your config
curl -s http://localhost:8000/v1/verticals/<your-vertical>/business-status | jq

# Expected fields:
# {
#   "vertical": "<name>",
#   "open": <bool>,         ← true now if you're inside the window
#   "voicemail_greeting": "<text from voicemail.md>",
#   "supports_voicemail": true,
#   "business_hours": { ... }
# }
```

If `supports_voicemail` is false, you forgot Step 1 (add `voicemail`
to `modes:`). If `voicemail_greeting` is null, the file path in
Step 3 didn't resolve — check the relative path against the pack
directory.

### 6. Verify the TwiML routing

The Twilio webhook itself can be tested without dialing a real
number — it's a regular HTTP endpoint:

```bash
# Inside business hours: agent TwiML (just <Connect><Stream>)
# Outside business hours: voicemail TwiML (<Say> then <Connect><Stream>)

curl -s -X POST http://localhost:8080/twilio/voice \
  -d "Called=+15555550100" \
  -d "From=+12145559876" \
  -d "CallSid=CA-test-1"
```

Look for either:
- agent TwiML — only `<Connect><Stream>`
- voicemail TwiML — `<Say>` + `<Connect><Stream>` with
  `<Parameter name="mode" value="voicemail"/>`

(If your edge has `TWILIO_AUTH_TOKEN` set, the signature check rejects
this curl test. Either temporarily unset it for the test, or build a
real Twilio signature — easier to dial the number.)

### 7. End-to-end test

Best done right at a window boundary so you can flip both ways:

1. Set `business_hours` so the current time is **outside** the window.
   `make tunnel` your edge.
2. Dial the Twilio number. You should hear the greeting, then a tone,
   leave a message, hang up.
3. In the cockpit, navigate to **Voicemails** (`/voicemails`). The
   call should appear within ~5 seconds.
4. Click the row. The transcript should be in the trace explorer.
5. Confirm `/data/post-call/<conversation_id>.json` exists with
   `kind: "voicemail"`.

---

## Verification checklist

- [ ] `pack.yaml` lists `voicemail` in `modes:`
- [ ] `pack.yaml` has `business_hours` with valid `tz`, `open`, `close`, `days`
- [ ] `pack.yaml` has `voicemail_greeting` pointing at a markdown file in the pack dir
- [ ] The markdown file exists and contains the spoken text
- [ ] Core was restarted after the config change
- [ ] `/v1/verticals/<name>/business-status` returns `supports_voicemail: true`
- [ ] During-hours call hits the agent; out-of-hours call hits voicemail
- [ ] Cockpit `/voicemails` lists the captured call

---

## Troubleshooting

**Symptom:** `is_open_now()` always returns true regardless of the
clock.
**Likely cause:** `business_hours` is missing or empty in
`pack.yaml`. Empty/missing config is treated as always-open by
design.
**Fix:** Add the `business_hours` block.

**Symptom:** Predicate says open=false at the wrong time.
**Likely cause:** Timezone mismatch. `is_open_now()` interprets
`tz` literally; if you wrote `Chicago` instead of `America/Chicago`
the lookup fails and you may see UTC-based behavior.
**Fix:** Use a full IANA tz name. Test with
`docker compose exec core python -c "from zoneinfo import ZoneInfo;
print(ZoneInfo('America/Chicago'))"` — if that throws, your image is
missing `tzdata`.

**Symptom:** Cockpit `/voicemails` is empty even though the call was
captured.
**Likely cause:** The conversation row didn't get `mode='voicemail'`.
This usually means the edge fell through to agent mode because
`supports_voicemail` came back false.
**Fix:** Re-check Step 1 — `voicemail` must be in `pack.yaml`'s
`modes:`.

**Symptom:** Twilio webhook returns 403 "invalid signature."
**Likely cause:** `PUBLIC_BASE_URL` no longer matches the URL Twilio
is calling (often after `make tunnel` reassigns a new public URL).
**Fix:** Update `.env`'s `PUBLIC_BASE_URL` to match the current
tunnel URL; update the Twilio number's voice webhook URL to match;
restart the edge.

---

## Where to read next

- The voicemail concept doc: [concepts/voicemail.md](../concepts/voicemail.md).
- The Twilio integration end-to-end:
  [reference/twilio-integration.md](../reference/twilio-integration.md).
- The `is_open_now()` predicate's edge cases:
  `core/tests/test_business_hours.py`.
