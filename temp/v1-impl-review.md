# V1 Action Plan Implementation Review

**Reviewer:** impl-verifier (Opus 4.6)
**Date:** 2026-02-28
**Target:** `temp/action-plan-draft-v1.md`
**Cross-validation:** Gemini 3.1 Pro (PAL clink), Vibe-check metacognitive pass

---

## Summary

The action plan is well-structured with correct phase ordering and accurate code references. However, it contains **2 critical implementation bugs** that would cause runtime failures if implemented as written, plus several high-severity omissions around test coverage and documentation updates.

**Verdict:** Solid plan that needs targeted fixes before implementation.

---

## 1. Code Reference Accuracy

All code references in the plan's "코드 참조" table (lines 78-88) are **CORRECT**:

| Plan Reference | Verified? | Notes |
|---|---|---|
| `hooks/hooks.json` lines 8-13 | YES | Stop hook `type: "command"` confirmed |
| `memory_triage.py` lines 950-953 | YES | `<triage_data>` inline embedding confirmed |
| `memory_triage.py` lines 1117-1131 | YES | Context file write + block message output confirmed |
| `memory_triage.py` lines 870-955 | YES | `format_block_message()` full range confirmed |
| `SKILL.md` lines 38-40 | YES | Phase 0 triage output parsing confirmed |
| `SKILL.md` lines 188-212 | YES | Phase 3 save operations confirmed |
| `SKILL.md` lines 229-241 | YES | CUD resolution table confirmed |
| `memory_retrieve.py` lines 411-429 | PARTIAL | See Issue #2 below -- insertion point needs adjustment |

---

## 2. Critical Issues

### Issue #1: `triage_data` Variable Scope Bug (Phase 1) -- BLOCKER

**Severity:** Critical (would cause NameError at runtime)

The plan (lines 169-183) proposes writing `triage_data` to a file inside `_run_triage()`:

```python
# Plan proposes this in _run_triage() context (line 1117-1131 area)
triage_data_path = os.path.join(cwd, ".claude", "memory", ".staging", "triage-data.json")
os.write(fd, json.dumps(triage_data, indent=2).encode("utf-8"))
```

**Problem:** `triage_data` is a **local variable** constructed inside `format_block_message()` at lines 931-948. It does NOT exist in `_run_triage()` scope. The plan's proposed code would raise `NameError: name 'triage_data' is not defined`.

**Fix options:**
1. **Extract helper:** Create `build_triage_data(results, context_paths, parallel_config, category_descriptions)` that returns the dict. Call it from `_run_triage()`, write to file, then pass the dict into a simplified `format_block_message()`.
2. **Return tuple:** Have `format_block_message()` return `(message_str, triage_data_dict)` instead of just a string. Caller writes the dict to file.

Option 1 is cleaner (separation of concerns).

### Issue #2: Phase 4 Insertion Point Dead Code (memory_retrieve.py) -- BLOCKER

**Severity:** Critical (pending save detection would never fire for short prompts)

The plan (line 87, lines 376-387) says to insert pending save detection at "line 429 근처" of `memory_retrieve.py`. However:

- Line 423: `if len(user_prompt.strip()) < 10:`
- Line 429: `sys.exit(0)`  (exits for short prompts)

Inserting AFTER line 429 means pending save notifications would never display for short prompts like "hi" or single-word inputs. This defeats the purpose -- pending saves should be detected on EVERY session start.

**Fix:** Insert the pending save detection block **before line 423** (between config loading at ~line 420 and the short-prompt check). The detection should fire regardless of prompt content.

---

## 3. High-Severity Issues

### Issue #3: Test Suite Breakage Not Addressed (Phase 1)

**Severity:** High (CI failure)

Multiple existing tests assert `"<triage_data>" in message` on `format_block_message()` output:

- `tests/test_memory_triage.py`: Lines 257, 280, 350 and class `TestTriageDataIncludesDescription`
- `tests/test_adversarial_descriptions.py`: Lines 136, 155, 456, 466, 501, 516, 714

Phase 1 removes the inline `<triage_data>` block from the message string, replacing it with `<triage_data_file>path</triage_data_file>`. All these tests will fail.

**Fix:** Add explicit step in Phase 1: "Update all tests that assert `<triage_data>` presence to assert `<triage_data_file>` tag presence instead, and verify the referenced file contains valid JSON."

### Issue #4: Phase 4 Cleanup Race Condition

**Severity:** High (data loss on subagent failure)

The plan says `/memory:save` deletes `.triage-pending.json` after execution. But if Phase 2 delegates saves to a Task subagent that crashes mid-save, the main agent might delete the pending file prematurely (believing the Task "completed").

**Fix:** Phase 4 should specify that `.triage-pending.json` is only deleted AFTER verifying the Task subagent's return summary confirms all saves succeeded. On partial failure, the pending file should be preserved with updated state.

### Issue #5: Documentation Drift

**Severity:** High (future sessions will have stale instructions)

These files reference the inline `<triage_data>` structure and would become outdated:
- `CLAUDE.md` line 22: "structured `<triage_data>` JSON + per-category context files"
- `SKILL.md` line 39: "Extract the `<triage_data>` JSON block from the stop hook output"
- `SKILL.md` line 58: "The `<triage_data>` JSON block emits lowercase category names"

