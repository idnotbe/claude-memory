# Stop Hook Re-fire Fix -- Test Coverage Analysis

## File 1: tests/test_memory_triage.py (3213 lines)

### Test Patterns
- **Fixtures**: Uses pytest `tmp_path` for isolated filesystem tests; no custom conftest fixtures
- **Mocking**: Heavy use of `unittest.mock.patch` targeting `memory_triage` namespace. Mocks `read_stdin`, `sys.stdout`, `check_stop_flag`, `run_triage`, `ensure_staging_dir`, `os.open`, `os.replace`
- **IO Capture**: Uses `io.StringIO` to capture stdout for JSON response validation
- **Module reimport**: `TestTriageFallbackStagingDir` reimports `memory_triage` after blocking `memory_staging_utils` to test the inline fallback codepath

### Test Functions by Group

#### TestLoadConfigCategoryDescriptions (5 tests)
- `test_load_config_reads_category_descriptions` -- config with descriptions returns them
- `test_load_config_missing_descriptions_fallback` -- missing descriptions default to empty string
- `test_load_config_descriptions_non_string_ignored` -- non-string description values become empty
- `test_load_config_empty_string_description` -- explicit empty string preserved
- `test_load_config_no_config_file_has_empty_descriptions` -- missing config yields empty dict

#### TestContextFileIncludesDescription (3 tests)
- `test_context_file_includes_description` -- "Description:" header written when description provided
- `test_context_file_no_description_when_absent` -- no "Description:" header when absent
- `test_context_file_session_summary_with_description` -- session_summary category also gets description

#### TestTriageDataIncludesDescription (3 tests)
- `test_triage_data_includes_description` -- triage_data JSON includes description per category
- `test_triage_data_no_description_when_absent` -- no description key when not provided
- `test_human_readable_includes_description` -- human-readable part mentions description

#### TestBackwardCompatNoDescriptions (3 tests)
- `test_load_config_still_returns_standard_keys` -- standard config keys still work
- `test_write_context_files_works_without_descriptions` -- backward compat without descriptions
- `test_format_block_message_works_without_descriptions` -- backward compat without descriptions

#### TestExtractTextContent (10 tests)
- `test_user_string_content_nested` -- nested user string content extracted
- `test_user_list_content_text_blocks` -- list content: only 'text' blocks extracted
- `test_assistant_list_content_text_blocks` -- assistant list content text only
- `test_thinking_blocks_excluded` -- thinking blocks NOT extracted
- `test_tool_result_blocks_excluded` -- tool_result blocks NOT extracted
- `test_human_backwards_compat` -- old 'human' type works
- `test_mixed_formats` -- mix of old and new format messages
- `test_empty_messages_returns_empty` -- empty list returns empty
- `test_non_content_types_skipped` -- progress/system types skipped
- `test_assistant_flat_content_backwards_compat` -- flat assistant content works

#### TestExtractActivityMetrics (7 tests)
- `test_user_counted_as_exchange` -- user messages counted
- `test_nested_tool_use_counted` -- tool_use blocks inside assistant counted
- `test_tool_result_not_counted_as_tool_use` -- tool_result not counted as tool use
- `test_thinking_not_counted` -- thinking blocks not counted
- `test_backwards_compat_flat_format` -- old flat format works
- `test_multiple_assistant_messages_with_tools` -- multiple assistant messages with tools
- `test_empty_messages` -- empty list returns zeros
- `test_assistant_no_nested_content` -- string content (no tool_use)

#### TestExitProtocol (5 tests)
- `test_block_output_is_valid_stdout_json` -- blocking path outputs valid JSON
- `test_block_output_no_extra_stdout` -- no extra text on stdout
- `test_allow_stop_no_stdout` -- allow-stop: no stdout
- `test_error_handler_no_stdout` -- error path: no stdout, only stderr
- `test_empty_stdin_returns_0_no_stdout` -- empty stdin returns 0
- `test_invalid_json_stdin_returns_0_no_stdout` -- invalid JSON returns 0

#### TestParseTranscriptFiltering (6 tests)
- `test_filters_non_content_messages` -- progress/system/file-history excluded
- `test_deque_capacity_preserves_content` -- content not pushed out by noise
- `test_human_preserved_by_filter` -- old 'human' type passes filter
- `test_empty_file_returns_empty` -- empty file returns []
- `test_missing_file_returns_empty` -- missing file returns []
- `test_all_noise_returns_empty` -- all non-content returns []
- `test_deque_window_keeps_latest` -- max_messages keeps latest

#### TestScoreLogging (1 test)
- `test_score_log_no_stdout_interference` -- score logging doesn't pollute stdout

