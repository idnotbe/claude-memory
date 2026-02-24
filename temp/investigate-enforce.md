# Investigation: memory_enforce.py -- Session Overflow Bug

**Date:** 2026-02-24
**Symptom:** 67 active session files accumulated in ops project (expected max: 5)

---

## 1. Code Flow Summary

### Entry Point

`memory_enforce.py` is a standalone CLI script (NOT a hook). It is invoked as:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_enforce.py" --category session_summary
```

### Execution Flow

1. **CLI parsing** (`main()`, line 280-317):
   - Required: `--category` (one of the 6 CATEGORY_FOLDERS keys)
   - Optional: `--max-retained N` (CLI override), `--dry-run`
   - Validates `--max-retained >= 1`

2. **Root discovery** (`_resolve_memory_root()`, line 49-71):
   - Checks `$CLAUDE_PROJECT_ROOT` env var first
   - Falls back to walking CWD upward looking for `.claude/memory/`
   - Hard exits if not found

3. **Config reading** (`_read_max_retained()`, line 78-101):
   - Priority: CLI override > `memory-config.json` (`categories.<name>.max_retained`) > DEFAULT_MAX_RETAINED (5)
   - Handles missing config, JSONDecodeError, OSError gracefully
   - Validates type: rejects booleans and non-integers (line 90)

4. **Core enforcement** (`enforce_rolling_window()`, line 170-273):
   - Resolves the category folder name via `CATEGORY_FOLDERS` dict
   - **Dry-run path** (line 201-223): Scans, computes excess, prints what would retire, returns `dry_run: True`
   - **Real path** (line 225-273):
     - Acquires `FlockIndex` lock (strict: calls `require_acquired()`)
     - Scans for active sessions via `_scan_active()`
     - Computes `excess = len(active) - max_retained`
     - Caps at `MAX_RETIRE_ITERATIONS = 10` (safety valve)
     - Iterates oldest-first, calling `retire_record()` for each
     - FileNotFoundError: continues (file disappeared)
     - Other Exception: breaks loop (structural error)
   - Returns JSON: `{"retired": [...], "active_count": N, "max_retained": N}`

5. **Active session scanning** (`_scan_active()`, line 108-137):
   - Globs `*.json` in the category directory
   - Filters to `record_status == "active"` (or absent, for pre-v4 compat)
   - Sorts by `(created_at, filename)` -- oldest first

6. **Retirement** (delegated to `memory_write.retire_record()`, line 893-957):
   - Sets `record_status = "retired"`, `retired_at`, `retired_reason`
   - Adds change entry to `changes[]`
   - Atomically writes the file
   - Removes entry from `index.md`
   - Idempotent: returns `already_retired` if already retired

---

## 2. How memory_enforce.py Is Invoked

### Finding: NOT a hook -- Agent-interpreted instruction only

**memory_enforce.py is NOT registered in `hooks/hooks.json`.** It is not called automatically by any hook or script. The hooks.json file contains exactly 5 hooks:
- Stop: `memory_triage.py`
- PreToolUse:Write: `memory_write_guard.py`
- PreToolUse:Bash: `memory_staging_guard.py`
- PostToolUse:Write: `memory_validate_hook.py`
- UserPromptSubmit: `memory_retrieve.py`

None of these call `memory_enforce.py`.

### The only invocation mechanism is SKILL.md instructions

In `skills/memory-management/SKILL.md` (line 204-210), after Phase 3 saves:

```
After all saves, if session_summary was created, enforce the rolling window:

python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_enforce.py" --category session_summary

This replaces the previous inline Python enforcement.
```

**This is an agent-interpreted instruction.** It depends on the LLM (Claude) reading SKILL.md and deciding to execute the command after creating a session summary. There is NO mechanical guarantee that the LLM will:
1. Read the SKILL.md instructions
2. Follow them correctly
3. Remember to call enforce after session saves
4. Actually execute the bash command

### ROOT CAUSE #1: Reliance on LLM compliance for a critical invariant

The rolling window enforcement is a mechanical invariant (max N active sessions) that depends entirely on LLM instruction-following. If the LLM skips the call, forgets, encounters an error earlier in Phase 3 that prevents reaching the enforce step, or the skill isn't triggered, sessions accumulate without limit.

---

## 3. Identified Bugs and Issues

### BUG #1 (CRITICAL): MAX_RETIRE_ITERATIONS = 10 prevents full cleanup

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`, line 41, 208, 235

