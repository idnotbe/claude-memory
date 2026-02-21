# S7 Integrator Output -- memory_retrieve.py Judge Integration

## What Was Done

Integrated the LLM judge module (`memory_judge.py`) into `memory_retrieve.py` with ~67 added lines across 4 integration points. The pseudocode showed ~30 LOC for one path; I integrated into both the FTS5 and legacy paths for full coverage.

## Integration Points (4 edits)

### 1. Config Defaults (lines 346-347)
Added `judge_cfg: dict = {}` and `judge_enabled = False` as defaults alongside other retrieval config variables. These exist outside the config parsing block so they're always defined even without a config file.

### 2. Config Parsing (lines 366-374)
Inside the retrieval config `try` block, reads `retrieval.judge` config and computes `judge_enabled` as `config enabled AND ANTHROPIC_API_KEY present`. Wrapped in its own try/except to not disrupt existing config parsing.

### 3. Info Message (lines 386-388)
After the config block, prints `[INFO] LLM judge enabled but ANTHROPIC_API_KEY not set` to stderr when the judge is configured but the API key is missing. This aids debugging without disrupting normal operation.

### 4a. FTS5 Path Integration (lines 422-447)
After `score_with_body()` returns `results` (list of dicts), before `_output_results()`:
- Lazy imports `judge_candidates` from `memory_judge`
- Passes `results[:pool_size]` directly (dicts have `path`, `title`, `tags`, `category`)
- On success: filters `results` by `filtered_paths` set
- On failure: conservative fallback to `results[:fallback_top_k]`

### 4b. Legacy Path Integration (lines 496-520)
After `scored.sort()`, before "Pass 2: Deep check":
- Same logic but destructures `(score, priority, entry)` tuples: `candidates_for_judge = [entry for _, _, entry in scored[:pool_size]]`
- On success: filters `scored` tuples by `filtered_paths`
- On failure: conservative fallback to `scored[:fallback_top_k]`

## Config Keys Used

All from `retrieval.judge` namespace:
- `enabled` (bool, default: false)
- `candidate_pool_size` (int, default: 15)
- `model` (str, default: "claude-haiku-4-5-20251001")
- `timeout_per_call` (float, default: 3.0)
- `include_conversation_context` (bool, default: true)
- `context_turns` (int, default: 5)
- `fallback_top_k` (int, default: 2)

## Design Decisions

1. **Both paths integrated**: The pseudocode only showed the legacy path, but the FTS5 BM25 path is the default. Integrating both ensures the judge works regardless of which scoring path is active.

2. **Lazy import**: `from memory_judge import judge_candidates` is inside the `if judge_enabled` block, so it only imports when actually needed. Zero overhead when judge is disabled.

3. **transcript_path from hook_input**: Uses `hook_input.get("transcript_path", "")` which is available in `main()` scope from the stdin JSON.

4. **No new module-level imports**: The integration uses only lazy imports to avoid adding startup cost when the judge is disabled.

## Verification

- `python3 -m py_compile` passes
- All 683 existing tests pass (no regressions)
- Integration is disabled by default (`judge_cfg.enabled` defaults to `false`)
