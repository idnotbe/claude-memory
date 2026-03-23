---
status: done
progress: "ALL PHASES COMPLETE. P3/P4/P5/P6 resolved. 1389 tests pass, 0 new regressions. 8 verification rounds passed."
---

# Phase 5 Hardening — Action Plan

Resolves the 4 residual low-severity risks from staging-hardening Phase 5:
- P3: Legacy path parent chain validation
- P4: fd-pinning with O_DIRECTORY|O_NOFOLLOW + dir_fd for TOCTOU elimination
- P5: XDG_RUNTIME_DIR / ~/.cache migration to eliminate /tmp/ class entirely
- P6: follow_symlinks=False audit for all os.chmod() calls

## Issue Summary

| # | Severity | Issue | Root Cause | Status |
|---|----------|-------|------------|--------|
| P6 | LOW | Missing follow_symlinks=False on os.chmod() | Potential chmod-through-symlink | **PASS** — audit confirms 2/2 covered |
| P3 | MEDIUM | Legacy path parent chain unvalidated | os.makedirs() blindly trusts ancestors | Active |
| P4 | MEDIUM | TOCTOU between validate and use | Path-based API, validate-then-use pattern | Pending |
| P5 | LOW | /tmp/ world-writable attack surface | Staging in world-writable directory | Pending |

## Implementation Order

P6 (done) → P3 → P4 → P5

