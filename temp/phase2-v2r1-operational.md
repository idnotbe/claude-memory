# Phase 2 V2R1 — Operational & Error Handling Review

**Scope:** SKILL.md Phase 3 (Save Subagent), lines 209-290
**Reviewer:** v2r1-operational agent
**Cross-validation:** Gemini 3.1 Pro via PAL clink (codex unavailable — rate limit)
**Date:** 2026-02-28

## Verdict: PASS_WITH_FIXES

Two concrete issues found (D1 critical, D2 moderate). Six areas pass cleanly.

---

## Findings

### D1: CRITICAL — Step 3 Error Handling Uses Blocked Bash Write

**Location:** SKILL.md lines 283-288 (Phase 3 Step 3)

**Issue:** The error handling instructs the main agent to write the pending sentinel via Bash heredoc:
```bash
cat > .claude/memory/.staging/.triage-pending.json <<'EOF'
{"timestamp": "...", "categories": [...], "reason": "subagent_error"}
EOF
```

This will be **blocked by `memory_staging_guard.py`**. The staging guard regex (`_STAGING_WRITE_PATTERN`) explicitly matches `cat ... > ... .claude/memory/.staging/`. The hook returns `permissionDecision: deny`.

The irony: the SKILL.md Phase 1 subagent instructions (lines 102-118) correctly forbid Bash writes to `.staging/` and mandate the Write tool. But Phase 3 Step 3 violates its own rule.

**Impact:** When a save subagent fails, the main agent cannot write the pending sentinel. Next session: no sentinel = no "pending save" notification (Block 3 in `memory_retrieve.py` lines 482-496). However, orphan detection (Block 2, lines 467-480) would still fire after 300s if triage-data.json remains. So recovery is delayed but not completely broken.

**Fix:** Change Step 3 to use the Write tool:
```
Write(
  file_path: ".claude/memory/.staging/.triage-pending.json",
  content: '{"timestamp": "<ISO 8601 UTC>", "categories": ["<failed categories>"], "reason": "subagent_error"}'
)
```

This is allowed: `memory_write_guard.py` lines 53-58 explicitly permit Write tool access to `.staging/` subdirectory.

**Cross-validation:** Gemini 3.1 Pro independently identified this as a critical issue with the same root cause analysis.

---

### D2: MODERATE — Unconditional Cleanup Risks Silent Data Loss on Partial Failure

**Location:** SKILL.md lines 253-254 (subagent prompt cleanup command)

**Issue:** The subagent prompt says:
```
After all commands, run cleanup:
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt ...
```

"After all commands" is ambiguous — the subagent may interpret this as "after attempting all commands" even if some failed. If a `memory_write.py` command fails but the subagent still runs cleanup:
1. Staging files (triage-data.json, context files) are deleted
2. Result file is written with errors in the `errors` array
3. Next session sees the result file, shows "Memories saved ... [errors: ...]"
4. But the staging context files needed for retry are gone

**Mitigating factors:**
- The subagent prompt also says "If a command fails, record the error and continue" — this captures the error in the result file, so it's not truly silent.
- Step 3 error handling is for complete subagent failure (timeout, crash), not individual command failure. For individual command failures, errors are recorded in the result file.
- However, the staging context files are still destroyed, making `/memory:save` retry impossible.

**Fix:** Make cleanup conditional in the subagent prompt:
```
If ALL commands succeeded (no errors), run cleanup:
  rm -f .claude/memory/.staging/...
If ANY command failed, do NOT delete staging files.
```

Then write the result file regardless (with errors array populated).

**Cross-validation:** Gemini 3.1 Pro flagged this as critical. I downgrade to moderate because the error IS recorded in the result file (not truly silent), and the next session does receive notification of partial failure. But the loss of retry capability is a real concern.

---

### PASS Items

#### A) Venv Bootstrap (os.execv) in Subagent Context — PASS

`memory_write.py` line 35 uses `os.execv()` to re-exec under `.venv/bin/python3`. When the haiku subagent runs `python3 memory_write.py` via Bash tool, the shell spawns a child process. `os.execv()` replaces that child — the shell waits on the same PID, and stdout/stderr file descriptors are preserved. Output flows back correctly to the Task subagent.

The venv path resolution (`../../.venv/bin/python3` relative to the script) resolves to the plugin's `.venv`, which is correct regardless of the caller's context.

#### B) Staging Guard vs Subagent Bash Calls — PASS

