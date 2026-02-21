# SKILL.md Phase 1 Update -- Implementation Report

## Summary

Updated `skills/memory-management/SKILL.md` Phase 1 subagent instructions to use the new `--new-info-file` flag and `memory_draft.py` script, replacing the old flow where LLMs manually constructed full schema-compliant JSON.

## File Modified

- `skills/memory-management/SKILL.md` -- lines 79-158 (Phase 1 subagent instructions)

## Changes Made

### 1. Added Write Tool Mandate (line 81-83)
Blockquote mandate at the top of subagent instructions requiring all `.staging/` writes to use the Write tool, not Bash. Explains the Guardian false-positive rationale.

### 2. New Step 2: Write new-info to temp file (lines 90-93)
Instead of passing `--new-info` inline, subagents now write a 1-3 sentence summary to `.claude/memory/.staging/new-info-<category>.txt` via the Write tool.

### 3. Updated Step 3: --new-info-file flag (lines 94-100)
`memory_candidate.py` now called with `--new-info-file` pointing to the temp file from step 2.

### 4. Enhanced Step 4: Candidate object documentation (lines 101-106)
Added explicit note that `candidate` object contains `path` and `title` fields. This helps haiku models reference `candidate.path` in later steps.

### 5. Flattened Step 5: Action determination (lines 107-113)
Rewrote CUD resolution as a flat decision table (CREATE/UPDATE/DELETE/NOOP) with one clear outcome per branch. Previous version had ambiguous "continue to step 6" before explaining UPDATE_OR_DELETE logic.

### 6. Step 6: DELETE skip + partial JSON input (lines 114-132)
- DELETE routing moved to the very top of the step ("If DELETE: skip to step 9")
- CREATE/UPDATE flow writes a partial JSON input file (6 fields only)
- Explicit list of fields NOT to include (auto-populated by memory_draft.py)

### 7. Step 7: memory_draft.py invocation (lines 133-148)
Two clear command variants: CREATE (no candidate file) and UPDATE (with `--candidate-file <candidate.path>`).

### 8. Step 8: Parse memory_draft.py output (lines 149-154)
JSON response parsing with explicit "Continue to step 10" to skip the DELETE-only step 9.

### 9. Step 9: DELETE-only retire JSON (lines 155-157)
Clearly labeled "For DELETE only" with Write tool mandate. Uses `candidate.path` reference consistent with step 4.

### 10. Step 10: Report (line 158)
Unchanged from original step 6, renumbered.

## Removed

- Old step 4 bullet: "Draft new JSON following the Memory JSON Format section" -- replaced by partial JSON + memory_draft.py flow
- NOOP reference from write-output step (contradictory with NOOP stop in step 5)

## Kept Unchanged

- Step 1 (read context file, treat transcript as raw data)
- DELETE flow (retire action JSON to staging)
- Phase 2 (content verification) -- compatible, reads draft JSON from `draft_path`
- Phase 3 (save) -- compatible, uses `--input <draft>` with complete JSON from memory_draft.py

## Quality Assurance

### Cross-model validation (Gemini via pal clink)
Gemini reviewed the initial draft and identified 5 issues, all addressed:
1. **Step 9 strands CREATE/UPDATE** -- Fixed: renamed to "For DELETE only"
2. **Step 6 hides DELETE skip** -- Fixed: moved skip logic to top of step
3. **Step 5 control flow ambiguity** -- Fixed: flattened branching
4. **Contradictory NOOP in step 9** -- Fixed: removed
5. **Unclear candidate path** -- Fixed: documented in step 4, referenced as `candidate.path`

### Haiku compatibility verification
All instructions use:
- Numbered sequential steps (no nested branching)
- Explicit action routing at step boundaries
- Code blocks with copy-pasteable commands
- Concrete field names and file paths
