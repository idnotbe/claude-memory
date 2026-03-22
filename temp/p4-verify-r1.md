# Phase 4 Verification -- Round 1 (Structural Correctness & Coverage)

**Verifier:** Claude Opus 4.6 (1M context)
**Date:** 2026-03-21
**Cross-model:** Gemini 3 Pro Preview (high thinking)
**Verdict:** PASS WITH CONCERNS

## Test Execution

All 27 tests pass, 1 expected warning (python3 -c sentinel):
```
27 passed, 1 warning in 0.04s
```

## A. Coverage Completeness

### A1. TestNoAskVerdict detection effectiveness: PASS
- Verified the AST detection correctly identifies `{"permissionDecision": "ask"}` in dict literals.
- Verified dynamic values (variable references) are flagged as "DYNAMIC".
- Regex fallback (DOTALL, 200-char window) catches multi-line constructs and split-line assignments like `key = "permissionDecision"; d[key] = "ask"`.
- **Limitation noted:** AST walker only handles `ast.Dict` nodes. It will miss `d["permissionDecision"] = "ask"` (subscript assignment) and `dict(permissionDecision="ask")` (call). However, the regex fallback covers these cases adequately since "permissionDecision" and "ask" would appear within 200 chars. Risk: LOW (guard scripts are developer-authored, not LLM-generated).

### A2. TestSkillMdGuardianConflicts coverage: PASS
- Covers all 4 relevant block patterns (claude deletion, find -delete, interpreter deletion, pathlib unlink).
- Covers all 4 relevant ask patterns (rm -rf, find -exec, mv .claude, xargs delete).
- Verified all 14 untested block patterns and 14 untested ask patterns against SKILL.md -- NONE match. The subset selection is correct.
- Includes the important `test_python3_c_multiline_does_not_match_block` edge case test.

### A3. TestSkillMdRule0Compliance: PASS
- Covers all 5 testable Rule 0 conditions from SKILL.md line 433:
  1. No heredoc + .claude path -- covered
  2. No python3 -c + .claude paths -- covered (as warning sentinel)
  3. No find -delete + .claude paths -- covered
  4. No rm + .claude paths -- covered
  5. No inline JSON + .claude paths -- covered
- 6th condition ("staging via Write tool") is a prose instruction, not statically testable.

### A4. Edge cases: PASS with minor gap
- The `test_python3_c_with_claude_path_warning` sentinel pattern (max_known=1) is well-designed but counts instances rather than verifying content. A substitution (removing the known Phase 0 command, adding a different dangerous one) would keep count=1 and pass. See Concern C2 below.

## B. Pattern Accuracy

### B1. Block patterns: CORRECT
Exact character-by-character comparison of embedded patterns vs `/home/idnotbe/projects/claude-code-guardian/assets/guardian.default.json`:
- `GUARDIAN_BLOCK_PATTERNS[0]` = Guardian block[2] (claude deletion): EXACT MATCH
- `GUARDIAN_BLOCK_PATTERNS[1]` = Guardian block[7] (find -delete): EXACT MATCH
- `GUARDIAN_BLOCK_PATTERNS[2]` = Guardian block[14] (interpreter deletion): EXACT MATCH
- `GUARDIAN_BLOCK_PATTERNS[3]` = Guardian block[15] (pathlib unlink): EXACT MATCH

### B2. Ask patterns: MOSTLY CORRECT
- `GUARDIAN_ASK_PATTERNS[0]` = Guardian ask[0] (rm -rf): EXACT MATCH
- `GUARDIAN_ASK_PATTERNS[1]` = Guardian ask[16] (find -exec): EXACT MATCH
- `GUARDIAN_ASK_PATTERNS[2]` vs Guardian ask[10] (mv protected): NARROWED
  - Test: `mv\s+['\"]?(?:\./)?\.claude`
  - Guardian: `mv\s+['"]?(?:\./)?\.(env|git|claude)`
  - Test only matches `.claude`, Guardian also matches `.env` and `.git`.
  - **Assessment:** Intentional narrowing (SKILL.md only deals with .claude paths). Acceptable but see Concern C1.
- `GUARDIAN_ASK_PATTERNS[3]` = Guardian ask[17] (xargs delete): EXACT MATCH

