# Log Review: 2026-03-22

## Summary

| Item | Value |
|------|-------|
| Review Date | 2026-03-22 |
| Analysis Period | 2026-03-21 ~ 2026-03-22 |
| Target Project | ops |
| Total Events | 144 (triage: 71, retrieval: 73) |
| Critical | 1 (downgraded to INFO — false positive) |
| High | 3 (1 confirmed, 2 underdetermined) |
| Medium | 0 |
| Low | 0 |
| Generated Action Plans | `plan-fix-analyzer-validity.md`, `plan-fix-constraint-threshold.md` |

## Methodology

- **Analysis pipeline**: 7 agents total (2 deep-dive + 3 R1 verification + 2 R2 verification)
- **Perspectives covered**: correctness/math, operational impact, security, cross-cutting synthesis, bias/false-positive detection
- **Cross-model verification**: Codex CLI (codex 5.3) + Gemini CLI (gemini 3.1 pro) at each stage
- **Bias corrections applied**: echo chamber detection, sample size validation, confidence recalibration

## Findings

### Finding 1: ZERO_LENGTH_PROMPT (Analyzer: CRITICAL -> Assessed: INFO)

**Status: FALSE POSITIVE — pre-fix artifact**

80% of retrieval.skip events (4/5) had prompt_length=0. Investigation confirmed these are artifacts of a known bug fixed in commit `e6592b1` on the same day. The bug: `hook_input.get("user_prompt", "")` read the wrong field name; Claude Code sends `"prompt"`.

**Evidence (deterministic, not statistical)**:
- All 4 zero-length events have `duration_ms: null` (pre-fix code path); the 1 post-fix skip has `duration_ms: 0.63`
- All 4 occurred between 01:58-02:11 UTC, before the fix commit at 03:00 UTC
- Post-fix logs (2026-03-22.jsonl) contain zero zero-length events
- 3 of 4 events are from the same session (effective N=2 sessions, not 4 events)

**Cross-model consensus**: All 3 models (opus, codex, gemini) agree this is a false positive.

**Action**: No code fix needed (already fixed). Analyzer improvement needed (see Finding 5).

### Finding 2: CONSTRAINT Never Triggers (Analyzer: HIGH -> Assessed: HIGH, CONFIRMED)

**Status: Structurally unreachable threshold — design intent unresolved**

CONSTRAINT threshold (0.5) exceeds the maximum achievable score without booster co-occurrence (0.4737). This is a mathematical fact: `3 * 0.3 / 1.9 = 0.4737 < 0.5`. Booster keywords never fired in 71 events.

**Important nuance**: The README documents "Limitation keywords + discovery co-occurrence" and "Higher values = fewer but higher-confidence captures," which is consistent with intentional precision gating. Whether the 0.0263 gap is a calibration bug or an intentional booster requirement is **unresolved without design-intent evidence**.

**What IS clear**: Regardless of intent, a category that never triggers in practice (0 triggers across 71 events with 53.5% non-zero scores) needs attention — either the booster vocabulary needs expansion so the precision gate can actually open, or the threshold needs adjustment.

**Cross-model divergence**: Codex says "precision gate — tune boosters, not threshold." Gemini says "structurally broken — fix threshold." Both agree the fix must be atomic (threshold + keyword cleanup in one PR).

**Action**: `plan-fix-constraint-threshold.md`

### Finding 3: DECISION Never Triggers (Analyzer: HIGH -> Assessed: UNDERDETERMINED)

**Status: Insufficient data to classify**

Max observed score: 0.2632 (1 boosted match) vs threshold 0.4. The keyword set may be too narrow for ops domain (explicit decision verbs vs implicit ops decisions), but this cannot be confirmed because:
- N=71 from 1 project on 1 day is insufficient (Rule of Three: 95% CI upper bound is only 4.2%)
- Commit `e6592b1` expanded DECISION keywords (+9 phrases) mid-analysis-window, confounding the data
- No labeled ground truth exists — "never triggers" could be correct if no memory-worthy decisions occurred

**Action**: Per-project ops tuning as reversible experiment (DECISION threshold -> 0.26 to capture observed boosted pattern). Re-evaluate after accumulating post-fix data.

### Finding 4: PREFERENCE Never Triggers (Analyzer: HIGH -> Assessed: UNDERDETERMINED)

**Status: Likely expected behavior for ops domain, insufficient data to confirm**

Max observed score: 0.3415 (2 primaries, observed once) vs threshold 0.4. Preference keywords ("always use", "prefer", "convention") appear infrequently in infrastructure work.

Same data limitations as Finding 3 apply.

**Action**: Per-project ops tuning as reversible experiment (PREFERENCE threshold -> 0.34). Re-evaluate after data accumulation.

### Finding 5: Analyzer Validity Gaps (Newly identified during review)

The analyzer has systematic issues that produced/amplified the findings above:

