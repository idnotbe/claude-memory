# User Scenarios for claude-memory Plugin

Comprehensive user scenarios covering the full developer lifecycle with the claude-memory plugin. Organized by developer motivation (what problem are they solving?) rather than by feature (what command do they run?).

---

## Persona Definitions

### Pat (New User)
- Just discovered claude-memory from a GitHub search or colleague recommendation
- Has Claude Code installed and uses it daily for coding
- Has never used a Claude Code plugin before
- Comfortable with CLI tools but not familiar with plugin internals
- Wants things to "just work" without deep configuration

### Alex (Experienced User)
- Has been using claude-memory for 2-4 weeks
- Understands the 6 memory categories and basic commands
- Uses /memory and /memory:search regularly
- Has ~30-50 memories across multiple categories
- Wants to optimize retrieval and keep the memory store clean

### Sam (Power User)
- Has been using claude-memory for 2+ months across multiple projects
- Understands the architecture (hooks, triage, candidate matching, CUD resolution)
- Has 100+ memories in at least one project
- Customizes config extensively
- Cares about token costs, performance, and team workflows

---

## Category 1: Discovery and Installation

### Scenario 1: First-Time Installation
- **Persona**: Pat (new user)
- **Motivation**: "I keep losing context between Claude Code sessions. Every time I start a new chat, I have to re-explain my project decisions."
- **Pre-conditions**: Has Claude Code installed and working. Has git installed. Has Python 3 available.
- **Steps**:
  1. Finds claude-memory on GitHub (via search, recommendation, or plugin directory)
  2. Reads the README to understand what it does
  3. Clones into `~/.claude/plugins/` directory
  4. Restarts Claude Code
  5. Starts a normal coding session to see if the plugin loads
- **Expected Outcome**: Plugin is detected via `.claude-plugin/plugin.json`. No visible change yet -- the plugin works silently until a session ends.
- **Potential Friction Points**:
  - Does `~/.claude/plugins/` exist? User may need to create it.
  - Does the user know to restart Claude Code?
  - No immediate feedback that the plugin is working (nothing happens until session end).
  - pydantic v2 is required but not mentioned in installation steps.
- **Documentation Needed**: Clear installation steps with prerequisites (Python 3, pydantic v2), directory creation, verification steps, "what to expect after installation" section.

### Scenario 2: Verifying Installation Works
- **Persona**: Pat (new user)
- **Motivation**: "I installed the plugin but nothing seems different. Did it work?"
- **Pre-conditions**: Plugin cloned and Claude Code restarted.
- **Steps**:
  1. Types `/memory` to check status
  2. Sees "no memories have been captured yet"
  3. Has a short coding session (making a decision or encountering an error)
  4. Ends the session (presses stop)
  5. Sees the triage hook fire: "Evaluating session for memories..."
  6. If categories triggered, sees memory being saved
  7. Starts a new session, types `/memory` to confirm memories exist
- **Expected Outcome**: At least one memory captured. `/memory` shows status with category counts.
- **Potential Friction Points**:
  - Session may be too short to trigger any category thresholds
  - User doesn't know what "Evaluating session for memories..." means
  - If no categories trigger, user thinks plugin is broken
- **Documentation Needed**: "First session" walkthrough explaining what triggers auto-capture, minimum session length/activity for triggers, how to manually save if auto-capture doesn't fire.

### Scenario 3: Understanding What Just Got Saved
- **Persona**: Pat (new user)
- **Motivation**: "The plugin saved something when I stopped. What did it save? Where? Can I see it?"
- **Pre-conditions**: First auto-capture has occurred.
- **Steps**:
  1. Sees stop hook message listing triggered categories
  2. Wants to inspect what was saved
  3. Types `/memory` to see overview
  4. Types `/memory:search` with a keyword from the session
  5. Browses `.claude/memory/` directory to see the JSON files
  6. Reads a JSON file to understand the structure
- **Expected Outcome**: User understands the storage structure, can find and read their memories.
- **Documentation Needed**: Explanation of storage structure, how to browse memories, what each field in the JSON means, link to schema documentation.

---

## Category 2: Daily Usage -- Automatic Behavior

### Scenario 4: Auto-Retrieval Surfaces Relevant Context
- **Persona**: Alex (experienced user)
- **Motivation**: "I'm working on the authentication module again. I made decisions about JWT vs sessions last week."
- **Pre-conditions**: Has memories saved from previous sessions, including a decision about JWT authentication.
- **Steps**:
  1. Starts a new session
  2. Types: "Let's continue working on the JWT authentication middleware"
  3. The UserPromptSubmit hook fires, matches "JWT" and "authentication" against index.md
  4. Relevant memories are injected as `<memory-context>` in Claude's context
  5. Claude responds with awareness of the previous JWT decision
- **Expected Outcome**: Claude references the stored decision without being asked. Alex doesn't need to re-explain the context.
- **Documentation Needed**: How auto-retrieval works (keywords, scoring, max_inject limit), what the `<memory-context>` injection looks like, how to tell when memories were retrieved.

### Scenario 5: Auto-Capture Saves a New Decision
- **Persona**: Alex (experienced user)
- **Motivation**: "We just decided to use Redis for caching instead of Memcached. I want this remembered."
- **Pre-conditions**: Active session with discussion about caching choices.
- **Steps**:
  1. During the session, discusses Redis vs Memcached with rationale
  2. Uses phrases like "decided to use Redis because..." or "chose Redis over Memcached"
  3. Ends the session
  4. Triage hook detects DECISION category keywords + rationale co-occurrence
  5. Score exceeds 0.4 threshold
  6. Parallel drafting creates a decision memory with context, alternatives, rationale
  7. Verification pass confirms quality
  8. Memory saved to `.claude/memory/decisions/use-redis-for-caching.json`
