# V1-Consistency Review: plan-poc-retrieval-experiments.md (Round 2 -- Post-Edit Verification)

**Reviewer:** V1-Consistency (Claude Opus 4.6)
**Date:** 2026-02-22
**Plan file:** `/home/idnotbe/projects/claude-memory/action-plans/plan-poc-retrieval-experiments.md` (555 lines)
**Editor input:** `/home/idnotbe/projects/claude-memory/temp/editor-input-findings.md`
**Authoritative source:** `/home/idnotbe/projects/claude-memory/temp/41-final-report.md`

**Scope:** Verify that all 8 edits from the editor-input-findings are internally consistent with the existing plan content. Check for contradictions, duplications, and confusing overlaps.

---

## Overall Verdict: PASS WITH NOTES

All 8 edits have been applied and are internally consistent with existing plan content. No contradictions found. Three minor items flagged for editor awareness, none blocking.

---

## A. Finding #1 REJECTION Block (L220-241) vs Existing Content

### A1. Does the REJECTION block contradict the "핵심 문제" section (L189-213)?

**PASS -- No contradiction.**

The "핵심 문제" section at L189-213 describes three *problems*: (1) single result always "high", (2) relative noise floor, (3) OR combination. The REJECTION block at L220-241 addresses a *proposed fix* for problem #1 and explains why that fix was rejected. The problems themselves remain valid independent of which fix approach is adopted. The two sections serve different purposes (problem identification vs. fix disposition) and are fully compatible.

### A2. Does any text still imply raw_bm25 WILL be used for confidence_label()?

**PASS -- No residual implication.**

Verified all `raw_bm25` references in the plan:
- L222: "raw_bm25 코드 변경 REJECTED" -- explicitly rejected
- L238: "Lines 283, 299의 코드 변경 **없음** -- `confidence_label()`은 현행 composite score 유지" -- explicitly states no change
- L240: "`raw_bm25`는 진단 로깅 전용 (confidence labeling에 사용하지 않음)" -- explicitly diagnostic only
- L243-247: Triple-field logging uses `raw_bm25` for *analysis*, not for confidence labeling -- consistent
- L100: Code reference table says `memory_retrieve.py:161-174` relates to "`confidence_label()` 상대 비율 문제" -- this is a neutral problem reference, not a fix direction. **Consistent.**

No text anywhere implies `raw_bm25` will be used for `confidence_label()`.

### A3. Does the "핵심 문제" section (L189-213) still make sense with the REJECTION block inserted after it?

**PASS.**

The narrative flow reads naturally:
1. L189-213: Three problems described with code references
2. L220-241: REJECTION block explaining why the obvious fix for problem #1 was rejected, and what the actual resolution is
3. L243-258: Alternative measurement approach (triple-field logging, dual precision, label_precision)

The REJECTION block serves as a "course correction" narrative that bridges the problem statement and the measurement methodology. Logical progression maintained.

### A4. "ranking-label inversion" example values

**PASS.** The example at L227-233 uses:
```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)
```

Math check: A: `-1.0 - 3 = -4.0` (correct). B: `-3.5 - 0 = -3.5` (correct). Ranking: -4.0 < -3.5, so A is ranked higher (more negative = better per `memory_search_engine.py:280`). `raw_bm25` labels: `abs(-1.0)/abs(-3.5) = 0.286` -> "low" (< 0.40). `abs(-3.5)/abs(-3.5) = 1.0` -> "high" (>= 0.75). **All math and label assignments are correct per `confidence_label()` at `memory_retrieve.py:161-174`.**

---

## B. Finding #2 Cluster Tautology Note (L186-187)

### B1. Does the note contradict anything in PoC #5 description?

**PASS WITH NOTE.**

The note at L186-187 says cluster detection's independent variable contribution is **0** (dead code). The PoC #5 "목적" at L184 says: "Action #1 (절대 하한선 + 클러스터 감지) 사전/사후 비교 baseline 확보."

The mention of "클러스터 감지" in L184 is technically misleading since the Finding #2 note 2 lines below proves it contributes nothing. However, this is **not a logical contradiction** -- it's a residual label. Action #1 in Plan #1 is named/scoped as "절대 하한선 + 클러스터 감지" even though the cluster detection portion is dead code. The Finding #2 note immediately clarifies this.

