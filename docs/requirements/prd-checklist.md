# PRD Compliance Checklist (v6.0.0)

Generated: 2026-03-24 | Source: docs/requirements/prd.md

**How to use:** Mark `[ ]` -> `[v]` when implementation satisfies the requirement. `[INFO]` items are design context, not scored. To report results, list failing section+item numbers (e.g., "FAIL: 3.1.1 item 5, 3.3.2 item 3").

Glossary: CUD=Create/Update/Delete, OCC=Optimistic Concurrency Control, FTS5=Full-Text Search v5 (SQLite), BM25=Best Matching 25, TOCTOU=Time-of-check-to-time-of-use, ACE=Analyze-Candidate-Execute, L1=Python structural CUD decision, L2=LLM subagent intent

---

## 0. Integration Checks

- [ ] Auto-capture round-trip: triage triggers -> drafters write intent-*.json -> `memory_orchestrate.py` saves to .claude/memory/ -> next-session retrieval hook outputs `<memory-note>` confirming save
- [ ] Data integrity invariant: every active JSON file in category folders has exactly one corresponding entry in index.md (bijection; verify with `memory_index.py --validate`)

---

## 1. Product Vision

### 1.1 What is claude-memory?
- [ ] Plugin provides persistent knowledge management across Claude Code sessions
- [ ] Stores data as schema-validated JSON files on local filesystem
- [ ] Covers 6 categories: decisions, runbooks, constraints, tech debt, session summaries, preferences
- [ ] Auto-captures and auto-retrieves project-specific knowledge

### 1.2 Problem Statement
- [ ] Addresses ephemeral session context loss (decisions, workarounds, accomplishments, preferences, tech debt, procedures)

### 1.3 Design Philosophy

> **INFO — Design context, not scored:**
> - Zero-friction: auto-capture on session end, auto-inject on prompt, no manual effort required
> - Silent operation: silent during normal workflow (retrieval injects silently); Stop hook outputs blocking message only when save triggered; next session shows brief confirmation
> - Safety-first: all writes go through schema validation; mechanical rules prevent data corruption
> - Fail-open: every hook silently fails rather than blocking user workflow
> - Defense-in-depth: multiple overlapping security layers (guards, validation, sanitization, containment checks)

### 1.4 Design Consistency

> **INFO — Design context, not scored:**
> Similar problems should be solved with similar solutions. Deviations from established patterns must be intentional, documented, and justified by a technical constraint — not accidental drift. When staging and final writes, or similar-purpose scripts, use different approaches, the difference should exist because the standard approach would fail in that context.

**Error handling boundary:**
- [ ] All 5 hook scripts fail-open: unexpected exceptions caught; PreToolUse hooks allow the operation through, PostToolUse hooks silently skip validation
- [ ] CLI/CRUD scripts (memory_write, memory_draft, memory_enforce, memory_candidate) fail-closed: validation failures produce non-zero exit + error message
- [ ] `memory_orchestrate.py` uses documented hybrid: fail-closed for structural errors, fail-open for individual category failures

**Data flow contracts:**
- [ ] Hook scripts: input via stdin JSON, structured output via stdout (JSON or XML); CLI tools: input via argparse + file paths, output via stdout; diagnostics to stderr in both categories

**Staging-storage symmetry:**
- [ ] Both staging and persistent writes use write-new-then-swap pattern (never modify a file in place); underlying mechanism varies (os.rename, os.replace, O_EXCL+fd-pin) but all guarantee atomicity
- [ ] Both staging and persistent paths apply symlink defense (O_NOFOLLOW)
- [ ] Path containment applied in both: `resolve().relative_to()` for persistent writes, fd-pinned `dir_fd` verification for staging writes

**Security at system boundaries:**
- [ ] Input sanitization (control chars, Unicode attack chars, index-injection markers) applied at write path, retrieval output, and search output (see 4.3 for full spec)

**Lifecycle structure:**
- [ ] All 4 lifecycle operations (retire, archive, unarchive, restore) follow the same structural progression: resolve path → read → verify state → set fields → append change → lock → atomic write → update index

**Documented divergences:**
- [ ] Each intentional divergence from a consistency axis includes an inline source comment explaining why the standard approach does not apply
- [ ] Cross-script divergences documented in source or CLAUDE.md: tokenizer thresholds (candidate 3+ chars vs search 2+ chars), pydantic bootstrap (os.execv vs lazy injection), stdin reading (json.load vs select.select)

> **INFO — Naming conventions (not scored, verifiable by inspection):**
> - Files: `memory_<purpose>.py`; functions: `snake_case`/`_snake_case`; constants: `UPPER_SNAKE_CASE`; config keys: `snake_case`; log events: `subsystem.action`

---

## 2. User Stories and Use Cases

### 2.1 Automatic Behavior
- [ ] US-1: Stop hook evaluates transcript on session end; blocks stop to save if meaningful knowledge found; user sees minimal output
- [ ] US-2: UserPromptSubmit hook searches memory index and injects relevant entries into context on every prompt; user never explicitly asks for memories
- [ ] US-3: Next-session retrieval hook displays `<memory-note>` confirming what was saved (categories and titles)
- [ ] US-4: Orphan detection -- retrieval hook detects stale `triage-data.json` without save result; notifies user; suggests `/memory:save`
- [ ] US-5: Session rolling window -- session_summary auto-capped at N most recent (default 5); oldest retired automatically via `memory_enforce.py`

### 2.2 Manual / Slash Command Behavior
- [ ] US-6: `/memory:save` -- manually save memory to specific category with natural language content
- [ ] US-7: `/memory` -- view status: counts per category, health indicators, index sync status
- [ ] US-8: `/memory --retire|--archive|--restore|--gc` -- lifecycle management
- [ ] US-9: `/memory:config` -- modify settings with natural language
- [ ] US-10: `/memory:search` -- explicit full-text search using FTS5
- [ ] US-11: Recall via conversational prompts ("What do you remember about X?") -- Claude reads/searches to answer

---

## 3. Functional Requirements

### 3.1 Auto-Capture (Stop Hook Triage -> Save Flow)

#### 3.1.1 Triage Hook (`memory_triage.py`)

**Hook basics:**
- [ ] Hook type is Stop (command type), fires on every session stop
- [ ] Receives hook JSON via stdin containing `transcript_path` and `cwd`

**Transcript processing:**
- [ ] Reads JSONL transcript file, last N messages (configurable via `triage.max_messages`, default 50)
- [ ] Strips fenced code blocks and inline code from text to reduce false positives
- [ ] Extracts activity metrics: tool_uses, distinct_tools, exchanges (for session_summary scoring)

