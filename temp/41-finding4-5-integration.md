# Finding #4 & #5: Integration Analysis

**Analyst:** analyst-integration
**Date:** 2026-02-22
**Findings:** #4 (PoC #6 Dead Correlation Path, HIGH), #5 (Logger Import Crash, HIGH)
**External Validation:** Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check

---

## 1. Executive Summary

Both findings expose integration boundary failures between the hook path (memory_retrieve.py) and the CLI path (memory_search_engine.py):

- **Finding #4:** PoC #6 correlates `retrieval.inject` and `search.query` events on `session_id`. CLI mode has no `hook_input`, so `session_id` is always empty. The join **structurally produces 0 matches**. Fix: add optional `--session-id` CLI parameter + env var fallback.

- **Finding #5:** If `memory_logger.py` is added as a top-level import and the file doesn't exist (partial deploy), `ModuleNotFoundError` crashes the entire retrieval hook. This violates fail-open. Fix: standardize a lazy import pattern with `try/except ImportError` fallback across all optional modules.

**Cross-finding insight:** Both touch the CLI/hook boundary and share a design principle: **optional features must never break core functionality**. The `--session-id` param is optional (empty string is valid), and the logger import must be optional (noop fallback on ImportError).

---

## 2. Finding #4: --session-id CLI Parameter Design

### 2.1 Current State

**CLI argparse** (`memory_search_engine.py:425-499`):
```python
parser.add_argument("--query", "-q", required=True, ...)
parser.add_argument("--root", "-r", required=True, ...)
parser.add_argument("--mode", "-m", choices=["auto", "search"], ...)
parser.add_argument("--max-results", "-n", type=int, ...)
parser.add_argument("--include-retired", action="store_true", ...)
parser.add_argument("--format", "-f", choices=["json", "text"], ...)
```

No `--session-id` parameter. No session concept in CLI mode.

**SKILL.md invocation** (`skills/memory-search/SKILL.md:37`):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_search_engine.py" \
    --query '<user query>' \
    --root .claude/memory \
    --mode search
```

No session_id propagation.

**Hook path** (`memory_retrieve.py:432`):
```python
transcript_path = hook_input.get("transcript_path", "")
```

Session identity derived from `transcript_path` (available only in hook mode via stdin JSON).

### 2.2 Environment Variable Investigation

Checked runtime environment:
- `CLAUDECODE=1` -- present
- `CLAUDE_CODE_SSE_PORT=46376` -- present
- **No `CLAUDE_SESSION_ID` or `CLAUDE_TRANSCRIPT_PATH`** environment variables exist

This means the LLM (skill invoker) has no programmatic access to session_id via env vars. The LLM **cannot reliably propagate session_id** because it doesn't know its own session_id.

### 2.3 Design Decision: Hybrid Propagation

**Recommended approach** (Codex 5.3 consensus + pragmatism):

```
Precedence: --session-id CLI arg > CLAUDE_SESSION_ID env var > empty string
```

**Rationale:**
1. `--session-id` CLI param: Most explicit, testable, future-proof. But the LLM invoker (SKILL.md) currently cannot provide it because no session_id is exposed to the LLM context.
2. `CLAUDE_SESSION_ID` env var: Zero-friction if Claude Code ever exposes session info. Currently unavailable.
3. Empty string (uncorrelated): The realistic default for now. PoC #6 acknowledges this limitation.

**Implementation:**

```python
# In memory_search_engine.py main(), after existing args:
parser.add_argument("--session-id", default="",
                    help="Session ID for log correlation (optional)")