#### TestEndToEndIntegration (3 tests)
- `test_e2e_realistic_transcript` -- full pipeline with realistic transcript
- `test_e2e_full_pipeline_blocking_output` -- full _run_triage with blocking output
- `test_e2e_non_triggering_transcript` -- minimal transcript doesn't trigger
- `test_e2e_session_summary_triggers` -- many tool uses trigger SESSION_SUMMARY

#### TestEdgeCases (5 tests)
- `test_extract_text_malformed_message_no_crash` -- malformed messages don't crash
- `test_extract_metrics_malformed_message_no_crash` -- malformed messages don't crash metrics
- `test_extract_text_content_list_with_plain_strings` -- plain strings in content list
- `test_score_session_summary_zero_activity` -- zero activity = zero score
- `test_run_triage_respects_thresholds` -- high threshold prevents triggering

#### TestStagingPaths (6 tests) -- R2: context files use /tmp/ staging
- `test_context_files_use_staging_dir_when_cwd_provided` -- staging dir used when cwd given
- `test_context_files_fallback_to_tmp_when_no_cwd` -- fallback to /tmp/ without cwd
- `test_staging_dir_created_if_absent` -- staging dir created if missing
- `test_multiple_categories_in_staging` -- multiple categories go to staging
- `test_staging_content_matches_tmp_content` -- content quality same as /tmp/
- `test_context_file_permissions` -- 0o600 permissions

#### TestSentinelIdempotency (7 tests) -- R3: sentinel-based idempotency
- `test_sentinel_allows_stop_when_fresh` -- existing sentinel suppresses re-fire
- `test_sentinel_ignored_when_different_session` -- different session_id allows triage
- `test_sentinel_created_when_blocking` -- sentinel created on block with JSON state
- `test_sentinel_missing_dir_handled_gracefully` -- no crash if .staging/ missing
- `test_sentinel_not_created_when_allowing` -- sentinel NOT created on allow
- `test_sentinel_idempotency_sequential_calls` -- first blocks, second suppressed
- `test_sentinel_uses_flag_ttl_constant` -- FLAG_TTL_SECONDS == 1800

#### TestBuildTriageData (6 tests)
- `test_build_triage_data_basic_structure` -- correct top-level keys
- `test_build_triage_data_includes_descriptions` -- descriptions included when provided
- `test_build_triage_data_no_description_when_absent` -- description omitted when absent
- `test_build_triage_data_parallel_config_defaults` -- missing parallel config keys use defaults
- `test_build_triage_data_no_context_path` -- context_file omitted when no path
- `test_build_triage_data_json_serializable` -- output is JSON-serializable

#### TestFormatBlockMessageTriageDataPath (4 tests)
- `test_format_block_message_with_triage_data_path` -- outputs `<triage_data_file>` tag
- `test_format_block_message_without_triage_data_path` -- outputs inline `<triage_data>`
- `test_format_block_message_default_is_inline` -- default is inline
- `test_format_block_message_file_path_with_descriptions` -- file path + descriptions

#### TestRunTriageWritesTriageDataFile (3 tests)
- `test_triage_data_file_written` -- triage-data.json written to staging with staging_dir field
- `test_triage_data_file_fallback_on_write_error` -- falls back to inline on write error
- `test_triage_data_file_fallback_on_replace_error` -- falls back to inline on replace error

#### TestSessionSummaryTranscriptExcerpt (6 tests) -- Phase 4
- `test_long_transcript_has_head_and_tail` -- >280 lines produces head+tail
- `test_short_transcript_has_full` -- <280 lines produces full
- `test_boundary_transcript_exact_280_lines` -- 280 lines uses full
- `test_trailing_newline_280_lines_uses_full` -- trailing newline still uses full
- `test_empty_transcript_no_excerpt` -- empty transcript no section
- `test_50kb_cap_still_works` -- long transcript truncated at 50KB
- `test_other_categories_unaffected` -- non-session categories use keyword excerpts

#### TestConstraintThresholdFix (8 tests)
- `test_three_primaries_crosses_threshold` -- 3 primaries > 0.45
- `test_two_primaries_below_threshold` -- 2 primaries < 0.45
- `test_cannot_not_primary` -- 'cannot' alone = 0.0
- `test_cannot_as_booster` -- primary + 'cannot' = boosted
- `test_constraint_runbook_overlap_reduced` -- error+cannot no longer triggers CONSTRAINT
- `test_new_primaries_score` -- new primary keywords score correctly
- `test_new_boosters_boost` -- new boosters amplify correctly
- `test_other_categories_unaffected` -- other thresholds unchanged
- `test_default_threshold_value` -- CONSTRAINT threshold == 0.45

