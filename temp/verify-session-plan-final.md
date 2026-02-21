# Session Plan Verification -- Final Consolidated Report

**Date:** 2026-02-21
**Source:** 4-track independent verification (accuracy, dependencies, feasibility, risks)
**Verdict:** 계획에 **구조적 오류 2건**, **누락 항목 6건**, **추정치 오류 3건** 발견. 수정 후 진행 권장.

---

## I. CRITICAL Issues (반드시 수정)

### 1. Session 4//5 병렬화는 불가능 — 순서가 반대여야 함
**[Track B + C 일치, HIGH severity]**

세션 5(confidence annotations)가 `memory_retrieve.py`의 출력 포맷을 변경함:
```
Before: - [DECISION] JWT token refresh flow -> path #tags:auth,jwt
After:  - [DECISION] JWT token refresh flow -> path #tags:auth,jwt [confidence:high]
```

세션 4(테스트)가 이 포맷을 검증해야 함. 따라서 **세션 5가 세션 4보다 먼저** 완료되어야 함.

**현재 계획의 의존성 그래프 (잘못됨):**
```
S1 → S2 → S3
      |
      +→ S4 (병렬) ─┐
      +→ S5 (병렬) ─┴→ S6 → S7 → S8 → S9
```

**수정된 의존성 그래프:**
```
S1 → S2 → S3 → S5 → S4 → S6 → S7 → S8 → S9
```

병렬화 가능 구간이 없어 **순차 실행이 필수**. 총 작업량은 동일하나 경과 시간은 ~1일 증가.

### 2. 토크나이저 변경이 Fallback 경로를 파괴
**[Track D: CRITICAL, Track C에서도 독립 확인]**

새 `_TOKEN_RE`가 `user_id`를 단일 토큰으로 보존하지만, fallback 경로의 `score_entry()`는 여전히 개별 토큰(`user`, `id`) 기반 매칭을 수행:

```
프롬프트: "fix the user_id field"
  OLD 토큰: {user, id, field, fix}    → title "User ID validation" 매치: 4점
  NEW 토큰: {user_id, field, fix}     → title "User ID validation" 매치: 1점 (75% 하락)
```

**해결책:** fallback 경로용 레거시 토크나이저를 별도 보존. FTS5 쿼리 빌더만 새 토크나이저 사용.

```python
_LEGACY_TOKEN_RE = re.compile(r"[a-z0-9]+")       # fallback 전용
_COMPOUND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")  # FTS5 전용
```

---

## II. Structural Gaps (누락 항목)

### 3. Phase 2d (검증 게이트) 누락
**[Track A: DISCREPANCY]**

rd-08이 Phase 2c(테스트)와 2e(annotations) 사이에 명시적 검증 단계를 정의함:
- 모든 수정 스크립트 컴파일 체크
- 전체 테스트 스위트 실행
- 10+ 쿼리 수동 회귀 테스트
- 기존 메모리 비회귀 검증

→ 세션 4 마지막에 포함시키거나 별도 체크포인트로 추가 필요.

### 4. Config 변경 누락
**[Track A + C 일치: MISSING]**

rd-08이 명시한 2개 핵심 config 변경이 어떤 세션에도 배정되지 않음:
- `match_strategy`: `"title_tags"` → `"fts5_bm25"` (새 기본값)
- `max_inject`: `5` → `3` (정밀도 최적화)

`assets/memory-config.default.json` 업데이트가 Phase 3에만 배정되어 있으나, 이 변경은 Phase 2 작업. **세션 2에 포함 필요.**

또한 기존 사용자의 `"title_tags"` 설정 호환성 문제: `score_entry()`를 제거하면 이 config 옵션이 무의미해짐. **키워드 fallback 경로를 config 스위치로 보존하거나, 명시적 breaking change로 문서화** 필요.

### 5. CLAUDE.md 업데이트 누락
**[Track A: MISSING]**

Phase 2에서 `memory_search_engine.py` 추가, 검색 아키텍처 변경, 새 스킬 등 주요 변경 발생. CLAUDE.md의 Key Files, Architecture, Security 섹션 업데이트 필요. **세션 3 또는 4에 포함 권장.**

### 6. plugin.json 및 기존 명령어 충돌
**[Track C: HIGH]**

- 새 스킬 `skills/memory-search/SKILL.md`가 `plugin.json`에 등록되지 않음
- 이미 `commands/memory-search.md` 명령어가 등록되어 있음
- **결정 필요:** 기존 명령어를 스킬로 교체? 공존? 명령어 업데이트?

### 7. test_adversarial_descriptions.py Import 문제
**[Track C: CRITICAL]**

이 파일이 `score_description`을 모듈 레벨에서 import:
```python
from memory_retrieve import tokenize, score_entry, score_description, _sanitize_title
```

`score_description` 제거 시 **전체 파일 (60+ parametrized 보안 테스트)이 import 실패로 전멸.** 세션 4에서 import 수정이 최우선.

