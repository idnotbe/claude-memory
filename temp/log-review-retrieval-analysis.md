# ZERO_LENGTH_PROMPT Deep Investigation

**Date**: 2026-03-22
**Analyst**: Claude Opus 4.6 (1M context)
**Severity Reassessment**: ~~CRITICAL~~ -> **INFO** (confirmed false positive)

---

## Raw Data Summary

**Period**: 2026-03-21 to 2026-03-22 (73 total retrieval events)

| Metric | Value |
|--------|-------|
| Total events | 73 |
| Inject events | 68 (93.2%) |
| Skip events | 5 (6.8%) |
| Skip with prompt_length=0 | 4 |
| Skip with prompt_length>0 | 1 (prompt_length=4) |
| Unique sessions | 9 |

### Skip Event Details

| Timestamp (UTC) | Session | prompt_length | duration_ms | Session Position |
|-----------------|---------|---------------|-------------|------------------|
| 01:58:11 | 40ccb26c | 0 | null | 0/7 (first) |
| 01:59:23 | c59a007f | 0 | null | 0/1 (only event) |
| 02:08:40 | 40ccb26c | 0 | null | 1/7 |
| 02:11:53 | 40ccb26c | 0 | null | 2/7 |
| 03:07:10 | 21a6d936 | 4 | 0.63 | 1/2 |

### Key Observations

1. All 4 zero-length skips occurred between **01:58-02:11 UTC** on 2026-03-21
2. All 4 have `duration_ms: null` (not recorded)
3. The one legitimate short-prompt skip (prompt_length=4) has `duration_ms: 0.63`
4. Session 40ccb26c: 3 skips at start, then 4 successful injects from 02:38 onward
5. Session c59a007f: single zero-length skip, no further activity (abandoned session)

---

## Root Cause Analysis

### Definitive Root Cause: Pre-Fix Bug Artifact

The zero-length prompt events are **artifacts of a known bug that was fixed in commit `e6592b1`** on 2026-03-21.

**The bug**: Before commit `e6592b1`, line 402 of `memory_retrieve.py` read:
```python
user_prompt = hook_input.get("user_prompt", "")
```

But Claude Code's `UserPromptSubmitHookInput` sends the field as `"prompt"`, not `"user_prompt"`. This meant every invocation received `user_prompt = ""`, causing immediate skip with `prompt_length=0`.

**The fix** (commit `e6592b1`, line 411):
```python
user_prompt = hook_input.get("prompt") or hook_input.get("user_prompt") or ""
```

This correctly reads the `"prompt"` field first, with `"user_prompt"` as a backwards-compatibility fallback.

### Two Corroborating Signatures

1. **`duration_ms: null`**: The pre-fix code did not pass `duration_ms` to `emit_event` for short-prompt skips. The post-fix code does. All 4 zero-length skips have `null`; the post-fix skip (prompt_length=4) has `0.63`.

2. **Timestamp alignment**: All 4 zero-length skips occur at 01:58-02:11 UTC. The fix commit timestamp is 03:00 UTC (12:00:13 +0900). The commit message explicitly states: *"Fix retrieval 100% skip: read 'prompt' key instead of 'user_prompt' (Claude Code API field)"*.

### Timeline Reconstruction

| Time (UTC) | Event |
|------------|-------|
| 01:58-02:11 | Pre-fix code running: all prompts yield `user_prompt=""`, all skipped |
| 02:11-02:38 | 27-minute gap -- user diagnosing and fixing the bug in working tree |
| 02:38+ | Fixed code in working tree: inject events succeed |
| 03:00 | Fix committed as `e6592b1` |
| 03:07 | First post-fix skip: prompt_length=4, duration_ms=0.63 (legitimate short prompt) |

The plugin runs from the filesystem, not from git. The user applied the fix to their working copy, which immediately took effect for subsequent hook invocations, then committed later.

---

## Self-Critique

