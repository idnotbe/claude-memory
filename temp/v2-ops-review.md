# V2 Operational Review: Memory Save Notification Changes

**Date:** 2026-02-28
**Reviewer:** v2-ops (Claude Opus 4.6)
**Cross-model:** Gemini 3.1 Pro (via PAL clink, codereviewer role)
**Files reviewed:**
- `hooks/scripts/memory_retrieve.py` (lines 422-494, 3 notification blocks)
- `skills/memory-management/SKILL.md` (Pre-Phase lines 38-54, Phase 0 lines 56-59, Post-save lines 235-262)
- `tests/test_memory_retrieve.py` (last ~180 lines, 21 new tests in 3 classes)
- `action-plans/plan-memory-save-noise-reduction.md` (Phase 3/4 alignment check)

**Test results:** 969/969 PASS (51.37s)

---

## 1. Performance Impact

### Measured I/O Overhead (10,000-iteration microbenchmark)

| Operation | Avg Time |
|-----------|----------|
| `Path.exists()` (file present) | 0.0015 ms |
| `Path.exists()` (file absent) | 0.0020 ms |
| `read_text()` + `json.loads()` | 0.0108 ms |
| `stat().st_mtime` | 0.0015 ms |

### Per-Prompt Overhead by Scenario

| Scenario | Operations | Total Overhead |
|----------|-----------|----------------|
| **No files exist** (normal case, 99%+ of prompts) | 3x `exists()` miss | **0.006 ms** |
| **Save result present** (first prompt after save) | 1x `exists()` hit + read + parse + unlink + 2x `exists()` miss | **0.016 ms** |
| **All files present** (worst case) | 3x `exists()` hit + 2x read + parse + stat | **0.017 ms** |

**Verdict: NEGLIGIBLE.** The hook already performs config file read (~0.01ms), index load (~0.5-2ms), FTS5 search (~1-5ms), and optionally LLM judge calls (~500-2000ms). The notification blocks add 0.006-0.017ms, which is <0.01% of the hook's total runtime. This is orders of magnitude below the threshold of concern.

---

## 2. Backwards Compatibility

### Scenario Matrix

