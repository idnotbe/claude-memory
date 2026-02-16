# V2 Adversarial Review: Config Exemption Fix

**Reviewer:** v2-adversarial
**Date:** 2026-02-16
**Rating:** PASS

---

## Summary

The V1 security fix (directory-depth validation) is solid. All attack vectors tested against the current code are properly handled. The implementation correctly relies on `os.path.realpath()` for path canonicalization and adds a well-designed depth check (`"/" not in after_mem`) to prevent subdirectory bypasses. No exploitable vulnerabilities found.

---

## Attack Vector Results

### 1. Path Traversal Variants: PASS

| Input Path | `resolved` (after realpath) | `after_mem` | `/` in `after_mem` | Result |
|---|---|---|---|---|
| `decisions/../memory-config.json` | `.claude/memory/memory-config.json` | `memory-config.json` | No | ALLOW (correct) |
| `../memory/decisions/memory-config.json` | `.claude/memory/decisions/memory-config.json` | `decisions/memory-config.json` | Yes | Falls through -> DENY (correct) |
| `decisions/../../memory/memory-config.json` | `.claude/memory/memory-config.json` | `memory-config.json` | No | ALLOW (correct) |

**Analysis:** `os.path.realpath()` resolves all `..` components before any checks run. The resolved path is the canonical absolute path. No traversal attack can bypass the depth check because by the time the check runs, the path has already been fully resolved.

### 2. Symlink Attacks: PASS

| Scenario | realpath Behavior | Exemption Fires? | Safe? |
|---|---|---|---|
| Symlink FROM `memory-config.json` TO a memory file (e.g., `decisions/evil.json`) | Resolves to `decisions/evil.json` | No (basename changes to `evil.json`) | Yes |
| Symlink FROM a memory file TO `memory-config.json` | Resolves to actual config file location | Yes (at root level) | Yes (equivalent to direct config edit) |
| Symlink FROM outside memory dir TO inside | Resolves to target inside memory dir | Normal deny applies | Yes |
| Symlink FROM inside memory dir TO outside | Resolves to target outside; not in memory dir | No deny needed | Yes |

**Analysis:** `os.path.realpath()` follows all symlinks to the final target. The basename and path depth checks operate on the real target, not the symlink name. No symlink manipulation can fool the guards.

### 3. Similar Filenames: PASS