```python
MAX_RETIRE_ITERATIONS = 10  # Safety valve: never retire more than this in one run
...
excess = min(excess, MAX_RETIRE_ITERATIONS)
```

With 67 active sessions and `max_retained = 5`, the excess is 62. But the safety valve caps retirement at 10 per invocation. This means:
- **Run 1:** Retires 10 sessions (57 remain active)
- **Run 2:** Retires 10 sessions (47 remain active)
- **Run 3:** Retires 10 sessions (37 remain active)
- **Run 4:** Retires 10 sessions (27 remain active)
- **Run 5:** Retires 10 sessions (17 remain active)
- **Run 6:** Retires 10 sessions (7 remain active)
- **Run 7:** Retires 2 sessions (5 remain active)

**It takes 7 separate invocations to clean up 67 sessions down to 5.**

Even if enforce runs after every session creation, the accumulation happened because enforce wasn't being called consistently (see ROOT CAUSE #1). Now, even when called once, it cannot fully rectify the overflow in a single run.

The safety valve was designed to limit blast radius, but it makes recovery from accumulated overflow very slow. The `--max-retained` CLI override does NOT bypass this cap.

### BUG #2 (MEDIUM): Empty `created_at` sorts to the front

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`, line 131-136

```python
results.append({
    ...
    "created_at": data.get("created_at", ""),
})
# Sort oldest first; filename as tiebreaker
results.sort(key=lambda s: (s["created_at"], s["path"].name))
```

If a session file has a missing or empty `created_at` field, it gets `""` as the value. Since `""` sorts before any ISO 8601 timestamp string, **files with missing timestamps are always treated as the oldest and retired first**. This is arguably correct behavior (retire unknowns first), but it's implicit and undocumented. If a legitimate new session has a missing `created_at` due to a write bug, it would be incorrectly retired as "oldest."

### BUG #3 (LOW): No validation that max_retained from config is >= 1

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py`, line 78-101

The CLI path validates `--max-retained >= 1` (line 304), but `_read_max_retained()` does NOT validate the config-sourced value is >= 1. A config with `"max_retained": 0` would set `max_retained = 0`, and `excess = len(active) - 0` would try to retire ALL sessions (capped at 10 by safety valve). This is mitigated by the safety valve but is still a correctness issue.

The boolean check (line 90) was added to fix a known issue where `"max_retained": true` silently became 1 in Python (since `bool` is a subtype of `int`). This is now handled correctly.

### NON-BUG: retire_record() works correctly

The `retire_record()` function in `memory_write.py` (line 893-957) is well-implemented:
- Sets all retirement fields correctly
- Handles already-retired idempotently
- Blocks archived -> retired (requires unarchive first)
- Computes relative path from `memory_root.parent.parent` (not CWD)
- Atomically writes the file
- Removes from index

### NON-BUG: Sorting logic is correct

The sort key `(created_at, path.name)` correctly sorts oldest first. ISO 8601 timestamps with `Z` suffix sort correctly as strings. The filename tiebreaker handles equal timestamps deterministically.

### NON-BUG: FlockIndex locking works correctly

The lock is acquired at the start, `require_acquired()` raises TimeoutError if not held, and the entire scan-retire cycle happens under the lock. No TOCTOU issues within a single run.

---

## 4. Dry-Run Capability

**Yes, `--dry-run` mode exists and works correctly.**

```bash
python3 hooks/scripts/memory_enforce.py --category session_summary --dry-run
```

Dry-run behavior (lines 201-223):
- Scans active sessions
- Computes excess
- Caps at `MAX_RETIRE_ITERATIONS = 10`
- Prints `[ROLLING_WINDOW] Would retire: <id> (created: <timestamp>)` to stderr for each
- Runs `_deletion_guard()` for each (advisory warnings to stderr)
- Returns JSON to stdout with `"dry_run": true`
- **Does NOT acquire the FlockIndex lock** (no lock needed for read-only)
- **Does NOT modify any files**

