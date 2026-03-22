# Verification Round 2 — Final Plan Review

**Plan**: `/home/idnotbe/projects/claude-memory/action-plans/staging-hardening.md`
**Reviewer**: Opus 4.6 (R2 final) + Codex 5.3 (cross-model)
**Date**: 2026-03-22

---

## 1. R1 Correction Verification

| R1 Correction | Status | Evidence |
|---------------|--------|----------|
| Step 1.1: `triage_data["staging_dir"]` = `None` (not empty string) | PASS | Line 22: "set `triage_data["staging_dir"]` to `None` (not `""`) when empty" |
| Step 1.2: `triage_data_path = None` BEFORE try block | PASS | Line 23: "Set `triage_data_path = None` BEFORE the try block (not relying on exception flow)" |
| Step 1.3: return `{}` immediately in `write_context_files()` | PASS | Line 24: "return `{}` immediately on staging dir failure (skip all context file writes)" |
| Step 2.2: corrected line numbers (551, 603, 653, 759, 1597, 1599) | PASS | Verified via grep: `memory_write.py` has `startswith("/tmp/")` at exactly those 6 lines |
| Step 2.3: 3 locations in `memory_draft.py` (not 2) | PASS (step) / FAIL (summary) | Step 2.3 correctly says "3 locations (lines 86, 89, 246)". However, Files Changed table (line 88) still says "2 resolved `/tmp/` prefix replacements" — inconsistency not caught by R1 |
| `memory_staging_guard.py` has its own step for regex fix | PASS | Step 2.9 is a dedicated step for the regex pattern |
| grep verification step exists in Phase 2 | PASS | Step 2.13 adds `grep -rn 'startswith("/tmp/' hooks/scripts/memory_*.py` |

**R1 Corrections Summary**: 6/7 PASS. One internal inconsistency remains — the Files Changed table says "2" for `memory_draft.py` but Step 2.3 correctly says "3".

---

## 2. README Compliance

| Requirement | Status | Notes |
|-------------|--------|-------|
| YAML frontmatter present | PASS | Lines 1-4: `status: not-started`, `progress: "Not started..."` |
| Valid status value | PASS | `not-started` is one of the four allowed values |
| Progress is free text string | PASS | Properly quoted YAML string |
| Checkmark format `[ ]`/`[v]`/`[/]` | PASS | All steps use `[ ]` (not-started), consistent with README spec |
| Ordered phases present | PASS | Phase 1 through Phase 5, logically sequenced |
| Phase headings with `##` | PASS | Proper markdown structure |

**README Compliance**: PASS — fully compliant.

---

## 3. Cross-Model Review (Codex 5.3)

### Finding C1 — HIGH: Existing test sweep missing

Phase 2/3 changes (path prefix constants, UID-in-hash) will break existing tests that hardcode the old path format. Examples:
- `tests/test_memory_retrieve.py:21-24` — `_get_staging_dir` helper
- `tests/test_memory_triage.py:1122-1160` — staging path assertions
- `tests/test_memory_staging_utils.py:72-78` — manual hash expectation

**Recommendation**: Add an explicit step to Phase 2 or Phase 4: "Update all existing tests and helpers that hardcode `/tmp/.claude-memory-staging-` paths or the old hash formula."

### Finding C2 — MEDIUM: Step 2.9 regex false-positive risk

The proposed regex `(?:/(?:private/)?tmp/\.claude-memory-staging-[a-f0-9]+/|\.claude/memory/\.staging/)` will match `/var/tmp/.claude-memory-staging-*` because the leading `/` is not anchored. This could cause false-positive Bash denials.

**Recommendation**: Use boundary-aware pattern: `(?<![A-Za-z0-9._-])/(?:private/)?tmp/\.claude-memory-staging-[a-f0-9]{12}/`. Add a negative test for `/var/tmp/...`.

### Finding C3 — MEDIUM: Step 2.12 monkeypatch won't work

`STAGING_DIR_PREFIX` is computed at module import time. A simple `monkeypatch` of `os.path.realpath` after import will not change the already-computed constant.

**Recommendation**: The macOS simulation test must either (a) reload the module under the patch, or (b) patch `STAGING_DIR_PREFIX` directly and test downstream behavior.

### Finding C4 — LOW: Step 2.13 grep gate is too narrow

