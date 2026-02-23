# 확장 가능한 상태 관리 -- 최종 추천안

**날짜:** 2026-02-22
**분석 방법:** 웹 리서치 (KEPs, PEPs, RFCs, Backlog.md) → 자체 분석 → Vibe-check → 검증 2라운드
**외부 도구:** Gemini CLI / Codex CLI 사용 불가 (API 키/한도). 웹 리서치 + vibe-check로 보완.

---

## 추천: Frontmatter + Archive 디렉토리

### 핵심 원리

1. **Frontmatter가 본질** -- 각 파일이 자신의 상태를 스스로 선언 (status, progress, priority, summary)
2. **디렉토리 이동은 위생 활동** -- root이 지저분해지면 done 파일들을 `_done/`으로 일괄 정리. 필수가 아님.
3. **LLM은 root만 보면 됨** -- active set는 항상 소수 (5~20개)

### 디렉토리 구조

```
action-plans/
  README.md                               # 시스템 규칙 (거의 안 바뀜)
  plan-01-retrieval-confidence.md          # Active
  plan-02-search-quality-logging.md        # Active
  plan-03-poc-experiments.md               # Active
  plan-04-guardian-conflict-fix.md         # Active
  retrieval-improvement-plan.md            # In progress (legacy)
  _done/                                    # 완료 파일 (batch 이동)
  _ref/                                     # 참고/역사적 문서
    MEMORY-CONSOLIDATION-PROPOSAL.md
    TEST-PLAN.md
```

### Frontmatter 스키마

```yaml
---
plan_id: plan-01
title: "Retrieval Confidence & Output"
status: active                        # active | blocked | done
priority: high                        # high | medium | low
progress: "미시작. Action #1부터 구현 예정"
summary: "검색 신뢰도 교정, 클러스터 감지, 계층적 출력"
depends_on: []                        # 논리 ID: ["plan-01"]
created: 2026-02-22
updated: 2026-02-22
---
```

**`progress` 필드가 핵심.** 이것이 사용자가 원하는 "상세 진행 상황 가시성"을 제공:
- `"미시작. Action #1부터 구현 예정"`
- `"Step 3/7 완료. Action #4 시작 대기"`
- `"S4 tests 다음. S1-S3, S5 완료"`

### Lifecycle 규칙

```
새 plan 생성
  → root에 파일 + frontmatter 작성

작업 시작
  → status: active, progress 업데이트

작업 완료
  → status: done, progress: "완료"
  → (선택) _done/으로 이동 (root 정리 시)

참고 전환
  → _ref/로 이동
```

**핵심: status 변경만 하면 됨. 파일 이동은 선택.**

### 왜 이 방식이 1000개에서도 작동하는가

| 시나리오 | root 파일 수 | LLM context 부담 | 관리 난이도 |
|----------|:-----------:|:---------------:|:----------:|
| 현재 (7개) | 5 active + README | 최소 | 최소 |
| 30개 | 10~15 active | 작음 | 낮음 |
| 100개 | 10~20 active | 작음 | 낮음 |
| 1000개 | 10~20 active | 작음 | 낮음 |

**비결:** Active set는 자연적으로 bounded. 완료된 건 `_done/`으로 이동하므로 root은 항상 깨끗.

### LLM 워크플로우

```
1. ls action-plans/*.md
   → 활성 파일 목록 (10~20개)

2. 각 파일의 frontmatter 읽기 (처음 ~10줄)
   → status, progress, priority 즉시 파악
   → "다음에 뭘 해야 하는지" 결정

3. 필요한 파일만 본문 읽기
   → 상세 실행 계획 확인
```

**INDEX.md 대비 장점:** 1000개 파일이어도 LLM은 20개 frontmatter만 읽으면 됨 (INDEX.md는 1000줄 전부 읽어야 함).

### 현재 7개 파일 마이그레이션 구체 예시

