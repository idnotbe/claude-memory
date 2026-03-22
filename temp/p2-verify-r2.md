# P2 Verification Round 2: Bias, Edge Cases, Memory Quality

**Date**: 2026-03-22
**Verifier**: Claude Opus 4.6 (1M context)
**Scope**: Per-project ops threshold tuning (DECISION 0.4->0.26, PREFERENCE 0.4->0.34)

---

## 1. Bias Assessment

### Circular Reasoning: CONFIRMED

The threshold 0.26 was chosen specifically to capture all events at the 0.2632 score quantum. This is textbook overfitting to observed data:

- **The question asked**: "What threshold captures decisions worth remembering?"
- **The question answered**: "What threshold captures all events we observed?"

These are different questions. The analysis never validated whether the 9 events at 0.2632 contain genuine decisions -- it only validated that the threshold captures the right *count*.

### Score Fingerprint Homogeneity: RED FLAG

All 9 newly triggered DECISION events share nearly identical multi-category score fingerprints:

| Pattern | Count | Fingerprint |
|---------|-------|-------------|
| A | 7/9 | DECISION=0.2632, RUNBOOK=0.6667, CONSTRAINT=0.4737, TECH_DEBT=0.1579 |
| B | 2/9 | DECISION=0.2632, RUNBOOK=0.6667, CONSTRAINT=0.4737, TECH_DEBT=0.4737 |

This means ALL 9 events come from conversations with the same heuristic signature. They are not 9 independent data points -- they likely represent one or two recurring conversational patterns. The threshold is not being tested against diverse decision scenarios; it is being tested against a single pattern archetype.

Additionally, every DECISION event co-triggers RUNBOOK (score 0.6667, well above its 0.4 threshold). This strongly suggests these are **troubleshooting/error-fixing conversations** where someone incidentally used a decision keyword (e.g., "decided to...") near a rationale booster (e.g., "because..."). These are most likely operational fix descriptions, not architectural or technical decisions.

### Session Concentration

The 9 events span 5 sessions, but one session (b0d315e1) accounts for 4 of them (44%). This further reduces the effective sample diversity.

### Noise Risk at 0.26

A score of 0.2632 represents the **absolute minimum boosted signal**: exactly 1 primary keyword match + 1 booster keyword within 4 lines, in an entire conversation of 50 exchanges (~17K chars). This is extremely sparse signal density.

Example: A conversation about fixing a deployment error where someone writes "I decided to restart the service because the process was stuck" would score 0.2632 for DECISION (boosted match on "decided" + "because"), 0.6667+ for RUNBOOK (multiple error/fix keywords), and the system would attempt to create a decision memory from what is actually a routine operational action.

---

## 2. Edge Case Findings

### Config Override Mechanism

From `memory_triage.py` line 564-619, the config loading works as follows:

1. Start with hardcoded defaults (`DEFAULT_THRESHOLDS` = 0.4 for DECISION)
2. Load `{cwd}/.claude/memory/memory-config.json`
3. Per-category threshold from config **replaces** the default (not merge/overlay)
4. Values are clamped to `[0.0, 1.0]` via `max(0.0, min(1.0, val))`
5. NaN and Inf are rejected

**Per-project override takes precedence** -- there is no global config merge. The script reads only the project-local `memory-config.json`. If the global default config (`assets/memory-config.default.json`) changes, it has no effect on projects with their own config files. This is correct behavior but means per-project configs can silently diverge from global defaults.

### Threshold = 0.0

`max(0.0, min(1.0, 0.0))` = 0.0. Since `score >= 0.0` is always true (scores range [0.0, 1.0]), threshold=0.0 would trigger the category on **every single triage event**, including those with zero keyword matches. This is a usability hazard but not a security issue -- there is no minimum threshold floor enforced beyond the clamp.

**Recommendation**: Consider adding a minimum threshold floor (e.g., 0.05) to prevent accidental universal triggers.

### Threshold < 0

Negative values are clamped to 0.0 by `max(0.0, ...)`. Same effect as threshold=0.0.

### Threshold > 1.0

Clamped to 1.0 by `min(1.0, ...)`. Only a perfect score of 1.0 would trigger.

### Global Default Change Impact

If the plugin's `DEFAULT_THRESHOLDS` constant changes in a future version, projects with per-project configs are unaffected (per-project values override defaults). Projects without per-project configs would pick up the new defaults. This is standard override behavior.

---

## 3. Memory Quality Prediction

### Signal Strength Analysis

DECISION score 0.2632 = 1 boosted match (0.5 / 1.9):
- **1 primary keyword** (e.g., "decided", "chose", "went with")
- **1 booster keyword** within 4 lines (e.g., "because", "reason", "instead of")
- In a conversation of ~50 exchanges, ~17,000 characters

This is the **weakest possible boosted signal**. The drafter subagent receives approximately 20 lines of context around this single match (CONTEXT_WINDOW_LINES = 10, so +/- 10 lines).

### Schema Requirement Gap

The DECISION content schema requires: `status`, `context`, `decision`, `rationale` (mandatory). `alternatives` and `consequences` are **optional** (confirmed in both `decision.schema.json` line 41 and `memory_write.py` line 96: `alternatives: Optional[list[Alternative]] = None`).

This means a low-signal capture can pass schema validation with just a context statement, a decision statement, and a single rationale bullet. The schema provides no quality gate against thin memories.

### Drafter Context Limitations

The memory-drafter agent receives:
- ~20 lines of transcript context around the keyword match
- Category description text
- No full conversation context

