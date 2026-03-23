---
status: done
progress: "ALL PHASES COMPLETE. I1/I2/I3 resolved. 1325 tests pass, 0 new regressions. 8 verification rounds passed."
---

# /tmp/ Staging Hardening — Action Plan

Cross-model audit (Opus 4.6 + Codex 5.3 + Gemini 3.1 Pro) of the eliminate-all-popups work discovered 3 security/cross-platform issues in the `/tmp/` staging migration. This plan addresses them in priority order.

## Issue Summary

| # | Severity | Issue | Root Cause |
|---|----------|-------|------------|
| I1 | HIGH | Triage fallback bypasses symlink defense | `ensure_staging_dir()` failure → `get_staging_dir()` returns same compromised path |
| I2 | CRITICAL | macOS `/tmp` → `/private/tmp` breaks all validation | Hardcoded `startswith("/tmp/")` fails after `Path.resolve()` on macOS |
| I3 | MEDIUM | `validate_staging_dir()` S_ISDIR gap + multi-user DoS | Missing type check; hash lacks UID |

## Phase 1: Security Fix — Triage Fallback Bypass (I1)

**Goal**: When `ensure_staging_dir()` detects a symlink attack, do NOT write to the compromised path.

- [x] **Step 1.1**: Fix `memory_triage.py:1523-1526` — replace `get_staging_dir(cwd)` fallback with `_staging_dir = ""`. When `_staging_dir` is empty, **omit** `triage_data["staging_dir"]` key entirely (do not set to `None` or `""`) — SKILL.md falls back to computing the path when key is absent.
- [x] **Step 1.2**: Guard triage-data.json write at line 1527+ with `if _staging_dir:` check. Set `triage_data_path = None` BEFORE the try block (not relying on exception flow). When `_staging_dir` is empty, skip the file write entirely → inline `<triage_data>` fallback triggers.
- [x] **Step 1.3**: Fix `write_context_files()` at lines 1130-1133 — return `{}` immediately on staging dir failure (skip all context file writes). This eliminates the predictable `/tmp/.memory-triage-context-*.txt` fallback paths entirely. **Note**: SKILL.md skips categories with missing `context_file` (SKILL.md:118-119). Verify that inline `<triage_data>` contains sufficient context snippets for the drafter, or update SKILL.md to process categories without context files as a degraded path.
- [x] **Step 1.4**: Sync fallback `ensure_staging_dir` in `memory_triage.py:42-54` with main module — add `S_ISDIR` check after symlink check
- [x] **Step 1.5**: Add test: `test_triage_fallback_does_not_use_rejected_path` — mock `ensure_staging_dir` to raise, verify no write to `get_staging_dir()` path
- [x] **Step 1.6**: Add test: `test_context_files_skip_on_staging_failure` — verify empty dict returned

**Files**: `hooks/scripts/memory_triage.py`, `tests/test_memory_triage.py`

## Phase 2: Cross-Platform Fix — macOS `/private/tmp` (I2)

**Goal**: All `startswith("/tmp/...")` checks work on macOS where `/tmp` → `/private/tmp`.

