# Folder Structure Alternatives - Detailed Analysis

## Context Recap

rd-08-final-plan.md (82KB)의 실제 성격:
- **문제 정의** ("precision ~40%, 이걸 고쳐야 한다") → GitHub issue와 유사
- **구현 계획** ("Phase 1-4, Session S1-S9") → action plan / roadmap
- **진행 추적** ("S1/S2/S3/S5/S5F/P3 complete, S4 next") → progress tracker
- **기술 결정 기록** ("FTS5 BM25: APPROVED (unanimous)") → ADR-like

이것은 **research가 아닌 "이니셔티브/프로젝트 계획"** 이다.

같은 범주에 속할 수 있는 기존 문서:
- `MEMORY-CONSOLIDATION-PROPOSAL.md` (77KB, superseded) - 이것도 proposal/plan
- `TEST-PLAN.md` (8KB) - testing strategy → 이건 좀 다름 (plan이라는 이름이지만 테스트 전략 문서)

---

## Alternative 1: `plans/`

```
claude-memory/
├── plans/                          # NEW
│   ├── rd-08-retrieval-improvement.md   # moved from research/
│   └── (future plans)
├── research/                       # UNCHANGED (pure research only)
│   ├── retrieval-improvement/
│   └── claude-mem-comparison/
└── ...
```

**장점:**
- 이름이 매우 직관적 - "계획"이 들어있음을 바로 알 수 있다
- 단순하다 - 폴더 하나 추가로 끝
- 진입 장벽 낮음

**단점:**
- "plan"이 너무 좁은 의미 - rd-08은 plan + progress + decisions 복합체
- progress tracking 측면이 이름에 반영되지 않음
- 향후 "완료된 계획"과 "진행 중인 계획" 구분 어려움

**적합도:** 7/10

---

## Alternative 2: `design/` (Go 스타일)

```
claude-memory/
├── design/                         # NEW (Go convention)
│   ├── rd-08-retrieval-improvement.md
│   └── (future design docs)
├── research/
└── ...
```

**장점:**
- Go 프로젝트에서 확립된 관행 (`golang/proposal` → `design/`)
- "설계"는 plan보다 넓은 의미 - 기술 결정, 아키텍처 선택 포함
- OSS 생태계에서 인지도 있음

**단점:**
- "design"이 UI/UX 디자인과 혼동될 수 있음 (이 프로젝트에선 덜하지만)
- progress tracking 측면이 이름에 반영되지 않음
- Go 프로젝트 관행을 따르는 것이 이 프로젝트에 맞는지?

**적합도:** 6/10

---

## Alternative 3: `proposals/` (Swift 스타일) 또는 `rfcs/`

```
claude-memory/
├── proposals/                      # NEW (Swift convention)
│   ├── rd-08-retrieval-improvement.md
│   └── (future proposals)
├── research/
└── ...
```

**장점:**
- Swift Evolution, Python PEPs 등에서 확립된 관행
- "제안"은 결정 과정을 암시 - accepted/rejected 상태 관리 가능
- MEMORY-CONSOLIDATION-PROPOSAL.md가 자연스럽게 여기로 이동 가능

**단점:**
- "proposal"은 "아직 결정되지 않은 제안"을 암시 - rd-08은 이미 승인되어 진행 중
- RFC 프로세스는 1인 프로젝트에 과도함
- progress tracking은 proposal의 범위가 아님

**적합도:** 5/10

---

## Alternative 4: `research/` 하위 구조 변경

```
claude-memory/
├── research/
│   ├── findings/                   # Pure research
│   │   ├── retrieval-improvement/
│   │   └── claude-mem-comparison/
│   └── plans/                      # Action plans
│       └── rd-08-retrieval-improvement.md
└── ...
```

**장점:**
- 기존 폴더명 유지 - 변경 최소화
- 주제별 연관성 유지 (retrieval 관련 연구 + 계획이 같은 상위에)

**단점:**
- 사용자가 명시적으로 "research와 분리하고 싶다"고 했음 → **사용자 의도에 반함**
- research/ 안에 plan이 있으면 여전히 혼란
- 중첩 깊이 증가

**적합도:** 3/10 (사용자 의도와 충돌)

---

## Alternative 5: `tracks/` (작업 스트림)

