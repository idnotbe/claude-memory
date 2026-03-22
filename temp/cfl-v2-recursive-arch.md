# CFL v2: Recursive Self-Installation Architecture

> Closed Feedback Loop -- recursive dogfooding of claude-memory within its own repo,
> with claude-code-guardian co-installed to simulate ops environment.

**Status**: Design complete, ready for implementation
**Date**: 2026-03-22

---

## 1. Executive Summary

Install claude-memory as a plugin ON the claude-memory repo itself. Co-install
claude-code-guardian. Run normal development sessions while the plugin captures
memories about its own development, fires retrieval on developer prompts, and
guardian enforces security guardrails. Observe behavior via screen capture and
structured logs.

**Decision: True dogfood in canonical repo** (not a worktree or isolated sandbox).
The user's goal is behavior observation during real development work. Worktree
isolation would mask path-resolution bugs and prevent the agent from benefiting
from its own memories.

---

## 2. Technical Investigation Results

### 2.1 Path Resolution Analysis

When claude-memory is loaded via `--plugin-dir ~/projects/claude-memory` while
working IN `~/projects/claude-memory`:

| Variable | Value | Used By |
|----------|-------|---------|
| `$CLAUDE_PLUGIN_ROOT` | `~/projects/claude-memory` | Hook script resolution (`hooks/scripts/*.py`) |
| `cwd` | `~/projects/claude-memory` | Memory root derivation (`cwd/.claude/memory`) |
| `memory_root` | `~/projects/claude-memory/.claude/memory` | All read/write operations |
| Staging dir | `/tmp/.claude-memory-staging-52f0f4a8baed` | Deterministic hash of realpath |

**Result: No circular dependency.** CLAUDE_PLUGIN_ROOT and cwd serve different
logical roles (code location vs. data location). They happen to be the same path,
but the scripts never reference one through the other. Hook scripts are invoked as
independent subprocesses by Claude Code -- there is no module-level recursion.

### 2.2 Plugin Manifest

```
/home/idnotbe/projects/claude-memory/.claude-plugin/plugin.json
```

- name: claude-memory v5.1.0
- commands: 3 (memory, memory-config, memory-save)
- agents: 1 (memory-drafter -- tools: Read, Write only)
- skills: 2 (memory-management, memory-search)

### 2.3 Hook Registration (Memory)

```
/home/idnotbe/projects/claude-memory/hooks/hooks.json
```

| Hook Event | Script | Timeout |
|-----------|--------|---------|
| Stop | memory_triage.py | 30s |
| PreToolUse:Write | memory_write_guard.py | 5s |
| PreToolUse:Bash | memory_staging_guard.py | 5s |
| PostToolUse:Write | memory_validate_hook.py | 10s |
| UserPromptSubmit | memory_retrieve.py | 15s |

### 2.4 Hook Registration (Guardian)

```
/home/idnotbe/projects/claude-code-guardian/hooks/hooks.json
```

| Hook Event | Script | Notes |
|-----------|--------|-------|
| SessionStart | session_start.sh | Init guardian state |
| PreToolUse:Bash | bash_guardian.py | Command analysis |
| PreToolUse:Read | read_guardian.py | Path security |
| PreToolUse:Edit | edit_guardian.py | Path security |
| PreToolUse:Write | write_guardian.py | Path security + outside-project blocking |
| Stop | auto_commit.py | Safety checkpoint commits |

### 2.5 Installed Plugins

```
~/.claude/plugins/installed_plugins.json
```

Only marketplace plugins for ops project (pyright-lsp, typescript-lsp, etc.).
No global installation of claude-memory or claude-code-guardian.

Plugin data dirs exist but are empty:
- `~/.claude/plugins/data/claude-memory-inline/` (empty)
- `~/.claude/plugins/data/claude-code-guardian-inline/` (empty)

### 2.6 Venv Bootstrap

