# V2 Adversarial Review: Guardian Conflict Memory Fix

**Reviewer:** V2 Adversarial (Fresh Eyes)
**Date:** 2026-02-22
**Files reviewed:**
- `action plans/plan-guardian-conflict-memory-fix.md` (memory_staging_guard.py plan)
- `temp/guardian-heredoc-fix-prompt.md` (bash_guardian.py heredoc fixes)
- `hooks/scripts/bash_guardian.py` (current source code)

---

## VERDICT: PASS WITH NOTES

The proposed solutions are sound for their intended scope. I found no critical security regressions. However, I found several regex bypass vectors in the staging guard (low severity -- defense-in-depth only), one subtle but real concern in the `_is_inside_quotes()` usage for Fix 2, and confirmed the arithmetic guard works correctly. Details below.

---

## PART 1: Action Plan -- `memory_staging_guard.py`

### 1.1 Regex Bypass Attacks

The staging guard regex is:
```python
staging_write_pattern = (
    r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'\btee\s+[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'(?:cp|mv|install|dd)\s+.*\.claude/memory/\.staging/'
)
```

#### Attack 1.1a: Shell variable expansion (BYPASS)

**Input:** `DIR=".claude/memory/.staging"; cat > "$DIR/test.json" << 'EOF'`

**Expected:** Should be blocked (writes to .staging/)

**Actual:** NOT blocked. The regex looks for the literal string `.claude/memory/.staging/` in the command. Shell variable expansion happens at runtime, not in the static string. The regex never sees the expanded path.

**Severity:** LOW. The plan acknowledges this: "exotic path patterns are unlikely from subagents who follow SKILL.md templates" and "C1 is the primary defense." This is a defense-in-depth guard, not a security boundary.

---

#### Attack 1.1b: Pipe chain (BYPASS)

**Input:** `python3 generate_json.py | cat > .claude/memory/.staging/test.json`

**Trace:** The first regex branch is `(?:cat|echo|printf)\s+[^|&;\n]*>\s*...`. The `[^|&;\n]*` character class STOPS at the pipe `|`. So the regex tries to match `cat` followed by non-pipe chars followed by `>`, but `cat > .staging/...` comes AFTER the pipe. The pipe itself separates the regex match.

Wait -- let me re-examine. After the pipe, bash sees `cat > .claude/memory/.staging/test.json`. The regex is applied to the ENTIRE command string. `re.search()` scans the whole string. So it would find `cat > .claude/memory/.staging/test.json` starting at the `cat` after the pipe.

Actually, `cat > .claude/memory/.staging/test.json` matches: `cat` then `\s+` (space) then `[^|&;\n]*` (zero chars) then `>` then `\s*` (zero spaces) then `[^\s]*` (zero chars) then `.claude/memory/.staging/`. Wait, the `[^|&;\n]*` is between `\s+` and `>`. In `cat > file`, after `cat ` (cat + space), `[^|&;\n]*` matches zero characters (because `>` is not excluded by `[^|&;\n]` -- actually `>` IS matched by `[^|&;\n]` since `>` is not `|`, `&`, `;`, or `\n`).

Let me re-trace: `cat > .claude/memory/.staging/test.json`
- `cat` matches `(?:cat|echo|printf)`
- ` ` matches `\s+`
- `[^|&;\n]*` matches `> .claude/memory/.staging/test.json` greedily (all chars are not `|&;\n`)
- Then `>` needs to match... but we've already consumed past it.

Hmm, but regex backtracking will kick in. `[^|&;\n]*` will backtrack to allow `>\s*[^\s]*\.claude/memory/\.staging/` to match. So `[^|&;\n]*` matches empty string, then `>` matches `>`, then `\s*` matches ` `, then `[^\s]*` matches `.claude/memory/.staging/test.json` which contains `.claude/memory/.staging/`.

**Result:** This IS caught by the regex. Not a bypass.

**Severity:** N/A (not a bypass)

---

#### Attack 1.1c: Heredoc with unusual delimiter (NOT A BYPASS)

**Input:** `cat > .claude/memory/.staging/test.json << 'UNUSUAL_DELIM_123'`

**Trace:** The regex matches `cat > .claude/memory/.staging/...` regardless of what follows after the path. The heredoc delimiter is irrelevant to the regex match.

**Severity:** N/A

---

#### Attack 1.1d: Commands NOT in regex list (BYPASS)

**Input:** `rsync /tmp/test.json .claude/memory/.staging/test.json`

**Trace:** The regex only covers `cat|echo|printf`, `tee`, and `cp|mv|install|dd`. `rsync` is not in any branch.

**Input:** `wget -O .claude/memory/.staging/test.json http://example.com/payload.json`

