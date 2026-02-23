# V1 Executability & Practical Review

**Date:** 2026-02-22
**Reviewer:** V1 Executability Reviewer
**Verdict:** PASS WITH NOTES (Action Plan) / FAIL (Guardian Prompt -- 1 blocking issue)

---

## 1. Action Plan: `plan-guardian-conflict-memory-fix.md`

### Verdict: PASS WITH NOTES

#### 1.1 `memory_staging_guard.py` -- Script Correctness

**Stdin JSON parsing**: Correct. Uses `json.load(sys.stdin)` which matches Claude Code's hook protocol. Falls through with `sys.exit(0)` on `JSONDecodeError`, which is the right fail-open behavior for a staging guard (not a security-critical hook).

**Tool name check**: Correct. `input_data.get("tool_name") != "Bash"` correctly filters non-Bash tool calls. Write tool calls will never reach the regex check.

**Deny output format**: The proposed script includes `hookEventName: "PreToolUse"` in the deny response. I verified this is present in the guardian plugin's deny responses (via `_guardian_utils.deny_response()`). However, the existing `memory_write_guard.py` in the same repo does NOT include `hookEventName`. Both formats appear to work with Claude Code (the `memory_write_guard.py` has been functioning correctly without it). Including it is fine and arguably more correct, but the inconsistency with the sibling guard should be noted.

**Regex trace against test inputs:**

| Test Input | Expected | Actual | Status |
|-----------|----------|--------|--------|
| `cat > .claude/memory/.staging/input-decision.json << 'EOFZ'\n{"title": "test"}\nEOFZ` | DENY | DENY | OK |
| `cat > /tmp/test.json << 'EOFZ'\n{"title": "test"}\nEOFZ` | ALLOW | ALLOW | OK |
| `python3 hooks/scripts/memory_write.py --action create ...` | ALLOW | ALLOW | OK |
| `cp /tmp/file .claude/memory/.staging/test.json` | DENY | DENY | OK |
| Write tool to `.claude/memory/.staging/` | ALLOW | ALLOW (tool_name != "Bash") | OK |
| `echo '{"title":"test"}' > .claude/memory/.staging/test.json` | DENY | DENY | OK |
| `tee .claude/memory/.staging/test.json` | DENY | DENY | OK |
| `cat .claude/memory/.staging/test.json` (read) | ALLOW | ALLOW (no `>`) | OK |
| `ls .claude/memory/.staging/` | ALLOW | ALLOW | OK |

All 9 core test cases pass regex verification.

**Regex gap found:** `tee -a .claude/memory/.staging/file.json` (append mode) is NOT caught by the regex `\btee\s+[^\s]*\.claude/memory/\.staging/`. The `[^\s]*` between `tee\s+` and the path matches zero or more non-whitespace characters, but `-a` is followed by a space, which breaks the match. This is a minor gap because:
- Subagents almost never use `tee -a` (they use `cat >` or heredoc)
- The C1 SKILL.md mandate would prevent this at the prompt level
- If needed, the fix is simple: change to `\btee\s+(?:-\w+\s+)*[^\s]*\.claude/memory/\.staging/`

**Severity: Low** -- not a blocking issue.

#### 1.2 hooks.json Modification

The proposed change is purely additive. It adds a new entry to the existing `PreToolUse` array. The existing `Write` matcher entry is unchanged. The JSON structure matches the existing format exactly (same keys: `matcher`, `hooks[]`, `type`, `command`, `timeout`, `statusMessage`). This will apply cleanly.

#### 1.3 SKILL.md Edit

The "Before" text at lines 81-83 matches the actual file content exactly (verified via grep). The replacement text is valid markdown. The edit can be applied cleanly with a simple text replacement.

#### 1.4 pytest Test File

The test file structure is correct:
- Uses `subprocess.run()` to invoke the script as a separate process (correct for hook scripts)
- Passes JSON via `input=` parameter (correct for stdin-based hooks)
- All assertions check for `'"deny"' in out` or `out == ""`, which correctly verifies the two possible outputs
- No import issues -- only `json` and `subprocess` from stdlib
- Test function naming follows pytest conventions

**One minor issue:** The `SCRIPT` path is relative (`"hooks/scripts/memory_staging_guard.py"`), which means pytest must be run from the repo root. This is consistent with the existing test conventions in this repo.

#### 1.5 Estimated Time

45 minutes for C2 (20 min) + C1 (10 min) + tests (15 min) is realistic. The implementation is straightforward and well-specified.

---

## 2. Guardian Prompt: `guardian-heredoc-fix-prompt.md`

### Verdict: FAIL -- 1 blocking issue, 2 notes

#### 2.1 BLOCKING: Arithmetic Bypass in `TestArithmeticBypassPrevention` (Security)

The proposed heredoc detection guard condition is:

```python
if (command[i:i+2] == '<<'
        and command[i:i+3] != '<<<'
        and (i == 0 or command[i-1] in ' \t\n;|&<>(')):
```

The prompt claims this prevents arithmetic shift `(( x << 2 ))` from being misdetected as a heredoc. **This claim is incorrect.**

