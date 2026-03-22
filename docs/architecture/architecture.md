# claude-memory Plugin -- Architecture Document (v5.1.0)

Target audience: Claude (AI agent). This document describes how every component works, how they interact, what state they manage, and where known weaknesses exist.

---

## 1. System Overview

### Component Map

```
Claude Code Runtime
 |
 |-- hooks/hooks.json                    (Hook registration manifest)
 |     |
 |     |-- Stop[*]         --> memory_triage.py        (1 deterministic command hook)
 |     |-- PreToolUse[Write] --> memory_write_guard.py  (Block direct memory writes)
 |     |-- PreToolUse[Bash]  --> memory_staging_guard.py (Block Bash writes to .staging/)
 |     |-- PostToolUse[Write] --> memory_validate_hook.py (Schema validate + quarantine)
 |     |-- UserPromptSubmit[*] --> memory_retrieve.py   (Auto-inject relevant memories)
 |
 |-- skills/memory-management/SKILL.md   (LLM-interpreted orchestration for Phases 0-3)
 |-- agents/memory-drafter.md            (Phase 1 subagent definition, tools: Read+Write only)
 |-- commands/
 |     |-- memory.md                     (Slash command: status, retire, archive, restore, gc)
 |     |-- memory-save.md               (Slash command: manual save)
 |     |-- memory-search.md             (Slash command: on-demand search)
 |     |-- memory-config.md             (Slash command: config modification)
 |
 |-- hooks/scripts/
 |     |-- memory_triage.py             (Stop hook: keyword heuristic scoring, context file gen)
 |     |-- memory_retrieve.py           (UserPromptSubmit: FTS5 BM25 search + output)
 |     |-- memory_search_engine.py      (Shared FTS5 engine, CLI search interface)
 |     |-- memory_judge.py              (LLM-as-judge relevance filter for retrieval)
 |     |-- memory_candidate.py          (ACE candidate selection for update/retire)
 |     |-- memory_draft.py              (Draft assembler: partial -> complete JSON)
 |     |-- memory_write.py              (Schema-enforced CRUD, OCC, atomic writes, index mgmt)
 |     |-- memory_enforce.py            (Rolling window enforcement for session_summary)
 |     |-- memory_index.py              (Index rebuild, validate, health, gc)
 |     |-- memory_write_guard.py        (PreToolUse: block direct writes to memory dir)
 |     |-- memory_staging_guard.py      (PreToolUse: block Bash writes to .staging/)
 |     |-- memory_validate_hook.py      (PostToolUse: schema validate, quarantine invalid)
 |     |-- memory_logger.py             (Shared JSONL structured logging, fail-open)
 |     |-- memory_log_analyzer.py       (Log anomaly detector, offline analysis)
 |
 |-- .claude/memory/                     (Per-project memory storage root)
 |     |-- memory-config.json           (Runtime config)
 |     |-- index.md                     (Enriched index: title + path + tags per entry)
 |     |-- .staging/                    (Transient working directory for save pipeline)
 |     |-- sessions/                    (session_summary JSON files)
 |     |-- decisions/                   (decision JSON files)
 |     |-- runbooks/                    (runbook JSON files)
 |     |-- constraints/                 (constraint JSON files)
 |     |-- tech-debt/                   (tech_debt JSON files)
 |     |-- preferences/                 (preference JSON files)
 |     |-- logs/                        (Structured JSONL logs by event category)
 |     |-- .index.lockdir/              (mkdir-based lock for index mutations)
 |
 |-- assets/
 |     |-- memory-config.default.json   (Default config template)
 |     |-- schemas/*.schema.json        (JSON Schema definitions for each category)
 |
 |-- .claude-plugin/plugin.json          (Plugin manifest: name, version, commands, agents, skills)
```

### Execution Model Summary

| Mechanism | What | When | Key Property |
|-----------|------|------|-------------|
| Hook (command) | `memory_triage.py` | Stop event | Deterministic. Reads stdin JSON, writes stdout JSON. No LLM. |
| Hook (command) | `memory_retrieve.py` | UserPromptSubmit | Deterministic search + optional LLM judge. Stdout added to context. |
| Hook (command) | `memory_write_guard.py` | PreToolUse:Write | Deterministic allow/deny. |
| Hook (command) | `memory_staging_guard.py` | PreToolUse:Bash | Deterministic deny for Bash writes to .staging/. |
| Hook (command) | `memory_validate_hook.py` | PostToolUse:Write | Detection-only. Schema validate, quarantine invalid. Cannot prevent write. |
| Skill (LLM) | `SKILL.md` | Loaded after triage blocks stop | LLM reads SKILL.md instructions, orchestrates Phases 0-3. |
| Agent subagent | `memory-drafter.md` | Phase 1 | LLM with tools: Read, Write only. No Bash (Guardian-safe). |
| Task subagent | Verification | Phase 2 | LLM checks draft quality against context. |
| Task subagent | Save | Phase 3 | Haiku model executes pre-computed Bash commands. |
| Bash (direct) | `memory_write.py`, `memory_candidate.py`, `memory_draft.py`, `memory_enforce.py` | Phases 1.5 and 3 | Deterministic Python scripts run via Bash tool. |

---

## 2. Data Flows

### 2.1 Auto-Capture Flow (Conversation -> Memory File)

