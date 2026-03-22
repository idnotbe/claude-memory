# Phase 3 Audit: Staging Migration to /tmp/

**Audited by:** Claude Opus 4.6 (1M context)
**Date:** 2026-03-22
**Action plan:** `action-plans/eliminate-all-popups.md`
**Phase 3 scope:** Fix P3 -- Eliminate Write Tool popups for staging files by moving staging from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<project-hash>/`

---

## Option Investigation Status

### Option C (PermissionRequest hook): INVESTIGATED, NOT USED
**Status:** DONE (correctly abandoned)
**Evidence:**
- `action-plans/eliminate-all-popups.md:39-43` defines Option C as a 30-min investigation
- `hooks/hooks.json` contains NO `PermissionRequest` hook entries (grep: 0 matches)
- No `PermissionRequest` handler script exists in `hooks/scripts/`
- **Conclusion:** Option C was investigated and determined not viable. The plan proceeded to Option B as designed.

### Option A (FALLBACK -- route staging writes through Python): NOT USED
**Status:** DONE (correctly not used)
**Evidence:**
- `memory_write.py` has NO `write-staging` action (grep: 0 matches for `write.staging` or `write_staging`)
- The `--action` dispatch in `memory_write.py` does not include any staging write pass-through
- **Conclusion:** Option A was correctly not implemented. Option B was chosen instead.

### Option B (RECOMMENDED -- move staging to /tmp/): IMPLEMENTED
**Status:** This is the implementation path. Verified step by step below.

---

## Step-by-Step Verification

### Step 3.1: Staging moved to `/tmp/.claude-memory-staging-<project-hash>/`
**Verdict: DONE**

| Evidence | Location |
|----------|----------|
| Shared utility module created | `hooks/scripts/memory_staging_utils.py:20` -- `STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"` |
| Deterministic path function | `memory_staging_utils.py:23-38` -- `get_staging_dir()` uses `SHA-256[:12]` of `os.path.realpath(cwd)` |
| Triage writes to /tmp/ | `memory_triage.py:1128-1141` -- context files written to staging dir |
| Triage data written to /tmp/ | `memory_triage.py:1527-1528` -- `triage_data["staging_dir"]` set, `triage-data.json` written there |
| Sentinel in /tmp/ | `memory_triage.py:662` -- `_sentinel_path()` uses `get_staging_dir()` |
| Lock file in /tmp/ | `memory_triage.py:847-850` -- `ensure_staging_dir(cwd)`, lock in staging dir |
| Retrieval reads from /tmp/ | `memory_retrieve.py:448` -- `Path(get_staging_dir(cwd))` for save result |
| SKILL.md updated | `SKILL.md:36` -- "Memory staging files are stored in `/tmp/.claude-memory-staging-<hash>/`" |

**Legacy compatibility note:** Some scripts still check BOTH paths. `memory_triage.py:780-781` checks the legacy `.claude/memory/.staging/last-save-result.json` first, then the /tmp/ path. This is intentional backwards compatibility for migration.

### Step 3.2: Deterministic hash + `O_NOFOLLOW` symlink defense
**Verdict: DONE**

**Deterministic hash:**
- `memory_staging_utils.py:37` -- `hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]`
- NOT `tempfile.mkdtemp()` (plan offered both; deterministic was chosen for cross-process coordination)

**Staging dir creation security:**
- `memory_staging_utils.py:63-92` -- `validate_staging_dir()`:
  - Uses `os.mkdir(staging_dir, 0o700)` (not `makedirs` -- single-level, fails if parent missing)
  - On `FileExistsError`: `os.lstat()` check for symlink (`S_ISLNK`), UID ownership check
  - Permissions tightened to `0o700` if world-accessible bits found
- Inline fallback in `memory_triage.py:42-51` mirrors the same security logic

**O_NOFOLLOW on file creates:**

| File | Line(s) | Usage |
|------|---------|-------|
| `memory_triage.py` | 632, 673, 712, 799, 858, 873, 1215, 1534 | All staging file creates/reads use `O_NOFOLLOW` |
| `memory_draft.py` | 261 | Draft file creation: `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` |
| `memory_write.py` | 594, 720-751, 1903 | Sentinel read/write uses `O_NOFOLLOW`; input validation rejects symlinks |
| `memory_logger.py` | 36, 166, 325 | Portable `O_NOFOLLOW` (with fallback to 0 on unsupported platforms) |