`grep 'startswith("/tmp/'` only catches `startswith` calls. It misses hardcoded string constants like `"/tmp/.claude-memory-staging-"` in variables, regex patterns, and f-strings.

**Recommendation**: Widen to also grep for literal `"/tmp/.claude-memory-staging-"` and `'/tmp/'` across all hook scripts.

### Finding C5 — LOW: `staging_dir = None` vs key omission

Step 1.1 sets `triage_data["staging_dir"] = None`. The SKILL.md contract currently says "if it lacks `staging_dir`, compute it." A `None` value and a missing key are semantically different in Python (`key in dict` returns `True` for `None`).

**Recommendation**: Either omit the key entirely on fallback, or update SKILL.md to treat `null`/`None` the same as absent.

---

## 4. Independent Source Code Verification

### Line number accuracy (spot-checked against working tree)

| Plan Reference | Actual Code | Match? |
|---------------|-------------|--------|
| `memory_triage.py:1523-1526` (fallback bypass) | Lines 1523-1526: `ensure_staging_dir` try/except falling back to `get_staging_dir` | YES |
| `memory_triage.py:1527` (staging_dir assignment) | Line 1527: `triage_data["staging_dir"] = _staging_dir` | YES |
| `memory_triage.py:1130-1133` (context files fallback) | Lines 1130-1133: `ensure_staging_dir` try/except falling back to empty string | YES |
| `memory_triage.py:42-54` (fallback ensure_staging_dir) | Lines 42-54: inline fallback, missing S_ISDIR check | YES |
| `memory_triage.py:1460` (/tmp/ check) | Line 1460: `resolved.startswith("/tmp/")` | YES |
| `memory_write.py` 6 locations | Lines 551, 603, 653, 759, 1597, 1599 | YES |
| `memory_draft.py` 3 locations | Lines 86, 89, 246 | YES |
| `memory_staging_utils.py:20` (STAGING_DIR_PREFIX) | Line 20: hardcoded `/tmp/.claude-memory-staging-` | YES |
| `memory_staging_utils.py:37` (hash formula) | Line 37: `hashlib.sha256(os.path.realpath(cwd).encode())` — no UID | YES |
| `memory_staging_guard.py:43` (regex) | Line 43: hardcoded `/tmp/` in pattern | YES |
| `memory_write_guard.py:85,97` | Lines 85, 97: hardcoded `/tmp/` prefixes | YES |
| `memory_validate_hook.py:193` | Line 193: hardcoded `_TMP_STAGING_PREFIX` | YES |
| `memory_judge.py:120` | Line 120: `resolved.startswith("/tmp/")` | YES |
| `memory_retrieve.py:50` (fallback) | Line 50: hardcoded `/tmp/.claude-memory-staging-` in fallback | YES |

All line numbers verified correct.

### S_ISDIR status

- `memory_staging_utils.py:80` — already has `S_ISDIR` check in working tree (modified file, uncommitted)
- `memory_triage.py:42-54` — fallback `ensure_staging_dir` does NOT have `S_ISDIR` check (Step 1.4 is correct)

---

## 5. Summary

### Verdict: CONDITIONALLY READY

The plan is well-structured, correctly prioritized (security > cross-platform > hardening > verification), and all R1 corrections have been applied. Line numbers are accurate against the working tree. The plan is substantively ready for implementation with the following corrections:

### Must-fix before implementation (2)

1. **Files Changed table**: Line 88 says `memory_draft.py` has "2 resolved `/tmp/` prefix replacements" but Step 2.3 says 3. Change to "3".
2. **Step 2.9 regex**: Add boundary anchor to prevent `/var/tmp/` false positives. Use `(?<![A-Za-z0-9._-])/(?:private/)?tmp/` or equivalent.

### Should-fix (3)

3. **Add test sweep step**: Explicitly add a step (Phase 2 or 4) to update existing tests that hardcode old paths/hash formulas.
4. **Step 2.12 monkeypatch**: Note that module reload is required, or change approach to patch the computed constant directly.
5. **Step 2.13 grep gate**: Widen to also search for `"/tmp/.claude-memory-staging-"` literals, not just `startswith("/tmp/"`.

### Consider (1)

6. **`staging_dir` = None vs omission**: Clarify contract in SKILL.md or use key omission for cleaner semantics.

### No new security or race condition issues found beyond what's already tracked in Phase 5 (P3/P4).
