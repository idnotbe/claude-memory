# V1 Integration Review: memory_retrieve.py + SKILL.md Changes

**Date:** 2026-02-28
**Reviewer:** v1-integration
**Scope:** 3 notification blocks in memory_retrieve.py, Pre-Phase + Phase 0 + Post-save in SKILL.md

---

## 1. Test Suite Results

```
969 passed in 63.22s -- ALL PASS
```

No failures, no warnings. The 21 new tests (8 SaveConfirmation + 6 OrphanCrash + 7 PendingSave) all pass alongside the 948 pre-existing tests.

---

## 2. Backwards Compatibility Assessment

### 2.1 No staging files exist (fresh install)
**PASS.** All 3 blocks in memory_retrieve.py are guarded by `.exists()` checks. When no staging directory or files exist:
- Block 1: `_save_result_path.exists()` returns False -- skipped
- Block 2: `_triage_data_path.exists()` returns False -- skipped
- Block 3: `_pending_path.exists()` returns False -- skipped
- Confirmed by test: `TestSaveConfirmation::test_no_save_result_file_no_output`, `TestOrphanCrashDetection::test_no_orphan_when_no_triage_data`, `TestPendingSaveNotification::test_no_pending_no_notification`

### 2.2 Old triage format (inline `<triage_data>` only, no file)
**PASS.** SKILL.md Phase 0 explicitly supports both formats:
1. First try: `<triage_data_file>` tag (new file-referenced format)
2. Fallback: inline `<triage_data>` JSON block (old format)

This is backwards-compatible with the existing triage hook output which only emits inline `<triage_data>`.

### 2.3 `~/.claude/` directory doesn't exist
**PASS.** Block 1 reads `Path.home() / ".claude" / "last-save-result.json"`. If `~/.claude/` doesn't exist, `_save_result_path.exists()` returns False. The outer `try/except Exception: pass` catches any OS-level errors. Confirmed by tests that use `monkeypatch` to set HOME to temp directories (e.g., `TestSaveConfirmation::test_no_save_result_file_no_output` doesn't create `~/.claude/`).

