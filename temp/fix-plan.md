# Fix Plan: Session Overflow -- MAX_RETIRE_ITERATIONS and Mechanical Enforcement

**Date:** 2026-02-24
**Author:** Claude Opus 4.6 (multi-perspective validated)
**Status:** Draft
**Root files:**
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_write.py`
- `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md`
- `/home/idnotbe/projects/claude-memory/tests/test_rolling_window.py`

---

## 1. Problem Summary

Two root causes allowed 67 session files to accumulate in the ops project (expected max: 5):

| ID | Severity | Problem | Impact |
|----|----------|---------|--------|
| RC1 | CRITICAL | No mechanical invocation -- enforcement depends on LLM reading SKILL.md | Sessions accumulate without limit when LLM skips the step |
| RC2 | HIGH | `MAX_RETIRE_ITERATIONS = 10` caps retirements per run | Recovery from accumulation takes 7 runs for 62 excess sessions |
| RC3 | MEDIUM | Stale index (11 of 16 entries incorrect) | Retrieval returns phantom/retired entries |
| RC4 | LOW | No automated archival after grace period | Retired files accumulate on disk indefinitely |

This plan addresses RC1 and RC2 as the primary fixes, RC3 as a follow-on action, and notes RC4 as future work.

---

## 2. External Opinions

### Gemini 3.1 Pro (via pal clink)

**Cap fix:** Recommends **(e) Dynamic cap** -- `max(10, max_retained * 5)`. Rationale: static caps always eventually fail; removing the cap destroys the safety valve; dynamic cap provides proportional safety.

**Mechanical invocation:** Recommends **(A) Direct integration into do_create()**. Rationale: LLM reliance (C) is non-deterministic; Bash hook (B) is brittle (requires parsing shell commands).

**Key warnings raised:**
1. **Circular import risk:** `memory_enforce.py` already imports from `memory_write.py`. Directly importing `enforce_rolling_window` into `memory_write.py` would create a circular import. Must use `subprocess.run()` instead.
2. **Deadlock risk:** Both scripts use `FlockIndex`. Must ensure `do_create()` releases the lock before triggering enforcement subprocess.
3. **Write latency:** Synchronous subprocess adds overhead. Consider detached process if latency is noticeable.

### Codex 5.3 (via pal clink)

Codex was unavailable (rate limit hit). Their opinion was not obtained.

### Synthesis of External Input

Gemini's circular import warning is the most critical insight. The naive approach of `from memory_enforce import enforce_rolling_window` inside `do_create()` would cause a circular dependency since `memory_enforce.py` already does `from memory_write import retire_record, FlockIndex, CATEGORY_FOLDERS`. The subprocess approach avoids this cleanly.

The deadlock concern is valid but manageable: `do_create()` uses a `with FlockIndex(index_path):` block that releases before the function returns. The subprocess call goes after that block exits.

---

## 3. Vibe Check

### Are we solving the right problem?
**Yes.** The ops project data confirms: enforcement IS working when called (62 sessions were correctly retired over Feb 20-24). The problem is that it was not called reliably (RC1) and when finally called after accumulation, it could not clean up in one pass (RC2). Both root causes are real and independently need fixing.

### Could our fix introduce new issues?
- **Subprocess overhead:** Each session create now spawns a subprocess for enforcement. For the normal case (6 active, retire 1), this is a trivial `~100ms` overhead -- acceptable.
- **Double enforcement:** If the LLM ALSO calls enforce per SKILL.md instructions, enforcement runs twice. This is harmless because `enforce_rolling_window()` is idempotent -- the second call finds no excess and returns immediately.
- **Category expansion:** Currently only `session_summary` uses rolling windows. If other categories add `max_retained`, the mechanical enforcement would need to be generalized. The current fix is scoped to session_summary only, matching the existing behavior.

### Are there edge cases we're missing?
- **What if enforce fails during the subprocess call?** The create itself has already succeeded and returned. Enforcement failure is logged to stderr but does not fail the create. This is the correct behavior -- a failed enforcement is recoverable on the next create.
- **What if max_retained is not set in config?** Falls back to `DEFAULT_MAX_RETAINED = 5`. The dynamic cap computation uses this value, so `max(10, 5*5) = 25`, which is reasonable.
- **What about the `--max-retained` CLI override?** The subprocess call reads from config, not CLI. This is correct -- mechanical enforcement should use the project's configured value, not a one-off override.

### Is this over-engineered or under-engineered?
**Appropriately scoped.** We're making two targeted changes: one constant becomes a formula, one function gets a subprocess call. No new files, no new hooks, no config schema changes. The SKILL.md instruction is kept (belt-and-suspenders) rather than removed.

---

## 4. Proposed Changes

### Change 1: Dynamic retirement cap (RC2 fix)

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`

