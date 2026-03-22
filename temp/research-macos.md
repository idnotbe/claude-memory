# Research: macOS `/tmp` Symlink Path Resolution Issue

## Problem Statement

On macOS, `/tmp` is a symlink to `/private/tmp`. Python's `os.path.realpath("/tmp/foo")` returns `/private/tmp/foo`. The codebase has hardcoded `startswith("/tmp/...")` checks that compare against **resolved** paths, causing all such checks to fail on macOS.

---

## 1. Affected Code Paths (Exhaustive)

### Category A: Staging prefix checks on RESOLVED paths -- WILL FAIL on macOS

These compare `os.path.realpath()` / `Path.resolve()` output against `"/tmp/.claude-memory-staging-"`:

| # | File | Line | Pattern | Resolution Method | macOS Impact |
|---|------|------|---------|-------------------|-------------|
| 1 | `memory_write.py` | 542 | `resolved_str.startswith("/tmp/.claude-memory-staging-")` | `Path(staging_dir).resolve()` at L535 | **FAIL** -- staging cleanup rejects valid dir |
| 2 | `memory_write.py` | 594 | `resolved_str.startswith("/tmp/.claude-memory-staging-")` | `Path(staging_dir).resolve()` at L587 | **FAIL** -- intent loading rejects valid dir |
| 3 | `memory_write.py` | 644 | `resolved_str.startswith("/tmp/.claude-memory-staging-")` | `Path(staging_dir).resolve()` at L640 | **FAIL** -- save-result write rejects valid dir |
| 4 | `memory_write.py` | 750 | `resolved_str.startswith("/tmp/.claude-memory-staging-")` | `Path(staging_dir).resolve()` at L746 | **FAIL** -- sentinel write rejects valid dir |
| 5 | `memory_write.py` | 1588 | `resolved.startswith("/tmp/.claude-memory-staging-")` | `os.path.realpath()` at L1576 | **FAIL** -- input path validation rejects valid staging |
| 6 | `memory_write.py` | 1590 | `resolved.startswith("/tmp/")` (general tmp check) | `os.path.realpath()` at L1576 | **FAIL** -- write-pending file acceptance fails |
| 7 | `memory_draft.py` | 86 | `resolved.startswith("/tmp/.claude-memory-staging-")` | `os.path.realpath()` at L80 | **FAIL** -- input validation rejects staging files |
| 8 | `memory_draft.py` | 89 | `resolved.startswith("/tmp/")` (general tmp check) | `os.path.realpath()` at L80 | **FAIL** -- broader /tmp/ allowance fails |
| 9 | `memory_write_guard.py` | 85 | `resolved.startswith("/tmp/")` (temp file allowlist) | `os.path.realpath()` at L77 | **FAIL** -- .memory-write-pending, .memory-draft, .memory-triage-context files blocked |
| 10 | `memory_write_guard.py` | 103 | `resolved.startswith(_TMP_STAGING_PREFIX)` (symlink defense) | `os.path.realpath()` at L77 | **FALSE POSITIVE** -- legitimate staging always triggers symlink-denial on macOS |
| 11 | `memory_write_guard.py` | 120 | `resolved.startswith(_TMP_STAGING_PREFIX)` (staging auto-approve) | `os.path.realpath()` at L77 | **FAIL** -- staging files never auto-approved |
| 12 | `memory_validate_hook.py` | 201 | `resolved.startswith(_TMP_STAGING_PREFIX)` | `os.path.realpath()` at L182 | **FAIL** -- staging files not skipped, triggers unnecessary validation |
| 13 | `memory_judge.py` | 120 | `resolved.startswith("/tmp/")` | `os.path.realpath()` at L118 | **FAIL** -- transcript path rejected, judge returns empty |
| 14 | `memory_triage.py` | 1460 | `resolved.startswith("/tmp/")` | `os.path.realpath()` at L1458 | **FAIL** -- transcript path rejected, triage exits 0 |

