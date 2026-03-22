---
name: memory-management
description: Manages structured project memories. Provides format instructions for writing and updating memory files in .claude/memory/.
globs:
  - ".claude/memory/**"
  - ".claude/memory/memory-config.json"
triggers:
  - "remember"
  - "forget"
  - "memory"
  - "memories"
  - "previous session"
---

# Memory Management System

Structured memory stored in `.claude/memory/`. When instructed to save a memory, follow the steps below.

> **Plugin self-check:** Before running any memory operations, verify plugin scripts are accessible by confirming `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py"` exists. If `CLAUDE_PLUGIN_ROOT` is unset or the file is missing, stop and report the error.

## Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| session_summary | sessions/ | Work resume snapshot |
| decision | decisions/ | Choice + rationale (why X over Y) |
| runbook | runbooks/ | Error fix procedure (diagnose, fix, verify) |
| constraint | constraints/ | Known limitations (enduring walls) |
| tech_debt | tech-debt/ | Deferred work (what was skipped and why) |
| preference | preferences/ | Conventions (how things should be done) |

Each category has a configurable `description` field in `memory-config.json` (under `categories.<name>.description`). Descriptions are included in triage context files and retrieval output to help classify content accurately.

## Memory Consolidation

**Staging directory**: Memory staging files are stored in `/tmp/.claude-memory-staging-<hash>/` where `<hash>` is a deterministic SHA-256 prefix derived from the project path. This avoids Claude Code's hardcoded `.claude/` protected directory prompts. The `triage-data.json` file includes a `staging_dir` field with the exact path. All staging file references below use `<staging_dir>` as shorthand.

When a triage hook fires with a save instruction:

### Pre-Phase: Staging Cleanup

Before parsing triage output, check for stale staging files from a previous failed session.
Only run this check when **no** `<triage_data>` or `<triage_data_file>` tag is present in the
current hook output (i.e., manual `/memory:save` invocation or recovery). If triage output IS
present, skip directly to Phase 0 -- the current triage data is fresh.

1. Determine the staging directory: Read the `staging_dir` field from `triage-data.json` if available, or compute it as `/tmp/.claude-memory-staging-<hash>/` (where `<hash>` is derived from the project path by `memory_triage.py`). Check if ANY of these exist:
   - `<staging_dir>/.triage-pending.json`
   - `<staging_dir>/triage-data.json` WITHOUT a corresponding `<staging_dir>/last-save-result.json`
