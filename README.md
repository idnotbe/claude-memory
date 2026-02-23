# claude-memory (v5.0.0)

Structured memory management plugin for [Claude Code](https://claude.ai/code). Automatically captures decisions, runbooks, constraints, tech debt, session summaries, and preferences as JSON files with intelligent retrieval.

## What It Does

claude-memory gives Claude Code persistent, structured memory across sessions. Instead of losing context when a conversation ends, important information is automatically saved as categorized JSON files and retrieved when relevant.

**Auto-capture** (deterministic Stop hook + parallel subagents): When a conversation ends, a single deterministic keyword triage hook evaluates all 6 categories. If any trigger, it blocks the stop and outputs structured data including per-category context files. The orchestrator then spawns per-category LLM subagents in parallel (haiku for simple categories, sonnet for complex ones) to draft memories, followed by a verification pass, then saves via the write pipeline.

**Auto-retrieval** (UserPromptSubmit hook): When you send a message, a Python script reads the memory index and injects relevant entries as context for Claude.

### Typical Workflow

1. **Code as usual** -- Have a normal Claude Code session making decisions, fixing errors, setting conventions
2. **Memories auto-capture on stop** -- When you press stop, the triage hook evaluates your session and saves relevant memories
3. **Next session auto-retrieves** -- When you start a new session and mention a topic, relevant memories are injected as context
4. **Search and manage** -- Use `/memory:search` to find specific memories, `/memory --retire` to remove outdated ones
5. **Verify with `/memory`** -- Check memory status, health, and category counts at any time

## Memory Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| `session_summary` | `sessions/` | Work resume snapshots -- what happened, what's next |
| `decision` | `decisions/` | Choices with rationale -- why X over Y |
| `runbook` | `runbooks/` | Error fix procedures -- symptom, fix, verification |
| `constraint` | `constraints/` | Known limitations -- what can't be done and why |
| `tech_debt` | `tech-debt/` | Deferred work -- what was skipped and the cost |
| `preference` | `preferences/` | Conventions -- how things should be done |

These 6 categories are built-in with dedicated Pydantic schemas. Custom categories are not currently supported by the validation pipeline.

## Prerequisites

- **Python 3.8+** (for triage and retrieval scripts)
- **pydantic v2** (required for write operations: `pip install 'pydantic>=2.0,<3.0'`)
  - Only `memory_write.py` and `memory_validate_hook.py` need pydantic; triage and retrieval work without it
  - The write script attempts to bootstrap a `.venv` in the plugin directory (e.g., `~/.claude/plugins/claude-memory/.venv`) if pydantic is not available on the system Python. A project-local `.venv` is not used.

## Installation

```bash
# Clone into your Claude Code plugins directory
cd ~/.claude/plugins   # Create this directory if it doesn't exist: mkdir -p ~/.claude/plugins
git clone https://github.com/idnotbe/claude-memory.git

# Install pydantic for write operations
pip install 'pydantic>=2.0,<3.0'
```

Then restart Claude Code. The plugin will be detected automatically via `.claude-plugin/plugin.json`.

To uninstall, remove the `claude-memory` directory from your plugins folder.

## How It Works

### Storage Structure

Memories are stored per-project in `.claude/memory/`:

```
your-project/
└── .claude/
    └── memory/
        ├── memory-config.json    # Per-project config
        ├── index.md              # Lightweight retrieval index
        ├── sessions/             # Session summaries
        ├── decisions/            # Decision records
        ├── runbooks/             # Fix procedures
        ├── constraints/          # Known limitations
        ├── tech-debt/            # Deferred work
        └── preferences/          # Conventions
```

### The Index

`index.md` is the retrieval layer -- a lightweight file with one-line summaries of every memory. The retrieval hook reads this (not every JSON file) to decide what's relevant, keeping token costs low.

Format:
```
- [DECISION] Use JWT tokens for API auth -> .claude/memory/decisions/jwt-auth-over-session-cookies.json
- [CONSTRAINT] Discourse Managed Pro: no custom plugins -> .claude/memory/constraints/discourse-managed-pro-no-plugins.json
```

### JSON Schema

All memory files follow the same base structure:

```json
{
  "schema_version": "1.0",
  "category": "decision",
  "id": "use-postgres-over-mongo-for-analytics",
  "title": "Use Postgres for analytics instead of Mongo",
  "record_status": "active",
  "created_at": "2026-02-11T14:30:00Z",
  "updated_at": "2026-02-11T14:30:00Z",
  "tags": ["database", "architecture", "analytics"],
  "related_files": ["src/db/schema.prisma"],
  "confidence": 0.9,
  "changes": [],
  "times_updated": 0,
  "content": {
    "status": "accepted",
    "context": "Need a database for analytics workload",
    "decision": "Use Postgres with materialized views",
    "rationale": ["Team already has Postgres expertise"],
    "consequences": ["Need materialized view refresh cron"]
  }
}
```

Additional lifecycle fields (`retired_at`, `retired_reason`, `archived_at`, `archived_reason`) are managed automatically when memories are retired or archived.

Full JSON Schema definitions are in `assets/schemas/`.

### Memory Lifecycle

Every memory has a `record_status` that controls its visibility and retention:

| Status | Indexed? | Retrievable? | GC-eligible? | Description |
|--------|----------|-------------|-------------|-------------|
| `active` | Yes | Yes | No | Default for all new memories |
| `retired` | No | No | Yes (after grace period) | Soft-retired; preserved for 30-day grace period |
| `archived` | No | No | No | Preserved indefinitely for historical reference |

**State transitions:**
- `active` -> `retired` via `/memory --retire <slug>` or auto-capture DELETE
- `active` -> `archived` via `/memory --archive <slug>`
- `retired` -> `active` via `/memory --restore <slug>`
- `archived` -> `active` via `/memory --unarchive <slug>`

Retired memories are permanently deleted by garbage collection (`/memory --gc`) after the grace period (default: 30 days, configurable via `delete.grace_period_days`). Archived memories are never garbage collected.

## Commands

| Command | Description |
|---------|-------------|
| `/memory` | Show memory status and statistics |
| `/memory --retire <slug>` | Soft-retire a memory (30-day grace period) |
| `/memory --archive <slug>` | Shelve a memory permanently (preserved, not GC'd) |
| `/memory --unarchive <slug>` | Restore an archived memory to active |
| `/memory --restore <slug>` | Restore a retired memory to active status |
| `/memory --gc` | Garbage collect retired memories past the grace period |
| `/memory --list-archived` | List all archived memories |
| `/memory:config <instruction>` | Configure settings using natural language |
| `/memory:search <query>` | Search memories by keyword |
| `/memory:save <category> <content>` | Manually save a memory |

### Examples

```
/memory                                    # See what's stored
/memory:search rate limit                  # Find memories about rate limiting
/memory:search --include-retired database  # Include retired/archived in search
/memory:save decision "We chose Vitest over Jest for speed and ESM support"
/memory:config disable runbook auto-capture
/memory --retire old-api-design            # Soft-retire, 30-day grace period
/memory --archive legacy-payment-provider  # Preserve indefinitely
/memory --restore old-api-design           # Undo retirement (if file not yet GC'd)
/memory --gc                               # Clean up expired retirements
```

## Configuration

Per-project config lives at `.claude/memory/memory-config.json`. Defaults are applied automatically on first use.

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `retrieval.max_inject` | `5` | Max memories injected per prompt (clamped 0-20) |
| `retrieval.enabled` | `true` | Master on/off for auto-retrieval |
| `triage.enabled` | `true` | Master on/off for auto-capture triage |
| `triage.max_messages` | `50` | Transcript tail size for triage (clamped 10-200) |
| `triage.thresholds.*` | varies | Per-category trigger sensitivity (0.0-1.0) |
| `categories.*.enabled` | `true` | Enable/disable a category |
| `categories.*.auto_capture` | `true` | Enable/disable auto-capture for a category |
| `categories.*.retention_days` | `0` (permanent) | Auto-expire after N days (90 for sessions) |
| `categories.session_summary.max_retained` | `5` | Rolling window: max active session summaries |
| `max_memories_per_category` | `100` | Max files per category folder |
| `delete.grace_period_days` | `30` | Days before retired memories are purged by GC |
| `delete.archive_retired` | `true` | Agent-interpreted: archive instead of purge on GC (not script-enforced) |
| `triage.parallel.enabled` | `true` | Enable parallel per-category subagent processing |
| `triage.parallel.category_models` | see below | Per-category model tier hint: `"haiku"`, `"sonnet"`, or `"opus"` (interpreted by orchestrator, not literal model IDs) |
| `triage.parallel.verification_model` | `"sonnet"` | Model for verification subagents |
| `triage.parallel.default_model` | `"haiku"` | Fallback model for unconfigured categories |

Default `category_models`: session_summary=haiku, decision=sonnet, runbook=haiku, constraint=sonnet, tech_debt=haiku, preference=haiku.

Default `triage.thresholds`: decision=0.4, runbook=0.4, constraint=0.5, tech_debt=0.4, preference=0.4, session_summary=0.6. Higher values = fewer but higher-confidence captures. Threshold keys are case-insensitive (both `decision` and `DECISION` work).

**`retention_days` vs `grace_period_days`**: These serve different purposes. `retention_days` is an agent-interpreted hint for when to consider auto-retiring old entries (e.g., 90 days for session summaries). `grace_period_days` is the script-enforced delay between retirement and permanent deletion by GC. A session summary with `retention_days=90` may be auto-retired after 90 days, then permanently deleted 30 days later (after the grace period).

Note: `retrieval.enabled` defaults to `true` when absent from config and is not included in the default config file.

See `assets/memory-config.default.json` for the complete config structure with all options.

## Index Maintenance

The index (`index.md`) is a derived artifact auto-generated from the authoritative JSON files. If it gets out of sync (e.g., after a git merge or manual file changes), use the included utility:

```bash
# Rebuild index from scratch (regenerates from JSON files)
python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory

# Validate index against actual files (detect desync)
python3 hooks/scripts/memory_index.py --validate --root .claude/memory

# Search index entries by keyword
python3 hooks/scripts/memory_index.py --query "authentication" --root .claude/memory

# Health check: category counts, heavily-updated entries, sync status
python3 hooks/scripts/memory_index.py --health --root .claude/memory

# Garbage collect: delete retired memories past the grace period
python3 hooks/scripts/memory_index.py --gc --root .claude/memory
```

The retrieval hook auto-rebuilds the index if it is missing but the memory root directory exists.

## Architecture

### Data Flow

```
User presses stop
  │
  ▼
memory_triage.py (Phase 0 · deterministic · stdlib Python)
  ├─ read stdin JSON from Claude Code
  ├─ load config (thresholds, parallel models)
  ├─ parse transcript tail (last N messages via deque)
  ├─ score 6 categories (keyword heuristic + co-occurrence)
  ├─ write /tmp/.memory-triage-context-<cat>.txt per triggered category
  └─ exit 2 + stderr: human message + <triage_data> JSON
        │
        ▼
  SKILL.md orchestration (Phase 1 · parallel Task subagents)
  ├─ parse <triage_data> JSON
  ├─ for each category: spawn Task(model=config.category_models[cat])
  │     ├─ read context file (<transcript_data> boundary tags)
  │     ├─ run memory_candidate.py → VETO/NOOP/CREATE/UPDATE_OR_DELETE
  │     └─ write draft JSON to /tmp/.memory-draft-<cat>-<pid>.json
  │           │
  │           ▼
  ├─ Phase 2: spawn verification subagents (content quality check)
  │     └─ PASS / FAIL per draft
  │           │
  │           ▼
  └─ Phase 3: main agent applies CUD resolution table
        ├─ memory_write.py --action create/update/retire/archive/unarchive
        │     ├─ Pydantic schema validation
        │     ├─ atomic write (tmp + rename)
        │     └─ lock index.md + atomic index update
        └─ enforce session rolling window
              │
              ▼
        User can stop (stop_hook_active flag allows through)
```

### Four-Phase Auto-Capture

Auto-capture uses a four-phase mechanism:

**Phase 0: Triage** (deterministic, stdlib Python). A single command-type Stop hook reads the transcript tail and applies keyword heuristic scoring across all 6 categories. If any category exceeds its threshold, the hook blocks the stop and outputs:
- Human-readable message listing triggered categories
- `<triage_data>` JSON block with per-category scores, context file paths, and model assignments
- Context files at `/tmp/.memory-triage-context-<category>.txt` with generous transcript excerpts (capped at 50KB)

The `stop_hook_active` flag prevents infinite loops -- when the agent stops again after saving, the hook allows it through.

**Phase 1: Parallel Drafting** (per-category subagents). For each triggered category, a Task subagent is spawned with the configured model (haiku for simple categories, sonnet for complex ones). Each subagent reads its context file, runs `memory_candidate.py` for CRUD awareness, and drafts a memory JSON.

**Phase 2: Verification** (verification subagents). Each draft is checked by a verification subagent (default: sonnet) for content quality and deduplication. Schema validation is handled by `memory_write.py` in Phase 3.

**Phase 3: Save** (main agent). The main agent applies the CUD resolution table, then calls `memory_write.py` for each verified draft.

| Category | Triage Signal |
|----------|--------------|
| SESSION_SUMMARY | Sufficient activity metrics (tool uses, exchanges) |
| DECISION | Choice keywords + rationale co-occurrence ("decided X because Y") |
| RUNBOOK | Error keywords + resolution co-occurrence ("error ... fixed by") |
| CONSTRAINT | Limitation keywords + discovery co-occurrence |
| TECH_DEBT | Deferral keywords + acknowledgment co-occurrence ("deferred ... because") |
| PREFERENCE | Convention keywords + agreement co-occurrence |

### Auto-Retrieval

The UserPromptSubmit hook uses a Python command script (`hooks/scripts/memory_retrieve.py`) that:
1. Reads the user's prompt from stdin (hook input JSON)
2. Reads `.claude/memory/index.md`
3. Matches entries against the prompt using keyword scoring
4. Outputs relevant entries (up to `max_inject`, default 5) to stdout, which gets injected as context for Claude

This is faster and more reliable than a prompt-based retrieval hook, since it does deterministic keyword matching without LLM overhead.

### Shared Index

All categories share `index.md` for discoverability. The main agent writes files sequentially in Phase 3 (not the subagents), and `mkdir`-based locking handles concurrent access. Updates use optimistic concurrency control (MD5 hash check) to prevent lost writes. All writes use a temp-file + rename pattern for atomicity. If the index gets out of sync, `memory_index.py --rebuild` fixes it.

### Hooks

All hooks are configured in `hooks/hooks.json` as command-type hooks (no prompt hooks):

| Hook | Trigger | Script | Timeout |
|------|---------|--------|---------|
| Stop | `*` | `memory_triage.py` | 30s |
| UserPromptSubmit | `*` | `memory_retrieve.py` | 10s |
| PreToolUse | Write | `memory_write_guard.py` | 5s |
| PostToolUse | Write | `memory_validate_hook.py` | 10s |

The `stop_hook_active` flag (`.claude/.stop_hook_active`) prevents infinite loops: when the triage hook blocks a stop to save memories, it creates this flag. On the next stop, the hook allows through immediately. The flag auto-expires after 5 minutes.

## Token Cost

The plugin adds overhead to each conversation.

**Phase 0: Triage** (always runs at stop, zero LLM cost):
- Deterministic Python keyword heuristic -- no model calls
- **Retrieval**: Also zero LLM cost (Python keyword matcher)

**Phases 1-3: Draft + Verify + Save** (only when triage triggers):
- **Drafting subagents**: One per triggered category, running on haiku (simple) or sonnet (complex)
- **Verification subagents**: One per draft, running on sonnet
- **Save**: Main agent calls memory_write.py (minimal tokens)

**Cost optimization**: Simple categories (session_summary, runbook, tech_debt, preference) use haiku. Complex categories (decision, constraint) use sonnet. Model assignments are configurable via `triage.parallel.category_models`.

**Requirements**: Python 3.8+, pydantic v2 (for write operations). See [Prerequisites](#prerequisites).

## Troubleshooting

**Memories not being captured (nothing happens on stop):**
- Check `triage.enabled` is `true` in your config (it is by default)
- Sessions need enough signal -- use keywords like "decided", "chose", "error", "fixed by" to trigger categories
- Lower the triage threshold for a category: `/memory:config set decision threshold to 0.3`
- Use `/memory:save` as a fallback for manual saves

**Memories not being retrieved (Claude doesn't reference stored memories):**
- Check `retrieval.enabled` is `true` and `retrieval.max_inject` > 0
- Retrieval uses exact keyword matching on index titles/tags, not semantic search. "API throttling" won't match a memory titled "API rate limit"
- Prompts shorter than 10 characters are skipped; common stop words are filtered
- Use `/memory:search <keywords>` to verify the memory exists

**Pydantic not installed (write operations fail):**
- Run `pip install 'pydantic>=2.0,<3.0'`
- Only `memory_write.py` and `memory_validate_hook.py` require pydantic; triage and retrieval work without it
- The write script attempts to re-exec under the plugin's `.venv/bin/python3` (e.g., `~/.claude/plugins/claude-memory/.venv`) if pydantic is missing from system Python. A project-local `.venv` is not used for this bootstrap.

**Index out of sync (search returns stale or missing results):**
- Run `python3 hooks/scripts/memory_index.py --validate --root .claude/memory` to detect issues
- Run `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory` to regenerate
- The index auto-rebuilds when missing, but does not auto-fix stale entries
- After git merges or manual file changes, always rebuild

**Quarantined files (`.invalid.*` files in memory directory):**
- These are created by the PostToolUse validation hook when a memory file fails schema validation
- Inspect the quarantined file to understand the issue, then either fix and re-save or delete it
- The naming convention is `<filename>.invalid.<unix_timestamp>`
- Note: PostToolUse hooks run after the write has already occurred. The "deny" response informs the agent but cannot undo the write. The PreToolUse guard is the primary prevention layer; the PostToolUse hook is detection-only with quarantine as a mitigation.

**Hook errors (warning messages during session):**
- All hooks fail-open: errors produce warnings but never trap the user
- Common warnings like "Config parse error, using defaults" are informational
- If hooks consistently fail, check that Python 3 is available and scripts are executable

**Anti-resurrection error (CREATE blocked after recent retirement):**
- A memory cannot be re-created within 24 hours of retirement at the same file path
- Workarounds: use a different title/slug, wait 24 hours, or restore the old memory with `/memory --restore` and update it

**OCC conflict (concurrent write detected):**
- This occurs when two sessions try to update the same memory simultaneously
- The write is rejected to prevent data loss -- re-read the memory and retry

## Sensitive Data

Auto-capture may inadvertently save sensitive information from your conversations. If this happens:

1. **Immediate removal**: `/memory --retire <slug>` to remove it from the index
2. **Permanent deletion**: After retirement, run `/memory --gc` (respects grace period) or for immediate removal, manually delete the file and rebuild the index with `memory_index.py --rebuild`
3. **Git history**: If the memory was committed, use `git filter-branch` or `git filter-repo` to scrub the file from history
4. **Prevention**: Disable auto-capture for categories that may capture sensitive data: `/memory:config disable <category> auto-capture`. Or add `.claude/memory/` to `.gitignore` if memories should not be committed.

## Upgrading

To upgrade the plugin:

1. `cd ~/.claude/plugins/claude-memory && git pull`
2. Restart Claude Code
3. Verify: `python3 hooks/scripts/memory_index.py --validate --root .claude/memory`

Existing memories and config are preserved across upgrades. The plugin uses backward-compatible schemas with lazy migration (new fields are added on the next update to each memory). Check the Version History section for breaking changes between major versions (e.g., v4 -> v5 replaced 6 hooks with 1).

## Known Limitations

- **Custom categories**: The 6 built-in categories each have dedicated Pydantic schemas. Custom categories are not supported by the validation pipeline.

## Design Decisions

- **Anti-resurrection window (24h)**: When a memory is retired, `--action create` is blocked at the same file path for 24 hours. This is an intentional safety feature that prevents accidental re-creation of recently deleted memories. The `--action restore` command bypasses this check because intentional restoration is a separate code path.
- **Agent-interpreted config keys**: Some config keys (`categories.*.enabled`, `auto_capture`, `retention_days`, `auto_commit`, `max_memories_per_category`, `retrieval.match_strategy`, `delete.archive_retired`) are read by the LLM via SKILL.md instructions, not by Python scripts. This is intentional -- these keys represent qualitative decisions (e.g., "should this memory be retired?") that require LLM judgment and cannot be reduced to deterministic script logic.

## Notes

**Cross-project memories**: Memories are stored per-project in `.claude/memory/`. To share memories between projects, copy the JSON files to the target project's memory directory and rebuild the index with `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory`.

**Performance**: The retrieval hook uses lightweight keyword matching on the index file (no LLM calls), completing in under 10ms for typical stores. First retrieval after a missing index may be slower (up to 10 seconds) due to automatic index rebuild. If retrieval feels slow, reduce `retrieval.max_inject` or temporarily disable retrieval with `/memory:config set retrieval.enabled to false`.

## Version History

- **v5.0.0** (current): Replaced 6 prompt-type Stop hooks with 1 deterministic command-type hook. Added parallel per-category subagent processing, context files, and structured `<triage_data>` output.
- **v4.2**: ACE (Adaptive Consolidation Engine) -- Python-tool-centric CRUD, Pydantic schema validation, merge protections, OCC, 2-layer CUD verification. See `action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md` for the original design.
- **v3.0**: Initial structured memory with 6 categories, keyword retrieval, and manual save commands.

## Testing

**Current state:** Tests exist in `tests/` with 6 test files (2,169 LOC) covering all 6 scripts. No CI/CD yet.

**Framework:** pytest

```bash
# Install test dependencies
pip install pytest pydantic>=2.0

# Run tests
pytest tests/ -v
```

**Key files that need test coverage:**

| Script | Role |
|--------|------|
| `hooks/scripts/memory_retrieve.py` | Keyword-based retrieval (stdlib only) |
| `hooks/scripts/memory_index.py` | Index rebuild/validate/query CLI (stdlib only) |
| `hooks/scripts/memory_candidate.py` | Candidate selection for update/delete (stdlib only) |
| `hooks/scripts/memory_write.py` | Schema-enforced write operations (requires pydantic v2) |
| `hooks/scripts/memory_write_guard.py` | PreToolUse write guard (stdlib only) |
| `hooks/scripts/memory_validate_hook.py` | PostToolUse validation + quarantine (pydantic v2 optional) |

See `action-plans/_ref/TEST-PLAN.md` for the full prioritized test plan including security considerations.
See `CLAUDE.md` for development guidance and security notes.

## License

MIT