### Category B: Unresolved path checks -- PASS on macOS (no fix needed)

| # | File | Line | Pattern | Why Safe |
|---|------|------|---------|----------|
| 1 | `memory_draft.py` | 246 | `root.startswith("/tmp/.claude-memory-staging-")` | Checks raw `root` argument (not resolved). Caller passes literal `/tmp/` path from `get_staging_dir()`. |
| 2 | `memory_staging_utils.py` | 76 | `staging_dir.startswith(STAGING_DIR_PREFIX)` | Input is from `get_staging_dir()` which constructs the path using `STAGING_DIR_PREFIX` directly. No resolution involved. |
| 3 | `memory_staging_utils.py` | 125 | `path.startswith(STAGING_DIR_PREFIX)` | Docstring says "Resolved (realpath) file path" but callers may pass unresolved. **BORDERLINE** -- safe only if callers pass the result of `get_staging_dir()` (which is unresolved). |
| 4 | `memory_staging_guard.py` | 43 | Regex pattern `/tmp/\.claude-memory-staging-` | Matches against raw bash command text, not resolved paths. |

### Category C: Fallback inline functions that hardcode `/tmp/` prefix

| # | File | Line | Code |
|---|------|------|------|
| 1 | `memory_retrieve.py` | 50 | `return f"/tmp/.claude-memory-staging-{_h}"` (fallback `get_staging_dir`) |
| 2 | `memory_triage.py` | 41 | `return f"/tmp/.claude-memory-staging-{_h}"` (fallback `get_staging_dir`) |

These construct paths using unresolved `/tmp/` prefix. On macOS, the constructed path (`/tmp/.claude-memory-staging-abc`) does NOT match paths resolved via `realpath` (`/private/tmp/.claude-memory-staging-abc`). While the path itself works for `os.mkdir()` (OS resolves the symlink), any subsequent `realpath()` on files inside returns `/private/tmp/...`, creating a mismatch with the prefix used to construct the directory.

---

## 2. Recommended Fix Strategy

### Option A (RECOMMENDED): Resolve `STAGING_DIR_PREFIX` at module load time

Change the single source of truth in `memory_staging_utils.py`:

```python
# Line 20 -- BEFORE:
STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"

# Line 20 -- AFTER:
STAGING_DIR_PREFIX = os.path.realpath("/tmp") + "/.claude-memory-staging-"
```

Add a second constant for general `/tmp/` checks:

```python
# New line 21:
RESOLVED_TMP_PREFIX = os.path.realpath("/tmp") + "/"
```

**Behavior:**
- Linux: `STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"` (unchanged)
- macOS: `STAGING_DIR_PREFIX = "/private/tmp/.claude-memory-staging-"` (matches realpath output)

### Why Option A is Best

| Criterion | Option A (resolve prefix) | Option B (normalize at callsites) | Option C (unresolved paths) |
|-----------|--------------------------|----------------------------------|---------------------------|
| Code changes | ~6 files | 14+ callsites | Requires removing all realpath() calls |
| Security risk | Low (resolve once at source) | Medium (easy to miss a site) | High (defeats symlink defense) |
| Correctness | Guaranteed match | Fragile (new code must remember) | Breaks path traversal defense |
| Backwards compat | Full (Linux paths unchanged) | Full | Breaks security model |

### Why NOT `tempfile.gettempdir()`

- `tempfile.gettempdir()` respects `TMPDIR`, `TEMP`, `TMP` env vars
- An attacker setting `TMPDIR=/home/attacker/fake-tmp` would redirect staging
- The security policy is explicitly "the system /tmp", not "whatever Python considers temp"

---

## 3. Exact Code Changes Required

### 3.1 `memory_staging_utils.py` (source of truth)

```python
# Line 20 -- change:
STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"
# to:
STAGING_DIR_PREFIX = os.path.realpath("/tmp") + "/.claude-memory-staging-"
RESOLVED_TMP_PREFIX = os.path.realpath("/tmp") + "/"
```

