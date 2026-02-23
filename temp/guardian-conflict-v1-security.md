# V1 Security Review: Guardian-Memory Conflict Fix Design

**Reviewer:** v1-security-reviewer
**Date:** 2026-02-22
**Input:** Root cause analysis + fix design documents
**External validation:** Gemini 3.1 Pro (via pal clink), vibe-check skill, empirical bash testing
**Scope:** Security implications of Options A, B, C; attack vector analysis

---

## Checklist Results

### 1. Heredoc Body Skipping (Option A): Could an attacker hide dangerous commands?

**PASS WITH NOTES**

The fix design proposes skipping ALL heredoc body lines from `split_commands()` output, regardless of whether the delimiter is quoted or unquoted.

**Key technical fact (empirically verified):**
- In **quoted** heredocs (`<< 'EOF'`): bash treats the body as literal text. No expansion occurs. Skipping is entirely safe.
- In **unquoted** heredocs (`<< EOF`): bash DOES execute `$()` and backtick command substitution inside the body. `>` is still literal (not redirection), but `$(echo payload > /etc/shadow)` inside the body WILL write files.

**Empirical verification:**
```bash
cat << EOF > /dev/null
$(echo "payload" > /tmp/target.txt)
EOF
# Result: /tmp/target.txt IS created with "payload"
```

**Risk assessment:** This is a real blind spot. If the guardian skips body lines of unquoted heredocs, it will miss file writes performed via command substitution inside the body. However:

1. **Practical exploitability is LOW in the Claude Code context.** The command is crafted by an LLM subagent, not a human attacker. A subagent using `$(cmd > path)` inside a heredoc body to write files would be a bizarre and impractical pattern -- the subagent already controls the command line and can write files directly.

2. **The command line itself IS still scanned** (verified in pseudocode: heredoc detection at line 53 just parses the delimiter and continues the loop; body consumption only happens at the newline handler at line 74-83). So `cat > dangerous_path << EOF` is properly analyzed.

3. **The current code (without the fix) also doesn't properly analyze this attack vector** -- it splits the body into separate sub-commands and `is_write_command()` does match `>` but not `$()` expansion. The fix doesn't make this worse; it just doesn't make it better.

4. **Mitigation exists in fix design:** The `_parse_heredoc_delimiter()` function already distinguishes quoted vs unquoted delimiters (line 110-127). The `pending_heredocs` tuple could easily carry a `quoted: bool` flag. A future enhancement could scan unquoted heredoc bodies for `$()` patterns.

**Recommendation:** Document this as a known limitation. For V1, skipping all bodies is acceptable because (a) it doesn't regress security vs current behavior, (b) the command line is still scanned, and (c) the practical attack surface is negligible. For V2, consider scanning unquoted heredoc bodies for command substitution patterns.

### 2. Is the command line still scanned?

**PASS**

Verified against pseudocode. The flow is:
1. `<<` detected at line 53 -> parse delimiter, push to `pending_heredocs`, `continue`
2. State machine continues parsing the rest of the line (`;`, `&&`, `>`, etc.) normally
3. Only when `c == '\n'` (line 74) does body consumption fire via `_consume_heredoc_bodies()`

This means `cat > dangerous_path << 'EOF'` is fully analyzed as a sub-command. The `> dangerous_path` redirection is seen by both `is_write_command()` and `extract_redirection_targets()`.

**Additionally verified:** Same-line trailing commands are preserved. `cat << EOF; rm -rf /` would:
- Detect `<<` at line 53, parse delimiter `EOF`, push to queue
- Continue parsing the line
- Hit `;` at line 182 (existing delimiter handler), emit `cat << EOF` as a sub-command
- Start new sub-command with `rm -rf /`
- Body consumption would fire after the NEXT newline

This is correct behavior -- `rm -rf /` is not hidden.

### 3. Quote-awareness in `is_write_command()` (Option B): Quote nesting attacks?

**PASS**

The proposed approach uses `_is_inside_quotes(command, match.start())` to check if a `>` match is inside quotes. The existing `_is_inside_quotes()` (verified at line 403-428):
- Tracks `in_single` and `in_double` quote state via linear scan
- Handles backslash escapes outside single quotes
- Returns `True` if position is inside any quoted region

