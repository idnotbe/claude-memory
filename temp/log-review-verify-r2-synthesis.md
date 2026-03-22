# Round 2 Verification: Cross-Cutting Synthesis

**Date**: 2026-03-22
**Verifier**: Claude Opus 4.6 (1M context)
**Role**: R2 synthesis agent -- contradictions, edge cases, unified priorities
**Cross-model**: Codex (OpenAI), Gemini (Google)
**Metacognitive check**: vibe-check skill applied

---

## 1. Contradictions Found and Resolved

### Contradiction 1: CONSTRAINT -- "Hold for keyword cleanup" vs "Fix to 0.47 immediately"

**Source**: R1-Operational says both:
- "Hold CONSTRAINT at 0.5 until keyword refinement is done" (Section 2, Tier 1)
- "The CONSTRAINT threshold should be lowered to at most 0.4737 in the global defaults immediately" (Section 2, Overall Tiering Assessment)

**Resolution**: These are genuinely contradictory as stated. Both Codex and Gemini independently confirm the contradiction. The resolution is to treat this as **one atomic change, not two sequential ones**:

- Lower CONSTRAINT threshold to 0.47 **and** demote bare `cannot` from primary keyword simultaneously.
- Rationale: Lowering threshold without keyword cleanup causes 23.9% trigger rate with 58.8% RUNBOOK overlap. Keyword cleanup without threshold fix leaves the category structurally disabled.
- This is a single PR, not a phased rollout.

**Verdict**: Contradiction resolved. Ship threshold + keyword change atomically.

### Contradiction 2: DECISION 0.35 vs 0.31 -- Math error or design intent?

**Source**: R1-Correctness flags 0.35 as a mathematical error because 0.3158 < 0.35. The original triage analysis recommended 0.35.

**Cross-model disagreement**: This is the most significant point of divergence:

- **R1-Correctness**: 0.35 is wrong; should be <= 0.31 to capture 2-primary matches
- **Codex**: Goes further -- recommends 0.26 for ops because observed max was only 0.2632 (boosted), not 0.3158 (2-primary)
- **Gemini**: Rejects both 0.31 and 0.34 entirely -- argues 0.35 is intentionally blocking unboosted 2-primary matches to enforce quality (booster = rationale signal)

**My assessment**: Gemini raises a valid point that the other verifiers missed. The DECISION schema in SKILL.md requires `rationale` and `alternatives_considered`. A booster keyword ("because", "due to", "rather than") strongly correlates with rationale presence. Lowering to 0.31 would trigger on "said 'decided' twice" without any rationale signal, which produces lower-quality memory candidates.

**Resolution**:
- R1-Correctness is mathematically correct: 0.35 does NOT capture 2-primary scores as the original analysis claimed.
- But the **rationale** for the proposed fix was wrong, not necessarily the threshold value itself.
- The original analysis stated the purpose was "Allows 2 primaries + no booster to trigger" -- this rationale is wrong at 0.35. But the actual question is whether 2 unboosted primaries SHOULD trigger. Gemini argues no.
- **Decision**: The original 0.35 may actually be reasonable for ops per-project config (it captures boosted matches at 0.4211 while blocking noisy unboosted matches at 0.3158). But the stated rationale must be corrected. For global defaults, maintain 0.40.

**Verdict**: R1-Correctness found a real mathematical error in the stated rationale. However, the corrected threshold of 0.31 is too aggressive. The right fix is to correct the rationale, not lower the threshold further.

### Contradiction 3: No contradictions between R1-Security and other verifiers

R1-Security's findings are complementary, not contradictory. Its short-prompt bypass concern (len < 10) is a retrieval-layer issue, distinct from the triage-layer findings in the other analyses.

---

## 2. Corrected Threshold Values Assessment

### DECISION threshold

| Value | What it captures | Quality signal |
|-------|-----------------|---------------|
| 0.40 (current default) | 3+ primaries (0.4737) or boosted combos | High precision, low recall |
| 0.35 (original Tier 1) | 1 boosted + 1 primary (0.4211) | Good -- requires booster = rationale |
| 0.31 (R1-Correctness) | 2 unboosted primaries (0.3158) | Medium -- no rationale required |
| 0.26 (Codex recommendation) | 1 boosted match (0.2632) | Lowest precision -- single contextual hit |

**Assessment**: For per-project ops config, 0.35 is defensible because it captures the boosted pattern (0.4211) which is a stronger signal than 2 bare primaries. However, Codex correctly notes that the ops dataset's max observed score is 0.2632 (boosted), not 0.3158. This means even at 0.35, DECISION would still not trigger in the observed data. To actually capture observed ops events, the threshold would need to be <= 0.26.

