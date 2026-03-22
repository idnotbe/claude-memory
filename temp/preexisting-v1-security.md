# Security Review: Pre-existing Bug Fixes (Symlink Hijack + Legacy Path Validation)

**Reviewer**: Claude Opus 4.6 + Gemini clink
**Date**: 2026-03-22
**Verdict**: PASS -- No Critical or High vulnerabilities. Two Low findings noted.

---

## Bug 1: Symlink Hijack Fix (`memory_staging_utils.py`)

### `_validate_existing_staging()` — Correctness

| Check | Verdict | Notes |
|-------|---------|-------|
| Symlink detection via `lstat` | CORRECT | `os.lstat()` does not follow symlinks; `S_ISLNK` correctly detects symlink st_mode |
| Ownership check (`st_uid != geteuid`) | CORRECT | Root-owned dirs correctly rejected (root uid=0 != user euid). Bind mounts require `CAP_SYS_ADMIN`; FUSE mounts isolated by default kernel policy |
| S_ISDIR check | CORRECT | New addition -- regular files at staging path now rejected (previously silently accepted) |
| Permission tightening | CORRECT | `0o077` mask detects group/other bits; `chmod(0o700)` fixes them |

### TOCTOU between lstat and chmod — **Info**

The window between `lstat` (line 75) and `chmod` (line 94) is practically unexploitable:

1. **POSIX `chmod` requires caller UID == file owner UID** (or root). If an attacker replaces the dir with a symlink in the window, `chmod` either (a) follows it to a file the attacker owns -- but then the attacker gains nothing since the file becomes 0o700 (stricter), or (b) targets a file owned by a different user -- `EPERM`.
2. `/tmp/` has sticky bit -- attacker cannot delete/replace another user's directory.
3. Legacy paths are in the user's workspace -- attacker needs write access to the project.

**Recommendation (hardening, not required):** `os.chmod(staging_dir, 0o700, follow_symlinks=False)` would structurally eliminate the window (Python 3.3+).

### Parent directory symlink (`os.makedirs`) — **Low**

`os.makedirs(parent, mode=0o700, exist_ok=True)` at line 122 follows symlinks in intermediate components. If an attacker pre-creates `.claude` as a symlink to `/tmp/attacker_dir`, `makedirs` creates `memory/` inside the attacker's directory.

**Impact**: The final `.staging` is still created atomically via `os.mkdir` and validated via `_validate_existing_staging` (ownership check passes since victim created it). The attacker cannot read files inside `.staging` (0o700, owned by victim). Worst case: denial of service (attacker deletes the parent they control).

**Accepted risk**: Legacy paths are in user-controlled workspace directories, not shared /tmp/. Pre-creating a `.claude` symlink requires write access to the project root, which implies the attacker already has significant access.

### umask interference with `os.mkdir` — Safe

`os.mkdir(staging_dir, 0o700)` applies `mode & ~umask`. Since umask can only *remove* bits, the result is always 0o700 or tighter (e.g., 0o600 with umask 0o077). No risk.

### RuntimeError propagation — Correct

`ensure_staging_dir()` calls `validate_staging_dir()` which raises `RuntimeError`. Callers (memory_triage.py, SKILL.md orchestration) catch `OSError`/`RuntimeError` and fail-open by design. Test `test_ensure_staging_dir_propagates_runtime_error` confirms propagation.

---

## Bug 2: Legacy Path Validation (`memory_write.py`)

### `_is_valid_legacy_staging()` — Correctness

| Check | Verdict | Notes |
|-------|---------|-------|
| Requires `.claude` ancestry | CORRECT | Iterates parts looking for exact `.claude -> memory -> .staging` sequence |
| Path traversal defense | CORRECT | All 5 call sites resolve paths via `Path.resolve()` or `os.path.realpath()` BEFORE calling the validator. Traversal components (`..,` symlinks) are eliminated before validation |
| Terminal constraint (`allow_child=False`) | CORRECT | `i + 2 == len(parts) - 1` ensures `.staging` is the last component in directory mode |
| `allow_child=True` scope | CORRECT | Used only in `_read_input()` (line 1598). Cannot escape staging because resolve happens first: `../.staging/../../etc/passwd` resolves to `/etc/passwd` which lacks the `.claude/memory/.staging` sequence |

### Multiple `.claude` components — **Info**

Path `/project/.claude/evil/.claude/memory/.staging` matches on the first `.claude` occurrence, but `i+1` would be `evil`, not `memory`, so the first match fails. The loop continues and finds the second `.claude`. This is structurally harmless -- the path does contain a legitimate `.claude/memory/.staging` sequence.

### Call site verification (all 5 updated)

| # | Function | Line | Resolution method | Status |
|---|----------|------|-------------------|--------|
| 1 | `cleanup_staging()` | 552 | `Path(staging_dir).resolve()` | OK |
| 2 | `cleanup_intents()` | 604 | `Path(staging_dir).resolve()` | OK |
| 3 | `write_save_result()` | 654 | `Path(staging_dir).resolve()` | OK |
| 4 | `update_sentinel_state()` | 760 | `Path(staging_dir).resolve()` | OK |
| 5 | `_read_input()` | 1598 | `os.path.realpath()` (line 1585) | OK |

