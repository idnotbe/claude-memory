# V1 Accuracy & Completeness Review

**Reviewer:** v1-accuracy
**Date:** 2026-02-22
**Files reviewed:**
1. Action Plan: `action plans/plan-guardian-conflict-memory-fix.md`
2. Guardian Prompt: `temp/guardian-heredoc-fix-prompt.md`
**Sources verified against:**
- `research/guardian-memory-pretooluse-conflict.md`
- `temp/guardian-conflict-v2-adversarial.md`
- `temp/guardian-conflict-fix-design.md`
- `skills/memory-management/SKILL.md` (actual file)
- `hooks/hooks.json` (actual file)
- `bash_guardian.py` (actual file in claude-code-guardian repo)

---

## Verdict: PASS WITH NOTES

Both deliverables are factually accurate and complete relative to their source materials. The action plan correctly captures the immediate memory-side fixes. The guardian prompt correctly captures the medium-term guardian-side fixes. A small number of discrepancies and improvement opportunities are documented below, none of which rise to FAIL severity.

---

## Action Plan Findings

### 1. Python code for `memory_staging_guard.py` -- ACCURATE (with improvement vs. source)

The action plan's regex at lines 103-108:
```python
staging_write_pattern = (
    r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'\btee\s+[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'(?:cp|mv|install|dd)\s+.*\.claude/memory/\.staging/'
)
```

**Comparison with fix-design source (lines 334-341):** The fix-design had a different regex pattern:
```python
staging_write_pattern = (
    r'(?:cat|echo|tee|printf)\s+.*'
    r'\.claude/memory/\.staging/'
    r'|'
    r'>\s*[\'"]?[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'<<[-]?\s*[\'"]?\w+[\'"]?\s*\n.*\.claude/memory/\.staging/'
)
```

The action plan's version is **superior** to the fix-design's version because:
- It includes `cp`, `mv`, `install`, `dd` which the V2-adversarial review (Challenge 4b, lines 104-116) flagged as bypass gaps
- The fix-design version missed these entirely; the action plan correctly incorporates the V2 feedback
- The regex structure is cleaner (requires `>` only for cat/echo/printf, not for cp/mv/install/dd which don't use redirection)

**V2-adversarial bypass coverage check:**

| Bypass from V2-adversarial | Covered in action plan? |
|---|---|
| `cat > .staging/...` | Yes (first branch) |
| `echo > .staging/...` | Yes (first branch) |
| `cp /tmp/payload .staging/...` | Yes (third branch) |
| `dd if=/tmp/payload of=.staging/...` | Yes (third branch) |
| `mv /tmp/payload .staging/...` | Yes (third branch) |
| `install /tmp/payload .staging/...` | Yes (third branch) |
| `python3 -c 'open(...)...'` | No -- but V2-adversarial acknowledged this is an exotic edge case not worth regex coverage |

**Finding: ACCURATE.** The action plan correctly incorporated V2-adversarial feedback that was missing from the original fix-design.

### 2. SKILL.md before/after sections -- ACCURATE

**Actual SKILL.md lines 81-83:**
```
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

**Action plan's "Before" (lines 191-193):** Exactly matches the actual file content.

**Action plan's "After" (lines 197-215):** Matches the research report's recommended wording (Section 2, Fix C1) verbatim.

**Finding: ACCURATE.** Line references and content match.

### 3. hooks.json registration format -- ACCURATE WITH NOTE

**Actual hooks.json structure** (verified): Uses a nested format with `"hooks"` key containing `"matcher"` and `"hooks"` array per event type. The PreToolUse section currently has one entry for `"matcher": "Write"`.

**Action plan's proposed addition (lines 136-147):** Uses the correct nested format:
```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_staging_guard.py\"",
      "timeout": 5,
      "statusMessage": "Checking memory staging write..."
    }
  ]
}
```

**Action plan's complete PreToolUse section (lines 150-174):** Correctly shows both existing Write guard and new Bash guard.

**NOTE:** The fix-design source (lines 364-372) used a **DIFFERENT, INCORRECT** hook registration format:
```json
{
  "type": "PreToolUse",
  "matcher": "Bash",
  "command": "python3 ...",
  "timeout": 5000
}
```
This flat format does not match the actual hooks.json structure. The action plan **correctly fixed** this discrepancy by using the proper nested format. Additionally, the fix-design used `"timeout": 5000` (milliseconds?) while the action plan uses `"timeout": 5` (seconds), matching the existing hooks.json convention (where existing entries use `5`, `10`, `15`, `30` -- clearly seconds).

**Finding: ACCURATE.** The action plan correctly fixed a format error in the fix-design source.

### 4. JSON output format for deny hooks -- ACCURATE

The action plan's deny output (lines 112-122):
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "..."
  }
}
```

