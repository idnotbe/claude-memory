# Verification: Session Plan vs rd-08-final-plan.md

**Date:** 2026-02-21
**Scope:** Line-by-line comparison of user's 6-session implementation plan against the source-of-truth document `research/rd-08-final-plan.md`

---

## 1. Session-by-Session Item Check

### Session 1 (Phase 1 -- Foundation)

**1.** [OK] **1a. Tokenizer regex fix** -- Plan says "user_id, React.FC 같은 코딩 식별자 보존". rd-08 Phase 1a (line 155-160) specifies exactly this: `_TOKEN_RE` regex change to preserve compound coding identifiers. Match.

**2.** [OK] **1b. Body content extraction** -- Plan says "카테고리별 JSON 필드에서 검색 가능한 텍스트 추출". rd-08 Phase 1b (lines 162-195) specifies `extract_body_text()` with `BODY_FIELDS` dict, ~50 LOC. Match.

**3.** [OK] **1c. FTS5 runtime check + fallback flag** -- Plan says "FTS5 사용 가능 여부 런타임 체크 + fallback 플래그". rd-08 Phase 1c (lines 197-198) + Decision #7 (lines 135-149) specifies exactly this: `HAS_FTS5` boolean, ~15 LOC try/except. Match.

**4.** [OK] **1d. Compile check + unit validation** -- Plan says "컴파일 체크 + 토크나이저/body 추출 단위 검증". rd-08 Phase 1d (lines 200-204) specifies compile check + tokenizer verification on 10+ identifiers + body extraction per category. Match.

### Session 2 (Phase 2a -- FTS5 Engine Core)

**5.** [OK] **FTS5 in-memory index build from index.md** -- rd-08 Phase 2a (lines 207-239) specifies building FTS5 table from index.md. Match.

**6.** [OK] **Smart wildcard query builder** -- Plan mentions "user_id -> exact, auth -> prefix wildcard". rd-08 Decision #3 (lines 56-73) specifies this exact behavior. Match.

**7.** [OK] **Pure Top-K threshold (25% noise floor)** -- rd-08 Decision #4 (lines 81-109) specifies pure Top-K with 25% noise floor. Match.

**8.** [OK] **Hybrid scoring (title/tags FTS5 -> top-K JSON -> body bonus)** -- rd-08 Phase 2a (lines 246-270) specifies hybrid scoring. Match.

**9.** [OK] **FTS5 fallback** -- Plan mentions "FTS5 없을 때 기존 키워드 시스템 fallback". rd-08 Decision #7 (lines 135-149) + "Changes from Consolidated Plan" table (line 44) mandates this. Match.

**10.** [OK] **Integration into memory_retrieve.py** -- Plan says "memory_retrieve.py에 통합". rd-08 confirms `memory_retrieve.py` is modified in Phase 2a (Files Changed table, line 975). Match.

### Session 3 (Phase 2b -- On-Demand Search Skill)

**11.** [OK] **memory_search_engine.py creation** -- rd-08 Phase 2b (lines 274-297) specifies creating `hooks/scripts/memory_search_engine.py` with shared FTS5 engine and CLI interface. Match.

**12.** [OK] **SKILL.md creation** -- rd-08 Phase 2b (lines 287-290) specifies `skills/memory-search/SKILL.md`. Match.

**13.** [OK] **Search mode: full FTS5 index including body** -- rd-08 Phase 2b (lines 282-285) specifies search mode reads all JSON for full body content indexing. Match.

**14.** [OK] **Auto-inject 0-result hint injection** -- Plan says "Auto-inject 결과 0건일 때 `<!-- Use /memory:search -->` 힌트 주입". rd-08 line 290 specifies this. Match.

**15.** [MISSING] **Import path fix** -- rd-08 Phase 2b (lines 292-296) explicitly calls out the R1-technical WARN about `sys.path.insert(0, ...)` for import path. The session plan does not mention this. While it may seem like an implementation detail, rd-08 calls it out as a specific named item from verifier findings.

### Session 4 (Phase 2c -- Test Rewrite)