2. If found, clean up ALL staging files before proceeding:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-staging --staging-dir <staging_dir>
   ```
3. Proceed with normal fresh triage below.

> Pre-existing context files may be stale (unknown age, missing transcript). Always run fresh triage for accurate saves.

### Phase 0: Parse Triage Output

**Step 0: Clean stale intent files.** Before processing triage data, remove leftover intent files from previous sessions to prevent stale data contamination. Only delete `intent-*.json` files (NOT `context-*.txt` or `triage-data.json` — those were just written by the triage hook for this session):
```bash
python3 -c "import glob,os
staging_dir = '<staging_dir>'
for f in glob.glob(os.path.join(staging_dir, 'intent-*.json')): os.remove(f)
print('ok')"
```
(Replace `<staging_dir>` with the actual staging directory path from the triage data.)

1. First try: Extract the file path from within `<triage_data_file>...</triage_data_file>` tags in the stop hook output. If present, read the JSON file at that path. The JSON includes a `staging_dir` field — use this for all subsequent staging file paths.
2. Fallback: Extract inline `<triage_data>` JSON block (backwards compatibility). If it lacks `staging_dir`, compute it from the project path.

Read `memory-config.json` for `triage.parallel.category_models`.

Categories are triggered by keyword heuristic scoring in `memory_triage.py`. Each category has primary keyword patterns and co-occurrence boosters (e.g., DECISION triggers on "decided", "chose" + rationale co-occurrence like "because", "rationale"). Thresholds are configurable via `triage.thresholds.*` in config (default range: 0.4-0.6). SESSION_SUMMARY uses activity metrics instead of text matching.

If `triage.parallel.enabled` is `false`, fall back to the sequential flow:
process each category one at a time using the current model (no Task subagents).

### Phase 1: Parallel Intent Drafting

For EACH triggered category, spawn an Agent subagent using the `memory-drafter` agent file:

```
Agent(
  subagent_type: "memory-drafter",
  model: config.category_models[category.lower()] or default_model,
  prompt: "Category: <cat>\nContext file: <staging_dir>/context-<cat>.txt\nOutput: <staging_dir>/intent-<cat>.json"
)
```

The `memory-drafter` agent has `tools: Read, Write` only (no Bash), which structurally prevents Guardian conflicts. Each subagent reads its context file and writes an intent JSON file -- nothing more.

**Important:** The `<triage_data>` JSON block emits lowercase category names
(e.g., "decision"), matching config keys and memory_candidate.py expectations.
The human-readable stderr section may use UPPERCASE for readability, but always
use the lowercase `category` value from the JSON for model lookup, CLI calls,
and file operations.

Spawn ALL category subagents in PARALLEL (single message, multiple Agent calls).

**Cost note:** Each triggered category spawns one drafting subagent (Phase 1)
and one verification subagent (Phase 2). With all 6 categories triggering,
this is 12 subagent calls total. This is rare (requires a very diverse
conversation) but be aware of the cost implications.

**Context file format** (`<staging_dir>/context-<category>.txt`):
Each context file contains a header with the category name and score, optionally
followed by a `Description:` line (from `categories.<name>.description` in config),
then a `<transcript_data>` block wrapping relevant transcript excerpts. For text-based
categories, these are keyword-matched snippets with surrounding context (+/- 10 lines).
For SESSION_SUMMARY, activity metrics (tool uses, distinct tools, exchanges) are provided,
followed by transcript excerpts: full transcript if short (<280 lines), or head (80 lines)
+ tail (200 lines) for longer conversations. This gives the drafter opening goals and
final state for meaningful session summaries. Files are capped at 50KB.

**Subagent output:** Each subagent writes one of two intent JSON types:

- **SAVE intent**: `{ "category", "new_info_summary", "intended_action"?, "lifecycle_hints"?, "partial_content": { "title", "tags", "confidence", "related_files"?, "change_summary", "content" } }`
- **NOOP intent**: `{ "category", "action": "noop", "noop_reason" }`

If `context_file` is missing from the triage entry for a category (can happen on
staging directory write failure), skip that category with a warning.

If a subagent fails or writes invalid JSON, skip that category (log warning) and continue.

### Phase 1.5: Deterministic Execution (Main Agent)

After all Phase 1 subagents complete, the main agent performs candidate selection,
CUD resolution, and draft assembly deterministically. No LLM judgment occurs here --
all decisions follow mechanical rules.

**Step 1: Collect and validate intent JSONs**

Read all `<staging_dir>/intent-<cat>.json` files. For each intent:
- If `action` is `"noop"`: log the `noop_reason` and skip the category.
- If `action` is not `"noop"` (SAVE intent): validate required fields exist:
  `category` (string), `new_info_summary` (string), `partial_content` (object with
  `title`, `tags`, `confidence`, `change_summary`, `content`).
- If validation fails: skip the category with a warning.

**Step 2: Run candidate selection (parallel Bash calls)**

For each validated SAVE intent, write `new_info_summary` to a temp file and run
`memory_candidate.py`. These calls are independent -- run them in PARALLEL
(single message, multiple Bash calls):

```bash
# First, write the new-info summary (use Write tool):
# Path: <staging_dir>/new-info-<cat>.txt
# Content: the new_info_summary value from the intent JSON

# Then run candidate.py:
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" \
  --category <cat> \
  --new-info-file <staging_dir>/new-info-<cat>.txt
```

If `lifecycle_hints` is present in the intent, pass `lifecycle_hints[0]` as
`--lifecycle-event`:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" \
  --category <cat> \
  --new-info-file <staging_dir>/new-info-<cat>.txt \
  --lifecycle-event <lifecycle_hints[0]>
```

If candidate.py fails for a category, skip that category (log error).

**Step 3: CUD Resolution**

For each category, combine L1 (candidate.py `structural_cud`) with L2 (intent's
`intended_action`, defaulting to `"update"` if absent) and apply the CUD Verification
Rules table (see below). Record the resolved action for each category.

Special cases:
- `pre_action="NOOP"`: NOOP (skip category).
- `vetoes` non-empty: vetoes restrict specific actions, not the entire category.
  A "Cannot DELETE" veto means DELETE is forbidden but UPDATE is still allowed.
  Only skip the category if the resolved action is vetoed (e.g., resolved DELETE
  but veto says "Cannot DELETE"). If `structural_cud="UPDATE"`, proceed with UPDATE
  regardless of vetoes (the veto only blocks DELETE).
- `intended_action` absent or unrecognized: use safety default UPDATE for L2.

**Step 4: Execute drafts (parallel Bash calls)**

For each category with a resolved CREATE or UPDATE action, write the intent's
`partial_content` to an input file and run `memory_draft.py`. These calls are
independent -- run them in PARALLEL:

