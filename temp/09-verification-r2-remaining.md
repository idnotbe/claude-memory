# Verification R2: Security Review of 12 Remaining Fixes

> **Reviewer:** verifier-r2-security (Claude Opus 4.6)
> **Date:** 2026-02-16
> **Files reviewed:** memory_write.py, memory_write_guard.py, memory_triage.py, memory-config.default.json, plugin.json
> **External reviews:** Gemini 3 Pro (via PAL clink, codereviewer role)
> **Methodology:** Adversarial attack vector analysis with proof-of-concept testing, automated test suite verification
> **Status:** COMPLETE

---

## Executive Summary

All 12 fixes verified. **No new vulnerabilities introduced. No bypass vectors found.** The fixes are well-implemented with defense-in-depth patterns. One cosmetic observation (unclosed XML tag on truncation -- actually resolved in code) was identified and corrected during review. Gemini 3 Pro independently confirmed all fixes as PASS.

**Overall Verdict: PASS -- All 12 fixes verified correct, no security regressions**

---

## A. Security-Critical Fix Verification

### Fix #1: SEC-4 -- _read_input Path Validation

**File:** `hooks/scripts/memory_write.py:1091-1121`
**Verdict:** PASS

**Code under review (lines 1098-1105):**
```python
resolved = os.path.realpath(input_path)
if not resolved.startswith("/tmp/") or ".." in input_path:
    print(f"SECURITY_ERROR\npath: {input_path}\nresolved: {resolved}\n...")
    return None
```

**Attack vectors tested:**

| Vector | Input | Resolved | Result | Correct? |
|--------|-------|----------|--------|----------|
| Normal path | `/tmp/.memory-draft-foo.json` | `/tmp/.memory-draft-foo.json` | ACCEPTED | YES |
| Path traversal | `/tmp/../../etc/passwd` | `/etc/passwd` | REJECTED (startswith) | YES |
| Subdir traversal | `/tmp/subdir/../.memory-draft-foo.json` | `/tmp/.memory-draft-foo.json` | REJECTED (.. check) | YES |
| Outside /tmp | `/etc/passwd` | `/etc/passwd` | REJECTED (startswith) | YES |
| Traversal after name | `/tmp/.memory-draft-foo.json/../../../etc/passwd` | `/etc/passwd` | REJECTED (startswith) | YES |
| **Symlink attack** | `/tmp/.memory-draft-evil.json -> /etc/passwd` | `/etc/passwd` | REJECTED (startswith) | YES |

**Symlink deep-dive:** Created actual symlink at `/tmp/.memory-draft-evil-symlink.json` pointing to `/etc/passwd`. `os.path.realpath()` resolves the symlink BEFORE the prefix check, so the resolved path is `/etc/passwd` which fails `startswith("/tmp/")`. The symlink vector is fully neutralized.

**O_NOFOLLOW question:** The task brief asked whether `O_NOFOLLOW` applies to `_read_input`. It does NOT -- `_read_input` uses `open()`, not `os.open()` with flags. However, this is irrelevant because `realpath()` resolves symlinks before `open()` is called. The resolved path is passed to `open()` (line 1107), so symlinks are followed to their true target, which is then validated. This is correct behavior.

**".." check redundancy:** The `".." in input_path` check is defense-in-depth. Without it, `/tmp/subdir/../.memory-draft-foo.json` would resolve to `/tmp/.memory-draft-foo.json` (valid startswith), but the user's intent was traversal. The double-check catches this. Not strictly necessary for security (realpath handles it), but reinforces intent validation.

**Error message safety:** The error message includes both `input_path` and `resolved` path. This is visible only to the agent (stdout), not to external users. Acceptable for debugging. No information leak to external parties.

### Fix #5: Write Guard Allowlist

**File:** `hooks/scripts/memory_write_guard.py:39-48`
**Verdict:** PASS

**Code under review:**
```python
basename = os.path.basename(resolved)
if resolved.startswith("/tmp/"):
    if (basename.startswith(".memory-write-pending") and basename.endswith(".json")):
        sys.exit(0)
    if (basename.startswith(".memory-draft-") and basename.endswith(".json")):
        sys.exit(0)
    if (basename.startswith(".memory-triage-context-") and basename.endswith(".txt")):
        sys.exit(0)
```