**16.** [OK] **Existing test breakage** -- Plan correctly identifies 42% breakage and names ScoreEntry, DescriptionScoring. rd-08 Phase 2c (lines 300-303) matches.

**17.** [OK] **New tests** -- Plan lists FTS5 index build/query, smart wildcard, body extraction, hybrid scoring, fallback, e2e auto-inject. rd-08 Phase 2c (lines 305-315) lists 7 test categories. Match in substance.

**18.** [OK] **Performance benchmark 500 docs < 100ms** -- rd-08 Phase 2c line 315 specifies this exact benchmark. Match.

**19.** [MISSING] **Phase 2d (Validate step)** -- See finding #27 below for dedicated analysis.

### Session 5 (Phase 2e -- Confidence Annotations)

**20.** [OK] **BM25 score-based confidence labels** -- Plan says "BM25 점수 기반 [confidence:high/medium/low]". rd-08 Phase 2e (lines 323-349) specifies `confidence_label()` function with ratio-based brackets (>=0.75 high, >=0.40 medium, else low). Match.

**21.** [OK] **Output format update** -- Plan says "<memory-context> 출력 포맷에 반영". rd-08 lines 341-347 show updated output format. Match.

**22.** [OK] **~20 LOC estimate** -- Both plan and rd-08 agree on ~20 LOC.

### Session 6 (Phase 2f -- Measurement Gate)

**23.** [OK] **20+ real queries** -- Plan says "20개 이상 실제 쿼리". rd-08 Phase 2f (lines 351-358) says "20+ representative real-world queries". Match.

**24.** [OK] **Decision rule: precision >= 80% skip Phase 3** -- Plan says "precision >= 80% -> Phase 3-4 건너뜀". rd-08 line 358 says "If precision >= 80%, skip Phase 3 entirely." Match.

**25.** [OK] **Conditional Sessions 7-9** -- Plan mentions conditional sessions for LLM judge, tests, dual verification. rd-08 Phase 3, 3b, 3c, and Phase 4 (lines 867-908) match this structure.

---

## 2. LOC Estimates

**26.** [OK] **Session 1 ~80 LOC** -- rd-08 Schedule table (line 934): "Day 1 AM | Tokenizer fix + body extraction + FTS5 check | ~80". Plan says "~80 LOC". Exact match.

**27.** [DISCREPANCY] **Session 2 ~200 LOC** -- Plan says "~200 LOC". rd-08 Schedule table breaks Day 1 PM as ~120 LOC (FTS5 engine core) and Day 2 AM as ~80 LOC (hybrid scoring + fallback + integration), totaling ~200 LOC. However, rd-08 Phase 2a header (line 207) says "~150-200 LOC rewrite". The plan's "~200 LOC" is at the upper bound. Not a hard discrepancy, but worth noting the plan takes the ceiling estimate.

**28.** [OK] **Session 3 ~100 LOC** -- rd-08 Phase 2b header (line 274) says "~80-120 LOC". Plan says "~100 LOC". Within range.

**29.** [DISCREPANCY] **Session 4 "4-6 hours"** -- Plan gives a time estimate instead of LOC. rd-08 Schedule table (line 938): "Day 3 | FTS5 test rewrite + validation + confidence annotations | ~70 LOC". The ~70 LOC in rd-08 is for BOTH tests and confidence annotations combined (Day 3). The plan separates them into two sessions (Session 4 = tests, Session 5 = confidence). This means the plan's "4-6 hours" for Session 4 actually corresponds only to the test rewrite portion, which rd-08 estimates at ~50 LOC of test code (from the "Budget test rewrite" row in the Changes table, line 46, which says "+4-6 hours"). LOC mismatch: plan gives no LOC for test rewrite; rd-08's ~70 LOC for Day 3 includes annotations too.

---

## 3. Items Placed in Wrong Session

