# Guardian Conflict Investigation: Memory Plugin Side

**Investigator:** investigator-memory
**Date:** 2026-02-22
**Scope:** claude-memory plugin's role in PreToolUse:Bash popup conflict with claude-code-guardian

---

## 1. How SKILL.md Instructs Staging Writes

### The Write Tool Mandate (SKILL.md lines 81-83)

SKILL.md contains an explicit mandate at the top of the subagent instructions section:

```
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

This mandate was added as part of the `memory_draft.py` introduction (confirmed in `temp/review-draft-security.md` line 12 and `temp/impl-skill-report.md` line 14). The Write tool is specified for three staging write operations:

1. **Step 2** (line 91-92): Writing `new-info-<category>.txt` summary files
2. **Step 6** (line 116-117): Writing `input-<category>.json` partial JSON files
3. **Step 9** (line 155): Writing `draft-<category>-retire.json` retire action files

### The Compliance Problem

Despite this mandate, **subagents (especially haiku-tier models) sometimes use `cat > path << 'EOFZ'` heredoc syntax instead of the Write tool**. Evidence from the guardian log at `/home/idnotbe/projects/ops/.claude/guardian/guardian.log`:

| Timestamp | ASK Reason | Command |
|-----------|-----------|---------|
| 2026-02-21T18:13:31 | "could not resolve target paths" | `cat > .../.staging/input-session_summar...` |
| 2026-02-21T18:23:12 | "Protected path: .env" | `cat > .../.staging/input-session_summar...` |
| 2026-02-21T18:44:12 | "Protected path: .env" | `cat > .../.staging/input-session_summar...` |
| 2026-02-21T20:38:53 | "could not resolve target paths" | `cat > .../.staging/update-session-v1.js...` |
| 2026-02-22T00:07:21 | "could not resolve target paths" | `cat > .../.staging/input-preference.jso...` |
| 2026-02-22T14:20:10 | "could not resolve target paths" | `cat > .../.staging/input-constraint.jso...` |
| 2026-02-22T14:31:07 | "could not resolve target paths" | `cat > .../.staging/input-session_summar...` |

This shows the problem is **recurring and ongoing** -- 7 instances across ~20 hours.

---

## 2. Previous Fix Attempts Found

### Fix A: `--action delete` to `--action retire` Rename (2026-02-18)

**Files:**
- `/home/idnotbe/projects/claude-memory/temp/fix-claude-memory.md` -- Implementation instruction file
- `/home/idnotbe/projects/ops/.claude/memory/tech-debt/guardian-regex-blocks-memory-delete.json` -- Tech debt record
- `/home/idnotbe/projects/ops/.claude/memory/sessions/plugin-memory-guardian-compat-analysis.json` -- Session summary

**What it fixed:** Guardian's block pattern `(?i)(?:rm|rmdir|del|remove-item).*\.claude` matched the substring `del` inside `--action delete` in memory_write.py commands. This BLOCKED (not just ASK) all soft-retire operations, breaking the session rolling window entirely.

**Resolution:** Renamed `--action delete` to `--action retire` across 25+ locations in 7 files. Also added `delete`/`deletion` to Guardian regex patterns with proper command-position anchoring. Double-verified (V1: 3 reviewers PASS, V2: completeness + 47/47 regex tests PASS).

**Status:** COMPLETED and deployed. This was a **different issue** from the current heredoc popup.

### Fix B: Staging Path Fix -- `/tmp/` to `.staging/` (prior session)

**File:** `/home/idnotbe/projects/claude-memory/temp/team-staging-path-fix.md`

**What it fixed:** `commands/memory-save.md` referenced `/tmp/.memory-write-pending.json`, but `memory_write.py`'s `_read_input()` enforced `.claude/memory/.staging/` paths only. The `/memory:save` command was completely non-functional.

**Resolution:** Updated 2 lines in `commands/memory-save.md` to use `.staging/` path.

**Status:** COMPLETED.

### Fix C: Write Tool Mandate in SKILL.md (part of memory_draft.py introduction)

**File:** `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md` line 81-83

**What it fixed:** Previously, subagents wrote staging files via Bash heredoc. If the JSON content happened to mention `.env` or other protected paths, Guardian's Layer 1 raw command scan flagged it as a protected path reference. The mandate instructs subagents to use the Write tool instead.

**Status:** DEPLOYED but **NOT EFFECTIVE** -- subagents (especially haiku) ignore the mandate and still use heredoc. This is the current unresolved issue.

---

## 3. Root Cause Analysis: Why Heredocs Trigger Guardian Popups

### Two distinct failure modes:

#### Failure Mode 1: "Detected write but could not resolve target paths"

**Trigger chain:**
1. Subagent uses `cat > /path/.staging/input.json << 'EOFZ'\n{json}\nEOFZ`
2. Guardian's `split_commands()` (bash_guardian.py line 230) splits on `\n` -- it has NO heredoc awareness
3. First fragment becomes: `cat > /path/.staging/input.json << 'EOFZ'`
4. `is_write_command()` returns `true` (matches `>\s*` pattern at line 651)
5. `extract_paths()` calls `shlex.split()` which can't parse `<<` heredoc syntax properly
6. `extract_redirection_targets()` regex `r'(?:(?:\d|&)?(?:>\|?|>{2})|<(?!<))\s*([^\s;|&<>]+)'` at line 447 -- the `<(?!<)` negative lookahead should skip the first `<` of `<<`, but the second `<` matches and captures `'EOFZ'` as a bogus "path"
7. Result: `is_write` is true but `sub_paths` is empty or contains only bogus paths
8. Fail-closed logic at line 1033-1037 escalates to ASK: `"Detected write but could not resolve target paths"`

#### Failure Mode 2: "Protected path reference detected: .env"

**Trigger chain:**
1. Same heredoc command, but JSON content contains the string `.env` (e.g., in a memory about environment variables)
2. Guardian's Layer 1 `scan_protected_paths()` scans the ENTIRE raw command string
3. Since split_commands fragments the heredoc, the JSON body lines become separate sub-commands, but Layer 1 runs on the full original command before splitting
4. The `.env` literal from `glob_to_literals()` matches inside the JSON content
5. Layer 1 escalates to ASK: `"Protected path reference detected: .env"`

### Key insight: These are TWO independent bugs

- **Guardian bug:** `split_commands()` has no heredoc awareness, breaking multi-line bash constructs
- **Memory bug:** Subagents ignore the Write tool mandate, using heredoc despite explicit instructions

---

## 4. Alternative Write Mechanisms Considered

### From vibe-check analysis:

1. **Strengthen the Write tool mandate** -- The current mandate uses positive language ("MUST use"). LLMs (especially smaller ones) respond better to negative constraints: "You are FORBIDDEN from using the bash tool to create staging files."

2. **Add a bash guardian for memory** -- A new PreToolUse:Bash hook in the memory plugin itself that detects `cat >` commands targeting `.staging/` and blocks them with a helpful error pointing to the Write tool. This turns a soft mandate into hard enforcement.

### From Gemini clink analysis:

1. **Native MCP/Plugin Tool Integration** -- Register `memory_write.py` directly as an MCP tool, bypassing bash entirely. LLM outputs JSON natively via tool-calling infrastructure.

2. **Base64 Echo-Decode Pattern** -- `echo "<base64>" | base64 -d > path` -- single-line (no newline splitting) and obfuscated (no Layer 1 scanning). Fragile for LLMs to generate correctly.

3. **STDIN Payload Delivery** -- `echo '{"json"}' | python3 memory_write.py --stdin` -- eliminates the staging file entirely.

4. **Granular CLI Arguments** -- Accept memory fields as CLI args instead of a JSON file: `memory_write.py --title "..." --tags "a,b"`. Eliminates staging but content args still trigger Layer 1.

5. **Environment Variable Injection** -- `export MEM_PAYLOAD='...' && python3 memory_write.py --read-env`. Avoids bash scanning of content.

### Evaluation of alternatives:

| Approach | Guardian-safe | LLM-reliable | Implementation cost | Risk |
|----------|:---:|:---:|:---:|:---:|
| Strengthen mandate wording | Partial | Low | Trivial | Still probabilistic |
| Memory-side bash guard | Yes | N/A (enforcement) | Low | Over-engineering? |
| MCP tool registration | Yes | High | High | Architecture change |
| Base64 pattern | Yes | Low | Low | LLMs can't reliably base64 |
| STDIN delivery | Partial | Medium | Medium | Content still in bash |
| Fix guardian split_commands | Yes (for this) | N/A | Medium | Broader guardian change |

---

## 5. Recommendations

### Immediate fix (memory side):
1. **Strengthen SKILL.md mandate wording** with negative constraints and explicit prohibition
2. Consider adding a concrete example of what NOT to do (anti-pattern)

### Short-term fix (guardian side):
3. **Fix `split_commands()` to recognize heredoc syntax** (`<<` and `<<'DELIM'`) and not split inside the heredoc body. This is a genuine parsing bug affecting all heredoc users, not just the memory plugin.

### Long-term fix (both sides):
4. **The Write tool IS the correct architecture** -- the mandate just needs better enforcement. The existing `memory_draft.py` pipeline (Write tool for partial JSON -> `memory_draft.py` assembles -> `memory_write.py` validates) is well-designed. The gap is subagent compliance, not architecture.
5. If compliance remains problematic, consider an **MCP tool** approach to eliminate the staging file write entirely.

---

## 6. Key Evidence Files

| File | Location | What it shows |
|------|----------|---------------|
| SKILL.md | `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md:81-83` | Write tool mandate |
| guardian.log | `/home/idnotbe/projects/ops/.claude/guardian/guardian.log:365,448,581,1704,4561,8853,9135` | ASK entries from heredoc |
| bash_guardian.py | `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/bash_guardian.py:230,1033-1037` | Newline split + fail-closed logic |
| tech-debt record | `/home/idnotbe/projects/ops/.claude/memory/tech-debt/guardian-regex-blocks-memory-delete.json` | Previous `--action delete` issue |
| fix-claude-memory.md | `/home/idnotbe/projects/claude-memory/temp/fix-claude-memory.md` | Previous rename fix instructions |
| team-staging-path-fix.md | `/home/idnotbe/projects/claude-memory/temp/team-staging-path-fix.md` | Previous /tmp/ fix |
| review-draft-security.md | `/home/idnotbe/projects/claude-memory/temp/review-draft-security.md:12,276` | Security review confirming Write tool rationale |
| config.json | `/home/idnotbe/projects/ops/.claude/guardian/config.json` | No staging-specific allowlist exists |