The `PreToolUse:Bash` hook (`memory_staging_guard.py`) fires for ALL Bash tool calls, including those from Task subagents. However:

1. **Cleanup command** (`rm -f ...`): `rm` is NOT in the staging guard regex pattern. The pattern only matches `cat|echo|printf|tee|cp|mv|install|dd` and redirect operators. PASS.

2. **Result file heredoc** (`cat > "$HOME/.claude/.last-save-result.tmp" ...`): The staging guard regex requires `.claude/memory/.staging/` in the target path. `$HOME/.claude/.last-save-result.tmp` does NOT contain `.claude/memory/.staging/`. PASS.

3. **memory_write.py Bash calls**: These are `python3 ... memory_write.py --action ...`. No redirect to `.staging/`. PASS.

#### C) Result File Heredoc — PASS

The result file path `$HOME/.claude/.last-save-result.tmp` does not match the staging guard pattern `\.claude/memory/\.staging/`. The atomic pattern (write to `.tmp`, then `mv` to final) is correct and prevents partial reads.

However, a minor observation: the result file JSON contains template placeholders (`<ISO 8601 UTC>`, `<cwd absolute path>`, `<saved categories>`, `<saved titles>`) that the haiku subagent must fill in. Haiku is generally capable of this template expansion, but the format is less mechanical than a structured output. This is acceptable given that the result file is informational (next-session confirmation), not a critical control file.

#### E) CWD Consistency — PASS

Task subagents inherit the parent agent's working directory. Relative paths like `.claude/memory/.staging/` resolve identically. This is a fundamental property of Claude Code's Task tool architecture.

#### F) CLAUDE_PLUGIN_ROOT Resolution — PASS

The commands in the subagent prompt use `${CLAUDE_PLUGIN_ROOT}` as literal text. When the subagent runs these via Bash, the shell expands the env var. `CLAUDE_PLUGIN_ROOT` is set by Claude Code for the entire plugin session and is inherited by all child processes, including Task subagent Bash calls.

Additionally, the SKILL.md Phase 0 plugin self-check (line 19) verifies the variable is set before any operations begin.

#### G) Pending Sentinel Format Compatibility — PASS

The Step 3 sentinel format:
```json
{"timestamp": "...", "categories": ["..."], "reason": "subagent_error"}
```

Matches what `memory_retrieve.py` Block 3 (lines 482-496) expects:
- Reads `.triage-pending.json` as JSON dict
- Checks `categories` is a list with `len > 0`
- Outputs count-based notification

The `reason` field is not consumed by the retrieve hook (future-proofing only).

#### H) Race Condition — New Session During Save — PASS

The Task subagent is foreground (blocking), so the main agent waits. A parallel session (new terminal) could trigger Block 2 orphan detection, but the 300-second age guard (`_triage_age > 300`) provides adequate buffer for normal save operations. The orphan notification is informational and non-destructive — it suggests running `/memory:save` to retry, which is harmless.

---

## Cross-Validation Summary (Gemini 3.1 Pro)

| Item | My Verdict | Gemini Verdict | Agreement |
|------|-----------|---------------|-----------|
| A) Venv bootstrap | PASS | PASS | Yes |
| B) Staging guard vs cleanup | PASS | PASS | Yes |
| C) Result file heredoc | PASS | PASS | Yes |
| D) Subagent failure detection | D1: CRITICAL | ISSUE (same root cause) | Yes |
| E) CWD consistency | PASS | PASS | Yes |
| F) CLAUDE_PLUGIN_ROOT | PASS | PASS | Yes |
| G) Cleanup-then-result order | D2: MODERATE | ISSUE (rated critical) | Partial — agree on issue, disagree on severity |
| H) Race condition | PASS | PASS | Yes |

**Severity disagreement on G/D2:** Gemini rates the unconditional cleanup as critical ("guaranteed data loss"). I rate it moderate because: (1) errors are recorded in the result file, so it's not silent; (2) the primary concern is loss of retry capability, not data loss per se — the conversation transcript is still in Claude's history. However, I agree the fix is warranted.

---

## Required Fixes

1. **D1 (Critical):** Change SKILL.md Step 3 error handling from `cat >` Bash heredoc to Write tool for `.triage-pending.json`.
2. **D2 (Moderate):** Make staging cleanup conditional on all commands succeeding. If any fail, preserve staging files for retry.