#### TestStopHookRefireFix (22 tests) -- MAIN REFIRE FIX TESTS
- `test_sentinel_survives_cleanup` -- .triage-handled NOT in cleanup patterns
- `test_flag_ttl_covers_save_flow` -- FLAG_TTL_SECONDS >= 1800
- `test_save_result_guard_blocks_same_session` -- fresh result + matching session_id blocks
- `test_save_result_guard_allows_different_session` -- different session_id allows
- `test_save_result_guard_allows_stale_result` -- stale result allows
- `test_save_result_guard_works_without_sentinel` -- session_id independent of sentinel
- `test_save_result_guard_fallback_to_sentinel` -- backwards compat via sentinel cross-reference
- `test_runbook_threshold` -- RUNBOOK >= 0.5
- `test_session_scoped_sentinel_blocks_same_session` -- same session_id + blocking state blocks
- `test_session_scoped_sentinel_allows_different_session` -- different session_id allows
- `test_session_scoped_sentinel_allows_failed_state` -- failed state allows re-triage
- `test_session_scoped_sentinel_allows_expired` -- expired timestamp allows
- `test_atomic_lock_acquire_release` -- acquire/release cycle works, lock in staging dir
- `test_atomic_lock_held_blocks_second_acquire` -- second acquire returns HELD
- `test_sentinel_read_write_roundtrip` -- write then read returns same data
- `test_read_sentinel_returns_none_when_missing` -- missing sentinel returns None
- `test_negative_patterns_suppress_doc_headings` -- doc headings suppressed
- `test_negative_patterns_allow_real_troubleshooting` -- real text not suppressed
- `test_negative_patterns_suppress_phase3_save_commands` -- Phase 3 commands suppressed
- `test_negative_patterns_suppress_phase3_boilerplate` -- Phase 3 boilerplate suppressed
- `test_negative_patterns_suppress_phase3_headings` -- Phase 3 headings suppressed
- `test_negative_patterns_dont_suppress_real_error_fix` -- real error fix not suppressed
- `test_negative_patterns_mixed_skillmd_and_real` -- mixed content: only real lines score
- `test_negative_patterns_dont_suppress_similar_real_text` -- similar phrasing not suppressed
- `test_lock_path_in_staging_dir` -- lock path in staging dir, not cwd/.claude/
- `test_stop_flag_ttl_is_separate` -- STOP_FLAG_TTL (300) < FLAG_TTL_SECONDS (1800)
- `test_check_stop_flag_uses_stop_flag_ttl` -- 400s old flag expires per STOP_FLAG_TTL
- `test_check_stop_flag_fresh_within_stop_flag_ttl` -- fresh flag returns True

#### TestTriageFallbackStagingDir (2 tests) -- V-R2 GAP 2
- `test_fallback_ensure_staging_dir_rejects_symlink` -- inline fallback rejects symlinks
- `test_fallback_ensure_staging_dir_rejects_foreign_uid` -- inline fallback rejects foreign UID

#### TestRuntimeErrorDegradation (4 tests) -- V-R2 GAP 3
- `test_write_context_files_degrades_on_runtime_error` -- fallback to per-file /tmp/ paths
- `test_write_context_files_degrades_on_os_error` -- handles OSError
- `test_main_triage_fails_open_on_runtime_error` -- main() returns 0 on RuntimeError
- `test_run_triage_triage_data_falls_back_to_inline_on_staging_error` -- triage-data falls back to inline

#### TestTriageFallbackPaths (3 tests) -- V-R2 GAP 2 continued
- `test_run_triage_fallback_when_ensure_staging_fails` -- inline `<triage_data>` fallback
- `test_write_context_files_returns_empty_on_staging_failure` -- empty dict on total failure
- `test_triage_data_path_none_triggers_inline_fallback` -- None path triggers inline

---

## File 2: tests/test_memory_staging_utils.py (427 lines)

### Test Patterns
- **Fixtures**: Uses pytest `tmp_path`; creates real `/tmp/.claude-memory-staging-*` dirs for some tests
- **Mocking**: `unittest.mock.patch` on `memory_staging_utils.os.*` for foreign UID tests
- **Cleanup**: `try/finally` blocks clean up real `/tmp/` paths

### Test Functions by Group

#### TestGetStagingDir (7 tests)
- `test_returns_tmp_prefix` -- result starts with /tmp/.claude-memory-staging-
- `test_deterministic_same_cwd` -- same cwd produces same path
- `test_different_cwd_gives_different_path` -- different cwds produce different paths
- `test_hash_is_12_chars` -- hash suffix is 12 hex chars
- `test_matches_manual_computation` -- matches SHA-256 computation
- `test_empty_cwd_uses_getcwd` -- empty cwd falls back to os.getcwd()
- `test_symlink_cwd_resolves_to_realpath` -- symlink cwd resolves to realpath

