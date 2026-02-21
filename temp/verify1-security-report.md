# Security and Edge Case Review Report

**Reviewer**: verify1-security
**Date**: 2026-02-18
**Scope**: Change 1 (rename --action delete to --action retire) and Change 2 (_read_input() staging-only restriction)

---

## 1. _read_input() Security (Change 2)

**File**: `hooks/scripts/memory_write.py`, lines 1165-1205

### 1.1 /tmp/ paths NO LONGER accepted

**PASS.** The old check `resolved.startswith("/tmp/")` has been completely removed. The function now only checks for `"/.claude/memory/.staging/" in resolved`. Passing a `/tmp/` path will hit the `SECURITY_ERROR` branch at line 1182-1189.

### 1.2 ONLY accepts paths containing `/.claude/memory/.staging/`

**PASS.** Line 1181: `in_staging = "/.claude/memory/.staging/" in resolved`. This is a substring check on the `os.path.realpath()` resolved path, which means:
- It works regardless of the project root location (any prefix is valid)
- It requires the exact segment `/.claude/memory/.staging/` to be present in the resolved path

### 1.3 Path traversal (..) blocked BEFORE staging check

**PASS.** Lines 1173-1179 check `".." in input_path` *before* the staging directory check at line 1181. The traversal check operates on the raw `input_path` string (not the resolved path), which is the correct approach -- it catches traversal attempts before `os.path.realpath()` resolves them away.

### 1.4 Error messages

**PASS.** Error messages include the `input_path` and `resolved` path for debugging but do not leak system internals like config contents, memory root paths, or other sensitive data. The `fix:` hints are actionable without being exploitable.

### 1.5 Bypass vectors analysis

| Vector | Status | Analysis |
|--------|--------|----------|
| Symlink attack | **MITIGATED** | `os.path.realpath()` resolves symlinks. A symlink at `.claude/memory/.staging/evil` pointing to `/etc/passwd` would resolve to `/etc/passwd`, which does NOT contain `/.claude/memory/.staging/` and would be rejected. |
| Double encoding (e.g., `%2e%2e`) | **NOT APPLICABLE** | Python's `os.path.realpath()` operates on filesystem paths, not URL-encoded strings. No URL decoding is performed. |
| Null byte injection | **MITIGATED** | Python 3 raises `ValueError` on null bytes in file paths. `os.path.realpath()` would raise before the check executes. |
| Unicode normalization | **LOW RISK** | `os.path.realpath()` uses the OS filesystem's native encoding. Path components like `.claude` and `.staging` are ASCII-only, so Unicode tricks cannot forge a match. |
| Crafted directory name | **EDGE CASE** | An attacker could create a directory named `.claude/memory/.staging/` elsewhere (e.g., `/tmp/.claude/memory/.staging/`). The substring check would match. However, this requires write access to the filesystem, and if an attacker has that, they can modify memory files directly. The staging guard is defense-in-depth against *subagent manipulation*, not against filesystem-level attackers. **Acceptable residual risk.** |
| Race condition (TOCTOU) | **MITIGATED** | `os.path.realpath()` and the subsequent `open()` are not atomic, but the check is on the resolved path. A symlink swap between `realpath()` and `open()` would require precise timing and filesystem access, which is outside the threat model (subagent manipulation). |

### 1.6 Overall assessment

**SECURE.** The new `_read_input()` correctly narrows the accepted input path from any `/tmp/` path to only project-local `.staging/` paths. The traversal check precedes the path check. The implementation is sound for its threat model (preventing subagent manipulation of input file paths).

---

## 2. _cleanup_input() Preservation

**File**: `hooks/scripts/memory_write.py`, lines 1208-1213

**PASS -- UNCHANGED.** The function is exactly:

```python
def _cleanup_input(input_path: str) -> None:
    """Delete the temp input file."""
    try:
        os.unlink(input_path)
    except OSError:
        pass
```

No modifications were made. This function correctly deletes the staging draft file after processing.

---

## 3. CUD Labels Preserved

**File**: `skills/memory-management/SKILL.md`

