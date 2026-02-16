# Verification Round 2: End-to-End Integration Walkthrough

## Summary
- Scenarios tested: 10 (critical paths from the 48 total)
- Successful: 7
- Partial Success: 3
- Issues found: 14

## Methodology
For each scenario, I assumed the role of a new user with ONLY the documentation available. I walked through each step, verified that referenced docs exist and are findable, confirmed that the stated steps match actual source code behavior, and assessed whether the expected outcome is realistic.

---

## Scenario Walkthroughs

### Scenario 1: Installation (New User)

- **Steps followed**:
  1. Find README.md -- clearly states what the plugin does in "What It Does"
  2. Check Prerequisites section -- Python 3.8+ and pydantic v2 listed with install command
  3. Follow Installation section: `mkdir -p ~/.claude/plugins && cd ~/.claude/plugins && git clone ...`
  4. Install pydantic: `pip install 'pydantic>=2.0,<3.0'`
  5. Restart Claude Code
  6. Plugin detected via `.claude-plugin/plugin.json`

- **Docs referenced**: README.md sections: "Prerequisites", "Installation"

- **Result**: SUCCESS

- **Verification against source code**:
  - `plugin.json` exists at `.claude-plugin/plugin.json` with correct structure (commands, skills, hooks defined)
  - `hooks/hooks.json` is properly structured with all 4 hooks
  - The venv bootstrap in `memory_write.py:27-34` handles missing pydantic as documented

- **Issues**:
  1. **MINOR**: README says "Create this directory if it doesn't exist" but the command `cd ~/.claude/plugins` would fail if the dir doesn't exist. The `mkdir -p` is in a comment. A user might miss this. The two steps should be presented more clearly as separate commands.

- **User experience rating**: Good

---

### Scenario 2: First Memory Capture (Auto-Capture on Stop)

- **Steps followed**:
  1. Have a coding session discussing a decision (e.g., "decided to use Postgres because...")
  2. Press stop
  3. Triage hook fires with status message "Evaluating session for memories..."
  4. Hook reads transcript, applies keyword heuristics
  5. If DECISION score >= 0.4 threshold, hook blocks stop (exit 2) with stderr message
  6. SKILL.md orchestration spawns parallel subagents for drafting
  7. Verification subagent checks draft quality
  8. `memory_write.py --action create` saves the memory
  9. Stop flag set, next stop allowed through

- **Docs referenced**: README.md "Typical Workflow", "Four-Phase Auto-Capture", "Triage Signal" table; SKILL.md "Phase 0-3"

- **Result**: SUCCESS

- **Verification against source code**:
  - `hooks.json`: Stop hook runs `memory_triage.py` with timeout 30s and status message "Evaluating session for memories..." -- MATCHES docs
  - `memory_triage.py:843-920` (`main()`/`_run_triage()`): Reads transcript, loads config, checks stop flag, runs heuristic triage, exits 2 if results found -- MATCHES docs
  - `memory_triage.py:44-51`: Default thresholds match README exactly (DECISION=0.4, RUNBOOK=0.4, etc.)
  - `memory_triage.py:76-171`: Category patterns match documented triage signals (DECISION: "decided", "chose" + rationale co-occurrence)
  - `memory_triage.py:654-737`: Context files written to `/tmp/.memory-triage-context-<cat>.txt`, capped at 50KB -- MATCHES docs
  - Stop flag TTL is 300 seconds (5 minutes) at line 38 -- MATCHES README "auto-expires after 5 minutes"

- **Issues**:
  2. **MINOR**: The README "Typical Workflow" doesn't explain that the session needs to contain specific keywords to trigger capture. A new user whose session doesn't happen to use "decided", "chose", etc. will see nothing happen and wonder why. The Troubleshooting section covers this but a user might not look there first.

- **User experience rating**: Acceptable -- works but requires knowing the right keywords

---

### Scenario 3: Manual Save with /memory:save

