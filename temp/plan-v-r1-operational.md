# Verification Round 1 — Operational Review: staging-hardening.md

**Reviewer**: V-R1 Operational
**Date**: 2026-03-22
**Plan**: `/home/idnotbe/projects/claude-memory/action-plans/staging-hardening.md`

---

## 1. Effort Estimation & Phase Scoping

### Phase 1 (Security Fix — Triage Fallback Bypass)

**Claimed**: ~4 code changes + 2 tests in 2 files.

**Verified against code**:
- Step 1.1: Lines 1523-1526 of `memory_triage.py` — change `get_staging_dir(cwd)` to `""`. One-line fix. Confirmed.
- Step 1.2: Guard at line 1527+ — add `if _staging_dir:` conditional around triage-data.json write block (lines 1528-1552). Needs to wrap ~25 lines but is a single logical change. Confirmed.
- Step 1.3: `write_context_files()` at lines 1130-1133 — the current code already sets `staging_dir = ""` on failure and falls through to `/tmp/.memory-triage-context-*.txt` predictable paths. The plan says "return empty dict" but the current fallback writes to predictable `/tmp/` filenames. The plan step is slightly ambiguous — does it mean skip writing entirely, or return `{}` early? **Needs clarification.** If "return empty dict" means skipping writes, the diff is small (early return). If it means removing the per-file fallback path, that changes the else-branch at line 1143.
- Step 1.4: Sync fallback `ensure_staging_dir` in lines 42-54 — add `S_ISDIR` check. Looking at the code, the fallback at line 42-54 is missing the `S_ISDIR` check that the main module has at line 80. This is a 2-line addition. Confirmed.
- Steps 1.5-1.6: Two tests. Reasonable scope.

**Assessment**: Phase 1 is well-scoped. ~30 minutes of implementation. The only ambiguity is Step 1.3 — the current `write_context_files` fallback writes to predictable `/tmp/` paths (`/tmp/.memory-triage-context-{category}.txt`) which are per-file (not in the staging dir). The plan should clarify whether to eliminate these fallback writes entirely or just fix the staging dir reuse.

### Phase 2 (Cross-Platform Fix — macOS `/private/tmp`)

**Claimed**: ~16 line changes across 8 files + 3 tests.

**Verified against code** (grepping `startswith("/tmp/"`):
- `memory_write.py`: 6 locations (lines 551, 603, 653, 759, 1597, 1599). Confirmed.
- `memory_draft.py`: 2 locations (lines 86, 89) + line 246. **Plan misses line 246** — `if root.startswith("/tmp/.claude-memory-staging-")`. This is a 3rd location in memory_draft.py.
- `memory_write_guard.py`: Lines 85 and 97. Confirmed.
- `memory_validate_hook.py`: Line 193. Confirmed.
- `memory_judge.py`: Line 120. Confirmed.
- `memory_triage.py`: Fallback at line 41 and line 1460. Confirmed.
- `memory_retrieve.py`: Fallback at line 50. Confirmed.
- `memory_staging_utils.py`: Line 20 (STAGING_DIR_PREFIX) and line 111 (`startswith(STAGING_DIR_PREFIX)`). The plan covers line 20 but line 111 is implicitly fixed by changing the constant. Confirmed.

**Missing location**: `memory_draft.py` line 246 (`root.startswith("/tmp/.claude-memory-staging-")`) is not listed in Steps 2.1-2.8. This is a validation check in a different function from the two locations listed in Step 2.3. **GAP: Plan undercounts memory_draft.py changes (3, not 2).**

**Assessment**: Phase 2 is broader than claimed. 17-18 line changes across 8 files. The mechanical nature (search-and-replace with a constant) reduces risk, but the sheer number of locations means a single missed instance silently breaks macOS validation for that code path. The plan's approach of defining `RESOLVED_TMP_PREFIX` in staging_utils and importing it everywhere is sound, but:
- Several files have inline fallbacks that don't import from staging_utils (triage fallback at line 41, retrieve fallback at line 50). These define their own `/tmp/` literals.
- **Recommendation**: Add a grep-based verification step: `grep -rn 'startswith("/tmp/' hooks/scripts/memory_*.py` should return zero hits after Phase 2. This is missing from Phase 4 verification.

