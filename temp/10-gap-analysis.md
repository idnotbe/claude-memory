# Documentation Gap Analysis

## Summary Statistics
- Total gaps found: 42
- Critical: 5, High: 13, Medium: 16, Low: 8

---

## CRITICAL Gaps (wrong/misleading information)

### GAP-C1: CLAUDE.md claims max_inject is unclamped -- it IS clamped
- **Location**: CLAUDE.md, "Security Considerations" section, item 2
- **Issue**: States "memory_retrieve.py:65-76 reads max_inject from config without validation or clamping. Extreme values (negative, very large) cause unexpected behavior." This is **factually wrong**. The implementation at `memory_retrieve.py:221` does `max(0, min(20, int(raw_inject)))` -- clamped to [0, 20] with fallback to 5 on parse failure.
- **Correct info**: max_inject is clamped to [0, 20] at `memory_retrieve.py:221`. Invalid values fall back to default 5 with a stderr warning (`memory_retrieve.py:223-226`).
- **Fix**: Remove or correct item 2 in the Security Considerations section. If keeping as a "tests should verify" note, reword to "max_inject is clamped to [0, 20] -- tests should verify this clamping holds."

### GAP-C2: CLAUDE.md security line-number references are stale
- **Location**: CLAUDE.md, "Security Considerations" section, items 1-2
- **Issue**: References `memory_retrieve.py:141-145` for verbatim title injection and `memory_retrieve.py:65-76` for max_inject. The actual locations are:
  - Title sanitization: `memory_retrieve.py:156` (`_sanitize_title`) and output at `memory_retrieve.py:298`
  - max_inject reading: `memory_retrieve.py:210-229`
  - `memory_index.py:81` for "titles written unsanitized" -- actual unsanitized title write is at `memory_index.py:104`
- **Correct info**: See line numbers above.
- **Fix**: Either remove line-number references entirely (they always go stale) or update them and add a warning that they may drift. Recommend removing them and describing the behavior instead.

### GAP-C3: TEST-PLAN.md P3.2 references "6 Stop hook prompts" -- now 1 command hook
- **Location**: TEST-PLAN.md, section P3.2 "Hook Prompt Snapshot Tests", lines 146-148
- **Issue**: States "Each of the 6 Stop hook prompts produces expected JSON structure" and "stop_hook_active = true always produces `{\"ok\": true}`". Since v5.0.0, there is 1 command-type Stop hook (`memory_triage.py`), not 6 prompt-type hooks. The `stop_hook_active` mechanism still exists but works differently (flag file, not JSON input).
- **Correct info**: Single command-type Stop hook (`memory_triage.py`) reads stdin JSON with `transcript_path`, uses exit codes (0=allow, 2=block), and the stop flag is a file at `.claude/.stop_hook_active` with TTL-based expiry.
- **Fix**: Rewrite P3.2 entirely to test `memory_triage.py` as a command hook: stdin JSON parsing, exit codes, triage scoring, context file generation, stop flag file behavior.

### GAP-C4: MEMORY-CONSOLIDATION-PROPOSAL.md describes "6 parallel Sonnet hooks" -- stale architecture
- **Location**: MEMORY-CONSOLIDATION-PROPOSAL.md, Section 4.1 (line 94)
- **Issue**: States "6 parallel Sonnet hooks evaluate each Stop event" which was the pre-v5.0.0 architecture. The current architecture uses 1 deterministic command-type Stop hook.
- **Correct info**: Single `memory_triage.py` command hook with keyword heuristics replaced the 6 prompt hooks in v5.0.0.
- **Fix**: Add a prominent banner at the top of the proposal noting it is a historical design document and that the v5.0.0 architecture differs (1 command hook, deterministic triage). List specific sections that are superseded.

