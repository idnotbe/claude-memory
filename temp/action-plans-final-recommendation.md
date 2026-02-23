# Action Plans 폴더 개선 -- 최종 분석 보고서

**날짜:** 2026-02-22
**분석 방법:** 자체 분석 → 웹 리서치 (업계 베스트 프랙티스) → Vibe-check → 독립 검증 2라운드 → 종합
**외부 도구:** Gemini CLI / Codex CLI 사용 불가 (API 키 미설정 / 사용량 한도). 웹 리서치 + vibe-check로 대체.

---

## 핵심 발견 사항 (검증에서 드러난 사실)

### Git 상태의 진실

| 사실 | 의미 |
|------|------|
| 최근 커밋 `6d0d597`이 `plans/`를 생성하고 3개 파일 이동 | `plans/`는 이미 커밋된 canonical name |
| 커밋 메시지: "Create plans/ folder for **action plans** and progress tracking" | 사용자는 이 파일들을 "action plans"로 인식 |
| 커밋 후 working tree에서 `plans/` → `action plans/`로 수동 변경 (미커밋) | 사용자가 `plans/`에 **불만족**하여 이름 변경 시도 |
| CLAUDE.md (L75, L99)와 README.md (L442)가 `plans/TEST-PLAN.md` 참조 | `plans/` 유지 시 참조 수정 불필요 |

**이 발견이 중요한 이유:** 사용자가 `plans/`를 커밋한 직후 `action plans/`로 바꾼 것은 `plans/`가 너무 일반적이라고 느꼈기 때문일 가능성이 높다. 하지만 공백이 포함된 이름의 문제점을 인식하고 이제 최적의 이름을 찾고 있다.

---

## Q1: 디렉토리 명칭 -- Best 추천

### 최종 추천: `plans/`

| 평가 기준 | 점수 | 근거 |
|-----------|------|------|
| **프로젝트 컨벤션** | 5/5 | hooks/, assets/, commands/, skills/, tests/, temp/, research/와 100% 동일 패턴 |
| **쉘 호환성** | 5/5 | 공백/특수문자 없음 |
| **기존 참조 호환** | 5/5 | CLAUDE.md, README.md의 `plans/TEST-PLAN.md` 참조가 그대로 동작 -- 수정 비용 제로 |
| **의미 명확성** | 3.5/5 | "plans"만으로 약간 일반적이지만, INDEX.md 도입으로 보완 |
| **간결성** | 5/5 | 6글자, 가장 짧은 후보 |
| **업계 사례** | 5/5 | Go: `design/`, Swift: `proposals/`, 대형 OSS 프로젝트 대부분 단일 단어 |

### 차선: `action-plans/` (kebab-case)

| 평가 기준 | 점수 | 근거 |
|-----------|------|------|
| **프로젝트 컨벤션** | 3.5/5 | 프로젝트의 사용자 정의 디렉토리는 모두 단일 단어. `.claude-plugin/`은 프레임워크 강제 |
| **쉘 호환성** | 5/5 | 공백 없음 |
| **기존 참조 호환** | 2/5 | CLAUDE.md 2곳, README.md 1곳 수정 필요 |
| **의미 명확성** | 5/5 | "실행 계획"이라는 의미가 가장 명확 |
| **간결성** | 3/5 | 13글자 |

### 왜 `plans/`를 추천하는가

1. **수정 비용 제로**: 이미 커밋된 이름이므로 CLAUDE.md/README.md 참조 수정 없이 사용 가능
2. **컨벤션 100% 일치**: 프로젝트 내 유일한 예외가 되지 않음
3. **의미 부족은 INDEX.md로 보완**: INDEX.md 첫 줄에 "실행 계획(Action Plans) 관리 대시보드"라고 명시하면 폴더의 목적이 명확해짐
4. **업계 표준**: 단일 lowercase 단어가 대세

### `plans/`의 약점과 대응

| 약점 | 대응 |
|------|------|
| "plans"가 너무 일반적 | INDEX.md 설명으로 보완. 프로젝트 내 다른 "plans" 개념 없음 |
| Claude Code "plan mode"와 혼동 가능? | 실제 충돌 없음 -- plan mode는 빌트인 기능이고 디렉토리와 무관. 대화에서 "plans 폴더"로 지칭하면 됨 |
| 사용자가 이전에 plans/에서 action plans/로 바꾼 이력 | 이번에 INDEX.md를 추가하여 "actions plans"로서의 목적을 명확히 하면 이전 불만 해소 |

### 결론

> **`plans/`** 를 추천하되, 사용자가 "action"이라는 수식어를 강하게 원한다면 **`action-plans/`** (kebab-case)도 좋은 선택.

---

## Q2: 파일 상태 관리 -- Best 추천

### 최종 추천: INDEX.md 단독 (단일 소스 대시보드)

**왜 이 방식인가:**

| 요구사항 | INDEX.md 충족도 | 비고 |
|----------|:---------------:|------|
| 한눈에 파악 | **최고** | 테이블 하나로 전체 현황 |
| 마찰 최소 | **양호** | 상태 변경 시 INDEX.md 한 곳만 수정 |
| 20개+ 확장 | **양호** | 테이블 50행까지 실용적. 그 이상은 frontmatter 전환 |
| 경로 안정 | **최고** | 파일 이동 없음 |
| git 친화 | **양호** | 단일 파일 변경 = 깔끔한 diff |

