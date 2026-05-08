"""Phase 5 — Audit transcripts: divergence diff between the agent's
transcript and the canonical whisper transcript.

Pairs user turns by (conversation_id, role='user') ordered by ts. Each
agent turn is matched to the closest-in-time whisper turn within a
small window. The diff is a token-level edit distance normalized
against the longer of the two strings (Word Error Rate, roughly).

Divergence kinds:
    'paraphrase' — small edit distance, both texts non-empty
    'omission'   — agent has fewer words than canonical
    'addition'   — agent has more words than canonical
    'mismatch'   — large edit distance (likely hallucination)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from cockpit_core.store.turns import Turn, list_turns

# Default thresholds — tunable per deployment if needed.
DEFAULT_MATCH_WINDOW = timedelta(seconds=5)
DEFAULT_PARAPHRASE_THRESHOLD = 0.15  # WER below this is "fine paraphrasing"
DEFAULT_MISMATCH_THRESHOLD = 0.5  # WER above this is "likely hallucination"


@dataclass(frozen=True)
class Divergence:
    conversation_id: str
    agent_turn_id: str | None
    canonical_turn_id: str | None
    kind: str
    score: float
    agent_text: str | None
    canonical_text: str | None


_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _word_error_rate(a: str, b: str) -> float:
    """Levenshtein distance over tokens, normalized by max len."""
    a_toks = _tokenize(a)
    b_toks = _tokenize(b)
    if not a_toks and not b_toks:
        return 0.0
    if not a_toks or not b_toks:
        return 1.0
    n, m = len(a_toks), len(b_toks)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, m + 1):
            cur = dp[j]
            if a_toks[i - 1] == b_toks[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = cur
    distance = dp[m]
    return distance / max(n, m)


def classify_divergence(
    agent_text: str,
    canonical_text: str,
    *,
    paraphrase_threshold: float = DEFAULT_PARAPHRASE_THRESHOLD,
    mismatch_threshold: float = DEFAULT_MISMATCH_THRESHOLD,
) -> tuple[str | None, float]:
    """Returns (kind, score). kind=None means within paraphrase tolerance.

    Classification order:
      1. WER <= paraphrase_threshold     -> None (no divergence)
      2. token-count differs by > 25%    -> 'omission' or 'addition'
         (size mismatch outranks 'mismatch' because the diff is structural,
         not a hallucination)
      3. WER >= mismatch_threshold       -> 'mismatch'
      4. otherwise                        -> 'paraphrase'
    """
    score = _word_error_rate(agent_text, canonical_text)
    if score <= paraphrase_threshold:
        return None, score
    a_toks = _tokenize(agent_text)
    c_toks = _tokenize(canonical_text)
    a_n, c_n = len(a_toks), len(c_toks)
    bigger = max(a_n, c_n)
    size_diff_ratio = abs(a_n - c_n) / bigger if bigger > 0 else 0.0
    if size_diff_ratio > 0.25:
        return ("omission" if a_n < c_n else "addition"), score
    if score >= mismatch_threshold:
        return "mismatch", score
    return "paraphrase", score


def _pair_user_turns(
    turns: list[Turn],
    *,
    window: timedelta,
) -> list[tuple[Turn | None, Turn | None]]:
    """Pair agent-side user turns with canonical (whisper) user turns by
    nearest timestamp within `window`. Unmatched turns become (turn, None)
    or (None, turn).
    """
    agent = [t for t in turns if t.role == "user" and t.model != "whisper"]
    canon = [t for t in turns if t.role == "user" and t.model == "whisper"]
    pairs: list[tuple[Turn | None, Turn | None]] = []
    used_canon: set[str] = set()
    for a in agent:
        best: Turn | None = None
        best_dt: timedelta = window
        for c in canon:
            if c.id in used_canon:
                continue
            dt = abs(c.ts - a.ts)
            if dt <= best_dt:
                best, best_dt = c, dt
        if best is not None:
            used_canon.add(best.id)
            pairs.append((a, best))
        else:
            pairs.append((a, None))
    for c in canon:
        if c.id not in used_canon:
            pairs.append((None, c))
    return pairs


async def compute_divergences(
    conversation_id: str,
    *,
    paraphrase_threshold: float = DEFAULT_PARAPHRASE_THRESHOLD,
    mismatch_threshold: float = DEFAULT_MISMATCH_THRESHOLD,
    match_window: timedelta = DEFAULT_MATCH_WINDOW,
) -> list[Divergence]:
    """Compute the divergence list for one conversation. Empty if all
    paired turns are within the paraphrase tolerance."""
    turns = await list_turns(conversation_id)
    pairs = _pair_user_turns(turns, window=match_window)
    out: list[Divergence] = []
    for agent_turn, canonical_turn in pairs:
        agent_text = (agent_turn.transcript if agent_turn else "") or ""
        canonical_text = (canonical_turn.transcript if canonical_turn else "") or ""
        if not agent_text and not canonical_text:
            continue
        if agent_turn is None:
            out.append(
                Divergence(
                    conversation_id=conversation_id,
                    agent_turn_id=None,
                    canonical_turn_id=canonical_turn.id if canonical_turn else None,
                    kind="omission",
                    score=1.0,
                    agent_text=None,
                    canonical_text=canonical_text,
                )
            )
            continue
        if canonical_turn is None:
            out.append(
                Divergence(
                    conversation_id=conversation_id,
                    agent_turn_id=agent_turn.id,
                    canonical_turn_id=None,
                    kind="addition",
                    score=1.0,
                    agent_text=agent_text,
                    canonical_text=None,
                )
            )
            continue
        kind, score = classify_divergence(
            agent_text,
            canonical_text,
            paraphrase_threshold=paraphrase_threshold,
            mismatch_threshold=mismatch_threshold,
        )
        if kind is None:
            continue
        out.append(
            Divergence(
                conversation_id=conversation_id,
                agent_turn_id=agent_turn.id,
                canonical_turn_id=canonical_turn.id,
                kind=kind,
                score=score,
                agent_text=agent_text,
                canonical_text=canonical_text,
            )
        )
    return out
