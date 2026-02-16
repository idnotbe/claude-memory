# Verification Round 1: Integration Review

**Reviewer:** reviewer-integration
**Date:** 2026-02-16
**Files reviewed:** memory_triage.py, SKILL.md, memory_write_guard.py, memory_write.py, memory_candidate.py, memory_retrieve.py, memory_validate_hook.py, memory_index.py, hooks.json, memory-config.default.json

---

## 1. Triage -> SKILL.md Handoff

**Verdict: PASS**

The `<triage_data>` JSON structure produced by `format_block_message()` (memory_triage.py:756-786) matches what SKILL.md Phase 0 expects to parse.

**Field consistency check:**
- `categories[]` array: each entry has `category` (string), `score` (float), `context_file` (optional string) -- SKILL.md Phase 1 step 1 says "Read the context file at the path from triage_data" -- matches.
- `parallel_config` object: has `enabled`, `category_models`, `verification_model`, `default_model` -- SKILL.md Phase 0 says "Read `memory-config.json` for `triage.parallel.category_models`" and Phase 1 says "model: config.category_models[category] or default_model" -- matches.
- Category name format: triage outputs UPPERCASE (`"DECISION"`, `"RUNBOOK"`, etc.) per memory_triage.py:759. SKILL.md Phase 1 step 2 says `--category <cat>` which memory_candidate.py expects as lowercase (`decision`, `runbook`, etc.) per its `--category` choices (memory_candidate.py:197-198).

**MAJOR issue found (upgraded from MINOR after cross-validation):**

- **Category name casing mismatch**: Triage outputs `"category": "DECISION"` (uppercase) in `<triage_data>`, but `memory_candidate.py --category` expects lowercase (`decision`). SKILL.md step 2 says `--category <cat>` without specifying the casing transformation. The subagent must lowercase the category name before passing it to memory_candidate.py.
  - **Severity: MAJOR** -- `memory_candidate.py` uses `argparse` with `choices=list(CATEGORY_FOLDERS.keys())` which are all lowercase. Argparse performs strict string matching -- passing `--category DECISION` will cause an immediate error: `error: argument --category: invalid choice: 'DECISION'`. This is a mechanical failure, not an LLM inference problem. The subagent would need to retry after seeing the error, wasting a tool call and risking haiku giving up.
  - **File:line:** memory_triage.py:759, SKILL.md:54, memory_candidate.py:197-198
  - **Fix (option A -- SKILL.md):** Add to SKILL.md Phase 1 step 2: "Use lowercase category name (e.g., `decision`, not `DECISION`)."
  - **Fix (option B -- triage hook, preferred):** In `memory_triage.py`, emit lowercase category names in `<triage_data>`. Change line 759 to `"category": category.lower()`. This fixes it at the source and requires no LLM-side awareness. The `parallel_config.category_models` keys are already lowercase, so this would make the triage output internally consistent.
  - **Cross-validation:** Confirmed by Gemini 3 Pro via pal clink -- rated CRITICAL. Upgraded from original MINOR to MAJOR (argparse is a strict validator, not an LLM that can infer intent).

---

## 2. SKILL.md -> Task Tool Integration

**Verdict: PASS with MINOR note**

SKILL.md correctly describes the Task tool invocation pattern (lines 39-47):
```
Task(
  model: config.category_models[category] or default_model,
  subagent_type: "general-purpose",
  prompt: [subagent instructions below]
)
```

**Model values check:**
- Config uses `"haiku"`, `"sonnet"`, `"opus"` -- these are the correct shorthand values for Claude Code's Task tool `model` parameter.
- VALID_MODELS in memory_triage.py:466 = `{"haiku", "sonnet", "opus"}` -- validated at config parse time.

**Note:** The Task tool's `subagent_type` parameter accepts `"general-purpose"` as a valid value. The SKILL.md correctly specifies this.

---

## 3. Subagent -> memory_candidate.py

**Verdict: PASS**

