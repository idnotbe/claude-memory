# V2 Dry-Run Execution Review

**Date:** 2026-02-22
**Reviewer:** Opus 4.6 (V2 dry-run execution reviewer)
**Verdict:** PASS WITH NOTES (Action Plan) / FAIL (Guardian Prompt)

---

## Dry-Run 1: Action Plan Execution (`plan-guardian-conflict-memory-fix.md`)

**Overall verdict: PASS WITH NOTES**

### Step 1: Create `memory_staging_guard.py`

**1-1. Compile check:** PASS
- `python3 -m py_compile` passes cleanly on the proposed script.

**1-2. Edge case handling:**
- **Empty stdin:** `json.load(sys.stdin)` raises `json.JSONDecodeError`, caught, exits 0. PASS.
- **Malformed JSON:** Same path. PASS.
- **Missing `tool_input` key:** `.get("tool_input", {})` returns `{}`, `.get("command", "")` returns `""`, regex finds no match, exits 0. PASS.
- **Missing `command` key:** Same as above. PASS.
- **Non-Bash tool_name:** Short-circuits at line 97 (`tool_name != "Bash"`), exits 0. PASS.

**1-3. Regex trace against test matrix:**

| Test | Command | Expected | Regex Match? | Verdict |
|------|---------|----------|-------------|---------|
| T1 | `cat > .claude/memory/.staging/test.json << 'EOF'` | DENY | YES -- first branch `(?:cat\|echo\|printf)\s+[^\|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/` matches | PASS |
| T2 | `echo '{}' > .claude/memory/.staging/test.json` | DENY | YES -- same first branch | PASS |
| T3 | `echo '{}' \| tee .claude/memory/.staging/test.json` | DENY | YES -- second branch `\btee\s+[^\s]*\.claude/memory/\.staging/` matches | PASS |
| T4 | `cp /tmp/test.json .claude/memory/.staging/test.json` | DENY | YES -- third branch `(?:cp\|mv\|install\|dd)\s+.*\.claude/memory/\.staging/` matches | PASS |
| T5 | Write tool to `.staging/` | ALLOW | N/A -- tool_name is "Write", not "Bash", exits at line 97 | PASS |
| T6 | `cat .claude/memory/.staging/test.json` | ALLOW | NO -- first branch requires `>` after the `cat` args, `cat .claude...` has no `>` | PASS |
| T7 | `ls .claude/memory/.staging/` | ALLOW | NO -- `ls` is not in any pattern group | PASS |
| T8 | `cat > /tmp/test.json << 'EOF'` | ALLOW | NO -- path after `>` is `/tmp/test.json`, not `.claude/memory/.staging/` | PASS |
| T9 | `python3 hooks/scripts/memory_write.py ...` | ALLOW | NO -- `python3` is not in any pattern group | PASS |
| T10 | Recovery after T1 deny | OK | Deny message includes Write tool usage guidance | PASS |

**All 10 test cases trace correctly.**

**1-4. Non-blocking note:** The `hookEventName` field is present in the staging guard output but absent from the sibling `memory_write_guard.py`. This is a style inconsistency noted in a prior review (V1). Both work correctly. Consider adding `hookEventName` to `memory_write_guard.py` for consistency, or removing it from the staging guard.

### Step 2: Modify `hooks.json`

**Verification:**
- Current `hooks.json` has 4 hook categories: Stop, PreToolUse, PostToolUse, UserPromptSubmit.
- The proposed change adds one entry to the `PreToolUse` array.
- After the change, `PreToolUse` would have 2 entries: `Write` matcher (existing) and `Bash` matcher (new).
- No duplicate entries. All existing hooks preserved.
- **JSON validity:** The proposed full `PreToolUse` section is valid JSON. Verified programmatically.
- **Result: PASS**

### Step 3: Modify SKILL.md

**Before text match:**
The action plan specifies lines 81-83 as the "Before" text:
```
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

Actual content at lines 81-83 of `skills/memory-management/SKILL.md`:
```
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

**Exact match confirmed.** The replacement text is valid markdown with proper blockquote continuation and fenced code blocks. The "After" text replaces 3 lines with a 12-line block (approximately), which is a clean expansion within the blockquote context.

**Result: PASS**

### Step 4: Tests