- **Steps followed**:
  1. Type: `/memory:save decision "We chose Vitest over Jest for speed and ESM support"`
  2. Agent reads `memory-config.json` to validate category
  3. Agent generates kebab-case slug from content
  4. Agent structures content into decision schema (context, decision, alternatives, rationale, consequences)
  5. Agent writes JSON to `/tmp/.memory-write-pending.json`
  6. Agent calls: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action create --category decision --target .claude/memory/decisions/<slug>.json --input /tmp/.memory-write-pending.json`
  7. `memory_write.py` validates, writes atomically, updates index.md

- **Docs referenced**: `commands/memory-save.md`, SKILL.md "Memory JSON Format", README.md "Commands"

- **Result**: SUCCESS

- **Verification against source code**:
  - `memory-save.md` lists correct category-to-folder mapping, matches `CATEGORY_FOLDERS` in `memory_write.py:57-64`
  - `memory_write.py` `do_create()`: reads input from `/tmp/`, validates path in /tmp/ (line 1098-1099), runs auto_fix, validates with Pydantic, atomic write + index update -- all match docs
  - `memory_write.py:624-625`: Forces `record_status="active"` and strips archived/retired fields on CREATE -- documented in SKILL.md "Write Pipeline Protections" as a behavior but not explicitly stated in memory-save.md (acceptable since it's internal)
  - The 6 content models in `memory_write.py:90-165` match SKILL.md "Content by category" exactly

- **Issues**:
  3. **MINOR**: `memory-save.md` says "Ask the user for missing required fields (e.g., for a decision: what were the alternatives? why was this chosen?)" -- this is a good instruction but the agent might not always do this, since it's an LLM behavior instruction not a script enforcement. Not a doc bug per se, but sets expectations that may not always be met.
  4. **INFO**: The examples in `memory-save.md` show `"content"` as a positional arg but the YAML frontmatter defines it as a named argument. Both work due to Claude Code's slash command parsing.

- **User experience rating**: Good

---

### Scenario 4: Search with /memory:search

- **Steps followed**:
  1. Type: `/memory:search rate limit`
  2. Agent reads `.claude/memory/index.md`
  3. Agent matches entries using index-based scoring (tag=3, title=2, prefix=1, recency=+1)
  4. Results shown grouped by category with title, path, summary, date
  5. If no index matches, falls back to Glob+Grep on JSON files

- **Docs referenced**: `commands/memory-search.md`, README.md "Commands"

- **Result**: SUCCESS

- **Verification against source code**:
  - The scoring algorithm documented in `memory-search.md` (tag=3, title=2, prefix=1, recency bonus) exactly matches `memory_retrieve.py:90-117` (`score_entry()`) and `check_recency()` at line 120-153
  - `memory-search.md` says "Limit to 10 results maximum" -- this is an agent instruction, not script-enforced, but reasonable
  - `--include-retired` flag documented and instructions are clear: scan JSON files directly in folders
  - `memory-search.md` says "Index entries include `#tags:` suffix for tag-based scoring" -- verified by `_INDEX_RE` regex in `memory_retrieve.py:45-48`

- **Issues**:
  5. **MINOR**: `memory-search.md` says "Recency bonus: +1 for memories updated within 30 days" -- this matches `_RECENCY_DAYS = 30` in `memory_retrieve.py:57` and the recency check at line 280. However, this scoring is done by the **retrieval hook** (automatic), not by the agent running /memory:search. The search command is agent-interpreted (it reads index.md and JSON files using tools), so the scoring algorithm in the docs is aspirational guidance for the agent, not enforced by code. A subtle distinction but potentially confusing.

- **User experience rating**: Good

---

### Scenario 5: Browse with /memory (Status)

- **Steps followed**:
  1. Type: `/memory`
  2. Agent reads `memory-config.json`
  3. Agent scans `.claude/memory/` subdirectories
  4. Reports: status, per-category counts (active/retired/archived), index sync, storage total, health indicators
  5. Runs `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_index.py --validate --root <memory_root>` for sync check

- **Docs referenced**: `commands/memory.md`, README.md "Commands"

- **Result**: SUCCESS

- **Verification against source code**:
  - `memory.md` instructions are agent-interpreted (no script), but references `memory_index.py --validate` which exists and works as documented
  - `memory_index.py:119-163` (`validate_index()`): Compares index entries against actual active files -- matches docs
  - `memory_index.py:260-388` (`health_report()`): Reports category counts, heavily-updated (>5), recent retirements, sync status -- matches docs
  - If `.claude/memory/` doesn't exist, the command says "no memories captured yet" and suggests /memory:save -- documented in `memory.md`

- **Issues**: None

- **User experience rating**: Good

---

### Scenario 6: Config Change with /memory:config

- **Steps followed**:
  1. Type: `/memory:config set max_inject to 3`
  2. Agent reads `memory-config.json` (creates from defaults if missing)
  3. Agent modifies `retrieval.max_inject` to 3
  4. Agent writes updated config
  5. Confirms change

- **Docs referenced**: `commands/memory-config.md`, README.md "Configuration"

- **Result**: SUCCESS