**Recommendation**: Per-project ops config should use 0.26 if the goal is to capture ops decisions with current keyword coverage. If combined with keyword expansion, 0.35 is acceptable.

### PREFERENCE threshold

| Value | What it captures | Quality signal |
|-------|-----------------|---------------|
| 0.40 (current default) | 3+ primaries or boosted combos | High precision |
| 0.34 (R1-Correctness) | 2 primaries (0.3415) | Reasonable -- appeared only once in 71 events |
| 0.35 (original Tier 1) | Does NOT capture 2 primaries despite claim | Misaligned with stated intent |

**Assessment**: 0.34 is appropriate if the goal is to capture 2-primary matches. Unlike DECISION, there is no strong semantic argument for requiring a booster for PREFERENCE (preferences don't necessarily need rationale). The PREFERENCE schema is simpler than DECISION.

**Recommendation**: 0.34 for per-project config. Maintain 0.40 for global defaults pending broader data.

### CONSTRAINT threshold

| Value | What it captures |
|-------|-----------------|
| 0.50 (current) | Nothing without booster (structurally broken) |
| 0.47 (proposed) | 3 primaries (0.4737) -- but ONLY with keyword cleanup |

**Assessment**: 0.47 is correct, but MUST be shipped with `cannot` demotion. All three cross-model analyses agree.

**Recommendation**: 0.47, atomic with keyword changes.

---

## 3. Interaction Effects Assessment

### CONSTRAINT keyword changes vs RUNBOOK scoring

**Current overlap**: 58.8% of CONSTRAINT max-score events also have RUNBOOK >= 0.4.

**Keyword change analysis** (reading actual code):

CONSTRAINT primaries: `limitation, api limit, cannot, restricted, not supported, quota, rate limit`
RUNBOOK primaries: `error, exception, traceback, stack trace, failed, failure, crash`

The overlap comes from `cannot` appearing in debugging contexts alongside RUNBOOK keywords. When a user says "the service cannot connect" followed by "error: connection refused," both categories score.

**Proposed CONSTRAINT changes**: Demote `cannot` to booster (or remove), add `does not support, limited to, hard limit, service limit, vendor limitation, managed plan`.

**Effect on overlap**: The new keywords are constraint-specific, not debugging-adjacent. This should **reduce** the CONSTRAINT/RUNBOOK overlap significantly because:
- `does not support` is a platform property statement, not a debugging artifact
- `hard limit`, `service limit`, `vendor limitation` are infrastructure-specific
- None of these commonly co-occur with `error`, `exception`, `traceback`

**Risk**: If `not supported` is added as a primary, it may still fire in debugging contexts ("feature not supported in this version"). However, the broader phrasing `does not support` is more specific.

**Verdict**: The proposed keyword changes improve the CONSTRAINT/RUNBOOK separation. The interaction effect is positive, not negative. Demoting `cannot` is the single highest-impact keyword change.

---

## 4. Edge Cases Assessment

### 4.1 All 6 Categories Trigger Simultaneously

**Code path verified** (`memory_triage.py` lines 467-484): `run_triage()` evaluates all categories independently and returns all that exceed their threshold. There is no top-K limit.

**What happens**:
1. Triage produces `triage-data.json` with 6 entries
2. SKILL.md orchestration spawns 6 drafting subagents in parallel (Phase 1)
3. Phase 1.5 performs 6 candidate selections + 6 draft assemblies
4. 6 verification subagents run (Phase 2)
5. 1 foreground save subagent runs all write commands (Phase 3)

**Risk assessment**:
- **Performance**: High latency. 6 parallel subagents + 6 verification rounds is expensive. Estimated 2-4x the time of a typical 2-category trigger.
- **Correctness**: No correctness issue -- each category is processed independently.
- **UX**: A single session producing 6 memory writes may feel aggressive. SESSION_SUMMARY alone fires 98.6% of the time; adding 5 more categories simultaneously could produce memory fatigue.
- **No guardrail exists**: There is no `max_categories` limit in the code. The SKILL.md orchestration will process everything `run_triage()` returns.

**Recommendation**: Add a `max_categories_per_triage` config option (default: 4) that caps triggered categories. SESSION_SUMMARY should always be included; additional categories should be ranked by score and capped.

### 4.2 Very Short Conversations (1-2 Messages)

**Code path verified**: `parse_transcript()` uses a deque with maxlen, so 1-2 messages are handled correctly. `extract_text_content()` works on any number of messages. `score_text_category()` iterates over lines -- 1-2 messages produce few lines.

**Behavior**:
- SESSION_SUMMARY: Will score low (few exchanges, few tool uses). With 1 exchange and 0 tool uses: `1 * 0.02 = 0.02`, which is well below the 0.6 threshold. Correct behavior.
- Text-based categories: A single message saying "we decided to use Redis because it's fast" would match 1 primary ("decided") + 1 booster ("because") = 0.5/1.9 = 0.2632 for DECISION. Below default 0.4 threshold. This is debatable -- it's a clear decision, but the threshold is designed for sustained signal, not single-line captures.
- A single message with 3+ decision keywords across lines is unlikely but possible (e.g., pasted meeting notes).

**Assessment**: Short conversations are under-captured. This is **acceptable behavior** for a stop-hook system that triggers at session end. A 1-2 message session is typically a quick query, not a substantial work session worth memorializing. The rare exception (pasting a decision document) would need explicit manual save.

### 4.3 Very Long Conversations (100+ Messages)

**Code path verified**: `parse_transcript()` with `max_messages=50` keeps only the last 50 messages. Early-session decisions, constraints, and preferences are discarded from the scoring window.

**Two distinct blind spots identified**:

1. **Scoring blind spot**: Keywords in messages 1-50 of a 100-message session are invisible to triage. If a user discovers a critical constraint early in a session and then spends 50+ messages working around it, the constraint will not be captured. The scoring system only sees the workaround, not the discovery.

2. **SESSION_SUMMARY "opening excerpt" blind spot** (newly identified by Codex): The context file uses `lines[:80]` as "opening excerpt." But `lines` is derived from the tail-50 messages, not the full session. So the "opening excerpt" shows message ~51, not message 1. The session summary drafter receives a misleading signal about what the session started with.

**Assessment**: The scoring blind spot is inherent to the tail-window design and is a known tradeoff (bounded compute vs. full coverage). The SESSION_SUMMARY excerpt blind spot is a genuine bug -- the code claims to show the "opening excerpt" but actually shows the start of the tail window.

**Gemini's length-bias claim** (over-triggering on long conversations): Partially valid but overstated. The `max_primary=3` and `max_boosted=2` caps bound the maximum score regardless of text length. Longer texts are more likely to hit these caps by chance, but the effect is bounded, not unbounded. The 50-message window also caps the input length. Within that window, a dense 50-message debugging session is indeed more likely to produce accidental keyword matches than a focused 5-message session. This is a moderate concern, not severe.

### 4.4 Empty Transcript (No Messages)

**Code path**: `parse_transcript()` returns `[]`. `extract_text_content()` returns `""`. All `score_text_category()` calls return 0.0. SESSION_SUMMARY scores 0.0. No categories trigger. `run_triage()` returns `[]`. The hook exits with no output.

**Assessment**: Handled correctly. No edge case concern.

---

## 5. Unified Priority-Ordered Action Items

Based on all findings from the original analyses, 3 R1 verifiers, 2 cross-model assessments, and source code verification:

### P0: Analyzer false positive prevention (Effort: LOW, Risk: NONE)
- Add minimum sample size guard to `memory_log_analyzer.py`
  - `_detect_zero_length_prompt`: require N >= 10 skip events
  - `_detect_skip_rate_high`: require N >= 20 skip events
  - `_detect_category_never_triggers`: require N >= 30 triage.score events
- **Rationale**: The N=4 CRITICAL false positive demonstrates unreliable percentage-based alerting on small samples. This blocks clean signal from all other improvements.
- **Consensus**: All 5 analyses + both cross-models agree.

### P1: Atomic CONSTRAINT fix (Effort: MEDIUM, Risk: LOW-MEDIUM)
- Lower CONSTRAINT threshold from 0.50 to 0.47 in `DEFAULT_THRESHOLDS`
- Simultaneously demote bare `cannot` from primary to booster in CONSTRAINT pattern
- Add constraint-specific primaries: `does not support`, `limited to`, `hard limit`, `service limit`, `vendor limitation`
- Expand CONSTRAINT boosters: `incompatible`, `deprecated`, `blocked by`, `upstream`, `provider`, `by design`
- **Must be atomic**: threshold change without keyword change causes 23.9% false trigger rate
- **Rationale**: Structurally broken category -- mathematically impossible to trigger without booster, and boosters never fire. Dual fix required.
- **Consensus**: All analyses agree CONSTRAINT is structurally broken. Codex and Gemini both insist on atomic change.

### P2: Per-project ops config tuning (Effort: LOW, Risk: NONE)
- Set DECISION threshold to 0.26 in ops project's `memory-config.json`
  - Rationale: ops max observed score is 0.2632 (boosted), not 0.3158 (2-primary). Threshold 0.26 captures the actual observed pattern.
- Set PREFERENCE threshold to 0.34 in ops project's `memory-config.json`
  - Rationale: captures 2-primary pattern (0.3415). Only 1 event would newly trigger -- low noise risk.
- **Do NOT change CONSTRAINT locally** -- wait for P1 global fix with keyword cleanup.
- **Rationale**: Per-project tuning is zero-risk to other projects and immediately actionable.

### P3: Threshold margin alert in analyzer (Effort: MEDIUM, Risk: NONE)
- Add detector: when `max_observed_score` for a category is within 0.05 of threshold but never exceeds it over 50+ events, fire an alert.
- Add booster-hit-rate as a first-class metric: fire alert when booster hit rate is 0% over 50+ events for a category with non-zero primary matches.
- **Rationale**: Would have caught the CONSTRAINT structural gap proactively. Prevents future similar issues.

### P4: SESSION_SUMMARY opening excerpt fix (Effort: LOW, Risk: NONE)
- The "opening excerpt" in context files uses `lines[:80]` from the tail-window text, not the true session start.
- Fix: capture head-of-transcript (first N messages) separately from the tail-window scoring pipeline.
- **Rationale**: Newly identified by Codex. The session summary drafter receives misleading context about session goals.
- **Consensus**: Codex identified; I verified against source code (lines 818-825 of `memory_triage.py`).

### P5: DECISION/PREFERENCE keyword expansion (Effort: MEDIUM, Risk: LOW)
- DECISION: Add implicit-decision phrases for ops domain: `using X for`, `deploying to`, `migrating to`, `replacing X with`
- PREFERENCE: Add booster expansion: `standard`, `formatting`, `naming`, `style guide`
- **Rationale**: Addresses the domain-sensitivity issue. DECISION keywords expect explicit decision verbs that ops rarely uses.
- **Gated by**: P1 must ship first to avoid compounding multiple keyword changes.

### P6: Deploy boundary awareness in analyzer (Effort: MEDIUM, Risk: NONE)
- Add `plugin_version` to JSONL event schema
- Partition analyzer metrics by version
- **Rationale**: Prevents mixed-version artifacts from producing false positives.

### P7: Short-prompt retrieval bypass review (Effort: MEDIUM, Risk: LOW)
- The `len < 10` threshold in `memory_retrieve.py` causes security constraints to not be injected for short prompts like "delete" (6 chars), "rollback" (8 chars).
- Consider: unconditional injection for CONSTRAINT-category memories regardless of prompt length.
- **Rationale**: Identified by R1-Security. Design-level gap, not urgent vulnerability.

### P8: Max-categories-per-triage guardrail (Effort: LOW, Risk: NONE)
- Add `max_categories_per_triage` config option (default: 4)
- When more than max categories trigger, keep SESSION_SUMMARY + top N-1 by score
- **Rationale**: Prevents UX fatigue when all 6 categories trigger simultaneously.

### P9: Long-conversation scoring window improvement (Effort: HIGH, Risk: MEDIUM)
- Options: head+tail window (first 10 + last 50 messages), or increase `max_messages` default
- **Rationale**: Early-session decisions/constraints are invisible to the current tail-only window.
- **Deferred**: High effort, needs design discussion. The current 50-message tail window is a deliberate tradeoff.

### P10: Tier 4 validation requirement (Ongoing)
- Before merging any default threshold changes: 3+ project types, 50+ labeled events, 70%+ precision
- **Rationale**: Universal consensus that one day from one project is insufficient for global defaults.

---

## 6. Cross-Model Consensus

### Points of Agreement (Codex + Gemini + my analysis)

1. CONSTRAINT is structurally broken -- threshold change + keyword cleanup must be atomic
2. Analyzer needs minimum sample size guard -- highest priority, lowest risk
3. Per-project tuning is the right immediate step for DECISION/PREFERENCE
4. The ZERO_LENGTH_PROMPT finding is a confirmed false positive
5. One day of data is insufficient for global default changes
6. The long-conversation tail-window creates blind spots for early-session content

### Points of Disagreement

| Issue | Codex | Gemini | My Assessment |
|-------|-------|--------|---------------|
| DECISION threshold | 0.26 (capture observed boosted pattern) | Reject 0.31; keep 0.35 or 0.40 (require booster) | 0.26 for per-project ops; 0.40 global default |
| PREFERENCE threshold | 0.34 (reasonable) | Reject 0.34 (too aggressive) | 0.34 for per-project; 0.40 global default |
| Length bias severity | Moderate (bounded by caps) | Severe (statistical inevitability) | Moderate -- caps bound the effect; 50-msg window limits input |
| All-6-category trigger | Latency/cost concern | No max_categories limit is a gap | Agree with both -- add configurable max |
| Code fence hiding | MEDIUM (design tradeoff) | CRITICAL (vulnerability) | MEDIUM (deliberate tradeoff with valid reasoning) |

### Resolution of Key Disagreement: DECISION Threshold

Codex argues from the observed data (max 0.2632), Gemini argues from semantic quality (boosters = rationale). Both are valid for different purposes:
- **For per-project ops config**: Codex is right. If you want DECISION to capture anything at all in ops, you need <= 0.26 with current keywords.
- **For global defaults**: Gemini is right. The booster requirement enforces that decisions have rationale, which is a quality signal.
- **Best path forward**: Keep global default at 0.40. Set ops per-project to 0.26. Expand DECISION keywords (P5) so that ops-style implicit decisions can reach higher scores.

---

## 7. Items All R1 Verifiers Missed

### 7.1 SESSION_SUMMARY Opening Excerpt Bug
The "opening excerpt" in context files is taken from `lines[:80]` where `lines` is derived from the last 50 messages, not the full transcript. For long sessions, this means the "opening excerpt" shows content from ~message 51, not message 1. The session summary drafter receives misleading context about what the session's original goals were.

**Source**: Identified by Codex in R2 cross-model analysis. Verified against source code: `memory_triage.py` lines 818-825 operate on `lines` from `extract_text_content(messages)` where `messages` is the tail-50 deque.

### 7.2 Observed vs Theoretical Score Mismatch for DECISION
R1-Correctness identified that 0.35 does not capture 2-primary scores (0.3158). But the ops dataset's actual max DECISION score was 0.2632 (1 boosted match), not 0.3158 (2 unboosted primaries). The 2-primary scenario was never observed in the dataset. So the corrected threshold of 0.31 fixes a hypothetical case, not the actual observed gap.

**Source**: Identified by Codex. Original triage analysis data (lines 27-31) shows DECISION max observed = 0.2632.

### 7.3 Missing Boundary Tests
There are no regression tests asserting behavior at the exact score quanta boundaries (0.3158, 0.3415, 0.4737). If thresholds are changed, there is no automated safety net to verify the intended capture behavior.

**Source**: Identified by Codex after scanning the test suite.

### 7.4 No Max-Categories Guardrail
No verifier flagged the absence of a limit on simultaneous category triggers. The system will happily process all 6 categories, spawning 6 drafting subagents + 6 verification subagents. This is a UX and cost concern for dense sessions.

**Source**: Identified by Gemini, verified against source code.

---

## 8. Final Verdict

### CONFIRMED (with corrections)

The original analyses and R1 verifications are **fundamentally sound**. The diagnoses are correct:
- ZERO_LENGTH_PROMPT is a confirmed false positive (pre-fix bug artifact)
- CONSTRAINT has a structural scoring gap (threshold 0.5 > max-without-booster 0.4737)
- DECISION and PREFERENCE are domain-limited with insufficient keyword coverage

**Corrections applied**:

1. **DECISION threshold 0.35 rationale is wrong** (R1-Correctness is correct about the math) but the corrected value of 0.31 is inappropriate because it bypasses the booster quality gate. Per-project ops config should use 0.26 (capturing observed boosted pattern), not 0.31 (capturing theoretical 2-primary).

2. **CONSTRAINT fix must be atomic** -- the R1-Operational contradiction (hold vs fix immediately) is resolved by requiring threshold + keyword change in the same PR.

3. **SESSION_SUMMARY opening excerpt bug** is a newly identified issue that none of the R1 verifiers caught.

4. **Missing boundary regression tests** should be added before any threshold changes are merged.

5. **Max-categories guardrail** should be implemented to prevent all-6-trigger UX fatigue.

**Overall confidence**: HIGH. The multi-layer verification (2 original analyses + 3 R1 verifiers + 2 R2 cross-model + source code verification) provides strong convergence on the core findings with productive disagreement on thresholds that has been resolved.
