# claude-memory

Structured memory management plugin for [Claude Code](https://claude.ai/code). Automatically captures decisions, runbooks, constraints, tech debt, session summaries, and preferences as JSON files with intelligent retrieval.

## What It Does

claude-memory gives Claude Code persistent, structured memory across sessions. Instead of losing context when a conversation ends, important information is automatically saved as categorized JSON files and retrieved when relevant.

**Auto-capture** (6 parallel Stop hooks): After each conversation turn, 6 per-category hooks evaluate in parallel whether anything worth remembering happened. Each hook is focused on exactly one category, running independently for better isolation and reliability.

**Auto-retrieval** (UserPromptSubmit hook): When you send a message, the plugin checks if any stored memories are relevant and injects them as context.

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
| `retrieval.match_strategy` | `title_tags` | How to match memories to prompts |
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

### 6 Parallel Stop Hooks

Each memory category has its own dedicated Stop hook. All 6 hooks fire in parallel after each conversation turn:

| Hook | Trigger Criteria |
|------|-----------------|
| SESSION_SUMMARY | Meaningful work completed or project state changed |
| DECISION | Choice made between alternatives with stated rationale |
| RUNBOOK | Non-trivial error diagnosed, fixed, AND verified |
| CONSTRAINT | Persistent limitation discovered from external factors |
| TECH_DEBT | Work explicitly deferred with acknowledged cost/risk |
| PREFERENCE | New convention established for future consistency |

Each hook independently evaluates its single triage question. If the answer is NO, it exits immediately (~100 tokens). Only hooks that match actually write files.

### Shared Index

The 6 hooks are independent in triage and capture logic but share `index.md` for discoverability. Since hooks run in parallel, multiple hooks writing to `index.md` simultaneously is theoretically possible (e.g., a session that produces both a decision and a tech_debt entry). In practice this is rare for a single-user CLI tool, and if it occurs, `memory_index.py --rebuild` fixes the index.

## Token Cost

The plugin adds overhead to each conversation turn. Actual cost depends on Claude Code's hook execution model (whether conversation context is replicated per hook or shared).

**Prompt text overhead** (always incurred):
- **Retrieval** (per user message): ~250 tokens prompt + index.md reading
- **Capture** (per assistant response): ~2,520 tokens total prompt text (6 hooks x ~420 each)

**Output tokens** (varies):
- Fast-exit (no save): near zero per hook
- One category triggers: ~500 output tokens

**Estimated per-session overhead** (10 messages, 1-2 saves): Prompt text contributes ~28,000 tokens. If your project has additional Stop hooks (e.g., active-context updater), total Stop-phase overhead is cumulative.

For a typical Claude Code session (50,000-200,000 tokens), expect roughly 10-20% overhead from this plugin alone.

## License

MIT