#### TestEnsureStagingDir (5 tests)
- `test_creates_directory` -- creates the directory
- `test_returns_same_as_get` -- returns same path as get_staging_dir
- `test_idempotent` -- calling twice works
- `test_permissions_0o700` -- 0o700 permissions
- `test_cleanup` -- cleanup after test

#### TestIsStagingPath (8 tests)
- `test_valid_tmp_staging_path` -- valid staging path identified
- `test_valid_staging_dir_only` -- directory itself identified
- `test_non_staging_path` -- random /tmp/ paths don't match
- `test_claude_memory_path_not_staging` -- old .claude/memory paths not staging
- `test_partial_prefix_no_match` -- partial prefix doesn't match
- `test_empty_string` -- empty string returns False
- `test_similar_prefix_but_different` -- near-miss prefix doesn't match
- `test_nested_file_within_staging` -- nested files match

#### TestValidateStagingDirSecurity (7 tests) -- V-R2 GAP 1
- `test_rejects_symlink_at_staging_path` -- symlink raises RuntimeError
- `test_rejects_foreign_ownership_via_mock` -- foreign UID raises RuntimeError
- `test_tightens_loose_permissions` -- 0o777 tightened to 0o700
- `test_regular_file_at_path_raises_runtime_error` -- non-directory raises RuntimeError
- `test_accepts_valid_own_directory` -- valid directory passes
- `test_mkdir_creates_new_dir_without_validation` -- new dir created without lstat
- `test_ensure_staging_dir_propagates_runtime_error` -- RuntimeError propagated

#### TestValidateStagingDirLegacyPath (6 tests)
- `test_legacy_staging_rejects_symlink` -- symlink at legacy path rejected
- `test_legacy_staging_fixes_permissions` -- loose permissions tightened
- `test_legacy_staging_rejects_wrong_owner` -- foreign UID rejected
- `test_legacy_staging_creates_parents` -- parent dirs created
- `test_legacy_staging_idempotent` -- calling twice works
- `test_legacy_staging_rejects_regular_file` -- non-directory rejected

---

## File 3: tests/test_memory_write.py (2091 lines)

### Test Patterns
- **Fixtures**: `memory_project` from conftest.py (creates tmp project dir); conftest factories (`make_decision_memory`, `make_preference_memory`, etc.)
- **Subprocess execution**: `run_write()` helper runs `memory_write.py` as a subprocess for integration tests
- **Direct imports**: Unit tests import functions directly from `memory_write` module
- **Real /tmp/ dirs**: Tests using `_make_tmp_staging()` create real `/tmp/.claude-memory-staging-*` directories with `try/finally` cleanup

### Test Functions by Group

#### TestAutoFix (7 tests)
- `test_missing_timestamps` -- adds missing timestamps and schema_version
- `test_tags_string_to_array` -- converts string tag to list
- `test_id_slugify` -- slugifies id field
- `test_confidence_clamp_above` -- clamps confidence to 1.0
- `test_confidence_clamp_below` -- clamps confidence to 0.0
- `test_dedup_and_sort_tags` -- deduplicates and sorts tags
- `test_empty_tags_after_dedup` -- empty tags become ["untagged"]

#### TestSlugify (3 tests)
- `test_basic` -- basic slugification
- `test_special_chars` -- special characters handled
- `test_max_length` -- max 80 chars

#### TestValidation (5 tests)
- `test_valid_decision` -- valid decision passes
- `test_wrong_enum_value` -- wrong enum fails
- `test_missing_required_field` -- missing required fails
- `test_extra_fields_rejected` -- extra content fields rejected
- `test_extra_top_level_rejected` -- extra top-level fields rejected

#### TestFormatValidationError (1 test)
- `test_error_format` -- error format includes field and expected

#### TestBuildIndexLine (2 tests)
- `test_enriched_format` -- enriched index line format
- `test_no_tags` -- no tags omits #tags:

#### TestWordDifferenceRatio (4 tests)
- `test_identical_titles` -- 0.0 for identical
- `test_completely_different` -- 1.0 for completely different
- `test_partial_overlap` -- 0.5 for partial
- `test_empty_strings` -- 0.0 for empty

