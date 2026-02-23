# Guardian-Memory Conflict: Fix Design Recommendations

**Author:** architect
**Date:** 2026-02-22
**Input:** Root cause analysis from investigator-guardian, memory plugin analysis from investigator-memory
**External opinions:** Codex (via pal clink), Gemini (via pal clink), vibe-check

---

## Problem Summary

The `bash_guardian.py` PreToolUse:Bash hook triggers false `[CONFIRM] Detected write but could not resolve target paths` popups when the memory plugin writes JSON staging files via heredoc. This is caused by a three-layer failure chain:

1. `split_commands()` (line 82) has no heredoc awareness -- splits on newlines inside heredoc body
2. `is_write_command()` (line 635) matches `>` inside JSON content (e.g., `B->A->C`) without quote awareness
3. F1 fail-closed safety net (line 1033) escalates because fake sub-commands yield no extractable paths

Additionally, memory subagents (especially haiku-tier) ignore the SKILL.md Write tool mandate and use `cat > path << 'EOFZ'` heredoc syntax, which triggers the above chain. 7 incidents logged across 20 hours.

---

## Option A: Fix `split_commands()` for Heredoc Awareness (Guardian-Side)

### What It Fixes
- Heredoc body lines no longer appear as independent sub-commands
- Eliminates ALL heredoc-triggered false positives (not just memory plugin)
- Fixes the known limitation documented at `test_bypass_v2.py:142-146`

### Implementation Approach

Add a **pending heredoc queue** to the existing character-by-character state machine. When `<<` or `<<-` is detected at top level (outside quotes/backticks/depth), parse the delimiter word, push a `HeredocSpec` onto a queue, and when the next top-level newline is hit, consume lines until each pending delimiter is matched.

**Pseudocode:**

```python
def split_commands(command: str) -> list[str]:
    sub_commands: list[str] = []
    current: list[str] = []
    depth = 0
    in_single_quote = False
    in_double_quote = False
    in_backtick = False
    pending_heredocs: list[tuple[str, bool]] = []  # (delimiter, strip_tabs)
    i = 0

    while i < len(command):
        c = command[i]

        # ... existing escape/quote/backtick/depth logic unchanged ...

        if depth == 0 and not in_single_quote and not in_double_quote and not in_backtick:

            # Detect heredoc operator: << or <<- (but NOT <<< here-string)
            if (command[i:i+2] == '<<' and
                not command[i:i+3] == '<<<'):

                strip_tabs = command[i:i+3] == '<<-'
                op_len = 3 if strip_tabs else 2
                current.append(command[i:i+op_len])
                i += op_len

                # Skip optional whitespace between << and delimiter
                while i < len(command) and command[i] in ' \t':
                    current.append(command[i])
                    i += 1

                # Parse delimiter word: bare, 'quoted', or "quoted"
                delim, raw_token, i = _parse_heredoc_delimiter(command, i)
                current.append(raw_token)
                pending_heredocs.append((delim, strip_tabs))
                continue

            # Newline handling -- check for pending heredocs
            if c == '\n':
                sub_commands.append(''.join(current).strip())
                current = []
                i += 1

                # Consume heredoc bodies
                if pending_heredocs:
                    i = _consume_heredoc_bodies(command, i, pending_heredocs)
                    pending_heredocs = []
                continue

            # ... rest of existing delimiter logic (;, &&, ||, |, &) unchanged ...

        current.append(c)
        i += 1

    remaining = ''.join(current).strip()
    if remaining:
        sub_commands.append(remaining)

    return [cmd for cmd in sub_commands if cmd]


def _parse_heredoc_delimiter(command: str, i: int) -> tuple[str, str, int]:
    """Parse heredoc delimiter word from position i.

    Handles:
      - Bare word: EOF, EOFZ, END_MARKER
      - Single-quoted: 'EOF' (literal heredoc, no expansion)
      - Double-quoted: "EOF" (expansion-active heredoc)

    Returns: (delimiter_text, raw_token, new_position)
    """
    if i >= len(command):
        return ('', '', i)

    if command[i] in ("'", '"'):
        quote_char = command[i]
        start = i
        i += 1
        while i < len(command) and command[i] != quote_char:
            i += 1
        if i < len(command):
            i += 1  # consume closing quote
        raw_token = command[start:i]
        delim = raw_token[1:-1]  # strip quotes
        return (delim, raw_token, i)

    # Bare word: consume until whitespace, newline, or shell metachar
    start = i
    while i < len(command) and command[i] not in ' \t\n;|&<>()':
        i += 1
    raw_token = command[start:i]
    return (raw_token, raw_token, i)


def _consume_heredoc_bodies(command: str, i: int,
                             pending: list[tuple[str, bool]]) -> int:
    """Consume heredoc body lines until each delimiter is matched.

    For each pending heredoc, reads lines until a line matches the
    delimiter exactly (after optional tab-stripping for <<-).

    Returns: new position after all heredoc bodies consumed.
    """
    for delim, strip_tabs in pending:
        while i < len(command):
            # Find end of current line
            line_start = i
            while i < len(command) and command[i] != '\n':
                i += 1
            line = command[line_start:i]

            # Advance past newline
            if i < len(command):
                i += 1

            # Check if this line matches the delimiter
            cmp_line = line.rstrip('\r')
            if strip_tabs:
                cmp_line = cmp_line.lstrip('\t')
            if cmp_line == delim:
                break
        # If we exhaust the input without finding the delimiter,
        # we've consumed an unterminated heredoc -- fail-closed
        # behavior is handled by the caller (no body lines leaked)
    return i
```

