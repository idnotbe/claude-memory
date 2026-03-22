# Verification Round 1: Correctness Review — staging-hardening.md

**Reviewer**: V-R1 (Correctness)
**Date**: 2026-03-22
**Verdict**: PASS WITH CORRECTIONS — Plan is structurally sound but has line-number inaccuracies and 3 completeness gaps.

---

## 1. Step Accuracy: Spot-Check Results

### Check 1: memory_triage.py:1523-1526 (triage fallback)

**Plan claims** (Step 1.1): Lines 1523-1526 have the fallback pattern where `get_staging_dir(cwd)` is called after `ensure_staging_dir()` fails.

**Actual code** (lines 1523-1526):
```python
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = get_staging_dir(cwd)
```

**Verdict**: CORRECT. Lines match exactly. The bug is real — the fallback returns the same path that was just rejected.

### Check 2: memory_staging_utils.py:20 (STAGING_DIR_PREFIX)

**Plan claims** (Step 2.1): Line 20 has `STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"` hardcoded.

**Actual code** (line 20):
```python
STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"
```

**Verdict**: CORRECT. Line number and content match exactly.

### Check 3: memory_write.py lines 542, 594, 644, 750 (startswith pattern)

**Plan claims** (Step 2.2): Lines 542, 594, 644, 750 all have `startswith("/tmp/.claude-memory-staging-")`.

**Actual code**:
- Line 542: This is a **comment** (`path (or legacy memory/.staging). Individual files are checked to be within`). The actual `startswith` is at **line 551**.
- Line 594: This is a **comment** (`the resolved staging directory before deletion.`). The actual `startswith` is at **line 603**.
- Line 644: This is a **docstring** (`Validates schema (allowed keys, type enforcement, length caps) and`). The actual `startswith` is at **line 653**.
- Line 750: This is a **return statement** (`"status": "error",`). The actual `startswith` is at **line 759**.

**Verdict**: INACCURATE. All four line numbers are off by approximately 9 lines. The correct lines are **551, 603, 653, 759**.

### Check 3b: memory_write.py lines 1588, 1590

**Plan claims** (Step 2.2): Lines 1588 and 1590 have `/tmp/` prefix checks.

**Actual code**:
- Line 1588: Inside a **print f-string** (`f"SECURITY_ERROR\npath: {input_path}\n"`). This is error message text, not a `startswith` check.
- Line 1590: Inside a **print f-string** (`f"fix: Input path must not contain '..' components."`). Also error message text.
- The actual `startswith` checks are at **lines 1597** (`resolved.startswith("/tmp/.claude-memory-staging-")`) and **1599** (`resolved.startswith("/tmp/")`).

**Verdict**: INACCURATE. Correct lines are **1597 and 1599**.

### Check 4: memory_write_guard.py line references

**Plan claims** (Step 2.4): Line 97 has `_TMP_STAGING_PREFIX`, line 85 has `/tmp/` check.

**Actual code**:
- Line 97: `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"` — CORRECT
- Line 85: `if resolved.startswith("/tmp/"):` — CORRECT

**Verdict**: CORRECT.

### Check 5: memory_validate_hook.py line 193

**Plan claims** (Step 2.5): Line 193 has `_TMP_STAGING_PREFIX`.

**Actual code** (line 193): `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"`

**Verdict**: CORRECT.

### Check 6: memory_judge.py line 120

**Plan claims** (Step 2.6): Line 120 has `/tmp/` check.

**Actual code** (line 120): `if not (resolved.startswith("/tmp/") or resolved.startswith(home + "/")):`

**Verdict**: CORRECT.

### Check 7: memory_triage.py lines 41, 1460

**Plan claims**: Line 41 has fallback `get_staging_dir` with hardcoded `/tmp/`, line 1460 has `/tmp/` check.

**Actual code**:
- Line 41: `return f"/tmp/.claude-memory-staging-{_h}"` — CORRECT
- Line 1460: `if not (resolved.startswith("/tmp/") or resolved.startswith(home + "/")):` — CORRECT

**Verdict**: CORRECT.

### Check 8: memory_retrieve.py line 50

**Plan claims**: Line 50 has fallback `get_staging_dir` with hardcoded `/tmp/`.

**Actual code** (line 50): `return f"/tmp/.claude-memory-staging-{_h}"` — CORRECT

**Verdict**: CORRECT.

### Check 9: memory_triage.py write_context_files (lines 1130-1133)

**Plan claims** (Step 1.3): Lines 1130-1133 should return empty dict on staging dir failure instead of falling to predictable `/tmp/` filenames.