### GAP-C5: README JSON schema example is incomplete -- missing lifecycle fields
- **Location**: README.md, "JSON Schema" section, lines 67-87
- **Issue**: The example JSON shows only: schema_version, category, id, title, created_at, updated_at, tags, related_files, confidence, content. Missing fields that are part of the actual schema: `record_status`, `changes`, `times_updated`, `retired_at`, `retired_reason`, `archived_at`, `archived_reason`. These are core lifecycle fields added in ACE v4.0 and critical for understanding the plugin's behavior.
- **Correct info**: The full base schema includes all these fields (see SKILL.md "Memory JSON Format" section and `assets/schemas/base.schema.json`).
- **Fix**: Add `record_status: "active"`, `changes: []`, and `times_updated: 0` to the example. Add a note: "Additional lifecycle fields (retired_at, archived_at, etc.) are managed automatically."

---

## HIGH Gaps (missing essential information)

### GAP-H1: README omits /memory subcommands (--retire, --archive, --unarchive, --restore, --gc, --list-archived)
- **Location**: README.md, "Commands" table, lines 92-98
- **Issue**: The commands table shows `/memory` as "Show memory status and statistics" only. The actual command supports 7 subcommands: status (default), --retire, --archive, --unarchive, --restore, --gc, --list-archived. Users have no way to discover lifecycle management features from the README.
- **Correct info**: See `commands/memory.md` for full subcommand documentation.
- **Fix**: Expand the `/memory` row or add a "Memory Lifecycle" subsection after the commands table showing the subcommands with one-line descriptions.

