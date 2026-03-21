---
status: done
progress: "All 6 phases complete. Phase 6 produced 2 action plans in guardian repo."
---

# Fix Approval Popups — Action Plan

Addresses excessive approval popups (~22 false positives over 6 days) and 118 quarantined `.invalid` files in the ops project when using the claude-memory plugin.

## Root Causes

| ID | Root Cause | Impact |
|----|-----------|--------|
| RC-1 | `memory_write_guard.py` exits silently for staging paths (no `permissionDecision: "allow"`) — Claude Code shows popup | ~5 popups/session |
| RC-2 | `memory_validate_hook.py` nlink check fails on WSL2 9p filesystem → quarantines valid staging files | 118 `.invalid` files |
| RC-3 | Guardian `ask` patterns match heredoc body content (`.env`, `.pem` substrings) | ~3 popups/session |
| RC-4 | Neither write_guard nor Guardian emits explicit `allow` for staging → Claude Code defaults to popup | Compounds RC-1 |
| RC-5 | SKILL.md commands use `find -delete` → Guardian BLOCK pattern match | 1-2 popups/session |
| RC-6 | PostToolUse validate_hook quarantines staging files (nlink check failure) → cascading errors | Compounds RC-2 |
| RC-7 | `memory_staging_guard.py` missing `ln`/`link` in blocked commands regex | Minor security gap |

## Phases

### Phase 1: Fix Write Tool Popups (3 file changes) [v]
- [v] **Step 1.1**: `memory_write_guard.py` — emit `permissionDecision: "allow"` for staging files with 4-gate safety model (extension whitelist → filename regex → nlink defense → new file passthrough)
- [v] **Step 1.2**: `memory_validate_hook.py` — change nlink from gate to warning-only for staging; OSError fails open (skip) instead of closed (quarantine)
- [v] **Step 1.3**: `memory_staging_guard.py` — add `ln`/`link` to blocked commands regex with `\b` word boundary
- [v] **Step 1.4**: Add tests for all changes (TestStagingAutoApprove, TestHardlinkBlocking)
- [v] Verification: 2 independent rounds (structural + adversarial) with cross-model (Codex 5.3 + Gemini 3.1 Pro)

### Phase 2: Address Guardian Bash Popups (SKILL.md update) [v]
- [v] **Step 2.1**: Replace `find -delete` with Python glob+os.remove in SKILL.md Phase 0
- [v] **Step 2.2**: Replace `--result-json` inline JSON with `--result-file` approach (Write tool for JSON → Bash for script invocation)
- [v] **Step 2.3**: Expand SKILL.md Rule 0 to document all Guardian-incompatible patterns
- [v] **Step 2.4**: Add `--result-file` argument to `memory_write.py` (backwards compatible)
- [v] Verification: 2 independent rounds — R2 found critical `rm .claude/...` issue → fixed with Python glob

### Phase 3: Add Logging to Guards [v]
- [v] **Step 3.1**: Add lazy JSONL logging to `memory_write_guard.py` (guard.write_allow_staging, guard.write_deny)
- [v] **Step 3.2**: Add lazy JSONL logging to `memory_staging_guard.py` (guard.staging_deny)
- [v] **Step 3.3**: Add lazy JSONL logging to `memory_validate_hook.py` (validate.staging_skip, validate.bypass_detected, validate.quarantine)
- [v] Verification: 2 independent rounds (structural + adversarial)

### Phase 4: Add Tests (P0 regression prevention) [v]
- [v] **Step 4.1**: `TestNoAskVerdict` — AST + regex + value whitelist scan for "ask" permissionDecision (9 tests)
- [v] **Step 4.2**: `TestSkillMdGuardianConflicts` — SKILL.md bash commands vs 4 block + 4 ask Guardian patterns (9 tests)
- [v] **Step 4.3**: `TestSkillMdRule0Compliance` — heredoc, find-delete, rm, inline JSON, python3-c checks (5 tests)
- [v] **Step 4.4**: `TestGuardScriptsExist` + `TestGuardianPatternSync` — sanity + optional sync check (6 tests)
- [v] Verification: 2 independent rounds (R1 structural PASS WITH CONCERNS, R2 adversarial PASS WITH CONCERNS)

### Phase 5: One-Time Cleanup (ops project) [v]
- [v] **Step 5.1**: Removed 118 `.invalid` files from ops staging (215 KB recovered)
- [v] **Step 5.2**: Removed nested `.staging/.claude/` directory (44 KB, 7 stale files)
- [v] **Step 5.3**: Retired stale `memory-staging-writes-and-team-communication-patterns` preference (contradicts Phase 1-2 fixes: recommended heredoc for staging writes, now harmful)
- [v] **Step 5.4**: Removed 7 stale staging files from incomplete save operations (Mar 2-17)
- [v] **Step 5.5**: Rebuilt ops memory index (58 entries)

### Phase 6: Guardian Repo Tech Debt [v]
- [v] **Step 6.1**: Documented regex fixes for heredoc body scanning → `claude-code-guardian/action-plans/heredoc-pattern-false-positives.md` (700+ lines, cross-model validated, 2-round verified with 3 BLOCKING fixes incorporated: allowlist trimmed, pipe-awareness added, backslash delimiter parsing)
- [v] **Step 6.2**: Proposed interpreter payload check refinement → `claude-code-guardian/action-plans/interpreter-path-resolution.md` (400+ lines, F1-contained path extraction from string literals, cross-model validated, 2-round verified)

## Changes Applied (Phases 1-3)

9 files changed, 1046 tests pass.

| File | Changes |
|------|---------|
| hooks/scripts/memory_write_guard.py | Staging auto-approve with 4-gate safety + logging |
| hooks/scripts/memory_validate_hook.py | Nlink warning-only for staging + fail-open OSError + logging |
| hooks/scripts/memory_staging_guard.py | `ln`/`link` blocking + logging |
| hooks/scripts/memory_write.py | `--result-file` argument |
| skills/memory-management/SKILL.md | Python glob cleanup, --result-file, expanded Rule 0 |
| tests/test_memory_write_guard.py | TestStagingAutoApprove (10 tests) |
| tests/test_memory_staging_guard.py | TestHardlinkBlocking (5 tests) + unlink test |
| tests/test_memory_validate_hook.py | Updated nlink/parity tests |
| tests/test_regression_popups.py | P0 regression: no-ask verdict, Guardian patterns, Rule 0 (29 tests) |