For **CREATE**:
```bash
# First, write partial_content (use Write tool):
# Path: <staging_dir>/input-<cat>.json
# Content: the partial_content object from the intent JSON

python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_draft.py" \
  --action create \
  --category <cat> \
  --input-file <staging_dir>/input-<cat>.json \
  --root <staging_dir>
```

For **UPDATE** (add `--candidate-file` with the `candidate.path` from Step 2):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_draft.py" \
  --action update \
  --category <cat> \
  --input-file <staging_dir>/input-<cat>.json \
  --candidate-file <candidate.path> \
  --root <staging_dir>
```

Parse each `memory_draft.py` JSON output. Extract `draft_path`:
```json
{"status": "ok", "action": "create", "draft_path": "<staging_dir>/draft-<cat>-<timestamp>.json"}
```

If draft.py fails for a category, skip that category (log error).

**Step 5: Handle DELETE actions**

For each category with a resolved DELETE action, write the retire JSON via the
**Write tool**:
- Path: `<staging_dir>/draft-<category>-retire.json`
- Content: `{"action": "retire", "target": "<candidate.path>", "reason": "<why>"}`

**Step 6: Summary**

If ALL categories resulted in NOOP, VETO, or error: do NOT proceed to Phase 2.
Otherwise, proceed with all categories that have draft files.

### Phase 2: Content Verification
For each draft from Phase 1.5, spawn a verification Task subagent with `verification_model` from config:
- Read the draft JSON file and the original context file.
- Focus on **content quality** (schema validation is handled by memory_write.py in Phase 3):
  - Is the summary accurate relative to the transcript context?
  - Does it capture the key information without hallucination?
  - Is it well-organized and complete?
  - Are tags relevant and sufficient?
- Hallucination or factual error = BLOCK (report issue, do not save).
- Minor quality concern = ADVISORY (log but proceed).
- Report: PASS or FAIL with issues.

Spawn ALL verification subagents in PARALLEL.

### Phase 3: Save (Subagent)

CUD resolution was performed in Phase 1.5. The main agent now builds the save command list from the pre-resolved actions and delegates execution to a single Task subagent. This keeps save operations (30-50 lines of Bash commands) out of the main conversation.

**Step 1: Build Command List (Main Agent)**

Collect Phase 1.5 resolved actions and Phase 2 verification results. Exclude any category where Phase 2 returned FAIL (BLOCK). For each remaining category, build the save command using the resolved action from Phase 1.5.

**Draft path validation:** Before including any draft file path in commands, verify it
starts with `<staging_dir>/draft-` (where `<staging_dir>` is the `/tmp/.claude-memory-staging-*` path) and contains no `..` path components.
Reject any draft with a non-conforming path.

Command templates:
- **CREATE**: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create --category <cat> --target "<path>" --input "<draft>"`
- **UPDATE**: Read the candidate file, compute its MD5 hash for OCC.
  `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action update --category <cat> --target "<path>" --input "<draft>" --hash <md5>`
- **DELETE** (soft retire): `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action retire --target "<path>" --reason "<why>"`

If session_summary was created, include the enforce command:
`python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_enforce.py" --category session_summary`

> Note: Enforcement also runs automatically after `memory_write.py --action create --category session_summary`. This explicit call is a safety belt.

**Step 2: Spawn Save Subagent**

Spawn ONE foreground Task subagent (model: haiku) with the pre-computed command list:

```
Task(
  model: "haiku",
  subagent_type: "general-purpose",
  prompt: "Execute these memory save commands in order.

**IMPORTANT: Minimal Console Output**
Combine ALL numbered commands into a SINGLE Bash tool call using `;`
separators. This minimizes console noise. Do NOT use heredoc (<<).

Example: `cmd1 ; cmd2 ; cmd3`

If any command fails, the `;` separator ensures remaining commands
still execute. After ALL commands complete, run cleanup and result
file commands in the same or a second Bash call.

Commands:
1. <first memory_write.py command>
2. <second memory_write.py command>
...
N. <memory_enforce.py command, if applicable>

If ALL commands succeeded (no errors), run cleanup:
python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py\" --action cleanup-staging --staging-dir <staging_dir>
If ANY command failed, do NOT delete staging files (preserve for retry).

Then write the result file (atomic, regardless of success/failure).
First, write the result JSON to a temp file using the Write tool:
Write(file_path='<staging_dir>/last-save-result-input.json', content='{\"saved_at\": \"<ISO 8601 UTC>\", \"categories\": [\"<saved categories>\"], \"titles\": [\"<saved titles>\"], \"errors\": []}')

Then run the save-result command referencing the file:
python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py\" --action write-save-result --staging-dir <staging_dir> --result-file <staging_dir>/last-save-result-input.json

Return ONLY a single-line summary like: 'Saved: session_summary (update), constraint (create)' — no extra text."
)
```

