# A-01: Config Loading Order Bug -- Audit Report

**Date:** 2026-02-25
**Auditor:** Claude Opus 4.6
**Status:** CONFIRMED and FIXED
**Severity:** MEDIUM (data completeness -- observability gap)

---

## Bug Summary

In `hooks/scripts/memory_retrieve.py`, two early `emit_event()` calls passed `config=None` because the config file had not been loaded yet at those points in the execution flow. Since `emit_event()` calls `parse_logging_config(config if config is not None else {})`, passing `None` yields an empty dict `{}`, and `parse_logging_config({})` returns `{"enabled": False, ...}`. This means these events were **silently dropped even when the user had explicitly enabled logging** in their `memory-config.json`.

---

## Execution Path Analysis

### Pre-fix control flow in `main()`:

```
1. Read stdin, parse hook_input                    (lines 317-323)
2. Extract user_prompt, cwd                        (lines 325-326)
3. Extract session_id                              (line 329)
4. [BUG] Short prompt check -> emit_event(config=None)  (lines 332-338)
5. Compute memory_root, index_path                 (lines 340-342)
6. Rebuild index if missing                        (lines 346-356)
7. [BUG] Index missing check -> emit_event(config=None)  (lines 358-362)
8. Load config from disk -> _raw_config populated  (lines 370-376)  <-- TOO LATE
9. All subsequent emit_event() calls use config=_raw_config  (lines 379+)
```

### `parse_logging_config(None)` trace:

```python
# memory_logger.py line 43-52:
def parse_logging_config(config):
    if not isinstance(config, dict):       # None is not dict -> True
        return {"enabled": False, ...}     # Returns DISABLED immediately
```

### `emit_event()` with `config=None` trace:

```python
# memory_logger.py line 231:
log_cfg = parse_logging_config(config if config is not None else {})
# config is None, so passes {} to parse_logging_config
# parse_logging_config({}) -> "logging" not in {} -> log_cfg = {}
# log_cfg.get("enabled", False) -> False
# Returns {"enabled": False, ...}
```

Both paths (None directly, or None->{}->parse) result in `enabled: False`, so the event is never written to disk.

---

## Affected Call Sites

| # | Line (pre-fix) | Event Type | Reason | Impact |
|---|----------------|------------|--------|--------|
| 1 | 332-337 | `retrieval.skip` | `short_prompt` | Short/greeting prompts never logged. User loses visibility into how often retrieval is skipped due to short prompts. |
| 2 | 358-361 | `retrieval.skip` | `empty_index` | Missing/empty index events never logged. User loses visibility into index health issues (e.g., missing index.md, failed rebuilds). |

### Call sites that were NOT affected (post-config-load):

| Line (pre-fix) | Event Type | config= | Status |
|---|---|---|---|
| 379-383 | `retrieval.skip` (disabled) | `_raw_config` | OK |
| 419-422 | `retrieval.skip` (max_inject_zero) | `_raw_config` | OK |
| 437-440 | `retrieval.skip` (empty_index, post-parse) | `_raw_config` | OK |
| 471-485 | `retrieval.search` | `_raw_config` | OK |
| 519-524 | `retrieval.search` (judge debug) | `_raw_config` | OK |
| 533-542 | `retrieval.inject` | `_raw_config` | OK |
| 547-550 | `retrieval.skip` (no_fts5_results) | `_raw_config` | OK |
| 560-564 | `retrieval.search` (fts5_unavailable) | `_raw_config` | OK |
| 678-688 | `retrieval.inject` (legacy) | `_raw_config` | OK |

---

## Fix Applied

**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`

**Strategy:** Move `memory_root` computation and raw config loading to occur **before** the first `emit_event()` call. This is safe because:

1. `cwd` is already available (extracted from `hook_input` at line 326)
2. Config loading is a simple `json.load()` with fail-open semantics (OSError/JSONDecodeError caught)
3. No functional logic depends on config being loaded later -- the retrieval settings extraction block simply references `_raw_config` instead of loading it fresh

**Changes:**

1. Moved `memory_root = Path(cwd) / ".claude" / "memory"` from line 341 to line 335 (before first `emit_event`)
2. Moved `_raw_config` initialization and `config_path` loading from lines 370-376 to lines 336-343 (before first `emit_event`)
3. Changed both early `emit_event` calls from `config=None` to `config=_raw_config`
4. Replaced the old `if config_path.exists(): try: ... _raw_config = config` block with `if _raw_config: try:` since `_raw_config` is already loaded
5. Removed `json.JSONDecodeError` from the inner except clause (line 418) since JSON parsing now happens in the early load block; only `KeyError` and `OSError` remain relevant for the settings extraction block

**Lines changed:** ~15 lines modified, net +5 lines (added early load block, removed redundant load)

---

## Edge Cases Considered

### 1. Config file does not exist
- `config_path.exists()` returns False
- `_raw_config` remains `{}`
- `emit_event(..., config={})` -> `parse_logging_config({})` -> `enabled: False`
- Same behavior as before: logging disabled by default. No regression.

### 2. Config file exists but is invalid JSON
- `json.load()` raises `json.JSONDecodeError`
- Caught by `except (json.JSONDecodeError, OSError): pass`
- `_raw_config` remains `{}`
- Same behavior as before: fails open, logging disabled.

### 3. Config file exists but logging is not configured
- `_raw_config` has no `logging` key
- `parse_logging_config({"retrieval": {...}})` -> `"logging" not in config` -> treats config itself as log_cfg -> `get("enabled", False)` -> False
- Logging disabled. Correct behavior.

### 4. Config file exists and logging is enabled
- `_raw_config = {"logging": {"enabled": true, ...}, ...}`
- Early `emit_event()` calls now receive the full config
- `parse_logging_config(...)` returns `{"enabled": True, ...}`
- Events are written to disk. **This is the bug fix.**

### 5. Performance impact of early config load
- One additional `json.load()` call for the short-prompt exit path (previously exited before any config I/O)
- Config file is typically < 2KB, so parsing overhead is negligible (< 0.1ms)
- This is acceptable: the early-exit optimization was about avoiding the full retrieval pipeline, not about avoiding a tiny config read

### 6. Double config read eliminated
- The old code loaded config at line 374-376. The new code loads it at line 340-341 and the settings extraction block at line 382+ reuses `_raw_config` directly.
- Net result: config is loaded exactly once, same as before.

### 7. Interaction with lazy import fallback
- If `memory_logger.py` is missing, the fallback `emit_event` is a no-op (`def emit_event(*args, **kwargs): pass`). The early config load is harmless -- it just populates `_raw_config` which the no-op ignores.

---

## Verification

- Syntax check: `python3 -m py_compile hooks/scripts/memory_retrieve.py` -- PASS
- Full test suite: `pytest tests/ -v` -- 852/852 PASS (zero regressions)

---

## Conclusion

The bug hypothesis from the audit plan was **confirmed**. Two `emit_event()` calls at the top of `main()` were permanently silenced due to config not being loaded yet. The fix moves config loading earlier in the function, before any logging calls. The change is minimal, safe (fail-open preserved), and introduces no performance regression.
