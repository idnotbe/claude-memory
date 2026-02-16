# Code Verification: Issues 2 and 3

Independent source code analysis with line-number citations.

---

## Q1: Anti-Resurrection (Issue 2)

### Is the anti-resurrection check ONLY on the `--action create` code path?

**Yes.** The anti-resurrection check exists exclusively within `do_create()` at lines 672-691 of `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_write.py`:

```python
# Line 670-691 (memory_write.py)
# OCC: flock on index -- anti-resurrection check inside lock
with _flock_index(index_path):
    # Anti-resurrection check (inside flock to prevent TOCTOU)
    if target_abs.exists():
        try:
            with open(target_abs, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if (existing.get("record_status") == "retired"
                    and existing.get("retired_at")):
                retired_at = datetime.fromisoformat(
                    existing["retired_at"].replace("Z", "+00:00")
                )
                age = (datetime.now(timezone.utc) - retired_at).total_seconds()
                if age < 86400:  # 24 hours
                    print(
                        f"ANTI_RESURRECTION_ERROR\n"
                        f"target: {args.target}\n"
                        f"retired_at: {existing['retired_at']}\n"
                        f"fix: This file was retired less than 24 hours ago. "
                        f"Wait or use a different target path."
                    )
                    return 1
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
```

No other action handler (`do_update`, `do_delete`, `do_archive`, `do_unarchive`) contains any anti-resurrection logic. Verified by searching all five `do_*` functions. The `do_update` function (lines 713-869) has OCC hash checking (line 829) and merge protections (line 761) but no resurrection check. `do_delete` (lines 872-944) is idempotent for already-retired entries (line 894) but does not check resurrection timing.

### Would a hypothetical `--action restore` bypass anti-resurrection?

**Yes, by design.** A `restore` action would be a purpose-built `retired -> active` transition. It would be its own code path (like `do_unarchive` is for `archived -> active`), and there is no reason it would call into `do_create()`. The anti-resurrection check lives inside `do_create()` specifically to prevent *accidental re-creation* of a retired memory through the normal CREATE workflow. A dedicated `restore` action is a *deliberate* user-initiated reversal -- the opposite of what anti-resurrection guards against.

For reference, `do_unarchive()` (lines 1021-1084) performs `archived -> active` without any resurrection check, demonstrating the pattern: lifecycle transition actions are clean code paths that don't inherit CREATE's guards.

### Is the anti-resurrection an intentional safety feature or a side effect?

**Intentional safety feature.** Evidence:

1. **Placement within flock**: The check is explicitly placed inside the `_flock_index` context manager with the comment `"Anti-resurrection check (inside flock to prevent TOCTOU)"` (line 672). This is deliberate defensive coding against a race condition, not accidental.

2. **Descriptive error code**: It produces a specific `ANTI_RESURRECTION_ERROR` with a human-readable fix suggestion (line 685-690). Accidental side effects don't have custom error codes.

3. **24-hour window is hardcoded**: `86400` seconds (line 683) is a deliberate choice, not a coincidental value.

4. **Documentation treats it as a feature**: SKILL.md line 135 documents it under "Write Pipeline Protections" as a deliberate protection: "A memory cannot be re-created within 24 hours of retirement."

### Conclusion: Is Issue 2 a real problem?

**No. Issue 2 is not a real problem.** It is a consequence of Issue 1's absence.

The analysis chain:
1. The anti-resurrection check is on the CREATE path only (verified above).
2. A hypothetical `--action restore` would be a separate code path (like `do_unarchive`).
3. Once `--action restore` exists, it would never hit the anti-resurrection check.
4. The anti-resurrection check is a *feature* that protects CREATE from accidentally overwriting a recently-retired file -- the exact correct behavior for CREATE.
5. The current `--restore` workaround in `commands/memory.md` (lines 80-99) uses `--action create` as a workaround, which is why it hits anti-resurrection. The workaround is the problem, not the check.

**The doc team conflated the workaround's limitation with a design flaw.** The anti-resurrection check is working as designed. It only appears to be a problem because Issue 1 (`--action restore` missing) forces the workaround to go through CREATE.

---

## Q2: Agent-Interpreted Config Keys (Issue 3)