#### TestMergeProtections (10 tests)
- `test_immutable_fields_rejected` -- created_at immutable
- `test_record_status_immutable_via_update` -- record_status via update blocked
- `test_tags_grow_only_below_cap` -- tag removal rejected below cap
- `test_tags_eviction_at_cap` -- eviction allowed at TAG_CAP
- `test_tags_eviction_no_addition_rejected` -- eviction without addition rejected
- `test_tags_exceed_cap_during_eviction_rejected` -- exceeding cap rejected
- `test_tags_grow_beyond_cap_no_removal_allowed` -- growth beyond cap OK if no removal
- `test_related_files_grow_only` -- file removal rejected
- `test_related_files_dangling_removal_allowed` -- nonexistent file removal OK
- `test_changes_append_only` -- changes append-only
- `test_auto_change_log_for_scalar_changes` -- auto-log for scalar changes

#### TestCreateFlow (3 tests)
- `test_create_valid` -- create memory successfully
- `test_create_anti_resurrection` -- cannot create over retired file
- `test_create_with_auto_fixes` -- auto-fixes applied on create

#### TestUpdateFlow (4 tests)
- `test_update_valid` -- update memory successfully
- `test_update_occ_hash_mismatch` -- hash mismatch blocked
- `test_update_slug_rename` -- title change triggers rename
- `test_update_changes_fifo_overflow` -- changes capped at CHANGES_CAP

#### TestRetireFlow (3 tests)
- `test_retire_retires` -- retire sets record_status, removes from index
- `test_retire_idempotent` -- double retire is idempotent
- `test_retire_nonexistent` -- retiring nonexistent fails

#### TestPydanticValidation (7 tests)
- `test_all_categories_validate` -- all 6 categories validate
- `test_decision_wrong_status` -- wrong status fails
- `test_constraint_wrong_severity` -- wrong severity fails
- `test_preference_wrong_strength` -- wrong strength fails
- `test_session_wrong_outcome` -- wrong outcome fails
- `test_tech_debt_wrong_priority` -- wrong priority fails
- `test_runbook_empty_steps` -- empty steps fails
- `test_decision_empty_rationale` -- empty rationale fails

#### TestArchiveFlow (6 tests)
- `test_archive_active_memory` -- archive happy path
- `test_archive_already_archived` -- idempotent
- `test_archive_retired_memory_fails` -- can't archive retired
- `test_archive_nonexistent_fails` -- nonexistent fails
- `test_archive_removes_from_index` -- removed from index
- `test_archive_adds_change_entry` -- change entry added

#### TestUnarchiveFlow (5 tests)
- `test_unarchive_archived_memory` -- unarchive happy path
- `test_unarchive_active_memory_fails` -- can't unarchive active
- `test_unarchive_retired_memory_fails` -- can't unarchive retired
- `test_unarchive_nonexistent_fails` -- nonexistent fails
- `test_unarchive_adds_to_index` -- added to index
- `test_unarchive_adds_change_entry` -- change entry added

#### TestRetireArchiveInteraction (2 tests)
- `test_retire_clears_archived_fields` -- retire clears stale archived fields
- `test_archived_to_retired_blocked` -- can't retire archived (must unarchive first)

#### TestPathTraversal (3 tests)
- `test_path_traversal_create_blocked` -- path traversal on create blocked
- `test_path_traversal_retire_blocked` -- path traversal on retire blocked
- `test_path_traversal_archive_blocked` -- path traversal on archive blocked

#### TestTagSanitization (5 tests)
- `test_newline_in_tags_stripped` -- newlines stripped
- `test_comma_in_tags_replaced` -- commas replaced
- `test_tags_prefix_in_tag_stripped` -- #tags: stripped
- `test_arrow_in_tag_stripped` -- arrow separator stripped
- `test_control_chars_in_tags_stripped` -- control chars stripped

#### TestCreateRecordStatusInjection (2 tests)
- `test_create_forces_active_status` -- forces active on create
- `test_create_forces_active_strips_archived` -- strips archived on create

#### TestTagCapEnforcement (2 tests)
- `test_tags_truncated_to_cap_on_create` -- tags truncated to TAG_CAP
- `test_create_with_many_tags_succeeds_within_cap` -- many tags succeed but truncated

#### TestTitleSanitization (2 tests)
- `test_null_bytes_stripped_from_title` -- null bytes stripped
- `test_newlines_stripped_from_title` -- newlines stripped

#### TestOCCWarning (1 test)
- `test_update_without_hash_warns` -- update without hash warns but succeeds