- **Expected Outcome**: Decision captured automatically with structured fields (context, decision, alternatives, rationale, consequences).
- **Documentation Needed**: What language triggers each category, how thresholds work, how to check what was auto-captured, the full list of triage signals per category.

### Scenario 6: Auto-Capture Updates an Existing Memory
- **Persona**: Alex (experienced user)
- **Motivation**: "We changed our mind about the caching approach -- adding an L1 in-process cache in front of Redis."
- **Pre-conditions**: Existing decision memory about Redis caching.
- **Steps**:
  1. During a new session, discusses adding L1 cache layer
  2. Ends the session
  3. Triage fires DECISION category
  4. memory_candidate.py finds the existing Redis caching decision (score >= 3)
  5. CUD resolution determines UPDATE (not CREATE)
  6. Memory updated with new rationale, changes[] appended
  7. times_updated incremented
- **Expected Outcome**: Existing memory updated rather than duplicate created. Change history preserved.
- **Documentation Needed**: How duplicate detection works, when UPDATE vs CREATE happens, how change history is tracked.

### Scenario 7: The "First Surprise" -- Discovering Injected Context
- **Persona**: Pat (new user)
- **Motivation**: "Wait, Claude just referenced something I said yesterday. How does it know that?"
- **Pre-conditions**: Has a few memories from previous sessions. Starts a new session.
- **Steps**:
  1. Asks Claude about a topic that matches a stored memory
  2. Claude's response includes details from the previous session
  3. Pat is surprised -- didn't explicitly ask Claude to remember
  4. Wants to understand what happened and what Claude "knows"
  5. Types `/memory:search` to see what memories exist
  6. Types `/memory` to see full status
- **Expected Outcome**: Pat understands that memories are automatically retrieved based on keyword matching.
- **Potential Friction Points**:
  - May feel invasive ("what else did it save about me?")
  - May not trust the accuracy of retrieved context
  - May want to control what gets injected
- **Documentation Needed**: Clear explanation of what auto-retrieval does and doesn't do, how to control it (max_inject, disable categories), how to review stored memories.

---

## Category 3: Intentional Memory Management

### Scenario 8: Manually Saving a Memory
- **Persona**: Pat (new user)
- **Motivation**: "I want to make sure Claude always remembers that we use Prettier with single quotes."
- **Pre-conditions**: Plugin installed and working.
- **Steps**:
  1. Types: `/memory:save preference "Always use Prettier with single quotes and 2-space indentation"`
  2. Plugin structures the natural language into preference schema (topic, value, reason, strength)
  3. Asks for any missing required fields if needed
  4. Writes to `/tmp/.memory-write-pending.json`
  5. Calls memory_write.py --action create
  6. Confirms: "Saved preference: always-use-prettier-single-quotes"
- **Expected Outcome**: Preference memory created with proper schema fields, appears in index.md.
- **Documentation Needed**: /memory:save syntax with examples for each category, what fields are auto-generated vs user-provided, how the content argument maps to schema fields.

### Scenario 9: Searching for a Specific Memory
- **Persona**: Alex (experienced user)
- **Motivation**: "What did we decide about the database migration strategy? I know we discussed it but can't remember the details."
- **Pre-conditions**: Has decision memories about database topics.
- **Steps**:
  1. Types: `/memory:search database migration`
  2. Plugin searches index.md for title/tag matches
  3. Results shown grouped by category with title, path, summary, date
  4. Finds the relevant decision memory
  5. Reads the full content including rationale and alternatives
- **Expected Outcome**: Finds the relevant memory with structured content.
- **Documentation Needed**: Search syntax, how scoring works (tag=3, title=2, prefix=1, recency bonus), result format, --include-retired flag, limit of 10 results.

### Scenario 10: Retiring an Outdated Decision
- **Persona**: Alex (experienced user)
- **Motivation**: "We switched from REST to GraphQL. The old REST API decision is no longer relevant and I don't want it influencing Claude."
- **Pre-conditions**: Has a decision memory about REST API.
- **Steps**:
  1. Types: `/memory --retire rest-api-design`
  2. Plugin finds `rest-api-design.json` in decisions/
  3. Shows title and asks for confirmation
  4. Calls memory_write.py --action delete
  5. Memory marked as retired (record_status="retired"), removed from index.md
  6. Memory file still exists (soft delete) with 30-day grace period
- **Expected Outcome**: Memory no longer appears in retrieval or search. Can be restored within 30 days.
- **Documentation Needed**: Difference between retire/archive/delete, what "soft delete" means, grace period, how to restore, that decisions/preferences cannot be hard-deleted by triage (only user-initiated).

### Scenario 11: Archiving a Memory for Posterity
- **Persona**: Alex (experienced user)
- **Motivation**: "This constraint about the old payment provider no longer applies since we switched providers, but I want to keep the record for historical reference."
- **Pre-conditions**: Has a constraint memory about old payment provider.
- **Steps**:
  1. Types: `/memory --archive old-payment-provider-api-limits`
  2. Plugin confirms the memory
  3. Sets record_status="archived", removes from index.md
  4. Memory preserved indefinitely (not subject to garbage collection)
- **Expected Outcome**: Memory preserved but no longer active in retrieval. Findable with `/memory:search --include-retired`.
- **Documentation Needed**: Archive vs retire differences, --list-archived command, how to unarchive.

### Scenario 12: Restoring a Retired Memory
- **Persona**: Alex (experienced user)
- **Motivation**: "I retired a runbook about the Docker build error last week, but the error just came back. I need that fix procedure again."
- **Pre-conditions**: Has a retired runbook memory within the 30-day grace period.
- **Steps**:
  1. Types: `/memory:search --include-retired docker build`
  2. Finds the retired runbook
  3. Types: `/memory --restore docker-build-fix`
  4. Plugin checks retired_at is within 30-day grace period
  5. Shows staleness warning if > 7 days old
  6. Restores to active, re-adds to index.md
