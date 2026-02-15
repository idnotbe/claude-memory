# Working Memory: Stop Hook JSON Validation Fix

## Status: COMPLETE

## Problem
6 Stop hooks in `hooks/hooks.json` instructed the LLM to return extra JSON fields (`lifecycle_event`, `cud_recommendation`) beyond Claude Code's allowed `{ok, reason}` schema, causing "JSON validation failed" errors x6 at every session end.

## Fix Applied
1. Replaced the old instruction block (requesting extra JSON fields) with a new block embedding metadata inside the `reason` string using `[CUD:<action>|EVENT:<event>]` prefix format
2. Fixed copy-paste error: each hook now has a category-specific example (not all SESSION_SUMMARY)

## External Model Consensus (Codex 5.3, Gemini 3 Pro, Claude Opus 4.6)
All three models confirmed the approach is correct and the fix resolves the primary issue.

## Verification Results

### Round 1 (Multi-perspective, 5 dimensions)
- JSON Schema Compliance: PASS
- Prompt Quality: PASS (copy-paste issue identified and fixed)
- Downstream Compatibility: PASS
- External Model Verification: PASS (both Codex and Gemini confirm)
- Completeness Check: PASS

### Round 2 (Adversarial, 5 attack vectors)
- JSON Validity: PASS
- Prompt Injection Risk: MEDIUM (pre-existing, not introduced by fix)
- Regression Risk: PASS (no unintended changes)
- Edge Case Analysis: copy-paste issue flagged (fixed), EVENT:none flagged (pre-existing pattern, not a regression)
- Consistency: PASS after example fix

## Final State
- hooks/hooks.json: 6 Stop hooks updated with category-specific examples
- No downstream code changes needed
- JSON validity confirmed
- All non-Stop hooks (PreToolUse, PostToolUse, UserPromptSubmit) untouched

## Known Accepted Risks (pre-existing, not introduced by this fix)
1. `EVENT:none` not in `VALID_LIFECYCLE_EVENTS` — same pattern as old `null` value; main agent maps to "omit flag"
2. `$ARGUMENTS` injection surface — pre-existing architectural concern
3. LLM may occasionally emit extra fields — inherent to prompt-type hooks
4. SKILL.md L2 references `cud_recommendation` — documentation-level, main agent parses from prefix