### Phase 3 (Hardening — S_ISDIR + Multi-User Isolation)

**Claimed**: 1 commit + 3 code changes + 4 tests.

**Verified**:
- Step 3.1: Commit existing S_ISDIR fix — already present in `_validate_existing_staging()` at line 80-83. The working tree diff confirms this. Confirmed.
- Step 3.2: Update test name/assertion. Minor. Confirmed.
- Step 3.3: FIFO and socket tests. New tests only.
- Steps 3.4-3.6: Change hash formula in 3 locations (staging_utils, triage fallback, retrieve fallback). Each is a one-line change from `os.path.realpath(cwd).encode()` to `f"{os.geteuid()}:{os.path.realpath(cwd)}"`. Confirmed.
- Steps 3.7-3.8: One test + one comment. Reasonable.

**Assessment**: Phase 3 is well-scoped. The S_ISDIR fix is already in the working tree, so the "commit" step is just `git add + commit`. The UID-in-hash changes are mechanical. ~20 minutes of implementation.

### Overall Session Feasibility

All three implementation phases + Phase 4 verification in one session: **feasible but tight**. The total is approximately:
- Phase 1: ~30 min (4 code changes, 2 tests, some ambiguity in Step 1.3)
- Phase 2: ~45 min (17-18 changes across 8 files, 3 tests, high attention needed)
- Phase 3: ~20 min (1 commit, 3 changes, 4 tests)
- Phase 4: ~15 min (test suite, compile checks, verification rounds)

Total: ~2 hours. This is achievable in a single focused session but leaves little buffer for debugging test failures or discovering additional missed locations. **Verdict: realistic but should not be rushed.**

---

## 2. Risk Assessment

### Phase 1 Blast Radius: LOW

- Changes only `memory_triage.py`.
- Fallback behavior already exists (inline `<triage_data>` emission). The fix makes the code use it more aggressively.
- Risk: if the inline fallback path has its own bugs, those now trigger more frequently. However, the inline path is already tested and works when triage-data.json write fails for any reason (line 1552: `triage_data_path = None`).
- **Rollback cost**: revert one file.

### Phase 2 Blast Radius: MEDIUM-HIGH

- Touches 8 files across the entire hook ecosystem.
- A partial application (some files fixed, some not) creates an inconsistent state where some guards pass and others reject the same path on macOS.
- The `STAGING_DIR_PREFIX` constant change in `memory_staging_utils.py` is module-load-time (`os.path.realpath("/tmp")` evaluated at import). This means the prefix becomes `/private/tmp/.claude-memory-staging-` on macOS. Any file that still uses the literal `"/tmp/.claude-memory-staging-"` will fail to match.
- **Critical risk**: The inline fallback functions in `memory_triage.py` (line 41) and `memory_retrieve.py` (line 50) define their own `get_staging_dir()` that hardcodes `f"/tmp/.claude-memory-staging-{_h}"`. If these fallbacks are used (import failure), they generate a path that won't match the updated `STAGING_DIR_PREFIX`. This is a **silent cross-module inconsistency on macOS with partial deployment**. The plan addresses this (Steps 2.7, 2.8) but the dependency is implicit.
- **Rollback cost**: revert 8 files. Moderate.

**Recommendation**: Phase 2 should be a single atomic commit. If any file is missed, the macOS behavior is worse than before (partial validation, inconsistent paths). Add an explicit verification grep as a gating check.

### Phase 3 Blast Radius: LOW-MEDIUM

- Hash formula change orphans existing staging dirs (new sessions get new paths, old dirs sit in `/tmp/` until OS cleanup).
- **Risk during upgrade**: An in-flight session (SKILL.md orchestration running) that started before the upgrade will have `triage-data.json` in the old staging dir. If the session's Phase 1.5 scripts load the new code (after upgrade), they'll compute a different staging dir and fail to find `triage-data.json`. This is documented as "orphaned dirs are harmless" but **in-flight sessions will break**.
- **Mitigation**: This is unlikely in practice because the plugin is loaded at session start. But it should be documented: "Do not upgrade while a memory save operation is in progress."
- **Rollback cost**: revert 3 files. Low.

