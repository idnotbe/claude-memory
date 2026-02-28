# V2 Action Plan Contrarian Review

**Reviewer:** Opus 4.6 (contrarian attack role)
**Target:** `temp/action-plan-draft-v2.md`
**Cross-validated by:** Gemini 3.1 Pro (gemini-3-pro-preview via PAL clink)
**Date:** 2026-02-28

---

## Executive Summary

The action plan is well-structured and addresses most of the v2-contrarian.md findings, but contains **8 concrete flaws** ranging from unreachable code paths to architectural gaps. Gemini independently agreed with all 8 findings. The 85% noise reduction headline figure is not achievable as stated -- realistic estimates for multi-category saves are 50-65%.

---

## Finding 1: Phase 2 Task Prompt Size Risk Is Unaddressed

**Severity:** Medium
**Gemini verdict:** AGREE

The plan says to pass CUD resolution context directly in the Task prompt (line 287-289): "Phase 1/2 results are short (1-2 lines per category) so direct inclusion in prompt is appropriate." This claim is never measured.

For a 6-category save, the Task prompt must contain:
- 6 draft file paths + 6 verification statuses + 6 L1/L2 resolution pairs
- The full CUD resolution table (8 rows x 4 columns, currently ~15 lines in SKILL.md at lines 230-240)
- The 3 "key principles" (lines 243-246)
- Plugin root path + memory_write.py / memory_enforce.py invocation syntax
- Instructions for cleanup (triage-data.json, context-*.txt deletion)
- Instructions for writing last-save-result.json

Conservative estimate: 800-1,200 tokens of static prompt before any dynamic content. This eats into the subagent's working context, potentially degrading CUD resolution quality for edge cases (e.g., UPDATE_OR_DELETE vs CREATE requires nuanced judgment).

**Recommendation:** Measure the actual prompt size for 3-category and 6-category saves. If >1,000 tokens, consider externalizing the CUD table to a file the subagent reads, or pre-resolving CUD in the main agent (since this is a deterministic table lookup, not LLM judgment).

---

## Finding 2: Phase 3 Cross-Project Confirmation Failure

**Severity:** Low-Medium
**Gemini verdict:** AGREE

`last-save-result.json` lives in `.claude/memory/.staging/` which is project-local. The v2-contrarian.md (Attack 4, lines 65-72) identified cross-project loss as a fatal flaw for deferred mode. The action plan correctly addresses this for Phase 5b (deferred opt-in) at line 489 but does NOT acknowledge the same issue for Phase 3's save confirmation.

Scenario: User completes a session in Project-X (save succeeds, result file written), then opens Project-Y. The confirmation never displays. The file persists in Project-X until the user eventually returns. This is NOT memory loss (saves already happened), but it defeats the stated goal of "silent failure prevention" -- the user cannot distinguish "save succeeded in another project" from "save silently failed."

**Recommendation:** Document this as a known limitation. Optionally, write the result file to a user-global path (e.g., `~/.claude/last-save-result.json`) instead of a project-local path, and include the project path in the JSON for disambiguation.

---

## Finding 3: The 85% Noise Reduction Estimate Is Optimistic

**Severity:** High (credibility of the plan)
**Gemini verdict:** AGREE (estimates 50-60% for multi-category saves)

The plan claims 50-100+ lines -> 8-12 lines (85% reduction) at line 315. Let me count what actually remains visible after Fix A + Fix B for a 3-category save:

| Source | Lines |
|--------|-------|
| Stop hook block notification (reason field, post-Fix A) | 3-5 |
| Main agent reads triage-data.json (Read tool call) | 1-2 |
| Main agent reads memory-config.json | 1 |
| Phase 1: 3 parallel drafting Task spawns + Done lines | 3-6 |
| Phase 2: 3 parallel verification Task spawns + Done lines | 3-6 |
| Phase 3: 1 save Task spawn + Done line | 1-2 |
| Main agent summary output | 1-2 |
| **Total** | **13-24** |

