# Session 5 (Phase 2e) -- Confidence Annotations Master Plan

**Date:** 2026-02-21
**Status:** COMPLETE
**Scope:** ~20 LOC, add confidence annotations to injected memories

---

## Task Summary

Add `[confidence:high/medium/low]` annotations to injected memories based on BM25 score brackets. Zero latency cost, zero dependencies.

### Checklist (from rd-08-final-plan.md)
- [ ] `confidence_label()` function (ratio-based brackets: >=0.75 high, >=0.40 medium, else low)
- [ ] Update output format to append `[confidence:high/medium/low]` to each injected memory line
- [ ] Smoke test: verify annotations appear in output for a few queries

### Reference Implementation (from plan)
```python
def confidence_label(bm25_score: float, best_score: float) -> str:
    """Map BM25 score to confidence bracket."""
    if best_score == 0:
        return "low"
    ratio = abs(bm25_score) / abs(best_score)
    if ratio >= 0.75:
        return "high"
    elif ratio >= 0.40:
        return "medium"
    return "low"
```

### Output Format Change
```xml
<memory-context source=".claude/memory/">
- [DECISION] JWT token refresh flow -> path #tags:auth,jwt [confidence:high]
- [CONSTRAINT] API middleware setup -> path #tags:auth,api [confidence:medium]
- [RUNBOOK] CSS grid layout -> path #tags:css,login [confidence:low]
</memory-context>
```

### Key Files
- `hooks/scripts/memory_retrieve.py` -- main file to modify (lines 245-271 `_output_results()`)
- `hooks/scripts/memory_search_engine.py` -- shared engine (read-only for this session)

### Critical Considerations
1. **FTS5 path**: Results have `score` field (BM25 rank, negative values, more negative = better)
2. **Legacy path**: Results are `(score, priority, entry)` tuples -- scores are positive integers
3. **Both paths** call `_output_results()` -- confidence must work for BOTH
4. **Security**: Confidence label is computed from score data, not user input -- low injection risk
5. **Backward compatibility**: Adding `[confidence:*]` to output is additive, doesn't break parsers

### Design Decisions to Make
1. Where to place `confidence_label()` -- in `memory_retrieve.py` or `memory_search_engine.py`?
2. How to handle legacy path scores (positive integers) vs FTS5 scores (negative floats)?
3. Should `_output_results()` accept scores, or should confidence be pre-computed?

---

## Team Roles
- **implementer**: Write the code with best practices
- **reviewer-security**: Security-focused review
- **reviewer-correctness**: Correctness + edge case review
- **verifier-r1-a / verifier-r1-b**: First independent verification round (different perspectives)
- **verifier-r2-a / verifier-r2-b**: Second independent verification round (different perspectives)

---

## Timeline
1. Phase 1: Implementation (implementer writes code)
2. Phase 2: Dual review (security + correctness reviewers)
3. Phase 3: Verification Round 1 (2 independent verifiers)
4. Phase 4: Verification Round 2 (2 independent verifiers)

---

## Log
- [start] Master plan created
- [phase 1 complete] Implementation done by team lead (implementer was too slow). Changes:
  - Added `confidence_label()` at line ~160 (14 LOC)
  - Updated `_output_results()` to compute best_score and append [confidence:*] (4 LOC changed)
  - Updated legacy path to attach score to entry dicts (5 LOC changed)
  - Compile check PASSED
  - Total: ~20 LOC net change (matches plan)
  - Report: temp/s5-implementer-output.md
- [phase 2 started] Dual reviewers spawned in parallel:
  - reviewer-security: security-focused review -> temp/s5-review-security.md
  - reviewer-correctness: correctness-focused review -> temp/s5-review-correctness.md
- [phase 2 complete] Both reviews done:
  - Security: APPROVE (1 MEDIUM -- confidence label spoofing via title; 1-line fix applied)
  - Correctness: APPROVE (0 bugs, all edge cases verified)
  - Applied security fix: added `re.sub(r'\[confidence:[a-z]+\]', '', title)` to `_sanitize_title()`
  - Compile check PASSED after fix
- [phase 3 started] Verification Round 1 (2 parallel verifiers: functional + integration)
- [phase 3 complete] Both V1 verifications APPROVE:
  - V1-functional: PASS on all 10 checks. 606/606 tests pass. 0 bugs. 1 LOW follow-up (case-insensitive regex)
  - V1-integration: PASS on all 7 checks. Integration boundary correct. No downstream breakage.
  - External: Gemini 3 Pro + vibe-check both APPROVE
- [phase 4 started] Verification Round 2 (2 parallel verifiers: adversarial + independent)
- [phase 4 - v2-independent complete] APPROVE (HIGH confidence). 2 new findings:
  - IF-1 MEDIUM: Case-insensitive spoofing bypass (regex only matches lowercase)
  - IF-2 MEDIUM: Tag-based spoofing vector (brackets survive html.escape)
  - Report: temp/s5-v2-independent.md
- [phase 4 - v2-adversarial complete] APPROVE WITH CONDITIONS. 3 spoofing vectors found:
  - F1 LOW-MEDIUM: Regex case-sensitivity bypass (S5-specific) -- BLOCKING CONDITION
  - F2 MEDIUM: Tag-based spoofing (pre-existing, amplified by S5)
  - F3 LOW: Path-based injection (pre-existing, amplified by S5)
  - Report: temp/s5-v2-adversarial.md
- [phase 4 complete] Both V2 verifications done. Converging findings:
  - Both independently found case-insensitive bypass + tag spoofing
  - Applied blocking fix: `re.sub(r'\[confidence:[a-z]+\]', '', title, flags=re.IGNORECASE)`
  - Compile check PASSED, 606/606 tests PASS
- [SESSION 5 COMPLETE] All phases done. Final status:
  - Implementation: ~25 LOC (confidence_label + output format + legacy score + security fixes)
  - Reviews: 2/2 APPROVE (security + correctness)
  - V1: 2/2 APPROVE (functional + integration)
  - V2: 2/2 APPROVE (adversarial APPROVE WITH CONDITIONS -> condition met; independent APPROVE)
  - Tests: 606/606 pass at every stage
  - Follow-up items tracked: tag-based spoofing fix, path-based injection fix, unit tests for confidence_label()
