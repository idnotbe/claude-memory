# V1 Practical Feasibility Verification

**Verifier:** v1-practical
**Date:** 2026-02-22
**Targets:** Revised Plans #1, #2, #3
**Method:** Source code line counting, test name/line verification, config compatibility check, external model consultation (Gemini 3 Pro, Codex), vibe-check metacognitive review

---

## Plan #1: Actions #1-#4 Implementation Plan

### LOC Verification Table

| Component | Plan Claimed LOC | Actual Code Measured | Verdict |
|-----------|-----------------|---------------------|---------|
| `confidence_label()` definition | 14 lines (161-174) | **14 lines** (161-174 confirmed) | EXACT MATCH |
| `_output_results()` definition | 40 lines (262-301) | **40 lines** (262-301 confirmed) | EXACT MATCH |
| Config parsing region | lines 353-384 | **32 lines** (353-384 confirmed, `dict.get()` pattern) | EXACT MATCH |
| Hint at line 458 | 1 line (FTS5 path) | **Line 458 confirmed**: `print("<!-- No matching memories found...")` | EXACT MATCH |
| Hint at line 495 | 1 line (legacy path) | **Line 495 confirmed**: identical HTML comment | EXACT MATCH |
| Hint at line 560 | 1 line (legacy deep check) | **Line 560 confirmed**: identical HTML comment | EXACT MATCH |
| Action #1 code estimate | ~20-35 LOC | Realistic: ~10-15 LOC function body + ~5-10 config parsing + ~5-10 cluster_count computation in `_output_results()` = ~20-35 | PLAUSIBLE |
| Action #2 code estimate | ~40-60 LOC | Realistic but tight: tiered branching in 40-line function + compact format + search hint + mode guard. Gemini estimates 20-30, Codex estimates 35-70. Practical range: ~35-70 LOC | PLAUSIBLE (may drift to upper bound) |
| Action #3 code estimate | ~6-10 LOC | Accurate: `_emit_search_hint()` helper ~8 LOC + 3 call-site replacements = ~11 LOC total, but net delta ~6-10 (replacing existing lines) | PLAUSIBLE |
| **Code subtotal** | **~66-105 LOC** | Aggregated practical range: **~65-115 LOC** | CLOSE MATCH |
| Action #1 tests | ~35-65 LOC | Reasonable for 15-25 new test methods at ~3-4 LOC avg | PLAUSIBLE |
| Action #2 tests | ~80-150 LOC | Reasonable for 15-30 new tests covering 3 modes + security + tags | PLAUSIBLE |
| Action #3 tests | ~15-25 LOC | Reasonable for 5-8 tests on helper + integration | PLAUSIBLE |
| **Test subtotal** | **~130-240 LOC** | Aggregated: **~130-240 LOC** | MATCH |

### Call-Site Completeness Verification

| Function | Definition | All Call Sites | Plan Accounts For | Status |
|----------|-----------|---------------|-------------------|--------|
| `confidence_label()` | Line 161 | Line 299 (inside `_output_results()`) -- **1 call site** | Yes -- plan modifies this call to pass `abs_floor` + `cluster_count` | COMPLETE |
| `_output_results()` | Line 262 | Line 455 (FTS5 path), Line 573 (legacy path) -- **2 call sites** | Yes -- plan adds `output_mode` + `abs_floor` params to both | COMPLETE |
| 3 hint locations | Lines 458, 495, 560 | All 3 confirmed as HTML comments | Yes -- plan replaces all 3 with `_emit_search_hint()` | COMPLETE |

### Test Impact Verification