```python
# memory_write.py lines 28-35
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    try:
        import pydantic  # quick availability check
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)
```

- Resolves `.venv` relative to plugin root: `hooks/scripts/../../.venv` = `<plugin_root>/.venv`
- When plugin root = project root: looks for `/home/idnotbe/projects/claude-memory/.venv`
- **Current state**: No `.venv` exists in the repo. BUT pydantic 2.12.5 is in system Python.
- **Result**: The `import pydantic` check succeeds, `os.execv` is never called. Venv concern is **moot**.

### 2.7 Staging Directory Design

Staging lives at `/tmp/.claude-memory-staging-<hash>/` by deliberate design decision.
This was moved OUT of `.claude/memory/.staging/` specifically because Claude Code has
a **hardcoded `.claude/` protected directory check** that causes approval popups for
Write tool calls targeting `.claude/*` paths. See:
- `hooks/scripts/memory_staging_utils.py` line 5
- `skills/memory-management/SKILL.md` line 36
- `action-plans/eliminate-all-popups.md`
- `tests/test_regression_popups.py`

**Moving staging back inside `.claude/` is NOT an option.** The `/tmp/` location is
non-negotiable for UX reasons.

### 2.8 Guardian Config Location

Guardian reads project-specific config from:
```
.claude/guardian/config.json
```
(`_guardian_utils.py` line 502)

No guardian config currently exists in the claude-memory repo.

### 2.9 Git Status

| Path | Gitignored? |
|------|------------|
| `temp/` | NO |
| `.claude/memory/` | NO (only `index.md` is ignored) |
| `.claude/guardian/` | NO (does not exist yet) |
| `.venv/` | YES |

---

## 3. Cross-Plugin Hazard Analysis

### 3.1 CRITICAL: Guardian Blocks /tmp Staging Writes

**Severity**: HIGH -- blocks entire memory save flow

**Mechanism**: Memory-drafter agents (Phase 1) use the Write tool to create intent
JSON files at `/tmp/.claude-memory-staging-52f0f4a8baed/intent-<category>.json`.
Guardian's `write_guardian.py` calls `run_path_guardian_hook("Write")` which checks
`is_path_within_project()`. `/tmp/` is NOT within the project directory. Guardian
blocks the write with "Path is outside project directory" unless the path matches
`allowedExternalWritePaths`.

**Impact**: Every memory save attempt will fail at Phase 1 intent drafting.

**Mitigation**: Create `.claude/guardian/config.json` with:
```json
{
  "allowedExternalWritePaths": [
    "/tmp/.claude-memory-staging-52f0f4a8baed/**"
  ]
}
```

**Note**: The hash `52f0f4a8baed` is deterministic for the path
`/home/idnotbe/projects/claude-memory`. It will NOT change unless the repo is
moved to a different absolute path.

### 3.2 CRITICAL: Stop Hook Race Condition

**Severity**: HIGH -- undefined behavior

**Mechanism**: Both plugins register Stop hooks. Claude Code runs hooks in
parallel, not serial. Memory's triage hook may return `{"decision": "block"}` to
prevent the stop (so the agent can save memories), while Guardian's auto-commit
simultaneously tries to commit unsaved changes.

**Scenarios**:
1. Guardian commits before memory saves complete -- partial/missing memory files
   get committed
2. Guardian commits memory's staging artifacts as project files
3. Memory blocks stop but Guardian has already committed -- state inconsistency

**Mitigation**: Disable Guardian auto-commit in the dogfood config:
```json
{
  "autoCommit": {
    "enabled": false
  }
}
```

Re-enable after Stop hook interaction is explicitly validated.

### 3.3 MEDIUM: Parallel PreToolUse:Write Evaluation

**Severity**: LOW (informational)

**Mechanism**: Both plugins fire PreToolUse:Write on every Write tool call.
Claude Code's decision model: if ANY hook returns `deny`, the write is denied.

