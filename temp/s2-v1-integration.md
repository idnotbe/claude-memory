# S2 V1 Integration Verification Report

**Verifier:** v1-integration (Claude Opus 4.6)
**Date:** 2026-02-21
**Scope:** Backward compatibility, hook contract, config migration, test suite, S3+ readiness

---

## 1. Backward Compatibility: PASS

### Legacy keyword path preserved unchanged

- `score_entry()` -- Present and unchanged at `memory_retrieve.py:94-126`. Uses `tokenize(entry["title"], legacy=True)` for backward-compatible tokenization. Exact title match (2 pts), exact tag match (3 pts), prefix match (1 pt). No changes to scoring logic.

- `score_description()` -- Present at `memory_retrieve.py:129-154`. Properly capped at 2 points. Uses `legacy=True` tokenizer. Functions as designed.

- `check_recency()` -- Present at `memory_retrieve.py:157-190`. Used in the legacy path at line 610 (`is_retired, is_recent = check_recency(file_path)`). Returns `(is_retired, is_recent)` tuple. Unchanged.

- Legacy path routing -- Lines 563-640. Triggered when `HAS_FTS5 == False` OR `match_strategy != "fts5_bm25"`. Uses `tokenize(user_prompt, legacy=True)` at line 567. The entire legacy keyword scoring pipeline (Pass 1: text matching, Pass 2: deep check, recency bonus, retired exclusion, path containment) is preserved verbatim.

- Revert to legacy via config -- Users can set `match_strategy: "title_tags"` in config to force legacy path. Verified at line 546: `if HAS_FTS5 and match_strategy == "fts5_bm25"`. Both conditions must be true to enter FTS5 path, so `title_tags` always routes to legacy regardless of FTS5 availability.

- Output format consistency -- Both FTS5 and legacy paths use `_output_results()` (lines 426-452) for output. This is a refactoring that extracts the output logic into a shared function. Same `<memory-context>` XML format, same `_sanitize_title()` application, same tag formatting.

### Tokenizer separation

- `_LEGACY_TOKEN_RE = re.compile(r"[a-z0-9]+")` -- line 54, unchanged
- `_COMPOUND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")` -- line 57, new for FTS5 only
- `tokenize()` accepts `legacy=True` parameter to select regex. FTS5 path uses `legacy=False` (default). Legacy path uses `legacy=True`. No cross-contamination.

**Verdict: PASS. Legacy path is fully preserved. Users can revert to legacy via `match_strategy: "title_tags"`. No function signatures changed.**

---

## 2. Hook Integration: PASS

### stdin/stdout contract

- **Input:** JSON via stdin (line 457-463). Reads `user_prompt` and `cwd` from hook input dict. Unchanged contract.
- **Output:** XML to stdout via `_output_results()`. Format: `<memory-context source=".claude/memory/" descriptions="...">` with `- [CAT] title -> path #tags:...` lines and `</memory-context>` closing tag. Exit code 0 on all paths.
- **Error handling:** All error paths exit cleanly with `sys.exit(0)` -- empty input (line 463), short prompt (line 470), missing index (line 491), no entries (line 541), no valid FTS query (line 561), no matches in legacy (line 592, 633).

### Hook timeout

- `hooks.json` line 50: UserPromptSubmit hook timeout is **10 seconds**.
- FTS5 estimated total latency is ~17ms for 500 entries (per arch review). Well within 10s budget.
- Legacy path latency is comparable (reads up to 20 JSON files for deep check). Also well within budget.

### Hook configuration integrity

```json
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
  "timeout": 10,
  "statusMessage": "Retrieving relevant memories..."
}
```

- Type: `command` (correct for UserPromptSubmit)
- Matcher: `*` (matches all prompts, script does its own filtering)
- Uses `$CLAUDE_PLUGIN_ROOT` for portable paths

### Other hooks unchanged

- Stop hook (memory_triage.py): timeout 30s, command type -- unchanged
- PreToolUse:Write (write_guard.py): timeout 5s -- unchanged
- PostToolUse:Write (validate_hook.py): timeout 10s -- unchanged

