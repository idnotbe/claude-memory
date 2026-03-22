# Operational Impact Verification -- Round 1

**Date**: 2026-03-22
**Reviewer**: Claude Opus 4.6 (1M context)
**Perspective**: Operational Impact
**Input Files**: `temp/log-review-retrieval-analysis.md`, `temp/log-review-triage-analysis.md`

---

## 1. Operational Impact Assessment Per Finding

### Finding: ZERO_LENGTH_PROMPT (Retrieval) -- Original Severity: CRITICAL

**Operational Impact: NONE (post-fix)**

The analysis conclusively demonstrates this is a pre-fix bug artifact from commit `e6592b1`. The evidence chain is airtight:
- All 4 zero-length skips have `duration_ms: null` (pre-fix code path signature)
- All 4 occurred in the 01:58-02:11 UTC window before the fix was applied
- Post-fix retrieval shows 100% inject rate for substantive prompts (68/68 non-trivial events)
- The fix (`hook_input.get("prompt") or hook_input.get("user_prompt") or ""`) is correct and complete

**User impact**: Zero. The bug was fixed the same day it was observed. No user-facing data loss occurred because the bug affected retrieval (injection of existing memories into context), not triage (capture of new memories). Existing memories were temporarily invisible during the ~40 minute pre-fix window, but were never lost.

**Verdict**: Confirmed false positive. No operational action needed on retrieval. The analyzer needs a minimum sample size guard (addressed in monitoring recommendations below).

---

### Finding: CONSTRAINT Never Triggers -- Original Severity: HIGH

**Operational Impact: MEDIUM-HIGH**

This is the most concerning finding from an operational perspective. The structural scoring math proves it:

| Parameter | Value |
|-----------|-------|
| Max score without booster | 0.4737 (3 primaries) |
| Threshold | 0.5000 |
| Gap | 0.0263 |
| Booster hits in 71 events | 0 |
| Result | **Mathematically impossible to trigger** |

**What this means for users**: The CONSTRAINT category is effectively disabled for the ops project. Any platform limitation, API restriction, or service boundary discovered during a session will NOT be auto-captured. The user must manually remember to save it.

**Actual data loss assessment**: The ops project has 6 constraints on disk. By examining their creation dates (Feb 22 - Mar 2), all were created during the plugin's earlier development phases or via manual intervention. Zero constraints have been auto-captured by the current triage system. During the analysis window (71 triage events from Mar 21), 17 events scored the maximum 0.4737 -- meaning the system detected constraint-like content 17 times but could never act on it.

**Silent failure risk**: HIGH. There is no user-visible signal that constraints are being missed. The triage hook runs, scores content, and silently discards it because 0.4737 < 0.5. No pending notification, no orphan artifact, no log warning. The user would only discover this by manually reviewing triage logs or running the analyzer.

**Compounding risk -- manual capture decay**: The 6 existing constraints provide a false sense of coverage. As the user increasingly trusts the plugin to "handle memory," manual constraint saves will decline. The gap between what should be captured and what is captured will widen over time without any visible indicator.

---

### Finding: DECISION Never Triggers -- Original Severity: HIGH

**Operational Impact: MEDIUM**

Unlike CONSTRAINT, the DECISION threshold (0.4) is mathematically reachable (3 primaries = 0.4737 > 0.4). The problem is domain-specific: ops conversations use implicit decision language ("using nginx", "deploying to us-east-1") rather than the explicit decision verbs the keyword set expects ("decided to use", "chose", "went with").

**What this means for users**: Architectural decisions made during ops sessions are not auto-captured. The 11 existing decisions (adr001-adr011) were all manually created with an ADR naming convention, confirming they were intentional manual saves, not auto-captures.

**Actual data loss assessment**: MODERATE. The user has established a manual ADR workflow that partially compensates. However, not all decisions warrant a formal ADR. Smaller technical decisions (e.g., choosing a specific configuration approach, selecting between two deployment strategies) may be lost because they fall below the user's "worth writing an ADR" threshold but above the "worth remembering" threshold.

**Silent failure risk**: MEDIUM. The manual ADR habit provides a safety net for major decisions, but creates a coverage gap for mid-tier decisions.

