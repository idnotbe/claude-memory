# Independent Verification Round 1

**Verifier**: Claude Opus 4.6 (independent agent)
**Date**: 2026-02-16
**Methodology**: Direct source code reading, exhaustive grep searches, vibe-check metacognitive review, Gemini 3 Pro independent code review via pal clink

---

## Verification Summary

| Conclusion from Analysis | My Verdict | Confidence |
|--------------------------|-----------|------------|
| 1. `--action restore` missing = REAL issue | **CONFIRMED** | Very High |
| 2. 24h anti-resurrection = NOT a real issue | **CONFIRMED** | Very High |
| 3. 8 agent-interpreted config keys = NOT systemic issue | **CONFIRMED** | Very High |
| 3a. `delete.archive_retired` = refinement opportunity | **CONFIRMED** | High |
| 3b. `retrieval.match_strategy` = refinement opportunity | **CONFIRMED with nuance** | High |

**Overall assessment**: The analysis is correct on all counts. I attempted to disprove each conclusion and failed.

---

## Detailed Findings

### Issue 1: `--action restore` Missing

**CONFIRMED as a real gap.**

Evidence:
- `memory_write.py` line 1250: `choices=["create", "update", "delete", "archive", "unarchive"]` -- "restore" is not an option.
- The five `do_*` handler functions are: `do_create()`, `do_update()`, `do_delete()`, `do_archive()`, `do_unarchive()`. There is no `do_restore()`.
- `do_update()` preserves record_status from the existing file (line 751: `new_data["record_status"] = old_data.get("record_status", "active")`). It cannot change retired to active.
- `do_unarchive()` only works on archived records (line 1043: `if data.get("record_status") != "archived"`). It explicitly rejects non-archived statuses.
- **State machine gap**: There exists `active -> retired` (do_delete) and `active -> archived` (do_archive) and `archived -> active` (do_unarchive), but NO `retired -> active` path.

Disproof attempt: Could you work around this via `do_update()` changing record_status? No -- line 497-501 in `check_merge_protections()` explicitly blocks record_status changes during UPDATE:
```python
if old.get("record_status", "active") != new.get("record_status", "active"):
    return False, (
        "MERGE_ERROR\nfield: record_status\nrule: immutable via UPDATE\n"
        "fix: Use --action delete to retire, or --action archive to archive"
    ), []
```

**Verdict: REAL ISSUE. No workaround exists in the current codebase.**

---

### Issue 2: 24h Anti-Resurrection Window

**CONFIRMED as NOT a real issue (working as designed).**

Evidence:
- The 86400-second (24h) check appears ONLY in `do_create()` at lines 672-691. Verified by grepping for `86400`, `24.*hour`, and `resurrection` -- all matches are within the `do_create()` function.
- It is completely absent from `do_update()`, `do_delete()`, `do_archive()`, and `do_unarchive()`.
- The check fires only when: (a) a CREATE action targets a file that already exists, AND (b) that file has `record_status == "retired"`, AND (c) `retired_at` is less than 24 hours ago.
- This is a safety feature preventing accidental overwrite of recently-retired memories during the create path.

Disproof attempt: Could the anti-resurrection block a future `--action restore`? No -- a restore action would be a separate code path (like `do_unarchive` is separate from `do_create`). It would transition `retired -> active` on the same file without going through the create path.

**The analysis correctly identifies that this issue only appeared relevant because of Issue 1's absence. Once `--action restore` is implemented, the anti-resurrection check on create is irrelevant to restoring retired memories.**

**Verdict: NOT AN ISSUE. Deliberate safety feature on create path only.**

---

### Issue 3: Agent-Interpreted Config Keys

**CONFIRMED as NOT a systemic issue.**

I verified all 8 keys against ALL Python scripts in `hooks/scripts/`:

| Config Key | Read by Any Script? | Evidence |
|------------|---------------------|----------|
| `memory_root` | NO | `memory_retrieve.py` hardcodes `Path(cwd) / ".claude" / "memory"` (line 189). `memory_write.py` derives root from target path. |
| `categories.*.enabled` | NO | `memory_triage.py` reads `triage.enabled` (different key). Category list is hardcoded in CATEGORY_FOLDERS/CATEGORY_PATTERNS. |
| `categories.*.auto_capture` | NO | Grep across all scripts: zero matches. |
| `categories.*.retention_days` | NO | Grep across all scripts: zero matches. |
| `auto_commit` | NO | Grep across all scripts: zero matches. |
| `max_memories_per_category` | NO | Grep across all scripts: zero matches. |
| `retrieval.match_strategy` | NO | `memory_retrieve.py` reads `retrieval.enabled` and `retrieval.max_inject` but NOT `match_strategy`. Scoring is hardcoded in `score_entry()`. |
| `delete.archive_retired` | NO | `do_delete()` unconditionally sets `record_status = "retired"`. Never reads config. |

Additional verification:
- `memory_candidate.py`: Does not read ANY config file (grep for "config" returns zero matches).
- `memory_index.py`: Does not read `auto_capture`, `retention_days`, or any of the 8 keys.
- `memory_write_guard.py`: Does not read any of the 8 keys.
- `memory_validate_hook.py`: Does not read any of the 8 keys.

