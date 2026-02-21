# S7 Verification Round 1: Integration & Consistency Report

**Reviewer:** v1-integration
**Date:** 2026-02-21
**Scope:** Cross-file coherence of all Session 7 changes

---

## Summary

**Overall Verdict: PASS (10/10 checks pass, 2 non-blocking notes)**

All S7 deliverables (memory_judge.py, memory_retrieve.py integration, config, hooks.json, CLAUDE.md) are integration-consistent. No mismatches found between config keys, import chains, default values, or data formats.

---

## Check Results

### 1. Config Key Consistency -- PASS

Config keys in `assets/memory-config.default.json` lines 53-62:
```json
"judge": {
  "enabled": false,
  "model": "claude-haiku-4-5-20251001",
  "timeout_per_call": 3.0,
  "fallback_top_k": 2,
  "candidate_pool_size": 15,
  "dual_verification": false,
  "include_conversation_context": true,
  "context_turns": 5
}
```

Keys read by `memory_retrieve.py` (lines 367-369, 427-438, 446, 500-511, 519):
- `judge_cfg.get("enabled", False)` -- MATCH
- `judge_cfg.get("candidate_pool_size", 15)` -- MATCH
- `judge_cfg.get("model", "claude-haiku-4-5-20251001")` -- MATCH
- `judge_cfg.get("timeout_per_call", 3.0)` -- MATCH
- `judge_cfg.get("include_conversation_context", True)` -- MATCH
- `judge_cfg.get("context_turns", 5)` -- MATCH
- `judge_cfg.get("fallback_top_k", 2)` -- MATCH

All key names, nesting levels, and default values match exactly.

**Note:** `dual_verification` is in the config but not read by any code. This is by design -- it's reserved for Phase 4 (Session 9). No issue.

**Note:** The spec (rd-08-final-plan.md line 892-900) includes a `modes` sub-object with `auto.verification` and `search.max_output`. This is NOT in the default config, and NOT read by the code. No issue -- it was part of the full spec schema, not the Phase 3 implementation scope.

### 2. Import Chain -- PASS

`memory_retrieve.py` line 23:
```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

This ensures sibling modules are importable regardless of cwd. The `from memory_judge import judge_candidates` at lines 425 and 498 use deferred imports (inside `if judge_enabled` branches), which is correct -- the module is only loaded when the judge is actually used.

`memory_judge.py` has no imports from other project modules (stdlib only + `urllib.request`). No circular dependency risk.

### 3. Hook Timeout Adequacy -- PASS

`hooks/hooks.json` line 52: `"timeout": 15` (seconds) for UserPromptSubmit.

Worst-case calculation:
- FTS5 index build from index.md: ~50ms (500 entries)
- FTS5 BM25 query: ~10ms
- Body extraction (read 10 JSON files): ~100ms
- **Judge API call**: default timeout 3.0s (config `timeout_per_call`)
- Context extraction from transcript: ~5ms
- Output formatting: <1ms

**Worst case total: ~3.17s** -- well within 15s budget. Even with network latency doubling the API call, the 15s timeout provides generous headroom. The judge's own timeout (3s) acts as an inner circuit breaker.

### 4. CLAUDE.md Accuracy -- PASS

**Key Files table** (line 47):
```
| hooks/scripts/memory_judge.py | LLM-as-judge for retrieval verification (anti-position-bias, anti-injection) | stdlib only (urllib.request) |
```
- Role description: Accurate -- implements anti-position-bias shuffle (sha256 seed) and anti-injection (`<memory_data>` tags, system prompt hardening).
- Dependencies: Accurate -- stdlib only (json, hashlib, random, urllib.request, etc.).

**Architecture table** (line 18):
```
| UserPromptSubmit | Retrieval hook -- FTS5 BM25 keyword matcher injects relevant memories (fallback: legacy keyword), optional LLM judge layer filters false positives |
```
- Accurate. The judge is described as optional, which matches `judge.enabled: false` default.

**Config Architecture** (line 64):
```
Script-read: ... `retrieval.judge.*` (enabled, model, timeout_per_call, candidate_pool_size, fallback_top_k, include_conversation_context, context_turns)
```
- Lists 7 judge config keys. All 7 are read by `memory_retrieve.py`. Matches.

**Security Considerations** (line 124):
```
6. **LLM judge prompt injection** -- memory_judge.py wraps untrusted memory data in `<memory_data>` XML tags...
```
- Accurate. References `<memory_data>` tags (line 166 of memory_judge.py), sha256 shuffle (line 151), write-side sanitization, None fallback.

**Quick Smoke Check** (line 137):
```
python3 -m py_compile hooks/scripts/memory_judge.py
```
- Present and correct.

### 5. Default Values Alignment -- PASS

| Parameter | Config Default | Code Default (memory_judge.py) | Code Default (memory_retrieve.py) | Match? |
|-----------|---------------|-------------------------------|----------------------------------|--------|
| model | `claude-haiku-4-5-20251001` | `_DEFAULT_MODEL = "claude-haiku-4-5-20251001"` (line 27) | `.get("model", "claude-haiku-4-5-20251001")` (lines 435, 508) | YES |
| timeout | `3.0` | `timeout: float = 3.0` (line 57, 217) | `.get("timeout_per_call", 3.0)` (lines 436, 509) | YES |
| fallback_top_k | `2` | N/A (caller's responsibility) | `.get("fallback_top_k", 2)` (lines 446, 519) | YES |
| pool_size | `15` | N/A (caller's responsibility) | `.get("candidate_pool_size", 15)` (lines 427, 500) | YES |
| context_turns | `5` | `context_turns: int = 5` (line 219) | `.get("context_turns", 5)` (lines 438, 511) | YES |
| include_context | `true` | `include_context: bool = True` (line 218) | `.get("include_conversation_context", True)` (lines 437, 510) | YES |
| enabled | `false` | N/A | `.get("enabled", False)` (lines 369, 386) | YES |

All defaults align across config, judge module, and integration code.

### 6. Plugin Manifest -- PASS

`plugin.json` (`.claude-plugin/plugin.json`):
- `version: "5.0.0"` -- not bumped for S7. This is acceptable since the judge is opt-in (disabled by default) and doesn't change existing behavior.
- No new commands or skills added in S7 (the judge is internal to the retrieval hook).
- No changes needed.

### 7. Candidate Data Format -- PASS

`memory_retrieve.py` passes candidates to `judge_candidates()`:

**FTS5 path** (line 428): `candidates_for_judge = results[:pool_size]`
- `results` comes from `score_with_body()` -> `query_fts()` -> returns dicts with keys: `title`, `tags` (set), `path`, `category`, `score`.

**Legacy path** (line 501): `candidates_for_judge = [entry for _, _, entry in scored[:pool_size]]`
- `entry` comes from `parse_index_line()` -> returns dicts with keys: `category`, `title`, `path`, `tags` (set), `raw`.

`memory_judge.py` `format_judge_input()` (lines 158-161) reads:
- `c.get("tags", set())` -- works with set (from both paths)
- `c.get("title", "untitled")` -- works (both paths have "title")
- `c.get("category", "unknown")` -- works (both paths have "category")

`judge_candidates()` return value (line 244): `[candidates[i] for i in sorted(...)]` -- returns the original dicts, preserving all keys including `path`.

`memory_retrieve.py` uses the filtered results by matching on `path` (lines 442-443, 515-516):
```python
filtered_paths = {e["path"] for e in filtered}
results = [e for e in results if e["path"] in filtered_paths]
```
Both paths have `path` key. Match confirmed.

### 8. Error Propagation (None Fallback) -- PASS

**FTS5 path** (lines 441-447):
```python
if filtered is not None:
    filtered_paths = {e["path"] for e in filtered}
    results = [e for e in results if e["path"] in filtered_paths]
