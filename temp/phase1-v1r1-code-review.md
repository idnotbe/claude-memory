# Phase 1 V1R1 Code Review: triage_data Externalization

**Reviewer:** v1r1-code-review agent (Opus 4.6)
**Cross-validated by:** Gemini 3.1 Pro (via PAL clink)
**Date:** 2026-02-28
**Verdict:** PASS_WITH_FIXES

---

## Files Reviewed

1. `hooks/scripts/memory_triage.py` -- build_triage_data (L870-915), format_block_message (L918-975), _run_triage atomic write (L1145-1177)
2. `tests/test_memory_triage.py` -- TestBuildTriageData (L1567-1654), TestFormatBlockMessageTriageDataPath (L1661-1740), TestRunTriageWritesTriageDataFile (L1747-1859)
3. `skills/memory-management/SKILL.md` -- Phase 0 parsing (L56-63)
4. `CLAUDE.md` -- Architecture table, Parallel Per-Category Processing section

## Test Results

All 82 tests pass (0.27s). No regressions.

---

## Issues Found

### BUG-1: fd double-close in atomic write except handler (LOW)

**Location:** `memory_triage.py:1161-1169`

```python
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:   # takes fd ownership
        json.dump(triage_data, f, indent=2)
except Exception:
    try:
        os.close(fd)   # fd already closed by `with` block __exit__
    except OSError:
        pass
    raise
```

`os.fdopen(fd)` takes ownership of the file descriptor. If `json.dump()` raises after `os.fdopen` succeeds, the `with` block exit closes `fd`. The except handler then calls `os.close(fd)` on an already-closed fd. The `except OSError: pass` masks this, and in single-threaded context it is harmless, but in a multi-threaded scenario the fd number could be reused by another thread, causing a wrong-fd-close.

**Pre-existing:** The identical pattern exists at L828-836 (write_context_files). Both should be fixed together.

**Fix:**
```python
try:
    f = os.fdopen(fd, "w", encoding="utf-8")
except Exception:
    os.close(fd)
    raise
with f:
    json.dump(triage_data, f, indent=2)
```

### BUG-2: triage_data_path not XML-escaped in output (LOW-MEDIUM)

**Location:** `memory_triage.py:964`

```python
lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
```

`triage_data_path` is constructed from `cwd` (line 1013, 1151-1153). `cwd` comes from `hook_input.get("cwd", os.getcwd())` -- provided by Claude Code's hook infrastructure. While not directly user-controlled, `cwd` is not validated or sanitized for XML-special characters.

**Mitigating factors:**
- `cwd` is provided by Claude Code runtime, not by external untrusted input
- The path subcomponents are deterministic (`.claude/memory/.staging/triage-data.json`)
- The `<triage_data_file>` tag is consumed by the same agent via SKILL.md
- `transcript_path` already has realpath validation (L1038-1041), but `cwd` does not

**Recommendation:** Apply `_sanitize_snippet()`-style escaping of `<`/`>` on the path, or add cwd validation similar to transcript_path. Defense-in-depth; not a practical exploit path.

### BUG-3: Missing O_EXCL on atomic tmp file (LOW)

**Location:** `memory_triage.py:1156-1159`

Uses `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` without `O_EXCL`. The PID-based tmp name (`triage-data.json.<pid>.tmp`) is predictable. Without `O_EXCL`, a pre-existing file at that path would be silently overwritten.

**Mitigating factors:**
- `O_NOFOLLOW` blocks symlink attacks
- `.staging/` directory is within `.claude/memory/` (user-owned)
- Consistent with pre-existing write patterns at L823-826 (context files) and L1125-1128 (sentinel)
- Single-process execution model means PID collisions are unrealistic

**Verdict:** Not a regression. Optional defense-in-depth improvement.

### BUG-4: Cleanup unlink may target file we never created (INFORMATIONAL)

**Location:** `memory_triage.py:1171-1176`

If `os.open()` itself fails (L1156), `tmp_path` is assigned (L1155) but no file was created. `os.unlink(tmp_path)` in the `except OSError:` handler would attempt to delete whatever exists at that path. The `except OSError: pass` catch prevents errors, but it's sloppy -- we could delete a pre-existing file.

**Fix:** Track whether fd was successfully opened before attempting cleanup.

---

## Correctness Verification