Config keys that ARE script-enforced (correctly excluded from the 8):
- `retrieval.enabled` -- read by `memory_retrieve.py` line 217
- `retrieval.max_inject` -- read by `memory_retrieve.py` line 219, clamped to [0, 20]
- `triage.enabled` -- read by `memory_triage.py` line 514
- `triage.max_messages` -- read by `memory_triage.py` line 518, clamped to [10, 200]
- `triage.thresholds.*` -- read by `memory_triage.py` lines 526-539, clamped to [0.0, 1.0]
- `triage.parallel.*` -- read by `memory_triage.py` via `_parse_parallel_config()`

**The architecture is intentional**: keys that require deterministic enforcement are script-enforced. Keys that require LLM judgment (like "should I auto-capture this?" or "is this memory past its retention period?") are deliberately left as agent-interpreted hints in SKILL.md.

Disproof attempt: Could any of the 8 keys be read indirectly via a helper function? Verified: `memory_triage.py`'s `load_config()` reads the full JSON but then extracts ONLY `raw.get("triage", {})` (line 509). The returned config dict contains only `enabled`, `max_messages`, `thresholds`, `parallel`. No category-level or top-level keys pass through.

**Verdict: NOT A SYSTEMIC ISSUE. This is intentional architecture with a clear division between script-enforced (deterministic) and agent-interpreted (judgment-based) keys.**

---

### Issue 3a: `delete.archive_retired` Refinement

**CONFIRMED as a refinement opportunity.**

- `do_delete()` (lines 872-944) unconditionally retires memories. It never reads config.
- `memory_write.py` never reads `memory-config.json` at all -- it is entirely driven by CLI arguments.
- If the LLM forgets to check `delete.archive_retired` before calling `--action delete`, the memory is retired without archiving, regardless of the user's config preference.
- The SKILL.md itself already documents this gap at line 266: `"delete.archive_retired -- whether to archive instead of purge (default: true; agent-interpreted, not script-enforced)"`.

This is a legitimate refinement: `do_delete()` could read config and auto-upgrade to archive when `delete.archive_retired` is true. This would prevent data loss from LLM oversight.

However, this is NOT evidence that the agent-interpreted architecture is wrong. It is one specific key where script enforcement would provide a useful safety net.

---

### Issue 3b: `retrieval.match_strategy` Refinement

**CONFIRMED as a refinement opportunity, with nuance.**

- `memory_retrieve.py` reads `retrieval` config (lines 216-219) but only extracts `enabled` and `max_inject`. The `match_strategy` key is completely ignored.
- The scoring logic in `score_entry()` (lines 90-117) hardcodes a single approach: title token matching (2 points), tag matching (3 points), prefix matching (1 point).
- The default config value is `"title_tags"` which coincidentally describes what the hardcoded logic does.

**Nuance (from vibe-check)**: The current hardcoded behavior happens to match the `"title_tags"` value. So it is not purely "decorative" -- it accurately describes the current behavior. What is missing is branching logic to support alternative strategies. The key is better described as an "unimplemented extension point" or "single-value switch with no alternatives implemented."

Two valid paths forward:
1. Implement alternative strategies (e.g., `"full_text"`, `"semantic"`) and branch on the config value.
2. Remove the key from config if no alternatives are planned.

---

## Cross-Verification

| Source | Agrees with Analysis? |
|--------|----------------------|
| My direct code reading | Yes -- all 5 conclusions confirmed |
| Vibe-check metacognitive review | Yes -- flagged no errors, suggested minor precision improvements |
| Gemini 3 Pro (via pal clink, reading actual source files) | Yes -- independently confirmed all 5 findings with line number references |

---

## Attempted Disproofs (All Failed)

1. **Could `do_update()` restore a retired memory?** No -- merge protections block record_status changes (line 497-501).
2. **Could `do_unarchive()` restore a retired memory?** No -- it checks for `record_status == "archived"` specifically (line 1043).
3. **Does the anti-resurrection check appear outside do_create()?** No -- grep for 86400/resurrection confirms it is exclusively in do_create().
4. **Are any of the 8 keys read indirectly via a config loader?** No -- `load_config()` in triage only extracts `triage.*` keys. `memory_retrieve.py` only extracts `retrieval.enabled` and `retrieval.max_inject`.
5. **Does `memory_candidate.py` read config?** No -- zero matches for "config" in the file.
6. **Could `match_strategy` be enforced by code outside hooks/scripts/?** Out of scope -- the analysis is about script enforcement, and no scripts enforce it.

---

## Final Verdict

The analysis document at `temp/11-remaining-issues-analysis.md` is **accurate on all counts**. Its conclusions are well-founded and withstand skeptical scrutiny:

1. **Issue 1 (restore missing)**: REAL -- implement `--action restore`.
2. **Issue 2 (anti-resurrection)**: NOT REAL -- deliberate safety feature, create-path only.
3. **Issue 3 (agent-interpreted keys)**: NOT SYSTEMIC -- intentional architecture.
4. **Issues 3a/3b (archive_retired, match_strategy)**: Valid refinement opportunities, not evidence of architectural failure.

The analysis's meta-conclusion is also correct: the doc team's original framing of Issues 2 and 3 as "remaining implementation problems" was a pattern of recharacterizing working-as-designed features as deficiencies.
