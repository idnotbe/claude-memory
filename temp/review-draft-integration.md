# Integration Review: memory_draft.py + --new-info-file + SKILL.md Updates

**Reviewer:** reviewer-integration
**Date:** 2026-02-21
**Files Reviewed:**
1. `hooks/scripts/memory_draft.py` (NEW)
2. `hooks/scripts/memory_candidate.py` (MODIFIED)
3. `skills/memory-management/SKILL.md` (MODIFIED)
4. `hooks/scripts/memory_write.py` (context, unchanged)
5. `hooks/hooks.json` (context, unchanged)

---

## Executive Summary

The implementation is **sound and pipeline-compatible**. The draft assembler correctly separates assembly from enforcement, and the SKILL.md instructions are clear enough for haiku-level subagents. I found **2 real issues** (one medium, one low), **1 potential race condition** (low risk), and several design observations that are acceptable as-is.

---

## Pipeline Trace: End-to-End Flow

### Full pipeline path:
```
Triage hook (memory_triage.py)
  -> SKILL.md Phase 0: Parse <triage_data>
  -> Phase 1 subagent:
       1. Read context file
       2. Write new-info summary -> .staging/new-info-<cat>.txt (Write tool)
       3. memory_candidate.py --new-info-file .staging/new-info-<cat>.txt
       4. Parse candidate output (vetoes, pre_action, structural_cud)
       5. Write partial JSON -> .staging/input-<cat>.json (Write tool)
       6. memory_draft.py --action create|update --input-file .staging/input-<cat>.json
       7. Parse draft output -> draft_path
       8. Report: action, draft_path, justification
  -> Phase 2 verifier:
       1. Read draft JSON (complete, schema-valid)
       2. Read context file
       3. Assess content quality
       4. Report PASS/FAIL
  -> Phase 3 main agent:
       1. CUD resolution
       2. memory_write.py --input <draft_path> --target <final_path>
```

---

## Findings

### FINDING-1: memory_write.py `_read_input` rejects /tmp/ paths; memory_draft.py allows them [MEDIUM]

**Issue:** `memory_draft.py:validate_input_path()` (line 67-88) allows input files from both `.claude/memory/.staging/` AND `/tmp/`. This is intentional per spec comment on line 73-74. However, `memory_draft.py:write_draft()` (line 219-233) writes draft output to `.claude/memory/.staging/` which IS accepted by `memory_write.py:_read_input()`.

**Pipeline impact:** None for the current flow. The asymmetry in path validation between memory_draft.py (accepts `.staging/` + `/tmp/` as INPUT sources) vs memory_write.py (accepts only `.staging/` as INPUT) is actually correct:
- memory_draft.py reads from broader paths (LLM may use /tmp/ for Write tool output)
- memory_draft.py writes drafts to `.staging/` only
- memory_write.py reads from `.staging/` only

**Verdict:** Correct design. The /tmp/ allowance in memory_draft.py is a wider input funnel that narrows at the draft output stage. No fix needed.

**Self-critique:** On re-examination, this is NOT an issue at all -- it's correct architecture. Downgrading from medium to OBSERVATION.

### FINDING-2: Draft filename collision window [LOW]

**Issue:** `memory_draft.py:write_draft()` (line 224-227) generates filenames as `draft-{category}-{timestamp}-{pid}.json` where timestamp is to the second. If two subagents running in the same process (same PID) for different categories trigger within the same second, the PID+timestamp combination prevents collision since the category is also in the filename. However, if somehow the SAME category were drafted twice in the same second with the same PID, there would be a silent overwrite.

**Pipeline impact:** Practically zero. Phase 1 spawns one subagent per category, so same-category collisions within one second + one PID is essentially impossible.

**Verdict:** Acceptable. No fix needed.

### FINDING-3: memory_draft.py does NOT run auto_fix or title sanitization [MEDIUM]

**Issue:** `memory_draft.py` calls `slugify()` for the ID and uses `now_utc()` for timestamps, but it does NOT call `auto_fix()` from memory_write.py. This means:
- No title sanitization (control chars, index-injection markers like ` -> ` and `#tags:`)
- No tag deduplication/sanitization
- No confidence clamping
- No whitespace stripping

This is partially mitigated because `memory_write.py` runs `auto_fix()` in Phase 3 before final save. However, there is a gap:
- **Phase 2 verification** reads the draft JSON as-is. If the draft contains unsanitized titles or tags, the verifier sees (and passes) content that will be modified by auto_fix in Phase 3.
- The Pydantic validation in memory_draft.py (line 307-315) will catch schema violations (wrong types, missing fields), but NOT semantic issues like index-injection markers in titles.

**Pipeline impact:** Low practical risk. The title sanitization in memory_write.py's auto_fix will clean it up in Phase 3. The Phase 2 verifier might see slightly different text than what gets saved, but this is a cosmetic difference, not a correctness issue.

