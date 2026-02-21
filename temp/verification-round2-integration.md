# Verification Round 2: Cross-File Integration Verification

**Reviewer**: verifier-integration
**Date**: 2026-02-18
**Scope**: R1 (SKILL.md script paths), R2 (staging paths), R3 (sentinel idempotency), R5 (plugin self-validation)
**Files reviewed**: SKILL.md, memory_triage.py, hooks.json, CLAUDE.md, memory_write_guard.py, .gitignore

---

## VERDICT: CONDITIONAL SHIP -- 1 blocking issue, 2 non-blocking issues

---

## 1. Path Consistency Check

### 1a. Context file paths: SKILL.md vs triage.py

**SKILL.md (line 71)**: `.claude/memory/.staging/context-<category>.txt`

**triage.py `write_context_files()` (lines 716-719)**:
```python
if staging_dir:
    path = os.path.join(staging_dir, f"context-{cat_lower}.txt")
else:
    path = f"/tmp/.memory-triage-context-{cat_lower}.txt"
```

Where `staging_dir` is `os.path.join(cwd, ".claude", "memory", ".staging")` (line 705).

**Result**: MATCH. When `cwd` is provided, triage.py writes to `{cwd}/.claude/memory/.staging/context-{cat_lower}.txt`, which matches SKILL.md's `.claude/memory/.staging/context-<category>.txt` (relative to project root). The fallback to `/tmp/` only activates when `cwd` is empty or directory creation fails.

### 1b. Draft file paths: SKILL.md consistency

**SKILL.md (line 99)**: `.claude/memory/.staging/draft-<category>-<pid>.json`
**SKILL.md (line 123-124)**: `starts with .claude/memory/.staging/draft-`

**Result**: MATCH. The draft path pattern is internally consistent within SKILL.md. Subagents receive the instruction to write drafts to `.claude/memory/.staging/draft-<category>-<pid>.json` (Phase 1, step 5), and the validation rule in Phase 3 checks for the `.claude/memory/.staging/draft-` prefix. These are aligned.

### 1c. Triage data `context_file` path in JSON output

**triage.py `format_block_message()` (lines 873-875)**:
```python
ctx_path = context_paths.get(cat_lower)
if ctx_path:
    entry["context_file"] = ctx_path
```

The `context_paths` dict contains the full absolute path (e.g., `/home/user/project/.claude/memory/.staging/context-decision.txt`). SKILL.md Phase 1 step 1 says: "Read the context file at the path from triage_data." This works because the path in the JSON is absolute and agents can read it directly.

**Result**: MATCH. The agent receives an absolute path in `triage_data.categories[].context_file` and reads it directly.

---

## 2. hooks.json Consistency

**hooks.json** reviewed at `/home/idnotbe/projects/claude-memory/hooks/hooks.json`:

| Hook | Command | Status |
|------|---------|--------|
| Stop | `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py"` | CORRECT |
| PreToolUse:Write | `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write_guard.py"` | CORRECT |
| PostToolUse:Write | `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_validate_hook.py"` | CORRECT |
| UserPromptSubmit | `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py"` | CORRECT |

All 4 hook entries correctly use `$CLAUDE_PLUGIN_ROOT`. No accidental modifications detected. The hooks.json was NOT part of the current changes and remains intact.

---

## 3. CLAUDE.md Consistency Check

### BLOCKING ISSUE: CLAUDE.md line 31 still references old `/tmp/` path

**CLAUDE.md line 31**:
```
3. **Context files** at `/tmp/.memory-triage-context-<CATEGORY>.txt` with generous transcript excerpts
```

**Should be**:
```
3. **Context files** at `.claude/memory/.staging/context-<CATEGORY>.txt` with generous transcript excerpts
```

The skill-fixer report (line 48) explicitly noted this:
> "CLAUDE.md line 31 still references `/tmp/.memory-triage-context-<CATEGORY>.txt` -- this is outside scope of Task #1 but should be updated separately for consistency."

**Severity**: BLOCKING. CLAUDE.md is loaded into the agent's system prompt. An agent reading CLAUDE.md could reasonably expect context files at `/tmp/` while triage.py now writes them to `.claude/memory/.staging/`. This is a documentation-code mismatch that could confuse agents trying to understand the architecture.

---

