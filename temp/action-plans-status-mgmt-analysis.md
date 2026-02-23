# Q2: 파일 상태 관리 분석

## 현재 문제

파일 7개에서 이미 혼란 발생:
- 일부 파일만 헤더에 Status 명시 (retrieval-improvement-plan.md: "Status: IN PROGRESS")
- 나머지 파일은 상태 정보 없음
- 파일 간 의존성(Plan #2 → Plan #1 의존)이 있지만 파일명에 반영 안 됨
- `ls`만으로 어떤 파일이 진행 중인지 알 수 없음

## 핵심 요구사항

1. **한눈에 파악** -- ls나 파일 목록만 봐도 상태가 보여야 함
2. **마찰 최소** -- 상태 변경이 번거로우면 안 됨
3. **20개+ 확장** -- 파일이 늘어나도 관리 가능해야 함
4. **plain markdown + git** -- 특별한 도구 불필요
5. **안정적 파일 경로** -- 다른 문서에서 참조 시 깨지면 안 됨 (CLAUDE.md, SKILL.md 등에서 참조)

## 후보 방안 심층 평가

### A: 디렉토리 기반 칸반 (todo/doing/done/)

```
plans/
  backlog/
    memory-consolidation.md
  active/
    test-plan.md
  done/
    folder-restructure.md
```

| 장점 | 단점 |
|------|------|
| ls만으로 즉시 상태 파악 | **파일 이동 시 경로 변경** → 다른 문서의 참조 깨짐 |
| mv 명령어 하나로 상태 변경 | git blame/history가 rename으로 분절 |
| 직관적, 도구 불필요 | 의존성 표현 불가 |

**치명적 단점:** 이 프로젝트에서 action plan 파일들은 CLAUDE.md나 다른 plan 파일에서 참조됨 (예: Plan #3 문서 내 "의존성: Plan #2"). 파일이 이동하면 이 참조들이 모두 깨진다.

**자기비판:** 칸반 방식은 직관적이지만, 이 프로젝트의 파일들은 상호 참조가 많아 경로 안정성이 중요. 단순한 todo 리스트가 아닌 "계획 문서"이므로 칸반은 부적합.

### B: YAML Frontmatter

```yaml
---
id: plan-01
title: "Retrieval Confidence & Output"
status: active  # draft | active | done | archived
priority: high
depends_on: []
created: 2026-02-22
updated: 2026-02-22
---
```

| 장점 | 단점 |
|------|------|
| 경로 안정적 | **ls만으로 상태 안 보임** -- 파일 열어야 함 |
| 풍부한 메타데이터 | 모든 파일에 일관된 frontmatter 유지 필요 |
| grep으로 검색 가능 | 기존 파일 7개 모두 수정 필요 |
| 20개+ 확장 우수 | 한눈에 파악하려면 추가 도구/스크립트 필요 |

**자기비판:** 가장 "올바른" 접근이지만, "한눈에 파악" 요구사항을 단독으로 충족하지 못함. 보조 수단이 필요.

### C: 중앙 인덱스 파일 (INDEX.md)

```markdown
# Plans Index

| # | Plan | Status | Depends On | Updated |
|---|------|--------|-----------|---------|
| 1 | [Retrieval Confidence](./plan-retrieval-confidence-and-output.md) | Active | - | 2026-02-22 |
| 2 | [Search Quality Logging](./plan-search-quality-logging.md) | Pending | #1 | 2026-02-22 |
| 3 | [PoC Experiments](./plan-poc-retrieval-experiments.md) | Pending | #2 | 2026-02-22 |
| 4 | [Guardian Conflict Fix](./plan-guardian-conflict-memory-fix.md) | Active | - | 2026-02-22 |
```

| 장점 | 단점 |
|------|------|
| 한눈에 전체 상태 파악 (가장 우수) | 인덱스 수동 관리 필요 (drift 위험) |
| 의존성 관계 표현 가능 | 파일 추가 시 인덱스도 수정 필요 |
| GitHub/에디터에서 렌더링 우수 | 인덱스-현실 불일치 가능 |
| 경로 안정적 | |

**자기비판:** "대시보드" 역할로는 최고이지만, 인덱스와 실제 파일의 동기화가 깨질 수 있다는 약점이 있음.

### D: 파일명 접두사/접미사

```
plans/
  01-active--plan-retrieval-confidence.md
  02-pending--plan-search-quality-logging.md
  03-pending--plan-poc-experiments.md
  04-active--plan-guardian-conflict-fix.md
  99-done--retrieval-improvement-plan.md
```

| 장점 | 단점 |
|------|------|
| ls에서 즉시 상태+순서 파악 | **상태 변경 = 파일명 변경** → 참조 깨짐 |
| 정렬 지원 | 파일명이 장황해짐 |
| 도구 불필요 | git history 분절 |

**자기비판:** 디렉토리 칸반과 동일한 "경로 불안정" 문제. 이 프로젝트에서는 부적합.

### E: 하이브리드 (Frontmatter + INDEX.md)

```
plans/
  INDEX.md                              # 대시보드 테이블
  plan-01-retrieval-confidence.md       # frontmatter에 status
  plan-02-search-quality-logging.md     # frontmatter에 status
  ...
```

| 장점 | 단점 |
|------|------|
| 한눈에 파악 (INDEX.md) | 두 곳(frontmatter + INDEX)을 모두 관리 |
| 풍부한 메타데이터 (frontmatter) | 동기화 필요 |
| 경로 안정적 | 약간의 중복 |
| grep + 대시보드 모두 지원 | |

**자기비판:** 가장 robust하지만 약간 over-engineering 느낌. 이 프로젝트 규모(7~20개 파일)에 두 시스템을 유지할 필요가 있는가?

### F: INDEX.md 단독 (Frontmatter 없이)

```
plans/
  INDEX.md                              # 유일한 상태 추적 소스
  plan-01-retrieval-confidence.md       # 내용만 (상태 없음)
  plan-02-search-quality-logging.md
  ...
```

| 장점 | 단점 |
|------|------|
| 관리 포인트 하나 (INDEX.md만) | 개별 파일에서 상태 확인 불가 |
| drift 문제 감소 (단일 소스) | grep 기반 상태 검색 불가 |
| 경로 안정적 | |

**자기비판:** 단순함이 장점. 파일 20개 수준에서는 INDEX.md 하나로 충분할 수 있음. Frontmatter는 파일이 50개 이상이 되거나 자동화가 필요해질 때 도입해도 늦지 않음.

---

## 평가 매트릭스

| 기준 (가중치) | 디렉토리 칸반 | YAML 단독 | INDEX.md 단독 | 파일명 접두사 | 하이브리드 |
|--------------|:-----------:|:---------:|:------------:|:-----------:|:---------:|
| 한눈에 파악 (30%) | 5 | 2 | 5 | 5 | 5 |
| 마찰 최소 (25%) | 4 | 3 | 4 | 2 | 3 |
| 확장성 20+ (15%) | 3 | 5 | 4 | 3 | 5 |
| 경로 안정 (20%) | 1 | 5 | 5 | 1 | 5 |
| git 친화 (10%) | 3 | 5 | 4 | 2 | 5 |
| **가중 합계** | **3.3** | **3.5** | **4.5** | **2.8** | **4.5** |

## 최종 판단 (내 분석)

**1위: INDEX.md 단독** -- 이 프로젝트 규모(7~20개)에서 최적의 단순성/효과 비율

이유:
- 관리 포인트가 하나뿐 (drift 최소화)
- 한눈에 전체 현황 파악 가능
- 파일 경로 안정적
- 의존성 관계도 표현 가능
- 향후 필요 시 frontmatter 추가로 확장 가능 (점진적 개선)

**2위: Frontmatter + INDEX.md 하이브리드** -- 파일이 30개 이상으로 늘어나면 전환

**탈락:** 디렉토리 칸반, 파일명 접두사 (경로 안정성 치명적), YAML 단독 (한눈에 파악 실패)
