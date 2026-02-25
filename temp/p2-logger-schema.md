# Plan #2 -- JSONL Logging Schema Contract (v1)

**Date:** 2026-02-25
**Status:** Finalized (Phase 1)

---

## Common Envelope (all events)

Every JSONL line contains these top-level fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| schema_version | int | yes | Always `1` for this version |
| timestamp | string | yes | UTC ISO-8601 with millisecond precision, e.g. `"2026-02-25T10:30:00.123Z"` |
| event_type | string | yes | Dotted event type, e.g. `"retrieval.search"` |
| level | string | yes | One of: `"debug"`, `"info"`, `"warning"`, `"error"` |
| hook | string | yes | Hook name, e.g. `"UserPromptSubmit"`, `"Stop"`, or `""` for CLI |
| script | string | yes | Script filename, e.g. `"memory_retrieve.py"` |
| session_id | string | yes | Extracted from transcript path stem, or `""` |
| duration_ms | float\|null | yes | Elapsed time in milliseconds, or `null` |
| data | object | yes | Event-specific payload (see below) |
| error | object\|null | yes | Error details `{type, message}` or `null` |

---

## Event Types & data Schemas

### 1. retrieval.search

FTS5/legacy search execution with results.

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:30:00.123Z","event_type":"retrieval.search","level":"info","hook":"UserPromptSubmit","script":"memory_retrieve.py","session_id":"transcript-abc123","duration_ms":87.4,"data":{"query_tokens":["authentication","oauth"],"engine":"fts5_bm25","candidates_found":5,"candidates_post_threshold":5,"results":[{"path":".claude/memory/decisions/use-oauth.json","score":-4.23,"raw_bm25":-1.23,"body_bonus":3.0,"confidence":"high"},{"path":".claude/memory/constraints/api-limits.json","score":-2.11,"raw_bm25":-0.61,"body_bonus":1.5,"confidence":"medium"}]},"error":null}
```

**data fields:**
- `query_tokens` (list[str]): Tokenized search terms
- `engine` (str): `"fts5_bm25"` or `"title_tags"`
- `candidates_found` (int): Total candidates from search (NOTE: currently same as candidates_post_threshold -- see DEFERRED D-02)
- `candidates_post_threshold` (int): After threshold filtering
- `candidates_post_judge` (int, optional): After judge filtering. Present only in debug-level supplementary events when judge is active.
- `injected_count` (int, optional): Final number injected into context. Present in `retrieval.inject` event, not in `retrieval.search`.
- `results` (list[object], max 20): Per-candidate details (path, score, raw_bm25, body_bonus, confidence)

**Privacy note (info level):** results contain paths only, no titles. At `debug` level, titles may be added.

### 2. retrieval.inject

Final injection results with confidence breakdown.

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:30:00.210Z","event_type":"retrieval.inject","level":"info","hook":"UserPromptSubmit","script":"memory_retrieve.py","session_id":"transcript-abc123","duration_ms":12.3,"data":{"injected_count":3,"results":[{"path":".claude/memory/decisions/use-oauth.json","confidence":"high"},{"path":".claude/memory/constraints/api-limits.json","confidence":"medium"}],"output_mode":"full"},"error":null}
```

**data fields:**
- `injected_count` (int): Number of memories injected
- `results` (list[object], max 20): path + confidence per injected memory
- `output_mode` (str, planned -- DEFERRED D-01): `"full"`, `"compact"`, or `"silent"`. Not yet emitted by code.

### 3. retrieval.skip

Search skipped due to short prompt, disabled retrieval, etc.

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:30:00.050Z","event_type":"retrieval.skip","level":"info","hook":"UserPromptSubmit","script":"memory_retrieve.py","session_id":"transcript-abc123","duration_ms":null,"data":{"reason":"short_prompt","prompt_length":12},"error":null}
```

**data fields:**
- `reason` (str): `"short_prompt"`, `"empty_index"`, `"retrieval_disabled"`, `"max_inject_zero"`, `"no_fts5_results"`
- `prompt_length` (int, optional): Prompt character count when reason is `"short_prompt"`
- `query_tokens` (list[str], optional): Present when skip occurs after tokenization (e.g., `"no_fts5_results"`)

### 4. judge.evaluate

Judge candidate evaluation results.

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:30:01.500Z","event_type":"judge.evaluate","level":"info","hook":"UserPromptSubmit","script":"memory_judge.py","session_id":"transcript-abc123","duration_ms":1340.5,"data":{"candidate_count":5,"model":"claude-haiku-4-5-20251001","batch_count":1,"mode":"sequential","accepted_indices":[0,1,3],"rejected_indices":[2,4]},"error":null}
```

**data fields:**
- `candidate_count` (int): Total candidates submitted to judge
- `model` (str): Judge model identifier
- `batch_count` (int): Number of batches (1 = sequential, 2 = parallel)
- `mode` (str): `"sequential"` or `"parallel"`
- `accepted_indices` (list[int]): Sorted indices of accepted candidates
- `rejected_indices` (list[int]): Indices of rejected candidates

### 5. judge.error