- [x] **Step 2.1**: Change `STAGING_DIR_PREFIX` in `memory_staging_utils.py:20` from `"/tmp/.claude-memory-staging-"` to `os.path.realpath("/tmp") + "/.claude-memory-staging-"`. Add `RESOLVED_TMP_PREFIX = os.path.realpath("/tmp") + "/"`.
- [x] **Step 2.2**: Fix `memory_write.py` — 6 locations (lines 551, 603, 653, 759, 1597, 1599). Import `STAGING_DIR_PREFIX` and `RESOLVED_TMP_PREFIX` from `memory_staging_utils` where import is available (post-venv bootstrap). For pre-bootstrap paths, define local `_RESOLVED_TMP_STAGING = os.path.realpath("/tmp") + "/.claude-memory-staging-"`. Replace all hardcoded strings.
- [x] **Step 2.3**: Fix `memory_draft.py` — 3 locations (lines 86, 89, 246). Replace hardcoded `/tmp/` prefixes with resolved equivalents.
- [x] **Step 2.4**: Fix `memory_write_guard.py` — line 97 `_TMP_STAGING_PREFIX` and line 85 `/tmp/` check. Use `os.path.realpath("/tmp")`.
- [x] **Step 2.5**: Fix `memory_validate_hook.py` — line 193 `_TMP_STAGING_PREFIX`. Use `os.path.realpath("/tmp")`.
- [x] **Step 2.6**: Fix `memory_judge.py` — line 120 `/tmp/` check. Use resolved prefix.
- [x] **Step 2.7**: Fix `memory_triage.py` — line 41 fallback `get_staging_dir` and line 1460 `/tmp/` check. Use `os.path.realpath("/tmp")`.
- [x] **Step 2.8**: Fix `memory_retrieve.py` — line 50 fallback `get_staging_dir`. Use resolved prefix.
- [x] **Step 2.9**: Fix `memory_staging_guard.py` — line 43 regex `_STAGING_PATH_PATTERN`. Build regex dynamically from `re.escape(STAGING_DIR_PREFIX)` (import from `memory_staging_utils`) to stay in sync with runtime paths. Generate alternation from `sorted({"/tmp", os.path.realpath("/tmp")})` to match both literal and resolved prefixes.
- [x] **Step 2.10**: Add test: `test_staging_prefix_is_resolved` — verify `STAGING_DIR_PREFIX.startswith(os.path.realpath("/tmp"))`.
- [x] **Step 2.11**: Add test: `test_resolved_path_matches_staging_prefix` — create file in staging dir, resolve, verify `startswith(STAGING_DIR_PREFIX)`.
- [x] **Step 2.12**: Add mock test: simulate macOS `/private/tmp` via `monkeypatch` on `os.path.realpath` + `importlib.reload(memory_staging_utils)` (constant is evaluated at import time). Verify `STAGING_DIR_PREFIX` changes.
- [x] **Step 2.13**: Add grep verification: `grep -rn 'startswith("/tmp/' hooks/scripts/memory_*.py` AND `grep -rn '"/tmp/.claude-memory-staging-' hooks/scripts/memory_*.py` must return zero hits after all Phase 2 changes. Also check SKILL.md and tests for hardcoded `/tmp/` staging paths.
- [x] **Step 2.14**: Update SKILL.md staging directory references (line 36+) and any test files that hardcode `/tmp/.claude-memory-staging-*` to use the resolved prefix or import from `memory_staging_utils`.

**Files**: `hooks/scripts/memory_staging_utils.py`, `memory_write.py`, `memory_draft.py`, `memory_write_guard.py`, `memory_validate_hook.py`, `memory_judge.py`, `memory_triage.py`, `memory_retrieve.py`, `memory_staging_guard.py`, `tests/`

## Phase 3: Hardening — S_ISDIR + Multi-User Isolation (I3)

**Goal**: Reject non-directory staging paths; prevent cross-user hash collisions.

- [x] **Step 3.1**: Commit the existing `_validate_existing_staging()` S_ISDIR fix in working tree (`memory_staging_utils.py`). Already adds `not stat.S_ISDIR(st.st_mode)` check.
- [x] **Step 3.2**: Update test `test_regular_file_at_path_does_not_pass_silently` → `test_regular_file_at_path_raises_not_directory`. Assert `RuntimeError` instead of silent pass.
- [x] **Step 3.3**: Add tests for FIFO and socket at staging path → `RuntimeError`.
- [x] **Step 3.4**: Change `get_staging_dir()` in `memory_staging_utils.py:37` to hash `f"{os.geteuid()}:{os.path.realpath(cwd)}"` for per-user isolation.
- [x] **Step 3.5**: Sync fallback `get_staging_dir()` in `memory_triage.py:37-41` with same UID-in-hash formula.
- [x] **Step 3.6**: Sync fallback `get_staging_dir()` in `memory_retrieve.py:50` with same formula.
- [x] **Step 3.7**: Add test: `test_different_users_get_different_staging_dirs` — mock `os.geteuid()` to return different values, verify different hashes.
- [x] **Step 3.8**: Add comment in `get_staging_dir()` documenting hash formula change from v5.1.0 (orphaned dirs are harmless, cleaned by OS).
- [x] **Step 3.9**: Update tests that manually compute staging hashes using old formula: `test_memory_staging_utils.py:75`, `test_memory_triage.py:1159,1732`, `test_memory_retrieve.py:23`. These will break with UID-in-hash change.
- [x] **Step 3.10**: Add `follow_symlinks=False` to `os.chmod()` calls in `memory_staging_utils.py:94` and `memory_triage.py:53` to prevent TOCTOU-based chmod-through-symlink on legacy paths.

