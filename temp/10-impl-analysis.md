# Implementation Analysis

Exhaustive catalog of every feature, behavior, CLI argument, config option, error path, and edge case in the claude-memory plugin. Derived from reading all source files.

---

## 1. memory_triage.py (Stop Hook)

### Purpose
Deterministic keyword-heuristic triage hook that fires on Claude Code `Stop` events. Reads the conversation transcript, scores 6 memory categories, and decides whether to block the stop so the agent can save memories. Replaces 6 older prompt-type Stop hooks with 1 command-type hook.

### CLI / Invocation
- No CLI arguments. Invoked as a command hook via stdin JSON.
- Exit code 0 = allow stop (nothing to save, or error/fallback)
- Exit code 2 = block stop (stderr contains items to save)
- On ANY uncaught exception, fails open (exit 0) with error message to stderr.

### stdin Input Format
JSON object with:
- `transcript_path` (string, optional): Path to JSONL transcript file
- `cwd` (string, optional): Working directory, defaults to `os.getcwd()`

### Config Keys Read
From `.claude/memory/memory-config.json` under `triage`:
- `triage.enabled` (bool, default: true) -- master on/off
- `triage.max_messages` (int, default: 50, clamped 10-200) -- max messages from transcript tail
- `triage.thresholds.<CATEGORY>` (float, clamped 0.0-1.0) -- per-category thresholds. Accepts both uppercase and lowercase keys (normalized to uppercase). Rejects NaN and Inf.
  - DECISION: 0.4
  - RUNBOOK: 0.4
  - CONSTRAINT: 0.5
  - TECH_DEBT: 0.4
  - PREFERENCE: 0.4
  - SESSION_SUMMARY: 0.6
- `triage.parallel.enabled` (bool, default: true)
- `triage.parallel.category_models` (dict, 6 keys: session_summary, decision, runbook, constraint, tech_debt, preference; values: "haiku"/"sonnet"/"opus")
  - Defaults: session_summary=haiku, decision=sonnet, runbook=haiku, constraint=sonnet, tech_debt=haiku, preference=haiku
- `triage.parallel.verification_model` (string, default: "sonnet")
- `triage.parallel.default_model` (string, default: "haiku")

### Constants
- `DEFAULT_MAX_MESSAGES = 50`
- `FLAG_TTL_SECONDS = 300` (5 minutes)
- `CO_OCCURRENCE_WINDOW = 4` (lines before/after a primary match)
- `CONTEXT_WINDOW_LINES = 10` (lines of context around keyword matches for context files)
- `MAX_CONTEXT_FILE_BYTES = 50_000` (50 KB max per context file)
- `VALID_MODELS = {"haiku", "sonnet", "opus"}`

### Behaviors

#### Transcript Parsing
- Reads JSONL transcript file line by line
- Uses `collections.deque(maxlen=N)` to keep only last N messages
- Gracefully handles missing files, empty files, corrupt JSONL lines (skips bad lines)
- Only processes `msg.type == "human"` or `"assistant"` for text content
- Handles content as string or list of text blocks

#### Text Preprocessing
- Strips fenced code blocks (```...```) via regex
- Strips inline code (`...`) via regex
- Reduces false positives from keywords in code

#### Activity Metrics Extraction
- Counts `tool_use` type messages (total uses + distinct tool names)
- Counts `human` and `assistant` exchanges

#### Scoring (5 text-based categories)
Each category has:
- `primary` regex patterns (must match to score)
- `boosters` regex patterns (co-occurrence amplifier within 4-line window)
- `primary_weight`, `boosted_weight`, `max_primary`, `max_boosted`, `denominator`
- Score = (primary_matches * primary_weight + boosted_matches * boosted_weight) / denominator
- Normalized to [0.0, 1.0] with `min(1.0, raw/denominator)`
- Only one primary pattern match counted per line

**DECISION** patterns:
- Primary: decided, chose, selected, went with, picked
- Boosters: because, due to, reason, rationale, over, instead of, rather than
- Weights: primary=0.3, boosted=0.5, max_primary=3, max_boosted=2, denom=1.9

**RUNBOOK** patterns:
- Primary: error, exception, traceback, stack trace, failed, failure, crash
- Boosters: fixed by, resolved, root cause, solution, workaround, the fix
- Weights: primary=0.2, boosted=0.6, max_primary=3, max_boosted=2, denom=1.8

**CONSTRAINT** patterns:
- Primary: limitation, api limit, cannot, restricted, not supported, quota, rate limit
- Boosters: discovered, found that, turns out, permanently, enduring, platform
- Weights: primary=0.3, boosted=0.5, max_primary=3, max_boosted=2, denom=1.9

**TECH_DEBT** patterns:
- Primary: TODO, deferred, tech debt, workaround, hack, will address later, technical debt
- Boosters: because, for now, temporary, acknowledged, deferring, cost, risk
- Weights: primary=0.3, boosted=0.5, max_primary=3, max_boosted=2, denom=1.9

**PREFERENCE** patterns:
- Primary: always use, prefer, convention, from now on, standard, never use, established
- Boosters: agreed, going forward, consistently, rule, practice, workflow
- Weights: primary=0.35, boosted=0.5, max_primary=3, max_boosted=2, denom=2.05

#### Scoring (SESSION_SUMMARY -- activity-based)
- Formula: `min(1.0, tool_uses * 0.05 + distinct_tools * 0.1 + exchanges * 0.02)`
- No text matching, purely activity metrics

