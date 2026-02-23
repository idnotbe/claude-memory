# V1 Robustness Verification Report

**Verifier:** v1-robustness
**Date:** 2026-02-22
**Scope:** Security, edge cases, rollback safety, review feedback incorporation
**Source files verified:** `memory_retrieve.py`, `memory_write_guard.py`, `memory_judge.py`, `memory_triage.py`, `memory-config.default.json`, `.gitignore`
**Reviews referenced:** `review-engineering.md`, `review-adversarial.md`

---

## Plan #1: Actions #1-#4 (draft-plan-actions.md)

### VERIFIED Items

1. **Rollback via config defaults is sound.** `abs_floor=0.0` disables the floor (`abs(best) < 0.0` is never true). `output_mode="legacy"` preserves current behavior. `cluster_detection_enabled=false` disables cluster capping. All three use `dict.get()` safe defaults (verified at `memory_retrieve.py:353-384`). Old configs missing these keys will get defaults -- backward-compatible.

2. **`confidence_label()` single-result bug is real.** Verified at lines 161-174: `ratio = abs(score) / abs(best_score)` produces 1.0 for single results, always returning "high". The proposed fix (abs_floor parameter with default 0.0) preserves current behavior when unused.

3. **Cluster detection logic is architecturally sound.** `_output_results()` (lines 282-300) computes `best_score` once, then calls `confidence_label()` per-entry. Pre-computing `cluster_count` (entries with ratio > 0.90) at the same scope and passing it to each call is correct -- the count applies to the entire result set, not individual entries.

4. **Existing sanitization chain is untouched.** `_sanitize_title()` (lines 143-158) strips control chars, replaces ` -> ` with ` - `, removes `#tags:`, escapes XML characters. `_output_results()` applies `html.escape()` to path, category, and tags (lines 287-298). None of the proposed changes modify these sanitization paths.

5. **Test impact analysis is accurate.** The 5 tests identified are correctly analyzed. Tests #4 and #5 (`test_v2_adversarial_fts5.py:1063, 1079`) test security properties that are format-agnostic and will pass in legacy mode (default). Only tests asserting `confidence="low"` in output (lines 618, 649) break in tiered mode, which is correctly identified.

6. **Hint locations (3, not 2) are correctly identified.** Verified at lines 458, 495, 560 -- all three contain identical HTML comment hint text.

7. **Agent Hook PoC branch isolation.** Separate branch requirement is well-specified. `hooks.json` changes affect all prompts, so isolation is necessary. Kill criteria (p95 > 5s, no context injection) are clear and actionable.

8. **`<memory-compact>` security requirements.** Plan correctly requires XML structure wrapper with system-controlled attributes and user content sanitized through existing `_sanitize_title()` + `html.escape()`. Tags are preserved in compact mode (needed for relevance judgment).

9. **`_emit_search_hint()` uses hardcoded text only.** No user-controlled data flows into the hint. The `<memory-note>` tag name does not create structural interference since it exists in a different context segment from user prompts.

10. **Cluster detection now has config toggle (review feedback incorporated).** `retrieval.cluster_detection_enabled` (bool, default: `true`) provides config-based rollback. This addresses the adversarial review Finding #3 and the engineering review MEDIUM finding.

### UNVERIFIED Items

1. **`<memory-note>` efficacy vs HTML comments.** No evidence that Claude processes `<memory-note>` differently from `<!-- -->` in UserPromptSubmit context. This is a plausible assumption but empirically unvalidated. Risk is minimal (3 string replacements, reversible).

2. **Agent hook `type: "agent"` behavior in plugin context.** No agent hooks exist in the current `hooks/hooks.json` to verify against. Claims about `{ok: true/false}` return format are based on documentation, not empirical testing. This is why the PoC exists.

### NEW Findings

#### NEW-P1-1: MEDIUM -- `cluster_count` computed on post-`max_inject` truncated set may differ from full set

