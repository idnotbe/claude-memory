# 확장 가능한 상태 관리 -- 심층 분석

## 대형 프로젝트 사례 연구

| 프로젝트 | 규모 | 상태 관리 방식 | LLM 친화도 |
|----------|------|--------------|:----------:|
| **Kubernetes KEPs** | 500+ | 디렉토리별 metadata.yaml 사이드카 파일 + SIG별 하위 디렉토리 | 최고 |
| **Python PEPs** | 800+ | 인라인 RFC 2822 헤더 + 자동 생성 PEP 0 인덱스 | 양호 |
| **Rust RFCs** | 3700+ | GitHub PR/Label로만 관리 (파일 내 메타데이터 없음) | 나쁨 |
| **Backlog.md** | - | 디렉토리=상태 (tasks/completed/archive/) + YAML frontmatter | 높음 |
| **Manus/Claude** | - | Progressive context disclosure + 일별 로그 | 높음 |

### 핵심 패턴 추출

**패턴 1: 디렉토리 = 상태 필터** (Backlog.md, KEPs)
- `ls active/` = 즉시 활성 항목만 보임
- LLM이 디렉토리 하나만 scan하면 됨
- 비용: 파일 이동 = 경로 변경

**패턴 2: 메타데이터를 콘텐츠와 분리** (KEPs)
- 작은 YAML 파일만 읽어 전체 현황 파악
- 80KB 마크다운을 열지 않아도 됨
- 비용: 파일 수 2배

**패턴 3: 자동 생성 인덱스** (PEPs)
- 수동 INDEX.md의 drift 문제 제거
- 단, 빌드 스크립트 필요

**패턴 4: Progressive Context Disclosure** (Manus)
- 전체를 한번에 로딩하지 않음
- 필요한 것만 점진적으로 로딩

---

## 후보 방안 재설계 (1000개 파일 스케일 기준)

### 방안 A: Frontmatter + Archive 디렉토리

```
action-plans/
  plan-01-retrieval-confidence.md     # frontmatter: status, summary
  plan-02-search-quality-logging.md
  _done/
    plan-00-old-feature.md
  _ref/
    MEMORY-CONSOLIDATION-PROPOSAL.md
    TEST-PLAN.md
```

각 파일 frontmatter:
```yaml
---
status: active          # active | blocked | done
priority: high          # high | medium | low
summary: "검색 신뢰도 교정 및 계층적 출력"
depends_on: []
created: 2026-02-22
---
```

**스케일 분석 (1000개 파일 시):**
- root: 10~20개 active 파일 → LLM context 부담 제로
- _done/: 900+ 파일 → LLM이 볼 필요 없음
- _ref/: 소수 → 필요 시만 접근

**LLM 워크플로우:**
1. `ls action-plans/*.md` → 활성 파일 목록 (10~20개)
2. 필요한 파일의 frontmatter 읽기 → 요약 + 상태 즉시 파악
3. 상세 내용 필요 시만 본문 읽기

**장점:**
- 가장 단순 (별도 스크립트/인덱스 파일 불필요)
- 어떤 규모에서든 동일한 방식 (시스템 전환 불필요)
- LLM context window 부담 최소 (active set만 보면 됨)
- frontmatter가 미래 자동화의 기반 (쿼리 스크립트 추가 가능)

**단점:**
- 파일 이동 시 경로 변경 (→ 하지만 논리명 참조이므로 실제 영향 적음)
- frontmatter 일관성 유지 필요

### 방안 B: KEP 스타일 사이드카 YAML

```
action-plans/
  plan-01-retrieval-confidence/
    plan.md
    metadata.yaml
  _done/
    plan-00-old/
      plan.md
      metadata.yaml
```

**스케일 분석:** 최고의 확장성이지만 솔로 개발자에게 과도한 구조.
**탈락 이유:** 파일 생성 시 매번 디렉토리 + 2개 파일 필요. 7개 파일에 14개 + 7개 디렉토리 = 28개 filesystem entity.

### 방안 C: Frontmatter + 자동 생성 인덱스

```
action-plans/
  _summary.yaml           # 자동 생성 (plan_index.py)
  plan-01-xxx.md
  plan-02-xxx.md
  _done/
    ...
```