Rationale: P3 is smallest/independent. P4 adds fd-pinning API (no path change). P5 changes WHERE staging lives (largest, uses P4's API).

## Phase P6: follow_symlinks=False Audit (DONE)

- [x] Audit all os.chmod() calls across hooks/scripts/*.py
- [x] Result: 2/2 calls have follow_symlinks=False + correct (NotImplementedError, OSError) fallback
- [x] No other follow_symlinks-relevant operations need changes
- [x] Report: temp/p5-p6-audit.md

## Phase P3: Legacy Path Parent Chain Validation

**Goal**: Validate ancestor ownership/type with lstat before os.makedirs() in legacy staging path branch.

- [x] **Step 3.1**: Add `_validate_parent_chain(target_path)` to `memory_staging_utils.py`
  - Walk root→target with os.lstat() per component
  - Check: not symlink (S_ISLNK), is directory (S_ISDIR), owned by euid or root (uid 0)
  - FileNotFoundError → break (component doesn't exist yet, safe)
  - PermissionError → fail-closed (RuntimeError)
  - Requires absolute path (ValueError on relative)
  - Uses os.path.normpath() (NOT realpath — don't resolve symlinks)

- [x] **Step 3.2**: Integrate into `validate_staging_dir()` legacy branch (line 127)
  - Call `_validate_parent_chain(staging_dir)` BEFORE `os.makedirs()`

- [x] **Step 3.3**: Add `TestValidateParentChain` tests (~13 unit tests):
  - valid_chain_all_owned_by_user
  - valid_chain_with_root_owned_ancestors
  - rejects_symlink_in_middle_of_chain
  - rejects_symlink_at_first_user_component
  - rejects_foreign_owned_ancestor (mock lstat uid=9999)
  - accepts_nonexistent_components
  - rejects_non_directory_ancestor
  - rejects_relative_path
  - handles_dot_dot_in_path
  - permission_denied_fails_closed
  - root_path_only
  - single_level_path

- [x] **Step 3.4**: Add integration tests (~4 tests):
  - legacy_staging_rejects_symlink_in_parent_chain
  - legacy_staging_rejects_foreign_parent
  - legacy_staging_creates_dirs_after_validation
  - legacy_staging_symlink_grandparent

- [x] **Step 3.5**: Regression tests:
  - tmp_staging_path_unchanged
  - legacy_idempotent_still_works

- [x] **Step 3.6**: Compile check + full test suite

**Files**: `hooks/scripts/memory_staging_utils.py`, `tests/test_memory_staging_utils.py`

**NOT modified** (rationale):
- memory_triage.py: fallback ensure_staging_dir only produces /tmp/ paths
- memory_draft.py: calls validate_staging_dir() which gets fix automatically
- memory_write.py: ImportError fallback is separate concern
- memory_logger.py: has own containment check, fail-open by design

## Phase P4: fd-pinning with O_DIRECTORY|O_NOFOLLOW + dir_fd

**Goal**: Eliminate TOCTOU by pinning staging dir to an fd, operating via dir_fd.

- [x] **Step 4.1**: Add `PinnedStagingDir` context manager to `memory_staging_utils.py`
  - Opens with O_RDONLY | O_DIRECTORY | O_NOFOLLOW
  - Validates via os.fstat(fd) — ownership, not symlink (inherent from O_NOFOLLOW)
  - Permission fix via os.fchmod(fd) — no follow_symlinks concern
  - Methods: open_file(), write_file(), read_file(), unlink(), listdir()
  - Atomic writes: tmp+rename pattern via os.rename(src, dst, src_dir_fd=fd, dst_dir_fd=fd)
  - Note: os.replace() lacks dir_fd → use os.rename() (identical on POSIX)

- [x] **Step 4.2**: Add `_create_staging_dir_if_needed()` helper
  - Simple os.mkdir() with FileExistsError pass
  - Full validation deferred to fstat after fd-open

- [x] **Step 4.3**: Adopt in `memory_triage.py` (8 TOCTOU sites)
  - write_sentinel, _acquire_triage_lock, _increment_fire_count
  - write_context_files, main triage output (triage-data.json)
  - Thread PinnedStagingDir through _run_triage()

- [x] **Step 4.4**: Adopt in `memory_orchestrate.py` (5 TOCTOU sites)
  - _safe_write(), collect_intents(), _write_manifest()
  - Replace Path.glob() with os.listdir(fd) + fnmatch
  - Opens own PinnedStagingDir (subprocess boundary)

- [x] **Step 4.5**: Adopt in `memory_draft.py` (1 TOCTOU site)
  - write_draft() uses PinnedStagingDir
  - Opens own PinnedStagingDir (subprocess boundary)

- [x] **Step 4.6**: Adopt in `memory_write.py` (4 TOCTOU sites)
  - atomic_write_text(): replace tempfile.mkstemp with os.open(dir_fd=)
  - cleanup_staging/cleanup_intents: os.listdir(fd) + fnmatch + os.unlink(dir_fd=)
  - write_save_result, _advance_sentinel_state: PinnedStagingDir

- [x] **Step 4.7**: Unit tests for PinnedStagingDir (~11 tests)
- [x] **Step 4.8**: TOCTOU elimination tests (~3 tests)
- [x] **Step 4.9**: Integration tests (~5 tests)
- [x] **Step 4.10**: Regression tests (~3 tests)

**Files**: memory_staging_utils.py, memory_triage.py, memory_orchestrate.py, memory_draft.py, memory_write.py, tests/

## Phase P5: XDG_RUNTIME_DIR / ~/.cache Migration

**Goal**: Eliminate /tmp/ class entirely. No /tmp/ fallback.

**Resolution priority**: XDG_RUNTIME_DIR (strict 0700) → /run/user/$UID → macOS confstr → ~/.cache/claude-memory/staging/

- [x] **Step 5.1**: Add `_resolve_staging_base()` to `memory_staging_utils.py`
  - XDG_RUNTIME_DIR: must be 0700, owned by euid, is directory
  - /run/user/$UID: same checks
  - macOS: os.confstr("CS_DARWIN_USER_TEMP_DIR") — bypasses TMPDIR env var
  - ~/.cache/claude-memory/staging/: universal fallback (always available)
  - WSL2 0777 XDG_RUNTIME_DIR → rejected by 0700 check → falls to ~/.cache

- [x] **Step 5.2**: Update STAGING_DIR_PREFIX, RESOLVED_TMP_PREFIX, _RESOLVED_TMP
  - STAGING_DIR_PREFIX = _STAGING_BASE + "/.claude-memory-staging-"
  - RESOLVED_TMP_PREFIX may become unnecessary (kept for /tmp/ Write tool compat)
  - is_staging_path() uses new prefix

- [x] **Step 5.3**: Import memory_staging_utils in guard scripts
  - memory_write_guard.py: import STAGING_DIR_PREFIX, is_staging_path
  - memory_validate_hook.py: import STAGING_DIR_PREFIX
  - memory_staging_guard.py: import STAGING_DIR_PREFIX, build regex from it
  - All 3 are safe to import (memory_staging_utils is stdlib-only)

- [x] **Step 5.4**: Move staging_utils import before venv bootstrap in memory_write.py
  - Eliminates fallback constant problem entirely
  - memory_staging_utils is stdlib-only, always importable

- [x] **Step 5.5**: Remove fallback copies in memory_triage.py and memory_retrieve.py
  - staging_utils is always available from installed plugin
  - Eliminates sync-drift risk

- [x] **Step 5.6**: Update memory_draft.py staging path validation
  - Keep /tmp/ allowance for Write tool input files
  - Update staging prefix check to use new location

- [x] **Step 5.7**: Update memory_judge.py transcript path validation
  - Keep /tmp/ for transcript paths (Claude Code uses /tmp/)
  - No staging change needed

- [x] **Step 5.8**: Add age-based cleanup in ensure_staging_dir()
  - Sweep sibling staging dirs with mtime > 7 days
  - Only for ~/.cache paths (tmpfs paths auto-clean)

- [x] **Step 5.9**: Update tests (~1000 references across 11 files)
  - Replace hardcoded /tmp/ assertions with STAGING_DIR_PREFIX
  - Add staging_base fixture for test isolation
  - Reload memory_staging_utils after monkeypatch

- [x] **Step 5.10**: Update documentation (CLAUDE.md, SKILL.md, agents/memory-drafter.md)

- [x] **Step 5.11**: Backward compatibility
  - Accept reads from both old (/tmp/) and new locations during transition
  - Guards auto-approve both locations
  - After one release cycle, drop /tmp/ staging support

**Files**: All 9 core scripts, 11 test files, 4+ documentation files (~20 total)

## Verification Strategy

Each phase (P3, P4, P5) gets 2 independent verification rounds:
- V1: Correctness/security perspective
- V2: Adversarial/edge case perspective
Each includes vibe-check + cross-model opinion (opus 4.6 + codex 5.3 + gemini 3.1 pro via pal clink)

## Decision Log

| Decision | Rationale |
|----------|-----------|
| P6 PASS, no changes | 2/2 os.chmod() already have follow_symlinks=False with correct fallback |
| P3: Accept TOCTOU gap | Defense-in-depth (lstat walk); P4 eliminates gap with fd-pinning |
| P3: Accept root-owned ancestors | System directories (/home, /tmp) are root-owned; attackers can't create root-owned dirs |
| P4: Context manager over tuple return | Auto-cleanup prevents fd leaks; exception-safe |
| P4: os.rename() over os.replace() | os.replace() lacks dir_fd; os.rename() is identical on POSIX |
| P5: No /tmp/ fallback at all | Core goal is eliminating /tmp/ attack class |
| P5: Import staging_utils in guards | stdlib-only module; eliminates all duplicated constants |
| P5: Strict 0700 check on XDG_RUNTIME_DIR | WSL2 sets 0777, which is no better than /tmp/ |
| P5: macOS confstr over tempfile.gettempdir() | confstr bypasses attacker-controlled TMPDIR env var |

## Research References

- `temp/p5-p3-research.md` — parent chain validation: vulnerability, algorithm, edge cases, tests
- `temp/p5-p4-research.md` — fd-pinning: TOCTOU sites, dir_fd matrix, PinnedStagingDir design
- `temp/p5-p5-research.md` — XDG migration: platform analysis, guard updates, test strategy
- `temp/p5-p6-audit.md` — chmod audit: 2/2 covered, PASS
