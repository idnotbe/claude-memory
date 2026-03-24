# claude-memory Plugin -- Product Requirements Document (PRD)

Version: 5.1.0 | Date: 2026-03-22 | Audience: Claude (AI)

---

## 1. Product Vision

### 1.1 What is claude-memory?

claude-memory is a structured memory plugin for Claude Code that provides persistent knowledge management across coding sessions. It automatically captures and retrieves project-specific knowledge -- decisions, runbooks, constraints, tech debt, session summaries, and preferences -- stored as schema-validated JSON files on the local filesystem.

### 1.2 Problem Statement

Claude Code conversations are ephemeral. When a session ends, all context is lost. The next session starts with zero knowledge of:

- Why architectural decisions were made
- What workarounds exist for known limitations
- What was accomplished in previous sessions
- User preferences for coding conventions
- Known tech debt and deferred work
- Procedures for fixing recurring errors

claude-memory solves this by silently capturing knowledge during sessions and injecting relevant memories into future conversations, creating continuity across the user's entire project history.

### 1.3 Design Philosophy

- **Zero-friction**: Auto-capture on session end, auto-inject on prompt. No manual effort required.
- **Silent operation**: Memory operations should be invisible to the user during normal workflow.
- **Safety-first**: All writes go through schema validation. Mechanical rules prevent data corruption.
- **Fail-open**: Every hook is designed to silently fail rather than block the user's workflow.
- **Defense-in-depth**: Multiple overlapping security layers (guards, validation, sanitization, containment checks).

---

## 2. User Stories and Use Cases

### 2.1 Automatic Behavior (No User Action Required)

**US-1: Auto-capture on session end.**
When the user stops a Claude Code session, the Stop hook evaluates the conversation transcript. If meaningful knowledge was discussed (decisions made, errors resolved, constraints discovered, etc.), the hook blocks the stop, saves memories, then allows the stop. The user sees minimal output.

**US-2: Auto-inject on prompt.**
When the user submits any prompt, the UserPromptSubmit hook searches the memory index for relevant entries and injects them into Claude's context. The user never needs to explicitly ask for memories.

**US-3: Save confirmation on next session.**
When starting a new session after memories were saved, the retrieval hook displays a brief `<memory-note>` confirming what was saved (categories and titles).

**US-4: Orphan crash detection.**
If a previous save operation crashed mid-way (staging files exist without a result file), the retrieval hook notifies the user and suggests running `/memory:save` to retry.

**US-5: Session rolling window.**
Session summaries are automatically capped at N most recent (default 5). When a new session summary is created and the limit is exceeded, the oldest is retired automatically via `memory_enforce.py`.

### 2.2 Manual / Slash Command Behavior

**US-6: Manual save via `/memory:save`.**
User explicitly saves a memory to a specific category with natural language content. Example: `/memory:save decision "We chose Vitest over Jest for speed"`

**US-7: Status check via `/memory`.**
User views memory system status: counts per category, health indicators, index sync status.

**US-8: Lifecycle management via `/memory --retire|--archive|--restore|--gc`.**
User manually retires, archives, restores, or garbage-collects memories.

**US-9: Configuration via `/memory:config`.**
User modifies settings with natural language: `/memory:config raise decision threshold to 0.7`

**US-10: Explicit search via `/memory:search`.**
User searches memories using full-text queries when auto-inject doesn't surface what they need.

**US-11: Recall via conversational prompts.**
User asks "What do you remember about X?" or "What did we decide about Y?" and Claude reads/searches memories to answer.

---

## 3. Functional Requirements

### 3.1 Auto-Capture (Stop Hook Triage -> Save Flow)

#### 3.1.1 Triage Hook (`memory_triage.py`)

**Hook type:** Stop (command type), fires on every session stop.

**Input:** Receives hook JSON via stdin containing `transcript_path` and `cwd`.

**Behavior:**

1. Reads the JSONL transcript file (last N messages, configurable via `triage.max_messages`, default 50).
2. Extracts text content (strips fenced code blocks and inline code to reduce false positives).
3. Extracts activity metrics (tool uses, distinct tools, exchanges) for session summary scoring.
4. Scores all 6 categories using keyword heuristic patterns:
   - Text-based categories (DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE): primary regex patterns + co-occurrence boosters within a sliding window of 4 lines.
   - Activity-based (SESSION_SUMMARY): formula based on tool_uses, distinct_tools, exchanges.
5. Compares scores against configurable thresholds (default range 0.4-0.6).
6. If any category exceeds its threshold:
   - Sets the stop flag (`.claude/.stop_hook_active`) to prevent re-fire loops.
   - Writes sentinel JSON (`<staging_dir>/.triage-handled`) -- JSON state machine with `{session_id, state, timestamp, pid}`. States: `pending`->`saving`->`saved`|`failed`. State `pending`/`saving`/`saved` blocks re-triage (same session, within TTL 1800s); `failed` allows re-triage.
   - Writes per-category context files (`<staging_dir>/context-<cat>.txt`) with transcript excerpts.
   - Writes `triage-data.json` to `<staging_dir>/` (atomic write via tmp+rename).
   - Outputs `{"decision": "block", "reason": "..."}` to stdout with human-readable message + structured data reference.

**Re-fire prevention mechanisms (5 layers):**
- `check_stop_flag()`: File-based flag (`.claude/.stop_hook_active`) with 5-minute TTL. If fresh flag exists, the hook exits immediately (allows the stop through).
- JSON sentinel: Session-scoped state machine (`<staging_dir>/.triage-handled`) -- blocks re-triage when state is `pending`/`saving`/`saved` for the same session within TTL (1800s). `failed` state allows retry.
- `_check_save_result_guard()`: If `last-save-result.json` exists and is recent (same session), skip -- the session has already saved successfully.
- `_acquire_triage_lock()`: `O_CREAT|O_EXCL` exclusive lock on `.stop_hook_lock` with 120s stale timeout -- prevents concurrent triage from parallel stop events.
- `sentinel_recheck`: Under triage lock, re-checks sentinel (double-check pattern prevents race between lock acquisition and sentinel write).

**Informational metric:** `_increment_fire_count()` tracks per-workspace fire count (`.triage-fire-count`), included in all triage log events for diagnostics. Does not block.

**Category pattern definitions:**