| Test Name (Plan Claim) | Actual Location | Exists? | Impact Assessment |
|------------------------|----------------|---------|-------------------|
| `TestConfidenceLabel` (17 tests, lines 493-562) | Lines 493-562, **17 test methods confirmed** | YES | Default params (`abs_floor=0.0`, `cluster_count=0`) preserve all 17 existing tests |
| `test_single_result_always_high` (line 535) | Line 535: `assert confidence_label(3.7, 3.7) == "high"` | YES | Unaffected with default params; affected only when `abs_floor > 3.7` |
| `test_all_same_score_all_high` (line 539) | Line 539-541: loops 5x asserting "high" | YES | Unaffected with `cluster_count=0` default |
| `test_confidence_label_in_output` (line 618) | Line 618: asserts `confidence="low"` in output | YES | **WILL BREAK in tiered mode** (LOW = silence). Safe in legacy mode (default) |
| `test_no_score_defaults_low` (line 649) | Line 649: asserts `confidence="low"` in output | YES | **WILL BREAK in tiered mode**. Safe in legacy mode (default) |
| `test_result_element_format` (line 658) | Line 658: asserts `<result ...>` pattern | YES | **SAFE** -- applies to HIGH results in both modes |
| `test_output_results_captures_all_paths` (line 1063 in test_v2_adversarial_fts5.py) | Line 1063: asserts `<script>` XSS sanitization | YES | **SAFE** -- tests security property, not output format. No `output_mode` param = legacy default |
| `test_output_results_description_injection` (line 1079 in test_v2_adversarial_fts5.py) | Line 1079: asserts description injection prevention | YES | **SAFE** -- tests security property. No `output_mode` param = legacy default |

**Engineering review correction confirmed:** Tests #4 and #5 (in test_v2_adversarial_fts5.py) are SAFE because they test security properties that are mode-independent, and the default output_mode is "legacy". The plan conservatively flags them as needing modification, but they do not.

### Config Compatibility Check

Current `assets/memory-config.default.json` structure (93 lines):
- `retrieval` section exists at line 50 with `max_inject`, `match_strategy`, `judge` subsection
- No existing `confidence_abs_floor`, `cluster_detection_enabled`, or `output_mode` keys

**Plan adds:**
```json
"retrieval": {
    "confidence_abs_floor": 0.0,
    "cluster_detection_enabled": true,
    "output_mode": "legacy"
}
```

**Compatibility:** All new keys use `dict.get(key, default)` pattern matching existing code (confirmed at lines 353-384). Adding keys to existing `retrieval` section is non-breaking. **No structural changes needed.** COMPATIBLE.

### Review Feedback Status