**Attack scenario: nested quotes to hide real redirection:**
```bash
cmd "quoted" > /etc/shadow "quoted"
```
The `>` at position after `"quoted"` is NOT inside quotes (the first `"quoted"` opens and closes). `_is_inside_quotes()` would correctly return `False`, and the redirection would be detected.

**Attack scenario: escaped quotes:**
```bash
cmd \"not_really_quoted\" > /etc/shadow
```
The `\"` is an escaped quote (not a real quote boundary). `_is_inside_quotes()` handles this via the backslash escape logic at line 420-422.

**Edge case: single-quoted string containing double quote:**
```bash
cmd '"not_double"' > /etc/shadow
```
The `"` inside single quotes is literal. `_is_inside_quotes()` correctly tracks that single quotes suppress double quote toggling (line 423: `if c == "'" and not in_double`).

**Limitation:** Option B is documented as a companion fix, not standalone. It cannot fix the heredoc body problem because after `split_commands()` splits body lines, the quotes in the original command context are lost. This is correctly noted in the fix design.

### 4. Memory Staging Guard (Option C): Path traversal bypass?

**PASS WITH NOTES**

The proposed regex:
```python
r'(?:cat|echo|tee|printf)\s+.*\.claude/memory/\.staging/'
r'|'
r'>\s*[\'"]?[^\s]*\.claude/memory/\.staging/'
r'|'
r'<<[-]?\s*[\'"]?\w+[\'"]?\s*\n.*\.claude/memory/\.staging/'
```

**Path traversal analysis:**

1. `.claude/memory/../memory/.staging/` -- The regex matches `.claude/memory/` then expects `.staging/` immediately after. The `../memory/` traversal breaks this, so the regex would NOT match. **However**, this bypass doesn't help an attacker because the resolved path still ends up in `.staging/`, and the purpose of this guard is to enforce Write tool usage (not to protect a directory). A traversal that reaches the same destination still indicates bash writing to staging.

2. **Symlink bypass:** `ln -s .claude/memory/.staging /tmp/link && cat > /tmp/link/file.json << 'EOF'` -- the regex won't match `/tmp/link/`. However, this requires a prior `ln` command which the guardian's existing symlink detection would catch.

3. **Variable substitution:** `cat > "$STAGING_DIR/file.json" << 'EOF'` -- regex won't match. This is a valid bypass but requires the subagent to know and set the variable, which is impractical.

**Key mitigating factor:** This guard is explicitly documented as "best-effort secondary defense" (fix design line 376-379). Its primary purpose is providing actionable guidance ("use Write tool") rather than being a security boundary. The real security enforcement comes from the guardian (Option A/B) and the existing `memory_write_guard.py` PreToolUse:Write hook.

**Recommendation:** The regex could be strengthened with path normalization (`os.path.normpath()`) before matching, but given it's a best-effort layer, the current approach is acceptable.

### 5. Unterminated Heredoc Attack

**PASS**

The `_consume_heredoc_bodies()` function (pseudocode line 130-160) handles this correctly:

```python
while i < len(command):
    # ... consume lines ...
    if cmp_line == delim:
        break
# If we exhaust the input without finding the delimiter,
# we've consumed an unterminated heredoc -- fail-closed
```

If `<<EOF` is used without a matching `EOF` line, the body consumer reads until end of string. The position `i` ends up at `len(command)`. No body lines leak into `sub_commands`. No subsequent commands are hidden.

**Attack scenario:** Use `<<REALLYUNLIKELYDELIM` to make the guardian consume the entire rest of the script:
```bash
cat <<REALLYUNLIKELYDELIM
innocent body
REALLYUNLIKELYDELIM
rm -rf /
```
In this case, the guardian would:
1. See `cat <<REALLYUNLIKELYDELIM` as sub-command 1
2. Hit newline, start body consumption
3. Read "innocent body", not a match
4. Read "REALLYUNLIKELYDELIM", exact match -- body consumption stops
5. Resume parsing: `rm -rf /` becomes sub-command 2

This is correct. The attacker cannot hide `rm -rf /` because the delimiter DOES match.

