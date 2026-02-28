# Implementation Results: memory_retrieve.py Notification Blocks

**Date:** 2026-02-28
**Task:** #1 -- Orphan crash recovery, save confirmation, pending notification
**Agent:** impl-retrieve

---

## Changes Made

### File: `hooks/scripts/memory_retrieve.py` (lines 422-489)

Added 3 notification blocks before the short-prompt check (line 492), so they fire for ALL prompts including short ones.

**Block 1: Save confirmation from previous session (global path)**
- Reads `~/.claude/last-save-result.json`
- If `saved_at` within 24 hours and same project: detailed `<memory-note>` with categories/titles/errors
- If different project: brief note with project basename
- Uses `_just_saved` boolean flag (set before processing) for Block 2 coordination
- Inner `finally` block ensures one-shot deletion even on parse errors
- All user-controlled data (`html.escape()`-sanitized, `str()` coerced for type safety)
- Wrapped in `try/except Exception: pass` (fail-open)

**Block 2: Orphan crash detection**
- Checks: `triage-data.json` exists AND `_just_saved` is False AND `.triage-pending.json` does NOT exist
- If triage data mtime > 300 seconds: prints orphan notification
- Uses `_just_saved` flag instead of re-checking global file (prevents race condition)
- Wrapped in `try/except Exception: pass` (fail-open)

**Block 3: Pending save notification**
- Checks: `.triage-pending.json` exists
- Reads categories count, prints notification with singular/plural
- Does NOT delete pending file (that's /memory:save's job)
- Wrapped in `try/except Exception: pass` (fail-open)

### File: `tests/test_memory_retrieve.py`

Added 21 new tests across 3 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestSaveConfirmation` | 8 | Same-project detail, cross-project brief, one-shot deletion, old result ignored, corrupt ignored, errors displayed, no-file no-output, fires for short prompts |
| `TestOrphanCrashDetection` | 6 | Old triage detected, suppressed by save result, suppressed by pending, recent triage ignored, no triage no alert, fires for short prompts |
| `TestPendingSaveNotification` | 7 | Notification shown, singular/plural, no pending no notification, file not deleted, corrupt ignored, fires for short prompts, empty categories no notification |

## Test Results

```
116 passed in 1.68s  (95 existing + 21 new)
```

## Cross-Model Review (Gemini 3.1 Pro via PAL clink)

3 issues found and **all fixed**:

1. **XML/Prompt Injection (HIGH)** -- User-controlled data from `last-save-result.json` was output without escaping.
   - **Fix:** Added `html.escape()` + `str()` coercion on all user-controlled values (categories, titles, errors, project names)

2. **Poison Pill Unlink Bypass (HIGH)** -- `unlink()` at end of try block would be skipped if parsing raised an exception, leaving corrupted file permanently.
   - **Fix:** Moved `unlink()` to inner `finally` block, guaranteed one-shot deletion regardless of data integrity

3. **Race Condition: Block 1/Block 2 (MEDIUM)** -- Block 1 deletes `last-save-result.json` before Block 2 checks it, causing simultaneous "saved" + "orphaned" messages.
   - **Fix:** Added `_just_saved` boolean flag, set before Block 1 processing, checked in Block 2 instead of re-reading filesystem

Codex 5.3 was unavailable (rate limit). Gemini 3.1 Pro used instead.

## Verification Checklist

- [x] `python3 -m py_compile hooks/scripts/memory_retrieve.py` -- PASS
- [x] `pytest tests/test_memory_retrieve.py -v` -- 116/116 PASS
- [x] All 3 blocks fire before short-prompt check (for ALL prompts)
- [x] Fail-open: all blocks wrapped in try/except
- [x] No direct writes to memory storage directory
- [x] User-controlled data HTML-escaped in output
- [x] One-shot deletion via inner finally block
- [x] Race condition fixed with _just_saved flag
- [x] Cross-model review completed (Gemini 3.1 Pro)
