# Guardian-Memory Conflict Analysis

**Date**: 2026-03-22
**Context**: claude-memory plugin (v5.1.0) operating in /home/idnotbe/projects/ops where claude-code-guardian is active as a plugin

---

## 1. Current Guardian Configuration

### Guardian Hook Surface (hooks/hooks.json)

| Hook Type | Script | Purpose |
|-----------|--------|---------|
| SessionStart | session_start.sh | Session initialization |
| PreToolUse:Bash | bash_guardian.py | 7-layer command analysis |
| PreToolUse:Read | read_guardian.py | Path access control |
| PreToolUse:Edit | edit_guardian.py | Path write protection |
| PreToolUse:Write | write_guardian.py | Path write protection |
| Stop | auto_commit.py | Auto-checkpoint commit |

### Bash Guardian Analysis Layers

The bash_guardian.py (2303 lines) runs a 7-layer pipeline on every Bash tool call:

1. **Layer 0 (Block patterns)**: 18 block regex patterns scanned against the *redacted* command (safe heredoc bodies removed). Key patterns affecting memory:
   - `(?i)find\s+.*\s+-delete` -- blocks any find-delete
   - `(?i)(?:^\s*|[;|&({]\s*)(?:rm|rmdir|del|delete)...\s+.*\.claude` -- blocks rm targeting .claude
   - `python3\s[^|&\n]*(?:os\.remove|os\.unlink|shutil\.rmtree)` -- blocks interpreter deletion (single-line only, `[^|&\n]*` stops at newlines)
   - `python3\s[^|&\n]*pathlib\.Path(...)\.unlink` -- blocks pathlib deletion

2. **Layer 0b (Ask patterns)**: 18 ask patterns. Key patterns:
   - `rm\s+-[rRf]+` -- any recursive/force rm
   - `mv\s+['"]?(?:\./)?\.(env|git|claude)` -- moving .env/.git/.claude
   - `find\s+.*-exec\s+(?:rm|del|shred)` -- find with exec delete
   - `xargs\s+(?:rm|del|shred)` -- xargs with delete

3. **Layer 1 (Protected path scan)**: Scans joined sub-commands for literal occurrences of zeroAccessPaths filenames (`.env`, `.pem`, `.key`, etc.). Default scanTiers: `["zeroAccess"]` only.

4. **Layer 2 (Command decomposition)**: `split_commands()` with heredoc-aware splitting. Safe heredoc bodies (feeding passive data sinks like cat/grep) are redacted. Unsafe bodies (interpreter, redirect, piped, unknown) are retained.

5. **Layer 3 (Path extraction)**: `extract_paths()` resolves paths from command arguments.

6. **Layer 4 (Command type detection)**: `is_delete_command()` and `is_write_command()` classify sub-commands. Critically, `is_delete_command()` includes a fallback `check_interpreter_payload()` that extracts `-c`/`-e` payloads and scans for destructive APIs.

7. **F1 Safety Net**: If write/delete is detected but no paths could be resolved, the F1 mechanism fires. For interpreter commands, it attempts `extract_paths_from_interpreter_payload()` first. If path resolution fails, verdict = ASK.

### Path-Based Guardian (Write/Edit/Read)

Uses `_guardian_utils.run_path_guardian_hook()` to check:
- zeroAccessPaths (deny all access)
- readOnlyPaths (deny write/edit)
- noDeletePaths (deny deletion)
- Symlink escape detection
- Outside-project path detection
- Self-guarding (`.claude/guardian/config.json`, `.claude/settings.json`, `.claude/settings.local.json`)

**Critical**: `.claude/memory/` paths are NOT in any guardian protected path list. Write/Edit/Read guardians will ALLOW operations on `.claude/memory/**`. The memory plugin's own `memory_write_guard.py` handles this.

### Guardian Config (guardian.default.json)

The config loaded by the guardian. Key settings:
- `bashPathScan.scanTiers`: `["zeroAccess"]` (only scans for secrets/credentials)
- `bashPathScan.exactMatchAction`: `"ask"`
- `bashPathScan.patternMatchAction`: `"ask"`
- No custom config exists at `/home/idnotbe/projects/ops/.claude/guardian/config.json` (checked but file not found)