- **Verification against source code**:
  - `memory-config.md` lists all supported operations -- verified against actual config keys read by scripts
  - Script-read keys: `triage.enabled` read at `memory_triage.py:514`, `triage.max_messages` clamped to [10,200] at line 520-522, `triage.thresholds.*` at lines 526-539, `triage.parallel.*` at line 542, `retrieval.enabled` at `memory_retrieve.py:217`, `retrieval.max_inject` clamped to [0,20] at line 221
  - `memory-config.md` says max_inject range is 0-20 -- matches `memory_retrieve.py:221` `max(0, min(20, int(raw_inject)))`
  - `memory-config.md` says triage.max_messages range is 10-200 -- matches `memory_triage.py:521` `max(10, min(200, val))`
  - Default config file (`assets/memory-config.default.json`) matches all documented defaults

- **Issues**:
  6. **MINOR**: `memory-config.md` says "Create from defaults at `$CLAUDE_PLUGIN_ROOT/assets/memory-config.default.json` if missing" -- but this is an agent instruction. The actual scripts don't create the config file; they just use defaults internally when the file is missing. So if a user runs `/memory:config` and no config file exists, the agent creates one from the defaults file. If a user tries to manually check config without running the command, there may be no file to read. This is correct behavior but could be clearer.
  7. **IMPORTANT**: `memory-config.md` says "Custom categories are not currently supported by the validation pipeline" -- this is documented at the bottom. Good. However, the README still says custom categories are possible in its commands table context. The user scenarios (Scenario 18) note this friction. The docs should be more explicit upfront that custom categories don't work with auto-capture.
  8. **MINOR**: `memory-config.md` lists `delete.archive_retired` setting, but the README Configuration table does NOT list this option, and it's marked as agent-interpreted in CLAUDE.md. The default is `true` in `memory-config.default.json`. Inconsistent documentation coverage.

- **User experience rating**: Good

---

### Scenario 7: Lifecycle (Retire, Archive, Restore)

