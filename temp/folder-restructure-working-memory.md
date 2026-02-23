# Folder Structure Restructuring - Working Memory

## Problem Statement
`research/rd-08-final-plan.md` (82KB)는 research 폴더에 있지만 실제로는:
- 문제 정의 (what's wrong) - issue-like
- 구현 계획 (what to do) - action plan
- 세션별 작업 분해 (how to do it) - task breakdown
- 진행 상황 추적 (what's done) - progress tracking

이것은 "연구 결과"가 아니라 "프로젝트/이니셔티브" 성격의 문서이다.

## Current Structure Analysis
```
research/
├── rd-08-final-plan.md          # HYBRID: action plan + progress (NOT research)
├── retrieval-improvement/       # PURE RESEARCH (5 files)
│   ├── README.md
│   ├── 01-research-claude-code-context.md
│   ├── 01-research-claude-mem-retrieval.md
│   ├── 02-research-claude-mem-rationale.md
│   └── 06-analysis-relevance-precision.md
└── claude-mem-comparison/       # MOSTLY RESEARCH (3 files)
    ├── final-analysis-report.md    # hybrid: research + assessment
    ├── phase1-comparator-output.md # pure research
    └── phase2-synthesis-output.md  # pure research + synthesis
```

Other relevant top-level docs:
- `MEMORY-CONSOLIDATION-PROPOSAL.md` (77KB) - superseded proposal (also plan-like)
- `TEST-PLAN.md` (8KB) - testing strategy
- `temp/` (392 files) - mixed working memory, session logs, etc.

## Alternatives to Evaluate

### Alt 1: `plans/` (simple dedicated folder)
### Alt 2: `work/` (generic work tracking with sub-structure)
### Alt 3: `epics/` or `tracks/` (project management metaphor)
### Alt 4: Topic-based flat structure (e.g., `retrieval/`, `comparison/`)
### Alt 5: Restructure research/ with sub-categories
### Alt 6: `roadmap/` or `initiatives/`

## Evaluation Criteria
1. 직관성 (Intuitiveness) - 이름만 보고 무엇이 들어있는지 알 수 있는가?
2. 확장성 (Scalability) - 새로운 계획/연구가 추가될 때 자연스럽게 수용하는가?
3. 관심사 분리 (Separation of Concerns) - research vs action plan이 명확히 분리되는가?
4. 프로젝트 컨벤션 적합성 - claude-memory 프로젝트의 기존 컨벤션과 조화로운가?
5. 실용성 - temp/ 392개 파일 정리에도 도움이 되는가?
6. 단순성 - 불필요한 복잡성을 추가하지 않는가?

## Vibe Check Insights (completed)

1. **사용자 의도 재해석:** "이런 것을 분리" = 단일 파일 이동이 아닌 **분류 원칙** 수립
2. **`plans/` 검증됨:** 1인 플러그인 프로젝트 규모에 적합, 과도한 분석 경고
3. **temp/ 별도 문제:** 현재 범위에서 제외 - 사용자가 요청하지 않음
4. **MEMORY-CONSOLIDATION-PROPOSAL.md:** 사용자에게 선택지로 제시할 것 (강제 포함 X)
5. **핵심 원칙 제시 필요:** "뭘 해야 하고 진행 추적 → plans/, 뭘 알게 되었나 → research/"

## Status
- [x] Detailed alternative analysis (temp/folder-restructure-alternatives.md)
- [x] Self-critique (alternatives 파일 내 Self-Critique Round 1)
- [x] Vibe check - DONE, plans/ 방향 검증됨
- [x] Final recommendation 작성 (temp/folder-restructure-final-report.md)
- [x] Independent verification x2 (Critic 1: plans/ 지지, Critic 2: 반대 but 사실 오류 기반)
- [x] 사실 검증: rd-01~07은 temp/에 위치 (Critic 2 주장 반증)
- [x] COMPLETE
