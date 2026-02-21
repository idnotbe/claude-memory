# V2 Adversarial Review: Rolling Window Implementation

**Reviewer:** v2-adversarial
**Date:** 2026-02-21
**Approach:** Try to break it. Think like an attacker. Find what V1 missed.
**Result:** All 24 tests pass (1.33s). All 50 existing arch_fixes tests pass (19.20s). Both scripts compile. No blocking issues found. Several medium/low findings and test gaps identified.

---

## Summary of V1 Reviews

V1 correctness found 0 issues. V1 security found 6 low-severity concerns. V1 integration found 2 advisory documentation gaps. All three gave PASS verdicts.

---

## Adversarial Findings

### Finding 1: `do_retire()` output format changed from relative to absolute paths

**Severity: MEDIUM**
**Category: Spec Deviation / Behavioral Change**
**V1 missed this: YES (all 3 reviewers)**

Before the refactor, `do_retire()` returned:
```json
{"status": "retired", "target": ".claude/memory/sessions/foo.json", "reason": "..."}
```

After the refactor, `do_retire()` delegates to `retire_record()` which returns:
```json
{"status": "retired", "target": "/home/user/project/.claude/memory/sessions/foo.json", "reason": "..."}
```

The `target` field changed from a relative path (`str(target)` where `target = Path(args.target)`) to an absolute path (`str(target_abs)`). This is because `retire_record()` receives and returns `target_abs` (the absolute path), and `do_retire()` now passes the result directly to `print(json.dumps(result))` without converting back to relative.

The spec's example code for `do_retire()` shows this exact pattern, so the implementation **matches the spec**. However, the spec did not call out this behavioral change explicitly. The same applies to the `"already_retired"` return case.

**Impact**: The CLI consumer (the Claude Code agent) parses this JSON output. If any downstream logic depends on the `target` field being a relative path, it would break. In practice, the agent likely just displays it, so the impact is cosmetic. But this is an undocumented breaking change in the public CLI interface.

**No test covers this**: None of the 24 tests verify the `target` field format of `do_retire()`'s JSON output via CLI invocation. Test 20 calls `retire_record()` directly and doesn't check the target field's path format.

---

### Finding 2: No type validation on `max_retained` from config file

**Severity: MEDIUM**
**Category: Input Validation Gap**
**V1 security noted this partially but underestimated one vector**

`_read_max_retained()` returns whatever JSON type is stored in config. Tested attack vectors:

| Config value | Type returned | Behavior in `enforce_rolling_window()` |
|---|---|---|
| `"3"` (string) | `str` | `len(active) - "3"` -> **TypeError** (uncaught, traceback) |
| `2.5` (float) | `float` | `len(active) - 2.5` -> float excess -> `active[:float]` -> **TypeError** (uncaught) |
| `null` | `NoneType` | `len(active) - None` -> **TypeError** (uncaught) |
| `true` (bool) | `bool` | `6 - True` = `5` (bool is int in Python). **max_retained=1** silently. |

The **boolean case** is the most dangerous: `true` in JSON config silently becomes `max_retained=1`, which could cause aggressive retirement. Unlike string/float/null (which crash fail-closed), boolean passes silently and retires memories.

V1 security noted that non-integer values crash (fail-closed), which is correct for string/float/null. But they missed that `bool` is a subtype of `int` in Python and passes through without error.

**Proof**: `isinstance(True, int)` returns `True` in Python. `6 - True` = `5`. The CLI validation (`args.max_retained < 1`) would catch `True` as `1 >= 1` (passes). But config-sourced `True` never hits CLI validation.

**Fix**: Add `isinstance(value, int) and not isinstance(value, bool)` check in `_read_max_retained()`, or coerce with `int()` and validate range.

---

### Finding 3: `MAX_RETIRE_ITERATIONS` safety valve is never tested

**Severity: LOW**
**Category: Test Gap**
**V1 missed this: YES**

`MAX_RETIRE_ITERATIONS = 10` is applied via `excess = min(excess, MAX_RETIRE_ITERATIONS)` in both dry-run and real enforcement paths. However, no test ever creates more than 8 sessions, so `excess` never exceeds 5 in any test. The safety valve code path (`min` actually capping the value) is never exercised.

**Suggested test**: 15 sessions, `max_retained=1` -> should retire exactly 10 (capped), not 14.

---

### Finding 4: Test 10 (dry-run) does not verify index unchanged

**Severity: LOW**
**Category: Test Gap**
**V1 missed this: YES**

Test 10 verifies that session files are not modified during dry-run, but does not verify that `index.md` is also unchanged. The dry-run code path correctly avoids touching the index (no `FlockIndex` context, no `retire_record` calls), so this is not a bug -- but the test should assert this explicitly for defense-in-depth.

---

### Finding 5: Test 09 has incomplete assertions

**Severity: LOW**
**Category: Test Weakness**
**V1 missed this: YES**