# After parsing:
session_id = args.session_id or os.environ.get("CLAUDE_SESSION_ID", "")
```

**Position in argparse:** After `--format` (last existing param). This is a non-breaking addition.

### 2.4 Skill-Side Propagation

**Problem:** The SKILL.md tells the LLM to run a bash command. The LLM cannot access its own session_id.

**Investigated options:**
1. `hook_input` -- only available in hook scripts, not in skill context
2. `$CLAUDE_SESSION_ID` env var -- does not exist (confirmed)
3. `transcript_path` -- not exposed to the LLM
4. LLM invents a session_id -- **DANGEROUS**: could fabricate values

**Recommendation:** Do NOT instruct the LLM to pass `--session-id` in SKILL.md yet. The parameter exists for:
1. Future use when Claude Code exposes session info
2. Manual CLI usage by developers
3. Automated test scripts

**SKILL.md change:** None needed now. The existing invocation remains valid. When `CLAUDE_SESSION_ID` env var becomes available, the script picks it up automatically via the env fallback.

### 2.5 Logging Integration

When `memory_search_engine.py` receives (or derives) a session_id, it passes it to `emit_event()`:

```python
# In main(), after search completes:
emit_event(
    event_type="search.query",
    data={"query_tokens": [...], "results": [...], ...},
    session_id=session_id,
    script="memory_search_engine.py",
    memory_root=str(memory_root),
)
```

The `memory_root` param is already available (parsed from `--root`). No additional CLI params needed for logging.

### 2.6 Impact on PoC #6

With the minimal fix:
- CLI searches with `--session-id` will emit correlated `search.query` events
- **Limitation:** SKILL.md-invoked searches will still have empty session_id (until env var is available)
- PoC #6 can proceed with **manual CLI testing** using explicit `--session-id`
- The env fallback provides a future upgrade path without code changes

**PoC #6 status changes from BLOCKED to PARTIALLY UNBLOCKED:**
- Manual correlation: possible (developer passes --session-id)
- Automatic correlation via SKILL.md: still unavailable
- Timestamp-based fallback: viable for exploratory analysis (not for KPIs)

---

## 3. Finding #5: Import Pattern Analysis

### 3.1 Current Import Patterns

**memory_retrieve.py (lines 13-37):**

| Import | Type | Location | Fail-safe? |
|--------|------|----------|-----------|
| `html, json, os, re, sys, unicodedata, datetime, pathlib` | stdlib | Top-level (lines 13-20) | Always available |
| `memory_search_engine` (11 symbols) | Local sibling | Top-level (lines 25-37) | **No try/except** -- crashes if missing |
| `memory_judge` | Local sibling | Lazy inside `if judge_enabled:` (lines 429, 503) | Partial -- skipped when disabled, but **crashes if enabled + missing** |
| `subprocess` | stdlib | Lazy inside conditional (line 328) | Always available |

**memory_search_engine.py (lines 15-20):**

| Import | Type | Location | Fail-safe? |
|--------|------|----------|-----------|
| `argparse, json, os, re, sys, pathlib` | stdlib | Top-level | Always available |
| `sqlite3` | stdlib | Try/except (lines 82-89) | **Yes** -- `HAS_FTS5 = False` on failure |

**memory_judge.py (lines 16-28):**

| Import | Type | Location | Fail-safe? |
|--------|------|----------|-----------|
| `concurrent.futures, hashlib, html, json, os, random, sys, time, urllib.*` | stdlib | Top-level | Always available |

**memory_triage.py (lines 16-28):**

| Import | Type | Location | Fail-safe? |
|--------|------|----------|-----------|
| `collections, datetime, json, math, os, re, select, sys, time, pathlib, typing` | stdlib | Top-level | Always available |

### 3.2 Key Observation: `memory_search_engine` is NOT Optional

The import of `memory_search_engine` at the top of `memory_retrieve.py` (line 25) imports 11 symbols (BODY_FIELDS, CATEGORY_PRIORITY, HAS_FTS5, etc.). This is a **core dependency**, not optional. If `memory_search_engine.py` is missing, the retrieval hook is fundamentally broken. No try/except needed here -- this is a deployment error, not a partial deploy scenario.

**`memory_logger` IS optional** -- it's a new module that provides observability, not core functionality. The hook must work without it.

**`memory_judge` IS optional** -- it's an enhancement feature gated by config. The hook must work without it.

### 3.3 Existing Judge Vulnerability

Gemini 3 Pro identified a critical flaw: the existing `memory_judge` import pattern at `memory_retrieve.py:429` and `memory_retrieve.py:503`:

```python
if judge_enabled and results:
    from memory_judge import judge_candidates  # No try/except!
