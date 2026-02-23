# V1 Code Correctness Review: Guardian-Memory Conflict

**Reviewer:** v1-code-reviewer
**Date:** 2026-02-22
**Scope:** Verify root cause analysis, fix design, and pseudocode against actual source code
**External validation:** Codex 5.3 (via pal clink), vibe-check skill

---

## Checklist Results

### 1. Root Cause Trace: Is the code trace accurate?

**PASS**

Verified against `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/bash_guardian.py`:

- `split_commands()` starts at **line 82** (confirmed: `def split_commands(command: str) -> list[str]:`)
- Newline splitting is at **line 230-234** (confirmed):
  ```python
  if c == "\n":
      sub_commands.append("".join(current).strip())
      current = []
      i += 1
      continue
  ```
- The function spans lines 82-245 (confirmed: line 245 is `return [cmd for cmd in sub_commands if cmd]`)
- There is zero heredoc handling anywhere in the function. Grep for `heredoc`, `here_doc`, `<<` in `split_commands` returns no results.
- The existing code tracks: single quotes, double quotes, backticks, `$()/<()/>()`  depth, backslash escapes. **No heredoc state.**

The investigation's claim that a heredoc command produces multiple sub-commands per line is accurate. Each `\n` in the heredoc body triggers line 230, creating a separate sub-command.

### 2. F1 Safety Net: Does line 1033-1038 produce "Detected write but could not resolve target paths"?

**PASS**

Verified at lines 1031-1038:
```python
# F1: Fail-closed safety net -- if write/delete detected but no paths resolved,
# escalate to "ask" instead of silently allowing (fail-closed)
if (is_write or is_delete) and not sub_paths:
    op_type = "delete" if is_delete else "write"
    final_verdict = _stronger_verdict(
        final_verdict,
        ("ask", f"Detected {op_type} but could not resolve target paths"),
    )
```

This is the exact source of the popup message. The `("ask", ...)` verdict is later emitted at line 1176 (`if final_verdict[0] == "ask":`) and ultimately produces the `[CONFIRM]` popup via `ask_response()` at line 1244.

**Note:** The investigation says "line 1176 emits the ask response." This is correct -- line 1176 is `if final_verdict[0] == "ask":` and line 1244 is `print(json.dumps(ask_response(final_verdict[1])))`. The investigation document references line 1176 for the emission, which is the correct conditional check. The actual print is at 1244 (the investigation says 1176 but the comment at line 1175 says "Handle ask verdict"). Minor documentation imprecision, not a correctness issue.

### 3. `is_write_command` Pattern: Does `r">\s*['\"]?[^|&;]+"` match `B->A->C`?

**PASS**

Verified at line 651:
```python
r">\s*['\"]?[^|&;]+",  # Redirection (existing)
```

This regex matches any `>` followed by optional whitespace, optional quote char, then one or more non-delimiter characters. Testing against `"upgrade path B->A->C"`:
- The `>` in `B->A` matches
- `\s*` matches zero whitespace
- `['\"]?` matches zero (no quote immediately after `>`)
- `[^|&;]+` matches `A->C"`
- Result: `is_write_command` returns `True`

The pattern is entirely quote-unaware. It does not check whether the `>` is inside a quoted string. This is correct as described in the analysis.

### 4. `extract_paths` Behavior: Single-token shlex yields empty `parts[1:]`?

**PASS**

Verified at lines 492-507:
```python
try:
    parts = shlex.split(command, posix=(sys.platform != "win32"))
except ValueError as e:
    log_guardian("DEBUG", f"shlex.split failed ({e}), falling back to simple split")
    parts = command.split()
# ...
for part in parts[1:]:  # Skip command name
```

For a sub-command like `"Use B->A migration path",` (a JSON body line treated as a standalone command after split):
- `shlex.split('"Use B->A migration path",')` produces `['Use B->A migration path,']` (one token -- the quotes are consumed by shlex)
- `parts[1:]` is `[]` (empty)
- `paths` list remains empty

Combined with `extract_redirection_targets()` also finding no redirection in this context (the `>` is inside the original JSON quotes, but after `split_commands` fragmentation, the sub-command as a whole is unquoted -- however `_is_inside_quotes()` on the sub-command string `"Use B->A migration path",` **would** see the `>` inside quotes):

