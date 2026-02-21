# claude-mem vs claude-memory: 최종 분석 보고서

**Date:** 2026-02-20
**Method:** 4-Phase 멀티에이전트 분석 (8명의 독립 에이전트, 2차 교차 검증)
**Cross-model validation:** Gemini 3.1 Pro, Gemini 2.5 Pro, Claude Sonnet 4.6

---

## Executive Summary

### 1. claude-mem 메모리 누수: 원인과 해결 상태

**원인: 구조적 결함 (확신도 9/10)**

claude-mem은 5개 이상의 프로세스 타입을 3개 런타임(Bun/Node, Python, Claude CLI)에서 운영하면서 **통합 프로세스 슈퍼바이저 없이** 동작한다. 3개월간(2025.12~2026.02) 8건의 독립적 리소스 누수 사건 발생:
- Issue #789: 워커 데몬 52GB RAM 소비
- Issue #1145: 218개 중복 데몬, 15GB 스왑, 하드 리셋 필요
- Issue #1168: 157개 좀비 프로세스, 8.4GB RAM
- Issue #1185: chroma-mcp 500-700% CPU (2026-02-20 현재 **미해결**)

Gemini 2.5 Pro는 이를 **"Local Distributed System Fallacy"** 로 명명 -- 로컬 프로세스를 클라우드 마이크로서비스처럼 운영하면서 오케스트레이션 인프라는 없는 구조.