---

### Finding: PREFERENCE Never Triggers -- Original Severity: HIGH

**Operational Impact: LOW-MEDIUM**

Only 9/71 events had any preference signal at all, with a maximum of 2 primary matches (score 0.3415). This is largely expected behavior for an ops project -- infrastructure work generates fewer coding style or workflow preferences than application development.

**What this means for users**: Workflow conventions and tool preferences are not auto-captured. The 3 existing preferences were manually created.

**Actual data loss assessment**: LOW. The ops project's preference needs are modest and largely satisfied by the 3 existing entries. Infrastructure projects tend to have stable, well-known conventions that don't change frequently.

**Silent failure risk**: LOW. The low signal density (12.7% of events had any preference signal) suggests there genuinely isn't much preference-worthy content to capture.

---

## 2. Feasibility Assessment of Recommendations

### Tier 1: Per-Project Config Tuning -- FEASIBLE, RECOMMENDED IMMEDIATELY

The ops project's `memory-config.json` already has a `triage.thresholds` section with per-category overrides. Adding lower thresholds for the 3 broken categories requires a single config file edit with zero code changes.

**Assessment**: This is the right first step. Low risk, immediately actionable, no regression risk to other projects.

**However**: For CONSTRAINT specifically, lowering the threshold alone (to 0.45) would trigger on 17/71 events, 58.8% of which overlap with RUNBOOK. This will produce noise. The analysis correctly identifies that CONSTRAINT needs keyword refinement alongside threshold tuning.

**Recommended immediate action**: Lower DECISION to 0.35 and PREFERENCE to 0.35 in the ops config. Hold CONSTRAINT at 0.5 until keyword refinement is done.

### Tier 2: Keyword Improvements -- FEASIBLE, MODERATE EFFORT

Expanding the keyword sets in `memory_triage.py` is a code change that affects all projects. The proposed additions are reasonable:
- CONSTRAINT: demoting bare `cannot`, adding `does not support`, `limited to`, `hard limit`, etc.
- PREFERENCE: adding `standard`, `always`, `formatting`, etc.

**Assessment**: Sound approach. The keyword changes should be validated by replaying existing triage logs through the updated scoring to measure the false positive impact before merging.

**Risk**: Keyword changes are global. A word that reduces false positives in ops may increase them in frontend/app development projects. The Tier 4 validation requirement (50+ labeled events from 3+ project types) is essential.

### Tier 3: Default Threshold Adjustment -- FEASIBLE, REQUIRES DATA

Changing the default thresholds in `memory_triage.py` or `assets/memory-config.default.json` affects every new project. The proposed changes (CONSTRAINT: 0.50->0.47, DECISION: 0.40->0.35, PREFERENCE: 0.40->0.35) are conservative.

**Assessment**: Premature without broader data. One day from one project is insufficient for global defaults. The tiered approach correctly defers this to Tier 3.

### Tier 4: Validation Requirement -- ESSENTIAL

The requirement for 3+ project types and 50+ labeled events with 70%+ precision is well-calibrated. Without this, any global change is speculative.

**Assessment**: This should be a hard gate, not a soft recommendation.

### Overall Tiering Assessment

The tiered approach is operationally sound with one caveat: the CONSTRAINT structural bug (threshold > max-without-booster) should be treated as a bug fix, not a tuning exercise. The math is unambiguous -- a category that cannot trigger regardless of input is broken by definition. The CONSTRAINT threshold should be lowered to at most 0.4737 in the global defaults immediately, with further tuning deferred to Tier 3. This is distinct from the DECISION and PREFERENCE issues, which are genuine domain-sensitivity questions.

---

## 3. Regression Risk Assessment

### Could proposed fixes break SESSION_SUMMARY, RUNBOOK, TECH_DEBT?

**SESSION_SUMMARY**: NO RISK. The proposed changes do not touch SESSION_SUMMARY's threshold (0.6) or keywords. Its 98.6% trigger rate is robust.

