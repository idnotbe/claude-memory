# Audit: Phase 4 (Regression Tests) — Eliminate-All-Popups Action Plan

**Auditor**: Claude Opus 4.6 (1M context)
**Date**: 2026-03-22
**Scope**: All Phase 4 tests vs. actual test files

---

## 1. User-Specified Step Verification

### Step 4.1: `test_zero_write_tool_calls_for_staging`

**STATUS: EXISTS (name differs)**

The plan names this test `test_zero_write_tool_calls_for_staging`. The actual implementation is in class `TestStagingPathOutsideClaudeDir` with 3 tests:

| Test | File:Line | Status |
|------|-----------|--------|
| `test_no_write_to_old_staging` | `test_regression_popups.py:758` | PASS |
| `test_staging_uses_tmp_prefix` | `test_regression_popups.py:774` | PASS |
| `test_no_write_tool_to_claude_staging` | `test_regression_popups.py:782` | PASS |

These tests verify SKILL.md never references old `.claude/memory/.staging/` paths and that staging uses `/tmp/` prefix. The intent matches Step 4.1 even though the class/method names differ from the plan description.

### Step 4.2: `test_no_python3_c_in_skill`

**STATUS: EXISTS (name differs)**

The actual implementation is in class `TestZeroPython3CInSkill` with 2 tests:

| Test | File:Line | Status |
|------|-----------|--------|
| `test_no_python3_c_in_any_bash_block` | `test_regression_popups.py:614` | PASS |
| `test_no_python3_c_in_non_bash_code_blocks` | `test_regression_popups.py:630` | PASS |

Verifies SKILL.md has zero `python3 -c` commands in both bash and non-bash code blocks.

### Step 4.3: `test_no_heredoc_in_skill`

**STATUS: EXISTS (name differs)**

The actual implementation is in class `TestNoHeredocInSavePrompt` with 3 tests:

| Test | File:Line | Status |
|------|-----------|--------|
| `test_heredoc_warning_present` | `test_regression_popups.py:698` | PASS |
| `test_no_heredoc_in_phase3_bash_commands` | `test_regression_popups.py:711` | PASS |
| `test_uses_write_save_result_direct` | `test_regression_popups.py:739` | PASS |

Verifies Phase 3 save subagent prompt forbids `<<` and uses `write-save-result-direct` action.

### Step 4.4: `test_cleanup_intents_deterministic`

**STATUS: EXISTS (name differs, split across files)**

The actual implementation is in `test_memory_write.py` in two classes:

**TestCleanupIntents** (8 tests, line 1028):

| Test | File:Line | Status |
|------|-----------|--------|
| `test_deletes_intent_files` | `test_memory_write.py:1051` | PASS |
| `test_preserves_non_intent_files` | `test_memory_write.py:1066` | PASS |
| `test_symlink_rejected` | `test_memory_write.py:1082` | PASS |
| `test_path_traversal_rejected` | `test_memory_write.py:1100` | PASS |
| `test_nonexistent_dir_returns_ok` | `test_memory_write.py:1117` | PASS |
| `test_invalid_staging_path_returns_error` | `test_memory_write.py:1124` | PASS |
| `test_empty_staging_dir` | `test_memory_write.py:1132` | PASS |
| `test_tmp_staging_path_accepted` | `test_memory_write.py:1140` | PASS |

**TestCleanupIntentsTmpPath** (4 tests, line 1160 -- V-R2 GAP 4 fill):

| Test | File:Line | Status |
|------|-----------|--------|
| `test_multiple_intents_in_tmp` | `test_memory_write.py:1169` | PASS |
| `test_symlink_rejected_in_tmp_staging` | `test_memory_write.py:1198` | PASS |
| `test_empty_tmp_staging` | `test_memory_write.py:1233` | PASS |
| `test_path_containment_in_tmp` | `test_memory_write.py:1245` | PASS |

---

## 2. Action Plan Step-to-Test Mapping

The action plan (Phase 4 section) describes 4 steps with expected test counts:

| Plan Step | Plan Description | Plan Count | Actual Class | Actual Count | Delta |
|-----------|-----------------|------------|--------------|--------------|-------|
| 4.1 | `TestNoAskVerdict` (AST + regex + value whitelist) | 9 | `TestNoAskVerdict` | 9 (3x3 parametrized) | 0 |
| 4.2 | `TestSkillMdGuardianConflicts` (4 block + 4 ask + 1 multiline) | 9 | `TestSkillMdGuardianConflicts` | 9 (4+4+1) | 0 |
| 4.3 | `TestSkillMdRule0Compliance` (heredoc, find-delete, rm, JSON, python3-c) | 5 | `TestSkillMdRule0Compliance` | 5 | 0 |
| 4.4 | `TestGuardScriptsExist` + `TestGuardianPatternSync` | 6 | `TestGuardScriptsExist` (4) + `TestGuardianPatternSync` (2) | 6 | 0 |