### Could this be a false positive from the analyzer?
**Yes, confirmed false positive.** The analyzer's `ZERO_LENGTH_PROMPT` rule triggers when >50% of skip events have `prompt_length=0`, regardless of:
- Absolute count (N=4 is too small for percentage-based alerting)
- Overall skip rate (6.8% is healthy)
- Deploy boundaries (pre-fix vs post-fix logs mixed in same window)

### Are there edge cases (empty user messages, system-initiated prompts)?
My initial hypothesis considered empty-enter inputs and session-init events. While these remain theoretically possible, the `duration_ms: null` signature and timestamp correlation with the known bug make the pre-fix artifact explanation far stronger. These are not runtime edge cases -- they are development-time bug artifacts.

### Security implications?
**Minimal, and now resolved.** The pre-fix bug caused retrieval to silently skip all prompts, meaning stored security constraints, runbooks, and decisions were never injected into context. This is an availability/recall issue, not a confidentiality or integrity issue. The fix in `e6592b1` resolved this completely. Post-fix logs show 100% inject success for substantive prompts.

---

## Cross-Model Opinions

### Codex (OpenAI)
**Verdict**: Partially agrees. Correctly identified that the commit history is the key evidence. Pointed out that `e6592b1` changed `hook_input.get("user_prompt", "")` to `hook_input.get("prompt") or hook_input.get("user_prompt") or ""` and that the `duration_ms: null` signature matches the pre-fix code path. Recommended segmenting analysis by deploy boundary and adding minimum sample size to the analyzer.

Key quote: *"likely a real bug, already fixed, plus an over-aggressive analyzer"*

### Gemini (Google)
**Verdict**: Strongly agrees with the false positive conclusion. Identified the `duration_ms: null` anomaly as proof of legacy code generation. Noted the security behavior is actually correct -- the short-circuit at `len < 10` prevents resource exhaustion and FTS5 query injection. Recommended minimum threshold of `len(skip_events) > 20` before calculating percentages.

Key quote: *"The `duration_ms: null` anomaly on zero-length skips indicates they are legacy logs generated by an older version of `memory_retrieve.py`"*

### Consensus
All three analyses (mine + codex + gemini) converge on:
1. The analyzer CRITICAL severity is a false positive
2. The `duration_ms: null` pattern is the strongest diagnostic signal
3. The root cause is the pre-fix `user_prompt` vs `prompt` field name bug
4. The analyzer needs a minimum sample size guard

---

## Final Assessment

**Confidence Level: 95% (High)**

The `ZERO_LENGTH_PROMPT` finding is a **confirmed false positive** caused by the analyzer processing a mixed pre-fix/post-fix log window. The underlying bug (wrong field name `user_prompt` instead of `prompt`) was real but was fixed in commit `e6592b1` before any post-fix zero-length events appeared. All post-fix retrieval events show healthy behavior (100% inject rate for substantive prompts).

The 5% uncertainty accounts for the theoretical possibility that Claude Code occasionally fires `UserPromptSubmit` with empty `prompt` fields during session initialization -- but no post-fix evidence of this exists in the current dataset.

---

## Recommended Fixes

### 1. Analyzer: Add minimum sample size guard (Priority: Medium)
**File**: `hooks/scripts/memory_log_analyzer.py`

The `ZERO_LENGTH_PROMPT` rule should require a minimum number of skip events before computing percentages. Suggested threshold: N >= 10 skip events.

### 2. Analyzer: Consider deploy boundaries (Priority: Low)
When the analysis window spans a known code change (detectable via `duration_ms: null` vs non-null pattern shift), flag the finding as "mixed-version artifact" rather than CRITICAL.

### 3. No changes needed to memory_retrieve.py
The fix in `e6592b1` is correct and complete. The dual-field lookup (`"prompt"` primary, `"user_prompt"` fallback) is robust against future Claude Code API changes.