### Edge Cases

| Edge Case | Handling |
|-----------|----------|
| `<<<` (here-string) | Excluded by checking `command[i:i+3] != '<<<'` |
| Multiple heredocs on one line: `cmd <<A <<'B'` | Queue processes all pending in order |
| `<<-` tab stripping | Only strips tabs (not spaces) from delimiter comparison |
| Quoted delimiters (`'EOF'`, `"EOF"`) | Quotes stripped for delimiter matching; quotedness tracked |
| Unterminated heredoc at EOF | Body consumed to end of string; no lines leak to sub-commands |
| `<<` inside quotes/backticks/subshells | Already skipped by existing quote/backtick/depth tracking |
| Commands after heredoc body | Resume normal parsing at position after delimiter line |
| CRLF line endings | `rstrip('\r')` on delimiter comparison lines |

### Security Considerations

**Unquoted heredocs** (`<< EOF`) allow shell expansion (`$()`, backticks) inside the body. The guardian should still scan the *command line itself* (the line containing `<<`), just not the body lines. For security-sensitive analysis of unquoted heredoc bodies, a future enhancement could expose `quoted` metadata to the policy layer. However, for the current use case (eliminating false positives), simply skipping body lines from `is_write_command()` / `extract_paths()` is correct and safe because:

1. The body content is not executed as separate commands -- it's stdin data
2. Even in unquoted heredocs, `>` in the body is literal text, not redirection
3. The command line itself (with the actual `>` redirection) IS still analyzed

### Complexity
- ~60 lines of new code added to `split_commands()` + two helper functions
- Zero changes to existing quote/escape/depth logic
- Backward-compatible: non-heredoc commands parse identically

### Test Cases Required

```python
# Basic heredoc -- should NOT split
assert len(split_commands("cat <<EOF\nhello\nEOF")) == 1

# Quoted heredoc -- should NOT split
assert len(split_commands("cat << 'EOFZ'\ncontent with > arrows\nEOFZ")) == 1

# Heredoc with redirection -- should be 1 command
assert len(split_commands("cat > file << 'EOF'\n{\"a\": \"B->C\"}\nEOF")) == 1

# <<- tab-stripping -- should match tab-indented delimiter
assert len(split_commands("cat <<-EOF\n\tcontent\n\tEOF")) == 1

# <<< here-string -- should NOT trigger heredoc mode
assert len(split_commands("cat <<< 'hello'")) == 1

# Multiple heredocs -- should be 1 command
assert len(split_commands("cmd <<A <<'B'\nbody A\nA\nbody B\nB")) == 1

# Heredoc followed by ; command -- should be 2 commands
assert len(split_commands("cat <<EOF\nbody\nEOF\necho done")) == 2

# Heredoc with > inside -- is_write_command on first sub only
subs = split_commands("cat > file << 'EOF'\n\"B->A->C\"\nEOF")
assert len(subs) == 1
assert is_write_command(subs[0])  # True (for the > file part)

# Existing test case (test_bypass_v2.py:142) -- should now pass
assert len(split_commands('cat <<EOF\n;\nEOF')) == 1
```

---