```

If `judge.enabled = true` in config but `memory_judge.py` is missing (partial deploy), this crashes the hook. This is the **same class of bug as Finding #5** -- just not yet triggered in practice because judge is disabled by default.

### 3.4 Pattern Comparison

| Pattern | Overhead when disabled | Crash on missing module | Multi-site boilerplate | Recommended? |
|---------|----------------------|------------------------|----------------------|-------------|
| **A: Module-level try/except** | Always incurs import attempt | No (fallback noop) | None (one site) | **Yes for logger** |
| **B: Function-level lazy** | Zero | No (fallback noop) | Moderate (accessor function) | Viable |
| **C: Conditional inline** | Zero | **YES if enabled** | High (every call site) | **No** |

### 3.5 Recommended Pattern: Module-level try/except (Option A)

**Against Gemini's recommendation (Option B) -- here's why:**

Gemini argued that Option A introduces "constant I/O and parse latency on every prompt even if logging is disabled." This is technically true for fresh subprocesses, but **the cost is negligible**:

1. Python's import system checks `sys.modules` first (dict lookup, ~100ns)
2. On first import of a missing module, `ImportError` is raised in ~0.1ms
3. The hook already does a top-level import of `memory_search_engine` (11 symbols) which is far more expensive
4. The noop fallback `def emit_event(*args, **kwargs): pass` has zero runtime cost

**Practical decision:** Option A is simpler, requires zero boilerplate at call sites, and the "overhead" argument doesn't hold for a single conditional import in a script that already does 12 stdlib imports + 11 local imports.

**Exception:** For `memory_judge`, the **existing pattern** (conditional inline) should be preserved but **wrapped in try/except**. Reason: the judge module imports `urllib.request` and `concurrent.futures` which have meaningful startup cost. Only importing when judge_enabled avoids ~5ms of unnecessary stdlib imports on every prompt.

### 3.6 Standardized Pattern

**For memory_logger (new, lightweight):**
```python
# At module level, after other imports:
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

**For memory_judge (existing, heavyweight):**
```python
# Inside main(), at existing import sites (lines 429, 503):
if judge_enabled and results:
    try:
        from memory_judge import judge_candidates
    except ImportError:
        judge_candidates = None

    if judge_candidates is not None:
        # existing judge logic...
    else:
        # fallback: unfiltered results (fail-open)
        fallback_k = judge_cfg.get("fallback_top_k", 2)
        results = results[:fallback_k]
```

**For memory_search_engine.py (CLI tool importing memory_logger):**
```python
# Same module-level pattern:
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

### 3.7 Exception Type: ImportError vs ModuleNotFoundError

Gemini flagged: "Ensure the exception catch is strictly `except ImportError`... not bare `except:`."

`ModuleNotFoundError` is a subclass of `ImportError` (since Python 3.6). Catching `ImportError` is correct and sufficient -- it catches missing modules but does NOT mask `SyntaxError`, `TypeError`, or other errors inside the module.

---

## 4. Cross-Finding Design Principles

### 4.1 Optional Features Must Never Break Core

Both findings share this principle. Applied:
- `--session-id`: Optional param, default empty string, never crashes
- `memory_logger`: Optional import, noop fallback, never crashes
- `memory_judge`: Should adopt same fail-safe pattern (currently vulnerable)

### 4.2 CLI/Hook Boundary Contract

The CLI tool (`memory_search_engine.py`) and hook (`memory_retrieve.py`) are the same codebase serving two contexts:

| Aspect | Hook mode | CLI mode |
|--------|-----------|----------|
| Invocation | Claude Code subprocess (stdin JSON) | LLM bash command or manual |
| Session info | `hook_input.transcript_path` | `--session-id` arg or env var |
| Logging | Automatic (if enabled) | Same interface, same output |
| Fail-open | Required (must not crash) | Desirable but not critical |

### 4.3 Future-Proofing Without Over-Engineering

The `--session-id` param + env fallback provides exactly one future upgrade path (env var availability) without speculative complexity. No `correlation_method` metadata, no `nudge_id`, no process group IDs.

**Vibe-check result:** The simplest fix IS sufficient. PoC #6 was already reclassified from "decision gate" to "exploratory data collection." Over-engineering the correlation mechanism for an exploratory experiment is unjustified.

---

## 5. External Validation Results

### 5.1 Codex 5.3 (planner mode)

**On session_id propagation:**
- Recommends hybrid: `--session-id` CLI arg > env var > empty string
- Warns against timestamp-based correlation as primary method (collision-prone, non-causal)
- Warns against process group ID (unstable across hook/CLI boundaries)
- Key insight: "Do not require the LLM to invent session_id. Allow pass-through if available."
- Recommends `correlation_method` enum in logs: `cli_arg|env|inferred_time|unavailable`

**Assessment:** Sound advice. I adopt the precedence hierarchy but simplify by omitting `correlation_method` metadata (premature for v1 exploratory data collection).

### 5.2 Gemini 3 Pro (planner mode)

**On import patterns:**
- Recommends Option B (function-level lazy import) -- I disagree (see section 3.5)
- Correctly identified the judge vulnerability: existing conditional imports at lines 429, 503 lack `try/except ImportError`, so `judge_enabled=true + missing module = crash`
- Recommends standardizing both judge and logger to same accessor pattern
- Key risk flagged: "Ensure exception catch is `except ImportError` not bare `except:` to avoid masking SyntaxError"

**Assessment:** The judge vulnerability finding is valuable and confirmed. I disagree on Option B vs A for the logger (see section 3.5 rationale) but adopt the judge hardening recommendation.

---

## 6. Vibe-Check Results

**Question:** Am I over-designing the `--session-id` feature?

**Answer:** Yes, partially. The minimal fix (argparse param + env fallback, ~5 LOC) is sufficient for unblocking PoC #6. The `correlation_method` metadata, `nudge_id`, timestamp-based fallback analytics -- all of these are premature given:

1. PoC #6 is classified as "exploratory data collection" (not decision gate)
2. No `CLAUDE_SESSION_ID` env var exists yet
3. The SKILL.md cannot propagate session_id to the LLM
4. Manual CLI usage with `--session-id` is sufficient for initial experiments

**Keep it minimal. Add complexity when data demands it.**

---

## 7. Exact Code Changes

### 7.1 Finding #4: --session-id CLI Parameter

**File: `hooks/scripts/memory_search_engine.py`**

**Change 1: Add argparse parameter** (after line 443, the `--format` arg):

```python
    parser.add_argument("--session-id", default="",
                        help="Session ID for log correlation (optional, "
                             "falls back to CLAUDE_SESSION_ID env var)")