Result file fields:
- `saved_at`: current UTC timestamp in ISO 8601
- `categories`: list of categories that were saved (PASS only)
- `titles`: list of titles corresponding to each saved memory
- `errors`: list of `{"category": "<name>", "error": "<message>"}` objects for any failed saves (empty array if all succeeded)

**Step 3: Error Handling**

If the Task subagent fails, times out, or returns errors:
1. Write a pending sentinel using the Write tool (NOT Bash — staging guard blocks Bash writes to staging):
   ```
   Write(
     file_path: "<staging_dir>/.triage-pending.json",
     content: '{"timestamp": "<ISO 8601 UTC>", "categories": ["<failed categories>"], "reason": "subagent_error"}'
   )
   ```
2. Do NOT delete staging files (preserve triage-data.json, context-*.txt for retry).
3. The next session's UserPromptSubmit hook will detect the pending sentinel.

### Write Pipeline Protections

`memory_write.py` enforces these protections automatically:

- **Anti-resurrection**: A memory cannot be re-created within 24 hours of retirement. If a CREATE targets a recently retired file path, it fails with `ANTI_RESURRECTION_ERROR`. Use a different title/slug, wait 24 hours, or restore the old memory and update it.
- **Merge protections on UPDATE**:
  - Immutable fields: `created_at`, `schema_version`, `category` cannot change
  - `record_status` cannot be changed via UPDATE (use retire/archive actions)
  - Tags: grow-only below the 12-tag cap; eviction allowed only when adding new tags
  - `related_files`: grow-only, except non-existent (dangling) paths can be removed
  - `changes[]`: append-only; at least 1 new change entry required per update
  - FIFO overflow: `changes[]` is capped at 50 entries (oldest dropped)
- **OCC (Optimistic Concurrency Control)**: UPDATE with `--hash` checks the file's current MD5 against the expected hash. Mismatches produce `OCC_CONFLICT` (re-read and retry).

## CUD Verification Rules

| L1 (Python) | L2 (Subagent) | Resolution | Rationale |
|---|---|---|---|
| CREATE | CREATE | CREATE | Agreement |
| UPDATE_OR_DELETE | UPDATE | UPDATE | Agreement |
| UPDATE_OR_DELETE | DELETE | DELETE | Structural permits |
| CREATE | UPDATE | CREATE | Structural: no candidate exists |
| CREATE | DELETE | NOOP | Cannot DELETE with 0 candidates |
| UPDATE_OR_DELETE | CREATE | CREATE | Subagent says new despite candidate |
| VETO | * | OBEY VETO | Mechanical invariant |
| NOOP | * | NOOP | No target |

This is the implemented 2-layer system. See action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md for the original 3-layer design.

Key principles:
1. Mechanical trumps LLM: Python vetoes are absolute.
2. Safety defaults: UPDATE over DELETE (non-destructive), UPDATE over CREATE (avoids duplicates), NOOP for CREATE-vs-DELETE (contradictory signals).
3. All resolution is automatic: No user confirmation needed.

## Memory JSON Format

**Common fields** (all categories):
```
{ schema_version: "1.0", category, id (=slug), title (max 120 chars),
  created_at (ISO 8601 UTC), updated_at, tags[] (min 1),
  related_files[], confidence (0.0-1.0),
  record_status: "active"|"retired"|"archived" (default: "active"),
  changes: [{ date, summary, field?, old_value?, new_value? }] (max 50),
  times_updated: integer (default: 0),
  retired_at?, retired_reason?, archived_at?, archived_reason?,
  content: {...} }
```

**record_status** (top-level system lifecycle):
| Status | Behavior |
|--------|----------|
| active | Indexed and retrievable (default for all new memories) |
| retired | Excluded from index; GC-eligible after 30-day grace period |
| archived | Excluded from index; NOT GC-eligible (preserved indefinitely) |

This is separate from content.status which tracks category-specific state (e.g., decision: proposed/accepted/deprecated/superseded).