**What:** Replace the hardcoded `MAX_RETIRE_ITERATIONS = 10` with a dynamic cap computed from `max_retained`.

**Formula:** `max(MAX_RETIRE_ITERATIONS_FLOOR, max_retained * MAX_RETIRE_MULTIPLIER)`
- `MAX_RETIRE_ITERATIONS_FLOOR = 10` (preserves original minimum safety)
- `MAX_RETIRE_MULTIPLIER = 10` (allows clearing 10x the retention limit per run)
- For `max_retained=5`: cap = `max(10, 50)` = **50** (handles up to 55 excess in one pass)
- For `max_retained=20`: cap = `max(10, 200)` = **200**
- For `max_retained=1`: cap = `max(10, 10)` = **10**

**Why multiplier of 10 instead of Gemini's 5:** With max_retained=5, a multiplier of 5 gives cap=25. The ops project had 62 excess, which still requires 3 runs. A multiplier of 10 gives cap=50, handling all but the most extreme accumulations in 1-2 runs. The safety valve still prevents unbounded operation.

**Specific code changes:**

```python
# Line 41: Replace
MAX_RETIRE_ITERATIONS = 10  # Safety valve: never retire more than this in one run

# With:
MAX_RETIRE_ITERATIONS_FLOOR = 10   # Minimum safety valve (original value)
MAX_RETIRE_MULTIPLIER = 10         # Dynamic cap = max_retained * this
```

```python
# In enforce_rolling_window(), compute dynamic cap:
# After line 230 (excess = len(active) - max_retained), replace line 235:
#   excess = min(excess, MAX_RETIRE_ITERATIONS)
# With:
retire_cap = max(MAX_RETIRE_ITERATIONS_FLOOR, max_retained * MAX_RETIRE_MULTIPLIER)
excess = min(excess, retire_cap)
```

```python
# Same change in dry-run path, line 208:
#   excess = min(excess, MAX_RETIRE_ITERATIONS)
# With:
retire_cap = max(MAX_RETIRE_ITERATIONS_FLOOR, max_retained * MAX_RETIRE_MULTIPLIER)
excess = min(excess, retire_cap)
```

**Also add a `--max-retire` CLI flag** for manual override in recovery scenarios:

```python
# In argparse section, add:
parser.add_argument(
    "--max-retire",
    type=int,
    default=None,
    help="Override maximum retirements per run (default: dynamic based on max_retained)",
)
```

Pass this to `enforce_rolling_window()` as a new parameter:

```python
def enforce_rolling_window(
    memory_root: Path,
    category: str,
    max_retained: int,
    dry_run: bool = False,
    max_retire_override: int | None = None,
) -> dict:
```

And in the cap computation:

```python
if max_retire_override is not None:
    retire_cap = max_retire_override
else:
    retire_cap = max(MAX_RETIRE_ITERATIONS_FLOOR, max_retained * MAX_RETIRE_MULTIPLIER)
excess = min(excess, retire_cap)
```

### Change 2: Mechanical enforcement in do_create() (RC1 fix)

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_write.py`

**What:** After a successful `do_create()` for any category that has `max_retained` configured, spawn `memory_enforce.py` as a subprocess.

**Why subprocess instead of direct import:** Circular dependency. `memory_enforce.py` imports `retire_record`, `FlockIndex`, `CATEGORY_FOLDERS` from `memory_write.py`. Importing back would create a cycle.

**Why after lock release:** `do_create()` uses `with FlockIndex(index_path):` for the write. The subprocess call goes after the `with` block exits (lock released), before the success output.

**Specific code change in `do_create()`:**

```python
# After line 718 (add_to_index), but OUTSIDE the FlockIndex `with` block
# (i.e., after line 719 which is the end of the `with` block):

    # Cleanup temp file
    _cleanup_input(args.input)

    # ── Mechanical enforcement: auto-enforce rolling window after session create ──
    if args.category == "session_summary":
        try:
            enforce_script = Path(__file__).parent / "memory_enforce.py"
            if enforce_script.exists():
                import subprocess
                env = os.environ.copy()
                # Pass project root so enforce can find .claude/memory/
                if "CLAUDE_PROJECT_ROOT" not in env:
                    env["CLAUDE_PROJECT_ROOT"] = str(memory_root.parent.parent)
                subprocess.run(
                    [sys.executable, str(enforce_script),
                     "--category", "session_summary"],
                    capture_output=True, text=True, timeout=30,
                    env=env,
                )
        except Exception as e:
            # Enforcement failure must not fail the create
            print(
                f"[WARN] Post-create enforcement failed: {e}. "
                f"Sessions may exceed max_retained until next enforcement.",
                file=sys.stderr,
            )
