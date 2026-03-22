# Adversarial Security Review: Step 6.1 & 6.2 Action Plans

**Reviewer**: Independent adversarial security reviewer (Round 2)
**Date**: 2026-03-21
**Documents reviewed**:
1. `action-plans/heredoc-pattern-false-positives.md` (Step 6.1)
2. `action-plans/interpreter-path-resolution.md` (Step 6.2)
3. `action-plans/interpreter-heredoc-bypass.md` (related)
4. `hooks/scripts/bash_guardian.py` (source)
5. `hooks/scripts/_guardian_utils.py` (source)
6. `assets/guardian.default.json` (config)

**Cross-model validation**: Gemini 2.5 Pro, Gemini 3 Pro Preview, vibe-check meta-mentor

---

## Executive Summary

**Final Verdict: PASS WITH CONCERNS (3 BLOCKING issues, 4 non-blocking concerns)**

Step 6.1 (heredoc false positives) solves a real and significant usability problem. The core architectural choice -- moving `split_commands()` before Layer 0 and selectively retaining/stripping heredoc bodies -- is sound. However, the `_DATA_HEREDOC_COMMANDS` allowlist contains multiple commands with shell escape capabilities that create confirmed RCE bypass vectors. These MUST be addressed before implementation.

Step 6.2 (interpreter path resolution) is a lower-risk, narrower change with a fail-closed design. It has two moderate concerns around decoy literal attacks and `glob.glob()` on untrusted input, but neither is blocking.

---

## SECTION A: Attack Vector Analysis -- Step 6.1 (Heredoc False Positives)

### A-1. Pipe-to-Interpreter Bypass [CRITICAL -- BLOCKING]

**Vector:**
```bash
cat << EOF | bash
rm -rf .git
EOF
```

**Analysis:**
1. `split_commands()` encounters `|` and splits the pipeline into sub-commands.
2. When the newline after `cat << EOF | bash` is processed, `cmd_so_far` contains either `cat << EOF` or the pipeline portion depending on exact split behavior.
3. The heredoc body `rm -rf .git` is consumed by `_consume_heredoc_bodies()`.
4. If the heredoc is associated with `cat` (which is in `_DATA_HEREDOC_COMMANDS`), `retain_body=False` and the body is silently discarded.
5. The resulting sub-commands are approximately `["cat << EOF", "bash"]` -- neither triggers block patterns.
6. The dangerous payload `rm -rf .git` is INVISIBLE to all security layers.

**Severity**: CRITICAL. This is a complete bypass of all guardian protections. The plan acknowledges this as a "known limitation" (line 597-602) and defers it as "separate pipeline-aware analysis," but this assessment is incorrect -- the bypass is a DIRECT CONSEQUENCE of the proposed change, not a pre-existing limitation. Before this change, the raw command scan in Layer 0 would match `rm -rf .git` in the raw string.

**Variants that also bypass:**
- `cat << EOF | sh` (any shell interpreter)
- `cat << EOF | python3` (script interpreters)
- `tee /dev/null << EOF | bash` (tee is also allowlisted)
- `echo << EOF | bash` (echo is allowlisted)
- `cat << EOF | tee harmless.txt | bash` (multi-stage pipe)
- `grep -v NEVER_MATCH << EOF | bash` (grep passes everything through)

**Cross-model consensus**: Both Gemini 2.5 Pro and Gemini 3 Pro Preview rated this CRITICAL. Gemini 2.5 Pro specifically noted the deeper issue: `split_commands()` associates the heredoc with `cmd_so_far` at the newline, which may be the LAST command in the pipeline, not the command that owns the `<<` operator.

**Mitigation requirement**: Before stripping a heredoc body, check ALL sub-commands in the current pipeline for interpreter commands. If ANY pipe destination is an interpreter, retain the body. Alternatively, NEVER strip bodies when the sub-command containing `<<` is part of a pipeline (i.e., connected via `|`).