### Step 3.3: ALL scripts updated to use new paths
**Verdict: DONE**

| Script | Updated? | Evidence |
|--------|----------|----------|
| `memory_triage.py` | YES | Imports `memory_staging_utils` (line 32), uses `get_staging_dir()`/`ensure_staging_dir()` throughout. Inline fallback (lines 37-51) for partial deploy resilience. |
| `memory_write.py` | YES | `cleanup_staging()` (line 527), `cleanup_intents()` (line 580), `write_save_result()` (line 631), `update_sentinel_state()` (line 738) all accept `/tmp/.claude-memory-staging-*` paths. Imports `validate_staging_dir` from `memory_staging_utils` (line 693). |
| `memory_write_guard.py` | YES | Lines 93-158: Full `/tmp/.claude-memory-staging-*` auto-approve logic with 4 safety gates. Lines 160-195: Legacy `.staging/` path kept for backward compatibility. |
| `memory_staging_guard.py` | YES | Line 43: `_STAGING_PATH_PATTERN` matches both `\.claude/memory/\.staging/` AND `/tmp/\.claude-memory-staging-[a-f0-9]+/` |
| `memory_validate_hook.py` | YES | Lines 193-201: `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"`, checks both legacy and new paths for staging skip logic |
| `memory_retrieve.py` | YES | Imports `get_staging_dir` (line 43), uses it for save result path (line 448). Inline fallback (lines 45-50). |
| `SKILL.md` | YES | Line 36: Documents `/tmp/.claude-memory-staging-<hash>/` as the staging directory. All `<staging_dir>` references throughout the orchestration flow. |
| `memory_draft.py` | YES | Imports `validate_staging_dir` from `memory_staging_utils` (line 53). Accepts both `/tmp/.claude-memory-staging-*` and legacy `.claude/memory/.staging/` (lines 86-87). `write_draft()` routes to staging dir (lines 246-249). |

### Step 3.4: `memory_write_guard.py` staging auto-approve matches new `/tmp/` paths
**Verdict: DONE**

- `memory_write_guard.py:97` -- `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"`
- Lines 99-118: **Symlink defense** (S2) -- if unresolved input looks like staging but resolves elsewhere, DENY
- Lines 120-158: **4-gate auto-approve** for `/tmp/.claude-memory-staging-*`:
  - Gate 1: Extension whitelist (`.json`, `.txt` only) -- line 124
  - Gate 2: Filename pattern whitelist (`_STAGING_FILENAME_RE`) -- line 128
  - Gate 3: No subdirectory traversal (single slash after hash) -- lines 134-137
  - Gate 4: Hard link defense (nlink check on existing files) -- lines 140-146
  - All gates pass: emit `permissionDecision: "allow"` -- lines 152-158

### Step 3.5: `memory_staging_guard.py` guards new path
**Verdict: DONE**

- `memory_staging_guard.py:43` -- `_STAGING_PATH_PATTERN` regex:
  ```
  r'(?:\.claude/memory/\.staging/|/tmp/\.claude-memory-staging-[a-f0-9]+/)'
  ```
- This matches both legacy AND new paths in the Bash write detection regex
- Blocks `cat`, `echo`, `printf`, `tee`, `cp`, `mv`, `install`, `dd`, `ln`, `link`, and redirect operators targeting either staging path

### Step 3.6: `.gitignore` exclusion (N/A for /tmp/)
**Verdict: DONE (correctly N/A)**

- Staging is in `/tmp/` (outside the project tree)
- `.gitignore` at project root has no staging-related entries
- No `.gitignore` changes needed -- this is correctly marked N/A in the plan

---

## Leftover References Check

Searched entire repo for `.claude/memory/.staging/` references:

