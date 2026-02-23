# Editor Output: plan-retrieval-confidence-and-output.md 수정 완료

**작성일:** 2026-02-22
**대상 파일:** `action-plans/plan-retrieval-confidence-and-output.md`

---

## 수정 결과 요약

6개 이슈 모두 수정 완료.

### Issue A (높음): Line 103 -- post-truncation counting 설명 수정
- **수정 전:** `cluster_count: ratio > 0.90인 결과 수 (복합 점수 기반 ratio). 주의: max_inject에 의해 결과가 잘린 후의 집합에서 계산.`
- **수정 후:** `cluster_count: ratio > 0.90인 결과 수 (복합 점수 기반 ratio). **현재 비활성** -- 호출 시 항상 0 전달. 향후 활성화 시 pre-truncation counting으로 구현 필요 (Deep Analysis: post-truncation counting은 dead code, temp/41-finding2-cluster-logic.md 참조).`
- **근거:** Finding #2가 post-truncation counting은 수학적으로 dead code임을 증명. "잘린 후 집합에서 계산"이라는 설명은 정면 충돌. 현재 비활성 상태(항상 0 전달)를 명시하고 향후 활성화 시 pre-truncation counting 필요를 기록.

### Issue B (중간): Line 141 -- 비활성 기능 구현 체크리스트 수정
- **수정 전:** `- [ ] 클러스터 감지 로직 구현: cluster_count >= 3이면 최대 "medium"`
- **수정 후:** `- [ ] 클러스터 감지 기능 비활성 유지 확인 (Deep Analysis: post-truncation counting은 dead code. 향후 활성화 시 pre-truncation counting으로 재구현)`
- **근거:** Deep Analysis 결론 -- "비활성 기능에 대한 구현은 불필요한 엔지니어링". 구현 체크리스트가 아닌 비활성 유지 확인 항목으로 변경.

### Issue C (낮음): Line 68 -- "BM25 모드" 구식 표현 수정
- **수정 전:** `권장 시작값: BM25 모드에서 1.0-2.0`
- **수정 후:** `권장 시작값: 복합 점수 도메인 기준 1.0-3.0`
- **근거:** confidence_label은 복합 점수(BM25 - body_bonus)를 사용하므로 "BM25 모드"는 부정확. line 102의 "복합 점수 도메인 기준 교정"과 용어 통일.

### Issue D (낮음): Line 68 vs 102 -- abs_floor 권장값 통일
- **수정 전:** line 68은 `1.0-2.0`, line 102는 `1.0-3.0`
- **수정 후:** 둘 다 `1.0-3.0`
- **근거:** Issue C와 동시 수정. 복합 점수 도메인(대략 0-15 범위)에서의 권장 시작값은 1.0-3.0이 적절.

### Issue E (중간): Lines 148-149 -- obsolete 클러스터 테스트 축소
- **수정 전:** `- [ ] 단위 테스트: 클러스터 감지 (~5개)` + `- [ ] 단위 테스트: 조합 시나리오 (~3개)` (총 ~8개 테스트)
- **수정 후:** `- [ ] 단위 테스트: cluster_count=0 기본값 시 기존 동작 유지 확인 (~2개)`
- **근거:** 비활성 기능의 구현 테스트(~8개)는 불필요. cluster_count 파라미터는 시그니처에 남아있으므로, 기본값 0에서 기존 동작 유지만 확인하는 최소 테스트(~2개)로 축소.

### Issue F (낮음): Line 490 -- 검토 이력에 Finding #5 추가
- **수정 전:** `Ranking-label inversion (NEW-4) breaks tiered output. Composite score is intentional. Cluster tautology proven dead code.`
- **수정 후:** `Ranking-label inversion (NEW-4) breaks tiered output. Composite score is intentional. Cluster tautology proven dead code. Import hardening (Finding #5, ~36 LOC): module-level try/except + e.name scoping for memory_logger/judge imports.`
- **근거:** Finding #5는 Deep Analysis에서 가장 중요한 실제 코드 변경(~36 LOC, 부분 배포 시 hook crash 방지)이며 검토 이력에서 누락되어 있었음.

---

## 외부 검증 결과

### Codex 5.3
- **상태:** 사용 불가 (usage limit 도달)

