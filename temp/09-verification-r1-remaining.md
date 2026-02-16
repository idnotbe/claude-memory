# Verification R1: Remaining Fixes (12 Issues)

**Date:** 2026-02-16
**Reviewer:** R1 Correctness Reviewer (Opus 4.6)
**Cross-validator:** Gemini 3 Pro (pal clink, codereviewer role)

## Per-Fix Verdicts

### Fix 1 (SEC-4): memory_write.py _read_input path validation

**Verdict: PASS**

File: `hooks/scripts/memory_write.py:1091-1121`

The `_read_input` function now:
1. Resolves the path via `os.path.realpath(input_path)` (line 1098) -- this follows symlinks and canonicalizes the path BEFORE the prefix check, which is correct.
2. Checks `resolved.startswith("/tmp/")` -- ensures the resolved path is in /tmp/ (line 1099).
3. Checks `".." in input_path` -- rejects traversal in the original string (line 1099).
4. Uses the `resolved` path for `open()` (line 1107) -- correct, prevents TOCTOU between resolve and open.

The `os.path.realpath` call happens BEFORE the `/tmp/` prefix check, so symlink-based escapes are blocked. The `..` check on the original string is defense-in-depth (realpath already resolves it, but the explicit check adds belt-and-suspenders protection).

SKILL.md documents the draft path validation instruction at lines 106-108: "Before reading any draft file, verify the path starts with `/tmp/.memory-draft-` and contains no `..` path components."

No issues found.

### Fix 2 (H-1): plugin.json version

**Verdict: PASS**

- `.claude-plugin/plugin.json` line 3: `"version": "5.0.0"` -- confirmed.
- `hooks/hooks.json` line 2: `"description": "v5.0.0: 1 deterministic command-type Stop hook..."` -- confirmed.

Versions are now synchronized.

### Fix 3+12 (Issue #2, H-3): Lowercase context file paths

**Verdict: PASS**

File: `hooks/scripts/memory_triage.py`

In `write_context_files()` (line 654-737):
- Line 670: `cat_lower = category.lower()` -- converts category to lowercase.
- Line 673: `path = f"/tmp/.memory-triage-context-{cat_lower}.txt"` -- uses lowercase for file path.
- Line 677: `f"Category: {cat_lower}"` -- writes lowercase in file content header.
- Line 732: `context_paths[cat_lower] = path` -- uses lowercase as dict key.

In `format_block_message()` (line 764-836):
- Line 802: `cat_lower = category.lower()` -- converts to lowercase for structured data.
- Line 803: `entry = {"category": cat_lower, ...}` -- emits lowercase in JSON.
- Line 807: `ctx_path = context_paths.get(cat_lower)` -- looks up using lowercase key, matching what `write_context_files()` stored.

There are NO remaining UPPERCASE references in context file path construction or structured data lookup. The human-readable stderr section (line 786) still uses the original `category` (UPPERCASE) for display, which is correct -- only the machine-parsed `<triage_data>` JSON uses lowercase.

SKILL.md (lines 52-56) documents this behavior: "The `<triage_data>` JSON block emits lowercase category names (e.g., 'decision'), matching config keys and memory_candidate.py expectations."

No issues found. Write and read paths are consistent.

### Fix 4 (Issue #3): Empty results guard

**Verdict: PASS**

File: `hooks/scripts/memory_triage.py:774`

```python
if not results:
    return ""
```

This is the very first check in `format_block_message()`, before any processing. Correct.

### Fix 5 (INFO-1): Write guard allowlist

**Verdict: PASS**

File: `hooks/scripts/memory_write_guard.py:39-48`

The allowlist now includes three patterns:
1. `.memory-write-pending` + `.json` (original) -- line 43
2. `.memory-draft-` + `.json` (new) -- line 45-46
3. `.memory-triage-context-` + `.txt` (new) -- line 47-48

All require `/tmp/` prefix (line 42). Each pattern checks both prefix and suffix. This correctly allows the Phase 1 draft files and triage context files through the write guard.

No issues found.

### Fix 6 (INFO-2): Cost note

**Verdict: PASS**

File: `skills/memory-management/SKILL.md:61-63`

The cost note reads: "Each triggered category spawns one drafting subagent (Phase 1) and one verification subagent (Phase 2). With all 6 categories triggering, this is 12 subagent calls total."

Clear, accurate, and placed right after the "Spawn ALL category subagents in PARALLEL" instruction. Good placement.

### Fix 7 (INFO-3): Atomic index writes

**Verdict: PASS**

File: `hooks/scripts/memory_write.py`

1. `atomic_write_text()` exists at lines 455-469. Uses `tempfile.mkstemp()` + `os.rename()` for atomic replacement. Correct pattern.
2. `atomic_write_json()` at lines 472-475 delegates to `atomic_write_text()`. Correct.
3. `add_to_index()` at line 397: calls `atomic_write_text(str(index_path), content)`. Correct.
4. `remove_from_index()` at line 407: calls `atomic_write_text(str(index_path), content)`. Correct.
5. `update_index_entry()` at line 428: calls `atomic_write_text(str(index_path), content)`. Correct.
6. `update_index_entry()` also calls `add_to_index()` on line 423 as fallback, which itself uses `atomic_write_text()`. Correct.

All index write paths now use atomic writes. No remaining `open("w")` calls for index mutation.

### Fix 8 (ARCH-2): Case-insensitive thresholds

**Verdict: PASS**

File: `hooks/scripts/memory_triage.py:526-539`

```python
user_thresholds = {k.upper(): v for k, v in triage["thresholds"].items()}
for cat, default_val in DEFAULT_THRESHOLDS.items():
    raw_val = user_thresholds.get(cat)
```