### 8. memory_candidate.py 토크나이저 동기화
**[Track D: MEDIUM, bonus finding]**

`memory_candidate.py`에도 동일한 `_TOKEN_RE = re.compile(r"[a-z0-9]+")`가 있음. 검색과 후보 선정에서 토크나이저 불일치 발생 가능. **동기화 또는 명시적 문서화 필요.**

---

## III. Estimate Corrections (추정치 수정)

### 9. 테스트 깨짐 비율: 42% → 60-63%
**[Track C: HIGH]**

| 파일 | 전체 테스트 | 깨지는 수 |
|------|----------|---------|
| test_memory_retrieve.py | 33 | ~20-22 |
| test_arch_fixes.py | ~45 | ~3-5 |
| test_adversarial_descriptions.py | ~60+ | **전부** (import 실패) |
| **합계** | ~138 | **~83-87 (60-63%)** |

세션 4 시간 추정: 4-6시간 → **8-12시간** 수정 필요.

### 10. LOC 추정 하향 편향
**[Track C: HIGH]**

| 세션 | 계획 추정 | 실제 추정 | 차이 원인 |
|------|---------|---------|----------|
| S2 | ~200 LOC | ~240-260 LOC | main() 재구성, 보안 체크 보존, config 분기 |
| S3 | ~100 LOC | ~195-255 LOC | 공유 상수 추출, CLI 스캐폴딩, full-body 검색 모드 |

특히 **세션 3이 ~2배 과소추정**. S2에서 inline으로 작성한 FTS5 코드를 S3에서 공유 모듈로 추출하는 리팩터링 비용 미반영.

### 11. Measurement Gate 통계적 한계
**[Track D: HIGH]**

20개 쿼리(60개 판정)의 95% 신뢰구간 폭: ~20 percentage points.
- 관측 precision 80% → 실제 68%-88% 범위
- 75% vs 85% 구분 불가능

**권장:** 40-50개 쿼리로 확대하거나, "대략적 방향성 확인"으로 재정의.

---

## IV. Minor Issues (참고 사항)

| # | 내용 | 심각도 | 출처 |
|---|------|--------|------|
| 12 | `"user_id"` FTS5 phrase 쿼리는 "exact match"가 아닌 "phrase match" — `user id`(공백)도 매치됨 | MEDIUM | Track D |
| 13 | sys.path import 경로 수정 (R1-technical WARN)이 세션 3에 명시되지 않음 | LOW | Track A |
| 14 | 0-result hint injection 시 exit point 4곳 중 2곳만 힌트 대상 | LOW | Track C |
| 15 | BM25 음수 점수 컨벤션이 오류 유발 가능 — 도우미 함수 권장 | LOW | Track D |
| 16 | conftest.py에 500문서 벤치마크용 bulk fixture 필요 (~20-30 LOC) | LOW | Track C |

---

## V. Recommended Session Order (수정안)

```
S1 → S2 → S3 → S5 → S4 → S6 → (conditional) S7 → S8 → S9
```

각 세션에 추가해야 할 항목:

| 세션 | 추가 항목 |
|------|----------|
| S1 | 레거시 토크나이저 별도 보존 (`_LEGACY_TOKEN_RE`), score_entry가 레거시 사용하도록 |
| S2 | `memory-config.default.json` 업데이트 (match_strategy, max_inject), config 분기 로직, 보안 체크(path containment) 보존, 스모크 테스트 5개 |
| S3 | plugin.json 스킬 등록, 기존 memory-search 명령어와의 관계 정리, import path fix, LOC 재추정 (~200 LOC) |
| S4 이전 (S5) | confidence annotations (변경 없음, 현재 계획 유지) |
| S4 | test_adversarial_descriptions.py import 수정 최우선, 시간 추정 8-12시간, conftest.py bulk fixture, Phase 2d 검증 포함 |
| S6 | 쿼리 수 40-50개로 확대 또는 게이트 재정의 |
| 아무 세션 (S3/S4) | CLAUDE.md 업데이트 |

---

## VI. Cross-Verification Matrix

4개 트랙에서 **독립적으로 동일 결론에 도달한** 항목 (높은 신뢰도):

| 발견 사항 | Track A | Track B | Track C | Track D |
|----------|---------|---------|---------|---------|
| S4//S5 병렬 불가 | - | HIGH | Confirmed | - |
| Config 변경 누락 | MISSING | - | GAP | MEDIUM |
| CLAUDE.md 누락 | MISSING | - | GAP | - |
| 테스트 과소추정 | - | - | 60-63% | HIGH |
| 토크나이저 fallback 문제 | - | - | Regression | CRITICAL |
| Measurement gate 한계 | - | - | - | HIGH |

**1개 트랙에서만 발견된 항목** (추가 검증 권장):
- plugin.json 충돌 (Track C만)
- memory_candidate.py 동기화 (Track D만)
- Phase 2d 누락 (Track A만 — 단, Track D의 "스모크 테스트 추가" 권장과 같은 맥락)