For a 1-category save: ~8-12 lines (matches the plan).
For a 3-category save: ~13-24 lines (far exceeds the plan's claim).
For a 6-category save: ~21-38 lines.

The plan only accounts for Fix A (triage_data externalization) and Fix B (Phase 3 consolidation). Phase 1/2 subagent spawn lines are untouched and scale linearly with category count. The 85% figure holds only for 1-category saves.

**Recommendation:** Report noise reduction as a range: "85% for single-category, 50-65% for multi-category saves." If a higher reduction is needed for multi-category, Phase 1/2 subagent spawns must also be consolidated (which is Solution 4 / Phase 5c in the plan).

---

## Finding 4: Subagent Crash Before Cleanup Leaves Stale Files Forever

**Severity:** Medium-High
**Gemini verdict:** AGREE

The plan specifies cleanup in Phase 2 (line 291-293): subagent deletes `.staging/triage-data.json` and `context-*.txt` after save. Phase 4 (line 403) intentionally preserves files on handled failures. But neither path covers **unhandled crashes** (OOM, Claude Code bug, network timeout killing the subagent mid-execution).

On an unhandled crash:
1. `triage-data.json` persists
2. `context-*.txt` files persist
3. `.triage-handled` sentinel persists (written at line 1104 of memory_triage.py, BEFORE save)
4. No `last-save-result.json` is written (subagent didn't finish)
5. No `.triage-pending.json` is written (error handler didn't run)

Result: Next session, `memory_retrieve.py` finds no result file and no pending file. The user gets zero feedback. Meanwhile, stale `.triage-handled` may cause the next triage run to skip processing (if it checks the sentinel). Stale context files accumulate indefinitely.

**Recommendation:** Add a staleness check. Either:
- (a) In `memory_retrieve.py`: if `triage-data.json` exists but neither `last-save-result.json` nor `.triage-pending.json` exists, treat as orphaned crash state and notify the user.
- (b) In `memory_triage.py`: before writing new staging files, check for and clean up stale files older than N hours.
- (c) Both.

---

## Finding 5: Phase 5a Agent Hook Lifecycle Misunderstanding

**Severity:** Medium
**Gemini verdict:** AGREE

Phase 5a (line 460) says: "`ok: false` return to prevent session exit during save (or `ok: true` to allow exit after save)." This implies the agent hook can dynamically choose between blocking and allowing -- but agent hooks return exactly once. They execute synchronously: the session is blocked for the entire duration of the agent hook's execution, then the single `ok` value determines what happens next.

The correct mental model is:
- Agent hook starts -> session is blocked (cannot exit)
- Agent hook runs full pipeline (all tool calls happen here)
- Agent hook returns `ok: true` -> session exit proceeds
- Agent hook returns `ok: false` -> session exit is blocked, reason shown to user

The plan's Phase 0 Experiment C (line 125) correctly tests `ok: false`, but the Phase 5a description conflates "blocking during execution" with "blocking via return value." This matters because if the save pipeline needs 60-120 seconds, the session is blocked for that entire duration regardless of the return value. The `ok` value only determines whether the session can exit AFTER the hook finishes.

**Recommendation:** Clarify the lifecycle model in Phase 5a. The agent hook should return `ok: true` after successful save (allowing session exit), or `ok: false` with an error reason on failure. The blocking-during-execution is automatic, not controlled by `ok`.

---

## Finding 6: `memory_retrieve.py` Insertion Point Is After `sys.exit(0)`

**Severity:** High (code correctness)
**Gemini verdict:** AGREE

The plan specifies inserting save confirmation logic at "line 429 이후" (after line 429) of `memory_retrieve.py`. Line 429 is:

```python
        sys.exit(0)
```

This is the early exit for short prompts (<10 chars). Code inserted after line 429 (i.e., at line 430+) IS reachable for normal prompts but NOT for short prompts. This means:

- User opens new session, types "hi" -> short prompt exit fires -> **save confirmation never shown**
- User opens new session, types "continue" (8 chars) -> short prompt exit fires -> **save confirmation never shown**
- User opens new session, types "what did we do last time?" -> save confirmation shown

Common first-session prompts like "hi", "hey", "continue", "go on", "yes", "ready" are all <10 chars and will miss the confirmation.

**Recommendation:** Insert the save confirmation logic BEFORE the short-prompt check (between lines 421 and 422). The confirmation is a one-shot file read that should fire regardless of prompt length. Note: this adds ~1ms of file I/O overhead to every UserPromptSubmit invocation (checking if the file exists), which is negligible but should be documented.

---

## Finding 7: `format_block_message()` Data Flow Requires Nontrivial Refactoring

**Severity:** Medium
**Gemini verdict:** AGREE

The plan's Phase 1 design (lines 186-219) shows triage_data being written to file BEFORE `format_block_message()` is called, with a new `triage_data_path` parameter. But `triage_data` is constructed INSIDE `format_block_message()` at lines 911-948 of `memory_triage.py`. The plan acknowledges this in a note (line 203):

> "참고: `triage_data` dict는 `format_block_message()` 내부에서 생성된다 (lines 908-948). 이를 외부에서도 접근하려면 `format_block_message()`가 `triage_data`를 반환하거나, `_run_triage()`에서 별도로 구성해야 한다."

This is hand-waved as "choose the cleanest approach at implementation time." But the cleanest approach -- extracting `triage_data` construction from `format_block_message()` -- changes the function's interface, return type, and caller contract. The function currently returns `str`; it would need to return `tuple[str, dict]` or the caller would need to independently reconstruct the same dict. Either approach requires careful attention to keep the inline JSON (for backwards compatibility fallback) and the file JSON in sync.

This is not a 10-line change. It is a ~40-60 line refactoring of a critical-path function with security-sensitive sanitization logic.

**Recommendation:** Design the refactoring explicitly. Preferred approach: extract a `build_triage_data()` function that both `format_block_message()` and `_run_triage()` can call. This keeps the data construction logic in one place and avoids drift between inline and file formats.

---

## Finding 8: Phase 4 `/memory:save` Resume Has No Implementation Path

**Severity:** Medium-High
**Gemini verdict:** AGREE

Phase 4 (line 423-424) says:

> "print(f'<memory-note>{n} unsaved memories from last session. Use /memory:save to save them.</memory-note>')"

But `/memory:save` (the skill command at `commands/memory-save.md` and `skills/memory-management/SKILL.md`) currently triggers the full 4-phase pipeline from Phase 0 (parse triage output). It does not know how to:

1. Detect that pre-existing `triage-data.json` and `context-*.txt` files represent a pending state
2. Skip triage (Phase 0) and use the existing files
3. Resume from the point of failure (which Phase failed? Were any categories already saved?)

Implementing "resume from pending" requires:
- A new execution mode in SKILL.md (detect pending files -> skip Phase 0 -> reuse context files)
- Handling partial saves (what if 2 of 3 categories were saved before the crash?)
- Staleness detection (are these context files from 10 minutes ago or 10 days ago?)

The plan lists "cleanup 로직" as a single checklist item (line 444) but the actual implementation is a full new SKILL.md execution branch.

**Recommendation:** Either (a) scope the resume feature explicitly with its own Phase-level design, or (b) simplify: instead of resuming, just notify the user about the failure and let them trigger a fresh save manually (accepting that the context files are stale and the save quality will be degraded for session_summary).

---

## Previously Identified Issues (v2-contrarian.md) -- Status Check

| v2-contrarian Issue | Addressed in v2 Plan? | Notes |
|---|---|---|
| Deferred mode ~5-10% save rate | YES (line 436-438) | Correctly relegated to error fallback only |
| Deferred mode breaks session_summary | YES (line 488) | Noted as quality degradation |
| Cross-project loss | PARTIAL | Addressed for deferred (5b) but not for confirmation (Phase 3) |
| Agent hook is not 10-min experiment | YES (line 106, 597) | Time-boxed to half-day, schema differences noted |
| Agent hook schema incompatibility | YES (lines 133-137) | ok:true/false schema documented |
| Agent hook structured data limitation | YES (line 136) | "Cannot pass arbitrary structured data" noted |
| Agent hook timeout concern | YES (line 104-105) | Listed as open question |
| Fix A+B promoted to primary | YES (line 61) | Correctly made primary path |

All major v2-contrarian issues are addressed. The remaining gaps are implementation-level details (Findings 1, 6, 7, 8 above) that were not in scope for the original contrarian analysis.

---

## Gemini Cross-Validation Notes

Gemini (gemini-3.1-pro-preview) agreed with all 8 findings and proposed 2 additional ones:

**Gemini Finding 9 (cleanup for last-save-result.json):** REJECTED. The plan DOES include `result_path.unlink()` at line 373 of the action plan. Gemini missed this. The one-shot deletion logic is already specified.

**Gemini Finding 10 (I/O latency on UserPromptSubmit):** PARTIALLY VALID. Adding a `Path.exists()` check before the short-prompt exit does add ~0.1-1ms overhead to every prompt. This is negligible in absolute terms but violates the principle of the short-prompt fast path. Acceptable trade-off, but should be documented.

---

## Severity Summary

| Severity | Findings | Action Required |
|---|---|---|
| High | #3 (85% estimate), #6 (unreachable code) | Must fix before implementation |
| Medium-High | #4 (stale files), #8 (resume path) | Should fix before implementation |
| Medium | #1 (prompt size), #5 (lifecycle), #7 (data flow) | Design before implementation |
| Low-Medium | #2 (cross-project confirmation) | Document as known limitation |

**Bottom line:** The plan's architecture is sound, but 3 findings (#3, #6, #8) will cause visible failures if implemented as written. The 85% noise reduction headline should be revised to "85% for 1-category, 50-65% for multi-category" or Phase 1/2 spawns must also be consolidated.