The plan states `cluster_count` is computed "on the result set after `max_inject` truncation" (line 80). With `max_inject=3`, if the full FTS5 result set has 8 entries with ratio > 0.90 but only 3 are returned, `cluster_count` would be 3 (triggering demotion). But if only 2 of the top 3 have ratio > 0.90 (because `apply_threshold()` reordered them), `cluster_count` would be 2 (no demotion). This creates a dependency on result ordering that could produce inconsistent behavior.

**Recommendation:** Clearly document whether `cluster_count` is computed before or after truncation. Computing it on the final result set (post-truncation) is simpler and consistent with what Claude sees, but should be explicitly stated.

#### NEW-P1-2: LOW -- `abs_floor` corpus-dependency warning is present but could be stronger

The plan includes a warning (line 64) about corpus-dependent behavior, added per review feedback. However, the warning is embedded in a "note" section. Given that miscalibrated `abs_floor` can suppress all results to "medium" (making them compact/silent in tiered mode), this deserves a more prominent position -- perhaps in the config description itself or as a startup warning when `abs_floor > 0` is detected.

### Review Feedback Status

| Finding | Source | Severity | Status |
|---------|--------|----------|--------|
| Briefing vs. plan inconsistency on output_mode default | Engineering | MEDIUM | **ADDRESSED** -- Plan correctly specifies "legacy" default (line 163). Briefing issue is external to this plan. |
| Cluster detection always-on risk | Engineering + Adversarial | MEDIUM | **ADDRESSED** -- Config toggle `cluster_detection_enabled` added (line 67-71), with default `true` and explicit rationale. External model consensus documented. |
| `cluster_count` semantics clarification | Engineering | LOW | **ADDRESSED** -- Lines 78-80 document that `cluster_count` represents entries "in the current result set" with ratio > 0.90, with note about `max_inject` truncation. |
| `abs_floor` corpus-dependency warning | Adversarial | MEDIUM | **ADDRESSED** -- Line 64 adds explicit warning about corpus dependence and interim nature. Mentions percentile-based future approach. |
| PoC #4 explicit failure path | Engineering | LOW | **Not in this plan's scope** -- Failure path is specified in Plan #3 (draft-plan-poc.md:157-162). |

### Verdict: **PASS WITH NOTES**

Notes:
- NEW-P1-1 (cluster_count computation scope) should be documented more explicitly
- No security concerns with the proposed changes
- All rollback paths are config-based except Action #3 (code revert, correctly flagged as low-risk)
- Rollback count correctly updated from "1" to "3" (V1-practical correction)

---

## Plan #2: Logging Infrastructure (draft-plan-logging-infra.md)

### VERIFIED Items

1. **`logging.enabled` default changed to `false` (review feedback incorporated).** Line 155: `"enabled": false`. Lines 160-163 provide detailed rationale citing engineering + adversarial review consensus. This is the correct default for v1.

2. **Write pattern changed to `os.write(fd, line_bytes)` (review feedback incorporated).** Line 74: explicit specification of `os.write(fd, line_bytes)` instead of `os.fdopen().write()`. This ensures single write syscall. Verified the existing `memory_triage.py:1000-1012` pattern still uses `os.fdopen()` -- this is the old pattern that the logging plan improves upon.

3. **Privacy: titles excluded at info level (review feedback incorporated).** Lines 112, 119-122: info level logs paths/IDs only; titles added only at debug level. This addresses the "secret residue" concern from the adversarial review.

4. **`schema_version: 1` added (review feedback incorporated).** Lines 115-116: all events include `schema_version` field for forward compatibility.

5. **`session_id` CLI limitation documented (review feedback incorporated).** Lines 123-124: CLI mode (`memory_search_engine.py --mode search`) has no `hook_input`, so `session_id` is unavailable. Documented as known limitation with future alternatives noted.

6. **Write guard non-interference confirmed.** Verified in `memory_write_guard.py:24-86`: the guard only intercepts Claude's `Write` tool via `hook_input.tool_input.file_path`. Python's `os.open()`/`os.write()` from hook scripts is completely invisible to this guard. The plan now documents this (line 367).

7. **Fail-open semantics.** All logging errors are caught and silently ignored. This is consistent with the existing `memory_triage.py` pattern (lines 1008-1015: `except OSError: pass`).