---

## 2. Claude-Memory's Guardian-Avoidance Measures (fix-approval-popups.md)

### What Was Done (Phases 1-6, all marked DONE)

**Phase 1: Fix Write Tool Popups (3 files)**
- `memory_write_guard.py`: Emits explicit `permissionDecision: "allow"` for staging files (4-gate safety: extension whitelist, filename regex, nlink defense, new file passthrough)
- `memory_validate_hook.py`: Changed nlink from gate to warning-only for staging; OSError fails open
- `memory_staging_guard.py`: Added `ln`/`link` to blocked commands regex

**Phase 2: Guardian Bash Popups (SKILL.md)**
- Replaced `find -delete` with `python3 -c "import glob,os; ..."` in Phase 0
- Replaced `--result-json` inline JSON with `--result-file` approach (Write tool for JSON, Bash for script)
- Expanded Rule 0 to document all Guardian-incompatible patterns
- Added `--result-file` argument to `memory_write.py`

**Phase 3: Logging**
- Added JSONL logging to all three guard scripts

**Phase 4: Regression Tests (29 tests)**
- `TestNoAskVerdict`: AST + regex scan for "ask" permissionDecision in guard scripts (9 tests)
- `TestSkillMdGuardianConflicts`: SKILL.md bash commands vs 4 block + 4 ask Guardian patterns (9 tests)
- `TestSkillMdRule0Compliance`: heredoc, find-delete, rm, inline JSON, python3-c checks (5 tests)
- `TestGuardScriptsExist` + `TestGuardianPatternSync`: sanity + sync check (6 tests)

**Phase 5: One-Time Cleanup**
- Removed 118 `.invalid` files, stale staging files, rebuilt index

**Phase 6: Guardian Repo Tech Debt**
- Created `heredoc-pattern-false-positives.md` action plan
- Created `interpreter-path-resolution.md` action plan

### SKILL.md Rule 0 (Current)
> "Never combine heredoc (<<), Python interpreter, and .claude path in a single Bash command. All staging file content must be written via Write tool (not Bash). Bash is only for running python3 scripts. Do NOT use python3 -c with inline code referencing .claude paths. Do NOT use find -delete or rm with .claude paths. Do NOT pass inline JSON containing .claude paths on the Bash command line."

---

## 3. Remaining Conflict Surface

### 3A. CONFIRMED: Phase 0 Cleanup Command -- F1 Safety Net ASK

**The known remaining trigger.** SKILL.md Phase 0 Step 0 contains:

```bash
python3 -c "import glob,os
for f in glob.glob('.claude/memory/.staging/intent-*.json'): os.remove(f)
print('ok')"
```

Analysis against guardian layers:
- **Layer 0 block**: NO MATCH. The `python3\s[^|&\n]*os\.remove` block pattern stops at the first newline (`[^|&\n]*`). Since `os.remove` is on line 2, it doesn't match.
- **Layer 0b ask**: NO MATCH. No ask patterns match.
- **Layer 1 scan**: NO MATCH. `.claude` is not in zeroAccessPaths.
- **Layer 4 is_delete_command()**: YES (via `check_interpreter_payload()`). Extracts the `-c` payload, finds `os.remove` in it.
- **F1 safety net**: `extract_paths_from_interpreter_payload()` tries to resolve paths from string literals. The glob pattern `.claude/memory/.staging/intent-*.json` contains `*`, so it attempts glob expansion. **If no intent-*.json files exist yet** (first run), glob returns empty, path resolution fails, F1 fires ASK.

**Verdict**: This command triggers an **ASK popup** via the F1 safety net when no intent files exist. This is the documented "accepted trade-off" (see `test_python3_c_with_claude_path_warning` in test_regression_popups.py).

**Impact**: 1 popup per memory save operation (Phase 0 cleanup runs once per save).

### 3B. CONFIRMED: Subagent Bash Commands -- No Conflict

Memory plugin Bash commands from SKILL.md Phases 1.5-3:

| Command | Guardian Result |
|---------|----------------|
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_candidate.py" --category ... --new-info-file ...` | ALLOW (no -c flag, no delete patterns) |
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_draft.py" --action create ...` | ALLOW (no -c flag, no delete patterns) |
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action create ...` | ALLOW (no -c flag, no delete patterns) |
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action retire ...` | ALLOW (no -c flag, no delete patterns) |
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action cleanup-staging ...` | ALLOW (no -c flag, no delete patterns) |
| `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_enforce.py" --category ...` | ALLOW (no -c flag, no delete patterns) |

All `memory_write.py` invocations use script paths (not `-c` inline code), so `check_interpreter_payload()` returns None and no F1 safety net is triggered. The block/ask regex patterns don't match because there's no `os.remove` on the same line as `python3`.

### 3C. CONFIRMED: Write Tool Operations -- No Conflict

The memory-drafter agent uses `tools: Read, Write` only (no Bash). Write operations to `.claude/memory/.staging/` go through:
1. **Memory write_guard.py**: Explicitly allows staging paths (Phase 1 fix)
2. **Guardian write_guardian.py**: `.claude/memory/` is not in zeroAccessPaths, readOnlyPaths, or self-guarded paths. Will ALLOW.
3. **Memory validate_hook.py**: PostToolUse, excludes `.staging/` paths (Phase 1 fix)

No conflict.

### 3D. POTENTIAL: Save Subagent Combined Commands

The Phase 3 save subagent (haiku) combines multiple `memory_write.py` commands with `;` separators:

```
python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action create ... ; python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action update ... ; python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_enforce.py" ...
```

Guardian's `split_commands()` will split these into individual sub-commands. Each sub-command is a plain script invocation (no `-c`). No conflict expected.

However, the SKILL.md instruction says: "Do NOT use heredoc (<<)" for the save subagent. If the haiku model ignores this and uses heredoc, it could trigger the interpreter+heredoc ASK backstop. This is a model compliance risk, not a systematic issue.

### 3E. POTENTIAL: Staging File Content with .env/.pem References

If a memory's content discusses `.env` or `.pem` files (e.g., a runbook about "how to set up .env"), and this content is written via the Write tool to `.staging/`, the guardian's write_guardian.py will see the `.staging/` path and ALLOW (not zeroAccess). The content itself is not scanned by the Write guardian.

However, if the save subagent uses Bash to echo or cat content containing `.env` references, Layer 1's `scan_protected_paths()` would detect the literal `.env` and trigger ASK. This is prevented by SKILL.md Rule 0 ("Bash is only for running python3 scripts") and the staging guard blocking heredoc writes to `.staging/`.

**No conflict if SKILL.md instructions are followed.**

---

## 4. Completed Guardian Action Plans

### Phase 6 Plans -- NOT IMPLEMENTED

The fix-approval-popups.md Phase 6 states two action plans were created in the guardian repo:
1. `heredoc-pattern-false-positives.md` -- 700+ lines, cross-model validated
2. `interpreter-path-resolution.md` -- 400+ lines, cross-model validated

**Status**: These files DO NOT EXIST in the guardian repo at the expected paths:
- `~/projects/claude-code-guardian/action-plans/heredoc-pattern-false-positives.md` -- NOT FOUND
- `~/projects/claude-code-guardian/action-plans/interpreter-path-resolution.md` -- NOT FOUND

However, a **unified superseding plan** exists and was IMPLEMENTED:
- `~/projects/claude-code-guardian/action-plans/_done/heredoc-scanning-redesign.md` (status: done)
  - Incorporates Phase 0 (delimiter parsing fixes), Phase 1 (heredoc body redaction), Phase 2 (interpreter path resolution for F1), Phase 3 (interpreter+heredoc ASK backstop)
  - 1086 total tests pass, 4 bypasses found and fixed across 2 verification rounds

This means the two separate plans were merged into a single comprehensive redesign that was fully implemented. The individual plan files may have been cleaned up or never committed as separate files.

### What Was Actually Implemented in Guardian