**Scoring:**
- [ ] Scores all 6 categories using keyword heuristic patterns
- [ ] Text categories (DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE): primary regex patterns + co-occurrence boosters within sliding window of 4 lines
- [ ] SESSION_SUMMARY: activity-based formula: `tool_uses*0.05 + distinct_tools*0.1 + exchanges*0.02`
- [ ] Scoring formula for text categories: `raw_score = (primary_matches * primary_weight) + (boosted_matches * boosted_weight)`, `normalized = min(1.0, raw_score / denominator)`
- [ ] primary_weight range ~0.2-0.35, boosted_weight range ~0.5-0.6, caps on both match types

**Category thresholds and patterns:**

| Category | Threshold | Primary Patterns | Boosters |
|----------|-----------|-----------------|----------|
- [ ] DECISION threshold = 0.4; primaries: decided, chose, selected, went with, let's go with, opting for, switching to (with negative lookbehind for negation); boosters: because, due to, reason, rationale, over, instead of, rather than
- [ ] RUNBOOK threshold = 0.4; primaries: error, exception, traceback, failed, failure, crash; boosters: fixed by, resolved, root cause, solution, workaround
- [ ] CONSTRAINT threshold = 0.45; primaries: limitation, api limit, restricted, not supported, quota, rate limit, hard limit; boosters: discovered, found that, turns out, permanently, cannot, by design, deprecated
- [ ] TECH_DEBT threshold = 0.4; primaries: TODO, deferred, tech debt, workaround, hack, will address later; boosters: because, for now, temporary, acknowledged, deferring
- [ ] PREFERENCE threshold = 0.4; primaries: always use, prefer, convention, from now on, standard, never use, default to, stick with; boosters: agreed, going forward, consistently, rule, practice, workflow
- [ ] SESSION_SUMMARY threshold = 0.6

**Threshold comparison and trigger gate:**
- [ ] Compares scores against configurable thresholds (default range 0.4-0.6)
- [ ] If any category exceeds its threshold, triggers output (sets stop flag, writes sentinel, writes context files, writes triage-data.json)

**Output on trigger:**
- [ ] Sets stop flag (`.claude/.stop_hook_active`) to prevent re-fire loops
- [ ] Writes sentinel JSON (`<staging_dir>/.triage-handled`) -- state machine with `{session_id, state, timestamp, pid}`
- [ ] Sentinel states: `pending`->`saving`->`saved`|`failed`; states `pending`/`saving`/`saved` block re-triage (same session, within TTL 1800s); `failed` allows re-triage
- [ ] Writes per-category context files (`<staging_dir>/context-<cat>.txt`) with transcript excerpts
- [ ] Writes `triage-data.json` to `<staging_dir>/` via atomic write (tmp+`os.replace()`)
- [ ] Outputs `{"decision": "block", "reason": "..."}` to stdout with human-readable message + structured data reference

**Re-fire prevention (5 layers):**
- [ ] Layer 1: `check_stop_flag()` -- file-based flag (`.claude/.stop_hook_active`) with 5-minute TTL; fresh flag = exit immediately
- [ ] Layer 2: JSON sentinel -- `<staging_dir>/.triage-handled` -- session-scoped state machine; blocks re-triage when state `pending`/`saving`/`saved` for same session within TTL 1800s; `failed` allows retry
- [ ] Layer 3: `_check_save_result_guard()` -- `last-save-result.json` exists and recent (same session) = skip
- [ ] Layer 4: `_acquire_triage_lock()` -- `O_CREAT|O_EXCL` exclusive lock on `.stop_hook_lock` with 120s stale timeout
- [ ] Layer 5: `sentinel_recheck` -- under triage lock, re-checks sentinel (double-check pattern prevents race between lock acquisition and sentinel write)

**Informational metric:**
- [ ] `_increment_fire_count()` tracks per-workspace fire count (`.triage-fire-count`), included in all triage log events; does NOT block

#### 3.1.2 Three-Phase Save Orchestration (SKILL.md v6)

**Pre-Phase:**
- [ ] On manual `/memory:save` (no triage data), clean stale staging files before proceeding

**SETUP (deterministic):**
- [ ] Clean stale intent files
- [ ] Extract `triage-data.json` path from `<triage_data_file>` tag (fallback: inline `<triage_data>` JSON)
- [ ] Read config for parallel processing settings and `architecture.simplified_flow` flag

**Phase 1: DRAFT (LLM, per-category Agent subagents):**
- [ ] For each triggered category, spawn Agent subagent using `memory-drafter` agent file
- [ ] Agent has `tools: Read, Write` only (no Bash) -- structurally prevents Guardian conflicts
- [ ] Agent reads context file and writes intent JSON (SAVE or NOOP)
- [ ] All category subagents spawn in PARALLEL
- [ ] Model selection per-category (configurable via `triage.parallel.category_models`)
- [ ] M1 fallback: if ALL drafters fail, write `.triage-pending.json` for retrieval hook detection

**Intent JSON formats:**
- [ ] SAVE intent: `{ category, new_info_summary, intended_action?, lifecycle_hints?, partial_content: { title, tags, confidence, related_files?, change_summary, content } }`
- [ ] NOOP intent: `{ category, action: "noop", noop_reason }`

**Phase 1.5: VERIFY (optional, disabled by default):**
- [ ] Enabled via `triage.parallel.verification_enabled: true`
- [ ] Orchestrator runs `--action prepare` (steps 1-6: collect, candidate, CUD, draft, manifest)
- [ ] Risk-eligible categories (decision/constraint, DELETE actions, low-confidence) are verified by inspection subagents
- [ ] Verifiers inspect assembled draft JSON for accuracy and hallucination
- [ ] `BLOCK` verdicts exclude categories from subsequent `--action commit` call

**Phase 2: COMMIT (deterministic, single Python subprocess):**
- [ ] Single call: `python3 memory_orchestrate.py --staging-dir <dir> --action run --memory-root <root>`
- [ ] Emits `save.start` and `save.complete` logging events (via `memory_logger.py`)
- [ ] Step 1: Collect intents, candidate selection (with OCC hash capture), CUD resolution
- [ ] Step 2: Draft assembly via `memory_draft.py`, target path generation for CREATEs
- [ ] Step 3: Save execution via `memory_write.py` (with `--skip-auto-enforce`)
- [ ] Step 4: Enforcement (`memory_enforce.py`) for session_summary creates
- [ ] Step 5: Result file writing (`last-save-result.json`) with `phase_timing` dict (`triage_ms`, `orchestrate_ms`, `write_ms`, `total_ms`)
- [ ] Step 6: Staging cleanup on success; `.triage-pending.json` + sentinel update on failure