**NOTE (non-blocking, carried from Round 1):** Consider updating L184 to "Action #1 (절대 하한선; 클러스터 감지는 Finding #2에서 dead code로 확인됨)" for precision. However, this is a pre-existing label from before the edits and is not something the editor introduced.

### B2. Is the cross-reference to "Plan #1" accurate?

**PASS.**

The cluster tautology concerns `cluster_count > max_inject` in `confidence_label()` / Action #1's cluster detection feature, which is defined in Plan #1 (plan-retrieval-confidence-and-output.md). "Plan #1 참조" is correct. It is not Plan #2 (logging) or Plan #3 (this PoC plan).

---

## C. Finding #5 Import Crash Note (L73-83)

### C1. Is the `e.name` scoping code consistent with existing import patterns?

**PASS.**

The plan does not describe other import patterns for `memory_logger` (it doesn't exist yet -- Plan #2 creates it). The code pattern shown is:
```python
try:
    from memory_logger import emit_event
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_logger':
        raise  # transitive dependency failure -> fail-fast
    def emit_event(*args, **kwargs): pass
```

This matches the authoritative source (`temp/41-final-report.md:96-103`) exactly. The `e.name` attribute is a Python 3.3+ feature on `ModuleNotFoundError` (subclass of `ImportError`) that stores the module name. Using `getattr` with a fallback to `None` is defensive for older Python versions. **Pattern is valid and consistent.**

The actual codebase has bare `from memory_judge import judge_candidates` imports at `memory_retrieve.py:429` and `memory_retrieve.py:503` (verified). The note at L83 correctly identifies these as needing the same hardening pattern.

### C2. Does the note correctly say "Plan #2 범위"?

**PASS.**

L73: "Plan #2 범위" is correct. The `memory_logger.py` module creation is Plan #2's responsibility (logging infrastructure). The note is positioned as a dependency note within Plan #3, not as a work item. L83 explicitly says "Plan #2 Phase 1의 선행 조건". **Consistent with the plan's scope boundaries.**

### C3. Source code line number references in the note

| Reference | Actual code | Status |
|-----------|-------------|--------|
| `memory_retrieve.py:429` | `from memory_judge import judge_candidates` (FTS5 path) | **CORRECT** |
| `memory_retrieve.py:503` | `from memory_judge import judge_candidates` (legacy path) | **CORRECT** |

---

## D. NEW-1 Noise Floor Note (L201-208)

### D1. Worked example score values vs existing noise floor description

**PASS.**

Existing noise floor description at L196-199:
```python
noise_floor = best_abs * 0.25  # 약한 best_score -> 약한 noise floor
```

NEW-1 worked example at L203-207:
```
Best: raw=-2.0, bonus=3 -> composite=-5.0 -> floor=1.25
Victim: raw=-1.0, bonus=0 -> composite=-1.0 -> abs(1.0) < 1.25 -> 제거됨
```

Math verification:
- Best composite: `-2.0 - 3 = -5.0` (consistent with `memory_retrieve.py:257`: `r["score"] = r["score"] - r.get("body_bonus", 0)`)
- Floor: `abs(-5.0) * 0.25 = 1.25` (consistent with `memory_search_engine.py:284-287`)
- Victim composite: `-1.0 - 0 = -1.0`
- Filter: `abs(-1.0) = 1.0 < 1.25` -> removed (consistent with `memory_search_engine.py:287`: `abs(r["score"]) >= noise_floor`)

**All values are mathematically correct and consistent with the actual codebase implementation.**

### D2. Does "deferred to PoC #5" disposition make sense?

**PASS.**

L208: "PoC #5의 triple-field 로깅 데이터(`body_bonus` 필드 포함)로 실제 발생 빈도를 확인한 후 결정."

PoC #5 (L182-285) measures BM25 precision with triple-field logging that includes `body_bonus` (L243). Using PoC #5's data to measure how often the noise floor distortion actually occurs is a logical deferred disposition. The note also correctly observes that "현재 Plan #1은 `memory_search_engine.py` 변경을 명시적으로 배제" (L208), which aligns with Plan #1's documented scope.

---

## E. Risk Table Additions (L425-426)

### E1. Format consistency

**PASS.**

Existing table header (L416): `| 위험 | 심각도 | PoC | 완화 |`

Both new rows follow the 4-column pipe format:
- L425: `| Judge 모듈 미배포 시 hook 크래시 | 중간 | #5, #6, #7 | ... |` -- 4 columns
- L426: `| Judge가 모든 후보를 거부하면... | 낮음 | #5 | ... |` -- 4 columns

### E2. Severity levels vs `41-final-report.md`

**NOTE (minor):**

The editor input (Item 7, line 169) prescribed "높음" for the NEW-2 row. The `temp/41-final-report.md:30` says "Judge import vulnerability | HIGH". But the plan at L425 uses "중간" (MEDIUM).

**Analysis:** This risk table describes *risks to PoC execution* and their mitigations, not the severity of code findings. Other existing rows use similar "residual risk" semantics (e.g., "Agent hook이 컨텍스트 주입을 지원하지 않음 | 중간" -- the uncertainty is medium because there's a clear mitigation). Since the mitigation for NEW-2 is already described (Finding #5 fix with `e.name` scoping), the residual risk to PoC execution is indeed medium-ish.

**However**, the editor input explicitly prescribed "높음", so the plan deviates from the editor specification. This may be intentional or a transcription adjustment by the editor who applied the changes.

**Recommendation:** Editor should confirm whether "중간" at L425 is intentional (residual risk interpretation) or should be "높음" (finding severity interpretation) to match the editor input.

### E3. NEW-3 severity

L426 uses "낮음" (LOW). `temp/41-final-report.md:31`: "Empty XML after judge rejects all candidates | LOW". Editor input (Item 8, line 189) also says "낮음". **Consistent across all sources.**

---

## F. Review History Update (L554)

### F1. Accuracy of the updated Deep Analysis row

**PASS.**

L554: `| Deep Analysis (7-agent) | Methodology refined + Finding #1 REJECTED | PoC #5: **raw_bm25 confidence 코드 변경 REJECTED** (NEW-4 ranking-label inversion), label_precision metric + triple-field logging + human annotation, abs_floor composite domain 교정. PoC #6: BLOCKED -> PARTIALLY UNBLOCKED via --session-id CLI param. |`

Cross-checked against actual edits in the plan:
- "raw_bm25 confidence 코드 변경 REJECTED" -> L222-224: confirmed
- "NEW-4 ranking-label inversion" -> L224, L226-234: confirmed
- "label_precision metric" -> L249-254: confirmed
- "triple-field logging" -> L243: confirmed
- "human annotation" -> L256-258: confirmed
- "abs_floor composite domain 교정" -> L239: confirmed
- "BLOCKED -> PARTIALLY UNBLOCKED via --session-id CLI param" -> L340, L346-351: confirmed

**All described changes are present in the plan.**

### F2. Format consistency with other rows

**PASS.** Uses the same `| 검토 | 결과 | 핵심 발견 |` format. The "결과" value "Methodology refined + Finding #1 REJECTED" is descriptive, consistent with other rows like "APPROVE WITH CHANGES" and "HIGH -> fixed".

---

## G. `--session-id` Checkbox (L495)

### G1. Does the checkbox fit naturally in PoC #6 checklist?

**PASS.**

Surrounding context:
```
L493: ### PoC #6: Nudge 준수율 측정
L494: - [ ] 선행 의존성 확인: Action #2 구현 완료 여부
L495: - [ ] `--session-id` CLI 파라미터 구현 (...)
L496: - [ ] Plan #2에 `/memory:search` skill 호출 로깅 추가 요청 전달
```

Logical flow: first check dependencies, then implement the prerequisite CLI parameter, then proceed with other setup. **Natural progression.**

### G2. Position correctness

The editor input (Item 11) specified placement after "선행 의존성 확인" (which was L447 in the pre-edit plan, now L494 after insertions). The checkbox is at L495, immediately after L494. **Correct relative position.**

### G3. Content consistency with the Deep Analysis resolution

L495: `--session-id CLI 파라미터 구현 (memory_search_engine.py에 argparse 추가, 우선순위: CLI arg > CLAUDE_SESSION_ID env var > 빈 문자열)`

This matches:
- L346-348: Deep Analysis resolution for Finding #4
- L360: Dependency list entry: "`--session-id` CLI 파라미터 -- `memory_search_engine.py`에 추가 필요"
- `temp/41-final-report.md:83-84`: "Add `--session-id` argparse param to `memory_search_engine.py` (optional, default empty) / Resolve precedence: `CLI arg > CLAUDE_SESSION_ID env var > empty string`"

**Fully consistent across all references.**

---

## H. Cross-References

### H1. Stale line number references due to inserted content

All line number references in the plan refer to **source code files** (not plan lines), so content insertions do not make them stale. Verified each reference against the actual codebase:

| Plan reference | Target file + line | Verified content | Status |
|----------------|-------------------|------------------|--------|
| `memory_retrieve.py:161-174` (L100, L191) | `confidence_label()` function | Yes, exact match | **CORRECT** |
| `memory_retrieve.py:262-301` (L101) | `_output_results()` function | Yes, exact match | **CORRECT** |
| `memory_retrieve.py:458, 495, 560` (L102) | 0-result hint print statements | 458=hint, 495=hint, 560=hint | **CORRECT** |
| `memory_search_engine.py:205-226` (L103) | `build_fts_query()` function | Yes, exact match | **CORRECT** |
| `memory_search_engine.py:283-288` (L104, L202) | `apply_threshold()` noise floor | Yes, exact match | **CORRECT** |
| `memory_retrieve.py:283` (L223, L238) | `best_score = max(...)` | Yes, `_output_results` body | **CORRECT** |
| `memory_retrieve.py:299` (L223, L238) | `conf = confidence_label(...)` | Yes, `_output_results` body | **CORRECT** |
| `memory_retrieve.py:429` (L83) | `from memory_judge import judge_candidates` (FTS5) | Yes, exact match | **CORRECT** |
| `memory_retrieve.py:503` (L83) | `from memory_judge import judge_candidates` (legacy) | Yes, exact match | **CORRECT** |
| `memory_search_engine.py:226` (L210, L294) | `return " OR ".join(safe)` | Yes, exact match | **CORRECT** |
| `memory_search_engine.py:284-287` (L202) | noise floor calculation block | Yes, exact match | **CORRECT** |

**No stale references found.** All source code line numbers are accurate as of the current codebase.

### H2. File path references

| Referenced path | Exists in codebase? |
|----------------|---------------------|
| `hooks/scripts/memory_retrieve.py` | **YES** |
| `hooks/scripts/memory_search_engine.py` | **YES** |
| `temp/agent-hook-verification.md` | Not verified (non-critical for consistency) |

---

## I. Terminology Consistency

### I1. "composite score" vs "복합 점수"

Both terms are used throughout the plan:
- English: L220 "Score Domain", L239 "composite domain", L243 "composite", L247 "composite"
- Korean: L243 "복합 점수 = BM25 - body_bonus", L246 "최종 `score` (복합)"

**PASS.** The definition at L243 explicitly bridges both terms: "`score` (복합 점수 = BM25 - body_bonus)". The Korean and English forms are used interchangeably but consistently.

### I2. "raw_bm25" spelling

All occurrences in the plan: L202, L206, L222, L224, L229, L231, L240, L243, L245, L247, L554.

**PASS.** Consistently spelled `raw_bm25` with underscore and all lowercase. No variants found.

### I3. "ranking-label inversion" -- new term

First used at L224: "**ranking-label inversion** (NEW-4)이 발견되어"

The term is defined by the immediately following code example (L227-234), which shows Entry A ranked #1 getting "low" label while Entry B ranked #2 gets "high" label. The term appears again at L554 in the review history.

**PASS.** The term is self-descriptive ("ranking order and label assignment are inverted"), defined-by-example on first use, and used consistently.

### I4. Additional terminology checks

- "abs_floor": Used at L187, L239, L249, L554. Consistently refers to the absolute floor threshold in `confidence_label()`. **Consistent.**
- "body_bonus": Used at L202, L204, L206, L208, L229, L231, L243, L247. Always refers to the score adjustment from body text matching. **Consistent.**
- "triple-field logging" / "triple-field": L243, L208, L554. Always refers to logging `raw_bm25`, `score`, `body_bonus` per result. **Consistent.**
- "label_precision": L250-253, L554. Always refers to the label classification accuracy metric. **Consistent.**
- "tiered output": L233, L241, L354. Always refers to Action #2's confidence-based injection format selection. **Consistent.**

---

## Duplication Check

### Are any newly inserted items duplicating existing content?

1. **Finding #1 REJECTION (L220-241):** The existing V2-adversarial block header was at the old L196 (now L220). The REJECTION block is new content inserted within it, not a duplication. The existing triple-field logging text (L243+) was already present and remains. **No duplication.**

2. **Finding #2 note (L186-187):** Cluster tautology is a new concept not previously mentioned anywhere in the plan. **No duplication.**

3. **Finding #5 note (L73-83):** Import crash handling is a new concept. The dependency mapping table (L66-71) mentions what log events are consumed but says nothing about import safety. **No duplication -- complementary content.**

4. **NEW-1 note (L201-208):** Noise floor distortion is a new analysis. The existing L196-199 describes the noise floor *mechanism*; NEW-1 describes a specific *distortion scenario*. **No duplication -- extends existing content.**

5. **Risk table rows (L425-426):** Neither "judge module crash" nor "empty XML output" were previously in the risk table. **No duplication.**

6. **Review history (L554):** Replaces the previous Deep Analysis row. **No duplication.**

7. **`--session-id` checkbox (L495):** Not previously in the checklist. L360 mentions it as a dependency but the checklist implementation item is new. **No duplication -- different purpose (dependency vs. task).**

---

## Summary of Findings

| Check | Result | Severity | Details |
|-------|--------|----------|---------|
| A. Finding #1 REJECTION vs existing | **PASS** | -- | No contradiction. REJECTION complements problem statement. Math verified. |
| B. Finding #2 cluster tautology | **PASS WITH NOTE** | LOW | "Plan #1 참조" is correct. L184 still says "클러스터 감지" but Finding #2 immediately clarifies it's dead code. Pre-existing wording, not introduced by edits. |
| C. Finding #5 import crash | **PASS** | -- | `e.name` pattern valid. "Plan #2 범위" correct. Line refs verified. |
| D. NEW-1 noise floor | **PASS** | -- | Math correct. Deferred-to-PoC-#5 logically sound. |
| E. Risk table rows | **PASS WITH NOTE** | LOW | NEW-2 severity "중간" vs editor input "높음" -- possible intentional residual-risk interpretation. NEW-3 severity correct. Format correct. |
| F. Review history | **PASS** | -- | All described changes verified present in plan. Format consistent. |
| G. `--session-id` checkbox | **PASS** | -- | Correct position, content matches all references. |
| H. Cross-references | **PASS** | -- | All 11 source code line references verified correct. No stale refs. |
| I. Terminology | **PASS** | -- | All terms used consistently. New term defined on first use. |
| Duplication check | **PASS** | -- | No duplicated content found. |

---

## Flagged Items (non-blocking)

1. **[LOW] PoC #5 Purpose line (L184):** Still says "Action #1 (절대 하한선 + 클러스터 감지)" despite Finding #2 note at L186-187 proving cluster detection contributes nothing. This is pre-existing wording (not introduced by the edits) and immediately corrected by the Finding #2 note. Consider clarifying if the plan is revised further.

2. **[LOW] Risk table NEW-2 severity (L425):** Uses "중간" where the editor input specified "높음". May be intentional (residual risk vs. finding severity). Recommend editor confirms.

3. **[INFORMATIONAL] PoC #5 Purpose line (L184) and label_precision:** The Purpose says "precision@k... 사전/사후 비교 baseline" but the Deep Analysis block (L249-254) clarifies that Action #1 won't change precision@k (only label_precision changes). These are not contradictory (precision@k serves as a general BM25 quality baseline, not an Action #1 comparison metric), but could confuse a reader who doesn't read the Deep Analysis block. Flagged from Round 1; noted again for completeness.

**No contradictions, logical errors, or harmful inconsistencies found. All edits are internally consistent with the existing plan.**
