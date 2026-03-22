# Verification Round 1 -- Security Review: staging-hardening.md

**Reviewer**: V-R1 Security
**Date**: 2026-03-22
**Verdict**: CONDITIONAL PASS -- 3 required fixes before implementation

---

## 1. I1 Fix Completeness: Triage Fallback (`_staging_dir = ""`)

### 1a. Does `_staging_dir = ""` trigger the inline fallback?

**Partially.** Empty string is falsy in Python, so `if _staging_dir:` guards (proposed in Step 1.2) will skip the file write. However, the plan has a **critical gap**: the code at line 1527-1528 runs BEFORE the guarded block:

```python
triage_data["staging_dir"] = _staging_dir  # line 1527 -- propagates ""
triage_data_path = os.path.join(_staging_dir, "triage-data.json")  # line 1528
```

`os.path.join("", "triage-data.json")` returns `"triage-data.json"` (relative path). If Step 1.2's `if _staging_dir:` guard is placed around the `os.open()` block (lines 1531-1544) as the plan implies, then the write is prevented and `triage_data_path` falls through to `None` at line 1552, triggering inline fallback correctly.

**Verdict**: The inline `<triage_data>` fallback DOES work IF Step 1.2 is implemented correctly. The `triage_data_path = None` assignment at line 1552 fires on exception, but Step 1.2 needs to ALSO set `triage_data_path = None` when `_staging_dir` is empty (before the try block, not relying on exception flow).

### 1b. Downstream propagation of `triage_data["staging_dir"] = ""`

**FINDING [MUST-FIX]**: The `staging_dir` field propagates into the inline `<triage_data>` JSON. SKILL.md consumers (line 67) read this field:

> *"If it lacks staging_dir, compute it from the project path."*

An empty string is truthy as a JSON field (key exists with value `""`), so SKILL.md would receive `staging_dir: ""` and attempt to use it for all subsequent file operations (`cleanup-intents`, `cleanup-staging`, writing intent files, etc.). This causes:
- `memory_write.py --action cleanup-staging --staging-dir ""` -- `Path("").resolve()` returns CWD, which fails the `startswith("/tmp/.claude-memory-staging-")` check. **Safe** (rejected by containment).
- Subagent write targets like `""/intent-decision.json` become CWD-relative. **Potentially unsafe** depending on Write tool guard behavior.

**Required fix**: Step 1.1/1.2 must also set `triage_data["staging_dir"]` to `None` or omit the key entirely when `_staging_dir` is empty. This forces SKILL.md to fall back to computing the staging dir, which will call `ensure_staging_dir()` fresh.

### 1c. Other writes after line 1526 using `_staging_dir`

Only `triage_data["staging_dir"]` (line 1527) and `triage_data_path` (line 1528). Both are covered above. The `context_paths` were already written by `write_context_files()` earlier (line 1509), which has its own independent `ensure_staging_dir()` call with proper empty-string fallback.

### 1d. `write_context_files()` fallback path security

The existing fallback at line 1143 writes to predictable paths `/tmp/.memory-triage-context-{cat_lower}.txt`. The write uses `O_NOFOLLOW` (prevents symlink follow) but **lacks `O_EXCL`**. An attacker can pre-create these files as regular files with permissive permissions. The victim process opens and truncates, writing transcript data that the attacker can read.

**Gemini finding (confirmed)**: Missing `O_EXCL` on fallback path = information disclosure vector.

The action plan's Step 1.3 proposes returning empty dict instead of falling back -- this **eliminates** the vector entirely by not writing context files at all. This is the safer choice. Subagents lose context file input but still have the inline triage data with snippets.

**Verdict**: Step 1.3 is sound. Eliminating the fallback is better than hardening it.

---

## 2. I2 Fix Completeness: macOS `os.path.realpath("/tmp")`

### 2a. Module load time evaluation

`os.path.realpath("/tmp")` evaluated at module load is safe for all practical scenarios:
- On Linux: `/tmp` is always a real directory (not a symlink). Returns `/tmp`.
- On macOS: `/tmp` -> `/private/tmp`. Returns `/private/tmp`. This is correct.
- Container edge case (no /tmp at import time): `os.path.realpath("/tmp")` returns `/tmp` even if the path doesn't exist (realpath resolves what it can). **Safe**.
- The value never changes during process lifetime. Module-level caching is correct.

**Verdict**: No issue.

### 2b. Missing fix: `memory_staging_guard.py` regex

**FINDING [MUST-FIX]**: The action plan lists `memory_staging_guard.py` in Step 4.3 ("Verify staging guard regex still matches new paths") but does NOT include it as a fix target in Phase 2. The regex at line 43:

```python
_STAGING_PATH_PATTERN = r'(?:\.claude/memory/\.staging/|/tmp/\.claude-memory-staging-[a-f0-9]+/)'
```

This is hardcoded with literal `/tmp/`. On macOS after the Phase 2 fix, paths would be `/private/tmp/.claude-memory-staging-*` which does NOT match this regex. The guard silently fails to detect Bash writes to staging.

**Gemini finding (confirmed)**: The regex accidentally works on macOS because the unanchored `[^\s]*` before the pattern can swallow `/private`, but this is extremely brittle and semantically incorrect.

**Required fix**: Add a Phase 2 step for `memory_staging_guard.py` -- either:
1. Import `STAGING_DIR_PREFIX` from `memory_staging_utils` and build the regex dynamically, OR
2. Replace the `/tmp/` literal with a pattern matching any `/tmp/` prefix: `r'(?:/(?:private/)?tmp/|\.claude/memory/)\.claude-memory-staging-[a-f0-9]+/'`

