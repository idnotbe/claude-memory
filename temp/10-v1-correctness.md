# Verification Round 1: Correctness Check

## Summary
- Claims verified: 87
- Correct: 84
- Issues found: 3

## Issues Found

### ISSUE-1: [HIGH] SKILL.md:83 -- `pre_action` field values are wrong
- **Claim**: SKILL.md Phase 1 subagent instructions (step 3) say: `pre_action` string: "CREATE", "NOOP", or "UPDATE_OR_DELETE". Step 4 then says: `If pre_action=UPDATE_OR_DELETE: Read the candidate file, then decide UPDATE or DELETE.`
- **Reality**: In `memory_candidate.py` (lines 278-283, 369-377), `pre_action` can only be `"CREATE"`, `"NOOP"`, or `null` (Python `None`). The value `"UPDATE_OR_DELETE"` belongs to the `structural_cud` field, not `pre_action`. The output JSON has both fields:
  ```json
  {
    "pre_action": "CREATE" | "NOOP" | null,
    "structural_cud": "CREATE" | "NOOP" | "UPDATE" | "UPDATE_OR_DELETE"
  }
  ```
- **Fix**: Change the subagent instructions to reference `structural_cud` instead of `pre_action` for the UPDATE_OR_DELETE case. Specifically:
  - Step 3: Change `pre_action` description to: `pre_action` string: "CREATE", "NOOP", or null. Also check `structural_cud` for "UPDATE", "UPDATE_OR_DELETE".
  - Step 4: Replace `If pre_action=UPDATE_OR_DELETE` with `If structural_cud=UPDATE or structural_cud=UPDATE_OR_DELETE`.
  - Also update step 3 bullet about `candidate`: "candidate object (present when structural_cud is UPDATE or UPDATE_OR_DELETE)."

### ISSUE-2: [LOW] README.md:288 -- "max 5" phrasing is slightly misleading
- **Claim**: README Auto-Retrieval section says "Outputs relevant entries (max 5) to stdout"
- **Reality**: The script outputs up to `max_inject` entries, which defaults to 5 but is configurable via `retrieval.max_inject` (0-20). The parenthetical "(max 5)" reads like a hard limit rather than a default.
- **Fix**: Change to "Outputs relevant entries (up to `max_inject`, default 5) to stdout" or simply "Outputs relevant entries to stdout, limited by `retrieval.max_inject`".

### ISSUE-3: [LOW] CLAUDE.md:259 -- `triage.parallel.category_models` default described as "haiku" but it varies
- **Claim**: CLAUDE.md Config section says `triage.parallel.category_models` default is "haiku"
- **Reality**: The defaults vary per category: session_summary=haiku, decision=sonnet, runbook=haiku, constraint=sonnet, tech_debt=haiku, preference=haiku. The parenthetical "(default: haiku)" is the `default_model` fallback, not the per-category defaults.
- **Fix**: Change to: `triage.parallel.category_models -- per-category model for drafting (see default config for per-category defaults)` or list all defaults inline.

## Verified Correct (sampling of key claims)

### README.md
- [OK] Version: v5.0.0 matches hooks.json description and plugin.json
- [OK] 6 memory categories with correct folder mappings match `CATEGORY_FOLDERS` in all scripts
- [OK] Prerequisites: Python 3.8+, pydantic v2 for write operations -- matches code imports and venv bootstrap
- [OK] Installation path: `~/.claude/plugins` with `git clone` -- standard plugin structure
- [OK] Storage structure diagram matches actual folder layout
- [OK] Index format: `- [CATEGORY] title -> path #tags:t1,t2` matches `_INDEX_RE` regex in memory_retrieve.py and memory_candidate.py
- [OK] JSON schema example has `record_status`, `changes`, `times_updated` -- matches Pydantic models in memory_write.py
- [OK] Lifecycle table (active/retired/archived) matches code in memory_write.py (do_delete, do_archive, do_unarchive)
- [OK] State transitions: active->retired via delete, active->archived via archive, etc. -- all match do_* handlers
- [OK] Grace period default 30 days -- matches `memory-config.default.json` and `memory_index.py:gc_retired` default
- [OK] Commands table: all 7 subcommands listed with correct descriptions
- [OK] Config table: all 15 settings with correct defaults verified against source
- [OK] `retrieval.max_inject` clamped 0-20 -- matches `max(0, min(20, int(raw_inject)))` at line 221
- [OK] `triage.max_messages` clamped 10-200 -- matches `max(10, min(200, val))` at line 521
- [OK] Triage thresholds defaults: decision=0.4, runbook=0.4, constraint=0.5, tech_debt=0.4, preference=0.4, session_summary=0.6 -- matches `DEFAULT_THRESHOLDS` dict
- [OK] Default category_models: session_summary=haiku, decision=sonnet, etc. -- matches `DEFAULT_PARALLEL_CONFIG`
- [OK] Data flow diagram: triage -> SKILL.md -> memory_candidate.py -> memory_write.py flow is accurate
- [OK] Phase 0-3 descriptions match SKILL.md and source code
- [OK] Phase 2 "content quality and deduplication" (not schema) -- matches SKILL.md Phase 2 instructions
- [OK] Stop flag at `.claude/.stop_hook_active` with 5-min TTL -- matches `FLAG_TTL_SECONDS = 300` and path in code
- [OK] Hook configuration table: all 4 hooks with correct triggers, scripts, timeouts match hooks.json
- [OK] "mkdir-based locking" -- matches `_flock_index` using `os.mkdir()` in memory_write.py
- [OK] OCC via MD5 hash check -- matches `file_md5()` and `args.hash` check in do_update
- [OK] Atomic writes: temp file + rename -- matches `atomic_write_json()` / `atomic_write_text()` using `tempfile.mkstemp()` + `os.rename()`
- [OK] Auto-rebuild when index missing -- matches code in both memory_retrieve.py and memory_candidate.py
- [OK] Troubleshooting: all 6 entries are accurate descriptions of actual behavior