**Important caveat:** Due to `MAX_RETIRE_ITERATIONS = 10`, dry-run will only show the first 10 sessions that would be retired, not the full excess. For 67 sessions with `max_retained=5`, it shows 10, not 62.

---

## 5. Recommended Fixes

### Fix 1 (CRITICAL): Add mechanical enforcement via hook or post-write trigger

The root cause is that enforcement depends on LLM instruction-following. Two options:

**Option A (Recommended): Add enforcement call inside `memory_write.py` itself**

After a successful `do_create()` for category `session_summary`, automatically call `enforce_rolling_window()`. This makes enforcement mechanical -- every session create triggers enforcement, regardless of whether the LLM follows SKILL.md instructions.

```python
# In do_create(), after the successful write:
if args.category == "session_summary":
    from memory_enforce import enforce_rolling_window
    max_retained = _read_max_retained_from_config(memory_root)
    enforce_rolling_window(memory_root, "session_summary", max_retained)
```

**Option B: Add enforcement as a PostToolUse:Bash hook**

Register a hook that detects when `memory_write.py --action create --category session_summary` completes and triggers enforcement. More complex and fragile than Option A.

### Fix 2 (HIGH): Increase or remove MAX_RETIRE_ITERATIONS for recovery

For the immediate overflow cleanup, either:
- Run the script 7 times in succession, or
- Temporarily modify `MAX_RETIRE_ITERATIONS` to a higher value (e.g., 100)
- Better: add a `--max-retire` CLI flag to override the safety valve for manual cleanup

Long-term, consider whether the safety valve of 10 is too low. If `max_retained` is 5 and a user creates 20 sessions before enforce runs, the first invocation should be able to clean up. A value of 20-30 would be more practical while still providing blast-radius protection.

### Fix 3 (LOW): Validate config-sourced max_retained >= 1

```python
def _read_max_retained(memory_root, category, cli_override):
    ...
    if isinstance(value, bool) or not isinstance(value, int):
        ...
        return DEFAULT_MAX_RETAINED
    if value < 1:
        print(f"[WARN] max_retained must be >= 1, got {value}. Using default.", ...)
        return DEFAULT_MAX_RETAINED
    return value
```

### Fix 4 (LOW): Document empty created_at behavior

Add a comment in `_scan_active()` explicitly noting that empty/missing `created_at` sorts before all valid timestamps, so such files are retired first. This is probably the desired behavior but should be documented.

---

## 6. Summary Table

| Issue | Severity | Type | Impact |
|-------|----------|------|--------|
| No mechanical invocation (LLM-only) | CRITICAL | Architecture | Root cause of overflow: enforce is never called if LLM skips it |
| MAX_RETIRE_ITERATIONS = 10 cap | HIGH | Bug | Cannot clean up >10 excess sessions per run; recovery requires 7 runs for 67 sessions |
| No config validation for max_retained >= 1 | LOW | Bug | Config `max_retained: 0` could retire all sessions (capped at 10) |
| Empty created_at sorts to front | LOW | Edge case | Undocumented behavior; correct in most cases |

### Immediate Action for ops project overflow:

```bash
# Preview (shows first 10 of 62):
python3 hooks/scripts/memory_enforce.py --category session_summary --dry-run

# Run enforcement 7 times to clean up all 62 excess sessions:
for i in $(seq 1 7); do
  python3 hooks/scripts/memory_enforce.py --category session_summary
done
```

Or temporarily set `MAX_RETIRE_ITERATIONS = 100` in the script, run once, then revert.

---

## 7. File References

| File | Absolute Path |
|------|---------------|
| memory_enforce.py | `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_enforce.py` |
| memory_write.py | `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_write.py` |
| hooks.json | `/home/idnotbe/projects/claude-memory/hooks/hooks.json` |
| SKILL.md | `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md` |
| Default config | `/home/idnotbe/projects/claude-memory/assets/memory-config.default.json` |
| Rolling window tests | `/home/idnotbe/projects/claude-memory/tests/test_rolling_window.py` |
| Overflow fix prompt | `/home/idnotbe/projects/claude-memory/temp/session-overflow-fix-prompt.md` |
