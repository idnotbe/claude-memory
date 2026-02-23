# Guardian-Memory PreToolUse:Bash Conflict Analysis

**Date:** 2026-02-22
**Status:** Research complete (V1 + V2 verified)
**Team:** 8 agents (2 investigators, 1 architect, 3 V1 reviewers, 3 V2 reviewers)
**External models:** Codex 5.3, Gemini 3 Pro (via pal clink)

---

## TL;DR: What to Do

| Action | Where | Effort | Effect |
|--------|-------|--------|--------|
| **Strengthen SKILL.md mandate wording** | claude-memory | 15 min | Reduces subagent non-compliance |
| **Add memory-side PreToolUse:Bash guard** | claude-memory | 30 min | Hard-blocks heredoc writes to `.staging/` |
| Fix `split_commands()` heredoc parsing | claude-code-guardian | 2-3 hr | Fixes all heredoc false positives (Layers 2-4) |
| Make `is_write_command()` quote-aware | claude-code-guardian | 30 min | Fixes `>` in quoted strings false positives |
| Make `scan_protected_paths()` heredoc-aware | claude-code-guardian | 1 hr | Fixes `.env` in heredoc body false positives (Layer 1) |

**Fastest fix: The first two rows (memory-side, 45 minutes total).** These stop the popup by preventing subagents from using heredoc in the first place. The guardian-side fixes address the root parser bug and benefit all guardian users.

---

## 1. Why the Popup Appears

### Two Independent Failure Modes

The popup can be triggered by **two distinct code paths** in `bash_guardian.py`. Both are caused by the same underlying issue: the guardian has no heredoc awareness.

#### Failure Mode A: "Detected write but could not resolve target paths"

**Trigger:** JSON content in heredoc body contains `>` characters (e.g., `B->A->C`, `score > 8`)

**Code path (bash_guardian.py):**
1. `split_commands()` (line 82) splits the heredoc body on newlines -- each JSON line becomes a separate "sub-command"
2. `is_write_command()` (line 635) matches `>` via regex `r">\s*['\"]?[^|&;]+"` -- it has no quote awareness
3. `extract_paths()` (line 478) and `extract_redirection_targets()` (line 431) find no real file paths in the JSON text
4. **F1 fail-closed safety net** (line 1033): `is_write=True` AND `sub_paths=[]` --> escalates to `ask`
5. User sees: `[CONFIRM] Detected write but could not resolve target paths`

**Evidence:** Reproduced empirically. `split_commands("cat > path << 'EOFZ'\n{\"B->A->C\"}\nEOFZ")` produces 3 sub-commands; JSON line triggers `is_write_command=True` but yields no paths.

#### Failure Mode B: "Protected path reference detected: .env"

**Trigger:** JSON content in heredoc body mentions `.env` or other protected path names

**Code path (bash_guardian.py):**
1. `scan_protected_paths()` (line 1009) scans the **entire raw command string** -- including heredoc body
2. `glob_to_literals()` converts `".env"` config entry to literal `".env"` for substring search
3. If JSON content mentions `.env` (e.g., a memory about environment configuration), the literal matches
4. Layer 1 escalates to `ask`: `"Protected path reference detected: .env"`
5. User sees: `[CONFIRM] Protected path reference detected: .env`

**Key difference:** This runs on the raw string at line 1009, BEFORE `split_commands()` at line 1015. Fixing the heredoc parser (Option A) does NOT fix this failure mode.

### Why It Happens Repeatedly (7 Times in 20 Hours)

The SKILL.md already has a mandate to use the Write tool instead of Bash heredoc for staging files. However, **subagents (especially haiku-tier models) ignore this mandate** and fall back to `cat > path << 'EOFZ'` heredoc syntax. Guardian log evidence from `/home/idnotbe/projects/ops/.claude/guardian/guardian.log` shows 7 occurrences across 2026-02-21 to 2026-02-22.

### The Previous Fix That Was Remembered

The user recalled fixing this before. Investigation found **three prior fixes**, but none addressed the current issue:

| Prior Fix | What It Fixed | Status |
|-----------|--------------|--------|
| `--action delete` → `--action retire` rename | Guardian blocked `del` substring in memory_write.py commands | Completed, deployed |
| `/tmp/` → `.staging/` path fix | memory-save command referenced wrong staging path | Completed, deployed |
| Write tool mandate in SKILL.md (Fix C) | Added instruction to use Write tool instead of heredoc | **Deployed but ineffective** -- subagents ignore it |

The Write tool mandate (Fix C) IS the prior fix the user remembers. It was deployed but did not solve the problem because LLM compliance is not 100%.

---

## 2. What Needs to Be Fixed and Where

### claude-memory (this repo) -- Immediate Fixes

**Fix C1: Strengthen SKILL.md mandate wording**