**Proof by tracing:**

For input `(( x << 2 ))\nrm -rf /`:

1. The `((` does NOT increase `depth` in the existing `split_commands()` parser. The depth tracking code only fires when `(` is preceded by `$`, `<`, or `>` (for `$()`, `<()`, `>()` substitutions). The first `(` at position 0 has no preceding character, and the second `(` at position 1 is preceded by `(`, which is not in `$<>`. So depth stays at 0.

2. At position 5, `<<` is found. `command[4]` is `' '` (space), which IS in the allowed set `' \t\n;|&<>('`.

3. The heredoc detection fires. It parses `2` as the delimiter (bare word, stops at the space before `)`).

4. On the newline at position 13, `_consume_heredoc_bodies` fires and looks for a line matching `2`.

5. `rm -rf /` does NOT match `2`, so it is consumed as heredoc body.

6. The input ends without finding delimiter `2`, and `rm -rf /` has been silently consumed.

**Result:** `rm -rf /` is hidden from the guardian -- **SECURITY BYPASS**.

The `test_arithmetic_shift_not_heredoc` test WILL FAIL because `rm` will not appear in any sub-command. The prompt's own test correctly catches this bug, but the proposed implementation does not pass it.

**Fix required:** The lookbehind guard needs to be strengthened. Options:
- Track `((` pairs separately at depth 0 (a `in_arithmetic` flag)
- Check that the text between `<<` and the newline contains at least one alphabetic character in the delimiter (arithmetic uses digits: `<< 2`, `<< 1`). This is fragile.
- Check for preceding `((` pattern: if the most recent unmatched `((` is open, skip `<<` detection. This would require additional state tracking.

The `let val<<1` case IS correctly handled because `l` is not in the allowed set.

**Severity: BLOCKING** -- this is a security bypass that would fail the prompt's own tests.

#### 2.2 NOTE: `_parse_heredoc_delimiter()` -- `\EOF` (backslash-escaped) not handled

The prompt's "Out of Scope" section explicitly excludes `<<\EOF`. The `_parse_heredoc_delimiter` function would parse `\EOF` as a bare word (backslash is not in the stop set), producing delimiter `\EOF`. This would work correctly for matching because the closing line must also be `\EOF`. So this is not a bug -- just a noted limitation consistent with the prompt's scope.

#### 2.3 NOTE: `<<-EOF` (tab-strip variant)

The implementation correctly handles `<<-`:
- `strip_tabs = command[i:i+3] == '<<-'` correctly detects the tab-strip operator
- `op_len = 3 if strip_tabs else 2` advances past the operator correctly
- `_consume_heredoc_bodies` strips tabs with `cmp_line.lstrip('\t')` when `strip_tabs=True`
- The test `test_heredoc_tab_stripping` verifies `<<-EOF` with `\tEOF`

This is correct.

#### 2.4 `_consume_heredoc_bodies()` -- Insertion Point

The prompt says to insert the two helper functions "right after the end of `split_commands()` and before the 'Layer 1: Protected Path Scan' section comment." This insertion point is clear and unambiguous (between line 246 and line 248 in the current file). The functions are module-level (not nested), which is correct.

#### 2.5 `is_write_command()` Replacement -- Drop-in Compatibility

The proposed replacement has the same function signature (`command: str -> bool`) and return type. The pattern list is identical except each entry becomes a `(pattern, needs_quote_check)` tuple. The behavior is strictly more permissive (allowing `>` inside quotes that was previously flagged) which is the correct direction for reducing false positives.

Verified by simulation: all 6 test cases in `TestWriteCommandQuoteAwareness` pass.

#### 2.6 Fix 3: Layer Reordering Safety

The proposed change moves `split_commands()` before `scan_protected_paths()` in `main()`, then scans `' '.join(sub_commands)` instead of the raw `command`.

**Safety analysis:**
- `scan_protected_paths()` does substring matching with word-boundary regex. Joining sub_commands with spaces preserves all token content.
- The only information lost is separator characters (`;`, `&&`, `||`, `|`, `&`, `\n`), which `scan_protected_paths()` does not use for matching.
- For normal (non-heredoc) commands, the joined text is equivalent to the original for scan purposes.
- For heredoc commands (after Fix 1), the heredoc body is excluded -- which is exactly the desired behavior.

**One subtlety:** The existing code at line 1012 logs `scan_reason`. The proposed replacement preserves this logging. The duplicate `sub_commands = split_commands(command)` removal is correctly noted.

**Assessment:** The reorder is safe. No security guarantees are broken for non-heredoc commands, and heredoc body false positives are eliminated.

#### 2.7 TDD Order

The prompt correctly specifies tests first (Step 1), then implementation (Steps 2-4), then verification (Step 5). However, Step 2 (Fix 2, quote-aware `is_write_command`) is ordered before Step 3 (Fix 1, heredoc-aware `split_commands`). The rationale is "simplest fix first, doesn't affect line numbers." This is pragmatically correct because Fix 2 modifies a function body (no line count change for other sections), while Fix 1 adds new functions and modifies `split_commands` (which shifts line numbers for everything below).

