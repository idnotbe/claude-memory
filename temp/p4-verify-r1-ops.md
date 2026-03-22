# Verification Report: CONSTRAINT Threshold Fix (Round 1 -- Operational/Security)

**Verifier perspective:** Operational Safety & Security
**Date:** 2026-03-22
**Verdict:** PASS_WITH_NOTES

---

## 1. Code Changes Reviewed

| File | Change |
|------|--------|
| `hooks/scripts/memory_triage.py:55-62` | `DEFAULT_THRESHOLDS["CONSTRAINT"]`: 0.5 -> 0.45 |
| `hooks/scripts/memory_triage.py:132-149` | Primary: removed `cannot`, added 5 new terms (`does not support`, `limited to`, `hard limit`, `service limit`, `vendor limitation`). Booster: added 8 new terms (`cannot`, `by design`, `upstream`, `provider`, `not configurable`, `managed plan`, `incompatible`, `deprecated`) |
| `assets/memory-config.default.json:73` | `constraint` threshold: 0.45 (matches code default) |
| `README.md:192` | Documents `constraint=0.45` in threshold defaults |
| `README.md:285` | Describes CONSTRAINT triage criteria |

---

## 2. Operational Safety Assessment

### 2.1 False-Positive Scenario Analysis

Simulated 5 realistic conversation scenarios against the new scoring:

| Scenario | Primary | Boosted | Score | Triggered? | Correct? |
|----------|---------|---------|-------|-----------|----------|
| **True constraint** (Discourse plugin limit) | 1 | 2 | 0.684 | Yes | YES |
| **Debugging rate limit error** (429/retry) | 3 | 2 | 1.000 | Yes | BORDERLINE |
| **API integration work** (limitations discovery) | 0 | 2 | 0.526 | Yes | ARGUABLY YES |
| **Deployment discussion** (EC2 quotas) | 0 | 1 | 0.263 | No | YES |
| **Normal coding session** | 0 | 0 | 0.000 | No | YES |

**Key observations:**

- **"Debugging rate limit error" scenario (concentrated 6-line input):** Scores 1.0 because `rate limit`, `quota`, `restricted` appear as primaries while `provider` co-occurs as booster. However, this is a worst-case concentrated test. In a real 50-message conversation window, these keywords would be diluted across many non-matching lines. The scoring algorithm counts max 3 primary + 2 boosted, so dilution does not change the max possible score, but the CO_OCCURRENCE_WINDOW of 4 lines means boosters must be spatially close to primaries to activate. **Likelihood: MEDIUM** for API-heavy debugging sessions. **Impact: LOW** -- a false CONSTRAINT trigger produces a draft that the LLM verification subagent can reject.

- **"API integration work" scenario:** This actually describes real limitations ("API does not support batch operations", "upstream service has a limitation on payload size"). This is arguably a TRUE positive, not a false positive. The system correctly identifies constraint-relevant content.

### 2.2 Threshold Sensitivity

Mathematical analysis of the boundary:
- **Minimum to trigger (primary only):** 3 primaries = 0.9/1.9 = 0.473 >= 0.45 (passes)
- **Old threshold (0.5):** 3 primaries alone would NOT trigger (0.473 < 0.5)
- **Gap created:** The 0.05 threshold reduction means 3 primary-only matches now cross the boundary

This is the intended design trade-off: catch more true constraints at the cost of marginal false-positive increase. The old threshold (0.5) was too strict, missing legitimate constraints that lacked booster co-occurrence.

### 2.3 Per-Project Override Escape Hatch

Verified all 3 override scenarios:
- `constraint: 0.5` (lowercase) -> correctly overrides to 0.5
- `CONSTRAINT: 0.5` (uppercase) -> correctly overrides to 0.5
- No constraint key specified -> correctly defaults to 0.45

The config loading code normalizes keys to uppercase (`k.upper()`) and clamps values to [0.0, 1.0] with NaN/Inf rejection. Users who find 0.45 too sensitive can set `constraint: 0.5` or higher in their per-project `memory-config.json`.

**Documentation:** The README (line 192) documents the default threshold values and notes that "Higher values = fewer but higher-confidence captures."

---

## 3. Security Assessment

### 3.1 ReDoS (Catastrophic Backtracking) Analysis

Tested all regex patterns against 8 adversarial inputs (up to 100KB, heavy whitespace, repeated partial matches):

| Pattern | Max time | Verdict |
|---------|----------|---------|
| Primary regex (11 alternations with `\s+`) | 1.0ms | SAFE |
| Booster regex (14 alternations with `\s+`) | 2.1ms | SAFE |

**Analysis:** The `\s+` quantifiers in patterns like `does\s+not\s+support` are sequential (not nested). Backtracking is linear O(N) -- after `does` matches, `\s+` greedily consumes whitespace, then attempts `not`. On failure, it backtracks linearly through whitespace positions. No nested quantifier groups means no exponential blowup. All patterns completed in under 3ms even on 100KB adversarial input.