- Memory's write_guard: Denies writes to `.claude/memory/**` (forces Bash route).
  Auto-approves staging files in `/tmp/`.
- Guardian's write_guardian: Denies outside-project writes. Checks zeroAccess,
  readOnly, symlink escape, self-guardian paths.

**Result**: For in-project writes, both evaluate independently. For staging writes
to `/tmp/`, memory approves but Guardian denies (without allowlist). For memory
directory writes, memory denies (correct behavior -- forces `memory_write.py`).

**No action needed** beyond the `/tmp/` allowlist in 3.1.

### 3.4 MEDIUM: Guardian readOnlyPaths vs Memory .venv

**Severity**: LOW (currently moot)

Guardian's default config marks `.venv/**` as readOnly. If a `.venv` is ever
created in the repo for plugin bootstrap, Guardian will block writes to it.
Currently moot since system Python has pydantic.

### 3.5 LOW: Guardian Read/Edit Hooks on Plugin Source

**Severity**: LOW (beneficial)

Guardian intercepts Read and Edit tool calls. During development, the agent
reads and edits hook scripts. Guardian will evaluate these normally. This is
actually the DESIRED behavior for ops simulation -- Guardian should be present
and active on all tool calls, not just Write.

---

## 4. Architecture Decision: True Dogfood

### 4.1 Cross-Model Analysis

Three models were consulted. Their recommendations diverged:

| Model | Recommendation | Optimization Target |
|-------|---------------|-------------------|
| Codex 5.3 | Worktree isolation | Safety (canonical tree pollution) |
| Gemini 3.1 Pro | True dogfood in canonical repo | Authenticity (real behavior) |
| Gemini 3 Pro (vibe check) | True dogfood + refactor staging inside project | Simplicity |

### 4.2 Resolution

**Adopt Gemini's "true dogfood" approach with Codex's specific mitigations.**

Rationale:
1. The user explicitly wants to observe behavior during real development work
2. Worktree isolation defeats the purpose -- it creates an artificial environment
3. Worktrees mask path-resolution bugs that only surface in real usage
4. The specific technical hazards (Guardian blocking, Stop races, git dirt) each
   have targeted mitigations that do not require isolation