**Recommendation:** Consider adding title sanitization to memory_draft.py's assembly functions. This is a defense-in-depth improvement, not a blocking issue.

**Self-critique:** The spec explicitly says "Do NOT duplicate merge protections -- that's memory_write.py's job" (spec line 82). Title sanitization is in auto_fix, which is technically part of the enforcement layer. This finding is valid but the decision to NOT sanitize in memory_draft.py is a deliberate spec choice. The Phase 2 verifier gap is real but the impact is negligible since sanitization changes are minor (stripping control chars from titles is not going to change semantic meaning).

### FINDING-4: Backward compatibility of --new-info vs --new-info-file [OK]

**Issue:** `memory_candidate.py` (lines 221-233) handles the new `--new-info-file` alongside existing `--new-info`:
- `--new-info-file` takes precedence when both provided
- At least one is required (error if neither)
- File reading has proper error handling (FileNotFoundError, PermissionError, OSError)

**Pipeline impact:** Full backward compatibility. Old callers using `--new-info "inline text"` still work. New flow uses `--new-info-file`. No breaking change.

**Verdict:** Correct implementation.

### FINDING-5: Phase 3 draft->save pipeline compatibility [OK]

**Issue:** Phase 3 calls `memory_write.py --action create --input <draft_path>`. The draft_path from memory_draft.py is in `.claude/memory/.staging/draft-<cat>-<timestamp>-<pid>.json`. memory_write.py's `_read_input()` validates that the resolved path contains `/.claude/memory/.staging/`.

**Verification:**
- Draft path: `.claude/memory/.staging/draft-decision-20260221T120000Z-12345.json`
- Resolved path will contain `/.claude/memory/.staging/` -- PASS
- No `..` components -- PASS
- memory_write.py reads the complete JSON, runs auto_fix, validates with Pydantic -- PASS
- memory_write.py cleans up the draft file after save (_cleanup_input) -- PASS

**Pipeline impact:** Fully compatible.

### FINDING-6: .staging/ directory creation [OK]

**Edge case (a):** What if `.staging/` doesn't exist?

- `memory_draft.py:write_draft()` (line 221): calls `os.makedirs(staging_dir, exist_ok=True)` -- handles missing directory
- `memory_triage.py:write_context_files()` (line 707): calls `os.makedirs(staging_dir, exist_ok=True)` -- handles missing directory
- SKILL.md step 2 uses Write tool to create files in `.staging/` -- Claude Code's Write tool creates parent directories

**Verdict:** All paths handle missing `.staging/` directory correctly.

### FINDING-7: Concurrent drafts for same category [LOW RISK]

**Edge case (b):** What if two sessions trigger triage for the same category simultaneously?

- Each draft gets a unique filename (timestamp + PID)
- Each session's Phase 3 save would attempt to write to the same target file
- memory_write.py uses `_flock_index` for atomicity, and OCC (`--hash`) for update conflict detection

**Pipeline impact:** The flock + OCC mechanism prevents corruption. One session would succeed, the other would get `OCC_CONFLICT` and need to retry. This is the correct behavior.

**Verdict:** Handled by existing concurrency controls.

### FINDING-8: Very large input files [OK]

**Edge case (c):** What about very large input files?

- Context files are capped at 50KB by memory_triage.py (MAX_CONTEXT_FILE_BYTES)
- The partial JSON input file should be small (title + tags + content fields)
- memory_draft.py reads the entire file into memory, which is fine for expected sizes
- No explicit size limit on input files, but the Pydantic validation will reject oversized content (title max_length=120, change_summary max_length=300)

**Verdict:** Adequate for expected usage. The 50KB context file cap upstream prevents excessive data propagation.

### FINDING-9: Empty content fields [OK]

**Edge case (d):** What happens with empty content fields?

- `memory_draft.py:check_required_fields()` checks presence of `title`, `tags`, `content`, `change_summary` in the input
- An empty `content: {}` would pass the presence check but fail Pydantic validation (category-specific models require fields like `goal` for session_summary)
- An empty `title: ""` would pass the presence check but `slugify("")` returns `""`, which fails the ID pattern regex validation
- An empty `tags: []` would pass presence check but fail Pydantic `min_length=1` on tags

**Pipeline impact:** All empty content edge cases are caught by Pydantic validation at line 307-315. Error messages are clear.

**Verdict:** Correct behavior.

### FINDING-10: SKILL.md instruction clarity for haiku subagents [OK WITH NOTES]

The SKILL.md Phase 1 instructions (steps 1-10) are clear and sequential. Key improvements over the previous flow:

**Strengths:**
- Step 6 explicitly lists which fields to include and which NOT to include
- The MANDATE about using Write tool (not Bash) is prominent
- The memory_draft.py command examples include `${CLAUDE_PLUGIN_ROOT}` correctly
- Step 4 parsing instructions are clear about vetoes being absolute