---

### A-2. MySQL/PostgreSQL/SQLite3 Shell Escape [CRITICAL -- BLOCKING]

**Vector:**
```bash
mysql << EOF
\! rm -rf .git
EOF
```

**Analysis:**
1. `mysql` is in `_DATA_HEREDOC_COMMANDS` (line 174 of the plan).
2. `_is_data_heredoc_command("mysql -u root << EOF")` returns `True`.
3. The heredoc body is stripped from scanning.
4. At runtime, `mysql`'s `\!` prefix executes an arbitrary shell command.
5. The `rm -rf .git` command executes with no guardian visibility.

**Identical bypass exists for:**
- `psql << EOF` with `\! rm -rf .git` (PostgreSQL `\!` shell escape)
- `sqlite3 << EOF` with `.shell rm -rf .git` (SQLite `.shell` command)

The plan's justification (line 616-621) that "the guardian protects the local filesystem, not remote databases" is INCORRECT for this vector. The `\!` command in mysql/psql executes on the LOCAL filesystem, not on a remote database server. The `.shell` command in sqlite3 is explicitly a local shell escape.

**Severity**: CRITICAL. Direct RCE on local filesystem via allowlisted command.

**Cross-model consensus**: Gemini 2.5 Pro rated CRITICAL. The plan's own security analysis (Section "Edge Cases and Security Considerations", item 3) dismisses this concern with incorrect reasoning.

**Mitigation requirement**: Remove `mysql`, `psql`, and `sqlite3` from `_DATA_HEREDOC_COMMANDS`. Their heredoc bodies contain SQL that may include shell escape commands. These should retain bodies and be scanned, or at minimum trigger ASK when used with heredocs.

---

### A-3. `sed` GNU Extension RCE [HIGH]

**Vector:**
```bash
sed -f /dev/stdin << EOF
1 e rm -rf .git
EOF
```

Or more subtly:
```bash
sed << EOF
s/x/y/e rm -rf .git
EOF
```

**Analysis:**
1. `sed` is in `_DATA_HEREDOC_COMMANDS` (line 168).
2. GNU `sed` supports the `e` command, which executes the pattern space (or a specified command) as a shell command.
3. The `e` flag on the `s` substitution command executes the replacement text as a shell command.
4. When the heredoc body is stripped, this RCE vector becomes invisible.

**Severity**: HIGH. Requires GNU sed (common on Linux, which is the primary deployment target). The `e` command is a documented GNU sed extension, not an obscure feature.

**Mitigation**: Remove `sed` from `_DATA_HEREDOC_COMMANDS`, or at minimum document the risk and accept it. Since `sed` heredocs containing block-pattern content are unlikely in normal AI agent usage, removing it is the safer choice.

---

### A-4. `sendmail` Pipe-to-Command [HIGH]

**Vector:**
```bash
sendmail -t << EOF
To: |rm -rf .git
Subject: test

body
EOF
```

**Analysis:**
1. `sendmail` is in `_DATA_HEREDOC_COMMANDS` (line 176).
2. `sendmail` interprets a recipient address starting with `|` as a command to pipe the email body to.
3. The heredoc body containing `To: |rm -rf .git` is stripped from scanning.
4. At runtime, sendmail executes `rm -rf .git`.

**Severity**: HIGH. Classic sendmail RCE vector. However, `sendmail` being present on the system and the AI agent using it in this way is relatively unlikely.

**Mitigation**: Remove `sendmail` from `_DATA_HEREDOC_COMMANDS`. `mail` is also questionable (some implementations support `~!` shell escape), but less commonly exploitable.

---

### A-5. Backslash-Escaped Heredoc Delimiter Parsing Differential [CRITICAL -- BLOCKING]

**Vector:**
```bash
cat << \EOF
safe data
EOF
rm -rf .git
```