1. **Heredoc body redaction** (Phase 1 of redesign): `split_commands()` now produces a redacted version of the command where safe heredoc bodies (feeding passive data sinks) are replaced with empty lines. Layer 0/0b scan the redacted command, preventing false positives from heredoc content.

2. **Interpreter path resolution** (Phase 2): `extract_paths_from_interpreter_payload()` extracts string literals from `-c`/`-e` payloads and resolves them as paths. If paths resolve within the project, they go through normal path validation instead of triggering F1 ASK.

3. **Interpreter+heredoc ASK backstop** (Phase 3): `_is_interpreter_heredoc()` detects interpreter commands with heredoc operators and escalates to ASK. This is defense-in-depth.

4. **Delimiter parsing fixes** (Phase 0): Backslash-escaped and ANSI-C quoted heredoc delimiters are now handled correctly.

### Guardian Security Fixes -- NOT STARTED

A separate action plan exists: `~/projects/claude-code-guardian/action-plans/security-fixes.md` (status: not-started). This contains 3 P0 security issues:
1. **auto_commit.py secrets filtering**: Stages and commits secrets without zeroAccessPaths filtering
2. **Non-dict JSON input validation**: `run_path_guardian_hook()` crashes on non-dict JSON
3. **Missing file_path denial for Write/Edit**: Allows empty file_path

These are guardian-internal issues that don't directly affect memory plugin popups.

---

## 5. The "4 Stop Hooks" Mystery

### Source Identification

When running in the ops project, 4 Stop hooks fire at session end:

| # | Source | Hook | Script |
|---|--------|------|--------|
| 1 | **ops settings.json** | Stop | Play `on_stop.wav` sound notification |
| 2 | **claude-code-guardian plugin** (hooks/hooks.json) | Stop | `auto_commit.py` -- git auto-checkpoint |
| 3 | **claude-memory plugin** (hooks/hooks.json) | Stop | `memory_triage.py` -- keyword triage for 6 categories |
| 4 | **hookify plugin** (plugin.json) | Stop | `stop.py` -- user-configurable hooks from .local.md files |

### How They Stack

The ops project has 6 plugins enabled (from `settings.json > enabledPlugins`):
- plugin-dev, pyright-lsp, claude-md-management, typescript-lsp, claude-code-setup, hookify

Plus 6 plugins loaded via `plugin-dirs`:
- claude-code-guardian, claude-memory, vibe-check, deepscan, prd-creator, fractal-wave

Checking each for Stop hooks:
- **claude-code-guardian**: 1 Stop hook (`auto_commit.py`)
- **claude-memory**: 1 Stop hook (`memory_triage.py`)
- **hookify**: 1 Stop hook (`stop.py`)
- **ops settings.json**: 1 Stop hook (sound notification)
- vibe-check: No hooks.json
- deepscan: No hooks.json
- prd-creator: No hooks.json
- fractal-wave: No Stop hooks (has PostToolUse and SessionStart only)
- Official plugins (plugin-dev, pyright-lsp, etc.): No hooks.json found in cache

**Total: 4 Stop hooks.** Mystery solved.

### Ordering Implications

Claude Code runs hooks in registration order. The likely execution sequence:
1. ops settings.json Stop (sound -- fast, non-blocking)
2. hookify Stop (user hooks -- variable)
3. guardian auto_commit.py (git commit -- may be slow)
4. memory triage.py (keyword analysis + file writes -- up to 30s timeout)

The guardian's auto_commit fires BEFORE memory triage. This means:
- Memory triage writes to `.staging/` AFTER auto_commit runs
- Staging files won't be included in the auto-commit (they don't exist yet)
- Next session: staging files are untracked, may be picked up by auto_commit on next Stop

This is not a conflict, but a timing consideration for staging file lifecycle.

---

## 6. Summary: What's Fixed vs What Remains

### Fixed (No Longer Causes Popups)

