# claude-memory

Structured memory management plugin for [Claude Code](https://claude.ai/code). Automatically captures decisions, runbooks, constraints, tech debt, session summaries, and preferences as JSON files with intelligent retrieval.

## What It Does

claude-memory gives Claude Code persistent, structured memory across sessions. Instead of losing context when a conversation ends, important information is automatically saved as categorized JSON files and retrieved when relevant.

**Auto-capture** (6 parallel Stop hooks): After each conversation turn, 6 lightweight triage hooks evaluate in parallel whether anything worth remembering happened. Each hook runs on Sonnet and evaluates exactly one category. If triggered, the hook blocks the stop and the main agent (with full tool access) writes the memory file.

**Auto-retrieval** (UserPromptSubmit hook): When you send a message, a Python script reads the memory index and injects relevant entries as context for Claude.

## Memory Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| `session_summary` | `sessions/` | Work resume snapshots -- what happened, what's next |
| `decision` | `decisions/` | Choices with rationale -- why X over Y |
| `runbook` | `runbooks/` | Error fix procedures -- symptom, fix, verification |
| `constraint` | `constraints/` | Known limitations -- what can't be done and why |
| `tech_debt` | `tech-debt/` | Deferred work -- what was skipped and the cost |
| `preference` | `preferences/` | Conventions -- how things should be done |

## Installation

```bash
# Clone into your Claude Code plugins directory
cd ~/.claude/plugins   # or wherever your plugins live
git clone https://github.com/idnotbe/claude-memory.git
```

Then restart Claude Code. The plugin will be detected automatically via `.claude-plugin/plugin.json`.

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
  "created_at": "2026-02-11T14:30:00Z",
  "updated_at": "2026-02-11T14:30:00Z",
  "tags": ["database", "architecture", "analytics"],
  "related_files": ["src/db/schema.prisma"],
  "confidence": 0.9,
  "content": {
    "status": "accepted",
    "context": "Need a database for analytics workload",
    "decision": "Use Postgres with materialized views",
    "rationale": ["Team already has Postgres expertise"],
    "consequences": ["Need materialized view refresh cron"]
  }
}
```

Full JSON Schema definitions are in `assets/schemas/`.

## Commands

| Command | Description |
|---------|-------------|
| `/memory` | Show memory status and statistics |
| `/memory:config <instruction>` | Configure settings using natural language |
| `/memory:search <query>` | Search memories by keyword |
| `/memory:save <category> <content>` | Manually save a memory |

### Examples

```
/memory                          # See what's stored
/memory:search rate limit        # Find memories about rate limiting
/memory:save decision "We chose Vitest over Jest for speed and ESM support"
/memory:config disable runbook auto-capture
```

## Configuration

Per-project config lives at `.claude/memory/memory-config.json`. Defaults are applied automatically on first use.

Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `categories.*.enabled` | `true` | Enable/disable a category |
| `categories.*.auto_capture` | `true` | Enable/disable auto-capture for a category |
| `categories.*.retention_days` | `0` (permanent) | Auto-expire after N days (90 for sessions) |
| `retrieval.max_inject` | `5` | Max memories injected per prompt |
| `max_memories_per_category` | `100` | Max files per category folder |

## Index Maintenance

If the index gets out of sync, use the included utility:

```bash
# Rebuild index from scratch
python hooks/scripts/memory_index.py --rebuild --root .claude/memory

# Validate index against actual files
python hooks/scripts/memory_index.py --validate --root .claude/memory

# Search index entries
python hooks/scripts/memory_index.py --query "authentication" --root .claude/memory
```

## Architecture

### Two-Phase Auto-Capture

Auto-capture uses a two-phase mechanism:

**Phase 1: Triage** (Sonnet, parallel). Six lightweight prompt hooks run in parallel after each conversation turn. Each evaluates exactly one category using a ~120-token prompt. Sonnet returns either "approve" (nothing to save) or "block" with a reason describing what to save.

**Phase 2: Write** (main agent, sequential). If any hooks block, the main agent continues with full tool access. It receives the hook reasons as instructions and writes the memory files following the SKILL.md format guide. The `stop_hook_active` flag in the hook input prevents infinite loops -- when the main agent stops again after writing, all hooks see `stop_hook_active: true` and approve immediately.

| Hook | Triage Question |
|------|----------------|
| SESSION_SUMMARY | Was a specific task completed, file modified with intent, or project decision made? |
| DECISION | Was a choice made between alternatives with stated rationale ("chose X because Y")? |
| RUNBOOK | Was a non-trivial error diagnosed, fixed, AND verified? (all three required) |
| CONSTRAINT | Was an enduring limitation from external factors discovered? |
| TECH_DEBT | Was work explicitly deferred with acknowledged cost/risk ("deferring X because Y")? |
| PREFERENCE | Was a new convention deliberately established for future consistency? |

### Auto-Retrieval

The UserPromptSubmit hook uses a Python command script (`hooks/scripts/memory_retrieve.py`) that:
1. Reads the user's prompt from stdin (hook input JSON)
2. Reads `.claude/memory/index.md`
3. Matches entries against the prompt using keyword scoring
4. Outputs relevant entries (max 5) to stdout, which gets injected as context for Claude

This is faster and more reliable than a prompt-based retrieval hook, since it does deterministic keyword matching without LLM overhead.

### Shared Index

The 6 category hooks share `index.md` for discoverability. Since the main agent writes files sequentially in Phase 2 (not the hooks themselves), there are no race conditions on index.md writes. If the index gets out of sync for any reason, `memory_index.py --rebuild` fixes it.

## Token Cost

The plugin adds overhead to each conversation turn.

**Phase 1: Triage** (always incurred, runs on Sonnet):
- **6 Stop hooks**: ~720 tokens total prompt text (6 x ~120 tokens each)
- **Retrieval**: Near zero LLM cost (Python script, no model call)
- **Sonnet output**: ~10-20 tokens per hook (JSON response)

**Phase 2: Write** (only when a hook triggers, runs on main model):
- **1 category triggers**: ~500-1,500 tokens (read index, write JSON, update index)
- **Multiple categories trigger**: Proportionally more, but rare in a single turn

**Estimated per-session overhead** (10 messages, 1-2 saves): Triage runs on Sonnet. Writes run on the main model but only when triggered. 

**Requirements**: Python 3 for the retrieval script.


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

See `TEST-PLAN.md` for the full prioritized test plan including security considerations.
See `CLAUDE.md` for development guidance and security notes.

## License

MIT