**30.** [DISCREPANCY] **Session 2 bundles Day 1 PM + Day 2 AM + Day 2 PM work** -- rd-08 Schedule (lines 935-937) allocates:
  - Day 1 PM: FTS5 engine core (~120 LOC)
  - Day 2 AM: Hybrid scoring + fallback + integration (~80 LOC)
  - Day 2 PM: Search skill + shared engine extraction (~100 LOC)

  The session plan puts ALL of Day 1 PM and Day 2 AM work into Session 2 ("Phase 2a"), then Session 3 covers Day 2 PM ("Phase 2b"). This is a granularity difference (plan merges two rd-08 half-days into one session), not necessarily wrong, but it means Session 2 is significantly larger (~200 LOC) than any single rd-08 half-day block (~120 LOC max). This increases session risk.

**31.** [DISCREPANCY] **Session 5 (Phase 2e) is separated from Session 4 (Phase 2c)** -- rd-08 Schedule (line 938) places confidence annotations on the SAME day as tests: "Day 3 | FTS5 test rewrite + validation + **confidence annotations** | ~70". The session plan splits them into Session 4 (tests only) and Session 5 (confidence only). While this is a reasonable decomposition for session sizing, it deviates from rd-08's grouping and means the plan has 6 sessions for what rd-08 calls "3 days" of Phase 1-2 work, plus the measurement gate.

---

## 4. Phase 2d Skip Analysis

**32.** [DISCREPANCY] **Plan skips "Phase 2d" -- this is NOT correct per rd-08.** rd-08 explicitly defines Phase 2d (lines 317-321) as a validation step:

  > #### 2d. Validate
  > - Compile check all modified scripts
  > - Run full test suite: `pytest tests/ -v`
  > - Manual test with 10+ queries across categories
  > - Verify no regression on existing memories

  Phase 2d in rd-08 is a validation/integration step that comes AFTER Phase 2c (tests) and BEFORE Phase 2e (confidence annotations). The session plan completely omits this as a named step. The plan's Session 4 ends with tests but includes no mention of a validation gate. The plan implicitly expects tests to serve as validation, but rd-08's Phase 2d includes manual regression testing ("10+ queries across categories") which is distinct from automated tests.

  This is a meaningful omission: rd-08 designed Phase 2d as a checkpoint to catch regressions before adding confidence annotations. Without it, Session 5 (confidence annotations) could build on top of unvalidated FTS5 code.

---

## 5. Config Changes (match_strategy + max_inject)

**33.** [MISSING] **`match_strategy: "fts5_bm25"` config change** -- rd-08 Configuration section (lines 987-1012) specifies adding `"match_strategy": "fts5_bm25"` to config, with note (line 1009): `match_strategy: "fts5_bm25"` (new default) or `"title_tags"` (legacy fallback). The session plan does not mention this config change in ANY session.

**34.** [MISSING] **`max_inject` reduction from 5 to 3** -- rd-08 Configuration section (line 1010): `max_inject: 3` (reduced from 5 for higher precision). The current code (memory_retrieve.py line 247) defaults to `max_inject = 5`. The session plan does not mention changing this default in any session.

**35.** [MISSING] **`assets/memory-config.default.json` update** -- rd-08 Files Changed table (line 979) lists this file as modified in Phase 3 (judge config). However, the `match_strategy` and `max_inject` changes from Phase 2a also need to go into this file. Neither the Phase 2a nor Phase 3 config updates appear in the session plan.

---

## 6. hooks.json Timeout Change

**36.** [AMBIGUOUS] **hooks.json timeout 10->15** -- rd-08 Phase 3 item #4 (line 872): "Update `hooks/hooks.json` timeout from 10 to 15 seconds". rd-08 Files Changed table (line 978) confirms: `hooks/hooks.json | Modify (timeout 10->15) | 3`. The session plan's conditional sessions (7-9) cover "LLM judge, tests, dual verification" but do not explicitly mention the hooks.json timeout change. Since Phase 3 is conditional (only if precision < 80%), and the timeout change is a Phase 3 item, it is arguably correct that it doesn't appear in Sessions 1-6. However, the conditional sessions description is too vague to confirm it's included: "Conditional Sessions 7-9 for LLM judge, tests, dual verification" does not mention infrastructure changes like hooks.json.