| Filename | `basename == _CONFIG_BASENAME`? | Result |
|---|---|---|
| `Memory-Config.json` | No (case-sensitive comparison) | DENY (correct on Linux) |
| `memory-config.json\x00.json` | `realpath()` raises `ValueError` -> fallback `normpath/abspath` preserves null byte in string -> basename `memory-config.json\x00.json` != config | DENY (correct) |
| `memory-config.json/` | `normpath()` strips trailing `/` -> basename `memory-config.json` matches | ALLOW (acceptable -- trailing-slash path isn't a valid file write) |
| `memory-config.json ` (trailing space) | `realpath()` preserves trailing space -> basename `"memory-config.json "` != config | DENY (correct) |

**Case sensitivity note:** On Linux (case-sensitive filesystem), `Memory-Config.json` is a distinct file and correctly doesn't match. On macOS HFS+ (case-insensitive), `realpath()` resolves to the actual casing on disk. If the actual file on disk is `memory-config.json`, then `realpath()` would return the canonical casing, and the check would match correctly. If no such file exists, the path passes through unchanged with the wrong case, and the exemption won't fire (safe default). This is correct behavior in both cases.

**Null byte note:** Python 3 raises `ValueError` from `os.path.realpath()` for embedded null bytes. The fallback branch (`normpath/abspath`) preserves the null byte in the string, but the basename won't match `memory-config.json` because the null byte is included. Furthermore, the OS cannot create a file with null bytes in its name, so this is a non-issue in practice.

### 4. Edge Paths: PASS

| Scenario | Outcome | Correct? |
|---|---|---|
| Multiple `/.claude/memory/` segments (config at inner root) | `find()` returns FIRST match; `after_mem` contains `subproject/.claude/memory/memory-config.json`; `/` is present -> falls through to DENY | Technically a false negative (inner config blocked), but this scenario is extremely unlikely and erring on the side of caution is the safe default |
| Very long paths (500+ chars) | `find()` and string operations work fine on long strings; Python has no practical string length limit | PASS |
| Unicode path components (e.g., zero-width space in filename) | Zero-width space makes basename `memory\u200b-config.json` (19 chars) != `memory-config.json` (18 chars) -> no match | PASS (correct -- it's a different file) |
| Config file outside any `.claude/memory/` directory | `idx < 0` -> `else` branch -> `sys.exit(0)` (allow). Would have been allowed anyway since the deny check also wouldn't match | PASS |

### 5. Logic Flow Exploits: PASS

**Q: Can `normalized` be manipulated between the config check and deny check in write_guard.py?**

No. `normalized` is a local variable assigned at line 56 from `resolved.replace(os.sep, "/")`. Between lines 56 and 66, the only code that executes is the config basename check (lines 57-65), which reads `normalized` but never modifies it. Python is single-threaded within a function execution, so no external mutation is possible.

**Q: What if `MEMORY_DIR_SEGMENT` is not found (idx < 0) but the file IS in a memory directory?**

This can only happen if the deny check at line 66 matches via `normalized.endswith(MEMORY_DIR_TAIL)` (no trailing slash) rather than `MEMORY_DIR_SEGMENT in normalized` (with trailing slash). But for a file named `memory-config.json`, the path would be `.../.claude/memory/memory-config.json`, which always contains `/.claude/memory/` (SEGMENT). The only path that ends with TAIL but doesn't contain SEGMENT would be `.../.claude/memory` (the directory itself), where basename is `memory`, not `memory-config.json`. So the config check never fires in this impossible case.

**Q: Consistency between write_guard and validate_hook?**

`write_guard.py` has an `else` branch at lines 63-65 for `idx < 0` (config file not in memory dir -> allow). `validate_hook.py` has no such `else` branch. This is correct because `validate_hook.py` gates on `is_memory_file(resolved)` at line 153, which checks `MEMORY_DIR_SEGMENT in normalized`. By the time the config check runs at line 164, `idx >= 0` is guaranteed. The absence of an `else` branch is intentional and correct.

### 6. Race Conditions: PASS (pre-existing, not worsened)

**TOCTOU between PreToolUse and actual write:** This is a pre-existing architectural limitation of Claude Code hooks. The config exemption does not widen this gap. An attacker exploiting this would need:
1. Code execution on the local machine (to swap files between check and write)
2. Precise timing to hit the window between PreToolUse hook and Write tool execution

If an attacker already has code execution, the hook bypass is moot -- they could write directly to the filesystem.

**Config file swapped between PreToolUse and PostToolUse:** Even if the config file at the resolved path is swapped with a malicious memory file:
- PostToolUse runs against the actual file on disk
- If the swap results in a file in a subfolder, the depth check blocks the exemption
- If the swap results in a non-JSON file, the non-JSON check at line 174 catches it
- If the swap results in an invalid memory file at root, it would be quarantined

This is a theoretical concern with no practical exploitability.

---

## Findings Summary

| # | Attack Vector | Verdict | Notes |
|---|---|---|---|
| 1 | Path traversal (`..` sequences) | PASS | `realpath()` resolves all traversals before checks |
| 2 | Symlink attacks | PASS | `realpath()` follows symlinks to real target |
| 3a | Case-insensitive filename | PASS | Linux: case-sensitive comparison. macOS: `realpath()` canonicalizes casing |
| 3b | Null byte injection | PASS | `realpath()` raises `ValueError`; fallback preserves null byte -> no basename match |
| 3c | Trailing slash | PASS | `normpath()` strips it; result is acceptable |
| 3d | Trailing space | PASS | Preserved by `realpath()`; no basename match |
| 4a | Multiple `/.claude/memory/` segments | PASS (note) | Inner-root config gets blocked; false negative but safe default; extremely unlikely scenario |
| 4b | Very long paths | PASS | Python handles arbitrary string lengths |
| 4c | Unicode variants | PASS | Different bytes = different filename = no match |
| 4d | Config outside memory dir | PASS | `else` branch allows (would be allowed anyway) |
| 5a | `normalized` variable manipulation | PASS | Local variable, no mutation path |
| 5b | SEGMENT not found but in memory dir | PASS | Impossible for files named `memory-config.json` |
| 5c | write_guard vs validate_hook consistency | PASS | Different `else` handling is intentional and correct |
| 6 | Race conditions (TOCTOU) | PASS | Pre-existing limitation, not worsened |

---

## New Vulnerabilities Found

None. The V1 fix addresses the original basename collision vulnerability correctly. The depth check (`"/" not in after_mem`) is a clean and effective guard.

## Minor Observations (not vulnerabilities)

1. **Nested `.claude/memory/` paths (Test 18):** `find()` matches the first occurrence, so a config file at an inner `.claude/memory/` root would be incorrectly blocked. Severity: negligible. A nested `.claude/memory/` inside another `.claude/memory/` is an extremely unlikely configuration. Using `rfind()` instead of `find()` would fix it, but the change is not worth the risk of introducing new bugs for a scenario that essentially never occurs.

2. **PostToolUse warning for config files:** The "bypassed PreToolUse guard" warning at line 157 of `validate_hook.py` still fires for config file writes even though they're intentionally allowed through the PreToolUse guard. This is benign (stderr only, not user-facing) and useful for debugging, but could be confusing in logs.

## Overall Assessment

**Rating: PASS**

The implementation is robust against all tested adversarial inputs. The core defense relies on `os.path.realpath()` for path canonicalization and a simple depth check for subdirectory validation. Both mechanisms are well-understood, battle-tested Python stdlib functions. The V1 security fix correctly addresses the only vulnerability found in the original implementation (basename collision in subdirectories). No new attack vectors succeed against the current code.