**Potential ambiguity:**
- Step 6 says "Path: `.claude/memory/.staging/input-<category>.json`" -- this does not include a PID or timestamp for uniqueness, unlike the spec which says `input-<category>-<pid>.json`. The simpler path is fine because each category subagent writes to a distinct category path, so there's no collision risk within a single triage cycle. However, between triage cycles, old input files could linger. This is not a real problem because:
  1. memory_draft.py reads and processes the file
  2. The draft file gets a unique timestamp+PID name
  3. The input file is an intermediate artifact

**Self-critique:** The missing PID in the SKILL.md input filename is intentional simplification -- haiku models should have fewer opportunities to hallucinate complex filenames. The spec's `input-<category>-<pid>.json` was a suggestion, and the implementation chose `input-<category>.json` for simplicity. This is a valid trade-off.

### FINDING-11: Config interactions [OK]

The new flow respects memory-config.json settings:
- `triage.parallel.category_models` -- used by SKILL.md Phase 0/1 to select subagent models
- `triage.parallel.enabled` -- respected by the fallback-to-sequential clause
- Category-specific settings (enabled, auto_capture) -- not changed by this PR

memory_draft.py does NOT read memory-config.json directly (it has no config dependency). All config-sensitive decisions happen upstream in the triage hook and SKILL.md instructions.

**Verdict:** Clean config separation.

### FINDING-12: Phase 2 verification can still read draft JSON [OK]

Phase 2 verifiers receive the `draft_path` from Phase 1 output. The draft at that path is a COMPLETE, schema-valid JSON file (assembled by memory_draft.py). This is a strict improvement over the old flow where the LLM manually constructed full JSON:

- Draft JSON has all required fields populated
- Pydantic validation has already passed
- Verifiers can assess content quality without worrying about schema issues

**Verdict:** Better than before.

### FINDING-13: $CLAUDE_PLUGIN_ROOT usage in SKILL.md [OK]

All three script invocations in SKILL.md use `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/..."`:
- memory_candidate.py (step 3)
- memory_draft.py (step 7)
- memory_write.py (Phase 3)

This is consistent with the plugin's design where `$CLAUDE_PLUGIN_ROOT` is set by Claude Code.

### FINDING-14: memory_draft.py import chain safety [OK]

`memory_draft.py` imports from `memory_write.py`:
```python
from memory_write import slugify, now_utc, build_memory_model, CONTENT_MODELS, CATEGORY_FOLDERS, ChangeEntry, ValidationError
```

**Concern:** Does importing memory_write.py trigger any side effects?

Analysis of memory_write.py's module-level code:
- Lines 25-35: venv bootstrap -- only fires when pydantic is missing AND running under wrong Python. Since memory_draft.py already did its own venv bootstrap (lines 22-30), pydantic should be available, so memory_write.py's import won't trigger os.execv.
- Lines 47-51: pydantic import -- already available from bootstrap
- Lines 58-78: Constants (CATEGORY_FOLDERS, CATEGORY_DISPLAY, etc.) -- safe
- Lines 85-166: Pydantic model definitions -- safe
- Lines 186-222: _model_cache and build_memory_model -- safe (lazy)
- No module-level I/O, no argparse at module level

**Verdict:** Import is safe. No side effects.

---

## Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | /tmp/ path allowance in memory_draft.py | OBSERVATION | Correct design |
| 2 | Draft filename collision window | LOW | Acceptable |
| 3 | No auto_fix/title sanitization in memory_draft.py | MEDIUM | By design per spec; memory_write.py covers it in Phase 3 |
| 4 | --new-info backward compat | OK | Fully compatible |
| 5 | Draft->save pipeline | OK | Fully compatible |
| 6 | .staging/ dir creation | OK | Handled |
| 7 | Concurrent drafts | LOW | Handled by OCC |
| 8 | Large input files | OK | Bounded upstream |
| 9 | Empty content fields | OK | Caught by Pydantic |
| 10 | SKILL.md clarity | OK | Clear for haiku |
| 11 | Config interactions | OK | Clean separation |
| 12 | Phase 2 verification | OK | Improved |
| 13 | $CLAUDE_PLUGIN_ROOT | OK | Consistent |
| 14 | Import chain safety | OK | No side effects |

**Overall Assessment:** PASS with advisory notes.

The only real consideration is FINDING-3 (no title sanitization in draft assembly), which is a deliberate design choice per the spec. Phase 2 verifiers will see pre-sanitized content, but the sanitization changes are minor enough that this doesn't affect verification quality. The defense-in-depth argument for adding sanitization to memory_draft.py is valid but not blocking.

All critical integration points (pipeline compatibility, backward compat, edge case handling, config interactions, Phase 2 readability, Phase 3 save flow) are correct.
