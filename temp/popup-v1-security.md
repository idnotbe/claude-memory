# Eliminate All Popups -- Security & Operational Verification (V-R1b)

**Reviewer**: Claude Opus 4.6 (1M context)
**Date**: 2026-03-22
**Scope**: Phase 3 staging migration from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<hash>/`
**Cross-model validation**: Codex (codereviewer), Gemini 3.1 Pro (codereviewer)

---

## Threat Model Context

This plugin runs as part of Claude Code on a **single developer's workstation**. The primary threat model is:
- A co-located user on a shared system (university server, CI runner) who can predict staging paths and pre-stage symlinks in `/tmp/`
- On a single-user laptop/desktop, the practical risk of most findings is significantly lower

Severity ratings below reflect the **shared-system** threat model. For single-user workstations, most findings drop by one level.

---

## 1. Security Findings

### S1. HIGH -- `ensure_staging_dir()` accepts pre-existing symlinks/attacker-owned directories

**Files**: `memory_staging_utils.py:52`, `memory_triage.py:42` (inline fallback)

**Root cause**: `os.makedirs(staging_dir, mode=0o700, exist_ok=True)` silently succeeds when the target already exists -- even if it is a symlink to an attacker-controlled directory, or a directory owned by a different user with different permissions. The `mode=0o700` argument is only applied when creating new directories; it does not fix permissions on existing ones.

**Attack scenario**:
1. Attacker computes the deterministic hash: `sha256(realpath(victim_project_dir))[:12]`
2. Attacker creates: `ln -s /home/attacker/capture /tmp/.claude-memory-staging-<hash>`
3. Victim runs Claude Code. `ensure_staging_dir()` calls `makedirs(exist_ok=True)` -- succeeds silently
4. `memory_triage.py` writes `triage-data.json`, `context-*.txt` to attacker-controlled directory
5. Attacker reads project context, or modifies `triage-data.json` to inject instructions

**Sticky bit analysis**: `/tmp/` sticky bit prevents *deletion/replacement* of files owned by others, but does NOT prevent *creation* of new symlinks. The attacker creates and owns the symlink, so sticky bit provides no protection.

**O_NOFOLLOW does NOT help**: `O_NOFOLLOW` only prevents following symlinks in the *final path component* (the filename). It will happily traverse a symlinked parent directory. So even though `memory_triage.py` uses `O_NOFOLLOW` for file creation, a symlinked staging *directory* is not caught.

**Recommended fix** (5-line patch in `ensure_staging_dir()`):
```python
def ensure_staging_dir(cwd: str = "") -> str:
    staging_dir = get_staging_dir(cwd)
    try:
        os.mkdir(staging_dir, 0o700)
    except FileExistsError:
        st = os.lstat(staging_dir)
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(f"Staging dir is a symlink (possible attack): {staging_dir}")
        if st.st_uid != os.geteuid():
            raise RuntimeError(f"Staging dir owned by uid {st.st_uid}, expected {os.geteuid()}: {staging_dir}")
        if stat.S_IMODE(st.st_mode) & 0o077:
            # Other users have access -- tighten or reject
            os.chmod(staging_dir, 0o700)
    return staging_dir
```

**All three reviewers** (self, Codex, Gemini) independently rated this HIGH.

---

### S2. MEDIUM -- `write_guard.py` fails open on symlink-compromised staging paths

**File**: `memory_write_guard.py:98`

**Root cause**: The guard resolves the path via `os.path.realpath()` before checking `resolved.startswith(_TMP_STAGING_PREFIX)`. If the staging dir is a symlink to `/etc/`, the resolved path becomes `/etc/somefile.json`, which fails the prefix check. The guard then falls through to `sys.exit(0)` (no output = default behavior = prompt user).

**Impact**: The user sees a prompt asking to write to `/tmp/.claude-memory-staging-<hash>/intent-decision.json` (the unresolved path) and may approve it, not realizing the actual write goes to the symlink target. This is a **deceptive prompt** vector.

**Recommended fix**: When the *unresolved* `file_path` starts with the staging prefix but the *resolved* path does not, explicitly deny:
```python
if file_path.startswith(_TMP_STAGING_PREFIX) and not resolved.startswith(_TMP_STAGING_PREFIX):
    # Symlink detected -- staging dir is compromised
    json.dump({"hookSpecificOutput": {
        "permissionDecision": "deny",
        "permissionDecisionReason": "Staging directory appears to be a symlink. Aborting.",
    }}, sys.stdout)
    sys.exit(0)
