# P2 Verification Report: Per-Project Ops Threshold Tuning

**Date**: 2026-03-22
**Verifier**: Claude Opus 4.6 (1M context)
**Impl report**: `temp/p2-impl-report.md`

---

## 1. Correctness Check: PASS

### Value Verification (programmatic)
```
decision:        0.26  == 0.26  ✓
preference:      0.34  == 0.34  ✓
session_summary: 0.6   == 0.6   ✓ (unchanged)
runbook:         0.4   == 0.4   ✓ (unchanged)
constraint:      0.5   == 0.5   ✓ (unchanged)
tech_debt:       0.4   == 0.4   ✓ (unchanged)
```

### JSON Validity
- Parsed successfully via `python3 -c "json.load(...)"`
- 2-space indentation preserved
- Trailing newline preserved
- No structural changes outside the `thresholds` block

### No Collateral Damage
All non-threshold config sections verified intact: categories, auto_commit, max_memories_per_category, parallel config, retrieval, delete, logging.

---

## 2. Safety Check: PASS

### Threshold Parsing Path (memory_triage.py)
1. `json.load()` reads config (line ~586)
2. `float(raw_val)` converts threshold value (line ~616)
3. `math.isnan(val) or math.isinf(val)` rejects NaN/Inf (line ~615)
4. `max(0.0, min(1.0, val))` clamps to [0, 1] (line ~617)
5. Stored in `config["thresholds"]` dict with UPPERCASE keys

**0.26 and 0.34 are valid inputs** -- ordinary finite floats, well within [0, 1] range.

### Comparison Operator
The threshold comparison at line 483 uses `>=` (greater-than-or-equal):
```python
if entry["score"] >= threshold:
```

For these specific values, `>=` vs `>` is **irrelevant** because 0.26 and 0.34 fall between quantized score buckets (no score lands exactly on them).

### Floating-Point Safety (confirmed by Codex)
- Raw DECISION score: `0.5 / 1.9 = 0.2631578947368421` (logged as 0.2632 after 4-decimal rounding)
- Raw PREFERENCE score: `0.7 / 2.05 = 0.34146341463414637` (logged as 0.3415)
- Margins above thresholds: ~0.003 (DECISION) and ~0.001 (PREFERENCE) -- far above IEEE 754 epsilon (~5.55e-17)
- The comparison uses raw scores, not rounded log values. No precision risk.

### Critical Safety Note
**Never set thresholds to the rounded log values** (e.g., 0.2632 or 0.3415). The log rounds to 4 decimals, but the actual raw score 0.263157... is below 0.2632, so that threshold would silently exclude the intended bucket.

### Crash Risk
None. The config parsing is defensive: wraps in try/except, clamps range, rejects NaN/Inf. Invalid values silently fall back to defaults.

---

## 3. Operational Check: PASS

### Other Systems Reading This Config
Only `memory_triage.py` reads threshold values at runtime. No other scripts or hooks consume `triage.thresholds`. The global default config (`assets/memory-config.default.json`) is separate and unchanged.

### Performance Impact of +9 DECISION Triggers

**Concurrency model**: Per triage event, each triggered category spawns a subagent in parallel. Max theoretical concurrency is 6 (one per category). The 9 DECISION triggers are spread across 71 distinct triage events, not simultaneous.

**Per-event worst case**: SESSION_SUMMARY + DECISION + others co-triggering = 2-3 parallel haiku subagents. This is well within normal API rate limits and local resource capacity.

**Gemini's concern about thundering herd**: Overstated. The ops project config uses `haiku` for ALL categories (not sonnet as Gemini assumed). Haiku subagents are lightweight. The FlockIndex lock in `memory_write.py` handles concurrent writes with a 15-second timeout and retry loop -- 2-3 concurrent writers is a normal operating condition.

### Memory Store Bloat