Replace the current positive mandate with explicit prohibition + anti-pattern example:

```markdown
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

**Location:** `skills/memory-management/SKILL.md` lines 81-83

**Rationale:** LLMs (especially smaller models) treat explicit prohibitions ("FORBIDDEN", "NEVER", "PROHIBITED") as harder constraints than positive mandates ("MUST use"). The anti-pattern example provides pattern-matching for the model to detect when it's about to violate the rule.

**Fix C2: Add memory-side PreToolUse:Bash guard hook**

New script `hooks/scripts/memory_staging_guard.py` that detects and blocks Bash writes to `.staging/`:

```python
#!/usr/bin/env python3
"""Memory staging guard -- blocks Bash writes to .staging/ directory."""
import json, re, sys

def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    if input_data.get("tool_name") != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")

    # Detect writes to .staging/ via bash (require redirection operator)
    staging_write_pattern = (
        r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
        r'|'
        r'\btee\s+[^\s]*\.claude/memory/\.staging/'
        r'|'
        r'(?:cp|mv|install|dd)\s+.*\.claude/memory/\.staging/'
    )

    if re.search(staging_write_pattern, command, re.DOTALL | re.IGNORECASE):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Bash writes to .claude/memory/.staging/ are blocked to prevent "
                    "guardian false positives. Use the Write tool instead: "
                    "Write(file_path='.claude/memory/.staging/<filename>', content='<json>')"
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

**Note on hook ordering:** Claude Code does not guarantee execution order between plugins' PreToolUse hooks. If the guardian fires first, the user may see the guardian popup before the memory guard can deny. The memory guard provides defense-in-depth, not guaranteed interception.

### claude-code-guardian -- Medium-Term Fixes

**Fix A: Add heredoc awareness to `split_commands()`**

The `split_commands()` function (line 82) splits on newlines without understanding heredoc syntax. The fix adds a pending heredoc queue to the existing state machine:

1. When `<<` or `<<-` is detected at `depth==0` outside quotes/backticks, parse the delimiter
2. After the next newline, consume body lines until a line matches the delimiter
3. Body lines are NOT added to the sub-commands list

**Implementation notes:**
- ~85 lines of new code (25 inline + 2 helper functions)
- Integration point: lines 179-234 in the `depth == 0` block, BEFORE the newline handler
- Backward-compatible: non-heredoc commands parse identically

**CRITICAL: Arithmetic bypass risk.** The V2 adversarial review identified that `(( x << 2 ))` (bash arithmetic shift) would be falsely detected as a heredoc at `depth==0`. The guardian's state machine does not track `((...))` depth. **Mitigation options:**
1. Add bare `((` / `))` tracking to the state machine
2. Add a guard: `(i == 0 or command[i-1] != '<')` to heredoc detection
3. Use a pre-pass regex approach instead of inline state machine (simpler, avoids the issue)

**Fix B: Make `is_write_command()` quote-aware**

Add `_is_inside_quotes()` check (already exists at line 403) to the `>` redirection pattern:

```python
def is_write_command(command: str) -> bool:
    write_patterns = [
        (r">\s*['\"]?[^|&;]+", True),    # Redirection -- needs quote check
        (r"\btee\s+", False),
        (r"\bmv\s+", False),
        # ... rest unchanged, all False ...
        (r":\s*>", True),                  # Truncation -- needs quote check
    ]
    for pattern, needs_quote_check in write_patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            if needs_quote_check and _is_inside_quotes(command, match.start()):
                continue
            return True
    return False
```

This fixes non-heredoc false positives like `echo "B->A"` and `git commit -m "score > 8"`.

**Fix A2: Make `scan_protected_paths()` heredoc-aware**

`scan_protected_paths()` at line 1009 scans the entire raw command string. To fix Failure Mode B, either:
- Strip heredoc bodies from the raw command before scanning, or
- Run `scan_protected_paths()` per sub-command instead of on the raw string

This is required to fix the `.env`-in-heredoc-body class of false positives.

---

## 3. Comparison and Recommendation

### Option Comparison

| Criterion | C1+C2 (Memory-side) | A+B (Guardian parser) | A2 (Layer 1 fix) | D (Config allowlist) |
|-----------|:---:|:---:|:---:|:---:|
| Fixes Failure Mode A | Prevents trigger | Fixes root cause | No | Bypasses check |
| Fixes Failure Mode B | Prevents trigger | No | Fixes root cause | Bypasses check |
| Security impact | Positive (enforcement) | Neutral (parser fix) | Neutral | **Negative** |
| Scope | Memory plugin only | All guardian users | All guardian users | Per-config |
| Implementation risk | Very low | Medium (arithmetic bypass) | Low | Medium |
| Time to deploy | 45 minutes | 2-3 hours + testing | 1 hour | Medium |

### Recommended Strategy

