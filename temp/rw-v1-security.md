# Rolling Window Security Review (V1)

**Reviewer**: v1-security
**Files reviewed**:
- `hooks/scripts/memory_write.py` (FlockIndex, require_acquired(), retire_record())
- `hooks/scripts/memory_enforce.py` (new rolling window enforcement)
- `tests/test_rolling_window.py` (24 test cases)

**Spec**: `prompt-rolling-window-option1.md`
**All 24 tests**: PASS

---

## 1. Path Traversal

### 1A. `_resolve_memory_root()` -- SAFE

**Analysis**: The function uses two strategies:
1. `CLAUDE_PROJECT_ROOT` env var + appending `.claude/memory/`
2. CWD upward walk looking for `.claude/memory/` as a directory

Both strategies only return a path if `candidate.is_dir()` is true. An attacker would need to control the environment variable OR create a `.claude/memory/` directory higher in the filesystem hierarchy. The env var is set by Claude Code, not user input. The CWD walk stops at filesystem root.

**Residual risk**: If an attacker can create `/tmp/.claude/memory/` and the script runs with CWD under `/tmp/`, it would find the wrong root. However, this is defense-in-depth: `memory_enforce.py` only retires files within that root, so the blast radius is confined to that directory.

**Rating**: **SAFE**

### 1B. `_scan_active()` -- SAFE

**Analysis**: Uses `category_dir.glob("*.json")` which is bounded to the specific directory (no recursive traversal). Filenames come from the filesystem, not user input. The function only reads files, never writes. Malicious filenames with special characters would be harmless since they're only used as Path objects and JSON is loaded with strict parsing.

**Rating**: **SAFE**

### 1C. `retire_record()` rel_path computation -- SAFE

**Analysis**: Uses `memory_root.parent.parent` (project root) to compute relative path, not CWD. The `target_abs.relative_to(project_root)` call will raise `ValueError` if the target is not under the project root. Per the spec, this ValueError is intentionally NOT caught -- it propagates up, which is the correct fail-closed behavior.

```python
project_root = memory_root.parent.parent  # .claude/memory -> .claude -> project root
rel_path = str(target_abs.relative_to(project_root))
```

**Test coverage**: Test 21 validates this. If target_abs were somehow outside the project root, ValueError would propagate and the enforcement loop in `enforce_rolling_window()` would catch it as a generic `Exception` and break the loop with a warning. Files already processed would remain retired. Correct behavior.

**Rating**: **SAFE**

### 1D. `memory_root.parent.parent` assumption -- CONCERN (Low)

**Analysis**: This assumes the memory root is always exactly at `<project>/.claude/memory/`. If the memory directory structure were ever non-standard (e.g., symlinked, or nested differently), this would compute the wrong project root.

In practice, the plugin always creates `.claude/memory/` at the project root, and `_resolve_memory_root()` enforces this convention. But `retire_record()` is a public API that accepts any `memory_root` Path -- a caller passing a non-standard path could produce incorrect relative paths for index removal.

**Mitigation**: The `relative_to()` call would succeed but produce a wrong path, causing `remove_from_index()` to silently fail (no matching entry). The memory file would be retired but its index entry would remain as an orphan. This is a correctness issue, not a security vulnerability.

**Rating**: **CONCERN** (Low severity -- orphaned index entries, no data loss or unauthorized access)

---

## 2. Race Conditions (TOCTOU)

### 2A. Scan -> retire cycle atomicity -- SAFE

**Analysis**: The entire scan-retire cycle in `enforce_rolling_window()` runs under a single `FlockIndex` lock:

```python
with FlockIndex(index_path) as lock:
    lock.require_acquired()  # STRICT: raises if lock not held
    active = _scan_active(category_dir)
    # ... retire loop ...
```

The lock is held for the entire duration. No other process using FlockIndex can modify the index concurrently. The `require_acquired()` call ensures the lock is actually held before proceeding.

**Rating**: **SAFE**

### 2B. File change between scan and retire -- SAFE

**Analysis**: A file could theoretically be modified between `_scan_active()` and `retire_record()` by a process that does NOT use the lock (e.g., raw file write). However:
1. All legitimate mutation paths go through `memory_write.py` which uses `FlockIndex`
2. `retire_record()` re-reads the file from disk before modifying (not using cached data from scan)
3. If the file status changed to "retired" between scan and retire, `retire_record()` returns `{"status": "already_retired"}` -- idempotent
4. If the file is deleted, `FileNotFoundError` is caught and the loop continues