| Issue | Fix | Location |
|-------|-----|----------|
| Write guard silent exit for staging | Explicit `permissionDecision: "allow"` | memory_write_guard.py |
| Validate hook quarantines staging files | Nlink warning-only, fail-open OSError | memory_validate_hook.py |
| Heredoc body content triggers ask patterns | Guardian: heredoc body redaction in split_commands() | bash_guardian.py |
| `find -delete` in SKILL.md | Replaced with python glob+os.remove | SKILL.md Phase 0 |
| Inline JSON with .claude paths | --result-file approach | SKILL.md + memory_write.py |
| `rm` with .claude paths | Python glob+os.remove | SKILL.md |
| Missing ln/link in staging guard | Added to blocked commands | memory_staging_guard.py |

### Remains (Accepted Trade-offs)

| Issue | Trigger | Impact | Mitigation |
|-------|---------|--------|------------|
| Phase 0 cleanup `python3 -c` with `os.remove` | F1 safety net when no intent files exist | 1 popup per save | Documented in test_regression_popups.py; accepted trade-off |

### Needs Change (Recommendations)

| Issue | Recommendation | Owner | Difficulty |
|-------|---------------|-------|------------|
| **Phase 0 cleanup F1 ASK** | Replace `python3 -c "import glob,os..."` with a proper script invocation: add `--action cleanup-intents` to `memory_write.py` and call `python3 "${CLAUDE_PLUGIN_ROOT}/.../memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging` | memory plugin | Easy |
| **Guardian F1 for in-project interpreter deletion** | The `heredoc-scanning-redesign.md` Phase 2 implemented path resolution but it only works for static string literals, not glob patterns. Consider adding glob expansion to `extract_paths_from_interpreter_payload()` | guardian | Medium |

### The Simple Fix for the Last Popup

The single remaining popup source (Phase 0 cleanup `python3 -c` with `os.remove`) can be eliminated entirely by **moving the intent cleanup logic into memory_write.py as a new action**. This converts:

```bash
# CURRENT (triggers F1 ASK):
python3 -c "import glob,os
for f in glob.glob('.claude/memory/.staging/intent-*.json'): os.remove(f)
print('ok')"
```

Into:

```bash
# PROPOSED (no F1 trigger -- plain script invocation):
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging
```

This eliminates the `-c` inline code, making it invisible to `check_interpreter_payload()`. The guardian sees a simple python3 script invocation with no destructive APIs detectable.

---

## 7. Full Conflict Surface Map

```
BASH TOOL CALL
    |
    v
+-- memory_staging_guard.py (PreToolUse:Bash) --> blocks heredoc/.staging writes
+-- bash_guardian.py (PreToolUse:Bash)
    |
    |-- Layer 0: Block patterns (redacted command)
    |   [X] find -delete         FIXED (replaced with python glob)
    |   [X] rm .claude           FIXED (replaced with python glob)
    |   [ ] python3 os.remove    NOT HIT (newline breaks [^|&\n]*)
    |
    |-- Layer 0b: Ask patterns (redacted command)
    |   [X] heredoc body content FIXED (heredoc redaction)
    |   [ ] rm -rf               NOT TRIGGERED (no rm in SKILL.md)
    |   [ ] mv .claude           NOT TRIGGERED (no mv in SKILL.md)
    |
    |-- Layer 1: Protected path scan
    |   [ ] .env/.pem in command NOT TRIGGERED (SKILL.md uses script invocations)
    |
    |-- Layer 4: is_delete_command + check_interpreter_payload
    |   [!] python3 -c with os.remove  TRIGGERS F1 (Phase 0 cleanup)
    |   [ ] python3 script.py          SAFE (no -c flag)
    |
    |-- F1 Safety Net
    |   [!] No resolved paths for Phase 0 cleanup glob  --> ASK popup
    |
    v
WRITE TOOL CALL
    |
    +-- memory_write_guard.py (PreToolUse:Write) --> allows staging with 4-gate safety
    +-- write_guardian.py (PreToolUse:Write) --> allows .claude/memory/ (not protected)
    |
    v (after write)
    +-- memory_validate_hook.py (PostToolUse:Write) --> skips staging, warns on nlink

Legend: [X] = fixed, [ ] = not triggered, [!] = remaining issue
```