- **No minimum sample size**: Percentage-based alerts fire on N=1 (e.g., 1 skip event with prompt_length=0 = 100% = CRITICAL)
- **No version/deploy boundary awareness**: Pre-fix and post-fix events are mixed in the same analysis window
- **No snapshot discipline**: Log files are live/mutable during analysis (count discrepancy: analysis says 73, actual grew to 75+)
- **No booster-hit-rate monitoring**: Zero booster hits across 38 non-zero CONSTRAINT events was not flagged

**Action**: `plan-fix-analyzer-validity.md`

## Additional Observations (Not Actionable Now)

These were identified during verification but are not urgent enough for action plans:

1. **SESSION_SUMMARY opening excerpt**: Uses `lines[:80]` from tail-50 window, not true session start. Misleading context for long sessions.
2. **Short-prompt retrieval bypass**: `len < 10` threshold skips constraint injection for prompts like "delete" (6 chars). Design tradeoff, not a vulnerability.
3. **No max-categories guardrail**: All 6 categories can trigger simultaneously, spawning 12+ subagents. UX/cost concern.
4. **Long-conversation blind spot**: Tail-50 window loses early-session discoveries. Known design tradeoff.

These should be tracked in backlog and revisited during future reviews.

## Action Plans Generated

### `plan-fix-analyzer-validity.md` (P0 — Highest Priority)

Implement analysis validity guards in `memory_log_analyzer.py`:
- Minimum sample size (N >= 10 for skip-rate checks, N >= 30 for category checks)
- Frozen snapshot with cutoff timestamp / hash
- Version/change-point boundary detection
- Booster-hit-rate as first-class metric

### `plan-fix-constraint-threshold.md` (P1 — High Priority)

Atomic CONSTRAINT fix (single PR):
- Intent decision: Is booster-gating intentional for CONSTRAINT? (Check design history)
- If relaxing: Lower threshold to 0.47 + demote bare `cannot` from primary + add ops-relevant primaries
- If keeping booster gate: Expand booster vocabulary for ops domain
- Update README/docs to reflect the decision
- Add boundary regression tests at score quanta (0.4737, 0.5)

### Per-project ops tuning (P2 — APPLIED 2026-03-22)

Updated `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`:
- `triage.thresholds.decision`: 0.4 → 0.26
- `triage.thresholds.preference`: 0.4 → 0.34

**Functional verification results** (against 71 historical triage events):
- DECISION: +9 triggers (all at score quantum 0.2632 — 1 boosted match)
- PREFERENCE: +1 trigger (at score quantum 0.3415 — 2 primaries)
- Other categories: zero delta

**Quality concern from V-R2**: All 9 DECISION triggers share identical multi-category fingerprints and co-trigger RUNBOOK (0.6667). Estimated precision ~25-35%. These may be troubleshooting conversations with incidental decision keywords, not genuine architectural decisions.

**Experiment guardrails**:
- Early stopping: revert DECISION to 0.4 if precision < 40% after 20 captures
- Re-review: 2026-04-05, or after 50 DECISION captures, whichever comes first
- Rollback: restore `decision: 0.4, preference: 0.4` — no restart needed
- Monitor: DECISION memory count accumulation (no `max_retained` cap unlike SESSION_SUMMARY)

## Verification Summary

| Round | Agent | Verdict |
|-------|-------|---------|
| R1 | Correctness | PASS_WITH_NOTES (threshold calc errors in recommendations) |
| R1 | Operational | PASS_WITH_NOTES (CONSTRAINT is global bug, not per-project) |
| R1 | Security | PASS_WITH_NOTES (short-prompt bypass, config trust model) |
| R2 | Synthesis | CONFIRMED with corrections (atomic fix, threshold recalibration) |
| R2 | Bias Detection | NEEDS_REVISION (echo chamber, overconfidence, confounded data) |
| Final | Opus + Codex + Gemini | Synthesis balanced, 3 action items correctly scoped |
| P2-R1 | Correctness + Safety + Ops | PASS (values correct, `>=` comparison safe, reversible) |
| P2-R2 | Bias + Edge Cases + Quality | PASS_WITH_NOTES (fingerprint homogeneity, precision ~30%, early stopping needed) |

## Cross-Model Consensus Summary

**All 3 models agree on**:
- ZERO_LENGTH_PROMPT is a false positive
- CONSTRAINT threshold math is a deterministic fact (0.4737 < 0.5)
- N=71 from 1 project is insufficient for global default changes
- Per-project tuning is the right immediate step
- Analyzer needs validity guards

**Models disagree on**:
- Whether CONSTRAINT threshold is a "bug" (gemini) or "intentional precision gate" (codex) — resolved as "needs explicit design-intent decision"
- DECISION optimal threshold: 0.26 (codex, data-driven) vs 0.40 (gemini, quality-driven) — resolved as "0.26 per-project, 0.40 global"

## Previous Reviews

None (first log review for ops project).

## Next Review

Trigger: 100+ new triage events accumulated post-fix, or 1 week from now (2026-03-29), whichever comes first.
