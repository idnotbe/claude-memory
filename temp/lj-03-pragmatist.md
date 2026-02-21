# LLM-as-Judge: Pragmatist Feasibility Analysis

**Date:** 2026-02-20
**Author:** pragmatist
**Status:** COMPLETE -- feasibility assessment with ranked implementation options
**Method:** Code reading of all hook scripts, hooks.json, SKILL.md, plugin.json; analysis of hook execution model; latency/cost estimation from Anthropic API characteristics

---

## Executive Summary

The architect's proposal (Option C: Inline API Judge via `urllib.request`) is **technically feasible and the most practical approach**. However, the pragmatist's analysis reveals important nuances that the architect's proposal either underweights or misses:

1. **The dual verification (2 calls) is over-engineered for a v1.** A single batch judge achieves ~85-90% precision at half the latency and cost. Start there.
2. **The 10-second hook timeout is tight.** Two sequential haiku calls at P95 latency could hit 6-8 seconds. Combined with FTS5 BM25 processing (~50-100ms), edge cases can timeout.
3. **`urllib.request` works but has sharp edges** (no connection pooling, SSL handshake per call, no HTTP/2). These matter more for dual calls than single.
4. **The `ANTHROPIC_API_KEY` is NOT guaranteed to be in the hook environment.** Claude Code may use a session-scoped token, OAuth flow, or internal routing. This needs investigation.
5. **Threading could parallelize dual calls** (stdlib `concurrent.futures.ThreadPoolExecutor`), cutting latency from 2x sequential to ~1.1x. But added complexity.

**Recommendation:** Implement single batch judge first (Option G variant). Add dual verification as a config-gated upgrade after measuring single-judge precision. This is the fastest path to value with the lowest risk.

---

## Table of Contents