**RUNBOOK**: LOW RISK. The CONSTRAINT keyword refinement (demoting `cannot`, adding more specific constraint phrases) may slightly reduce the 58.8% CONSTRAINT/RUNBOOK overlap, which is actually desirable -- it means fewer dual-trigger events, not fewer RUNBOOK triggers. RUNBOOK has its own distinct keyword set and a healthy 18.3% trigger rate.

**TECH_DEBT**: NO RISK. The proposed changes do not touch TECH_DEBT's threshold or keywords. Its 8.5% trigger rate is stable.

**Cross-category interaction**: The scoring system evaluates all 6 categories independently. Changing thresholds for CONSTRAINT/DECISION/PREFERENCE does not alter the scores computed for other categories. The only interaction is if keyword changes cause a word to be reclassified between categories, but the proposed changes add new terms rather than moving existing ones.

**Overall regression risk**: LOW. The changes are additive (new keywords, lower thresholds) and category-independent.

---

## 4. Additional Monitoring Recommendations

### Current State

The log analyzer (`memory_log_analyzer.py`) processes JSONL logs and produces severity-rated findings. It correctly identified the 3 dead categories but also produced a false positive CRITICAL for the retrieval pre-fix artifact.

### Recommended Additions

#### 4.1 Minimum Sample Size Guard (Priority: HIGH)

All percentage-based detectors should require a minimum event count before firing:
- `_detect_skip_rate_high`: require N >= 20 skip events before computing skip percentage
- `_detect_zero_length_prompt`: require N >= 10 skip events before computing zero-length percentage
- `_detect_category_never_triggers`: require N >= 30 triage.score events before flagging

**Rationale**: The N=4 false positive CRITICAL demonstrates that small samples produce unreliable percentages.

#### 4.2 Deploy Boundary Awareness (Priority: MEDIUM)

Add `plugin_version` to the JSONL event schema (read from `.claude-plugin/plugin.json`). The analyzer should partition metrics by version to prevent mixed-version artifacts from producing false positives.

**Implementation**: Add `plugin_version` field to `emit_event` in `memory_logger.py`. Add `--since` or `--version` CLI flag to the analyzer for post-incident filtering.

#### 4.3 Threshold Margin Alert (Priority: MEDIUM)

Add a detector that fires when `max_observed_score` for a category is within 0.05 of the threshold but never exceeds it over a sustained period (e.g., 50+ events). This would have caught the CONSTRAINT structural gap proactively.

**Alert text**: "CONSTRAINT: max score 0.4737 is within 0.0263 of threshold 0.5 but never triggers. Possible threshold misalignment."

#### 4.4 Auto vs Manual Capture Gap (Priority: MEDIUM)

Track whether categories have manually-created memories but zero auto-captures. This indicates the auto-capture system is failing for that category while the user compensates manually.

**Implementation**: Compare `memory_write` events (source=triage vs source=manual) per category. Alert if manual writes exist but auto-triage triggers are zero.

#### 4.5 End-to-End Capture Conversion (Priority: LOW)

Track the full pipeline: triage trigger -> draft -> verification -> save. Drop-off at any stage indicates a different failure mode. Currently, only triage scores are logged; the downstream phases lack structured logging.

#### 4.6 Session-Based Windowing (Priority: LOW)

Replace day-based analysis windows with session-count-based windows. A project with 2 sessions/day and a project with 20 sessions/day should not use the same day-count threshold.

#### 4.7 SQLite Metrics Rollup (Priority: LOW)

For historical trending and cross-project aggregation, add a lightweight SQLite rollup that stores daily summary statistics. This enables day-over-day comparisons without reparsing JSONL on every analyzer run.

---

## 5. Cross-Model Opinions

### Codex (OpenAI) -- Operational Risk Assessment

**Verdict**: Medium operational risk, medium-high silent loss risk.

Key contributions:
- Confirmed the silent failure mechanism: categories that never trigger produce no staging artifacts, so the orphan/pending notification system never fires. This means missed content disappears with no user-visible signal.
- Recommended fixing DECISION and PREFERENCE locally first, holding CONSTRAINT for keyword cleanup.
- Identified a nuance missed in the analysis: the `memory_retrieve.py` recovery path only fires if `triage-data.json` or `.triage-pending.json` exists, which never happens for categories that score below threshold.
- Proposed 5 additional monitoring metrics: rolling dead-category alerts, threshold-margin checks, booster-hit-rate metrics, manual-vs-auto capture gap, and end-to-end conversion tracking.