```
USER types /stop or session ends
    |
    v
[Stop Hook fires]
    |
    v
memory_triage.py (command hook, 30s timeout)
    |-- Reads stdin JSON: { transcript_path, cwd }
    |-- Checks .stop_hook_active flag (TTL 5min): if fresh, allow stop (exit 0 silent)
    |-- Checks .triage-handled sentinel (TTL 5min): if fresh, skip (idempotency)
    |-- Reads transcript JSONL (last N messages, default 50)
    |-- Strips code blocks to reduce false positives
    |-- Scores 5 text-based categories via regex primary+booster with co-occurrence window
    |-- Scores SESSION_SUMMARY via activity metrics (tool_uses, distinct_tools, exchanges)
    |-- Compares each score against configurable threshold (default 0.4-0.6)
    |-- If ANY category exceeds threshold:
    |     |-- Sets .stop_hook_active flag file
    |     |-- Touches .triage-handled sentinel
    |     |-- Writes per-category context-<cat>.txt files to .staging/
    |     |-- Writes triage-data.json to .staging/ (atomic via tmp+rename)
    |     |-- Outputs stdout: {"decision": "block", "reason": "<message with <triage_data_file> tag>"}
    |-- If NO category exceeds threshold:
    |     |-- Outputs nothing (allow stop)
    v
[Claude Code blocks stop, loads memory-management skill]
    |
    v
SKILL.md Phase 0: Parse Triage Output
    |-- Clean stale intent-*.json files
    |-- Read triage-data.json (file ref from <triage_data_file> tag, fallback inline <triage_data>)
    |-- Extract categories[], parallel_config from JSON
    v
SKILL.md Phase 1: Parallel Intent Drafting
    |-- For EACH triggered category, spawn Agent subagent:
    |     Agent(subagent_type="memory-drafter", model=config.category_models[cat],
    |           prompt="Category: <cat>\nContext file: .staging/context-<cat>.txt\nOutput: .staging/intent-<cat>.json")
    |-- memory-drafter agent (Read+Write only, no Bash):
    |     |-- Reads context-<cat>.txt
    |     |-- Analyzes transcript data between <transcript_data> tags
    |     |-- Writes intent-<cat>.json: either SAVE intent or NOOP intent
    |-- All subagents run in PARALLEL
    v
SKILL.md Phase 1.5: Deterministic Execution (Main Agent, NO LLM judgment)
    |
    |-- Step 1: Collect + validate intent JSONs
    |     |-- Read .staging/intent-<cat>.json for each category
    |     |-- Filter NOOPs, validate SAVE intent required fields
    |
    |-- Step 2: Run candidate selection (parallel Bash calls)
    |     |-- Write new_info_summary to .staging/new-info-<cat>.txt
    |     |-- Run memory_candidate.py --category <cat> --new-info-file <path>
    |     |     |-- Reads index.md, filters to target category
    |     |     |-- Tokenizes new_info (3+ char tokens, higher precision than retrieval)
    |     |     |-- Scores entries: title word match (2pts), tag match (3pts), prefix (1pt)
    |     |     |-- Selects top-1 candidate if score >= 3
    |     |     |-- Determines structural_cud: CREATE / UPDATE_OR_DELETE / UPDATE / NOOP
    |     |     |-- Outputs JSON: { candidate, structural_cud, vetoes, hints, ... }
    |
    |-- Step 3: CUD Resolution (2-layer)
    |     |-- L1 = structural_cud from candidate.py (mechanical)
    |     |-- L2 = intended_action from intent JSON (LLM-derived, default "update")
    |     |-- Resolution table:
    |     |     CREATE + CREATE = CREATE
    |     |     UPDATE_OR_DELETE + UPDATE = UPDATE
    |     |     UPDATE_OR_DELETE + DELETE = DELETE
    |     |     CREATE + UPDATE = CREATE (structural: no candidate)
    |     |     CREATE + DELETE = NOOP (contradictory)
    |     |     UPDATE_OR_DELETE + CREATE = CREATE (subagent override)
    |     |     VETO + * = OBEY VETO (mechanical invariant)
    |     |     NOOP + * = NOOP
    |
    |-- Step 4: Execute drafts (parallel Bash calls)
    |     |-- Write partial_content to .staging/input-<cat>.json
    |     |-- Run memory_draft.py --action create/update --category <cat> --input-file <path>
    |     |     |-- Reads partial input JSON
    |     |     |-- Assembles complete schema-valid memory JSON:
    |     |     |     CREATE: adds schema_version, id (slugified title), timestamps, changes[]
    |     |     |     UPDATE: preserves immutables, unions tags/files, appends change, shallow-merges content
    |     |     |-- Validates against Pydantic model
    |     |     |-- Writes draft to .staging/draft-<cat>-<timestamp>.json
    |     |     |-- Outputs JSON: { status: "ok", draft_path: "..." }
    |
    |-- Step 5: Handle DELETE actions
    |     |-- Write .staging/draft-<cat>-retire.json: { action: "retire", target, reason }
    |
    |-- Step 6: Summary check -- if ALL NOOP/VETO/error, skip Phase 2
    v
SKILL.md Phase 2: Content Verification (parallel Task subagents)
    |-- For each draft, spawn Task subagent (verification_model from config, default sonnet):
    |     |-- Read draft JSON + original context file
    |     |-- Check: accuracy, hallucination, completeness, tag relevance
    |     |-- BLOCK if hallucination/factual error, ADVISORY if minor quality issue
    |     |-- Report PASS or FAIL
    |-- All verification subagents run in PARALLEL
    v
SKILL.md Phase 3: Save (single foreground Task subagent, haiku model)
    |
    |-- Step 1: Main agent builds command list from resolved actions + verification results
    |     |-- Excludes Phase 2 FAILs
    |     |-- Validates draft paths: must start with .staging/draft-, no ..
    |     |-- For CREATE: memory_write.py --action create --category <cat> --target <path> --input <draft>
    |     |-- For UPDATE: memory_write.py --action update --category <cat> --target <path> --input <draft> --hash <md5>
    |     |-- For DELETE: memory_write.py --action retire --target <path> --reason <why>
    |     |-- If session_summary created: memory_enforce.py --category session_summary
    |
    |-- Step 2: Spawn ONE foreground Task subagent (haiku)
    |     |-- Executes all commands combined with ; separator
    |     |-- On success: cleanup-staging + write-save-result
    |     |-- On failure: write .triage-pending.json sentinel, preserve staging
    |
    |-- memory_write.py (per-command execution):
    |     |-- CREATE:
    |     |     |-- Reads input from .staging/
    |     |     |-- auto_fix(): schema_version, timestamps, slugify id, sanitize title, dedup tags
    |     |     |-- Forces record_status="active"
    |     |     |-- Validates via Pydantic model
    |     |     |-- Path containment + traversal check
    |     |     |-- Anti-resurrection check (24h cooldown on retired file paths)
    |     |     |-- Acquires FlockIndex lock
    |     |     |-- Atomic write (tmp+rename)
    |     |     |-- Adds to index.md (sorted)
    |     |     |-- If session_summary: auto-triggers memory_enforce.py
    |     |
    |     |-- UPDATE:
    |     |     |-- Reads existing file + new input
    |     |     |-- auto_fix() on new data
    |     |     |-- Preserves immutable fields (created_at, schema_version, category, id)
    |     |     |-- check_merge_protections():
    |     |     |     - Immutable fields check
    |     |     |     - record_status immutable via UPDATE
    |     |     |     - Tags: grow-only below cap, eviction allowed at cap only with additions
    |     |     |     - related_files: grow-only except dangling path removal
    |     |     |     - changes[]: append-only, at least 1 new entry required
    |     |     |-- FIFO overflow: changes[] capped at 50
    |     |     |-- Slug rename if title changed >50% (word_difference_ratio)
    |     |     |-- OCC: if --hash provided, checks MD5 inside flock (prevents TOCTOU)
    |     |     |-- Acquires FlockIndex lock
    |     |     |-- Atomic write
    |     |     |-- Updates index entry
    |     |
    |     |-- RETIRE:
    |     |     |-- Sets record_status="retired", retired_at, retired_reason
    |     |     |-- Clears archived fields
    |     |     |-- Appends change entry
    |     |     |-- Acquires FlockIndex lock
    |     |     |-- Atomic write + removes from index
    |     |
    |     |-- ARCHIVE/UNARCHIVE/RESTORE: Similar lifecycle transitions with field management
    |
    |-- memory_enforce.py (if session_summary created):
    |     |-- Acquires FlockIndex lock (strict: require_acquired())
    |     |-- Scans sessions/ for active files, sorted by created_at oldest first
    |     |-- If active count > max_retained (default 5):
    |     |     |-- Retires oldest excess sessions
    |     |     |-- Deletion guard: warns if unique content, but proceeds anyway
    |     |     |-- Uses retire_record() from memory_write.py
```

### 2.2 Retrieval Flow (User Prompt -> Memory Injection)

