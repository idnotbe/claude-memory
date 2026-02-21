# Verification Round 2 -- Cross-Check & Final Sign-Off

**Verifier:** v2-crosscheck
**Date:** 2026-02-20
**Method:** External source verification (official Anthropic docs, GitHub repos, IR literature), cross-model validation (Gemini 3 Pro), code grep verification
**Files cross-checked:** 7 research files, 4 prior verification files, 2 source code files

---

## External Source Verification

### 1. Claude Code Hooks API Claims

**Source:** Official Anthropic documentation at [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) (fetched and verified 2026-02-20)

| Claim in Research | Official Docs Say | Verdict |
|---|---|---|
| All hooks receive `transcript_path` | YES -- listed in "Common input fields" table: `transcript_path` = "Path to conversation JSON" | CONFIRMED |
| All hooks receive `session_id`, `cwd`, `permission_mode`, `hook_event_name` | YES -- all listed in common input fields table | CONFIRMED |
| UserPromptSubmit receives the prompt as `prompt` field | YES -- docs show `"prompt": "Write a function..."` in the example JSON | CONFIRMED |
| `memory_retrieve.py` reads `user_prompt` (line 218) | Code reads `hook_input.get("user_prompt", "")` -- **this is NOT the official field name** | CONFIRMED BUG |
| Stop hook receives `stop_hook_active` and `last_assistant_message` | YES -- documented in Stop input section | CONFIRMED |
| Stop hook output uses `decision: "block"` + `reason` | YES -- documented in Stop decision control: `{"decision": "block", "reason": "..."}` | CONFIRMED |
| Hook timeout defaults | Official: command=600s, prompt=30s, agent=60s. Research file `01-research-claude-code-context.md` says "15 seconds" for hooks -- **DISCREPANCY** | PARTIALLY WRONG in research |
| JSONL transcript format is not a stable API | Official docs do NOT document the JSONL format or guarantee its stability. Research correctly identifies this risk. | CONFIRMED |
| SessionStart receives `source`, `model` fields | YES -- documented with examples | CONFIRMED |
| PreCompact receives `trigger`, `custom_instructions` | YES -- documented | CONFIRMED |
| SubagentStop receives `agent_transcript_path` | YES -- documented as separate from main `transcript_path` | CONFIRMED |

**New finding: Hook timeout discrepancy.** The research file `02-research-claude-mem-rationale.md` line 27 states "Hook timeouts are strict (15 seconds in Claude Code)". The official docs show default timeouts of 600 seconds (command), 30 seconds (prompt), 60 seconds (agent). The 15-second figure appears to be incorrect or outdated. This does not affect the research conclusions significantly (both are "fast enough" for retrieval), but is a factual error.

**Critical finding confirmed: `user_prompt` vs `prompt`.** The official Anthropic hooks reference clearly shows the field name is `prompt` for UserPromptSubmit hooks. The code at `memory_retrieve.py:218` reads `user_prompt`, which would receive an empty string from the official API. This was independently flagged by reviewer-accuracy, verified by v1-functional, and is now confirmed against the authoritative source. **This may mean the retrieval hook has never worked with the standard Claude Code hooks protocol**, unless there is an undocumented compatibility alias.

---

### 2. claude-mem Architecture Claims