| Feedback Item (Source) | Status | Evidence |
|----------------------|--------|---------|
| Cluster detection config toggle (adversarial Finding #3, engineering MEDIUM) | **ADDRESSED** | Plan adds `retrieval.cluster_detection_enabled` (bool, default: `true`) with ~3 LOC cost. Config-based rollback path provided. |
| `abs_floor` corpus-dependent warning (adversarial Finding #2) | **ADDRESSED** | Plan line 64 adds explicit warning: "abs_floor is corpus-dependent interim measure... re-calibration needed if index grows significantly" |
| `cluster_count` semantics documentation (engineering LOW) | **ADDRESSED** | Plan line 80 documents: "current result set within ratio > 0.90 count... post max_inject truncation" |
| `output_mode` default = "legacy" (engineering MEDIUM, adversarial) | **ADDRESSED** | Plan line 163-164 sets default "legacy" with explicit backwards-compatibility rationale |
| Briefing vs plan inconsistency on output_mode (engineering MEDIUM) | **NOT ADDRESSED** (out of plan scope -- briefing file issue, not plan issue) |
| LOC estimate range for Action #2 "tight" (engineering LOW) | **PARTIALLY ADDRESSED** | Plan retains ~40-60 range. Practical estimate is ~35-70. Minor gap. |

### Plan #1 Overall: **PASS WITH NOTES**

**Notes:**
1. Action #2 LOC may drift to ~70 at the upper bound (plan says 60). Minor.
2. Tests 4-5 in test_v2_adversarial_fts5.py do NOT need tiered mode branches (engineering review correctly identified this, plan over-flags conservatively).
3. All function call sites are accounted for. No hidden callers.

---

## Plan #2: Logging Infrastructure Plan

### LOC Verification Table

| Component | Plan Claimed | Actual Assessment | Verdict |
|-----------|-------------|-------------------|---------|
| `memory_logger.py` new module | 80-120 LOC | `emit_event()` + `get_session_id()` + `cleanup_old_logs()` + `parse_logging_config()` + level filtering + fail-open + imports + docstrings. Codex notes: minimal = 80-120, full features (retention, schema_version, truncation, level filtering) = 120-180 | PLAUSIBLE if kept minimal; at risk of exceeding upper bound with all listed features |
| `memory_retrieve.py` instrumentation | 30-50 LOC added (577 total) | 5 logging points x ~6-10 LOC each (timing + emit call + try/except). Codex estimates 35-70. | PLAUSIBLE (may drift high) |
| `memory_judge.py` instrumentation | 15-25 LOC added (369 total) | 3 logging points (lines 347, 352, 360 currently have stderr `[DEBUG]`). Replacing with emit_event + timing = ~5-8 LOC each. Codex estimates 20-35. | PLAUSIBLE |
| `memory_search_engine.py` instrumentation | 10-15 LOC added (499 total) | 1 logging point (CLI search query). Import + single emit call + timing = ~10-15 LOC | ACCURATE |
| `memory_triage.py` migration | 10-15 LOC changed (1061 total) | Replace lines 997-1012 (existing `os.open` + `fdopen` + `json.dumps`) with import + `emit_event()` call. Net change likely smaller (replacing ~15 lines with ~5). | PLAUSIBLE |
| `assets/memory-config.default.json` | ~5 LOC added (93 total) | `"logging": {"enabled": false, "level": "info", "retention_days": 14}` = 5 lines | ACCURATE |
| `tests/test_memory_logger.py` | 150-250 LOC | 10+ test scenarios listed (append, dir creation, fail-open, config, levels, cleanup, session_id, concurrency) at ~10-20 LOC each | PLAUSIBLE |

### Existing Pattern Verification

| Pattern | Location | Confirmed | Plan Uses Correctly |
|---------|----------|-----------|-------------------|
| `os.open(O_APPEND\|O_CREAT\|O_WRONLY\|O_NOFOLLOW)` | `memory_triage.py:1000-1002` | YES | YES (with `os.write()` fix per review) |
| `os.fdopen(fd, "a")` + `f.write()` (existing, not atomic) | `memory_triage.py:1006-1007` | YES | Plan changes to `os.write(fd, line_bytes)` per review |
| Sibling import: `from memory_search_engine import ...` | `memory_retrieve.py:25` | YES | `from memory_logger import emit_event` follows same pattern |
| `dict.get()` config parsing | `memory_retrieve.py:353-384` | YES | `logging` section uses same pattern |
| stderr `[DEBUG]`/`[WARN]`/`[INFO]` | `memory_retrieve.py:362,387,466`; `memory_judge.py:347,352,360` | YES | Plan replaces these with structured `emit_event()` calls |
| `transcript_path` in hook_input | `memory_retrieve.py:432` (UserPromptSubmit), `memory_triage.py:939` (Stop) | YES | session_id extraction source confirmed available |

### Import Path Feasibility

Tests use `conftest.py` to add `hooks/scripts/` to `sys.path`. Verified: existing tests import `from memory_search_engine import ...` and `from memory_retrieve import ...` using this mechanism. A new `memory_logger.py` in the same directory follows the identical pattern. **No import friction.**

### Review Feedback Status

| Feedback Item (Source) | Status | Evidence |
|----------------------|--------|---------|
| `logging.enabled` default: `true` -> `false` (engineering HIGH, adversarial HIGH) | **ADDRESSED** | Plan line 160: "logging.enabled default false -- (review feedback change)" |
| `os.write()` instead of `os.fdopen().write()` (engineering MEDIUM, adversarial MEDIUM) | **ADDRESSED** | Plan line 74: "os.write(fd, line_bytes)" specified explicitly |
| `session_id` unavailable in CLI mode (engineering MEDIUM) | **ADDRESSED** | Plan line 124: "CLI mode에서는 hook_input이 없으므로 session_id 미제공... 향후 os.getppid() 또는 타임스탬프 기반 그루핑 검토" |
| `schema_version` field (engineering LOW) | **ADDRESSED** | Plan line 115: `"schema_version": 1` in all events |
| Write guard non-interference (adversarial LOW) | **ADDRESSED** | Plan line 367: explicit note that PreToolUse:Write guard only intercepts Claude's Write tool, not Python file I/O |
| `.gitignore` guidance (adversarial HIGH) | **ADDRESSED** | Plan line 166: ".gitignore에 .claude/memory/logs/ 추가 안내" |
| Secret residue -- info level no titles (adversarial HIGH) | **ADDRESSED** | Plan lines 119-122: info = paths/IDs only, debug = titles + raw prompts |
| Entry size cap (adversarial) | **ADDRESSED** | Plan line 125: "data.results 배열 최대 20개로 제한, 4KB 미만 유지" |

### Plan #2 Overall: **PASS WITH NOTES**

**Notes:**
1. `memory_logger.py` at 80-120 LOC is feasible ONLY if kept minimal. With all described features (emit_event, get_session_id, cleanup_old_logs, parse_logging_config, level filtering, fail-open wrappers, schema_version, entry truncation), practical estimate is closer to **100-150 LOC**. Plan should acknowledge the range may shift upward.
2. `memory_retrieve.py` instrumentation at 30-50 LOC is on the tight side given 5 logging points each needing timing + emit + error wrapping. Practical: 35-70 LOC. Plan should acknowledge.
3. Triage migration (`memory_triage.py`) pattern at lines 997-1012 uses `os.fdopen(fd, "a")` -- the plan correctly changes this to `os.write()` per review. Implementation must also update the existing triage code to match.

---

## Plan #3: PoC Experiments Plan

### LOC Verification (Minimal -- mostly methodology)

Plan #3 is primarily methodology and data collection, not code changes. The only code-relevant references are:

| Reference | Actual Code | Verified |
|-----------|------------|----------|
| `build_fts_query()` OR join at line 226 | Line 226: `return " OR ".join(safe)` | EXACT MATCH |
| `apply_threshold()` noise floor at lines 283-288 | Lines 283-288 confirmed | EXACT MATCH |
| `confidence_label()` at lines 161-174 | Confirmed (see Plan #1) | EXACT MATCH |
| `_output_results()` at lines 262-301 | Confirmed (see Plan #1) | EXACT MATCH |
| Hint locations at 458, 495, 560 | Confirmed (see Plan #1) | EXACT MATCH |
| hooks.json UserPromptSubmit at lines 43-55 | Lines 43-55: `type: "command"`, timeout 15 | EXACT MATCH |

### Cross-Plan Dependency Verification

The 8-step cross-plan ordering (Plan #3, Appendix):

| Step | Dependency | Feasible | Notes |
|------|-----------|----------|-------|
| 1. Plan #2 Phase 1-2 (logger + retrieval.search event) | None | YES | Minimal viable logging must come first |
| 2. PoC #5 Phase A (pilot baseline) | Step 1 | YES | Needs logging to capture pre-change metrics |
| 3. Plan #1 Actions #1-#3 | Step 2 | YES | Baseline must be captured before code changes |
| 4. Plan #2 Phase 3-4 (remaining instrumentation) | Step 3 | YES | Must instrument modified code, not original |
| 5. PoC #5 Phase B (post-comparison) | Steps 3, 4 | YES | Same query set, post-change metrics |
| 6. PoC #7 (OR-query analysis) | Step 5 | YES | Reuses #5 dataset |
| 7. PoC #6 (Nudge compliance) | Plan #1 Action #2 | YES | Needs tiered output to exist |
| 8. Plan #1 Action #4 (Agent Hook) | Independent | YES | Separate branch, parallel |

**Critical constraint (Codex confirmation):** All metrics required for pre/post comparison must be finalized BEFORE baseline capture (Step 2). If logging schema changes between Step 2 and Step 5, baseline data may be incompatible.

### Review Feedback Status

| Feedback Item (Source) | Status | Evidence |
|----------------------|--------|---------|
| PoC #6 redesign: remove decision thresholds, downgrade to exploratory (adversarial MEDIUM) | **ADDRESSED** | Plan lines 313-323: explicit reclassification to "exploratory data collection", decision thresholds removed, caveats about confounding variables added |
| Test-retest reliability instead of inter-annotator agreement (engineering LOW) | **ADDRESSED** | Plan line 214: "test-retest reliability 사용. 동일 5-6개 쿼리를 1주 간격으로 재라벨링" |
| PoC #4 explicit failure path (engineering LOW) | **ADDRESSED** | Plan lines 157-162: explicit kill path -- archive branch, document results, mark WONTFIX, proceed to PoC #5 |
| `matched_tokens` cross-plan gap with Plan #2 (engineering MEDIUM) | **PARTIALLY ADDRESSED** | Plan #3 documents the workaround (title+tags tokenization, lines 257-264) but Plan #2 schema still doesn't include `matched_tokens`. Accepted as pragmatic workaround per engineering review. |
| Cross-plan implementation ordering (engineering MEDIUM, adversarial LOW) | **ADDRESSED** | Plan #3 Appendix (lines 437-456) provides explicit 8-step ordering with rationale |

### Tool/Library Availability

| Tool | Required By | Available | Notes |
|------|------------|-----------|-------|
| `pytest` | All test plans | YES (`/home/idnotbe/projects/claude-memory/.venv/bin/pytest`) | |
| `python3` | All scripts | YES (`/home/idnotbe/projects/claude-memory/.venv/bin/python3`) | |
| `pydantic v2` | memory_write.py, memory_validate_hook.py | YES (v2.12.5 confirmed) | |
| `jq` | PoC log analysis | YES (`/usr/bin/jq`) | |
| `git` (branching for PoC #4) | Action #4 / PoC #4 | YES (repo confirmed as git repo) | |
| `sqlite3` | FTS5 engine | YES (stdlib, confirmed working via existing tests) | |

### Plan #3 Overall: **PASS**

All code references verified. Cross-plan ordering is sound. Review feedback properly incorporated. Methodology is well-designed with appropriate caveats.

---

## Cross-Plan Verification

### Config Namespace Check

| Plan | New Config Keys | Namespace | Collision Check |
|------|----------------|-----------|----------------|
| Plan #1 | `retrieval.confidence_abs_floor`, `retrieval.cluster_detection_enabled`, `retrieval.output_mode` | `retrieval.*` | No collision -- existing `retrieval` section has `max_inject`, `match_strategy`, `judge.*` only |
| Plan #2 | `logging.enabled`, `logging.level`, `logging.retention_days` | `logging.*` | No collision -- `logging` section does not exist yet |

**All new keys are non-breaking additions using `dict.get()` safe defaults.**

### File Modification Overlap

| File | Plan #1 Modifies | Plan #2 Modifies | Conflict Risk |
|------|-----------------|-----------------|---------------|
| `hooks/scripts/memory_retrieve.py` | confidence_label, _output_results, hints, config parsing | Instrumentation (logging calls at 5 points) | **MEDIUM** -- both touch _output_results and config parsing. Cross-plan ordering (Plan #1 first, then Plan #2 instrumentation) resolves this. |
| `assets/memory-config.default.json` | +3 keys in `retrieval` | +3 keys in new `logging` section | **LOW** -- different sections |
| `tests/test_memory_retrieve.py` | Modify 2 tests, add ~35-65 | Not modified by Plan #2 directly | **NONE** |

### External Model Consensus

| Aspect | Gemini 3 Pro | Codex | Agreement |
|--------|-------------|-------|-----------|
| Plan #1 LOC estimates | "66-105 highly accurate" | "75-130 practical range, slight upward drift likely" | **Agree: feasible, may drift slightly high** |
| Plan #2 logger module | "80-120 correctly budgeted" | "80-120 only if minimal; full features = 120-180" | **Agree: feasible with scope discipline** |
| Plan #2 instrumentation | "10-50 LOC per module accurate" | "directionally reasonable, retrieve may drift to 70" | **Agree: feasible** |
| Plan #3 ordering | "enforces strict scientific rigor" | "sound with one constraint: freeze metrics before baseline" | **Agree: ordering correct** |
| Overall feasibility | "structurally sound, well-scoped, highly practical" | "all three plans practically buildable as described" | **Strong agreement** |

---

## Summary

| Plan | Verdict | Key Notes |
|------|---------|-----------|
| Plan #1: Actions #1-#4 | **PASS WITH NOTES** | LOC estimates realistic (may drift +10% at upper bound for Action #2). All code references verified. All review feedback addressed. 2 tests in test_v2_adversarial_fts5.py flagged conservatively but actually safe. |
| Plan #2: Logging Infrastructure | **PASS WITH NOTES** | Logger module may exceed 120 LOC with all features. Retrieve instrumentation may reach 70 LOC. All patterns verified against existing code. Import path feasible. All review feedback addressed. |
| Plan #3: PoC Experiments | **PASS** | Mostly methodology, minimal code. All code references exact. Cross-plan ordering sound. All review feedback addressed. `matched_tokens` gap accepted as pragmatic workaround. |

**Overall: All 3 plans are practically feasible and buildable as described.** No blocking issues found. LOC estimates are within acceptable tolerances (potential ~10-20% upward drift on upper bounds for Plan #1 Action #2 and Plan #2 logger module).