**Verdict: PASS. Hook contract unchanged. Timeout sufficient. All error paths exit cleanly.**

---

## 3. Config Migration: PASS

### Silent upgrade for existing users

| Existing Config | Behavior After Update |
|----------------|----------------------|
| No config file at all | Defaults: `max_inject=3`, `match_strategy="fts5_bm25"` -- silent FTS5 upgrade |
| Config without `match_strategy` key | `retrieval.get("match_strategy", "fts5_bm25")` -> FTS5 silently |
| Config with `match_strategy: "title_tags"` | Routes to legacy path -- explicit revert works |
| Config with `max_inject: 5` | Honored, clamped to [0,20] |
| Config with `max_inject: 3` (new default) | Honored |
| Config with `retrieval.enabled: false` | Exits immediately (line 504) |

### max_inject validation (lines 506-513)

```python
raw_inject = retrieval.get("max_inject", 3)
try:
    max_inject = max(0, min(20, int(raw_inject)))
except (ValueError, TypeError, OverflowError):
    max_inject = 3
```

- Default changed from 5 to 3 (FTS5 BM25 is more precise, fewer results needed)
- Clamping to [0, 20] works for negative, large, float, string-number, and string-text inputs
- Invalid types (None, "five") fall through to `except` and get default 3 with stderr warning
- `max_inject == 0` triggers early exit at line 527

### Default config file (`assets/memory-config.default.json`)

```json
"retrieval": {
    "max_inject": 3,
    "match_strategy": "fts5_bm25"
}
```

Updated to reflect new defaults. Existing configs without these keys get the same values via `.get()` defaults.

**Verdict: PASS. Clean migration. Existing users without `match_strategy` get FTS5 silently. Explicit revert supported. `max_inject` values validated and clamped.**

---

## 4. Test Suite: PASS (502 passed, 10 xpassed)

### Test execution results

```
platform linux -- Python 3.11.14, pytest-9.0.2
collected 512 items
502 passed, 10 xpassed in 28.57s
```

### Breakdown by file

| Test File | Tests | Status |
|-----------|-------|--------|
| test_adversarial_descriptions.py | 132 | All PASSED |
| test_arch_fixes.py | 47 (37 passed + 10 xpassed) | All PASSED |
| test_memory_retrieve.py | 26 | All PASSED |
| test_memory_triage.py | 150 | All PASSED |
| test_memory_write.py | 92 | All PASSED |
| test_memory_write_guard.py | 13 | All PASSED |

### The 10 xpassed tests

These are tests that were marked `@pytest.mark.xfail(reason="pre-fix")` but now pass because the fixes have been implemented:

1. `TestIssue2ResolveMemoryRoot::test_path_without_marker_fails_closed` -- _resolve_memory_root now correctly exits(1)
2. `TestIssue2ResolveMemoryRoot::test_external_path_rejected_via_write` -- Path traversal now blocked
3. `TestIssue2ResolveMemoryRoot::test_error_message_includes_example` -- Error message now includes example
4. `TestIssue3MaxInjectClamp::test_max_inject_negative_clamped_to_zero` -- Negative values now clamped
5. `TestIssue3MaxInjectClamp::test_max_inject_zero_exits_early` -- Zero now exits early
6. `TestIssue3MaxInjectClamp::test_max_inject_hundred_clamped_to_twenty` -- Large values now clamped to 20
7. `TestIssue3MaxInjectClamp::test_max_inject_string_invalid_type` -- String "five" now handled gracefully
8. `TestIssue3MaxInjectClamp::test_max_inject_float_coerced` -- Float 5.7 now coerced to int
9. `TestIssue3MaxInjectClamp::test_max_inject_string_number_coerced` -- String "5" now coerced to int
10. `TestIssue5TitleSanitization::test_pre_sanitization_entries_cleaned` -- Titles now sanitized on read

**Action needed:** These 10 tests should have their `@pytest.mark.xfail` decorators removed since the fixes are now in place. The xpassed status is not a failure, but leaving stale xfail markers creates confusion. This is a cleanup item, not a blocking issue.