```
USER submits a prompt
    |
    v
[UserPromptSubmit Hook fires]
    |
    v
memory_retrieve.py (command hook, 15s timeout)
    |
    |-- Block 1: Save Confirmation
    |     |-- Reads .staging/last-save-result.json (if exists, < 24h old)
    |     |-- Outputs <memory-note> with saved categories/titles
    |     |-- One-shot delete of result file
    |
    |-- Block 2: Orphan Crash Detection
    |     |-- If triage-data.json exists AND no last-save-result AND no .triage-pending
    |     |     AND age > 300s: outputs orphan warning note
    |
    |-- Block 3: Pending Save Notification
    |     |-- If .triage-pending.json exists: outputs pending save note
    |
    |-- Skip short prompts (< 10 chars)
    |
    |-- Rebuild index.md on demand if missing (derived artifact pattern)
    |
    |-- Load config: max_inject, match_strategy, abs_floor, output_mode, judge config
    |     |-- max_inject: clamped to [0, 20], default 3
    |     |-- judge_enabled: requires config enabled + ANTHROPIC_API_KEY set
    |
    |-- Parse index.md entries (once)
    |
    |-- FTS5 BM25 Path (default):
    |     |-- Tokenize prompt using compound tokenizer (preserves user_id, e.g.)
    |     |-- Build FTS5 query: compound tokens -> exact phrase, single tokens -> prefix wildcard
    |     |-- Build in-memory SQLite FTS5 index from parsed entries
    |     |-- score_with_body():
    |     |     1. Query FTS5 MATCH on title+tags
    |     |     2. Pre-filter ALL entries for path containment (security)
    |     |     3. Check retired/archived status on ALL entries
    |     |     4. For top-K non-retired: extract body text, compute body_bonus (up to +3)
    |     |     5. Re-rank: composite score = BM25_rank - body_bonus (more negative = better)
    |     |     6. apply_threshold(): sort, 25% noise floor, cap at max_inject/pool_size
    |     |-- If judge_enabled:
    |     |     |-- Fetch candidate_pool_size (default 15) entries
    |     |     |-- memory_judge.py judge_candidates():
    |     |     |     |-- If candidates > 6: parallel batch split (2 batches, ThreadPoolExecutor)
    |     |     |     |-- Anti-position-bias: deterministic SHA256-seeded shuffle per batch
    |     |     |     |-- format_judge_input(): XML-escape all user content, wrap in <memory_data>
    |     |     |     |-- call_api(): Anthropic Messages API (haiku-4-5), 128 max_tokens, 3s timeout
    |     |     |     |-- parse_response(): extract {"keep": [indices]}, map shuffled->real indices
    |     |     |     |-- On failure: returns None -> caller uses fallback_top_k (default 2)
    |     |     |-- Filter results to judge-kept entries
    |     |     |-- Re-cap to max_inject
    |     |-- Output via _output_results():
    |     |     |-- Each entry: <result category="..." confidence="high|medium|low">title -> path #tags:...</result>
    |     |     |-- Tiered mode: HIGH=<result>, MEDIUM=<memory-compact>, LOW=silence
    |     |     |-- confidence_label(): ratio to best score, with abs_floor cap
    |     |     |-- All titles sanitized: control chars stripped, XML-escaped, index markers removed
    |
    |-- Legacy Keyword Fallback (when FTS5 unavailable):
    |     |-- Tokenize with legacy tokenizer (simple alphanumeric, 2+ chars)
    |     |-- score_entry(): title word (2pts), tag (3pts), prefix (1pt), reverse prefix (1pt)
    |     |-- score_description(): category description bonus (capped at 2, only for already-matched entries)
    |     |-- Deep check top-20: read JSON for recency (+1 if < 30 days) and retired status
    |     |-- Same judge pipeline as FTS5 path
```

### 2.3 Guard Flow (PreToolUse / PostToolUse)

```
[PreToolUse:Write fires on every Write tool call]
    |
    v
memory_write_guard.py (5s timeout)
    |-- Reads stdin JSON: { tool_input: { file_path } }
    |-- Resolves path via os.path.realpath()
    |-- ALLOW: /tmp/.memory-write-pending*.json, /tmp/.memory-draft-*.json, /tmp/.memory-triage-context-*.txt
    |-- ALLOW (auto-approve): .staging/ files passing 4 gates:
    |     Gate 1: Extension whitelist (.json, .txt only)
    |     Gate 2: Filename pattern whitelist (intent-*, input-*, draft-*, context-*, etc.)
    |     Gate 3: Hard link defense (nlink > 1 on existing files -> require user approval)
    |     Gate 4: New file pass-through (doesn't exist yet -> allow)
    |-- ALLOW: memory-config.json directly in memory root (not in subfolders)
    |-- DENY: any other path containing /.claude/memory/ segment
    |     Output: {"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "..."}}
    |-- PASS-THROUGH: all other paths (exit 0 silent)

[PreToolUse:Bash fires on every Bash tool call]
    |
    v
memory_staging_guard.py (5s timeout)
    |-- Reads stdin JSON: { tool_name: "Bash", tool_input: { command } }
    |-- Regex scan for Bash write patterns targeting .claude/memory/.staging/:
    |     cat/echo/printf > .staging/, tee .staging/, cp/mv/install .staging/,
    |     ln/link .staging/, redirect >{1,2} .staging/
    |-- If detected: DENY with message directing to Write tool
    |-- Otherwise: exit 0 (pass-through)

[PostToolUse:Write fires AFTER every Write tool call]
    |
    v
memory_validate_hook.py (10s timeout)
    |-- Reads stdin JSON: { tool_input: { file_path } }
    |-- Resolves path
    |-- If NOT in memory directory: exit 0 (irrelevant)
    |-- If in .staging/: skip validation (diagnostic nlink warning only)
    |-- If in memory directory (bypassed PreToolUse guard):
    |     |-- Log bypass detection (WARNING)
    |     |-- Skip config file (memory-config.json in root)
    |     |-- DENY non-JSON files outright
    |     |-- validate_file():
    |     |     |-- Lazy-bootstrap pydantic from plugin .venv
    |     |     |-- If pydantic available: full Pydantic validation via memory_write.validate_memory()
    |     |     |-- Fallback: basic field existence check
    |     |-- If valid: WARNING logged (file ok but bypassed guard)
    |     |-- If invalid: quarantine(file) -> rename to .invalid.<timestamp>, DENY with error
    |
    |-- NOTE: PostToolUse CANNOT prevent writes. By the time it fires, the file is already written.
    |-- NOTE: Only intercepts Write tool calls. Python open() writes (memory_write.py, memory_draft.py)
    |         are invisible to this hook.
```

---

## 3. Component Details

### 3.1 memory_triage.py (Stop Hook)

**Input:** stdin JSON from Claude Code: `{ transcript_path: string, cwd: string }`

**Output:** stdout JSON: `{"decision": "block", "reason": "..."}` or nothing (allow stop).

**Dependencies:** stdlib only. Optional lazy import of `memory_logger`.

**Error handling:** Fail-open. Top-level try/except catches all exceptions and returns exit 0 (allows stop). Individual file operations (flag, sentinel, context files, triage-data.json) have individual try/except blocks that fall back gracefully.

**LLM judgment:** NONE. Entirely deterministic regex-based keyword heuristic scoring with co-occurrence boosting.

**Key internals:**
- `read_stdin()`: Uses `select()` with timeout because Claude Code does not send EOF. Reads 65536-byte chunks with 2s initial timeout, then 0.1s drain timeout.
- `parse_transcript()`: Reads JSONL, collects last N messages of type user/human/assistant using a deque(maxlen=N).
- `extract_text_content()`: Strips fenced code blocks and inline code before keyword matching to reduce false positives.
- `score_text_category()`: Per-line regex scan. Primary matches score `primary_weight` (0.2-0.35). If a booster pattern exists within +/- 4 lines, score `boosted_weight` (0.5-0.6) instead. Capped at `max_primary` + `max_boosted` hits. Normalized by dividing raw score by denominator.
- `score_session_summary()`: Formula: `min(1.0, tool_uses*0.05 + distinct_tools*0.1 + exchanges*0.02)`.
- `write_context_files()`: Writes `.staging/context-<cat>.txt` with category, score, description, and `<transcript_data>` block containing keyword-matched excerpts (text categories) or head+tail transcript excerpts (session_summary). Capped at 50KB. Written with `O_NOFOLLOW` to prevent symlink attacks.
- `build_triage_data()`: Assembles structured JSON with categories[], parallel_config for downstream skill consumption.
- Flag file `.stop_hook_active`: Created when triage blocks stop. Consumed on next triage invocation -- if fresh (< 5min), allows stop immediately (prevents re-fire loop). Uses exception-based stat+unlink to avoid TOCTOU.
- Sentinel `.triage-handled`: Touched when triage fires. If fresh on next invocation, skips evaluation (idempotency for same session).

### 3.2 memory_retrieve.py (UserPromptSubmit Hook)