#### 2.8 Precision of Code Modifications

The prompt uses semantic landmarks ("search for `def split_commands`", "look for `if c == '\n':`") rather than line numbers. This is the correct approach since line numbers shift during editing. All landmarks are unique and findable.

#### 2.9 Version Bump

Step 5 mentions "bump to 1.1.0" -- but the prompt does not specify where the version is stored. A fresh session would need to search for a manifest or version file. This is imprecise but non-blocking (the instruction says "if a plugin manifest or version file exists").

#### 2.10 `test_bypass_v2.py` Compatibility

The prompt mentions this file and expects the heredoc test at lines 142-146 to now pass. This file uses a standalone test runner (not pytest), which is correctly noted. The import path uses `_bootstrap` for path setup, which is different from the proposed test file's `sys.path.insert`. Both approaches work.

---

## 3. Practical Concerns

### 3.1 Dependencies

- **Action Plan (`memory_staging_guard.py`)**: stdlib only (json, re, sys). No dependency issues.
- **Guardian Prompt**: No new dependencies. `_is_inside_quotes()` already exists in the codebase. All new code is stdlib-only.
- **Tests**: pytest for both repos. Already present in requirements.

### 3.2 File Paths

- Action plan uses relative paths consistent with the repo convention (e.g., `hooks/scripts/memory_staging_guard.py`).
- Guardian prompt correctly identifies the working directory as `/home/idnotbe/projects/claude-code-guardian/`.
- All file references are resolvable from their respective repo roots.

### 3.3 Ordering Dependencies Between Fixes

The action plan documents C2 -> C1 order (hard guard first, then SKILL.md). These two fixes are independent and can be deployed in either order. The plan correctly notes this and provides justification for the chosen order.

The guardian prompt's Fix 1/2/3 have a dependency: Fix 3 depends on Fix 1 (Layer reordering only works correctly if `split_commands` excludes heredoc bodies). Fix 2 is independent. This dependency IS correctly documented ("Step 4... After Fix 1, split_commands excludes heredoc bodies").

### 3.4 Cross-Repo Dependency

The action plan correctly identifies that Plan #4 (memory-side) is independent of the guardian-side fixes. The memory-side fixes eliminate the false positive trigger, while the guardian-side fixes address the root parsing limitation. Both can be deployed independently.

### 3.5 Estimated Time

- Action Plan: 45 minutes -- realistic.
- Guardian Prompt: No explicit time estimate, but the work is substantial (3 code changes + tests). A realistic estimate would be 60-90 minutes for a Claude Code session.

---

## 4. Summary of Findings

### Blocking Issues

| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | Guardian Prompt | `(( x << 2 ))` arithmetic bypass -- the lookbehind guard `command[i-1] in ' \t\n;|&<>('` does not prevent heredoc detection inside `((...))` because `((` does not increase parser depth. The prompt's own `test_arithmetic_shift_not_heredoc` test will FAIL. | **BLOCKING** |

### Non-Blocking Issues

| # | File | Issue | Severity |
|---|------|-------|----------|
| 2 | Action Plan | `tee -a .claude/memory/.staging/file` not caught by regex (flag before path breaks `[^\s]*` match) | Low |
| 3 | Action Plan | `hookEventName` field present in staging guard but absent from sibling `memory_write_guard.py` -- inconsistency (both work) | Informational |
| 4 | Guardian Prompt | No time estimate provided | Informational |
| 5 | Guardian Prompt | Version bump location not specified | Low |

### Suggested Improvements

1. **Guardian Prompt (blocking fix):** Add `((` tracking to `split_commands()`. Simplest approach: detect `((` at depth 0 and set `in_arithmetic = True`, decrementing when `))` is found. Skip heredoc detection when `in_arithmetic` is true. Alternatively, require the heredoc delimiter to contain at least one alphabetic character (this would reject `<< 2` but could be fragile for unusual delimiter names like `123`).

2. **Action Plan (tee -a):** Adjust the tee regex to `\btee\s+(?:-\w+\s+)*[^\s]*\.claude/memory/\.staging/` to handle optional flags. This is low priority but easy.

3. **Action Plan (consistency):** Either add `hookEventName` to `memory_write_guard.py` as well, or remove it from the staging guard, to maintain consistency within the plugin.

---

## 5. Final Verdicts

| Deliverable | Verdict | Can Execute? |
|------------|---------|-------------|
| Action Plan (`plan-guardian-conflict-memory-fix.md`) | **PASS WITH NOTES** | Yes -- all code runs correctly, regex is verified, hooks.json edit is additive, SKILL.md edit matches. Minor `tee -a` gap is non-critical. |
| Guardian Prompt (`guardian-heredoc-fix-prompt.md`) | **FAIL** | No -- the arithmetic bypass guard is insufficient. `(( x << 2 ))\nrm -rf /` would hide `rm -rf /` from the guardian. The prompt's own security test catches this, so the implementor would hit the failure, but the prompt does not provide a correct solution. Must be revised before execution. |
