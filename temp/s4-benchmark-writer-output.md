# S4 Benchmark Writer Output

## Task: T8 -- Performance Benchmark Test

### What was done
Created `tests/test_fts5_benchmark.py` with 5 benchmark tests verifying FTS5 performance at 500-doc scale.

### Tests written

| Test | What it verifies |
|------|-----------------|
| `test_500_doc_index_build_under_limit` | Building FTS5 index from 500 entries < 100ms |
| `test_500_doc_query_under_limit` | Querying 500-doc index < 100ms |
| `test_500_doc_full_cycle_under_limit` | Build + tokenize + query + threshold < 100ms; also checks correctness (max_inject respected, result structure) |
| `test_500_doc_results_are_correct` | Known keywords ("timeout crash") match expected categories (RUNBOOK) |
| `test_500_doc_with_body_under_limit` | Full cycle with body content (include_body=True) < 100ms |

### Design decisions
- **Separate file** (`test_fts5_benchmark.py`): avoids merge conflicts with other teammates editing existing test files
- **100ms threshold**: generous for CI but meaningful -- actual runtime is ~7ms total for all 5 tests
- **`time.perf_counter()`**: high-resolution monotonic clock, standard for benchmarks
- **Helper `_memories_to_entries()`**: converts `bulk_memories` fixture dicts to `parse_index_line()` format (category, title, path, tags, raw)
- **Correctness alongside performance**: tests verify result structure, non-empty results, category matching, and max_inject clamping -- not just speed

### Results
- All 5 new tests pass
- Full suite: 659 passed in 26.86s (0 failures, 0 regressions)
- Actual benchmark times well under threshold (~1-2ms per test on this machine)

### Files created
- `tests/test_fts5_benchmark.py` (118 LOC)

### Dependencies
- Uses `bulk_memories` fixture from `conftest.py` (created by fixture-builder)
- Imports from `memory_search_engine.py`: `build_fts_index`, `build_fts_query`, `query_fts`, `apply_threshold`, `tokenize`
- Imports `FOLDER_MAP` from `conftest.py` for path construction