**Fix:** Add documentation update steps to Phase 1 checklist for CLAUDE.md and SKILL.md references.

---

## 4. Medium-Severity Issues

### Issue #6: SessionStart Hook stdin Handling (Phase 3)

**Severity:** Medium

`SessionStart` hooks do NOT receive a user prompt via stdin (unlike `UserPromptSubmit` hooks). The new `memory_session_confirm.py` script must handle empty or absent stdin gracefully. If it reuses patterns from `memory_retrieve.py` (which reads `user_prompt` from stdin JSON), it will crash on `KeyError` or `json.JSONDecodeError`.

**Fix:** Add a note in Phase 3 that `memory_session_confirm.py` should NOT attempt to parse stdin for user prompt data. It should only read `last-save-result.json` and output the confirmation message.

### Issue #7: Phase 2 `$CLAUDE_PLUGIN_ROOT` in Task Subagents

**Severity:** Medium (acknowledged in plan's risk table)

The plan correctly identifies this as a risk ("주의사항") and proposes a mitigation (adding `source .venv/bin/activate` to subagent prompt if needed). This is adequate. Task subagents typically inherit the session environment, so this should work, but early validation in Phase 2 is important.

---

## 5. Execution Order Assessment

The phase ordering is **sound**:

1. **Phase 0 first:** Correct -- agent hook isolation test is cheap and informs architecture direction
2. **Phase 1 before Phase 2:** Correct -- Fix A (triage_data externalization) is a prerequisite for Phase 4 (which reuses triage-data.json)
3. **Phase 2 after Phase 1:** Correct -- Phase 3 subagent consolidation is independent but benefits from reduced reason field size
4. **Phase 3 after Phase 2:** Correct -- SessionStart confirmation depends on save pipeline being functional
5. **Phase 4 after Phase 1:** Correct -- explicitly declared dependency on triage-data.json externalization

**One ordering concern:** Phase 4 depends on Phase 1's file-based triage_data, but Phase 4 also interacts with Phase 2's single-subagent save pipeline. The plan should note this dual dependency explicitly.

---

## 6. Backwards Compatibility Assessment

**Generally good.** The plan includes fallback parsing in SKILL.md (read `<triage_data_file>` tag, fall back to inline `<triage_data>`). This handles the transition gracefully.

**Gap:** No version detection mechanism. If a user has an older `memory_triage.py` (producing inline triage_data) with a newer `SKILL.md` (expecting file-based), the fallback handles it. But the reverse (newer triage.py + older SKILL.md cache) would produce a file that SKILL.md doesn't know to read. This is unlikely in practice (plugin updates are atomic), but worth noting.

---

## 7. Missing Steps Summary

| Phase | Missing Step | Priority |
|---|---|---|
| Phase 1 | Extract `triage_data` construction from `format_block_message()` | Critical |
| Phase 1 | Update ~15+ existing tests that assert inline `<triage_data>` | High |
| Phase 1 | Update CLAUDE.md documentation references | High |
| Phase 2 | Early `$CLAUDE_PLUGIN_ROOT` validation test step | Medium |
| Phase 3 | Note that `memory_session_confirm.py` must not parse stdin for user_prompt | Medium |
| Phase 4 | Adjust insertion point in `memory_retrieve.py` to before line 423 | Critical |
| Phase 4 | Add save-success verification before pending file cleanup | High |
| Phase 4 | Declare dual dependency on Phase 1 AND Phase 2 | Low |

---

## 8. Cross-Validation Results

### Vibe-Check (Metacognitive)
- Approach validated as methodical and correctly scoped
- Flagged risk of depth-over-breadth (spending too much time on Phase 1 vs later phases) -- addressed by covering all phases
- Confirmed all six review dimensions (code accuracy, feasibility, order, missing steps, tests, backwards compat) are covered

### Gemini 3.1 Pro (PAL Clink)
- **Confirmed** all critical and high findings independently
- **Added:** Phase 4 cleanup race condition (Issue #4)
- **Added:** Documentation drift concern (Issue #5)
- **Added:** SessionStart stdin handling (Issue #6)
- **Confirmed** phase ordering is sound
- **Confirmed** atomic write pattern and SKILL.md fallback are good practices

---

## 9. Positive Observations

1. **Atomic file writes:** Phase 1's `.tmp` + `os.replace()` pattern prevents partial reads from race conditions
2. **Backwards-compatible fallback:** SKILL.md fallback to inline `<triage_data>` parsing is well-designed
3. **Time-boxed experimentation:** Phase 0's kill criteria and branch isolation are disciplined
4. **Risk table completeness:** All major risks are identified with mitigations
5. **Research backing:** Claims are well-sourced from multi-agent research with cross-validation

---

## Final Verdict

**Plan quality: 7.5/10** -- Well-researched and well-structured, with correct code references and sound phase ordering. The two critical bugs (triage_data scope, retrieve.py insertion point) are fixable without architectural changes. Address the 8 missing steps listed above, and this plan is implementation-ready.
