# Phase 2 V2R2: Full Diff Review

**Date:** 2026-02-28
**Reviewer:** v2r2-diff agent (Opus 4.6) + Gemini 3.1 Pro (PAL clink cross-validation)
**Verdict:** PASS_WITH_FIXES

## Files Reviewed

1. `CLAUDE.md` -- Updated references to file-based triage_data
2. `hooks/scripts/memory_triage.py` -- `build_triage_data()`, `format_block_message()`, `_run_triage()` atomic write
3. `skills/memory-management/SKILL.md` -- Phase 3 rewrite (subagent save) + Pre-Phase cleanup update
4. `tests/test_memory_triage.py` -- New test classes: `TestBuildTriageData`, `TestFormatBlockMessageTriageDataPath`, `TestRunTriageWritesTriageDataFile`
5. `action-plans/plan-memory-save-noise-reduction.md` -- Progress tracking updates

## Test Results

982 passed in 77.87s -- all green.

---

## 1. Cross-File Consistency: PASS

All three code/doc files tell the same story consistently:

| Aspect | CLAUDE.md | memory_triage.py | SKILL.md |
|--------|-----------|-------------------|----------|
| File output | `triage-data.json` to staging | Writes to `.staging/triage-data.json` (line 1151-1153) | Phase 0 reads from `triage-data.json` (line 58) |
| Tag format | `<triage_data_file>` with `<triage_data>` fallback | `<triage_data_file>` (line 964) / `<triage_data>` (line 971) | `<triage_data_file>` first-try, `<triage_data>` fallback (lines 58-59) |
| Subagent save | "delegates save execution to a single foreground Task subagent (haiku)" | N/A (triage script only) | Phase 3 Step 2: "Spawn ONE foreground Task subagent (model: haiku)" (line 236) |
| Cleanup patterns | N/A | N/A | Pre-Phase (line 50) and Phase 3 (line 254) match exactly |

## 2. Regressions: PASS

- `build_triage_data()` preserves lowercase category normalization (`cat_lower = category.lower()`)
- `format_block_message()` backwards-compatible: default (no `triage_data_path` kwarg) produces inline `<triage_data>`, identical to pre-change behavior
- Human-readable message format unchanged (category list with scores and snippets)
- All 982 pre-existing tests continue to pass

## 3. Completeness: PASS

- SKILL.md Pre-Phase cleanup and Phase 3 subagent cleanup patterns are identical (both include `draft-*.json`, `input-*.json`, `new-info-*.txt`)
- SKILL.md Phase 3 error handling correctly uses Write tool (not Bash) for `.triage-pending.json` to avoid staging guard
- Result file path (`$HOME/.claude/last-save-result.json`) and atomic write pattern consistent between old Phase 3 and new subagent instructions
- CUD resolution table and verification rules unchanged

## 4. Edge Cases -- Atomic Write Logic: FAIL (2 bugs found)

### Bug A: File descriptor double-close (memory_triage.py:1161-1169)

**Severity:** Medium (swallowed but creates fd-reuse race in threaded scenarios)

```python
# CURRENT (buggy):
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(triage_data, f, indent=2)
except Exception:
    try:
        os.close(fd)  # BUG: fd already closed by `with` block's __exit__
    except OSError:
        pass
    raise
```

If `json.dump()` raises (e.g., `TypeError` for unserializable data), the `with` statement closes the file object (and underlying fd). Then the `except` block calls `os.close(fd)` again. The `OSError` is swallowed, but in a multi-threaded environment the fd number could have been reassigned.

**Note:** Same pattern pre-exists at line 828-836 (`write_context_files()`). Not introduced by this session but worth fixing together.

**Fix:**
```python
fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
try:
    f = os.fdopen(fd, "w", encoding="utf-8")
except Exception:
    os.close(fd)
    raise
with f:
    json.dump(triage_data, f, indent=2)
os.replace(tmp_path, triage_data_path)
```

### Bug B: UnboundLocalError on `tmp_path` (memory_triage.py:1174)

**Severity:** Low-Medium (extremely unlikely trigger, but fails to produce output if hit)

If an exception occurs before `tmp_path` is assigned at line 1155 (e.g., `MemoryError` during f-string construction), the outer `except Exception:` handler at line 1171 reaches `os.unlink(tmp_path)` at line 1174. Since `tmp_path` was never bound, this raises `UnboundLocalError`. Because `UnboundLocalError` is not `OSError`, it escapes the `except OSError:` guard at line 1175 and propagates up to `main()`'s blanket handler. The hook fails open (returns 0) but the blocking message is never printed -- categories are silently lost.

**Fix:** Initialize `tmp_path = None` before the `try` block and guard the unlink:
```python
tmp_path = None
try:
    tmp_path = f"{triage_data_path}.{os.getpid()}.tmp"
    ...
except Exception:
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    triage_data_path = None
```

## 5. Test Adequacy: PASS (with gap noted)

New tests adequately cover:
- `build_triage_data()` structure, descriptions, parallel config defaults, context paths, JSON serializability (6 tests)
- `format_block_message()` file-based vs inline output, default behavior, descriptions with file path (4 tests)
- `_run_triage()` file write happy path, `os.open` failure fallback, `os.replace` failure fallback (3 tests)

**Gap:** No test for `json.dump()` failure during atomic write. This would have caught Bug A. Recommend adding a test that mocks `json.dump` to raise `TypeError`, verifying inline fallback and no unhandled exception.

## 6. Format/Style: PASS

SKILL.md markdown is well-structured. Phase 3 subagent prompt template uses clear numbered command list. Code block fencing and indentation are correct throughout.

---

## Summary

| Area | Verdict |
|------|---------|
| Cross-file consistency | PASS |
| Regressions | PASS |
| Completeness | PASS |
| Edge cases (atomic write) | FAIL -- 2 bugs (fd double-close, UnboundLocalError) |
| Test adequacy | PASS (gap noted) |
| Format/style | PASS |

**Overall: PASS_WITH_FIXES**

Both bugs are in error-handling paths that are unlikely to trigger in normal operation (the triage data is always JSON-serializable, and `MemoryError` on f-string is near-impossible). The fixes are mechanical and low-risk. The pre-existing double-close pattern at line 828 should be fixed at the same time.