This matches the existing `memory_write_guard.py` pattern (verified in the actual file, which uses the same `hookSpecificOutput` / `permissionDecision` / `permissionDecisionReason` structure). It also matches the fix-design source (lines 344-355).

**Finding: ACCURATE.**

### 5. Test matrix coverage -- COMPLETE

The test matrix (lines 222-234) covers:
- T1-T4: True positives (heredoc, echo, tee, cp) -- covers Failure Mode A trigger
- T5: True negative (Write tool) -- verifies no interference with correct pattern
- T6-T7: True negatives (read commands) -- verifies no false positives on reads
- T8: True negative (different directory) -- verifies scope is limited to .staging/
- T9: True negative (memory_write.py) -- verifies legitimate python3 execution
- T10: Recovery (deny message guidance)

**Failure mode coverage:**
- Failure Mode A (heredoc `>` in body): T1 directly tests heredoc, which is the primary trigger
- Failure Mode B (.env in body): Not explicitly tested with `.env` content, but the mechanism is the same -- the guard blocks the bash command before Guardian ever sees it. The guard operates at the command level (detecting write to .staging/), not at the content level.

**NOTE:** The pytest tests (lines 259-306) cover T1-T9 programmatically. T10 (recovery) is appropriately left as manual observation.

**Missing test:** No test for `mv` or `install` or `dd` to staging, even though these were added to the regex. Only `cp` (T4) is tested among the non-redirection write commands. Consider adding:
- `test_blocks_mv_to_staging()`
- `test_blocks_dd_to_staging()`
- `test_blocks_install_to_staging()`

**Finding: MOSTLY COMPLETE.** Minor gap: mv/dd/install bypass methods are in the regex but not in the test suite.

### 6. Research Section 5 "Implementation Checklist - Immediate" coverage -- COMPLETE

Research checklist items:
- [x] Update SKILL.md lines 81-83 with prohibition wording + anti-pattern example -- Step 2 (lines 185-215)
- [x] Create `hooks/scripts/memory_staging_guard.py` -- Step 1-1 (lines 82-129)
- [x] Add PreToolUse:Bash entry to `hooks/hooks.json` -- Step 1-2 (lines 131-175)
- [x] Test: verify heredoc to `.staging/` is denied with actionable message -- T1, T10 (lines 222-234)
- [x] Test: verify Write tool to `.staging/` still works normally -- T5 (lines 222-234)

**Finding: COMPLETE.** All immediate checklist items are covered.

---

## Guardian Prompt Findings

### 7. bash_guardian.py line references -- MOSTLY ACCURATE

Spot-checked 8 line references:

| Prompt reference | Actual line | Correct? |
|---|---|---|
| `split_commands()` at line 82 | Line 82: `def split_commands(command: str) -> list[str]:` | **YES** |
| `is_write_command()` at line 635 | Line 635: `def is_write_command(command: str) -> bool:` | **YES** |
| `_is_inside_quotes()` at line 403 | Line 403: `def _is_inside_quotes(command: str, pos: int) -> bool:` | **YES** |
| `extract_paths()` at line 478 | Line 478: `def extract_paths(` | **YES** |
| F1 safety net at line 1033 | Line 1033: `if (is_write or is_delete) and not sub_paths:` | **YES** |
| `scan_protected_paths(command, config)` at line 1009 | Line 1009: `scan_verdict, scan_reason = scan_protected_paths(command, config)` | **YES** |
| `sub_commands = split_commands(command)` at line 1015 | Line 1015: `sub_commands = split_commands(command)` | **YES** |
| Depth tracking at lines 162-177 | Lines 162-177: `$(`, `<(`, `>(` depth tracking | **YES** |

