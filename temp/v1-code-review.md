# V1 Code Correctness Review

**Date:** 2026-02-28
**Reviewer:** v1-code-reviewer (Claude Opus 4.6)
**Cross-model:** Gemini 3.1 Pro (via PAL clink)
**Files reviewed:**
- `hooks/scripts/memory_retrieve.py` (lines 422-489, 3 notification blocks)
- `skills/memory-management/SKILL.md` (Pre-Phase, Phase 0, Post-save changes)
- `tests/test_memory_retrieve.py` (21 new tests across 3 classes)

**Test results:** 116/116 PASS (4.85s)
**Compile check:** PASS

---

## Bug List

### BUG-1: JSON Schema Mismatch -- errors array (MEDIUM)
**Location:** `memory_retrieve.py:450` vs `SKILL.md:247`
**Description:** SKILL.md defines `errors` as `[{"category": "decision", "error": "OCC_CONFLICT"}]` (list of dicts), but `memory_retrieve.py` uses `str(e)` to stringify each element. When `e` is a dict, `str()` produces Python repr format: `{'category': 'decision', 'error': 'OCC_CONFLICT'}`. After `html.escape()`, user sees ugly `{&#x27;category&#x27;: ...}` in the notification.
**Impact:** Cosmetic -- notification message looks garbled when errors contain structured objects.
**Test gap:** The test at line 1198 uses `errors: ["validation failed"]` (list of strings), NOT the dict schema from SKILL.md. This means the test passes but doesn't cover the actual production schema.
**Fix recommendation:** Change line 450 to explicitly format dict errors:
```python
_err_parts = []
for e in _save_errors:
    if isinstance(e, dict):
        _err_parts.append(f"{e.get('category', 'unknown')}: {e.get('error', 'error')}")
    else:
        _err_parts.append(str(e))
_msg += f" [errors: {html.escape(', '.join(_err_parts))}]"
```
Also update the test to use the dict schema: `"errors": [{"category": "decision", "error": "OCC_CONFLICT"}]`.

### BUG-2: Non-Atomic Global Result Write (HIGH, low probability)
**Location:** `SKILL.md:239-240` (writer) vs `memory_retrieve.py:426-429` (reader)
**Description:** SKILL.md instructs `echo ... > "$HOME/.claude/last-save-result.json"`. The `>` operator truncates the file to 0 bytes before `echo` writes data. If `memory_retrieve.py` runs at this exact instant (concurrent session), it reads a 0-byte or partial file, throws JSONDecodeError, and the `finally` block unlinks the file -- permanently losing the save notification.
**Impact:** Race condition. The save notification is silently destroyed. Very low probability (requires microsecond timing) but possible with rapid multi-session usage.
**Fix recommendation:** In SKILL.md, use atomic write-then-rename:
```bash
echo '...' > "$HOME/.claude/last-save-result.tmp.json" && mv "$HOME/.claude/last-save-result.tmp.json" "$HOME/.claude/last-save-result.json"
```

### BUG-3: Pending Save Destruction via Pre-Phase (MEDIUM-HIGH, design issue)
**Location:** `SKILL.md:38-54` (Pre-Phase) vs `memory_retrieve.py:484-486` (Block 3 notification)
**Description:** Block 3 in memory_retrieve.py correctly detects `.triage-pending.json` and tells user "Run /memory:save to complete." But when the user runs `/memory:save`, the SKILL.md Pre-Phase fires (no triage tags present in manual invocation), detects `.triage-pending.json`, and deletes it as "stale staging" (line 48-51). The pending data is destroyed instead of being resumed.
**Impact:** The user follows the notification's advice but gets no save -- the pending data is wiped. This is a functional defect in the designed workflow.
**Note:** This is partially by design (the contrarian-impl-context.md at line 47 says "Do NOT attempt to resume from stale context"). However, the Block 3 notification message misleadingly says "Run /memory:save to complete" when in fact running it will destroy the pending data and start fresh. The message should say "Run /memory:save to retry" or explicitly state the pending data will be re-triaged.
**Fix recommendation:** Change Block 3 message (line 484-486) from "ready. Run /memory:save to complete." to "detected. Run /memory:save to re-triage and save." -- making it clear this is a retry, not a resume.

### BUG-4: False Orphan After Double-Prompt Race (LOW, multi-prompt race)
**Location:** `SKILL.md:239-258` (post-save order) vs `memory_retrieve.py:461-474` (Block 2)
**Description:** Post-save in SKILL.md writes `last-save-result.json` (Step 1), then cleans staging files (Step 2). If user submits Prompt-A between Steps 1-2, Block 1 reads+deletes the result file (`_just_saved=True`, no orphan). But if user submits Prompt-B before Step 2 completes, `last-save-result.json` is gone (`_just_saved=False`) while `triage-data.json` still exists and is old -- triggering a false "Orphaned triage data" warning.
**Impact:** Benign false positive. Requires two rapid prompts during a narrow window (seconds between LLM tool calls). The orphan message is informational only and causes no data loss.
**Fix recommendation:** Reverse post-save order in SKILL.md: clean staging first, then write result file. This eliminates the window entirely.

---

## Edge Case Analysis