#### 1. plan-01-retrieval-confidence.md (현재 plan-retrieval-confidence-and-output.md)
```yaml
---
plan_id: plan-01
title: "Actions #1-#4 구현 계획"
status: active
priority: high
progress: "미시작. Action #1 (confidence_label 개선)부터 시작"
summary: "검색 신뢰도 교정, 클러스터 감지, 계층적 출력, 0-result hint 개선"
depends_on: []
created: 2026-02-22
updated: 2026-02-22
---
```

#### 2. plan-02-search-quality-logging.md (현재 plan-search-quality-logging.md)
```yaml
---
plan_id: plan-02
title: "로깅 인프라스트럭처"
status: active
priority: high
progress: "미시작. Plan #1 완료 후 진행"
summary: "구조화된 JSONL 로깅 인프라 구축 (검색 품질 측정, PoC 지원)"
depends_on: ["plan-01"]
created: 2026-02-22
updated: 2026-02-22
---
```

#### 3. plan-03-poc-experiments.md (현재 plan-poc-retrieval-experiments.md)
```yaml
---
plan_id: plan-03
title: "PoC 실험 계획"
status: active
priority: medium
progress: "미시작. Plan #2 (로깅) 완료 후 진행"
summary: "Agent Hook, BM25 정밀도, OR-query 정밀도, Nudge 준수율 PoC 4건"
depends_on: ["plan-02"]
created: 2026-02-22
updated: 2026-02-22
---
```

#### 4. plan-04-guardian-conflict-fix.md (현재 plan-guardian-conflict-memory-fix.md)
```yaml
---
plan_id: plan-04
title: "Guardian 충돌 메모리 측 수정"
status: active
priority: high
progress: "미시작. SKILL.md 강화 + PreToolUse:Bash staging guard 구현"
summary: "Guardian false positive 팝업 제거 (SKILL.md 강화 + staging guard hook)"
depends_on: []
created: 2026-02-22
updated: 2026-02-22
---
```

#### 5. retrieval-improvement-plan.md → root 유지
```yaml
---
plan_id: retrieval-master
title: "Final Retrieval Improvement Plan"
status: active
priority: high
progress: "S1-S3, S5 완료. S4 (tests) 다음"
summary: "FTS5 BM25 엔진 + LLM-as-judge 검증 레이어 (마스터 플랜)"
depends_on: []
created: 2026-02-20
updated: 2026-02-22
---
```

#### 6. MEMORY-CONSOLIDATION-PROPOSAL.md → `_ref/`로 이동
역사적 문서. 더 이상 실행 대상 아님. frontmatter 불필요.

#### 7. TEST-PLAN.md → `_ref/`로 이동
테스트 전략 참고 문서. CLAUDE.md에서 참조됨. frontmatter 불필요.

---

## INDEX.md 대비 비교

| 기준 | INDEX.md | Frontmatter + Archive |
|------|----------|----------------------|
| 1000개 파일 | context window 폭발 (25K+ tokens) | Active 20개 frontmatter만 (~2K tokens) |
| LLM 혼란 | 1000줄 테이블 파싱 | 작은 YAML 블록 파싱 |
| 상세 progress | INDEX.md에 한줄로 축약 | frontmatter progress 필드에 상세 기록 |
| 동기화 drift | INDEX.md ↔ 파일 내용 불일치 위험 | 파일 자체가 source of truth (drift 없음) |
| "다음 할 일" 파악 | 테이블 전체 스캔 | ls root + frontmatter 읽기 |
| 관리 비용 | 매 변경마다 INDEX.md 수정 | frontmatter만 수정 (자기 완결적) |

---

## 확장 전략 (미래 대비)

| 시점 | 추가 조치 |
|------|-----------|
| 30개+ 파일 | `_done/` 내부를 연도별 구분 (`_done/2026/`) |
| 50개+ active | `_backlog/` 추가 (미시작 vs 진행 중 분리) |
| 100개+ 파일 | 간단한 query 스크립트 (`plan_query.py --status active --priority high`) |
| 자동화 필요 시 | 기존 `memory_index.py` 패턴 재활용하여 자동 요약 생성 |

모든 확장은 **현재 frontmatter 스키마 위에** 올라감. 시스템 전환 불필요.
