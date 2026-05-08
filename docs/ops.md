# Operations runbook

Common failure modes and recovery procedures for the Voice Operations
Cockpit.

## Stuck approvals

A pending approval that is never resolved blocks the agent's tool call
indefinitely (until the configured timeout fires — default 60 s).

**Symptoms:**
- Caller hears silence after Aria says the preamble.
- Cockpit Approvals tab shows a pending row that doesn't move.

**Resolution:**
1. Approve or deny in the cockpit Approvals tab.
2. If the cockpit is unreachable, the approval times out automatically
   and the tool call is marked `denied` with `decided_via=auto`.
3. If timeouts are firing too often, increase the timeout in the
   vertical's `approvals.yaml` for the affected tool.

**Root cause checks:**
- Redis pub/sub down → `make logs` will show
  `approval_publish_failed`.
- Cockpit not subscribed → check the browser console; the Approvals
  page polls every 1 s as a fallback.

## OpenAI rate limits

OpenAI Realtime sessions are rate-limited per API key. Symptoms:
- Edge logs `openai_realtime_error` with HTTP 429.
- New sessions fail to open; existing sessions continue.

**Resolution:**
1. Check the OpenAI dashboard for current usage.
2. Limit concurrent sessions on the edge (env var `EDGE_MAX_SESSIONS`).
3. Consider an org with higher tier for production.

## Twilio webhook signing failures

If the edge logs `twilio_signature_invalid`, the Twilio webhook
signature did not match.

**Resolution:**
- Verify `TWILIO_AUTH_TOKEN` matches the account's auth token.
- Verify `PUBLIC_BASE_URL` matches the URL Twilio is calling (must
  include scheme and host, no trailing slash).
- If you're using a tunnel (`make tunnel`), make sure the public URL
  in your Twilio number's voice webhook matches the current tunnel URL
  (these change every restart unless you have a named tunnel).

## Postgres recovery

`docker volume` removal is the only destructive recovery path for v1.
If migrations are out of sync:

```
make down
docker volume rm gpt-realtime-2_openai_postgres-data
make up
make migrate
make seed-hvac
```

This destroys all conversation history. For production, set up
`pg_dump` backups outside of this guide.

## Edge ↔ core connection lost

If the core restarts, active edge sessions don't auto-reconnect to the
per-session WebSocket — they will still serve audio (the OpenAI WS is
held by the edge), but trace + transcript pushes to the cockpit will
stop until the next session.

Restart edge after restarting core in production:

```
docker compose restart edge
```

## Voice-intent classifier accuracy

If approval-by-voice misses obvious phrases:
- The v1 classifier requires an *exact* phrase match (case-insensitive,
  whitespace-trimmed). Verify the dispatcher is saying the configured
  phrase exactly as written in `approvals.yaml`.
- Phone audio quality is lower than browser audio. If accuracy gets
  unacceptable, fall back to cockpit-click resolution.

## Disk usage

Trace events and tool call rows accumulate over time. There is no
automatic retention in v1. Monitor `app.trace_events` size; consider:

```sql
DELETE FROM app.trace_events WHERE ts < now() - interval '30 days';
DELETE FROM app.conversations WHERE ended_at < now() - interval '90 days';
```

(Cascades clean up dependent rows.)

## "make seed-hvac" fails on Windows

The script is a bash script. On Windows, run via Git Bash or WSL.
Alternatively, manually copy `verticals/hvac/fixtures/*.json` to
`data/hvac/`.
