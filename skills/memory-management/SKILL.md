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

## Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| session_summary | sessions/ | Work resume snapshot |
| decision | decisions/ | Choice + rationale (why X over Y) |
| runbook | runbooks/ | Error fix procedure (diagnose, fix, verify) |
| constraint | constraints/ | Known limitations (enduring walls) |
| tech_debt | tech-debt/ | Deferred work (what was skipped and why) |
| preference | preferences/ | Conventions (how things should be done) |

## Memory Consolidation

When a triage hook fires with a save instruction:

### 1. Find Candidate
Call `memory_candidate.py` with the category and new information summary.
You will receive one of:
- `pre_action: "CREATE"` -- no matching memory exists. Skip to step 3.
- `pre_action: "NOOP"` -- lifecycle event but no matching memory. Do nothing.
- `candidate: {...}` -- a potential match was found. Proceed to step 2.

### 2. CUD Verification (decide-then-compare)
You have three assessments:
- L1 (STRUCTURAL): From memory_candidate.py output (structural_cud, vetoes).
- L2 (TRIAGE): From triage hook output (cud_recommendation).
- L3 (YOUR DECISION): Form your OWN CUD decision FIRST by reading the
  candidate excerpt. Only THEN compare with L1 and L2.

RESOLUTION RULES:
- If L1 has vetoes -> OBEY the veto (mechanical trumps LLM)
- If all 3 agree -> Proceed with agreed action
- If you disagree with L2:
  - CREATE vs UPDATE -> UPDATE (preserves existing)
  - UPDATE vs DELETE -> UPDATE (non-destructive)
  - CREATE vs DELETE -> NOOP (contradictory signals)
- State: "CUD: [ACTION] (L1:[x], L2:[y], L3:[z] [resolution])"

### 3. Execute
Based on the action:
- **CREATE**: Draft a new memory JSON following the schema.
  Write to `/tmp/.memory-write-pending-<pid>.json` (use your process ID or a unique suffix).
  Call `memory_write.py --action create --category <cat> --target <path>
  --input /tmp/.memory-write-pending-<pid>.json`.
- **UPDATE**: Read the candidate file and compute its MD5 hash for OCC.
  Integrate new info (tags: union, lists: append, scalars: update).
  Write complete updated JSON to `/tmp/.memory-write-pending-<pid>.json`.
  Call `memory_write.py --action update --category <cat> --target <path>
  --input /tmp/.memory-write-pending-<pid>.json --hash <md5>`.
- **DELETE** (soft retire): Call `memory_write.py --action delete --target <path>
  --reason "<why>"`. Do not write a temp file for DELETE.

State your chosen action and one-line justification before calling
memory_write.py.

## CUD Verification Rules

| L1 (Python) | L2 (Sonnet) | L3 (Opus) | Resolution | Rationale |
|-------------|-------------|-----------|------------|-----------|
| CREATE | CREATE | CREATE | CREATE | Unanimous |
| UPDATE_OR_DELETE | UPDATE | UPDATE | UPDATE | Unanimous |
| UPDATE_OR_DELETE | DELETE | DELETE | DELETE | Unanimous (structural permits) |
| CREATE | CREATE | UPDATE | UPDATE | Opus found candidate L1 missed |
| CREATE | UPDATE | CREATE | CREATE | Structural confirms none exists |
| UPDATE_OR_DELETE | UPDATE | DELETE | **UPDATE** | Safety default: non-destructive |
| UPDATE_OR_DELETE | DELETE | UPDATE | **UPDATE** | Safety default: non-destructive |
| CREATE | DELETE | * | **NOOP** | Cannot DELETE with 0 candidates (structural veto) |
| UPDATE_OR_DELETE | CREATE | CREATE | CREATE | Both LLMs say CREATE despite candidate |
| VETO | * | * | **OBEY VETO** | Mechanical invariant violated |
| NOOP | * | * | **NOOP** | No target for lifecycle action |

Key principles:
1. Mechanical trumps LLM: Python vetoes are absolute.
2. Safety defaults for LLM disagreements: UPDATE over DELETE (non-destructive), UPDATE over CREATE (avoids duplicates), NOOP for CREATE-vs-DELETE (contradictory signals).
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
3. **Deletion guard**: Before retiring the oldest session, check if it contains unique content not captured in other memories:
   - Extract key items from the session's `completed[]`, `blockers[]`, and `next_actions[]` fields.
   - Compare against index.md entries and other active session summaries.
   - If the session references decisions, constraints, or tech debt items that do NOT appear in their respective category folders, log a warning to stderr: `"WARNING: Session <slug> contains unique content not captured elsewhere: <items>. Consider saving these before retirement."`
   - The warning is informational only -- retirement still proceeds. The content is preserved during the 30-day grace period.
4. **Retire oldest**: Call `memory_write.py --action delete --target <path> --reason "Session rolling window: exceeded max_retained limit"`.

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
- `/memory --restore <slug>` -- restore a recently retired session within the grace period

## When the User Asks About Memories

- "What do you remember?" -> Read index.md and summarize
- "Remember that..." -> Create a memory in the appropriate category
- "Forget..." -> Read the memory, confirm with user, retire via memory_write.py --action delete
- "What did we decide about X?" -> Search decisions/ folder
- /memory, /memory:config, /memory:search, /memory:save -> See slash commands

## Rules

1. **CRUD lifecycle**: Memories can be created, updated, or retired through the 3-step consolidation flow
2. **Silent operation**: Do NOT mention memory operations in visible output during auto-capture
3. **Check before creating**: Always run memory_candidate.py first to avoid duplicates
4. **CUD verification**: All save operations go through 3-layer CUD verification
5. **Confidence scores**: 0.7-0.9 for most; 0.9+ only for explicitly confirmed facts
6. **All writes via memory_write.py**: Never write directly to .claude/memory/ -- use the Python tool

## Config

`.claude/memory/memory-config.json` (all defaults apply if absent):
- `categories.<name>.enabled` -- enable/disable category (default: true)
- `categories.<name>.auto_capture` -- enable/disable auto-capture (default: true)
- `categories.<name>.retention_days` -- auto-expire after N days (0 = permanent; 90 for sessions)
- `categories.session_summary.max_retained` -- max session summaries to keep (default: 5)
- `retrieval.max_inject` -- max memories injected per prompt (default: 5)
- `max_memories_per_category` -- max files per folder (default: 100)
- `delete.grace_period_days` -- days before retired records are purged (default: 30)
- `delete.archive_retired` -- whether to archive instead of purge (default: true)