| Category | Primary Patterns | Boosters | Threshold |
|----------|-----------------|----------|-----------|
| DECISION | decided, chose, selected, went with, let's go with, opting for, switching to, etc. (with negative lookbehind for negation) | because, due to, reason, rationale, over, instead of, rather than | 0.4 |
| RUNBOOK | error, exception, traceback, failed, failure, crash | fixed by, resolved, root cause, solution, workaround | 0.4 |
| CONSTRAINT | limitation, api limit, restricted, not supported, quota, rate limit, hard limit, etc. | discovered, found that, turns out, permanently, cannot, by design, deprecated, etc. | 0.45 |
| TECH_DEBT | TODO, deferred, tech debt, workaround, hack, will address later | because, for now, temporary, acknowledged, deferring | 0.4 |
| PREFERENCE | always use, prefer, convention, from now on, standard, never use, default to, stick with, etc. | agreed, going forward, consistently, rule, practice, workflow | 0.4 |
| SESSION_SUMMARY | (activity metrics: tool_uses*0.05 + distinct_tools*0.1 + exchanges*0.02) | N/A | 0.6 |

**Scoring formula for text categories:**
```
raw_score = (primary_matches * primary_weight) + (boosted_matches * boosted_weight)
normalized = min(1.0, raw_score / denominator)
```
Where `primary_weight` ~ 0.2-0.35, `boosted_weight` ~ 0.5-0.6, caps on both match types.

#### 3.1.2 Three-Phase Save Orchestration (SKILL.md v6)

**Pre-Phase: Staging Cleanup.**
On manual `/memory:save` (no triage data present), clean stale staging files from previous failed sessions before proceeding.

**SETUP (deterministic).**
- Clean stale intent files.
- Extract `triage-data.json` path from `<triage_data_file>` tag (fallback: inline `<triage_data>` JSON).
- Read config for parallel processing settings and `architecture.simplified_flow` flag.

**Phase 1: DRAFT (LLM, per-category Agent subagents).**
For each triggered category, spawn an Agent subagent using the `memory-drafter` agent file:
- Agent has `tools: Read, Write` only (no Bash -- structurally prevents Guardian conflicts).
- Agent reads its context file and writes an intent JSON (SAVE or NOOP).
- All category subagents spawn in PARALLEL.
- Model selection is per-category (configurable via `triage.parallel.category_models`).
- M1 fallback: if ALL drafters fail, write `.triage-pending.json` for retrieval hook detection.

Intent JSON formats:
- **SAVE:** `{ category, new_info_summary, intended_action?, lifecycle_hints?, partial_content: { title, tags, confidence, related_files?, change_summary, content } }`
- **NOOP:** `{ category, action: "noop", noop_reason }`

**Phase 1.5: VERIFY (optional, disabled by default).**
When `triage.parallel.verification_enabled: true`:
- Orchestrator runs `--action prepare` (steps 1-6: collect, candidate, CUD, draft, manifest).
- Risk-eligible categories (decision/constraint, DELETE actions, low-confidence) are verified.
- Verifiers inspect assembled draft JSON for accuracy and hallucination.
- `BLOCK` verdicts exclude categories from the subsequent `--action commit` call.

**Phase 2: COMMIT (deterministic, single Python subprocess).**
Single call: `python3 memory_orchestrate.py --staging-dir <dir> --action run --memory-root <root>`.
The orchestrator emits `save.start` and `save.complete` logging events (via `memory_logger.py`) bracketing the full save flow.
The orchestrator performs all deterministic steps as subprocesses:
1. Collect intents, candidate selection (with OCC hash capture), CUD resolution.
2. Draft assembly via `memory_draft.py`, target path generation for CREATEs.
3. Save execution via `memory_write.py` (with `--skip-auto-enforce`).
4. Enforcement (`memory_enforce.py`) for session_summary creates.
5. Result file writing (`last-save-result.json`) for next-session confirmation. The result includes a `phase_timing` dict with `triage_ms`, `orchestrate_ms`, `write_ms`, and `total_ms` fields for observability.
6. Staging cleanup on success; `.triage-pending.json` + sentinel update on failure.

#### 3.1.3 CUD Verification Rules Table

| L1 (Python structural) | L2 (Subagent intent) | Resolution |
|---|---|---|
| CREATE | CREATE | CREATE |
| UPDATE_OR_DELETE | UPDATE | UPDATE |
| UPDATE_OR_DELETE | DELETE | DELETE |
| CREATE | UPDATE | CREATE (no candidate exists) |
| CREATE | DELETE | NOOP (cannot delete without candidate) |
| UPDATE_OR_DELETE | CREATE | CREATE (subagent override) |
| VETO | * | OBEY VETO (mechanical invariant) |
| NOOP | * | NOOP |

### 3.2 Memory Retrieval (UserPromptSubmit Hook)

#### 3.2.1 Retrieval Hook (`memory_retrieve.py`)

**Hook type:** UserPromptSubmit, fires on every user prompt.

**Behavior:**

1. **Save confirmation (Block 1):** Checks for `last-save-result.json` in `<staging_dir>` (via `get_staging_dir()` with legacy `.staging/` fallback). If recent (<24h), displays what was saved, then deletes the file.
2. **Orphan detection (Block 2):** Checks for stale `triage-data.json` in `<staging_dir>` (via `get_staging_dir()` with legacy `.staging/` fallback) without a save result. Notifies user if orphaned data found.
3. **Pending notification (Block 3):** Checks for `.triage-pending.json` in `<staging_dir>` (via `get_staging_dir()` with legacy `.staging/` fallback). Notifies user of pending saves from last session.
4. **Short prompt skip:** Prompts < 10 characters are skipped (greetings, acks).
5. **Index rebuild on demand:** If `index.md` is missing but memory root exists, auto-rebuilds.
6. **FTS5 BM25 search:** Tokenizes user prompt, constructs FTS5 query, searches title+tags index.
7. **Hybrid body scoring:** For top-K candidates, reads JSON files, extracts body text, adds body bonus (0-3 points).
8. **Description scoring (`score_description()`):** Adds up to 2 bonus points for entries matching category description keywords, applied only to already-matched entries.
9. **Recency check:** Reads JSON for top candidates to check `updated_at` (30-day recency window) and `record_status` (filters retired/archived).
10. **Threshold + Top-K:** Applies 25% noise floor, limits to max_inject (default 3, configurable 0-20).
11. **Confidence labeling:** Labels results as high/medium/low based on ratio to best score, with optional absolute floor.
12. **Output:** Prints XML elements (`<memory-context>` wrapper with `<result>` elements) to stdout, which Claude receives as context.

