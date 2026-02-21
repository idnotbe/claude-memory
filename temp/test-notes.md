# Test Notes: memory_triage.py Bug Fix Tests

**Test file**: `/home/idnotbe/projects/claude-memory/tests/test_memory_triage.py`
**Date**: 2026-02-18
**Result**: 56 passed, 0 failed (14 original + 42 new)

---

## Summary

Added 42 new tests across 7 test classes covering all 4 bug fixes, the score logging improvement, end-to-end integration, and edge cases.

## Test Classes Added

### TestExtractTextContent (10 tests) -- Bug 1
| Test | What it verifies |
|------|-----------------|
| test_user_string_content_nested | `type: "user"` with string at `msg["message"]["content"]` |
| test_user_list_content_text_blocks | `type: "user"` with list content -- only `text` blocks extracted, `tool_result` excluded |
| test_assistant_list_content_text_blocks | `type: "assistant"` with list content -- `text` extracted, `tool_use`/`thinking` excluded |
| test_thinking_blocks_excluded | `thinking` blocks NOT extracted |
| test_tool_result_blocks_excluded | `tool_result` blocks in user content NOT extracted |
| test_human_backwards_compat | Old `type: "human"` with flat `content` still works |
| test_mixed_formats | Mix of old-format and new-format messages together |
| test_empty_messages_returns_empty | Empty messages list returns empty string |
| test_non_content_types_skipped | progress/system messages skipped |
| test_assistant_flat_content_backwards_compat | Assistant with flat string content still works |

### TestExtractActivityMetrics (8 tests) -- Bug 2
| Test | What it verifies |
|------|-----------------|
| test_user_counted_as_exchange | `type: "user"` counted as exchange |
| test_nested_tool_use_counted | tool_use blocks inside assistant content counted |
| test_tool_result_not_counted_as_tool_use | tool_result in user content NOT counted |
| test_thinking_not_counted | thinking blocks NOT counted |
| test_backwards_compat_flat_format | Old flat format with top-level tool_use still works |
| test_multiple_assistant_messages_with_tools | Multiple assistant messages with multiple tool_use blocks |
| test_empty_messages | Empty list returns zero metrics |
| test_assistant_no_nested_content | Assistant with string content (no tool_use blocks) |

### TestExitProtocol (6 tests) -- Bug 3
| Test | What it verifies |
|------|-----------------|
| test_block_output_is_valid_stdout_json | Blocking path outputs valid JSON to stdout with `decision`+`reason` keys, exit 0 |
| test_block_output_no_extra_stdout | Exactly 1 JSON line on stdout, no extra text |
| test_allow_stop_no_stdout | Allow-stop: exit 0, no stdout |
| test_error_handler_no_stdout | Error path: no stdout, stderr has error, exit 0 |
| test_empty_stdin_returns_0_no_stdout | Empty stdin: exit 0, no stdout |
| test_invalid_json_stdin_returns_0_no_stdout | Invalid JSON stdin: exit 0, no stdout |

### TestParseTranscriptFiltering (7 tests) -- Bug 4
| Test | What it verifies |
|------|-----------------|
| test_filters_non_content_messages | progress/system/file-history excluded from result |
| test_deque_capacity_preserves_content | Low max_messages doesn't lose content messages to noise |
| test_human_preserved_by_filter | Old `type: "human"` passes deque filter |
| test_empty_file_returns_empty | Empty file returns empty list |
| test_missing_file_returns_empty | Missing file returns empty list |
| test_all_noise_returns_empty | All non-content messages returns empty list |
| test_deque_window_keeps_latest | max_messages=2 keeps last 2 content messages |

### TestScoreLogging (2 tests) -- Improvement
| Test | What it verifies |
|------|-----------------|
| test_score_log_written | Log file created with valid JSON containing expected keys |
| test_score_log_no_stdout_interference | Log write doesn't interfere with stdout |

### TestEndToEndIntegration (4 tests) -- Integration
| Test | What it verifies |
|------|-----------------|
| test_e2e_realistic_transcript | Full pipeline: parse -> extract -> triage with realistic mixed transcript |
| test_e2e_full_pipeline_blocking_output | Full _run_triage() pipeline producing valid JSON block response |
| test_e2e_non_triggering_transcript | Minimal transcript produces no triggers |
| test_e2e_session_summary_triggers | Many tool uses trigger SESSION_SUMMARY |

### TestEdgeCases (5 tests) -- Robustness
| Test | What it verifies |
|------|-----------------|
| test_extract_text_malformed_message_no_crash | Missing keys don't crash text extraction |
| test_extract_metrics_malformed_message_no_crash | Missing keys don't crash metrics extraction |
| test_extract_text_content_list_with_plain_strings | Content list with plain strings (defensive) |
| test_score_session_summary_zero_activity | Zero activity = zero score |
| test_run_triage_respects_thresholds | Categories below threshold not returned |

## Verification Checklist

- [x] All 14 original tests still pass
- [x] `extract_text_content()` returns non-empty text from `type: "user"` with nested content
- [x] `extract_text_content()` returns non-empty text from `type: "assistant"` with nested content
- [x] `extract_text_content()` still works with old-format `type: "human"` with flat `content`
- [x] `extract_activity_metrics()` counts exchanges for `type: "user"` messages
- [x] `extract_activity_metrics()` counts tool_use from nested assistant content blocks
- [x] Blocking output goes to stdout as JSON `{"decision": "block", "reason": "..."}`
- [x] No non-JSON output appears on stdout (verified with line count assertion)
- [x] Allow-stop case returns 0 with no stdout output
- [x] Score logging writes to `/tmp/.memory-triage-scores.log`
- [x] `thinking` blocks in assistant content are NOT extracted as text
- [x] `tool_result` blocks in user content list are NOT extracted as text
- [x] `parse_transcript()` filters out non-content message types
- [x] Module, main(), and format_block_message() docstrings updated (verified by reading source)

## Warnings

6 `DeprecationWarning` for `datetime.datetime.utcnow()` in the score logging code (line 959). This is cosmetic -- `utcnow()` is deprecated in Python 3.12+ in favor of `datetime.datetime.now(datetime.UTC)`. Not in scope for this fix but worth noting for a follow-up.

## Test Design Notes

- Used `io.StringIO` + `mock.patch("sys.stdout")` for stdout capture in exit protocol tests (more reliable than capsys for testing functions that write to stdout through mocked paths)
- Used `mock.patch("memory_triage.read_stdin")` to inject hook input without requiring real stdin
- Used `mock.patch("memory_triage.check_stop_flag")` to bypass flag file logic in integration tests
- Helper functions (`_user_msg`, `_assistant_msg`, `_progress_msg`, etc.) mirror real transcript format for consistent test construction
- End-to-end integration test builds a realistic transcript with all message types (user string content, user list content with tool_result, assistant list content with thinking/tool_use, progress noise) to verify the full pipeline
