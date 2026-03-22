# P2 Implementation Report: Per-Project Ops Threshold Tuning

**Date**: 2026-03-22
**Status**: DONE
**Reversibility**: Full (revert to 0.4/0.4)

---

## Changes Made

**File**: `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`

```diff
 "thresholds": {
-  "decision": 0.4,
+  "decision": 0.26,
   "runbook": 0.4,
   "constraint": 0.5,
   "tech_debt": 0.4,
-  "preference": 0.4,
+  "preference": 0.34,
   "session_summary": 0.6
 }
```

---

## JSON Validation

**Result**: PASSED

- Valid JSON after edit
- 2-space indent preserved
- Trailing newline preserved
- No trailing whitespace on any lines
- Only one `memory-config.json` in the ops project (no duplicates)
- Global default config (`assets/memory-config.default.json`) unchanged at 0.4/0.4

---

## Functional Verification

**Data source**: `/home/idnotbe/projects/ops/.claude/memory/logs/triage/2026-03-21.jsonl` (71 events)

### Trigger Counts: Old vs New Thresholds

| Category | Old Threshold | New Threshold | Old Triggers | New Triggers | Delta | Status |
|----------|--------------|--------------|-------------|-------------|-------|--------|
| SESSION_SUMMARY | 0.6 | 0.6 | 70/71 | 70/71 | 0 | Unchanged |
| DECISION | 0.4 | **0.26** | 0/71 | **9/71** | **+9** | As expected |
| RUNBOOK | 0.4 | 0.4 | 13/71 | 13/71 | 0 | Unchanged |
| CONSTRAINT | 0.5 | 0.5 | 0/71 | 0/71 | 0 | Unchanged |
| TECH_DEBT | 0.4 | 0.4 | 6/71 | 6/71 | 0 | Unchanged |
| PREFERENCE | 0.4 | **0.34** | 0/71 | **1/71** | **+1** | As expected |

### Score Distributions for Changed Categories

**DECISION** (12 non-zero events):
- 0.1579: 3 events (below both thresholds)
- 0.2632: 9 events (newly triggered at 0.26, was below 0.4)

**PREFERENCE** (9 non-zero events):
- 0.1707: 8 events (below both thresholds)
- 0.3415: 1 event (newly triggered at 0.34, was below 0.4)

### Note on Expected Count

The task predicted "~12" DECISION triggers based on the analysis report's count of non-zero events. The actual newly triggered count is 9 -- the 3 events at 0.1579 (1 primary, no boost) remain correctly below the 0.26 threshold. The 9 triggered events are all at 0.2632 (1 boosted match pattern), which is the intended capture target.

---

## Cross-Model Opinions

### Codex (via clink)

**Verdict**: Keep 0.26 and 0.34.

Key findings:
- Verified that `>= 0.26` and `>= 0.25` both produce 9/71 DECISION triggers (no score quanta between them)
- Verified that `>= 0.34` and `>= 0.33` both produce 1/71 PREFERENCE triggers (same reason)
- Floating point is a non-issue: the raw scores (e.g., 0.263157...) are well above the thresholds
- The main float risk would be using the *rounded log values* (0.2632, 0.3415) as thresholds -- those could miss. 0.26 and 0.34 are safely below.
- Experiment magnitude (+12.7% DECISION, +1.4% PREFERENCE) is reasonable for a reversible per-project trial
- Recommends review after 200+ events or 2 weeks

### Gemini (via clink)

**Verdict**: Use wider margins -- 0.22 for DECISION, 0.30 for PREFERENCE.

Key argument:
- Thresholds should be midpoints between adjacent score quanta for upstream resilience
- If plugin weights change (e.g., boosted_weight 0.5 -> 0.6), the quanta shift and tight thresholds could silently break
- DECISION optimal: 0.22 (midpoint between 0.1579 and 0.2632)
- PREFERENCE optimal: 0.30 (midpoint between 0.2439 and 0.3415)
- Floating point precision is NOT an issue (IEEE 754 has ~1e-16 precision)

### Synthesis

Both models agree that:
1. The current 0.26/0.34 values are mathematically correct for today's code
2. Floating point is not a concern
3. The trigger counts match expectations

They disagree on margin sizing. Gemini's midpoint approach is academically sound but adds no practical value here because:
- The score space is quantized (no scores exist between adjacent quanta)
- Any threshold between 0.1579 and 0.2632 captures the same events
- The plugin developer (us) controls upstream weight changes
- This is a reversible experiment, not a permanent setting

**Decision**: Keep 0.26/0.34 as implemented. The tight-to-quantum values make the intent self-documenting.

---

## Self-Check Results

### Could this change cause regressions?

**No.** Analysis:
- Per-project config only; global defaults unchanged
- Only DECISION and PREFERENCE thresholds modified; all other categories verified unaffected
- The change ADDS triggers (more permissive), never removes existing ones
- Worst case: some false-positive memory captures that can be manually cleaned

### Are there other config files referencing these thresholds?

**No.** Verified:
- Only one `memory-config.json` in the ops project
- Plugin default config (`assets/memory-config.default.json`) is separate and unchanged
- Thresholds are read at runtime by `memory_triage.py` from the project config only

### Is JSON formatting consistent?

**Yes.** Verified:
- 2-space indentation preserved
- Trailing newline preserved
- No trailing whitespace
- Valid JSON (parsed successfully)

---

## Review Checkpoint

Recommended review after:
- 200+ triage events, OR
- 2 weeks (2026-04-05)

Review criteria:
- How many DECISION/PREFERENCE triggers occurred?
- What fraction were true positives (actually memory-worthy)?
- Target precision >= 70% to keep thresholds; revert if below 50%

---

## Overall Status: DONE