**Optional LLM Judge (`memory_judge.py`):**
When enabled via config + `ANTHROPIC_API_KEY` env var:
- Sends top candidates to Anthropic Messages API (haiku model).
- Judge determines which memories are "DIRECTLY RELEVANT and would ACTIVELY HELP."
- Anti-position-bias: deterministic shuffling of candidate order.
- Anti-injection: untrusted data wrapped in `<memory_data>` XML tags.
- Parallel batch splitting via ThreadPoolExecutor when candidates > 6.
- Falls back to unfiltered results on any failure.
- `retrieval.judge.dual_verification` config key enables a second verification pass for borderline candidates.

**Output modes:**
- `legacy` (default): All results as `<result>` elements.
- `tiered`: HIGH=`<result>`, MEDIUM=`<memory-compact>`, LOW=silence. Search hints for all-low or medium-only sets.

#### 3.2.2 Search Engine (`memory_search_engine.py`)

Shared FTS5 engine used by both the retrieval hook and CLI search skill.

**Core functions:**
- `tokenize()`: Extracts lowercase tokens, filters stop words, supports legacy (simple) and compound-preserving (FTS5) modes.
- `parse_index_line()`: Parses enriched index format `- [CAT] title -> path #tags:t1,t2,...`
- `build_fts_index()`: Creates in-memory SQLite FTS5 virtual table.
- `build_fts_query()`: Constructs MATCH queries with smart wildcards (compounds=exact, singles=prefix).
- `query_fts()`: Executes MATCH query, returns BM25-ranked results.
- `apply_threshold()`: 25% noise floor, category priority sorting, Top-K limiting.
- `extract_body_text()`: Extracts searchable text from category-specific content fields (capped at 2000 chars).

**CLI interface:**
```bash
python3 memory_search_engine.py --query "auth" --root .claude/memory --mode search
```
Modes: `auto` (title+tags, top-3) and `search` (full-body, top-10). Outputs JSON or text.

### 3.3 Memory CRUD Operations

#### 3.3.1 CREATE (`memory_write.py --action create`)

1. Reads input JSON from staging file.
2. Applies auto-fix rules (schema_version, timestamps, id slugification, tag dedup/sort, title sanitization, confidence clamping).
3. Forces `record_status="active"` (prevents injection of retired/archived status).
4. Validates against category-specific Pydantic model.
5. Path traversal check + directory component validation (S5F defense).
6. Anti-resurrection check: blocks re-creation within 24 hours of retirement at the same path.
7. Atomic write via tmp+rename under FlockIndex lock.
8. Adds entry to `index.md`.
9. For session_summary: auto-triggers `memory_enforce.py` for rolling window.

#### 3.3.2 UPDATE (`memory_write.py --action update`)

1. Reads existing file and new input.
2. Preserves immutable fields (created_at, schema_version, category, id, record_status).
3. Validates against Pydantic model.
4. Enforces merge protections:
   - Tags: grow-only below 12-tag cap; eviction only when adding new tags at cap.
   - related_files: grow-only, except dangling paths can be removed.
   - changes[]: append-only, minimum 1 new entry per update, FIFO overflow at 50.
5. OCC hash check (MD5 of current file vs expected hash) inside FlockIndex.
6. Slug rename on >50% title word difference.
7. Atomic write + index update.

#### 3.3.3 RETIRE (`memory_write.py --action retire`)

Soft delete with grace period:
1. Reads existing file.
2. Sets `record_status="retired"`, `retired_at`, `retired_reason`.
3. Appends change entry.
4. Atomic write.
5. Removes entry from `index.md`.
6. Idempotent: already-retired returns success.
7. Blocks archived -> retired transition (must unarchive first).

#### 3.3.4 ARCHIVE (`memory_write.py --action archive`)

Long-term preservation:
1. Only active memories can be archived.
2. Sets `record_status="archived"`, `archived_at`, `archived_reason`.
3. Clears retired fields.
4. Removes from index.
5. NOT GC-eligible (preserved indefinitely).

#### 3.3.5 UNARCHIVE (`memory_write.py --action unarchive`)

Restores archived memory to active:
1. Reads file, verifies `record_status="archived"`.
2. Sets `record_status="active"`, clears archived fields.
3. Re-adds to index.

#### 3.3.6 RESTORE (`memory_write.py --action restore`)

Restores retired memory to active:
1. Reads file, verifies `record_status="retired"`.
2. Sets `record_status="active"`, clears retired fields.
3. Re-adds to index.

#### 3.3.7 Staging Utilities

- `cleanup-staging`: Removes transient files (triage-data, context-*, draft-*, intent-*, etc.) with path containment check.
- `write-save-result`: Writes `last-save-result.json` with schema validation (allowed keys, length caps).
- `cleanup-intents`: Removes stale `intent-*.json` from staging (called during SETUP Step 2).
- `update-sentinel-state`: Updates sentinel JSON state machine to a given state (called by `memory_orchestrate.py`).
- `--result-file <path>` flag: Writes save result to a file (replaces old `write-save-result-direct` which was removed for shell injection safety).
- `--skip-auto-enforce` flag: Prevents `memory_write.py` from auto-triggering enforce after `session_summary` create (used by orchestrator which runs enforce separately).
- C1 overwrite guard: `do_create()` rejects CREATE if an active file already exists at target path.
- C2 index dedup: `add_to_index()` deduplicates by path before appending.

### 3.4 Guard Rails

#### 3.4.1 Write Guard (`memory_write_guard.py`)

**Hook type:** PreToolUse:Write

**Behavior:**
- Blocks any Write tool call targeting files inside `.claude/memory/` (the memory directory).
- Auto-approves writes to `.staging/` subdirectory with safety gates:
  - Gate 1: Extension whitelist (.json, .txt only).
  - Gate 2: Filename pattern whitelist (intent-*, input-*, draft-*, context-*, etc.).
  - Gate 3: Hard link defense (checks st_nlink for existing files; nlink > 1 = require user approval).
  - Gate 4: New file pass-through.
- Exempts `memory-config.json` if directly in memory root (not subfolder).
- Exempts `/tmp/.memory-write-pending*.json`, `/tmp/.memory-draft-*.json`, `/tmp/.memory-triage-context-*.txt`.
- Returns `{"permissionDecision": "deny"}` for blocked writes with guidance to use `memory_write.py`.

#### 3.4.2 Staging Guard (`memory_staging_guard.py`)

