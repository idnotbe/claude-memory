# Verification Round 2: Adversarial Review

**Reviewer:** Opus 4.6 (1M context)
**Date:** 2026-03-22
**Focus:** Security, data loss, Guardian interaction, multi-hook interference, config corruption, rollback safety, P0 hotfix hidden interactions

---

## 1. SECURITY: New Attack Vectors Introduced by Proposed Changes

### 1.1 CRITICAL: `--action write-staging` is a General-Purpose Arbitrary File Writer

**Plan:** eliminate-all-popups.md Phase 3, Step 3.1
**Proposed:** Add `--action write-staging` to `memory_write.py`. Takes `--staging-dir`, `--filename`, `--content-file` (reads content from a /tmp file). Uses Python `open()` which bypasses the Write tool's protected directory check.

**Attack:** This action creates a new Bash-accessible write primitive that bypasses Claude Code's `.claude/` protected directory check entirely. Today, `memory_write.py` only writes to well-defined paths (memory files via create/update, `last-save-result.json` via write-save-result, cleanup via cleanup-staging). The `write-staging` action would accept an arbitrary `--filename` parameter. If `--filename` is not validated (e.g., `--filename ../../decisions/evil.json`), it becomes a directory traversal attack against the memory store.

Even WITH filename validation, the action creates a new code path where untrusted content (from `--content-file` in `/tmp/`) is written into `.claude/memory/.staging/`. If an attacker can control the `/tmp/` file contents (e.g., by winning a TOCTOU race between the main agent writing the file and `memory_write.py` reading it), they can inject arbitrary content into staging files.

**Severity:** HIGH. The existing `cleanup_staging()` has path containment checks (`resolve().relative_to(staging_path)`). The proposed `write-staging` action has NO containment specification in the plan. R1 missed this entirely.

**Mitigation required:**
- Validate `--filename` against the same `_STAGING_FILENAME_RE` regex used by `memory_write_guard.py`
- Resolve the full output path and verify `relative_to(staging_dir)`
- Use `O_NOFOLLOW` to prevent symlink attacks on the staging file itself
- Validate `--content-file` is in `/tmp/` with a known prefix

### 1.2 MEDIUM: `/tmp/` Staging (Option B) Symlink Attacks

**Plan:** eliminate-all-popups.md Phase 3, Option B proposes `/tmp/.claude-memory-staging-<project-hash>/`.

R1 did not analyze this option's security. On multi-user systems or systems with malicious processes, `/tmp/` is a hostile environment:
- **Pre-creation attack:** An attacker creates `/tmp/.claude-memory-staging-<hash>` as a symlink to `/home/victim/.claude/memory/decisions/`. All subsequent "staging" writes now directly modify the memory store.
- **Project hash predictability:** The hash is derived from the project path, which is observable. An attacker who knows the user's project location can precompute the hash.
- **Race condition:** Even with `mkdir -p`, if the attacker creates the symlink between the `os.path.exists` check and `os.makedirs`, the attack succeeds.

**Severity:** MEDIUM (Option B is "ALTERNATIVE", not recommended). But if anyone implements Option B, it needs `os.makedirs` with `lstat` symlink check, or exclusive `mkdir` (which fails if the path exists).

### 1.3 LOW: `cleanup-intents` Glob Injection

**Plan:** eliminate-all-popups.md Phase 1, Step 1.1
**Proposed:** `glob.glob(staging_dir + '/intent-*.json')` -> `os.remove()` each.

The `staging_dir` parameter comes from CLI args (`--staging-dir`). If the staging_dir contains glob metacharacters (e.g., `[` or `?`), the glob could match unintended files. However, the existing `cleanup_staging()` already uses `staging_path.glob(pattern)` with the same input, so this is not a NEW vulnerability -- it mirrors existing behavior. Low concern.

---

## 2. DATA LOSS: Memory Data Loss Scenarios

### 2.1 HIGH: `cleanup-intents` Could Race With Active Drafter Subagents

**Plan:** eliminate-all-popups.md Phase 1, Step 1.1
**Proposed:** `--action cleanup-intents` deletes `intent-*.json` files.

**Scenario:** SKILL.md Phase 0 Step 0 runs cleanup-intents BEFORE spawning Phase 1 drafters. But what if a PREVIOUS session's triage fired, spawned drafters, then crashed mid-save? The Pre-Phase checks for stale staging (`.triage-pending.json` or `triage-data.json` without `last-save-result.json`), but only if `<triage_data>` is absent. If triage data IS present (normal flow), Pre-Phase is skipped, and Phase 0 Step 0 blindly deletes all intent files -- including potentially valid ones from a concurrent drafter that hasn't finished writing.