## Option B: Make `is_write_command()` Quote-Aware (Guardian-Side)

### What It Fixes
- `>` inside quoted strings no longer triggers write detection
- Fixes false positives on commands like `echo "B->A"`, `git commit -m "score > 8"`
- Addresses Investigation Issue A (quote-unaware redirections)

### Implementation Approach

The `_is_inside_quotes()` helper already exists at line 403. Use it to filter `is_write_command()` regex matches:

```python
def is_write_command(command: str) -> bool:
    write_patterns = [
        (r">\s*['\"]?[^|&;]+", True),    # Redirection -- needs quote check
        (r"\btee\s+", False),
        (r"\bmv\s+", False),
        # ... rest unchanged, all False for quote_check ...
        (r":\s*>", True),                  # Truncation -- needs quote check
    ]
    for pattern, needs_quote_check in write_patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            if needs_quote_check and _is_inside_quotes(command, match.start()):
                continue  # Skip: > is inside a quoted string
            return True
    return False
```

### Limitations
- Does NOT fix the heredoc splitting problem (body lines are still separate sub-commands)
- Insufficient as a standalone fix: heredoc body lines like `"B->A"` are unquoted at the sub-command level after `split_commands()` splits them out
- Only helps for non-heredoc commands where `>` appears inside quotes

### Recommendation
**Companion fix to Option A, not a replacement.** The quote-awareness addresses a real separate class of false positives (`echo "B->A"`, `git commit -m "value > threshold"`) that heredoc-awareness alone won't fix.

### Complexity
- ~10 lines changed in `is_write_command()`
- Uses existing `_is_inside_quotes()` helper (already used by `extract_redirection_targets()`)

---

## Option C: Strengthen SKILL.md + Memory-Side Guard Hook (Memory-Side)

### What It Fixes
- Prevents subagent non-compliance with Write tool mandate
- Eliminates the second root cause (subagents using heredoc despite instructions)

### Part C1: Strengthen SKILL.md Wording

Replace the current positive mandate with negative constraints. LLMs (especially smaller models) respond better to prohibitions:

**Current (line 81-83):**
```
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

**Proposed:**
```
> **FORBIDDEN**: You are PROHIBITED from using the Bash tool to create or write
> files in `.claude/memory/.staging/`. This includes `cat >`, `echo >`, heredoc
> (`<< EOF`), `tee`, or any other shell write mechanism. ALL staging file writes
> MUST use the **Write tool** exclusively.
>
> **Anti-pattern (DO NOT DO THIS):**
> ```bash
> # WRONG -- will be blocked by Guardian and memory guard hooks
> cat > .claude/memory/.staging/input-decision.json << 'EOFZ'
> {"title": "..."}
> EOFZ
> ```
>
> **Correct pattern:**
> ```
> Use the Write tool with path: .claude/memory/.staging/input-decision.json
> ```
```

### Part C2: Memory-Side PreToolUse:Bash Guard Hook

Add a new PreToolUse:Bash hook to the memory plugin that detects and blocks heredoc/redirect writes to `.staging/` paths:

**Script:** `hooks/scripts/memory_staging_guard.py`

```python
#!/usr/bin/env python3
"""Memory staging guard -- blocks Bash writes to .staging/ directory.

Enforces the Write tool mandate by detecting cat/echo/heredoc commands
targeting .claude/memory/.staging/ and returning a deny with guidance.
"""
import json
import re
import sys

def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # Not our problem

    if input_data.get("tool_name") != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")

    # Detect writes to .staging/ via bash
    staging_write_pattern = (
        r'(?:cat|echo|tee|printf)\s+.*'
        r'\.claude/memory/\.staging/'
        r'|'
        r'>\s*[\'"]?[^\s]*\.claude/memory/\.staging/'
        r'|'
        r'<<[-]?\s*[\'"]?\w+[\'"]?\s*\n.*\.claude/memory/\.staging/'
    )

    if re.search(staging_write_pattern, command, re.DOTALL | re.IGNORECASE):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Bash writes to .claude/memory/.staging/ are blocked. "
                    "Use the Write tool instead: "
                    "Write(file_path='.claude/memory/.staging/<filename>', "
                    "content='<json>')"
                ),
            }
        }))
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

**Hook registration** in `hooks/hooks.json`:
```json
{
  "type": "PreToolUse",
  "matcher": "Bash",
  "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_staging_guard.py\"",
  "timeout": 5000
}
```

