# claude-memory Plugin Architecture Issues and Recommendations

**Date**: 2026-02-18
**Context**: Observed during memory saving in ops project session
**Reviewers**: Claude Opus 4.6 (primary), vibe-check skill (metacognitive), Gemini 3 Pro (via pal clink)
**Severity**: HIGH (Architecture/Security)

---

## Executive Summary

The claude-memory plugin suffers from **Environment Context Failure** -- it was designed and tested as if it runs inside its own project directory, but when deployed as a plugin to other projects (e.g., ops), all path assumptions break. This results in Guardian security blocks, agents searching for scripts via glob, repeated stop hook triggers, and reliance on development artifacts accidentally committed to user projects.

**Root Cause**: The plugin's skill instructions (SKILL.md) assume CWD = plugin root. The hooks correctly use `${CLAUDE_PLUGIN_ROOT}`, but the skill instructions do not. This inconsistency means hooks work but agent-driven operations fail.

---

## Observed Failures (with Evidence)

### F1: `/tmp/` Usage Blocked by Guardian

**What happened**: The memory-management skill instructs the agent to write draft JSON files to `/tmp/.memory-draft-<category>-<pid>.json`. When the agent tried to read these files with the Read tool, Guardian blocked it:

```
PreToolUse:Read hook blocking error:
[BLOCKED] Path is outside project directory
```

**Workaround used**: Agent fell back to `Bash(cat /tmp/...)` which bypasses Guardian's Read tool hook but is an anti-pattern (circumvents security controls).

**Root cause**: The skill assumes unrestricted filesystem access. Guardian (and any security-conscious environment) restricts tool access to the project directory.

**Impact**: Every memory save operation triggers a Guardian block, requiring a security-circumventing workaround.

### F2: Script Path Resolution Failure

**What happened**: The skill instructs the agent to run:
```
python3 hooks/scripts/memory_candidate.py --category <cat> --new-info "..."  --root .claude/memory
```

This path is relative to CWD, which is the user's project (e.g., `/home/idnotbe/projects/ops/`). The scripts don't exist at `ops/hooks/scripts/`. The agent got:
```
python3: can't open file '/home/idnotbe/projects/ops/hooks/scripts/memory_candidate.py': [Errno 2] No such file or directory
```

**Workaround used**: Agent used `Glob("**/memory_candidate.py")` to search the entire project, finding `temp/memory_candidate.py` -- a copy that was bulk-committed during plugin development (git commit f9e1f34, Feb 14).

**Root cause**: The skill instructions use CWD-relative paths, but CWD is the user's project, not the plugin root. The plugin's hooks correctly use `${CLAUDE_PLUGIN_ROOT}` (e.g., `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py"`), but this convention is NOT applied to the skill instructions.

**Impact**: Non-deterministic script discovery. Agent found development artifacts in `temp/` that happen to work but are not the canonical plugin scripts. Different projects without these artifacts would fail entirely.

### F3: Development Artifacts Leaked to User Project

**What happened**: `memory_candidate.py` and `memory_write.py` exist in `/home/idnotbe/projects/ops/temp/` (77+ memory-related files total). These were added via `git commit f9e1f34` ("bulk commit working files, temp artifacts, and memory data"). They are copies of the plugin's scripts, not proper plugin-provided resources.

**Root cause**: During plugin development, scripts were tested from the ops project's temp directory. These working copies were committed alongside other temp files but never cleaned up. The agent found and used these instead of the plugin's canonical scripts.

**Impact**: Creates a false sense of functionality -- the memory system "works" in ops because the scripts happen to exist in temp/, but would fail in any other project. The scripts in temp/ may also diverge from the plugin's canonical versions over time.

### F4: Repeated Stop Hook Firing

**What happened**: The stop hook (`memory_triage.py`) fired 3 times during a single session stop, each time demanding the agent save a `session_summary` memory. The agent had to handle each trigger separately, wasting 3 turns and significant tokens.

**Timeline**:
1. First trigger: Agent saved session_summary successfully
2. Second trigger: Agent checked, found memory already exists, reported NOOP
3. Third trigger: Agent again checked, found memory exists, but also triggered for `constraint` category

**Root cause**: The stop hook has no state tracking. It doesn't check whether the memory was already saved by a previous invocation in the same stop sequence. Each time the agent completes a response (even the one handling the memory save), the hook fires again.