SKILL.md step 2 instructs subagents to run:
```
python3 hooks/scripts/memory_candidate.py --category <cat> --new-info "<summary>" --root .claude/memory
```

**Checks:**
- **Working directory**: Subagents inherit the project's working directory. `hooks/scripts/memory_candidate.py` is a relative path from project root -- correct.
- **Python path**: `python3` will use the system Python. memory_candidate.py is stdlib-only -- no venv needed. Correct.
- **Argument format**: `--category`, `--new-info`, `--root` all match memory_candidate.py's argparse definition (lines 192-214).
- **Output parsing**: SKILL.md step 3 lists `vetoes`, `pre_action`, `candidate` -- these match the JSON output keys in memory_candidate.py:369-377. The output also includes `structural_cud`, `lifecycle_event`, `delete_allowed`, `hints` -- not mentioned in SKILL.md but not needed by subagents.

**One consideration:**
- The `--new-info` argument needs to be properly quoted since it contains free-form text. Bash tool handles this, so this is a non-issue for subagents using the Bash tool.

---

## 4. Main Agent -> memory_write.py

**Verdict: PASS**

SKILL.md Phase 3 (lines 84-88) describes these calls:
- **CREATE**: `python3 hooks/scripts/memory_write.py --action create --category <cat> --target <path> --input <draft>`
- **UPDATE**: `python3 hooks/scripts/memory_write.py --action update --category <cat> --target <path> --input <draft> --hash <md5>`
- **DELETE**: `python3 hooks/scripts/memory_write.py --action delete --target <path> --reason "<why>"`

**Checks:**
- All argument names match memory_write.py's argparse (lines 1230-1247).
- `--hash` is the MD5 OCC parameter -- memory_write.py:1243-1245 accepts this.
- For CREATE, `--category` is required (memory_write.py:1255-1256) -- SKILL.md includes it. Correct.
- For UPDATE, `--hash` is optional but warned (memory_write.py:1259-1260) -- SKILL.md says "compute its MD5 hash for OCC" implying it will be provided. Correct.
- For DELETE, `--reason` is used (memory_write.py:1246) -- SKILL.md includes it. Correct.

**OCC hash computation**: SKILL.md Phase 3 line 86 says "Read the candidate file, compute its MD5 hash for OCC." This is correct -- memory_write.py's `file_md5()` (line 449-455) computes MD5 of the file content. The main agent would compute `md5sum <file>` or use Python to compute it. Either approach produces the same hex digest.

---

## 5. Hook System Integration (Write Guard)

**Verdict: CRITICAL ISSUE FOUND**

### 5a. PreToolUse:Write guard (memory_write_guard.py)

The write guard at memory_write_guard.py:41-43 allows temp files matching this pattern:
```python
if (resolved.startswith("/tmp/")
        and basename.startswith(".memory-write-pending")
        and basename.endswith(".json")):
    sys.exit(0)
```

This allows filenames like `/tmp/.memory-write-pending*.json`.

**However**, SKILL.md Phase 1 step 5 instructs subagents to write drafts to:
```
/tmp/.memory-draft-<category>-<pid>.json
```

**The write guard does NOT allow `/tmp/.memory-draft-*` files.** The guard only allows files starting with `.memory-write-pending`.

- **Severity: CRITICAL**
- **Impact:** When a Phase 1 subagent tries to use Claude's Write tool to create `/tmp/.memory-draft-DECISION-12345.json`, the PreToolUse:Write guard will fire and... actually, wait.

Let me re-examine. The write guard checks if the path contains `/.claude/memory/` (memory_write_guard.py:47). If the path is `/tmp/.memory-draft-...`, it does NOT contain `/.claude/memory/`. The guard only blocks writes to the memory directory, not writes to `/tmp/`.

**Re-analysis:** The write guard has TWO checks:
1. Lines 41-43: If path starts with `/tmp/` and matches `.memory-write-pending*.json` -> allow immediately (`sys.exit(0)`)
2. Lines 46-47: If path contains `/.claude/memory/` -> deny

