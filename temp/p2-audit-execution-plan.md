# Plan #2 Quality Audit -- Execution Plan

**Date:** 2026-02-25
**Goal:** Execute all 11 audit actions (A-01 through A-11), each phase independently verified 2x

---

## Phase Structure

### Phase A: Tier 1 -- Integration Data Contract Verification (A-01, A-02, A-03)
- A-01: Config loading order bug (config=None on early skip events)
- A-02: Call-site schema audit (12 emit_event call sites vs schema contract)
- A-03: results[] field accuracy (score_with_body data flow)
- **2x independent verification after fixes**

### Phase B: Tier 2 -- Behavioral Verification (A-04, A-05, A-06, A-07)
- A-04: E2E data flow trace (integration test)
- A-05: Lazy import fallback verification
- A-06: Cleanup latency under accumulated state
- A-07: Large payload concurrent append
- **2x independent verification after fixes**

### Phase C: Tier 3 -- Operational & Design (A-08, A-09, A-10, A-11)
- A-08: Operational workflow smoke test
- A-09: Truncation metadata enhancement
- A-10: Non-triggered category scores in triage.score
- A-11: Non-deterministic set serialization defense
- **2x independent verification after fixes**

---

## Verification Protocol (per phase)

Each phase:
1. Execute audit actions → identify bugs/gaps → implement fixes
2. Verification Round 1: Fresh teammate + vibe check + pal clink
3. Verification Round 2: Different perspective teammate + vibe check + pal clink
4. Resolve all findings from both rounds
5. Proceed to next phase

---

## Progress

- [x] Phase A started
- [x] Phase A V1 verification (CONDITIONAL → PASS after fixes)
- [x] Phase A V2 verification (CONDITIONAL → PASS after fixes)
- [x] Phase A complete (all V1+V2 conditions resolved)
- [x] Phase B started (A-04: 10 E2E tests, A-05: 6 import tests, A-06+A-07: 4 perf tests)
- [x] Phase B V1 verification (CONDITIONAL → PASS after B-01/B-02/B-03/B-06/B-09 fixes)
- [x] Phase B V2 verification (CONDITIONAL → PASS after V2-02/V2-03/V2-05 fixes)
- [x] Phase B complete (875/875 tests passing)
- [x] Phase C started (A-08: 11 tests, A-09: 8 tests, A-10: 11 tests, A-11: 12 tests)
- [x] Phase C V1+V2 verification (combined -- agents hit rate limit, verified directly + Gemini clink)
- [x] Phase C complete (916/916 tests passing)
- [x] All phases done, final summary written