### CLAUDE.md
- [OK] Architecture table: 4 hooks correctly described with types and behaviors
- [OK] Key Files table: 7 scripts with correct roles and dependencies
- [OK] `$CLAUDE_PLUGIN_ROOT` referenced in hooks.json -- confirmed
- [OK] Venv bootstrap: memory_write.py re-execs via `os.execv()` -- matches code at lines 27-34
- [OK] Config architecture: Script-read vs Agent-interpreted classification is accurate per impl-analysis
- [OK] Security item 1: Multi-layer sanitization chain -- confirmed in memory_write.py:auto_fix and memory_retrieve.py:_sanitize_title
- [OK] Security item 1: memory_index.py trusts write-side sanitization -- confirmed (rebuild_index uses title from JSON directly)
- [OK] Security item 2: max_inject clamped to [0, 20] with default 5 fallback -- confirmed
- [OK] Security item 3: Config read without integrity check -- confirmed (all scripts just `json.load()`)
- [OK] Security item 4: Index format fragility with ` -> ` and `#tags:` delimiters -- confirmed in parsing code
- [OK] Development workflow steps are reasonable and accurate
- [OK] Testing section: pytest, 6 test files, pydantic v2 for write tests -- accurate
- [OK] What needs tests: prioritized list matches actual script coverage needs

### SKILL.md
- [OK] Frontmatter: name, globs, triggers are reasonable
- [OK] Categories table: 6 categories with correct folders
- [OK] Phase 0: Parse `<triage_data>` JSON -- matches triage output format
- [OK] Phase 1: Parallel drafting with configured models -- matches design
- [OK] Phase 2: Content verification (not schema) -- correctly documented
- [OK] Phase 3: Save via memory_write.py -- correct CLI invocations
- [OK] CUD verification table: L1/L2 resolution matrix is correct and complete
- [OK] Anti-resurrection: 24-hour cooldown -- matches `age < 86400` in memory_write.py
- [OK] Merge protections: immutable fields, grow-only tags, append-only changes -- all match code
- [OK] FIFO overflow at 50 changes -- matches `CHANGES_CAP = 50`
- [OK] Tag cap of 12 -- matches `TAG_CAP = 12`
- [OK] OCC description -- matches implementation
- [OK] Session rolling window: max_retained default 5 -- matches config
- [OK] Memory JSON format: all category content schemas match Pydantic models
- [OK] record_status states and behaviors -- match implementation
- [OK] Context file format: `<transcript_data>` tags, +/- 10 lines, 50KB cap -- matches `CONTEXT_WINDOW_LINES = 10` and `MAX_CONTEXT_FILE_BYTES = 50_000`

### Command Files
- [OK] memory.md: All subcommands (--retire, --archive, --unarchive, --restore, --gc, --list-archived) have correct descriptions
- [OK] memory.md: --retire calls `memory_write.py --action delete` -- correct (delete = soft retire)
- [OK] memory.md: --restore modifies JSON manually then calls `memory_write.py --action update` -- reasonable flow
- [OK] memory-save.md: 6 categories listed (no "or custom") -- matches validation in memory_write.py
- [OK] memory-save.md: Category folder mapping table is correct
- [OK] memory-save.md: Calls `memory_write.py --action create` -- correct
- [OK] memory-search.md: Scoring algorithm matches memory_retrieve.py
- [OK] memory-search.md: `--include-retired` flag described -- consistent with command design
- [OK] memory-config.md: All supported operations list correct config keys with correct defaults
- [OK] memory-config.md: Threshold defaults match `DEFAULT_THRESHOLDS`
- [OK] memory-config.md: Note about custom categories not supported -- matches 6 hardcoded Pydantic models

### TEST-PLAN.md
- [OK] P0.1: Prompt injection tests -- references correct files, behavioral descriptions (no stale line numbers)
- [OK] P0.2: max_inject clamping -- correctly says clamped to [0, 20] with default 5
- [OK] P0.3: Config integrity -- correct test cases
- [OK] P1.1-P1.4: Core functional tests are well-described and match implementation
- [OK] P1.4: DELETE described as "soft retire" -- correct
- [OK] P1.5: Triage hook tests -- comprehensive and accurate
- [OK] P2.1: Write guard tests match memory_write_guard.py behaviors
- [OK] P2.2: Validate hook tests match memory_validate_hook.py behaviors
- [OK] P3.2: Command hook integration tests -- correctly reference exit codes 0/2, stop flag with 5-min TTL
- [OK] References section: points to CLAUDE.md (not stale ops/temp/ paths)

### hooks.json
- [OK] 4 hooks, all type "command", all using `$CLAUDE_PLUGIN_ROOT`
- [OK] Stop hook: matcher `*`, timeout 30s, runs memory_triage.py
- [OK] PreToolUse: matcher `Write`, timeout 5s, runs memory_write_guard.py
- [OK] PostToolUse: matcher `Write`, timeout 10s, runs memory_validate_hook.py
- [OK] UserPromptSubmit: matcher `*`, timeout 10s, runs memory_retrieve.py

### assets/memory-config.default.json
- [OK] All config keys present with documented defaults
- [OK] Structure matches documentation in README and CLAUDE.md