**Impact**: Token waste (3x handling), user frustration (repeated delays), and potential infinite loops if the hook never stops blocking.

### F5: Non-Deterministic Script Discovery

**What happened**: Due to F2, the agent had to use `Glob("**/memory_candidate.py")` and `Glob("**/memory_write.py")` to find the scripts. This is a search operation that:
- Could return multiple results (plugin scripts, dev copies, test fixtures)
- Has no guarantee of finding the correct version
- Wastes tool calls on discovery instead of execution

**Root cause**: Skill instructions provide relative paths that don't resolve in the user's project.

**Impact**: Agents waste turns on discovery. In projects without temp/ copies, the entire memory system fails silently or with cryptic "file not found" errors.

---

## Root Cause Analysis

All five failures trace to a single architectural flaw:

> **The plugin's skill instructions (SKILL.md) were written assuming the plugin IS the project, not a guest in someone else's project.**

This is an **Environment Context Failure**:

| Component | Uses `${CLAUDE_PLUGIN_ROOT}`? | Status |
|-----------|------------------------------|--------|
| `hooks.json` (hook configs) | YES (`$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py`) | CORRECT |
| Hook scripts (memory_triage.py) | YES (runs from plugin root) | CORRECT |
| Skill instructions (SKILL.md) | NO (uses `hooks/scripts/...` relative to CWD) | BROKEN |
| Draft file paths in SKILL.md | NO (uses `/tmp/` -- outside project) | BROKEN |

The inconsistency is clear: hooks were written with proper plugin context awareness, but the skill instructions were not. This likely happened because the skill was developed and tested in the claude-memory project repo itself, where CWD = plugin root and everything resolves correctly.

---

## Recommendations

### R1: Use `${CLAUDE_PLUGIN_ROOT}` in All Skill Script References (CRITICAL)

**Current (broken)**:
```
python3 hooks/scripts/memory_candidate.py --category <cat> ...
python3 hooks/scripts/memory_write.py --action create ...
```

**Fixed**:
```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" --category <cat> ...
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create ...
```

**Where to change**: `skills/memory-management/SKILL.md` -- every occurrence of `hooks/scripts/memory_candidate.py` and `hooks/scripts/memory_write.py` must be prefixed with `${CLAUDE_PLUGIN_ROOT}/`.

**Rationale**: The hooks already use this pattern. The skill must match. `${CLAUDE_PLUGIN_ROOT}` is a Claude Code platform feature specifically designed for this purpose.

### R2: Move Staging Files from `/tmp/` to Project-Local Path (CRITICAL)

**Current (broken)**:
```
Draft files: /tmp/.memory-draft-<category>-<pid>.json
Context files: /tmp/.memory-triage-context-<category>.txt
```

**Fixed**:
```
Draft files: .claude/memory/.staging/draft-<category>-<pid>.json
Context files: .claude/memory/.staging/context-<category>.txt
```

**Where to change**:
1. `skills/memory-management/SKILL.md` -- all `/tmp/.memory-draft-*` and `/tmp/.memory-triage-context-*` references
2. `hooks/scripts/memory_triage.py` -- where it writes context files
3. Add `.staging/` to `.gitignore` in `.claude/memory/`

**Rationale**:
- Guardian and other security plugins block `/tmp/` access via Read tool
- `/tmp/` is OS-specific (behaves differently on Windows/macOS/Linux)
- Project-local staging keeps artifacts contained and cleanup is trivial
- `.claude/memory/.staging/` is already within the plugin's storage scope