#### TestCleanupIntents (8 tests) -- P1 popup fix
- `test_deletes_intent_files` -- intent files deleted
- `test_preserves_non_intent_files` -- non-intent files preserved
- `test_symlink_rejected` -- symlinks rejected
- `test_path_traversal_rejected` -- path traversal rejected
- `test_nonexistent_dir_returns_ok` -- nonexistent dir OK
- `test_invalid_staging_path_returns_error` -- invalid path returns error
- `test_empty_staging_dir` -- empty dir OK
- `test_tmp_staging_path_accepted` -- /tmp/ prefix accepted

#### TestCleanupIntentsTmpPath (5 tests) -- V-R2 GAP 4
- `test_multiple_intents_in_tmp` -- multiple intent files deleted from /tmp/
- `test_symlink_rejected_in_tmp_staging` -- symlinks rejected in /tmp/
- `test_empty_tmp_staging` -- empty /tmp/ staging OK
- `test_path_containment_in_tmp` -- path traversal via symlink rejected
- `test_rejects_invalid_tmp_path` -- invalid /tmp/ path rejected
- `test_rejects_arbitrary_memory_staging` -- arbitrary memory/.staging rejected

#### TestCleanupStagingTmpPath (5 tests) -- V-R2 GAP 4
- `test_cleanup_staging_accepts_real_tmp_path` -- transient files deleted from /tmp/
- `test_cleanup_staging_rejects_invalid_tmp_path` -- invalid /tmp/ path rejected
- `test_cleanup_staging_rejects_arbitrary_memory_staging` -- arbitrary staging rejected
- `test_cleanup_staging_symlink_skipped_in_tmp` -- symlinks skipped in /tmp/
- `test_cleanup_staging_empty_tmp_dir` -- empty staging OK

#### TestWriteSaveResultDirect (8 tests) -- P2 popup fix
- `test_happy_path` -- creates last-save-result.json with correct fields
- `test_missing_categories_fails` -- missing --categories fails
- `test_missing_titles_fails` -- missing --titles fails
- `test_empty_categories_fails` -- empty categories fails
- `test_empty_titles_fails` -- empty titles fails
- `test_single_category_and_title` -- single values work
- `test_missing_staging_dir_fails` -- missing --staging-dir fails
- `test_comma_in_title_splits` -- commas split titles
- `test_session_id_from_sentinel` -- reads session_id from sentinel
- `test_session_id_none_without_sentinel` -- null session_id when no sentinel

#### TestUpdateSentinelState (10 tests) -- Follow-up: sentinel state advancement
- `test_pending_to_saving` -- valid transition: pending -> saving
- `test_saving_to_saved` -- valid transition: saving -> saved
- `test_saving_to_failed` -- valid transition: saving -> failed
- `test_pending_to_failed` -- valid transition: pending -> failed
- `test_invalid_transition_pending_to_saved` -- invalid: pending -> saved
- `test_invalid_transition_saved_to_saving` -- invalid: saved -> saving
- `test_missing_sentinel_file` -- missing sentinel -> error (exit 0)
- `test_missing_staging_dir_fails_open` -- missing --staging-dir -> exit 0
- `test_missing_state_fails_open` -- missing --state -> exit 0
- `test_session_id_preserved` -- session_id preserved through transition
- `test_timestamp_updated` -- timestamp updated on transition
- `test_malformed_json_sentinel_fails_open` -- malformed JSON -> error (exit 0)

#### TestLegacyStagingValidation (11 tests) -- Pre-existing: legacy path validation
- `test_valid_legacy_path_accepted` -- standard path accepted
- `test_evil_memory_staging_rejected` -- /tmp/evil/memory/.staging rejected
- `test_etc_memory_staging_rejected` -- /etc/memory/.staging rejected
- `test_tmp_staging_still_accepted` -- /tmp/.claude-memory-staging-* handled separately
- `test_nested_claude_path_accepted` -- deeply nested path accepted
- `test_root_claude_path_accepted` -- root-level path accepted
- `test_wrong_order_rejected` -- wrong component order rejected
- `test_missing_memory_rejected` -- missing memory component rejected
- `test_partial_claude_name_rejected` -- 'claude' without dot rejected
- `test_subdirectory_bypass_rejected` -- deep subdirectory rejected
- `test_file_in_staging_rejected_in_dir_mode` -- file path rejected in dir mode
- `test_file_inside_staging_accepted_with_allow_child` -- allow_child=True accepts file
- `test_staging_dir_accepted_with_allow_child` -- allow_child=True accepts dir
- `test_evil_path_rejected_with_allow_child` -- evil path rejected even with allow_child

#### TestRuntimeErrorDegradation (4 tests) -- Pre-existing: write_save_result RuntimeError catch
- `test_write_save_result_degrades_on_runtime_error` -- RuntimeError returns error dict
- `test_write_save_result_degrades_on_os_error` -- OSError returns error dict
- `test_update_sentinel_state_rejects_invalid_path` -- invalid path rejected
- `test_write_save_result_error_message_contains_detail` -- error includes original exception text