**Analysis (identified by Gemini 3 Pro Preview):**
1. Bash treats `\EOF` as a delimiter with the value `EOF` (backslash-escaping disables variable expansion in the body, but the delimiter itself is `EOF`).
2. The existing `_parse_heredoc_delimiter()` (lines 443-473) handles bare words, single-quoted, and double-quoted delimiters, but does NOT handle backslash-escaped delimiters.
3. The bare-word parser extracts `\EOF` as the delimiter text.
4. `_consume_heredoc_bodies()` searches for a line matching `\EOF` exactly.
5. The actual terminator line `EOF` (without backslash) does NOT match `\EOF`.
6. The parser consumes the rest of the input as heredoc body -- including `rm -rf .git` on line 4.
7. Since `cat` is in `_DATA_HEREDOC_COMMANDS` with `retain_body=False`, the ENTIRE remainder of the script (including `rm -rf .git`) is silently discarded from scanning.

**Severity**: CRITICAL. This is a parsing differential vulnerability -- the Python parser and Bash disagree on where the heredoc body ends. An attacker can use this to hide arbitrary commands after a "data" heredoc with a backslash-escaped delimiter. Note: this bug exists in the CURRENT code as well, but the proposed change makes it exploitable for security bypass (currently heredoc bodies are not used for security decisions in Layer 0).

**Variants:**
- `cat << E\OF` (partial escaping)
- `cat << EOF\ ` (trailing backslash)

**Mitigation requirement**: Update `_parse_heredoc_delimiter()` to strip backslashes from bare-word delimiters, matching Bash's actual behavior. This is a BLOCKING issue because the parsing differential can be weaponized to hide commands.

---

### A-6. `_is_data_heredoc_command()` Flag-Skipping Logic Bypass [HIGH]

**Vector:**
```bash
sudo -u cat bash << EOF
rm -rf .git
EOF
```

**Analysis (identified by Gemini 3 Pro Preview):**
1. The proposed `_is_data_heredoc_command()` tokenizes the prefix and skips:
   - Variable assignments (`FOO=bar`)
   - Known wrapper commands (`env`, `sudo`, `command`, etc.)
   - Flags (tokens starting with `-`)