```

**Change 2: Resolve session_id** (after line 445, `args = parser.parse_args()`):

```python
    session_id = args.session_id or os.environ.get("CLAUDE_SESSION_ID", "")
```

**Change 3: Pass session_id to emit_event** (inside the results output block, after line 482):

```python
    # After outputting results (both json and text paths):
    emit_event(
        event_type="search.query",
        data={
            "query": args.query,
            "mode": args.mode,
            "total_results": len(results),
        },
        session_id=session_id,
        script="memory_search_engine.py",
        memory_root=str(memory_root),
    )
```

**Note:** Change 3 depends on `memory_logger.py` existing (Plan #2). The `emit_event` import (see section 7.2) ensures this is a noop if the logger doesn't exist yet.

**File: `skills/memory-search/SKILL.md`**

**No changes needed.** The `--session-id` param is optional. The env var fallback handles future session propagation automatically.

**File: `plans/plan-poc-retrieval-experiments.md`**

**Change:** Update PoC #6 status from BLOCKED to PARTIALLY UNBLOCKED:
- Remove "BLOCKED" label
- Add note: "Manual correlation via `--session-id` CLI param available. Automatic skill-to-hook correlation awaits `CLAUDE_SESSION_ID` env var."

### 7.2 Finding #5: Lazy Import Pattern

**File: `hooks/scripts/memory_retrieve.py`**

**Change 1: Add module-level try/except for memory_logger** (after line 37, the memory_search_engine imports):

```python
# Optional logging module (fail-open: noop if missing)
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

**Change 2: Harden judge import at line 429** (FTS5 path):

```python
                if judge_enabled and results:
                    try:
                        from memory_judge import judge_candidates
                    except ImportError:
                        judge_candidates = None

                    if judge_candidates is not None:
                        candidates_for_judge = results[:judge_pool_size]
                        transcript_path = hook_input.get("transcript_path", "")
                        filtered = judge_candidates(
                            user_prompt=user_prompt,
                            candidates=candidates_for_judge,
                            transcript_path=transcript_path,
                            model=judge_cfg.get("model", "claude-haiku-4-5-20251001"),
                            timeout=judge_cfg.get("timeout_per_call", 3.0),
                            include_context=judge_cfg.get("include_conversation_context", True),
                            context_turns=judge_cfg.get("context_turns", 5),
                        )
                        if filtered is not None:
                            filtered_paths = {e["path"] for e in filtered}
                            results = [e for e in results if e["path"] in filtered_paths]
                        else:
                            fallback_k = judge_cfg.get("fallback_top_k", 2)
                            results = results[:fallback_k]
                    else:
                        # Judge module missing: conservative fallback
                        fallback_k = judge_cfg.get("fallback_top_k", 2)
                        results = results[:fallback_k]
```