**Key question: Does allowlist apply before or after path resolution?**
AFTER. The `resolved` variable is computed on line 34 via `os.path.realpath(os.path.expanduser(file_path))`. The allowlist checks operate on the resolved path and its basename. This means:
- A symlink like `/tmp/.memory-draft-evil.json -> .claude/memory/index.md` resolves to the memory directory, which FAILS the `startswith("/tmp/")` check. Correct.
- The allowlist correctly applies to resolved paths only.

**Can malicious .memory-draft-*.json files trick the system?**
No. The write guard's purpose is to protect `.claude/memory/` from direct writes. Files in `/tmp/` are consumed by `memory_write.py` which performs full Pydantic schema validation before writing to the memory directory. A malicious draft file would fail schema validation and be rejected. The guard and the write tool form a layered defense.

**Allowlist scope assessment:**
- `.memory-write-pending*.json` -- legacy draft format. Tightly prefixed. OK.
- `.memory-draft-*.json` -- new draft format. Tightly prefixed. OK.
- `.memory-triage-context-*.txt` -- triage context files. Written by `memory_triage.py` with `O_NOFOLLOW`. OK.
- All require `/tmp/` prefix on resolved path. No escaping possible.

### Fix #7: Atomic Index Writes

**File:** `hooks/scripts/memory_write.py:455-469`
**Verdict:** PASS

**Code under review:**
```python
def atomic_write_text(target: str, content: str) -> None:
    import tempfile
    target_dir = os.path.dirname(target) or "."
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp", prefix=".mw-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.rename(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

**Security analysis:**

| Check | Result | Notes |
|-------|--------|-------|
| Temp file permissions | `0o600` | `mkstemp` default. Correct -- only owner can read/write. |
| Same-directory temp file | YES | `dir=target_dir` ensures same filesystem for atomic rename. |
| `os.rename` atomicity | ATOMIC | On same filesystem (POSIX guarantee). Confirmed by test. |
| Cleanup on failure | YES | `except BaseException` catches all exceptions, unlinks temp file. |
| Orphaned temp files on crash | POSSIBLE | If process is killed between mkstemp and rename, `.mw-*.tmp` remains. |
| Orphan security impact | NONE | Orphans are inert `.tmp` files with `0o600` permissions. Not a security issue. |

**Integration check:** `add_to_index`, `remove_from_index`, and `update_index_entry` all call `atomic_write_text` (lines 397, 407, 428). All index mutations are now atomic. The `_flock_index` context manager provides mutual exclusion, and atomic writes provide crash safety. This is a correct two-layer protection.

### Fix #10: NaN/Inf Threshold Guard

**File:** `hooks/scripts/memory_triage.py:534-535`
**Verdict:** PASS

**Code under review (within load_config threshold parsing):**
```python
val = float(raw_val)
# Reject NaN and Inf (CPython json.loads accepts these)
if math.isnan(val) or math.isinf(val):
    continue
config["thresholds"][cat] = max(0.0, min(1.0, val))
```

**CPython json.loads behavior confirmed:**

| Input JSON | Parsed value | `math.isnan` | `math.isinf` | Guard catches? |
|-----------|-------------|-------------|-------------|---------------|
| `NaN` | `nan` | `True` | `False` | YES |
| `Infinity` | `inf` | `False` | `True` | YES |
| `-Infinity` | `-inf` | `False` | `True` | YES |

All three special float values are correctly rejected. The `continue` statement skips the value, falling back to the default threshold. This is the correct behavior.

**Downstream impact if guard were missing:** A threshold of `NaN` would cause `score >= threshold` to always be `False` (NaN comparisons always return False), effectively disabling the category. A threshold of `Infinity` would have the same effect. `-Infinity` would make the threshold always fire. The guard prevents all three attack vectors.

### Fix #11: Context File 50KB Cap

**File:** `hooks/scripts/memory_triage.py:706-713`
**Verdict:** PASS

**Code under review:**
```python
content_bytes = content.encode("utf-8")
if len(content_bytes) > MAX_CONTEXT_FILE_BYTES:
    truncated = content_bytes[:MAX_CONTEXT_FILE_BYTES].decode("utf-8", errors="ignore")
    content = truncated + "\n</transcript_data>\n[Truncated: context exceeded 50KB]"