**Sources:** [GitHub repo](https://github.com/thedotmack/claude-mem), [DeepWiki analysis](https://deepwiki.com/thedotmack/claude-mem), [Architecture Overview](https://docs.claude-mem.ai/architecture/overview)

| Claim in Research | External Source Says | Verdict |
|---|---|---|
| claude-mem uses dual-path retrieval (hook + MCP) | YES -- GitHub README confirms 5 lifecycle hooks + 5 MCP tools | CONFIRMED |
| SessionStart hook uses recency-based injection, no vector search | Confirmed by research and architecture docs | CONFIRMED |
| ChromaDB used for vector search | YES -- README states "Chroma Vector Database - Hybrid semantic + keyword search" | CONFIRMED |
| 3-layer progressive disclosure (search -> timeline -> get_observations) | YES -- 5 MCP tools including search, timeline, get_observations confirmed | CONFIRMED |
| FTS5 is deprecated/dead code in active search path | Research claims this based on code analysis; external sources confirm FTS5 exists but is not in active search flow | CONFIRMED (with caveat: inferred from code, not explicitly stated in docs) |
| No keyword search in active retrieval path | Research finding; consistent with external architecture descriptions showing only vector search and recency-based retrieval | CONFIRMED |

**Version discrepancy:** GitHub README badge shows v6.5.0. Research file `01-research-claude-mem-retrieval.md` says v6.5.0 (correct for README). Research file `02-research-claude-mem-rationale.md` says v10.3.1 (from npm, reflecting rapid iteration). The npm package has 88+ versions published. Both numbers are factually correct for their respective sources but the discrepancy is confusing. The architecture described (3-layer MCP, Chroma vector) is consistent across both version references.

---

### 3. BM25/TF-IDF Claims vs IR Literature

**Sources:** [Wikipedia: Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25), [GeeksforGeeks BM25](https://www.geeksforgeeks.org/nlp/what-is-bm25-best-matching-25-algorithm/), [Sourcegraph BM25F blog](https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f), Gemini 3 Pro analysis

| Claim | Assessment | Verdict |
|---|---|---|
| BM25 improves precision over naive keyword matching | Directionally correct -- BM25's IDF weighting and term saturation are well-established improvements over boolean keyword matching | CONFIRMED (directional) |
| BM25 improves precision from ~40% to ~55-60% on 600-entry corpus | **Specific numbers are unmeasured estimates.** BM25's advantage may be smaller on small corpora where IDF discrimination is weak (many terms appear in only 1-3 documents). Gemini independently assessed this as "likely overstated for this specific data scale" | WEAK -- directionally correct but magnitude uncertain |
| "30 years of IR literature" supports BM25 | True that BM25 dates to 1994 (Robertson & Walker) and is well-established. However, the literature primarily evaluates on large corpora (TREC collections, thousands to millions of documents). Extrapolation to 600 short-title entries is an unstated assumption | PARTIALLY VALID -- the extrapolation caveat was correctly identified by reviewer-critical |
| Comparison between keyword/BM25/vector search is fair | The research correctly positions keyword < BM25 < vector in quality, and correctly notes the stdlib-only constraint prevents vector search. The precision estimates for each tier are rough but directionally sound | FAIR -- relative ordering is correct, absolute numbers are guesses |
| BM25 parameter tuning (k1, b) affects results | Standard IR knowledge; BM25 requires corpus-specific tuning. The research does not discuss parameter selection, which is a gap | CONFIRMED but INCOMPLETE |

---

## Cross-Model Validation (Gemini)

Codex was unavailable (usage limit). Gemini 3 Pro (via clink) provided independent assessment.

### Gemini's Assessment of Key Claims

| Claim | Gemini Verdict | Notes |
|---|---|---|
| ~40% current precision | "ACCURATE" -- "reasonable, if not generous, estimate for this 'bag-of-words' approach" | Agrees directionally |
| BM25 to ~55-60% | "DEBATABLE / OVER-OPTIMISTIC" -- "jump to 60% precision is likely overstated for this specific data scale" | Aligns with reviewer-critical's assessment |
| Precision-First Hybrid architecture | "HIGHLY SOUND" -- "AI context windows are precious. Polluting context with irrelevant chunks causes hallucinations" | Strong endorsement of the concept |
| claude-mem dual-path architecture | "VERIFIED" -- confirmed via external research | Aligns with our findings |
| transcript_path stability risk | "CRITICAL & ACCURATE" -- "The JSONL format is an internal logging artifact, not a public API contract" | Strong agreement on risk |
| No evaluation framework exists | "TRUE" -- "Without a dataset to measure Precision@k, all numbers are educated guesses" | Universal agreement |

### Gemini's Key Recommendations

1. "Adopt the Precision-First Hybrid approach immediately"
2. "Do not prioritize BM25 implementation over the Evaluation Framework"
3. "Treat transcript_path as experimental/unstable"
4. BM25 is "low-regret but low-reward for <1000 items"

### Assessment of Gemini's Review

Gemini's analysis is **independent and consistent** with our internal reviews. It did not identify any issues that our review process missed, which is a positive sign for completeness. Its most valuable contribution is the external perspective on BM25's marginal value at small corpus scale, which aligns with the adversarial review's skepticism.

---

## Remaining Issues

### Critical (should fix before considering research complete)

1. **`user_prompt` vs `prompt` field name bug in `memory_retrieve.py:218`** -- Confirmed against official Anthropic docs. The retrieval hook reads a field name that does not match the official API. This is a code bug, not a research documentation error, but the research should clearly flag it as a finding. The V1-functional verification says a fix was applied to the research files but **NOT to the code itself**.

2. **Hook timeout claim (15 seconds)** -- `02-research-claude-mem-rationale.md` line 27 states "Hook timeouts are strict (15 seconds in Claude Code)". Official docs show 600s (command), 30s (prompt), 60s (agent). This factual error should be corrected.

### Moderate (acknowledged but acceptable)

3. **All precision/recall numbers are unmeasured** -- Universally acknowledged across all reviewers and Gemini. The research correctly identifies Phase 0 (evaluation framework) as mandatory. The numbers serve as directional estimates, not engineering targets.

4. **transcript_path in retrieval is proposal, not implementation** -- V1-functional verification reports this was fixed (clearly separated in research files). Confirmed by code grep: zero occurrences of `transcript_path` in `memory_retrieve.py`.

5. **claude-mem version discrepancy (v6.5.0 vs v10.3.1)** -- Both numbers are correct for their respective sources (GitHub README badge vs npm). Confusing but not wrong.

6. **BM25 precision improvement may be overstated for 600-entry corpus** -- Both Gemini and reviewer-critical agree the specific numbers are likely optimistic. The directional claim (BM25 > keyword) is correct.

### Low Priority

7. **`description_score` component not documented in research** -- The scoring system includes a category description bonus (up to +2) that research files omit. Affects threshold analysis accuracy but the V1-functional fix accounted for it in the revised threshold math.

8. **Recency bonus and priority tie-breaking not prominently documented** -- Minor completeness gap.

9. **No "null hypothesis" section** -- The research does not ask "What if ~40% precision is acceptable?" This is a valid gap identified by reviewer-critical.

---

## Final Quality Assessment

### Strengths

1. **Problem analysis is excellent.** The identification of body content gap, evaluation framework need, and stdlib constraint is well-grounded in code analysis and universally agreed upon.

2. **External research (claude-mem) is high quality.** The dual-file analysis (01-retrieval + 02-rationale) with [CONFIRMED]/[INFERRED] evidence classification is rigorous and verified against external sources.

3. **Claude Code context research is accurate and valuable.** The transcript_path discovery, hook field documentation, and OTel capabilities are all confirmed against official Anthropic documentation (with the minor timeout discrepancy noted above).

4. **Multi-layer verification process worked.** The accuracy review caught scoring errors, the critical review caught the threshold flaw, the functional verification applied fixes, and the holistic verification mapped contradictions. This process surface real issues that improved the research.

5. **Self-awareness about limitations is commendable.** The research repeatedly acknowledges that precision numbers are estimates and that Phase 0 must come first.

### Weaknesses

1. **Specific precision numbers create false confidence.** Despite caveats, tables with "~40%", "~55-60%", "~85%+" look like measurements. Readers may not read the fine print.

2. **The Precision-First Hybrid is conceptually sound but under-specified.** The threshold value (revised to 4), the /memory-search skill (unimplemented), and the transcript_path integration (proposed) are all design concepts, not validated implementations.

3. **The "boring fix" was arguably sidelined prematurely.** Body tokens + synonyms + deeper deep-check is concrete and implementable. The Hybrid architecture added complexity (skill system, configuration) that may not be necessary if the boring fix proves sufficient. This was identified by reviewer-critical but not fully resolved.

4. **Hook timeout factual error in claude-mem rationale.** The "15 seconds" claim is wrong per official docs (600s default). Minor but undermines confidence in other unverified claims.

### Overall Rating

**7/10 -- Good research with known limitations.**

The research is thorough in breadth, transparent about its limitations, and has survived multiple rounds of independent verification. The core findings (body content gap, evaluation framework need, transcript_path availability, claude-mem architecture) are well-supported. The solution design (Precision-First Hybrid) is architecturally sound in concept but its specific parameters (threshold, precision targets) are based on unmeasured estimates.

The research is **sufficient to make directional engineering decisions** (what to work on first) but **insufficient to make specific parameter decisions** (what threshold to set) without the Phase 0 evaluation framework.

---

## SIGN-OFF

### APPROVED WITH NOTES

**Justification:**

The research package is approved for use as an engineering planning document with the following conditions:

1. **Phase 0 (Evaluation Framework) is non-negotiable.** All reviewers, Gemini, and the research itself agree: no measurement = no confidence. This must precede any implementation.

2. **The `user_prompt` vs `prompt` bug should be investigated immediately.** If the retrieval hook has been silently failing due to reading the wrong field name, this is a more urgent fix than any retrieval algorithm improvement. (It is possible Claude Code sends both fields for compatibility, but this should be verified.)

3. **Treat all precision/recall numbers as directional estimates.** The ~40%, ~55-60%, ~85%+ figures are educated guesses. They indicate relative ordering (keyword < BM25 < vector) but should not be used as engineering targets or success criteria without Phase 0 measurement.

4. **The Precision-First Hybrid is the right conceptual direction.** Both Gemini and the internal reviews endorse the "conservative auto-inject + on-demand search" architecture. However, start with the simplest possible implementation (raise threshold + body tokens) and add complexity (skill, transcript parsing) only if measurement shows it's needed.

5. **Fix the hook timeout claim** in `02-research-claude-mem-rationale.md` (15s -> 600s default per official docs).

**The research provides a solid foundation for iterative improvement of the retrieval system, provided implementation follows the measurement-first principle it correctly advocates.**

---

## Sources

### Official Documentation (Verified)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) -- Confirmed transcript_path, prompt field, Stop hook fields, timeout values
- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide)
- [Claude Code Monitoring (OTel)](https://docs.anthropic.com/en/docs/claude-code/monitoring-usage)

### External Repositories (Verified)
- [claude-mem GitHub](https://github.com/thedotmack/claude-mem) -- v6.5.0 README, architecture description, MCP tools
- [claude-mem DeepWiki](https://deepwiki.com/thedotmack/claude-mem) -- Architecture analysis
- [claude-mem Architecture Overview](https://docs.claude-mem.ai/architecture/overview)

### IR Literature (Referenced)
- [BM25 Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25)
- [BM25 GeeksforGeeks](https://www.geeksforgeeks.org/nlp/what-is-bm25-best-matching-25-algorithm/)
- [Sourcegraph BM25F](https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f)

### Cross-Model Validation
- Gemini 3 Pro via clink -- Independent assessment of 6 key claims
- Codex -- Unavailable (usage limit reached)

### Source Code (Verified via grep)
- `memory_retrieve.py:218` -- Reads `user_prompt` (not `prompt`)
- `memory_retrieve.py` -- Zero occurrences of `transcript_path`
- `memory_triage.py:939,961,965` -- Uses `transcript_path` correctly