### 3.2 `memory_write.py` -- 6 locations

Lines 542, 594, 644, 750: Already use `Path.resolve()` on the input. The resolved string will now match `STAGING_DIR_PREFIX` on macOS. **But these use inline `"/tmp/.claude-memory-staging-"` strings, not the imported constant.** Must either:
- (a) Import `STAGING_DIR_PREFIX` from `memory_staging_utils` and replace hardcoded strings, OR
- (b) Define a local `_RESOLVED_TMP_STAGING = os.path.realpath("/tmp") + "/.claude-memory-staging-"` and use it.

Option (b) is safer since `memory_write.py` already has complex imports (pydantic venv bootstrap).

Lines 1588, 1590: Same pattern. Replace `"/tmp/.claude-memory-staging-"` and `"/tmp/"` with resolved equivalents.

### 3.3 `memory_draft.py` -- 2 locations

Lines 86, 89: Replace `"/tmp/.claude-memory-staging-"` and `"/tmp/"` with resolved constants. This file already has `os.path.realpath()` available.

### 3.4 `memory_write_guard.py` -- 3 locations

Line 97: Change `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"` to `_TMP_STAGING_PREFIX = os.path.realpath("/tmp") + "/.claude-memory-staging-"`.

Line 85: Change `resolved.startswith("/tmp/")` to use `os.path.realpath("/tmp") + "/"`.

Lines 103, 120, 134: Automatically fixed by the `_TMP_STAGING_PREFIX` change.

### 3.5 `memory_validate_hook.py` -- 1 location

Line 193: Change `_TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"` to `_TMP_STAGING_PREFIX = os.path.realpath("/tmp") + "/.claude-memory-staging-"`.

### 3.6 `memory_judge.py` -- 1 location

Line 120: Change `resolved.startswith("/tmp/")` to `resolved.startswith(os.path.realpath("/tmp") + "/")`.

### 3.7 `memory_triage.py` -- 2 locations

Line 41 (fallback inline): Change `f"/tmp/.claude-memory-staging-{_h}"` to `f"{os.path.realpath('/tmp')}/.claude-memory-staging-{_h}"`.

Line 1460: Change `resolved.startswith("/tmp/")` to `resolved.startswith(os.path.realpath("/tmp") + "/")`.

### 3.8 `memory_retrieve.py` -- 1 location

Line 50 (fallback inline): Change `f"/tmp/.claude-memory-staging-{_h}"` to `f"{os.path.realpath('/tmp')}/.claude-memory-staging-{_h}"`.

### Summary: ~8 files, ~16 line changes (mostly mechanical string replacements)

---

## 4. Test Strategy

### Current Coverage

No existing tests cover macOS path resolution. There are:
- Zero references to `/private/tmp` in tests
- Zero `realpath` mocking in tests
- Existing tests in `tests/test_memory_staging_utils.py` test against `STAGING_DIR_PREFIX` but on Linux this is always `/tmp/...`

### Recommended New Tests

#### 4.1 Unit test: `STAGING_DIR_PREFIX` resolves correctly

```python
def test_staging_dir_prefix_is_resolved():
    """STAGING_DIR_PREFIX must match realpath('/tmp') to work on macOS."""
    from memory_staging_utils import STAGING_DIR_PREFIX
    assert STAGING_DIR_PREFIX.startswith(os.path.realpath("/tmp") + "/")
```

#### 4.2 Mock-based test: macOS `/private/tmp` simulation

```python
@mock.patch("os.path.realpath")
def test_staging_prefix_macos_simulation(mock_realpath):
    """Simulate macOS where realpath('/tmp') returns '/private/tmp'."""
    mock_realpath.side_effect = lambda p: p.replace("/tmp", "/private/tmp", 1) if p.startswith("/tmp") else p
    # Re-import to trigger module-level constant evaluation
    import importlib
    import memory_staging_utils
    importlib.reload(memory_staging_utils)
    assert memory_staging_utils.STAGING_DIR_PREFIX == "/private/tmp/.claude-memory-staging-"
```