5. The venv concern (Codex's primary bootstrap worry) is moot -- pydantic is in
   system Python

**Rejected**: Vibe check suggestion to move staging inside project. The `/tmp/`
staging location is a deliberate design decision to avoid Claude Code's hardcoded
`.claude/` protected directory approval popups. Moving it back would reintroduce
P3-level UX regressions.

---

## 5. Implementation Plan

### Phase 0: Prerequisites

#### 0.1 Update `.claude/plugin-dirs`

```
# .claude/plugin-dirs
~/projects/vibe-check

# Recursive self-installation (dogfood)
~/projects/claude-memory

# Ops environment simulation
~/projects/claude-code-guardian
```

Plugin load order: vibe-check, then claude-memory (self), then guardian.
Load order should not matter (hooks run in parallel), but listing memory
before guardian documents intent.

#### 0.2 Create Guardian Dogfood Config

Create `.claude/guardian/config.json`:

```json
{
  "$schema": "https://raw.githubusercontent.com/idnotbe/claude-code-guardian/main/assets/guardian.schema.json",
  "_comment": "Dogfood config for claude-memory recursive self-installation",
  "autoCommit": {
    "enabled": false,
    "reason": "Disabled to prevent race with memory triage Stop hook"
  },
  "allowedExternalWritePaths": [
    "/tmp/.claude-memory-staging-52f0f4a8baed/**"
  ],
  "allowedExternalReadPaths": [
    "/tmp/.claude-memory-staging-52f0f4a8baed/**"
  ]
}
```

#### 0.3 Update .gitignore

Add to `/home/idnotbe/projects/claude-memory/.gitignore`:

```gitignore
# Dogfood: recursive self-installation runtime data
.claude/memory/*.json
!.claude/memory/memory-config.json
.claude/guardian/
.claude/cfl-data/
```

Note: `.claude/memory/index.md` is already ignored.

#### 0.4 Create Data Collection Directory

```
.claude/cfl-data/
  sessions/          # Session transcripts and metadata
  captures/          # Screen capture images
  logs/              # Aggregated JSONL logs from memory plugin
  analysis/          # Post-hoc analysis reports
```

#### 0.5 Create Memory Config (Optional)

If no project-level config exists yet, create `.claude/memory/memory-config.json`
with logging enabled for observability:

```json
{
  "memory_root": ".claude/memory",
  "logging": {
    "enabled": true,
    "level": "debug",
    "retention_days": 30
  },
  "triage": {
    "enabled": true,
    "parallel": {
      "enabled": true
    }
  },
  "retrieval": {
    "max_inject": 3,
    "judge": {
      "enabled": false
    }
  }
}
```

### Phase 1: Smoke Test

1. Launch: `ccyolo` from the claude-memory repo root
2. Verify both plugins load (check for hook registration messages)
3. Issue a test prompt and verify retrieval hook fires
4. Make a small code change, then stop the session
5. Verify triage hook fires and evaluates categories
6. Verify guardian does NOT block memory staging writes
7. Verify guardian does NOT auto-commit during memory save
8. Check `.claude/memory/` for new memory JSON files

### Phase 2: Data Collection

Each dogfood session should produce:
- Memory JSON files in `.claude/memory/<category>/`
- JSONL logs in `.claude/cfl-data/logs/` (when logging enabled)
- Session transcript (available via Claude Code's transcript path)
- Screen captures (manual, stored in `.claude/cfl-data/captures/`)

Session index format in `.claude/cfl-data/sessions/`:
```json
{
  "session_id": "<extracted from transcript path>",
  "timestamp": "2026-03-22T...",
  "duration_minutes": 45,
  "plugins_loaded": ["claude-memory", "claude-code-guardian", "vibe-check"],
  "categories_triggered": ["decision", "session_summary"],
  "memories_created": 2,
  "memories_retrieved": 3,
  "guardian_blocks": 0,
  "guardian_allows": 15,
  "notes": "Free-form observation notes"
}
```

### Phase 3: Iterative Validation

After 3-5 dogfood sessions:
1. Review memory quality -- are the captured memories useful?
2. Review retrieval relevance -- does the plugin inject helpful context?
3. Review guardian interactions -- any unexpected blocks?
4. Review Stop hook behavior -- any race conditions observed?
5. Based on findings, enable guardian auto-commit and test interaction

---

## 6. Risk Registry

| ID | Risk | Severity | Probability | Mitigation | Status |
|----|------|----------|-------------|------------|--------|
| R1 | Guardian blocks /tmp staging writes | HIGH | CERTAIN (without config) | allowedExternalWritePaths | Mitigated by 0.2 |
| R2 | Stop hook race (triage vs auto-commit) | HIGH | LIKELY | Disable auto-commit initially | Mitigated by 0.2 |
| R3 | Memory JSON dirties git working tree | MEDIUM | CERTAIN | .gitignore additions | Mitigated by 0.3 |
| R4 | Self-retrieval bias (plugin retrieves memories about itself) | LOW | CERTAIN | Accepted -- this IS the dogfood |
| R5 | Guardian blocks plugin source file edits | LOW | UNLIKELY | Guardian allows in-project edits by default |
| R6 | Parallel PreToolUse race condition | LOW | UNLIKELY | Hooks are idempotent read-only checks |
| R7 | Agent modifies its own hook scripts | LOW | POSSIBLE | Guardian Edit hook provides natural guardrail |

---

## 7. What This Replaces

This architecture replaces the "Cross-Repo Promotion" approach from CFL v1
(`research/closed-feedback-loop.md`). Instead of importing verification data
from the ops repo, we simulate the ops environment within the claude-memory
repo itself by co-installing guardian.

Key differences:
- **v1**: Run in ops, export data, import to claude-memory for analysis
- **v2**: Run directly in claude-memory with both plugins, observe in-place
- **v2 advantage**: Zero data transfer, real-time observation, true recursive feedback
- **v2 tradeoff**: Memory captures are about plugin development (feature, not bug)

---

## 8. File Reference

| File | Role in Architecture |
|------|---------------------|
| `.claude/plugin-dirs` | Plugin loading config (add self + guardian) |
| `.claude/guardian/config.json` | Guardian dogfood profile (to be created) |
| `.claude/memory/memory-config.json` | Memory runtime config (to be created) |
| `.claude/cfl-data/` | Data collection root (to be created) |
| `.gitignore` | Ignore rules for runtime data (to be updated) |
| `hooks/hooks.json` | Memory hook registration (no changes needed) |
| `.claude-plugin/plugin.json` | Plugin manifest (no changes needed) |
| `hooks/scripts/memory_staging_utils.py` | Staging dir computation (hash: 52f0f4a8baed) |
| `agents/memory-drafter.md` | Phase 1 agent (Write tool to /tmp/ -- needs guardian allowlist) |

---

## Appendix A: Staging Hash Derivation

```python
import hashlib, os
cwd = '/home/idnotbe/projects/claude-memory'
h = hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]
# Result: 52f0f4a8baed
# Staging dir: /tmp/.claude-memory-staging-52f0f4a8baed
```

## Appendix B: Hook Interaction Matrix

| Event | Memory Hook | Guardian Hook | Interaction |
|-------|------------|---------------|-------------|
| Stop | triage (may block) | auto-commit | RACE -- disable auto-commit |
| PreToolUse:Write | write_guard (deny .claude/memory, approve staging) | write_guardian (deny outside-project) | CONFLICT on /tmp/ staging -- needs allowlist |
| PreToolUse:Bash | staging_guard (deny staging writes) | bash_guardian (command analysis) | Independent -- different concerns |
| PreToolUse:Read | (none) | read_guardian | Guardian only -- no conflict |
| PreToolUse:Edit | (none) | edit_guardian | Guardian only -- no conflict |
| PostToolUse:Write | validate_hook (schema check) | (none) | Memory only -- no conflict |
| UserPromptSubmit | retrieve (inject memories) | (none) | Memory only -- no conflict |
| SessionStart | (none) | session_start | Guardian only -- no conflict |

## Appendix C: Cross-Model Validation Summary

### Codex 5.3 (433s, 1.2M input tokens)
- Recommended worktree isolation
- Identified 5 critical findings: no circular execution risk, config memory_root is agent-interpreted only, guardian blocks /tmp staging, venv resolves wrong path, hook precedence undefined
- Proposed 4-phase plan: create worktree, define cross-plugin contract, separate data classes, harden runtime resolution
- **Adopted**: Guardian staging allowlist, auto-commit disable, data collection structure
- **Rejected**: Worktree isolation (defeats dogfood purpose)

### Gemini 3.1 Pro (149s, 30K tokens)
- Recommended true dogfood in canonical repo
- Identified CLAUDE_PLUGIN_ROOT == cwd as safe since hooks are independent subprocesses
- Proposed embracing shared .venv as feature
- Noted Guardian AND logic for PreToolUse hooks
- **Adopted**: True dogfood approach, .venv-as-feature framing
- **Rejected**: Underestimated guardian /tmp blocking severity

### Gemini 3 Pro (thinkdeep vibe check)
- Suggested moving staging inside project to avoid Guardian /tmp issue
- **Rejected**: Staging was deliberately moved to /tmp/ to avoid Claude Code's hardcoded .claude/ protected directory approval popups. Moving it back reintroduces P3 UX regression.
- Suggested .claude/.gitignore with `*` for recursive ignore
- **Partially adopted**: Use targeted .gitignore rules instead of blanket ignore
