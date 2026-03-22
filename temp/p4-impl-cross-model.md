# Phase 4 Cross-Model Review: Regression Prevention Tests

## Models Consulted
- **Gemini 3 Pro Preview** (thinking: high, temp: 0.2)
- **Gemini 2.5 Pro** (thinking: high, temp: 0.2)
- Codex 5.3 was unavailable (environment error)

## Convergent Findings (both models agreed)

### 1. Missing pathlib block pattern
Both models identified that `pathlib.Path(...).unlink()` was absent from the embedded Guardian patterns despite being present in guardian.default.json.
- **Action taken**: Added as `GUARDIAN_BLOCK_PATTERNS[3]` with parametrized test case.

### 2. AST evasion via dynamic values
Both models pointed out that `_find_string_literals_with_permission()` only catches `ast.Constant` values, missing variables (`ast.Name`), f-strings (`ast.JoinedStr`), and concatenation (`ast.BinOp`).
- **Action taken**: Now flags non-constant values as `"DYNAMIC"` so `test_only_allow_or_deny` catches them.

### 3. Multi-line raw text evasion
Both models noted the single-line regex fallback misses split-line constructs like `{"permissionDecision":\n    "ask"}`.
- **Action taken**: Added DOTALL-based multi-line matching as a second check.

### 4. Bash block extraction too narrow
Both models suggested expanding language hints beyond bash/sh/shell.
- **Action taken**: Added console, terminal, zsh to the hint list.

## Divergent / Declined Suggestions

### `rm -r -f` separated flags (Gemini 3 Pro only)
Suggested the ask pattern `rm\s+-[rRf]+` misses `rm -r -f` (separated flags).
- **Decision: Not applied.** The actual Guardian pattern has the same limitation. Since we're testing against Guardian's real behavior, matching its exact regex is correct. A "fixed" test pattern would produce false positives (our regex catches violations Guardian wouldn't).

### Broader inline JSON regex (both models)
Both suggested simplifying inline JSON detection to `\{.*\.claude.*\}` or `'.*\{.*\.claude.*\}.*'`.
- **Decision: Not applied.** Broader patterns increase false positive risk. The current regex specifically targets JSON object literals (quoted strings with braces containing .claude) and already correctly handles the cleanup-staging command by stripping shell variable references first.

### Content fingerprinting for python3 -c (Gemini 2.5 Pro)
Suggested matching specific content strings instead of counting instances.
- **Decision: Not applied.** Content fingerprinting couples the test to exact command text, breaking on minor edits. The count-based approach is intentionally fragile to force review when new instances appear, which is the desired behavior.

### Root deletion pattern `rm -rf /` (Gemini 3 Pro)
Suggested adding root deletion block pattern.
- **Decision: Not applied.** No SKILL.md command approaches `rm -rf /`. This pattern protects against catastrophic system damage, not popup regressions. Adding it would be scope creep without adding popup-prevention value.

### Nested JSON false negatives (Gemini 2.5 Pro)
Noted `[^}]*` in inline JSON regex stops at first `}` in nested JSON like `{"a": {}, "path": ".claude/x"}`.
- **Decision: Acknowledged but not critical.** SKILL.md bash commands don't use nested JSON objects on the command line. The regex is scoped to catch the specific violation pattern (inline JSON with .claude paths), not arbitrary JSON parsing. If a nested case appears in practice, the test can be refined.

## Summary
4 improvements were applied based on cross-model consensus. 5 suggestions were evaluated and declined with documented rationale. The test suite is stronger for the review while remaining practical and maintainable.