#### Stop Flag Mechanism
- Flag file: `<cwd>/.claude/.stop_hook_active`
- On block (exit 2): creates flag file with current timestamp
- On next stop: if flag exists and age < 300s (5 min), allows stop immediately (exit 0) and deletes flag
- If flag is stale (>5 min): ignored (continues evaluation)
- Uses exception-based flow to avoid TOCTOU races

#### Context File Generation
- Writes per-category files to `/tmp/.memory-triage-context-<category_lowercase>.txt`
- For text-based categories: merges context windows around keyword match lines (+/- 10 lines), separated by `---`
- For SESSION_SUMMARY: writes activity metrics (tool uses, distinct tools, exchanges)
- Truncates at 50KB with `[Truncated: context exceeded 50KB]` marker
- Secure file creation: `O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW` with mode 0o600
- Each file contains: Category, Score, `<transcript_data>` block, Key snippets section

#### Output Format (stderr on exit 2)
1. Human-readable message listing triggered categories with sanitized snippets and scores
2. Empty line
3. Instruction: "Use the memory-management skill to save each item..."
4. `<triage_data>` JSON block containing:
   - `categories[]`: array of `{category (lowercase), score, context_file}`
   - `parallel_config`: `{enabled, category_models, verification_model, default_model}`

#### Snippet Sanitization
- Strips control characters (\x00-\x1f, \x7f)
- Strips zero-width Unicode (U+200B-U+200F, U+2028-U+202F, U+2060-U+2069, U+FEFF, U+E0000-U+E007F including tag characters)
- Removes backticks
- Escapes XML: `&` -> `&amp;`, `<` -> `&lt;`, `>` -> `&gt;`
- Truncates to 120 chars

### stdin Reading
- Uses `select.select()` with timeout (default 2s) since Claude Code doesn't send EOF
- After first successful read, uses 0.1s timeout to drain remaining data
- Reads in 64KB chunks

### Transcript Path Validation (Defense in Depth)
- `os.path.realpath()` to resolve symlinks
- Must start with `/tmp/` or `$HOME/`
- Rejects paths outside these scopes

### Error Paths
- Empty stdin -> exit 0
- Invalid JSON stdin -> exit 0
- Non-dict stdin -> exit 0
- Missing transcript_path -> exit 0
- Transcript file not found -> exit 0
- Transcript path outside allowed scope -> exit 0
- Empty transcript -> exit 0
- Config parse errors -> fall back to defaults
- Context file write failures -> silently skipped (non-critical)
- Any uncaught exception in `main()` -> fail-open exit 0 with stderr message

### Dependencies
- stdlib only (no external packages)

---

## 2. memory_retrieve.py (UserPromptSubmit Hook)

### Purpose
Keyword-based retrieval hook that fires on every user prompt. Matches prompt words against index.md entries and injects relevant memories into Claude's context via stdout.

### CLI / Invocation
- No CLI arguments. Invoked as command hook via stdin JSON.
- Exit code 0 always (outputs to stdout which is added to context)
- Calls `sys.exit(0)` to exit early in many conditions

### stdin Input Format
JSON object with:
- `user_prompt` (string): The user's prompt text
- `cwd` (string, optional): Working directory, defaults to `os.getcwd()`

### Config Keys Read
From `.claude/memory/memory-config.json`:
- `retrieval.enabled` (bool, default: true) -- if false, exits immediately
- `retrieval.max_inject` (int, default: 5, clamped 0-20) -- max memories injected

### Constants
- `STOP_WORDS`: 70+ common English words (a, an, the, is, was, etc.)
- `CATEGORY_PRIORITY`: DECISION=1, CONSTRAINT=2, PREFERENCE=3, RUNBOOK=4, TECH_DEBT=5, SESSION_SUMMARY=6
- `_DEEP_CHECK_LIMIT = 20` -- top N candidates for JSON file deep-checking
- `_RECENCY_DAYS = 30` -- recency bonus window
- Minimum prompt length: 10 characters (shorter prompts silently skipped)
- Minimum token length: 3 characters (shorter tokens excluded)

### Behaviors

#### Index Auto-Rebuild
- If `index.md` doesn't exist but memory root directory does, auto-rebuilds by running `memory_index.py --rebuild`
- Uses subprocess with 10s timeout
- Silently proceeds if rebuild fails

#### Tokenization
- Regex: `[a-z0-9]+` (lowercase alphanumeric tokens)
- Filters out stop words and tokens <= 2 characters

#### Index Line Parsing
- Regex: `^- \[([A-Z_]+)\] (.+?) -> (\S+)(?:\s+#tags:(.+))?$`
- Extracts: category, title, path, tags (optional)
- Tags parsed as comma-separated, lowercased, stripped

#### Scoring Algorithm (2-pass)
**Pass 1 (text matching):**
- Exact word match on title: 2 points
- Exact tag match: 3 points
- Prefix match (4+ chars) on title or tags: 1 point
- Sort: highest score first, then by category priority (lower = higher priority)

**Pass 2 (deep check on top 20):**
- Reads JSON files to check:
  - `record_status == "retired"` -> excluded (defense in depth)
  - `updated_at` within 30 days -> +1 recency bonus
- Entries beyond top 20 get no recency check, assumed not retired
- Re-sort with adjusted scores
- Take top `max_inject` entries

#### Output Format (stdout)
```
<memory-context source=".claude/memory/">
- [CATEGORY] sanitized_title -> path #tags:tag1,tag2
</memory-context>
```

#### Title Sanitization (retrieval side, defense-in-depth)
- Strips control characters (\x00-\x1f, \x7f)
- Strips zero-width/bidi Unicode (U+200B-U+200F, U+2028-U+202F, U+2060-U+2069, U+FEFF)
- Replaces ` -> ` with ` - ` (index-injection prevention)
- Removes `#tags:` substring
- Escapes XML: `&`, `<`, `>`
- Truncates to 120 chars