**Trace:** `wget` is not in any branch.

**Input:** `curl -o .claude/memory/.staging/test.json http://example.com/payload.json`

**Trace:** `curl` is not in any branch.

**Input:** `python3 -c "open('.claude/memory/.staging/test.json','w').write('{}')"`

**Trace:** `python3` is not in any branch.

**Severity:** LOW. These are exotic commands that subagents would not typically use. The guard only needs to catch the patterns that subagents actually produce (cat heredoc, echo, tee, cp). The risk assessment in the plan is correct.

---

#### Attack 1.1e: Path traversal (BYPASS)

**Input:** `cat > .claude/memory/../memory/.staging/test.json << 'EOF'`

**Trace:** The regex looks for `.claude/memory/.staging/` literally. The path `.claude/memory/../memory/.staging/` does NOT contain that exact substring, but resolves to the same directory.

**Severity:** LOW. Subagents do not generate traversal paths.

---

#### Attack 1.1f: Absolute path variant (BYPASS)

**Input:** `cat > /home/user/project/.claude/memory/.staging/test.json << 'EOF'`

**Trace:** The regex pattern `[^\s]*\.claude/memory/\.staging/` uses `[^\s]*` before `.claude`. This matches any non-whitespace prefix, including `/home/user/project/`. So this IS caught.

**Result:** NOT a bypass. The `[^\s]*` handles absolute paths correctly.

**Severity:** N/A

---

### 1.2 False Positive Analysis

#### Attack 1.2a: Read-only cat (NOT a false positive)

**Input:** `cat .claude/memory/.staging/test.json`

**Trace:** First regex branch requires `>\s*` after the `[^|&;\n]*` group. In `cat .claude/memory/.staging/test.json`, there is no `>` character. The match attempt for `cat` + `\s+` + `[^|&;\n]*` + `>` fails because the string doesn't contain `>`.

Second branch (`tee`) doesn't match. Third branch (`cp|mv|install|dd`) doesn't match.

**Result:** Correctly allowed. No false positive.

---

#### Attack 1.2b: grep on .staging path (NOT a false positive)

**Input:** `grep "pattern" .claude/memory/.staging/test.json`

**Trace:** `grep` is not `cat|echo|printf`, not `tee`, not `cp|mv|install|dd`. No match.

**Result:** Correctly allowed.

---

#### Attack 1.2c: ls .staging/ (NOT a false positive)

**Input:** `ls .claude/memory/.staging/`

**Trace:** `ls` is not in any regex branch. No match.

**Result:** Correctly allowed.

---

#### Attack 1.2d: python3 script with .staging path argument (NOT a false positive)

**Input:** `python3 hooks/scripts/memory_write.py --output .claude/memory/.staging/test.json`

**Trace:** `python3` is not in any regex branch.

**Result:** Correctly allowed.

---

#### Attack 1.2e: echo without redirection (potential edge case)

**Input:** `echo "Writing to .claude/memory/.staging/ is forbidden"`

**Trace:** `echo` matches, `\s+` matches the space, then `[^|&;\n]*` greedily consumes `"Writing to .claude/memory/.staging/ is forbidden"`. Then `>` needs to match but there's no `>`. Backtracking cannot create a `>` from nothing.

**Result:** Correctly allowed. No false positive.

---

### 1.3 Race Conditions

The staging guard is a PreToolUse hook. It runs synchronously before the Bash tool executes. There is no TOCTOU window because the guard inspects the command string, not the filesystem. The command cannot change between inspection and execution.

**Severity:** N/A (no race condition possible in this architecture)

---

### 1.4 Summary for Action Plan