Note: Module-level constants evaluated at import time require `importlib.reload()` to test with mocked `realpath`. This is slightly fragile but necessary.

#### 4.3 Integration test: resolved path matches staging prefix

```python
def test_resolved_path_matches_staging_prefix():
    """A file created in staging_dir, when resolved, must startswith STAGING_DIR_PREFIX."""
    from memory_staging_utils import STAGING_DIR_PREFIX, get_staging_dir
    staging = get_staging_dir("/some/project")
    # Simulate what happens inside memory_write.py
    resolved = os.path.realpath(staging)
    assert resolved.startswith(STAGING_DIR_PREFIX), (
        f"Resolved path {resolved!r} does not start with {STAGING_DIR_PREFIX!r}. "
        f"This will fail on macOS where /tmp -> /private/tmp."
    )
```

#### 4.4 Parametric test for all affected files

For each of the 14 affected callsites, add a test that verifies the comparison works when `realpath("/tmp")` returns `/private/tmp`. Use `monkeypatch` or `mock.patch` to simulate the macOS behavior.

---

## 5. Cross-Model Opinions

### Codex (OpenAI)

**Recommendation**: Resolve both the allowed base and the candidate path, then check containment structurally with `Path.relative_to()` or `os.path.commonpath()`. Do NOT use `startswith()` for containment. Noted that this repo already has the stronger `resolve().relative_to()` pattern in `memory_search_engine.py::_check_path_containment`.

**Key insight**: The codebase already has two competing patterns -- secure `relative_to()` containment and insecure `startswith()` prefix checks. The long-term fix should migrate toward `relative_to()` everywhere, but the immediate `realpath` prefix fix is appropriate as a targeted bug fix.

### Gemini (Google)

**Confirmed**: `os.mkdir('/tmp/foo')` on macOS physically creates at `/private/tmp/foo`. `os.path.realpath('/tmp/foo')` returns `/private/tmp/foo`. The fix must resolve the prefix before comparison.

**Key insight**: `os.path.abspath()` does NOT resolve symlinks (it just normalizes `.` and `..`), so it cannot be used as an alternative. Only `realpath()` / `Path.resolve()` will canonicalize the symlink.

### Vibe Check (Self-assessment)

**Verdict**: Plan is sound. Main risk is incomplete propagation -- there are 4+ locations that duplicate the prefix without importing the constant. The fix must cover all inline fallbacks and local `_TMP_STAGING_PREFIX` definitions, not just the central `STAGING_DIR_PREFIX`.

---

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Missing a callsite | Medium | Exhaustive grep already done; CI test can catch regression |
| `os.path.realpath("/tmp")` returns unexpected value on exotic systems | Low | `/tmp` is POSIX standard; FreeBSD/Linux/macOS all have it |
| Module reload issues in tests | Low | Use `importlib.reload()` carefully; document the pattern |
| Breaking the staging guard symlink defense (L103) | High | The fix actually **improves** the symlink defense -- on macOS the current code false-positives on every legitimate staging write |
| Performance of module-level `realpath()` | Negligible | Single syscall at import time |

---

## 7. Implementation Order

1. Fix `memory_staging_utils.py` (add `RESOLVED_TMP_PREFIX`, change `STAGING_DIR_PREFIX`)
2. Fix `memory_write.py` (6 locations)
3. Fix `memory_draft.py` (2 locations)
4. Fix `memory_write_guard.py` (3 locations via 1 constant change + 1 tmp prefix)
5. Fix `memory_validate_hook.py` (1 location)
6. Fix `memory_judge.py` (1 location)
7. Fix `memory_triage.py` (2 locations)
8. Fix `memory_retrieve.py` (1 location)
9. Add tests
10. Manual smoke test on macOS (if available) or mock-based verification