### Error Paths
- Empty stdin -> exit 0
- Invalid JSON stdin -> exit 0
- Prompt < 10 chars -> exit 0
- No memory root -> exit 0
- No index after rebuild attempt -> exit 0
- Config parse errors -> use defaults (max_inject=5, enabled=true)
- Invalid max_inject value -> warning to stderr, use default 5
- max_inject=0 -> exit 0
- No entries in index -> exit 0
- No prompt tokens after filtering -> exit 0
- No scored entries -> exit 0
- File read errors during deep check -> (False, False) for recency/retired

### Dependencies
- stdlib only
- Optionally imports `subprocess` for auto-rebuild

---

## 3. memory_index.py (Index Management Utility)

### Purpose
CLI tool for rebuilding, validating, querying, health-checking, and garbage-collecting the `index.md` file.

### CLI Arguments
- `--root <path>` (default: `.claude/memory`) -- root directory of memory storage
- Mutually exclusive group (one required):
  - `--rebuild` -- scan all memory files and regenerate index.md
  - `--validate` -- check index.md against actual files
  - `--query <KEYWORD>` -- search index entries by keyword
  - `--health` -- report memory store statistics and health
  - `--gc` -- garbage collect retired memories past grace period

### Constants
- `CATEGORY_FOLDERS`: session_summary->sessions, decision->decisions, runbook->runbooks, constraint->constraints, tech_debt->tech-debt, preference->preferences
- `CATEGORY_DISPLAY`: session_summary->SESSION_SUMMARY, decision->DECISION, etc.

### Behaviors

#### scan_memories(root, include_inactive=False)
- Iterates all 6 category folders
- Reads each `.json` file, extracts metadata
- By default, only includes `record_status == "active"` entries
- `include_inactive=True` includes retired and archived entries
- Computes relative path from project root (root.parent.parent)
- Replaces backslashes with forward slashes for cross-platform consistency
- Handles JSON parse errors with WARNING to stderr

#### --rebuild
- Scans active memories only
- Sorts by category display name, then title (case-insensitive)
- Generates index.md with header: `# Memory Index`, auto-generated comment
- Each line: `- [CATEGORY_DISPLAY] title -> relative_path #tags:tag1,tag2`
- Tags joined with commas, no tags suffix if no tags present
- Outputs count: "Rebuilt index.md with N entries"

#### --validate
- Parses existing index.md for paths (splits on ` -> `, strips `#tags:` suffix)
- Scans actual active files
- Reports:
  - Files NOT in index.md (missing_from_index)
  - Index entries with NO matching file (stale_in_index)
  - "Index is valid" if no mismatches
- Exit code: 0 if valid, 1 if mismatches

#### --query <keyword>
- Case-insensitive substring search across full index lines
- Reports match count and matching lines
- No scoring, purely substring

#### --health
- Sections: Entries by Category, Heavily Updated (times_updated > 5), Recent Retirements (last 7 days), Index Sync Status, Summary
- Reports active/retired/archived counts
- Detects index desync (missing from index + stale entries)
- Overall health: "GOOD" or "NEEDS ATTENTION" with issues list

#### --gc (Garbage Collect)
- Reads `delete.grace_period_days` from config (default: 30)
- Scans all memories including inactive
- For retired entries: checks `retired_at` timestamp
- Deletes files where age >= grace_period_days
- Reports: deleted files, warnings/errors, suggests --rebuild if files deleted
- Handles missing/invalid `retired_at` gracefully (SKIP with warning)

### Config Keys Read
- `delete.grace_period_days` (int, default: 30) -- for --gc only

### Error Paths
- Root not a directory -> stderr error, exit 1
- index.md missing (--validate) -> error message, return False
- JSON parse errors in scan -> WARNING to stderr, skip file
- File delete failures (--gc) -> ERROR in report
- Invalid retired_at timestamps -> SKIP in report

### Dependencies
- stdlib only

---

## 4. memory_candidate.py (ACE Candidate Selection)

### Purpose
Finds the best existing memory entry to update/delete for new information, or determines CREATE/NOOP. Called by subagents once per save operation.

### CLI Arguments
- `--category <cat>` (required, choices: session_summary, decision, runbook, constraint, tech_debt, preference)
- `--new-info <text>` (required) -- new information to match against existing entries
- `--lifecycle-event <event>` (optional, choices: resolved, removed, reversed, superseded, deprecated)
- `--root <path>` (default: `.claude/memory`)

### Constants
- `DELETE_DISALLOWED = frozenset({"decision", "preference", "session_summary"})` -- categories where triage-initiated delete is blocked
- `CATEGORY_KEY_FIELDS`: per-category content fields for excerpt (e.g., decision -> context, decision, rationale)
- `VALID_LIFECYCLE_EVENTS = {"resolved", "removed", "reversed", "superseded", "deprecated"}`
- Score threshold for candidate: >= 3

### Behaviors

#### Index Auto-Rebuild
- Same pattern as memory_retrieve.py: if index.md missing, runs memory_index.py --rebuild

#### Scoring
- Same algorithm as memory_retrieve.py (exact title=2, tag=3, prefix=1)
- Only scores entries matching the target category
- Sort: highest score first, tie-break by path (deterministic)
- Top-1 candidate selected if score >= 3

#### Pre-classification Logic
| candidate | lifecycle_event | pre_action |
|-----------|----------------|------------|
| None | None | CREATE |
| None | present | NOOP |
| exists | * | None (deferred to structural CUD) |