| Plugin Version | SKILL.md Version | Behavior | Safe? |
|---------------|-----------------|----------|-------|
| OLD (no notification blocks) | OLD (no result writer) | Current behavior, no change | YES |
| OLD (no notification blocks) | NEW (writes result file) | Result file written to `$HOME/.claude/last-save-result.json`, never read. Overwrites on each save. No accumulation. | YES |
| NEW (with notification blocks) | OLD (no result writer) | All 3 blocks skip silently (files don't exist). Orphan detection may helpfully detect pre-existing stale `triage-data.json`. | YES |
| NEW (with notification blocks) | NEW (writes result file) | Full notification flow as designed. | YES |

**Key insight:** All 3 reader blocks in `memory_retrieve.py` are guarded by `Path.exists()` inside `try/except Exception: pass`. There is no scenario where missing files cause errors. The two components are fully independently deployable.

### Version Coexistence During Incremental Rollout

- **Safe.** The global result file at `$HOME/.claude/last-save-result.json` is overwritten (not appended) on each save. Even if multiple sessions use mixed versions, the worst case is a result file that sits unreaded until a new-version session picks it up.

---

## 3. Documentation Accuracy

### CLAUDE.md Update Needed?

**YES -- minor update recommended.** The UserPromptSubmit hook description in CLAUDE.md (line 18) reads:
```
| UserPromptSubmit | Retrieval hook -- FTS5 BM25 keyword matcher injects relevant memories (fallback: legacy keyword), optional LLM judge layer filters false positives |
```

This does not mention the new save confirmation, orphan detection, or pending notification behaviors. While the notification blocks are logically part of the retrieval hook, the description is now incomplete. Recommended update:

```
| UserPromptSubmit | Retrieval hook -- FTS5 BM25 keyword matcher injects relevant memories (fallback: legacy keyword), optional LLM judge layer filters false positives; also shows save confirmation/orphan/pending notifications |
```

**Severity: LOW.** The missing description doesn't cause operational issues; it's a documentation accuracy concern only.

### Action Plan Alignment

The action plan (`plan-memory-save-noise-reduction.md`) Phase 3/4 design vs actual implementation:

| Plan Element | Plan Says | Implemented | Aligned? |
|-------------|-----------|-------------|----------|
| Result file path | `.claude/memory/.staging/last-save-result.json` (local) | `$HOME/.claude/last-save-result.json` (global) | INTENTIONAL UPGRADE (V2 Contrarian Finding 4) |
| Result file write | `echo ... >` (non-atomic) | `cat > tmp + mv` (atomic) | INTENTIONAL UPGRADE (V1 BUG-2 fix) |
| Post-save order | Not specified | Clean staging first, then write result | INTENTIONAL UPGRADE (V1 BUG-4 fix) |
| Error dict formatting | Not specified | `isinstance(e, dict)` with `category: error` formatting | INTENTIONAL UPGRADE (V1 BUG-1 fix) |
| Pending message text | "Use /memory:save to save them" | "Run /memory:save to re-triage and save" | INTENTIONAL UPGRADE (V1 BUG-3 fix) |
| Orphan detection threshold | >5 min | >5 min (`_triage_age > 300`) | MATCH |
| 24h staleness check | Included | `_age_secs < 86400` | MATCH |
| One-shot deletion | Included | `finally: unlink(missing_ok=True)` | MATCH |

**All deviations from the original plan are intentional improvements based on V1/V2 code review findings.** The plan's `status` field should be updated from `active` to reflect Phase 3/4's partial completion (reader code is done, writer code in SKILL.md is done, Phase 4 pending writer is deferred).

### SKILL.md Instructions Clarity

The SKILL.md instructions are **clear and unambiguous** for an LLM agent:

- Pre-Phase: Guard condition ("Only run when **no** triage tags present") is explicit and well-formatted.
- Phase 0: Two-step fallback (file tag first, inline fallback) is clearly ordered.
- Post-save: Step 1 (cleanup) then Step 2 (write result) ordering is explicitly stated with rationale.
- Heredoc template for result JSON includes clear field descriptions.

**One minor clarity issue:** The heredoc uses `<<'RESULT_EOF'` (single-quoted) which prevents variable expansion inside the heredoc. The LLM agent needs to construct the actual JSON with real values, not placeholder text like `<ISO 8601 UTC>`. The placeholders are clearly marked with angle brackets, so this is adequate. But it could be confused with literal strings. **Not a bug, just a style note.**

---

## 4. Deployment Ordering

### Recommended Order

**Either file can be deployed first.** There is no required deployment order.

- **SKILL.md first:** The new Post-save section writes `last-save-result.json`. The old `memory_retrieve.py` ignores it. When new `memory_retrieve.py` is deployed later, it picks up the result file. No window of failure.

- **memory_retrieve.py first:** The new notification blocks find no files and skip silently. When new SKILL.md is deployed later, saves start writing result files. Next prompt picks them up. No window of failure.

### Partial Deployment Risk

**NONE.** Unlike Phase 1 (triage_data externalization) which has a strict "SKILL.md first" requirement, these changes are fully order-independent because:
1. The reader (memory_retrieve.py) is fail-open on missing files
2. The writer (SKILL.md) writes to a global path that doesn't interfere with existing behavior
3. No existing functionality depends on these files existing or not existing

### Rollback Procedure

| File | Rollback Method | Side Effects |
|------|----------------|-------------|
| `memory_retrieve.py` | Remove lines 422-494 (3 notification blocks) | Stale `last-save-result.json` may accumulate in `$HOME/.claude/` but is harmless (small file, overwrites on next save) |
| `SKILL.md` | Remove Pre-Phase section (lines 38-54) + Post-save section (lines 235-262) | No more result file written. Old notification code fails silently (no file to read). Staging files may accumulate after crashes but cause no functional harm. |
| Both files | Revert both. Clean existing result files manually if desired: `rm -f ~/.claude/last-save-result.json` | Full rollback to pre-change state |

---

## 5. Test Coverage Assessment

### Test Suite Results

```
969 passed in 51.37s -- ALL PASS
```

### New Test Coverage (21 tests, 3 classes)

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestSaveConfirmation` | 8 | Same-project detail, cross-project brief, one-shot deletion, 24h expiry, corrupt JSON, errors with structured dicts, no-file baseline, short prompt |
| `TestOrphanCrashDetection` | 6 | Old triage detected, suppressed by save result, suppressed by pending, recent triage (< 5min) skipped, no triage file, short prompt |
| `TestPendingSaveNotification` | 7 | Multi-category plural, single-category singular, corrupt JSON, empty categories, no file, zero count, short prompt |

### Test Schema Accuracy

**The V1 BUG-1 fix has been incorporated.** Looking at `test_save_result_with_errors` (line 1198):
```python
"errors": [{"category": "decision", "error": "OCC_CONFLICT"}]
```
And the assertion (line 1208):
```python
assert "decision: OCC_CONFLICT" in stdout
```

This confirms the test uses the actual SKILL.md structured error schema (dict objects, not strings), and validates that the `isinstance(e, dict)` formatting in `memory_retrieve.py:450-455` correctly produces `decision: OCC_CONFLICT` output. **This was the exact gap identified by V1 BUG-1 and it has been fixed.**

### Missing Test Scenarios

| Scenario | Covered? | Priority |
|----------|----------|----------|
| Concurrent session race (read during write) | NO | LOW -- atomic `mv` makes this moot; requires multiprocessing test harness |
| `$HOME/.claude/` directory doesn't exist | Implicitly YES -- `monkeypatch` HOME to `tmp_path/fakehome` where `.claude` is created manually; tests that don't create it verify `exists()` returns False | N/A |
| Symlink for `last-save-result.json` | NO | VERY LOW -- `unlink(missing_ok=True)` removes symlink, not target; purely defensive |
| Pre-Phase cleanup actually runs correct `rm` pattern | NO (SKILL.md is agent instructions, not testable code) | N/A |
| Post-save heredoc produces valid JSON | NO (same -- agent instructions) | N/A |

**Verdict:** Test coverage is thorough for the Python code. The untestable parts (SKILL.md agent instructions) are inherently verification-by-review.

---

## 6. Cross-File Consistency Verification

### JSON Schema: Writer (SKILL.md) vs Reader (memory_retrieve.py)

| Field | SKILL.md Writer (line 247-253) | memory_retrieve.py Reader (line 429-456) | Match? |
|-------|-------------------------------|----------------------------------------|--------|
| `saved_at` | `"<ISO 8601 UTC>"` string | `datetime.fromisoformat(str(_saved_at).replace("Z", "+00:00"))` | MATCH |
| `project` | `"<cwd absolute path>"` | Compared via `== cwd` | MATCH |
| `categories` | `["category1", "category2"]` list | Iterated with `str(c)` + `html.escape()` | MATCH |
| `titles` | `["Title 1", "Title 2"]` list | Iterated with `str(t)` + `html.escape()` | MATCH |
| `errors` | `[{"category": "name", "error": "msg"}]` objects | `isinstance(_e, dict)` with `.get('category')` + `.get('error')` | MATCH |

### File Paths

| Path | SKILL.md | memory_retrieve.py | Match? |
|------|----------|-------------------|--------|
| Global result | `$HOME/.claude/last-save-result.json` | `Path.home() / ".claude" / "last-save-result.json"` | MATCH |
| Atomic tmp file | `$HOME/.claude/.last-save-result.tmp` | N/A (reader never sees this) | N/A |
| Triage data | `.claude/memory/.staging/triage-data.json` | `memory_root / ".staging" / "triage-data.json"` | MATCH |
| Triage pending | `.claude/memory/.staging/.triage-pending.json` | `memory_root / ".staging" / ".triage-pending.json"` | MATCH |

### Cleanup Lists

Pre-Phase cleanup (SKILL.md line 50):
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

Post-save cleanup (SKILL.md line 241):
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

**MATCH** -- Identical 4-pattern lists.

### Post-Save Order vs Orphan Detection Logic

SKILL.md post-save order: (1) Clean staging first, (2) Write result file.

This means: after cleanup, `triage-data.json` is gone. Then result file is written. If a prompt fires between steps 1 and 2:
- `triage-data.json` doesn't exist -> Block 2 skips (no orphan false positive)
- `last-save-result.json` doesn't exist yet -> Block 1 skips (no confirmation)
- Next prompt: result file exists -> Block 1 shows confirmation

This is correct. The BUG-4 fix (reverse post-save order) eliminates the false orphan window entirely.

---

## 7. Cross-Model Validation (Gemini 3.1 Pro)

### Findings

| # | Severity | Finding | Assessment |
|---|----------|---------|------------|
| 1 | LOW | `$HOME/.claude/` directory may not exist when writing result file | **VALID but practically moot** -- Claude Code creates `~/.claude/` on startup. The `cat > tmpfile` would fail if directory is missing, but this directory's absence implies Claude Code itself is broken. Could add `mkdir -p "$HOME/.claude"` as a safety belt. |

### Confirmed by Gemini

- Deployment ordering is safe (fail-open)
- Backwards compatibility verified (both directions)
- Performance overhead is negligible (~0.006ms worst case)
- Atomic write pattern (`cat > tmp + mv`) is correct on Linux (same-filesystem `rename(2)`)
- `_just_saved` flag logic is sound
- One-shot `finally` + `unlink(missing_ok=True)` pattern is robust

---

## 8. Findings Summary

### OPS-1: CLAUDE.md UserPromptSubmit Description Outdated (LOW)

**Location:** `CLAUDE.md:18`
**Issue:** The UserPromptSubmit hook description doesn't mention save confirmation, orphan detection, or pending notification behaviors added by the 3 new blocks.
**Impact:** Documentation inaccuracy only. No operational impact.
**Fix:** Add brief mention of notification behaviors to the hook description.

### OPS-2: Missing `mkdir -p "$HOME/.claude"` Before Result File Write (LOW)

**Location:** `SKILL.md:246`
**Issue:** The `cat > "$HOME/.claude/.last-save-result.tmp"` command assumes `$HOME/.claude/` exists. If the directory is missing (extremely unlikely in practice -- Claude Code creates it), the write fails and no save confirmation appears.
**Impact:** Silent loss of save confirmation notification in the edge case of missing global Claude config directory.
**Fix:** Add `mkdir -p "$HOME/.claude"` before the `cat` command.

### OPS-3: Action Plan Status Not Updated (INFORMATIONAL)

**Location:** `action-plans/plan-memory-save-noise-reduction.md:3`
**Issue:** The plan's frontmatter still shows Phase 3/4 reader code as not started (`[ ]`), but the reader code in `memory_retrieve.py` and corresponding SKILL.md instructions are fully implemented. The Phase 4 writer (SKILL.md writes `.triage-pending.json` on error) is correctly still marked as not started.
**Fix:** Update the plan checklist to reflect current implementation state.

---

## 9. Overall Verdict

### **PASS**

**Rationale:**
- **969/969 tests pass** with no regressions
- **Performance impact is negligible** (0.006ms worst case, <0.01% of hook runtime)
- **Backwards compatibility is verified** in all 4 version combinations
- **Deployment is order-independent** -- either file can go first
- **Rollback is clean** -- remove notification blocks or SKILL.md sections independently
- **Cross-file consistency is fully verified** -- JSON schema, file paths, cleanup lists all match
- **All V1 bugs (BUG-1 through BUG-4) have been addressed** in the implementation
- **Cross-model validation (Gemini 3.1 Pro) confirms** no high/medium severity issues

The two LOW-severity findings (CLAUDE.md outdated description, missing `mkdir -p`) are cosmetic/defensive improvements, not blocking issues. The implementation is production-ready.