**Content by category**:
- **session_summary**: `{ goal, outcome: "success|partial|blocked|abandoned", completed[], in_progress[], blockers[], next_actions[], key_changes[] }`
- **decision**: `{ status: "proposed|accepted|deprecated|superseded", context, decision, alternatives: [{option, rejected_reason}], rationale[], consequences[] }`
- **runbook**: `{ trigger, symptoms[], steps[], verification, root_cause, environment }`
- **constraint**: `{ kind: "limitation|gap|policy|technical", rule, impact[], workarounds[], severity: "high|medium|low", active: true, expires: "condition or 'none'" }`
- **tech_debt**: `{ status: "open|in_progress|resolved|wont_fix", priority: "critical|high|medium|low", description, reason_deferred, impact[], suggested_fix[], acceptance_criteria[] }`
- **preference**: `{ topic, value, reason, strength: "strong|default|soft", examples: { prefer[], avoid[] } }`

Full JSON Schema definitions are in the plugin's assets/schemas/ directory.

## Session Rolling Window

Session summaries use a rolling window strategy: keep the last N sessions (default 5, configurable via `categories.session_summary.max_retained` in `memory-config.json`), retire the oldest when the limit is exceeded.

### How It Works

The rolling window is enforced AFTER a new session summary is successfully created:

1. **Count active sessions**: Scan `sessions/` folder, count only files with `record_status == "active"` (or field absent for pre-v4 files).
2. **Check limit**: If active count > `max_retained` (default 5), identify the oldest session by `created_at` timestamp.
3. **Deletion guard**: Before retiring, warn if the session contains unique content not captured elsewhere. The warning is informational only -- retirement still proceeds. The content is preserved during the 30-day grace period.
4. **Retire oldest**: Handled automatically by `memory_enforce.py`. The script acquires the index lock, scans for active sessions, and retires excess sessions in a single atomic operation. The retirement reason is "Session rolling window: exceeded max_retained limit".

### Configuration

In `memory-config.json`:
```json
{
  "categories": {
    "session_summary": {
      "max_retained": 5
    }
  }
}
```

### Manual Cleanup

Users can also manage sessions directly:
- `/memory --retire <slug>` -- manually retire a specific session
- `/memory --gc` -- garbage collect retired sessions past the 30-day grace period
- `/memory --restore <slug>` -- restore a retired session to active status

## When the User Asks About Memories

- "What do you remember?" -> Read index.md and summarize
- "Remember that..." -> Create a memory in the appropriate category
- "Forget..." -> Read the memory, confirm with user, retire via memory_write.py --action retire
- "What did we decide about X?" -> Search decisions/ folder
- /memory, /memory:config, /memory:search, /memory:save -> See slash commands

## Rules

0. **Guardian compatibility**: Never combine heredoc (`<<`), Python interpreter, and `.claude` path in a single Bash command. All staging file content must be written via Write tool (not Bash). Bash is only for running python3 scripts. Do NOT use `python3 -c` with inline code referencing `.claude` paths. Do NOT use `find -delete` or `rm` with `.claude` paths (use Python glob+os.remove instead). Do NOT pass inline JSON containing `.claude` paths on the Bash command line (use `--result-file` with a staging temp file instead).
1. **CRUD lifecycle**: Memories can be created, updated, or retired through the 4-phase consolidation flow
2. **Silent operation**: Do NOT mention memory operations in visible output during auto-capture
3. **Check before creating**: Always run memory_candidate.py first to avoid duplicates
4. **CUD verification**: All save operations go through 2-layer CUD verification
5. **Confidence scores**: 0.7-0.9 for most; 0.9+ only for explicitly confirmed facts
6. **All writes via memory_write.py**: Never write directly to .claude/memory/ -- use the Python tool

## Config

`.claude/memory/memory-config.json` (all defaults apply if absent):
- `categories.<name>.enabled` -- enable/disable category (default: true)
- `categories.<name>.description` -- plain-text category description for LLM classification context (default: see memory-config.default.json)
- `categories.<name>.auto_capture` -- enable/disable auto-capture (default: true)
- `categories.<name>.retention_days` -- auto-expire after N days (0 = permanent; 90 for sessions)
- `categories.session_summary.max_retained` -- max session summaries to keep (default: 5)
- `retrieval.max_inject` -- max memories injected per prompt (default: 5)
- `max_memories_per_category` -- max files per folder (default: 100)
- `triage.parallel.enabled` -- enable parallel subagent drafting (default: true)
- `triage.parallel.category_models` -- per-category model for drafting (see default config for per-category defaults; fallback: haiku)
- `triage.parallel.verification_model` -- model for verification phase (default: sonnet)
- `triage.parallel.default_model` -- fallback model if category not in map (default: haiku)
- `delete.grace_period_days` -- days before retired records are purged (default: 30)
- `delete.archive_retired` -- whether to archive instead of purge (default: true; agent-interpreted, not script-enforced)