#### Structural CUD Determination
| Condition | structural_cud |
|-----------|---------------|
| pre_action=CREATE | CREATE |
| pre_action=NOOP | NOOP |
| candidate exists + delete_allowed | UPDATE_OR_DELETE |
| candidate exists + delete not allowed | UPDATE |
| else | CREATE |

#### Structural Vetoes
- If candidate is None and pre_action is None: "Cannot UPDATE with 0 candidates" + "Cannot DELETE with 0 candidates"
- If delete not allowed and candidate exists: "Cannot DELETE {category} (triage-initiated)"

#### Hints
- Candidate found: "1 candidate found (score=N)"
- lifecycle_event + delete allowed: "suggests DELETE if eligible"
- lifecycle_event + delete not allowed: "present but DELETE disallowed; consider UPDATE"
- NOOP: "lifecycle_event=X with no matching candidate; NOOP"

#### Candidate Excerpt Building
- Reads the JSON file
- Extracts category-specific key_fields (truncated to 200 chars each, lists joined with "; ")
- Derives `last_change_summary` from last entry in `changes[]` or "Initial creation"
- Returns: title, record_status, tags, last_change_summary, key_fields

#### Path Safety
- Validates candidate path ends in `.json`
- Resolves path and ensures it's under memory root via `relative_to()`
- If invalid: logs WARNING, falls back to CREATE or NOOP

### Output Format (stdout JSON)
```json
{
  "candidate": { "path", "title", "tags", "excerpt" } | null,
  "lifecycle_event": string | null,
  "delete_allowed": bool,
  "pre_action": "CREATE" | "NOOP" | null,
  "structural_cud": "CREATE" | "NOOP" | "UPDATE" | "UPDATE_OR_DELETE",
  "vetoes": [string],
  "hints": [string]
}
```

### Error Paths
- index.md not found after rebuild attempt -> stderr error, exit 1
- index.md read error -> stderr error, exit 1
- Candidate file read error -> WARNING to stderr, returns None excerpt
- Path not .json -> WARNING, falls back to CREATE/NOOP
- Path resolves outside memory root -> WARNING, falls back

### Dependencies
- stdlib only
- Optionally imports subprocess for auto-rebuild

---

## 5. memory_write.py (Schema-Enforced CRUD)

### Purpose
Handles CREATE, UPDATE, DELETE, ARCHIVE, and UNARCHIVE operations with Pydantic v2 validation, merge protections, OCC (Optimistic Concurrency Control), atomic writes, and index management.

### CLI Arguments
- `--action <action>` (required, choices: create, update, delete, archive, unarchive)
- `--category <cat>` (optional, choices: 6 categories; required for create)
- `--target <path>` (required) -- relative path to memory file
- `--input <path>` (optional) -- path to temp JSON input file (required for create, update)
- `--hash <md5>` (optional) -- MD5 hash for OCC (update only; warning if missing)
- `--reason <text>` (optional) -- reason for delete/archive

### Constants
- `TAG_CAP = 12` -- maximum tags per memory
- `CHANGES_CAP = 50` -- maximum change entries (FIFO overflow)
- `ID_PATTERN = ^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$` -- 1-80 char kebab-case
- Category folders/display: same as other scripts
- Lock timeout: 5.0s, stale age: 60.0s, poll interval: 0.05s

### Pydantic Models (6 categories)

**DecisionContent**: status (proposed|accepted|deprecated|superseded), context, decision, alternatives (optional list of {option, rejected_reason}), rationale (list, min 1), consequences (optional list)

**SessionSummaryContent**: goal, outcome (success|partial|blocked|abandoned), completed (list), in_progress (optional list), blockers (optional list), next_actions (list), key_changes (optional list)

**RunbookContent**: trigger, symptoms (optional list), steps (list, min 1), verification, root_cause (optional), environment (optional)

**ConstraintContent**: kind (limitation|gap|policy|technical), rule, impact (list, min 1), workarounds (optional list), severity (high|medium|low), active (bool), expires (optional)

**TechDebtContent**: status (open|in_progress|resolved|wont_fix), priority (critical|high|medium|low), description, reason_deferred, impact (optional list), suggested_fix (optional list), acceptance_criteria (optional list)

**PreferenceContent**: topic, value, reason, strength (strong|default|soft), examples (optional: {prefer[], avoid[]})

**ChangeEntry**: date, summary (max 300), field (optional), old_value (optional), new_value (optional)

All content models use `extra="forbid"` (no unknown fields allowed).

**Base Memory Model** (built dynamically per category via `create_model()`):
- schema_version: Literal["1.0"]
- category: Literal[<category>]
- id: pattern-validated string
- title: max_length=120
- record_status: Literal["active", "retired", "archived"], default="active"
- created_at, updated_at: string
- tags: list[str], min_length=1
- related_files: optional list[str]
- confidence: optional float, 0.0-1.0
- content: category-specific model
- changes: optional list[ChangeEntry]
- times_updated: int, default=0
- retired_at, retired_reason, archived_at, archived_reason: optional strings

### Behaviors

#### Venv Bootstrap
- If pydantic not importable, re-execs under `.venv/bin/python3` via `os.execv()`
- Checks `os.path.realpath()` to avoid infinite re-exec loop