**Important nuance:** `extract_redirection_targets` at line 449-451 calls `_is_inside_quotes(command, match.start())` and would skip the `>` if it's inside quotes in the sub-command. However, the investigation's claim about F1 triggering is still correct because:
1. `is_write_command()` still returns `True` (it does NOT use `_is_inside_quotes`)
2. Both `extract_paths` and `extract_redirection_targets` return empty
3. Therefore `sub_paths` is empty, and F1 fires

This is a subtle but important point: `extract_redirection_targets` is more careful than `is_write_command`, creating a mismatch where write is detected but no targets are found.

### 5. Option A Pseudocode: Is the heredoc parsing logic correct?

**PASS WITH NOTES**

The overall design is architecturally correct:
- Pending heredoc queue model is the right structure
- Consuming bodies at newline boundaries is the correct integration point
- `<<-` tab-stripping comparison is correct
- Multiple heredocs per line (`cmd <<A <<'B'`) handled correctly via queue
- `cat > file << 'EOF'\nbody\nEOF\necho done` correctly produces 2 sub-commands

**Issues found by Codex 5.3 (confirmed):**

**High: `<<<` exclusion is fragile.** The check `command[i:i+2] == '<<' and not command[i:i+3] == '<<<'` can fail when the parser encounters the second `<` of `<<<` on a subsequent iteration. If position `i` lands on the second `<` of `<<<`, the check `command[i:i+2] == '<<'` would match (it sees `<<` starting from the second `<`). However, in practice, the first `<` would be consumed by the existing depth tracking for `<(...)` at line 163, or would be appended to `current` as a literal character. The existing code does not have a special `<` handler at depth 0 outside of `<(...)`, so the first `<` of `<<<` would fall through to `current.append(c)` at line 236. The second `<` would then be at position `i`, and `command[i:i+2]` would be `<<` (the last two `<` of `<<<`). This **is** a real bug if the `<<<` check only looks forward from the current position without checking the previous character.

**Fix suggestion:** Add a guard: `(i == 0 or command[i-1] != '<')` to the heredoc detection condition.

**High: Delimiter parsing lacks escape awareness.** `_parse_heredoc_delimiter` does not handle `\\` escapes inside quoted delimiters (e.g., `<<"EO\"F"`). In practice, escaped delimiters in heredocs are extremely rare, and the memory plugin uses simple delimiters like `EOFZ`. This is a correctness issue for a general-purpose parser but not a blocking issue for the immediate fix.

**Medium: Empty delimiter handling.** If `<<` is followed immediately by `\n`, the delimiter is empty string, and any blank line in the body would terminate the heredoc. The pseudocode should either reject empty delimiters or handle them explicitly.

**Assessment:** The pseudocode is correct for the 95%+ common case. The edge cases identified by Codex are legitimate but should be addressed as refinements, not blockers. A `# TODO: handle <<<` re-entry and escaped delimiters` comment would be appropriate if shipping the initial fix without these.

### 6. Option B: Does `_is_inside_quotes()` exist and is its usage correct?

**PASS**

Verified at lines 403-428:
```python
def _is_inside_quotes(command: str, pos: int) -> bool:
```

The function exists and is already used by `extract_redirection_targets()` at line 451:
```python
if _is_inside_quotes(command, match.start()):
    continue
```

The proposed usage in Option B (calling `_is_inside_quotes(command, match.start())` for `is_write_command()` regex matches) is consistent with the existing usage pattern. The function correctly tracks single quotes, double quotes, and backslash escapes.

**However**, Option B alone is insufficient as a fix because heredoc body lines, after being split by `split_commands()`, are independent sub-commands. A line like `"Use B->A migration path",` as a standalone sub-command string has `"` at position 0 -- the `>` at position 8 IS inside quotes at the sub-command level. So `_is_inside_quotes` would actually work for this specific case. But not all heredoc body lines are quoted (e.g., bare `{` or `}` lines, or lines like `"key": "B->A"` where quotes are balanced and `>` is inside them).

The analysis correctly states Option B is a companion fix, not a replacement for Option A.

### 7. Option C: Is the staging guard regex robust?

**PASS WITH NOTES**

The proposed regex:
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

**Bypass vectors identified:**

1. **Command not in list:** `cp source .claude/memory/.staging/file` -- `cp` is not in the `(?:cat|echo|tee|printf)` group. Similarly `dd`, `install`, `mv`.
2. **Path traversal:** `cat > /project/../project/.claude/memory/.staging/file` -- the literal `.claude/memory/.staging/` still matches, but `../` prefix could confuse path resolution.
3. **Bash indirection:** `bash -c 'cat > .claude/memory/.staging/file'` -- the inner command is inside quotes, so the top-level regex may not match depending on how the outer command is structured.
4. **Variable expansion:** `DIR=".claude/memory/.staging"; cat > "$DIR/file"` -- variable indirection hides the path.