**Alternative**: If `.claude/memory/.staging/` is not desirable, use `${CLAUDE_PLUGIN_ROOT}/.staging/` (within the plugin's own directory). However, project-local is preferred for Read tool accessibility.

### R3: Make Stop Hook Idempotent (HIGH)

**Current (broken)**: Hook fires on every stop attempt, regardless of whether the memory was already saved.

**Fixed options**:

**Option A: Sentinel file approach**
```python
# In memory_triage.py, before blocking:
sentinel = ".claude/memory/.staging/.triage-handled"
if os.path.exists(sentinel):
    age = time.time() - os.path.getmtime(sentinel)
    if age < 300:  # 5 minutes
        sys.exit(0)  # Allow stop, already handled

# After emitting triage data:
Path(sentinel).touch()
```

**Option B: Check recent session memory**
```python
# Check if a session_summary was created in the last 2 minutes
sessions_dir = ".claude/memory/sessions/"
for f in sorted(Path(sessions_dir).glob("*.json"), key=os.path.getmtime, reverse=True):
    if time.time() - os.path.getmtime(f) < 120:
        # Recent session exists, skip session_summary trigger
        break
```

**Rationale**: The hook is a gatekeeper but has no gate state. Without idempotency, it creates an infinite loop pattern: hook blocks -> agent handles -> agent tries to stop -> hook blocks again.

### R4: Clean Up Development Artifacts from User Projects (MEDIUM)

**Action**: Remove `memory_candidate.py`, `memory_write.py`, and other plugin scripts from `ops/temp/`:
```bash
# These are development artifacts, not canonical plugin scripts
rm temp/memory_candidate.py temp/memory_write.py
```

**Rationale**: These files create a false dependency. When R1 is implemented (using `${CLAUDE_PLUGIN_ROOT}`), the scripts will be found at the correct plugin location. Leaving copies in `temp/` creates version divergence risk and confuses agents that search for scripts.

### R5: Add Plugin Self-Validation (LOW)

Add a validation step to the skill that verifies the plugin environment on first use:
```
# At the start of the skill instructions, add:
Verify: Run "ls ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" to confirm plugin scripts are accessible.
If not found, report: "claude-memory plugin scripts not found at expected location."
```

**Rationale**: Fail fast with a clear error message instead of letting the agent search via glob.

---

## Cross-Model Consensus

| Issue | Claude Opus 4.6 | Vibe-Check | Gemini 3 Pro |
|-------|-----------------|------------|--------------|
| Root cause | Plugin assumes CWD = plugin root | Same -- "designed and tested in own repo" | "Lack of Plugin Context Awareness" |
| `/tmp/` fix | Use `.claude/memory/.staging/` | Use project-local path | Use `.claude/memory/.cache/` or `.claude/tmp/` |
| Script path fix | Use `${CLAUDE_PLUGIN_ROOT}` | Same -- hooks already do this | Same -- "hardcode absolute paths via env var" |
| Idempotency fix | Sentinel file or recent-check | Check if already saved before blocking | Sentinel file in `.cache/` |
| Severity | HIGH | "On track but sharpen root cause" | HIGH (Architecture/Security) |

**All three assessors agree**: The root cause is environment context failure. The fix is `${CLAUDE_PLUGIN_ROOT}` for paths and project-local staging for temp files. The hooks already demonstrate the correct pattern -- it just needs to be applied to the skill instructions.

---

## Implementation Priority

| Priority | Issue | Fix | Effort |
|----------|-------|-----|--------|
| P0 | Script paths in SKILL.md | R1: `${CLAUDE_PLUGIN_ROOT}` prefix | ~30 min (find-replace) |
| P0 | `/tmp/` staging files | R2: `.claude/memory/.staging/` | ~2 hours (SKILL.md + triage.py + .gitignore) |
| P1 | Stop hook idempotency | R3: Sentinel file approach | ~1 hour (triage.py modification) |
| P2 | Dev artifacts in ops | R4: Delete temp/ copies | ~5 min |
| P3 | Self-validation | R5: ls check at skill start | ~15 min |

---

## Appendix: Correct vs Incorrect Patterns

### Script Invocation

```
# WRONG (current SKILL.md)
python3 hooks/scripts/memory_candidate.py --category session_summary ...

# RIGHT (should be)
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" --category session_summary ...

# ALREADY CORRECT (hooks.json)
"command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py\""
```

### Staging File Paths

```
# WRONG (current SKILL.md)
/tmp/.memory-draft-session_summary-12345.json
/tmp/.memory-triage-context-session_summary.txt

# RIGHT (should be)
.claude/memory/.staging/draft-session_summary-12345.json
.claude/memory/.staging/context-session_summary.txt
```

### Stop Hook Behavior

```
# WRONG (current)
Stop hook fires -> Agent saves memory -> Agent tries to stop -> Hook fires AGAIN

# RIGHT (should be)
Stop hook fires -> Agent saves memory -> Creates sentinel -> Agent tries to stop -> Hook checks sentinel -> Allows stop
```

---

*Analysis complete. All three reviewers (Claude Opus 4.6, vibe-check, Gemini 3 Pro) concur on root cause and fixes.*