### B3. Regex flags: CORRECT
- Block patterns use `re.MULTILINE` where Guardian uses `(?i)` prefix for case-insensitive matching. The embedded patterns preserve the inline `(?i)` flag from Guardian. Correct.
- Ask patterns don't use `re.IGNORECASE`, matching Guardian's behavior (Guardian ask patterns don't use `(?i)` except for OS-specific ones not included here).

## C. SKILL.md Command Extraction

### C1. Bash block count: CORRECT
- SKILL.md has 24 code fences (12 paired blocks).
- 6 blocks are labeled `bash` -- the extractor finds all 6.
- 6 blocks are non-bash: 2 JSON, 2 unlabeled (Task() prompt at line 267, Write() call at line 314), 1 unlabeled (JSON schema at line 360), 1 unlabeled (Agent() call at line 79).
- The unlabeled blocks correctly omitted because:
  - Task() prompts are not Bash tool inputs (Guardian doesn't scan Task tool)
  - Write() calls are not Bash tool inputs
  - JSON schemas are data, not commands
  - Agent() calls are not Bash tool inputs

### C2. Extraction logic correctness: CORRECT
- Handles multi-line blocks properly (joins with `\n`).
- Records line numbers for diagnostic output.
- Language hint matching is case-insensitive (`stripped.lower()`).
- Includes console/terminal/zsh in addition to bash/sh/shell.

### C3. Commands inside Task() prompt: VERIFIED SAFE
- The Task() prompt at lines 267-302 contains `python3 ... memory_write.py --action cleanup-staging` and `python3 ... --action write-save-result` commands.
- Tested both against all 36 Guardian patterns: NO MATCHES.
- These are safe commands (no rm, no find -delete, no os.remove).

## D. Test Quality

### D1. Assertions: GOOD
- All assertion messages include script name, line numbers, matched patterns, and failing command text.
- The parametrized tests produce clear test IDs (e.g., `block:claude_deletion`, `ask:mv_claude`).

### D2. Docstrings: ACCURATE
- All test docstrings correctly describe what the test verifies.
- The `test_python3_c_multiline_does_not_match_block` docstring includes an excellent NOTE about the F1 safety net limitation.

### D3. False-pass risk: LOW
- No test matches "nothing when it should match something" -- verified by checking that bash blocks ARE found (assert len(blocks) > 0) and guard scripts DO contain permissionDecision values (assert len(literals) > 0).
- Inline code spans (backtick-delimited) in SKILL.md prose were checked -- none match Guardian patterns. Not a gap.

### D4. False-fail risk: NONE DETECTED
- The inline JSON regex is carefully constructed to skip `--result-file` lines, comment lines, and shell variable references.
- The heredoc regex requires `<<\s*['\"]?\w+` (actual heredoc syntax), not just `<<` in any context.

## E. Concerns

### C1: mv pattern narrowing (MINOR)
The test's mv pattern only matches `.claude` while Guardian matches `.env`, `.git`, and `.claude`. If SKILL.md ever adds an `mv .env` or `mv .git` command, this test would not catch it. Risk: LOW (SKILL.md is a memory plugin, unlikely to mv .env/.git). Recommendation: consider using the full Guardian pattern for completeness.

### C2: Sentinel counts instances, not content (MINOR)
`test_python3_c_with_claude_path_warning` caps at `max_known=1` but doesn't verify the content of the known instance. If someone replaces the Phase 0 cleanup command with a different dangerous `python3 -c` command, the count stays 1 and the test passes. Recommendation: optionally assert on a content fingerprint of the known instance (e.g., check for `glob.glob` or `intent-*.json`).

### C3: Static vs runtime gap (INHERENT LIMITATION)
The test validates SKILL.md templates statically. If an LLM resolves variables or modifies template commands at runtime (e.g., expanding `$TARGET_DIR` to `.claude/memory`), Guardian would catch it at runtime but this test would not predict it. This is an inherent limitation of static analysis and does not reduce the test's value -- it catches the 90% case of SKILL.md template regressions.

### C4: Guardian pattern drift (OPERATIONAL)
The test embeds Guardian patterns as constants. If Guardian updates its patterns, the test won't automatically update. This is documented in the test docstring (line 37-38) and is an intentional trade-off for test self-containedness. Recommendation: a periodic manual sync check should be part of the maintenance process.

## F. Cross-Model Review (Gemini 3 Pro Preview)

Gemini 3 Pro concurred on all major findings and additionally flagged:
- Q1 (mv pattern): Recommends using the exact Guardian pattern for zero-complexity improvement.
- Q2 (unlabeled blocks): Suggests expanding extraction to catch unlabeled blocks. Assessed as LOW risk since verified all unlabeled blocks contain non-bash content.
- Q3 (AST robustness): Confirmed the subscript assignment blind spot; agrees regex fallback mitigates it.
- Q4 (sentinel approach): Recommends content-based assertion over pure count. Agrees the ratcheting pattern is sound.
- Q5 (static vs runtime): Acknowledges this as a fundamental limitation; suggests documenting it explicitly.

## Verdict: PASS WITH CONCERNS

The test suite is structurally sound and provides effective regression coverage for the three core invariants. All 27 tests pass. Guardian patterns are correctly embedded (exact match for 7 of 8, intentionally narrowed for 1). SKILL.md bash block extraction is complete and correct. Rule 0 coverage spans all 5 testable conditions.

The concerns (C1-C4) are all MINOR or INHERENT LIMITATIONS. None require fixes before merging. They are improvement opportunities for a future iteration.

**No fixes required for PASS.**
