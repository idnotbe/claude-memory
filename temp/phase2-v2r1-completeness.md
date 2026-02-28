# Phase 2 V2R1: Completeness & Correctness Review

**Verdict: PASS_WITH_FIXES**

**Reviewer:** v2r1-completeness agent (Opus 4.6)
**Cross-validation:** Gemini 3.1 Pro (via PAL clink); Codex unavailable (quota)
**Files reviewed:** `skills/memory-management/SKILL.md` (lines 209-290), `CLAUDE.md` (line 34), git diff HEAD~1
**Date:** 2026-02-28

---

## Checklist Results

### 1. CUD Resolution (CREATE/UPDATE/RETIRE) -- PASS

All three command templates are preserved verbatim from the old Phase 3:
- **CREATE**: `memory_write.py --action create --category <cat> --target <path> --input <draft>` (line 224)
- **UPDATE**: `memory_write.py --action update --category <cat> --target <path> --input <draft> --hash <md5>` (line 226)
- **DELETE (retire)**: `memory_write.py --action retire --target <path> --reason "<why>"` (line 227)

The old version's "State the chosen action and one-line justification before each memory_write.py call" is reworded as "For each category, state the CUD resolution (CREATE / UPDATE / RETIRE / NOOP) and a one-line justification" (line 217) and moved to Step 1. Functionally equivalent.

### 2. Draft Path Validation -- PASS

Lines 219-221 preserve the exact same validation: path must start with `.claude/memory/.staging/draft-` and contain no `..` components. Wording changed from "Before reading any draft file" to "Before including any draft file path in commands" -- appropriate for the subagent delegation model.

### 3. memory_enforce.py After session_summary -- PASS

Lines 229-232 preserve the enforce call and the safety-belt note. The old version placed it after all saves; the new version includes it in the pre-computed command list (line 251: "N. <memory_enforce.py command, if applicable>"). Functionally equivalent.

### 4. Staging Cleanup (rm -f) -- PASS_WITH_FIXES

Line 254 includes:
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

**Finding (Medium):** Missing `draft-*.json`, `input-*.json`, and `new-info-*.txt` from the rm command.

- `memory_write.py` calls `_cleanup_input(args.input)` which deletes the `--input` draft file on successful CREATE/UPDATE. However:
  - Drafts that FAIL Phase 2 verification are never passed to `memory_write.py`, so they persist.
  - `draft-*-retire.json` files (written by Phase 1 for DELETE actions) are never passed as `--input` to the retire command.
  - `input-*.json` (Phase 1 partial JSON) and `new-info-*.txt` (Phase 1 summaries) are never cleaned by any script.

**Fix:** Update line 254 to:
```
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/draft-*.json .claude/memory/.staging/input-*.json .claude/memory/.staging/new-info-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json
```

Note: The Pre-Phase cleanup (lines 38-54) also only cleans `triage-data.json`, `context-*.txt`, `.triage-handled`, and `.triage-pending.json`. If draft/input/new-info files are added to the Phase 3 cleanup, they should also be added to the Pre-Phase cleanup for consistency.

### 5. Result File (atomic write, last-save-result.json) -- PASS

Lines 256-267 implement atomic write via tmp+mv pattern. All 5 fields documented at lines 273-278:
- `saved_at` (ISO 8601 UTC)
- `project` (absolute cwd path)
- `categories` (PASS only)
- `titles` (corresponding to saved memories)
- `errors` (list of `{"category", "error"}` objects)

This is a new feature (old Phase 3 had none). Correctly integrated.

### 6. Error Handling / .triage-pending.json Sentinel -- PASS

Lines 280-290 define the sentinel format:
```json
{"timestamp": "<ISO 8601 UTC>", "categories": ["<failed categories>"], "reason": "subagent_error"}
```

Cross-validated against `memory_retrieve.py` Block 3 (lines 484-496):
- Block 3 reads `.triage-pending.json`, parses as dict, extracts `_pending_data.get("categories", [])`.
- The sentinel format satisfies this: it's a dict with a `categories` list.
- Block 2 (orphan crash detection, lines 467-480) checks for `triage-data.json` WITHOUT `.triage-pending.json`, which is the complement case.
- Staging files are preserved on error (line 289: "Do NOT delete staging files"), allowing retry.

### 7. Task() Subagent Format Consistency -- PASS

Phase 3 Task format (lines 238-270):
```
Task(model: "haiku", subagent_type: "general-purpose", prompt: "...")
```

Phase 1 format (lines 72-76):
```
Task(model: config.category_models[...], subagent_type: "general-purpose", prompt: ...)
```

Consistent pattern. Phase 3 hardcodes "haiku" since it's always mechanical execution, while Phase 1 uses config-driven model selection.

### 8. Model Choice (haiku) -- PASS

Haiku is appropriate. The save subagent executes pre-computed Bash commands in sequence, records errors, and writes a JSON result file. No reasoning, content generation, or decision-making is required. This is the lightest possible workload.

## CLAUDE.md Update (Line 34) -- PASS

The description correctly reflects the new architecture: "delegates save execution to a single foreground Task subagent (haiku) that runs all memory_write.py commands, staging cleanup, and result file creation."

The Hook table (line 17) was also updated for the triage_data externalization (separate Fix A change) -- consistent.

## Cross-Validation Summary (Gemini 3.1 Pro)

Gemini independently confirmed:
- All 8 checklist items align with my findings
- Identified the same staging cleanup gap (draft files missing from rm)
- Additionally flagged unquoted `--target`/`--input` paths in command templates (Low severity)
- Positively noted the quoted here-doc (`<<'__MEMORY_SAVE_RESULT_EOF__'`) as good shell injection prevention

## Additional Findings

### Low: Unquoted CLI Arguments in Command Templates (Gemini finding, confirmed)
Lines 224-227 show `--target <path> --input <draft>` without quotes. While paths are slugified and unlikely to contain spaces, defensive quoting (`--target "<path>" --input "<draft>"`) would be more robust.

### Info: Old Phase 3 Had No Staging Cleanup or Result File
The old Phase 3 (lines 188-213 in previous commit) had neither staging cleanup nor result file writing. These are entirely new features added in this rewrite. Both are well-designed additions.

### Info: Pre-Phase Cleanup Scope Mismatch
The Pre-Phase staging cleanup (lines 48-51) does not include `draft-*.json`, `input-*.json`, or `new-info-*.txt`. If these are added to the Phase 3 subagent cleanup, they should also be added to Pre-Phase for consistency, since stale draft/input files from a crashed session would also need cleaning.

---

## Summary of Required Fixes

| # | Severity | Description | Location |
|---|----------|-------------|----------|
| 1 | Medium | Add `draft-*.json`, `input-*.json`, `new-info-*.txt` to Phase 3 staging cleanup | SKILL.md line 254 |
| 2 | Low | Same additions to Pre-Phase staging cleanup for consistency | SKILL.md line 50 |
| 3 | Low | Quote `--target` and `--input` parameters in command templates | SKILL.md lines 224-227 |