#### 3.1.3 CUD Verification Rules Table (8 rows)

*(L1 = Python structural CUD from `memory_candidate.py`, L2 = LLM subagent intent from intent JSON)*

- [ ] L1=CREATE + L2=CREATE -> CREATE
- [ ] L1=UPDATE_OR_DELETE + L2=UPDATE -> UPDATE
- [ ] L1=UPDATE_OR_DELETE + L2=DELETE -> DELETE
- [ ] L1=CREATE + L2=UPDATE -> CREATE (no candidate exists)
- [ ] L1=CREATE + L2=DELETE -> NOOP (cannot delete without candidate)
- [ ] L1=UPDATE_OR_DELETE + L2=CREATE -> CREATE (subagent override)
- [ ] L1=VETO + L2=* -> OBEY VETO (mechanical invariant)
- [ ] L1=NOOP + L2=* -> NOOP

### 3.2 Memory Retrieval (UserPromptSubmit Hook)

#### 3.2.1 Retrieval Hook (`memory_retrieve.py`)

**Hook type:** UserPromptSubmit, fires on every user prompt.

**Block 1 -- Save confirmation:**
- [ ] Checks `last-save-result.json` in `<staging_dir>` (via `get_staging_dir()` with legacy `.staging/` fallback)
- [ ] If recent (<24h), displays what was saved, then deletes the file

**Block 2 -- Orphan detection:**
- [ ] Checks for stale `triage-data.json` in `<staging_dir>` (with legacy fallback) without save result
- [ ] Notifies user if orphaned data found

**Block 3 -- Pending notification:**
- [ ] Checks for `.triage-pending.json` in `<staging_dir>` (with legacy fallback)
- [ ] Notifies user of pending saves from last session

**Search pipeline:**
- [ ] Short prompt skip: prompts < 10 characters skipped (greetings, acks)
- [ ] Index rebuild on demand: if `index.md` missing but memory root exists, auto-rebuilds
- [ ] FTS5 BM25 search: tokenizes user prompt, constructs FTS5 query, searches title+tags index
- [ ] Hybrid body scoring: for top-K candidates, reads JSON files, extracts body text, adds body bonus (0-3 points)
- [ ] Description scoring (`score_description()`): adds up to 2 bonus points for entries matching category description keywords; applied only to already-matched entries
- [ ] Recency check: reads JSON for top candidates, checks `updated_at` (30-day recency window) and `record_status` (filters retired/archived)
- [ ] Threshold + Top-K: filters entries with abs(BM25 score) < 25% of absolute best score, limits to max_inject (default 3, configurable 0-20)
- [ ] Confidence labeling: labels results as high/medium/low based on ratio to best score, with optional absolute floor
- [ ] Output: prints XML elements (`<memory-context>` wrapper with `<result>` elements) to stdout

**Optional LLM Judge (`memory_judge.py`):**
- [ ] Enabled via config + `ANTHROPIC_API_KEY` env var
- [ ] Uses Anthropic Messages API (haiku model)
- [ ] Judge determines which memories are "DIRECTLY RELEVANT and would ACTIVELY HELP"
- [ ] Anti-position-bias: deterministic shuffling of candidate order
- [ ] Anti-injection: untrusted data wrapped in `<memory_data>` XML tags
- [ ] Parallel batch splitting via ThreadPoolExecutor when candidates > 6
- [ ] Falls back to unfiltered results on any failure
- [ ] `retrieval.judge.dual_verification`: config key retained for schema compat; feature cancelled, not implemented

**Output modes:**
- [ ] `legacy` (default): all results as `<result>` elements
- [ ] `tiered`: HIGH=`<result>`, MEDIUM=`<memory-compact>`, LOW=silence; search hints for all-low or medium-only sets

#### 3.2.2 Search Engine (`memory_search_engine.py`)
- [ ] Shared FTS5 engine used by both retrieval hook and CLI search skill
- [ ] `tokenize()`: extracts lowercase tokens, filters stop words, supports legacy (simple) and compound-preserving (FTS5) modes
- [ ] `parse_index_line()`: parses enriched index format `- [CAT] title -> path #tags:t1,t2,...`
- [ ] `build_fts_index()`: creates in-memory SQLite FTS5 virtual table
- [ ] `build_fts_query()`: constructs MATCH queries with smart wildcards (compounds=exact, singles=prefix)
- [ ] `query_fts()`: executes MATCH query, returns BM25-ranked results
- [ ] `apply_threshold()`: filters entries with abs(BM25 score) < 25% of absolute best score, category priority sorting, Top-K limiting
- [ ] `extract_body_text()`: extracts searchable text from category-specific content fields (capped at 2000 chars)
- [ ] CLI modes: `auto` (title+tags, top-3) and `search` (full-body, top-10); outputs JSON or text

### 3.3 Memory CRUD Operations

#### 3.3.1 CREATE (`memory_write.py --action create`)
- [ ] Reads input JSON from staging file
- [ ] Applies auto-fix rules: schema_version, timestamps, id slugification, tag dedup/sort, title sanitization, confidence clamping
- [ ] Forces `record_status="active"` (prevents injection of retired/archived status)
- [ ] Validates against category-specific Pydantic model
- [ ] Path traversal check + directory component validation (S5F defense)
- [ ] Anti-resurrection check: blocks re-creation within 24 hours of retirement at same path
- [ ] Atomic write via tmp+`os.replace()` under FlockIndex lock
- [ ] Adds entry to `index.md`
- [ ] For session_summary: auto-triggers `memory_enforce.py` for rolling window UNLESS `--skip-auto-enforce` (orchestrator runs enforce separately in Phase 2 Step 4)

#### 3.3.2 UPDATE (`memory_write.py --action update`)
- [ ] Reads existing file and new input
- [ ] Preserves immutable fields: created_at, schema_version, category, id, record_status
- [ ] Validates against Pydantic model
- [ ] Tags: grow-only below 12-tag cap; eviction only when adding new tags at cap
- [ ] related_files: grow-only, except dangling paths can be removed
- [ ] changes[]: append-only, minimum 1 new entry per update, FIFO overflow at 50
- [ ] OCC hash check (MD5 of current file vs expected hash) inside FlockIndex
- [ ] Slug rename on >50% title word difference
- [ ] Atomic write via tmp+`os.replace()` + index update