```

**Critical check -- does truncation break the `</transcript_data>` closing tag?**

Initial concern: The opening `<transcript_data>` tag would be in the content, but truncation might cut before the closing tag. However, **the code explicitly appends `\n</transcript_data>\n` after truncation** (line 713). This ensures the XML structure remains well-formed after truncation. The subagent receives properly closed tags regardless of truncation.

**UTF-8 multi-byte split:** Byte-boundary truncation at 50KB could split a multi-byte UTF-8 character (e.g., a 4-byte emoji at bytes 49998-50001). The `errors="ignore"` parameter drops the incomplete character rather than producing a replacement character or raising an error. Confirmed by test: a content near 50KB with multi-byte chars at the boundary is correctly handled -- incomplete chars are silently dropped.

**Size after truncation:** The appended closing tag + truncation marker adds ~53 bytes. Total output is at most 50,053 bytes. This is well within acceptable limits and does not create a secondary size issue.

---

## B. Non-Security Fix Verification

### Fix #2: plugin.json Version Sync (4.0.0 -> 5.0.0)

**File:** `.claude-plugin/plugin.json`
**Verdict:** PASS

Version now reads `"5.0.0"`, matching `hooks.json` description `"v5.0.0"`. No security implications.

### Fix #3: Lowercase Context File Paths

**File:** `hooks/scripts/memory_triage.py:673`
**Verdict:** PASS

Context file paths now use lowercase category names (e.g., `/tmp/.memory-triage-context-decision.txt` instead of `/tmp/.memory-triage-context-DECISION.txt`). This matches the downstream scripts that expect lowercase. No security implications.

### Fix #4: Empty Results Guard in format_block_message

**File:** `hooks/scripts/memory_triage.py:775`
**Verdict:** PASS

```python
if not results:
    return ""