```

**Design decisions:**
- `capture_output=True`: Prevent enforce's stderr/stdout from mixing with write's output
- `timeout=30`: Match the hook timeout convention
- `try/except`: Never fail the create due to enforcement failure
- Only triggers for `session_summary`: The only category currently using rolling windows
- Uses `sys.executable`: Same Python interpreter, respects venv bootstrap

### Change 3: Config validation for max_retained (Bug #3 fix)

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`

**What:** Add `value < 1` check in `_read_max_retained()`.

```python
# After line 90-96 (the bool/type check), add:
if value < 1:
    print(
        f"[WARN] max_retained must be >= 1, got {value}. "
        f"Using default {DEFAULT_MAX_RETAINED}.",
        file=sys.stderr,
    )
    return DEFAULT_MAX_RETAINED
```

### Change 4: Document empty created_at sort behavior (Bug #2 fix)

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`

**What:** Add a comment at line 136 explaining the empty-string sort behavior:

```python
# Sort oldest first; filename as tiebreaker for identical timestamps.
# Note: missing/empty created_at ("") sorts before all ISO 8601 timestamps,
# so files with missing timestamps are retired first. This is intentional --
# files without timestamps are treated as oldest/most suspect.
results.sort(key=lambda s: (s["created_at"], s["path"].name))
```

### Change 5: Keep SKILL.md instruction (belt-and-suspenders)

**File:** `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md`

**What:** Keep the existing instruction but add a note that enforcement is now also mechanical:

```markdown
After all saves, if session_summary was created, enforce the rolling window:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_enforce.py" --category session_summary
```

> Note: Enforcement also runs automatically after `memory_write.py --action create --category session_summary`. This explicit call is a safety belt.
```

This ensures backwards compatibility and provides defense-in-depth.

---

## 5. Test Plan

### New tests to add to `tests/test_rolling_window.py`:

**Test A: Dynamic cap handles large excess in one run**
```python
def test_dynamic_cap_handles_large_excess(self, tmp_path):
    """50 active sessions, max_retained=5 -> retires 45 in one run (cap=50)."""
    from memory_enforce import enforce_rolling_window
    proj, mem_root, sessions = _setup_enforce_project(tmp_path, 50)
    result = enforce_rolling_window(mem_root, "session_summary", max_retained=5)
    assert len(result["retired"]) == 45
    assert result["active_count"] == 5
```

**Test B: Dynamic cap respects floor**
```python
def test_dynamic_cap_floor(self, tmp_path):
    """With max_retained=1, cap = max(10, 1*10) = 10. 15 sessions -> retires 10."""
    from memory_enforce import enforce_rolling_window
    proj, mem_root, sessions = _setup_enforce_project(tmp_path, 15)
    result = enforce_rolling_window(mem_root, "session_summary", max_retained=1)
    assert len(result["retired"]) == 10
    assert result["active_count"] == 5  # 15 - 10 = 5
```

**Test C: max_retire_override works**
```python
def test_max_retire_override(self, tmp_path):
    """--max-retire 3 limits retirements to 3 regardless of dynamic cap."""
    from memory_enforce import enforce_rolling_window
    proj, mem_root, sessions = _setup_enforce_project(tmp_path, 10)
    result = enforce_rolling_window(
        mem_root, "session_summary", max_retained=5, max_retire_override=3
    )
    assert len(result["retired"]) == 3
    assert result["active_count"] == 7
```

**Test D: Config max_retained < 1 falls back to default**
```python
def test_config_max_retained_zero_uses_default(self, tmp_path):
    """Config max_retained=0 -> falls back to DEFAULT_MAX_RETAINED (5)."""
    from memory_enforce import _read_max_retained
    proj, mem_root, _ = _setup_enforce_project(tmp_path, 3, config_max_retained=0)
    value = _read_max_retained(mem_root, "session_summary", cli_override=None)
    assert value == 5  # DEFAULT_MAX_RETAINED
```