```
claude-memory/
├── tracks/                         # NEW
│   ├── retrieval-improvement/
│   │   ├── plan.md                 # rd-08 → renamed
│   │   └── progress.md            # optional: 진행 추적 분리
│   └── (future tracks)
├── research/
└── ...
```

**장점:**
- "track"은 진행 중인 작업 흐름을 잘 표현
- 하위 폴더로 관련 문서 그룹화 가능
- plan + progress + decisions를 하나의 track으로 묶을 수 있음

**단점:**
- 일반적이지 않은 용어 - 새 기여자가 의미 파악 어려움
- 지나치게 구조화할 위험
- 단일 파일(rd-08)을 위해 폴더를 만드는 것이 과도할 수 있음

**적합도:** 5/10

---

## Alternative 6: `roadmap/` 또는 `initiatives/`

```
claude-memory/
├── initiatives/                    # NEW
│   ├── rd-08-retrieval-improvement.md
│   └── memory-consolidation.md     # MEMORY-CONSOLIDATION-PROPOSAL.md 이동
├── research/
└── ...
```

**장점:**
- "initiative"는 rd-08의 성격을 가장 정확히 반영 (문제 → 계획 → 실행 → 추적)
- 상위 개념이라 plan, progress, decisions 모두 포함
- MEMORY-CONSOLIDATION-PROPOSAL도 자연스럽게 수용

**단점:**
- "initiatives"는 기업 용어 느낌 - OSS 프로젝트에서 드물다
- 다소 격식 있는 느낌
- "roadmap"은 단수형이라 여러 문서를 담기 어색

**적합도:** 6/10

---

## Comparison Matrix

| 기준 | plans/ | design/ | proposals/ | research/sub | tracks/ | initiatives/ |
|------|--------|---------|------------|-------------|---------|-------------|
| 직관성 | ★★★★☆ | ★★★☆☆ | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ | ★★★☆☆ |
| 확장성 | ★★★☆☆ | ★★★★☆ | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★★☆ |
| 관심사 분리 | ★★★★☆ | ★★★★☆ | ★★★★☆ | ★★☆☆☆ | ★★★★☆ | ★★★★☆ |
| 프로젝트 적합성 | ★★★★☆ | ★★★☆☆ | ★★☆☆☆ | ★★☆☆☆ | ★★★☆☆ | ★★★☆☆ |
| 실용성 | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★☆☆☆ | ★★★☆☆ | ★★★★☆ |
| 단순성 | ★★★★★ | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★★☆☆ | ★★★★★ |
| **합계** | **25** | **23** | **21** | **15** | **20** | **23** |

---

## Self-Critique Round 1

### plans/에 대한 비판:
- "plan"이라는 단어가 rd-08의 복합적 성격(ADR + progress + plan)을 다 담지 못한다. 하지만, 사용자가 "뭘 해야 한다는 지침"이라고 표현한 것은 plan에 가깝다.
- plans/ 안에 완료된 것과 진행 중인 것이 섞이면? → 파일 내 Status 필드로 충분히 관리 가능.

### design/에 대한 비판:
- Go 스타일을 차용하는 것이 이 프로젝트에 맞나? 이 프로젝트는 Claude Code 플러그인이지 Go 프로젝트가 아님.
- 하지만 "design"은 기술 결정 + 아키텍처를 포함하므로 rd-08의 기술 결정 기록 측면에 적합.

### 놓친 대안?
- **`specs/`** - "specification"은 계획보다 명세에 가까움. rd-08은 spec이라기보다 plan.
- **`work/`** - 매우 일반적이나 너무 모호함.
- **`dev/`** - 개발 관련 문서를 모을 수 있으나, hooks/scripts/도 "dev"이므로 혼란.

---

## Emerging Recommendation

**`plans/`가 가장 적합해 보인다.** 이유:
1. 사용자의 핵심 의도("뭘 해야 한다는 지침 + 진행 경과")에 가장 직접적으로 대응
2. 가장 단순하고 직관적
3. 이 프로젝트 규모에 적합 (1인 플러그인 프로젝트)
4. MEMORY-CONSOLIDATION-PROPOSAL.md도 수용 가능
5. research/와 깔끔하게 분리

**차선:** `design/` - 더 넓은 의미를 가지나, 이 프로젝트 맥락에서 직관성이 떨어짐.

→ Vibe check에서 이 결론 검증 필요
