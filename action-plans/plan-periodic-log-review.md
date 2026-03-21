---
status: active
progress: "프로세스 정의 완료. 첫 리뷰 실행 대기."
---

# Periodic Log Review

## 목적

claude-memory 로깅 데이터를 주기적으로 분석하여 오류와 개선점을 사전 감지한다. memory_log_analyzer.py 보고서를 기반으로 severity별 대응 체계를 운영하고, 발견된 이슈에 대해 개별 action plan을 생성하여 추적한다.

## 주기

- 매주 1회 또는 로깅 이벤트 100건 이상 축적 시 (둘 중 먼저 도래하는 조건)

## 실행 절차

### Step 1: 로그 분석 실행
- [ ] memory_log_analyzer.py 실행
  ```bash
  python3 hooks/scripts/memory_log_analyzer.py --root <project>/.claude/memory --format json
  ```
- [ ] 출력된 JSON 보고서를 확인하여 분석 기간과 총 이벤트 수 파악

### Step 2: 보고서 분석
- [ ] critical/high severity findings 확인
- [ ] 반복 패턴 및 에러 클러스터 식별
- [ ] 이전 리뷰 대비 추세 변화 확인

### Step 3: Critical/High 대응
- [ ] critical/high 발견 시 → 개별 action plan 생성 (`action-plans/plan-fix-<issue-code>.md`)
- [ ] 생성된 action plan에 frontmatter (`status: not-started`) 설정
- [ ] 긴급도에 따라 즉시 대응 또는 다음 작업 세션에 배정

### Step 4: Medium/Low 대응
- [ ] medium 발견 시 → 기존 backlog에 추가 또는 관련 action plan에 병합
- [ ] low 발견 시 → 기록만 하고 무시 가능

### Step 5: 리뷰 결과 기록
- [ ] 리뷰 결과를 `action-plans/_ref/log-review-YYYY-MM-DD.md`에 기록
- [ ] 기록 형식:
  - 리뷰 날짜
  - 분석 기간 (시작일 ~ 종료일)
  - 총 이벤트 수
  - severity별 발견 건수 (critical / high / medium / low)
  - 생성된 action plan 목록 (파일명 + 요약)

### Step 6: 추적
- [ ] 생성된 action plan의 status를 추적
- [ ] 이전 리뷰에서 생성된 미완료 action plan 진행 상황 확인
- [ ] 완료된 action plan은 `action-plans/_done/`으로 이동

## 대상 프로젝트

`logging.enabled: true`인 모든 프로젝트. 현재 대상: **ops**.

## 자동화 가능성

향후 `/review-logs` skill로 자동화 가능. Step 1~2를 자동 실행하고, critical/high 발견 시 사용자에게 알림 후 action plan 생성을 제안하는 흐름으로 구성할 수 있다.

## 기록 형식

각 리뷰 결과 파일(`action-plans/_ref/log-review-YYYY-MM-DD.md`)은 다음 형식을 따른다:

| 항목 | 내용 |
|------|------|
| 리뷰 날짜 | YYYY-MM-DD |
| 분석 기간 | YYYY-MM-DD ~ YYYY-MM-DD |
| 총 이벤트 수 | N건 |
| Critical | N건 |
| High | N건 |
| Medium | N건 |
| Low | N건 |
| 생성된 action plan | `plan-fix-<code>.md` -- 요약 |
