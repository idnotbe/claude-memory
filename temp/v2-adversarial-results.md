# V2-Adversarial Review: plan-poc-retrieval-experiments.md

**Reviewer:** V2-Adversarial
**Date:** 2026-02-22
**Verdict:** APPROVE WITH NOTES (no CRITICAL findings, several HIGH/MEDIUM)

---

## V1 Fixes Verification

### V1 Fix #1: L184 -- label_precision vs precision@k clarification + cluster detection dead code

**Status: CORRECTLY APPLIED**

Plan L184 now reads:
> "precision@k는 BM25 일반 품질 baseline이며, Action #1 전후 비교 지표는 **label_precision** (ranking 불변이므로 precision@k는 동일)."

Additionally, L186-187 adds the cluster tautology blockquote from Finding #2.

The fix correctly distinguishes precision@k (BM25 baseline quality) from label_precision (Action #1 before/after metric), and correctly notes cluster detection is dead code.

### V1 Fix #2: L425 -- NEW-2 severity changed from "중간" to "높음"

**Status: CORRECTLY APPLIED**

Plan L425 risk table row:
> `| Judge 모듈 미배포 시 hook 크래시 | 높음 | #5, #6, #7 | ...`

Severity is "높음" (HIGH), matching the final report's NEW-2 severity of HIGH.

---

## Technical Attacks

### Finding T-1: Line number references in plan vs actual source code

**Severity: MEDIUM (confusing)**

The plan makes specific line-number references that need verification against the actual source files.

| Plan Reference | Claimed Line(s) | Actual Line(s) | Verdict |
|----------------|-----------------|-----------------|---------|
| `confidence_label()` -- "memory_retrieve.py:161-174" (L100) | 161-174 | **161-174** | CORRECT |
| `_output_results()` -- "memory_retrieve.py:262-301" (L101) | 262-301 | **262-301** | CORRECT |
| 0-result hint -- "memory_retrieve.py:458, 495, 560" (L102) | 458, 495, 560 | **458, 495, 560** | CORRECT |
| `build_fts_query()` OR join -- "memory_search_engine.py:205-226" (L103) | 205-226 | **205-226** | CORRECT |
| `apply_threshold()` noise floor -- "memory_search_engine.py:283-288" (L104) | 283-288 | **283-288** | CORRECT |
| Judge import FTS5 path -- "memory_retrieve.py:429" (L83) | 429 | **429** | CORRECT |
| Judge import legacy path -- "memory_retrieve.py:503" (L83) | 503 | **503** | CORRECT |
| `hooks.json` UserPromptSubmit -- "43-55" (L99) | 43-55 | **54-66** (actual JSON lines) | INCORRECT |

**Details on hooks.json lines:** The plan claims "hooks.json: 43-55" for the current UserPromptSubmit hook. The actual `hooks.json` file has the UserPromptSubmit section at lines **54-66**. Lines 43-55 actually span the end of the PostToolUse section and the start of the UserPromptSubmit section. This is misleading for someone following the plan to locate the relevant code.

### Finding T-2: Noise floor math example in NEW-1 blockquote

**Severity: LOW (cosmetic, but math is slightly misleading)**

Plan L202-207:
```
Best: raw=-2.0, bonus=3 → composite=-5.0 → floor=1.25
Victim: raw=-1.0, bonus=0 → composite=-1.0 → abs(1.0) < 1.25 → 제거됨
```

The math itself is correct:
- `abs(-5.0) * 0.25 = 5.0 * 0.25 = 1.25` -- CORRECT
- `abs(-1.0) = 1.0 < 1.25` -- CORRECT, victim is removed

However, the notation `composite=-5.0 → floor=1.25` skips a step. A pedantic reader might think `|-5.0| * 0.25 = -1.25`, not 1.25. The calculation is `abs(best_score) * 0.25 = abs(-5.0) * 0.25 = 5.0 * 0.25 = 1.25`. The plan omits the `abs()` step in the narrative, though the code at L284-286 clearly uses `abs()`. Minor but could cause a moment of confusion.

### Finding T-3: `e.name` scoping pattern -- potential Python version concern

**Severity: LOW (informational)**

Plan L79 and L83 rely on `getattr(e, 'name', None) != 'memory_logger'`. The `ImportError.name` attribute was added in Python 3.3. Given that Claude Code likely runs on Python 3.10+, this is not a practical concern. However, the plan does not state a minimum Python version requirement. If someone ran this on a very old Python, `e.name` would return `None` (via `getattr` default), and the condition `None != 'memory_logger'` would be `True`, causing a re-raise -- which is actually the SAFER behavior (fail-fast). So the pattern degrades safely. No action needed.

### Finding T-4: Ranking-label inversion example -- score calculation verification

**Severity: LOW (correct but incomplete)**

Plan L228-233:
```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)
```

Let me verify: `composite = raw_bm25 - body_bonus` (from `memory_retrieve.py:257`: `score = score - body_bonus`).
- Entry A: `-1.0 - 3 = -4.0` -- CORRECT
- Entry B: `-3.5 - 0 = -3.5` -- CORRECT
- Ranking: more negative = better, so -4.0 < -3.5, A is ranked #1 -- CORRECT

The raw_bm25 confidence labels claim: A="low", B="high". Let me verify via `confidence_label()`:
- `best_score` (if using raw_bm25) would be `max(abs(-1.0), abs(-3.5))` = 3.5
- Entry A: `abs(-1.0) / 3.5 = 0.286` -- below 0.40, so "low" -- CORRECT
- Entry B: `abs(-3.5) / 3.5 = 1.0` -- above 0.75, so "high" -- CORRECT

All math checks out.

### Finding T-5: `build_fts_query()` line reference

**Severity: MEDIUM (misleading)**

Plan L210 states: `OR 결합 (memory_search_engine.py:226)`, and L103 says `memory_search_engine.py:205-226`.

The actual `return " OR ".join(safe)` is at line **226** -- CORRECT.

However, the plan L296-299 shows a code example:
```python
return " OR ".join(safe)
# "React error handling" → '"react"* OR "error"* OR "handling"*'
```

This is **slightly inaccurate**. Looking at the actual code (L214-226), the `tokenize()` function (used by `build_fts_query` callers) filters stop words and tokens with `len <= 1`. The word "error" has `len > 1` and is not in `STOP_WORDS`, so it passes. But the word "handling" is also not in `STOP_WORDS`, so it also passes. The example is technically correct.

However, the plan's example implies all three words survive tokenization. Let me verify: "react" (6 chars, not stop), "error" (5 chars, not stop), "handling" (8 chars, not stop). All three would survive. CORRECT.

Actually, wait -- `build_fts_query` receives pre-tokenized `tokens`, not raw text. The upstream `tokenize()` call in `memory_retrieve.py:411` does `list(tokenize(user_prompt))`. The `tokenize()` function (L96-100 of search engine) uses `_COMPOUND_TOKEN_RE` (default, non-legacy), filters `len > 1` and not in STOP_WORDS. All three tokens pass. The example is correct.

---

## Logic Attacks

### Finding L-1: PoC #7 token matching estimation is approximate and unstated

**Severity: MEDIUM (hidden assumption)**

Plan L326-332 describes how to estimate token-level matching:
```python
result_tokens = tokenize(result["title"]) | result["tags"]
matched_tokens = query_tokens & result_tokens
matched_token_count = len(matched_tokens)
```

The plan acknowledges "이 방식은 body bonus까지는 반영하지 못하지만" but there is a deeper hidden assumption: **FTS5 matching uses prefix wildcards** (`"auth"*`), but the plan's intersection uses **exact token matching**. A result titled "authentication guide" would be matched by the FTS5 query `"auth"*` (prefix match), but the Python set intersection `{"auth"} & {"authentication", "guide"}` would return **empty** -- the plan's method would classify this as a 0-token match when it's actually a legitimate match.

This means the plan's `matched_token_count` estimation **systematically undercounts** matches for tokens that match via prefix expansion, leading to an **overestimate of single-token-only matches** (inflated `polluted_query_rate`). The plan does not acknowledge this bias.

**Impact:** Implementers following this method would produce biased metrics, potentially concluding OR-query pollution is worse than it actually is, leading to unnecessary optimization effort.

**Recommendation:** The token matching approximation should either:
1. Use prefix matching (`any(rt.startswith(qt) for rt in result_tokens)`) instead of exact set intersection
2. Or explicitly note this systematic undercount bias in the methodology

### Finding L-2: PoC #5 recall@k -- ground truth challenge unstated

**Severity: MEDIUM (hidden assumption)**

Plan L272: `recall@k` is listed as a metric (also in L513). The formula is `전체 relevant 중 top-k에 포함된 비율`. But to compute recall, you need to know the **total number of relevant documents** for each query. The plan's methodology (L263-278) describes labeling only the top-k results, not the entire corpus.

This means recall@k cannot be computed from the plan's methodology unless the annotator also reviews ALL memories in the corpus for each query (impractical for 50+ queries over a potentially large memory store). The plan silently implies recall is computable from top-k labeling alone, which is only true if k equals the corpus size.

The final report (L77) mentions reframing to label_precision but does not address this recall@k issue. The plan's Progress checklist at L475 includes "precision@3, precision@5, recall@k 계산" as a task, suggesting someone is expected to compute it.

**This is a methodological gap that could waste annotator effort** or produce meaningless recall numbers.

**Recommendation:** Either:
1. Remove recall@k or explicitly note it requires full-corpus annotation (impractical for large stores)
2. Define a "pooled recall" methodology (e.g., union of top-k from multiple retrieval runs as the approximation of the relevant set)

### Finding L-3: Cross-Plan implementation order -- PoC #4 position ambiguity

**Severity: LOW (confusing)**

Plan L532-534:
```
7. PoC #6: Nudge 준수율 탐색적 수집 (Action #2 구현 후)
8. Plan #1 Action #4: Agent Hook PoC (독립, 별도 브랜치에서 병행)
```

But earlier (L52): "결정된 순서: #4 (time-boxed) -> #5 -> #7 -> #6" and the consensus (L62) is that #4 runs FIRST. The Cross-Plan order puts #4 LAST (item 8). The parenthetical "(독립, 별도 브랜치에서 병행)" explains it can run in parallel, but listing it as step 8 contradicts the stated PoC execution order of "#4 first."

A reader could be confused: do they start with #4 (as section "실행 순서 및 근거" says) or do they do it last (as the Cross-Plan order says)?

The resolution is that the Cross-Plan order is about **dependency sequencing** (what blocks what), while the PoC order is about **execution priority**. Since #4 is independent, it floats. But the plan does not make this distinction explicit.

**Recommendation:** Add a note at L534 like: "PoC #4는 위 1-7과 독립적이므로, 실제로는 Step 1과 병행 시작 (PoC 실행 순서 섹션 참조)"

---

## Completeness Attacks

### Finding C-1: Final report severity alignment check

**Severity: N/A (verification)**

| Finding | Final Report Severity | Plan Severity/Framing | Match? |
|---------|----------------------|----------------------|--------|
| #1 Score Domain | HIGH | "CRITICAL → HIGH" (L241) | YES |
| #2 Cluster Tautology | LOW | "dead code" (L187) | YES |
| #3 PoC #5 Measurement | LOW | label_precision metric (L250-254) | YES |
| #4 PoC #6 Dead Path | LOW | "PARTIALLY UNBLOCKED" (L340-351) | YES |
| #5 Logger Import Crash | HIGH | "높음" (L425) | YES |
| NEW-1 | LOW-MEDIUM | "LOW-MEDIUM, deferred" (L202) | YES |
| NEW-2 | HIGH | "높음" (L425) | YES |
| NEW-3 | LOW | "낮음" (L426) | YES |
| NEW-4 | HIGH | Described as inversion, part of Finding #1 rejection (L224-234) | YES |
| NEW-5 | MEDIUM | Described in `e.name` scoping (L79-83) | YES (implicit) |

All severities match the final report. No discrepancies found.

### Finding C-2: Final report code LOC alignment

**Severity: N/A (verification)**

Final report says "Total code changes: ~48 LOC across 2 files." The plan does not claim specific LOC counts in the body, but the risk table and Finding #5 section correctly describe the scope as ~12 LOC for `--session-id` and ~36 LOC for import hardening.

### Finding C-3: Missing final report recommendation about process sizing

**Severity: LOW (omission)**

The final report (L184) recommends: "Use triage sizing. <50 LOC fixes = 2-agent pipeline (analyst + verifier). Reserve the full multi-phase pipeline for >200 LOC architectural changes."

The plan does not include this process recommendation. This is acceptable -- it is a meta-process observation, not a PoC methodology concern. However, it might be valuable for the review history section.

---

## Consistency Attacks

### Finding CO-1: Korean/English consistency in risk table

**Severity: LOW (cosmetic)**

The risk table (L416-426) uses Korean severity labels ("중간", "낮음", "높음") consistently. The review history table (L546-554) uses English exclusively. The metrics summary (L509-517) uses Korean headers with English descriptions. This is a consistent bilingual pattern (Korean for plan body, English for review metadata). No issue.

### Finding CO-2: PoC #6 "PARTIALLY UNBLOCKED" vs checklist ordering

**Severity: LOW (minor)**

The PoC #6 heading (L340) says "PARTIALLY UNBLOCKED" but the checklist (L493-503) starts with `- [ ] 선행 의존성 확인: Action #2 구현 완료 여부`. The `--session-id` CLI implementation is listed as item 2 in the checklist (L495). This ordering is correct -- Action #2 is the primary blocker, and `--session-id` is a secondary requirement. Consistent.

### Finding CO-3: "Plan #1 Action #4" vs "PoC #4" naming

**Severity: MEDIUM (confusing)**

Throughout the plan, "PoC #4" refers to the Agent Hook experiment. But L533 says "Plan #1 Action #4: Agent Hook PoC" -- this conflates the naming. In the earlier plan context (L19), the numbering is established as "4가지 즉시 실행 가능한 개선 액션(#1-#4)과 4가지 데이터 수집 후 결정할 실험(PoC #4-#7)". So "Action #4" (from Plan #1) and "PoC #4" are the SAME thing, just described differently.

However, saying "Plan #1 Action #4: Agent Hook PoC" in a plan that calls it "PoC #4" everywhere else is mildly confusing. A reader might think there are two different things: a Plan #1 Action #4 and a Plan #3 PoC #4.

### Finding CO-4: Dual precision claim vs actual measurement plan

**Severity: MEDIUM (potential implementation gap)**

Plan L245-247:
> - **BM25 품질 질문:** `raw_bm25` 기반 ranking의 precision → "BM25 자체의 검색 품질"
> - **End-to-end 품질 질문:** 최종 `score` (복합) 기반 ranking의 precision → "사용자가 실제로 받는 결과의 품질"

But the PoC #5 methodology (L260-278, Phase A and B) does not explicitly describe HOW to compute dual precision. The annotator labels results based on what they SEE (the final ranked output). To compute raw_bm25-based precision, you would need to RE-RANK results by raw_bm25 and then check which of the top-k results are relevant. The plan does not describe this re-ranking step.

An implementer reading the methodology section would only compute single precision (on the composite-score ranking they observe). The dual precision instruction is buried in the blockquote at L245-247 without operational steps.

**Recommendation:** Add an explicit step in Phase A or B methodology: "For dual precision analysis, also re-rank results by `raw_bm25` field from logs and compute precision on that alternative ranking."

---

## Misleading Content

### Finding M-1: "abs_floor composite domain (range ~0-15)" claim

**Severity: MEDIUM (potentially misleading)**

Plan L239: "abs_floor을 composite domain (range ~0-15, BM25 - body_bonus)으로 교정"

The claim "range ~0-15" needs scrutiny:
- BM25 scores from SQLite FTS5 `rank` function are typically in range [-20, 0] for small corpora (more negative = better). The absolute value range is [0, 20+].
- body_bonus is capped at 3 (from `memory_retrieve.py:247`: `min(3, len(body_matches))`).
- Composite score = BM25 - body_bonus. If BM25 = -10 and bonus = 3, composite = -13, abs = 13.
- If BM25 = -0.5 and bonus = 0, composite = -0.5, abs = 0.5.

The range "~0-15" is a reasonable rough estimate for typical corpora, but it is NOT derived from any formal analysis. BM25 scores depend on corpus size, term frequency, and document frequency. For a very small corpus (e.g., 5 memories), scores might cluster in [-2, 0]. For a larger corpus (hundreds of memories), scores could exceed -15.

The danger: someone calibrating `abs_floor` to "range 0-15" might set it to, say, 3.0. But on a corpus with only 5 memories where the best composite is -2.5 (abs=2.5), that floor would filter everything. Conversely, on a large corpus where composite abs values reach 20+, a floor of 3.0 might be too permissive.

The plan should note that the range is corpus-dependent and any `abs_floor` calibration should be based on **observed score distributions from PoC #5 data**, not a priori range estimates.

### Finding M-2: "Action #1 전후 비교에서 클러스터 감지의 독립변수 기여는 0" could be misread

**Severity: LOW (minor)**

Plan L187: "PoC #5의 Action #1 사전/사후 비교에서 클러스터 감지의 독립변수 기여는 **0**"

This is correct (cluster detection is dead code), but a hasty reader might misinterpret this as "Action #1 has zero effect on PoC #5 measurements" rather than "the cluster detection component of Action #1 contributes zero effect." The sentence correctly specifies "클러스터 감지의 독립변수 기여" but the bolded **0** draws attention away from the qualifier.

---

## Summary of Findings

| # | Finding | Severity | Category | Action Required |
|---|---------|----------|----------|-----------------|
| T-1 | hooks.json line reference 43-55 is incorrect (actual: 54-66) | MEDIUM | Technical | Fix line reference |
| T-2 | Noise floor math skips abs() step in narrative | LOW | Technical | No action |
| T-3 | No minimum Python version stated for e.name | LOW | Technical | No action |
| T-4 | Ranking-label inversion math verified correct | LOW | Technical | No action |
| T-5 | build_fts_query code example verified correct | LOW | Technical | No action |
| L-1 | PoC #7 token matching underestimates prefix matches (systematic bias) | **HIGH** | Logic | Add prefix matching or note bias |
| L-2 | recall@k is not computable from top-k-only annotation | **MEDIUM** | Logic | Define pooled recall method or remove |
| L-3 | Cross-Plan order puts PoC #4 last despite it being first in PoC order | LOW | Logic | Add clarifying note |
| C-1 | All severity levels match final report | N/A | Completeness | Verified |
| C-2 | LOC counts match final report | N/A | Completeness | Verified |
| C-3 | Missing process sizing recommendation from final report | LOW | Completeness | Optional |
| CO-1 | Korean/English usage consistent | LOW | Consistency | No action |
| CO-2 | PARTIALLY UNBLOCKED vs checklist consistent | LOW | Consistency | No action |
| CO-3 | "Plan #1 Action #4" vs "PoC #4" naming conflation | MEDIUM | Consistency | Clarify |
| CO-4 | Dual precision lacks operational steps in methodology | MEDIUM | Consistency | Add re-ranking step |
| M-1 | "range ~0-15" is corpus-dependent, not universal | MEDIUM | Misleading | Add caveat |
| M-2 | "독립변수 기여는 0" could be misread | LOW | Misleading | No action |

**Critical findings: 0**
**High findings: 1** (L-1: systematic prefix-match undercount in PoC #7)
**Medium findings: 6** (T-1, L-2, CO-3, CO-4, M-1, plus recall@k)
**Low findings: 9**

---

## Overall Assessment

The plan is well-constructed and accurately reflects the Deep Analysis final report. All V1 fixes have been correctly applied. All severity levels match the authoritative source. The math examples are correct.

The single HIGH finding (L-1) is actionable and could produce systematically biased metrics if not addressed: the PoC #7 token-matching approximation uses exact set intersection but FTS5 uses prefix wildcards, meaning prefix-expanded matches would be falsely classified as zero-token matches, inflating the `polluted_query_rate` metric. This is the kind of subtle implementation bug that could lead to incorrect optimization decisions.

The MEDIUM findings are mostly about missing operational detail (dual precision re-ranking step, recall@k ground truth, `abs_floor` range caveat) and minor reference errors (hooks.json line numbers). None block implementation but could cause confusion.

**Verdict: APPROVE WITH NOTES.** The HIGH finding (L-1) should be addressed before PoC #7 implementation but does not block the plan's approval.
