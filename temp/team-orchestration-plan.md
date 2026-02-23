# Team Orchestration Plan: plan-poc 완전 반영 작업

**작성일:** 2026-02-22
**목표:** Deep Analysis 10개 항목을 plan-poc-retrieval-experiments.md에 완전 반영

## 작업 항목 (감사 결과 기반)

### 반영 필요 항목
1. **Finding #1 (PARTIAL→YES):** raw_bm25 코드 변경 REJECTED 명시, abs_floor composite domain 교정, NEW-4 이유 기재
2. **Finding #2 (NO→YES):** Plan #1 범위이나 cross-reference 노트 추가 (PoC #5 독립변수 축소 영향)
3. **Finding #3 (YES):** 이미 반영 -- 확인만
4. **Finding #4 (YES):** 이미 반영 -- 확인만
5. **Finding #5 (NO→YES):** 로깅 안정성 의존성 노트 추가, e.name scoping 패턴 언급
6. **NEW-1 (PARTIAL→YES):** defer to PoC #5 처분 명시, body_bonus noise floor 왜곡 상세
7. **NEW-2 (NO→YES):** Judge import 취약성 + Finding #5로 해결됨 노트
8. **NEW-3 (NO→YES):** Empty XML 이슈 기재
9. **NEW-4 (PARTIAL→YES):** ranking-label inversion 구체 시나리오 + raw_bm25 REJECTED 이유
10. **NEW-5 (NO→YES):** e.name scoping으로 해결됨 노트

### 추가 수정
11. **PoC #6 체크리스트:** `--session-id` CLI 파라미터 구현을 별도 체크 항목으로 추가

## 팀 구성

### Phase 1: 편집 (Editor + Context Specialist)
- **editor:** plan-poc 파일 직접 편집. 10개 항목 + 1개 체크리스트 수정
- **context-specialist:** 원본 분석 파일(41-*.md)에서 정확한 내용을 추출하여 editor에게 파일로 전달

### Phase 2: 검증 Round 1 (3명 독립 검증)
- **v1-accuracy:** 10개 항목이 정확히 반영되었는지 라인별 대조
- **v1-consistency:** plan 내부 일관성 검증 (기존 내용과 새 내용 간 모순 없는지)
- **v1-completeness:** 누락 없이 전부 반영되었는지, 그리고 불필요한 것이 추가되지 않았는지

### Phase 3: 검증 Round 2 (2명 독립 검증 + 외부 모델)
- **v2-adversarial:** 적대적 관점에서 오류/모순/누락 탐색
- **v2-fresh-eyes:** plan만 읽고 이해 가능한지 fresh perspective 검증

## 파일 기반 소통 규칙
- Input: `temp/editor-input-*.md` (context-specialist → editor)
- Output: 편집된 plan 파일 자체
- 검증 결과: `temp/v1-*.md`, `temp/v2-*.md`