- **Expected Outcome**: Memory restored to active status, appears in retrieval again.
- **Documentation Needed**: Restore command, grace period (30 days), staleness warning (7 days), what happens after grace period expires.

---

## Category 4: Configuration and Customization

### Scenario 13: Checking Current Configuration
- **Persona**: Alex (experienced user)
- **Motivation**: "I want to see what settings the plugin is using for my project."
- **Pre-conditions**: Plugin has been running with default config.
- **Steps**:
  1. Types `/memory` to see status including config overview
  2. Looks at `.claude/memory/memory-config.json` directly
  3. Compares with defaults
- **Expected Outcome**: Understands current configuration state.
- **Documentation Needed**: Where config lives, full list of all config options with defaults, which options are actually read by scripts vs documentation-only.

### Scenario 14: Reducing Context Injection Noise
- **Persona**: Alex (experienced user)
- **Motivation**: "Claude is getting too many memories injected and some aren't relevant. I want to reduce the number."
- **Pre-conditions**: max_inject is at default (5), retrieval is injecting irrelevant matches.
- **Steps**:
  1. Types: `/memory:config set max_inject to 3`
  2. Plugin reads current config, updates retrieval.max_inject to 3
  3. Writes updated config
  4. Confirms: "Updated max_inject from 5 to 3"
- **Expected Outcome**: Future prompts inject at most 3 memories.
- **Documentation Needed**: /memory:config syntax, max_inject range (clamped 0-20), what happens at 0 (retrieval disabled), how to re-enable.

### Scenario 15: Disabling Auto-Capture for a Category
- **Persona**: Alex (experienced user)
- **Motivation**: "Session summaries are generating too much noise. I don't need them."
- **Pre-conditions**: Session summaries being captured every session.
- **Steps**:
  1. Types: `/memory:config disable session_summary auto-capture`
  2. Plugin sets categories.session_summary.auto_capture to false
  3. Confirms change
- **Expected Outcome**: Session summaries no longer auto-captured but existing ones preserved.
- **Documentation Needed**: Difference between `enabled` and `auto_capture`, that disabling doesn't delete existing memories, how to re-enable.

### Scenario 16: Tuning Triage Thresholds
- **Persona**: Sam (power user)
- **Motivation**: "The plugin captures too many low-quality decisions. I want to raise the threshold so only strong signals trigger."
- **Pre-conditions**: Getting false-positive decision captures.
- **Steps**:
  1. Types: `/memory:config raise decision triage threshold to 0.7`
  2. Plugin updates triage.thresholds.decision from 0.4 to 0.7
  3. Confirms change
- **Expected Outcome**: Fewer but higher-quality decision captures.
- **Documentation Needed**: Full list of triage thresholds with defaults, what each threshold value means (0.0-1.0 scale), how scoring works for each category, how to tune per-category.

### Scenario 17: Changing Model Assignments for Cost Control
- **Persona**: Sam (power user)
- **Motivation**: "I want to save on token costs by using haiku for all categories, not just the simple ones."
- **Pre-conditions**: Default model assignments (some sonnet, some haiku).
- **Steps**:
  1. Types: `/memory:config set all category models to haiku`
  2. Plugin updates triage.parallel.category_models for all 6 categories
  3. Optionally also sets verification_model to haiku
  4. Confirms changes
- **Expected Outcome**: All drafting and verification uses haiku, reducing costs at the expense of quality.
- **Documentation Needed**: Model assignment options (haiku/sonnet/opus), per-category defaults, cost implications, quality trade-offs, verification_model and default_model options.

### Scenario 18: Adding a Custom Category
- **Persona**: Sam (power user)
- **Motivation**: "I want to track API endpoint documentation as a separate category."
- **Pre-conditions**: Using the 6 built-in categories.
- **Steps**:
  1. Types: `/memory:config add category api_docs with folder api-docs`
  2. Plugin adds to categories object in config
  3. Creates the folder in .claude/memory/
  4. User can now use `/memory:save api_docs "..."`
- **Expected Outcome**: New category available for manual saves.
- **Potential Friction Points**:
  - Custom categories have no Pydantic schema -- how is validation handled?
  - Auto-capture triage has no keyword patterns for custom categories
  - /memory:save says "or custom" but doesn't explain limitations
- **Documentation Needed**: Custom category capabilities and limitations, that auto-capture won't work for custom categories (no triage patterns), validation behavior for custom categories.

---

## Category 5: Trust and Verification

### Scenario 19: Verifying Memory Accuracy
- **Persona**: Pat (new user)
- **Motivation**: "Claude said we decided to use Postgres, but I'm not sure that's right. Did the auto-capture get it wrong?"
- **Pre-conditions**: Auto-captured decision may have inaccuracies.
- **Steps**:
  1. Types `/memory:search postgres` to find the memory
  2. Reads the full JSON to check accuracy
  3. Finds the rationale field has a minor inaccuracy
  4. Wants to correct it
- **Expected Outcome**: User can find, read, and understand the memory content.
- **Documentation Needed**: How to inspect memory content, confidence field meaning, that auto-captured memories are LLM-drafted (not verbatim quotes), how to request corrections.

### Scenario 20: Correcting an Inaccurate Memory
- **Persona**: Alex (experienced user)
- **Motivation**: "The runbook for fixing the Docker error has a wrong step. I need to update it."
- **Pre-conditions**: Existing runbook with incorrect step.
- **Steps**:
  1. Tells Claude: "The runbook for docker-build-fix has step 3 wrong. It should be `docker compose build --no-cache` not `docker build --no-cache`."
  2. Claude uses the memory-management skill to update the memory
  3. Calls memory_candidate.py to find the existing entry
  4. Drafts updated content
  5. Calls memory_write.py --action update
  6. Change recorded in changes[] array