For `/tmp/.memory-draft-DECISION-12345.json`:
- Check 1 fails (basename doesn't start with `.memory-write-pending`)
- Check 2: `/tmp/.memory-draft-DECISION-12345.json` does NOT contain `/.claude/memory/`
- Falls through to `sys.exit(0)` at line 63 -> **allowed**

**Revised verdict: PASS** -- The write guard only blocks writes INTO the memory directory. Writes to `/tmp/` that don't match the early-exit pattern simply fall through to the default allow. The `.memory-write-pending` check is an optimization (early exit before path resolution) rather than a security gate.

However, there is an **INFO-level inconsistency**: The write guard's comment on line 38-39 says "Allow writes to temp staging files used by the LLM" suggesting the `.memory-write-pending` pattern was intentionally designed for this purpose. The new flow uses a different pattern (`.memory-draft-`). If someone later tightens the guard to explicitly deny all `/tmp/` writes except the allowlisted pattern, the new flow would break.

- **Severity: INFO**
- **Fix (recommended):** Add `.memory-draft-` and `.memory-triage-context-` to the write guard's allowlist for future-proofing:

```python
basename = os.path.basename(resolved)
if resolved.startswith("/tmp/") and basename.endswith(".json"):
    if (basename.startswith(".memory-write-pending")
            or basename.startswith(".memory-draft-")):
        sys.exit(0)
```

### 5b. PostToolUse:Write hook (memory_validate_hook.py)

The PostToolUse hook checks if the written file is inside the memory directory (memory_validate_hook.py:49-52). For `/tmp/.memory-draft-*` files, `is_memory_file()` returns False (no `/.claude/memory/` in path), so the hook exits silently. **No issue.**

### 5c. Context file writes

Context files are written directly by Python (memory_triage.py:692), not via Claude's Write tool. They bypass hooks entirely. **No issue.**

---

## 6. Index Management Under Parallelism

**Verdict: PASS (with design notes)**

**Can parallel memory_write.py calls conflict on index.md?**

memory_write.py uses `_flock_index` (lines 1130-1187) which implements a directory-based lock (`mkdir` atomicity) with:
- 5-second timeout
- 60-second stale lock detection
- Poll interval of 0.05s

When Phase 3 runs multiple `memory_write.py` calls, they will contend on the index lock. But Phase 3 is executed by the **main agent sequentially** (SKILL.md line 81: "The main agent collects all Phase 1 and Phase 2 results, then applies..."). The main agent runs one `python3 memory_write.py` call at a time via Bash, waits for output, then runs the next.

Even if two Bash calls were somehow concurrent (e.g., the main agent runs them in parallel), the `_flock_index` lock ensures serialization.

**Key insight:** SKILL.md does not say "run all saves in parallel" -- it says "For each verified draft (PASS only)" implying sequential iteration. This is safe.

**Design note 1:** If Phase 3 were ever changed to parallelize saves, the lock mechanism is robust enough to handle it, though the 5-second timeout could be tight with 6 concurrent writers. This is not a current concern.

**Design note 2 (pre-existing, flagged by Gemini cross-validation):** The index.md write operations inside `add_to_index()`, `remove_from_index()`, and `update_index_entry()` (memory_write.py:380-431) use plain `open("w")` rather than atomic write-then-rename. While the `_flock_index` lock prevents concurrent *writers* from conflicting, concurrent *readers* (e.g., `memory_candidate.py`, `memory_retrieve.py`) do NOT acquire the lock. If `memory_write.py` crashes mid-write, `index.md` could be left truncated. The parallel flow increases the window of exposure since Phase 1 subagents may call `memory_candidate.py` (which reads index.md) while Phase 3 writes are in progress on a different category. In practice, Phase 1 and Phase 3 are sequential (Phase 1 completes before Phase 3 starts), so this is low-risk in the current design. This is a pre-existing concern, not introduced by the parallel changes. See INFO-3 below.

---

## 7. Edge Cases

### 7a. 0 categories triggered

**Verdict: PASS**

When `run_triage()` returns an empty `results` list (memory_triage.py:862-877), the hook exits with code 0 (allow stop). The SKILL.md is never invoked. No issue.

### 7b. 1 category triggered

**Verdict: PASS**

With 1 category, the flow still goes through the full parallel pipeline. SKILL.md Phase 1 says "Spawn ALL category subagents in PARALLEL" -- with 1 category, that's 1 subagent. This is correct and efficient (no wasted parallelism overhead since it's just a single Task call).