**해결 상태: 완벽히 해결되지 않음.** 7건 수정, 1건(#1185) 미해결. 안정 버전 v10.2.6 핀 권장.

### 2. claude-memory에서 같은 이슈 발생 가능성

**프로세스 누수 위험: 거의 제로 (확신도 10/10)**

소스코드 직접 분석 확인:
- 데몬 없음, 포트 없음, 백그라운드 프로세스 없음
- 모든 스크립트가 hook 호출 시 실행 후 즉시 종료
- 유일한 subprocess 호출: `memory_retrieve.py`의 index rebuild (10초 타임아웃, 동기 실행)

**단, 디스크 수준의 운영적 누수 4건 존재** (RAM/CPU 누수와 완전히 다른 심각도 등급):
1. staging 드래프트 파일 축적 (HIGH) -- ~30분 수정 가능
2. retired 메모리 수동 GC 필요 (MEDIUM-HIGH) -- ~1시간 수정 가능
3. triage 스코어 로그 무한 증가 (MEDIUM) -- ~15분 수정 가능
4. max_memories_per_category 미강제 (MEDIUM) -- ~30분 수정 가능

### 3. claude-memory vs claude-mem: 핵심 비교

**3개 차원으로 압축** (15개 차원 비교는 과도하게 세분화됨):

| 차원 | 승자 | 상세 |
|------|------|------|
| **검색 품질** | claude-mem (압도적) | 시맨틱 ~80-85% vs 키워드 ~40% (추정치, 미측정) |
| **안정성/신뢰성** | claude-memory (압도적) | 프로세스 누수 제로 vs 8건 누수 이력 |
| **이식성/라이선스** | claude-memory | WSL2 호환, git 네이티브, MIT vs AGPL |

### 4. 최종 판단: claude-memory 개발을 계속할 것인가?

**조건부 YES -- 확신도 6/10**

(Phase별 확신도 범위: 적대적 검증 5/10, 종합 보고서 7/10, 독립 검증 8/10 → 가중 평균 6/10)

---

## 확신도 6/10의 의미

| 조건 | 충족 시 확신도 |
|------|---------------|
| 현재 상태 (auto-injection이 net-negative) | 5/10 |
| BM25 + 임계값 조정 후 측정 precision > 50% | 7/10 |
| FTS5 기반 BM25 + 정밀 태그 체계 구축 후 precision > 65% | 8/10 |

---

## 핵심 발견: 현재 auto-injection은 아마 해롭다

**이것이 이 분석의 가장 중요한 발견이다.**

현재 설정(max_inject=5, min_score~1)에서 ~40% precision은 5개 주입 메모리 중 ~3개가 무관한 노이즈를 의미. 적대적 검증과 실용적 검증 모두 "net-negative" 판정.

Gemini 3.1 Pro: "At 60% precision, 4 out of every 10 pieces of context injected into the LLM are garbage. In a RAG pipeline, auto-injecting irrelevant data actively degrades the LLM's reasoning."

**그러나** 독립 검증의 Gemini는 반론: "LLMs are highly resilient to noisy context; if a keyword search returns a few irrelevant files alongside the correct ones, Claude can simply ignore the irrelevant ones."

이 두 관점의 균형: auto-injection의 net 효과는 **현재 측정 불가** (벤치마크 없음). 위험 회피를 위해 즉시 임계값을 올려야 한다.

---

## 즉시 실행 사항 (이번 주)

1. **설정 변경 (5분):** `min_score=4`, `max_inject=3` → 최악의 false positive 즉시 제거
2. **운영적 누수 수정 (2-4시간):** staging cleanup, 로그 로테이션, auto-GC, 카테고리 상한 강제
3. **"zero process leak risk"를 "near-zero"로 정정** (subprocess.run 존재 확인됨)

## 향후 개발 로드맵 (중요도 순)

1. **검색 평가 벤치마크 구축** -- 20+ 테스트 쿼리, precision/recall 측정 (모든 개선의 전제조건)
2. **FTS5 기반 BM25 구현** -- Python 내장 sqlite3의 FTS5 확장 사용, 신규 의존성 제로 (Gemini 3.1 Pro 제안: 임시 인메모리 SQLite DB로 구현)
3. **injection 임계값 정밀 조정** -- 벤치마크 데이터 기반
4. **가벼운 동의어 맵** -- 코딩 용어 ~30쌍

## Kill Criteria (중단 기준)

BM25 구현 후 20-쿼리 벤치마크에서 **측정 precision이 50% 미만**이면:
- stdlib-only 제약이 유용한 auto-injection과 양립 불가능
- 수동 검색(slash command) 전용으로 전환하거나 프로젝트 중단 검토

---

## 왜 claude-memory를 계속 개발하는가? (솔직한 프레이밍)

claude-memory는 claude-mem의 "더 나은 버전"이 아니다. **다른 철학의 도구**다.

### "다른 철학"이란 무엇인가?

같은 문제(Claude Code의 세션 간 기억 유지)를 풀되, **무엇을 포기하고 무엇을 얻는가**에 대한 설계 철학이 정반대이다.

| | claude-mem | claude-memory |
|---|---|---|
| **최적화 목표** | 검색 정밀도 극대화 | 안정성/이식성 극대화 |
| **감수하는 대가** | 인프라 복잡성, 프로세스 누수 위험 (52GB RAM, 시스템 프리즈) | 검색 정밀도 열세 (~40% vs ~85%) |
| **저장소** | 글로벌 SQLite + ChromaDB 벡터 DB (시맨틱 임베딩) | 프로젝트별 JSON 파일 (git 네이티브, 사람이 읽을 수 있음) |
| **런타임 모델** | 상시 실행 데몬 (Bun + Node + Python + Claude CLI, 5+ 프로세스 타입) | 실행 후 즉시 종료 (Python stdlib 스크립트, 잔류 프로세스 없음) |
| **검색 방식** | 시맨틱 벡터 + 키워드 하이브리드 (ChromaDB + SQLite FTS5) | 키워드 기반 가중 스코어링 (stdlib, 추후 BM25) |
| **메모리 구조** | 비정형 "관찰(observation)" 플랫 리스트 | 6개 타입 분류 + Pydantic 스키마 + 라이프사이클 관리 |
| **프로젝트 격리** | 글로벌 DB (교차 오염 가능) | 프로젝트별 `.claude/memory/` (완전 격리) |
| **보안 모델** | 최소한 (내부 데이터 신뢰) | 다층 방어 (쓰기 가드, 제목 세정, 경로 순회 검사, anti-resurrection) |
| **라이선스** | AGPL-3.0 (상업적 제한) | MIT (제한 없음) |
| **비유** | 고성능 스포츠카 -- 빠르지만 정비 필요, 고장 시 큰 피해 | 자전거 -- 느리지만 고장 안 남, 어디서든 탈 수 있음 |

**핵심 차이:**
- claude-mem은 **"최고의 기억력을 줄 테니, 백그라운드 데몬이 52GB RAM을 먹는 리스크를 감수하라"** 는 철학
- claude-memory는 **"기억력은 60-70%이지만, 시스템을 절대 프리즈시키지 않겠다"** 는 철학

이것은 "어떤 게 더 좋은가?"가 아니라 **"어떤 트레이드오프를 선택하는가?"** 의 문제다. 검색 정밀도와 안정성은 현재 아키텍처에서 양립 불가능하다 -- 시맨틱 검색은 벡터 DB + 임베딩 모델이 필요하고, 이는 필연적으로 상주 프로세스나 외부 서비스를 요구한다. claude-memory는 이 인프라를 의도적으로 거부함으로써 안정성을 얻지만, 검색 품질의 상한선(~60-70%)을 감수한다.

### 누구를 위한 도구인가?

- **claude-mem이 맞는 사용자:** macOS + 16GB+ RAM, 데몬 프로세스 관리에 익숙, 최고 정밀도 검색이 생산성에 결정적, 시스템 리소스 여유 충분
- **claude-memory가 맞는 사용자:** WSL2/Linux/제한된 환경, 시스템 프리즈 경험이 있거나 감수 불가, git 기반 프로젝트별 메모리 필요, 인프라 제로 운영 선호

WSL2 환경에서, 데몬 아키텍처가 시스템을 프리즈시킨 경험이 있는 개발자에게, claude-memory는 유일하게 안전한 선택이다. 이것은 sunk cost가 아니라 **환경 제약에 의한 합리적 선택**이다.

단, macOS + 32GB RAM 환경이라면 claude-mem v10.2.6 핀이 더 나은 선택일 수 있다. WSL2 제약이 이 분석의 결론을 뒤집는 단일 요인이다.

---

## 검증 요약

| Phase | 에이전트 | 핵심 발견 | 확신도 |
|-------|---------|----------|--------|
| 1 | mem-leak-researcher | claude-mem 8건 구조적 누수, #1185 미해결 | Very High |
| 1 | arch-analyst | claude-memory 프로세스 누수 제로, 운영적 누수 4건 | High |
| 1 | comparator | claude-memory 15+ 차원 우세, 검색 품질 열세 | High (8/10) |
| 2 | synthesizer | 조건부 YES, 검색 격차가 핵심 | High (7/10) |
| 3 | verifier-1-tech | 2개 오류 발견 (zero→near-zero, precision 오귀속) | 7/10 |
| 3 | verifier-1-practical | 보고서 6/10, "현재 net-negative" 지적 | 5-6/10 |
| 4 | verifier-2-adversarial | 검색 격차 공격 성공, 확신도 5/10으로 하향 | 5/10 |
| 4 | verifier-2-independent | 독립 분석 동일 결론, FTS5 제안, 확신도 8/10 | 8/10 |

### 검증 간 핵심 불일치

| 항목 | 독립 검증 (8/10) | 적대적 검증 (5/10) |
|------|-----------------|-------------------|
| 현재 auto-injection | "LLM이 노이즈에 resilient" | "net-negative, 해롭다" |
| BM25 효과 | "~65-75% 가능" | "~60% 천장, 여전히 부족" |
| 계속 개발 근거 | "WSL2 니치가 실제로 존재" | "WSL2가 유일한 방어선" |
| bus factor | "개인 도구에는 무관" | "커뮤니티 없으면 지속 불가" |

**최종 판단:** 두 검증 모두 "계속 개발" 결론에는 동의. 차이는 확신도와 조건의 엄격함. 가중 평균 **6/10**이 가장 정직한 평가.

---

## 이 분석의 한계

1. **모든 precision 수치는 추정치.** 벤치마크 없이 측정된 값 없음.
2. **source bias.** claude-memory 프로젝트 내부에서 생성된 분석.
3. **claude-mem을 실제 실행하지 않음.** GitHub 공개 데이터 기반.
4. **Gemini quota 소진.** 일부 검증에서 Claude로 대체 (같은 모델 패밀리 bias 가능).
5. **Codex 5.3 사용 불가.** quota 초과로 3-모델 교차 검증 불가.

---

## 참고: 전체 보고서 파일 목록

### 결론 파일 (research/claude-mem-comparison/)
| 파일 | 내용 |
|------|------|
| `final-analysis-report.md` | 이 최종 보고서 |
| `phase2-synthesis-output.md` | 종합 보고서 (상세 분석) |
| `phase1-comparator-output.md` | claude-mem vs claude-memory 상세 비교 |

### 과정 파일 (temp/)
| 파일 | 내용 |
|------|------|
| `temp/phase1-leak-researcher-output.md` | claude-mem 메모리 누수 상세 조사 |
| `temp/phase1-arch-analyst-output.md` | claude-memory 아키텍처 취약점 분석 |
| `temp/phase3-verifier-tech-output.md` | 기술적 정확성 검증 |
| `temp/phase3-verifier-practical-output.md` | 실용적 관점 검증 |
| `temp/phase4-verifier-adversarial-output.md` | 적대적 검증 |
| `temp/phase4-verifier-independent-output.md` | 독립 재검증 |