## 4. BLOCKING ISSUE: memory_write_guard.py NOT updated for staging paths

**This is a newly discovered integration issue not documented in the fix reports.**

`memory_write_guard.py` (lines 42-51) has an allowlist for `/tmp/` paths:

```python
# Allow writes to temp staging files used by the LLM
# Accept /tmp/.memory-write-pending*.json, /tmp/.memory-draft-*.json,
# and /tmp/.memory-triage-context-*.txt (parallel triage temp files)
basename = os.path.basename(resolved)
if resolved.startswith("/tmp/"):
    if (basename.startswith(".memory-write-pending") and basename.endswith(".json")):
        sys.exit(0)
    if (basename.startswith(".memory-draft-") and basename.endswith(".json")):
        sys.exit(0)
    if (basename.startswith(".memory-triage-context-") and basename.endswith(".txt")):
        sys.exit(0)
```

**Problem**: Now that staging files have moved to `.claude/memory/.staging/`, subagents will write draft files to `.claude/memory/.staging/draft-<category>-<pid>.json`. But this path is INSIDE the `.claude/memory/` directory, which the write guard BLOCKS (lines 66-80):

```python
if MEMORY_DIR_SEGMENT in normalized or normalized.endswith(MEMORY_DIR_TAIL):
    # DENY write
```

The subagent Write tool calls to `.claude/memory/.staging/draft-*.json` will be blocked by the write guard because:
1. The path contains `/.claude/memory/` (matches `MEMORY_DIR_SEGMENT`)
2. There is no allowlist exception for `.staging/` paths

**Impact**: HIGH. This breaks the Phase 1 drafting flow entirely. Subagents cannot write drafts to the staging directory.

**Fix needed**: Add a `.staging/` allowlist to `memory_write_guard.py` that exempts files matching `.claude/memory/.staging/draft-*.json` and `.claude/memory/.staging/context-*.txt` from the memory directory block.

**Note on context files**: The context files are written by `memory_triage.py` via `os.open()` (direct syscall), NOT via the Write tool, so they bypass the write guard. However, draft files are written by LLM subagents using the Write tool and WILL be blocked.

---

## 5. End-to-End Flow Trace

### Full flow with path verification:

```
Step 1: Stop hook fires
  -> Claude Code runs: python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py"
  -> triage.py reads stdin JSON (transcript_path, cwd)
  -> triage.py checks sentinel at {cwd}/.claude/memory/.staging/.triage-handled
     - If fresh (< 300s): returns 0 (allow stop) -- IDEMPOTENCY WORKS
     - If stale/missing: continues evaluation

Step 2: triage.py evaluates transcript
  -> Writes context files to {cwd}/.claude/memory/.staging/context-{cat}.txt
     via os.open() (bypasses Write tool guard) -- PATH CORRECT
  -> Writes score log to {cwd}/.claude/memory/.staging/.triage-scores.log
     via os.open() -- PATH CORRECT
  -> Creates sentinel at {cwd}/.claude/memory/.staging/.triage-handled
     via os.open() -- PATH CORRECT
  -> Sets stop_hook_active flag at {cwd}/.claude/.stop_hook_active -- UNCHANGED
  -> Outputs JSON: {"decision": "block", "reason": "...<triage_data>..."}
     - triage_data includes absolute context_file paths -- CORRECT
     - triage_data includes parallel_config -- CORRECT
     - Category names in JSON are lowercase -- CORRECT

Step 3: Agent receives block, reads SKILL.md
  -> SKILL.md Phase 0: Parse <triage_data> JSON -- CORRECT
  -> SKILL.md self-check (line 19): Verify ${CLAUDE_PLUGIN_ROOT} scripts exist -- NEW (R5)

Step 4: Agent spawns Phase 1 subagents
  -> Subagent reads context file from triage_data.context_file (absolute path) -- CORRECT
  -> Subagent runs: python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py"
     -- PATH CORRECT (R1 fix applied)
  -> Subagent writes draft to .claude/memory/.staging/draft-{cat}-{pid}.json
     -- !! BLOCKED by memory_write_guard.py !! (see issue #4 above)

Step 5: Agent runs Phase 3 save
  -> Draft path validation: starts with .claude/memory/.staging/draft- -- CORRECT
  -> Runs: python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create ...
     -- PATH CORRECT (R1 fix applied)

Step 6: Agent tries to stop again
  -> Stop hook fires again
  -> triage.py checks sentinel at {cwd}/.claude/memory/.staging/.triage-handled
  -> Sentinel is fresh (< 300s): returns 0 (allow stop) -- IDEMPOTENCY WORKS
  -> Also checks stop_hook_active flag (separate mechanism) -- WORKS
```