**Rating**: **SAFE**

### 2C. Lock timeout behavior -- SAFE

**Analysis**: The `require_acquired()` method raises `TimeoutError` if the lock was not acquired. This is a strict enforcement -- unlike the legacy behavior where timed-out callers proceed without the lock. The `enforce_rolling_window()` function does NOT catch `TimeoutError` internally; it propagates to `main()` which exits with code 1.

The legacy callers (do_create, do_update, etc.) still use the old "proceed without lock" behavior. This is a known design decision documented in the spec (backward compatibility).

**Concern**: The legacy callers represent a theoretical race condition window -- if `do_create` times out on the lock while `enforce_rolling_window()` holds it, `do_create` proceeds without the lock and could modify the index concurrently. However, this pre-existing issue is OUT OF SCOPE for this review (it existed before the rolling window changes) and is documented in the spec as intentional backward compatibility.

**Rating**: **SAFE** (for the new code; pre-existing risk in legacy callers is acknowledged)

### 2D. Stale lock detection race -- CONCERN (Low)

**Analysis**: The stale lock detection in `FlockIndex.__enter__` has a small TOCTOU window:

```python
mtime = self.lock_dir.stat().st_mtime
if (time.time() - mtime) > self._STALE_AGE:
    try:
        os.rmdir(self.lock_dir)
    except OSError:
        pass
```

Between `stat()` and `rmdir()`, another process could:
1. Release and re-acquire the lock (stat would show new mtime, but rmdir would delete the new lock)
2. However, this is mitigated by the `continue` after rmdir -- the loop retries `os.mkdir()`, and the worst case is both processes briefly believe they hold the lock

In practice, stale locks only happen when a process crashes (unclean exit), and the 60-second stale age makes this race window extremely unlikely during normal operation.

**Rating**: **CONCERN** (Low severity -- very narrow race window, only during crash recovery)

---

## 3. Input Validation

### 3A. `--category` validation -- SAFE

**Analysis**: Uses `argparse.choices=list(CATEGORY_FOLDERS.keys())`. Argparse rejects unknown values before `main()` is reached. The `CATEGORY_FOLDERS` dict is hardcoded with 6 known categories.

Additionally, `enforce_rolling_window()` calls `CATEGORY_FOLDERS.get(category)` and exits if the category is unknown. Double validation.

**Rating**: **SAFE**

### 3B. Config file manipulation -- CONCERN (Low)

**Analysis**: `_read_max_retained()` reads `memory-config.json` with no integrity check. A malicious config could set `max_retained` to 1, causing aggressive retirement of memories. However:

1. `MAX_RETIRE_ITERATIONS = 10` caps retirements per run, limiting blast radius
2. Retirement is a soft operation (sets `record_status="retired"`, preserves data for 30-day grace period)
3. Config manipulation requires write access to the project directory, which implies the attacker already has full project access

The config value can be any JSON type. If it's not an integer, the `.get()` chain returns `DEFAULT_MAX_RETAINED` (5) -- no crash.

```python
return config.get("categories", {}).get(category, {}).get("max_retained", DEFAULT_MAX_RETAINED)
```

If `max_retained` is a string like `"999"`, it passes through as a string. The `len(active) - max_retained` comparison would raise `TypeError`. This is caught by the generic `except Exception` in the enforcement loop... wait, no -- this would happen before the loop, in the `excess = len(active) - max_retained` line. Let me trace the flow:

Actually, the `max_retained` value from config flows into `enforce_rolling_window()` as the `max_retained` parameter. If it's a non-integer (e.g., string), `excess = len(active) - max_retained` raises `TypeError`, which propagates uncaught from `enforce_rolling_window()`, and since `main()` only catches `TimeoutError`, the script crashes with a traceback. This is fail-closed behavior (no retirements happen), which is safe.

If `max_retained` is a float like `0.5`, the subtraction works but `active[:excess]` with a float slice raises `TypeError`. Again, fail-closed.

If `max_retained` is a very large negative number, `excess = len(active) - (-1000000)` would be huge, but `min(excess, MAX_RETIRE_ITERATIONS)` caps it at 10. Safe.

**Rating**: **CONCERN** (Low severity -- non-integer config values cause a crash, but fail-closed; integer values are capped by MAX_RETIRE_ITERATIONS)

### 3C. JSON parsing errors -- SAFE

**Analysis**: Both `_scan_active()` and `_read_max_retained()` catch `json.JSONDecodeError` and `OSError`. Corrupted files are skipped with warnings. No infinite loops possible.

