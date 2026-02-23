# Folder Structure Restructuring - Final Report

## Executive Summary

**추천:** 프로젝트 루트에 `plans/` 폴더 생성, `rd-08-final-plan.md`를 이동.

**분류 원칙:**
- `plans/` → "무엇을 해야 하고, 진행을 추적하는" 문서 (action plans, roadmaps, progress)
- `research/` → "무엇을 알게 되었는가" 기록하는 문서 (findings, analysis, comparisons)

---

## Analysis Process

1. **탐색**: 프로젝트 전체 구조 + research/ 내 모든 파일의 성격 분류
2. **대안 분석**: 6개 대안 비교 (plans/, design/, proposals/, research/sub, tracks/, initiatives/)
3. **OSS 관행 조사**: Rust, Go, Swift, Python, Kubernetes 등의 폴더 구조 관행 리서치
4. **Vibe Check**: 메타인지 검증 → plans/ 방향 확인, "원칙 제시" 필요성 지적
5. **독립 검증 x2**:
   - Critic 1 (회의적 시각): plans/ 지지 → "치명적 결함 없음"
   - Critic 2 (다른 문화적 시각): plans/ 반대 → "rd-08을 research/retrieval-improvement/로" 권고
6. **사실 검증**: Critic 2의 핵심 주장(rd-01~07이 research/에 있다) → **사실 오류** (실제로 temp/에 있음)

## Disagreement Resolution

### Critic 1 vs Critic 2

| 논점 | Critic 1 | Critic 2 | 판정 |
|------|---------|---------|------|
| plans/ 생성 여부 | 찬성 | 반대 | **Critic 1** |
| rd-08의 소속 | plans/ (독립 문서) | research/retrieval-improvement/ | **Critic 1** (rd-01~07은 temp/에 있음, 사실 오류) |
| 1개 파일로 폴더 생성 | 정당화됨 (MEMORY-CONSOLIDATION-PROPOSAL.md 흡수 가능) | 과도함 | **Critic 1** (합리적) |
| false dichotomy 우려 | 인정하되 실용적으로 충분 | 4/4 테스트 실패 | **Critic 2 일부 유효** (아래 참조) |

### Critic 2의 유효한 지적 (반영할 것)

1. **"What about" 테스트**: 하이브리드 문서 처리 기준이 필요
   - 해결: "주된 목적이 뭔가?"로 판단. 비교 연구가 "X를 채택하자"로 끝나도, 주된 목적이 "비교 분석"이면 research/. 주된 목적이 "구현 로드맵"이면 plans/.

2. **Git history**: `git mv`로 단독 커밋 권장 (rename detection 보장)

3. **`design-docs/`가 `plans/`보다 나을 수 있다는 주장**:
   - 검토 결과 → 이 프로젝트에서는 plans/가 더 직관적. design-docs/는 Google/SRE 문화에서 온 용어로 이 프로젝트 맥락에 과함.

## Proposed Structure

```
claude-memory/
├── plans/                                    # NEW
│   └── rd-08-retrieval-improvement.md        # moved from research/
├── research/                                 # UNCHANGED
│   ├── retrieval-improvement/                # pure research (stays)
│   │   ├── README.md
│   │   ├── 01-research-claude-code-context.md
│   │   ├── 01-research-claude-mem-retrieval.md
│   │   ├── 02-research-claude-mem-rationale.md
│   │   └── 06-analysis-relevance-precision.md
│   └── claude-mem-comparison/                # mostly research (stays)
│       ├── final-analysis-report.md
│       ├── phase1-comparator-output.md
│       └── phase2-synthesis-output.md
├── temp/                                     # UNCHANGED
├── MEMORY-CONSOLIDATION-PROPOSAL.md          # user에게 이동 여부 질문
├── TEST-PLAN.md                              # stays at root (reference doc)
└── ...
```

## User Decision Points

1. **MEMORY-CONSOLIDATION-PROPOSAL.md (77KB, superseded)** → plans/로 이동할지?
2. **파일명 변경 여부** → rd-08-final-plan.md를 더 서술적인 이름으로 바꿀지?
3. **claude-mem-comparison/final-analysis-report.md** (하이브리드) → research/에 유지할지?
