# P1+P2 Implementation Notes

## Analysis

### P1: Replace python3 -c with cleanup-intents action

**Current state**: SKILL.md Phase 0 Step 0 uses inline `python3 -c "import glob,os..."` to delete stale `intent-*.json` files. This triggers Guardian's `check_interpreter_payload()` which detects `os.remove` and may trigger an F1 safety net "ask" popup.

**Plan**:
1. Add `cleanup-intents` action to `memory_write.py` (similar to `cleanup_staging`)
2. Update SKILL.md Phase 0 Step 0 to call the new action
3. Update SKILL.md Rule 0 to explicitly forbid `python3 -c` for all file operations

**Security considerations**:
- Path containment: validate each intent file resolves within staging_dir (same pattern as cleanup_staging)
- Only delete files matching `intent-*.json` pattern
- Check resolved paths before deletion (no symlink following)

### P2: Prevent Haiku Heredoc

**Current state**: Phase 3 save subagent (haiku) may use heredoc to write JSON files, triggering Guardian patterns.

**Plan**:
1. Strengthen SKILL.md Phase 3 prompt with explicit heredoc warning
2. Add `write-save-result-direct` action that builds result JSON internally
3. Update SKILL.md Phase 3 to use the new direct action

**Security considerations**:
- Validate --categories and --titles inputs (length caps, item counts)
- Reuse existing write_save_result validation
- Same staging path containment as write-save-result

## Implementation Log

All steps completed:

- Step 1.1: Added `cleanup_intents()` function and `cleanup-intents` action to memory_write.py
- Step 1.2: Updated SKILL.md Phase 0 Step 0 to use `--action cleanup-intents`
- Step 1.3: Updated SKILL.md Rule 0: "Do NOT use `python3 -c` for any file operations"
- Step 2.1: Added CRITICAL heredoc warning to SKILL.md Phase 3 save subagent prompt
- Step 2.2: Added `write-save-result-direct` action to memory_write.py
- Step 2.3: Replaced Write+Bash two-step with single `write-save-result-direct` command in Phase 3

## Post-review fixes (from Gemini clink review)

- Fixed symlink loop DoS: moved `is_symlink()` check before `resolve()` call and added `RuntimeError` to the exception catch in `cleanup_intents()`
- Documented comma-in-titles limitation with comment in `write-save-result-direct` handler
- Updated `test_regression_popups.py`: changed `test_python3_c_with_claude_path_warning` from warning-about-1-known to hard assertion of zero instances

## Test results

- 107 passed, 2 skipped (Guardian sync tests need sibling repo)
- No regressions
