# Master Briefing: plan-retrieval-confidence-and-output.md 수정 작업

**작성일:** 2026-02-22
**목적:** Deep Analysis 결과와 충돌/불일치하는 6개 이슈를 모두 수정
**대상 파일:** `action-plans/plan-retrieval-confidence-and-output.md`

---

## 수정해야 할 이슈 목록

### Issue A (높음): Line 103 -- post-truncation counting 설명이 Finding #2와 충돌
- **현재:** `cluster_count: ratio > 0.90인 결과 수 (복합 점수 기반 ratio). 주의: max_inject에 의해 결과가 잘린 후의 집합에서 계산.`
- **문제:** Finding #2가 post-truncation counting은 dead code임을 수학적으로 증명. "잘린 후 집합에서 계산"은 정면 충돌.
- **수정 방향:** pre-truncation counting을 명시하거나, 현재 비활성이므로 호출 시 항상 0 전달됨을 명시

### Issue B (중간): Line 141 -- 비활성 기능의 구현 체크리스트
- **현재:** `- [ ] 클러스터 감지 로직 구현: cluster_count >= 3이면 최대 "medium"`
- **문제:** "비활성 기능 구현은 불필요한 엔지니어링"이라는 Deep Analysis 결정과 충돌
- **수정 방향:** 항목을 "비활성 유지 확인" 또는 제거

### Issue C (낮음): Line 68 -- "BM25 모드" 구식 표현
- **현재:** `권장 시작값: BM25 모드에서 1.0-2.0`
- **문제:** 복합 점수 도메인이어야 함. line 102에서는 이미 "복합 점수 도메인 기준 교정 (일반 코퍼스에서 권장 시작값 1.0-3.0)"으로 정정됨
- **수정 방향:** line 68의 값을 line 102와 통일 (복합 점수 도메인 기준 1.0-3.0)

### Issue D (낮음): Line 68 vs 102 -- abs_floor 권장값 내부 불일치
- **현재:** line 68은 1.0-2.0, line 102는 1.0-3.0
- **수정 방향:** 둘 다 1.0-3.0으로 통일 (복합 점수 도메인 기준)

### Issue E (중간): Lines 148-149 -- obsolete 클러스터 테스트 체크리스트
- **현재:** `- [ ] 단위 테스트: 클러스터 감지 (~5개)` + `- [ ] 단위 테스트: 조합 시나리오 (~3개)`
- **문제:** 비활성 기능의 테스트는 불필요
- **수정 방향:** 제거하거나 "비활성 확인 테스트"로 축소

### Issue F (낮음): Line 491 -- 검토 이력에 Finding #5 누락
- **현재:** Deep Analysis 결과에 raw_bm25 기각만 언급
- **문제:** Finding #5 (Logger Import Crash, ~36 LOC)가 가장 중요한 실제 코드 변경인데 누락
- **수정 방향:** 검토 이력에 Finding #5 언급 추가

---

## 팀 구성

### editor (편집자)
- Issues A-F를 실제로 수정하는 역할
- 수정 전 원본 참조 필수: 41-final-report.md, 41-finding2-cluster-logic.md
- vibe-check + pal clink으로 수정안 검증
- 결과를 temp/fix-plan1-editor-output.md에 기록

### reviewer-accuracy (정확성 검증자) -- 1차 검증
- 수정된 파일을 원본 Deep Analysis 문서와 대조
- 기술적 정확성, 수치 일관성, 용어 정확성 검증
- vibe-check + pal clink으로 재확인
- 결과를 temp/fix-plan1-review1-accuracy.md에 기록

### reviewer-completeness (완전성 검증자) -- 1차 검증
- 6개 이슈가 모두 수정되었는지 확인
- 수정으로 인한 새로운 불일치가 생기지 않았는지 확인
- vibe-check + pal clink으로 재확인
- 결과를 temp/fix-plan1-review1-completeness.md에 기록

### reviewer-adversarial (적대적 검증자) -- 2차 검증
- 수정된 내용을 적대적으로 공격
- 새로운 모순, 불일치, 누락 탐색
- vibe-check + pal clink으로 재확인
- 결과를 temp/fix-plan1-review2-adversarial.md에 기록

### reviewer-fresh (신선한 눈 검증자) -- 2차 검증
- plan 파일만 읽고 (Deep Analysis 문서 참조 없이) 내부 일관성 검증
- 처음 읽는 사람 관점에서 혼란스러운 부분 식별
- vibe-check + pal clink으로 재확인
- 결과를 temp/fix-plan1-review2-fresh.md에 기록

---

## 워크플로우

```
Phase 1: editor가 6개 이슈 수정
Phase 2: reviewer-accuracy + reviewer-completeness (병렬, 1차 검증)
Phase 3: 1차 검증 피드백 반영 (필요 시)
Phase 4: reviewer-adversarial + reviewer-fresh (병렬, 2차 검증)
Phase 5: 최종 확인 및 보고
```