### Systematic verification of each key

The 8 agent-interpreted keys listed in CLAUDE.md line 59:

> `memory_root`, `categories.*.enabled`, `categories.*.folder`, `categories.*.auto_capture`, `categories.*.retention_days`, `auto_commit`, `max_memories_per_category`, `retrieval.match_strategy`, `delete.archive_retired`

(Note: CLAUDE.md actually lists 9 items including `categories.*.folder` which the original Issue 3 analysis listed 8. I'll cover all of them.)

#### Key 1: `memory_root`

**Python usage:** The `memory_root` config value is NOT read by any Python script.

- `memory_retrieve.py` (line 189): Hardcodes the path as `Path(cwd) / ".claude" / "memory"`.
- `memory_triage.py` (line 499): Hardcodes the path as `Path(cwd) / ".claude" / "memory" / "memory-config.json"`.
- `memory_write.py` (line 1205-1237): Derives `memory_root` from the `--target` argument by scanning for `.claude/memory` in the path.
- `memory_candidate.py` (line 80-81): Uses `--root` CLI argument, defaulting to `".claude/memory"`.
- `memory_index.py` (line 397-398): Uses `--root` CLI argument, defaulting to `".claude/memory"`.

**Verdict:** Truly agent-only. The scripts hardcode the path; the config value is a hint for the LLM to know where to look. This is **intentional** -- the Python scripts are invoked by the LLM agent which constructs CLI arguments, and the agent reads `memory_root` from config to know which directory to pass as `--root`. Making scripts read this config value would add complexity for zero benefit since the agent already constructs the paths.

#### Key 2: `categories.*.enabled`

**Python usage:** NOT read by any Python script.

- `memory_triage.py`: Does NOT check `categories.*.enabled`. It reads `triage.enabled` (line 514-515) but evaluates ALL 6 categories unconditionally via `CATEGORY_PATTERNS` (line 75) and `run_triage()` (line 393).
- `memory_retrieve.py`: Does NOT filter by category enabled status. It processes all index entries regardless.
- `memory_write.py`: Does NOT check whether a category is enabled before accepting writes.

**Verdict:** Truly agent-only. The triage hook fires for all categories based on keyword patterns. Whether to *act* on a triggered category (i.e., actually spawn a subagent to draft a memory) is the agent's decision, informed by this config.

**Could script enforcement help?** Partially. `memory_triage.py` could skip disabled categories before scoring. However, this would require the triage hook to read the full `categories.*` config section, and it already reads `triage.thresholds.*` per category, so the plumbing exists. This is a **reasonable candidate for script enforcement** in the triage hook -- it would prevent unnecessary context file generation for disabled categories.

#### Key 3: `categories.*.folder`

**Python usage:** NOT read from config. The folder mapping is hardcoded in three scripts:

- `memory_write.py` line 57-64: `CATEGORY_FOLDERS` dict
- `memory_index.py` line 26-33: `CATEGORY_FOLDERS` dict
- `memory_candidate.py` line 35-42: `CATEGORY_FOLDERS` dict

**Verdict:** The config value is purely informational -- it documents which folder maps to which category. The scripts use their own hardcoded mapping. This is **intentional** and correct: the mapping must be consistent across all scripts, so hardcoding ensures correctness. Making scripts read it from config would introduce a failure mode where a misconfigured `folder` value causes data to land in the wrong directory.

#### Key 4: `categories.*.auto_capture`

**Python usage:** NOT read by any Python script.

**Verdict:** Truly agent-only. This controls whether the agent should automatically save memories of this category when the triage hook triggers, versus only saving when the user explicitly requests. This is inherently a judgment call -- the hook triggers based on keywords, but the agent decides whether to auto-capture or wait for user instruction. **Script enforcement would not make sense** here because the hook already fires deterministically; `auto_capture` governs the agent's response to the hook's output, which is LLM behavior by nature.

#### Key 5: `categories.*.retention_days`

**Python usage:** NOT read by any Python script for automated expiry.

- `memory_index.py`'s `gc_retired()` (line 189-257) reads `delete.grace_period_days` (line 203) but NOT `retention_days`. The GC function only deletes retired memories past the grace period -- it does not auto-retire active memories past `retention_days`.

**Verdict:** Truly agent-only. The agent uses `retention_days` to decide when a memory should be retired (e.g., session summaries older than 90 days). This is **inherently judgment-based** -- "should this memory be retired?" requires evaluating relevance, not just age. A 91-day-old session summary might still be the most recent context for a long-running project.

**Could script enforcement help?** A script could flag memories past `retention_days` during GC or health checks, but the *decision* to retire should remain agent-interpreted. A **hybrid approach** would be reasonable: the health report (`memory_index.py --health`) could list active memories past their `retention_days` as "candidates for retirement," informing the agent without forcing action.

#### Key 6: `auto_commit`

**Python usage:** NOT read by any Python script.

**Verdict:** Truly agent-only. This controls whether the agent runs `git commit` after saving memories. This **cannot be script-enforced** in the current architecture because `memory_write.py` performs file writes and index updates but has no git integration. Adding git operations to `memory_write.py` would couple it to git, which is undesirable (the plugin should work in non-git directories). The agent is the right layer for this decision.

#### Key 7: `max_memories_per_category`

**Python usage:** NOT read by any Python script.

**Verdict:** Truly agent-only. The agent uses this to decide when a category folder is "full" and should trigger consolidation or retirement of old entries. **Script enforcement is feasible** -- `memory_write.py`'s `do_create()` could count existing files in the target category folder and reject creates that exceed the limit. This would provide a hard cap. However, the current design treats it as a soft limit, allowing the agent to decide *which* entries to retire to make room. A hard cap in the script would need to be paired with agent-side logic anyway.

**Assessment:** This is a reasonable candidate for adding a **warning** (not a hard block) in `memory_write.py` on CREATE -- e.g., stderr warning when the category count approaches the limit.

#### Key 8: `retrieval.match_strategy`

**Python usage:** NOT read by any Python script.

- `memory_retrieve.py` (lines 90-117): Uses a fixed `title_tags` matching strategy (exact word match on title: 2 points, exact tag match: 3 points, prefix match: 1 point). There is no branching based on a `match_strategy` config value.

**Verdict:** Truly agent-only. The config default is `"title_tags"` which happens to match what the script implements. This key was likely intended for future extensibility (e.g., adding `"semantic"` or `"full_text"` strategies). Currently it is effectively decorative -- the script ignores it and always uses title+tags matching.

**Could script enforcement help?** Yes, this is the **strongest candidate for script enforcement**. If `match_strategy` were read by `memory_retrieve.py`, different strategies could be implemented programmatically (e.g., `"title_only"`, `"tags_only"`, `"title_tags"`, `"full_text"`). Currently having it in config but not reading it is misleading to users who might think changing it affects retrieval behavior.

#### Key 9: `delete.archive_retired`

**Python usage:** NOT read by any Python script.

- `memory_index.py`'s `gc_retired()` (line 189-257) **permanently deletes** files past the grace period (line 235: `m["file"].unlink()`). It does NOT check `archive_retired` to decide whether to archive instead of delete.

**Verdict:** Truly agent-only. SKILL.md line 266 even annotates it: `"agent-interpreted, not script-enforced"`. The intent is that the agent, when running `/memory --gc`, should check this config and archive memories instead of purging them.

**Could script enforcement help?** Yes. `memory_index.py`'s `gc_retired()` could read `delete.archive_retired` and, when true, call `memory_write.py --action archive` instead of `unlink()`. This would be a **meaningful improvement** -- currently the agent must remember to honor this setting during GC, and if it forgets, data is permanently lost. Script enforcement would make this behavior reliable.

### Summary table: Agent-interpreted keys

| # | Config Key | Any Script Reads It? | Intentional Design? | Should Script Enforce? |
|---|-----------|---------------------|--------------------|-----------------------|
| 1 | `memory_root` | No | Yes -- agent constructs CLI paths | No -- would add complexity for no benefit |
| 2 | `categories.*.enabled` | No | Mostly -- but triage hook could skip disabled | Maybe -- triage could skip, saving context file generation |
| 3 | `categories.*.folder` | No (hardcoded) | Yes -- consistency requires hardcoding | No -- config is informational only |
| 4 | `categories.*.auto_capture` | No | Yes -- inherently agent judgment | No -- this is behavioral guidance |
| 5 | `categories.*.retention_days` | No | Yes -- retirement is qualitative | Hybrid -- health report could flag candidates |
| 6 | `auto_commit` | No | Yes -- git is agent-layer concern | No -- coupling scripts to git is wrong |
| 7 | `max_memories_per_category` | No | Yes -- soft limit by design | Maybe -- warning on CREATE near limit |
| 8 | `retrieval.match_strategy` | No | Questionable -- currently decorative | Yes -- strongest candidate for script logic |
| 9 | `delete.archive_retired` | No | Risky -- data loss if agent forgets | Yes -- GC should honor this deterministically |

---

## Q3: Cross-check

### Does SKILL.md explicitly instruct the LLM to read and act on these config keys?

**Partially.** Here is what SKILL.md says:

1. **Phase 0** (line 36): `"Read memory-config.json for triage.parallel.category_models."` -- This instructs reading the config, but only for the parallel config section, not the agent-interpreted keys.

2. **Config section** (lines 254-266): Lists all config keys with brief descriptions. This section is the primary mechanism for instructing the agent. Relevant entries:
   - Line 255: `categories.<name>.enabled` -- described as "enable/disable category (default: true)"
   - Line 256: `categories.<name>.auto_capture` -- described as "enable/disable auto-capture (default: true)"
   - Line 257: `categories.<name>.retention_days` -- described as "auto-expire after N days (0 = permanent; 90 for sessions)"
   - Line 260: `max_memories_per_category` -- described as "max files per folder (default: 100)"
   - Line 266: `delete.archive_retired` -- described with explicit note: "agent-interpreted, not script-enforced"

3. **Session Rolling Window** (lines 199-213): Explicitly instructs agent behavior around `max_retained` (not one of the 8 keys, but relevant pattern).

4. **Rules section** (line 248): `"Silent operation: Do NOT mention memory operations in visible output during auto-capture"` -- this is behavioral instruction, not config-key-driven.

**Key finding:** The SKILL.md Config section (lines 254-266) serves as a lookup table. It does NOT contain explicit behavioral instructions like "when `auto_capture` is false, skip automatic memory saves." The agent must infer behavior from brief descriptions. This works because LLMs are good at following configuration semantics from concise descriptions, but it does mean behavior depends on the LLM's interpretation of phrases like "enable/disable auto-capture."

### Is this a well-designed system where LLM interpretation is the right choice?

**Mostly yes, with two exceptions.**

**Where agent interpretation is correct:**
- `memory_root` -- agent constructs paths; script hardcoding ensures consistency
- `categories.*.folder` -- informational only; scripts must use hardcoded values
- `categories.*.auto_capture` -- behavioral guidance that inherently requires judgment
- `categories.*.retention_days` -- retirement is qualitative (age is one signal, not the only one)
- `auto_commit` -- git operations belong at the agent layer
- `max_memories_per_category` -- soft limit that requires agent to decide what to evict

**Where script enforcement would be better:**
- `delete.archive_retired` -- This controls data preservation during GC. If the agent forgets to check this, data is permanently deleted. The `gc_retired()` function in `memory_index.py` (line 235) calls `m["file"].unlink()` without checking this config. Making it script-enforced would prevent accidental data loss.
- `retrieval.match_strategy` -- Currently decorative. Either the config key should be removed (reducing user confusion) or the script should read it to enable different strategies.

**Where it's a reasonable gray area:**
- `categories.*.enabled` -- The triage hook could skip disabled categories to save compute (context file generation), but the agent still needs to honor this for user-initiated saves.

### Final assessment

The "agent-interpreted config keys are non-deterministic" framing is misleading. These keys are not non-deterministic in a harmful way -- they are configuration hints for an LLM agent, which is the correct pattern for behavioral guidance that requires judgment. The two exceptions (`delete.archive_retired` and `retrieval.match_strategy`) are real but minor design debts, not systemic issues with the architecture.

**Issue 3 verdict: NOT A REAL ISSUE as framed.** It is an intentional architectural choice with two specific keys that could benefit from tightening, not a systemic problem requiring rethinking.