**Change 3: Harden judge import at line 503** (legacy path):

```python
    if judge_enabled and scored:
        try:
            from memory_judge import judge_candidates
        except ImportError:
            judge_candidates = None

        if judge_candidates is not None:
            pool_size = judge_cfg.get("candidate_pool_size", 15)
            # ... existing judge logic unchanged ...
        else:
            # Judge module missing: conservative fallback
            fallback_k = judge_cfg.get("fallback_top_k", 2)
            scored = scored[:fallback_k]
```

**File: `hooks/scripts/memory_search_engine.py`**

**Change: Add module-level try/except for memory_logger** (after line 20, the stdlib imports):

```python
# Optional logging module (fail-open: noop if missing)
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

**Note:** `memory_search_engine.py` doesn't currently have a `sys.path.insert` for sibling imports (unlike `memory_retrieve.py:23`). It's imported directly by `memory_retrieve.py` via `sys.path.insert`. For standalone CLI usage, the sibling path must be added. However, since `sys` is already imported at line 19, the actual change is:

```python
# After line 20 (from pathlib import Path):
# Ensure sibling modules are findable for standalone CLI usage
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Optional logging module (fail-open: noop if missing)
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

**Wait -- `sys.path.insert` side effect.** This already happens in `memory_retrieve.py:23` before importing `memory_search_engine`. For standalone CLI usage, `memory_search_engine.py` is invoked directly (not imported), so the `sys.path` doesn't include sibling dir. Adding `sys.path.insert` at module level is the correct fix.

**However**, this `sys.path.insert` will run even when `memory_search_engine.py` is imported as a module (from `memory_retrieve.py`). That's harmless -- `sys.path` is idempotent in practice and `memory_retrieve.py` already does the same insertion.

---

## 8. Risks & Edge Cases

### 8.1 Finding #4 Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| LLM fabricates session_id | Medium | SKILL.md does NOT instruct LLM to pass --session-id. Env fallback handles future propagation. |
| Empty session_id in most CLI searches | Low | Expected and documented. PoC #6 methodology accounts for this. |
| --session-id used for injection | Low | session_id is only written to JSONL logs (not to stdout or prompt context). No injection vector. |

### 8.2 Finding #5 Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| SyntaxError in memory_logger.py masked by except ImportError | None | `ImportError` does NOT catch `SyntaxError`. Only missing modules trigger the fallback. |
| memory_judge.py SyntaxError masked | None | Same: `ImportError` doesn't catch `SyntaxError`. |
| Noop emit_event silently drops all logging | Low | Expected behavior when module is missing. Fail-open by design. |
| sys.path.insert in memory_search_engine.py affects import resolution | Very Low | Same path as memory_retrieve.py:23. Idempotent, sibling-dir only. |
| Judge fallback (fallback_top_k) activated when module is present but import fails for other reasons | Very Low | Only `ImportError` and its subclass `ModuleNotFoundError` are caught. Other exceptions propagate. |

### 8.3 Cross-Finding Edge Case

**Partial deploy scenario:** User updates plugin but `memory_logger.py` isn't yet deployed:
1. `memory_retrieve.py` -- noop fallback, works fine
2. `memory_search_engine.py` -- noop fallback, works fine
3. `--session-id` parsed but emit_event is noop -- harmless
4. All core functionality preserved

---

## Appendix: LOC Estimates

| Change | File | LOC Added | LOC Modified |
|--------|------|-----------|-------------|
| --session-id argparse | memory_search_engine.py | 3 | 0 |
| session_id resolution | memory_search_engine.py | 1 | 0 |
| emit_event call (CLI) | memory_search_engine.py | 8 | 0 |
| Logger import (retrieve) | memory_retrieve.py | 4 | 0 |
| Logger import (search engine) | memory_search_engine.py | 5 | 0 |
| Judge hardening (FTS5 path) | memory_retrieve.py | 6 | 4 |
| Judge hardening (legacy path) | memory_retrieve.py | 6 | 4 |
| sys.path.insert | memory_search_engine.py | 1 | 0 |
| **Total** | | **34** | **8** |