From 20 lines of an error-fixing conversation, the drafter can plausibly extract:
- A decision statement ("Decided to restart the service")
- A rationale ("The process was stuck")
- A context ("Service X was unresponsive during deployment")

But it **cannot reliably infer**:
- Alternatives considered (what else could have been done?)
- Long-term consequences (was this a one-time fix or a pattern?)
- Whether this is a durable decision or an ephemeral operational action

### Precision Estimate

Based on:
- Minimum possible boosted signal strength
- 100% co-trigger overlap with RUNBOOK (troubleshooting conversations)
- Identical score fingerprints suggesting one conversation pattern
- Optional alternatives/consequences fields allowing thin memories

**Estimated precision: 25-35%** (2-3 of the 9 events likely contain genuine, durable decisions). This is well below the implementation report's 70% success target and at or below the 50% revert threshold.

---

## 4. Experiment Design Recommendations

### Issues with Current Design

1. **"200 events" is ambiguous**: 200 total triage events (of which ~25 would be DECISION triggers) vs. 200 DECISION captures. The margin of error differs dramatically: +/-8% for 126 captures vs. +/-18% for 25 captures.

2. **Precision measurement is undefined**: "memory-worthy" has no operational definition. Who judges? When? Manual review or automated?

3. **No early stopping rule**: Bad memories compound. If the system ingests 30 low-quality decision memories, retrieval quality degrades, which degrades future memory evaluations.

4. **Systematic bias from fingerprint homogeneity**: Evaluating threshold quality on a sample where 100% of triggers share the same heuristic signature means you are evaluating one pattern, not the threshold's general effectiveness.

5. **No silent failure detection mechanism**: False-positive memories enter retrieval without observable breakage.

### Recommended Improvements

| Issue | Recommendation |
|-------|---------------|
| Sample size | Change stopping condition to **50 DECISION captures** (not 200 total events) |
| Precision measurement | Daily manual binary grading (decision-worthy: yes/no) for the 2-week window |
| Early stopping | Revert if precision < 40% after 20 captures, or duplication rate > 30% |
| Additional metrics | Track: retrieval hit rate, user deletion rate, near-duplicate rate |
| False positive detection | Consider shadow mode: log candidate memories to a separate file without injecting into active retrieval |
| Recall estimation | Sample 10% of rejected events (scores < 0.26) for manual review to check false negatives |

---

## 5. Cross-Model Opinions

### Codex

**Verdict**: Estimated precision ~30% (center estimate), recommends a minimum signal diversity gate.

Key findings:
- Confirmed that 0.2632 is the weakest possible boosted signal
- The drafter gets only ~20 lines of local context, sufficient for restating a choice but not for reliably inferring alternatives or impact
- The fingerprint homogeneity + RUNBOOK co-triggering strongly suggests routine troubleshooting, not durable decisions
- The schema's optional `alternatives` and `consequences` fields mean weak captures can pass validation
- Recommends: require 2+ distinct primary-hit lines for DECISION, or a hybrid rule allowing 1 boosted hit only when explicit contrast language ("over", "instead of", "rather than") is present and RUNBOOK is not the dominant co-trigger
- Keep 0.26 experimental only; manually label the 9 captures before committing

### Gemini

**Verdict**: The identical fingerprint anomaly is the biggest red flag. You are testing one heuristic combination, not a threshold.

Key findings:
- 126 DECISION captures over 2 weeks gives +/-8% margin of error -- statistically sufficient if counting captures, not events
- Precision should be measured via daily manual binary grading (gold standard for this volume)
- Must track retrieval hit rate and user deletion rate alongside precision
- Recommends shadow mode for false positive detection -- log candidate memories separately without injecting into active retrieval
- A/B testing is infeasible for single-user CLI; before/after is acceptable but annotate project phase
- Early stopping: revert if precision < 40% after 20 captures or duplication > 30%
- The `RUNBOOK+CONSTRAINT` co-trigger pattern may be worth a dedicated rule rather than lowering the generic DECISION threshold

### Cross-Model Consensus

Both models independently identified:
1. The fingerprint homogeneity as a fundamental evaluation flaw
2. The signal strength as insufficient for reliable alternative/impact inference
3. Estimated precision well below the 70% success target
4. The need for early stopping rules and additional quality metrics

---

## 6. Overall Assessment: PASS_WITH_NOTES

### Rationale

The implementation is **technically correct** -- the config change is valid JSON, the values are properly clamped, the per-project override mechanism works as designed, and the change is fully reversible. The implementation report accurately counts trigger deltas.

However, the **analytical foundation has significant gaps**:

1. **Circular reasoning** in threshold selection (optimized for capture count, not capture quality)
2. **Fingerprint homogeneity** means the experiment evaluates one conversation pattern, not the threshold's general effectiveness
3. **Estimated precision (~30%)** is well below both the 70% success target and the 50% revert threshold
4. **Missing experiment controls**: no early stopping, no precision measurement protocol, no shadow mode

### Conditions for Full PASS

The experiment may proceed as-is (it is reversible and low-risk), but should be upgraded with:

1. **Early stopping rule**: Revert if precision < 40% after 20 DECISION captures
2. **Manual precision tracking**: Binary-grade each captured decision memory daily
3. **Investigate the fingerprint**: Before drawing conclusions from the experiment, determine what actual conversations produce the 0.2632 DECISION + 0.6667 RUNBOOK pattern. If they are all troubleshooting conversations, the threshold change is capturing the wrong signal and should be reverted regardless of count.
4. **Consider a diversity gate**: Rather than lowering the threshold, consider requiring 2+ distinct primary matches for DECISION to trigger -- this would filter out incidental keyword usage in non-decision conversations.