#### 3.3.3 RETIRE (`memory_write.py --action retire`)
- [ ] Reads existing file
- [ ] Soft delete with grace period
- [ ] Sets `record_status="retired"`, `retired_at`, `retired_reason`
- [ ] Appends change entry
- [ ] Atomic write
- [ ] Removes entry from `index.md`
- [ ] Idempotent: already-retired returns success
- [ ] Blocks archived -> retired transition (must unarchive first)

#### 3.3.4 ARCHIVE (`memory_write.py --action archive`)
- [ ] Only active memories can be archived
- [ ] Sets `record_status="archived"`, `archived_at`, `archived_reason`
- [ ] Clears retired fields
- [ ] Removes from index
- [ ] NOT GC-eligible (preserved indefinitely)

#### 3.3.5 UNARCHIVE (`memory_write.py --action unarchive`)
- [ ] Reads file, verifies `record_status="archived"`
- [ ] Sets `record_status="active"`, clears archived fields
- [ ] Re-adds to index

#### 3.3.6 RESTORE (`memory_write.py --action restore`)
- [ ] Reads file, verifies `record_status="retired"`
- [ ] Sets `record_status="active"`, clears retired fields
- [ ] Re-adds to index

#### 3.3.7 Staging Utilities
- [ ] `cleanup-staging`: removes transient files (triage-data, context-*, draft-*, intent-*, etc.) with path containment check
- [ ] `write-save-result`: writes `last-save-result.json` with schema validation (allowed keys, length caps)
- [ ] `cleanup-intents`: removes stale `intent-*.json` from staging (called during SETUP Step 2)
- [ ] `update-sentinel-state`: updates sentinel JSON state machine to given state (called by `memory_orchestrate.py`)
- [ ] `--result-file <path>` flag: writes save result to a file (replaces `write-save-result-direct` for shell injection safety)
- [ ] `--skip-auto-enforce` flag: prevents auto-triggering enforce after `session_summary` create (used by orchestrator)
- [ ] C1 overwrite guard: `do_create()` rejects CREATE if active file exists at target path (applies to CREATE in 3.3.1)
- [ ] C2 index dedup: `add_to_index()` deduplicates by path before appending (applies to CREATE in 3.3.1)

### 3.4 Guard Rails

#### 3.4.1 Write Guard (`memory_write_guard.py`)
- [ ] Hook type: PreToolUse:Write
- [ ] Blocks Write tool calls targeting files inside `.claude/memory/`
- [ ] Auto-approves staging directory writes (both XDG `<staging_dir>` and legacy `.staging/`) via `is_staging_path()`
- [ ] Gate 1: Extension whitelist -- .json and .txt only
- [ ] Gate 2: Filename pattern whitelist -- intent-*, input-*, draft-*, context-*, etc.
- [ ] Gate 3: Hard link defense -- checks `st_nlink` for existing files; nlink > 1 = require user approval
- [ ] Gate 4: New file pass-through
- [ ] Exempts `memory-config.json` if directly in memory root (not subfolder)
- [ ] Exempts `/tmp/.memory-write-pending*.json`, `/tmp/.memory-draft-*.json`, `/tmp/.memory-triage-context-*.txt`
- [ ] Returns `{"permissionDecision": "deny"}` for blocked writes with guidance to use `memory_write.py`

#### 3.4.2 Staging Guard (`memory_staging_guard.py`)
- [ ] Hook type: PreToolUse:Bash
- [ ] Blocks Bash commands that write to staging directories (both `<staging_dir>` and legacy `.claude/memory/.staging/`) via dynamic regex from `memory_staging_utils`
- [ ] Blocked commands: heredoc, cat, echo, printf, tee, cp, mv, redirect, ln
- [ ] Prevents Guardian bash_guardian.py false positives
- [ ] Does NOT block `python3` script execution (approved write path)

#### 3.4.3 Validation Hook (`memory_validate_hook.py`)
- [ ] Hook type: PostToolUse:Write
- [ ] Detection-only (PostToolUse deny cannot prevent writes, only inform)
- [ ] Fires on Write tool calls targeting `.claude/memory/`
- [ ] Skips staging files (`.staging/` subdirectory) -- with diagnostic nlink warning
- [ ] Skips `memory-config.json`
- [ ] For JSON files: runs Pydantic schema validation (lazy-bootstraps pydantic from plugin venv)
- [ ] Invalid files quarantined (renamed to `.invalid.<timestamp>`)
- [ ] Non-JSON files in memory directory: denied outright
- [ ] Fallback basic validation when pydantic unavailable (checks required fields, category match, tags array, content object)

### 3.5 Session Rolling Window
- [ ] Script: `memory_enforce.py`
- [ ] Enforces max_retained limit for session_summary category (default 5, configurable)
- [ ] Scans category folder for active files, sorted by `created_at` (oldest first; missing timestamps = oldest)
- [ ] Retires oldest sessions when count exceeds limit
- [ ] Runs under FlockIndex lock for atomicity
- [ ] Advisory deletion guard: warns about unique content in retired sessions
- [ ] Dynamic retirement cap: `max(10, max_retained * 10)` prevents runaway loops
- [ ] Dry-run mode available
- [ ] Auto-triggers after `memory_write.py --action create --category session_summary` UNLESS `--skip-auto-enforce` (orchestrator runs enforce separately in Phase 2 Step 4)

### 3.6 Index Management
- [ ] Script: `memory_index.py`
- [ ] `--rebuild`: scans all category folders, regenerates `index.md` with enriched format (only active records)
- [ ] `--validate`: compares index entries against actual files, reports mismatches
- [ ] `--query <keyword>`: simple keyword search against index lines
- [ ] `--health`: health report (counts by category, heavily-updated memories, recent retirements, index sync status)
- [ ] `--gc`: garbage collection of retired memories past grace period (default 30 days)
- [ ] Index format: `- [CATEGORY] title -> path #tags:t1,t2,...`
- [ ] Auto-rebuild: both `memory_candidate.py` and `memory_retrieve.py` auto-rebuild `index.md` if missing (derived artifact pattern)

### 3.7 Draft Assembly (`memory_draft.py`)
- [ ] Separates ASSEMBLY from ENFORCEMENT
- [ ] Takes partial input from LLM subagents, produces complete schema-compliant JSON
- [ ] CREATE assembly: generates all metadata (schema_version, id from slugified title, timestamps, record_status=active, times_updated=0, initial change entry)
- [ ] UPDATE assembly: preserves immutable fields from existing, unions tags/related_files, shallow-merges content, appends change entry, increments times_updated
- [ ] Input validation: restricts input paths to `.staging/` or `/tmp/`; restricts candidate paths to `.claude/memory/`