Test 09 (file disappears between scan and retire) asserts that `len(result["retired"]) == 1` and `result["retired"][0] == "session-001"`. However, it does NOT:
1. Assert `result["active_count"]` (should be 6, since victim 0 was skipped and victim 1 was retired out of 7)
2. Verify that `session-000` was left untouched on disk (its file should still be active)

The test adequately tests the loop control flow (continue on FileNotFoundError) but could be more thorough.

---

### Finding 6: `enforce_rolling_window()` uses `sys.exit(1)` for unknown category

**Severity: LOW**
**Category: Design / Spec Compliance**
**V1 security noted this (6F)**

The function calls `sys.exit(1)` for unknown categories. This is unreachable via CLI (argparse `choices` validates first) but would kill the process if called programmatically. The spec explicitly shows this pattern, so it matches. But it violates the principle that library functions should raise exceptions, not exit.

No test covers this code path because argparse prevents it. A programmatic test would need to call `enforce_rolling_window()` directly with an invalid category.

---

### Finding 7: `retire_record()` does not check for `already_retired` return in enforce loop

**Severity: INFO**
**Category: Defensive Programming**

In `enforce_rolling_window()`, after calling `retire_record()`, the code always appends `victim["id"]` to `retired_list` regardless of the return dict's `status` field:

```python
result = retire_record(...)
retired_list.append(victim["id"])  # Always appends, even if "already_retired"
```

If `retire_record()` returns `{"status": "already_retired"}`, the victim is counted as retired in the output, inflating the retirement count. In practice, this cannot happen because `_scan_active()` only returns files with `record_status == "active"` and the entire operation runs under a lock. But defensive code would check `result["status"]`.

---

### Finding 8: `_deletion_guard()` output is never tested

**Severity: INFO**
**Category: Test Gap**
**V1 security noted this (test gap #4)**

`_deletion_guard()` prints advisory warnings to stderr when sessions contain `completed`, `blockers`, or `next_actions` content. No test verifies this output. The function is advisory-only (does not block retirement), so this is low-priority, but stderr output should be at least spot-checked.

---

### Finding 9: No test for non-`session_summary` categories

**Severity: INFO**
**Category: Test Gap**

All 15 enforce tests use `session_summary`. The code supports all 6 categories via `CATEGORY_FOLDERS`. A single test using e.g. `decision` would verify that category-to-folder mapping works end-to-end for a non-default category.

---

## Concurrency Analysis

### Lock Correctness

`enforce_rolling_window()` holds `FlockIndex` for the entire scan-retire cycle. `require_acquired()` ensures the lock is actually held. No double-locking: `retire_record()` does not acquire the lock.

### Pre-existing Race: Legacy Callers

The legacy callers (`do_create`, `do_update`, etc.) still proceed without the lock on timeout. If `enforce_rolling_window()` holds the lock for an extended period (scanning many files + retiring), a concurrent `do_create` could timeout and proceed without the lock, potentially causing index corruption. This is a pre-existing issue NOT introduced by this change, and is documented in the spec as intentional backward compatibility.

### Stale Lock Detection Race

V1 security noted a narrow TOCTOU window in stale lock detection. Confirmed: between `stat()` and `rmdir()`, another process could release and re-acquire the lock, causing the stale detector to break a valid lock. This is pre-existing and extremely unlikely (60-second stale age).

---

## Regression Check

- All 24 rolling window tests: **PASS** (1.33s)
- All 50 existing arch_fixes tests: **PASS** (19.20s)
- `python3 -m py_compile memory_enforce.py`: **OK**
- `python3 -m py_compile memory_write.py`: **OK**
- No remaining `_flock_index` references in `hooks/scripts/`: **CONFIRMED**
- `_flock_index` reference in `tests/test_arch_fixes.py:500`: In a docstring comment only, not executable code. **SAFE**

---

## Verdict

**No CRITICAL issues found. No blocking issues for merge.**

| ID | Severity | Finding | V1 Missed? |
|----|----------|---------|------------|
| F1 | MEDIUM | `do_retire()` output changed from relative to absolute paths (undocumented breaking change) | Yes (all 3) |
| F2 | MEDIUM | Config `max_retained: true` silently becomes 1 (bool is int in Python) | Partially (security noted type issue but missed bool) |
| F3 | LOW | `MAX_RETIRE_ITERATIONS` safety valve never tested | Yes |
| F4 | LOW | Test 10 dry-run does not verify index unchanged | Yes |
| F5 | LOW | Test 09 missing `active_count` and file-state assertions | Yes |
| F6 | LOW | `sys.exit(1)` in library function, no test for unknown category | Noted by security but no test gap identified |
| F7 | INFO | `retire_record` return status not checked in enforce loop | Yes |
| F8 | INFO | `_deletion_guard()` stderr output never tested | Noted by security |
| F9 | INFO | No test for non-session_summary categories | Yes |

**Recommendation**: Fix F1 (the output format change) by having `do_retire()` convert the target back to a relative path before printing, or document it as an intentional change. Fix F2 by adding type checking in `_read_max_retained()`. The remaining findings are test gaps that should be addressed but don't block the merge.