**Layer 1 (IMMEDIATE -- deploy now):** Fix C1 + C2 in claude-memory
- Stops the popup by preventing subagents from using heredoc
- Covers both failure modes (A and B)
- No changes needed in guardian
- 45 minutes total

**Layer 2 (MEDIUM-TERM):** Fix A + B + A2 in claude-code-guardian
- Addresses the root parser bugs
- Benefits all guardian users, not just memory plugin
- Requires careful handling of arithmetic bypass (Challenge 2a)
- 4-5 hours including tests

**NOT recommended:** Config allowlists (Option D) -- creates security blind spots

**Long-term consideration:** Option E (subagent stdout extraction instead of file writes) eliminates the heredoc trigger entirely but requires orchestration refactoring.

---

## 4. Verification Summary

### V1 Verification (3 reviewers)

| Reviewer | Angle | Verdict | Key Finding |
|----------|-------|---------|-------------|
| v1-code-reviewer | Code correctness | PASS WITH NOTES | `<<<` re-entry edge case in Option A pseudocode |
| v1-security-reviewer | Security | PASS WITH NOTES | Unquoted heredoc `$()` is known limitation, not regression |
| v1-ux-reviewer | UX/usability | PASS WITH NOTES | Deny message should include "why"; monitor retry behavior |

### V2 Verification (3 fresh reviewers)

| Reviewer | Angle | Verdict | Key Finding |
|----------|-------|---------|-------------|
| v2-adversarial | Break the design | PASS WITH NOTES | **CRITICAL: `(( x << 2 ))` arithmetic bypass for Option A** |
| v2-crossmodel | External models | PASS WITH NOTES | Codex/Gemini confirm approach; Gemini proposes pre-pass alternative |
| v2-practical | Implementation | PASS WITH NOTES | **Layer 1 gap: `scan_protected_paths` not fixed by Option A** |

### Consensus Points

All 6 reviewers agree on:
1. Root cause diagnosis is correct
2. C1+C2 should be deployed first
3. Option A needs the arithmetic bypass addressed before implementation
4. Option D (config allowlists) should NOT be used
5. The layered defense strategy is appropriate

---

## 5. Implementation Checklist

### Immediate (claude-memory repo)

- [ ] Update SKILL.md lines 81-83 with prohibition wording + anti-pattern example
- [ ] Create `hooks/scripts/memory_staging_guard.py`
- [ ] Add PreToolUse:Bash entry to `hooks/hooks.json`
- [ ] Test: verify heredoc to `.staging/` is denied with actionable message
- [ ] Test: verify Write tool to `.staging/` still works normally

### Medium-term (claude-code-guardian repo)

- [ ] Add heredoc detection to `split_commands()` (with `((...))` guard)
- [ ] Add `_is_inside_quotes()` check to `is_write_command()`
- [ ] Make `scan_protected_paths()` heredoc-body-aware
- [ ] Add test cases (10+ per the fix design)
- [ ] Verify existing test suite passes (regression check)
- [ ] Verify `test_bypass_v2.py:142-146` now passes
- [ ] Version bump to 1.1.0

---

## Appendix: Key File References

| File | Location | Role |
|------|----------|------|
| bash_guardian.py:82-245 | claude-code-guardian/hooks/scripts/ | `split_commands()` -- no heredoc handling |
| bash_guardian.py:635-667 | same | `is_write_command()` -- quote-unaware `>` regex |
| bash_guardian.py:1009 | same | `scan_protected_paths()` on raw command |
| bash_guardian.py:1033-1038 | same | F1 fail-closed safety net |
| bash_guardian.py:403-428 | same | `_is_inside_quotes()` helper |
| test_bypass_v2.py:142-146 | claude-code-guardian/tests/security/ | Known heredoc limitation |
| SKILL.md:81-83 | claude-memory/skills/memory-management/ | Write tool mandate |
| hooks.json | claude-memory/hooks/ | Hook registration |
| config.json | ops/.claude/guardian/ | Guardian config (no staging allowlist) |
| guardian.log | ops/.claude/guardian/ | 7 incidents logged |

## Appendix: Working Files

| File | Contents |
|------|----------|
| temp/guardian-conflict-investigation.md | Root cause trace (investigator-guardian) |
| temp/guardian-conflict-memory-side.md | Memory plugin analysis (investigator-memory) |
| temp/guardian-conflict-fix-design.md | Fix design with pseudocode (architect) |
| temp/guardian-conflict-v1-code.md | V1 code correctness review |
| temp/guardian-conflict-v1-security.md | V1 security review |
| temp/guardian-conflict-v1-ux.md | V1 UX review |
| temp/guardian-conflict-v2-adversarial.md | V2 adversarial review |
| temp/guardian-conflict-v2-crossmodel.md | V2 cross-model review |
| temp/guardian-conflict-v2-practical.md | V2 practical implementation review |