`DEFAULT_THRESHOLDS` keys are UPPERCASE (line 44-51: "DECISION", "RUNBOOK", etc.). User config keys are normalized to UPPERCASE via `k.upper()`. The lookup `user_thresholds.get(cat)` uses the UPPERCASE category from `DEFAULT_THRESHOLDS`. This means both `"decision": 0.4` and `"DECISION": 0.4` in config will match.

File: `assets/memory-config.default.json:51-58`

Threshold keys are lowercase: `"decision"`, `"runbook"`, etc. This is correct -- the default config uses the "natural" lowercase form, and `load_config()` normalizes on read.

No issues found. The normalization pattern is clean.

### Fix 9 (ARCH-3): Data flow diagram

**Verdict: PASS**

File: `README.md:148-182`

An ASCII data flow diagram exists in the Architecture section. It traces:
1. User presses stop -> memory_triage.py (Phase 0)
2. SKILL.md orchestration (Phase 1: parallel Task subagents)
3. Phase 2: verification subagents
4. Phase 3: main agent -> memory_write.py
5. User can stop (stop_hook_active flag)

The diagram accurately reflects the v5.0.0 architecture. Uses Unicode box-drawing characters for the flow arrows. Readable and correct.

### Fix 10 (BONUS-1): NaN/Inf guard

**Verdict: PASS**

File: `hooks/scripts/memory_triage.py`

1. `import math` at line 20 -- confirmed.
2. In `load_config()` at lines 534-536:
```python
if math.isnan(val) or math.isinf(val):
    continue
```

This rejects NaN and Inf threshold values, falling back to the default. The check happens AFTER `float()` conversion and BEFORE the clamping (`max(0.0, min(1.0, val))`). Correct order -- `float("nan")` would pass the `float()` call but be caught here.

Note: Standard `json.loads()` does NOT accept NaN/Inf by default in CPython. However, some JSON parsers or custom decoders might, and the value could also arrive via programmatic config manipulation. The guard is good defense-in-depth.

### Fix 11 (ADV-5): Context file size cap

**Verdict: PASS**

File: `hooks/scripts/memory_triage.py`

1. `MAX_CONTEXT_FILE_BYTES = 50_000` at line 605 -- confirmed (50 KB).
2. Truncation logic in `write_context_files()` at lines 707-713:
```python
content_bytes = content.encode("utf-8")
if len(content_bytes) > MAX_CONTEXT_FILE_BYTES:
    truncated = content_bytes[:MAX_CONTEXT_FILE_BYTES].decode(
        "utf-8", errors="ignore"
    )
    content = truncated + "\n[Truncated: context exceeded 50KB]"
```

The truncation:
- Measures in bytes (correct for file size limiting)
- Handles multi-byte UTF-8 safely with `errors="ignore"` (avoids partial character at truncation boundary)
- Appends a clear marker so downstream consumers know content was truncated

The 50KB cap is mentioned in README.md line 191: "capped at 50KB". Consistent.

### Fix 12: Updated SKILL.md casing documentation

**Verdict: PASS**

File: `skills/memory-management/SKILL.md:52-56`

The "Important" note reads:

> The `<triage_data>` JSON block emits lowercase category names (e.g., "decision"), matching config keys and memory_candidate.py expectations. The human-readable stderr section may use UPPERCASE for readability, but always use the lowercase `category` value from the JSON for model lookup, CLI calls, and file operations.

This accurately reflects the implementation in `memory_triage.py` where `format_block_message()` emits `cat_lower` in the structured data (line 803) while using UPPERCASE in the human-readable portion (line 786).

## Cross-File Consistency Checks

| Check | Result |
|-------|--------|
| Context file paths: write_context_files() keys == format_block_message() lookup | CONSISTENT (both use cat_lower) |
| Write guard allowlist covers all temp file patterns used in codebase | CONSISTENT (.memory-write-pending, .memory-draft-, .memory-triage-context-) |
| plugin.json version == hooks.json version reference | CONSISTENT (both 5.0.0) |
| Default config threshold keys (lowercase) match load_config() normalization target (UPPERCASE via k.upper()) | CONSISTENT |
| atomic_write_text used by all index mutation functions | CONSISTENT (add_to_index, remove_from_index, update_index_entry) |
| _read_input path validation matches SKILL.md draft path instruction | CONSISTENT (both check /tmp/ prefix and reject ..) |
| MAX_CONTEXT_FILE_BYTES value matches README documentation | CONSISTENT (50KB) |
| SKILL.md casing docs match actual format_block_message() behavior | CONSISTENT |

## Gemini Cross-Validation Summary

Gemini 3 Pro (codereviewer role) independently verified all 12 fixes as **Correctly Implemented** with no issues found. Key observations aligned with this review:

- SEC-4: Confirmed `os.path.realpath()` before prefix check, defense-in-depth `..` check
- Issue #2/H-3: Confirmed consistent lowercase usage across write and read paths
- ARCH-2: Confirmed `k.upper()` normalization pattern
- INFO-3: Confirmed `mkstemp + rename` atomic write pattern used by all index functions
- ADV-5: Confirmed 50KB cap with safe UTF-8 truncation

No discrepancies between this review and Gemini's findings.

## Overall Assessment

**All 12 fixes: PASS**

Every fix is correctly implemented, cross-file references are consistent, and documentation accurately reflects the code behavior. No new issues introduced. The plugin is in good shape for v5.0.0.

**Specific strengths noted:**
1. Defense-in-depth approach in SEC-4 (realpath + explicit .. check + SKILL.md instruction)
2. Clean separation between human-readable UPPERCASE display and machine-parsed lowercase data
3. Proper atomic write pattern with exception safety (cleanup on failure)
4. Consistent normalization direction (user input -> UPPERCASE for matching, lowercase for file operations)