Judge API error with fallback strategy.

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:30:02.000Z","event_type":"judge.error","level":"warning","hook":"UserPromptSubmit","script":"memory_judge.py","session_id":"transcript-abc123","duration_ms":3050.0,"data":{"error_type":"api_failure","message":"API call returned None","fallback":"caller_fallback","candidate_count":5,"model":"claude-haiku-4-5-20251001"},"error":null}
```

**data fields:**
- `error_type` (str): Error classification (`"api_failure"`, `"parse_failure"`, `"parallel_failure"`)
- `message` (str): Human-readable error description
- `fallback` (str): Fallback strategy (`"caller_fallback"`, `"sequential"`)
- `candidate_count` (int): Number of candidates that were being evaluated
- `model` (str): Judge model that failed

### 6. retrieval.judge_result (debug only)

Post-judge candidate filtering result. Debug-level supplementary event emitted after judge evaluation.

**data fields:**
- `candidates_post_judge` (int): Number of candidates surviving judge filtering
- `judge_active` (bool): Always `true` (event only emitted when judge is active)

### 7. retrieval.fallback (warning)

FTS5 unavailable, falling back to legacy keyword matching.

**data fields:**
- `engine` (str): Always `"title_tags"`
- `reason` (str): Always `"fts5_unavailable"`

### 8. search.query

CLI search query (on-demand via memory_search_engine.py).

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T11:00:00.400Z","event_type":"search.query","level":"info","hook":"CLI","script":"memory_search_engine.py","session_id":"","duration_ms":45.2,"data":{"fts_query":"oauth OR token","token_count":2,"result_count":6,"top_score":4.23},"error":null}
```

**data fields:**
- `fts_query` (str): The FTS5 query string sent to the search engine
- `token_count` (int): Number of tokens in the query
- `result_count` (int): Number of results returned
- `top_score` (float): Absolute score of the top result (0.0 if no results)

### 7. triage.score

Triage category scores (replaces `.staging/.triage-scores.log`).

```jsonl
{"schema_version":1,"timestamp":"2026-02-25T10:35:00.800Z","event_type":"triage.score","level":"info","hook":"Stop","script":"memory_triage.py","session_id":"transcript-abc123","duration_ms":230.0,"data":{"text_len":15000,"exchanges":12,"tool_uses":8,"triggered":[{"category":"DECISION","score":0.72},{"category":"RUNBOOK","score":0.55}],"all_scores":[{"category":"DECISION","score":0.72},{"category":"RUNBOOK","score":0.55},{"category":"CONSTRAINT","score":0.0},{"category":"TECH_DEBT","score":0.12},{"category":"PREFERENCE","score":0.0},{"category":"SESSION_SUMMARY","score":0.83}]},"error":null}
```

**data fields:**
- `text_len` (int): Transcript text length
- `exchanges` (int): Number of exchanges
- `tool_uses` (int): Number of tool uses
- `triggered` (list[object]): Categories that exceeded threshold, with scores
- `all_scores` (list[object]): ALL 6 category scores (for threshold tuning analytics). Each entry: `{category, score}`. Added in A-10.

---

## Directory Structure

```
<project>/.claude/memory/logs/
  retrieval/
    2026-02-25.jsonl
  judge/
    2026-02-25.jsonl
  search/
    2026-02-25.jsonl
  triage/
    2026-02-25.jsonl
  .last_cleanup          (timestamp file, not JSONL)
```

Event category = `event_type.split('.')[0]`.

---

## Config Keys

```json
{
  "logging": {
    "enabled": false,
    "level": "info",
    "retention_days": 14
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `logging.enabled` | bool | `false` | Enable JSONL logging. When false, zero file I/O |
| `logging.level` | string | `"info"` | Minimum log level: debug < info < warning < error |
| `logging.retention_days` | int | `14` | Auto-cleanup threshold. 0 = no cleanup |

---

## Constraints

- **Max results[]**: 20 entries per event (truncated). When truncation occurs, `data._truncated: true` and `data._original_results_count: <N>` are added to preserve the original count for analytics. These keys are absent when results are within the limit (<= 20).
- **POSIX atomic write**: Single `os.write()` syscall, line < 4KB
- **Symlink protection**: `O_NOFOLLOW` on all file opens
- **Fail-open**: All logging errors silently caught
- **Privacy (info level)**: Paths only, no titles in results
- **schema_version**: Always `1`; bump on breaking changes

---

## jq Verification Examples

```bash
# Parse and validate all retrieval events
cat .claude/memory/logs/retrieval/*.jsonl | jq '.event_type'

# Extract search duration timeseries
cat .claude/memory/logs/retrieval/*.jsonl | jq 'select(.event_type=="retrieval.search") | .duration_ms'

# Count candidates per search (retrieval pipeline)
cat .claude/memory/logs/retrieval/*.jsonl | jq 'select(.event_type=="retrieval.search") | .data.candidates_found'

# Count results per CLI search
cat .claude/memory/logs/search/*.jsonl | jq 'select(.event_type=="search.query") | .data.result_count'

# Filter judge errors
cat .claude/memory/logs/judge/*.jsonl | jq 'select(.event_type=="judge.error")'

# Session correlation
cat .claude/memory/logs/retrieval/*.jsonl | jq 'select(.session_id=="transcript-abc123")'
```

## Python Verification

```python
import json

line = '{"schema_version":1,"timestamp":"2026-02-25T10:30:00.123Z","event_type":"retrieval.search","level":"info","hook":"UserPromptSubmit","script":"memory_retrieve.py","session_id":"transcript-abc123","duration_ms":87.4,"data":{"query_tokens":["authentication","oauth"],"engine":"fts5_bm25","candidates_found":8,"candidates_post_threshold":5,"candidates_post_judge":3,"injected_count":3,"results":[]},"error":null}'

event = json.loads(line)
assert event["schema_version"] == 1
assert event["event_type"].count(".") == 1
assert event["level"] in ("debug", "info", "warning", "error")
assert isinstance(event["data"], dict)
print("Schema validation passed")
```