**Actual code** (lines 1130-1133):
```python
try:
    staging_dir = ensure_staging_dir(cwd or "")
except (OSError, RuntimeError):
    staging_dir = ""  # Fall back to per-file /tmp/ paths
```

**Verdict**: PARTIALLY ACCURATE. The code already sets `staging_dir = ""` on failure, but when empty it falls through to line 1143: `path = f"/tmp/.memory-triage-context-{cat_lower}.txt"`. So the plan's description of the issue is correct (predictable filenames), but the fix description ("return empty dict") is imprecise — the function continues and writes to predictable paths. The fix should skip writing context files entirely when staging fails, not just "return empty dict."

### Check 10: memory_triage.py fallback ensure_staging_dir (lines 42-54)

**Plan claims** (Step 1.4): Lines 42-54 have a fallback `ensure_staging_dir` missing `S_ISDIR` check.

**Actual code** (lines 42-54): The inline fallback `ensure_staging_dir` checks `S_ISLNK`, `st_uid`, and permissions, but does NOT check `S_ISDIR`.

**Verdict**: CORRECT. The S_ISDIR gap is real.

---

## 2. Completeness: Coverage of All 14 Locations

The research (`temp/research-macos.md`) identifies 14 Category A locations that WILL FAIL on macOS.

| Research # | File:Line | Plan Step | Covered? |
|-----------|-----------|-----------|----------|
| 1 | memory_write.py:542 (actual 551) | Step 2.2 | Yes (line # wrong) |
| 2 | memory_write.py:594 (actual 603) | Step 2.2 | Yes (line # wrong) |
| 3 | memory_write.py:644 (actual 653) | Step 2.2 | Yes (line # wrong) |
| 4 | memory_write.py:750 (actual 759) | Step 2.2 | Yes (line # wrong) |
| 5 | memory_write.py:1588 (actual 1597) | Step 2.2 | Yes (line # wrong) |
| 6 | memory_write.py:1590 (actual 1599) | Step 2.2 | Yes (line # wrong) |
| 7 | memory_draft.py:86 | Step 2.3 | Yes |
| 8 | memory_draft.py:89 | Step 2.3 | Yes |
| 9 | memory_write_guard.py:85 | Step 2.4 | Yes |
| 10 | memory_write_guard.py:103 | Step 2.4 | Yes (auto-fixed by constant) |
| 11 | memory_write_guard.py:120 | Step 2.4 | Yes (auto-fixed by constant) |
| 12 | memory_validate_hook.py:201 (plan says 193) | Step 2.5 | Yes (line # slightly off — 193 is the constant def, 201 is the usage) |
| 13 | memory_judge.py:120 | Step 2.6 | Yes |
| 14 | memory_triage.py:1460 | Step 2.7 | Yes |

**All 14 Category A locations are covered.** Line numbers for memory_write.py are consistently ~9 lines off.

### Category B (unresolved paths — no fix needed): Verified correct. The plan does not needlessly touch these.

### Category C (fallback inline functions): Both covered in Steps 2.7 and 2.8.

### Fallback `get_staging_dir()` functions in Phase 3:

The plan captures both fallback locations:
- memory_triage.py:37-41 (Step 3.5)
- memory_retrieve.py:50 (Step 3.6)

**No missing callsites detected.**

### MISSING from Phase 2: `memory_staging_guard.py` regex

The research Category B item 4 notes `memory_staging_guard.py:43` has a regex pattern `/tmp/\.claude-memory-staging-` that matches raw bash text. The plan only mentions "verify" this in Phase 4 Step 4.3, but does NOT include an active fix step. On macOS, if a command spells out `/private/tmp/...` (e.g., after path expansion), the guard would miss it. This should be escalated to a Phase 2 step or explicitly documented as acceptable risk.

### MISSING consideration: `memory_draft.py:246` raw-input boundary

The research Category B item 1 notes `memory_draft.py:246` checks `root.startswith("/tmp/.claude-memory-staging-")` against a raw (unresolved) argument. If Phase 2 changes `STAGING_DIR_PREFIX` to resolved form but callers still pass unresolved `/tmp/...`, this check would break on macOS. The plan does not address this boundary. Fix: normalize `root` with `realpath()` before the check, or accept both spellings.

---

## 3. Phase Ordering Assessment

**Plan ordering**: Phase 1 (triage fallback security fix) -> Phase 2 (macOS cross-platform) -> Phase 3 (S_ISDIR + UID)

**Assessment**: The ordering is defensible. Phase 1 is a security fix for a real attack vector (symlink squatting causes fallback to compromised path). Phase 2 is a correctness fix that is CRITICAL severity but only affects macOS users. Phase 3 is hardening.

**However**, if these ship as separate commits/PRs, Phase 2 should arguably come first because:
- I2 is marked CRITICAL vs I1's HIGH
- I2 affects all macOS users (100% breakage), while I1 requires an active attacker
- Phase 1 changes (fallback behavior) are somewhat dependent on the staging infrastructure working correctly on all platforms

**If shipped as a single branch**, the ordering is fine — all phases land together.

**Recommendation**: Add a note that these phases should land in a single branch/PR. If split, reorder to Phase 2 first.

---

## 4. README Compliance

Checked against `/home/idnotbe/projects/claude-memory/action-plans/README.md`:

| Requirement | Status |
|------------|--------|
| YAML frontmatter present | PASS — has `status: not-started` and `progress: "..."` |
| Valid status value | PASS — `not-started` is valid |
| Ordered phases | PASS — Phase 1-5 |
| Checkmark format `[ ]`/`[v]`/`[/]` | PASS — all steps use `[ ]` (not started) |
| Phase structure | PASS — clear phase headers with step lists |

**Verdict**: Fully compliant with README conventions.

---

## 5. External Review (Codex clink)

Codex independently confirmed:

**Agreements with this review:**
- Triage fallback bug at 1523-1526 is real and fix is directionally correct
- `os.path.realpath("/tmp")` is the right choice over `tempfile.gettempdir()`
- S_ISDIR hardening is correct
- UID-in-hash is pragmatic

**Additional findings from Codex:**
1. **HIGH**: `memory_staging_guard.py` regex is incomplete — plan only "verifies" it. Must actively fix to match both `/tmp/` and resolved prefix on macOS.
2. **MEDIUM**: `memory_draft.py:246` raw-input boundary — if STAGING_DIR_PREFIX becomes resolved, raw `/tmp/...` inputs will be misclassified on macOS.
3. **MEDIUM**: `_staging_dir = ""` risk — if serialized as `triage_data["staging_dir"] = ""`, downstream SKILL.md may treat empty string differently from absent key. Must either omit the key entirely or set to `None`.
4. **MEDIUM**: UID-in-hash will break more tests than the plan lists — several tests manually compute the old hash formula. Need to centralize through `get_staging_dir()`.

---

## 6. Vibe Check

**Quick Assessment**: Plan is on track with minor corrections needed. No pattern traps or scope creep detected.

**Pattern Watch**: None. The plan is appropriately scoped, avoids feature creep, and makes sound architectural decisions (realpath over gettempdir, local constants over risky imports, incremental UID fix over XDG migration).

**Recommendation**: Proceed after applying corrections below.

---

## Summary of Required Corrections

### MUST FIX (accuracy)

1. **Line numbers in Step 2.2**: memory_write.py lines 542/594/644/750/1588/1590 should be 551/603/653/759/1597/1599. All are ~9 lines off.

2. **Step 1.1 empty-string serialization**: Plan says `_staging_dir = ""` but does not address that line 1527 then does `triage_data["staging_dir"] = _staging_dir` which serializes an empty string. Must either omit `staging_dir` key when empty, or document that downstream handles empty string correctly.

3. **Step 1.3 description imprecision**: "Return empty dict on staging dir failure" is misleading. The actual fix needed is: when `staging_dir` is empty, skip writing individual context files to predictable `/tmp/.memory-triage-context-*.txt` paths (line 1143). The function should either skip the write loop or truly return early with empty dict.

### SHOULD FIX (completeness)

4. **Add Phase 2 step for `memory_staging_guard.py` regex**: The regex at line 43 only matches `/tmp/`. On macOS, resolved-path commands would bypass it. Add an explicit step (not just Phase 4 "verify") to make the regex match both `/tmp/` and `/private/tmp/` (or dynamically build the pattern).

5. **Add Phase 2 step for `memory_draft.py:246` raw-input boundary**: This `root.startswith(...)` check compares against raw input. If callers pass `/tmp/...` on macOS but prefix is now `/private/tmp/...`, this breaks. Add `realpath(root)` normalization or dual-prefix acceptance.

6. **Add note about test hash migration**: UID-in-hash (Phase 3) will break tests that manually compute staging paths. Add a step to audit and fix test helpers.

### NICE TO HAVE (ordering)

7. **Add note about single-branch landing**: If phases are split into separate PRs, recommend reordering Phase 2 before Phase 1 (CRITICAL > HIGH). If single branch, current ordering is fine — add a note.