### Hook Ordering Caveat

Claude Code does not guarantee inter-plugin hook execution order. If the Guardian plugin's PreToolUse:Bash hook runs before the memory plugin's hook, the Guardian popup fires first. The memory guard is therefore a **best-effort secondary defense**, not a guaranteed interception. Its primary value is:

1. When Guardian allows (no false positive triggered), the memory guard still catches the non-compliance
2. Even if both fire, the deny from the memory guard provides actionable guidance ("use Write tool")
3. It turns a soft prompt mandate into a hard enforcement mechanism within the plugin's control

### Complexity
- ~40 lines for the guard script
- 1 hook registration entry
- Trivial SKILL.md wording change

---

## Option D: Configuration-Based Allowlist (Guardian-Side)

### What It Would Do
- Add an `allowedBashCommands` or `trustedPaths` config entry to the Guardian
- Auto-allow commands targeting known safe paths (e.g., `.claude/memory/.staging/`)

### Why NOT Recommended

1. **Security regression**: Allowlists create blind spots. A compromised plugin could write arbitrary content to `.staging/` paths and bypass all guardian scanning
2. **Maintenance burden**: Every new plugin staging directory needs config updates
3. **Wrong abstraction**: The problem is a parser bug, not an overly strict policy. Fixing the parser is the correct architectural response
4. **No existing infrastructure**: Grep for `allowedBash`, `allowedPatterns`, `trustedPaths` in the guardian codebase returns zero results -- this would be entirely new config surface area

### Complexity
- Medium (new config parsing, integration with verdict logic)
- High maintenance cost

---

## Option E: Stdout Extraction Pattern (Architectural Alternative)

### What It Would Do
- Subagents return draft JSON inside XML tags in their conversational output
- Main orchestrator parses the response, extracts JSON, writes files itself
- Subagents never call Bash or Write tools for staging

### How It Would Work

**SKILL.md subagent instructions (Phase 1):**
```
Instead of writing a file, return your draft JSON wrapped in XML tags:
<memory_draft category="decision">
{"title": "...", "tags": [...], "content": {...}}
</memory_draft>
```

**Orchestrator (main agent):**
```
Parse subagent response -> extract <memory_draft> content ->
Write tool to .staging/input-<category>.json -> continue Phase 2
```