### 7c. All 6 categories triggered

**Verdict: PASS with MINOR note**

With 6 categories, Phase 1 spawns 6 Task subagents in parallel, and Phase 2 spawns up to 6 verification subagents. This is 12 total subagent calls, which could be expensive.

- **Severity: INFO**
- **Note:** 6 simultaneous subagents is within Claude Code's capabilities, but the cost/latency should be considered. The config allows disabling specific categories (`categories.<name>.enabled`) to reduce load, but the triage hook itself checks thresholds, not the enabled flag. The `enabled` flag in config (memory-config.default.json:5) is for auto_capture, not triage thresholds. However, in practice, 6 categories triggering simultaneously would require a very diverse conversation -- unlikely but possible.

### 7d. Session rolling window after parallel session_summary creation

**Verdict: PASS**

SKILL.md lines 92-93: "After all saves, enforce session rolling window if session_summary was created." This is handled after Phase 3 completes, by the main agent. The rolling window logic (SKILL.md lines 146-173) runs sequentially after all parallel work is done. The `memory_write.py --action delete` call for the oldest session also uses the index lock. No conflict.

---

## 8. hooks.json Configuration

**Verdict: PASS**

hooks.json (hooks/hooks.json) contains:
- **Stop**: 1 command hook running `memory_triage.py` with 30s timeout, matcher `*` -- correct.
- **PreToolUse**: Write matcher, runs `memory_write_guard.py` with 5s timeout -- correct.
- **PostToolUse**: Write matcher, runs `memory_validate_hook.py` with 10s timeout -- correct.
- **UserPromptSubmit**: matcher `*`, runs `memory_retrieve.py` with 10s timeout -- correct.

All hooks use `"type": "command"` with `$CLAUDE_PLUGIN_ROOT` for path resolution. The Stop hook timeout of 30s is generous enough for the triage hook to read stdin, parse transcript, run scoring, write context files, and format output.

---

## Summary Table

| # | Aspect | Verdict | Severity | Notes |
|---|--------|---------|----------|-------|
| 1 | Triage -> SKILL.md handoff | PASS* | **MAJOR** | Category casing (UPPER vs lower) -- argparse rejects uppercase |
| 2 | SKILL.md -> Task tool | PASS | - | Model values correct |
| 3 | Subagent -> memory_candidate.py | PASS | - | Args, paths, output format all match |
| 4 | Main agent -> memory_write.py | PASS | - | All action arg formats correct |
| 5 | Write guard (PreToolUse) | PASS | INFO | New temp file pattern not in allowlist but falls through to default allow |
| 6 | Index management parallelism | PASS | INFO | Sequential Phase 3 safe; non-atomic index writes pre-existing concern |
| 7a | 0 categories | PASS | - | |
| 7b | 1 category | PASS | - | |
| 7c | 6 categories | PASS | INFO | 12 subagent calls, cost consideration |
| 7d | Session rolling window | PASS | - | |
| 8 | hooks.json | PASS | - | |

*PASS contingent on fix: either SKILL.md must specify lowercase or triage must emit lowercase.

---

## Issues Found