### 2.4 Pre-Phase guard correctly NOT fires during normal auto-save flow
**PASS.** SKILL.md Pre-Phase explicitly states: "Only run this check when **no** `<triage_data>` or `<triage_data_file>` tag is present in the current hook output." During normal auto-save, triage tags are present, so Pre-Phase is skipped entirely. This guard condition was specifically added to fix a critical race condition identified by Gemini review (impl-skill-results.md, Finding #1).

### 2.5 Short prompt handling
**PASS.** All 3 notification blocks are placed BEFORE the short prompt check (line 491: `if len(user_prompt.strip()) < 10:`). Confirmed by 3 dedicated tests: `TestSaveConfirmation::test_fires_for_short_prompts`, `TestOrphanCrashDetection::test_orphan_fires_for_short_prompts`, `TestPendingSaveNotification::test_pending_fires_for_short_prompts`.

---

## 3. Cross-File Consistency Check

### 3.1 JSON Schema: SKILL.md writer vs memory_retrieve.py reader

| Field | SKILL.md (writer) | memory_retrieve.py (reader) | Match? |
|-------|-------------------|----------------------------|--------|
| `saved_at` | ISO 8601 UTC string | Parsed via `datetime.fromisoformat()` with Z->+00:00 replacement | MATCH |
| `project` | `<cwd absolute path>` | Compared against `cwd` from hook input | MATCH |
| `categories` | `["category1", "category2"]` | Iterated with `str(c)` + `html.escape()` | MATCH |
| `titles` | `["Title 1", "Title 2"]` | Iterated with `str(t)` + `html.escape()` | MATCH |
| `errors` | `[{"category": "name", "error": "msg"}]` (objects) | Iterated with `str(e)` coercion | **TYPE MISMATCH** (see Finding #1) |

### 3.2 File Paths

| Path | SKILL.md | memory_retrieve.py | Match? |
|------|----------|-------------------|--------|
| Global result | `$HOME/.claude/last-save-result.json` | `Path.home() / ".claude" / "last-save-result.json"` | MATCH |
| Triage data | `.claude/memory/.staging/triage-data.json` | `memory_root / ".staging" / "triage-data.json"` | MATCH |
| Triage pending | `.claude/memory/.staging/.triage-pending.json` | `memory_root / ".staging" / ".triage-pending.json"` | MATCH |
| Context files | `.claude/memory/.staging/context-*.txt` | N/A (not read by retrieve) | N/A |

### 3.3 Cleanup Lists

Pre-Phase cleanup (SKILL.md line 50):
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

Post-save cleanup (SKILL.md line 258):
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

**MATCH** -- Both lists are identical (4 patterns).

---

## 4. Action Plan Alignment Check

**Source:** `action-plans/plan-memory-save-noise-reduction.md`

| Plan Section | Expected | Implemented | Aligned? |
|-------------|----------|-------------|----------|
| Phase 3 (Save Confirmation) | `memory_retrieve.py` reads result file, shows confirmation, deletes after read | Block 1: reads global path, shows detail/brief per project match, inner finally for one-shot deletion | YES (upgraded from plan: global path per V2 Contrarian Finding 4, html.escape per cross-model review) |
| Phase 3 (24h check) | Ignore results > 24 hours old | `_age_secs < 86400` check | YES |
| Phase 3 (Cross-project) | Known limitation in plan (local path) | Implemented as global path with project disambiguation (V2 Contrarian Fix) | EXCEEDS PLAN (improvement) |
| Phase 4 (Pending detection) | `memory_retrieve.py` reads `.triage-pending.json` and shows notification | Block 3: reads pending file, shows category count with singular/plural | YES |
| Phase 4 (Orphan detection) | Detect triage-data.json without result/pending | Block 2: checks `_just_saved` flag + pending absence + 5min age | YES |
| Phase 4 (Pending writer) | SKILL.md writes `.triage-pending.json` on error | **NOT IMPLEMENTED** (Phase 4 status: `[ ]` not started) | EXPECTED -- reader is forward-compatible |
| SKILL.md Pre-Phase | Clean stale staging on `/memory:save` | Pre-Phase section with guard condition | YES |
| SKILL.md Phase 0 | Parse `<triage_data_file>` tag | File tag first, inline fallback | YES (forward-compatible for future Phase 1) |
| SKILL.md Post-save | Write global result + cleanup staging | Post-save section with structured schema + cleanup | YES |

**Key discrepancy:** The action plan's Phase 3 design originally placed `last-save-result.json` at `.claude/memory/.staging/` (local). The implementation uses `~/.claude/last-save-result.json` (global) per V2 Contrarian Finding 4. This is an intentional upgrade documented in `temp/contrarian-impl-context.md`.

---

## 5. Cross-Model Validation Results

### Gemini 3.1 Pro (via PAL clink, codereviewer role)
25 API requests, 565K tokens consumed.

**Findings:**

| # | Severity | Finding | Assessment |
|---|----------|---------|------------|
| 1 | Critical (Gemini) | `.triage-pending.json` writer missing in SKILL.md | **FALSE POSITIVE** -- This is Phase 4 (not yet started). Reader code is intentionally forward-compatible. The action plan marks Phase 4 as `[ ]`. Reader + tests verify the code handles both present and absent cases correctly. |
| 2 | Medium | `errors` field type mismatch: writer produces `{category, error}` objects, reader uses `str(e)` coercion | **VALID** -- Will display raw dict repr like `{'category': 'decision', 'error': 'OCC_CONFLICT'}` instead of clean formatted text. See Finding #1 below. |
| 3 | Medium | Bash `echo` for JSON generation may break on apostrophes | **LOW RISK** -- Memory titles are sanitized (max 120 chars, no special chars in practice). The `str(e)` coercion on errors already handles dict-to-string. Heredoc is safer but `echo` works for this structured data. |

---

## 6. Findings

### Finding #1: `errors` field type mismatch (MEDIUM)

**Location:** `memory_retrieve.py:450` (reader) vs `SKILL.md:253` (writer schema)

**Issue:** SKILL.md specifies `errors` as `[{"category": "decision", "error": "OCC_CONFLICT"}]` (structured objects). The reader at line 450 uses `str(e)` coercion:
```python
_msg += f" [errors: {html.escape(', '.join(str(e) for e in _save_errors))}]"
```

This will display: `[errors: {&#x27;category&#x27;: &#x27;decision&#x27;, &#x27;error&#x27;: &#x27;OCC_CONFLICT&#x27;}]`

**Recommended fix:** Format dict errors properly:
```python
def _fmt_err(e):
    if isinstance(e, dict):
        return f"{e.get('category', 'unknown')}: {e.get('error', 'unknown')}"
    return str(e)
_msg += f" [errors: {html.escape(', '.join(_fmt_err(e) for e in _save_errors))}]"
```

**Severity:** Medium (UX degradation, not functional breakage). The `str()` + `html.escape()` prevents injection. Output is ugly but safe.

### Finding #2: No test for structured error object display (LOW)

**Location:** `tests/test_memory_retrieve.py`, class `TestSaveConfirmation`

The test `test_save_result_with_errors` uses plain string errors (`["validation failed"]`), not the structured `{"category": "...", "error": "..."}` objects that SKILL.md actually produces. This means the type mismatch from Finding #1 is not caught by tests.

### Finding #3: `.triage-pending.json` writer deferred to Phase 4 (INFORMATIONAL)

Block 3 (pending notification) in memory_retrieve.py is forward-compatible code. It will become active when Phase 4 (Error Fallback) is implemented and SKILL.md is updated to write `.triage-pending.json` on save failure. Currently it's dormant -- the reader code has test coverage for both present and absent cases.

---

## 7. Overall Verdict

### **PASS_WITH_FIXES**

**Blocking:** None.

**Recommended fixes (non-blocking):**
1. **Finding #1:** Fix `errors` field formatting in `memory_retrieve.py:450` to handle structured objects (dict with category/error keys). This is a UX issue, not a correctness issue.
2. **Finding #2:** Add a test with structured error objects to catch the type mismatch.

**Summary:**
- All 969 tests pass
- Backwards compatibility verified across 5 scenarios
- File paths and cleanup lists are fully consistent
- Action plan alignment is strong (one intentional upgrade: global path)
- Cross-model validation confirmed file path consistency, identified the `errors` type mismatch
- The implementation is safe (fail-open, html.escape, one-shot deletion, _just_saved flag)
- Forward-compatible with upcoming Phase 1 (triage_data_file) and Phase 4 (.triage-pending.json writer)