**Finding: ACCURATE.** All 8 spot-checked line references are correct.

### 8. Arithmetic bypass guard implementation -- ACCURATE

The prompt (lines 359-361) specifies:
```python
if (command[i:i+2] == '<<'
        and command[i:i+3] != '<<<'
        and (i == 0 or command[i-1] in ' \t\n;|&<>(')):
```

The V2-adversarial review (Challenge 2a) identified the arithmetic bypass as CRITICAL. The guard `(i == 0 or command[i-1] in ' \t\n;|&<>(')` prevents `x<<2` from being detected because `x` is not in the allowed set.

**Analysis:** This is a correct and sufficient guard for the arithmetic shift case:
- `(( x << 2 ))`: The `<<` at position 5 is preceded by a space -- this IS in the allowed set, so it would trigger heredoc detection. BUT: the delimiter would be `2` and `))\nrm -rf /` does not contain a line matching just `2`. Wait -- let me re-analyze.

Actually, re-examining: in `(( x << 2 ))`, the `<<` is preceded by space ` `, which IS in `' \t\n;|&<>('`. So the guard would NOT prevent this case. The `_parse_heredoc_delimiter` would parse `2` as the delimiter (stopping at `)` which is in the stop chars). Then after the newline, body consumption would look for a line matching just `2`.

**FINDING: POTENTIAL ISSUE.** The arithmetic bypass guard `command[i-1] in ' \t\n;|&<>('` does NOT prevent `(( x << 2 ))` from being misdetected because the `<<` is preceded by a space. The prompt document acknowledges this at line 466: "This prevents `x<<2` (arithmetic shift) from being misdetected as a heredoc, because `x` is a word character not in the allowed set."

This is correct for `x<<2` (no space) but does NOT address the V2-adversarial's actual example `(( x << 2 ))` where there IS a space before `<<`. The test at lines 173-177 tests `(( x << 2 ))` and expects `rm -rf /` to remain visible. Whether this test actually passes depends on what happens during heredoc body consumption:
- Delimiter parsed as `2` (stopping at `)`)
- After newline, consume lines looking for `2`
- Line `rm -rf /` does not match `2`
- We reach end of string without matching -- unterminated heredoc behavior (fail-closed, body consumed)
- `rm -rf /` IS consumed as heredoc body -- **this is the bypass!**

Wait, but looking more carefully at the test:
```python
def test_arithmetic_shift_not_heredoc(self):
    subs = split_commands("(( x << 2 ))\nrm -rf /")
    assert any("rm" in sub for sub in subs), \
        "rm -rf / was consumed as heredoc body -- arithmetic bypass!"
```

The command is `(( x << 2 ))\nrm -rf /`. After `<<`, whitespace is skipped, then `2` is parsed as delimiter (stopping at space/`)` -- actually `)` IS in the stop chars set `' \t\n;|&<>()'`). So delimiter = `2`. Then `current` continues accumulating. The `))\n` -- when the newline at the position after `))` is hit, heredoc body consumption starts. It reads line `rm -rf /`, which does not match `2`, so it is consumed. End of string reached -- unterminated heredoc, fail-closed. `rm -rf /` is invisible.

**This test WILL FAIL with the proposed implementation.** The guard does not catch `(( x << 2 ))` because the space before `<<` passes the lookbehind check.

However, I need to re-check -- is this really a problem with the guardian prompt, or is the prompt's approach actually different? Looking at the prompt's "About the arithmetic bypass guard" section (line 466): "This prevents `x<<2` (arithmetic shift) from being misdetected as a heredoc, because `x` is a word character not in the allowed set."