**Hook type:** PreToolUse:Bash

**Behavior:**
- Blocks Bash commands that write to `.claude/memory/.staging/` via heredoc, cat, echo, printf, tee, cp, mv, redirect, or ln.
- Prevents Guardian bash_guardian.py false positives caused by heredoc content triggering write detection.
- Does NOT block `python3` script execution (which is the approved write path).

#### 3.4.3 Validation Hook (`memory_validate_hook.py`)

**Hook type:** PostToolUse:Write

**Behavior:**
- Detection-only (PostToolUse deny cannot prevent writes, only inform).
- Fires on Write tool calls targeting files inside `.claude/memory/`.
- Skips staging files (`.staging/` subdirectory) -- with diagnostic nlink warning.
- Skips `memory-config.json`.
- For JSON files: runs Pydantic schema validation (lazy-bootstraps pydantic from plugin venv).
- Invalid files are quarantined (renamed to `.invalid.<timestamp>`).
- Non-JSON files in memory directory: denied outright.
- Fallback basic validation when pydantic unavailable (checks required fields, category match, tags array, content object).

### 3.5 Session Rolling Window

**Script:** `memory_enforce.py`

**Behavior:**
- Enforces max_retained limit for session_summary category (default 5, configurable).
- Scans category folder for active files, sorted by `created_at` (oldest first; missing timestamps = oldest).
- Retires oldest sessions when count exceeds limit.
- Runs under FlockIndex lock for atomicity.
- Advisory deletion guard: warns about unique content in retired sessions.
- Dynamic retirement cap: `max(10, max_retained * 10)` prevents runaway loops.
- Dry-run mode available.
- Automatically triggered after `memory_write.py --action create --category session_summary`.

### 3.6 Index Management

**Script:** `memory_index.py`

**Operations:**
- `--rebuild`: Scans all category folders, regenerates `index.md` with enriched format (only active records).
- `--validate`: Compares index entries against actual files, reports mismatches.
- `--query <keyword>`: Simple keyword search against index lines.
- `--health`: Comprehensive health report (counts by category, heavily-updated memories, recent retirements, index sync status).
- `--gc`: Garbage collection of retired memories past the grace period (default 30 days).

**Index format:**
```
# Memory Index
<!-- Auto-generated by memory_index.py. Do not edit manually. -->
- [DECISION] JWT authentication decision -> .claude/memory/decisions/jwt-auth.json #tags:auth,jwt,security
```

**Auto-rebuild:** Both `memory_candidate.py` and `memory_retrieve.py` auto-rebuild index.md if missing (derived artifact pattern).

### 3.7 Draft Assembly

**Script:** `memory_draft.py`

**Purpose:** Separates ASSEMBLY from ENFORCEMENT. Takes partial input from LLM subagents and produces complete, schema-compliant JSON.

**CREATE assembly:** Generates all metadata (schema_version, id from slugified title, timestamps, record_status=active, times_updated=0, initial change entry).

**UPDATE assembly:** Preserves immutable fields from existing, unions tags/related_files, shallow-merges content, appends change entry, increments times_updated.

**Input validation:** Restricts input paths to `.staging/` or `/tmp/`. Restricts candidate paths to `.claude/memory/`.

### 3.8 Candidate Selection

**Script:** `memory_candidate.py`

**Purpose:** ACE (Analyze-Candidate-Execute) candidate selection for update/retire decisions.

**Behavior:**
1. Parses `index.md`, filters to target category.
2. Tokenizes new info summary (3+ char tokens for higher precision).
3. Scores entries: exact title match (2pts), tag match (3pts), prefix match (1pt).
4. Selects top-1 candidate if score >= 3.
5. Determines structural CUD:
   - No candidate + no lifecycle event = CREATE
   - No candidate + lifecycle event = NOOP
   - Candidate + delete allowed = UPDATE_OR_DELETE
   - Candidate + delete disallowed = UPDATE
6. Produces vetoes (DELETE blocked for decision, preference, session_summary).
7. Builds excerpt from candidate file (key content fields, last change summary).

### 3.9 Configuration System

**File:** `.claude/memory/memory-config.json` (per-project)
**Defaults:** `assets/memory-config.default.json`

**Config categories:**

**Script-read (Python):**
- `triage.enabled` (bool, default true)
- `triage.max_messages` (int, clamped 10-200, default 50)
- `triage.thresholds.*` (float, clamped 0.0-1.0, NaN/Inf rejected)
- `triage.parallel.*` (models validated against {haiku, sonnet, opus})
- `retrieval.enabled` (bool, default true)
- `retrieval.max_inject` (int, clamped 0-20, default 3)
- `retrieval.judge.*` (enabled, model, timeout, pool size, etc.)
- `retrieval.confidence_abs_floor` (float, default 0.0 = disabled)
- `retrieval.output_mode` ("legacy" or "tiered")
- `delete.grace_period_days` (int, default 30)
- `logging.*` (enabled, level, retention_days)
- `categories.*.description` (used in triage context files and retrieval output)

**Agent-interpreted (LLM reads):**
- `memory_root` (path, default `.claude/memory`)
- `categories.*.enabled` (bool)
- `categories.*.folder` (informational mapping)
- `categories.*.auto_capture` (bool)
- `categories.*.retention_days` (int, 0 = permanent)
- `categories.session_summary.max_retained` (int, default 5)
- `auto_commit` (bool, default false)
- `max_memories_per_category` (int, default 100)
- `retrieval.match_strategy` (string)
- `delete.archive_retired` (bool, default true)

### 3.10 Logging and Observability

**Script:** `memory_logger.py`

**Format:** JSONL (one JSON object per line)
**Location:** `{memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl`
**Event category:** Derived from `event_type.split('.')[0]` (e.g., "triage" from "triage.score")

**Design principles:**
- Fail-open: all errors silently swallowed, never blocks hook execution.
- Atomic append: O_APPEND flag for concurrent safety.
- Level filtering: debug < info < warning < error.
- Auto-cleanup: daily scan removes files older than retention_days (default 14).
- Symlink protection: skips symlinks during cleanup.
- Session correlation: extracts session ID from transcript path filename.