#### Auto-Fix (applied to all CREATE and UPDATE operations)
1. `schema_version`: set to "1.0" if missing/empty
2. `updated_at`: set to current UTC if missing/empty
3. `created_at`: set to current UTC on CREATE if missing/empty
4. `tags` string -> wrapped in array
5. `id`: slugified (NFKD normalize, ASCII-only, kebab-case, max 80 chars)
6. `confidence`: clamped to [0.0, 1.0]
7. `title`, `id`: stripped of whitespace
8. `title`: stripped of control characters, ` -> ` replaced with ` - `, `#tags:` removed
9. `tags`: lowercased, stripped, control chars removed, commas/arrows/tags-prefix removed, deduplicated, sorted; empty tags set to ["untagged"]; truncated to TAG_CAP(12)

#### CREATE Operation
1. Read input from temp file
2. Auto-fix
3. Force `record_status = "active"`, remove retired/archived fields (injection prevention)
4. Force category to match `--category` arg
5. Validate via Pydantic
6. Path traversal check (target must be under memory_root)
7. Force `id` to match filename stem
8. Re-validate after fixes
9. Create parent directories
10. **flock index** for atomicity:
    - Anti-resurrection check: if target exists with `record_status == "retired"` and `retired_at < 24 hours ago`, block with `ANTI_RESURRECTION_ERROR`
    - Atomic write JSON
    - Add to index (sorted insertion)
11. Cleanup temp file
12. Output: `{"status": "created", "target", "id", "title"}`

#### UPDATE Operation
1. Path traversal check
2. File must exist (else error: "Use --action create instead")
3. Read existing file
4. Read new input, auto-fix
5. Preserve immutable fields from old: created_at, schema_version, category, id
6. Preserve record_status from old
7. Validate
8. Check merge protections:
   - **Immutable fields**: created_at, schema_version, category (block if changed)
   - **record_status**: immutable via UPDATE (must use delete/archive actions)
   - **Tags**: grow-only below TAG_CAP; at cap, eviction allowed only if adding new tags; no net shrink without addition; cap enforcement
   - **related_files**: grow-only, except non-existent (dangling) paths can be removed
   - **changes[]**: append-only (new count >= old count)
   - Auto-generates change entries for scalar content field changes
   - Warns (but allows) content list fields that shrink
9. Strict check: total changes must exceed old count (at least 1 new change required)
10. FIFO overflow at 50 changes
11. Increment times_updated
12. Update timestamp
13. **Slug rename**: If title changed >50% (word_difference_ratio), computes new slug. If no collision, renames file + updates index. Collision -> keeps old slug with warning.
14. Re-validate after all changes
15. **flock index**:
    - OCC hash check (if --hash provided): compares current MD5 vs expected
    - Rename flow or in-place update
16. Cleanup temp file
17. Output: `{"status": "updated", "target", "id", "title", "times_updated", "renamed_from"?}`

#### DELETE Operation (Soft Retire)
1. Path traversal check
2. File must exist
3. Read existing
4. If already retired -> idempotent success: `{"status": "already_retired"}`
5. If archived -> error: "must unarchive before retiring"
6. Set: record_status="retired", retired_at=now, retired_reason (from --reason or "No reason provided"), updated_at=now
7. Clear archived fields
8. Append change entry, FIFO overflow at 50
9. **flock index**: atomic write + remove from index
10. Output: `{"status": "retired", "target", "reason"}`

#### ARCHIVE Operation
1. Path traversal check
2. File must exist
3. If already archived -> idempotent: `{"status": "already_archived"}`
4. Only active memories can be archived (error otherwise)
5. Set: record_status="archived", archived_at=now, archived_reason, updated_at=now
6. Clear retired fields
7. Append change entry, FIFO overflow at 50
8. **flock index**: atomic write + remove from index
9. Output: `{"status": "archived", "target", "reason"}`

#### UNARCHIVE Operation
1. Path traversal check
2. File must exist
3. Only archived memories can be unarchived (error otherwise)
4. Set: record_status="active", updated_at=now
5. Clear archived fields
6. Append change entry, FIFO overflow at 50
7. **flock index**: atomic write + add to index
8. Output: `{"status": "unarchived", "target"}`

#### Atomic Writes
- Uses `tempfile.mkstemp()` in target directory
- Write to temp file, then `os.rename()` (atomic on POSIX)
- Cleanup temp file on failure

#### Locking (_flock_index)
- Uses `os.mkdir()` as atomic lock (works on all FS including NFS)
- Lock directory: `<memory_root>/.index.lockdir`
- Timeout: 5s with 0.05s poll interval
- Stale lock detection: >60s age -> break with warning
- Falls back to proceeding without lock on timeout or mkdir failure
- Lock released via `os.rmdir()` in __exit__

#### Input File Validation
- Must resolve to `/tmp/` path
- Must not contain `..` path components
- Defense-in-depth against subagent manipulation

#### Memory Root Resolution
- Scans target path for `.claude/memory` components
- Obfuscated string construction (`.clau` + `de`) to avoid guardian pattern matching
- Fails closed if marker not found in path

### Error Output Formats
- `VALIDATION_ERROR`: field, expected, got, fix
- `MERGE_ERROR`: field, rule, old/new/removed values, fix
- `OCC_CONFLICT`: target, expected_hash, current_hash, fix
- `PATH_ERROR`: target, fix
- `ANTI_RESURRECTION_ERROR`: target, retired_at, fix
- `UPDATE_ERROR`, `DELETE_ERROR`, `ARCHIVE_ERROR`, `UNARCHIVE_ERROR`, `READ_ERROR`, `INPUT_ERROR`, `SECURITY_ERROR`

### Dependencies
- pydantic >= 2.0, < 3.0 (required)
- stdlib: argparse, hashlib, json, os, re, sys, tempfile, time, unicodedata, datetime, pathlib

---

## 6. memory_write_guard.py (PreToolUse Guard)