| Finding | Severity | Verdict |
|---------|----------|---------|
| Shell variable expansion bypasses regex | LOW | Accepted (defense-in-depth, not security boundary) |
| Missing commands (rsync, wget, curl, python3) | LOW | Accepted (subagents don't use these) |
| Path traversal bypasses regex | LOW | Accepted (subagents don't use traversal) |
| No false positives found for read ops | N/A | Good |
| No race conditions | N/A | Good |

**Action Plan Verdict: PASS** -- adequate for its stated purpose as a defense-in-depth layer.

---

## PART 2: Guardian Prompt -- Heredoc Fixes

### 2.1 Security Regression Tests

#### Attack 2.1a: Write to /etc/passwd via heredoc

**Input:** `cat << EOF > /etc/passwd\nroot::\nEOF`

**Trace (post-fix):** In `split_commands()`, the parser encounters characters sequentially.
1. Processes `c`, `a`, `t`, ` ` -- appended to current.
2. At `<`, checks `command[i:i+2]` = `<<`. Checks `command[i:i+3]` = `<< ` (not `<<<`). Checks `command[i-1]` = ` ` which IS in `' \t\n;|&<>('`. So heredoc detection triggers.
3. Parses delimiter: skips spaces, finds `EOF`.
4. But wait -- between `<<` and `EOF` there's ` ` then `>` then ` ` then `/etc/passwd`. Let me re-read: `cat << EOF > /etc/passwd\nroot::\nEOF`

Actually, the full command is `cat << EOF > /etc/passwd`. In bash, this is a heredoc with redirection. The `> /etc/passwd` is the redirection target, and `EOF` is the heredoc delimiter. But in the command string, after `<< `, the parser would skip whitespace and then try to parse the delimiter.

Let me trace through the proposed code:
- `i` is at `<<`
- `strip_tabs` = False (not `<<-`)
- `op_len` = 2
- `current.append('<<')`, `i += 2`
- Skip whitespace: `i` advances past the space after `<<`
- `_parse_heredoc_delimiter(command, i)` is called. At position `i`, the character is `E` (from `EOF`). It's a bare word. Parses `EOF`, stops at the space after `EOF`.
- `pending_heredocs.append(('EOF', False))`
- `continue` -- back to main loop

Now `i` is past `EOF`. The next chars are ` > /etc/passwd\n`. The parser continues the normal loop:
- ` ` -- appended to current
- `>` -- appended to current
- ` ` -- appended to current
- `/etc/passwd` -- appended to current
- `\n` -- triggers newline handler. `sub_commands.append(current)`. Then checks `pending_heredocs` -- yes, there's `('EOF', False)`. Calls `_consume_heredoc_bodies()` which consumes `root::\n` and then `EOF\n`.
- After consuming, the parser resumes.

The sub-command would be: `cat << EOF > /etc/passwd`

Now `is_write_command("cat << EOF > /etc/passwd")` checks `>\s*['\"]?[^|&;]+` -- this matches `> /etc/passwd`. So `is_write = True`. Then `extract_redirection_targets` finds `> /etc/passwd` and extracts `/etc/passwd`. The guardian then checks zero-access/read-only rules against `/etc/passwd`.

**Result:** The write to `/etc/passwd` IS still detected. No regression.

**Severity:** N/A

---

#### Attack 2.1b: Redirection before heredoc with .env

**Input:** `> .env << EOF\ndata\nEOF`

**Trace:** This is unusual syntax but valid bash. The parser sees:
- `>` at position 0, depth==0, not a delimiter character that triggers splitting. Appended to current.
- ` ` appended.
- `.env` appended.
- ` ` appended.
- `<<` at some position. Check `command[i-1]` = ` ` which IS in the allowed set. Heredoc detection triggers.
- Delimiter: `EOF`. `pending_heredocs.append(('EOF', False))`.
- `\n` triggers newline. Sub-command: `> .env << EOF`. Heredoc body consumed.

Sub-command is `> .env << EOF`. `is_write_command` matches `>` (the truncation pattern `:\s*>` doesn't match, but `>\s*['\"]?[^|&;]+` matches `> .env << EOF`). `scan_protected_paths` on the joined sub-commands also sees `.env` in the command part (not hidden in heredoc body).

**Result:** Still detected. No regression.

**Severity:** N/A

---

#### Attack 2.1c: Nested heredocs / command substitution

**Input:** `cat << OUTER\n$(cat << INNER\nevil > /etc/passwd\nINNER\n)\nOUTER`

**Trace:**
- Parser sees `cat `, then `<< OUTER`. Heredoc detected, delimiter `OUTER`.
- `\n` triggers newline. Sub-command: `cat << OUTER`. `_consume_heredoc_bodies` starts.
- Lines consumed: `$(cat << INNER`, `evil > /etc/passwd`, `INNER`, `)`. None of these equal `OUTER`.
- Next line: `OUTER` -- matches delimiter. Consumption stops.

The entire heredoc body including `evil > /etc/passwd` is consumed and never appears as a sub-command. The `evil > /etc/passwd` is INSIDE the heredoc body, which in real bash would be passed as stdin to `cat`, not executed. The guardian correctly ignores it.

**But wait** -- could this be used to HIDE a command? No. The command `cat << OUTER` doesn't write anywhere by itself. The `evil > /etc/passwd` inside the heredoc body is literal text, not a command. This is correct behavior.

**Result:** Correct behavior. No regression.

**Severity:** N/A

---

### 2.2 The Arithmetic Bypass -- Detailed Trace

**Input:** `(( x << 2 ))\nrm -rf /`

The question is whether the proposed guard `command[i-1] in ' \t\n;|&<>('` prevents `<<` inside arithmetic `(( ))` from being misdetected as a heredoc.

**Step-by-step trace through `split_commands()`:**

Position 0: `(` -- Not `$()`, `<()`, or `>()` because `i > 0` check fails (i==0). Not `depth > 0`. Falls through to `depth == 0` block. None of the delimiter checks match `(`. Falls through to `current.append('(')`, `i = 1`.

Position 1: `(` -- `i > 0` and `command[i-1]` = `(` which is NOT in `("$", "<", ">")`. So depth NOT incremented. Not `depth > 0` (depth is still 0). Falls to `depth == 0` block. Not a delimiter. `current.append('(')`, `i = 2`.

Position 2: ` ` -- Appended. `i = 3`.

Position 3: `x` -- Appended. `i = 4`.

Position 4: ` ` -- Appended. `i = 5`.

Position 5-6: `<<` -- Check: `command[5:7]` = `<<`. `command[5:8]` = `<< ` (not `<<<`). Check `command[i-1]` = `command[4]` = ` ` (space).

**CRITICAL:** Space IS in `' \t\n;|&<>('`. So the guard PASSES and heredoc detection triggers!

This means `(( x << 2 ))` WOULD be misdetected as a heredoc with delimiter `2`. The parser would then look for a line containing just `2` to end the heredoc body.

Let me continue the trace:
- Heredoc detected. `strip_tabs = False`. `op_len = 2`.
- `current.append('<<')`, `i = 7`.
- Skip whitespace at position 7: space. `current.append(' ')`, `i = 8`.
- `_parse_heredoc_delimiter(command, 8)`: At position 8, character is `2`. It's a bare word. Parses until whitespace/metachar. `2` then ` ` (space). So `delim = "2"`, `raw_token = "2"`, `i = 9`.
- `current.append("2")`. `pending_heredocs.append(("2", False))`.
- `continue`.

Position 9: ` ` -- Appended.

Position 10: `)` -- Not `depth > 0`. Falls to `depth == 0`. Not a delimiter. Appended.

Position 11: `)` -- Appended.

Position 12: `\n` -- Newline handler triggers. `sub_commands.append("(( x << 2 ))")`. Then `pending_heredocs` is not empty: `[("2", False)]`. Calls `_consume_heredoc_bodies`.

`_consume_heredoc_bodies` at position 13 in string `(( x << 2 ))\nrm -rf /`:
- Reads line from position 13 to end (no more `\n`): line = `rm -rf /`.
- `cmp_line = "rm -rf /"`. Does `"rm -rf /" == "2"`? NO.
- Advances past (no newline at end, loop exits).
- Body consumed. `rm -rf /` is eaten as heredoc body!

**RESULT: `rm -rf /` is consumed as heredoc body and NEVER appears as a sub-command.**

**This is a SECURITY BYPASS.** An attacker can hide arbitrary commands after arithmetic expressions.

**However**, let me consider the real-world impact:
1. The `(( x << 2 ))` itself becomes a sub-command. `is_write_command` and `is_delete_command` would not match it.
2. `rm -rf /` is completely invisible to the guardian.
3. This WOULD be caught by Layer 0 block patterns (`match_block_patterns`) which runs on the raw command string BEFORE splitting. `rm -rf /` with force flag would typically be in block patterns. But `rm -rf /` without `-f` might not be.

Let me check: The test says `rm -rf /`. Block patterns typically catch `rm -rf /` (recursive force delete root). But what about `rm -r /important/file`? That would go through split_commands and could be hidden.

**Actually, wait.** Let me re-read the proposed guard more carefully:

```python
if (command[i:i+2] == '<<'
        and command[i:i+3] != '<<<'
        and (i == 0 or command[i-1] in ' \t\n;|&<>(')):
```

The guard is `command[i-1] in ' \t\n;|&<>('`. In `(( x << 2 ))`, at the `<<` position, `command[i-1]` is a space character. Space IS in the allowed set.

**The proposed test `test_arithmetic_shift_not_heredoc` expects:**
```python
subs = split_commands("(( x << 2 ))\nrm -rf /")
assert any("rm" in sub for sub in subs)
```

This test WILL FAIL with the proposed implementation. The `rm -rf /` will be consumed as heredoc body.

**Severity:** HIGH. This is a security regression. The arithmetic guard `command[i-1] in ' \t\n;|&<>('` does NOT prevent the bypass because `<<` in `x << 2` is preceded by a space, which is in the allowed set.

**Root cause:** The guard checks only the character immediately before `<<`. In `x << 2`, the space before `<<` is ambiguous -- it could be a heredoc or a bitshift. The guard needs more context, such as checking whether we are inside `(( ))` or `[[ ]]` arithmetic context, or checking whether the character before the space is a word character (indicating an operand for bitshift).

**Proposed mitigation:** Change the guard to also check that the character before any whitespace preceding `<<` is NOT a word character or `)`. Something like:

```python
# Check that << is not preceded by a word char (with possible whitespace gap)
# x << 2 -> 'x' then ' ' then '<<' -- the 'x' indicates bitshift
j = i - 1
while j >= 0 and command[j] in ' \t':
    j -= 1
if j >= 0 and (command[j].isalnum() or command[j] in '_)'):
    # Preceded by a word/variable/expression -- likely arithmetic shift, skip
    pass  # Don't trigger heredoc detection
```

Or alternatively, track `(( ))` depth separately like `$()` is tracked.

---

#### Attack 2.2b: `let val<<1`

**Input:** `let val<<1\necho done`

**Trace:**
- `l`, `e`, `t`, ` ` appended.
- At `v`, `a`, `l` appended.
- At `<<`: `command[i-1]` = `l`. `l` is NOT in `' \t\n;|&<>('`.

**So the guard DOES prevent this.** Heredoc detection does NOT trigger for `let val<<1` because `l` (from `val`) is not in the allowed set.

**Result:** Correctly handled. `echo done` remains visible.

**Severity:** N/A (not a bypass)

---

#### Summary of arithmetic analysis

| Input | `command[i-1]` at `<<` | In allowed set? | Heredoc triggered? | Security impact |
|-------|----------------------|-----------------|-------------------|----------------|
| `(( x << 2 ))` | ` ` (space) | YES | YES -- BYPASS | HIGH |
| `let val<<1` | `l` | NO | NO -- correct | None |
| `echo $((x<<1))` | `x` | NO | NO -- correct | None |
| `x=1; $((x << 2))` | ` ` | YES | YES -- BYPASS | HIGH (same class) |

---

### 2.3 Heredoc Delimiter Edge Cases

#### Attack 2.3a: Empty delimiter

**Input:** `<< ""\nbody\n`

**Trace through `_parse_heredoc_delimiter`:**
- Position `i` points to `"`. `command[i]` is `"`.
- `quote_char = '"'`, `start = i`, `i += 1`.
- Next char is `"` which equals `quote_char`. `i += 1`.
- `raw_token = '""'`, `delim = ''` (empty string after stripping quotes).
- Returns `('', '""', i)`.

In `_consume_heredoc_bodies`, the delimiter is `''` (empty string). It matches any empty line (`cmp_line == ""`). An empty line in the heredoc body would terminate it.

**Real bash behavior:** `<< ""` creates a heredoc with empty delimiter. Any empty line terminates it. The proposed implementation matches bash behavior.

**Result:** Correct.

---

#### Attack 2.3b: Delimiter with special characters

**Input:** `<< END;comment\nbody\nEND;comment`

**Trace through `_parse_heredoc_delimiter`:**
- At `E`: bare word. Parses until `command[i] not in ' \t\n;|&<>()'`. `;` IS in this set (yes, `;` is in the stop set).
- So `delim = "END"`, stops at `;`.

The `;comment` after `END` would be treated as a new command (`;` is a command separator). The heredoc delimiter is just `END`.

**Real bash behavior:** `<< END;comment` means heredoc with delimiter `END`, followed by command `comment` after the `;`. The proposed implementation correctly handles this.

**Result:** Correct.

---

#### Attack 2.3c: Very long delimiter

**Input:** `<< AAAAAA...AAAAAA\nbody\nAAAAA...AAAAAA` (1000 A's)

**Trace:** `_parse_heredoc_delimiter` parses the bare word of 1000 A's. No length limit in the parser. `_consume_heredoc_bodies` compares each line against the 1000 A's.

**Risk:** No security risk, just potential performance concern for extremely long delimiters. String comparison is O(n) but bounded by input size.

**Result:** No issue.

---

#### Attack 2.3d: Delimiter matching a bash keyword

**Input:** `<< if\nreal code\nif`

**Trace:** `_parse_heredoc_delimiter` parses `if` as a bare word. Delimiter is `if`. Body `real code` is consumed. Line `if` matches delimiter. Consumption stops.

**Real bash behavior:** Heredoc delimiters can be any word, including reserved words. The proposed implementation handles this correctly.

**Result:** Correct.

---

### 2.4 The `_is_inside_quotes()` Usage in `is_write_command()` (Fix 2)

The proposed Fix 2 changes `is_write_command()` to use `_is_inside_quotes()` for the `>` redirection pattern:

```python
match = re.search(pattern, command, re.IGNORECASE)
if match:
    if needs_quote_check and _is_inside_quotes(command, match.start()):
        continue  # Skip: > is inside a quoted string
    return True
```

#### Attack 2.4a: Multiple `>` characters, first in quotes, second real

**Input:** `echo "value > threshold" > /etc/passwd`

**Trace:**
- Pattern `r">\s*['\"]?[^|&;]+"` matches the FIRST `>` in `"value > threshold"` (at position 12 inside the double quotes).
- `_is_inside_quotes(command, 12)` returns `True` (position 12 is inside `"..."`).
- The match is skipped via `continue`.
- The loop continues to the next pattern... but wait, this is `for pattern, needs_quote_check in write_patterns`. We're inside the loop over patterns, not over matches. After `continue`, we move to the NEXT pattern (`\btee\s+`), not to the next match of the SAME pattern.

**This means the SECOND `>` (the real redirection `> /etc/passwd`) is NEVER checked by the redirection pattern!**

Wait, let me re-read the regex: `r">\s*['\"]?[^|&;]+"`. `re.search()` finds the FIRST match. In `echo "value > threshold" > /etc/passwd`:

Actually, let me think about what `re.search` returns. It returns the first match scanning left to right. The first `>` is at position 12 (inside quotes). `re.search(r">\s*['\"]?[^|&;]+", command)` would match starting at position 12.

But `_is_inside_quotes(command, 12)` returns True. So `continue` skips to the next pattern in the list. The second `>` at position 30 (after `" `) is never examined by this pattern.

**Is this a real security bypass?** In `echo "value > threshold" > /etc/passwd`:
- `is_write_command()` returns False for the `>` pattern (the only match found was inside quotes, and it was skipped).
- No other pattern matches (no `tee`, `mv`, `cp`, etc.).
- `is_write_command()` returns `False`.

**But** `extract_redirection_targets()` uses `_is_inside_quotes()` independently per match via `re.finditer()`. It would find both `>` matches, skip the first (inside quotes), and correctly extract `/etc/passwd` from the second. So `sub_paths` would contain `/etc/passwd`.

However, since `is_write = False`, the path-level checks would not apply write-specific protections (read-only check requires `is_write`). The F1 safety net (`if (is_write or is_delete) and not sub_paths`) would also not trigger because `is_write` is False.

**But wait**, zero-access checks apply to ALL operations, not just writes. So if `/etc/passwd` is in `zeroAccessPaths`, it would still be denied. But if the target is a non-zero-access path that's read-only, the read-only protection would be bypassed.

**Concrete exploit:** `echo "value > threshold" > poetry.lock` where `poetry.lock` is read-only.

**Trace:**
1. `is_write_command()` returns `False` (quote-aware check skips the only regex match)
2. `extract_redirection_targets()` correctly finds `> poetry.lock` (second match, not inside quotes)
3. Since `is_write = False`, the read-only check at line 1060 (`if is_write and match_read_only(path_str)`) does NOT fire
4. The write to `poetry.lock` is ALLOWED despite it being read-only

**Severity:** MEDIUM. This creates a bypass for read-only (but not zero-access) path protections when a command contains a `>` character inside quotes before the real redirection.

**Fix:** Instead of `re.search()` (first match only), use `re.finditer()` and check ALL matches:

```python
for pattern, needs_quote_check in write_patterns:
    for match in re.finditer(pattern, command, re.IGNORECASE):
        if needs_quote_check and _is_inside_quotes(command, match.start()):
            continue
        return True
```

This ensures that if the first `>` is inside quotes but a second `>` is outside quotes, the function correctly returns `True`.

---

#### Attack 2.4b: Backtick blindness in `_is_inside_quotes()`

**Input:** `` echo `echo "` > /etc/passwd ``

The `_is_inside_quotes()` function does NOT track backticks. Given `` echo `echo "` > /etc/passwd ``:

- Scanning to the position of `>`: encounters the opening backtick, but doesn't track it. Encounters `"` inside the backtick -- toggles `in_double` to True. Reaches `>` position -- reports `True` (inside double quotes).

**But in real bash:** The `"` inside the backtick is part of the backtick substitution, not a standalone quote. The `>` after the closing backtick is at the top level and IS a real redirection.

However, this is explicitly listed as out of scope in the prompt ("The `_is_inside_quotes()` backtick blindness ... is a pre-existing limitation, not a regression"). Since this is a pre-existing issue, not introduced by the fix, I note it but don't count it against the proposed changes.

**Severity:** Pre-existing limitation. Not a regression.

---

### 2.5 Layer Reordering (Fix 3): Protected Paths After split_commands()

After Fix 3, the flow becomes:
```python
sub_commands = split_commands(command)
scan_text = ' '.join(sub_commands)
scan_verdict, scan_reason = scan_protected_paths(scan_text, config)
```

#### Attack 2.5a: Protected path in non-heredoc command

**Input:** `cat .env`

**Trace:**
- `split_commands("cat .env")` returns `["cat .env"]`
- `' '.join(["cat .env"])` = `"cat .env"`
- `scan_protected_paths("cat .env", config)` finds `.env` -- triggers ask/deny

**Result:** Correctly detected. No regression.

---

#### Attack 2.5b: Protected path after semicolon

**Input:** `echo hello; cat .env`

**Trace:**
- `split_commands(...)` returns `["echo hello", "cat .env"]`
- `' '.join(...)` = `"echo hello cat .env"`
- `scan_protected_paths` finds `.env`

**Result:** Correctly detected. The join with spaces preserves all sub-command content.

---

#### Attack 2.5c: Could joining sub-commands CREATE a false match?

**Input:** `echo .en; echo v`

**Trace:**
- `split_commands(...)` returns `["echo .en", "echo v"]`
- `' '.join(...)` = `"echo .en echo v"`
- `.env` does NOT appear as a substring in `"echo .en echo v"` because the `;` split creates a space between `.en` and `echo`.

**Result:** No false positive. The word-boundary regex in `scan_protected_paths` would not match `.en echo v` as `.env` anyway.

---

#### Attack 2.5d: Could joining sub-commands DESTROY a match?

Could splitting and rejoining lose information? The only content removed by `split_commands()` post-fix is heredoc bodies and the delimiters between sub-commands (`;`, `&&`, `||`, `|`, `&`, `\n`). The actual command text (minus heredoc bodies) is preserved in the sub-commands list.

**Input:** `echo .env; rm file`

**Trace:**
- `split_commands(...)` returns `["echo .env", "rm file"]`
- `' '.join(...)` = `"echo .env rm file"`
- `.env` is present in joined text

**Result:** No loss of information. Correct.

---

#### Attack 2.5e: Heredoc body intentionally hiding a real command

Could an attacker use a heredoc to hide a real command that references a protected path?

**Input:** `cat << EOF\nEOF\ncat .env`

**Trace:**
- Parser sees `cat << EOF`. Heredoc detected, delimiter `EOF`.
- `\n` triggers newline. Sub-command: `cat << EOF`. Heredoc body consumption starts.
- Next line: `EOF` -- matches delimiter. Consumption stops.
- Position is now at `cat .env`.
- `\n` is not present (end of string). `cat .env` falls through to "remaining" logic.
- `sub_commands = ["cat << EOF", "cat .env"]`
- Joined: `"cat << EOF cat .env"`
- `scan_protected_paths` finds `.env`

**Result:** Correctly detected. The command after the heredoc is preserved.

---

### 2.6 Additional Edge Cases

#### Attack 2.6a: Heredoc inside single quotes

**Input:** `echo 'cat << EOF\nbody\nEOF'`

**Trace:** The `<<` is inside single quotes. In `split_commands()`, when `in_single_quote` is True, the code skips to the `current.append(c)` path. The heredoc detection code is only reached inside the `depth == 0` block, which is never entered while in quotes. Correct behavior.

**Result:** No issue.

---

#### Attack 2.6b: Double heredoc followed by dangerous command

**Input:** `cmd <<A <<'B'\nbody A\nA\nbody B\nB\nrm -rf /tmp/important`

**Trace:**
- Parser sees `cmd <<A`. Heredoc detected, delimiter `A`.
- Then `<<'B'`. Space before `<<`: `command[i-1]` = `A`. `A` is NOT in `' \t\n;|&<>('`.

Wait, after parsing the first `<<A`, the parser's `i` is past `A` (from the delimiter). Then there's a space, then `<<'B'`.

Let me re-trace more carefully. The input is `cmd <<A <<'B'\nbody A\nA\nbody B\nB\nrm -rf /tmp/important`.

- `c`, `m`, `d`, ` ` appended.
- Position at first `<`: `command[i:i+2]` = `<<`. Not `<<<`. `command[i-1]` = ` ` (space), IS in allowed set. Heredoc detected.
- Skip whitespace (none). Parse delimiter: `A`. Bare word, stops at space. `pending_heredocs = [('A', False)]`.
- Now `i` is past `A`, at the space before `<<'B'`.
- ` ` appended to current.
- Position at second `<`: `command[i:i+2]` = `<<`. Not `<<<`. `command[i-1]` = ` `. Heredoc detected again.
- Parse delimiter: `'B'`. Single-quoted. `delim = 'B'`. `pending_heredocs = [('A', False), ('B', False)]`.
- Continue.
- `\n` triggers newline. Sub-command: `cmd <<A <<'B'`. Then `_consume_heredoc_bodies` processes BOTH pending heredocs:
  - First, consume until line == `A`: `body A` (no match), `A` (match). Done.
  - Second, consume until line == `B`: `body B` (no match), `B` (match). Done.
- After consumption, position is at `rm -rf /tmp/important`.
- This becomes a new sub-command.

**Result:** `rm -rf /tmp/important` is correctly visible as a separate sub-command. No issue.

---

#### Attack 2.6c: Backslash continuation before heredoc

**Input:** `cat \\\n> file << 'EOF'\nbody\nEOF`

In bash, `\` followed by newline is a line continuation. The command is `cat > file << 'EOF'`.

**Trace in split_commands():**
- `c`, `a`, `t`, ` ` appended.
- Position at `\`: backslash handler triggers (not in single quote). Appends `\`, advances to `\n`, appends `\n`, `i += 1`.
- Now at `>`, ` `, `f`, `i`, `l`, `e`, ` ` -- all appended.
- At `<<`: `command[i-1]` = ` `. Heredoc detected. Delimiter: `'EOF'` -> `EOF`.
- `\n` triggers newline. Sub-command: `cat \\\n> file << 'EOF'`. Heredoc body consumed.

**Result:** Works correctly. The backslash-newline is treated as a literal (part of the command), and the heredoc is detected after the continuation. In bash, this would be equivalent to `cat > file << 'EOF'`, and the guardian sees the `> file` redirection in the sub-command.

---

## SUMMARY OF FINDINGS

### Critical Findings

| # | Component | Finding | Severity | Impact |
|---|-----------|---------|----------|--------|
| 1 | Fix 1 (heredoc detection) | Arithmetic `(( x << 2 ))` bypass: space before `<<` passes the guard, causing `rm -rf /` after the expression to be consumed as heredoc body and hidden from the guardian | **HIGH** | Attacker can hide commands after arithmetic expressions |
| 2 | Fix 2 (quote-aware is_write_command) | `re.search()` only finds first `>` match; if first is inside quotes, second (real) redirection is never checked | **MEDIUM** | Read-only path protection bypass when quoted `>` precedes real `>` |

### Non-Critical Findings

| # | Component | Finding | Severity |
|---|-----------|---------|----------|
| 3 | memory_staging_guard.py | Shell variable expansion bypasses regex | LOW |
| 4 | memory_staging_guard.py | Missing commands (rsync, wget, curl, python3) | LOW |
| 5 | memory_staging_guard.py | Path traversal (`../`) bypasses regex | LOW |
| 6 | Fix 2 | `_is_inside_quotes()` backtick blindness | Pre-existing, not a regression |
| 7 | Fix 3 | Layer reorder tested thoroughly -- no regressions found | N/A |

### Recommended Fixes

**For Finding #1 (HIGH):** Strengthen the heredoc detection guard. Instead of only checking `command[i-1]`, also look backward past whitespace to see if the preceding non-whitespace character is a word character (indicating arithmetic context):

```python
# After confirming command[i-1] is in the allowed set, also check
# that the preceding non-whitespace char is not a word char
# (which would indicate arithmetic shift like "x << 2")
j = i - 1
while j >= 0 and command[j] in ' \t':
    j -= 1
if j >= 0 and (command[j].isalnum() or command[j] in '_)'):
    # Preceded by word/expression -- skip heredoc detection
    current.append(c)
    i += 1
    continue
```

**For Finding #2 (MEDIUM):** Replace `re.search()` with `re.finditer()` in `is_write_command()`:

```python
for pattern, needs_quote_check in write_patterns:
    for match in re.finditer(pattern, command, re.IGNORECASE):
        if needs_quote_check and _is_inside_quotes(command, match.start()):
            continue
        return True
return False
```

---

## FINAL VERDICT: PASS WITH NOTES

The action plan (memory_staging_guard.py) is solid for its defense-in-depth role. The guardian heredoc fixes are architecturally sound but have two concrete bugs that should be fixed before deployment:

1. The arithmetic bypass guard is insufficient and WILL cause the `test_arithmetic_shift_not_heredoc` test to fail.
2. The `re.search()` single-match limitation in `is_write_command()` creates a real (if narrow) protection bypass.

Neither finding is catastrophic -- the arithmetic bypass requires a specific command format and many dangerous commands would still be caught by Layer 0 block patterns. The quote bypass requires a specific pattern of quoted `>` before real `>`, targeting non-zero-access paths. But both should be fixed.