**Key events logged:**
- `triage.score`: Category scores, triggered categories, text length, metrics.
- `triage.error`: Triage failures.
- `retrieval.*`: Search queries, results, skip reasons, errors.
- `search.query`: CLI search queries.
- `guard.write_deny`, `guard.write_allow_staging`: Write guard decisions.
- `guard.staging_deny`: Staging guard denials.
- `validate.*`: PostToolUse validation results, quarantines, staging skips.
- `triage.idempotency_skip`: Fired when triage is skipped due to idempotency guards (5 variants: `stop_flag`, `sentinel`, `save_result`, `lock_held`, `sentinel_recheck`).
- `save.start`, `save.complete`: Emitted by `memory_orchestrate.py` at the beginning and end of the save pipeline.
- `retrieval.inject`, `retrieval.judge_result`, `retrieval.fallback`: Retrieval pipeline events for injection, judge filtering, and fallback behavior.

**Phase timing:**
`last-save-result.json` includes a `phase_timing` dict with `triage_ms`, `orchestrate_ms`, `write_ms`, `total_ms` for end-to-end save flow profiling.

**Log analyzer (`memory_log_analyzer.py`):**
- `--metrics` mode: Operational dashboard showing save duration stats, re-fire distribution, category frequency, success rates, and phase timing averages.
- `--watch` mode: Real-time log tailing with `--filter` prefix filtering for targeted monitoring.

### 3.11 Slash Commands

| Command | Description |
|---------|-------------|
| `/memory` | Status display: counts, health, index sync |
| `/memory --retire <slug>` | Soft-retire a memory |
| `/memory --archive <slug>` | Archive for permanent preservation |
| `/memory --unarchive <slug>` | Restore from archive |
| `/memory --restore <slug>` | Restore from retirement |
| `/memory --gc` | Garbage collect expired retirements |
| `/memory --list-archived` | List all archived memories |
| `/memory:save <category> <content>` | Manually save a memory |
| `/memory:config <instruction>` | Configure settings via natural language |
| `/memory:search <query>` | Full-text search with FTS5 |

### 3.12 Memory JSON Schema

**Base fields (all categories):**
```json
{
  "schema_version": "1.0",
  "category": "<category>",
  "id": "<kebab-case-slug>",
  "title": "<max 120 chars>",
  "record_status": "active|retired|archived",
  "created_at": "<ISO 8601 UTC>",
  "updated_at": "<ISO 8601 UTC>",
  "tags": ["<min 1, max 12>"],
  "related_files": ["<paths>"],
  "confidence": 0.0-1.0,
  "content": { /* category-specific */ },
  "changes": [{ "date", "summary", "field?", "old_value?", "new_value?" }],
  "times_updated": 0,
  "retired_at?": "<ISO 8601>",
  "retired_reason?": "<string>",
  "archived_at?": "<ISO 8601>",
  "archived_reason?": "<string>"
}
```

**Category-specific content schemas:**

| Category | Key Fields |
|----------|-----------|
| session_summary | goal, outcome (success/partial/blocked/abandoned), completed[], in_progress[], blockers[], next_actions[], key_changes[] |
| decision | status (proposed/accepted/deprecated/superseded), context, decision, alternatives[{option, rejected_reason}], rationale[], consequences[] |
| runbook | trigger, symptoms[], steps[], verification, root_cause, environment |
| constraint | kind (limitation/gap/policy/technical), rule, impact[], workarounds[], severity (high/medium/low), active, expires |
| tech_debt | status (open/in_progress/resolved/wont_fix), priority (critical-low), description, reason_deferred, impact[], suggested_fix[], acceptance_criteria[] |
| preference | topic, value, reason, strength (strong/default/soft), examples{prefer[], avoid[]} |

---

## 4. Non-Functional Requirements

### 4.1 UX: Minimal Screen Noise

- **Silent auto-capture:** Memory operations during auto-capture should produce no visible output to the user except a brief save confirmation in the next session.
- **No approval popups:** Write guard auto-approves staging file writes. All memory operations go through approved tool paths (Bash for `memory_write.py` scripts).
- **Guardian compatibility:** The `memory-drafter` agent uses `tools: Read, Write` only (no Bash) to structurally prevent Guardian bash_guardian.py conflicts. Staging writes use the Write tool (not Bash heredoc) to avoid Guardian false positives. Path strings are constructed at runtime to avoid static pattern matching.
- **Deterministic save execution:** Phase 2 COMMIT runs `memory_orchestrate.py` as a single Python subprocess, which is invisible to Guardian. No haiku saver subagent or heredoc Bash commands needed.
- **Progressive disclosure:** Search results show compact summaries first; full JSON only on explicit request.

### 4.2 Performance

**Hook timeouts (from hooks.json):**
| Hook | Timeout |
|------|---------|
| Stop (triage) | 30s |
| UserPromptSubmit (retrieve) | 15s |
| PreToolUse:Write (guard) | 5s |
| PreToolUse:Bash (staging guard) | 5s |
| PostToolUse:Write (validate) | 10s |

**Subagent costs:**
- Each triggered category spawns 1 drafting subagent (Phase 1 DRAFT). Only subagent type used.
- Worst case: all 6 categories = 6 drafting subagent calls (rare).
- When optional verification is enabled: risk-eligible categories (decision/constraint, DELETE, low-confidence) spawn additional verification subagents.
- Save execution: deterministic Python subprocess (no subagent needed).
- Per-category model selection optimizes cost (haiku for simple categories, sonnet for complex).

**Search performance:**
- FTS5 in-memory SQLite index: sub-millisecond query execution.
- Body text extraction capped at 2000 chars per entry.
- Context files capped at 50KB.
- Search results capped at 30 from FTS5, further limited by threshold and top-K.

### 4.3 Security

#### 4.3.1 Prompt Injection Defenses

- **Title/tag sanitization:** Strip control chars, zero-width Unicode, bidirectional overrides, combining marks, variation selectors. Escape XML-sensitive chars (`<`, `>`, `&`, `"`). Remove index-injection markers (` -> `, `#tags:`). Remove confidence label spoofing patterns (`[confidence:...]`).
- **Output boundaries:** User content placed inside XML element bodies; system attributes (category, confidence) in XML attributes. Structural separation prevents data boundary breakout.
- **Transcript data isolation:** `<transcript_data>` tags mark untrusted content. Drafter agent explicitly instructed to treat transcript content as raw data.
- **Judge integrity:** Untrusted data wrapped in `<memory_data>` tags with explicit instruction not to follow embedded instructions. Deterministic shuffling prevents position bias.
- **Description sanitization:** Category descriptions (user-configurable) are sanitized before injection into triage context files and retrieval output.

#### 4.3.2 Config Manipulation

