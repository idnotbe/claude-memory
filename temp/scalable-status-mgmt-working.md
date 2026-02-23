# 확장 가능한 상태 관리 분석 -- Working Memory

**날짜:** 2026-02-22
**결정 사항:** 디렉토리명 = `action-plans/` (확정)
**문제:** INDEX.md는 1000개 파일에서 LLM context window 폭발 + 관리 불가

---

## 핵심 요구사항 (사용자 피드백 반영)

1. **1000개 파일에서도 작동** -- INDEX.md 하나에 다 담으면 context window 폭발
2. **LLM이 헷갈리지 않아야** -- 활성 작업만 빠르게 파악 가능해야
3. **장기적으로 말이 되어야** -- 지금 7개 → 미래 수백, 수천 개
4. **마찰 최소** -- 과도한 인프라/스크립트 없이

## 핵심 인사이트

**관찰:** 1000개 파일이 있어도 "지금 활성인 것"은 항상 소수 (5~20개).
- 완료된 계획은 더 이상 attention이 필요 없음
- LLM은 "지금 뭘 해야 하는지"만 빠르게 알면 됨
- 핵심은 "활성 집합을 작게 유지"하는 메커니즘

---

## 후보 방안

### A: Archive 패턴 (디렉토리 기반 lifecycle)
```
action-plans/
  plan-01-xxx.md          # 활성 파일 (root = active)
  plan-02-xxx.md
  _done/                   # 완료
    plan-00-xxx.md
  _archive/                # 참고/역사적
    MEMORY-CONSOLIDATION-PROPOSAL.md
```
- `ls action-plans/*.md` = 즉시 활성 목록
- LLM context: 활성 파일 수만큼만 (5~20개)

### B: Frontmatter + Query Script
```yaml
---
status: active
priority: high
summary: "검색 신뢰도 교정 및 계층적 출력"
---
```
- `python3 plan_query.py --status active` → 활성 목록
- 파일 이동 없음 (경로 안정)
- 별도 스크립트 개발/유지 필요

### C: Frontmatter + Archive 하이브리드
```
action-plans/
  plan-01-xxx.md          # frontmatter: status + summary
  _done/                   # 완료 파일 이동
  _archive/                # 참고용
```
- 활성 파일은 root에서 즉시 확인
- 각 파일에 풍부한 메타데이터
- 완료 시 `_done/`으로 이동

### D: 날짜 기반 자동 아카이빙
```
action-plans/
  2026/                    # 연도별 정리
    02/                    # 월별
      plan-xxx.md
  active/                  # 활성 파일만
```

### E: Frontmatter 단독 (디렉토리 없이)
- 모든 파일 root에 flat
- frontmatter의 status 필드로만 관리
- LLM이 전체 파일 목록을 보고 frontmatter 읽어야 함

---

## 평가 결과
- [x] Gemini: 사용 불가 (API key 미설정, non-interactive 모드에서 OAuth 불가)
- [x] Codex: 사용 불가 (ChatGPT 계정으로 codex 모델 미지원 + 사용량 한도)
- [x] Vibe-check: 통과 + 3가지 보강 피드백
- [x] 검증 R1: 핵심 비판 -- **과도한 엔지니어링**, 8개 필드 중 실제 필요한 건 1-2개
- [x] 검증 R2: 실용 검증 -- 의존성 방향 오류, CLAUDE.md 통합 누락, 참조 깨짐 5곳

## 검증에서 발견된 핵심 결함

### V1 비판 (심각도 순)
1. **HIGH: 과도한 엔지니어링** -- 7개 파일에 8-field YAML frontmatter는 과잉. retrieval-improvement-plan.md가 이미 `**Status:** IN PROGRESS` 패턴 사용 중.
2. **HIGH: 가장 단순한 해법 누락** -- 이미 1개 파일이 쓰는 `**Status:**` 패턴을 나머지 4개에도 적용하면 끝. 4줄 추가, 인프라 제로.
3. **HIGH: CLAUDE.md 통합 없음** -- LLM이 frontmatter 유지 규칙을 알 수 없음.
4. **MEDIUM: INDEX.md를 가상의 1000개 시나리오로 기각** -- 현재 5개 active 파일 = ~200 tokens.

### V2 실용 검증
1. **HIGH: Plan #2 depends_on 방향 오류** -- "의존 대상"은 "내가 의존하는 것"이 아니라 "나에게 의존하는 것". Plan #2는 독립적.
2. **HIGH: Claude가 README.md 규칙을 볼 메커니즘 없음**
3. **MEDIUM: 참조 5곳 업데이트 필요** (CLAUDE.md 2, README.md 2, SKILL.md 1)
4. **MEDIUM: retrieval-improvement-plan.md progress 정보 손실** (S5F, P3 누락)

## 진행 로그
- 작업 시작
- 리서치 완료 (KEPs, PEPs, RFCs, Backlog.md)
- 자체 분석 + 방안 A-E 비교 완료
- Vibe-check: progress 필드 추가, 이동=위생활동 프레이밍, 구체적 예시 권고
- 검증 R1: 과도한 엔지니어링 지적, 단순 **Status:** 패턴 제안
- 검증 R2: 의존성 오류, CLAUDE.md 통합 누락 확인
- **최종안 수정 중** -- 검증 피드백 전면 반영