### GAP-H2: README does not explain record_status lifecycle (active/retired/archived)
- **Location**: README.md -- entirely absent
- **Issue**: The concept of record_status (active/retired/archived) is fundamental to understanding how memories are managed. It affects retrieval (only active memories are indexed), garbage collection (only retired memories are GC'd), and archiving. This is documented in SKILL.md but absent from README.
- **Correct info**: See SKILL.md "record_status" table: active=indexed+retrievable, retired=excluded+GC-eligible after grace period, archived=excluded+preserved indefinitely.
- **Fix**: Add a "Memory Lifecycle" section to README between "JSON Schema" and "Commands" explaining active/retired/archived states and the state transitions.

### GAP-H3: README does not mention pydantic v2 as a dependency
- **Location**: README.md, "Requirements" line 239
- **Issue**: States only "Requirements: Python 3" but `memory_write.py` and `memory_validate_hook.py` require pydantic v2. Without pydantic, write operations fail (the venv bootstrap may handle this, but users need to know).
- **Correct info**: `memory_write.py` requires pydantic >= 2.0, < 3.0. The script attempts venv bootstrap (`os.execv` under `.venv/bin/python3`) but this only works if the venv exists with pydantic installed.
- **Fix**: Change "Requirements: Python 3" to "Requirements: Python 3, pydantic v2 (for write operations)" with installation instructions: `pip install pydantic>=2.0`.

### GAP-H4: Several config options are undocumented in all user-facing docs
- **Location**: README.md, SKILL.md -- missing from config tables
- **Issue**: The following config options exist in `memory-config.default.json` but are not explained in any user-facing documentation:
  - `triage.enabled` (bool, default: true) -- master on/off for triage. Not in README.
  - `triage.max_messages` (int, default: 50) -- transcript tail size. Not in README.
  - `triage.thresholds.*` (per-category floats) -- trigger sensitivity. Not in README.
  - `auto_commit` (bool, default: false) -- purpose unclear, not read by any script.
  - `retrieval.match_strategy` (string, default: "title_tags") -- referenced in `/memory:config` but no strategies documented.
  - `delete.archive_retired` (bool, default: true) -- in SKILL.md config list but not explained anywhere.
- **Correct info**: `triage.enabled`, `triage.max_messages`, and `triage.thresholds.*` are read by `memory_triage.py`. The others (`auto_commit`, `retrieval.match_strategy`, `delete.archive_retired`) are in the config but NOT read by any script.
- **Fix**: Add `triage.enabled`, `triage.max_messages`, and `triage.thresholds.*` to the README config table (these are actually used). For config keys not read by any script, either document them as "reserved for future use" or remove them from the default config.

### GAP-H5: /memory:config command covers only 4 of 20+ config options
- **Location**: `commands/memory-config.md`, lines 13-17
- **Issue**: Only documents: enabled, auto_capture, max_inject, match_strategy. Missing all triage config (triage.enabled, max_messages, thresholds, parallel.*), delete config (grace_period_days, archive_retired), max_memories_per_category, retention_days, max_retained.
- **Correct info**: Users can reasonably want to configure any of these via natural language.
- **Fix**: Expand the "Supported operations" list to include all config sections: triage settings, delete settings, per-category retention, and session limits. At minimum add: triage.enabled, triage.thresholds.*, delete.grace_period_days, categories.session_summary.max_retained.

### GAP-H6: No troubleshooting section anywhere
- **Location**: README.md -- absent; CLAUDE.md -- absent
- **Issue**: No documentation covers common problems: pydantic not installed, index out of sync, memory not being captured (threshold too high), retrieval not working (max_inject=0 or retrieval.enabled=false), write guard blocking legitimate writes, etc.
- **Correct info**: Common failure modes are well-understood from the implementation: fail-open behavior on errors, index auto-rebuild, venv bootstrap for pydantic.
- **Fix**: Add a "Troubleshooting" section to README covering at least: pydantic missing, index desync, memories not capturing, retrieval not injecting.

### GAP-H7: TEST-PLAN.md has no tests for memory_triage.py
- **Location**: TEST-PLAN.md -- all sections
- **Issue**: The triage script (`memory_triage.py`) is the most complex script (keyword scoring, transcript parsing, context file generation, stop flag, config reading) but has NO dedicated test section in the test plan. P3.2 references "6 Stop hook prompts" which is stale.
- **Correct info**: `memory_triage.py` handles: stdin JSON parsing, transcript JSONL reading, text preprocessing, 6-category keyword+co-occurrence scoring, activity metrics, stop flag TTL, context file generation, config reading with defaults, snippet sanitization.
- **Fix**: Add a new P1 section "P1.5: Triage Hook (memory_triage.py)" with test cases covering: keyword scoring, transcript parsing, stop flag behavior, context file generation, config reading, edge cases.

### GAP-H8: memory.md --gc fallback is stale
- **Location**: `commands/memory.md`, line 90
- **Issue**: States "If `--gc` is not yet supported by memory_index.py, perform manually" but `--gc` IS implemented in `memory_index.py` (verified at line 423). The fallback code is unnecessary and confusing.
- **Correct info**: `memory_index.py --gc` is fully implemented.
- **Fix**: Remove the "If `--gc` is not yet supported" fallback paragraph. Just call `memory_index.py --gc`.

### GAP-H9: custom category support is mentioned but undefined
- **Location**: `commands/memory-save.md` line 6 (argument description says "or custom"), `commands/memory-config.md` line 14 (Add custom category)
- **Issue**: Both command docs reference custom categories but: (1) `memory_write.py` validates against 6 hardcoded category choices, (2) no Pydantic model exists for custom categories, (3) no schema exists for custom content, (4) `memory_candidate.py` only accepts 6 choices. Custom categories would fail validation.
- **Correct info**: Custom categories are NOT supported by the implementation. `memory_write.py` CLI uses `choices` parameter limiting to 6 categories. Pydantic models are defined per-category with no extensibility.
- **Fix**: Remove "or custom" from memory-save.md argument description. In memory-config.md, remove or mark "Add custom category" as not currently supported. If custom categories are planned, note it as future work.

### GAP-H10: CLAUDE.md security item 1 is partially stale (titles ARE sanitized on write)
- **Location**: CLAUDE.md, "Security Considerations" section, item 1
- **Issue**: States "Titles are written unsanitized in memory_index.py:81 and memory_write.py." In reality, `memory_write.py` auto-fix DOES sanitize titles (strips control chars, replaces ` -> ` with ` - `, removes `#tags:` substring). However, `memory_index.py` rebuilds the index from whatever title is in the JSON file without re-sanitizing. The retrieval hook (`memory_retrieve.py:156`) also sanitizes on read as defense-in-depth.
- **Correct info**: Titles are sanitized at write time by `memory_write.py` auto-fix, and re-sanitized at retrieval time by `memory_retrieve.py`. The remaining gap is `memory_index.py` which writes titles from JSON without re-sanitizing (assuming write-side sanitization was applied).
- **Fix**: Update item 1 to reflect the current multi-layer sanitization: write-side (memory_write.py), retrieval-side (memory_retrieve.py), and note the remaining gap in memory_index.py (trusts write-side sanitization). Remove stale line numbers.

### GAP-H11: README does not document --health subcommand for memory_index.py
- **Location**: README.md, "Index Maintenance" section, lines 131-142
- **Issue**: Shows --rebuild, --validate, --query but omits --health and --gc. Both are implemented in `memory_index.py`.
- **Correct info**: `memory_index.py` supports 5 subcommands: --rebuild, --validate, --query, --health, --gc.
- **Fix**: Add --health and --gc to the "Index Maintenance" section with usage examples.

### GAP-H12: No version/changelog documentation
- **Location**: All docs
- **Issue**: plugin.json says version 5.0.0. MEMORY-CONSOLIDATION-PROPOSAL.md is labeled v4.2. No changelog explains the v4.2 -> v5.0.0 transition or what changed. The most recent commit message says "feat: replace 6 prompt Stop hooks with 1 command hook (v5.0.0)" but this is not in any documentation.
- **Correct info**: Key change was replacing 6 prompt-type Stop hooks with 1 command-type deterministic Stop hook.
- **Fix**: Either add a CHANGELOG.md or add a "Version History" section to README summarizing major changes (v5.0.0: single command hook replacing 6 prompt hooks).

### GAP-H13: SKILL.md Phase 2 verification says "schema compliance" check but implementation says content quality only
- **Location**: README.md, "Four-Phase Auto-Capture", Phase 2 description, line 197
- **Issue**: README says verification subagents check "schema compliance, content quality, and deduplication." SKILL.md explicitly says "Focus on content quality (schema validation is handled by memory_write.py in Phase 3)." The SKILL.md is the authoritative instruction; README contradicts it.
- **Correct info**: Phase 2 verification focuses on content quality (accuracy, hallucination, completeness, tags). Schema validation happens in Phase 3 via memory_write.py Pydantic models.
- **Fix**: Remove "schema compliance" from README Phase 2 description. Keep "content quality" and optionally "deduplication."

---

## MEDIUM Gaps (missing helpful information)

### GAP-M1: README lacks a "Prerequisites" section
- **Location**: README.md
- **Issue**: Prerequisites are scattered: Python 3 at bottom, pydantic in Testing section, pip install in Testing section. No consolidated prerequisites section near Installation.
- **Fix**: Add a "Prerequisites" section after "Installation" listing: Python 3.8+, pydantic v2 (for write operations), and optional pytest for testing.

### GAP-M2: No explanation of $CLAUDE_PLUGIN_ROOT
- **Location**: `commands/memory.md`, `commands/memory-save.md` -- used in CLI commands
- **Issue**: `$CLAUDE_PLUGIN_ROOT` is used in all command files for script paths but never defined. New developers or users reading command files won't know what this resolves to.
- **Fix**: Add a one-line note in CLAUDE.md Key Files section: "$CLAUDE_PLUGIN_ROOT is set by Claude Code to the plugin's installation directory."

### GAP-M3: memory-search.md scoring mentions "content matches at 1 point" not in implementation
- **Location**: `commands/memory-search.md`, line 34
- **Issue**: States scoring includes "content matches at 1 point." The actual `memory_retrieve.py` only scores against index.md entries (title words and tags). There is no content-level scoring in the retrieval hook. The search command instructs the agent to do a Glob+Grep fallback for full content search, which is an agent-level behavior, not a scoring algorithm.
- **Correct info**: Retrieval scoring is: exact title word = 2, exact tag = 3, prefix (4+ chars) = 1, recency bonus = 1. No content scoring exists in the Python implementation.
- **Fix**: Clarify that the scoring algorithm applies to index-based matches only. Content search via Glob+Grep is a fallback path without numeric scoring.

### GAP-M4: No documentation for config keys that are NOT read by any script
- **Location**: All docs
- **Issue**: Several config keys in `memory-config.default.json` are not read by ANY Python script: `memory_root`, `categories.*.enabled`, `categories.*.auto_capture`, `categories.*.retention_days`, `auto_commit`, `max_memories_per_category`, `retrieval.match_strategy`, `delete.archive_retired`. They exist only as hints for the LLM agent. This is not documented anywhere.
- **Fix**: Add a note in CLAUDE.md and/or the default config indicating which keys are "agent-interpreted" (read by LLM via SKILL.md instructions) vs "script-read" (parsed by Python scripts). This helps developers understand the architecture.

### GAP-M5: CLAUDE.md lacks development workflow guidance
- **Location**: CLAUDE.md
- **Issue**: Titled "Development Guide" but contains no guidance on: how to add a new category, how to modify a hook, how to test changes, how to update schemas, coding style conventions, PR process.
- **Fix**: Add a brief "Development Workflow" section covering: adding a new category (modify 5+ files), testing changes (pytest), modifying hooks (hooks.json format).

### GAP-M6: No documentation for the stop_hook_active flag file mechanism
- **Location**: README.md -- mentioned in data flow diagram but not explained; CLAUDE.md -- not mentioned
- **Issue**: The stop flag (`<cwd>/.claude/.stop_hook_active`) with 5-minute TTL prevents infinite loops during memory saving. This is mentioned in the README data flow diagram as "stop_hook_active flag" but never explained as a user-facing concept. If the flag file gets stuck, the triage hook silently allows stops.
- **Fix**: Add a brief explanation in the "Architecture" section of README: what the flag does, the 5-minute TTL, and that it auto-expires.

### GAP-M7: No documentation for the venv bootstrap mechanism
- **Location**: All docs -- not mentioned
- **Issue**: `memory_write.py` and `memory_validate_hook.py` use a venv bootstrap that re-execs under `.venv/bin/python3` if pydantic isn't importable. This is critical for understanding setup requirements but is not documented anywhere.
- **Fix**: Document in CLAUDE.md Key Files or a new "Setup" section: `memory_write.py` auto-detects a `.venv` directory and re-execs if pydantic is missing from the system Python.

### GAP-M8: No documentation for the anti-resurrection check
- **Location**: README.md -- absent; SKILL.md -- absent
- **Issue**: `memory_write.py` CREATE has an anti-resurrection check: if a file with the same path was retired less than 24 hours ago, CREATE is blocked. This prevents accidental re-creation of recently deleted memories. Not documented in any user-facing doc.
- **Fix**: Document in SKILL.md under "Rules" or "Phase 3": "A memory cannot be re-created within 24 hours of retirement (anti-resurrection check)."

### GAP-M9: merge protections for UPDATE are not documented in user-facing docs
- **Location**: README.md -- absent; SKILL.md mentions UPDATE but not merge rules
- **Issue**: `memory_write.py` UPDATE enforces complex merge protections: immutable fields (created_at, schema_version, category), grow-only tags (below cap), grow-only related_files (dangling removal allowed), append-only changes, minimum 1 new change required. None of this is in README or SKILL.md.
- **Fix**: Add a brief note in SKILL.md Phase 3 or as a "Merge Rules" subsection explaining key constraints: immutable fields, grow-only tags, append-only changes.

### GAP-M10: SKILL.md does not mention triage thresholds or scoring algorithm
- **Location**: SKILL.md -- Phase 0 section
- **Issue**: SKILL.md describes Phase 0 as "Parse triage output" but doesn't explain HOW categories are triggered. No mention of keyword heuristics, scoring weights, co-occurrence patterns, or configurable thresholds. Users tuning thresholds have no reference.
- **Fix**: Add a brief note after Phase 0: "Categories are triggered by keyword heuristic scoring (primary patterns + co-occurrence boosters). Thresholds are configurable via `triage.thresholds.*` in config."

### GAP-M11: SKILL.md CUD table is simplified vs proposal without explanation
- **Location**: SKILL.md, "CUD Verification Rules" table
- **Issue**: SKILL.md has 8 resolution rows with 2 layers (L1 Python, L2 Subagent). The proposal describes 3 layers (L1 Python, L2 Sonnet, L3 Opus) with 11 rows. The relationship is unclear -- is SKILL.md the simplified implementation or was the proposal never fully implemented?
- **Fix**: Add a note under the CUD table: "This is the implemented 2-layer system. See MEMORY-CONSOLIDATION-PROPOSAL.md for the original 3-layer design."

### GAP-M12: OCC (Optimistic Concurrency Control) not explained in README
- **Location**: README.md -- absent
- **Issue**: The `--hash` flag for UPDATE operations enables OCC to prevent lost updates. This is a significant feature for concurrent access but is only documented in SKILL.md CLI examples and the proposal.
- **Fix**: Mention briefly in README's "Architecture" section or "Shared Index" subsection: "Updates use optimistic concurrency control (MD5 hash check) to prevent lost writes."

### GAP-M13: TEST-PLAN.md P1.4 DELETE description is inaccurate
- **Location**: TEST-PLAN.md, P1.4 line 103
- **Issue**: States "DELETE: removes file + removes index entry." In reality, DELETE is a soft retire: sets record_status to "retired", does NOT delete the file. File deletion happens only via --gc after the grace period.
- **Correct info**: DELETE = soft retire (record_status -> "retired", removed from index, file preserved for grace period). Hard delete via --gc only.
- **Fix**: Reword to "DELETE (soft retire): sets record_status to retired, removes from index, preserves file for grace period."

### GAP-M14: Plugin manifest lacks dependency and compatibility information
- **Location**: `.claude-plugin/plugin.json`
- **Issue**: No dependencies listed (pydantic v2 required), no minimum Python version, no Claude Code compatibility version.
- **Fix**: If the manifest format supports it, add: dependencies (pydantic>=2.0), python requirement (>=3.8), Claude Code compatibility info.

### GAP-M15: No examples in any of the 4 command files
- **Location**: `commands/memory.md`, `commands/memory-save.md`, `commands/memory-search.md`, `commands/memory-config.md`
- **Issue**: All command files are procedural instructions with zero examples. Adding examples would help the agent (and developers reading the docs) understand expected usage and output.
- **Fix**: Add 1-2 examples per command file showing typical invocations and expected output.

### GAP-M16: Context file format not documented
- **Location**: SKILL.md, Phase 1
- **Issue**: Phase 1 instructions say "Read the context file" but the format of context files (`/tmp/.memory-triage-context-<cat>.txt`) is not specified. The files contain: Category header, Score, `<transcript_data>` block with key snippets. Subagents need to know this format.
- **Fix**: Add a brief note in SKILL.md Phase 1 describing the context file format: header with category/score, `<transcript_data>` tags wrapping transcript excerpts.

---

## LOW Gaps (nice to have)

### GAP-L1: No uninstallation instructions
- **Location**: README.md
- **Issue**: Installation is documented but not removal. Users may want to cleanly remove the plugin.
- **Fix**: Add a one-liner: "To uninstall, remove the `claude-memory` directory from your plugins folder."

### GAP-L2: No version number in README
- **Location**: README.md
- **Issue**: No version displayed. Plugin.json says 5.0.0 but README doesn't show it.
- **Fix**: Add version badge or text near the title.

### GAP-L3: CLAUDE.md references "v5.0.0" architecture implicitly but not explicitly
- **Location**: CLAUDE.md
- **Issue**: The architecture is described generically without version context. The transition from 6 prompt hooks to 1 command hook is significant context.
- **Fix**: Add a brief version note: "Architecture: v5.0.0 (1 command-type Stop hook replacing 6 prompt hooks)."

### GAP-L4: No contributor guidelines
- **Location**: All docs
- **Issue**: No CONTRIBUTING.md or contribution section in README/CLAUDE.md.
- **Fix**: Add brief contribution guidelines if accepting external contributions.

### GAP-L5: hooks.json not referenced from README
- **Location**: README.md
- **Issue**: README describes the hook architecture but never mentions `hooks/hooks.json` by name. Developers may not know where hook configuration lives.
- **Fix**: Add a mention in the Architecture section: "Hook configuration is in `hooks/hooks.json`."

### GAP-L6: No documentation for atomic write mechanism
- **Location**: README.md -- mentioned in passing in data flow diagram
- **Issue**: The tempfile+rename atomic write pattern is a key reliability feature but is only documented in the proposal.
- **Fix**: Optional -- add a one-line note in Architecture: "All writes use atomic temp-file + rename to prevent corruption."

### GAP-L7: TEST-PLAN.md references "originally in ops/temp/" for audit/security docs
- **Location**: TEST-PLAN.md, line 173-174
- **Issue**: References "originally in ops/temp/audit-claude-memory.md" and "ops/temp/v1-security-review.md" which likely don't exist in this repo.
- **Fix**: Update or remove the stale references.

### GAP-L8: No user workflow / day-to-day usage guide
- **Location**: README.md
- **Issue**: README explains architecture in depth but doesn't describe a typical user workflow: "Start coding -> memories auto-capture on stop -> next session retrieves relevant context -> use /memory:search to find specific memories -> use /memory --retire to clean up."
- **Fix**: Add a brief "Typical Workflow" section showing the user journey.

---

## Stale/Outdated References

| Document | Reference | Status | Detail |
|----------|-----------|--------|--------|
| CLAUDE.md | `memory_retrieve.py:141-145` | **Stale** | Title sanitization is at `:156`; output at `:298` |
| CLAUDE.md | `memory_retrieve.py:65-76` | **Stale** | max_inject reading is at `:210-229` |
| CLAUDE.md | `memory_index.py:81` | **Stale** | Title write is at `:104` |
| CLAUDE.md | "unclamped max_inject" | **Factually wrong** | max_inject IS clamped to [0,20] at `:221` |
| TEST-PLAN.md | "6 Stop hook prompts" (P3.2) | **Stale** | Now 1 command-type Stop hook |
| TEST-PLAN.md | "stop_hook_active = true" (P3.2) | **Stale** | Flag mechanism changed (file-based, not JSON input) |
| TEST-PLAN.md | "ops/temp/" references | **Stale** | Files likely don't exist in current repo |
| TEST-PLAN.md | P1.4 "DELETE: removes file" | **Inaccurate** | DELETE is soft retire; file preserved |
| PROPOSAL.md | "6 parallel Sonnet hooks" (line 94) | **Stale** | Superseded by v5.0.0 architecture |
| memory.md | "--gc not yet supported" fallback | **Stale** | --gc IS implemented in memory_index.py |

## Documentation That Doesn't Match Implementation

| Doc Claim | Implementation Reality | Severity |
|-----------|----------------------|----------|
| CLAUDE.md: max_inject is unclamped | Clamped to [0,20] with fallback to 5 | CRITICAL |
| README: Phase 2 checks "schema compliance" | Phase 2 = content quality only; schema = Phase 3 | HIGH |
| memory-search.md: "content matches at 1 point" scoring | No content-level scoring in retrieval code | MEDIUM |
| memory-save.md: category arg accepts "or custom" | memory_write.py rejects non-standard categories | HIGH |
| memory-config.md: "Add custom category" | No custom category support in validation | HIGH |
| memory.md: --gc "not yet supported" fallback | --gc is fully implemented | MEDIUM |
| TEST-PLAN.md P1.4: "DELETE removes file" | DELETE = soft retire, file preserved | MEDIUM |
| TEST-PLAN.md P3.2: "6 Stop hook prompts" | 1 command-type Stop hook since v5.0.0 | CRITICAL |
| PROPOSAL.md: 3-layer CUD verification | 2-layer CUD in SKILL.md implementation | MEDIUM |

---

## Priority Fix Order (recommended for doc-writer)

1. **CRITICAL fixes first**: GAP-C1 through GAP-C5 (wrong information that could mislead users/developers)
2. **HIGH fixes next**: GAP-H1 through GAP-H13 (essential information that's missing)
3. **Stale reference cleanup**: Update or remove all entries in the Stale/Outdated References table
4. **MEDIUM improvements**: GAP-M1 through GAP-M16 (helpful information that improves usability)
5. **LOW polish**: GAP-L1 through GAP-L8 (nice-to-have improvements)