This is the same risk as the current `python3 -c` inline code, but it's worth noting that the plan does NOT address the concurrency edge case. In practice, concurrent sessions running against the same project directory would have drafters racing against cleanup.

**R1 missed:** Concurrent session drafter/cleanup race.

### 2.2 MEDIUM: Removing `.triage-handled` From Cleanup Without Considering Multi-Session Accumulation

**Plan:** fix-stop-hook-refire.md Phase 1, Step 1.1
**Proposed:** Remove `.triage-handled` from `_STAGING_CLEANUP_PATTERNS`. The sentinel's 5-min TTL already provides self-cleanup.

After this change, `.triage-handled` is NEVER cleaned up by the plugin. It only self-cleans via TTL expiry checked at line 1081: `time.time() - sentinel_mtime < FLAG_TTL_SECONDS`. But after Step 1.2 increases `FLAG_TTL_SECONDS` to 1800 (30 min), the sentinel persists for 30 minutes.

The file itself is tiny (a timestamp string), so disk accumulation is not a concern. But the semantic issue is: after Step 1.2, `.triage-handled` blocks ALL triage for 30 minutes, even if the user genuinely starts a new, different task within that window. R1 identified this ("stale save-result may block new sessions") but only for `last-save-result.json`, not for `.triage-handled` itself.

**Combined effect of Step 1.1 + Step 1.2:** The sentinel never gets cleaned by staging cleanup AND it blocks for 30 minutes. If the user has a quick session (<30 min) that triggers a save, then starts a new session immediately, the new session's triage is silently suppressed for up to 30 minutes. This is the OPPOSITE of the current problem (too many fires), but it's a data loss scenario: genuinely new memory-worthy sessions are silently dropped.

Phase 3 (session-scoped sentinel) fixes this, but between Phase 1 and Phase 3, there's a regression window.

### 2.3 LOW: SKILL.md Phase 3 Write Tool for `last-save-result-input.json` After Guard Removal

**Plan:** eliminate-all-popups.md Phase 3 Step 3.4 removes staging auto-approve from `memory_write_guard.py`. But SKILL.md line 295 still instructs the Write tool for `last-save-result-input.json` (a staging file).

If Step 3.4 executes before Phase 2's `write-save-result-direct` action is implemented, the Write tool call for `last-save-result-input.json` would no longer be auto-approved. It would fall through to the default Claude Code protected directory check for `.claude/`, causing a popup. If the user denies the popup, the save-result file is never written, meaning `last-save-result.json` is never created. The P0 hotfix's Step 1.3 (save-result guard) would then never block re-triage, weakening the re-fire defense.

R1 identified this ordering issue but did not trace the cascading effect on the re-fire fix.

---

## 3. GUARDIAN INTERACTION: Do the Fixes Break Guardian Compatibility?

### 3.1 MEDIUM: `memory-drafter` Return-JSON Breaks Agent Tooling Model

**Plan:** eliminate-all-popups.md Phase 3 Step 3.2
**Proposed:** Drafter returns JSON as stdout instead of writing via Write tool.

The memory-drafter agent (`agents/memory-drafter.md`) has `tools: Read, Write`. The plan proposes changing it to output JSON as its response text. This means:
- The drafter no longer uses the Write tool
- The Write tool permission in `tools: Read, Write` is now unused
- The main agent must parse JSON from a conversational response

The main agent then writes the parsed JSON to staging via `memory_write.py --action write-staging` (a Bash call).

**Guardian concern:** The main agent now runs a Bash command containing or referencing `.claude/memory/.staging/` paths. The staging guard (`memory_staging_guard.py`) blocks Bash writes to `.staging/`. The `write-staging` action would need to be exempted from this guard, or the staging guard pattern would need updating.

