# 최종 보고서: 메모리 검색 아키텍처 분석 및 권고

**날짜:** 2026-02-22
**프로세스:** 4명 분석 → 1명 종합 → 2×2 검증 → 독립 사실 확인
**참여:** Architect, Pragmatist, Skeptic, Creative, Synthesizer, V1-Robustness, V1-Practical, V2-Fresh, V2-Adversarial + Codex 5.3, Gemini 3 Pro

---

## 사용자 질문에 대한 직접 답변

### Q1: "UserPromptSubmit hook에서 LLM judge가 구현되어 있는가?"
**YES.** `memory_judge.py`에 구현, `memory_retrieve.py`에서 호출. 기본 비활성(opt-in, ANTHROPIC_API_KEY 필요). 관련성+유용성 모두 평가(strict 모드).

### Q2: "/memory:search에서 LLM judge가 구현되어 있는가?"
**YES.** `SKILL.md`에서 Task subagent로 오케스트레이션. 관련성만 평가(lenient 모드). API 키 불필요.

### Q3: "Claude Code가 자율적으로 검색하는 경로가 있는가?"
**NO.** 미구현, 미계획. 하지만 0-result hint가 부분적 트리거 역할을 함.

### Q4: "Claude Code가 직접 judge하면 되지 않나? (별도 API 없이)"
**가능성 있음 — 단, 제약 존재.** Agent hook(`type: "agent"`)이 Claude Code에 존재하며 UserPromptSubmit에서 사용 가능. 하지만 agent hook은 binary decision(ok/false)을 반환하며, command hook처럼 임의 텍스트를 컨텍스트에 주입하지는 않음. 따라서 **메모리 주입에는 여전히 command hook이 필요**하고, agent hook은 판단/필터링 용도로 활용 가능.

### Q5: "Hook이 그냥 skill 존재를 상기시켜주면 되지 않나?"
**비권장.** 결정론적 주입(100ms, 100% 실행)을 확률적 instruction-following으로 대체하는 것은 기능 퇴행. LLM의 메타인지 한계(자기가 뭘 모르는지 모름)와 적대적 공격 표면(프롬프트로 검색 억제 가능)이 핵심 위험.

### Q6: "LLM judge 기준을 미리 설정할 필요 없지 않나?"
**필요함.** 기준 없으면 (1) 테스트 불가, (2) 모델 버전 드리프트 감지 불가, (3) 프롬프트 인젝션 방어 약화. 다만 실질적 인젝션 방어는 `html.escape()` + 구조적 경계에서 나오며, 기준 자체는 테스트 가능성과 일관성을 제공.

---

## 핵심 아키텍처 권고

### 현행 유지 (변경 불필요)
1. **BM25 auto-inject hook** — 결정론적, 100ms, 의존성 없음
2. **`memory_judge.py` (opt-in API judge)** — 구축 완료, 비활성 시 비용 0
3. **`/memory:search` + subagent judge** — API 키 불필요, 컨텍스트 창 보호
4. **Judge 기준 (strict/lenient 비대칭)** — 보안, 테스트 가능성, 모델 안정성
5. **CLAUDE.md에 자율 검색 지시 미추가** — 결정론→확률 퇴행 방지

### 즉시 실행 가능한 개선 (Phase 1, ~60-80 LOC)

| # | 액션 | 변경량 | 위험 |
|---|------|--------|------|
| 1 | `confidence_label()`에 **절대 하한선** 추가 + **클러스터 감지** | ~20-35 LOC | 낮음 |
| 2 | **중간 신뢰도 결과의 축약 주입** (제목+경로만, XML 구조 유지 필수) | ~40-60 LOC | 낮음 |
| 3 | **0-result hint AND all-low-confidence** 시 `<memory-note>` 형식 hint | ~6-10 LOC | 매우 낮음 |

**Action #1 상세:**
- 현재 `confidence_label()`은 상대 비율만 사용 → 단일 약한 매칭도 "high" 됨
- 절대 하한선: `abs(best_score) < MIN_THRESHOLD` 이면 최대 "medium"으로 cap
- 클러스터 감지: 3개 이상 결과가 ratio > 0.90이면 "medium"으로 cap (V1-robustness 발견)
- 설정 가능하게: `retrieval.confidence_abs_floor` config 키

**Action #2 상세:**
- HIGH confidence → 전체 주입 (`<result>` 형식, 현행)
- MEDIUM confidence → 축약 주입 (`<memory-compact>` 형식, 제목+경로+태그만)
  + 조건부 지시문 첨부
  + **XML 구조 wrapper 필수 유지** (V1-robustness 보안 요건)
- LOW confidence → 침묵 (주입 없음, 배너 맹시 방지)
- 설정: `retrieval.output_mode` = "tiered" (기본) / "legacy" (현행 복원)