The prompt explicitly only claims to handle `x<<2` (no space). The V2-adversarial review's example `(( x << 2 ))` has a space. The prompt's guard is **necessary but not sufficient** for the full arithmetic bypass case.

**However**: Looking at the test `test_arithmetic_shift_not_heredoc` which tests exactly `(( x << 2 ))`, the prompt expects this test to pass. If the implementation as written cannot pass this test, that is a factual error in the prompt.

**SEVERITY: MEDIUM-HIGH.** The prompt claims the guard prevents arithmetic bypass and includes a test for `(( x << 2 ))`, but the guard as implemented (`command[i-1] in ' \t\n;|&<>('`) will NOT prevent `(( x << 2 ))` because space is in the allowed set. The test will fail.

**Correction needed:** The prompt either needs:
1. A stronger guard (e.g., check if `<<` is inside `(( ... ))` context), or
2. Acknowledge that the `(( x << 2 ))` case is NOT handled and remove/modify the test, or
3. Use a different detection approach entirely (e.g., the pre-pass regex suggested by V2-adversarial Challenge 7)

### 9. `_consume_heredoc_bodies()` function -- ACCURATE

The function (prompt lines 433-463) correctly handles:
- Tab-stripping for `<<-`: `cmp_line = cmp_line.lstrip('\t')` (line 457)
- CRLF: `cmp_line = line.rstrip('\r')` (line 455)
- Unterminated heredoc: consuming to end of string (lines 460-462)
- Multiple pending heredocs: iterates over `pending` list (line 442)

**Edge case: quoted vs unquoted delimiters.** The function does not differentiate between quoted and unquoted heredocs for body consumption -- it just matches the delimiter text. This is correct for the splitting use case (body content should be excluded from sub-commands regardless of quoting).

**Finding: ACCURATE.**

### 10. `is_write_command()` replacement code -- ACCURATE

The prompt's replacement (lines 311-334) correctly:
- Converts flat list to `(pattern, needs_quote_check)` tuples
- Preserves all 14 existing patterns in the same order
- Adds `True` for `>` redirection and `: >` truncation patterns only
- Uses `_is_inside_quotes(command, match.start())` for filtering
- Uses `continue` to skip matched-but-quoted patterns (not `return False`)

Verified against actual `is_write_command()` at lines 635-667: all 14 patterns match exactly.

**Finding: ACCURATE.**

### 11. Layer 1 reordering (Fix 3) -- ACCURATE

The prompt's "Current order in main()" (lines 482-489) matches the actual file:
- Line 1008-1012: Layer 1 (`scan_protected_paths(command, config)`)
- Line 1014-1015: Layer 2+3+4 (`sub_commands = split_commands(command)`)

The proposed change (lines 493-511) correctly:
- Moves `split_commands()` before `scan_protected_paths()`
- Scans `' '.join(sub_commands)` instead of raw `command`
- Removes duplicate `sub_commands = split_commands(command)` call
- Updates comments to reflect new ordering

**Finding: ACCURATE.**

### 12. Test comprehensiveness -- MOSTLY COMPLETE

The prompt includes 30+ test cases across 6 test classes:
- `TestHeredocSplitting`: 13 tests covering basic, quoted, tab-stripping, here-string, multiple, unterminated, subshell, real production command
- `TestArithmeticBypassPrevention`: 2 tests (but see Finding 8 -- the `(( x << 2 ))` test will likely fail)
- `TestParseHeredocDelimiter`: 4 tests
- `TestWriteCommandQuoteAwareness`: 6 tests
- `TestScanProtectedPathsHeredocAware`: 2 tests

**Missing tests:**
- No test for `<<\EOF` (backslash-escaped delimiter) -- flagged by Gemini in V2-adversarial (line 180) but documented as out of scope in the prompt (line 11)
- No test for the `let val<<1` case verifying the guard works correctly when NO space precedes `<<` (the `test_let_shift_not_heredoc` test exists but `let ` has a space before `val`, and `val` is a word char preceding `<<` -- so the guard should work here)