### MAJOR-1: Category casing mismatch (triage -> memory_candidate.py)
- **File:** memory_triage.py:759, SKILL.md:54, memory_candidate.py:197-198
- **Severity:** MAJOR (upgraded from MINOR after Gemini cross-validation)
- **Description:** Triage outputs uppercase category names (`DECISION`) in `<triage_data>`, but `memory_candidate.py --category` uses argparse with `choices=list(CATEGORY_FOLDERS.keys())` (all lowercase). Argparse performs strict string equality -- `--category DECISION` fails with `invalid choice`. This is a mechanical failure that blocks the subagent flow.
- **Fix (preferred):** In memory_triage.py, emit lowercase category names in `<triage_data>` by changing line 759 to `"category": category.lower()`. This fixes at the source.
- **Fix (alternative):** Add explicit lowercase instruction to SKILL.md Phase 1 step 2.

### INFO-1: Write guard allowlist doesn't include new temp file patterns
- **File:** hooks/scripts/memory_write_guard.py:41-43
- **Severity:** INFO
- **Description:** The write guard's early-exit allowlist only covers `.memory-write-pending*.json`. The new parallel flow uses `/tmp/.memory-draft-*` and `/tmp/.memory-triage-context-*`. These are allowed by the default fall-through path (no `/.claude/memory/` in path), so there's no functional bug. But if the guard is ever tightened, this could break.
- **Fix:** Add `.memory-draft-` pattern to the allowlist for future-proofing.

### INFO-2: 6-category simultaneous trigger cost
- **File:** skills/memory-management/SKILL.md:49
- **Severity:** INFO
- **Description:** Maximum parallelism (6 drafting + 6 verification = 12 subagents) could be expensive. No functional issue.
- **Fix:** None needed. Cost is acceptable for the rare 6-category case.

### INFO-3: Non-atomic index.md writes (pre-existing)
- **File:** hooks/scripts/memory_write.py:380-431
- **Severity:** INFO (pre-existing, not introduced by this change)
- **Description:** `add_to_index()`, `remove_from_index()`, and `update_index_entry()` use plain `open("w")` rather than atomic write-then-rename. Concurrent readers (memory_candidate.py, memory_retrieve.py) do not acquire the flock and could see a truncated index if a crash occurs mid-write. Low risk in the current sequential Phase 3 design, but worth noting.
- **Fix:** Update index write functions to use write-to-temp-then-rename pattern (matching `atomic_write_json`).

---

## Cross-Validation Notes

- Triage hook's `format_block_message()` output was traced end-to-end through SKILL.md's Phase 0-3 pipeline. All field references resolve correctly.
- memory_write.py's `_flock_index` was verified as safe for the sequential Phase 3 pattern.
- The write guard fall-through behavior was verified by tracing both code paths (allowlist match and default path).
- memory_candidate.py's `--root .claude/memory` default matches the project convention.

### Gemini 3 Pro Cross-Validation (via pal clink)

Gemini identified 4 findings:
1. **Category casing** -- rated CRITICAL. Agreed, upgraded from MINOR to MAJOR (argparse strict matching). See MAJOR-1.
2. **Non-atomic index writes** -- rated HIGH. Acknowledged as pre-existing. The parallel flow's sequential Phase 3 mitigates risk. See INFO-3.
3. **Task tool model aliases** -- rated MEDIUM. **Disagree**: Claude Code's Task tool does accept "haiku", "sonnet", "opus" as shorthand values. This is documented behavior. No issue.
4. **Write guard allowlist** -- rated LOW. Agreed. See INFO-1.

### Vibe Check Self-Assessment

The initial review had a **severity downgrade bias** on the category casing issue: the original analysis conflated "LLM can figure it out" with argparse's strict validation behavior. Argparse is not an LLM -- it performs exact string matching. This was the key insight from cross-validation.

---

## Overall Assessment

**CONDITIONAL PASS** -- All integration points are structurally sound, but one MAJOR issue (category casing mismatch) must be fixed before the parallel flow can work. The fix is straightforward (one line change in memory_triage.py or one sentence added to SKILL.md). Three INFO-level notes for future consideration. No CRITICAL issues found.