8. **Cleanup strategy: `.last_cleanup` time gate.** 24-hour cooldown prevents excessive cleanup runs. Double-cleanup race is benign (redundant `os.listdir()` + `os.unlink()`). Correctly documented.

9. **Config uses `dict.get()` safe defaults.** Matches existing pattern in `memory_retrieve.py:353-384`. Old configs without `logging` section will use defaults (enabled=false, level=info, retention_days=14).

10. **`.gitignore` guidance added (review feedback incorporated).** Lines 122, 166: explicit guidance to add `.claude/memory/logs/` to `.gitignore`. Verified: current `.gitignore` does NOT include this path -- guidance is necessary.

### UNVERIFIED Items

1. **p95 < 5ms performance target.** Cannot verify without implementation. The single `os.write()` + `json.dumps()` pattern should meet this target for sub-4KB entries, but actual benchmarking is needed in Phase 5.

2. **Atomic append for entries exceeding 4KB.** Plan caps `data.results` at 20 entries (line 125) to stay under 4KB. POSIX `write()` on regular files with `O_APPEND` is atomic for the file offset, but interleaved content from concurrent writes is theoretically possible for very large entries. Practically, Claude Code does not execute the same hook concurrently, making this a non-issue.

### NEW Findings

#### NEW-P2-1: MEDIUM -- `.gitignore` guidance is documentation-only, not enforced

The plan provides documentation guidance to add `.claude/memory/logs/` to `.gitignore`, but does not auto-generate or verify the `.gitignore` entry. If `logging.enabled` is set to `true` by a user, logs will accumulate without `.gitignore` protection unless the user manually adds the entry.

**Recommendation:** Consider having `memory_logger.py` emit a one-time stderr warning on first log creation if `.claude/memory/logs/` is not in the project's `.gitignore`. Cost: ~10 LOC. This is a belt-and-suspenders approach that doesn't modify any files automatically.

#### NEW-P2-2: LOW -- `query_tokens` at info level still reveals user intent

The privacy model excludes titles at info level but includes `query_tokens` (line 122). Query tokens like `["authentication", "api_key", "production_secret"]` can reveal what the user is working on. The plan acknowledges this (line 122: "`.gitignore` guide mandatory") but doesn't offer an option to redact query tokens at info level.

**Risk assessment:** With `logging.enabled` defaulting to `false`, this is opt-in behavior. Users who enable logging are implicitly accepting query token storage. The `.gitignore` guidance mitigates accidental git exposure. Acceptable for v1.

#### NEW-P2-3: LOW -- No size-based rotation alongside time-based retention

The plan uses time-based retention only (14 days). For heavy usage, a single day's JSONL could theoretically grow large. The plan estimates < 1MB for 14 days of normal usage, which is reasonable.

**Risk assessment:** Single-user plugin with typical usage patterns. The 20-entry cap on `data.results` limits per-event size. No immediate fix needed, but `logging.max_file_mb` is correctly identified as a future enhancement (line 164).

#### NEW-P2-4: LOW -- `O_NOFOLLOW` flag prevents symlink attacks on log files

The plan specifies `O_NOFOLLOW` in the `os.open()` flags (from the existing `memory_triage.py` pattern). This prevents symlink-based attacks where an attacker creates a symlink at the log path pointing to a sensitive file. Good security practice.

### Review Feedback Status

| Finding | Source | Severity | Status |
|---------|--------|----------|--------|
| `logging.enabled: true` default | Engineering (HIGH) + Adversarial (HIGH) | HIGH | **ADDRESSED** -- Changed to `false` (line 155) with detailed rationale (lines 160-163). |
| `os.fdopen().write()` should be `os.write()` | Engineering (MEDIUM) + Adversarial (MEDIUM) | MEDIUM | **ADDRESSED** -- Explicitly specified `os.write(fd, line_bytes)` pattern (line 74, line 319). |
| `session_id` unavailable in CLI mode | Engineering (MEDIUM) | MEDIUM | **ADDRESSED** -- Documented as limitation (lines 123-124) with future alternatives noted. |
| Missing `schema_version` field | Engineering (LOW) | LOW | **ADDRESSED** -- `schema_version: 1` added to all events (lines 115-116). |
| Cleanup race condition | Engineering (LOW) | LOW | **ADDRESSED** -- Documented as benign race (line 177). |
| Log privacy / secret residue | Adversarial (HIGH) | HIGH | **ADDRESSED** -- Titles excluded at info level (line 112), `.gitignore` guidance added (line 166). |
| Write guard blocking logs | Adversarial (LOW) | LOW | **ADDRESSED** -- Documented as non-issue with explanation (line 367). |
| Entry size cap | Engineering suggestion + Adversarial | MEDIUM | **ADDRESSED** -- `data.results` capped at 20 entries, 4KB target per entry (line 125). |