### Import chain verification

- `test_adversarial_descriptions.py` imports `memory_triage` and `memory_retrieve` functions -- no import errors
- `test_memory_retrieve.py` imports `score_description` with conditional fallback (lines 28-31) -- `score_description` now exists, so direct import succeeds
- `conftest.py` imports `memory_candidate.CATEGORY_DISPLAY` for index building -- works correctly

### No test isolation issues

All tests use `tmp_path` or `tmp_path_factory` fixtures for filesystem isolation. No tests modify global state. FTS5 availability is checked at module level but does not affect test isolation.

**Verdict: PASS. 512 tests collected, 502 passed, 10 xpassed (stale xfail markers for already-fixed issues). Zero failures. Zero errors. No import issues.**

---

## 5. S3+ Session Readiness: READY

### Function extraction assessment

| Function | Signature | Extractable to `memory_search_engine.py`? | Notes |
|----------|-----------|-------------------------------------------|-------|
| `build_fts_query(tokens: list[str]) -> str \| None` | Pure function | YES, as-is | No external dependencies |
| `query_fts(conn, fts_query, limit=15) -> list[dict]` | Pure function | YES, as-is | Only depends on sqlite3 Connection |
| `apply_threshold(results, mode="auto") -> list[dict]` | Pure function | YES, as-is | Uses CATEGORY_PRIORITY constant |
| `build_fts_index_from_index(index_path: Path) -> Connection` | Coupled to file | REFACTOR needed | Should accept `list[dict]` instead of Path |
| `score_with_body(conn, fts_query, user_prompt, top_k_paths, memory_root, mode)` | Coupled to path resolution | REFACTOR needed | Decouple `project_root` from `memory_root.parent.parent` |

3 of 5 functions are ready for extraction as-is. The other 2 need minor refactoring to decouple file I/O and path resolution, which is expected and planned.

### S5 confidence annotations readiness

`apply_threshold()` returns dicts with `score` key. The score distribution (BM25 rank values) can be used to compute confidence:
- Best match score as reference
- Ratio of each entry's score to best score -> confidence percentage
- Adding `[confidence:high/medium/low]` to output is a straightforward post-processing step on the result list

No blocking issues for S5.

### Function signature stability

All new function signatures use standard types (`Path`, `sqlite3.Connection`, `list[dict]`, `str`, `int`). No custom classes or complex types that would create coupling issues. The `dict` result format (`title`, `tags`, `path`, `category`, `score`) is consistent across FTS5 and legacy paths.

**Verdict: READY. Core functions have clean extraction boundaries. 3/5 extractable as-is, 2/5 need planned refactoring.**

---

## 6. Cross-Validation

### Architecture Review Alignment

The arch review (`temp/s2-arch-review.md`) found:
- **M1** (in-place score mutation): Minor, acceptable for S2, fix in S3. Agreed.
- **M2** (retired entries beyond top_k_paths): Known limitation, mitigated by index rebuild. Agreed.
- No must-fix items. Agreed -- no blockers found in this integration review either.
- Plan alignment: Full. No unauthorized deviations. Confirmed by code inspection.

### Plugin Manifest

`plugin.json` version is `5.0.0`, matching the v5.0.0 architecture described in CLAUDE.md. Commands (`memory`, `memory-config`, `memory-search`, `memory-save`) and skills (`memory-management`) are correctly declared.

---

## Summary

| Area | Verdict |
|------|---------|
| Backward compatibility | **PASS** |
| Hook contract | **PASS** |
| Config migration | **PASS** |
| Test suite | **PASS** (502 passed, 10 xpassed, 0 failed) |
| S3+ readiness | **READY** |
| **Overall** | **PASS** |

### Action items (non-blocking)

1. **Remove 10 stale `@pytest.mark.xfail` decorators** in `tests/test_arch_fixes.py` for tests whose fixes are now implemented. These are not failures but create confusing output.
2. **Track M1 and M2** from the arch review for S3 resolution.
3. **Plan `build_fts_index_from_index` and `score_with_body` refactoring** for S3 extraction into `memory_search_engine.py`.