**장점:** drift 없는 인덱스
**단점:** 추가 스크립트 개발/유지, 7개 파일에서는 불필요
**판단:** 방안 A의 확장 옵션으로 유지 (필요 시 추가)

### 방안 D: 순수 Frontmatter (디렉토리 분리 없이)

```
action-plans/
  plan-01-xxx.md           # status: active
  plan-02-xxx.md           # status: done
  plan-03-xxx.md           # status: active
  ...
```

**스케일 문제:** 1000개 파일 시 LLM이 모든 frontmatter를 읽어야 활성 항목 파악 가능.
**탈락 이유:** LLM context window 요구사항 위반.

---

## 방안 A 세부 설계

### 디렉토리 구조

```
action-plans/
  README.md                               # 시스템 설명 + 규칙
  plan-01-retrieval-confidence.md          # Active
  plan-02-search-quality-logging.md        # Active
  plan-03-poc-experiments.md               # Active
  plan-04-guardian-conflict-fix.md         # Active
  retrieval-improvement-plan.md            # Active (legacy format)
  _done/                                    # 완료된 계획
  _ref/                                     # 참고/역사적 문서
    MEMORY-CONSOLIDATION-PROPOSAL.md
    TEST-PLAN.md
```

### Frontmatter 스키마

```yaml
---
plan_id: plan-01                    # 고유 논리 식별자
title: "Retrieval Confidence & Output"
status: active                       # active | blocked | done
priority: high                       # high | medium | low
summary: "검색 신뢰도 교정, 클러스터 감지, 계층적 출력 도입"
depends_on: []                       # 논리 ID로 참조: ["plan-01"]
created: 2026-02-22
updated: 2026-02-22
---
```

### Lifecycle 규칙

1. **새 plan 생성**: root에 파일 생성 + frontmatter 작성
2. **상태 변경**: frontmatter의 `status` 필드 수정
3. **완료 시**: `status: done`으로 변경 → `_done/`으로 이동
4. **참고 전환**: `_ref/`로 이동
5. **활성 목록 확인**: `ls action-plans/*.md` (README.md 제외하면 = 활성 목록)

### 경로 안정성 검증

| 참조 유형 | 현재 상태 | 영향 |
|-----------|----------|------|
| plan 파일 간 참조 | 논리명 ("Plan #1") | **영향 없음** -- 이동해도 깨지지 않음 |
| CLAUDE.md → plan 파일 | `plans/TEST-PLAN.md` | **어차피 수정 필요** (action-plans/ 변경) |
| README.md → plan 파일 | `plans/TEST-PLAN.md` | **어차피 수정 필요** |

### README.md 내용

```markdown
# Action Plans

실행 계획 관리 디렉토리.

## 규칙
- root의 .md 파일 = 활성 계획 (진행 중 또는 대기)
- 완료된 계획 → `_done/`으로 이동
- 참고/역사적 문서 → `_ref/`로 이동
- 모든 plan 파일에 YAML frontmatter 필수 (status, summary, priority)
- plan 간 참조는 논리 ID 사용 (예: "Plan #1")

## Status Values
- `active`: 현재 진행 중 또는 다음 실행 대상
- `blocked`: 의존성 미해결로 대기
- `done`: 완료 (→ _done/으로 이동)
```

---

## 자기비판

### 이 방안의 잠재적 약점

1. **"_done으로 이동"이 귀찮을 수 있음**: `mv` 한 번이지만 잊을 수 있다
   - 대응: status를 done으로 바꾸면 됨. 이동은 루트가 지저분해질 때 batch로 해도 됨

2. **README.md가 또 다른 관리 대상이 되는 것은 아닌가?**:
   - 대응: README.md는 규칙 설명이므로 거의 바뀌지 않음. INDEX.md와 다름.

3. **frontmatter를 잊고 안 쓸 수 있음**:
   - 대응: CLAUDE.md에 규칙 명시. Claude가 plan 생성 시 자동으로 frontmatter 포함하도록.

4. **1000개 중 active가 50개면?**: root에 50개도 꽤 많음
   - 대응: 그때 `_backlog/` 추가하여 "시작 전" 구분 가능. 하지만 50개 active는 비정상적.

5. **_done/ 내부가 1000개면 찾기 어려움**:
   - 대응: _done/ 내부를 연도별로 구분 가능 (`_done/2026/`). 하지만 done은 거의 참조 안 하므로 우선순위 낮음.