**Gemini raised a valid concern here.** DECISION has no `max_retained` rolling window (only SESSION_SUMMARY has `max_retained: 5`). Over 2 weeks (~1000 events at ~12.7% trigger rate), approximately 127 DECISION memories could accumulate.

**Mitigating factors:**
- `max_memories_per_category: 100` provides a hard cap (though enforcement is manual via `memory_enforce.py`)
- `retrieval.max_inject: 5` limits how many memories are injected per query regardless of store size
- The 2-week review checkpoint (2026-04-05) will catch excessive accumulation before it becomes problematic
- False positives can be retired manually; `memory_enforce.py` can be run for bulk cleanup

**Assessment**: Acceptable risk for a 2-week experiment. Monitor at review checkpoint.

---

## 4. Rollback Plan

### Exact Rollback Steps
1. Open `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`
2. Change `"decision": 0.26` back to `"decision": 0.4`
3. Change `"preference": 0.34` back to `"preference": 0.4`
4. No restart required -- thresholds are read at runtime per triage event

### Validation After 2 Weeks

**Review date**: 2026-04-05 (or after 200+ triage events, whichever comes first)

**Method**:
```bash
# Count DECISION triggers in triage logs
python3 -c "
import json, glob
files = sorted(glob.glob('/home/idnotbe/projects/ops/.claude/memory/logs/triage/*.jsonl'))
for f in files:
    dec_count = sum(1 for line in open(f)
                    if 'DECISION' in json.loads(line).get('triggered', []))
    print(f'{f}: {dec_count} DECISION triggers')
"

# Count actual DECISION memories created
ls /home/idnotbe/projects/ops/.claude/memory/decisions/ | wc -l
```

**Success criteria**:
- Precision >= 70% (at least 70% of DECISION triggers resulted in genuinely memory-worthy content)
- No retrieval quality degradation observed
- Keep thresholds if passing; revert to 0.4/0.4 if precision < 50%

---

## 5. Cross-Model Opinions

### Codex

**Verdict**: Safe to proceed.

Key findings:
- Confirmed no floating-point edge case for 0.26/0.34 thresholds (margins ~0.003 and ~0.001, far above ULP)
- Comparison uses raw scores, not rounded log values -- correct behavior
- `>=` vs `>` is irrelevant for these inter-bucket thresholds
- Config validation is sufficient for finiteness; noted minor permissiveness (accepts string-encoded numbers, booleans) but not a problem
- **Warned against using rounded log values as thresholds** (e.g., 0.2632 would silently exclude the target bucket)

### Gemini

**Verdict**: Safe at concurrency layer; flagged memory bloat risk.

Key findings:
- Correctly identified max concurrency is 6 per event (not 10 simultaneous)
- **Incorrectly stated** DECISION uses `sonnet` model (actual: all categories use `haiku` in ops config)
- Raised valid concern about DECISION lacking rolling-window retirement (`max_retained` only set for SESSION_SUMMARY)
- Estimated ~127 DECISION memories over 2 weeks, ~38 false positives -- could degrade FTS5 retrieval precision
- Recommended implementing pruning strategy before extended production use

### Synthesis
Both models agree the change is safe. Codex focused on numerical correctness (confirmed). Gemini raised an operational concern about memory accumulation that is valid but manageable within the 2-week experiment window.

---

## 6. Vibe Check

**Assessment**: Plan is solidly on track. Low-risk, data-driven, reversible experiment with clear success criteria and review checkpoint. No concerning patterns detected.

---

## Overall: PASS

| Dimension | Result | Notes |
|-----------|--------|-------|
| Correctness | PASS | All values verified programmatically |
| Safety | PASS | No crash risk, no float edge cases |
| Operational | PASS | Acceptable risk for 2-week experiment; monitor accumulation at review |
| Rollback | Documented | Revert decision→0.4, preference→0.4 |

**One action item**: At the 2026-04-05 review, specifically check DECISION memory count and precision rate. If accumulation exceeds expectations, consider running `memory_enforce.py --category decision --max-retained N` before reverting thresholds.
