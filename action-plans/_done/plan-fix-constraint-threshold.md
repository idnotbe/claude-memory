---
status: done
progress: "완료. Modified Hybrid (Option C): threshold 0.45, cannot 강등, 5 new primaries, 8 new boosters. 97/97 tests pass. 2-round verification PASS_WITH_NOTES."
---

# Fix: CONSTRAINT Threshold — Atomic Adjustment

## Origin

Log review 2026-03-22에서 식별. CONSTRAINT 카테고리가 71개 이벤트에서 한 번도 트리거되지 않음. Threshold(0.5)가 booster 없이 도달 가능한 최대 점수(0.4737)를 초과.

## Problem

- 수학적 사실: `3 * 0.3 / 1.9 = 0.4737 < 0.5` (threshold)
- Booster 키워드가 71개 이벤트에서 한 번도 매칭되지 않음
- 결과: CONSTRAINT 카테고리가 사실상 비활성화 상태

## Phase 1: Research & Design Decision
- [v] 현재 코드 분석 (scoring logic, keyword patterns, threshold math)
- [v] Option A vs B vs Hybrid 분석
- [v] Cross-model validation (Opus + Codex + Gemini via pal clink)
- [v] Vibe check
- [v] 설계 결정: Modified Hybrid (Option C) — threshold 0.45, cannot 강등

## Phase 2: Implementation
- [v] memory_triage.py: CONSTRAINT primary regex — cannot 제거, 5 new primaries 추가
- [v] memory_triage.py: CONSTRAINT booster regex — cannot + 7 structural terms 추가
- [v] memory_triage.py: DEFAULT_THRESHOLDS CONSTRAINT 0.5 → 0.45
- [v] memory-config.default.json: constraint threshold 0.5 → 0.45
- [v] README.md: threshold 문서 업데이트
- [v] commands/memory-config.md: threshold 참조 업데이트 (R1 검증에서 발견)
- [v] Compile check 통과

## Phase 3: Test Writing
- [v] 9개 regression tests 작성 (TestConstraintThresholdFix)
- [v] Boundary tests: 3-primary crosses 0.45, 2-primary below
- [v] cannot demoted: not primary, works as booster
- [v] RUNBOOK overlap reduction 확인
- [v] New primaries/boosters 동작 확인
- [v] Other categories unaffected
- [v] 97/97 tests pass

## Phase 4: Verification Round 1
- [v] R1-Math: PASS_WITH_NOTES (수학 정확, regex 안전, commands/memory-config.md stale ref 발견→수정)
- [v] R1-Ops: PASS_WITH_NOTES (ReDoS 안전, backwards compatible, injection resistance 개선)

## Phase 5: Verification Round 2
- [v] R2-Edge: PASS_WITH_NOTES (모든 edge case 안전, stale ref 없음)
- [v] R2-Holistic: PASS_WITH_NOTES — MERGE 권장 (3 goals 달성, systemic balance 유지)

## Design Decision: Modified Hybrid (Option C)

| 항목 | Before | After |
|------|--------|-------|
| Threshold | 0.5 | 0.45 |
| Primary | limitation, api limit, **cannot**, restricted, not supported, quota, rate limit | limitation, api limit, restricted, not supported, quota, rate limit, **does not support, limited to, hard limit, service limit, vendor limitation** |
| Booster | discovered, found that, turns out, permanently, enduring, platform | discovered, found that, turns out, permanently, enduring, platform, **cannot, by design, upstream, provider, not configurable, managed plan, incompatible, deprecated** |
| Denominator | 1.9 | 1.9 (unchanged) |
| Scope | Global default | Global default (threshold은 bug fix, keyword는 improvement) |

### 0.45를 선택한 이유 (0.47이 아닌)
- 0.47은 3-primary 점수(0.4737)와 margin 0.0037 — fragile
- 0.45는 margin 0.0237 (6x) — future weight 조정에도 robust

### 향후 고려사항 (버그 아님)
- plural forms (`limitations`, `api limits`) 미매칭
- hyphenated forms (`rate-limit`) 미매칭
- `limited to`가 동사적 용법으로도 매칭 가능 (threshold 3+ hits로 완화)

## Files Modified
- `hooks/scripts/memory_triage.py` (3 edits: threshold, primary regex, booster regex)
- `assets/memory-config.default.json` (threshold)
- `README.md` (threshold docs, triage signal description)
- `commands/memory-config.md` (threshold reference)
- `tests/test_memory_triage.py` (9 new tests in TestConstraintThresholdFix)

## Working Files (temp/)
- `temp/constraint-context.md` — initial context dump
- `temp/constraint-design-decision.md` — full design decision document
- `temp/p2-impl-results.md` — implementation results
- `temp/p3-test-results.md` — test writing results
- `temp/p4-verify-r1-math.md` — R1 math verification report
- `temp/p4-verify-r1-ops.md` — R1 ops verification report
- `temp/p5-verify-r2-edge.md` — R2 edge case verification report
- `temp/p5-verify-r2-holistic.md` — R2 holistic verification report