---

## Coverage Matrix: Action Plan Features vs. Test Coverage

### Phase 1: P0 Hotfix

| Feature | Tests | Status |
|---------|-------|--------|
| Sentinel survives cleanup (removed from `_STAGING_CLEANUP_PATTERNS`) | `test_sentinel_survives_cleanup` (triage) | **COVERED** |
| FLAG_TTL 1800 (increased from 300) | `test_flag_ttl_covers_save_flow` (triage), `test_sentinel_uses_flag_ttl_constant` (triage) | **COVERED** |
| STOP_FLAG_TTL 300 (separate from FLAG_TTL) | `test_stop_flag_ttl_is_separate`, `test_check_stop_flag_uses_stop_flag_ttl`, `test_check_stop_flag_fresh_within_stop_flag_ttl` (triage) | **COVERED** |
| Save-result guard: same session blocks | `test_save_result_guard_blocks_same_session` (triage) | **COVERED** |
| Save-result guard: different session allows | `test_save_result_guard_allows_different_session` (triage) | **COVERED** |
| Save-result guard: stale result allows | `test_save_result_guard_allows_stale_result` (triage) | **COVERED** |
| Save-result guard: works without sentinel | `test_save_result_guard_works_without_sentinel` (triage) | **COVERED** |
| Save-result guard: fallback to sentinel | `test_save_result_guard_fallback_to_sentinel` (triage) | **COVERED** |
| Atomic lock: acquire | `test_atomic_lock_acquire_release` (triage) | **COVERED** |
| Atomic lock: release | `test_atomic_lock_acquire_release` (triage) | **COVERED** |
| Atomic lock: stale (120s detection) | None | **MISSING** |
| Atomic lock: concurrent/HELD | `test_atomic_lock_held_blocks_second_acquire` (triage) | **COVERED** |

### Phase 2: Raise RUNBOOK Threshold

| Feature | Tests | Status |
|---------|-------|--------|
| RUNBOOK threshold >= 0.5 | `test_runbook_threshold` (triage) | **COVERED** |
| Negative patterns: doc scaffolding headings | `test_negative_patterns_suppress_doc_headings` (triage) | **COVERED** |
| Negative patterns: Phase 3 save commands | `test_negative_patterns_suppress_phase3_save_commands` (triage) | **COVERED** |
| Negative patterns: Phase 3 boilerplate | `test_negative_patterns_suppress_phase3_boilerplate` (triage) | **COVERED** |
| Negative patterns: Phase 3 headings | `test_negative_patterns_suppress_phase3_headings` (triage) | **COVERED** |
| Negative patterns: real text NOT suppressed | `test_negative_patterns_allow_real_troubleshooting`, `test_negative_patterns_dont_suppress_real_error_fix`, `test_negative_patterns_dont_suppress_similar_real_text` (triage) | **COVERED** |
| Negative patterns: mixed content | `test_negative_patterns_mixed_skillmd_and_real` (triage) | **COVERED** |

### Phase 3: Session-Scoped Idempotency

| Feature | Tests | Status |
|---------|-------|--------|
| Session-scoped sentinel blocks same session | `test_session_scoped_sentinel_blocks_same_session` (triage), `test_sentinel_allows_stop_when_fresh` (triage) | **COVERED** |
| Sentinel allows different session | `test_session_scoped_sentinel_allows_different_session` (triage), `test_sentinel_ignored_when_different_session` (triage) | **COVERED** |
| Sentinel allows failed state | `test_session_scoped_sentinel_allows_failed_state` (triage) | **COVERED** |
| Sentinel allows expired timestamp | `test_session_scoped_sentinel_allows_expired` (triage) | **COVERED** |
| Sentinel JSON roundtrip | `test_sentinel_read_write_roundtrip` (triage) | **COVERED** |
| Sentinel states (pending/saving/saved/failed) | Implicit in `test_sentinel_allows_stop_when_fresh` (pending), `test_session_scoped_sentinel_allows_failed_state` (failed), `test_session_scoped_sentinel_blocks_same_session` (saved) | **PARTIAL** -- "saving" state not explicitly tested via check_sentinel_session |
| Sentinel created when blocking | `test_sentinel_created_when_blocking` (triage) | **COVERED** |
| Sentinel NOT created when allowing | `test_sentinel_not_created_when_allowing` (triage) | **COVERED** |
| Sequential idempotency (first blocks, second suppressed) | `test_sentinel_idempotency_sequential_calls` (triage) | **COVERED** |