**Flow verdict**: The flow is correct EXCEPT for Step 4 where the write guard blocks draft writes to `.claude/memory/.staging/`.

---

## 6. .gitignore Check

The `.gitignore` at `/home/idnotbe/projects/claude-memory/.gitignore` does NOT have an entry for `.claude/memory/.staging/`. The original issues report (R2) recommended adding `.staging/` to `.gitignore` in `.claude/memory/`.

**Severity**: LOW (non-blocking). The `.staging/` directory is ephemeral. Without gitignore, staging artifacts could be accidentally committed. However, since this is the plugin's own repo (not a user project), the impact is minimal. In user projects, `.claude/` directories are typically gitignored.

---

## 7. Summary of Issues

| # | Issue | Severity | File | Action |
|---|-------|----------|------|--------|
| I1 | memory_write_guard.py has no allowlist for `.claude/memory/.staging/` paths; subagent draft writes will be BLOCKED | **BLOCKING** | hooks/scripts/memory_write_guard.py | Add `.staging/` exemption for draft-*.json and context-*.txt files |
| I2 | CLAUDE.md line 31 still references `/tmp/.memory-triage-context-<CATEGORY>.txt` | **NON-BLOCKING** (docs) | CLAUDE.md | Update to `.claude/memory/.staging/context-<CATEGORY>.txt` |
| I3 | `.gitignore` missing `.claude/memory/.staging/` entry | **LOW** | .gitignore | Add `.claude/memory/.staging/` |

### What's correct:
- SKILL.md script paths all use `${CLAUDE_PLUGIN_ROOT}` (R1) -- 5 occurrences verified
- SKILL.md staging paths all use `.claude/memory/.staging/` (R2) -- 3 occurrences verified
- SKILL.md has no remaining `/tmp/` references (confirmed by skill-fixer grep)
- triage.py `write_context_files()` writes to staging dir when `cwd` provided (R2)
- triage.py sentinel idempotency works correctly (R3)
- SKILL.md plugin self-check added (R5)
- hooks.json all use `$CLAUDE_PLUGIN_ROOT` correctly
- triage_data JSON emits lowercase category names matching downstream expectations
- Context files use secure `O_NOFOLLOW` + `0o600` permissions
- Sentinel file uses secure `O_NOFOLLOW` + `0o600` permissions
- Score log uses secure `O_NOFOLLOW` + `0o600` permissions
- `/tmp/` fallback in triage.py preserves backward compatibility
- SKILL.md Phase 3 draft path validation matches Phase 1 draft path format

---

## 8. Detailed Write Guard Analysis

To be absolutely clear about the blocking issue, here is the exact code path that fails:

1. SKILL.md Phase 1, Step 5 instructs subagent:
   > "Write complete memory JSON to `.claude/memory/.staging/draft-<category>-<pid>.json`."

2. The subagent uses the Write tool with `file_path=".claude/memory/.staging/draft-decision-12345.json"`

3. The PreToolUse:Write hook fires (`memory_write_guard.py`)

4. The guard resolves the path to something like `/home/user/project/.claude/memory/.staging/draft-decision-12345.json`

5. The guard normalizes it: `normalized = resolved.replace(os.sep, "/")`

6. The guard checks (line 66): `MEMORY_DIR_SEGMENT in normalized` where `MEMORY_DIR_SEGMENT = "/.claude/memory/"`

7. The path contains `/.claude/memory/` so the guard **DENIES** the write

8. The subagent cannot write its draft file

**Fix**: Insert a `.staging/` exemption check before the deny block:
```python
# Allow writes to staging directory (draft files, context files)
staging_segment = MEMORY_DIR_SEGMENT.rstrip("/") + "/.staging/"
if staging_segment in normalized:
    sys.exit(0)
```

Note: The old `/tmp/` allowlist (lines 42-51) can be kept for backward compatibility or removed -- the staging path exemption is the critical addition.