else:
    # Judge failed: conservative fallback
    fallback_k = judge_cfg.get("fallback_top_k", 2)
    results = results[:fallback_k]
```
- When judge returns None: falls back to BM25 Top-2. Correct.
- When judge returns empty list: `filtered_paths` is empty set, all results filtered out. This is the intended behavior (judge says nothing is relevant).

**Legacy path** (lines 514-520):
```python
if filtered is not None:
    filtered_paths = {e["path"] for e in filtered}
    scored = [(s, p, e) for s, p, e in scored if e["path"] in filtered_paths]
else:
    fallback_k = judge_cfg.get("fallback_top_k", 2)
    scored = scored[:fallback_k]
```
- Identical logic pattern. Correct.

**No-API-key path** (lines 386-388):
```python
if judge_cfg.get("enabled", False) and not os.environ.get("ANTHROPIC_API_KEY"):
    print("[INFO] LLM judge enabled but ANTHROPIC_API_KEY not set. ...")
```
- `judge_enabled` (line 369-372) requires BOTH `enabled=True` AND `ANTHROPIC_API_KEY` set. When key is missing, `judge_enabled` is False, so judge blocks are skipped entirely. The info message at line 386 fires as a user-facing notice. Correct.

### 9. Compile Check -- PASS

```
$ python3 -m py_compile hooks/scripts/memory_judge.py    -> OK
$ python3 -m py_compile hooks/scripts/memory_retrieve.py -> OK
```

Both files compile without errors.

### 10. Test Suite -- PASS

```
$ pytest tests/ -v
683 passed in 35.18s
```

All 683 tests pass. No regressions from S7 changes.

---

## Non-Blocking Notes

### N1: Implementation Improvement Over Spec (random.Random)

The spec (rd-08-final-plan.md line 714) uses `random.seed(seed)` + `random.shuffle(order)` which mutates global RNG state. The implementation (memory_judge.py line 152-153) uses `rng = random.Random(seed)` + `rng.shuffle(order)` which uses a local RNG instance. This is strictly better -- avoids polluting global RNG state that could affect other code in the same process. No action needed.

### N2: Implementation Improvement Over Spec (boolean guard)

The implementation (memory_judge.py line 201-203) adds a `isinstance(di, bool)` guard before `isinstance(di, int)` to reject boolean values in keep indices (since `bool` is a subclass of `int` in Python). The spec's `_extract_indices` (rd-08 line 761-772) does not include this guard. This is an improvement. No action needed.

### N3: `modes` Config Omission (By Design)

The spec's full config schema (rd-08 line 892-900) includes `judge.modes.auto.verification` and `judge.modes.search.max_output`. These are not in the default config or the code. This is by design -- the `modes` sub-object is for Phase 4 (Session 9, dual verification). No action needed.

---

## Conclusion

All 10 integration checks PASS. The S7 implementation is cross-file consistent with no mismatches in config keys, defaults, import chains, data formats, error handling, documentation, or hook configuration. The implementation includes two improvements over the spec (local RNG instance, boolean guard) that are strictly better.