- `max_inject` clamped to [0, 20] (prevents memory flooding).
- `max_messages` clamped to [10, 200].
- Thresholds clamped to [0.0, 1.0]; NaN and Inf rejected.
- Model names validated against allowlist {haiku, sonnet, opus}.
- `max_retained` validated as integer >= 1 (booleans explicitly rejected).
- `grace_period_days` clamped to >= 0.

#### 4.3.3 Index Integrity

- ` -> ` and `#tags:` delimiter patterns stripped from user inputs (titles, tags) to prevent parsing corruption.
- Index lines sorted for deterministic ordering.
- Index treated as derived artifact: auto-rebuilt when missing.

#### 4.3.4 FTS5 Injection

- Query tokens restricted to safe chars (`[a-z0-9_.-]`).
- All FTS5 queries use parameterized execution (no string interpolation into SQL).
- Stop words filtered before query construction.

#### 4.3.5 Path Security

- Path containment: all file operations verify target is within memory root via `resolve().relative_to()`.
- Path traversal: `..` components rejected in input/candidate paths.
- Directory component validation: rejects brackets and injection characters in directory names (S5F defense).
- Hard link defense: PreToolUse write guard checks `st_nlink` for existing staging files.
- Symlink defense: Secure file creation uses `O_NOFOLLOW`. Cleanup skips symlinks.

#### 4.3.6 Thread Safety

- LLM judge parallel batch splitting uses ThreadPoolExecutor with no shared mutable state.
- Index mutations use FlockIndex (mkdir-based lock, portable across all FS including NFS).

#### 4.3.7 Anti-Resurrection

- CREATE at a recently-retired path (< 24 hours) is blocked with `ANTI_RESURRECTION_ERROR`.
- Check performed inside FlockIndex to prevent TOCTOU races.

### 4.4 Reliability

#### 4.4.1 Fail-Open Design

Every hook script follows fail-open principles:
- Unexpected exceptions are caught and logged, never propagated.
- Missing files, corrupt JSON, unavailable pydantic: all handled gracefully.
- Logger itself is fail-open (never blocks hook execution).
- Guard scripts exit 0 on any parse error (allows the operation through).

#### 4.4.2 OCC (Optimistic Concurrency Control)

- UPDATE operations accept `--hash <md5>` parameter.
- Current file MD5 compared against expected hash inside FlockIndex.
- Mismatch produces `OCC_CONFLICT` error with retry guidance.

#### 4.4.3 Atomic Writes

- All file mutations use `atomic_write_json()` / `atomic_write_text()`: write to temp file, then `os.rename()`.
- Triage data written atomically via `os.replace()`.
- Context files created with `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` (secure creation, restrictive permissions).

#### 4.4.4 FlockIndex

- mkdir-based lock (atomic on all filesystems including NFS).
- 15-second timeout, 50ms poll interval.
- Stale lock detection: breaks locks older than 60 seconds with warning.
- `require_acquired()` method for strict enforcement (used by memory_enforce.py).

#### 4.4.5 Venv Bootstrap

- `memory_write.py`, `memory_draft.py`, `memory_enforce.py`, `memory_validate_hook.py` require pydantic v2.
- If pydantic not importable, scripts re-exec under plugin venv (`.venv/bin/python3`) via `os.execv()`.
- Validate hook uses lazy site-packages injection instead (avoids process replacement that would lose stdin data).

---

## 5. Data Architecture

### 5.1 Storage Layout

Memory storage and staging are **separate directory trees**. Memory storage lives inside the project; staging lives in a secure per-user external directory.

#### Memory Storage (project-local)

```
.claude/memory/
  memory-config.json          # Per-project configuration
  index.md                    # Enriched index (auto-generated, derived artifact)
  sessions/                   # session_summary memories
  decisions/                  # decision memories
  runbooks/                   # runbook memories
  constraints/                # constraint memories
  tech-debt/                  # tech_debt memories
  preferences/                # preference memories
  logs/                       # Structured JSONL logs (optional)
    triage/
    retrieval/
    search/
    guard/
    validate/
```

#### Staging Directory (external, per-user)

Staging files are stored **outside** the project tree in a secure per-user directory to eliminate the `/tmp/` symlink attack class. The staging directory path is:

```
<staging_base>/.claude-memory-staging-<hash>/
```

Where `<hash>` is `SHA-256(f"{os.geteuid()}:{os.path.realpath(cwd)}")[:12]`.

**4-tier staging base resolution** (via `memory_staging_utils._resolve_staging_base()`):