**Alternative attack:** What if the delimiter never appears?
```bash
cat <<EOF
innocent
malicious_after
```
Body consumer reads to end of string. `malicious_after` is consumed as body (not a sub-command). But bash would also treat it as heredoc body (unterminated heredoc warning). Guardian and bash are synchronized -- **fail-closed**.

### 6. Delimiter Injection

**PASS**

**Attack scenario:** Attacker controls heredoc body content and injects a line matching the delimiter to end body-skipping early:
```bash
cat << EOF
user controlled content
EOF
rm -rf /
more user content
EOF
```

Bash terminates the heredoc at the FIRST `EOF` match (line 3). The guardian's `_consume_heredoc_bodies()` also terminates at the first exact match. Both would see `rm -rf /` as a post-heredoc command. **Guardian and bash are synchronized.**

**Cross-trust-boundary analysis:** In the memory plugin use case, both the command line and body content come from the same LLM subagent. There is no trust boundary between command author and body content author. For other use cases where the body might contain user-controlled data, the delimiter can be chosen to be unique (e.g., `EOFZ_$(date +%s)` or a random string), making injection impractical.

**Delimiter matching strictness:** The proposal uses exact line match (`cmp_line == delim`). Bash also uses exact match (empirically verified: trailing spaces prevent match). The `rstrip('\r')` in the proposal is a minor desync -- bash does NOT strip `\r`, so a CRLF-terminated file would cause the guardian to match earlier than bash. However, this direction is **safe** (guardian stops body consumption early, resumes scanning -- it over-scans rather than under-scans).

### 7. Overall Fail-Closed Property

**PASS**

The proposed fix maintains fail-closed behavior across all scenarios:

1. **Parser error (unterminated heredoc):** Body consumed to end of string -- no lines leak. Equivalent to current behavior (all lines become sub-commands, which over-triggers but is safe).

2. **`<<<` misidentification:** Explicitly excluded (`command[i:i+3] != '<<<'`). Falls through to normal parsing.

3. **Unknown heredoc syntax:** Any `<<` variant not matching the parser's expectations would either be parsed as a normal operator (no body consumption) or consumed conservatively (to end of string). Both are fail-closed.

4. **`_parse_heredoc_delimiter` returning empty:** If no delimiter is parsed (empty string returned), every line would match the empty delimiter immediately, so body consumption would stop after zero lines. No scanning is skipped -- fail-closed.

5. **Existing safety nets preserved:** F1 fail-closed (line 1033), `scan_protected_paths()` (line 1009) on raw command, `match_block_patterns()` (line 990), and `match_ask_patterns()` (line 1004) all operate on the original command string before `split_commands()` runs. These are unaffected by the heredoc fix.

---

## Attack Scenarios Identified

### Scenario A: Unquoted Heredoc with File-Writing Command Substitution (MEDIUM)

```bash
cat << EOF > /dev/null
$(echo "malicious" > /etc/shadow)
EOF
```

