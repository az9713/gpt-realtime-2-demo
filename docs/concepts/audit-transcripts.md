# Audit transcripts + divergence pipeline

> **Whisper feature 4 of 5.** Sidecar always-on for verticals that
> opt in via `pack.yaml`.
> **Where it lives:** `RealtimeSession` opens whisper in parallel at
> session start; a nightly `make audit` job diffs agent vs. canonical
> transcripts and flags divergences.

---

## What it solves

In regulated industries (telehealth, finance, anywhere subject to
audit), the question "did the agent paraphrase, omit, or hallucinate?"
isn't theoretical — it's the central compliance question. The agent's
own user-transcript output is interpretive: the model heard audio
and wrote down what *it* thought the user said. That's not the same
as a verbatim ground-truth recording.

Audit-flagged verticals run **two transcription models in parallel**:

- `gpt-realtime-2` (or `gpt-realtime-translate`) — the agent, doing
  its job, transcribing as a side effect.
- `gpt-realtime-whisper` — pure transcription, the canonical record.

A nightly diff job compares them per turn and flags every place they
disagreed materially. The result is a queryable trail of "the agent's
view vs. the source of truth."

---

## When does it activate

A single per-vertical knob:

```yaml
# verticals/<name>/pack.yaml
audit_transcripts: true     # default: false
```

When true:

- `CreateSessionResponse.audit_transcripts` is true.
- `RealtimeSession` is constructed with `auditTranscripts: true`.
- `RealtimeSession.shouldHaveSidecar()` returns true unconditionally.
- The sidecar opens **at session start in parallel** with the primary
  WS — `Promise.all([primary.open(), sidecar.open()])` — not lazily.

Why parallel and not lazy: for translate-mode bilingual capture, lazy
opening hides latency behind the user's first utterance; for audit,
*completeness* matters more than first-response p50. We pay the
~200 ms sidecar setup cost up front so we don't risk losing the first
turn's canonical transcript.

HVAC defaults to `audit_transcripts: false`. The setting is intended
for verticals like a hypothetical telehealth pack where audit is
mandatory.

---

## How a turn is paired

The diff is per-pair, not per-conversation. Pairing logic
(`core/src/cockpit_core/observability/audit.py: _pair_user_turns`):

```
Given a conversation's turns:

  turns where role='user' AND model != 'whisper'   → "agent" stream
  turns where role='user' AND model == 'whisper'   → "canonical" stream

For each agent turn, find the canonical turn closest in timestamp
within a 5-second window. Pair them.

Unmatched agent turn → 'addition' divergence (agent imagined
                                                an utterance)
Unmatched canonical turn → 'omission' divergence (agent missed an
                                                    utterance)
```

The 5-second window handles the small skew between the two models'
end-of-utterance detection. Wider windows risk false pairings; tighter
windows risk missed pairings on noisy audio.

---

## How a divergence is classified

Once an agent turn is paired with a canonical turn,
`classify_divergence()` runs:

1. Tokenize both transcripts (whitespace + punctuation stripped, lowercased).
2. Compute Levenshtein edit distance over tokens, normalized by max
   length. This is roughly **Word Error Rate (WER)**.
3. Branch on:

```
If WER ≤ 0.15 (paraphrase_threshold)  → no divergence (return None)
Else if |a_tokens - c_tokens| / max > 0.25  → 'omission' or 'addition'
                                              (structural size diff)
Else if WER ≥ 0.50 (mismatch_threshold)  → 'mismatch' (likely hallucination)
Else  → 'paraphrase' (worth flagging but not alarming)
```

Order matters: size-mismatch is checked **before** mismatch because a
big size difference is a structural diff, not a hallucination — even
if WER is high, the right kind is "the agent left out half the
sentence" not "the agent made it up."

Thresholds are tunable per call site in
`compute_divergences(paraphrase_threshold=…, mismatch_threshold=…)`.

---

## What gets persisted

Migration 0003 adds `app.audit_divergences`:

```sql
audit_divergences (
  id                   uuid pk,
  conversation_id      uuid fk,
  agent_turn_id        uuid,        -- nullable for omissions
  canonical_turn_id    uuid,        -- nullable for additions
  kind                 text,        -- paraphrase|omission|addition|mismatch
  score                numeric(5,4),
  agent_text           text,
  canonical_text       text,
  flagged_at           timestamptz default now()
)
```

The runner script writes one row per detected divergence. The
cockpit's `/audit` page lists them; clicking a row jumps to the
conversation's trace explorer.

---

## The runner

```bash
# Default: scan the last 24 hours
make audit

# Custom window
python scripts/audit-divergences.py --hours 72

# Restrict to specific verticals
python scripts/audit-divergences.py --vertical telehealth --hours 168
```

The script:

1. Builds a list of audit-flagged verticals (those with
   `pack.audit_transcripts == true`).
2. Pulls recent conversations from `app.conversations` filtered to
   those verticals + the time window.
3. For each, calls `compute_divergences(conversation_id)`.
4. Persists each divergence to `app.audit_divergences`.
5. Prints a per-conversation count and a grand total.

It's idempotent across reruns only in the sense that re-scanning the
same conversation will produce duplicate rows — there's no UPSERT.
Production deployments should cron-run it once per day with a window
that doesn't overlap previous runs (or add a uniqueness constraint
in a future migration if reruns become a habit).

---

## What the cockpit shows

`/audit` page (`frontend/src/audit/AuditListPage.tsx`):

```
Audit divergences
──────────────────

[OMISSION]  WER 0.42                                      conv 1210e2ab  May 8, 11:14 AM

  Agent transcript                       Canonical (whisper)
  ───────────────                        ───────────────────
  Hi, I need a capacitor                 Hi, I need a 440 volt capacitor
                                         for a Carrier 58STA — also can
                                         you check warranty on serial
                                         U-LENN-993301?

[MISMATCH]  WER 0.71                                       conv 84a0c4d1  May 8, 09:02 AM

  Agent transcript                       Canonical (whisper)
  ───────────────                        ───────────────────
  Yes that should be fine                Actually I'd rather wait until
                                         my husband gets home
```

Color coding:
- `paraphrase` → slate (informational; tune your threshold if you see
  too many of these)
- `omission` / `addition` → amber (the agent literally heard a
  different number of words)
- `mismatch` → rose (likely hallucination — investigate)

---

## Cost

Whisper sidecars double the audio-input cost while running. For
verticals where audit is mandatory, that's the cost of doing
business. For HVAC and similar non-regulated verticals, leave
`audit_transcripts: false` and incur zero whisper cost.

A typical 5-minute conversation at GA pricing is roughly $0.10-$0.20
in additional whisper input cost.

---

## Operating notes

- **Tuning thresholds.** The defaults (paraphrase 0.15, mismatch 0.50)
  err on the side of flagging. If you see a flood of false-positive
  paraphrases, raise paraphrase to 0.25. Don't lower mismatch — false
  negatives there hide real problems.
- **The runner doesn't enforce uniqueness.** Re-running on overlapping
  windows duplicates rows. Schedule it once per day with a
  non-overlapping window in cron.
- **Sidecar errors don't kill sessions.** If whisper drops mid-call,
  the primary session keeps going. The audit data for that
  conversation will be incomplete; the cockpit shows that as
  unmatched-turns divergences (omissions on the agent side).
- **PII redaction still applies.** The PIIRedactor runs on agent
  transcripts before persistence. Whisper transcripts are persisted
  raw — they're the canonical record — and redacted at read time when
  needed. Consult your compliance officer.

---

## Eval coverage

`core/tests/test_audit.py` — 9 tests covering identical strings,
paraphrase tolerance, omission/addition classification, mismatch
threshold, paired/unmatched turn handling, clean-pair empty result.

## Where to read next

- The whisper sidecar machinery: [reference/realtime-models-in-use.md](../reference/realtime-models-in-use.md).
- The bilingual capture feature (the same sidecar plumbing in lazy mode):
  [concepts/translate-mode.md](translate-mode.md).
- The conversation store: [concepts/realtime-conversations.md](realtime-conversations.md).