```

**Gemini** rated this MEDIUM. **Codex** rated the TOCTOU aspect LOW (because it requires prior compromise via S1). I agree with MEDIUM -- the deceptive prompt aspect is the real concern.

---

### S3. LOW -- `memory_draft.py` uses plain `open()` instead of `O_NOFOLLOW`

**File**: `memory_draft.py:252`

**Root cause**: `write_draft()` uses `with open(draft_path, "w")` for staging file creation. This is inconsistent with `memory_triage.py` which uses `os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)` for all staging writes.

**Impact**: Not independently exploitable -- requires S1 (compromised staging directory) to be leveraged. But once S1 is exploited, draft writes will follow leaf-level symlinks within the staging directory. This is a hardening gap, not a standalone vulnerability.

**Recommended fix**: Replace `open()` with the `os.open()` + `O_NOFOLLOW` pattern already used in `memory_triage.py`:
```python
fd = os.open(draft_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
except Exception:
    os.close(fd)
    raise
```

**Codex** rated this LOW (derivative of S1). Agreed.

---

### S4. LOW -- `cleanup_staging()` missing symlink rejection (inconsistency with `cleanup_intents()`)

**Files**: `memory_write.py:541-553` vs `memory_write.py:589-593`

**Root cause**: `cleanup_staging()` iterates with `Path.glob()` and calls `f.resolve().relative_to(staging_path)` without first checking `f.is_symlink()`. In contrast, `cleanup_intents()` correctly rejects symlinks first. A symlink loop can cause `resolve()` to raise `RuntimeError`, crashing cleanup.

**Impact**: DoS / cleanup bypass. Not arbitrary file deletion (`unlink()` removes the symlink itself, not its target). But failed cleanup could leave sensitive context files in `/tmp/`.

**Recommended fix**: Mirror `cleanup_intents()` pattern -- add `if f.is_symlink(): skipped += 1; continue` before the `resolve()` call.

---

### S5. INFORMATIONAL -- `atomic_write_text()` uses `tempfile.mkstemp()` (no `O_NOFOLLOW`)

**File**: `memory_write.py:472-486`

**Not exploitable**: `mkstemp()` securely creates a new temp file with a random name. The subsequent `os.rename()` replaces a destination symlink atomically rather than following it. This is safe. The real risk is always whether the *directory* is trusted (S1), not the atomic write primitive.

**Codex** and I agree: Informational only.

---

### S6. INFORMATIONAL -- 48-bit hash (12 hex chars) collision resistance

**File**: `memory_staging_utils.py:36`

**Analysis**: Birthday paradox requires ~2^24 = ~16.7 million distinct project paths for 50% collision probability. Second-preimage (attacker targeting a specific hash) requires ~2^48 attempts. Both are far beyond practical concern for local staging directory isolation.

**All reviewers** agree: Informational / not a practical concern.

---

### S7. LOW -- TOCTOU in write_guard.py nlink check

**File**: `memory_write_guard.py:118-124`

**Root cause**: Gate 4 checks `os.stat(resolved).st_nlink` before the Write tool actually opens the file. Between the check and the write, an attacker could swap a normal file for a hard link.

**Impact**: Only exploitable if S1 is already exploited (attacker controls the staging directory). On its own, the current user owns the directory and other users cannot create hard links inside it. The nlink check is defense-in-depth, not a primary gate.

**Codex** rated LOW. Agreed.

---

## 2. Operational Concerns

### O1. LOW -- No cleanup of orphaned `/tmp/` staging directories

**Issue**: Staging directories persist in `/tmp/` indefinitely. `cleanup_staging()` removes files *within* the directory but never removes the directory itself. Over weeks on long-running systems, directories accumulate.

**Context data**:
- Per-session staging: ~6 context files (50KB each max) + triage-data.json + intent/draft files
- Worst case per run: ~300KB + metadata files
- Reboot clears `/tmp/` on most Linux systems

**Risk**: Low on typical developer machines (rebooted regularly). Higher on CI runners or long-lived servers. The accumulated data is project context (potentially sensitive).

**Recommended fix**: Add directory-level cleanup option to `cleanup_staging()` that removes the staging dir itself after all files are cleaned. Or add a `--cleanup-dir` flag that runs `os.rmdir()` (safe -- only removes empty dirs).

---

### O2. INFORMATIONAL -- tmpfs memory pressure

**Issue**: On systems where `/tmp/` is `tmpfs` (RAM-backed), staging files consume RAM. Worst case: 300KB per session.

**Assessment**: 300KB is negligible even on memory-constrained systems. Not a practical concern.

---

### O3. INFORMATIONAL -- Multi-user staging isolation

**Assessment**: The deterministic hash ensures different project paths get different staging directories. Different users with the same project path would get the same hash -- but this is covered by S1 (the directory ownership check fix). With S1 fixed, each user's `ensure_staging_dir()` would reject a directory owned by another user.

---

### O4. INFORMATIONAL -- Reboot clears `/tmp/`

**Issue**: On reboot, `/tmp/` is cleared. Pending (unsaved) staging files are lost.

**Assessment**: Not a real concern. Memory consolidation runs within a single session (seconds). If the machine reboots mid-save, the entire Claude Code session is lost anyway. The sentinel file (`.triage-handled`) is session-scoped and meant to be ephemeral.

---

## 3. Code Review Summary

### Files Reviewed

| File | Verdict | Notes |
|------|---------|-------|
| `memory_staging_utils.py` | **Needs fix** (S1) | `ensure_staging_dir()` must validate existing dirs |
| `memory_write_guard.py` | **Needs fix** (S2) | Add explicit deny for symlink-resolved mismatch |
| `memory_staging_guard.py` | **OK** | Regex correctly covers both old and new paths |
| `memory_triage.py` | **OK** | Uses `O_NOFOLLOW` + atomic writes consistently |
| `memory_write.py` | **Minor fix** (S4) | `cleanup_staging()` needs symlink check |
| `memory_draft.py` | **Minor fix** (S3) | `write_draft()` should use `O_NOFOLLOW` |
| `memory_validate_hook.py` | **OK** | Correctly handles both staging paths |

### Positive Practices

- `memory_triage.py` consistently uses `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` with `0o600` permissions -- this is the gold standard pattern
- Atomic write via tmp + `os.replace()` for `triage-data.json`
- Path containment checks (`resolve()` + `relative_to()`) in cleanup functions
- Hard link defense (nlink check) in write guard and validate hook
- Strict filename regex whitelist in write guard
- Extension whitelist (.json, .txt only) in write guard
- No-subdirectory gate (slash_count check) in write guard

---

## 4. Cross-Model Validation Summary

| Finding | Claude (self) | Codex | Gemini | Consensus |
|---------|--------------|-------|--------|-----------|
| S1: ensure_staging_dir symlink | HIGH | HIGH | HIGH | **HIGH** -- unanimous |
| S2: write_guard deceptive prompt | MEDIUM | (not separately rated) | MEDIUM | **MEDIUM** |
| S3: memory_draft.py open() | LOW | LOW | (not separately rated) | **LOW** |
| S4: cleanup_staging symlink gap | LOW | LOW | (not separately rated) | **LOW** |
| S5: atomic_write_text mkstemp | INFO | INFO | (not separately rated) | **INFO** |
| S6: 48-bit hash | INFO | INFO | (not separately rated) | **INFO** |
| O1: Orphaned dir cleanup | LOW | (not rated) | LOW | **LOW** |

**Agreement level**: Strong convergence on the primary finding (S1). No reviewer found a Critical-severity issue. No significant disagreements on severity ratings.

**Note on cross-model independence**: All three models were given similar framing. The convergence on S1 likely reflects genuine signal (it is a textbook symlink squatting pattern), but the agreement is partially explained by shared training data on `/tmp/` security patterns.

---

## 5. Verdict

### Block/Ship Recommendation

**Ship with S1 and S2 fixes.** S3 and S4 are desirable hardening but not blockers.

| Issue | Severity | Action | Effort |
|-------|----------|--------|--------|
| S1 | HIGH | **Fix before shipping** | ~10 lines in `memory_staging_utils.py` + inline fallback in `memory_triage.py` |
| S2 | MEDIUM | **Fix before shipping** | ~8 lines in `memory_write_guard.py` |
| S3 | LOW | Fix in follow-up | ~6 lines in `memory_draft.py` |
| S4 | LOW | Fix in follow-up | ~2 lines in `memory_write.py` |
| O1 | LOW | Fix in follow-up | ~5 lines in `memory_write.py` |

### Residual Risk After S1+S2 Fixes

With `ensure_staging_dir()` validating ownership and rejecting symlinks, and `write_guard.py` denying symlink-mismatched paths:
- The staging directory is provably owned by the current user
- `O_NOFOLLOW` on file creates prevents leaf-level symlink attacks
- Nlink checks provide defense-in-depth against hard link attacks
- Filename/extension whitelists prevent unexpected file types
- Path containment checks prevent directory traversal

**Residual risk**: LOW. The remaining S3/S4 findings are hardening gaps that are only exploitable if S1 is somehow bypassed.
