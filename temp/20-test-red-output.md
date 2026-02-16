# TDD RED Phase -- Category Description Tests

## Summary

Wrote 15 new failing tests + 5 passing backward-compatibility tests across 2 test files. All 32 existing tests continue to pass.

**Result: 15 FAILED, 32 passed (47 total)**

## Test Files Modified

### NEW: `tests/test_memory_triage.py`

14 tests total (9 new description tests fail, 5 backward-compat tests pass).

| Test | Status | Tests What |
|------|--------|-----------|
| `test_load_config_reads_category_descriptions` | FAIL | Config with descriptions returns `category_descriptions` dict |
| `test_load_config_missing_descriptions_fallback` | FAIL | Missing descriptions = empty string |
| `test_load_config_descriptions_non_string_ignored` | FAIL | Non-string description values fallback |
| `test_load_config_empty_string_description` | FAIL | Explicit `""` preserved |
| `test_load_config_no_config_file_has_empty_descriptions` | FAIL | No config file = empty dict |
| `test_context_file_includes_description` | FAIL (TypeError) | `write_context_files()` new kwarg `category_descriptions` |
| `test_context_file_no_description_when_absent` | PASS | Backward compat: no description header when not provided |
| `test_context_file_session_summary_with_description` | FAIL (TypeError) | SESSION_SUMMARY context includes description |
| `test_triage_data_includes_description` | FAIL (TypeError) | `format_block_message()` new kwarg `category_descriptions` |
| `test_triage_data_no_description_when_absent` | PASS | Backward compat: no description in JSON when not provided |
| `test_human_readable_includes_description` | FAIL (TypeError) | Human-readable message mentions description |
| `test_load_config_still_returns_standard_keys` | PASS | Standard config keys unchanged |
| `test_write_context_files_works_without_descriptions` | PASS | Existing signature still works |
| `test_format_block_message_works_without_descriptions` | PASS | Existing signature still works |

### UPDATED: `tests/test_memory_retrieve.py`

6 new tests added (6 fail), existing 13 tests all pass.

| Test | Status | Tests What |
|------|--------|-----------|
| `test_description_tokens_boost_score` | FAIL | `score_description()` not yet implemented |
| `test_description_scoring_lower_weight_than_tags` | FAIL | Description < tag weight (3 pts) |
| `test_description_no_match_returns_zero` | FAIL | No overlap = 0 score |
| `test_description_empty_returns_zero` | FAIL | Empty description = 0 score |
| `test_description_prefix_matching` | FAIL | 4+ char prefix matching |
| `test_output_includes_category_descriptions` | FAIL | Integration: output includes description |
| `test_no_description_backward_compat` | PASS | Integration: works without descriptions |

## Failure Modes

The tests fail for exactly the right TDD RED reasons:

1. **`load_config()`**: Returns dict without `category_descriptions` key -> `AssertionError`/`KeyError`
2. **`write_context_files()`**: Doesn't accept `category_descriptions` kwarg -> `TypeError`
3. **`format_block_message()`**: Doesn't accept `category_descriptions` kwarg -> `TypeError`
4. **`score_description()`**: Function doesn't exist -> `pytest.fail()` (conditional import)
5. **Integration retrieval**: Output doesn't contain description text -> `AssertionError`

## Design Decisions Encoded in Tests

1. **`load_config()` returns `config["category_descriptions"]`** -- a flat `dict[str, str]` mapping lowercase category name to description
2. **`write_context_files()` accepts optional `category_descriptions=` kwarg** -- adds `Description: ...` header line
3. **`format_block_message()` accepts optional `category_descriptions=` kwarg** -- adds `description` field to triage_data JSON per category
4. **`score_description(prompt_words, description_tokens)` is a new function** in `memory_retrieve.py` -- returns int score, lower weight than tags
5. **All changes backward compatible** -- missing descriptions = no behavioral change

## Full Test Output

```
15 failed, 32 passed in 0.43s

FAILED tests/test_memory_triage.py::TestLoadConfigCategoryDescriptions::test_load_config_reads_category_descriptions
FAILED tests/test_memory_triage.py::TestLoadConfigCategoryDescriptions::test_load_config_missing_descriptions_fallback
FAILED tests/test_memory_triage.py::TestLoadConfigCategoryDescriptions::test_load_config_descriptions_non_string_ignored
FAILED tests/test_memory_triage.py::TestLoadConfigCategoryDescriptions::test_load_config_empty_string_description
FAILED tests/test_memory_triage.py::TestLoadConfigCategoryDescriptions::test_load_config_no_config_file_has_empty_descriptions
FAILED tests/test_memory_triage.py::TestContextFileIncludesDescription::test_context_file_includes_description
FAILED tests/test_memory_triage.py::TestContextFileIncludesDescription::test_context_file_session_summary_with_description
FAILED tests/test_memory_triage.py::TestTriageDataIncludesDescription::test_triage_data_includes_description
FAILED tests/test_memory_triage.py::TestTriageDataIncludesDescription::test_human_readable_includes_description
FAILED tests/test_memory_retrieve.py::TestDescriptionScoring::test_description_tokens_boost_score
FAILED tests/test_memory_retrieve.py::TestDescriptionScoring::test_description_scoring_lower_weight_than_tags
FAILED tests/test_memory_retrieve.py::TestDescriptionScoring::test_description_no_match_returns_zero
FAILED tests/test_memory_retrieve.py::TestDescriptionScoring::test_description_empty_returns_zero
FAILED tests/test_memory_retrieve.py::TestDescriptionScoring::test_description_prefix_matching
FAILED tests/test_memory_retrieve.py::TestRetrievalOutputIncludesDescriptions::test_output_includes_category_descriptions
```
