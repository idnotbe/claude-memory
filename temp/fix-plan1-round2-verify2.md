# Independent Verification #2: Round 2 Fixes (Adversarial + Fresh Eyes)

**Reviewer:** Opus 4.6 (independent verifier #2)
**Date:** 2026-02-23
**Target:** `action-plans/plan-retrieval-confidence-and-output.md` (post Round 2, 15 fixes applied)
**Method:** Full document read-through, adversarial attack on each fix, fresh-eyes readability assessment, code cross-verification, external model consultation (Gemini 3.1 Pro via pal clink)

---

## Final Verdict: PASS WITH NOTES

15건의 수정은 전체적으로 정확하며 문서 품질을 실질적으로 개선했다. **수정에 의해 도입된 새로운 모순이나 결함은 0건이다.** 그러나 수정 과정에서 드러난 pre-existing 문체 이슈 2건(사소)과, Gemini가 제기한 3건의 공격 중 1건의 부분 유효성을 확인했다.

---

## Part 1: Adversarial Attacks on 15 Fixes

### Fix #1 (L1): Header LOC -- ~66-105 + ~130-240
- **공격:** header (line 11)와 cross-cutting table (lines 455-467)의 수치를 대조.
- **결과:** PASS. Header "~66-105 LOC (코드) + ~130-240 LOC (테스트)"는 table의 "코드 소계: ~66-105", "테스트 소계: ~130-240"과 정확히 일치한다. 새로운 불일치 없음.

### Fix #2 (F1): abs_floor domain -- "(0-15 범위에서 하위 약 7-20%)" 추가
- **공격:** "1.0-3.0"이 "0-15 범위의 하위 7-20%"인지 수학적 검증.
  - 1.0 / 15.0 = 6.7% (약 7%)
  - 3.0 / 15.0 = 20.0% (정확히 20%)
- **결과:** PASS. 수학적으로 정확. "약 7-20%"는 올바른 근사치다.

### Fix #3 (L3): "모든 성공적인 쿼리" -> "대다수(70%+)의 성공적인 쿼리"
- **공격:** line 74의 전체 문맥: `대다수(70%+)의 성공적인 쿼리에 발동하는 논리 오류 (tautology)`.
- **Gemini 공격:** "70%+ tautology"는 의미론적 모순이다. Tautology는 100% 참인 명제이므로 "70% tautology"는 성립 불가.
- **나의 판정:** Gemini의 지적은 **부분적으로 유효**하나 심각도는 INFO 수준이다.
  - 정확히 말하면, line 74에서 "tautology"라는 단어는 `>= 3` 임계치(원안)에 대한 것이 아니라, 바로 뒤에 나오는 수학적 증명 `C ≤ N ≤ max_inject → C > max_inject는 수학적으로 불가능 (dead code)`을 지칭한다. 이 dead code 증명 자체는 100% 참이다.
  - 그러나 "대다수(70%+)의 성공적인 쿼리에 발동하는 논리 오류 (tautology)"라는 구문에서, "70%+"는 `>= 3` 원안의 발동 빈도이고, "(tautology)"는 그 발동의 논리적 성격이다. 두 개념이 한 문장에 압축되어 있어 혼동을 줄 수 있다.
  - **그러나 이것은 수정 #3이 도입한 새로운 문제가 아니다.** 수정 전에도 "모든 성공적인 쿼리에 발동하는 논리 오류 (tautology)"였으며, 수정은 "모든"을 "대다수(70%+)"로 교정한 것일 뿐이다. "(tautology)" 단어 자체는 원래부터 있었다. 수정은 과장을 줄였을 뿐, 새로운 의미론적 문제를 도입하지 않았다.
- **결과:** PASS (새로운 문제 아님). pre-existing 문체 개선 여지로 기록 (INFO).

### Fix #4 (L7): body_bonus 정의 추가
- **공격:** line 83의 정의 `body_bonus: 본문 토큰 매칭 보너스 0-3점, score_with_body() line 247에서 계산`을 실제 코드와 대조.
- **코드 검증:** `memory_retrieve.py:247`: `result["body_bonus"] = min(3, len(body_matches))`. `body_matches`는 query_tokens & body_tokens의 교집합이므로 범위는 0-3점 맞음.
- **결과:** PASS. 정의가 코드와 정확히 일치한다.

### Fix #5 (L6): 가독성 개선 -- "구현 결론:" 1줄 요약 추가
- **공격:** line 83의 새 요약 `> **구현 결론:** confidence_label()은 복합 점수(BM25 - body_bonus)를 그대로 사용한다 (코드 변경 없음). 아래는 이 결정에 이른 검토 이력이다.`가 blockquote 본문(lines 84-95)의 내용과 정확히 일치하는지 확인.
- **검증:** blockquote 본문은 raw_bm25 사용을 기각하고 복합 점수 유지를 결론짓는다. 요약문이 이를 정확하게 반영한다.
- **결과:** PASS. 가독성이 실제로 개선됨 (신선한 눈 관점에서도 확인).

### Fix #6 (M2): abs_floor 전달 line 108
- **공격:** line 108 수정 후: `_output_results() (line 299): confidence_label() 호출 시 abs_floor=abs_floor, cluster_count=0 전달`. 이것이 Action #1의 함수 시그니처(lines 98-101) 및 Action #2의 `_output_results()` 시그니처(lines 244-247)와 일관적인지 확인.
- **Gemini 공격 (Implementation Sequence Paradox):** Action #1의 checklist (line 142)에서 `_output_results()`에서 abs_floor를 confidence_label()에 전달하라고 하지만, `_output_results()`의 시그니처에 `abs_floor` 파라미터가 추가되는 것은 Action #2에서이므로, Action #1은 완성 불가능하다.
- **나의 판정:** Gemini의 이 공격은 **FALSE POSITIVE**이다.
  - 이유: Action #1의 scope는 `confidence_label()` 함수 자체의 수정이다. Line 108의 "호출 지점 변경"은 "구현 시 이 함수가 어디서 호출되는지" 참고 정보이다.
  - Action #1의 체크리스트 (lines 139-151)를 주의 깊게 읽으면: `confidence_label()` 시그니처 확장, 로직 구현, 설정 파싱, 테스트가 나열된다. `_output_results()` 시그니처 변경은 체크리스트에 없다 -- 이는 Action #2의 체크리스트 line 254에 있다.
  - Line 142의 `_output_results()에서 cluster_count=0 고정 전달 + abs_floor를 confidence_label()에 전달`은 "Action #2에서 구현할 때 이렇게 해라"라는 의미이다. Action #1에서 이 체크리스트 항목을 완료하라는 것이 아니라, `_output_results()` 수정 시(Action #2) abs_floor가 어떻게 흘러야 하는지를 Action #1에서 미리 명시한 것이다.
  - **그러나**, 이 체크리스트 항목이 Action #1의 Progress 섹션에 있으면서 실제로는 Action #2에서 완료해야 한다는 점은 혼동을 줄 수 있다. 이것은 **pre-existing 배치 이슈**이지 수정 #6이 도입한 새로운 문제가 아니다. 수정 #6은 기존 line 108의 "cluster_count=0 전달"에 "abs_floor=abs_floor"를 추가한 것이며, 이 추가 자체는 정확하다.
- **결과:** PASS (수정 #6 자체는 정확). pre-existing 체크리스트 배치 모호성은 별도 기록 (INFO).

### Fix #7 (M2 연속): abs_floor 전달 line 142
- **공격:** line 142 수정 후: `cluster_count=0 고정 전달 + abs_floor를 confidence_label()에 전달`. 수정 전: `복합 점수 기반 cluster_count 계산 + abs_floor 전달`. 수정이 모호성을 해소했는지 확인.
- **결과:** PASS. "계산"이라는 모호한 단어가 "고정 전달"로 교체되어 Gemini의 1차 CRITICAL 판정(cluster_count 계산 모순)이 해소됨. 동시에 "abs_floor를 confidence_label()에 전달"로 전달 대상이 명시됨.

### Fix #8 (M1): all-LOW wrapper 억제 명세
- **공격:** line 216 수정 후: `_output_results()는 <memory-context> 래퍼를 출력하지 않고 _emit_search_hint("all_low")만 호출하여 빈 래퍼 주입을 방지한다`.
- **일관성 검증:** 이 명세가 Action #2 체크리스트 line 260 `모든 결과 LOW 시 <memory-context> 래퍼 생략, _emit_search_hint("all_low")만 호출`과 일치하는지 확인.
- **결과:** PASS. 설계 설명과 체크리스트가 정확히 일치한다.

### Fix #9 (L4): 테스트 추정 ~15-30 -> ~15-20
- **공격:** line 225(수정 후)의 "~15-20개"가 체크리스트 합계(lines 265-268: ~6 + ~4 + ~2 + ~3 = ~15)와 일관적인지 확인.
- **결과:** PASS. 15개 기본 + 5개 여유분 = 최대 20개. 합리적 범위.

### Fix #10 (L5): _emit_search_hint에 "medium_present" reason 추가
- **공격:** lines 313-315의 새 reason `medium_present`가 Action #2 line 210의 호출과 일치하는지 확인.
- **Gemini 공격 (Logical Collapse):** line 210의 분기 조건 `not any(high) and any(medium) 또는 MEDIUM 결과가 1개 이상일 때`가 단순히 "if any medium"으로 축소되어 HIGH가 있어도 hint가 발생한다.
- **나의 판정:** Gemini의 이 공격은 **부분적으로 유효하나 심각도가 과장**되었다.
  - Line 210의 한국어 원문: `분기 조건: not any(high) and any(medium) 또는 MEDIUM 결과가 1개 이상일 때`. "또는" 앞뒤가 OR 조건으로 읽히면 `any(medium)`이 항상 참이 되어 `not any(high)` 조건이 무의미해진다는 Gemini의 지적은 논리적으로 맞다.
  - **그러나**, 이 텍스트는 수정 #10이 도입한 것이 맞다(fix-plan1-round2-working.md의 수정 #10 기록 참조). 따라서 이것은 수정이 도입한 새로운 모호성이다.
  - **심각도 평가:** 이것은 **분기 조건의 자연어 기술이 모호**한 것이지, 코드 로직 자체의 결함이 아니다. 구현 시 체크리스트 line 261 `MEDIUM 결과 존재 시 _emit_search_hint("medium_present") 호출`을 보고 구현할 것이며, 정확한 분기 조건은 코드 작성 시 결정된다. 그러나 설계 문서로서 모호한 분기 조건은 바람직하지 않다.
  - **권장:** line 210을 `분기 조건: not any(high) and any(medium)`으로 단일화하여 모호성 제거. 현재의 "또는 MEDIUM 결과가 1개 이상일 때"는 `any(medium)`의 한국어 풀어쓰기이므로 중복이자 혼동 요인.
- **결과:** MINOR ISSUE FOUND. 수정 #10이 도입한 분기 조건 기술 모호성 1건. 심각도: LOW (구현 차단 아님, 문체 개선 가능).

### Fix #11 (L2): config 파일 목록에 cluster_detection_enabled 추가
- **공격:** line 431 수정 후: `confidence_abs_floor, cluster_detection_enabled, output_mode 추가`. Action #1의 설정 변경(lines 124-131)과 대조: `confidence_abs_floor: 0.0, cluster_detection_enabled: false` + Action #2: `output_mode: "legacy"`. 3개 항목 일치.
- **결과:** PASS.

### Fix #12 (F2): Gate E 추가
- **공격:** line 453의 Gate E 형식이 Gates A-D(lines 449-452)와 일관적인지 확인.
  - Gates A-D: 번호 + **Gate X** (Action 후) + 검증 기준 기술
  - Gate E: `5. **Gate E** (Action #4 후): Agent hook이 feat/agent-hook-poc 브랜치에서 정상 로드되고, 4가지 핵심 질문(레이턴시, 컨텍스트 주입 메커니즘, Plugin 호환성, 하이브리드 연쇄)에 대한 답변이 temp/agent-hook-poc-results.md에 문서화됨`
  - 형식: 번호 + bold gate name + (Action 후) + 검증 기준. Gates A-D와 동일 패턴.
  - "4가지 핵심 질문"이 Action #4 본문(lines 369-373)과 일치하는지: (1) 레이턴시, (2) 컨텍스트 주입 메커니즘, (3) Plugin 호환성, (4) 하이브리드 연쇄. 본문의 4가지 질문과 정확히 일치.
- **결과:** PASS. 형식과 내용 모두 일관적.

### Fix #13 (M3): Finding #5 추적 노트
- **공격:** line 497의 추적 노트가 `plan-import-hardening.md`를 참조하는데, 이 파일이 존재하는지 확인.
- **검증:** `glob action-plans/plan-import-hardening.md` -> 파일 없음. 이는 아직 생성되지 않은 미래 plan이다.
- **판정:** 이것은 문제가 아니다. 추적 노트는 "별도 plan으로 추적 필요"라는 의도이며, 아직 생성되지 않은 것은 이 plan의 status가 "not-started"인 것과 일관적이다. 향후 구현 시 해당 plan을 생성하면 된다.
- **결과:** PASS.

### Fix #14 (추가): Action #2 체크리스트 항목 2건 추가
- **공격:** lines 260-261의 새 체크리스트 항목이 본문의 설계 명세와 일치하는지 확인.
  - Line 260: `모든 결과 LOW 시 <memory-context> 래퍼 생략, _emit_search_hint("all_low")만 호출` -- line 216의 본문과 일치.
  - Line 261: `MEDIUM 결과 존재 시 _emit_search_hint("medium_present") 호출` -- line 210의 호출과 일치.
- **결과:** PASS.

### Fix #15 (추가): medium_present 분기 조건 명시
- **공격:** Fix #10과 동일 이슈 -- line 210의 분기 조건 "또는" 모호성. Fix #10에서 이미 분석 완료.
- **결과:** Fix #10의 판정 참조 (LOW 모호성 1건).

---

## Part 2: Adversarial Attacks Summary

### 수정이 도입한 새로운 문제

| # | 심각도 | 수정 | 이슈 |
|---|--------|------|------|
| 1 | LOW | Fix #10 (L5) | Line 210의 분기 조건 `not any(high) and any(medium) 또는 MEDIUM 결과가 1개 이상일 때`에서 "또는" 뒤의 절이 앞 조건을 논리적으로 무효화하는 모호한 기술. 구현자가 단순히 `any(medium)`으로 해석할 위험 |

**새로운 문제 총 1건 (LOW 1건).**

### Gemini 3.1 Pro 공격 반론

| Gemini 주장 | 심각도 | 내 판정 | 이유 |
|-------------|--------|---------|------|
| Implementation Sequence Paradox (abs_floor가 Action #2 시그니처에서만 추가) | CRITICAL | FALSE POSITIVE | Action #1의 체크리스트는 `confidence_label()` 자체의 수정에 집중. `_output_results()` 시그니처는 Action #2에서 추가되며, line 142는 Action #2 구현 시 따를 가이드. 체크리스트 배치가 혼동을 줄 수는 있으나 pre-existing 이슈이며 수정이 도입한 것이 아님 |
| Logical Collapse in Hint Trigger | HIGH | PARTIALLY VALID (LOW로 하향) | "또는" 구문의 모호성은 인정하나, 설계 문서의 자연어 기술이며 코드 로직이 아님. 체크리스트(line 261)는 명확하므로 구현 차단 아님 |
| Semantic Oxymoron (70%+ tautology) | LOW | FALSE POSITIVE | "(tautology)"는 dead code 증명(line 74 후반)을 지칭하며 "70%+"는 발동 빈도를 지칭. 한 문장에 두 개념이 압축되어 있지만 수정 전에도 동일한 구조였으며, 수정은 "모든"을 "대다수(70%+)"로 개선한 것 |

---

## Part 3: Fresh Eyes Assessment

### 전체 문서 흐름

전체적으로 문서의 흐름은 논리적이다: 배경 -> Action #1(기반) -> Action #2(핵심) -> Action #3(보조) -> Action #4(실험) -> 횡단 관심사. 각 Action 내에서 목적 -> 관련 정보 -> 테스트 영향 -> 설정 -> 진행 상황의 구조가 일관적이다.

### Fix #5 (L6) 가독성 개선 평가

Line 83의 `> **구현 결론:** ...` 1줄 요약은 효과적이다. blockquote의 나머지 12줄은 역사적 맥락인데, 요약이 먼저 오므로 구현자가 결론을 빠르게 파악하고 상세 이력은 필요할 때만 읽을 수 있다. 그러나 blockquote 전체가 여전히 하나의 시각적 블록으로 보이므로, "구현 결론"과 "검토 이력" 사이에 빈 줄이나 하위 구분이 있으면 더 좋았을 것이다. 이것은 사소한 포매팅 제안이며 현재도 충분히 읽을 수 있다.

### Fix #4 (L7) body_bonus 정의 평가

Line 83-85 영역에서 `body_bonus`가 처음 등장할 때 바로 정의가 삽입되어 있다: `(body_bonus: 본문 토큰 매칭 보너스 0-3점, score_with_body() line 247에서 계산)`. 자연스럽게 삽입되어 있으며, 코드 참조까지 포함하여 처음 읽는 엔지니어도 즉시 이해할 수 있다.

### Gate E 형식 일관성

Gates A-E가 모두 동일한 패턴(`번호. **Gate X** (조건): 검증 기준`)을 따른다. Gate E는 Action #4의 4가지 핵심 질문을 명시적으로 나열하여 pass/fail 기준이 명확하다. Gates A-C보다 오히려 더 구체적이다.

### 여전히 개선 가능한 부분 (사소)

1. **Line 210의 "또는" 분기 조건 모호성** (Fix #10이 도입, 상기 Part 2에서 분석)
2. **Action #1의 line 142 체크리스트 항목이 실제로는 Action #2에서 완료해야 하는 내용** (pre-existing, 수정이 도입한 것 아님) -- 구현자에게 혼동을 줄 수 있으나, line 108의 "호출 지점 변경" 섹션과 Action #2의 체크리스트(line 254)를 함께 읽으면 해소됨
3. **Cluster detection 비활성 반복 언급** (pre-existing, fresh review B4에서 이미 지적) -- 수정으로 악화되지 않았으며, 비활성 기능의 명시적 확인은 방어적 엔지니어링 관점에서 유효

---

## Part 4: Code Cross-Verification

| Plan 주장 | 코드 실제 | 결과 |
|-----------|----------|------|
| `confidence_label()` at line 161-174 | `memory_retrieve.py:161-174` 확인 | MATCH |
| `score_with_body()` body_bonus at line 247 | `result["body_bonus"] = min(3, len(body_matches))` 확인 | MATCH |
| `raw_bm25` preservation at line 256 | `r["raw_bm25"] = r["score"]` 확인 | MATCH |
| `score` mutation at line 257 | `r["score"] = r["score"] - r.get("body_bonus", 0)` 확인 | MATCH |
| `_output_results()` at line 262-301 | Function body 확인 | MATCH |
| `confidence_label()` call at line 299 | `conf = confidence_label(entry.get("score", 0), best_score)` 확인 | MATCH |
| `apply_threshold()` at `memory_search_engine.py:283-288` | Lines 283-289 (noise floor 로직) 확인 | CLOSE (off by 1 at end) |
| Hint at line 458 (FTS5 path) | `print("<!-- No matching memories found...")` 확인 | MATCH |
| Hint at line 495 (Legacy path) | `print("<!-- No matching memories found...")` 확인 | MATCH |
| Hint at line 560 (Legacy deep-check) | `print("<!-- No matching memories found...")` 확인 | MATCH |
| TestConfidenceLabel 17개 테스트 | 17개 test methods 확인 (lines 493-562) | MATCH |
| `assets/memory-config.default.json`에 confidence_abs_floor 등 미존재 | 현재 파일에 해당 키 없음 (구현 전이므로 정상) | MATCH |

**코드 교차 검증: 12/12 항목 통과 (1건 off-by-1, 기능적 문제 아님).**

---

## Part 5: Gemini 3.1 Pro External Validation

Gemini가 제기한 주요 공격 3건에 대한 최종 판정:

1. **Implementation Sequence Paradox**: FALSE POSITIVE. Action #1의 체크리스트 경계를 오해한 것. line 142는 Action #2 구현 가이드이며, `_output_results()` 시그니처 확장은 Action #2 체크리스트(line 254)에 명시적으로 있다.

2. **Logical Collapse in Hint Trigger**: PARTIALLY VALID (LOW). line 210의 "또는" 구문이 논리적 모호성을 가지는 것은 사실이나, 설계 문서의 자연어 기술이며 체크리스트(line 261)로 충분히 보완된다. 수정 #10이 도입한 새로운 모호성이므로 기록.

3. **Semantic Oxymoron**: FALSE POSITIVE. 문맥을 무시한 형식 논리 공격. "(tautology)"는 line 74 후반의 dead code 증명(`C > max_inject`는 수학적으로 불가능)을 지칭하며, "70%+"는 `>= 3` 원안의 발동 빈도. 수정이 도입한 것이 아닌 pre-existing 구조.

Gemini가 확인한 양호한 수정:
- body_bonus 정의 정확성 (Fix #4) -- 코드와 일치
- Gate E 형식 일관성 (Fix #12) -- Gates A-D와 동일 패턴
- Finding #5 추적 노트 (Fix #13) -- 적절한 범위 위임
- LOC header 수치 (Fix #1) -- table과 정확히 일치

---

## Conclusion

### 판정: PASS WITH NOTES

**15건의 수정이 도입한 새로운 결함: 1건 (LOW)**
- Fix #10: line 210의 분기 조건 "또는" 모호성. `not any(high) and any(medium) 또는 MEDIUM 결과가 1개 이상일 때`를 `not any(high) and any(medium)`으로 단일화하면 해소됨.

**가독성 개선 확인:**
- Fix #5 (구현 결론 요약): 효과적. blockquote의 핵심을 첫 줄에 배치하여 읽기 부담 감소.
- Fix #4 (body_bonus 정의): 효과적. 처음 읽는 엔지니어의 코드 참조 필요성 제거.
- Fix #12 (Gate E): 효과적. Action #4의 pass/fail 기준이 명확해짐.
- Fix #1 (LOC 통일): 효과적. header와 상세 table 간 수치 모순 해소.

**Gemini의 CRITICAL/HIGH 판정은 모두 기각 또는 하향 조정됨.** Implementation Sequence Paradox는 Action 경계 오해, Logical Collapse는 LOW 수준 자연어 모호성, Semantic Oxymoron은 문맥 무시.

**권장 조치 (선택):**
1. Line 210의 "또는 MEDIUM 결과가 1개 이상일 때" 삭제 -> 모호성 제거 (LOW, 구현 비차단)

---

*Verified by Opus 4.6 (independent verifier #2)*
*External validation: Gemini 3.1 Pro via pal clink*