- **Expected Outcome**: Memory updated with correct information, change history preserved.
- **Documentation Needed**: How to request memory corrections during a session, that changes are tracked in the changes[] array, what "natural language" interactions are supported ("remember that...", "forget...", "update the runbook...").

### Scenario 21: Understanding What Claude "Knows"
- **Persona**: Pat (new user)
- **Motivation**: "What does Claude remember about my project? I want to see everything."
- **Pre-conditions**: Has various memories across categories.
- **Steps**:
  1. Types: "What do you remember about this project?"
  2. Claude reads index.md and lists all active memories
  3. Pat browses the list, asks about specific entries
  4. Types `/memory` for structured status view
- **Expected Outcome**: Complete view of all stored memories.
- **Documentation Needed**: Natural language queries ("What do you remember?"), /memory status command, how to browse by category, difference between what's stored vs what's injected per prompt.

---

## Category 6: Troubleshooting

### Scenario 22: Memory Not Being Captured
- **Persona**: Pat (new user)
- **Motivation**: "I had a long session discussing architecture decisions but nothing was saved when I stopped."
- **Pre-conditions**: Session ended without triggering any categories.
- **Steps**:
  1. Ends session, sees "Evaluating session for memories..." but no categories trigger
  2. Wonders why nothing was saved
  3. Checks `/memory` status -- everything looks normal
  4. Possible causes:
     a. Session transcript was too short
     b. Discussion didn't use trigger keywords (e.g., said "we'll go with X" instead of "decided to use X")
     c. Thresholds too high
     d. Category disabled in config
     e. triage.enabled set to false
- **Expected Outcome**: User understands why capture didn't trigger and how to either adjust language, lower thresholds, or use /memory:save manually.
- **Documentation Needed**: Troubleshooting guide for "nothing captured", list of trigger keywords per category, minimum session activity for session_summary, how to check triage.enabled, how to manually save as fallback.

### Scenario 23: Memory Not Being Retrieved
- **Persona**: Alex (experienced user)
- **Motivation**: "I know I have a memory about the API rate limit but Claude isn't mentioning it in this session."
- **Pre-conditions**: Has a constraint memory about API rate limits. Prompt doesn't match well.
- **Steps**:
  1. Asks about "API throttling" but memory is titled "API rate limit"
  2. No memory retrieved because "throttling" doesn't match "rate limit" in title/tags
  3. Tries `/memory:search rate limit` and finds it
  4. Realizes the keyword matching is exact, not semantic
- **Expected Outcome**: User understands retrieval is keyword-based (not semantic), learns to use /memory:search directly.
- **Documentation Needed**: How keyword matching works (exact word match, not semantic), that retrieval uses index title/tags only, how to improve match quality (better tags), that prompts < 10 chars are skipped, that stop-words are filtered.

### Scenario 24: Index Out of Sync
- **Persona**: Alex (experienced user)
- **Motivation**: "I can see memory files in the directory but /memory:search doesn't find them."
- **Pre-conditions**: Index.md is out of sync with actual files (e.g., after a git merge or manual file manipulation).
- **Steps**:
  1. Files exist in .claude/memory/ but not in index.md
  2. `/memory:search` returns nothing
  3. Types `/memory` and sees index sync warning
  4. Runs index rebuild: `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory`
  5. Or asks Claude to rebuild the index
- **Expected Outcome**: Index rebuilt, search works again.
- **Documentation Needed**: How to detect index desync, rebuild command, --validate command, when auto-rebuild happens (on missing index), when it doesn't (on stale index).

### Scenario 25: Pydantic Not Installed
- **Persona**: Pat (new user)
- **Motivation**: "I get an error when the plugin tries to save a memory."
- **Pre-conditions**: Plugin cloned but pydantic v2 not installed.
- **Steps**:
  1. Auto-capture triggers at session end
  2. memory_write.py tries to import pydantic
  3. Attempts to re-exec under .venv/bin/python3
  4. If no venv: import fails, write operation fails
  5. Error message appears
- **Expected Outcome**: User understands they need to install pydantic v2.
- **Documentation Needed**: Prerequisites section listing pydantic v2, installation command (`pip install pydantic>=2.0`), that only memory_write.py and memory_validate_hook.py require pydantic, that triage and retrieval work without it.

### Scenario 26: Quarantined Files
- **Persona**: Alex (experienced user)
- **Motivation**: "I see `.invalid.` files in my memory directory. What happened?"
- **Pre-conditions**: A write bypassed the guard and the PostToolUse validation hook quarantined an invalid file.
- **Steps**:
  1. Notices files like `some-memory.json.invalid.1708099200` in a category folder
  2. Wonders what these are and if they're safe to delete
  3. Reads the quarantined file to understand the issue
  4. Either fixes and re-saves, or deletes the quarantined file
- **Expected Outcome**: User understands quarantine mechanism and how to handle quarantined files.
- **Documentation Needed**: What quarantine is, why it happens (validation failure), the naming convention (`.invalid.<timestamp>`), how to inspect and fix, that the original file is preserved as evidence.

### Scenario 27: Hook Errors During Session
- **Persona**: Pat (new user)
- **Motivation**: "I see error messages about memory hooks. Is something broken?"
- **Pre-conditions**: A hook encounters a non-fatal error.
- **Steps**:
  1. Sees stderr output from a hook (e.g., "WARNING: Config parse error, using defaults")
  2. Worries the plugin is broken
  3. Session continues normally (hooks fail-open)
- **Expected Outcome**: User understands that hooks fail-open (never trap the user), warnings are informational.
- **Documentation Needed**: Fail-open behavior explanation, common warning messages and what they mean, when to worry vs when to ignore.