| Scenario | Behavior | Verdict |
|----------|----------|---------|
| Empty `last-save-result.json` (0 bytes) | JSONDecodeError caught, `_just_saved=True`, file unlinked | SAFE |
| Malformed JSON in result file | JSONDecodeError caught in inner try, `finally` unlinks, `_just_saved=True` | SAFE |
| Missing `saved_at` field | `_saved_at = ""`, `_is_recent_save = False`, no notification shown | SAFE |
| Missing `project` field | `_save_project = ""`, cross-project path shown as "unknown" | SAFE |
| Missing `categories`/`titles` fields | `.get()` returns `[]`, `_cats_str = "unknown"` | SAFE |
| Zero-byte `triage-data.json` | `exists()` returns True, `.stat().st_mtime` works, orphan detected normally | SAFE |
| Zero-byte `.triage-pending.json` | JSONDecodeError caught, no notification (correct: corrupt = skip) | SAFE |
| `categories` in pending is a string not list | `isinstance(_, list)` returns False, `_cat_count = 0`, no notification | SAFE |
| `categories` in pending is None | `isinstance(None, list)` returns False, `_cat_count = 0` | SAFE |
| First-ever run (no files exist) | All `.exists()` checks return False, all blocks silently skip | SAFE |
| `~/.claude/` directory doesn't exist | `Path.home() / ".claude" / "last-save-result.json"` -- `.exists()` returns False | SAFE |
| Symlink `last-save-result.json` pointing elsewhere | `unlink(missing_ok=True)` removes the symlink, not the target | SAFE |
| File deleted between `.exists()` and `.read_text()` | FileNotFoundError caught by outer `except Exception: pass` | SAFE |
| `.staging/` directory doesn't exist | `_triage_data_path.exists()` returns False (parent doesn't exist) | SAFE |
| Concurrent unlink (two sessions) | `unlink(missing_ok=True)` is TOCTOU-safe on Python 3.8+ | SAFE |

---

## Security Assessment

| Vector | Status | Notes |
|--------|--------|-------|
| XML/HTML injection in output | MITIGATED | `html.escape()` applied to all user-controlled values (categories, titles, errors, project name) |
| Path traversal via project name | MITIGATED | `Path(str(_save_project)).name` extracts only basename, no filesystem interaction |
| Prompt injection via memory-note tags | MITIGATED | All data within `<memory-note>` is HTML-escaped; tag structure cannot be broken |
| Unlink safety | SAFE | `missing_ok=True` handles TOCTOU; symlinks are not followed |
| Config injection | N/A | These blocks don't read config values into output |
| FTS5 injection | N/A | These blocks don't perform FTS5 queries |

---

## Cross-Model Validation Results

### Gemini 3.1 Pro (via PAL clink, codereviewer role)
**Model used:** gemini-3.1-pro-preview
**Duration:** 432s (read 2 files, ran 13 shell commands, 1 grep)

**Findings:**
1. **CRITICAL: Non-atomic write race condition** -- Confirmed as BUG-2 above. Valid finding.
2. **CRITICAL: Pending save destruction** -- Confirmed as BUG-3 above. Valid finding (but partially by design).
3. **HIGH: False orphan after double-prompt** -- Confirmed as BUG-4 above. Valid but low practical impact.
4. **MEDIUM: Error dict stringification** -- Confirmed as BUG-1 above. Valid finding with test gap.

**Positives noted by Gemini:**
- Variable scoping is clean; no UnboundLocalError possible
- `_just_saved` flag logic is correct (set before parsing, survives parse errors)
- Block 2/Block 3 mutual exclusion is correct
- `isinstance()` type guards are thorough
- `html.escape()` usage is comprehensive
- `Path.name` for project basename is safe

---

## Test Coverage Assessment

**21 new tests across 3 classes. Coverage is good but has one gap:**

| Concern | Covered? | Notes |
|---------|----------|-------|
| Same-project detailed notification | YES | `test_same_project_detailed_confirmation` |
| Cross-project brief notification | YES | `test_different_project_brief_note` |
| One-shot deletion | YES | `test_save_result_deleted_after_display` |
| Old result (>24h) ignored | YES | `test_old_save_result_ignored` |
| Corrupt JSON fail-open | YES | `test_corrupt_save_result_ignored` |
| Error display | PARTIAL | Test uses string errors, not dict schema from SKILL.md (BUG-1) |
| No-file baseline | YES | `test_no_save_result_file_no_output` |
| Short prompt execution | YES | `test_fires_for_short_prompts` (all 3 blocks) |
| Orphan detection | YES | 6 tests covering all combinations |
| Pending notification | YES | 7 tests covering singular/plural, corrupt, empty |
| `_just_saved` suppression | YES | `test_no_orphan_when_save_result_exists` |
| Pending suppresses orphan | YES | `test_no_orphan_when_pending_exists` |
| Concurrent session race | NO | Would need multiprocessing test (complex, low priority) |

---

## Overall Verdict: PASS_WITH_FIXES

**4 issues found, all fixable without architectural changes:**

| Bug | Severity | Fix Effort | Blocks Ship? |
|-----|----------|-----------|--------------|
| BUG-1: Error schema mismatch | MEDIUM | 5 min (code + test) | No |
| BUG-2: Non-atomic write race | HIGH (low prob) | 2 min (SKILL.md only) | No |
| BUG-3: Misleading pending message | MEDIUM-HIGH | 1 min (message text) | No |
| BUG-4: False orphan race | LOW | 2 min (SKILL.md order swap) | No |

None of these are correctness-blocking. The core logic (variable scoping, flag coordination, fail-open behavior, security sanitization) is solid. All 116 tests pass. The implementation matches the design spec from `contrarian-impl-context.md`.