**Assessment:** The guard is defense-in-depth and does not need to be watertight. The hook ordering caveat (Claude Code does not guarantee inter-plugin hook order) means the guardian may fire first anyway. The regex catches the observed failure mode (haiku subagents using `cat > path << 'EOFZ'`), which is sufficient for its purpose. The bypasses above require intentional evasion, not accidental subagent behavior.

---

## Additional Findings

### Finding A: Investigation line reference imprecision

The investigation says the ask verdict is emitted at "line 1176". Verified:
- Line 1175: `# ========== Handle ask verdict (from Layer 0b or Layer 1) ==========`
- Line 1176: `if final_verdict[0] == "ask":`
- Line 1244: `print(json.dumps(ask_response(final_verdict[1])))`

The verdict check is at 1176, the actual print is at 1244. The investigation is not wrong (1176 is where the ask path begins), but it could be clearer. Minor documentation issue.

### Finding B: `extract_redirection_targets` and `<<` handling

The investigation claims `extract_redirection_targets()` regex `<(?!<)` would match the second `<` of `<<` and capture `'EOFZ'` as a bogus path. Let me verify:

The regex at line 447: `r'(?:(?:\d|&)?(?:>\|?|>{2})|<(?!<))\s*([^\s;|&<>]+)'`

For input `cat > path << 'EOFZ'`:
- The `<(?!<)` negative lookahead means: match `<` NOT followed by `<`
- In `<<`, the first `<` IS followed by `<`, so `<(?!<)` does NOT match
- The second `<` IS followed by a space (or `'`), so `<(?!<)` DOES match
- It would capture `'EOFZ'` as a redirection target (after stripping quotes at line 454: `target = match.group(1).strip("'\"")`), yielding `EOFZ`

However, this analysis applies to the **first sub-command** (`cat > path << 'EOFZ'`) which already has `is_write=True` from the `>` redirection AND has a valid path from the `> path` redirection. So `sub_paths` is non-empty and F1 does NOT fire for this sub-command. The investigation correctly notes that F1 fires on the **body line** sub-commands, not the first line.

The bogus `EOFZ` path is a separate minor issue (it could cause a false path check) but does not change the main failure chain.

### Finding C: Existing heredoc test coverage

Verified at `test_bypass_v2.py:142-146`:
```python
# 1f. Heredoc with separator
result = split_commands('cat <<EOF\n;\nEOF')
# Tokenizer doesn't track heredocs
test("tokenizer: heredoc with ; should NOT split at ;",
     len(result), 1, "tokenizer")
```

This test **expects 1 result but currently fails** (the tokenizer produces multiple results). It is a known limitation test, not a passing test. The comment "Tokenizer doesn't track heredocs" documents the gap.

Also verified `test_v2fixes_adversarial.py:154-161`:
```python
def test_f1_heredoc_write_bypass(self):
    """cat << EOF > /etc/passwd -- heredoc with redirect."""
    cmd = "cat << EOF > /tmp/output"
    self.assertTrue(is_write_command(cmd))
```

This test only checks `is_write_command` on a single-line heredoc command (no body, no newlines). It passes because `>` in the command triggers the write detection. It does NOT test the full flow with heredoc body splitting.

---

## Overall Verdict

### **PASS WITH NOTES**

**Root cause analysis:** Accurate. All line numbers verified. The three-layer failure chain (split on newline -> `>` regex matches arrows -> F1 fires on empty paths) is correctly traced through the source code.

**Fix design (Option A):** Architecturally sound. The pending heredoc queue approach is correct. Pseudocode has two edge-case issues (Codex-confirmed: `<<<` re-entry, escape-unaware delimiter parsing) that should be addressed during implementation but do not invalidate the design.

**Fix design (Option B):** Correct companion fix. `_is_inside_quotes()` exists and works. Properly scoped as supplementary, not standalone.

**Fix design (Option C):** Adequate for defense-in-depth. Regex is bypassable via indirection but catches the observed failure mode. Hook ordering caveat is properly documented.

**No blocking correctness issues found.** The analysis is ready for V2 verification with the notes above incorporated.
