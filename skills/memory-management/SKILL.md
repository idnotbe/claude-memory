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

# Memory Management System (v6)

Structured memory stored in `.claude/memory/`. When instructed to save a memory, follow the steps below.

> **Plugin self-check:** Before running any memory operations, verify plugin scripts are accessible by confirming `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py"` exists. If `CLAUDE_PLUGIN_ROOT` is unset or the file is missing, stop and report the error.

> **Architecture version check:** Read `memory-config.json` key `architecture.simplified_flow`. If explicitly set to `false`, fall back to the v5 orchestration flow in `SKILL.md.v5`. If `SKILL.md.v5` is not found, report the error: "Cannot fall back to v5 flow: SKILL.md.v5 is missing. Set architecture.simplified_flow to true in memory-config.json or restore SKILL.md.v5." and stop. The instructions below assume `simplified_flow: true` (default).

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

**Staging directory**: Memory staging files are stored in `/tmp/.claude-memory-staging-<hash>/` (on Linux; `/private/tmp/.claude-memory-staging-<hash>/` on macOS) where `<hash>` is a deterministic SHA-256 prefix derived from the project path. This avoids Claude Code's hardcoded `.claude/` protected directory prompts. The `triage-data.json` file includes a `staging_dir` field with the exact path. All staging file references below use `<staging_dir>` as shorthand.

When a triage hook fires with a save instruction:

### Pre-Phase: Staging Cleanup

Before parsing triage output, check for stale staging files from a previous failed session.
Only run this check when **no** `<triage_data>` or `<triage_data_file>` tag is present in the
current hook output (i.e., manual `/memory:save` invocation or recovery). If triage output IS
present, skip directly to SETUP -- the current triage data is fresh.

1. Determine the staging directory: Read the `staging_dir` field from `triage-data.json` if available, or compute it using `memory_staging_utils.get_staging_dir()` (path is `<resolved_tmp>/.claude-memory-staging-<hash>/` where `<hash>` is derived from the project path). Check if ANY of these exist:
   - `<staging_dir>/.triage-pending.json`
   - `<staging_dir>/triage-data.json` WITHOUT a corresponding `<staging_dir>/last-save-result.json`
2. If found, clean up ALL staging files before proceeding:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-staging --staging-dir <staging_dir>
   ```
3. Proceed with normal fresh triage below.

> Pre-existing context files may be stale (unknown age, missing transcript). Always run fresh triage for accurate saves.

### SETUP (deterministic)

**Step 1: Parse triage output** (must run FIRST to obtain `<staging_dir>`).
1. First try: Extract the file path from within `<triage_data_file>...</triage_data_file>` tags in the stop hook output. If present, read the JSON file at that path. The JSON includes a `staging_dir` field -- use this for all subsequent staging file paths.
2. Fallback: Extract inline `<triage_data>` JSON block (backwards compatibility). If it lacks `staging_dir`, compute it from the project path.

**Step 2: Clean stale intent files.** Remove leftover intent files from previous sessions (requires `<staging_dir>` from Step 1):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir <staging_dir>
```

**Step 3: Read config.** Read `memory-config.json` for `triage.parallel.category_models` and `triage.parallel.verification_enabled`.

Categories are triggered by keyword heuristic scoring in `memory_triage.py`. Each category has primary keyword patterns and co-occurrence boosters. Thresholds are configurable via `triage.thresholds.*` in config (default range: 0.4-0.6). SESSION_SUMMARY uses activity metrics instead of text matching.

If `triage.parallel.enabled` is `false`, fall back to the sequential flow: process each category one at a time using the current model (no Agent subagents).

### Phase 1: DRAFT (LLM, Agent subagents)

For EACH triggered category, spawn an Agent subagent using the `memory-drafter` agent file:

```
Agent(
  subagent_type: "memory-drafter",
  model: config.category_models[category.lower()] or default_model,
  run_in_background: true,
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

Background subagents run concurrently. Do NOT proceed to Phase 1.5 or Phase 2 until every
background subagent has returned a completion notification. For each completed
subagent, verify it succeeded before reading its intent file. If a subagent
failed, skip that category (log warning) and continue with remaining categories.

**M1 Fallback:** If ALL Phase 1 drafters fail (no `intent-*.json` files produced), write a pending file using the Write tool:
```
Write(
  file_path: "<staging_dir>/.triage-pending.json",
  content: '{"categories": ["all"], "reason": "total_drafter_failure", "timestamp": "<ISO 8601 UTC>"}'
)
```
Then stop -- do not proceed to Phase 2. The retrieval hook will detect this on the next session.

**Context file format** (`<staging_dir>/context-<category>.txt`):
Each context file contains a header with the category name and score, optionally
followed by a `Description:` line (from `categories.<name>.description` in config),
then a `<transcript_data>` block wrapping relevant transcript excerpts. For text-based
categories, these are keyword-matched snippets with surrounding context (+/- 10 lines).
For SESSION_SUMMARY, activity metrics (tool uses, distinct tools, exchanges) are provided,
followed by transcript excerpts: full transcript if short (<280 lines), or head (80 lines)
+ tail (200 lines) for longer conversations. Files are capped at 50KB.

**Subagent output:** Each subagent writes one of two intent JSON types:

- **SAVE intent**: `{ "category", "new_info_summary", "intended_action"?, "lifecycle_hints"?, "partial_content": { "title", "tags", "confidence", "related_files"?, "change_summary", "content" } }`
- **NOOP intent**: `{ "category", "action": "noop", "noop_reason" }`

If `context_file` is missing from the triage entry for a category (can happen on
staging directory write failure), skip that category with a warning.

If a subagent fails or writes invalid JSON, skip that category (log warning) and continue.

### Phase 1.5: VERIFY (OPTIONAL)

**Skip check**: If `triage.parallel.verification_enabled` is `false` in config (default: `false`), skip Phase 1.5 entirely and proceed directly to Phase 2 COMMIT with `--action run`.

When verification IS enabled (`verification_enabled: true`):

**Step 1: Prepare.** Run the orchestrator in prepare mode:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_orchestrate.py" \
  --staging-dir <staging_dir> --action prepare --memory-root <memory_root>
```
This runs steps 1-6 (collect intents, candidate selection, CUD resolution, draft assembly, manifesting) and writes `<staging_dir>/orchestration-result.json`.