```

Prevents generating a malformed block message from empty results. No security implications, purely a robustness improvement.

### Fix #6: Cost Documentation for 6-Category Trigger

**Verdict:** PASS. Documentation only. No code changes.

### Fix #8: Config Case-Insensitive Threshold Parsing

**File:** `hooks/scripts/memory_triage.py:528`
**Verdict:** PASS

```python
user_thresholds = {k.upper(): v for k, v in triage["thresholds"].items()}
```

**Backward compatibility confirmed:**

| Config key casing | `.upper()` result | Matches `DEFAULT_THRESHOLDS` key? |
|------------------|-------------------|----------------------------------|
| `"DECISION"` | `"DECISION"` | YES |
| `"decision"` | `"DECISION"` | YES |
| `"Decision"` | `"DECISION"` | YES |

All three casing variants correctly normalize to UPPERCASE for matching. The default config file (`memory-config.default.json`) now uses lowercase keys, and existing configs with UPPERCASE keys continue to work. No security implications.

### Fix #9: Data Flow Diagram

**Verdict:** PASS. Documentation only (README.md). No code changes.

### Fix #12: Category Casing Consistency

**File:** `hooks/scripts/memory_triage.py` (multiple locations)
**Verdict:** PASS

Category keys in `write_context_files` and `format_block_message` now consistently use lowercase, matching downstream expectations. No security implications.

---

## C. Cross-Validation: Gemini 3 Pro

Gemini 3 Pro (via PAL clink, codereviewer role) independently reviewed all 6 security-relevant fixes:

| Fix | Gemini Rating | Agreement? | Notes |
|-----|--------------|------------|-------|
| SEC-4 path validation | PASS | YES | Confirmed realpath + startswith is robust |
| Write guard allowlist | PASS | YES | Correctly identifies layered defense with memory_write.py |
| Atomic index writes | PASS | YES | Standard mkstemp/rename pattern approved |
| NaN/Inf guard | PASS | YES | Confirmed CPython json.loads behavior |
| 50KB context cap | PASS | YES | Noted closing tag is properly appended after truncation |
| Config case-insensitive | PASS | YES | Standard normalization pattern |

**Notable Gemini observation:** Gemini highlighted the `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` flags in context file creation (line 717-719 of memory_triage.py) as a "high-quality security practice" for preventing symlink attacks on context file writes. This is correct -- the flag combination ensures that even if an attacker places a symlink at `/tmp/.memory-triage-context-*.txt`, the write will fail rather than following the symlink to an unintended target.

**Gemini correction applied:** Gemini correctly identified that line 713 appends `\n</transcript_data>\n` after truncation, which I initially missed in my test (my test simulated the truncation logic without this line). The actual code properly closes the XML tag.

---

## D. Test Suite Verification

| Test File | Tests | Result |
|-----------|-------|--------|
| `test_memory_write_guard.py` | 9 | 9 PASSED |
| `test_memory_write.py` | 80 | 80 PASSED |
| `test_arch_fixes.py` | 50 | 40 PASSED, 10 XPASSED |
| `test_memory_candidate.py` | (verified in prior round) | ALL PASSED |
| `test_memory_index.py` | (verified in prior round) | ALL PASSED |
| `test_memory_retrieve.py` | (verified in prior round) | ALL PASSED |
| `test_memory_validate_hook.py` | (verified in prior round) | ALL PASSED |

**No regressions.** The 10 XPASSED tests in `test_arch_fixes.py` are tests that were previously marked `xfail` (expected to fail) but now pass due to the fixes -- this confirms the fixes resolved the underlying issues.

---

## E. Residual Risk Assessment

### E1. Orphaned Temp Files from Crash (INFO)

**Location:** `atomic_write_text()` (memory_write.py:459)
**Risk:** If the process is killed (SIGKILL) between `mkstemp` and `rename`, a `.mw-*.tmp` file remains in the index directory.
**Impact:** Cosmetic. Files have `0o600` permissions and contain benign content (index or JSON data). They do not affect functionality and can be cleaned up manually.
**Mitigation:** Not needed. Standard behavior for atomic write patterns.

### E2. ".." Check False Positive Edge Case (INFO)

**Location:** `_read_input()` (memory_write.py:1099)
**Risk:** A filename literally containing ".." (e.g., `/tmp/.memory-draft-..version-bump.json`) would be rejected by the `".." in input_path` check even though it resolves to a valid /tmp/ path.
**Impact:** None in practice. Memory draft filenames are generated by the agent and never contain "..". This is an overly-broad but safe check (false reject, not false accept).
**Severity:** INFO

### E3. Write Guard Allows Any Matching Filename in /tmp/ (INFO)

**Location:** `memory_write_guard.py:42-48`
**Risk:** Any process can write a `.memory-draft-*.json` file in `/tmp/`. If another user on the system creates a malicious draft file, and the agent happens to reference it as input, `memory_write.py` would attempt to read it.
**Impact:** Mitigated by schema validation in `memory_write.py`. A malicious JSON file that doesn't match the Pydantic schema is rejected. A file that DOES match the schema would need to contain valid memory data, which is benign by definition (it's just a memory entry).
**Severity:** INFO (multi-user system threat, mitigated by schema validation)

---

## F. Summary

| # | Fix ID | Description | Security Verdict | Bypass Found? |
|---|--------|-------------|-----------------|---------------|
| 1 | SEC-4 | _read_input path validation | **PASS** | NO |
| 2 | H-1 | plugin.json version sync | **PASS** (non-security) | N/A |
| 3 | Issue #2 | Lowercase context file paths | **PASS** (non-security) | N/A |
| 4 | Issue #3 | Empty results guard | **PASS** (non-security) | N/A |
| 5 | INFO-1 | Write guard allowlist | **PASS** | NO |
| 6 | INFO-2 | Cost documentation | **PASS** (docs only) | N/A |
| 7 | INFO-3 | Atomic index writes | **PASS** | NO |
| 8 | ARCH-2 | Config case-insensitive parsing | **PASS** | NO |
| 9 | ARCH-3 | Data flow diagram | **PASS** (docs only) | N/A |
| 10 | BONUS-1 | NaN/Inf threshold guard | **PASS** | NO |
| 11 | ADV-5 | Context file 50KB cap | **PASS** | NO |
| 12 | H-3 | Category casing consistency | **PASS** (non-security) | N/A |

**New vulnerabilities introduced by fixes:** NONE

**Residual risks:** 3 INFO-level items (orphaned temp files, ".." false positive, multi-user draft file injection). All mitigated by existing defenses.

**Gemini cross-validation:** 6/6 security fixes independently confirmed PASS.

**Test suite:** 139+ tests pass, 0 failures, 10 xpassed (confirming fixes resolved known issues).

---

## G. Overall Security Assessment

**PASS -- All 12 fixes are correctly implemented with no security regressions.**

The fixes demonstrate consistent application of defense-in-depth principles:
- Path validation uses both `realpath()` resolution AND literal ".." checking
- Write operations use both file locking AND atomic rename
- Input validation uses both type checking AND value clamping
- Truncation preserves XML structure AND adds explicit boundary markers

No CRITICAL, HIGH, or MEDIUM issues found. Three INFO-level residual risks identified, all mitigated by existing layered defenses.