**Rating**: **SAFE**

### 3D. `--max-retained` from CLI -- SAFE

**Analysis**: `argparse` with `type=int` rejects non-integer input. The `args.max_retained < 1` check rejects zero and negatives. The CLI override bypasses config entirely via `_read_max_retained()`.

Tests 14 and 15 verify this.

**Rating**: **SAFE**

---

## 4. Lock Safety

### 4A. `require_acquired()` -- SAFE

**Analysis**: Simple boolean check on `self.acquired`. The `acquired` flag is set to `True` only in the `os.mkdir()` success path. All failure paths (FileExistsError timeout, OSError) leave it as `False`. No way to bypass.

**Rating**: **SAFE**

### 4B. Lock breaks during enforcement -- SAFE

**Analysis**: If the lock directory is externally deleted while enforcement runs, the lock semantics break silently. However:
1. `__exit__` does `os.rmdir()` which fails silently if already removed
2. Another process could then acquire the lock while enforcement still believes it holds it
3. This requires active interference (someone running `rmdir .index.lockdir` during enforcement)

This is a pre-existing design limitation of directory-based locks, not introduced by this change.

**Rating**: **SAFE** (pre-existing, not a regression)

### 4C. MAX_RETIRE_ITERATIONS bypass -- SAFE

**Analysis**: `MAX_RETIRE_ITERATIONS = 10` is applied via `excess = min(excess, MAX_RETIRE_ITERATIONS)`. Since `excess` is an integer computed from `len(active) - max_retained`, and the loop iterates `active[:excess]`, the cap is enforced mathematically. No way to bypass without modifying the source.

The constant is module-level, not configurable via config file or CLI. Would require code modification to change.

**Rating**: **SAFE**

---

## 5. Denial of Service

### 5A. Large number of files in `_scan_active()` -- CONCERN (Low)

**Analysis**: `_scan_active()` reads ALL `.json` files in the category directory. With thousands of files, this could be slow due to:
1. `sorted(category_dir.glob("*.json"))` -- O(n log n) sort
2. Each file is opened, read, and JSON-parsed
3. Results list grows linearly

However:
1. `MAX_RETIRE_ITERATIONS = 10` means only 10 files are ever retired per run
2. The scan time is bounded by disk I/O, not CPU
3. An attacker creating thousands of files requires write access to the memory directory
4. This is a local-only tool, not network-exposed

With 10,000 files of ~1KB each, the scan would take a few seconds at most. Inconvenient but not a real DoS vector.

**Rating**: **CONCERN** (Low severity -- performance degradation with extreme file counts, but not exploitable remotely)

### 5B. Lock contention -- SAFE

**Analysis**: Lock timeout is 15 seconds. If contention prevents acquisition, `require_acquired()` raises `TimeoutError`, and the script exits cleanly with code 1. No resource leak, no hang. The caller (Claude Code agent) can retry.

Multiple concurrent enforcement attempts would serialize via the lock. At most one proceeds; others timeout and exit. No deadlock possible (single lock, no nesting).

**Rating**: **SAFE**

---

## 6. Additional Security Observations

### 6A. Venv bootstrap chain -- SAFE

**Analysis**: `memory_enforce.py` re-execs via `os.execv()` if pydantic is not importable. The venv path is computed relative to `__file__`, not user input:

```python
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
```

This is the same pattern used in `memory_write.py`. The path resolves to the plugin's installation directory. An attacker would need to place a malicious `python3` binary in the plugin's `.venv/bin/` directory, which requires write access to the plugin installation -- a higher privilege level than what this script operates at.

**Rating**: **SAFE**

### 6B. sys.path manipulation -- SAFE

**Analysis**: `sys.path.insert(0, _script_dir)` adds the scripts directory. This is needed for `from memory_write import ...`. The directory path is computed from `__file__`, not user input. Same pattern as `memory_draft.py`.

**Rating**: **SAFE**

### 6C. `retire_record()` does not re-validate data -- CONCERN (Low)

**Analysis**: `retire_record()` reads JSON, modifies fields, and writes back without Pydantic validation. If the file contains non-schema-conformant data (e.g., from a pre-validation-era write or manual editing), `retire_record()` preserves the invalid structure.

However, retirement is a status change, not a content operation. The data is already on disk. Writing it back with modified status fields does not increase the attack surface. And the original `do_retire()` also did not validate before this refactor.

**Rating**: **CONCERN** (Low severity -- pre-existing, not a regression)

### 6D. Dry-run information disclosure -- SAFE