1. [Hook Execution Model: Deep Analysis](#1-hook-execution-model-deep-analysis)
2. [The API Key Question](#2-the-api-key-question)
3. [Implementation Options Ranked](#3-implementation-options-ranked)
4. [Latency Analysis](#4-latency-analysis)
5. [urllib.request: Practical Gotchas](#5-urllibrequest-practical-gotchas)
6. [Code Sketches](#6-code-sketches)
7. [Test Strategy](#7-test-strategy)
8. [The Subagent Impossibility: Confirmed](#8-the-subagent-impossibility-confirmed)
9. [Alternative: Skill-Based Judge (On-Demand Only)](#9-alternative-skill-based-judge-on-demand-only)
10. [Risk Assessment](#10-risk-assessment)
11. [Recommendation](#11-recommendation)

---

## 1. Hook Execution Model: Deep Analysis

### What hooks.json tells us

```json
"UserPromptSubmit": [{
  "matcher": "*",
  "hooks": [{
    "type": "command",
    "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
    "timeout": 10,
    "statusMessage": "Retrieving relevant memories..."
  }]
}]
```

Key facts from code reading:

1. **Type is `"command"`** -- this runs a subprocess. The Python script is a standalone process.
2. **Timeout is 10 seconds** -- after 10s, Claude Code kills the process and discards output.
3. **`statusMessage`** is shown to the user while the hook runs -- the user sees "Retrieving relevant memories..." as a spinner.
4. **Input:** `memory_retrieve.py` reads `sys.stdin` (line 211-216) to get `hook_input` JSON containing `user_prompt` and `cwd`.
5. **Output:** Whatever the script writes to `stdout` is injected into Claude's context (lines 385-394).
6. **Exit code 0 = inject, non-zero = discard** (implied by the `sys.exit(0)` pattern throughout).

### What the script has access to

From reading `memory_retrieve.py`:
- **Environment variables:** `os.environ` (full user environment)
- **File system:** Full access (reads index.md, config JSON, memory JSONs)
- **Network:** Unrestricted (Python stdlib networking available)
- **No Claude Code tools:** Cannot call Task, Read, Write, Bash, etc.

### Critical constraints for LLM-as-judge

| Constraint | Impact | Severity |
|------------|--------|----------|
| 10-second timeout | Must complete BM25 + LLM call(s) in <10s | HIGH |
| Subprocess execution | No access to Task tool or agent context | BLOCKING for Task-based approach |
| User sees spinner | Long delays degrade UX ("Retrieving relevant memories..." for 3-5s) | MEDIUM |
| Exit code semantics | Must exit 0 to inject; non-zero = discard everything | LOW (design around it) |
| No streaming | `urllib.request` waits for full response | LOW (haiku responses are small) |

### Comparison: Stop hook (memory_triage.py)

The Stop hook has `"timeout": 30` (3x more budget) and is more complex:
- Reads stdin with `select()` timeout (lines 179-208)
- Parses JSONL transcript files
- Writes context files to `.staging/`
- Outputs JSON decision `{"decision": "block", "reason": "..."}`

The retrieval hook is simpler (no transcript parsing, no file writing) but has a tighter timeout budget. This means LLM calls must be fast.

---

## 2. The API Key Question

### The CRITICAL unknown

The architect assumes `ANTHROPIC_API_KEY` is available in the hook environment:

```python
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    return None  # Graceful fallback
```

**But is it actually there?**

Claude Code's API authentication may work differently:
1. **Direct API key:** User sets `ANTHROPIC_API_KEY` in their shell. Hook inherits it. **This works.**
2. **OAuth/session token:** Claude Code may use OAuth or session-based auth that isn't a simple API key. **This would NOT be available as `ANTHROPIC_API_KEY`.**
3. **Internal routing:** Claude Code might proxy through an internal endpoint, not `api.anthropic.com`. **Hook can't use the same endpoint.**
4. **Claude Max/Team accounts:** May use different auth mechanisms entirely.

### Practical assessment

For users who set `ANTHROPIC_API_KEY` in their shell profile (most developers using Claude Code directly), the key WILL be available. The `os.environ` inheritance from the parent process (Claude Code) should pass it through.

For users on managed deployments (Claude Max, enterprise), this is uncertain.

### Mitigation

The architect's fallback design (judge disabled when no API key) is correct. But the documentation should explicitly state:

> LLM-as-judge requires `ANTHROPIC_API_KEY` to be set in your shell environment. If you use Claude Code via OAuth or managed deployment, the judge feature may not be available.

**Feasibility impact:** Medium. For the target user base (developers with API keys), this works. The fallback to BM25-only is safe.

---

## 3. Implementation Options Ranked

### Option G (RECOMMENDED): Single Batch Judge

**Description:** One `urllib.request` call to haiku with all BM25 candidates. LLM returns which are relevant.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **9/10** | Simplest LLM approach, stdlib only |
| Precision | ~85-90% | Single judge, batch evaluation |
| Latency | 0.8-2.0s | Single API call |
| Cost | $1.68/month (100/day) | 1 haiku call per prompt |
| LOC estimate | ~120 LOC | API client + judge prompt + parser + integration |
| Dependencies | None (stdlib) | urllib.request, json, ssl |
| Reliability | HIGH | Single call = fewer failure modes |

**Pros:**
- Simplest path to value
- Half the latency of dual verification
- Half the cost
- Fewer failure modes (one call vs two)
- Position bias manageable with shuffling
- Can upgrade to dual later

**Cons:**
- No dual verification (user requirement: "check twice independently")
- ~85-90% precision vs ~95-98% for dual
- Single point of failure per call

**LOC breakdown:**
- `call_anthropic_api()`: ~40 LOC
- `JUDGE_BATCH_SYSTEM`: ~15 LOC (single combined prompt)
- `format_judge_input()`: ~20 LOC
- `parse_judge_response()`: ~25 LOC
- Integration in `main()`: ~20 LOC

### Option C: Inline Dual Judge (Architect's Recommendation)

**Description:** Two sequential `urllib.request` calls (relevance + usefulness).

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **7/10** | Works but latency is tight |
| Precision | ~95-98% | Dual verification, different perspectives |
| Latency | 1.6-4.0s (sequential), 0.9-2.5s (threaded) | Two API calls |
| Cost | $3.36/month (100/day) | 2 haiku calls per prompt |
| LOC estimate | ~190 LOC | As architect proposed |
| Dependencies | None (stdlib) | urllib.request + optional concurrent.futures |
| Reliability | MEDIUM-HIGH | Partial failure handling adds complexity |

**Pros:**
- Highest precision
- Meets "check twice" requirement
- Different perspectives catch different failure modes

**Cons:**
- 2x latency (sequential) or threading complexity (parallel)
- Partial failure handling (what if one judge fails?) adds ~30 LOC
- 2x cost
- Over-engineered for v1 without measured baseline precision

### Option C-threaded: Inline Dual Judge with Threading

**Description:** Same as C but uses `concurrent.futures.ThreadPoolExecutor` to parallelize the two calls.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **6/10** | Works but adds threading complexity |
| Precision | ~95-98% | Same as C |
| Latency | 0.9-2.5s | ~max(call1, call2) instead of sum |
| Cost | $3.36/month | Same as C |
| LOC estimate | ~220 LOC | C + threading boilerplate |
| Dependencies | None (stdlib) | concurrent.futures |
| Reliability | MEDIUM | Thread lifecycle + partial failure |

**Pros:**
- Latency nearly as good as single call
- True independence between judges

**Cons:**
- Threading in a short-lived subprocess (threads must finish before process exits)
- Thread exception handling is less obvious
- More complex testing (need to mock concurrent API calls)

### Option D: stdlib urllib with Raw HTTP

**Description:** Direct HTTP call using urllib, minimal wrapper. Single yes/no per candidate.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **8/10** | Slightly simpler than batch |
| Precision | ~80-85% | Binary classification per-candidate loses nuance |
| Latency | 0.8-2.0s | Single API call |
| Cost | $1.68/month | Same as G |
| LOC estimate | ~100 LOC | Minimal wrapper |
| Dependencies | None | stdlib |
| Reliability | HIGH | Simple |

**Pros:**
- Simplest possible approach
- Easy to understand and test

**Cons:**
- Lower precision than batch (no relative comparison between candidates)
- Per-candidate yes/no is less nuanced than "which of these are relevant"

### Option B: Hook Outputs Candidates, Skill Judges

**Description:** Hook outputs all BM25 candidates as a "candidate list" in a special format. A SKILL (SKILL.md) orchestration reads them and uses Task subagent to judge.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **3/10** | Requires agent cooperation, breaks auto-inject |
| Precision | ~90-95% | Task subagent judgment is high quality |
| Latency | 5-15s | Agent must process, spawn Task, collect results |
| Cost | Variable | Task subagent cost |
| LOC estimate | ~150 LOC hook + ~100 LOC skill | Two components |
| Dependencies | None | But requires SKILL.md changes |
| Reliability | LOW | Agent may not cooperate, timing unpredictable |

**Pros:**
- Task subagent has access to conversation context
- Better judgment quality (full agent capabilities)

**Cons:**
- **Breaks auto-inject:** The hook's purpose is automatic injection. If it requires agent cooperation, it's no longer automatic.
- **Timing:** Hook output goes into context. Agent processes it... eventually. There's no guarantee the agent will run the judge skill before continuing.
- **UX:** User sees candidate list in context, then later sees filtered results. Confusing.
- **The hook CAN'T request agent actions.** Hook stdout is injected as context, not as an instruction to Claude. Claude might or might not act on it.

### Option E: Move ALL Retrieval to Skill

**Description:** Remove the UserPromptSubmit hook entirely. All retrieval happens via `/memory:search` skill.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **2/10** | Destroys core feature (auto-inject) |
| Precision | ~95-100% | Claude judges everything manually |
| Latency | N/A | User must explicitly trigger |
| Cost | Variable | Per-search cost |
| LOC estimate | ~80 LOC | Simpler than hooks |
| Dependencies | None | |
| Reliability | LOW | Users forget to search; defeats purpose |

**Pros:**
- Maximum precision (Claude judges everything)
- No network dependency in hook

**Cons:**
- **Destroys the core value proposition.** The whole point of auto-inject is "memories appear when relevant without user action."
- Users must remember to search. They won't.
- Claude-mem comparison research showed that on-demand-only retrieval has poor adoption.

### Option F: No LLM, Aggressive BM25

**Description:** No LLM. Use very tight BM25 thresholds.

| Dimension | Rating | Notes |
|-----------|--------|-------|
| **Feasibility** | **10/10** | Already being built (rd-08) |
| Precision | ~65-75% | BM25 ceiling |
| Latency | <50ms | No API call |
| Cost | $0 | |
| LOC estimate | 0 (already in plan) | |
| Dependencies | None | |
| Reliability | HIGHEST | No external deps |

**Verdict:** This is the baseline. The user explicitly requires higher precision.

### Ranking

| Rank | Option | Feasibility | Precision | Recommended? |
|------|--------|-------------|-----------|-------------|
| 1 | **G: Single Batch** | 9/10 | ~85-90% | **YES (v1)** |
| 2 | C: Dual Sequential | 7/10 | ~95-98% | v2 upgrade |
| 3 | C-threaded: Dual Parallel | 6/10 | ~95-98% | v2 alternative |
| 4 | D: Per-candidate Yes/No | 8/10 | ~80-85% | Viable but less precise |
| 5 | F: No LLM | 10/10 | ~65-75% | Baseline only |
| 6 | B: Hook + Skill | 3/10 | ~90-95% | Not recommended |
| 7 | E: Skill-only | 2/10 | ~95-100% | Not recommended |

---

## 4. Latency Analysis

### Haiku API Call Latency (Empirical Estimates)

Based on Anthropic API characteristics for `claude-haiku-4-5-20251001`:

| Metric | Value | Notes |
|--------|-------|-------|
| TTFB (time to first byte) | 200-500ms | Network + model initialization |
| Generation speed | ~100-200 tokens/sec | Haiku is fast |
| Total for 30-token output | 150-300ms generation | After TTFB |
| **Total wall clock** | **500-1500ms** | TTFB + generation + network overhead |
| P95 | ~2000ms | Slow network, API load, cold start |
| P99 | ~3000ms | Worst case before timeout |

### Full Pipeline Latency Budget (10s timeout)

**Single judge (Option G):**
```
BM25 retrieval:     50-100ms
Judge API call:     500-1500ms (P50), 2000ms (P95)
Response parsing:   5ms
Output formatting:  5ms
---
Total P50:          560-1610ms
Total P95:          ~2100ms
Margin to timeout:  ~8 seconds at P50, ~8 seconds at P95
```
**Verdict: Comfortable.** Single call easily fits within 10s timeout.

**Dual judge sequential (Option C):**
```
BM25 retrieval:     50-100ms
Judge call 1:       500-1500ms (P50), 2000ms (P95)
Judge call 2:       500-1500ms (P50), 2000ms (P95)
Response parsing:   10ms
Output formatting:  5ms
---
Total P50:          1065-3610ms
Total P95:          ~4100ms
Margin to timeout:  ~6 seconds at P50, ~6 seconds at P95
```
**Verdict: Acceptable** at P50, but P95 is getting close to the "user perceives as slow" threshold (~3 seconds).

**Dual judge threaded (Option C-threaded):**
```
BM25 retrieval:     50-100ms
Both judge calls:   max(call1, call2) = 500-1500ms (P50), 2000ms (P95)
Response parsing:   10ms
Output formatting:  5ms
Thread overhead:    20-50ms
---
Total P50:          585-1665ms
Total P95:          ~2080ms
```
**Verdict: Nearly as fast as single call.** Threading is worth it IF dual verification is desired.

### UX Impact of Latency

The `statusMessage: "Retrieving relevant memories..."` spinner is visible to the user. Current latency (~50ms) means the spinner barely flashes. With LLM judge:

| Duration | User Perception |
|----------|----------------|
| <500ms | Imperceptible |
| 500ms-1.5s | Noticeable but acceptable |
| 1.5-3s | Feels slow but tolerable |
| 3-5s | Feels broken ("why is it loading?") |
| >5s | User considers disabling the feature |

**Single judge P50 (~1s) is in the "acceptable" zone. Dual sequential P50 (~2-3s) is borderline.** This is a strong argument for starting with single judge.

---

## 5. urllib.request: Practical Gotchas

### SSL/TLS

```python
# urllib.request uses ssl module for HTTPS
# On most systems, this works out of the box with system CA certificates.
# BUT: on some stripped-down Docker images or custom Python builds, SSL verification may fail.
# WSL2 (this project's platform) has full SSL support -- no issue.
```

**Gotcha:** No concern for WSL2/standard Linux. Potential issue on exotic deployments.

### No Connection Pooling

`urllib.request.urlopen()` creates a new TCP connection per call. For dual verification:
- Call 1: TCP handshake + TLS handshake + request + response (~overhead: 50-100ms)
- Call 2: Another TCP handshake + TLS handshake + request + response (~overhead: 50-100ms)

This adds ~50-100ms per call that a connection-pooling library (httpx, requests) would avoid.

**Impact:** Minor. 100ms is negligible compared to ~800ms API latency.

### Timeout Behavior

```python
# urllib.request timeout applies to EACH socket operation, not total time.
# A slow response that trickles data byte-by-byte could exceed the logical timeout.
urllib.request.urlopen(req, timeout=3.0)
```

For haiku's small response (~30 tokens), the response arrives in a single read. This is not a practical concern.

**Better pattern:** Use a wall-clock timeout wrapper:

```python
import signal

def timeout_wrapper(func, timeout_seconds):
    """Wall-clock timeout using SIGALRM (Unix only)."""
    def handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {timeout_seconds}s")
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout_seconds)
    try:
        return func()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
```

**Note:** `signal.alarm` only works in the main thread and only on Unix. Since the hook script is a single-threaded subprocess on Linux (WSL2), this works perfectly. But if threading is used for dual verification, `signal.alarm` can only be set from the main thread -- the threaded approach would need `concurrent.futures` timeout instead.

### Response Size

Haiku judge response is ~30 tokens of JSON. At ~4 bytes/token, that's ~120 bytes. No chunked encoding issues, no memory concerns.

### Error Handling

The architect's exception list is correct:
```python
except (
    urllib.error.URLError,      # Network unreachable, DNS failure
    urllib.error.HTTPError,     # 4xx/5xx responses (rate limit, auth error)
    json.JSONDecodeError,       # Malformed API response
    TimeoutError,               # Socket timeout
    OSError,                    # Low-level I/O
    KeyError,                   # Unexpected response shape
    IndexError,                 # Empty content blocks
):
    pass
```

**Additional edge case:** `ssl.SSLError` (certificate issues). This is a subclass of `OSError`, so already caught.

**Rate limiting:** The Anthropic API returns `429 Too Many Requests` with a `Retry-After` header. `urllib.error.HTTPError` catches this. In a hook context, retrying is usually not worth it (would consume timeout budget). Better to fail fast and fallback to BM25.

---

## 6. Code Sketches

### Option G: Single Batch Judge (Recommended v1)

```python
"""LLM-as-judge for memory retrieval (single batch)."""

import json
import os
import random
import ssl
import urllib.error
import urllib.request

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

JUDGE_SYSTEM = """\
You are a memory relevance classifier for a coding assistant.

Given a user's prompt and a list of stored memories, identify which memories are
RELEVANT and would be USEFUL for the task. A memory qualifies if:
- It addresses the same topic, technology, or concept
- It contains decisions, constraints, or procedures that apply
- Injecting it would improve the response quality

A memory does NOT qualify if:
- It shares keywords but is about a different topic
- It is too general or tangential
- It would waste the assistant's attention

Output ONLY a JSON object: {"keep": [0, 2, 5]}
where values are memory indices to keep. Empty if none qualify: {"keep": []}
"""


def call_api(system: str, user_msg: str, model: str, timeout: float) -> str | None:
    """Call Anthropic Messages API. Returns response text or None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    payload = json.dumps({
        "model": model,
        "max_tokens": 128,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }).encode("utf-8")

    req = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            blocks = data.get("content", [])
            if blocks and blocks[0].get("type") == "text":
                return blocks[0]["text"]
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, TimeoutError, OSError,
            KeyError, IndexError):
        pass
    return None


def format_candidates(user_prompt: str, candidates: list[dict]) -> str:
    """Format candidates for judge. Shuffles to prevent position bias."""
    n = len(candidates)
    order = list(range(n))
    random.seed(hash(user_prompt) % (2**32))
    random.shuffle(order)

    lines = []
    for display_idx, real_idx in enumerate(order):
        c = candidates[real_idx]
        tags = ", ".join(sorted(c.get("tags", set())))
        title = c.get("title", "untitled")
        cat = c.get("category", "unknown")
        lines.append(f"[{display_idx}] [{cat}] {title} (tags: {tags})")

    text = "\n".join(lines)
    # order_map: display_idx -> real_idx (for de-shuffling)
    return f"User prompt: {user_prompt[:500]}\n\nStored memories:\n{text}", order


def parse_response(text: str, order_map: list[int], n_candidates: int) -> list[int] | None:
    """Parse judge response. Returns list of real candidate indices, or None on failure."""
    import re
    # Try direct parse
    for candidate_text in [text.strip(), None]:
        if candidate_text is None:
            m = re.search(r'\{[^}]+\}', text)
            if not m:
                return None
            candidate_text = m.group()
        try:
            data = json.loads(candidate_text)
            if isinstance(data, dict) and "keep" in data:
                display_indices = data["keep"]
                if isinstance(display_indices, list):
                    real = []
                    for di in display_indices:
                        if isinstance(di, int) and 0 <= di < len(order_map):
                            real.append(order_map[di])
                    return real
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def judge_candidates(
    user_prompt: str,
    candidates: list[dict],
    model: str = _DEFAULT_MODEL,
    timeout: float = 3.0,
) -> list[dict] | None:
    """Run single-batch LLM judge. Returns filtered candidates or None on failure."""
    if not candidates:
        return []

    formatted, order_map = format_candidates(user_prompt, candidates)
    response = call_api(JUDGE_SYSTEM, formatted, model, timeout)
    if response is None:
        return None  # API failure

    kept_indices = parse_response(response, order_map, len(candidates))
    if kept_indices is None:
        return None  # Parse failure

    return [candidates[i] for i in sorted(set(kept_indices)) if i < len(candidates)]
```

**Total: ~115 LOC**

### Integration Point in memory_retrieve.py

```python
# After scoring and before output (around line 321):
# Insert between "scored.sort()" and "Pass 2: Deep check"

# --- LLM Judge (if configured) ---
judge_enabled = False
judge_cfg = {}
if config_path.exists():
    try:
        judge_cfg = config.get("retrieval", {}).get("judge", {})
        judge_enabled = (
            judge_cfg.get("enabled", False)
            and os.environ.get("ANTHROPIC_API_KEY")
        )
    except (KeyError, AttributeError):
        pass

if judge_enabled and scored:
    from memory_judge import judge_candidates  # or inline
    pool_size = judge_cfg.get("candidate_pool_size", 15)
    candidates_for_judge = [entry for _, _, entry in scored[:pool_size]]

    filtered = judge_candidates(
        user_prompt=user_prompt,
        candidates=candidates_for_judge,
        model=judge_cfg.get("model", "claude-haiku-4-5-20251001"),
        timeout=judge_cfg.get("timeout_per_call", 3.0),
    )

    if filtered is not None:
        # Re-score filtered candidates (preserve original scoring for priority)
        filtered_paths = {e["path"] for e in filtered}
        scored = [(s, p, e) for s, p, e in scored if e["path"] in filtered_paths]
    else:
        # Judge failed: conservative fallback
        fallback_k = judge_cfg.get("fallback_top_k", 2)
        scored = scored[:fallback_k]
```

**Additional integration: ~25 LOC**

---

## 7. Test Strategy

### The Non-Determinism Problem

LLM-as-judge outputs are inherently non-deterministic. You cannot assert `judge("fix auth bug", candidates) == [0, 2]` because the LLM might return `[0, 1, 2]` on the next run.

### Testing Approach: Mock the API

```python
# tests/test_memory_judge.py

import json
from unittest.mock import patch, MagicMock

def mock_api_response(keep_indices: list[int]) -> MagicMock:
    """Create a mock urllib response."""
    response_body = json.dumps({
        "content": [{"type": "text", "text": json.dumps({"keep": keep_indices})}]
    }).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp
```

### What to Test (Deterministic)

| Test | What | How |
|------|------|-----|
| `test_format_candidates_shuffles` | Shuffling works, order_map is correct | Verify output indices map back correctly |
| `test_format_candidates_truncates_prompt` | Prompt truncated to 500 chars | Long prompt input |
| `test_parse_response_valid` | Valid JSON parsed correctly | Mock responses |
| `test_parse_response_code_block` | JSON in markdown code block extracted | `"```json\n{...}\n```"` |
| `test_parse_response_invalid` | Graceful failure on garbage | `"I think memories 1 and 3"` |
| `test_parse_response_empty` | Empty keep list | `{"keep": []}` |
| `test_parse_response_out_of_range` | Indices beyond candidate count | `{"keep": [0, 99]}` |
| `test_judge_no_api_key` | Returns None (fallback) | `os.environ` without key |
| `test_judge_api_timeout` | Returns None (fallback) | Mock raises TimeoutError |
| `test_judge_api_error` | Returns None (fallback) | Mock raises HTTPError |
| `test_judge_integration` | End-to-end with mocked API | Full pipeline test |
| `test_judge_empty_candidates` | Returns empty list | Edge case |
| `test_shuffling_deterministic` | Same prompt + candidates = same shuffle | Hash-based seed |
| `test_deshuffle_correctness` | Display indices map back to real indices | Round-trip test |

### LOC estimate for tests: ~200 LOC

### Integration Tests (Manual)

The true precision measurement requires manual testing:
1. Craft 20 diverse prompts
2. Create 50 memory entries across categories
3. For each prompt, manually annotate which memories are truly relevant
4. Run the judge, compare output to ground truth
5. Calculate precision and recall

This is not automatable but is essential for tuning.

---

## 8. The Subagent Impossibility: Confirmed

From reading the code carefully, I confirm the architect's finding:

**Hook scripts (type: "command") run as external subprocesses. They have NO mechanism to invoke Claude Code's Task tool.**

Evidence:
1. `memory_retrieve.py` reads stdin, writes stdout, exits. No Claude Code API interaction.
2. `memory_triage.py` does the same pattern -- even the Stop hook (which is more complex) has no Task tool access.
3. The SKILL.md shows Task tool usage, but skills run WITHIN the agent conversation, not as subprocesses.
4. hooks.json explicitly specifies `"type": "command"` -- this is a subprocess, not an agent-side operation.

**The Task tool approach is not "difficult" -- it is structurally impossible from a hook context.**

The only way to use Task tool for retrieval judging would be:
1. Remove the UserPromptSubmit hook
2. Make retrieval a skill-triggered operation
3. Lose automatic injection (requires agent to actively run the skill)

This defeats the core purpose. The inline API approach is the correct solution.

---

## 9. Alternative: Skill-Based Judge (On-Demand Only)

For the on-demand search mode (`/memory:search`), the skill CAN use Task subagent:

```
User: /memory:search authentication
  -> SKILL.md activates
  -> Agent runs: python3 memory_search_engine.py --query "auth" --mode search
  -> Agent gets raw candidate list (BM25 results)
  -> Agent calls Task(model=haiku, prompt="Judge these candidates...")
  -> Agent applies filter
  -> Agent presents results
```

**This is a viable hybrid:**
- **Auto-inject:** Inline API judge (in hook)
- **On-demand search:** Task subagent judge (in skill)

The advantage of Task subagent for on-demand: it has access to full conversation context, not just the user prompt. It can make better relevance judgments.

**However,** implementing two different judge mechanisms (one in hook, one in skill) adds complexity. For v1, I recommend using the same inline API approach for both, and reserving Task-based judging for a future enhancement.

---

## 10. Risk Assessment

| Risk | Severity | Likelihood | Mitigation | Pragmatist Assessment |
|------|----------|-----------|------------|----------------------|
| API key not available | HIGH | Medium | Fallback to BM25 | Document requirement clearly |
| Latency > 3s (user perceives as slow) | MEDIUM | Medium (P50: ~1s, P95: ~2s) | Single call, not dual | Start with single judge |
| API rate limiting (429) | LOW | Low | Fail fast, no retry | Acceptable for personal project |
| Judge always rejects (empty results) | HIGH | Low | Log decisions, monitor | Add stderr logging |
| Judge always accepts (no filtering) | MEDIUM | Low | Validate precision manually | Test with adversarial prompts |
| SSL issues on exotic platforms | LOW | Very Low | Fallback to BM25 | Not a concern on WSL2 |
| Prompt injection via memory titles | MEDIUM | Low | Existing sanitization + judge hardening | Architect's mitigation is adequate |
| Cost accumulation | LOW | Certain | ~$3.36/month at 100 prompts/day | Acceptable, configurable disable |
| urllib connection overhead | LOW | Certain | ~50-100ms per call | Negligible vs API latency |
| Hook timeout (10s) hit | LOW | Very Low | 3s per-call timeout + fallback | Single call has 8s margin |

### Additional Risk: Circular Dependency

If the LLM judge itself is a Claude model (haiku), and the user is using Claude Code (which uses Claude)... there's a conceptual circularity. The same organization's API is used for both the main conversation and the judge.

**Impact:** If the Anthropic API is down, BOTH the main conversation and the judge fail. But: if the main conversation fails, the hook never runs anyway. So this is not an additional failure mode.

---

## 11. Recommendation

### Implementation Path (Phased)

#### Phase 0: Baseline Measurement (Before Any LLM Work)
- Implement FTS5 BM25 (rd-08 plan)
- Manually test precision on 20 queries
- Record baseline precision number

**Why:** Without a measured baseline, we cannot validate that the judge actually improves precision. The architect's estimates (~65-75% BM25, ~85-90% single judge, ~95-98% dual judge) are educated guesses. Measure first.

#### Phase 1: Single Batch Judge (v1)
- Add `memory_judge.py` (~120 LOC) with single batch judge
- Integrate into `memory_retrieve.py` (~25 LOC)
- Add tests (~200 LOC)
- Add config keys (`judge.enabled`, `judge.model`, `judge.timeout_per_call`, `judge.fallback_top_k`, `judge.candidate_pool_size`)
- Set `judge.enabled: false` by default (opt-in)
- Total: ~345 LOC, ~1 focused day

#### Phase 2: Measure and Decide
- Test single judge precision on same 20 queries
- Compare to baseline
- If precision >= 90%: Ship as-is, dual verification may be unnecessary
- If precision 80-90%: Consider dual verification
- If precision < 80%: Investigate judge prompt quality before adding more calls

#### Phase 3: Dual Verification (If Needed)
- Add second judge prompt (usefulness)
- Add intersection/union logic
- Add threading option (`concurrent.futures`)
- Total: ~70 additional LOC

#### Phase 4: On-Demand Search Integration
- Apply judge to `/memory:search` results (lenient mode)
- Reuse same `memory_judge.py` module

### Config Recommendation

```json
{
  "retrieval": {
    "judge": {
      "enabled": false,
      "model": "claude-haiku-4-5-20251001",
      "timeout_per_call": 3.0,
      "fallback_top_k": 2,
      "candidate_pool_size": 15,
      "dual_verification": false
    }
  }
}
```

- **`enabled: false` by default** -- opt-in feature, not forced on users
- **`dual_verification: false` by default** -- single judge first
- **`model: haiku`** -- best speed/cost ratio for per-prompt operation

### Why NOT the Architect's Recommendation

The architect recommends dual verification as the default. I disagree for three reasons:

1. **No measured baseline.** We don't know if single judge achieves 85% or 92%. If it's 92%, dual verification adds cost and latency for marginal gain.
2. **Latency impact.** Single call P50 ~1s vs dual P50 ~2-3s. The difference is perceptible.
3. **YAGNI.** Start simple. Measure. Add complexity only if data shows it's needed.

The architect's dual verification design is sound. I don't object to the architecture -- I object to implementing it before measuring whether it's needed.

### Key Agreement with Architect

1. **Inline API via `urllib.request`** -- correct approach. Task subagent is impossible from hooks.
2. **Fallback to BM25** -- essential. Judge failure must never break retrieval.
3. **Position bias mitigation via shuffling** -- good practice.
4. **Config-gated** -- users must opt in.
5. **Title+tags only (not body)** -- token-efficient and sufficient for relevance judgment.

---

## Appendix: Quick Implementation Checklist

- [ ] Create `hooks/scripts/memory_judge.py` (~120 LOC)
- [ ] Modify `hooks/scripts/memory_retrieve.py` to import and use judge (~25 LOC)
- [ ] Add `judge.*` config keys to `memory-config.default.json`
- [ ] Update `hooks.json` timeout from 10 to 15 seconds (safety margin)
- [ ] Create `tests/test_memory_judge.py` (~200 LOC)
- [ ] Update CLAUDE.md Key Files table
- [ ] Update CLAUDE.md Security Considerations
- [ ] Manual precision test on 20 queries (before and after)

**Estimated total effort: 1 focused day for v1 (single judge).**