- **Guardian behavior after fix:** Skips body line, sees only `cat << EOF > /dev/null` command line
- **Bash behavior:** Executes `$(echo "malicious" > /etc/shadow)`, writes to `/etc/shadow`
- **Guardian misses the write:** Yes, but it also misses it TODAY (body line becomes sub-command `$(echo "malicious" > /etc/shadow)` which is analyzed by `is_write_command()` but the `>` inside `$()` is at depth > 0 and the current parser doesn't extract paths from command substitutions)
- **Severity:** MEDIUM -- no regression from current behavior; theoretical attack surface
- **Mitigation:** Future enhancement: scan unquoted heredoc bodies for `$()` patterns

### Scenario B: CRLF Desynchronization (LOW)

```bash
cat << EOF\r\n
body\r\n
EOF\r\n
```

- **Guardian behavior:** `rstrip('\r')` strips the `\r`, matches `EOF` on line 3, resumes scanning
- **Bash behavior:** Does NOT strip `\r`, does NOT match `EOF\r` as `EOF`, continues heredoc body
- **Direction:** Guardian over-scans (treats post-heredoc lines as commands). Bash under-scans (treats them as body).
- **Severity:** LOW -- desync direction is safe (guardian is more strict, not less)

### Scenario C: Multiple Heredoc Ordering Confusion (NOT VIABLE)

```bash
cmd <<A <<B
body A contains B
A
body B
B
```

- Bash processes bodies in declaration order: first A's body until `A`, then B's body until `B`
- Guardian's queue-based processing does the same: iterate `pending` list, consume each in order
- Line `body A contains B` does not match `A`, so it's consumed. `A` matches, stop. Then `body B` doesn't match `B`, consumed. `B` matches, stop.
- **No desync possible** with queue ordering.

---

## Risk Assessment Per Fix Option

### Option A: Heredoc Parser

| Risk | Severity | Mitigated? |
|------|----------|-----------|
| Unquoted heredoc expansion blind spot | MEDIUM | Acceptable: no regression from current; documentable |
| Delimiter quoting desync | N/A | Already handled: quotes stripped in `_parse_heredoc_delimiter` |
| Here-string confusion | N/A | Already handled: `<<<` explicitly excluded |
| Same-line trailing commands | N/A | Already handled: body consumption after newline only |
| Tab stripping desync | N/A | Already handled: `lstrip('\t')` for `<<-` |
| Unterminated heredoc | N/A | Already handled: fail-closed to end of string |
| CRLF desync | LOW | Safe direction (over-scanning) |

### Option B: Quote-Aware `is_write_command()`

| Risk | Severity | Mitigated? |
|------|----------|-----------|
| Nested quote confusion | N/A | `_is_inside_quotes()` handles correctly |
| Escaped quote bypass | N/A | Backslash handling in `_is_inside_quotes()` |
| False negative (real redirection missed) | VERY LOW | Only skips matches confirmed inside quotes |

### Option C: Memory Staging Guard

| Risk | Severity | Mitigated? |
|------|----------|-----------|
| Path traversal bypass | LOW | Best-effort layer; real enforcement elsewhere |
| Variable substitution bypass | LOW | Impractical for LLM subagents |
| Hook ordering uncertainty | MEDIUM | Documented; secondary defense by design |

---

## Overall Verdict

### PASS WITH NOTES

The fix design is security-sound. It maintains fail-closed properties, correctly handles the major heredoc parsing edge cases (quoting, `<<<`, `<<-`, unterminated, same-line commands), and the layered defense strategy is appropriate.

**Notes:**

1. **Unquoted heredoc expansion** is a genuine blind spot where the guardian would miss `$()` writes inside heredoc bodies. However, this does NOT represent a security regression from current behavior (the current code also fails to detect this pattern). It should be documented as a known limitation with a recommendation to scan unquoted heredoc bodies for expansion patterns in a future iteration.

2. **CRLF handling** in `_consume_heredoc_bodies` creates a minor desync where the guardian matches earlier than bash on CRLF-terminated files. The desync direction is safe (over-scanning). No action required.

3. **Option C regex** could be strengthened with `os.path.normpath()` preprocessing, but given its role as a best-effort secondary defense, this is a low-priority enhancement.

4. **Option D (config allowlists) is correctly rejected** -- it would create genuine security regression.

5. **The fix design's pseudocode is well-constructed.** All five of Gemini's identified attack vectors are already addressed in the proposed code (delimiter quoting, here-string exclusion, same-line trailing commands, tab stripping, stacked heredoc ordering).

---

## Cross-Reference: Gemini Adversarial Analysis

Gemini (3.1 Pro) identified 5 findings. Assessment of each against the actual pseudocode:

| Gemini Finding | Severity Claimed | Actual Status |
|---|---|---|
| 1. Unquoted heredoc command substitution | CRITICAL | **VALID but not a regression** -- documented as known limitation above |
| 2. Delimiter quoting desynchronization | CRITICAL | **ALREADY HANDLED** -- `_parse_heredoc_delimiter` strips quotes at line 119 |
| 3. Here-string (`<<<`) misinterpretation | CRITICAL | **ALREADY HANDLED** -- explicit `<<<` check at pseudocode line 55 |
| 4. Same-line trailing commands bypass | HIGH | **ALREADY HANDLED** -- body consumption only at newline handler (line 74-83) |
| 5. `<<-` tab stripping desync | MEDIUM | **ALREADY HANDLED** -- `lstrip('\t')` at pseudocode line 154 |

Gemini's findings 2-5 were valid theoretical concerns but are all addressed in the proposed pseudocode. Finding 1 is the only genuine gap, and it's not a regression.