**Files**: `hooks/scripts/memory_staging_utils.py`, `memory_triage.py`, `memory_retrieve.py`, `tests/`

## Phase 4: Regression Tests + Verification

- [x] **Step 4.1**: Run full test suite `pytest tests/ -v` — verify no regressions from Phase 1-3 changes
- [x] **Step 4.2**: Compile-check all modified scripts: `for f in hooks/scripts/memory_*.py; do python3 -m py_compile "$f"; done`
- [x] **Step 4.3**: Verify staging guard regex in `memory_staging_guard.py` still matches new paths
- [x] **Step 4.4**: Verification: 2 independent rounds (structural + adversarial)

## Phase 5: Future Hardening (Track Only)

These are lower-priority follow-ups, not blocking for this plan:

- [x] **P3**: Legacy path parent chain validation (validate ancestor ownership with `lstat`)
- [x] **P4**: fd-pinning with `O_DIRECTORY | O_NOFOLLOW` + `dir_fd=` for TOCTOU elimination
- [x] **P5**: `XDG_RUNTIME_DIR` / `~/.cache` migration to eliminate `/tmp/` class entirely
- [x] **P6**: `follow_symlinks=False` audit for all `os.chmod()` calls across hook scripts

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_triage.py | Triage fallback fix, context files fix, fallback function S_ISDIR + UID hash |
| hooks/scripts/memory_staging_utils.py | Resolved STAGING_DIR_PREFIX, RESOLVED_TMP_PREFIX, S_ISDIR commit, UID-in-hash |
| hooks/scripts/memory_write.py | 6 resolved `/tmp/` prefix replacements |
| hooks/scripts/memory_draft.py | 3 resolved `/tmp/` prefix replacements |
| hooks/scripts/memory_write_guard.py | Resolved _TMP_STAGING_PREFIX + /tmp/ check |
| hooks/scripts/memory_validate_hook.py | Resolved _TMP_STAGING_PREFIX |
| hooks/scripts/memory_judge.py | Resolved /tmp/ check |
| hooks/scripts/memory_retrieve.py | Fallback get_staging_dir UID hash + resolved prefix |
| hooks/scripts/memory_staging_guard.py | Regex updated for macOS `/private/tmp/` paths |
| tests/ | New tests for all 3 issues |

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Inline triage data fallback over get_staging_dir() | Using rejected path defeats validation; inline fallback already exists and is tested |
| Omit `staging_dir` key over setting to `None`/`""` | SKILL.md checks for key absence (not null); `null` becomes literal `"null"` via `jq -r` |
| Dynamic regex from runtime prefix over hardcoded OS aliases | Hardcoded `(?:/(?:private/)?tmp/...)` breaks on non-macOS/Linux systems; `re.escape(prefix)` stays in sync |
| `os.path.realpath("/tmp")` at module load, not `tempfile.gettempdir()` | `gettempdir()` respects TMPDIR env var (attacker-controlled); `realpath("/tmp")` is safe |
| UID-in-hash over XDG_RUNTIME_DIR | Pragmatic incremental fix; XDG is architecturally superior but larger change (tracked as P5) |
| Accept orphaned staging dirs on hash change | /tmp/ is cleaned by OS; staging data is ephemeral; no migration needed |

## Research References

- `temp/research-macos.md` — 14 affected code paths, fix strategy
- `temp/research-triage-fallback.md` — full fallback flow trace, attack surface analysis
- `temp/research-staging-hardening.md` — S_ISDIR flow, UID-in-hash, other gaps
- `temp/cross-model-analysis.md` — Opus/Codex/Gemini agreement matrix