| Priority | Candidate | Conditions |
|----------|-----------|------------|
| 1 | `XDG_RUNTIME_DIR` | Set, absolute, 0700, owned by euid, is directory (strict: rejects WSL2's 0777) |
| 2 | `/run/user/$UID` | Linux systemd, exists, 0700, owned by euid (even if `XDG_RUNTIME_DIR` not set) |
| 3 | macOS `CS_DARWIN_USER_TEMP_DIR` | Via `os.confstr()`, bypasses `TMPDIR` env var, owner-only permissions |
| 4 | `$XDG_CACHE_HOME/claude-memory/staging/` | Universal fallback (defaults to `~/.cache/claude-memory/staging/`), created with 0700 |

**No `/tmp/` fallback** -- the goal is to eliminate the `/tmp/` attack class entirely.

```
<staging_base>/.claude-memory-staging-<hash>/
  triage-data.json              # Triage output (categories, scores)
  context-<category>.txt        # Per-category transcript excerpts
  intent-<category>.json        # Phase 1 drafter output (SAVE or NOOP)
  input-<category>.json         # Orchestrator input for draft assembly
  new-info-<category>.txt       # Extracted new information per category
  draft-<category>-<ts>.json    # Assembled draft memory JSON
  last-save-result.json         # Save outcome (with phase_timing)
  .triage-handled               # Sentinel: triage consumed by save flow
  .triage-pending.json          # Fallback: drafters failed, retrieval detects
  .index.lockdir/               # FlockIndex lock directory
```

> **Legacy note:** In v5.x, staging was located at `.claude/memory/.staging/` inside the project tree. The v6 external staging layout eliminates symlink/TOCTOU attacks on shared `/tmp/` directories. Legacy `.staging/` paths are still recognized by guards for backward compatibility.

### 5.2 Record Lifecycle

```
                    +---------+
         CREATE --> | active  | <-- RESTORE (from retired)
                    +---------+    <-- UNARCHIVE (from archived)
                     |       |
              RETIRE |       | ARCHIVE
                     v       v
               +---------+  +-----------+
               | retired |  | archived  |
               +---------+  +-----------+
                     |
               GC (30d) --> PURGE (file deleted)
```

States:
- **active**: Indexed and retrievable (default for all new memories).
- **retired**: Excluded from index; GC-eligible after grace period (default 30 days).
- **archived**: Excluded from index; NOT GC-eligible (preserved indefinitely).

---

## 6. Current Pain Points (Evidence from Codebase)

### 6.1 Stop Hook Re-fire Loop

**Problem:** After the triage hook blocks a stop to save memories, the user might try to stop again while saves are in progress. Without mitigation, the triage hook would fire again, potentially creating duplicate saves or infinite loops.

**Evidence:** The codebase has FIVE overlapping mechanisms to prevent this:
1. `check_stop_flag()` / `set_stop_flag()`: File-based flag (`.claude/.stop_hook_active`) with 5-minute TTL.
2. JSON sentinel (`<staging_dir>/.triage-handled`): Session-scoped state machine with TTL check prevents duplicate triage within a session.
3. `_check_save_result_guard()`: If `last-save-result.json` exists and is recent (same session), skip -- the session has already saved.
4. `_acquire_triage_lock()`: `O_CREAT|O_EXCL` exclusive lock on `.stop_hook_lock` with 120s stale timeout.
5. `sentinel_recheck`: Under triage lock, re-checks sentinel (double-check pattern prevents race between lock acquisition and sentinel write).

**Informational metric:** `_increment_fire_count()` tracks per-workspace fire count (`.triage-fire-count`), included in all triage log events. Does not block.

All five blocking guards exist because no single mechanism was sufficient in all edge cases. The layers address different failure modes: concurrent stop events, rapid re-fires, same-session duplicates, and lock-sentinel races.

### 6.2 Screen Noise from Multi-Phase Save Flow

**Problem:** The 5-phase save orchestration (Phase 0-3) involves multiple subagent spawns, Bash commands, and file operations. Each phase generates console output.

**Evidence:**
- SKILL.md explicitly instructs Phase 3 subagent: "Combine ALL numbered commands into a SINGLE Bash tool call using `;` separators. This minimizes console noise."
- SKILL.md rule: "Silent operation: Do NOT mention memory operations in visible output during auto-capture."
- The Phase 3 subagent instruction ends with: "Return ONLY a single-line summary."

Despite these mitigations, the multi-phase flow inherently creates visible tool calls (Agent spawns, Bash executions, Write tool calls for staging files).

**Status: RESOLVED in v6.** Architecture simplification (3-phase, `run_in_background: true` for drafters, single `memory_orchestrate.py` subprocess for COMMIT) eliminated multi-phase visible output.

### 6.3 Guardian Compatibility Issues

**Problem:** Claude Code's built-in Guardian (bash_guardian.py) scans Bash commands for potentially dangerous operations. Memory operations frequently trigger false positives because they write to `.claude/` paths and use JSON content that contains path strings.

**Evidence:**
- Runtime string construction throughout the codebase to avoid Guardian pattern matching:
  ```python
  _DOT_CLAUDE = ".clau" + "de"
  _MEMORY = "mem" + "ory"
  ```
- memory-drafter agent structurally limited to `tools: Read, Write` only (no Bash) to prevent Guardian conflicts.
- SKILL.md Rule 0: "Never combine heredoc (`<<`), Python interpreter, and `.claude` path in a single Bash command."
- Staging guard exists specifically to prevent Bash heredoc writes that trigger Guardian.
- Write-save-result uses Write tool + `--result-file` indirection instead of inline JSON on command line.

**Status: LARGELY RESOLVED in v6.** Python subprocess from `memory_orchestrate.py` is invisible to Guardian. Phase 1 drafter Write-only restriction remains. Guardian compatibility code in guard scripts still present.

### 6.4 Complex 5-Phase Orchestration

**Problem:** The save flow involves 5 phases, 3 types of subagents (memory-drafter Agent, verification Task, save Task), multiple Python scripts, and numerous staging files. This complexity creates maintenance burden and failure modes.

**Evidence:**
- SKILL.md is 457 lines of detailed orchestration instructions.
- Error handling at every phase boundary (skip on failure, preserve staging for retry, pending sentinel for next session).
- Cost note warns about 12 subagent calls when all 6 categories trigger.
- Multiple file handoff points (context files -> intent files -> new-info files -> input files -> draft files -> save commands).

**Status: RESOLVED in v6.** Simplified to 3-phase (SETUP, Phase 1 DRAFT, Phase 2 COMMIT) with 1 subagent type (memory-drafter). Max 6 subagent calls (one per category). `memory_orchestrate.py --action run` replaces Phase 1.5 LLM orchestration + Phase 3 haiku saver.

### 6.5 Tokenizer Divergence

**Problem:** Two different minimum token lengths exist intentionally but create cognitive overhead.

**Evidence:** CLAUDE.md explicitly documents this:
> `memory_candidate.py` uses a 3+ char token minimum (`len(w) > 2`), while `memory_search_engine.py` / `memory_retrieve.py` use 2+ chars (`len(w) > 1`). This is intentional -- candidate selection needs higher precision; retrieval benefits from broader recall.

### 6.6 PostToolUse Limitation

**Problem:** PostToolUse:Write hook is detection-only -- it cannot prevent writes, only inform after the fact.

**Evidence:** CLAUDE.md:
> PostToolUse deny cannot prevent writes, only inform. Only fires on Write tool calls; Python `open()` writes (memory_write.py, memory_draft.py) are not intercepted.

This means the PreToolUse guard is the critical defense, and the PostToolUse hook serves as a safety net that quarantines invalid files after they're already written.

---

## 7. Test Coverage

### 7.1 Test Files

| Test File | Coverage Area |
|-----------|--------------|
| `test_memory_triage.py` | Triage scoring, thresholds, category patterns, config loading, transcript parsing, context file generation |
| `test_memory_retrieve.py` | Retrieval hook flow, scoring, recency, confidence labeling, output formatting, save confirmation, orphan detection |
| `test_memory_write.py` | CRUD operations, merge protections, OCC, anti-resurrection, auto-fix, validation, atomic writes, staging utilities |
| `test_memory_candidate.py` | Candidate selection, scoring, structural CUD, vetoes, lifecycle events, excerpt building |
| `test_memory_draft.py` | Draft assembly (create/update), input validation, path security, schema compliance |
| `test_memory_index.py` | Index rebuild, validate, query, health report, GC |
| `test_memory_write_guard.py` | Write guard decisions, staging auto-approve, path detection, exemptions |
| `test_memory_staging_guard.py` | Staging guard pattern detection, Bash command blocking |
| `test_memory_validate_hook.py` | PostToolUse validation, quarantine, staging skip, category detection |
| `test_memory_judge.py` | LLM judge API calls, batch splitting, anti-position-bias, error handling |
| `test_memory_logger.py` | Structured logging, config parsing, session ID extraction, cleanup |
| `test_fts5_search_engine.py` | FTS5 search engine, tokenization, indexing, querying, threshold |
| `test_fts5_benchmark.py` | Search performance benchmarks |
| `test_rolling_window.py` | Session rolling window enforcement, config reading, deletion guard |
| `test_arch_fixes.py` | Architecture-level fix verification |
| `test_regression_popups.py` | Regression tests for approval popup prevention |
| `test_adversarial_descriptions.py` | Category description injection attacks |
| `test_v2_adversarial_fts5.py` | FTS5-specific adversarial attacks |
| `test_log_analyzer.py` | Log analysis tooling |
| `conftest.py` | Shared test fixtures |

---

## 8. Script Dependency Map

```
memory_triage.py (Stop hook)
  imports: memory_staging_utils, memory_logger (lazy, optional)
  reads: transcript JSONL, memory-config.json
  writes: <staging_dir>/context-*.txt, <staging_dir>/triage-data.json, <staging_dir>/.triage-handled, .claude/.stop_hook_active

memory_retrieve.py (UserPromptSubmit hook)
  imports: memory_staging_utils, memory_search_engine, memory_logger (lazy)
  reads: index.md, memory JSONs, <staging_dir>/last-save-result.json, <staging_dir>/.triage-pending.json
  calls: memory_index.py --rebuild (subprocess, on demand)
  calls: memory_judge.py (when judge enabled)

memory_search_engine.py (shared engine + CLI)
  imports: memory_logger (lazy)
  reads: index.md, memory JSONs (search mode)

memory_candidate.py (Phase 2 COMMIT, via orchestrator)
  reads: index.md, memory JSONs (excerpt)
  calls: memory_index.py --rebuild (subprocess, on demand)

memory_draft.py (Phase 2 COMMIT, via orchestrator)
  imports: memory_write (slugify, now_utc, build_memory_model, etc.)
  reads: input JSON, candidate JSON (update)
  writes: <staging_dir>/draft-*.json

memory_write.py (Phase 2 COMMIT + manual)
  imports: pydantic v2 (bootstraps from venv)
  reads: input JSON, target JSON (update/retire/archive/etc.)
  writes: memory JSONs (atomic), index.md
  calls: memory_enforce.py (subprocess, after session_summary create)

memory_enforce.py (rolling window)
  imports: memory_write (retire_record, FlockIndex, CATEGORY_FOLDERS)
  reads: memory JSONs, memory-config.json
  writes: memory JSONs (via retire_record), index.md

memory_write_guard.py (PreToolUse:Write)
  imports: memory_staging_utils, memory_logger (lazy)

memory_staging_guard.py (PreToolUse:Bash)
  imports: memory_staging_utils, memory_logger (lazy)

memory_validate_hook.py (PostToolUse:Write)
  imports: memory_staging_utils, memory_write (lazy, via pydantic bootstrap), memory_logger (lazy)

memory_judge.py (LLM judge)
  imports: memory_logger (lazy)
  calls: Anthropic Messages API

memory_orchestrate.py (Phase 2 COMMIT orchestrator)
  imports: memory_staging_utils, memory_write
  reads: <staging_dir>/intent-*.json, memory-config.json
  writes: <staging_dir>/manifest-*.json, <staging_dir>/last-save-result.json
  calls: memory_candidate.py (subprocess, for update/retire candidate selection)
  calls: memory_draft.py (subprocess, for draft assembly)
  calls: memory_write.py (subprocess, for CUD execution)
  calls: memory_enforce.py (subprocess, for rolling window enforcement)

memory_staging_utils.py (shared staging path utility)
  no internal imports (stdlib only)
  used by: memory_triage, memory_retrieve, memory_orchestrate, memory_write_guard, memory_staging_guard, memory_validate_hook

memory_logger.py (shared logging)
  no internal imports
  writes: logs/{category}/{date}.jsonl

memory_index.py (index management)
  reads: memory JSONs, memory-config.json (for GC)
  writes: index.md, deletes retired files (GC)
```

---

## 9. Plugin Manifest

```json
{
  "name": "claude-memory",
  "version": "5.1.0",
  "commands": ["./commands/memory.md", "./commands/memory-config.md", "./commands/memory-save.md"],
  "agents": ["./agents/memory-drafter.md"],
  "skills": ["./skills/memory-management", "./skills/memory-search"],
  "license": "MIT"
}
```

---

## 10. Key Design Decisions Embedded in Code

1. **Single Stop hook (command type) over 6 prompt-type hooks.** The original 6 prompt-type Stop hooks were "unreliable" (per code comments). The command-type hook runs deterministically and evaluates all categories in one pass.

2. **Keyword heuristics over LLM classification for triage.** Triage uses regex patterns, not LLM calls. This keeps the Stop hook fast (< 30s timeout), deterministic, and cost-free. The LLM is involved only in the drafting phase (Phase 1).

3. **Pydantic v2 as source of truth for schemas.** JSON Schema files in `assets/schemas/` exist for reference, but the Pydantic models in `memory_write.py` are the authoritative validation layer.

4. **FTS5 BM25 over simple keyword matching.** The search engine supports both (FTS5 primary, legacy keyword fallback), but FTS5 provides ranked relevance scoring that simple keyword intersection cannot.

5. **mkdir-based locking over flock().** FlockIndex uses `os.mkdir()` which is atomic on all filesystems including NFS, unlike POSIX `flock()` which has known issues on network filesystems.

6. **Per-category model selection.** Categories like "decision" and "constraint" use sonnet (more reasoning needed), while simpler categories use haiku (cost optimization).

7. **Separate ASSEMBLY from ENFORCEMENT.** `memory_draft.py` handles assembly (partial -> complete JSON), `memory_write.py` handles enforcement (validation, merge protections, atomic writes). This separation allows the drafter to focus on content without worrying about write safety.