### build_triage_data() (L870-915)
- **Fields:** `categories` (list of {category, score, description?, context_file?}) and `parallel_config` (enabled, category_models, verification_model, default_model) -- all present
- **Case normalization:** `category.lower()` applied correctly (L884)
- **Score rounding:** `round(r["score"], 4)` consistent with prior inline behavior
- **Description inclusion:** Conditional on `category_descriptions` provided and non-empty (L889-892)
- **Defaults:** Falls back to `DEFAULT_PARALLEL_CONFIG` for missing keys (L902-914)
- **SKILL.md compliance:** Phase 0 expects `categories` and `parallel_config` -- both present. `context_file` and `description` are optional per SKILL.md. **PASS.**

### format_block_message() (L918-975)
- **File-based path:** When `triage_data_path` is provided, outputs `<triage_data_file>` tag (L962-964). Does NOT call `build_triage_data()` (avoids double computation). **CORRECT.**
- **Inline fallback:** When `triage_data_path` is None, calls `build_triage_data()` and outputs `<triage_data>` block (L966-973). **CORRECT.**
- **Default behavior:** `triage_data_path=None` default, so callers without kwarg get inline. **BACKWARDS COMPATIBLE.**
- **Human-readable part:** Unchanged from pre-Phase-1. **PASS.**

### _run_triage() atomic write (L1145-1177)
- **Build + write separation:** `build_triage_data()` called once, written to file, path passed to `format_block_message()`. **CORRECT.**
- **Atomic rename:** PID-tmp + `os.replace()` is the correct POSIX atomic rename. **PASS.**
- **Fallback:** On `OSError`, `triage_data_path = None`, causing inline `<triage_data>`. **CORRECT.**
- **SKILL.md consistency:** SKILL.md Phase 0 step 1 reads `<triage_data_file>` first, falls back to inline `<triage_data>`. Matches output format. **PASS.**

---

## Test Coverage Assessment

| Scenario | Covered? | Test |
|----------|----------|------|
| build_triage_data basic structure | YES | test_build_triage_data_basic_structure |
| Descriptions included | YES | test_build_triage_data_includes_descriptions |
| Descriptions omitted when absent | YES | test_build_triage_data_no_description_when_absent |
| Parallel config defaults | YES | test_build_triage_data_parallel_config_defaults |
| No context_file when path missing | YES | test_build_triage_data_no_context_path |
| JSON serializability round-trip | YES | test_build_triage_data_json_serializable |
| File-based output with triage_data_path | YES | test_format_block_message_with_triage_data_path |
| Inline fallback without triage_data_path | YES | test_format_block_message_without_triage_data_path |
| Default kwarg produces inline | YES | test_format_block_message_default_is_inline |
| File path with descriptions | YES | test_format_block_message_file_path_with_descriptions |
| _run_triage writes triage-data.json | YES | test_triage_data_file_written (mocks run_triage, asserts non-empty stdout) |
| _run_triage fallback on write error | YES | test_triage_data_file_fallback_on_write_error (mocks os.open failure) |

**Note:** Prior BUG-1 (integration tests silently skipping) has been fixed. Tests now mock `run_triage` to return forced results and assert `stdout_text` is non-empty with descriptive messages (L1791, 1797, 1846, 1853).

**Coverage:** 12/12 paths covered. Minor gap: no test for `os.replace` failure (tmp written successfully but rename fails -- would exercise BUG-4 cleanup path). Non-blocking.

---

## CLAUDE.md / SKILL.md Consistency

- **CLAUDE.md:** Architecture table updated with `<triage_data>` JSON + context files. Parallel Per-Category Processing mentions `<triage_data_file>` for file-based output. **PASS.**
- **SKILL.md Phase 0:** Step 1 tries `<triage_data_file>` first, falls back to inline `<triage_data>`. Consistent with `format_block_message()` output. **PASS.**

---

## Summary

**Verdict: PASS_WITH_FIXES**

The Phase 1 externalization is functionally correct, backwards compatible, and well-tested (82/82 pass, all new code paths exercised). `build_triage_data()` produces field-complete output matching SKILL.md expectations. The atomic write + fallback pattern is sound.

Four issues found, none blocking:
- **BUG-1 (LOW):** fd double-close in except handler -- pre-existing pattern, fix both sites
- **BUG-2 (LOW-MEDIUM):** triage_data_path not XML-escaped -- defense-in-depth recommendation
- **BUG-3 (LOW):** Missing O_EXCL on tmp file -- pre-existing pattern, not a regression
- **BUG-4 (INFORMATIONAL):** Cleanup may unlink file we never created

**Recommended fixes:** BUG-1 and BUG-2. BUG-3 and BUG-4 can be deferred.

**Confidence: HIGH** -- All code paths verified through reading + test execution + Gemini cross-validation.