### Scenario 28: The "Broken Index" Panic
- **Persona**: Pat (new user)
- **Motivation**: "I accidentally edited index.md and now retrieval is broken."
- **Pre-conditions**: User manually edited index.md, introducing format errors.
- **Steps**:
  1. Edited index.md to "fix a typo" in a memory title
  2. Retrieval stops working (regex can't parse malformed lines)
  3. Realizes something is wrong
  4. Runs `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory`
  5. Index regenerated from authoritative JSON files
- **Expected Outcome**: Index rebuilt, retrieval works again. User learns that index.md is a derived artifact that should not be manually edited.
- **Documentation Needed**: That index.md is auto-generated (not hand-edited), how to rebuild, that JSON files are the source of truth.

---

## Category 7: Collaboration and Git Workflows

### Scenario 29: Git Merge Conflicts in index.md
- **Persona**: Alex (experienced user)
- **Motivation**: "My teammate and I both triggered memory saves on different branches. Now we have merge conflicts in index.md."
- **Pre-conditions**: Two branches with different index.md additions.
- **Steps**:
  1. Both developers have memories auto-captured on separate branches
  2. On merge, index.md has conflicts
  3. Resolve by accepting both additions (index is append-style)
  4. Run `python3 hooks/scripts/memory_index.py --validate --root .claude/memory` to verify
  5. If needed, run --rebuild to regenerate clean index from JSON files
- **Expected Outcome**: Merge resolved, index valid.
- **Documentation Needed**: Git merge strategy for memory files, that JSON files rarely conflict (unique filenames), that index.md can always be rebuilt, recommended .gitattributes settings.

### Scenario 30: Cloning a Repo with Existing Memories
- **Persona**: Pat (new user)
- **Motivation**: "I just cloned a project that uses claude-memory. There are already memories from other developers."
- **Pre-conditions**: Project repo includes .claude/memory/ with existing memories.
- **Steps**:
  1. Clones the repo
  2. Starts Claude Code
  3. Types a prompt -- retrieval hook fires, injects existing memories
  4. Claude has context about previous decisions, constraints, preferences
  5. Pat is onboarded with institutional knowledge automatically
- **Expected Outcome**: New team member gets project context from day one.
- **Documentation Needed**: That memories are stored in the repo (per-project), how shared memories work, that session_summaries may not be relevant to new team members, how to disable retrieval of certain categories.

### Scenario 31: Sharing Memories Across Projects
- **Persona**: Sam (power user)
- **Motivation**: "I have coding preferences and team constraints that apply to all my projects. I don't want to recreate them each time."
- **Pre-conditions**: Has preference and constraint memories in one project.
- **Steps**:
  1. Copies JSON files from project A's `.claude/memory/preferences/` to project B's
  2. Copies relevant constraint files similarly
  3. Runs `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory` in project B
  4. Verifies with `/memory`
- **Expected Outcome**: Shared preferences available in new project.
- **Documentation Needed**: How to copy memories between projects, that index must be rebuilt after manual file operations, that related_files paths may need updating.

---

## Category 8: Privacy and Security

### Scenario 32: Sensitive Data Accidentally Captured
- **Persona**: Sam (power user)
- **Motivation**: "A runbook memory captured a database connection string with credentials. I need to remove it immediately."
- **Pre-conditions**: A memory contains sensitive data in its content fields.
- **Steps**:
  1. Discovers sensitive data via `/memory:search` or browsing files
  2. Uses `/memory --retire <slug>` to remove from active retrieval immediately
  3. Manually edits the JSON file to scrub the sensitive data, OR
  4. Waits for garbage collection to delete the file after grace period
  5. If urgent: manually deletes the file and runs --rebuild
  6. Checks git history -- may need to scrub from git as well
- **Expected Outcome**: Sensitive data removed from retrieval and storage.
- **Documentation Needed**: How to handle sensitive data in memories, immediate removal steps, git history scrubbing note, that auto-capture doesn't filter secrets, recommendation to use .gitignore for sensitive categories.

### Scenario 33: Controlling What Gets Auto-Captured
- **Persona**: Alex (experienced user)
- **Motivation**: "I'm working on a security-sensitive project. I want to limit what the plugin captures automatically."
- **Pre-conditions**: Default auto-capture settings.
- **Steps**:
  1. Disables auto-capture for categories that might capture sensitive info
  2. Types: `/memory:config disable runbook auto-capture`
  3. Lowers triage.enabled to false for maximum control
  4. Uses only /memory:save for manual, intentional saves
- **Expected Outcome**: No automatic memory capture, full manual control.
- **Documentation Needed**: How to disable all auto-capture (triage.enabled=false), per-category auto_capture toggle, manual-only workflow, privacy considerations.

---

## Category 9: Maintenance and Lifecycle

### Scenario 34: Routine Garbage Collection
- **Persona**: Alex (experienced user)
- **Motivation**: "I've retired several memories over the past month. I want to clean up the deleted ones."
- **Pre-conditions**: Has retired memories past the 30-day grace period.
- **Steps**:
  1. Types: `/memory --gc`
  2. Plugin reads delete.grace_period_days from config (default: 30)
  3. Scans all retired memories, checks retired_at timestamps
  4. Deletes files past the grace period
  5. Reports: "Purged 3 memories. 2 retired memories still within grace period."
  6. Suggests running --rebuild if files were deleted
- **Expected Outcome**: Old retired memories cleaned up, disk space reclaimed.
- **Documentation Needed**: GC command, grace period configuration, that archived memories are NOT garbage collected, --rebuild after GC.

### Scenario 35: Health Check and Index Validation
- **Persona**: Sam (power user)
- **Motivation**: "I want to make sure my memory store is in good shape."
- **Pre-conditions**: Has a large memory store (100+ memories).
- **Steps**:
  1. Types `/memory` for status overview
  2. Runs: `python3 hooks/scripts/memory_index.py --health --root .claude/memory`
  3. Reviews: entries by category, heavily updated memories, recent retirements, index sync
  4. If issues found, runs --validate to get specifics
  5. Runs --rebuild if needed
- **Expected Outcome**: Clear picture of memory store health.
- **Documentation Needed**: --health command output format, what "GOOD" vs "NEEDS ATTENTION" means, --validate command, what "heavily updated" means (times_updated > 5).

### Scenario 36: Session Rolling Window Cleanup
- **Persona**: Sam (power user)
- **Motivation**: "I have 20 session summaries. I only need the last 5."
- **Pre-conditions**: max_retained is 5 (default) but more than 5 active sessions exist.
- **Steps**:
  1. Session rolling window should auto-retire oldest when new one is created
  2. If not happening, checks config: categories.session_summary.max_retained
  3. Reviews active session summaries
  4. Manually retires old ones with `/memory --retire <slug>`
- **Expected Outcome**: Only the most recent N sessions remain active.
- **Documentation Needed**: How session rolling window works, max_retained config, that it auto-retires oldest, deletion guard warning for unique content.

### Scenario 37: Plugin Upgrade
- **Persona**: Alex (experienced user)
- **Motivation**: "A new version of claude-memory is available. How do I upgrade without losing my memories?"
- **Pre-conditions**: Has existing memories in .claude/memory/.
- **Steps**:
  1. `cd ~/.claude/plugins/claude-memory && git pull`
  2. Restarts Claude Code
  3. Checks `/memory` to verify memories are intact
  4. If schema changes: existing memories may need migration
  5. Runs --validate to check for issues
- **Expected Outcome**: Plugin upgraded, existing memories preserved.
- **Documentation Needed**: Upgrade procedure, backward compatibility guarantees, schema version handling, what to do if validation fails after upgrade.

---

## Category 10: Scale and Performance

### Scenario 38: Memory Store Growing Too Large
- **Persona**: Sam (power user)
- **Motivation**: "I have 300+ memories and retrieval is injecting too much irrelevant context."
- **Pre-conditions**: Large memory store with many entries across categories.
- **Steps**:
  1. Notices retrieval quality declining (irrelevant memories injected)
  2. Reduces max_inject from 5 to 3
  3. Reviews and retires outdated memories
  4. Archives historically important but no longer active memories
  5. Runs /memory --gc to clean up retired memories
  6. Considers per-category max_memories_per_category setting
- **Expected Outcome**: Leaner memory store with better retrieval quality.
- **Documentation Needed**: Scaling guidelines, when to retire vs archive, max_inject tuning, that max_memories_per_category exists (100 default), recommended maintenance cadence.

### Scenario 39: Retrieval Adding Too Much Latency
- **Persona**: Sam (power user)
- **Motivation**: "Every prompt takes noticeably longer because of memory retrieval. Can I speed it up?"
- **Pre-conditions**: Large index.md, deep-check reads many JSON files.
- **Steps**:
  1. Notices delay on each prompt ("Retrieving relevant memories..." takes several seconds)
  2. Options: reduce max_inject (fewer files to deep-check), set retrieval.enabled to false temporarily, reduce index size by retiring unused memories
  3. Understands that deep-check reads top 20 JSON files for recency/retired status
- **Expected Outcome**: Retrieval faster or disabled for performance-critical sessions.
- **Documentation Needed**: What causes retrieval latency (index scan + top-20 deep check), how to temporarily disable (retrieval.enabled=false or max_inject=0), performance characteristics.

---

## Category 11: Edge Cases and Error Recovery

### Scenario 40: Zombie Memory (File Deleted but Still in Index)
- **Persona**: Alex (experienced user)
- **Motivation**: "I deleted a memory JSON file directly from the filesystem. Now /memory:search shows it but the file is missing."
- **Pre-conditions**: User ran `rm .claude/memory/decisions/some-decision.json` directly.
- **Steps**:
  1. File gone but index.md still references it
  2. Retrieval may try to inject it (gets file-not-found during deep check)
  3. `/memory:search` shows it in results but can't display content
  4. Fix: `python3 hooks/scripts/memory_index.py --validate --root .claude/memory` to detect
  5. Then: `python3 hooks/scripts/memory_index.py --rebuild --root .claude/memory` to fix
- **Expected Outcome**: Index cleaned up to match actual files.
- **Documentation Needed**: Don't delete files directly (use /memory --retire), how to fix if you do, --validate to detect, --rebuild to fix.

### Scenario 41: Anti-Resurrection Conflict
- **Persona**: Sam (power user)
- **Motivation**: "I retired a memory and now I'm trying to create a new one with a similar title but getting an error."
- **Pre-conditions**: Recently retired memory with same slug as new creation attempt.
- **Steps**:
  1. Retired `use-redis-for-caching.json` an hour ago
  2. Tries to create new memory about caching with similar title
  3. Auto-fix generates same slug: `use-redis-for-caching`
  4. memory_write.py detects anti-resurrection: retired file exists with retired_at < 24 hours
  5. Gets ANTI_RESURRECTION_ERROR
  6. Options: use a different title/slug, wait 24 hours, or restore the old memory and update it
- **Expected Outcome**: User understands the anti-resurrection check and how to work around it.
- **Documentation Needed**: What anti-resurrection is (prevents accidental re-creation of retired memories within 24 hours), how to resolve (different slug, wait, or restore+update).

### Scenario 42: OCC (Optimistic Concurrency Control) Conflict
- **Persona**: Sam (power user)
- **Motivation**: "I got an OCC_CONFLICT error when trying to update a memory."
- **Pre-conditions**: Memory was modified by another process between read and write.
- **Steps**:
  1. Two concurrent sessions both try to update the same memory
  2. First update succeeds, changes the file's MD5 hash
  3. Second update provides stale --hash, gets OCC_CONFLICT
  4. Retry: re-read the file, incorporate changes, re-submit
- **Expected Outcome**: Conflict detected safely, no data loss.
- **Documentation Needed**: What OCC is, when it triggers, how to resolve (re-read and retry), that this protects against lost updates.

### Scenario 43: Dealing with a Corrupted Memory File
- **Persona**: Alex (experienced user)
- **Motivation**: "A memory file has invalid JSON or missing required fields. The plugin is showing errors."
- **Pre-conditions**: A memory file was corrupted (bad merge, manual edit, etc.).
- **Steps**:
  1. Validation hook may quarantine the file
  2. `/memory` status may show index desync
  3. Options: fix the JSON manually, delete and recreate, or let quarantine handle it
  4. After fixing: run --rebuild to update index
- **Expected Outcome**: Corrupted file handled, memory store restored to valid state.
- **Documentation Needed**: Common causes of corruption, how validation/quarantine works, manual repair steps, --validate to diagnose.

---

## Category 12: Natural Language Interactions

### Scenario 44: "Remember That..."
- **Persona**: Pat (new user)
- **Motivation**: "I want Claude to remember a fact without knowing which category to use."
- **Pre-conditions**: In a conversation, wants to save something.
- **Steps**:
  1. Says: "Remember that we should always run migrations with --dry-run first"
  2. Claude recognizes the "remember" trigger
  3. Determines this is a preference (convention about how things should be done)
  4. Creates a preference memory via the memory-management skill
- **Expected Outcome**: Memory saved to the appropriate category.
- **Documentation Needed**: Natural language triggers ("remember that...", "from now on...", "always..."), how category is auto-determined.

### Scenario 45: "Forget About..."
- **Persona**: Alex (experienced user)
- **Motivation**: "I told Claude to remember something that's no longer true. I want to undo it."
- **Pre-conditions**: Has a memory that is now incorrect.
- **Steps**:
  1. Says: "Forget about the preference to use yarn -- we switched to pnpm"
  2. Claude recognizes the "forget" trigger
  3. Asks for confirmation before retiring
  4. Retires the old preference
  5. Optionally creates a new preference for pnpm
- **Expected Outcome**: Old memory retired, optionally new one created.
- **Documentation Needed**: "Forget" trigger behavior, confirmation step, that retire (not permanent delete) is used.

### Scenario 46: "What Did We Decide About..."
- **Persona**: Alex (experienced user)
- **Motivation**: "I can't remember the rationale for a past decision."
- **Pre-conditions**: Has decision memories.
- **Steps**:
  1. Says: "What did we decide about the authentication approach?"
  2. Claude searches decision memories for "authentication"
  3. Finds the relevant decision
  4. Presents the full rationale, alternatives considered, and consequences
- **Expected Outcome**: Full decision context retrieved and presented.
- **Documentation Needed**: Supported natural language queries, that search covers titles/tags/content.

---

## Category 13: Runbook Evolution (Active Learning)

### Scenario 47: Runbook Retrieved and Applied During Error
- **Persona**: Pat (new user)
- **Motivation**: "I'm hitting the same Docker build error that was fixed before."
- **Pre-conditions**: Has a runbook memory for a Docker build error.
- **Steps**:
  1. Encounters a Docker build error
  2. Describes the error to Claude
  3. Retrieval hook matches keywords ("error", "docker", "build") against runbook
  4. Claude references the stored runbook: "I found a runbook for this error..."
  5. Follows the fix steps
  6. Error resolved
- **Expected Outcome**: Error fixed faster using stored institutional knowledge.
- **Documentation Needed**: How runbooks are retrieved, that error keywords trigger matching, the runbook schema fields (trigger, symptoms, steps, verification).

### Scenario 48: Runbook Updated After Discovering Better Fix
- **Persona**: Alex (experienced user)
- **Motivation**: "I followed the runbook but found a better fix. I want to update it."
- **Pre-conditions**: Applied a runbook but discovered an improvement.
- **Steps**:
  1. Says: "The docker-build-fix runbook works but there's a faster fix: use `docker compose build --no-cache --pull`"
  2. Claude updates the existing runbook via memory-management skill
  3. memory_candidate.py finds the existing entry
  4. Drafts updated content with new steps
  5. memory_write.py updates with change tracked in changes[]
- **Expected Outcome**: Runbook improved for next time, change history preserved.
- **Documentation Needed**: How to request runbook updates, that changes are tracked, that the original information is preserved in change history.

---

## Scenario Coverage Matrix

| Feature / Behavior | Scenario # | Persona | Currently Documented? |
|---|---|---|---|
| **Installation** | 1 | Pat | Partial (README) - missing prerequisites |
| **Verification** | 2 | Pat | No |
| **Inspecting saved memories** | 3 | Pat | No |
| **Auto-retrieval** | 4 | Alex | Partial (README) |
| **Auto-capture (decision)** | 5 | Alex | Partial (README architecture section) |
| **Auto-update existing memory** | 6 | Alex | No |
| **First surprise (injected context)** | 7 | Pat | No |
| **Manual save (/memory:save)** | 8 | Pat | README commands table |
| **Search (/memory:search)** | 9 | Alex | README commands table |
| **Retire (/memory --retire)** | 10 | Alex | No (not in README) |
| **Archive (/memory --archive)** | 11 | Alex | No (not in README) |
| **Restore (/memory --restore)** | 12 | Alex | No (not in README) |
| **Check config** | 13 | Alex | Partial |
| **Reduce max_inject** | 14 | Alex | No |
| **Disable category** | 15 | Alex | README config table |
| **Tune triage thresholds** | 16 | Sam | No |
| **Change model assignments** | 17 | Sam | Partial (README) |
| **Custom category** | 18 | Sam | Mentioned but not explained |
| **Verify memory accuracy** | 19 | Pat | No |
| **Correct inaccurate memory** | 20 | Alex | No |
| **View all memories** | 21 | Pat | No |
| **Capture not triggering** | 22 | Pat | No |
| **Retrieval not matching** | 23 | Alex | No |
| **Index desync** | 24 | Alex | Partial (index maintenance section) |
| **Pydantic missing** | 25 | Pat | No |
| **Quarantined files** | 26 | Alex | No |
| **Hook errors** | 27 | Pat | No |
| **Broken index** | 28 | Pat | No |
| **Git merge conflicts** | 29 | Alex | No |
| **Clone with existing memories** | 30 | Pat | No |
| **Share memories across projects** | 31 | Sam | No |
| **Sensitive data captured** | 32 | Sam | No |
| **Control auto-capture** | 33 | Alex | No |
| **Garbage collection** | 34 | Alex | No (not in README) |
| **Health check** | 35 | Sam | Partial |
| **Session rolling window** | 36 | Sam | No (not in README) |
| **Plugin upgrade** | 37 | Alex | No |
| **Scale/noise** | 38 | Sam | No |
| **Retrieval latency** | 39 | Sam | No |
| **Zombie memory** | 40 | Alex | No |
| **Anti-resurrection** | 41 | Sam | No |
| **OCC conflict** | 42 | Sam | No |
| **Corrupted file** | 43 | Alex | No |
| **"Remember that..."** | 44 | Pat | SKILL.md only |
| **"Forget about..."** | 45 | Alex | SKILL.md only |
| **"What did we decide..."** | 46 | Alex | SKILL.md only |
| **Runbook retrieved** | 47 | Pat | No |
| **Runbook updated** | 48 | Alex | No |

### Coverage Summary

- **Total scenarios**: 48
- **Currently well-documented**: 4 (8%)
- **Partially documented**: 8 (17%)
- **Not documented at all**: 36 (75%)

### Documentation Priority by Scenario Group

| Priority | Category | Scenarios | Rationale |
|---|---|---|---|
| P0 | Installation & Verification | 1-3 | First-time users need this to succeed |
| P0 | Troubleshooting | 22-28 | Users will hit these and need help |
| P1 | Daily Usage | 4-7 | Core value proposition |
| P1 | Memory Management | 8-12 | Commands missing from README |
| P1 | Trust & Verification | 19-21 | Unique to AI memory systems |
| P2 | Configuration | 13-18 | Power users need reference |
| P2 | Collaboration | 29-31 | Multi-developer workflows |
| P2 | Privacy & Security | 32-33 | Important but situational |
| P3 | Maintenance | 34-37 | Routine operations |
| P3 | Scale | 38-39 | Large-store optimization |
| P3 | Edge Cases | 40-43 | Rare but documented |
| P3 | Natural Language | 44-46 | Partially in SKILL.md |
| P3 | Runbook Evolution | 47-48 | Advanced usage pattern |

---

## Config Options Coverage by Scenario

| Config Option | Scenario # | Currently Documented? |
|---|---|---|
| retrieval.max_inject | 14, 38, 39 | README |
| retrieval.enabled | 33, 39 | No |
| categories.*.enabled | 15 | README |
| categories.*.auto_capture | 15, 33 | README |
| categories.*.retention_days | -- | README (not in any scenario -- no current user need) |
| categories.session_summary.max_retained | 36 | No |
| triage.enabled | 22, 33 | No |
| triage.max_messages | -- | No (not in any scenario) |
| triage.thresholds.* | 16, 22 | No |
| triage.parallel.enabled | -- | README |
| triage.parallel.category_models | 17 | README |
| triage.parallel.verification_model | 17 | README |
| triage.parallel.default_model | 17 | README |
| max_memories_per_category | 38 | README |
| delete.grace_period_days | 12, 34, 41 | No |
| delete.archive_retired | -- | No (not in any scenario) |
| auto_commit | -- | No (not in any scenario -- not read by scripts) |
| retrieval.match_strategy | -- | No (not in any scenario -- not read by scripts) |
| memory_root | -- | No (not in any scenario -- not read by scripts) |

**Config options with no scenario coverage**: retention_days, triage.max_messages, triage.parallel.enabled, delete.archive_retired, auto_commit, match_strategy, memory_root. These are either not read by scripts (documentation-only) or are too niche for standard scenarios.

---

## Cross-Model Validation Notes

### From Gemini 3 Pro (via pal clink)
Gemini identified 13 additional scenarios, several of which were incorporated:
- "Broken Index" Panic -> Scenario 28
- "Zombie Memory" Confusion -> Scenario 40
- "Secret Leaked" Emergency -> Scenario 32
- "Permissions" Block -> Covered implicitly in Scenario 25 (dependency errors)
- "Git Merge" Conflict -> Scenario 29
- "Edit War" Resolution -> Partially covered by Scenario 42 (OCC)
- "Code Review" Context -> Out of scope (CI/CD integration, not current feature)
- "Shared Preferences" Bootstrap -> Scenario 31
- "Stale Knowledge" Deprecation -> Scenario 10
- "Custom Category" Expansion -> Scenario 18
- "Context Hog" Overload -> Scenario 38
- "Runbook" Evolution -> Scenarios 47-48
- "Schema Migration" Update -> Scenario 37

### From Vibe-Check (metacognitive review)
Key adjustments made based on vibe-check feedback:
- Reorganized from feature-catalog to motivation-driven scenarios
- Added "Trust & Verification" category (Scenarios 19-21)
- Added "First Surprise" scenario (7) for the auto-retrieval discovery moment
- Added "Privacy & Security" category (Scenarios 32-33)
- Added "Collaboration & Git" category (Scenarios 29-31)
- Ensured ~30% unhappy-path coverage (Scenarios 22-28, 40-43)

### Codex 5.3
Codex was unavailable due to rate limits at time of authoring. The scenario list was validated through Gemini and vibe-check instead.