### Purpose
Intercepts Write tool calls and denies any that target the memory storage directory. Forces all writes through memory_write.py.

### CLI / Invocation
- No CLI arguments. Invoked as command hook via stdin JSON.
- Always exits 0.
- Outputs JSON to stdout with `permissionDecision: "deny"` when blocking.

### stdin Input Format
JSON object with:
- `tool_input.file_path` (string): The file path being written to

### Behaviors

#### Path Detection
- Resolves path via `os.path.realpath(os.path.expanduser())`
- Falls back to `os.path.normpath(os.path.abspath())` on error
- Normalizes to forward slashes
- Checks for `/.claude/memory/` segment or path ending in `/.claude/memory`

#### Allowed Exceptions (bypass guard)
All must be in `/tmp/`:
- `.memory-write-pending*.json` -- temp staging files
- `.memory-draft-*.json` -- parallel triage draft files
- `.memory-triage-context-*.txt` -- triage context files

#### Path Marker Obfuscation
- Constructs `.claude` and `memory` strings at runtime to avoid self-detection
- `_DOT_CLAUDE = ".clau" + "de"`, `_MEMORY = "mem" + "ory"`

#### Deny Output Format
```json
{
  "hookSpecificOutput": {
    "permissionDecision": "deny",
    "permissionDecisionReason": "Direct writes to the memory directory are blocked..."
  }
}
```

### Error Paths
- Invalid JSON stdin -> exit 0 (allow)
- Empty file_path -> exit 0 (allow)
- Path resolution errors -> fallback normalization

### Dependencies
- stdlib only

---

## 7. memory_validate_hook.py (PostToolUse Validation)

### Purpose
Detection-only fallback that catches writes bypassing the PreToolUse guard. Validates memory JSON files via Pydantic schema, quarantines invalid files.

### CLI / Invocation
- No CLI arguments. Invoked as command hook via stdin JSON.
- Always exits 0.
- May output deny JSON to stdout for non-JSON memory files or invalid files.

### stdin Input Format
Same as write guard: `tool_input.file_path`

### Behaviors

#### Pydantic Bootstrap
- Tries to add plugin `.venv/lib/*/site-packages` to sys.path
- Sets `_HAS_PYDANTIC` flag (True/False)
- Avoids importing memory_write.py if pydantic is missing (would trigger os.execv)

#### Path Detection
- Same obfuscated marker as write guard
- `MEMORY_DIR_SEGMENT = "/.claude/memory/"`

#### Category Detection from Path
- `FOLDER_TO_CATEGORY`: sessions->session_summary, decisions->decision, etc.
- Falls back to `data.get("category")` if folder not recognized

#### Validation
- If pydantic available: imports `validate_memory` from memory_write.py
- If not: falls back to `_basic_validation()`:
  - Required fields: schema_version, category, id, title, created_at, updated_at, tags, content
  - Category must match folder
  - Tags must be non-empty array
  - Content must be object

#### Non-JSON files
- Any non-.json file in memory directory -> deny with error message

#### Quarantine
- Invalid files renamed to `<path>.invalid.<unix_timestamp>`
- Preserves original file as evidence
- WARNING to stderr if rename fails

#### Flow
1. If file not in memory dir -> exit 0
2. WARNING to stderr: write bypassed guard
3. If not .json -> deny
4. Validate file -> if valid, WARNING only; if invalid, quarantine + deny

### Error Paths
- Invalid JSON stdin -> exit 0
- Empty file_path -> exit 0
- File read errors during validation -> invalid
- JSON parse errors -> invalid
- Cannot determine category -> invalid
- Quarantine rename failure -> WARNING, uses original path

### Dependencies
- pydantic v2 (optional, graceful degradation)
- Imports from memory_write.py (conditionally)

---

## 8. hooks.json (Hook Configuration)

### Structure
- `description`: "v5.0.0: 1 deterministic command-type Stop hook..."
- 4 hook types configured:

| Hook Type | Matcher | Script | Timeout | Status Message |
|-----------|---------|--------|---------|---------------|
| Stop | * | memory_triage.py | 30s | "Evaluating session for memories..." |
| PreToolUse | Write | memory_write_guard.py | 5s | "Checking memory write path..." |
| PostToolUse | Write | memory_validate_hook.py | 10s | "Validating memory file..." |
| UserPromptSubmit | * | memory_retrieve.py | 10s | "Retrieving relevant memories..." |

- All hooks use `type: "command"` (not "prompt")
- Commands use `$CLAUDE_PLUGIN_ROOT` variable for portability

---

## 9. plugin.json (Plugin Manifest)

### Fields
- `name`: "claude-memory"
- `version`: "5.0.0"
- `description`: Full description string
- `author`: name="idnotbe", url="https://github.com/idnotbe"
- `commands`: 4 command files (memory, memory-config, memory-search, memory-save)
- `skills`: 1 skill directory (memory-management)
- `homepage`: github URL
- `repository`: github URL
- `license`: "MIT"
- `keywords`: memory, context, knowledge-management, session-state, decisions, runbooks

---

## 10. memory-config.default.json (Default Configuration)