**Agreement level**: Strong agreement with my assessment. Codex validated the medium risk level and independently arrived at the same "fix DECISION+PREFERENCE now, defer CONSTRAINT" prioritization.

### Gemini (Google) -- Monitoring Recommendations

**Verdict**: Fix analyzer noise first, then add structured monitoring.

Key contributions:
- Proposed minimum volume gates with specific threshold: `if total_events < 20: return None` for percentage-based detectors.
- Recommended injecting `plugin_version` into the JSONL schema for deploy boundary partitioning.
- Suggested session-based alerting instead of day-based: track against `triage.score` events (actual user activity) rather than calendar days.
- Proposed a SQLite metrics rollup for historical trending without reparsing JSONL.
- Defined healthy vs degraded indicators: triage capture rate 5-15% of sessions, drafting completion >90%, retrieval duration P95 <100ms.
- Introduced "category entropy" metric: if 99% of captures are SESSION_SUMMARY, extraction diversity is degraded.

**Agreement level**: Strong agreement on monitoring gaps. Gemini's session-based windowing recommendation is particularly valuable -- day-based analysis conflates inactive days with failed detection.

### Consensus Across All Models (Opus, Codex, Gemini)

All three models agree on:
1. **Retrieval finding is a false positive** -- no operational action needed
2. **CONSTRAINT has a structural bug** -- the math is unambiguous
3. **Per-project tuning is the correct first step** -- global changes need more data
4. **The analyzer needs a minimum sample size guard** -- percentage-based alerting on small samples is unreliable
5. **Monitoring should be expanded** -- current analyzer is necessary but insufficient

The models diverge on:
- **CONSTRAINT fix urgency**: I and Codex treat the threshold > max-without-booster gap as a bug that warrants an immediate default fix (to at most 0.4737). The original triage analysis noted Gemini's position that this is intentional design. The math resolves this: regardless of design intent, a gate that never opens is a broken gate.
- **Monitoring complexity**: Gemini recommends SQLite rollup and cross-project aggregation; Codex focuses on per-project alerting. Both are valid at different maturity stages.

---

## 6. Overall Verdict

### PASS_WITH_NOTES

**Rationale**: Both analyses are thorough, well-evidenced, and reach sound conclusions. The retrieval analysis correctly identifies and dismisses a false positive with strong corroborating evidence. The triage analysis correctly diagnoses the structural scoring gap in CONSTRAINT and the domain-sensitivity issues in DECISION/PREFERENCE. The tiered recommendation approach is operationally appropriate.

**Notes requiring attention before acting on recommendations**:

1. **CONSTRAINT should be treated as a bug fix, not a tuning exercise.** The structural gap (threshold 0.5 > max-without-booster 0.4737) should be fixed in the global defaults immediately (lower to 0.47 at minimum). This is mathematically proven to be broken regardless of project type. The keyword cleanup is a separate, additive improvement.

2. **The "manual capture compensates" assumption has a shelf life.** The 6 constraints and 11 decisions exist because the user has strong manual habits. As plugin trust grows, manual saves will decline. The analysis should explicitly call out that the current risk level is MEDIUM only because of active manual compensation, and will degrade to HIGH if auto-capture remains broken and manual habits fade.

3. **The analyzer minimum sample size fix should be implemented before any threshold changes.** Without it, lowering thresholds will increase trigger counts and potentially produce new false positives from the analyzer, creating noise during the validation period.

4. **Add booster-hit-rate as a first-class metric.** The fact that CONSTRAINT and PREFERENCE boosters NEVER fired in 71 events is a powerful diagnostic signal that the current analyzer does not track. A "booster effectiveness" metric would catch vocabulary misalignment early.

5. **Session-based windowing should replace day-based windowing.** This was a consensus recommendation from Gemini and independently validated by the data -- the ops project's activity varies significantly by day, making day-based thresholds unreliable.
