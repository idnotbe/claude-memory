# Phase 4 Implementation Results: Regression Prevention Tests

## Test File
`tests/test_regression_popups.py` -- 27 tests, all passing

## Test Classes & Coverage

### TestNoAskVerdict (9 tests)
Scans all 3 guard scripts (`memory_write_guard.py`, `memory_staging_guard.py`, `memory_validate_hook.py`):
- **test_no_ask_in_source** (x3): AST-based detection of `permissionDecision` values; verifies none are "ask". Now also flags non-constant (dynamic) values as DYNAMIC to catch evasion via variables, f-strings, or concatenation.
- **test_only_allow_or_deny** (x3): Verifies all `permissionDecision` values are exactly "allow" or "deny". Catches any unexpected value including DYNAMIC.
- **test_no_ask_in_raw_text** (x3): Regex fallback scan for "ask" near "permissionDecision". Uses both single-line and DOTALL multi-line matching to catch split-line constructs.

### TestSkillMdGuardianConflicts (8 tests)
Extracts bash code blocks from SKILL.md and tests against Guardian patterns:
- **test_no_block_pattern_matches** (x4): Tests 4 block patterns -- claude deletion, find -delete, interpreter deletion (os.remove etc.), pathlib.Path().unlink
- **test_no_ask_pattern_matches** (x4): Tests 4 ask patterns -- rm -rf, find -exec rm, mv .claude, xargs rm/del/shred
- **test_python3_c_multiline_does_not_match_block** (x1): Verifies the Phase 0 cleanup command does NOT match the block regex (multiline stops it). Documents the known F1 safety net ask as a comment.

### TestSkillMdRule0Compliance (5 tests)
Verifies SKILL.md bash commands follow its own Rule 0:
- **test_no_heredoc_with_claude_path**: No `<<` + `.claude` in same block
- **test_no_find_delete_with_claude_path**: No `find -delete` + `.claude`
- **test_no_rm_with_claude_path**: No `rm` + `.claude`
- **test_no_inline_json_with_claude_path**: No JSON object literals with `.claude` paths on command line (distinguishes from shell variable references and plain CLI args)
- **test_python3_c_with_claude_path_warning**: Caps known `python3 -c` + `.claude` instances at 1 (Phase 0 cleanup). Emits warning, not failure. Fails hard if new instances appear.

### TestGuardScriptsExist (4 tests)
Sanity check that all referenced files exist.

## Full Suite Results
- **1044 tests passed, 0 failed, 1 warning**
- Warning is expected: documents the known Phase 0 cleanup trade-off
- No regressions in existing 1017 tests

## Cross-Model Improvements Applied
Based on Gemini 3 Pro and Gemini 2.5 Pro review:
1. Added pathlib.Path().unlink block pattern (was missing from original set)
2. AST detection now flags DYNAMIC (non-constant) permissionDecision values
3. Raw text fallback uses DOTALL for multi-line matching
4. Bash block extraction expanded to include console/terminal/zsh hints