### Should Phases Be More Granular?

No. The current granularity is appropriate:
- Phase 1 is already minimal (one file, one bug).
- Phase 2 must be atomic (partial application is worse than no fix).
- Phase 3 groups two related hardening changes (S_ISDIR + UID hash) that share the same test surface.

---

## 3. Migration Impact

### UID-in-Hash Change (Phase 3, Step 3.4)

The plan documents this in the Decision Log: "Accept orphaned staging dirs on hash change — /tmp/ is cleaned by OS; staging data is ephemeral; no migration needed."

**Assessment**: This is the correct call. However:

1. **Documentation clarity**: Step 3.8 says "Add comment documenting hash formula change from v5.1.0." This is good but should also note the version number in which the change was made (v5.1.1 or whatever it becomes) so future maintainers can trace when the hash changed.

2. **No migration step needed**: Correct. Staging dirs contain only ephemeral files (triage-data.json, context-*.txt, intent-*.json). There is no persistent state worth migrating.

3. **In-flight sessions during upgrade**: As noted in Section 2, an in-flight memory save will break because the triage-data.json is in the old-hash staging dir. The plan does not mention this. **GAP: Add a note that upgrades should not be applied during active memory save operations, or add a one-time fallback that checks both old-hash and new-hash staging dirs.**

4. **Multi-user scenario**: The whole point of UID-in-hash is multi-user isolation. On a shared machine, User A's sessions generate staging dirs with hash `sha256("1000:/real/path")[:12]` while User B gets `sha256("1001:/real/path")[:12]`. This is correct and the old dirs (without UID) become orphans. No collision risk because new sessions always use the new formula.

---

## 4. Test Strategy Assessment

### Proposed Tests

| Phase | Test | Coverage |
|-------|------|----------|
| 1 | `test_triage_fallback_does_not_use_rejected_path` | Verifies the core fix |
| 1 | `test_context_files_skip_on_staging_failure` | Verifies context file fallback |
| 2 | `test_staging_prefix_is_resolved` | Verifies constant initialization |
| 2 | `test_resolved_path_matches_staging_prefix` | Integration test |
| 2 | Mock macOS `/private/tmp` test | Cross-platform simulation |
| 3 | `test_regular_file_at_path_raises_not_directory` | S_ISDIR check (rename existing) |
| 3 | FIFO and socket tests | Non-directory rejection |
| 3 | `test_different_users_get_different_staging_dirs` | UID isolation |

### Gaps Identified

1. **Missing: Phase 2 cross-file consistency test.** No test verifies that ALL files use the resolved prefix. A test that greps the source files for literal `"/tmp/.claude-memory-staging-"` (excluding comments and the resolved-prefix definition itself) would catch future regressions. This is more of a lint check but is important given Phase 2's "one missed location breaks macOS" nature.

2. **Missing: Phase 1 end-to-end triage output test.** The proposed tests mock `ensure_staging_dir` but don't verify the full `main()` output when staging fails. A test that runs `_run_triage()` with a broken staging dir and checks that the JSON output contains `<triage_data>` inline (not `<triage_data_file>`) would be valuable.

3. **Missing: Phase 2 `is_staging_path()` after prefix change.** The `is_staging_path()` function in `memory_staging_utils.py` uses `STAGING_DIR_PREFIX` which will change. Tests should verify it still works with resolved paths. The existing `TestIsStagingPath` tests use literal `/tmp/...` paths — on macOS, they'd need to use `/private/tmp/...`. This gap could cause test failures on macOS CI.

4. **Missing: Phase 3 hash stability test.** A test that pins the expected hash for a known input (e.g., `get_staging_dir("/home/testuser/project")` with `geteuid() == 1000`) and asserts the exact output. This catches accidental hash formula changes in future refactors.