### Phase 4: Tests (listed tests from action plan)

| Feature | Tests | Status |
|---------|-------|--------|
| `test_sentinel_survives_cleanup` | Present in TestStopHookRefireFix | **COVERED** |
| `test_flag_ttl_covers_save_flow` | Present in TestStopHookRefireFix | **COVERED** |
| `test_save_result_guard_*` (3 tests) | 5 tests present (same, different, stale, without sentinel, fallback) | **COVERED** |
| `test_runbook_threshold` | Present in TestStopHookRefireFix | **COVERED** |
| `test_session_scoped_sentinel_*` (4 tests) | 4 tests present (blocks, allows different, allows failed, allows expired) | **COVERED** |
| Additional: lock acquire/release | `test_atomic_lock_acquire_release`, `test_atomic_lock_held_blocks_second_acquire` | **COVERED** |
| Additional: sentinel roundtrip | `test_sentinel_read_write_roundtrip`, `test_read_sentinel_returns_none_when_missing` | **COVERED** |
| Additional: negative patterns (2) | 8 negative pattern tests | **COVERED** |
| Additional: STOP_FLAG_TTL (3) | 3 tests | **COVERED** |

### Follow-up Items

| Feature | Tests | Status |
|---------|-------|--------|
| Sentinel state advancement (update-sentinel-state CLI) | `test_pending_to_saving`, `test_saving_to_saved`, `test_saving_to_failed`, `test_pending_to_failed`, `test_invalid_transition_*` (2), `test_missing_*` (3), `test_session_id_preserved`, `test_timestamp_updated`, `test_malformed_json_sentinel_fails_open` (write) | **COVERED** |
| RUNBOOK negative filter broadening | 8 tests covering 5 pattern groups in TestStopHookRefireFix | **COVERED** |
| Lock path in staging dir | `test_lock_path_in_staging_dir`, `test_atomic_lock_acquire_release` (verifies staging dir) (triage) | **COVERED** |
| session_id in save-result | `test_session_id_from_sentinel`, `test_session_id_none_without_sentinel` (write); `test_save_result_guard_works_without_sentinel`, `test_save_result_guard_fallback_to_sentinel` (triage) | **COVERED** |

### Pre-existing Security Fixes

| Feature | Tests | Status |
|---------|-------|--------|
| Staging dir symlink hijack (memory_staging_utils.py) | `test_rejects_symlink_at_staging_path`, `test_rejects_foreign_ownership_via_mock`, `test_tightens_loose_permissions`, `test_regular_file_at_path_raises_runtime_error`, `test_accepts_valid_own_directory`, `test_mkdir_creates_new_dir_without_validation`, `test_ensure_staging_dir_propagates_runtime_error` (staging_utils) | **COVERED** |
| Legacy path validation (_is_valid_legacy_staging) | 14 tests in TestLegacyStagingValidation (write) | **COVERED** |
| write_save_result RuntimeError catch | `test_write_save_result_degrades_on_runtime_error`, `test_write_save_result_degrades_on_os_error`, `test_write_save_result_error_message_contains_detail`, `test_update_sentinel_state_rejects_invalid_path` (write) | **COVERED** |

---

## Summary

| Category | Total Features | COVERED | PARTIAL | MISSING |
|----------|---------------|---------|---------|---------|
| Phase 1: P0 Hotfix | 12 | 11 | 0 | 1 |
| Phase 2: RUNBOOK threshold + negatives | 7 | 7 | 0 | 0 |
| Phase 3: Session-scoped sentinel | 9 | 8 | 1 | 0 |
| Phase 4: Listed tests | 9 | 9 | 0 | 0 |
| Follow-up items | 4 | 4 | 0 | 0 |
| Pre-existing fixes | 3 | 3 | 0 | 0 |
| **TOTAL** | **44** | **42** | **1** | **1** |

### Gaps

1. **MISSING -- Atomic lock stale detection (120s)**: No test verifies that a lock file older than 120 seconds is treated as stale and allows re-acquisition. The tests cover acquire, release, and held-blocks-second-acquire, but not the stale-lock bypass path.

2. **PARTIAL -- Sentinel "saving" state via check_sentinel_session**: The `check_sentinel_session()` function is tested with states "saved" (blocks), "failed" (allows), and "pending" (tested via `test_sentinel_allows_stop_when_fresh` which uses state="pending"). The "saving" state should also block, but no explicit test verifies `check_sentinel_session()` returns `True` for `state="saving"`. The TestUpdateSentinelState tests in test_memory_write.py cover the state machine transitions thoroughly, but those test `update_sentinel_state()` CLI, not `check_sentinel_session()`.