**Test E: Mechanical enforcement subprocess (integration test)**
```python
def test_mechanical_enforcement_after_create(self, tmp_path):
    """Creating a 6th session_summary via memory_write.py auto-triggers enforcement."""
    # This is an integration test that runs memory_write.py via subprocess
    # and verifies that only 5 active sessions remain after the 6th create.
    # (Full implementation uses subprocess to call memory_write.py --action create)
```

### Existing tests that must still pass:
- `test_01` through `test_15`: All existing enforce tests
- `test_16` through `test_24`: All FlockIndex/retire_record tests

---

## 6. Self-Critique

### Points raised by external review that I missed:
1. **Circular import:** I initially considered direct function import. Gemini correctly flagged that `memory_enforce.py` already imports from `memory_write.py`, making a reverse import circular. The subprocess approach is the correct solution.
2. **Deadlock timing:** Gemini emphasized ensuring lock release before subprocess. I had this right but it deserved explicit callout -- the subprocess call MUST be after the `with FlockIndex` block exits.

### Security implications:
- **No new attack surface.** The subprocess call uses hardcoded script path (`Path(__file__).parent / "memory_enforce.py"`) and hardcoded arguments. No user input flows into the subprocess command.
- **Category arg is from `args.category`** which is validated by argparse `choices` earlier in the flow.
- **Environment variable injection:** We copy `os.environ` and add `CLAUDE_PROJECT_ROOT`. The enforcement script validates this path against filesystem reality. No injection vector.

### Operational risks:
- **Subprocess timeout:** If enforce hangs (e.g., FlockIndex deadlock from an external process), the 30-second timeout prevents blocking the create indefinitely.
- **Double enforcement overhead:** Negligible. Second call finds 0 excess and returns in <50ms.
- **Migration:** No config schema changes. No hook registration changes. No breaking changes. The fix is purely additive -- old behavior (LLM-driven enforcement) continues to work alongside the new mechanical enforcement.

### What this plan does NOT address:
- **RC4 (No automated archival):** Retired files still accumulate on disk. This is a separate issue requiring either a cron-like mechanism or integration into the enforcement flow. Deferred to a future plan.
- **RC3 (Stale index):** The index rebuild is a one-time operational action, not a code fix. Run: `python3 hooks/scripts/memory_index.py --rebuild --root /home/idnotbe/projects/ops/.claude/memory`
- **Generalized rolling windows:** If other categories eventually need `max_retained`, the mechanical enforcement in `do_create()` should be generalized to check config rather than hardcoding `session_summary`. This is acceptable tech debt for now.

---

## 7. Final Recommended Approach

| Priority | Change | Files Modified | Risk |
|----------|--------|----------------|------|
| 1 (HIGH) | Dynamic retirement cap with floor | `memory_enforce.py` | Low -- formula is simple and testable |
| 2 (HIGH) | Mechanical enforcement via subprocess in do_create() | `memory_write.py` | Medium -- subprocess + lock ordering |
| 3 (LOW) | Config validation for max_retained < 1 | `memory_enforce.py` | Trivial |
| 4 (LOW) | Document empty created_at sort behavior | `memory_enforce.py` | Trivial |
| 5 (LOW) | Update SKILL.md with belt-and-suspenders note | `SKILL.md` | Trivial |
| 6 (LOW) | Add --max-retire CLI flag | `memory_enforce.py` | Low |

### Implementation order:
1. Change 1 (dynamic cap) + Change 3 (config validation) + Change 4 (comment) + Change 6 (CLI flag) -- all in `memory_enforce.py`
2. Change 2 (mechanical enforcement) -- in `memory_write.py`
3. Change 5 (SKILL.md update)
4. Add new tests (Tests A-E)
5. Run full test suite: `pytest tests/ -v`
6. One-time ops cleanup: rebuild index for the ops project

### Immediate ops project recovery (before code fix):
```bash
# Rebuild stale index
python3 hooks/scripts/memory_index.py --rebuild --root /home/idnotbe/projects/ops/.claude/memory

# Verify current state (should show 5 active, 62 retired)
python3 hooks/scripts/memory_enforce.py --category session_summary --dry-run
```

The retired files (62) are correctly in grace period and will remain on disk until archival is implemented (RC4). This is acceptable -- they are already excluded from the index and retrieval.