- **Steps followed**:

  **Retire:**
  1. Type: `/memory --retire old-api-design`
  2. Agent scans category folders for `old-api-design.json`
  3. Agent shows title, asks confirmation
  4. Calls: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action delete --target <path> --reason "User-initiated retirement"`
  5. Memory gets `record_status="retired"`, `retired_at` set, removed from index

  **Archive:**
  1. Type: `/memory --archive legacy-notes`
  2. Agent finds file, confirms
  3. Calls: `memory_write.py --action archive --target <path> --reason "..."`
  4. Memory gets `record_status="archived"`, `archived_at` set, removed from index

  **Restore:**
  1. Type: `/memory --restore old-api-design`
  2. Agent finds file, checks it's retired
  3. Checks `retired_at` within 30-day grace period
  4. Modifies JSON (set active, remove retired fields, add change entry)
  5. Writes to `/tmp/.memory-write-pending.json`
  6. Calls: `memory_write.py --action update --category <cat> --target <path> --input <tmp> --hash <md5>`
  7. Rebuilds index

- **Docs referenced**: `commands/memory.md` (--retire, --archive, --restore, --unarchive sections), README.md "Memory Lifecycle"

- **Result**: PARTIAL SUCCESS

- **Verification against source code**:
  - `memory_write.py:872-944` (`do_delete()`): Sets `record_status="retired"`, `retired_at`, `retired_reason`, removes from index -- MATCHES docs
  - `memory_write.py:947-1018` (`do_archive()`): Sets `record_status="archived"`, `archived_at`, only allows archiving active memories -- MATCHES docs
  - `memory_write.py:1021-1084` (`do_unarchive()`): Sets active, clears archived fields, adds to index -- MATCHES docs
  - `memory_write.py:899-900`: Blocks archived -> retired (must unarchive first) -- documented in archive action
  - `memory_write.py:974-981`: Only active memories can be archived -- MATCHES docs

- **Issues**:
  9. **IMPORTANT**: The `--restore` flow in `memory.md` has the agent manually modify the JSON and call `memory_write.py --action update`. But `memory_write.py` `do_update()` enforces merge protections including: record_status is immutable via UPDATE (line 497-501). The --restore procedure sets `record_status` to `"active"` in the input JSON, but `do_update()` at line 751 forcibly preserves the old `record_status`. This means the documented restore flow **would fail**: the memory would remain "retired" after the update because `do_update()` preserves record_status from the old file.

     **Workaround**: The agent should either:
     (a) Use `--action unarchive` (but that's for archived, not retired memories), or
     (b) The code needs a dedicated `--action restore` for retired memories, or
     (c) The agent needs to edit the file directly (bypassing `memory_write.py`), which the write guard would block.

     **This is a functional gap**: There is no script-level `--action restore` in `memory_write.py`. The documented restore procedure in `memory.md` relies on `--action update` which will silently preserve the "retired" status, making the restore appear successful but not actually changing the record_status back to "active".

  10. **RELATED**: `memory_write.py` supports 5 actions: create, update, delete, archive, unarchive. There is NO `restore` action. The `--unarchive` action (line 1021) only works for `archived` memories, not `retired` ones. A `restore` action for retired memories is missing from the write pipeline.

  11. **MINOR**: `memory.md` --restore step 7 says to call `memory_write.py --action update` with `--hash <md5_of_original>` -- but if the agent reads the file and then writes a modified version to `/tmp/`, the hash it provides would be of the *original retired file*, which would match. However, the immutable record_status protection still prevents the status change from taking effect.

- **User experience rating**: Poor (for restore specifically; retire/archive work correctly)

---

### Scenario 8: Troubleshooting (Memory Not Captured)

- **Steps followed**:
  1. End session, see "Evaluating session for memories..." but nothing triggers
  2. Check Troubleshooting section in README
  3. README says:
     - Check `triage.enabled` is `true`
     - Sessions need enough signal -- use keywords like "decided", "chose", "error", "fixed by"
     - Lower triage threshold: `/memory:config set decision threshold to 0.3`
     - Use `/memory:save` as fallback
  4. Check config for `triage.enabled`
  5. Try `/memory:save` as manual fallback

- **Docs referenced**: README.md "Troubleshooting" section

- **Result**: SUCCESS

- **Verification against source code**:
  - `memory_triage.py:877`: `if not config["enabled"]: return 0` -- matches docs
  - `memory_triage.py:76-171`: Keyword patterns confirm the documented trigger words are accurate
  - The troubleshooting section is comprehensive and actionable

- **Issues**:
  12. **MINOR**: README Troubleshooting doesn't mention that the transcript must exist and be readable. `memory_triage.py:884-885` checks `if not transcript_path or not os.path.isfile(transcript_path): return 0`. If the transcript path is not provided in the hook input (which depends on Claude Code's behavior), triage silently does nothing. This is an edge case but worth noting.

- **User experience rating**: Good

---

### Scenario 9: Plugin Upgrade

- **Steps followed**:
  1. `cd ~/.claude/plugins/claude-memory && git pull`
  2. Restart Claude Code
  3. Verify: `python3 hooks/scripts/memory_index.py --validate --root .claude/memory`

- **Docs referenced**: README.md "Upgrading" section

- **Result**: SUCCESS

- **Verification against source code**:
  - The schemas use `schema_version: "1.0"` which is a Literal field in Pydantic models. If the schema version changes, old files would fail validation. The README says "backward-compatible schemas with lazy migration (new fields added on next update)" -- this is accurate for adding Optional fields but would break if Literal values change.
  - Memory files and config are stored per-project in `.claude/memory/` (not in the plugin dir), so `git pull` on the plugin won't touch them -- CORRECT

- **Issues**:
  13. **MINOR**: README "Upgrading" section doesn't mention checking for breaking changes in hooks.json or SKILL.md behavior. A major version upgrade (like v4 -> v5 which replaced 6 hooks with 1) could change behavior significantly. The upgrade section could mention checking release notes.

- **User experience rating**: Acceptable

---

### Scenario 10: Sensitive Data Accidentally Captured

- **Steps followed**:
  1. Discover sensitive data in a memory via `/memory:search`
  2. Immediately: `/memory --retire <slug>` -- removes from index, stops retrieval
  3. Permanently delete: wait for GC or run `/memory --gc`
  4. If committed to git: use `git filter-branch` or `git filter-repo`
  5. Prevention: disable auto-capture for sensitive categories, or add `.claude/memory/` to `.gitignore`

- **Docs referenced**: README.md "Sensitive Data" section

- **Result**: SUCCESS

- **Verification against source code**:
  - `do_delete()` in `memory_write.py`: Immediately removes from index.md (line 937) and sets `record_status="retired"` -- so retrieval stops immediately (retrieval hook skips retired entries at line 277)
  - `gc_retired()` in `memory_index.py:189-257`: Checks grace_period_days, permanently deletes files past the period -- MATCHES docs
  - The file still exists on disk after retirement (soft delete) -- the 30-day grace period applies. For urgent removal, user must manually delete the file.

- **Issues**:
  14. **MINOR**: The README "Sensitive Data" section says "run `/memory --gc`" but GC respects the grace period. For truly urgent removal, the user would need to manually `rm` the file and then `--rebuild` the index. The docs mention this implicitly ("or wait for the 30-day grace period") but don't explicitly say "for immediate permanent deletion, delete the file manually." Step 5 mentions this but step 2 could be clearer.

- **User experience rating**: Acceptable

---

## Cross-Cutting Issues

### Issue A: The `--restore` functional gap (Critical)
The `/memory --restore` flow documented in `memory.md` calls `memory_write.py --action update`, but `do_update()` enforces record_status immutability. This means restoring a retired memory to active status **does not work as documented**. The write pipeline has `archive`/`unarchive` actions but no `restore` action for retired memories.

**Impact**: Any user trying to restore a retired memory will get unexpected behavior -- the command appears to succeed (if the agent constructs the right JSON) but the memory remains retired because `do_update()` preserves the old record_status.

**Fix needed**: Add `--action restore` to `memory_write.py` that handles retired -> active transitions, or modify `do_update()` to allow record_status changes when explicitly requested.

### Issue B: Documentation discoverability
The docs are split across 7 files. The README is comprehensive but long. For a new user, the critical path is:
1. README (installation, overview) -- findable
2. Commands (slash commands) -- referenced from README but not linked
3. SKILL.md (auto-capture internals) -- not referenced from README for end users
4. CLAUDE.md (developer guide) -- clearly dev-only

The README covers most user-facing scenarios well. The commands files are properly discoverable through the plugin.json commands list.

### Issue C: Documentation-code consistency
Overall the documentation is remarkably consistent with the implementation. Specific numbers (thresholds, caps, timeouts) match between docs and code. The few discrepancies found are minor (custom categories, delete.archive_retired coverage).

---

## Overall Assessment

The documentation is **comprehensive and largely accurate**. The README covers installation, usage, configuration, troubleshooting, sensitive data handling, and upgrading -- all the critical user paths. The command files (`memory.md`, `memory-save.md`, `memory-search.md`, `memory-config.md`) provide clear agent instructions. The SKILL.md provides detailed orchestration guidance for the auto-capture pipeline.

**Strengths:**
- Prerequisites clearly stated with install commands
- Configuration table is complete with defaults and descriptions
- Troubleshooting section addresses the most common issues
- Source code consistently matches documented behavior
- Security considerations (sanitization, path validation, OCC) are well-documented in CLAUDE.md

**Weaknesses:**
- The `--restore` flow has a functional gap (documented procedure doesn't work due to merge protection)
- Some agent-interpreted behaviors (search scoring, manual JSON modifications) may not always execute as documented since they depend on LLM behavior, not script enforcement
- No explicit documentation of which config keys are script-enforced vs agent-interpreted (this is in CLAUDE.md but not user-facing docs)

## Remaining Issues

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | MINOR | README.md Installation | mkdir command could be clearer as a separate step |
| 2 | MINOR | README.md Workflow | New user may not know trigger keywords; no "getting started" scenario |
| 3 | MINOR | memory-save.md | Agent might not always ask for missing fields (LLM behavior) |
| 4 | INFO | memory-save.md | Content positional vs named arg -- both work, just inconsistent |
| 5 | MINOR | memory-search.md | Scoring algorithm documented as agent instruction, not script-enforced |
| 6 | MINOR | memory-config.md | Config file creation behavior could be clearer |
| 7 | IMPORTANT | README + memory-config.md | Custom categories limitations not prominent enough |
| 8 | MINOR | README.md Config table | Missing `delete.archive_retired` from table |
| 9 | **CRITICAL** | memory.md --restore | `--action update` preserves old record_status; restore doesn't work |
| 10 | **CRITICAL** | memory_write.py | No `--action restore` for retired->active transitions |
| 11 | MINOR | memory.md --restore | Hash/OCC check passes but status change silently fails |
| 12 | MINOR | README Troubleshooting | Doesn't mention transcript_path availability edge case |
| 13 | MINOR | README Upgrading | Should mention checking release notes for breaking changes |
| 14 | MINOR | README Sensitive Data | Immediate permanent deletion requires manual rm, not well-highlighted |

### Priority for fixes:
1. **P0**: Issues 9-10 (restore functional gap) -- either fix `memory_write.py` to add `--action restore` or update `memory.md` to use a different approach
2. **P1**: Issue 7 (custom categories) -- add explicit note in README about limitations
3. **P2**: Issues 1, 2, 8, 13, 14 -- minor doc improvements
4. **P3**: Issues 3, 4, 5, 6, 11, 12 -- informational, low impact