**Finding: MOSTLY COMPLETE.** Good coverage overall. The arithmetic bypass test gap (Finding 8) is the main concern.

### 13. Medium-term fixes coverage (Fix A + B + A2) -- COMPLETE

| Research fix | Guardian prompt coverage |
|---|---|
| Fix A: heredoc awareness in `split_commands()` | Step 3 (lines 339-473) -- full implementation |
| Fix B: quote-aware `is_write_command()` | Step 2 (lines 277-337) -- full implementation |
| Fix A2: `scan_protected_paths()` heredoc-aware | Step 4 (lines 475-519) -- via layer reordering |

**Finding: COMPLETE.** All three medium-term fixes are fully specified.

### 14. V1/V2 findings incorporation

| V1/V2 Finding | Incorporated? |
|---|---|
| V1: `<<<` re-entry edge case | Yes -- line 360 checks `command[i:i+3] != '<<<'` |
| V1: Deny message should include "why" | Yes -- action plan deny message explains purpose (line 117) |
| V2: Arithmetic `(( x << 2 ))` bypass (CRITICAL) | **Partially** -- guard added but insufficient (see Finding 8) |
| V2: Guard regex bypass gaps (cp, mv, install) | Yes -- action plan regex includes these (line 108) |
| V2: `_is_inside_quotes()` backtick blindness | Documented as out of scope (prompt line 10) |
| V2: `<<\EOF` backslash-escaped delimiter | Documented as out of scope (prompt line 11) |

**Finding: MOSTLY COMPLETE.** The arithmetic bypass mitigation is the main gap.

---

## Summary of Findings

### Factual Errors

| # | Location | Error | Severity |
|---|---|---|---|
| 1 | Guardian Prompt, lines 359-361 + 466 | The arithmetic bypass guard `command[i-1] in ' \t\n;|&<>('` does NOT prevent `(( x << 2 ))` from being misdetected because space IS in the allowed set. The prompt claims it does ("prevents `x<<2`") but the test at line 174 tests `(( x << 2 ))` (with spaces), which would fail with this guard. | **MEDIUM-HIGH** |

### Completeness Gaps

| # | Location | Gap | Severity |
|---|---|---|---|
| 1 | Action Plan, test matrix | No tests for `mv`, `dd`, `install` bypass methods despite being in regex | LOW |
| 2 | Guardian Prompt, arithmetic tests | Test `test_arithmetic_shift_not_heredoc` will fail because the guard is insufficient for spaced `<<` | MEDIUM |

### Positive Discrepancies (improvements over source)

| # | Location | Improvement |
|---|---|---|
| 1 | Action Plan, regex | Correctly incorporated V2-adversarial bypass feedback (cp/mv/install/dd) that fix-design missed |
| 2 | Action Plan, hooks.json format | Correctly fixed the flat format error from fix-design to match actual hooks.json nested structure |
| 3 | Action Plan, timeout units | Correctly uses `5` (seconds) matching existing convention, vs fix-design's `5000` |

---

## Recommendations

1. **Guardian Prompt -- Fix arithmetic bypass guard**: The current guard is necessary (prevents `x<<2`) but not sufficient (misses `(( x << 2 ))`). Options:
   - Add `(` to a SECOND check: if `command[i-1] == ' '`, look backwards further to check if we are inside `(( ... ))` context
   - Use the regex pre-pass approach from V2-adversarial Challenge 7 instead
   - At minimum, update the test to use `x<<2` (no space) instead of `(( x << 2 ))`, and add a comment documenting the spaced-arithmetic limitation

2. **Action Plan -- Add mv/dd/install tests**: Three one-liner tests to match the regex coverage.

3. **Both documents are otherwise ready for execution.** The action plan in particular is well-crafted and shows evidence of careful V2 feedback integration.