Option 1 is cleaner but adds an import dependency. Option 2 is self-contained but macOS-specific.

---

## 3. I3 Fix Completeness: UID-in-Hash

### 3a. Staging guard regex compatibility

The `memory_staging_guard.py` regex `[a-f0-9]+` matches any hex string regardless of length. Since `sha256(f"{uid}:{path}").hexdigest()[:12]` still produces hex characters, the regex continues to match. **No issue.**

### 3b. `_STAGING_FILENAME_RE` dependency

`_STAGING_FILENAME_RE` in `memory_write_guard.py` (line 23-26) matches file basenames within the staging directory, not the directory path itself. The hash format change does not affect filename matching. **No issue.**

### 3c. Cross-session breakage

Changing the hash formula means existing staging directories become orphaned. The plan acknowledges this (Step 3.8, Decision Log). Since:
- Staging data is ephemeral (per-session)
- `/tmp/` is cleaned by OS (typically on reboot)
- Old dirs have `0o700` permissions (not accessible to other users)
- No migration is needed

**No issue.** This is a correct tradeoff.

### 3d. Fallback function sync

The plan correctly identifies all 3 fallback `get_staging_dir()` locations (Steps 3.4-3.6): `memory_staging_utils.py`, `memory_triage.py:37-41`, `memory_retrieve.py:50`. All need the UID-in-hash update. **Complete.**

---

## 4. Security Issues Introduced by Fixes

### 4a. Write-to-CWD via empty staging_dir (I1) -- HIGH

As detailed in Section 1b. `triage_data["staging_dir"] = ""` propagates to SKILL.md consumers who may attempt CWD-relative file operations. The `memory_write.py` containment checks reject empty-string staging dirs, but the LLM-driven subagent Write tool operations are the concern -- a Write to `""/intent-decision.json` resolves to `intent-decision.json` in CWD.

**Mitigated by**: Step 1.2's `if _staging_dir:` guard prevents the triage-data.json write, AND setting `triage_data["staging_dir"]` to None/omitting it forces SKILL.md to recompute. But this mitigation is NOT explicitly in the plan.

### 4b. Guard bypass on macOS (I2) -- HIGH

As detailed in Section 2b. The staging guard regex is not updated, creating a bypass on macOS where the guard fails to block Bash writes to `/private/tmp/.claude-memory-staging-*/`.

### 4c. No new vectors from I3

The UID-in-hash change does not introduce new attack surface. Orphaned directories are benign.

---

## 5. Cross-Model Review (Gemini 3.1 Pro)

Gemini confirmed three findings:

| Finding | Severity | Gemini Assessment | My Assessment |
|---------|----------|-------------------|---------------|
| I1 write-to-CWD via `os.path.join("", ...)` | HIGH | Confirmed -- "new regression that writes plugin state into CWD" | **Confirmed** but partially mitigated by Step 1.2's guard. Needs explicit `triage_data["staging_dir"]` fix. |
| I2 staging guard regex bypass | CRITICAL | Confirmed -- "guard will silently fail to detect writes" | **Confirmed** -- downgrade to HIGH (guard is defense-in-depth, not primary defense; Write guard is primary) |
| I1 context file fallback missing O_EXCL | HIGH | Confirmed -- "attacker can pre-create file, victim writes to it" | **Confirmed** but moot if Step 1.3 eliminates fallback entirely. Existing code pre-fix has same issue. |
| I3 orphaned dirs | MEDIUM | Confirmed -- "minor storage leak" | **Agreed** -- acceptable, documented in plan |

Gemini additionally recommended `tempfile.mkdtemp()` as fallback for I1 instead of empty string. This is architecturally cleaner but introduces a non-deterministic path that SKILL.md cannot predict. The inline fallback (empty string -> skip file write -> emit inline JSON) is the correct design for this codebase's architecture.

---

## 6. Vibe Check

### Quick Assessment
The plan correctly identifies real security issues and proposes fundamentally sound fixes, but has two gaps that would introduce new vulnerabilities if implemented as-written.

### Pattern Watch
Mild "fix introduces new bug" pattern: the empty-string fallback for I1 is correct in principle (don't use compromised path) but needs more thorough downstream propagation handling than the plan currently specifies.

### Recommendation
**CONDITIONAL PASS** -- implement with the 3 required fixes below.

---

## Required Fixes Before Implementation

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| F1 | HIGH | `triage_data["staging_dir"] = ""` propagates to SKILL.md consumers | Step 1.2 must also set `triage_data["staging_dir"] = None` (or omit key) when `_staging_dir` is empty. Additionally, set `triage_data_path = None` before the try block when staging_dir is empty, not just on exception. |
| F2 | HIGH | `memory_staging_guard.py` regex not updated for resolved `/tmp/` prefix | Add Phase 2 step: update `_STAGING_PATH_PATTERN` to use resolved prefix or a broader pattern covering `/private/tmp/` |
| F3 | LOW | Existing `write_context_files()` fallback lacks `O_EXCL` (pre-existing, not introduced) | Step 1.3 eliminates this by returning empty dict. Verify Step 1.3 is implemented before closing. |

## Accepted Items (No Action Needed)

- I2 `os.path.realpath("/tmp")` at module load: safe on all platforms
- I3 UID-in-hash: regex compatible, no cross-session breakage
- I3 orphaned directories: acceptable tradeoff, documented
- Phase ordering: no dangerous partial-application windows (each phase is independently safe)