**Step 2: Identify risk-eligible categories.** Read the manifest. Categories eligible for verification:
- `decision` or `constraint` categories
- `DELETE` actions
- Low-confidence drafts (confidence < 0.5 in intent)

If no categories are eligible, skip to Step 4.

**Step 3: Verify.** For each eligible category, spawn a verification Agent subagent:
- Read the assembled draft JSON at the `draft_path` from the manifest
- Read the original context file
- Check: Is the summary accurate? Any hallucination? Well-organized?
- Output verdict: `PASS`, `BLOCK` (hallucination/factual error), or `REVISE` (advisory)

Spawn ALL verification subagents in PARALLEL. Collect verdicts.

**Step 4: Commit.** Build the exclude list from any `BLOCK` verdicts, then run:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_orchestrate.py" \
  --staging-dir <staging_dir> --action commit --memory-root <memory_root> \
  --exclude-categories <comma-separated-blocked-categories>
```

### Phase 2: COMMIT (deterministic, single script)

When verification is DISABLED (default):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_orchestrate.py" \
  --staging-dir <staging_dir> --action run --memory-root <memory_root>
```

This single command handles everything:
1. Collects and validates intent JSONs (strips markdown fences)
2. Runs candidate selection (`memory_candidate.py`) per category + captures OCC hashes
3. Resolves CUD actions via the rules table
4. Assembles drafts (`memory_draft.py`) per category, generates target paths
5. Handles DELETE actions (writes retire JSONs)
6. Builds orchestration manifest
7. Executes saves: sentinel management, per-category `memory_write.py` calls (with `--skip-auto-enforce`), enforcement, result file, cleanup

If ALL categories are NOOP (manifest `status` is `"all_noop"`): the script exits cleanly. No saves performed.

On partial failure: `.triage-pending.json` is written with failed categories. Staging is preserved. Sentinel set to `failed`.

On full success: staging cleaned up, result file written, sentinel set to `saved`.

**On orchestrator crash (non-zero exit):** Do NOT retry the orchestrator. Report the error to the user with the stderr output and stop. The orchestrator's own exception handler writes `.triage-pending.json` and sets sentinel to `failed`, so recovery will happen on next triage. Retrying risks duplicate saves or data corruption.

> **Final output rule**: After Phase 2 completes, output ONLY the single-line save summary (e.g., "Saved: session_summary (create), decision (update)"). No intermediate status, phase completion messages, or additional commentary.

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

This table is implemented in `memory_orchestrate.py`. It is documented here for reference.
See action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md for the original 3-layer design.

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

0. **Guardian compatibility**: Never combine heredoc (`<<`), Python interpreter, and `.claude` path in a single Bash command. All staging file content must be written via Write tool (not Bash). Bash is only for running python3 scripts. Do NOT use `python3 -c` for any file operations (read, write, delete, glob). Use dedicated scripts instead. Do NOT use `find -delete` or `rm` with `.claude` paths (use Python glob+os.remove instead). Do NOT pass inline JSON containing `.claude` paths on the Bash command line (use `--result-file` with a staging temp file instead).
1. **CRUD lifecycle**: Memories can be created, updated, or retired through the 3-phase consolidation flow (SETUP + DRAFT + COMMIT)
2. **Silent operation**: Do NOT mention memory operations in visible output during auto-capture
3. **Check before creating**: Candidate selection in the orchestrator prevents duplicates automatically
4. **CUD verification**: All save operations go through 2-layer CUD verification (structural + intent)
5. **Confidence scores**: 0.7-0.9 for most; 0.9+ only for explicitly confirmed facts
6. **All writes via memory_write.py**: Never write directly to .claude/memory/ -- use the Python tool

## Config

`.claude/memory/memory-config.json` (all defaults apply if absent):
- `architecture.simplified_flow` -- enable simplified 3-phase flow (default: true). When false, falls back to SKILL.md.v5 5-phase flow.
- `categories.<name>.enabled` -- enable/disable category (default: true)
- `categories.<name>.description` -- plain-text category description for LLM classification context (default: see memory-config.default.json)
- `categories.<name>.auto_capture` -- enable/disable auto-capture (default: true)
- `categories.<name>.retention_days` -- auto-expire after N days (0 = permanent; 90 for sessions)
- `categories.session_summary.max_retained` -- max session summaries to keep (default: 5)
- `retrieval.max_inject` -- max memories injected per prompt (default: 5)
- `max_memories_per_category` -- max files per folder (default: 100)
- `triage.parallel.enabled` -- enable parallel subagent drafting (default: true)
- `triage.parallel.category_models` -- per-category model for drafting (see default config for per-category defaults; fallback: haiku)
- `triage.parallel.verification_enabled` -- enable/disable Phase 1.5 content verification (default: false)
- `triage.parallel.verification_model` -- model for verification phase (default: sonnet)
- `triage.parallel.default_model` -- fallback model if category not in map (default: haiku)
- `delete.grace_period_days` -- days before retired records are purged (default: 30)
- `delete.archive_retired` -- whether to archive instead of purge (default: true; agent-interpreted, not script-enforced)