---

## 7. CLAUDE.md Update

**37.** [MISSING] **CLAUDE.md update** -- rd-08 Files Changed table (line 983): `CLAUDE.md | Update (key files, security, config) | 3`. rd-08 Phase 3 item #5 (line 873): "Update CLAUDE.md Key Files table". The session plan does not mention CLAUDE.md in any session, including the conditional sessions.

  Even if the judge (Phase 3) is skipped, FTS5 engine changes (Phase 2a-2b) add new files (`memory_search_engine.py`) and change retrieval behavior significantly. CLAUDE.md's "Key Files" table, "Security Considerations" section, and architecture description all need updating. This should arguably be in Session 3 or Session 4, not deferred to the conditional Phase 3.

---

## 8. Files Changed Table Completeness Check

rd-08 Files Changed table (lines 973-983):

| File | rd-08 Phase | In Session Plan? |
|------|-------------|-----------------|
| `hooks/scripts/memory_retrieve.py` | 1, 2a, 3 | Session 1, 2 -- [OK] (Phase 3 is conditional) |
| `hooks/scripts/memory_search_engine.py` | 2b | Session 3 -- [OK] |
| `hooks/scripts/memory_judge.py` | 3 | Conditional sessions -- [OK] |
| `hooks/hooks.json` | 3 | [AMBIGUOUS] -- see finding #36 |
| `assets/memory-config.default.json` | 3 | [MISSING] -- see finding #35. Also missing Phase 2 config changes. |
| `skills/memory-search/SKILL.md` | 2b, 3c | Session 3 -- [OK] for 2b. Conditional for 3c. |
| `tests/test_memory_retrieve.py` | 2c | Session 4 -- [OK] |
| `tests/test_memory_judge.py` | 3b | Conditional sessions -- [OK] |
| `CLAUDE.md` | 3 | [MISSING] -- see finding #37 |

**38.** [MISSING] **`assets/memory-config.default.json` Phase 2 updates** -- The session plan never mentions updating the default config file. Phase 2 introduces FTS5 as the new match strategy and changes max_inject from 5 to 3. These are config-level changes that should be reflected in the default config file during Phase 2, not deferred to the conditional Phase 3.

---

## Summary of Findings

| # | Status | Finding |
|---|--------|---------|
| 1-14 | [OK] | Sessions 1-3 items match rd-08 |
| 15 | [MISSING] | Import path fix (`sys.path.insert`) not mentioned in Session 3 |
| 16-18 | [OK] | Session 4 test items match rd-08 |
| 20-25 | [OK] | Sessions 5-6 + conditional sessions match rd-08 |
| 26 | [OK] | Session 1 LOC estimate matches |
| 27 | [DISCREPANCY] | Session 2 takes ceiling estimate (~200 vs rd-08's ~150-200) |
| 29 | [DISCREPANCY] | Session 4 gives time estimate instead of LOC |
| 30 | [DISCREPANCY] | Session 2 merges two rd-08 half-day blocks into one session |
| 31 | [DISCREPANCY] | Session 5 separated from Session 4 (rd-08 groups them on Day 3) |
| 32 | [DISCREPANCY] | Phase 2d (validation gate) completely skipped -- not just renumbered |
| 33 | [MISSING] | `match_strategy: "fts5_bm25"` config not in any session |
| 34 | [MISSING] | `max_inject` 5->3 reduction not in any session |
| 35 | [MISSING] | `assets/memory-config.default.json` update not in any session (Phase 2 changes) |
| 36 | [AMBIGUOUS] | `hooks.json` timeout change vaguely covered by conditional sessions |
| 37 | [MISSING] | CLAUDE.md update not in any session |
| 38 | [MISSING] | Default config file Phase 2 updates missing |

**Critical gaps:** Findings #32 (Phase 2d validation gate omitted), #33-34 (config changes missing), and #37 (CLAUDE.md update missing) are the most significant discrepancies. The Phase 2d omission removes a regression safety gate, and the config changes are core behavioral modifications that would leave the system partially configured if forgotten.