### 3.8 Candidate Selection (`memory_candidate.py`)
- [ ] ACE candidate selection for update/retire decisions
- [ ] Parses `index.md`, filters to target category
- [ ] Tokenizes new info summary using 3+ char tokens (higher precision than retrieval's 2+ char)
- [ ] Scoring: 2pts per exact-matching token in title, 3pts per exact tag match, 1pt per prefix match
- [ ] Selects top-1 candidate if score >= 3
- [ ] Structural CUD: no candidate + no lifecycle event = CREATE
- [ ] Structural CUD: no candidate + lifecycle event = NOOP
- [ ] Structural CUD: candidate + delete allowed = UPDATE_OR_DELETE
- [ ] Structural CUD: candidate + delete disallowed = UPDATE
- [ ] DELETE vetoed for decision, preference, session_summary categories (structurally enforced via `DELETE_DISALLOWED` frozenset)
- [ ] Builds excerpt from candidate file (key content fields, last change summary)

### 3.9 Configuration System

**File locations:**
- [ ] Runtime config: `.claude/memory/memory-config.json` (per-project)
- [ ] Defaults: `assets/memory-config.default.json`

**Script-read config keys (Python):**
- [ ] `triage.enabled` (bool, default true)
- [ ] `triage.max_messages` (int, clamped 10-200, default 50)
- [ ] `triage.thresholds.*` (float, clamped 0.0-1.0, NaN/Inf rejected)
- [ ] `triage.parallel.*` (models validated against {haiku, sonnet, opus})
- [ ] `retrieval.enabled` (bool, default true)
- [ ] `retrieval.max_inject` (int, clamped 0-20, default 3)
- [ ] `retrieval.judge.*` (enabled, model, timeout, pool size, etc.)
- [ ] `retrieval.judge.dual_verification`: config key retained for schema compat; feature cancelled, not implemented
- [ ] `retrieval.confidence_abs_floor` (float, default 0.0 = disabled)
- [ ] `retrieval.output_mode` ("legacy" or "tiered")
- [ ] `delete.grace_period_days` (int, default 30)
- [ ] `logging.*` (enabled, level, retention_days)
- [ ] `categories.*.description` (used in triage context files and retrieval output)

**Agent-interpreted config keys (LLM reads):**
- [ ] `memory_root` (path, default `.claude/memory`)
- [ ] `categories.*.enabled` (bool)
- [ ] `categories.*.folder` (informational mapping)
- [ ] `categories.*.auto_capture` (bool)
- [ ] `categories.*.retention_days` (int, 0 = permanent)
- [ ] `categories.session_summary.max_retained` (int, default 5)
- [ ] `auto_commit` (bool, default false)
- [ ] `max_memories_per_category` (int, default 100)
- [ ] `retrieval.match_strategy` (string)
- [ ] `delete.archive_retired` (bool, default true)
- [ ] `architecture.simplified_flow` (bool, default true -- v6 3-phase flow)
- [ ] `triage.parallel.verification_enabled` (bool, default false)

### 3.10 Logging and Observability

**Logger (`memory_logger.py`):**
- [ ] Format: JSONL (one JSON object per line)
- [ ] Location: `{memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl`
- [ ] Event category derived from `event_type.split('.')[0]` (e.g., "triage" from "triage.score")
- [ ] Fail-open: all errors silently swallowed, never blocks hook execution
- [ ] Atomic append: O_APPEND flag for concurrent safety
- [ ] Level filtering: debug < info < warning < error
- [ ] Auto-cleanup: daily scan removes files older than retention_days (default 14)
- [ ] Symlink protection: skips symlinks during cleanup
- [ ] Session correlation: extracts session ID from transcript path filename

**Key events logged:**
- [ ] `triage.score`: category scores, triggered categories, text length, metrics
- [ ] `triage.error`: triage failures
- [ ] `retrieval.*`: search queries, results, skip reasons, errors
- [ ] `search.query`: CLI search queries
- [ ] `guard.write_deny`, `guard.write_allow_staging`: write guard decisions
- [ ] `guard.staging_deny`: staging guard denials
- [ ] `validate.*`: PostToolUse validation results, quarantines, staging skips
- [ ] `triage.idempotency_skip`: fired when triage skipped due to idempotency guards (5 variants: `stop_flag`, `sentinel`, `save_result`, `lock_held`, `sentinel_recheck`)
- [ ] `save.start`, `save.complete`: emitted by `memory_orchestrate.py` at save pipeline start/end
- [ ] `retrieval.inject`, `retrieval.judge_result`, `retrieval.fallback`: retrieval pipeline events

**Phase timing:**
- [ ] `last-save-result.json` includes `phase_timing` dict with `triage_ms`, `orchestrate_ms`, `write_ms`, `total_ms`

**Log analyzer (`memory_log_analyzer.py`):**
- [ ] `--metrics` mode: operational dashboard (save duration stats, re-fire distribution, category frequency, success rates, phase timing averages)
- [ ] `--watch` mode: real-time log tailing with `--filter` prefix filtering

### 3.11 Slash Commands (10 commands)
- [ ] `/memory` -- status display: counts, health, index sync
- [ ] `/memory --retire <slug>` -- soft-retire a memory
- [ ] `/memory --archive <slug>` -- archive for permanent preservation
- [ ] `/memory --unarchive <slug>` -- restore from archive
- [ ] `/memory --restore <slug>` -- restore from retirement
- [ ] `/memory --gc` -- garbage collect expired retirements
- [ ] `/memory --list-archived` -- list all archived memories
- [ ] `/memory:save <category> <content>` -- manually save a memory
- [ ] `/memory:config <instruction>` -- configure settings via natural language
- [ ] `/memory:search <query>` -- full-text search with FTS5

### 3.12 Memory JSON Schema

**Base fields (all categories):**
- [ ] `schema_version`: "1.0"
- [ ] `category`: one of the 6 categories
- [ ] `id`: kebab-case-slug
- [ ] `title`: max 120 chars
- [ ] `record_status`: "active" | "retired" | "archived"
- [ ] `created_at`: ISO 8601 UTC
- [ ] `updated_at`: ISO 8601 UTC
- [ ] `tags`: array, min 1, max 12
- [ ] `related_files`: array of paths
- [ ] `confidence`: float 0.0-1.0
- [ ] `content`: object (category-specific)
- [ ] `changes`: array of `{ date, summary, field?, old_value?, new_value? }`
- [ ] `times_updated`: integer starting at 0
- [ ] `retired_at?`: ISO 8601 (optional)
- [ ] `retired_reason?`: string (optional)
- [ ] `archived_at?`: ISO 8601 (optional)
- [ ] `archived_reason?`: string (optional)

**Category-specific content schemas:**
- [ ] session_summary: goal, outcome (success/partial/blocked/abandoned), completed[], in_progress[], blockers[], next_actions[], key_changes[]
- [ ] decision: status (proposed/accepted/deprecated/superseded), context, decision, alternatives[{option, rejected_reason}], rationale[], consequences[]
- [ ] runbook: trigger, symptoms[], steps[], verification, root_cause, environment
- [ ] constraint: kind (limitation/gap/policy/technical), rule, impact[], workarounds[], severity (high/medium/low), active, expires
- [ ] tech_debt: status (open/in_progress/resolved/wont_fix), priority (critical-low), description, reason_deferred, impact[], suggested_fix[], acceptance_criteria[]
- [ ] preference: topic, value, reason, strength (strong/default/soft), examples{prefer[], avoid[]}

---

## 4. Non-Functional Requirements

### 4.1 UX: Minimal Screen Noise
- [ ] Silent during normal workflow (retrieval injects silently); Stop hook outputs blocking message only when save triggered; next session shows brief confirmation
- [ ] No approval popups: write guard auto-approves staging file writes; manual ops use Bash to invoke `memory_write.py`; automated Phase 1 drafters use Read/Write tools only (no Bash)
- [ ] Guardian compatibility: `memory-drafter` agent uses `tools: Read, Write` only (no Bash); staging writes use Write tool (not Bash heredoc); path strings constructed at runtime
- [ ] Deterministic save execution: Phase 2 COMMIT runs `memory_orchestrate.py` as single Python subprocess (invisible to Guardian); no haiku saver subagent or heredoc Bash commands
- [ ] Progressive disclosure: search results show compact summaries first; full JSON only on explicit request

### 4.2 Performance

**Hook timeouts:**
- [ ] Stop (triage): 30s
- [ ] UserPromptSubmit (retrieve): 15s
- [ ] PreToolUse:Write (guard): 5s
- [ ] PreToolUse:Bash (staging guard): 5s
- [ ] PostToolUse:Write (validate): 10s

**Subagent costs:**
- [ ] Each triggered category spawns 1 drafting subagent (Phase 1 DRAFT only)
- [ ] Worst case: all 6 categories = 6 drafting subagent calls (rare)
- [ ] Optional verification: risk-eligible categories (decision/constraint, DELETE, low-confidence) spawn additional verification subagents
- [ ] Save execution: deterministic Python subprocess (no subagent)
- [ ] Per-category model selection optimizes cost (haiku for simple, sonnet for complex)

**Search performance:**
- [ ] FTS5 in-memory SQLite index (`:memory:`)
- [ ] Body text extraction capped at 2000 chars per entry
- [ ] Context files capped at 50KB
- [ ] Search results capped at 30 from FTS5, further limited by threshold and top-K

### 4.3 Security

#### 4.3.1 Prompt Injection Defenses
- [ ] Title/tag sanitization: strip control chars, zero-width Unicode, bidirectional overrides, combining marks, variation selectors
- [ ] Title/tag sanitization: escape XML-sensitive chars (`<`, `>`, `&`, `"`)
- [ ] Title/tag sanitization: remove index-injection markers (` -> `, `#tags:`)
- [ ] Title/tag sanitization: remove confidence label spoofing patterns (`[confidence:...]`)
- [ ] Output boundaries: user content in XML element bodies; system attributes (category, confidence) in XML attributes -- structural separation prevents boundary breakout
- [ ] Transcript data isolation: `<transcript_data>` tags mark untrusted content; drafter agent treats transcript as raw data
- [ ] Judge integrity: untrusted data wrapped in `<memory_data>` XML tags with instruction not to follow embedded instructions; deterministic shuffling prevents position bias
- [ ] Description sanitization: category descriptions sanitized before injection into triage context files and retrieval output

#### 4.3.2 Config Manipulation
- [ ] `max_inject` clamped to [0, 20]
- [ ] `max_messages` clamped to [10, 200]
- [ ] Thresholds clamped to [0.0, 1.0]; NaN and Inf rejected
- [ ] Model names validated against allowlist {haiku, sonnet, opus}
- [ ] `max_retained` validated as integer >= 1 (booleans explicitly rejected)
- [ ] `grace_period_days` clamped to >= 0

#### 4.3.3 Index Integrity
- [ ] ` -> ` and `#tags:` delimiter patterns stripped from user inputs (titles, tags) to prevent parsing corruption
- [ ] Index lines sorted for deterministic ordering
- [ ] Index treated as derived artifact: auto-rebuilt when missing

#### 4.3.4 FTS5 Injection
- [ ] Query tokens restricted to safe chars (`[a-z0-9_.-]`)
- [ ] All FTS5 queries use parameterized execution (no string interpolation into SQL)
- [ ] Stop words filtered before query construction

#### 4.3.5 Path Security
- [ ] Path containment: all file ops verify target within memory root via `resolve().relative_to()`
- [ ] Path traversal: `..` components rejected in input/candidate paths
- [ ] Directory component validation: rejects brackets and injection characters in directory names (S5F defense)
- [ ] Hard link defense: PreToolUse write guard checks `st_nlink` for existing staging files (see also 3.4.1 Gate 3)
- [ ] Symlink defense: secure file creation uses `O_NOFOLLOW`; cleanup skips symlinks
- [ ] PinnedStagingDir: TOCTOU defense using `O_DIRECTORY|O_NOFOLLOW` + `fstat` + `dir_fd` to pin directory identity at open time and verify it hasn't been swapped before operations
- [ ] Parent chain validation: validates every path chain component, preventing symbolic link attacks at intermediate directories
- [ ] `write-save-result-direct` removed: replaced by `--result-file <path>` flag to eliminate shell injection vector
- [ ] XDG staging: 4-tier resolution. No `/tmp/` fallback for staging resolution. Per-operation scratch files may use `/tmp/` with restrictive filename patterns.

#### 4.3.6 Thread Safety
- [ ] LLM judge parallel batch splitting uses ThreadPoolExecutor with no shared mutable state
- [ ] Index mutations use FlockIndex (mkdir-based lock, portable across all FS including NFS)

#### 4.3.7 Anti-Resurrection
- [ ] CREATE at recently-retired path (< 24 hours) blocked with `ANTI_RESURRECTION_ERROR`
- [ ] Check performed inside FlockIndex to prevent TOCTOU races

### 4.4 Reliability

#### 4.4.1 Fail-Open Design

Per-hook fail-open behavior:
- [ ] Triage (Stop): exits with `{"decision": "allow"}` on error -- stop proceeds, no save attempted
- [ ] Retrieve (UserPromptSubmit): prints nothing on error -- prompt proceeds without injected memories
- [ ] Write guard (PreToolUse:Write): exits 0 on parse error -- write allowed through
- [ ] Staging guard (PreToolUse:Bash): exits 0 on parse error -- Bash command allowed through
- [ ] Validate (PostToolUse:Write): detection-only; error = no quarantine, write already completed

General principles:
- [ ] Unexpected exceptions caught and logged, never propagated
- [ ] Missing files, corrupt JSON, unavailable pydantic: all handled gracefully
- [ ] Logger itself is fail-open (never blocks hook execution)
- [ ] Guard scripts exit 0 on any parse error (allows operation through)

#### 4.4.2 OCC (Optimistic Concurrency Control)
- [ ] UPDATE accepts `--hash <md5>` parameter
- [ ] Current file MD5 compared against expected hash inside FlockIndex
- [ ] Mismatch produces `OCC_CONFLICT` error with retry guidance

#### 4.4.3 Atomic Writes
- [ ] All file mutations use `atomic_write_json()` / `atomic_write_text()`: write to temp file, then `os.replace()`
- [ ] Triage data written atomically via `os.replace()`
- [ ] Context files created with `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` (secure creation, restrictive permissions)

#### 4.4.4 FlockIndex
- [ ] mkdir-based lock (atomic on all filesystems including NFS)
- [ ] 15-second timeout, 50ms poll interval
- [ ] Stale lock detection: breaks locks older than 60s with warning; `__exit__` unconditionally runs `os.rmdir()` (no ownership verification -- a process whose lock was stale-broken can delete another process's lock)
- [ ] `require_acquired()` method for strict enforcement (used by memory_enforce.py)

#### 4.4.5 Venv Bootstrap
- [ ] `memory_write.py`, `memory_draft.py`, `memory_enforce.py`, `memory_validate_hook.py` require pydantic v2
- [ ] If pydantic not importable, scripts re-exec under plugin venv (`.venv/bin/python3`) via `os.execv()`
- [ ] Validate hook uses lazy site-packages injection instead (avoids process replacement that would lose stdin data)

---

## 5. Data Architecture

### 5.1 Storage Layout

**Memory storage (project-local):**
- [ ] Root: `.claude/memory/`
- [ ] `memory-config.json` in root
- [ ] `index.md` in root (auto-generated, derived artifact)
- [ ] Category folders: `sessions/`, `decisions/`, `runbooks/`, `constraints/`, `tech-debt/`, `preferences/`
- [ ] `logs/` with subcategories: `triage/`, `retrieval/`, `search/`, `guard/`, `validate/`

**Staging directory (external, per-user):**
- [ ] Located OUTSIDE project tree in secure per-user directory
- [ ] Path: `<staging_base>/.claude-memory-staging-<hash>/`
- [ ] Hash: `SHA-256(f"{os.geteuid()}:{os.path.realpath(cwd)}")[:12]`

**4-tier staging base resolution:**
- [ ] Priority 1: `XDG_RUNTIME_DIR` -- set, absolute, 0700, owned by euid, is directory (strict: rejects WSL2's 0777)
- [ ] Priority 2: `/run/user/$UID` -- Linux systemd, exists, 0700, owned by euid (even if XDG_RUNTIME_DIR not set)
- [ ] Priority 3: macOS `CS_DARWIN_USER_TEMP_DIR` -- via `os.confstr()`, bypasses `TMPDIR` env var, owner-only permissions
- [ ] Priority 4: `$XDG_CACHE_HOME/claude-memory/staging/` -- universal fallback (defaults to `~/.cache/claude-memory/staging/`), created with 0700
- [ ] No `/tmp/` fallback for staging resolution. Per-operation scratch files may use `/tmp/` with restrictive filename patterns.

**Staging files:**
- [ ] `triage-data.json` -- triage output (categories, scores)
- [ ] `context-<category>.txt` -- per-category transcript excerpts
- [ ] `intent-<category>.json` -- Phase 1 drafter output (SAVE or NOOP)
- [ ] `input-<category>.json` -- orchestrator input for draft assembly
- [ ] `new-info-<category>.txt` -- extracted new information per category
- [ ] `draft-<category>-<ts>.json` -- assembled draft memory JSON
- [ ] `last-save-result.json` -- save outcome (with phase_timing)
- [ ] `.triage-handled` -- sentinel: triage consumed by save flow
- [ ] `.triage-pending.json` -- fallback: drafters failed, retrieval detects

**Additional notes:**
- [ ] `.index.lockdir/` (FlockIndex) is in memory storage root (`.claude/memory/.index.lockdir/`), NOT in staging
- [ ] Legacy `.claude/memory/.staging/` paths recognized by guards for backward compatibility

### 5.2 Record Lifecycle

**State transitions:**
- [ ] CREATE -> active
- [ ] RESTORE -> active (from retired)
- [ ] UNARCHIVE -> active (from archived)
- [ ] RETIRE -> retired (from active)
- [ ] ARCHIVE -> archived (from active)
- [ ] GC (30d grace) -> PURGE (file deleted, from retired)

**State descriptions:**
- [ ] active: indexed and retrievable (default for all new memories)
- [ ] retired: excluded from index; GC-eligible after grace period (default 30 days)
- [ ] archived: excluded from index; NOT GC-eligible (preserved indefinitely)

---

## 6. Current Pain Points

| # | Pain Point | Status | Evidence |
|---|------------|--------|----------|
| 6.1 | Stop hook re-fire loop | Active (5 prevention layers) | 5 mechanisms: stop flag, sentinel, save-result guard, triage lock, sentinel recheck; `_increment_fire_count()` informational metric |
| 6.2 | Screen noise from multi-phase save | RESOLVED in v6 | 3-phase architecture, `run_in_background: true` for drafters, single subprocess COMMIT, SKILL.md silent-op rules |
| 6.3 | Guardian compatibility issues | LARGELY RESOLVED in v6 | Runtime string construction, drafter Read/Write only, SKILL.md Rule 0, staging guard, `--result-file` indirection |
| 6.4 | Complex 5-phase orchestration | RESOLVED in v6 | Simplified to 3-phase (SETUP, DRAFT, COMMIT), 1 subagent type, max 6 calls, `memory_orchestrate.py --action run` |
| 6.5 | Tokenizer divergence | Intentional | `memory_candidate.py` 3+ chars (precision) vs `memory_search_engine.py` 2+ chars (recall) |
| 6.6 | PostToolUse limitation | By design | Detection-only, cannot prevent writes; Python `open()` invisible; PreToolUse guard is critical defense |

---

## 7. Test Coverage

### 7.1 Test Files (30 files)

- [ ] All 30 test files exist in tests/ and pass with `pytest tests/ -v`

| Test File | Coverage |
|-----------|----------|
| test_memory_triage.py | triage scoring, thresholds, category patterns, config, transcript parsing, context files |
| test_memory_retrieve.py | retrieval hook, scoring, recency, confidence, output, save confirmation, orphan detection |
| test_memory_write.py | CRUD, merge protections, OCC, anti-resurrection, auto-fix, validation, atomic writes, staging |
| test_memory_candidate.py | candidate selection, scoring, structural CUD, vetoes, lifecycle, excerpts |
| test_memory_draft.py | draft assembly (create/update), input validation, path security, schema |
| test_memory_index.py | index rebuild, validate, query, health, GC |
| test_memory_write_guard.py | write guard decisions, staging auto-approve, path detection, exemptions |
| test_memory_staging_guard.py | staging guard pattern detection, Bash command blocking |
| test_memory_validate_hook.py | PostToolUse validation, quarantine, staging skip, category detection |
| test_memory_judge.py | LLM judge API calls, batch splitting, anti-position-bias, error handling |
| test_memory_logger.py | structured logging, config parsing, session ID extraction, cleanup |
| test_memory_orchestrate.py | orchestration pipeline, CUD resolution, action modes, save execution |
| test_memory_staging_utils.py | staging path resolution, PinnedStagingDir, is_staging_path, validation |
| test_fts5_search_engine.py | FTS5 search engine, tokenization, indexing, querying, threshold |
| test_fts5_benchmark.py | search performance benchmarks |
| test_rolling_window.py | session rolling window enforcement, config reading, deletion guard |
| test_arch_fixes.py | architecture-level fix verification |
| test_regression_popups.py | regression tests for approval popup prevention |
| test_adversarial_descriptions.py | category description injection attacks |
| test_v2_adversarial_fts5.py | FTS5-specific adversarial attacks |
| test_log_analyzer.py | log analysis tooling |
| test_log_analyzer_metrics.py | log analyzer --metrics mode, save duration, category frequency |
| test_screen_noise_reduction.py | screen noise reduction verification (run_in_background, single subprocess) |
| test_triage_observability.py | triage logging events, idempotency skip events, phase timing |
| test_save_timing.py | save pipeline timing capture, phase_timing dict validation |
| test_triage_interruption.py | triage interruption handling, re-fire prevention guards |
| test_hook_stderr.py | hook stderr handling, error output isolation |
| test_contract_drift.py | contract drift detection between code and config/docs |
| test_config_defaults.py | config default values, range clamping, validation |
| test_rejection_loop.py | rejection loop prevention, guardian interaction |

---

## 8. Script Dependency Map

| Script | Imports | Reads | Writes | Calls |
|--------|---------|-------|--------|-------|
| memory_triage.py | staging_utils, logger | transcript, config | context-*, triage-data.json, .triage-handled, .stop_hook_active | - |
| memory_retrieve.py | staging_utils, search_engine, logger | index.md, memory JSONs, last-save-result.json, .triage-pending.json | - | memory_index.py --rebuild, memory_judge.py |
| memory_search_engine.py | logger | index.md, memory JSONs | - | - |
| memory_candidate.py | - | index.md, memory JSONs | - | memory_index.py --rebuild |
| memory_draft.py | memory_write | input JSON, candidate JSON | draft-*.json | - |
| memory_write.py | pydantic v2 | input JSON, target JSON | memory JSONs, index.md | memory_enforce.py |
| memory_enforce.py | memory_write | memory JSONs, config | memory JSONs, index.md | - |
| memory_write_guard.py | staging_utils, logger | - | - | - |
| memory_staging_guard.py | staging_utils, logger | - | - | - |
| memory_validate_hook.py | staging_utils, memory_write, logger | - | - | - |
| memory_judge.py | logger | - | - | Anthropic Messages API |
| memory_orchestrate.py | staging_utils, memory_write | intent-*.json, config | manifest-*.json, last-save-result.json | memory_candidate, memory_draft, memory_write, memory_enforce |
| memory_staging_utils.py | stdlib only | - | - | - |
| memory_logger.py | stdlib only | - | logs/{category}/{date}.jsonl | - |
| memory_index.py | - | memory JSONs, config | index.md, deletes retired (GC) | - |

---

## 9. Plugin Manifest
- [ ] `name`: "claude-memory"
- [ ] `version`: "6.0.0"
- [ ] `commands`: `["./commands/memory.md", "./commands/memory-config.md", "./commands/memory-save.md"]`
- [ ] `agents`: `["./agents/memory-drafter.md"]`
- [ ] `skills`: `["./skills/memory-management", "./skills/memory-search"]`
- [ ] `license`: "MIT"

---

## 10. Key Design Decisions (7 decisions)

- [ ] DD-1: Single Stop hook (command type) over 6 prompt-type hooks -- command-type runs deterministically, evaluates all categories in one pass; original 6 prompt-type hooks were "unreliable"
- [ ] DD-2: Keyword heuristics over LLM classification for triage -- keeps Stop hook fast (<30s), deterministic, cost-free; LLM only in drafting phase
- [ ] DD-3: Pydantic v2 as source of truth for schemas -- JSON Schema files in `assets/schemas/` are reference only; Pydantic models in `memory_write.py` are authoritative
- [ ] DD-4: FTS5 BM25 over simple keyword matching -- FTS5 primary with legacy keyword fallback; provides ranked relevance scoring
- [ ] DD-5: mkdir-based locking over flock() -- `os.mkdir()` is atomic on all filesystems including NFS; POSIX `flock()` has known NFS issues
- [ ] DD-6: Per-category model selection -- decision/constraint use sonnet (more reasoning); simpler categories use haiku (cost optimization)
- [ ] DD-7: Separate ASSEMBLY from ENFORCEMENT -- `memory_draft.py` handles assembly (partial->complete JSON), `memory_write.py` handles enforcement (validation, merge protections, atomic writes)