### 구체적 INDEX.md 템플릿

```markdown
# Plans -- 실행 계획 대시보드

> **관리 규칙:** 새 plan 파일 추가/상태 변경 시 반드시 이 테이블도 업데이트할 것.

## Active Plans

| # | Plan | Status | Depends On | Updated |
|---|------|--------|------------|---------|
| 1 | [Retrieval Confidence & Output](./plan-retrieval-confidence-and-output.md) | Pending | - | 2026-02-22 |
| 2 | [Search Quality Logging](./plan-search-quality-logging.md) | Pending | #1 | 2026-02-22 |
| 3 | [PoC Experiments](./plan-poc-retrieval-experiments.md) | Pending | #2 | 2026-02-22 |
| 4 | [Guardian Conflict Fix](./plan-guardian-conflict-memory-fix.md) | Pending | - | 2026-02-22 |

## In Progress

| Plan | Status Detail | Updated |
|------|--------------|---------|
| [Retrieval Improvement Plan](./retrieval-improvement-plan.md) | S4 (tests) is NEXT | 2026-02-21 |

## Reference / Archived

| Plan | Notes |
|------|-------|
| [Memory Consolidation Proposal](./MEMORY-CONSOLIDATION-PROPOSAL.md) | Historical -- superseded by v5.0.0 |
| [Test Plan](./TEST-PLAN.md) | Test coverage strategy |

---

### Status Legend
- **Pending**: 아직 시작 안 함
- **Active**: 현재 진행 중
- **Blocked**: 의존성 미해결로 대기
- **Done**: 완료
- **Archived**: 참고용 (더 이상 실행 대상 아님)
```

### INDEX.md Drift 방지 가이드라인

검증 과정에서 "drift 위험"이 주요 우려로 나왔습니다. 대응:

1. **INDEX.md 상단에 관리 규칙 명시** (위 템플릿에 포함)
2. **CLAUDE.md에 한 줄 추가**: `plans/ 폴더에 파일 추가/변경 시 plans/INDEX.md도 업데이트할 것`
3. **파일 수가 30개 초과 시**: YAML frontmatter + 자동 생성 INDEX.md로 전환 고려 (프로젝트의 memory_index.py 패턴과 동일)

### 탈락 방안과 이유

| 방안 | 탈락 이유 |
|------|-----------|
| 디렉토리 칸반 (todo/doing/done/) | 파일 이동 → 경로 변경 → 다른 문서의 참조 깨짐 |
| 파일명 접두사 (01-wip-) | 동일한 경로 불안정 문제 + 파일명 장황 |
| YAML frontmatter 단독 | `ls`만으로 상태 확인 불가. 7~20개 규모에선 INDEX.md가 더 실용적 |
| Frontmatter + INDEX.md 하이브리드 | 7~20개 규모에서 오버엔지니어링. 두 곳 관리 = drift 위험 증가 |
| 자동 생성 INDEX.md | 매력적이지만 현재 규모에선 스크립트 개발 비용 > 수동 관리 비용 |

---

## 검증 로그

### 검증 라운드 1 (도전적 비판)에서 발견한 결함과 반영

| 결함 | 심각도 | 반영 |
|------|--------|------|
| git rename 역사 오해 | 높음 | **수정됨** -- 실제 git 상태 정확히 반영 |
| action-plans/ 경시 | 중간 | **수정됨** -- 차선으로 격상, 장단점 공정 비교 |
| 점수 산술 오류 | 중간 | **수정됨** -- 최종 보고서에서 가중치 매트릭스 제거, 정성적 비교로 대체 |
| INDEX.md 마찰 과소평가 | 높음 | **반영됨** -- "양호"로 하향, drift 방지 가이드라인 추가 |
| 자동 생성 INDEX.md 누락 | 높음 | **반영됨** -- 확장 전략으로 언급 (현재 규모에서는 비용 대비 부적합) |
| Claude Code plan mode 혼동 | 중간 | **반영됨** -- 약점 테이블에 대응 포함 |

### 검증 라운드 2 (실용 검증)에서 발견한 사실과 반영

| 사실 | 반영 |
|------|------|
| plans/가 이미 커밋된 상태 | **핵심 근거로 채택** -- 참조 수정 비용 제로 |
| plan 파일 간 참조가 논리명(#1, #2) | 경로 안정성 걱정이 실제로는 낮음 (INDEX.md 방식에 유리) |
| 7개 중 1개만 상태 명시 | INDEX.md 초기화 시 수동 상태 판정 필요 -- 템플릿에 반영 |
| 2개 파일이 역사적/참고용 | 테이블을 Active/In Progress/Reference로 분리 |

---

## 실행 요약

| 항목 | 추천 | 이유 |
|------|------|------|
| **디렉토리 이름** | `plans/` (현재 커밋 상태 유지) | 컨벤션 일치, 참조 호환, 업계 표준 |
| **차선** | `action-plans/` | "action" 의미가 중요하다면 |
| **상태 관리** | INDEX.md 단독 대시보드 | 한눈에 파악 + 경로 안정 + 최소 마찰 |
| **확장 전략** | 30개+ 시 frontmatter + 자동 INDEX 전환 | memory_index.py 패턴 재활용 |