### 3.2 Prompt Injection Risk

**Pre-change:** `cannot` as a primary keyword was trivially injectable -- nearly any error message contains "cannot". An attacker embedding "cannot" in tool output could bump CONSTRAINT scores.

**Post-change:** Primary keywords require domain-specific vocabulary (`limitation`, `api limit`, `vendor limitation`, `hard limit`, etc.). This is HARDER to inject naturally without appearing suspicious. The change is a net security improvement.

**Existing mitigations (unchanged):**
- Code fences and inline code are stripped before scoring
- Triage hook reads only the last 50 messages (configurable, clamped to [10, 200])
- Memory drafts go through LLM verification subagents before persistence
- Sanitization of titles (escape `<`/`>`, strip control chars) remains intact

### 3.3 Sanitization Invariants

The new booster keywords (`provider`, `upstream`, `deprecated`, `by design`, etc.) are plain text terms matched via regex with `\b` word boundaries. They:
- Contain no delimiter arrows (` -> `) or tag markers
- Contain no bracket sequences like `[SYSTEM]`
- Cannot corrupt index parsing
- Are matched against already-sanitized transcript text (code blocks stripped)

No sanitization invariants are violated.

---

## 4. Cross-Category Impact

### 4.1 CONSTRAINT vs RUNBOOK Overlap

**Before:** `cannot` was a CONSTRAINT primary. Lines like "cannot connect", "cannot authenticate" scored as CONSTRAINT primaries, overlapping with RUNBOOK error contexts.

**After:** `cannot` is a CONSTRAINT booster only. It no longer independently scores CONSTRAINT, only amplifies when a real constraint primary is nearby. This is a clear overlap REDUCTION.

Verified: No direct keyword overlap between CONSTRAINT boosters and RUNBOOK boosters.

### 4.2 CONSTRAINT vs TECH_DEBT/DECISION Overlap

- No overlap between CONSTRAINT primaries and TECH_DEBT primaries
- No overlap between CONSTRAINT boosters and DECISION boosters
- The new CONSTRAINT primaries (`vendor limitation`, `service limit`, `hard limit`) are highly domain-specific and do not appear in other category patterns

### 4.3 Other Hook Scripts

Grep confirmed: `memory_write.py`, `memory_candidate.py`, `memory_search_engine.py`, `memory_index.py`, and `memory_log_analyzer.py` reference "CONSTRAINT" only as a category name string for routing/mapping. None reference specific CONSTRAINT keywords. No cross-script breakage.

---

## 5. Backwards Compatibility

- Existing per-project configs with `constraint: 0.5` override the new default correctly (verified)
- Case-insensitive key matching works for both `constraint` and `CONSTRAINT` (verified)
- All 143 relevant tests pass (including 9 new `TestConstraintThresholdFix` tests)
- No API contract changes in triage output format

---

## 6. Cross-Model Feedback (Gemini 3.1 Pro)

Gemini independently verified:
1. **False-positive risk in debugging sessions:** Confirmed that 3 primaries cross threshold (0.473 > 0.45). Flagged as a concern.
2. **Booster noise (`provider`, `upstream`, `deprecated`):** Confirmed these are common in API debugging contexts and could amplify false positives.
3. **ReDoS safety:** Confirmed `does\s+not\s+support` is safe -- no nested quantifiers, linear backtracking only.

Gemini recommended rollback to 0.5 or denominator increase. **My assessment:** This goes beyond the fix's scope. The 0.45 threshold is a deliberate design choice to improve true-positive capture, with per-project override as the documented escape hatch. The marginal false-positive risk is mitigated by the multi-layer pipeline (LLM verification subagents reject low-quality drafts).

---

## 7. Issues Found

| # | Severity | Issue | Likelihood | Impact |
|---|----------|-------|-----------|--------|
| 1 | LOW | 3 primary-only matches (rate limit + quota + restricted) trigger CONSTRAINT at 0.473 in API debugging conversations without booster co-occurrence | MEDIUM | LOW (draft goes through verification) |
| 2 | INFO | Boosters `provider` and `upstream` are common in cloud/API discussions, potentially amplifying marginal primary matches | LOW | LOW (boosters alone cannot trigger) |

No HIGH or CRITICAL issues found.

---

## 8. Verdict: PASS_WITH_NOTES

The CONSTRAINT threshold fix is operationally sound and introduces no security regressions. The implementation is well-tested (9 dedicated tests), backwards-compatible, and the regex patterns are ReDoS-safe. Moving `cannot` from primary to booster is a clear improvement that reduces RUNBOOK overlap and makes prompt injection harder.

The noted false-positive risk in API debugging scenarios is a known trade-off of the lower threshold, mitigated by: (a) per-project override capability, (b) downstream LLM verification that filters low-quality drafts, and (c) the fact that API-heavy debugging conversations discussing rate limits and quotas may genuinely warrant constraint capture.