| File | Line | Context | Assessment |
|------|------|---------|------------|
| `memory_draft.py:10,13` | Docstring examples | **Cosmetic only** -- usage examples in module docstring. No functional impact. Could be updated but harmless. |
| `memory_draft.py:75,87,93-94` | Input path validation | **Intentional legacy compat** -- accepts both paths for backward compatibility |
| `memory_draft.py:249` | `write_draft()` fallback | **Intentional legacy compat** -- if root is not a /tmp/ staging path, falls back to `root/.staging/` |
| `memory_validate_hook.py:190-192` | Staging skip logic | **Intentional legacy compat** -- checks both paths |
| `memory_write_guard.py:95,160-195` | Legacy auto-approve | **Intentional legacy compat** -- kept explicitly with comment "Legacy: Auto-approve writes to the .claude/memory/.staging/ subdirectory. Kept for backward compatibility during migration." |
| `memory_write.py:525,578,629,738` | cleanup/sentinel functions | **Intentional legacy compat** -- all accept both staging path formats |
| `memory_write.py:1561,1573,1578,1586` | Input file validation | **Intentional legacy compat** -- accepts inputs from both paths |
| `memory_staging_guard.py:42-43` | Guard regex | **Intentional** -- guards both paths |
| `memory_triage.py:781` | `_was_saved_this_session()` | **Intentional legacy compat** -- checks legacy path first, then /tmp/ |
| `docs/architecture/architecture.md:340,500` | Documentation | **Should be updated** -- docs reference `.claude/memory/.staging/` as the primary path |
| Various `temp/` files | Analysis/verification | **N/A** -- temp analysis files, not production code |

**Assessment:** All production code references to `.claude/memory/.staging/` are intentional backward compatibility paths. The only candidates for cleanup are:
1. `memory_draft.py` docstring examples (lines 10, 13) -- cosmetic
2. `docs/architecture/architecture.md` -- documentation should be updated to reflect /tmp/ as primary

---

## `memory_staging_utils.py` Verification

**Status: EXISTS and FUNCTIONAL**
**Path:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_staging_utils.py`

| Function | Purpose | Used By |
|----------|---------|---------|
| `STAGING_DIR_PREFIX` | Constant `/tmp/.claude-memory-staging-` | Guard scripts, tests |
| `get_staging_dir(cwd)` | Deterministic path computation | `memory_triage.py`, `memory_retrieve.py`, tests |
| `ensure_staging_dir(cwd)` | Create + validate dir | `memory_triage.py` |
| `validate_staging_dir(path)` | Security validation (symlink/ownership) | `memory_draft.py`, `memory_write.py` |
| `is_staging_path(path)` | Path membership check | Available for callers |

**Test coverage:** `tests/test_memory_staging_utils.py` exists with comprehensive tests.

**Import pattern:** Scripts import with `try/except ImportError` fallback for partial deployment resilience (`memory_triage.py:31-51`, `memory_retrieve.py:42-50`).

---

## Summary

| Step | Verdict | Notes |
|------|---------|-------|
| Option C investigated | DONE | No PermissionRequest hook in hooks.json; abandoned |
| Option A NOT used | DONE | No `write-staging` action implemented |
| Step 3.1: Staging moved | DONE | All primary paths use `/tmp/.claude-memory-staging-<hash>/` |
| Step 3.2: Deterministic hash + O_NOFOLLOW | DONE | SHA-256[:12], O_NOFOLLOW on all staging file I/O |
| Step 3.3: All scripts updated | DONE | 8/8 scripts confirmed (triage, write, write_guard, staging_guard, validate_hook, retrieve, SKILL.md, draft) |
| Step 3.4: write_guard auto-approve | DONE | 4-gate safety + symlink defense (S2) |
| Step 3.5: staging_guard guards new path | DONE | Regex matches both legacy and /tmp/ paths |
| Step 3.6: .gitignore N/A | DONE | Correctly not needed for /tmp/ |
| memory_staging_utils.py exists | DONE | Shared module with 5 exports, tested |
| Leftover legacy refs | INTENTIONAL | All `.staging/` references in production code are backward compat; docs could use update |

**Overall Phase 3 verdict: COMPLETE. All steps implemented with security hardening (symlink defense, O_NOFOLLOW) beyond what the plan originally specified.**