Specifically, `_STAGING_WRITE_PATTERN` (line 42-52 of `memory_staging_guard.py`) looks for patterns like `cat|echo|printf` + redirect to `.claude/memory/.staging/`. Running `python3 memory_write.py --action write-staging --staging-dir .claude/memory/.staging/` does NOT match this regex (it's a python3 script call, not a cat/echo redirect). So the staging guard would NOT block it. This is correct behavior, but it means the staging guard provides NO protection for the new write-staging path. If someone runs `python3 memory_write.py --action write-staging --filename ../../../etc/evil` in a Bash command, the staging guard does not intercept it.

**R1 missed:** The staging guard's regex does not cover python3 script calls that write to staging. This is by design (memory_write.py is trusted), but the `write-staging` action extends the trusted surface area.

### 3.2 LOW: Removing Write Tool Usage May Trigger Guardian "No Tool Use" Patterns

If the drafter agent receives `tools: Read, Write` but never uses Write (only reads context file and returns JSON as text), some Guardian implementations may flag this as anomalous behavior (agent was given Write permission but didn't use it). This is speculative and depends on Guardian implementation details.

More practically: if the drafter agent has `tools: Read, Write` but the plan says it should NOT use Write, the prompt must explicitly say "Do NOT use the Write tool." This contradicts the current agent file line 24: "Write an intent JSON file to the given output path using the Write tool." The agent file and SKILL.md must be updated in lockstep.

---

## 4. THE "4 STOP HOOKS" ISSUE

### 4.1 CRITICAL: Multiple Stop Hooks Can Interfere With Re-Fire Fix

From the installed plugins and hooks.json files, the following Stop hooks are active:

| Plugin | Stop Hook | Behavior |
|--------|-----------|----------|
| claude-memory | `memory_triage.py` | Block stop to save memories |
| hookify | `stop.py` | User-configurable stop hooks |
| ralph-loop (marketplace, may or may not be installed per-project) | `stop-hook.sh` | Self-referential loop detection |

**The interference problem:** Claude Code evaluates ALL Stop hooks. If any hook returns `{"decision": "block"}`, the stop is blocked. The execution order of hooks is NOT guaranteed to be deterministic across plugins.

**Scenario 1: hookify Stop hook blocks AFTER memory triage allows.**
Memory triage checks its idempotency guards (`.triage-handled`, `FLAG_TTL`, save-result), determines this is a re-fire, and allows the stop (exit 0, no output). But hookify's `stop.py` independently blocks the stop for its own reasons. The user's session continues. Eventually, the user stops again. Memory triage's idempotency guards may have expired by this point, causing a GENUINE re-fire that the P0 hotfix was supposed to prevent.

This scenario is unlikely (hookify stop hooks are user-configured and rarely block), but the P0 fix's correctness depends on the assumption that memory triage is the ONLY hook that can block stops. If another hook blocks, the save flow starts but memory triage's idempotency guards are already consumed.

**Scenario 2: Other Stop hooks slow down the stop event.**
Each Stop hook has a timeout (memory triage: 30s, hookify: 10s). If hookify's stop.py hangs for 10s, the total stop evaluation takes 30+10=40s. During re-fire, this compounds: 3 re-fires * 40s = 120s of stop-time latency. The P0 fix (TTL increase) addresses memory triage re-fires but not the cumulative latency from other hooks.

**R1 completely missed the multi-hook interaction.** The `.stop_hook_active` flag at `.claude/.stop_hook_active` is consumed-on-read by `check_stop_flag()`. If hookify blocks the stop (after memory triage allowed it through by consuming the flag), the flag is gone. Next stop attempt: no flag, no sentinel (if TTL expired), triage re-fires.

### 4.2 MEDIUM: `set_stop_flag()` Location Creates Cross-Plugin Visibility

The stop flag is at `{cwd}/.claude/.stop_hook_active`. This is in `.claude/` -- the same protected directory. The flag is written via Python `open()` (not Write tool), so it bypasses the Write guard. But it's in the same namespace as hookify's potential files. If hookify or another plugin writes to `.claude/`, there's a namespace collision risk.

More importantly: the flag is in `.claude/` (not `.claude/memory/.staging/`). This means `cleanup_staging()` never touches it (correct), but it also means there's no centralized cleanup for `.claude/` root files. The `.stop_hook_active` file relies solely on TTL expiry + consumed-on-read for cleanup. If the read (consumption) never happens (e.g., the session crashes before the next stop), the flag persists as an orphan until TTL expires.

---

## 5. CONFIG CORRUPTION DURING TRANSITION

### 5.1 MEDIUM: New Config Keys Without Migration Path

Multiple plans propose new config keys:
- `triage.parallel.verification_enabled` (screen-noise-reduction, architecture-simplification)
- `triage.parallel.verification_categories` (architecture-simplification)

These keys do NOT exist in the current `memory-config.default.json` or any schema. The scripts use `config.get()` with defaults, so missing keys are safe. But:

**Problem:** If a user manually edits their `memory-config.json` and adds these keys during transition (e.g., following documentation before the code supports them), and the code is not yet deployed, the keys are silently ignored. When the code deploys, the keys take effect. This is safe but confusing.

**Worse problem:** If a user adds `"verification_enabled": false` to their config, and then the architecture-simplification plan changes the config structure (e.g., nests it differently), the old key is orphaned and verification is re-enabled by default. The user thinks verification is off, but it's on.

No migration mechanism exists for config schema evolution. The `load_config()` function in `memory_triage.py` reads flat keys with `.get()` defaults. There's no config version field, no migration script, no deprecation warnings.

### 5.2 LOW: `triage.thresholds.*` During RUNBOOK Threshold Change

Plan 1 Phase 2 changes RUNBOOK threshold from 0.4 to 0.5 in `DEFAULT_THRESHOLDS`. But users can override thresholds via `triage.thresholds.RUNBOOK` in `memory-config.json`. If a user has explicitly set `"RUNBOOK": 0.4"` in their config, the code change to defaults has NO EFFECT -- the user's config takes priority.

The plan does not mention checking for user-overridden thresholds. This is not a bug (the config system works correctly), but it means the RUNBOOK false positive fix only works for users who haven't customized thresholds.

---

## 6. ROLLBACK: Partial Completion Recovery

### 6.1 HIGH: P0 Hotfix Partial Application Creates Worse State

The P0 hotfix has 3 independent code changes:
- Step 1.1: Remove `.triage-handled` from cleanup patterns (memory_write.py)
- Step 1.2: Increase FLAG_TTL to 1800 (memory_triage.py)
- Step 1.3: Add save-result guard (memory_triage.py)

**Partial application scenarios:**

| Applied | Not Applied | Result |
|---------|------------|--------|
| Step 1.1 only | Steps 1.2, 1.3 | `.triage-handled` survives cleanup but still has 5-min TTL. Improvement: covers the case where save completes in <5 min. Still fails for 17-28 min saves. Partial fix, not worse. |
| Step 1.2 only | Steps 1.1, 1.3 | FLAG_TTL is 30 min, but `.triage-handled` is still deleted by cleanup. After cleanup, the only guard is `.stop_hook_active` (consumed on first re-check). Second re-fire goes through. Improvement: extends the window but doesn't solve cleanup destruction. Partial fix, not worse. |
| Step 1.3 only | Steps 1.1, 1.2 | Save-result guard checks `last-save-result.json` mtime. But FLAG_TTL is still 300s, so the guard uses a 5-min window. `last-save-result.json` is only written at save completion (Phase 3 end). Between triage fire and save completion, the file does not exist, so the guard has no effect during the critical window. After save completes, the file exists and blocks re-fires for 5 min. Marginal improvement. |
| Steps 1.1 + 1.2 | Step 1.3 | Sentinel survives cleanup AND has 30-min TTL. This is actually sufficient to prevent re-fires for most save flows. Step 1.3 is truly defense-in-depth. **This partial application works well.** |

**Conclusion:** Steps 1.1 + 1.2 are the minimal effective pair. Step 1.3 is genuinely optional for Phase 1. Partial application of individual steps is not worse than current behavior but provides reduced protection.

**However:** If Step 1.1 is applied (sentinel survives cleanup) but Step 1.2 is NOT applied, and a save flow takes exactly 5-6 minutes, the sentinel expires mid-save, cleanup runs, sentinel is gone (wait, no -- Step 1.1 removed it from cleanup). Actually, even without Step 1.2, removing the sentinel from cleanup (Step 1.1) means it persists for its full 5-min TTL from creation. If the save flow takes 6 minutes, the sentinel expires at minute 5, and re-fire at minute 6+ is unprotected. This is the same as current behavior minus the cleanup destruction. So Step 1.1 alone is a strict improvement.

**Rollback safety: GOOD.** All three changes can be independently reverted via git. No data migration, no schema changes, no state files to clean up.

### 6.2 MEDIUM: Architecture Simplification Partial Completion

If `memory_detect.py` is created (Phase 2) but SKILL.md is not updated (Phase 4), the new script is dead code. No harm.

If SKILL.md is updated (Phase 4) but `memory_detect.py` crashes, the save flow fails entirely. The existing SKILL.md is destroyed. Rollback requires `git checkout skills/memory-management/SKILL.md`. R1 recommended keeping `SKILL-v1.md` as fallback, which is the correct mitigation.

If `memory_commit.py` is partially implemented and crashes mid-save, some categories are saved and others are not. Staging files are preserved. But the index may be in an inconsistent state (some files written, index not fully updated). `memory_index.py --rebuild` can recover the index. Acceptable.

---

## 7. THE REAL QUESTION: Is the P0 Hotfix Safe to Ship Immediately?

### Analysis of Hidden Interactions

**Step 1.1 (Remove `.triage-handled` from cleanup patterns):**
- One-line deletion from a list constant
- Does NOT change any function signatures, control flow, or external behavior
- The cleanup function still runs, just skips this one file
- Other cleanup patterns (triage-data.json, context-*.txt, drafts, inputs, intents) are unaffected
- No interaction with other plans
- **SAFE**

**Step 1.2 (Increase FLAG_TTL_SECONDS from 300 to 1800):**
- One constant change
- Affects TWO code paths: `check_stop_flag()` (line 536: `age < FLAG_TTL_SECONDS`) and sentinel check (line 1081: `time.time() - sentinel_mtime < FLAG_TTL_SECONDS`)
- The stop flag (`check_stop_flag()`) uses `FLAG_TTL_SECONDS` to decide if the flag is "fresh." A stale flag (> TTL) is treated as expired. Increasing TTL means the flag is "fresh" for longer, meaning the hook allows stops through for a longer window after blocking.
- The sentinel check uses `FLAG_TTL_SECONDS` to decide if triage was "recently handled." Increasing TTL means triage is skipped for a longer window.

**Hidden interaction:** Both the stop flag AND the sentinel use the SAME `FLAG_TTL_SECONDS` constant. This means:
- If the user tries to stop within 30 minutes of a previous triage block, the stop flag check (step 4, line 1074) allows through immediately (returning 0 = allow stop). This is the intended "re-stop = allow" behavior.
- If the stop flag was consumed (deleted) on a previous check, the sentinel check (step 4b, line 1081) blocks triage for 30 minutes.

This creates a 30-minute window where NO triage can fire. For users who have long sessions (>30 min), this is fine -- the sentinel expires naturally. For users who have short sessions (<30 min) and stop/restart frequently, this suppresses legitimate triage.

**Concrete example:** User works for 25 minutes, stops. Triage fires, blocks stop, creates sentinel. Save flow runs (5 min). User stops again at minute 30. Sentinel was created at minute 25, so it's 5 minutes old -- well within the 1800s TTL. Triage is skipped. The save from the first stop covered the session. This is CORRECT behavior.

**Edge case:** User works for 25 minutes, stops. Triage fires, save fails (crash). User starts a new session, works for 10 minutes, stops. Sentinel is now 35 minutes old (25 + 10). 35 > 30 min TTL. Sentinel expired. Triage fires. This is CORRECT -- the failed save doesn't permanently block triage.

**Another edge case:** User works for 5 minutes, stops. Triage fires, save succeeds quickly (3 min). Total time: 8 minutes. Sentinel is 8 minutes old. User immediately starts a new session with completely different work. Works for 10 minutes, stops. Sentinel is now 18 minutes old. 18 min < 30 min TTL. Triage is SKIPPED. The new session's memories are NOT captured.

This is the R1-identified regression window. It's real but acceptable:
- Duration: up to 30 minutes after a successful save
- Impact: one missed auto-capture
- Recovery: manual `/memory:save` still works; next session after TTL expiry captures normally
- Frequency: only affects users who complete short sessions back-to-back

**Step 1.3 (Add save-result guard):**
- New code in `_run_triage()` after sentinel check
- Checks `last-save-result.json` mtime < FLAG_TTL_SECONDS
- `last-save-result.json` is written by `write_save_result()` at the END of Phase 3
- This file is NOT in `_STAGING_CLEANUP_PATTERNS` (confirmed by grep: only lines 562 and 619 reference it)

**Hidden interaction:** `last-save-result.json` persists through cleanup AND through session boundaries. It has no session scoping. If User A's session saves at 14:00, and User B (or the same user with a different task) starts at 14:15, the file is 15 minutes old, well within the 1800s TTL. Triage is blocked for User B.

On a single-user system, this is the same regression as Step 1.2. On a multi-user system (multiple Claude Code instances against the same project), this is a cross-session blocker. However, Claude Code is single-user by design, so this is acceptable.

**The only truly concerning hidden interaction:** After Steps 1.1 + 1.2 + 1.3, there are now THREE idempotency guards that all use the same `FLAG_TTL_SECONDS = 1800`:
1. `.stop_hook_active` flag (consumed on read, so one-shot)
2. `.triage-handled` sentinel (persists for 30 min, survives cleanup)
3. `last-save-result.json` mtime (persists for 30 min, survives cleanup)

Guards 2 and 3 are redundant (both persist, both use same TTL). This is acceptable as defense-in-depth, but it means TWO guards must expire before triage can fire again. If either file's mtime is within 30 minutes, triage is suppressed. In practice, both files are created within seconds of each other (sentinel at triage time, save-result at save completion), so their expiry times differ by the save flow duration (3-28 minutes). The LATER file (save-result) is the binding constraint.

**Net effect:** After the P0 hotfix, triage is suppressed for `FLAG_TTL_SECONDS` after the save completes (because `last-save-result.json` is the last file written). This is 30 minutes after save completion. For a 28-minute save flow, that's 58 minutes after the initial triage fire before triage can fire again. This is aggressive suppression but prevents re-fires.

### Verdict on P0 Safety

**The P0 hotfix (all 3 steps) is SAFE to ship immediately.** The regression window (30 min suppression of new-session triage) is acceptable because:
1. It only affects the very next session after a successful save
2. Manual `/memory:save` is always available as override
3. Phase 3 (session-scoped sentinel) eliminates this regression
4. The current behavior (2-3x re-fire producing ~78+ noise items) is dramatically worse than occasionally missing one auto-capture

**Recommended ship order:** Steps 1.1 + 1.2 together (minimal effective pair), then Step 1.3 (defense-in-depth). All three can ship in one commit.

---

## 8. FINDINGS R1 MISSED (Summary)

| # | Finding | Severity | Affected Plan(s) |
|---|---------|----------|-------------------|
| F1 | `write-staging` action is an arbitrary file writer with no path containment spec | HIGH | eliminate-all-popups |
| F2 | Multiple Stop hooks (hookify, ralph-loop) can consume the stop flag without memory triage knowing, breaking idempotency | CRITICAL (theoretical) | fix-stop-hook-refire |
| F3 | Steps 1.1 + 1.2 combined create 30-min suppression of `.triage-handled` (not just `last-save-result`) | MEDIUM | fix-stop-hook-refire |
| F4 | `cleanup-intents` races with concurrent session drafters | HIGH (edge case) | eliminate-all-popups |
| F5 | Staging guard regex does not cover `python3 script.py --action write-staging` pattern -- by design but extends trust surface | MEDIUM | eliminate-all-popups |
| F6 | No config migration mechanism for new keys across plan versions | MEDIUM | screen-noise-reduction, architecture-simplification |
| F7 | User-overridden `triage.thresholds.RUNBOOK` in config defeats the default threshold change | LOW | fix-stop-hook-refire |
| F8 | Step 3.4 (remove staging auto-approve) cascading effect on re-fire fix when Step 2 is incomplete | MEDIUM | eliminate-all-popups |
| F9 | `last-save-result.json` has no session scoping -- blocks cross-session triage for 30 min | MEDIUM | fix-stop-hook-refire |
| F10 | After P0, effective triage suppression is 30 min after save COMPLETION (not after triage fire), potentially 58 min total | LOW | fix-stop-hook-refire |

---

## 9. RECOMMENDED PRIORITY ADJUSTMENTS

1. **Ship P0 Steps 1.1 + 1.2 immediately.** Step 1.3 can follow but is optional for the immediate fix.
2. **Add path containment to `write-staging` design** before implementing eliminate-all-popups Phase 3.
3. **Investigate stop flag consumption** in multi-hook scenarios. Consider making the stop flag check non-destructive (check mtime without unlinking) or moving to session-scoped guard earlier.
4. **Test PermissionRequest hook** (eliminate-all-popups Option C) before committing to the more invasive Option A. If PermissionRequest works, it eliminates the need for `write-staging` entirely, avoiding finding F1.
5. **Skip screen-noise-reduction SKILL.md changes** if architecture-simplification is planned within 2 weeks. The SKILL.md rewrites would be thrown away.