**Compile check on proposed `tests/test_memory_staging_guard.py`:**
- Uses only `json` and `subprocess` from stdlib -- no import issues.
- `SCRIPT = "hooks/scripts/memory_staging_guard.py"` -- relative path. Tests would need to run from the repo root (`cd /home/idnotbe/projects/claude-memory && pytest tests/`). This is the existing convention for the repo (other tests use similar relative paths).
- All 9 test method names are valid Python identifiers (snake_case, no special characters).
- The `run_guard()` helper properly constructs JSON and pipes it to the script.
- **All tests verified to produce correct results** via regex tracing above.

**Non-blocking note:** The SCRIPT path is relative, meaning tests must be run from the repo root. This matches the existing test convention (`pytest tests/ -v` from repo root), but could be made more robust with an absolute path using `__file__` resolution.

**Result: PASS**

---

## Dry-Run 2: Guardian Prompt Execution (`guardian-heredoc-fix-prompt.md`)

**Overall verdict: FAIL -- 1 critical blocking issue**

### Step 1: Create test file (`tests/test_heredoc_fixes.py`)

**Import verification:**
- The test file uses `sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "scripts"))`.
- From `tests/test_heredoc_fixes.py`, `parent.parent` = repo root, so this resolves to `<repo>/hooks/scripts/`.
- However, the guardian repo uses `conftest.py` which imports `_bootstrap`, which already adds `hooks/scripts/` to `sys.path`. So the explicit `sys.path.insert` in the test file is redundant but harmless.
- `from bash_guardian import split_commands, is_write_command, scan_protected_paths` -- these three are public functions, import would succeed.
- `from bash_guardian import _parse_heredoc_delimiter` in `TestParseHeredocDelimiter` -- this function does not exist yet (TDD). Tests importing it would fail at collection time with `ImportError`, not at runtime. This means ALL tests in the file would fail to collect, not just the `TestParseHeredocDelimiter` class.

**Blocking issue for TDD baseline:** The `_parse_heredoc_delimiter` import in `TestParseHeredocDelimiter` is a module-level import inside each test method (`from bash_guardian import _parse_heredoc_delimiter`). Wait -- re-reading the test code, the import is inside each test method, not at module level:
```python
def test_bare_word(self):
    from bash_guardian import _parse_heredoc_delimiter
```
This means the import happens at test execution time, not collection time. So only `TestParseHeredocDelimiter` tests would fail with `ImportError`, while other test classes would be collected and fail for their own reasons. This is **correct TDD behavior**.