**Analysis**: Dry-run mode prints session IDs and created_at timestamps to stderr. This is intentional (user-requested `--dry-run` output). No sensitive content from the memory files is exposed -- only IDs and timestamps.

**Rating**: **SAFE**

### 6E. Error messages in retire loop -- SAFE

**Analysis**: Exception messages are printed to stderr. For `FileNotFoundError`, the message includes the file path. For generic `Exception`, the message could contain arbitrary content if the JSON data triggers an unexpected error. However, stderr output is local-only and not exposed to external systems.

**Rating**: **SAFE**

### 6F. `enforce_rolling_window()` calls `sys.exit(1)` for unknown category -- CONCERN (Low)

**Analysis**: Line 182-183:
```python
if not folder_name:
    print(f"ERROR: Unknown category '{category}'", file=sys.stderr)
    sys.exit(1)
```

This calls `sys.exit()` from a library function, which means if `enforce_rolling_window()` is ever imported and called programmatically (not via CLI), an unknown category would kill the caller's process. The CLI's argparse `choices` validation prevents this in normal use, but it's a design smell.

**Rating**: **CONCERN** (Low severity -- defensive programming issue, not exploitable)

---

## 7. Test Coverage Assessment

### Strengths
- Tests 1-15 cover all enforce scenarios from the spec
- Tests 16-24 cover FlockIndex and retire_record changes
- Mock-based tests (8, 9, 13) properly simulate failure modes
- Tests 14-15 use subprocess for real CLI validation (more realistic than mocking argparse)
- Test 21 validates the critical rel_path computation
- Test 24 uses source-code scanning to verify the FlockIndex rename (meta-test)

### Gaps (no security vulnerability, but coverage could improve)
1. **No test for config with non-integer `max_retained`**: A string or float value from config would cause a TypeError crash. Should test that this fails cleanly.
2. **No test for symlinked memory root**: If `.claude/memory/` is a symlink, `parent.parent` may not point to the project root.
3. **No test for very large `max_retained` from config**: e.g., `max_retained: 999999` should work fine (no retirements), but untested.
4. **No test for `_deletion_guard()` output**: The advisory warning is printed but not verified.
5. **No concurrency test**: Two concurrent `enforce_rolling_window()` calls to verify serialization.

---

## Summary

| Area | Rating | Severity | Notes |
|------|--------|----------|-------|
| Path traversal: `_resolve_memory_root()` | SAFE | -- | Env var + CWD walk with is_dir check |
| Path traversal: `_scan_active()` | SAFE | -- | Bounded glob, read-only |
| Path traversal: `retire_record()` rel_path | SAFE | -- | Fail-closed on ValueError |
| Path traversal: `parent.parent` assumption | CONCERN | Low | Orphaned index entry if non-standard root |
| TOCTOU: scan-retire atomicity | SAFE | -- | Single lock covers entire cycle |
| TOCTOU: file change between scan/retire | SAFE | -- | Re-reads file, idempotent checks |
| TOCTOU: lock timeout | SAFE | -- | require_acquired() is strict |
| TOCTOU: stale lock detection | CONCERN | Low | Narrow race window during crash recovery |
| Input: --category | SAFE | -- | argparse choices validation |
| Input: config manipulation | CONCERN | Low | Non-integer crash is fail-closed |
| Input: JSON errors | SAFE | -- | Caught and skipped |
| Input: --max-retained CLI | SAFE | -- | type=int + >= 1 check |
| Lock: require_acquired() | SAFE | -- | Simple boolean, no bypass |
| Lock: break during enforcement | SAFE | -- | Pre-existing limitation |
| Lock: MAX_RETIRE_ITERATIONS | SAFE | -- | Math-enforced cap, not configurable |
| DoS: large file count | CONCERN | Low | Performance degradation, not exploitable |
| DoS: lock contention | SAFE | -- | Clean timeout + exit |
| Venv bootstrap | SAFE | -- | Path from __file__, not user input |
| sys.path manipulation | SAFE | -- | Same pattern as memory_draft.py |
| retire_record() no re-validation | CONCERN | Low | Pre-existing, not a regression |
| sys.exit() in library function | CONCERN | Low | Design smell, CLI prevents in practice |

**Overall assessment**: **SAFE with minor concerns.** No vulnerabilities found. 6 low-severity concerns identified, none exploitable in practice. The implementation follows the spec correctly, maintains backward compatibility, and introduces strict lock enforcement for the new enforce path. The test suite covers all spec scenarios with 24 passing tests.

**No blocking issues for merge.**