**Input:** stdin JSON: `{ prompt: string (or user_prompt), cwd: string, transcript_path?: string }`

**Output:** stdout text (added to Claude's context automatically on exit 0).

**Dependencies:** stdlib + `memory_search_engine` (sibling import). Optional lazy import of `memory_logger`, `memory_judge`.

**Error handling:** Fail-open throughout. JSON parse errors, missing files, config errors all result in exit 0 (no injection, no crash).

**LLM judgment:** Optional LLM judge (`memory_judge.py`) when `retrieval.judge.enabled=true` AND `ANTHROPIC_API_KEY` is set. The judge is a filter applied after BM25 ranking, not a replacement.

**Key internals:**
- Three notification blocks run before search: save confirmation (Block 1), orphan crash detection (Block 2), pending save (Block 3).
- Short prompt filter: < 10 chars -> skip.
- Index auto-rebuild: if `index.md` missing but memory root exists, spawns `memory_index.py --rebuild` via subprocess (10s timeout).
- Config parsing: `max_inject` clamped [0,20], `abs_floor` validated for finiteness, output_mode must be "legacy" or "tiered".
- FTS5 path: compound tokenizer + `build_fts_query()` (OR-joined, prefix wildcards for simple tokens, exact phrases for compound tokens). `score_with_body()` does hybrid title+tags BM25 ranking plus body content bonus (up to +3 points from exact token matches in JSON content fields).
- Legacy path: fallback when FTS5 unavailable. Uses score_entry() (title 2pts, tag 3pts, prefix 1pt) + score_description() (capped at 2, only when entry already matched). Deep-checks top 20 for recency bonus and retired status.
- Output: XML elements `<memory-context>` wrapping `<result>` or `<memory-compact>` per entry. Titles sanitized via `_sanitize_title()`: control chars stripped, Unicode format chars removed, index-injection markers replaced, truncated to 120 chars, XML-escaped.

### 3.3 memory_search_engine.py (Shared FTS5 Engine)

**Input:** As module: called by `memory_retrieve.py` and CLI. As CLI: `--query`, `--root`, `--mode`, `--max-results`, `--format`.

**Output:** Module: Python objects. CLI: JSON or text to stdout.

**Dependencies:** stdlib + sqlite3 (FTS5 extension required). Optional `memory_logger`.

**Error handling:** Graceful fallback if FTS5 unavailable (`HAS_FTS5 = False`). CLI exits with error JSON.

**LLM judgment:** None.

**Key internals:**
- Two tokenizers: `_LEGACY_TOKEN_RE` (simple `[a-z0-9]+`) used for fallback scoring, `_COMPOUND_TOKEN_RE` (`[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]+`) used for FTS5 query construction. Both filter by `len(w) > 1` and stop words (including 2-char: "as", "am", "us", "vs").
- `build_fts_index()`: Creates in-memory SQLite FTS5 virtual table with columns `title, tags, [body,] path UNINDEXED, category UNINDEXED`.
- `build_fts_query()`: Smart wildcard strategy -- compound tokens (containing `_`, `.`, `-`) get exact phrase match `"user_id"`, simple tokens get prefix wildcard `"auth"*`. Tokens joined with OR.
- `query_fts()`: Executes `WHERE memories MATCH ? ORDER BY rank LIMIT ?`. Returns BM25 rank scores (more negative = better).
- `apply_threshold()`: Noise floor at 25% of best absolute score. Sorts by (score, category_priority). MAX_AUTO=3, MAX_SEARCH=10.
- `BODY_FIELDS`: Per-category list of content fields to extract for body search.
- `extract_body_text()`: Joins string/list values from content fields, capped at 2000 chars.

### 3.4 memory_judge.py (LLM-as-Judge)

**Input:** `judge_candidates(user_prompt, candidates, transcript_path, model, timeout, ...)`.

**Output:** Filtered list of candidates, or None on failure (caller falls back).

**Dependencies:** stdlib only (`urllib.request`, `concurrent.futures`). Optional `memory_logger`.

**Error handling:** All errors return None. Caller (memory_retrieve.py) applies fallback_top_k.

**LLM judgment:** YES -- this is the LLM judge. Uses Anthropic Messages API directly via `urllib.request`.

**Key internals:**
- `JUDGE_SYSTEM`: System prompt defining memory relevance classification. Instructs to output `{"keep": [indices]}`.
- `format_judge_input()`: Anti-position-bias via deterministic SHA256-seeded shuffle. All user content (prompt, context, titles, tags) HTML-escaped. Memory entries wrapped in `<memory_data>` tags.
- `call_api()`: Direct HTTP POST to `https://api.anthropic.com/v1/messages`. Model: `claude-haiku-4-5-20251001`. Max tokens: 128.
- `parse_response()`: Tries direct JSON parse, falls back to finding outermost `{...}`. Maps display indices back to real indices via order_map. Coerces string indices ("2" -> 2). Rejects booleans.
- Parallel batching: When `len(candidates) > _PARALLEL_THRESHOLD (6)`, splits into 2 equal batches. Each batch gets an independent shuffle seed (`{prompt}_batch{offset}`). Uses `ThreadPoolExecutor(max_workers=2)` with a total deadline (`timeout + 2s pad`). Any batch failure -> falls back to sequential single-batch.
- Thread safety: No shared mutable state between batch threads. Each `_judge_batch()` has its own shuffle, format, API call, and parse.

### 3.5 memory_candidate.py (ACE Candidate Selection)

**Input:** CLI: `--category`, `--new-info` or `--new-info-file`, `[--lifecycle-event]`, `[--root]`.

**Output:** stdout JSON: `{ candidate, structural_cud, vetoes, hints, lifecycle_event, delete_allowed, pre_action }`.

**Dependencies:** stdlib only.

**Error handling:** Exits with error on missing index, invalid args. Logs warnings on unreadable candidate files but continues.

**LLM judgment:** None. Entirely deterministic scoring.

**Key internals:**
- Tokenizer: `len(w) > 2` (3+ char tokens) -- intentionally stricter than search engine's 2+ chars. Higher precision for candidate matching.
- `score_entry()`: Exact title word match (2pts), exact tag match (3pts), prefix match on title+tags for 4+ char tokens (1pt).
- Candidate selection: Top-1 entry with score >= 3. Below 3 = no candidate.
- `build_excerpt()`: Reads candidate JSON file, extracts category-specific key fields (capped at 200 chars each), last change summary.
- Structural CUD determination:
  - No candidate, no lifecycle event -> CREATE
  - No candidate, lifecycle event present -> NOOP
  - Candidate found, delete allowed -> UPDATE_OR_DELETE
  - Candidate found, delete disallowed -> UPDATE
- DELETE_DISALLOWED categories: decision, preference, session_summary (triage-initiated delete forbidden).
- VALID_LIFECYCLE_EVENTS: resolved, removed, reversed, superseded, deprecated.
- Path safety: Resolves candidate path and checks it's under memory root.
- Auto-rebuilds index via subprocess if missing.

### 3.6 memory_draft.py (Draft Assembler)

**Input:** CLI: `--action create|update`, `--category`, `--input-file`, `[--candidate-file]`, `[--root]`.

**Output:** stdout JSON: `{ status: "ok", action, draft_path }`.

**Dependencies:** pydantic v2 (via venv bootstrap). Imports from `memory_write.py`: slugify, now_utc, build_memory_model, CATEGORY_FOLDERS, ChangeEntry, ValidationError.

**Error handling:** Returns exit code 1 with error on stderr for validation failures, missing files, security violations.

**LLM judgment:** None. Pure assembly logic.

**Key internals:**
- Venv bootstrap: Same pattern as `memory_write.py` -- if pydantic not importable, `os.execv()` under `.venv/bin/python3`.
- Input path validation: Must be in `.claude/memory/.staging/` or `/tmp/`. No `..` components.
- Candidate path validation: Must exist, be `.json`, resolve within `.claude/memory/`.
- `assemble_create()`: Sets schema_version, category, id (slugified title), record_status="active", timestamps, tags, related_files, confidence, content, initial change entry, times_updated=0.
- `assemble_update()`: Starts from existing data. Preserves immutable fields. Unions tags and related_files. Shallow-merges content (top-level content keys from input overlay existing). Appends change entry. Increments times_updated.
- Pydantic validation: Validates assembled JSON against `build_memory_model(category)` before writing.
- Draft output: Written to `.staging/draft-<category>-<timestamp>-<pid>.json` (non-atomic, uses regular `open()`).

### 3.7 memory_write.py (Schema-Enforced CRUD)

**Input:** CLI: `--action create|update|retire|archive|unarchive|restore|cleanup-staging|write-save-result`, plus action-specific args.

**Output:** stdout JSON with status. Exit code 0 on success, 1 on error.

**Dependencies:** pydantic v2 (bootstrapped from plugin `.venv` via `os.execv()`).

**Error handling:** Structured error output with error types: VALIDATION_ERROR, MERGE_ERROR, OCC_CONFLICT, ANTI_RESURRECTION_ERROR, PATH_ERROR, SECURITY_ERROR, etc.

**LLM judgment:** None. Entirely mechanical.

**Key internals:**
- Pydantic models: 6 content models (DecisionContent, SessionSummaryContent, etc.) with `ConfigDict(extra="forbid")`. Base memory model built dynamically per category via `create_model()`, cached in `_model_cache`.
- `auto_fix()`: Schema normalization layer. Sets defaults (schema_version, timestamps), slugifies id, clamps confidence [0,1], wraps string tags in array, deduplicates/sorts tags, sanitizes titles (control chars, Unicode format chars, index injection markers, confidence label spoofing patterns), enforces TAG_CAP (12).
- `validate_memory()`: Full Pydantic validation via `Model.model_validate(data)`.
- `check_merge_protections()`: Enforces immutable fields, grow-only tags (eviction at cap only), grow-only related_files (dangling removal allowed), append-only changes[], record_status immutable via UPDATE.
- `FlockIndex`: Portable mkdir-based lock. `os.mkdir()` is atomic on all filesystems including NFS. 15s timeout, 60s stale detection (breaks stale locks), 50ms poll interval. Falls back to proceeding without lock on timeout (legacy behavior). `require_acquired()` method for strict enforcement (used by `memory_enforce.py`).
- `atomic_write_text()` / `atomic_write_json()`: Uses `tempfile.mkstemp()` in target directory + `os.rename()`.
- Index management: `add_to_index()` (sorted insert), `remove_from_index()` (filter by path), `update_index_entry()` (replace matching line).
- Anti-resurrection: During CREATE inside flock, checks if target file exists with `record_status="retired"` and `retired_at` < 24h ago. Returns `ANTI_RESURRECTION_ERROR`.
- Slug rename on UPDATE: If title changed > 50% (by word_difference_ratio), generates new slug, checks for collision, renames file.
- Auto-enforcement: After creating session_summary, spawns `memory_enforce.py` via subprocess.
- `cleanup_staging()`: Removes transient files matching specific patterns. Path containment validated (must end with `memory/.staging`).
- `write_save_result()`: Validates result JSON schema (allowed keys, type enforcement, length caps), atomic write.
- `_read_input()`: Security gate -- input must be from `.claude/memory/.staging/`, no `..` components.
- `_check_dir_components()`: Rejects directory names with brackets or other injection characters (S5F defense).

### 3.8 memory_enforce.py (Rolling Window)

**Input:** CLI: `--category`, `[--max-retained]`, `[--dry-run]`, `[--max-retire]`.

**Output:** stdout JSON: `{ retired: [], active_count, max_retained }`.

**Dependencies:** pydantic v2 (via venv bootstrap + imports from memory_write).

**Error handling:** Strict lock requirement via `FlockIndex.require_acquired()`. Raises TimeoutError if lock not acquired (unlike memory_write.py which proceeds without lock).

**LLM judgment:** None.

**Key internals:**
- Root derivation: `$CLAUDE_PROJECT_ROOT` env var, or walk CWD upward looking for `.claude/memory/`.
- Config: reads `categories.<category>.max_retained` from `memory-config.json`. Rejects booleans. Default 5.
- `_scan_active()`: Scans category folder for active `.json` files. Sorted by `created_at` oldest first. Missing timestamps sort first (treated as oldest/most suspect).
- Dynamic retirement cap: `max(10, max_retained * 10)` to prevent runaway loops.
- Deletion guard: Advisory warning if session contains content in completed/blockers/next_actions fields. Does NOT block retirement.
- Uses `retire_record()` from memory_write.py directly (caller holds lock).

### 3.9 memory_index.py (Index Management)

**Input:** CLI: `--rebuild | --validate | --query KEYWORD | --health | --gc`, `--root`.

**Output:** stdout text.

**Dependencies:** stdlib only.

**Error handling:** Reports errors and continues.

**LLM judgment:** None.

**Key internals:**
- `scan_memories()`: Iterates all category folders, reads each `.json` file. Filters by record_status unless `include_inactive=True`.
- `rebuild_index()`: Scans active memories, writes sorted index.md with enriched format: `- [DISPLAY] title -> path #tags:t1,t2,...`.
- `validate_index()`: Compares index entries against actual active files. Reports missing/stale entries.
- `gc_retired()`: Reads `delete.grace_period_days` from config (default 30). Scans all folders for retired files past grace period. Deletes permanently via `unlink()`.
- `health_report()`: Statistics: entries by category, heavily updated (times_updated > 5), recent retirements, index sync status.
- `_sanitize_index_title()`: Collapses whitespace, strips ` -> ` and `#tags:` markers, truncates to 120 chars.

### 3.10 memory_logger.py (Structured Logging)

**Input:** `emit_event(event_type, data, *, level, hook, script, session_id, duration_ms, error, memory_root, config)`.

**Output:** JSONL file at `{memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl`.

**Dependencies:** stdlib only.

**Error handling:** EVERYTHING wrapped in try/except that catches `Exception` and passes silently. Never blocks hook execution.

**LLM judgment:** None.

**Key internals:**
- `parse_logging_config()`: Extracts enabled/level/retention_days from config dict. Returns `{"enabled": False, ...}` on any error.
- `get_session_id()`: Extracts stem from transcript path (e.g., "transcript-abc123").
- Level filtering: debug(0) < info(1) < warning(2) < error(3). Events below configured level are dropped.
- Duration sanitization: Rejects NaN/Infinity values.
- Results truncation: `data.results` capped at 20 entries per log line.
- Atomic append: Single `os.write()` syscall via `os.open()` with `O_CREAT | O_WRONLY | O_APPEND | O_NOFOLLOW`.
- Containment check: `log_dir.resolve().relative_to(logs_root.resolve())` prevents symlink escape.
- `cleanup_old_logs()`: Runs at most once per 24h (guarded by `.last_cleanup` file). Skips symlinks. Deletes `.jsonl` files older than retention_days.

### 3.11 memory_write_guard.py (PreToolUse:Write Guard)

**Input:** stdin JSON: `{ tool_input: { file_path } }`.

**Output:** stdout JSON with `permissionDecision: "allow" | "deny"` or nothing (pass-through).

**Dependencies:** stdlib only. Optional `memory_logger`.

**Error handling:** JSON parse failure -> exit 0 (pass-through).

**LLM judgment:** None.

**Key internals:**
- Path marker construction: `_DOT_CLAUDE = ".clau" + "de"` -- split string to avoid Guardian pattern matching on the source code itself.
- Staging auto-approve gates: 4 sequential safety checks (extension whitelist, filename pattern regex, hard link defense via nlink check, new file pass-through).
- Config file exemption: `memory-config.json` allowed only when directly in memory root (not in subfolders like `decisions/memory-config.json`).
- All other paths containing `/.claude/memory/` segment -> DENY with helpful error message.

### 3.12 memory_staging_guard.py (PreToolUse:Bash Guard)

**Input:** stdin JSON: `{ tool_name, tool_input: { command } }`.

**Output:** stdout JSON with `permissionDecision: "deny"` or nothing.

**Dependencies:** stdlib only. Optional `memory_logger`.

**Error handling:** JSON parse failure -> exit 0.

**LLM judgment:** None.

**Key internals:**
- Single regex `_STAGING_WRITE_PATTERN` detects: cat/echo/printf redirects, tee, cp/mv/install/dd, ln/link, and shell redirects (>, >>) targeting `.claude/memory/.staging/`.
- Rationale: Forces subagents to use Write tool for staging files, preventing Guardian false positives from heredoc body content.

### 3.13 memory_validate_hook.py (PostToolUse:Write Validator)

**Input:** stdin JSON: `{ tool_input: { file_path } }`.

**Output:** stdout JSON with `permissionDecision: "deny"` (on invalid) or nothing.

**Dependencies:** Optional pydantic v2 (lazy-bootstrapped from `.venv`). Imports `memory_write.validate_memory()` if pydantic available.

**Error handling:** Falls back to basic validation if pydantic unavailable.

**LLM judgment:** None.

**Key internals:**
- Staging files: Always skipped (not memory records). Diagnostic nlink warning only (not a gate).
- Bypass detection: If a write reaches this hook for a file in the memory directory, it means PreToolUse guard was bypassed. Logs warning.
- Quarantine: Invalid files renamed to `<path>.invalid.<timestamp>` to preserve evidence.
- Lazy pydantic bootstrap: Adds `.venv/lib/python3.*/site-packages` to sys.path. Does NOT use `os.execv()` (would replace process and lose stdin).
- `_basic_validation()`: Fallback -- checks required fields exist, category matches folder, tags is non-empty list, content is dict.

### 3.14 memory_log_analyzer.py (Log Anomaly Detector)

**Input:** CLI: `--root`, `[--days]`, `[--format]`.

**Output:** JSON or text report of detected anomalies.

**Dependencies:** stdlib only.

**Error handling:** Fail-open on malformed log lines (skipped silently).

**LLM judgment:** None.

**Key internals:**
- Anomaly detectors: skip rate spikes (90%+ critical), zero-length prompts (50%+ of skips), category never triggers, booster never hits, error spikes (10%+).
- Minimum sample size thresholds prevent false alarms on small datasets.
- Symlink-safe path traversal throughout.

---

## 4. Orchestration Model

### What Runs as Hooks (Deterministic, command-type)

| Hook | Script | When | Decision |
|------|--------|------|----------|
| Stop[*] | memory_triage.py | Every stop attempt | Block (stdout JSON) or allow (silent) |
| UserPromptSubmit[*] | memory_retrieve.py | Every user prompt | Add context to stdout or silent |
| PreToolUse[Write] | memory_write_guard.py | Every Write tool call | Allow, deny, or pass-through |
| PreToolUse[Bash] | memory_staging_guard.py | Every Bash tool call | Deny or pass-through |
| PostToolUse[Write] | memory_validate_hook.py | After every Write tool call | Quarantine invalid, or pass-through |

All hooks communicate via stdin JSON (hook input) and stdout JSON (hook output). Exit code 0 always. Decision encoded in stdout content.

### What Runs as Skill (LLM-interpreted SKILL.md instructions)

The memory-management skill (`SKILL.md`) is loaded when the Stop hook blocks stop. The main Claude agent reads SKILL.md and follows its Phase 0-3 orchestration instructions. This is NOT a script -- it's a prompt that the LLM interprets and executes step by step.

Key properties:
- Phase 0, 1.5, and 3 command-building are mechanical instructions the LLM must follow literally.
- Phase 1 and 2 spawn subagents.
- The LLM's judgment is involved in interpreting SKILL.md instructions and deciding execution flow, but the actual memory operations are all deterministic Python scripts.

### What Runs as Subagents

| Phase | Type | Model | What | Tools |
|-------|------|-------|------|-------|
| Phase 1 | Agent (memory-drafter) | Config per-category (default haiku) | Draft intent JSON from context | Read, Write ONLY |
| Phase 2 | Task | Config verification_model (default sonnet) | Verify draft quality | General |
| Phase 3 | Task | haiku | Execute save commands | General (Bash) |

Agent vs Task distinction:
- Agent subagents use a named agent file (`memory-drafter.md`) that defines their persona, instructions, and available tools.
- Task subagents are ad-hoc with an inline prompt and general tool access.

### What Runs as Direct Bash Commands

| Script | Called By | Phase |
|--------|-----------|-------|
| memory_candidate.py | Main agent (SKILL.md Phase 1.5 Step 2) | 1.5 |
| memory_draft.py | Main agent (SKILL.md Phase 1.5 Step 4) | 1.5 |
| memory_write.py | Phase 3 Task subagent | 3 |
| memory_enforce.py | Phase 3 Task subagent (and auto-triggered by memory_write.py after session_summary create) | 3 |
| memory_index.py | Slash commands, auto-rebuild in retrieve/candidate | On-demand |
| memory_search_engine.py | Slash commands | On-demand |

### Inconsistencies in the Orchestration Model

1. **Mixed execution contexts for the same operation**: `memory_write.py` is called both by the Phase 3 Task subagent (Bash tool) AND automatically by itself (subprocess for enforce after session_summary create). This creates a confusing dependency chain.

2. **SKILL.md as prose, not code**: Phases 0, 1.5, and 3 are written as LLM instructions that must be followed literally (e.g., "write this file, run this command"). This is fragile -- the LLM may interpret instructions differently across sessions, skip steps, or add unnecessary steps.

3. **Three subagent types for different phases**: Phase 1 uses Agent subagents (named agent file, restricted tools), Phase 2 uses Task subagents (general), Phase 3 uses a Task subagent (general but with Bash). The rationale (Phase 1 = tool restriction for Guardian safety) is valid but adds complexity.

4. **Deterministic steps run by LLM**: Phase 1.5 is explicitly labeled "no LLM judgment" but is still orchestrated by the main LLM agent, which must correctly interpret 6 steps of instructions, run parallel Bash calls, parse JSON output, apply the CUD resolution table, etc. Any misinterpretation produces incorrect saves.

5. **Guardian compatibility workarounds**: The entire .staging/ file architecture, the Write tool for staging files (instead of simpler Bash heredocs), the string-splitting for path markers in guard scripts (`".clau" + "de"`) -- all exist to work around Claude Code's Guardian security scanner. This is a significant source of complexity.

---

## 5. State Management

### 5.1 Staging Directory Lifecycle

Location: `.claude/memory/.staging/`

```
[Triage fires]
   |-- Creates: triage-data.json (atomic)
   |-- Creates: context-<cat>.txt (per triggered category)
   |-- Creates: .triage-handled (sentinel timestamp)
   v
[Phase 0: Skill loads]
   |-- Cleans: intent-*.json (stale from previous sessions)
   v
[Phase 1: Drafters run]
   |-- Creates: intent-<cat>.json (per category)
   v
[Phase 1.5: Main agent]
   |-- Creates: new-info-<cat>.txt (per category, for candidate.py)
   |-- Creates: input-<cat>.json (per category, for draft.py)
   v
[Phase 1.5: draft.py runs]
   |-- Creates: draft-<cat>-<timestamp>-<pid>.json (per category)
   v
[Phase 3: Save subagent]
   |-- Reads: draft-*.json files
   |-- On success: cleanup-staging removes all transient files
   |-- On success: Creates last-save-result.json (atomic)
   |-- On failure: Creates .triage-pending.json, preserves all staging files
   v
[Next session: retrieve.py]
   |-- Reads + deletes: last-save-result.json (one-shot confirmation)
   |-- Detects: orphaned triage-data.json (possible crash)
   |-- Detects: .triage-pending.json (pending save from failed session)
```

Staging cleanup patterns (what gets removed on success):
- `triage-data.json`, `context-*.txt`, `draft-*.json`, `input-*.json`, `intent-*.json`, `new-info-*.txt`, `.triage-handled`, `.triage-pending.json`

Files that survive cleanup:
- `last-save-result.json` (consumed by next session's retrieve hook)

### 5.2 Flag Files

| File | Created By | Consumed By | TTL | Purpose |
|------|-----------|-------------|-----|---------|
| `.claude/.stop_hook_active` | memory_triage.py (when blocking stop) | memory_triage.py (next invocation) | 5 min (300s) | Prevents re-fire loop. If user re-stops within 5min, allows through. |
| `.staging/.triage-handled` | memory_triage.py (when blocking stop) | memory_triage.py (next invocation) | 5 min (300s) | Idempotency sentinel. Prevents duplicate triage in same session. |
| `.staging/.triage-pending.json` | Phase 3 error handler (main agent) | memory_retrieve.py (next session) | None | Signals that a save failed. Contains `{timestamp, categories, reason}`. |
| `.staging/last-save-result.json` | Phase 3 save subagent | memory_retrieve.py (next session) | 24 hours (checked at read time) | One-shot save confirmation. Contains `{saved_at, categories, titles, errors}`. |
| `.index.lockdir/` | FlockIndex (mkdir) | FlockIndex (rmdir on exit) | 60s (stale detection) | Portable mutex for index mutations. |

### 5.3 Index File (index.md)

Format: Enriched markdown list.
```
# Memory Index

<!-- Auto-generated by memory_index.py. Do not edit manually. -->

- [CATEGORY_DISPLAY] Title Text -> .claude/memory/folder/slug.json #tags:tag1,tag2,tag3
```

Properties:
- Derived artifact: can be fully reconstructed from JSON files via `memory_index.py --rebuild`.
- Only contains active entries (retired/archived are removed from index).
- Sorted alphabetically by line content (case-insensitive).
- Mutated by: `add_to_index()`, `remove_from_index()`, `update_index_entry()` -- all inside FlockIndex lock.
- Read by: `memory_retrieve.py`, `memory_candidate.py`, `memory_search_engine.py`, slash commands.
- Auto-rebuilt if missing (by retrieve and candidate scripts).
- Can be .gitignored since it's derived.

### 5.4 Config File (memory-config.json)

Location: `.claude/memory/memory-config.json`

Two categories of config keys:
1. **Script-read** (parsed by Python scripts at runtime):
   - `triage.enabled`, `triage.max_messages` (10-200), `triage.thresholds.*` (0.0-1.0 per category)
   - `triage.parallel.*` (enabled, category_models, verification_model, default_model)
   - `retrieval.enabled`, `retrieval.max_inject` (0-20), `retrieval.judge.*`
   - `retrieval.confidence_abs_floor`, `retrieval.output_mode`, `retrieval.match_strategy`
   - `delete.grace_period_days`
   - `logging.enabled`, `logging.level`, `logging.retention_days`
   - `categories.*.description`

2. **Agent-interpreted** (read by LLM via SKILL.md, not by Python):
   - `memory_root`, `categories.*.enabled`, `categories.*.folder`, `categories.*.auto_capture`
   - `categories.*.retention_days`, `auto_commit`, `max_memories_per_category`
   - `delete.archive_retired`

Config validation: Scripts clamp values to valid ranges (e.g., `max_inject` clamped [0,20], `max_messages` clamped [10,200]). Invalid model names fall back to defaults. NaN/Infinity values rejected.

---

## 6. Concurrency & Race Conditions

### 6.1 FlockIndex (mkdir-based Lock)

Implementation in `memory_write.py`:
- Lock mechanism: `os.mkdir()` (atomic on all filesystems including NFS).
- Lock path: `.claude/memory/.index.lockdir/`
- Timeout: 15 seconds with 50ms poll interval.
- Stale detection: If lock directory mtime > 60s old, breaks it via `rmdir()`.
- On timeout: Proceeds WITHOUT lock (legacy behavior, logs warning).
- `require_acquired()`: Strict mode (used by `memory_enforce.py`). Raises `TimeoutError` if lock not acquired.

### 6.2 OCC (Optimistic Concurrency Control)

Used by UPDATE action in `memory_write.py`:
- Caller passes `--hash <md5>` (MD5 of file content at time of read).
- Inside FlockIndex lock, `file_md5()` computes current hash.
- If mismatch: returns `OCC_CONFLICT` error (caller must re-read and retry).
- This prevents lost updates when two sessions try to update the same file.

### 6.3 Parallel Subagent Execution

Phase 1 (Intent Drafting):
- Multiple Agent subagents spawned in parallel (one per triggered category).
- Each reads its own context file and writes its own intent file.
- No shared state. No contention.
- If one fails, it's skipped; others continue.

Phase 1.5 (Candidate Selection + Draft Assembly):
- Multiple Bash calls spawned in parallel (SKILL.md instructs this).
- `memory_candidate.py` reads index.md (read-only) -- safe for parallel execution.
- `memory_draft.py` writes unique draft files (PID + timestamp in filename) -- no collision.

Phase 2 (Verification):
- Multiple Task subagents spawned in parallel.
- Each reads its own draft + context file (read-only).
- No shared state.

Phase 3 (Save):
- Single Task subagent executes commands SEQUENTIALLY (combined with `;`).
- All index mutations happen inside FlockIndex lock.
- `memory_enforce.py` acquires its own FlockIndex lock (strict mode).

### 6.4 Race Condition Risks

1. **Stop hook re-fire between flag consumption and sentinel creation**: After `check_stop_flag()` unlinks the flag but before triage completes and creates the sentinel, another stop attempt could trigger a full re-evaluation. Mitigated by the sentinel file.

2. **Concurrent session stops**: If two Claude Code instances stop simultaneously for the same project, both could read the index, both could pass OCC checks on different files, and both could write. The FlockIndex lock serializes index mutations but not the entire pipeline.

3. **Enforce during Phase 3**: `memory_write.py` auto-triggers `memory_enforce.py` after session_summary CREATE. The explicit enforce in Phase 3's command list creates a double-enforcement. Both acquire the FlockIndex lock, so they won't corrupt state, but the second one is redundant.

4. **Staging file cleanup vs. pending saves**: If the save subagent crashes mid-execution, some commands may have succeeded (files written) while staging files remain. The `.triage-pending.json` sentinel captures this, but recovery (next session's `/memory:save`) re-triages from scratch, not from the partial state.

---

## 7. Integration Points

### 7.1 Claude Code Hook API

**Stdin JSON format** (provided by Claude Code to hook scripts):

For Stop hook:
```json
{ "transcript_path": "/tmp/transcript-abc123.json", "cwd": "/path/to/project" }
```

For UserPromptSubmit hook:
```json
{ "prompt": "user's prompt text", "cwd": "/path/to/project", "transcript_path": "/tmp/..." }
```

For PreToolUse hooks:
```json
{ "tool_name": "Write|Bash", "tool_input": { "file_path": "...", "command": "..." } }
```

For PostToolUse hooks:
```json
{ "tool_input": { "file_path": "..." } }
```

**Stdout JSON format** (hook output to Claude Code):

Block stop:
```json
{ "decision": "block", "reason": "Human-readable message" }
```

Permission decision (allow/deny):
```json
{ "hookSpecificOutput": { "hookEventName": "PreToolUse", "permissionDecision": "allow|deny", "permissionDecisionReason": "..." } }
```

Context injection (UserPromptSubmit): Plain text written to stdout is appended to the LLM's context.

**Exit codes:** Always 0. Decision communicated via stdout content.

**Timeouts:** Configured per-hook in `hooks.json` (5s for guards, 15s for retrieval, 30s for triage).

### 7.2 Claude Code Agent/Task Subagent API

Agent subagents (Phase 1):
```
Agent(
  subagent_type: "memory-drafter",    // References agents/memory-drafter.md
  model: "haiku|sonnet|opus",         // From config category_models
  prompt: "Category: ...\nContext file: ...\nOutput: ..."
)
```

Task subagents (Phase 2, 3):
```
Task(
  model: "sonnet|haiku",
  subagent_type: "general-purpose",
  prompt: "..."                       // Inline instructions
)
```

Key constraints:
- Agent subagents have restricted tool access (defined in agent file YAML frontmatter `tools: Read, Write`).
- Task subagents have general tool access.
- Subagents cannot access the main conversation context (they get only the prompt passed to them).

### 7.3 Guardian Interaction Surface

Claude Code's Guardian (`bash_guardian.py` and `write_guardian.py`) scans:
- Bash commands for patterns matching file operations on protected paths.
- Write tool calls for paths in `.claude/` directory.

**Conflict points and mitigations:**

1. **Heredoc with `.claude` paths in Bash**: Guardian flags heredoc body content that mentions `.claude` paths. Mitigation: SKILL.md Rule 0 -- all staging file content must be written via Write tool, not Bash. `memory_staging_guard.py` enforces this.

2. **Python string literals in source code**: Guard scripts split path markers at runtime (`".clau" + "de"`) to avoid Guardian scanning source files and flagging them.

3. **`python3 -c` with inline code**: Guardian may flag inline Python that references `.claude` paths. Mitigation: SKILL.md prohibits `python3 -c` with `.claude` paths. All operations go through script files.

4. **Write tool to memory directory**: `memory_write_guard.py` auto-approves staging files (with safety gates) to avoid user approval prompts during automated saves. Non-staging memory files are denied (must go through memory_write.py via Bash).

5. **`find -delete` or `rm` with `.claude` paths**: Guardian may flag these. Mitigation: SKILL.md prohibits these commands. Uses Python glob+os.remove instead.

---

## 8. Known Architectural Weaknesses

### 8.1 Stop Hook Re-fire Loop

**Problem:** The `.stop_hook_active` flag is consumed (unlinked) on check. If the user stops again before the save completes, the flag is gone and triage re-fires, potentially blocking stop again. The `.triage-handled` sentinel mitigates this (5min TTL), but the sentinel is cleaned up by staging cleanup after successful save, creating a window where re-fire can occur.

**Sequence:**
1. Triage fires, blocks stop, creates `.stop_hook_active` + `.triage-handled`
2. Save starts, cleanup deletes `.triage-handled`
3. User re-stops during save
4. Triage fires again (no flag, no sentinel) -- blocks stop again
5. Now the agent has two pending save operations

### 8.2 Multi-Phase Orchestration Complexity

The 5-phase pipeline (0, 1, 1.5, 2, 3) with 3 different subagent types creates significant complexity:

- **Phase 0** is just JSON parsing -- could be a script.
- **Phase 1** needs LLM judgment (correct) but uses Agent subagents with restricted tools.
- **Phase 1.5** is deterministic -- the main agent is instructed to follow mechanical rules, but it's an LLM interpreting prose instructions.
- **Phase 2** needs LLM judgment (correct) but is a simple quality check.
- **Phase 3** is just running commands -- a Task subagent runs pre-computed Bash.

The entire Phase 1.5 + 3 could be a single script, eliminating the need for the main LLM to orchestrate deterministic steps and the Phase 3 subagent to merely execute commands.

### 8.3 Screen Noise from Intermediate Steps

Each subagent creates visible output in the user's terminal:
- Phase 1: N subagent spawn/completion messages
- Phase 1.5: M Bash call outputs (candidate.py, draft.py)
- Phase 2: N verification subagent messages
- Phase 3: 1 save subagent with command outputs

For a session triggering 3 categories, this is approximately 10+ visible console interactions, all during what should be a silent auto-capture.

### 8.4 Mixed Execution Models

The system uses four different execution models:
1. **Hooks** (deterministic scripts communicating via stdin/stdout JSON)
2. **Skills** (LLM-interpreted prose instructions)
3. **Subagents** (Agent with agent file, Task with inline prompt)
4. **Direct Bash** (Python scripts run via Bash tool)

This means:
- The same operation (e.g., "select a candidate") could theoretically be implemented in any of these models.
- Debugging requires understanding which model is executing at any point.
- The LLM must switch between "follow instructions literally" (Phase 1.5), "use judgment" (Phase 1, 2), and "just run commands" (Phase 3) within a single interaction.

### 8.5 PostToolUse Limitation

`memory_validate_hook.py` fires AFTER the write has already occurred. It cannot prevent the write -- it can only quarantine (rename) the invalid file and report the error. This means:
- The LLM sees the denial message but the file is already on disk.
- If the quarantine fails (permissions, etc.), the invalid file persists.
- Python `open()` writes (from memory_write.py, memory_draft.py) are completely invisible to this hook.

### 8.6 Staging Directory as Shared Mutable State

The `.staging/` directory is the central communication channel between all phases:
- Triage writes context files and triage-data.json
- Phase 1 subagents write intent files
- Phase 1.5 writes new-info, input, and draft files
- Phase 3 reads drafts and cleans up

If any phase crashes or produces unexpected output, subsequent phases may read stale or corrupt data. The pre-phase cleanup (removing stale intent files) partially addresses this, but context files and triage-data.json are not cleaned between phases.

### 8.7 Dual Enforcement Path for Session Summaries

Session summary rolling window enforcement is triggered in two places:
1. `memory_write.py` do_create(): auto-spawns `memory_enforce.py` after successful session_summary create (subprocess).
2. SKILL.md Phase 3: explicit `memory_enforce.py --category session_summary` command in the save subagent's command list.

This is documented as "safety belt" but creates redundant work and potential confusion if the auto-enforcement fails silently.

### 8.8 Config Split Between Script-Read and Agent-Interpreted

Some config keys are read by Python scripts (deterministic behavior), while others are read by the LLM interpreting SKILL.md (non-deterministic). For example:
- `categories.*.enabled` is agent-interpreted (the LLM decides whether to skip disabled categories).
- `triage.thresholds.*` is script-read (Python enforces thresholds mechanically).

This means disabling a category via `enabled: false` depends on the LLM correctly interpreting SKILL.md, while threshold changes take effect immediately in the deterministic triage hook.

### 8.9 Index as Single Point of Failure

The index.md file is the primary data structure for both retrieval and candidate selection. While it can be rebuilt from JSON files, a corrupt index (e.g., from a crashed write) can cause:
- Retrieval failures (no matches found)
- Duplicate memory creation (candidate.py doesn't find existing entry)
- Stale entries pointing to deleted/renamed files

The auto-rebuild on missing index helps, but a corrupt (but existing) index is not detected until `--validate` is run.

### 8.10 Tokenizer Inconsistency (Intentional)

`memory_candidate.py` uses 3+ char minimum tokens, while `memory_search_engine.py` / `memory_retrieve.py` use 2+ char minimum. This is documented as intentional (precision vs recall tradeoff) but creates a cognitive burden -- the same word may match in retrieval but not in candidate selection, or vice versa.