2. For `sudo -u cat bash << EOF`:
   - `sudo` is skipped (in `skip_prefixes`)
   - `-u` is skipped (starts with `-`)
   - `cat` is identified as `base_cmd` (it's the next non-flag, non-prefix token)
   - `cat` is in `_DATA_HEREDOC_COMMANDS` -- body is stripped!
3. But the actual command being executed is `bash`, not `cat`. `-u cat` tells sudo to run as user `cat`.

**Severity**: HIGH. The flag-skipping logic blindly skips all flags without knowing whether they take arguments. For `sudo -u <user>`, the `-u` flag consumes the next token as its argument, but the parser treats `cat` as the command.

**Other variants:**
- `env -u CAT bash << EOF` (env `-u` unsets variable named CAT, bash is the command)
- `nice -n 19 bash << EOF` (nice `-n` takes a numeric argument)
- `strace -e trace=open bash << EOF` (strace `-e` takes an argument)

**Mitigation**: The flag-skipping logic must either:
1. Know which flags take arguments for each wrapper command (complex), OR
2. Fail-closed: if ANY unrecognized flag is encountered after a wrapper, return `False` (treat as interpreter), OR
3. Only skip single-character flags that are known to NOT take arguments

Option 2 is recommended for simplicity and security.

---

### A-7. Function/Alias Redefinition [MEDIUM]

**Vector:**
```bash
cat() { bash "$@"; }
cat << 'EOF'
rm -rf /
EOF
```

**Analysis:**
1. `split_commands()` produces two sub-commands: the function definition and the `cat << 'EOF'` call.
2. `_is_data_heredoc_command` sees `cat` in the second sub-command and strips the body.
3. At runtime, the `cat` function (which is actually `bash`) executes the heredoc body.

**Severity**: MEDIUM. This requires defining a function in the same command, which is unusual for AI agent behavior. The existing block patterns might catch the function definition if it contains obvious dangerous patterns, but the function definition itself (`cat() { bash "$@"; }`) does not match any current block pattern.

**Mitigation**: Consider adding a block/ask pattern for function definitions that shadow allowlisted data commands. This is a defense-in-depth measure, not a blocking requirement.

---

### A-8. Unterminated Heredoc with `retain_body=False` [MEDIUM]

**Vector:**
```bash
cat << NEVER_ENDING_DELIMITER
safe content
# The delimiter never appears, so the rest of the script is consumed
rm -rf .git
# This is also consumed and discarded
```

**Analysis:**
When `_consume_heredoc_bodies()` cannot find the delimiter, it consumes the entire remaining input. With `retain_body=False` (data command), this means everything after the heredoc operator is silently discarded from scanning. With `retain_body=True` (interpreter), the content is retained and scanned.

For data commands, this means an intentionally unterminated heredoc can hide subsequent dangerous commands. However, this is also a pre-existing issue (the current code always discards heredoc bodies, terminated or not).

**Severity**: MEDIUM. The behavior change makes this exploitable for targeted command hiding, but it requires the attacker to intentionally craft an unterminated heredoc.

**Mitigation**: When `_consume_heredoc_bodies()` reaches end-of-input without finding the delimiter, flag the command as malformed and fail-closed (deny or ask).

---

### A-9. `patch` Command as Data [LOW]

**Vector:**
```bash
patch << EOF
--- a/some-file
+++ b/some-file
@@ -1 +1 @@
-safe
+malicious content
EOF
```

**Analysis:**
`patch` is in `_DATA_HEREDOC_COMMANDS`. While `patch` modifies files, its heredoc body is a unified diff, not executable code. The body does not enable arbitrary code execution. However, `patch` can be used to modify protected files if the diff targets them.

**Severity**: LOW. `patch` cannot execute arbitrary commands from its input. File modification by `patch` is caught by Layer 3/4 path extraction (the `-p` flag and file paths in the diff header may be extractable). The risk is limited.

---

## SECTION B: Attack Vector Analysis -- Step 6.2 (Interpreter Path Resolution)

### B-1. Decoy String Literal Suppressing F1 [HIGH]

**Vector:**
```python
python3 -c "
safe = './temp/harmless.txt'  # Benign literal
target = chr(46) + chr(101) + chr(110) + chr(118)  # .env
import os; os.remove(target)
"
```

**Analysis:**
1. This is a multiline payload, so the Layer 0 block pattern `python[23]?\s[^|&\n]*os\.remove` fails (the `[^|&\n]*` stops at the first `\n`).
2. `is_delete_command()` correctly identifies the destructive API via `check_interpreter_payload()`.
3. `extract_paths()` finds no filesystem paths (the argument is source code).
4. F1 safety net triggers: `is_delete=True` and `sub_paths=[]`.
5. The new `extract_paths_from_interpreter_payload()` extracts `'./temp/harmless.txt'` as a string literal.
6. If `./temp/harmless.txt` exists and is within the project, `interpreter_paths` is non-empty.
7. F1 is suppressed. The extracted path `./temp/harmless.txt` passes all validation.
8. The command is ALLOWED.
9. At runtime, `os.remove()` targets `.env` (constructed dynamically), which is a zeroAccess protected file.

**Result**: F1 safety net bypassed. The command changes from ASK to ALLOW, silently deleting `.env`.

**Severity**: HIGH. However, this is mitigated by several factors:
- The attack requires a multiline payload (single-line would be caught by Layer 0)
- The decoy path must actually exist on the filesystem and be within the project
- The result is downgrading ASK to ALLOW, not bypassing DENY
- AI agents do not typically generate obfuscated code

**Mitigation recommendation**:
1. Require ALL string literals that look like paths to be validated, not just "at least one". If any literal fails validation, F1 should still fire.
2. Consider adding a check: if `check_interpreter_payload()` detected a destructive API AND string literals were found, verify that the destructive API's argument references one of the extracted literals (not a variable or dynamic construction).
3. At minimum, document this as an accepted risk given the threat model.

---

### B-2. `glob.glob()` as Filesystem Oracle [MEDIUM]

**Vector:**
```python
python3 -c "
import os
os.chmod(var, 0o777)  # Triggers is_write, no extractable path
# Attacker includes probing pattern:
probe = '/home/user/.ssh/id_rsa'
"
```

**Analysis:**
1. `is_write_command()` or `is_delete_command()` fires due to the destructive API.
2. No paths extracted by `extract_paths()`.
3. F1 triggers, `extract_paths_from_interpreter_payload()` is called.
4. The function calls `glob.glob()` on the extracted string literal.
5. If the path exists, `glob.glob()` returns it. If it's a zeroAccess path, validation fails and the verdict is DENY.
6. If the path does not exist, `glob.glob()` returns empty, F1 fires with ASK.
7. The DIFFERENCE between DENY and ASK reveals whether the file exists.

**Severity**: MEDIUM. This is an information disclosure oracle. However:
- The probed path must match glob patterns (or be exact)
- The agent observes verdict differences (DENY vs ASK), not file contents
- The threat model focuses on accidental destruction, not information disclosure
- `glob.glob()` does not traverse symlinks by default (unless `recursive=True`)

**Mitigation**: Replace `glob.glob()` with pure path validation (use `Path.exists()` instead of glob expansion). Only expand globs when the path contains wildcard characters AND is within the project directory. For paths outside the project, skip glob expansion entirely.

---

### B-3. Raw String and Byte String Handling [LOW]

**Vector:**
```python
python3 -c "import os; os.remove(b'/path/to/file'.decode())"
```

**Analysis:**
The `_STRING_LITERAL_PATTERN` regex captures `'/path/to/file'` inside `b'...'` because the `b` prefix is outside the quote -- the regex sees `'` as the start of a string literal and captures `/path/to/file`. This is actually CORRECT behavior for security purposes (the path is extracted and validated).

For `r'/path/to/file'`, the `r` prefix is similarly outside the quote, and the regex correctly extracts the path.

For f-strings like `f'/path/{var}'`, the regex would extract `/path/{var}` which contains `{` and would fail `_is_path_candidate()` or path validation. This fails closed.

**Severity**: LOW. The regex handles these cases correctly or fails closed.

---

### B-4. Triple-Quoted String Bypass [LOW]

**Vector:**
```python
python3 -c "
import os
path = '''/path/to/secret'''
os.remove(path)
"
```

**Analysis:**
The regex `(?:'([^'\\]*(?:\\.[^'\\]*)*)')` would match the first `'''` as an empty string `''` followed by a bare `/path/to/secret'''`. The path extraction would fail. F1 still fires (fail-closed).

**Severity**: LOW. Fails closed correctly.

---

## SECTION C: Operational Risk Analysis

### C-1. Performance Impact of Moving `split_commands()` Before Layer 0

**Current flow**: Layer 0 short-circuits on block patterns (fast regex scan of raw string) BEFORE `split_commands()` runs.

**Proposed flow**: `split_commands()` runs FIRST (O(n) character-by-character parsing), THEN Layer 0 scans per-sub-command.

**Assessment**: `MAX_COMMAND_LENGTH` is 100,000 bytes. `split_commands()` is a single-pass O(n) parser with no regex backtracking. Processing 100KB in a Python while loop takes milliseconds. The size check can be moved BEFORE `split_commands()` (as proposed in Step 4 of the plan, line 321-332) to prevent parsing oversized commands.

**Risk**: LOW. Performance impact is negligible.

### C-2. Backwards Compatibility

The change modifies `_consume_heredoc_bodies()` signature (new `retain_body` parameter with default `False`). Existing callers that don't pass the parameter get the old behavior (body discarded). This is backwards-compatible.

The change modifies `split_commands()` behavior: heredoc bodies may now appear in sub-command output for interpreter commands. Any code that assumes sub-commands never contain heredoc bodies could break.

**Risk**: MEDIUM. Requires audit of all `split_commands()` consumers.

### C-3. Allowlist Maintenance Burden

`_DATA_HEREDOC_COMMANDS` is a hardcoded frozenset. Adding new commands requires code changes. The plan does not provide a configuration mechanism.

**Risk**: LOW. The fail-closed default (unknown commands retain bodies) means missing commands cause false positives (ask popups), not false negatives (bypasses). This is acceptable.

---

## SECTION D: Cross-Model Synthesis

### Gemini 2.5 Pro Findings

| Finding | Severity | Concurrence |
|---------|----------|-------------|
| Pipe-to-interpreter bypass | CRITICAL | AGREE -- confirmed as complete bypass |
| mysql shell escape (\!) | CRITICAL | AGREE -- confirmed RCE vector |
| sed `e` command RCE | HIGH | AGREE -- GNU sed specific but common |
| sendmail pipe-to-command | CRITICAL | AGREE -- classic vector |
| Decoy literal suppressing F1 | HIGH | AGREE -- valid bypass of safety net |
| glob.glob() as oracle | MEDIUM | AGREE -- information disclosure |
| awk omission correct | NOT-AN-ISSUE | AGREE -- fail-closed by design |
| Multiple heredocs correct | NOT-AN-ISSUE | AGREE -- bash prefix detected |

### Gemini 3 Pro Preview Findings

| Finding | Severity | Concurrence |
|---------|----------|-------------|
| Backslash-escaped delimiter parsing | CRITICAL | AGREE -- parsing differential vulnerability |
| ANSI-C quoting bypass | NOT-AN-ISSUE | AGREE -- fail-closed correctly |
| Variable expansion in command | NOT-AN-ISSUE | AGREE -- fail-closed correctly |
| `env -S` / `sudo -u` flag bypass | HIGH | AGREE -- flag-skipping logic is naive |
| Alias/function redefinition | HIGH | PARTIALLY AGREE -- downgrade to MEDIUM |
| Unterminated heredoc behavior | MEDIUM | AGREE -- exacerbated by retain_body=False |
| Performance DoS | LOW | AGREE -- mitigated by MAX_COMMAND_LENGTH |

### Vibe-Check Meta-Mentor Assessment

The meta-mentor raised a fundamental question: **is an allowlist the right abstraction?** The allowlist tries to enumerate all "safe data" commands, but the set of commands with shell escape features is larger than expected. An inverted approach (denylist of known interpreters, fail-closed for everything else) would be more robust, though the plan already uses fail-closed as the default. The real issue is that commands IN the allowlist can still be dangerous.

---

## SECTION E: Blocking Issues Summary

### BLOCKING Issue 1: Pipe-to-Interpreter Bypass [CRITICAL]
**What**: `cat << EOF | bash` strips the heredoc body because cat is allowlisted, but the body pipes to an interpreter.
**Fix required**: Before stripping a heredoc body, check if the sub-command containing `<<` is part of a pipeline where ANY downstream command is an interpreter. If yes, retain the body. The simplest approach: if the sub-command containing `<<` also contains `|`, never strip the body.

### BLOCKING Issue 2: Database CLI Shell Escapes [CRITICAL]
**What**: `mysql`, `psql`, `sqlite3` have `\!` / `.shell` commands that execute arbitrary shell commands from their input.
**Fix required**: Remove `mysql`, `psql`, and `sqlite3` from `_DATA_HEREDOC_COMMANDS`. Also remove `sendmail` (pipe-to-command via `|` in To: header) and consider removing `sed` (GNU `e` command) and `mail` (`~!` escape).

### BLOCKING Issue 3: Backslash-Escaped Delimiter Parsing Differential [CRITICAL]
**What**: `cat << \EOF` -- Bash treats delimiter as `EOF`, but the parser stores `\EOF`. The parser never finds the terminator and silently discards all subsequent commands (for data heredocs).
**Fix required**: Update `_parse_heredoc_delimiter()` to strip backslashes from bare-word delimiters, matching Bash's actual behavior. Specifically: after extracting the bare word, apply backslash removal (each `\X` becomes `X`).

---

## SECTION F: Non-Blocking Concerns

### Concern 1: Flag-Skipping Logic in `_is_data_heredoc_command()` [HIGH]
The naive `if token.startswith('-'): continue` skips all flags, but flags like `sudo -u <user>` consume the next token. Recommend: fail-closed on unrecognized flags after wrapper commands.

### Concern 2: Decoy Literal Suppressing F1 in Step 6.2 [HIGH]
A benign string literal alongside an obfuscated destructive path can suppress the F1 safety net. Recommend: verify that the destructive API's argument is one of the extracted literals, or require ALL literals to pass validation.

### Concern 3: `glob.glob()` on Untrusted Input in Step 6.2 [MEDIUM]
Calling `glob.glob()` on attacker-controlled strings enables filesystem enumeration. Recommend: use `Path.exists()` for non-glob paths and restrict glob expansion to project-internal paths only.

### Concern 4: Unterminated Heredoc Silently Discards Commands [MEDIUM]
With `retain_body=False`, an unterminated data heredoc silently consumes and discards all remaining script content. Recommend: fail-closed (deny or ask) when a heredoc delimiter is not found.

---

## SECTION G: Recommended Allowlist After Fixes

If the blocking issues are addressed, the safe subset of `_DATA_HEREDOC_COMMANDS` is:

```python
_DATA_HEREDOC_COMMANDS = frozenset({
    # File output (write to file, no execution capability)
    'cat', 'tee',
    # Text processing (read-only, no shell escape)
    'grep', 'egrep', 'fgrep', 'head', 'tail', 'wc', 'sort', 'uniq',
    'cut', 'tr', 'fold', 'fmt', 'column', 'paste', 'join', 'comm',
    # Display (no shell escape)
    'echo', 'printf', 'less', 'more',
    # Data tools (no shell escape)
    'jq', 'yq', 'csvtool',
})
```

**Removed** (shell escape / code execution capabilities):
- `sed` -- GNU `e` command executes shell commands
- `patch` -- modifies files (low risk but not needed)
- `mysql`, `psql`, `sqlite3` -- `\!` / `.shell` executes shell commands
- `mail`, `sendmail` -- pipe-to-command via `|` recipient

---

## SECTION H: Implementation Order Recommendation

1. Fix `_parse_heredoc_delimiter()` backslash handling (BLOCKING)
2. Remove dangerous commands from allowlist (BLOCKING)
3. Add pipe-awareness to body stripping decision (BLOCKING)
4. Fix flag-skipping logic in `_is_data_heredoc_command()` (HIGH)
5. Add unterminated heredoc detection (MEDIUM)
6. Implement Step 6.2 with restricted glob usage (after Step 6.1)
7. Add function-redefinition detection pattern (defense-in-depth)

---

## Final Assessment

The core architecture of Step 6.1 is correct: selective heredoc body retention based on command classification, with fail-closed default. The PROBLEM is in the specific allowlist contents and edge cases in the classification logic. With the three blocking fixes applied, the approach is sound and significantly improves both usability (eliminating false positives) and security (enabling interpreter heredoc body scanning).

Step 6.2 is a well-scoped, fail-closed change with acceptable risk. The decoy literal concern is real but mitigated by the threat model (AI agents do not generate obfuscated code).

**Verdict: PASS WITH CONCERNS** -- implementation can proceed AFTER the three blocking issues are resolved.