**Subtotal from plan Steps 4.1-4.4**: 29 tests (matches plan's "29 tests" claim for test_regression_popups.py)

---

## 3. Additional Tests Beyond Plan Steps 4.1-4.4

The commit `3f073f2` added tests across 4 files. Beyond the 29 in `test_regression_popups.py`:

| Class | File | Count | Category |
|-------|------|-------|----------|
| `TestZeroPython3CInSkill` | `test_regression_popups.py` | 2 | P4 extras (not in plan steps) |
| `TestNoHeredocInSavePrompt` | `test_regression_popups.py` | 3 | P4 extras (not in plan steps) |
| `TestStagingPathOutsideClaudeDir` | `test_regression_popups.py` | 3 | P4 extras (not in plan steps) |
| `TestCleanupIntents` | `test_memory_write.py` | 8 | P1 fix unit tests |
| `TestWriteSaveResultDirect` | `test_memory_write.py` | 10 | P2 fix unit tests |
| `TestMemoryStagingUtils` (3 classes) | `test_memory_staging_utils.py` | 20 | P3 staging utils |

These 8 additional tests in `test_regression_popups.py` bring it to **37 total** (29 from plan steps + 8 extras = 37), matching the commit message claim.

---

## 4. "37 Regression Tests" Claim Verification

The commit `3f073f2` message says "add 37 regression tests for popup elimination (Phase 4)".

**`test_regression_popups.py` collected: 37 tests** -- CONFIRMED via `pytest --co`.

Breakdown by class:
- `TestNoAskVerdict`: 9 (3 methods x 3 parametrized scripts)
- `TestSkillMdGuardianConflicts`: 9 (4 block + 4 ask + 1 multiline)
- `TestSkillMdRule0Compliance`: 5
- `TestGuardScriptsExist`: 4 (3 parametrized + 1)
- `TestGuardianPatternSync`: 2
- `TestZeroPython3CInSkill`: 2
- `TestNoHeredocInSavePrompt`: 3
- `TestStagingPathOutsideClaudeDir`: 3
- **Total: 37** -- MATCHES claim

Note: The commit also added tests in other files (16 in test_memory_write.py, 20 in test_memory_staging_utils.py), but the "37 regression tests" claim refers specifically to tests in `test_regression_popups.py`.

---

## 5. "1164 Tests Pass" Claim Verification

The plan says "1046 tests pass" (after Phase 1-3), and the progress note should reference Phase 4 additions.

**Current test count: 1198 tests collected** (via `pytest tests/ --co -q`).

The commit `b174c26` (V-R2 gap fill) message says "All 1198 tests pass", which matches the current count. The growth path:
- Phase 1-3: 1046 tests
- Phase 4 commit (`3f073f2`): added tests across 4 files (+1513 insertion lines)
- V-R2 gap fill (`b174c26`): added 17 more tests (+557 insertion lines)
- Current: 1198 tests

The plan does NOT claim "1164 tests" -- that number does not appear in the plan text. The plan says "1046 tests pass" (Phase 1-3 complete), and the final V-R2 commit says "1198 tests pass".

---

## 6. "2 Independent Verification Rounds" Evidence

### Git log evidence:

| Commit | Message | Round |
|--------|---------|-------|
| `3f073f2` | "test: add 37 regression tests for popup elimination (Phase 4)" | Initial implementation |
| `b174c26` | "test: fill V-R2 adversarial test gaps -- symlink defense, degradation, /tmp/ paths" | V-R2 gap fill |

The Phase 4 section of the plan says:
> Verification: 2 independent rounds (R1 structural PASS WITH CONCERNS, R2 adversarial PASS WITH CONCERNS)

Evidence of V-R2 findings being addressed:
- `b174c26` commit explicitly names "V-R2 adversarial test gaps" with 4 gap categories (GAP 1-4)
- `56e6d0a` "fix: propagate symlink squat defense to all makedirs call sites (V-R2 findings)"

V-R1 evidence is less explicit in git log -- the R1 findings were likely incorporated into the initial Phase 4 commit itself (the plan says "R1 structural PASS WITH CONCERNS"). The V-R2 gap fill is separately committed.

**Assessment**: V-R2 is clearly evidenced. V-R1 is implied but not separately committed (likely folded into the main Phase 4 commit).

---

## 7. Test Quality Observations

### Strengths:
- All 37 regression tests PASS (verified via `pytest -v`)
- Tests cover multiple detection layers (AST walk, regex scan, multi-line scan for `TestNoAskVerdict`)
- Guardian patterns are embedded as constants -- self-contained without external dependency
- `TestGuardianPatternSync` provides optional drift detection when guardian repo is available
- V-R2 gap fill added real `/tmp/` path testing (tempfile.mkdtemp) instead of just `tmp_path` mocking
- Symlink/traversal defense tests present in cleanup_intents

### Concerns:
- The user-facing Step 4.1-4.4 names in the question do NOT match actual test names. The question names (`test_zero_write_tool_calls_for_staging`, `test_no_python3_c_in_skill`, `test_no_heredoc_in_skill`, `test_cleanup_intents_deterministic`) appear to be planned names that were refined during implementation. All functionality is covered.
- `TestGuardianPatternSync` tests are skip-dependent (only run when guardian repo is a sibling). They did PASS in the test run, meaning the guardian repo IS present.

---

## 8. Summary

| Check | Result |
|-------|--------|
| Step 4.1 (staging Write tool) | EXISTS -- 3 tests in `TestStagingPathOutsideClaudeDir` |
| Step 4.2 (python3 -c) | EXISTS -- 2 tests in `TestZeroPython3CInSkill` |
| Step 4.3 (heredoc) | EXISTS -- 3 tests in `TestNoHeredocInSavePrompt` |
| Step 4.4 (cleanup-intents) | EXISTS -- 12 tests in `TestCleanupIntents` + `TestCleanupIntentsTmpPath` |
| "37 regression tests" claim | CONFIRMED -- 37 tests in `test_regression_popups.py` |
| "1164 tests pass" claim | N/A -- plan says 1046 (Phase 1-3), V-R2 commit says 1198 (current) |
| V-R1 verification round | IMPLIED -- no separate commit, likely folded into Phase 4 commit |
| V-R2 verification round | CONFIRMED -- commit `b174c26` explicitly fills V-R2 gaps |
| All regression tests pass | CONFIRMED -- 37/37 passed |
| Current total test count | 1198 collected |