---

## Cross-Cutting Analysis

### Other staging path checks in the codebase

| File | Line | Pattern | Vulnerable? | Severity |
|------|------|---------|-------------|----------|
| `memory_draft.py` | 87 | `"/.claude/memory/.staging/" in resolved` | Partially (see below) | **Low** |
| `memory_validate_hook.py` | 192-201 | `staging_marker in normalized` (marker = `/.claude/memory/.staging/`) | Mitigated | Info |
| `memory_write_guard.py` | 163-165 | `_stg_segment` in `normalized` (segment = `/.claude/memory/.staging/`) | Mitigated | Info |
| `memory_staging_guard.py` | 43 | Regex: `\.claude/memory/\.staging/` | Mitigated | Info |

**`memory_draft.py` (Low)**: Line 87 uses the old substring pattern `"/.claude/memory/.staging/" in resolved`. This accepts paths like `/tmp/evil/.claude/memory/.staging/file.json`. However, this is mitigated by two factors:
1. Line 89 (`in_tmp = resolved.startswith("/tmp/")`) already accepts ANY `/tmp/` path, so the legacy staging check is only relevant for non-/tmp/ paths.
2. `memory_draft.py` reads partial LLM-written input, so input paths are under plugin control, not user-supplied.
3. On Windows, `os.path.realpath()` returns backslashes, so the forward-slash substring match would silently fail (cross-platform bug, not security).

**Recommendation**: Update `memory_draft.py` line 87 to use `_is_valid_legacy_staging` or an equivalent parts-based check for consistency. This is a cleanup item, not a security requirement.

**`memory_validate_hook.py` (Info)**: The staging marker check (`/.claude/memory/.staging/` in normalized) is used for **skipping validation** (sys.exit(0)), not for granting access. A false positive means a write bypasses PostToolUse quarantine -- but PostToolUse is already detection-only and cannot prevent writes. The `is_memory_file()` gate (line 186) further constrains which paths reach this check.

**`memory_write_guard.py` (Info)**: Uses the same substring pattern but has 4 additional gates (extension whitelist, filename pattern whitelist, file existence check, hardlink defense) that constrain what gets auto-approved. A crafted path would need to also have a whitelisted filename pattern like `intent-*.json`.

### Do the two fixes interact correctly?

Yes. Bug 1 (staging_utils) handles filesystem-level defense (symlink, ownership, permissions) for directory creation. Bug 2 (memory_write) handles path validation for operations that read/write within the staging directory. They operate at different layers and do not conflict.

### Worktree copies

The old vulnerable `parts[-1] == ".staging" and parts[-2] == "memory"` pattern exists in `.claude/worktrees/agent-*/hooks/scripts/memory_write.py` (temporary agent branches). These are transient and will be cleaned up when worktrees are deleted. Not a concern for the main codebase.

---

## Test Coverage Assessment

### Bug 1 tests (`test_memory_staging_utils.py`)

- 5 new tests in `TestValidateStagingDirLegacyPath` (symlink, permissions, wrong owner, parent creation, idempotent)
- 1 updated test (`test_regular_file_at_path_raises_runtime_error`)
- Existing `/tmp/` path tests provide baseline coverage
- **Gap**: No test for parent directory symlink attack (`.claude` is a symlink). Acceptable -- this is an accepted risk per analysis above.

### Bug 2 tests (`test_memory_write.py`)

- 14 tests in `TestLegacyStagingValidation` covering:
  - Valid paths (standard, nested, root-level)
  - Rejected paths (evil /tmp/, /etc/, wrong order, missing components, partial name)
  - Terminal constraint enforcement
  - `allow_child=True` mode (file accepted, dir accepted, evil rejected)
  - `/tmp/` staging returns False (delegated to separate check)
- **Good**: Tests cover the exact attack patterns from the bug report.

---

## Summary

| Finding | Severity | Action |
|---------|----------|--------|
| TOCTOU between lstat and chmod | Info | Optional: add `follow_symlinks=False` |
| Parent dir symlink in legacy `os.makedirs` | Low | Accepted risk (workspace-scoped) |
| `memory_draft.py` old substring pattern | Low | Recommend updating to parts-based check for consistency |
| Multiple `.claude` in path | Info | Structurally harmless |
| `allow_child=True` scope | Info | Safe due to pre-resolution |
| Bind mount / FUSE bypass of st_uid | Info | Requires elevated privileges |
| umask vs os.mkdir | Info | Cannot weaken 0o700 |
| validate_hook/write_guard substring patterns | Info | Mitigated by layered gates |

**Overall**: Both fixes are sound. The core security properties (symlink rejection, ownership verification, path ancestry validation) are correctly implemented. The `Path.resolve()` / `os.path.realpath()` before validation pattern is textbook defense-in-depth. No bypasses found that would allow privilege escalation or data exfiltration.