**Would all tests fail initially?**
- `TestHeredocSplitting`: Most tests would fail because `split_commands()` splits on newlines, producing multiple sub-commands. FAIL (expected for TDD).
- `TestArithmeticBypassPrevention`: Both tests would PASS initially because without heredoc detection, `split_commands` splits on `\n` normally, keeping `rm -rf /` visible. This is **correct initial state** -- these tests verify no regression.
- `TestParseHeredocDelimiter`: FAIL with `ImportError` (function doesn't exist). Expected for TDD.
- `TestWriteCommandQuoteAwareness`: `test_arrow_in_double_quotes_not_write`, `test_score_comparison_in_quotes_not_write`, `test_git_commit_message_with_gt` would FAIL (current `is_write_command` has no quote awareness). `test_real_redirection_still_detected`, `test_tee_still_detected`, `test_truncation_outside_quotes_detected` would PASS (existing behavior). Mixed results, expected.
- `TestScanProtectedPathsHeredocAware`: `test_env_in_heredoc_body_not_flagged` would FAIL (current split doesn't strip heredoc bodies). `test_env_in_command_still_present` would PASS. Expected.

**Result: PASS (test file structure is sound for TDD)**

### Step 2: Fix `is_write_command()` -- Make it quote-aware

**Current function location:** Line 635 in `bash_guardian.py`.
**Replacement analysis:**
- Same function name: `is_write_command`
- Same parameters: `(command: str) -> bool`
- Same return type: `bool`
- Clean 1:1 replacement.

**Post-change test results (verified by execution):**
- All 6 `TestWriteCommandQuoteAwareness` tests: **PASS**
- `_is_inside_quotes` is already defined at line 403 and is accessible.

**Result: PASS**

### Step 3: Fix `split_commands()` -- Add heredoc awareness

**CRITICAL BLOCKING ISSUE: Arithmetic shift bypass**

The proposed heredoc detection guard is:
```python
if (command[i:i+2] == '<<'
        and command[i:i+3] != '<<<'
        and (i == 0 or command[i-1] in ' \t\n;|&<>(')):
```

The prompt states: *"This prevents `x<<2` (arithmetic shift) from being misdetected as a heredoc, because `x` is a word character not in the allowed set."*

This guard is **insufficient for `(( x << 2 ))`**:

1. In `(( x << 2 ))\nrm -rf /`, the `<<` at position 5 is preceded by a **space** character.
2. Space IS in the allowed set `' \t\n;|&<>('`.
3. The `((`  construct does NOT increment `depth` because the depth tracking only triggers when `(` is preceded by `$`, `<`, or `>` -- not when preceded by another `(` at depth 0.
4. Therefore, `<<` inside `(( ... ))` **IS detected as heredoc** at depth 0.
5. `_parse_heredoc_delimiter` would parse `2` as the delimiter.
6. `_consume_heredoc_bodies` would then consume `rm -rf /` as the heredoc body, searching for a line equal to `2`.
7. **Result: `rm -rf /` is HIDDEN from the guardian.** This is a security bypass.

**Verified by execution:**
```
split_commands("(( x << 2 ))\nrm -rf /") => ['(( x << 2 ))']
# rm -rf / is consumed as heredoc body -- SECURITY BYPASS
```

The test `test_arithmetic_shift_not_heredoc` from the prompt's own test file **FAILS** with this implementation.

**Mitigation options (for the prompt author to consider):**
1. Add `(( ... ))` tracking to the depth counter (bash arithmetic context).
2. Require `<<` to be preceded by a command word position (after `|`, `;`, `&&`, `||`, or at start of line), not just any whitespace.
3. Check that the character sequence before `<<` matches a command pattern (e.g., a command word like `cat`, `tee`, etc.), not arbitrary whitespace.
4. Track `((` as a depth-incrementing construct (similar to `$(`).

**The `let val<<1` test PASSES** because `l` (from `val`) is not in the allowed set.

**Other test results (excluding the arithmetic bypass):**
All other heredoc tests pass correctly:
- Basic heredoc: PASS
- Quoted heredoc: PASS
- Heredoc with redirection: PASS
- Tab-stripping: PASS
- Here-string exclusion: PASS
- Multiple heredocs: PASS
- Heredoc followed by command: PASS (produces 2 sub-commands)
- Arrows in body: PASS
- Semicolon in body: PASS
- Double-quoted delimiter: PASS
- Unterminated heredoc: PASS
- Real memory plugin command: PASS
- `.env` in heredoc body not flagged: PASS

**Helper function placement:** The prompt specifies placing `_parse_heredoc_delimiter` and `_consume_heredoc_bodies` as module-level functions after `split_commands()` and before the "Layer 1: Protected Path Scan" section comment. This is at line 246 (after `return [cmd for cmd in sub_commands if cmd]`) and before line 248 (`# Layer 1: Protected Path Scan`). This is a clean insertion point.

**Result: FAIL (critical security bypass in arithmetic context)**

### Step 4: Reorder Layer 1 after Layer 2 in `main()`

**Current order (lines 1008-1015):**
```python
# ========== Layer 1: Protected Path Scan ==========
scan_verdict, scan_reason = scan_protected_paths(command, config)
...
# ========== Layer 2+3+4: Command Decomposition + Path Analysis ==========
sub_commands = split_commands(command)
```

**Proposed reorder:**
1. Move `sub_commands = split_commands(command)` before Layer 1.
2. Change `scan_protected_paths(command, config)` to `scan_protected_paths(' '.join(sub_commands), config)`.
3. Remove the duplicate `sub_commands = split_commands(command)` from the old Layer 2+3+4 location.

**Variable dependency check:**
- `sub_commands` is first used at line 1018 (`for sub_cmd in sub_commands:`). Moving its computation earlier has no dependency conflicts.
- `all_paths` initialization at line 1016 remains in its current position.
- `scan_text = ' '.join(sub_commands)` is a new variable, used only for the `scan_protected_paths` call.
- No circular dependencies. Clean reorder.

**Semantic correctness of `' '.join(sub_commands)`:**
- After heredoc-aware splitting, heredoc body content is consumed and excluded from sub-commands.
- Joining with spaces preserves word boundaries for the regex-based `scan_protected_paths`.
- Edge case: multi-word sub-commands joined with single space could merge tokens at boundaries. Example: `['cat .env', 'echo hi']` -> `'cat .env echo hi'`. The `.env` token boundaries are preserved (space before and after). No false negative introduced.

**Result: PASS (assuming Step 3 is fixed)**

### Step 5: Final verification

**Compile check:** Would pass if the code is syntactically correct (all proposed additions are syntactically valid Python).

**Test suite:**
- `test_heredoc_fixes.py`: 1 test would FAIL (`test_arithmetic_shift_not_heredoc`) due to the security bypass issue.
- Existing tests: The `is_write_command` change preserves all existing behavior (the new quote check only SKIPS patterns that were previously matching, reducing false positives). `split_commands` changes only affect newline splitting (adding heredoc consumption), which should not affect commands without heredocs. Existing tests should pass.
- `test_bypass_v2.py` (standalone): The heredoc test at lines 142-146 would now PASS (this is a positive change).

**Version bump:** The prompt mentions bumping to 1.1.0. There is no version file checked in this review.

**Result: CONDITIONAL PASS (blocked by Step 3 arithmetic bypass)**

---

## Summary of Findings

### Blocking Issues

| # | Deliverable | Issue | Severity | Details |
|---|------------|-------|----------|---------|
| 1 | Guardian Prompt | Arithmetic shift bypass: `(( x << 2 ))\nrm -rf /` hides `rm -rf /` from guardian | **CRITICAL** | The lookbehind guard `command[i-1] in ' \t\n;|&<>('` does not prevent `<<` detection inside `(( ... ))` because space is in the allowed set and `((` does not increment depth. The prompt's own `test_arithmetic_shift_not_heredoc` test fails. |

### Non-Blocking Issues

| # | Deliverable | Issue | Severity | Details |
|---|------------|-------|----------|---------|
| 1 | Action Plan | `hookEventName` inconsistency between staging guard and write guard | Informational | Both work; consider aligning for consistency |
| 2 | Action Plan | Test SCRIPT path is relative, requires running from repo root | Low | Matches existing convention but could be more robust |
| 3 | Guardian Prompt | TDD baseline: `TestArithmeticBypassPrevention` tests pass initially (before implementation), which is correct but could confuse someone expecting "all tests fail" | Informational | The prompt says "Most tests should fail" which is accurate -- these 2 are the exception |
| 4 | Guardian Prompt | Redundant `sys.path.insert` in test file (conftest.py already handles it) | Informational | Harmless; defensive coding |
| 5 | Guardian Prompt | The prompt says to place helper functions "right after the end of `split_commands()`" but the exact insertion point (line 246 vs 247) could be ambiguous if there's blank lines | Low | Semantic landmark is clear enough |

### Specific Line-Level Findings

**Action Plan -- `memory_staging_guard.py`:**
- Line 93 (`except json.JSONDecodeError`): Correctly handles malformed JSON. Note: does not catch `EOFError` which the sibling `memory_write_guard.py` catches at its line 27. Consider adding `EOFError` to the catch for robustness (empty stdin from a pipe close can raise `EOFError` in some Python versions).

**Guardian Prompt -- `bash_guardian.py` heredoc detection (proposed line within `split_commands`):**
- The guard condition `(i == 0 or command[i-1] in ' \t\n;|&<>(')` is the root cause of the blocking issue. The `(` character is correctly included to allow `<(cat <<EOF` process-substitution heredocs, but `((` arithmetic is not tracked as a depth-incrementing construct. Fix options:
  - Track `((` as depth (complex, changes parser semantics)
  - After detecting `<<`, look backward past whitespace to see if the context is `(( ... ))` arithmetic
  - Require `<<` to follow a command-word position (e.g., preceded by `|`, `;`, line-start, not just any whitespace)

**Guardian Prompt -- `_consume_heredoc_bodies`:**
- Line `if i < len(command): i += 1` -- correct handling of newline advancement.
- `cmp_line.rstrip('\r')` -- correctly handles CRLF line endings.
- Unterminated heredoc fallthrough: correctly consumes to end of string (fail-closed behavior).

---

## Conclusion

The **Action Plan** (memory-side fix) is **ready for execution**. All steps trace correctly, the regex handles all test cases, the hooks.json modification is valid, and the SKILL.md text matches exactly. Minor notes are non-blocking.

The **Guardian Prompt** has a **critical security flaw**: the heredoc detection lookbehind guard fails to prevent `(( x << 2 ))` arithmetic from being misdetected as a heredoc, allowing a command-hiding bypass. The prompt's own security test (`test_arithmetic_shift_not_heredoc`) would fail. This must be fixed before the guardian prompt can be used.