### Verdict: **PASS WITH NOTES**

Notes:
- NEW-P2-1 (`.gitignore` warning on first log creation) is a recommended enhancement, not a blocker
- All HIGH and MEDIUM review findings are properly addressed
- The privacy model (IDs at info, titles at debug) is sound but query tokens at info level still reveal intent -- acceptable with opt-in logging
- `O_NOFOLLOW` flag is a positive security measure carried from existing code

---

## Plan #3: PoC Experiments (draft-plan-poc.md)

### VERIFIED Items

1. **PoC #4 time-box and kill criteria are actionable.** p95 > 5s = auto-inject unsuitable. Context injection impossible = dead end. 1-day maximum. These are clear, measurable criteria.

2. **PoC #4 explicit failure path added (review feedback incorporated).** Lines 157-162: branch archive, results documentation, Action #4 marked WONTFIX/DEFERRED, immediate progression to PoC #5. This addresses the engineering review LOW finding.

3. **PoC #5 sample size staged approach is sound.** Pilot 25-30 queries, expand to 50+ after methodology validation. Stratified by 5 query types. This resolves the Codex/Gemini/Vibe-check disagreement pragmatically.

4. **PoC #5 test-retest reliability replaces inter-annotator agreement (review feedback incorporated).** Lines 213-215: 5-6 queries re-labeled at 1-week interval for self-agreement measurement. This is appropriate for a single-evaluator setup and addresses the engineering review LOW finding.

5. **PoC #6 reclassified as "exploratory data collection" (review feedback incorporated).** Lines 313-323: decision thresholds removed, v1 reports correlation only with explicit caveats, A/B test deferred to v2. This addresses both the adversarial review MEDIUM finding and external model concerns about causal inference.

6. **PoC #7 reuses #5 dataset efficiently.** Labeled data from PoC #5 is directly applicable to OR-query analysis, eliminating redundant labeling effort.

7. **Cross-plan implementation ordering is explicit (review feedback incorporated).** Lines 437-456: 8-step ordering with Plan #2 minimum viable logging before PoC #5 baseline, then Plan #1 Actions, then remaining instrumentation. This addresses the adversarial review LOW finding and engineering review MEDIUM finding about cross-plan ordering.

8. **Agent hook output mechanism correctly documented.** The plan accurately describes that agent hooks return `{ok: true/false}` and cannot inject arbitrary text (lines 146-150). Command hook is still required for context injection. This is consistent with the agent hook verification document.

9. **PoC #4 branch isolation required.** Separate branch (`poc4-agent-hook`) prevents experimental `hooks.json` changes from affecting production retrieval. Correct.

### UNVERIFIED Items

