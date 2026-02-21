# SKILL.md Phase 1 Update -- Working Notes

## What Changes
- Phase 1 subagent instructions (lines ~79-102 in SKILL.md)
- Steps 2-6 need rewriting; step 1 stays the same

## Key Decisions
- Step 2: Write new-info to `.claude/memory/.staging/new-info-<category>.txt` via Write tool
- Step 3: Use `--new-info-file` instead of inline `--new-info`
- Step 4: Parse JSON (same as before)
- Step 5 (NEW): Write partial JSON input file via Write tool
- Step 6 (NEW): Run memory_draft.py to assemble complete JSON
- Step 7: Parse memory_draft.py output for draft_path
- Step 8: Report action, draft_path, justification

## Mandate
- All file writes to .staging/ MUST use Write tool (not Bash cat/heredoc/echo)
- This avoids Guardian bash scanning false positives

## DELETE flow: unchanged (small JSON, no Guardian concern)

## Status: implementing edit