### Full Structure
```json
{
  "memory_root": ".claude/memory",
  "categories": {
    "session_summary": { "enabled": true, "folder": "sessions", "auto_capture": true, "retention_days": 90, "max_retained": 5 },
    "decision":        { "enabled": true, "folder": "decisions", "auto_capture": true, "retention_days": 0 },
    "runbook":         { "enabled": true, "folder": "runbooks", "auto_capture": true, "retention_days": 0 },
    "constraint":      { "enabled": true, "folder": "constraints", "auto_capture": true, "retention_days": 0 },
    "tech_debt":       { "enabled": true, "folder": "tech-debt", "auto_capture": true, "retention_days": 0 },
    "preference":      { "enabled": true, "folder": "preferences", "auto_capture": true, "retention_days": 0 }
  },
  "auto_commit": false,
  "max_memories_per_category": 100,
  "retrieval": { "max_inject": 5, "match_strategy": "title_tags" },
  "triage": {
    "enabled": true,
    "max_messages": 50,
    "thresholds": { "decision": 0.4, "runbook": 0.4, "constraint": 0.5, "tech_debt": 0.4, "preference": 0.4, "session_summary": 0.6 },
    "parallel": {
      "enabled": true,
      "category_models": { "session_summary": "haiku", "decision": "sonnet", "runbook": "haiku", "constraint": "sonnet", "tech_debt": "haiku", "preference": "haiku" },
      "verification_model": "sonnet",
      "default_model": "haiku"
    }
  },
  "delete": { "grace_period_days": 30, "archive_retired": true }
}
```

### Config Keys NOT Read by Any Script (documentation-only or future)
- `memory_root` -- not read by scripts (they use `--root` arg or `cwd`)
- `categories.<cat>.enabled` -- not read by triage.py or retrieve.py (only in commands/SKILL.md)
- `categories.<cat>.auto_capture` -- not read by any script
- `categories.<cat>.retention_days` -- not read by any script (GC uses `delete.grace_period_days`)
- `auto_commit` -- not read by any script
- `max_memories_per_category` -- not read by any script
- `retrieval.match_strategy` -- not read by memory_retrieve.py
- `delete.archive_retired` -- not read by any script

---

## 11. JSON Schemas (assets/schemas/)

### base.schema.json
- Defines common fields: schema_version("1.0"), category (enum), id (pattern), title (maxLength:120), created_at, updated_at, tags (array, minItems:1), related_files, confidence (0.0-1.0), record_status (enum: active/retired/archived), changes (array, maxItems:50), times_updated (integer), retired_at, retired_reason (maxLength:300), archived_at, archived_reason (maxLength:300), content (object)
- `additionalProperties: false`

### Category-Specific Schemas (6 files)
Each extends base with category-specific content:

**decision.schema.json**: content.status (proposed|accepted|deprecated|superseded), context, decision, alternatives [{option, rejected_reason}], rationale (array, minItems:1), consequences

**session-summary.schema.json**: content.goal, outcome (success|partial|blocked|abandoned), completed, in_progress, blockers, next_actions, key_changes

**runbook.schema.json**: content.trigger, symptoms, steps (minItems:1), verification, root_cause, environment

**constraint.schema.json**: content.kind (limitation|gap|policy|technical), rule, impact (minItems:1), workarounds, severity (high|medium|low), active (boolean), expires

**tech-debt.schema.json**: content.status (open|in_progress|resolved|wont_fix), priority (critical|high|medium|low), description, reason_deferred, impact, suggested_fix, acceptance_criteria

**preference.schema.json**: content.topic, value, reason, strength (strong|default|soft), examples {prefer[], avoid[]}

All category schemas duplicate base fields (not using $ref), all have `additionalProperties: false` on both root and content.

---

## 12. Commands (commands/*.md)

### /memory (memory.md)
- **Frontmatter**: name=memory, description="Show memory status, manage lifecycle (retire, archive, restore, GC)", arguments: action (optional)
- **Subcommands**:
  - (no args): Status display -- config, categories with active/retired/archived counts, index sync, storage total, health indicators
  - `--retire <slug>`: Soft delete. Find file by slug across all folders, confirm, call memory_write.py --action delete
  - `--archive <slug>`: Shelve permanently. Only active->archived. Call memory_write.py --action archive
  - `--unarchive <slug>`: Restore archived->active. Call memory_write.py --action unarchive
  - `--restore <slug>`: Restore retired->active within 30-day grace. Checks staleness (>7 days warning). Manually modifies JSON, calls memory_write.py --action update, rebuilds index
  - `--gc`: Garbage collect. Calls memory_index.py --gc or manual fallback
  - `--list-archived`: Lists all archived memories as table

### /memory:config (memory-config.md)
- **Frontmatter**: name=memory:config, description="Configure memory categories and settings using natural language", arguments: instruction (required)
- **Operations**: Enable/disable category, add custom category, remove (disable) category, change retrieval settings (max_inject, match_strategy), change storage root

### /memory:search (memory-search.md)
- **Frontmatter**: name=memory:search, description="Search memories by keyword across all categories", arguments: query (required), options (optional)
- **Features**: Index-based title/tag matching, fallback to Glob+Grep search, results grouped by category (max 10), scoring: tag=3, title=2, content=1 + recency bonus
- **Flag**: `--include-retired` -- also scans JSON files directly for retired/archived memories

### /memory:save (memory-save.md)
- **Frontmatter**: name=memory:save, description="Manually save a memory to a specific category", arguments: category (required), content (required)
- **Flow**: Validate category, generate slug, create JSON with all schema fields, write to /tmp/.memory-write-pending.json, call memory_write.py --action create
- **Category folder mapping**: documented as table

---

## 13. SKILL.md (Memory Management Skill)

### Frontmatter
- name: memory-management
- globs: `.claude/memory/**`, `.claude/memory/memory-config.json`
- triggers: remember, forget, memory, memories, previous session