**Action #3 상세:**
- 0-result hint: `<!-- ... -->` → `<memory-note>...</memory-note>`
- **새로 추가**: all-low-confidence일 때도 hint 발생 (V2-adversarial HIGH #1 해소)
- hint 발생 지점 3곳 (lines 458, 495, 560) → 헬퍼 함수로 추출

### 보류 (데이터 수집 후 결정)

| # | 항목 | 필요 데이터 |
|---|------|-------------|
| 4 | Agent hook PoC | `type: "agent"` hook으로 UserPromptSubmit에서 LLM 판단 가능한지 실험 (context injection 메커니즘 확인 필수) |
| 5 | BM25 정밀도 측정 | 20-30건 수동 라벨링으로 현재 정밀도 계량 |
| 6 | Nudge 준수율 측정 | 축약 주입 후 `/memory:search` 호출 비율 (stderr 로깅) |
| 7 | OR-query 정밀도 | 단일 키워드 매칭의 false positive 비율 (V2-fresh 발견) |

---

## 검증에서 발견된 주요 보완 사항

### V1-Robustness (보안/견고성)
- **Score clustering**: 절대 하한선만으로 부족, 클러스터 감지도 필요 → Action #1에 반영
- **Judge prompt truncation**: 500자 제한이 코드 중심 프롬프트에서 문제 → 향후 개선
- **Compact injection**: XML 구조 wrapper 필수 → Action #2에 반영

### V1-Practical (구현 가능성)
- **LOC 약간 과소 추정**: Action #2는 40-60 LOC (종합 보고 30-50)
- **Rollback은 2 config 변경** (output_mode + abs_floor), 종합의 "1건" 주장 수정
- **테스트 5-8개 업데이트 필요** (test_memory_retrieve.py, test_v2_adversarial_fts5.py)
- **hint 발생 지점 3곳** (종합의 2곳 → 실제 3곳)

### V2-Fresh (독립 검증)
- **OR-query 정밀도 문제**: 단일 키워드가 무관한 결과를 flood → 미해결
- **테스트 수 오류**: 종합의 "149개"는 과장, 실제 ~86개
- **Medium 모드에서 태그 보존 필요**: 태그 없으면 Claude가 관련성 판단 어려움

### V2-Adversarial (적대적 검증)
- **Agent hooks 존재**: `type: "agent"` hook이 Claude Code에 존재하며 UserPromptSubmit 지원. 다만 binary decision(ok/false) 반환이므로 **context injection에는 command hook 여전히 필요**. 종합의 "hard constraint"는 과장이었으나, 핵심 결론(command hook으로 주입)은 유효.
- **0-result hint 불충분**: 잘못된 결과가 반환될 때 hint 미발생 → Action #3에서 all-low-confidence hint 추가로 해소
- **외부 모델 의견 방법론**: 분석가마다 다른 프레이밍으로 같은 모델에 질의 → 상반된 "합의" 도출. 향후 동일 프레이밍으로 재검증 권장.

---

## Agent Hook 가능성에 대한 현실적 평가

V2-adversarial이 발견한 `type: "agent"` hook은 실재하며, 향후 아키텍처에 중요한 함의가 있다:

**가능한 것:**
- Agent hook으로 UserPromptSubmit에서 LLM 기반 판단 수행
- Read, Grep, Glob, Bash 도구 사용 (최대 50턴)
- API 키 없이 Claude의 자체 LLM으로 판단

**불가능하거나 불확실한 것:**
- Agent hook은 `{ "ok": true/false }` 반환 — 임의 텍스트 주입 불가
- 메모리 검색 결과를 Claude 컨텍스트에 넣으려면 command hook의 stdout 메커니즘 필요
- Agent hook의 실제 레이턴시 (60s 기본 타임아웃, 실행 시간 미측정)

**권장 경로:**
1. 현재는 command hook 유지 (검증된 안정적 경로)
2. **Agent hook PoC 별도 실험** — 레이턴시, output 메커니즘, plugin 호환성 확인
3. PoC 결과에 따라 아키텍처 재평가

---

## 프로세스 자체에 대한 반성 (V2-adversarial 지적)

1. **모든 분석가가 동일한 false premise를 공유**: "hooks는 command type만 가능"이라는 가정을 아무도 독립 검증하지 않음 → anchoring bias
2. **외부 모델 의견의 방법론적 한계**: 프레이밍에 따라 같은 모델이 상반된 답변 → 향후 동일 프롬프트 사용 필요
3. **프로세스 대비 산출물 비율**: ~20,000+ words 분석 → ~60-80 LOC 변경 권고. 다만 "현행 아키텍처가 건전함을 확인"한 것 자체가 가치.

---

## 최종 요약

| 영역 | 결론 |
|------|------|
| 현재 아키텍처 | **기본적으로 건전** — BM25 + opt-in judge + on-demand skill |
| 자율 검색 | **미권장** — 결정론적 hook이 확률적 instruction보다 우월 |
| API judge 삭제 | **미권장** — 비활성 시 비용 0, 파워유저에게 가치 |
| Judge 기준 삭제 | **미권장** — 테스트 가능성, 일관성, 보안에 필수 |
| 즉시 실행 | confidence 교정 + 축약 주입 + hint 개선 (~60-80 LOC) |
| Agent hook | **PoC 실험 권장** — 향후 아키텍처 선택지 확대 가능 |