1. **`matched_tokens` field implementation complexity.** The plan estimates ~10-15 LOC for title+tags tokenization workaround (Plan #2 line 305). This is a post-hoc approximation that doesn't capture body bonus matches. Acceptable for v1 analysis scope.

2. **PoC #6 `session_id` stability across UserPromptSubmit calls.** The plan requires `session_id` derived from `transcript_path` to be stable within a session. While `transcript_path` IS available in hook input (verified at `memory_retrieve.py:432`), whether it remains constant across all prompts in the same Claude session is not explicitly verified. The plan notes this as a limitation.

### NEW Findings

#### NEW-P3-1: MEDIUM -- PoC #6 `nudge_id` mechanism is mentioned but not designed

The plan mentions adding a `nudge_id` for stronger correlation (line 323) but doesn't specify how it would be generated, stored, or correlated. Without this, the correlation relies entirely on `session_id` + time window, which the plan itself acknowledges is brittle.

**Recommendation:** If `nudge_id` is to be included, design it now: generate a UUID at compact injection time, embed it in the `retrieval.inject` log event, and match it against subsequent `search.query` events within the attribution window. Cost: ~5 LOC. If not implementing, remove the mention to avoid ambiguity.

#### NEW-P3-2: LOW -- PoC #5 labeling rubric single-criterion may be insufficient

The rubric "Would this memory help Claude give a better answer?" is a binary classification. For borderline cases (e.g., a memory about "React hooks" when the query is about "React performance"), different evaluators (or the same evaluator at different times) might disagree. The test-retest reliability measurement will catch this, but consider adding a 3-level scale (clearly relevant / borderline / clearly irrelevant) to improve data quality.

**Risk assessment:** Low. Binary labeling is standard for precision@k measurement. The test-retest reliability check will surface labeling inconsistencies.

#### NEW-P3-3: LOW -- PoC #7 `polluted_query_rate` thresholds (30%/50%) are pre-defined without baseline

The decision thresholds for OR-query pollution (>30% = priority increase, >50% = immediate fix) are set before any baseline data exists. These thresholds may be too aggressive or too lenient depending on the actual distribution.

**Risk assessment:** Low. These are guidelines, not automated gates. The PoC results will inform whether the thresholds are appropriate, and they can be adjusted.

### Review Feedback Status

| Finding | Source | Severity | Status |
|---------|--------|----------|--------|
| PoC #6 methodology weakness | Adversarial (MEDIUM) | MEDIUM | **ADDRESSED** -- Reclassified as exploratory data collection, decision thresholds removed, A/B test deferred to v2 (lines 313-323). |
| PoC #7 `matched_tokens` cross-plan gap | Engineering (MEDIUM) | MEDIUM | **PARTIALLY ADDRESSED** -- Plan acknowledges the gap (line 67) and proposes a title+tags tokenization workaround (lines 256-264). Plan #2 schema does NOT include `matched_tokens`, but the workaround is pragmatic. The explicit recommendation to add it to Plan #2 remains (line 305). |
| Inter-annotator agreement impractical | Engineering (LOW) | LOW | **ADDRESSED** -- Replaced with test-retest reliability (lines 213-215). |
| PoC #4 "if killed" path missing | Engineering (LOW) | LOW | **ADDRESSED** -- Explicit failure path added (lines 157-162): archive branch, document results, mark WONTFIX, proceed to PoC #5. |
| Cross-plan implementation ordering | Adversarial (LOW) + Engineering (MEDIUM) | MEDIUM | **ADDRESSED** -- 8-step cross-plan ordering explicitly stated (lines 437-456). |

### Verdict: **PASS WITH NOTES**

Notes:
- NEW-P3-1 (`nudge_id` design gap) should either be designed or the mention removed
- `matched_tokens` cross-plan gap is partially addressed via workaround -- acceptable for v1
- PoC #7 thresholds are guidelines, not hard gates -- acceptable

---

## Cross-Plan Verification

### Rollback Completeness

| Change | Rollback Method | Complete? |
|--------|----------------|-----------|
| Action #1: abs_floor | `confidence_abs_floor: 0.0` | YES -- disables the check (`abs(best) < 0.0` is impossible) |
| Action #1: cluster detection | `cluster_detection_enabled: false` | YES -- skips cluster count computation |
| Action #2: tiered output | `output_mode: "legacy"` | YES -- entire tiered code path is guarded by this config |
| Action #3: hint format | Code revert | YES but NO config rollback -- acceptable given 3-line change, hardcoded text only |
| Action #4: Agent Hook | Branch deletion | YES -- isolated on separate branch, never merges to main |
| Plan #2: logging | `logging.enabled: false` | YES -- zero file I/O when disabled |
| Plan #3: PoCs | No production changes | YES -- PoCs are measurement activities, not code changes (except PoC #4 on separate branch) |

**Rollback gap assessment:** All config-based rollbacks are complete. The `dict.get()` pattern ensures missing keys use safe defaults. Old configs without new keys will behave identically to pre-change behavior. No rollback gaps identified.

### Security Surface

| Concern | Assessment |
|---------|-----------|
| New logging creates injection vector? | NO -- Log files are written by Python scripts, not consumed by Claude. No path from log files back into LLM context. |
| `<memory-compact>` tag introduces XSS? | NO -- Uses same `_sanitize_title()` + `html.escape()` chain as existing `<result>` tags. User content is XML-escaped. |
| `<memory-note>` tag enables prompt injection? | NO -- Hardcoded text only, no user-controlled data. |
| Query tokens in logs enable data exfiltration? | MITIGATED -- Logging defaults to `false`. `.gitignore` guidance provided. Opt-in only. |
| New config keys enable config manipulation? | LOW RISK -- All new keys have safe defaults via `dict.get()`. Worst case: `abs_floor=999999` suppresses all confidence to medium, `output_mode` invalid string falls back to legacy. |

### Edge Cases

| Scenario | Plan #1 | Plan #2 | Plan #3 |
|----------|---------|---------|---------|
| Empty index (0 entries) | `_output_results()` never called; existing `sys.exit(0)` at line 404 handles this | No log events emitted (no search to log) | PoC #5 requires non-empty index by design |
| 0 search results | Existing 3 hint paths handle this; `_emit_search_hint("no_match")` replaces HTML comments | `retrieval.skip` or `retrieval.search` with 0 results logged | N/A |
| 1 search result | `abs_floor` check activates; cluster_count=1 < 3 so no cluster demotion | Normal logging | PoC #5 labels this normally |
| 500+ results | `max_inject` caps at 20 (clamped); `apply_threshold()` filters; only top-k reach `_output_results()` | `data.results` capped at 20 entries per log event | N/A |
| Corrupt config | All `dict.get()` with defaults; JSON parse failure caught at lines 383 | `parse_logging_config()` returns safe defaults | N/A |
| Missing logs dir | N/A | `os.makedirs(exist_ok=True)` creates dir; failure caught (fail-open) | N/A |
| Concurrent hook execution | N/A | `O_APPEND` + single `os.write()` syscall; benign race on cleanup | N/A |

### Fail-Open Correctness

Verified: The logging system truly never blocks hook execution.

1. `emit_event()` wraps all operations in try/except with silent catch (specified in plan)
2. `cleanup_old_logs()` failures are ignored (fail-open)
3. File creation failures fall through silently
4. The existing `memory_triage.py` logging (lines 1008-1015) demonstrates this pattern: `except OSError: pass`

No path exists where a logging failure can cause `memory_retrieve.py` to exit abnormally or fail to inject results.

### Config Safety

All new defaults are backward-compatible:

| Key | Default | Effect When Missing |
|-----|---------|-------------------|
| `retrieval.confidence_abs_floor` | `0.0` | No floor applied (current behavior) |
| `retrieval.cluster_detection_enabled` | `true` | Cluster detection active (new behavior, but safe -- only affects labeling, not selection) |
| `retrieval.output_mode` | `"legacy"` | Current output format preserved |
| `logging.enabled` | `false` | No logging (current behavior) |
| `logging.level` | `"info"` | Standard level if logging is enabled |
| `logging.retention_days` | `14` | 2-week retention if logging is enabled |

Old configs (pre-update `memory-config.json`) will not have any of these keys. The `dict.get(key, default)` pattern ensures all defaults apply. Verified this pattern is used consistently in `memory_retrieve.py:353-384`.

### Data Residue

The privacy approach (IDs at info, titles at debug) correctly prevents title leakage:

1. **Info level:** `results[]` contains `path`, `score`, `confidence` only -- no title. A retired/deleted memory's title will NOT appear in info-level logs.
2. **Debug level:** Titles included. Users enabling debug logging accept this risk.
3. **Query tokens at info level:** Reveals user intent but not memory content. Acceptable with opt-in logging + `.gitignore` guidance.

**Gap:** `query_tokens` at info level can indirectly reveal deleted memory content if the user was searching for it. For example, if a user had a memory titled "Stripe API key: sk_live_..." and searched for "stripe api key", the query tokens would persist in logs. This is a narrow edge case mitigated by:
- Logging defaults to `false`
- `.gitignore` guidance
- 14-day retention auto-cleanup

### Concurrency

**Log file corruption:** Prevented by `O_APPEND` flag + single `os.write()` syscall. The kernel guarantees atomic file offset update with `O_APPEND`. Single write syscall ensures the data is not interleaved with another process's write.

**Cleanup race:** Two simultaneous hook invocations could both read `.last_cleanup` as stale and both attempt cleanup. This results in redundant but harmless `os.unlink()` calls. Already documented as benign.

**FTS5 in-memory database:** Each `memory_retrieve.py` invocation creates its own in-memory FTS5 database (`:memory:`). No shared state between concurrent invocations.

---

## Overall Verdicts

| Plan | Verdict |
|------|---------|
| Plan #1: Actions #1-#4 | **PASS WITH NOTES** |
| Plan #2: Logging Infrastructure | **PASS WITH NOTES** |
| Plan #3: PoC Experiments | **PASS WITH NOTES** |

### Summary of NEW Findings

| ID | Severity | Plan | Description |
|----|----------|------|-------------|
| NEW-P1-1 | MEDIUM | #1 | `cluster_count` computation scope (pre vs post truncation) needs explicit documentation |
| NEW-P1-2 | LOW | #1 | `abs_floor` corpus-dependency warning could be more prominent |
| NEW-P2-1 | MEDIUM | #2 | `.gitignore` guidance is documentation-only, not enforced; consider first-log warning |
| NEW-P2-2 | LOW | #2 | `query_tokens` at info level reveals user intent (acceptable with opt-in) |
| NEW-P2-3 | LOW | #2 | No size-based log rotation (acceptable for v1, future enhancement noted) |
| NEW-P2-4 | LOW (positive) | #2 | `O_NOFOLLOW` flag is a good security measure |
| NEW-P3-1 | MEDIUM | #3 | `nudge_id` mechanism mentioned but not designed |
| NEW-P3-2 | LOW | #3 | Binary labeling rubric may miss borderline cases (mitigated by test-retest) |
| NEW-P3-3 | LOW | #3 | PoC #7 decision thresholds set without baseline data (acceptable as guidelines) |

### All HIGH/MEDIUM Review Findings: Incorporation Status

| Finding | Original Severity | Source | Status |
|---------|------------------|--------|--------|
| `logging.enabled: true` default | HIGH | Both reviews | **ADDRESSED** -- changed to `false` |
| Log privacy / secret residue | HIGH | Adversarial | **ADDRESSED** -- titles excluded at info level, `.gitignore` guidance |
| Cluster detection toggle | MEDIUM | Both reviews | **ADDRESSED** -- `cluster_detection_enabled` config key added |
| `os.fdopen()` -> `os.write()` | MEDIUM | Both reviews | **ADDRESSED** -- pattern explicitly specified |
| `session_id` CLI limitation | MEDIUM | Engineering | **ADDRESSED** -- documented as known limitation |
| Briefing inconsistency | MEDIUM | Engineering | **ADDRESSED** -- plan has correct default, briefing is external |
| PoC #6 methodology weakness | MEDIUM | Adversarial | **ADDRESSED** -- reclassified as exploratory |
| PoC #7 `matched_tokens` gap | MEDIUM | Engineering | **PARTIALLY ADDRESSED** -- workaround provided, cross-plan recommendation stands |
| Cross-plan ordering | MEDIUM | Both reviews | **ADDRESSED** -- 8-step ordering explicitly stated |
| `abs_floor` corpus dependency | MEDIUM | Adversarial | **ADDRESSED** -- warning added with percentile future path |

**No HIGH or MEDIUM findings remain unaddressed.** The one PARTIALLY ADDRESSED item (matched_tokens) has a pragmatic workaround that is acceptable for v1.