5. **Missing: `write_context_files` predictable path security test.** The fallback path at line 1143 (`/tmp/.memory-triage-context-{cat_lower}.txt`) uses predictable filenames. Even though `O_NOFOLLOW` is used for the write, there's no test verifying that `O_NOFOLLOW` is actually used in the fallback path. The plan's Step 1.3 may eliminate this path, but if it doesn't, a test should exist.

---

## 5. Cross-Model Consultation (clink/codex)

**Question**: Is splitting macOS cross-platform fix and triage fallback into separate phases the right ordering?

**Codex assessment**: Keep Phase 1 and Phase 2 as separate changesets. Recommended order: Phase 1 first, Phase 2 second, Phase 3 third. Ship Phase 1 and Phase 2 in the same release train or as back-to-back hotfixes.

**Key rationale from Codex**:
- Phase 1 is a one-file control-flow fix with clear security semantics and minimal blast radius — easiest to review, backport, cherry-pick, and roll back independently.
- Phase 2 is a repo-wide compatibility sweep across independent validators — larger test surface and higher regression risk, but no code dependency on Phase 1.
- Combining them muddies rollback and root-cause analysis.
- Phase 3 should remain separate and later since it changes the staging-dir identity formula — materially different from bug-fix work and should not share rollback scope with emergency fixes.

**My agreement**: The plan's current ordering is correct. Phase 1 (security) before Phase 2 (cross-platform) is the right priority because the security fix is narrow and high-impact, while the cross-platform fix is broad and mechanical. Separate phases allow independent rollback.

---

## 6. Vibe Check

### Quick Assessment

The plan is well-structured and addresses real issues found by cross-model audit. It is on track with minor gaps in test coverage and one missing code location.

### Key Questions to Consider

1. What happens to `write_context_files`'s predictable `/tmp/.memory-triage-context-*.txt` fallback paths — does Step 1.3 eliminate them entirely, or just stop using the rejected staging dir? The plan's language ("return empty dict on staging dir failure") suggests elimination, but this should be explicit.
2. Has `memory_draft.py` line 246 been accounted for in Phase 2? The plan lists 2 locations but there are 3.
3. How will you verify that no literal `"/tmp/.claude-memory-staging-"` strings remain after Phase 2? Without a grep gate, a single missed location silently breaks macOS.
4. Is the in-flight session breakage from Phase 3's hash change acceptable without documentation?

### Pattern Watch

- **Undercount bias**: The plan undercounts Phase 2 locations (memory_draft.py has 3, not 2). This is a common pattern in search-and-replace plans where locations are enumerated manually rather than by automated grep.
- **Implicit dependency**: Phase 2's fallback functions in triage/retrieve must be updated together with the constant — this cross-module coupling is documented in steps but not called out as a hard dependency.

### Recommendation

**Proceed with minor adjustments:**
1. Clarify Step 1.3 intent (eliminate predictable fallback paths vs. just fix staging dir reuse).
2. Add `memory_draft.py` line 246 to Phase 2 Step 2.3.
3. Add a grep-based verification gate to Phase 4: `grep -rn 'startswith("/tmp/' hooks/scripts/memory_*.py` should return zero matches.
4. Add a note about in-flight session impact for Phase 3.
5. Consider adding a hash stability test (pin expected output for known input).

---

## Summary

| Area | Verdict | Notes |
|------|---------|-------|
| Phase scoping | GOOD | Appropriate granularity, correct ordering |
| Effort estimation | SLIGHTLY UNDER | Phase 2 has 17-18 changes, not 16; memory_draft.py has 3 locations not 2 |
| Session feasibility | FEASIBLE | ~2 hours total, tight but doable |
| Risk assessment | ADEQUATE | Phase 2 needs atomic commit; Phase 3 in-flight risk undocumented |
| Migration impact | ACCEPTABLE | Orphaned dirs are harmless; in-flight sessions need a warning |
| Test strategy | GOOD WITH GAPS | 5 test gaps identified; most important is Phase 2 grep-based consistency check |
| Phase ordering | CORRECT | Confirmed by Codex: security first, cross-platform second, hardening third |