### 4-Phase Consolidation Flow
1. **Phase 0**: Parse `<triage_data>` JSON from stop hook. Check `triage.parallel.enabled`.
2. **Phase 1**: Parallel Drafting -- spawn Task subagents per category using configured models. Instructions: read context file, run memory_candidate.py, apply CUD resolution, write draft JSON to `/tmp/.memory-draft-<category>-<pid>.json`
3. **Phase 2**: Content Verification -- spawn verification subagents (verification_model). Check accuracy, hallucination, completeness. PASS/FAIL.
4. **Phase 3**: Save -- main agent collects results, validates draft paths, calls memory_write.py per action. Enforces session rolling window.

### CUD Verification Rules (2-layer table)
- L1 (Python structural) vs L2 (Subagent decision)
- Key principles: mechanical trumps LLM, safety defaults (UPDATE over DELETE, NOOP for contradictions)

### Session Rolling Window
- Keep last N active sessions (default 5, config: `categories.session_summary.max_retained`)
- After creating new session: count active, retire oldest if over limit
- Deletion guard: warns if oldest session has unique content not in other categories
- Warning is informational only, retirement proceeds

### Natural Language Handlers
- "What do you remember?" -> Read index.md
- "Remember that..." -> Create memory
- "Forget..." -> Confirm, retire
- "What did we decide about X?" -> Search decisions/

### Rules
1. CRUD lifecycle through 4-phase flow
2. Silent operation during auto-capture
3. Always run memory_candidate.py first (avoid duplicates)
4. 2-layer CUD verification
5. Confidence: 0.7-0.9 normally, 0.9+ for confirmed facts
6. All writes via memory_write.py

### Config Keys Referenced
- `categories.<name>.enabled`
- `categories.<name>.auto_capture`
- `categories.<name>.retention_days`
- `categories.session_summary.max_retained`
- `retrieval.max_inject`
- `max_memories_per_category`
- `triage.parallel.enabled`
- `triage.parallel.category_models`
- `triage.parallel.verification_model`
- `triage.parallel.default_model`
- `delete.grace_period_days`
- `delete.archive_retired`

---

## Cross-Cutting Concerns

### Inter-file Dependencies

| Caller | Callee | How |
|--------|--------|-----|
| memory_retrieve.py | memory_index.py | subprocess --rebuild on missing index |
| memory_candidate.py | memory_index.py | subprocess --rebuild on missing index |
| memory_validate_hook.py | memory_write.py | imports `validate_memory` function |
| memory_write.py | memory_index.py (implicit) | manages index.md directly (add/remove/update) |
| SKILL.md | memory_candidate.py | subagents call via CLI |
| SKILL.md | memory_write.py | main agent calls via CLI |
| commands/memory.md | memory_write.py | calls via CLI |
| commands/memory.md | memory_index.py | calls --validate, --gc |
| commands/memory-save.md | memory_write.py | calls via CLI |

### Shared Constants Across Files

| Constant | Files |
|----------|-------|
| CATEGORY_FOLDERS mapping | memory_index.py, memory_candidate.py, memory_write.py |
| CATEGORY_DISPLAY mapping | memory_index.py, memory_candidate.py, memory_write.py |
| STOP_WORDS | memory_retrieve.py, memory_candidate.py |
| Index line regex | memory_retrieve.py, memory_candidate.py |
| MEMORY_DIR_SEGMENT path marker | memory_write_guard.py, memory_validate_hook.py |
| Score algorithm (exact=2, tag=3, prefix=1) | memory_retrieve.py, memory_candidate.py |

### Config Keys -- Actual Implementation vs Default Config

| Config Key | Read By | Default |
|------------|---------|---------|
| triage.enabled | memory_triage.py | true |
| triage.max_messages | memory_triage.py | 50 |
| triage.thresholds.* | memory_triage.py | varies (0.4-0.6) |
| triage.parallel.* | memory_triage.py | enabled=true, models=haiku/sonnet |
| retrieval.enabled | memory_retrieve.py | true |
| retrieval.max_inject | memory_retrieve.py | 5 |
| delete.grace_period_days | memory_index.py (--gc) | 30 |

**Config keys in default config but NOT read by any script:**
- memory_root
- categories.*.enabled, auto_capture, retention_days
- auto_commit
- max_memories_per_category
- retrieval.match_strategy
- delete.archive_retired

These are referenced only in documentation (SKILL.md, commands) as instructions for the agent/LLM, not by Python scripts.

### Common Patterns

1. **Fail-open**: All hooks exit 0 on errors to avoid trapping the user
2. **Path obfuscation**: `.claude` and `memory` strings constructed at runtime to avoid self-matching by guards
3. **Index as derived artifact**: Auto-rebuilt from authoritative JSON files when missing
4. **Sanitization defense-in-depth**: Title sanitization on both write side (memory_write.py auto_fix) and read side (memory_retrieve.py, memory_triage.py)
5. **Atomic operations**: temp file + rename pattern for all writes
6. **Idempotent operations**: delete of already-retired = success, archive of already-archived = success
7. **Graceful degradation**: validate hook works without pydantic (basic validation fallback)

### Security Features Implemented
1. Path traversal checks in memory_write.py (target must be under memory_root)
2. Input file restricted to /tmp/ with no .. components
3. Transcript path restricted to /tmp/ or $HOME/
4. Anti-resurrection check (24h cooldown after retirement)
5. Context file creation with O_NOFOLLOW (prevents symlink attacks)
6. Title sanitization: control chars, zero-width Unicode, XML escaping, index-injection markers
7. Tag sanitization: control chars, commas, arrows, tags-prefix removal
8. Snippet sanitization in triage output
9. write_guard blocks direct writes to memory directory
10. validate_hook quarantines invalid files that bypass the guard