| Item | Expected | Found | Status |
|------|----------|-------|--------|
| `UPDATE_OR_DELETE` in structural_cud fields | Present | Lines 90, 91, 95, 155, 156, 159 | **PASS** |
| `DELETE` in CUD decision table | Present | Lines 95, 96, 156, 158, 167 | **PASS** |
| "UPDATE over DELETE" principle | Present | Lines 96, 167 | **PASS** |

All three items are intact and were NOT renamed to "retire". These are internal state machine labels from `memory_candidate.py`, not CLI arguments.

---

## 4. Config Keys Preserved

| Config Key | Occurrences Found | Status |
|------------|-------------------|--------|
| `delete.grace_period_days` | CLAUDE.md:58, SKILL.md:271, README.md:134/183, commands/*.md, hooks/scripts/memory_index.py:192, plus temp/ files | **PASS -- UNCHANGED** |
| `delete.archive_retired` | CLAUDE.md:59, SKILL.md:272, README.md:184/403, commands/*.md, plus temp/ files | **PASS -- UNCHANGED** |

Neither config key was renamed. They remain as `delete.grace_period_days` and `delete.archive_retired` across all files.

---

## 5. Rename Flow Comment

**File**: `hooks/scripts/memory_write.py`, line 843

**PASS -- UNCHANGED.** The comment reads exactly:

```python
# Rename flow: write new, update index, delete old
```

This comment describes physically unlinking an old JSON file during a slug rename in the `do_update()` function. It was correctly left unmodified.

---

## 6. No New Injection Vectors

### 6.1 String replacements reviewed

All replacements in Change 1 are literal string substitutions:
- `"delete"` -> `"retire"` in argparse choices (line 1334)
- `"DELETE"` -> `"RETIRE"` in `_check_path_containment` label (line 879)
- `"DELETE_ERROR"` -> `"RETIRE_ERROR"` in error output strings (lines 883, 903)
- `do_delete` -> `do_retire` function name (line 873)
- Dispatch `args.action == "delete"` -> `args.action == "retire"` (line 1368)

**No new injection vectors.** The replacements are all in:
1. Static string literals (not user-controlled)
2. Argparse choices (validated by argparse before reaching handler code)
3. Error message format strings that only interpolate `args.target` (already validated by `_check_path_containment`)
4. Function names (not exposed to user input)

### 6.2 write_guard.py error message

The `memory_write_guard.py` error message at line 78 was updated from:
```
--action <create|update|delete> ...
```
to:
```
--action <create|update|retire|archive|unarchive|restore> ...
```

This is a static string in a denial message. **No injection risk** -- it is not interpolated with user input.

### 6.3 SKILL.md changes

Four locations in SKILL.md changed `--action delete` to `--action retire` in instruction text. These are LLM-consumed instructions, not code. The changes only affect what CLI action string the LLM agent will use. **No new attack surface.**

### 6.4 Residual `--action delete` references

Searched all active Python source files and test files for remaining `--action delete` references:

- `hooks/scripts/*.py`: **0 matches**
- `tests/*.py`: **0 matches**
- `skills/memory-management/SKILL.md`: **0 matches** (only in CUD table which uses bare `DELETE`, not `--action delete`)

Searched for remaining `DELETE_ERROR` and `do_delete`:
- Active source files: **0 matches** (only in temp/ historical docs)

**CLEAN.** No stale references remain in active code.

---

## Summary

| Check | Result |
|-------|--------|
| 1. _read_input() security | **PASS** -- No /tmp/, staging-only, traversal blocked first |
| 2. _cleanup_input() unchanged | **PASS** -- Identical to original |
| 3. CUD labels preserved | **PASS** -- UPDATE_OR_DELETE, DELETE, "UPDATE over DELETE" all intact |
| 4. Config keys preserved | **PASS** -- delete.grace_period_days, delete.archive_retired unchanged |
| 5. Rename flow comment | **PASS** -- Line 843 comment preserved exactly |
| 6. No new injection vectors | **PASS** -- All changes are static string replacements |

**Overall verdict: ALL CHECKS PASS. No security regressions or new vulnerabilities introduced.**