### Gemini 3.1 Pro (via pal clink, codereviewer role)
- **Issue A/B 수정:** "Deep Analysis의 수학적 증명을 완벽히 반영한 훌륭한 결정" -- APPROVED
- **cluster_count 시그니처 유지:** "적절하다. 향후 하위 호환성을 위한 좋은 설계" -- APPROVED
- **추가 발견 (HIGH):** 문서 내 잔존하는 cluster_count 계산 지시 (Lines 106, 119-121, 142, 255)가 비활성화 결정과 모순
- **추가 발견 (LOW):** Line 110 "이번 변경으로 해결된다"가 클러스터 감지 보류와 모순

### Gemini 추가 발견 대응 (2차 수정)

Gemini가 발견한 잔존 모순은 Issues A/B/E와 동일한 root cause (cluster detection 비활성화의 cascade effect)이므로 추가 수정 실행:

1. **Line 106:** `cluster_count 계산 필요` -> `cluster_count=0 전달 (비활성)` 으로 수정
2. **Lines 119-121:** 클러스터 관련 테스트 3줄 -> `cluster_count=0 기본값 확인 (~2개)` 1줄로 축소
3. **Line 117:** 신규 테스트 수 `~15-25개` -> `~10-12개`로 조정 (클러스터 테스트 삭감 반영)
4. **Line 255:** `cluster_count 계산 로직 구현` -> `cluster_count=0 고정 전달 확인 (비활성)` 으로 수정
5. **Line 110:** `이번 변경으로 해결된다` -> `abs_floor를 도입하여 점수 미달 결과가 "high"로 분류되는 오분류를 우선 방어한다` 로 수정

---

## 완전성 검증 피드백 대응 (3차 수정)

### 추가 이슈: Line 474 `cluster_detection_enabled, default: true` 불일치
- **수정 전:** `클러스터 감지 설정 토글 추가 (cluster_detection_enabled, default: true)`
- **수정 후:** `클러스터 감지 설정 토글 추가 (cluster_detection_enabled, default: false)`
- **근거:** 2차 리뷰 합의 당시에는 `default: true`였으나, Deep Analysis 이후 최종 결정이 `false`로 변경됨 (Line 72, 77, 78, 127, 133, 413 모두 `false`). Line 474만 구버전 값이 잔존하는 pre-existing 불일치.

---

## 내부 일관성 확인 (최종)

수정 후 문서 내 `cluster_detection_enabled` 전수 조사:
- Line 72 (`default: false`): 일치
- Line 77 (`cluster_detection_enabled: false`): 일치
- Line 78 (`cluster_detection_enabled: false`): 일치
- Line 127 (`"cluster_detection_enabled": false`): 일치
- Line 133 (`cluster_detection_enabled: false`): 일치
- Line 413 (`cluster_detection_enabled: false`): 일치
- Line 474 (`default: false`): 일치 (이번 수정)

기타 교차 참조:
- Line 68 (`1.0-3.0`) = Line 102 (`1.0-3.0`): 일치
- Line 103 (비활성, 항상 0) = Line 106 (cluster_count=0 전달) = Line 141 (비활성 유지 확인): 일치
- Line 103 (pre-truncation counting 필요) = Line 76 (Option B 언급): 일치
- Line 110 (abs_floor로 우선 방어) = Line 141 (클러스터 감지 보류): 일치
- Line 119 (cluster_count=0 테스트 ~2개) = Line 148 (cluster_count=0 테스트 ~2개): 일치
- Line 255 (cluster_count=0 고정 전달 확인) = Line 103 (항상 0 전달): 일치
- Line 490 (Finding #5 포함) = Final report 핵심 발견: 일치

`cluster_detection_enabled` 관련 불일치 모두 해소됨. 새로운 모순 없음.

---

## 수정 총괄

| 구분 | 항목 수 | 범위 |
|------|--------|------|
| 원본 이슈 수정 (A-F) | 6건 | 브리핑에서 지정된 이슈 |
| Gemini 추가 발견 수정 | 5건 | cluster detection 비활성화의 cascade 불일치 |
| 완전성 검증 추가 발견 수정 | 1건 | Line 474 `default: true` -> `false` (pre-existing 불일치) |
| **총 수정** | **12건** | |