### Evaluation
- **Eliminates the problem class entirely** -- zero bash/write tool usage by subagents
- **Higher reliability** -- subagents are better at outputting text than choosing the right tool
- **Requires orchestration refactor** -- SKILL.md Phase 1 instructions and main agent parsing logic both change
- **Risk**: XML parsing of subagent output is fragile (what if the LLM doesn't close tags properly?)
- **Claude Code subagent API consideration**: Need to verify that Task tool responses reliably preserve XML-tagged content

### Recommendation
**Long-term consideration, not immediate fix.** The guardian parser fix (Option A) addresses the root cause with lower risk and effort.

---

## Comparison Matrix

| Criterion | A: Heredoc Parser | B: Quote-Aware | C: SKILL.md + Guard | D: Config Allowlist | E: Stdout Extraction |
|-----------|:-:|:-:|:-:|:-:|:-:|
| **Fixes heredoc false positives** | Yes (all plugins) | No (body lines still split) | Prevents trigger (memory only) | Bypasses check | Eliminates trigger |
| **Fixes non-heredoc `>` FP** | No | Yes | N/A | N/A | N/A |
| **Security impact** | Neutral (body skipping is correct) | Neutral | Positive (enforcement) | Negative (blind spots) | Positive (less bash) |
| **Scope** | Guardian (all users) | Guardian (all users) | Memory plugin only | Guardian (config) | Memory plugin only |
| **Implementation complexity** | Medium (~60 LOC) | Low (~10 LOC) | Low (~40 LOC + wording) | Medium (new config) | High (orchestration refactor) |
| **Risk of regression** | Low (existing tests + new) | Very low | Very low | Medium (security) | Medium (fragile parsing) |
| **Addresses root cause** | Yes (parser bug) | Partially (one layer) | No (works around it) | No (bypasses it) | Yes (eliminates bash) |
| **Benefits beyond this issue** | Yes (all heredoc users) | Yes (all `>` in quotes) | No | No | Potentially |

---

## Recommended Approach

### Layered Defense Strategy

**Layer 1 (PRIMARY -- Guardian fix):** Option A + Option B combined

Fix `split_commands()` to add heredoc awareness AND make `is_write_command()` quote-aware. These address two independent bugs:
- Heredoc unawareness: affects any plugin/user writing multi-line content via heredoc
- Quote unawareness: affects any command with `>` inside quoted strings

Both are genuine parser correctness issues in the guardian, not workarounds for the memory plugin.

**Layer 2 (SECONDARY -- Memory-side enforcement):** Option C (both parts)

Strengthen SKILL.md with negative constraints and add the memory staging guard hook. This provides defense-in-depth:
- Even if the guardian is not updated immediately, the memory guard blocks the non-compliant bash writes
- Negative constraint wording improves subagent compliance rates
- The anti-pattern example provides a concrete "don't do this" reference

**Layer 3 (LONG-TERM OPTIONAL):** Option E as future consideration

The stdout extraction pattern is the most architecturally clean solution but requires the highest investment. Consider it when refactoring the memory consolidation pipeline.

**NOT recommended:** Option D (config allowlists) -- creates security regression.

### Implementation Priority

| Order | Action | Owner | Effort |
|-------|--------|-------|--------|
| 1 | Strengthen SKILL.md wording (C1) | claude-memory | 15 min |
| 2 | Add memory staging guard hook (C2) | claude-memory | 30 min |
| 3 | Fix `split_commands()` heredoc (A) | claude-code-guardian | 2-3 hours |
| 4 | Add `is_write_command()` quote-awareness (B) | claude-code-guardian | 30 min |
| 5 | Add comprehensive heredoc tests | claude-code-guardian | 1 hour |

Steps 1-2 can be deployed immediately as the memory-side fix. Steps 3-5 address the guardian root cause and benefit all guardian users.

---

## External Model Opinions

### Codex (via pal clink)

Confirmed the heredoc parser approach. Key recommendations:
- Use a `HeredocSpec` dataclass with `delimiter`, `quoted`, `strip_tabs` fields
- Introduce `split_commands_with_meta()` returning `Chunk` objects that separate command text from heredoc bodies
- Handle `<<<` here-string exclusion explicitly
- Unterminated heredocs should fail closed
- Multiple heredocs per command line must be queued and consumed in order
- Expose `quoted` metadata so policy can distinguish literal vs expansion-active heredocs

### Gemini (via pal clink)

Proposed creative alternatives beyond the standard fixes:
1. **"Stdout Extraction" pattern** -- subagents return JSON in XML tags, orchestrator writes files (our Option E)
2. **"Silent Writer" PreToolUse hook** -- intercepts heredoc commands, writes files natively in Python, returns simulated success to the subagent (creative but complex)
3. **Environment variable payloading** -- `export DRAFT_JSON='...' && python3 memory_write.py --env-payload` (avoids heredoc but content still in bash)
4. **Trust tokens** -- ephemeral env var checked by Guardian for auto-allow (interesting but over-engineered)

Gemini's top recommendation aligned with ours: fix the parser (Option A) for correctness, use memory-side enforcement (Option C) for defense-in-depth.

### Vibe Check

Validated the layered approach. Key feedback:
1. **Promote `is_write_command()` quote-awareness as companion fix** -- not standalone, but addresses separate false positive class (adopted in final recommendation)
2. **Hook ordering caveat** -- Claude Code inter-plugin hook order is not guaranteed; memory guard is best-effort (documented in Option C)
3. **No over-engineering detected** -- each layer is simple and targeted

---

## Key File References

| File | Location | Role |
|------|----------|------|
| bash_guardian.py:82-245 | `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/` | `split_commands()` -- needs heredoc fix |
| bash_guardian.py:403-428 | same | `_is_inside_quotes()` -- existing helper for Option B |
| bash_guardian.py:635-667 | same | `is_write_command()` -- needs quote awareness |
| bash_guardian.py:1033-1038 | same | F1 safety net -- source of popup |
| test_bypass_v2.py:142-146 | `/home/idnotbe/projects/claude-code-guardian/tests/security/` | Known heredoc limitation (test should pass after fix) |
| SKILL.md:81-83 | `/home/idnotbe/projects/claude-memory/skills/memory-management/` | Write tool mandate (needs strengthening) |
| hooks.json | `/home/idnotbe/projects/claude-memory/hooks/` | Hook registration (needs new guard entry) |
