# SKILL.md Rewrite -- Implementation Notes

**Date:** 2026-02-16
**Task:** #2 -- Rewrite SKILL.md for parallel subagent orchestration
**Status:** Complete

---

## Changes Made

### Memory Consolidation section (lines 30-92)
Completely rewritten from sequential 3-step flow to parallel 4-phase flow:

- **Phase 0: Parse Triage Output** -- Extract `<triage_data>` JSON block, read parallel config
- **Phase 1: Parallel Drafting** -- Spawn per-category Task subagents in parallel with configured models
- **Phase 2: Verification** -- Spawn verification subagents in parallel with `verification_model`
- **Phase 3: Save (Main Agent)** -- Main agent applies CUD resolution table, calls memory_write.py

### CUD Verification Rules table (lines 94-110)
Simplified from 3-layer (L1/L2/L3 = Python/Sonnet/Opus) to 2-layer (L1/L2 = Python/Subagent):
- Removed L3 (Opus) column -- no longer needed since main agent is orchestrator, not evaluator
- 11 rows -> 8 rows (removed redundant combinations)
- Table header changed from `L2 (Sonnet) | L3 (Opus)` to `L2 (Subagent)`

### Rules section (line 192-196)
- Rule #1: Updated "3-step" to "4-phase"
- Rule #4: Updated "3-layer" to "2-layer"

### Config section (lines 208-211)
Added 4 new config entries for `triage.parallel.*`.

---

## Gemini 3 Pro Review Findings + Resolutions

Ran `pal clink` with Gemini 3 Pro as code reviewer. Key findings and how they were addressed:

### Critical Issues (Fixed)

1. **Orphaned CUD Verification Logic** -- Gemini flagged that the CUD resolution table was defined but no agent was instructed to apply it.
   - **Fix**: Added explicit step 3-4 in subagent instructions telling them to parse memory_candidate.py output fields (`vetoes`, `pre_action`, `candidate`) and apply safety defaults. Also updated Phase 3 description to clarify the main agent applies the resolution table as final arbiter.

2. **Ambiguous DELETE Flow for Haiku** -- Phase 1 said "write draft JSON" but Phase 3 said "no temp file needed" for DELETE.
   - **Fix**: Step 5 now explicitly distinguishes: CREATE/UPDATE write full memory JSON; DELETE writes `{"action": "delete", "target": "...", "reason": "..."}` to the draft path.

3. **Missing Field References** -- Subagent instructions were too high-level for haiku.
   - **Fix**: Added step 3 with explicit field names (`vetoes` list, `pre_action` string, `candidate` object) and what to check for each.

### Noted but Not Changed

4. **Contradictory Safety Defaults** -- Gemini flagged `UPDATE_OR_DELETE + CREATE -> CREATE` as contradicting "UPDATE > CREATE" safety text.
   - **Rationale for keeping**: This row matches the team lead's specification verbatim. The scenario means the Python script found a candidate (UPDATE_OR_DELETE) but the subagent, after reading the candidate, decided the new info is different enough to warrant a new entry (CREATE). This is a valid override -- the subagent has semantic understanding the script lacks. The safety defaults text refers to LLM *disagreement* scenarios, not informed decisions.

### Low Priority (Fixed)

5. **Confusing Numbering** -- Steps were "1. Parse", "2. Phase 1", "3. Phase 2", "4. Phase 3".
   - **Fix**: Renamed to "Phase 0", "Phase 1", "Phase 2", "Phase 3" for consistency.

6. **Vague "integrate"** -- Gemini flagged "integrate new info" as ambiguous.
   - **Fix**: Step 4 now reads: "append new items to list fields, merge new tags, update scalar fields. Add a change entry to the `changes` list."

---

## Preserved Sections (Unchanged)

- YAML frontmatter (lines 1-13)
- Categories table (lines 19-28)
- Memory JSON Format (lines 112-143)
- Session Rolling Window (lines 145-180)
- When the User Asks About Memories (lines 182-188)
- Config section structure (lines 199-213, with 4 new entries added)

---

## Haiku Reliability Assessment

The subagent instructions were designed for haiku reliability:

1. **Numbered steps** -- Linear 1-6 sequence, no branching logic within steps
2. **Explicit field names** -- `vetoes`, `pre_action`, `candidate` spelled out
3. **Clear stop conditions** -- "report NOOP and stop" at two points (vetoes, pre_action=NOOP)
4. **Concrete output format** -- Exact JSON shown for DELETE; "complete memory JSON" for CREATE/UPDATE
5. **No table lookup required** -- Safety defaults embedded inline ("prefer UPDATE over DELETE")
6. **Single tool call** -- Only one bash command (memory_candidate.py) to run

The CUD resolution table remains in a separate section for the main agent (Opus) to apply as final arbiter in Phase 3.

---

## File

Modified: `skills/memory-management/SKILL.md`
