# Verification Round 1: Usability Check

## Summary
- Scenarios tested: 48
- Fully supported: 28
- Partially supported: 15
- Not supported: 5

## Methodology

Each scenario was evaluated from the perspective of a NEW user who has NEVER seen this codebase. A "PASS" means a user could complete the scenario using ONLY the documentation. "PARTIAL" means the user can find some guidance but key steps or information are missing. "FAIL" means the user would be stuck without external help.

Documentation files tested:
- `README.md` (main user docs)
- `commands/memory.md`, `commands/memory-save.md`, `commands/memory-search.md`, `commands/memory-config.md`
- `CLAUDE.md` (developer docs)
- `skills/memory-management/SKILL.md` (orchestration docs)

---

## Scenario Results

### Category 1: Discovery and Installation

#### Scenario 1: First-Time Installation - PASS
- **Can user find docs?** Yes -- README has Prerequisites + Installation sections
- **Instructions clear?** Yes -- step-by-step with bash commands, includes `mkdir -p`
- **Examples provided?** Yes -- copy-pasteable bash commands
- **Troubleshooting available?** Partial -- pydantic error is covered in Troubleshooting section
- **Issues**: None significant. The prerequisites clearly list Python 3.8+ and pydantic v2 with installation command.

#### Scenario 2: Verifying Installation Works - PARTIAL
- **Can user find docs?** Partially -- "Typical Workflow" section provides high-level steps, `/memory` command is documented
- **Instructions clear?** No -- there is no explicit "verify your installation" walkthrough
- **Examples provided?** The Typical Workflow hints at what to expect but doesn't walk through a first session
- **Troubleshooting available?** Yes -- "Memories not being captured" section exists
- **Issues**:
  - No "First Session" guide explaining what the user should see after installation
  - No explanation of what "Evaluating session for memories..." means when it appears
  - No guidance on minimum session activity needed to trigger auto-capture
  - User scenario notes "Session may be too short to trigger any category thresholds" but docs don't address this for new users

#### Scenario 3: Understanding What Just Got Saved - PARTIAL
- **Can user find docs?** Yes -- Storage Structure section, JSON Schema section, Memory Lifecycle section all exist
- **Instructions clear?** Partially -- storage structure is documented with directory tree, JSON example shows fields
- **Examples provided?** Yes -- full JSON example in README
- **Troubleshooting available?** No specific guidance for browsing/inspecting individual memories
- **Issues**:
  - No guide for "what each field means" beyond what's shown in the JSON example
  - The `confidence` field is shown but not explained (what does 0.9 mean to the user?)
  - `record_status`, `changes`, `times_updated` are listed but their user-facing significance is not explained inline (lifecycle section helps but is separate)
  - No "how to browse your memories" walkthrough

---

### Category 2: Daily Usage -- Automatic Behavior

#### Scenario 4: Auto-Retrieval Surfaces Relevant Context - PASS
- **Can user find docs?** Yes -- "Auto-Retrieval" section in Architecture, plus Troubleshooting for "not retrieved"
- **Instructions clear?** Yes -- explains keyword scoring on index titles/tags
- **Examples provided?** No explicit example of what injected context looks like to the user
- **Troubleshooting available?** Yes -- "Memories not being retrieved" covers exact keyword matching limitation
- **Issues**:
  - No visual example of what `<memory-context>` injection looks like in a response
  - User scenario mentions "how to tell when memories were retrieved" -- docs don't cover this

#### Scenario 5: Auto-Capture Saves a New Decision - PASS
- **Can user find docs?** Yes -- Four-Phase Auto-Capture section, Triage Signal table
- **Instructions clear?** Yes -- signals table explains what triggers each category
- **Examples provided?** Triage Signal table gives examples like "decided X because Y"
- **Troubleshooting available?** Yes -- "Memories not being captured" troubleshooting entry
- **Issues**:
  - The threshold defaults are documented (decision=0.4), which helps
  - The Triage Signal table is helpful but brief -- power users may want more detail on exact keywords

#### Scenario 6: Auto-Capture Updates an Existing Memory - PARTIAL
- **Can user find docs?** Partially -- CUD table in SKILL.md, but nothing user-facing in README
- **Instructions clear?** No -- the update vs create decision logic is only in SKILL.md (developer doc)
- **Examples provided?** No user-facing example of how an update looks
- **Troubleshooting available?** No
- **Issues**:
  - README doesn't explain that auto-capture can UPDATE existing memories (not just CREATE)
  - No mention of `memory_candidate.py` or duplicate detection from the user perspective
  - The `changes[]` array and `times_updated` field are documented but not connected to this use case

#### Scenario 7: The "First Surprise" -- Discovering Injected Context - PARTIAL
- **Can user find docs?** Partially -- Auto-Retrieval section exists but doesn't address the "surprise" experience
- **Instructions clear?** Partially -- explains mechanism but not the user experience
- **Examples provided?** No
- **Troubleshooting available?** No specific guidance for "what just happened?"
- **Issues**:
  - No FAQ-style entry like "Why did Claude reference something from a previous session?"
  - No explanation of how to control what gets injected (pointer to max_inject, retrieval.enabled is in config table but not contextualized)
  - The Typical Workflow step 3 helps: "When you start a new session and mention a topic, relevant memories are injected" -- but a new user hitting this for the first time may not connect the dots

---

### Category 3: Intentional Memory Management

#### Scenario 8: Manually Saving a Memory - PASS
- **Can user find docs?** Yes -- Commands table lists `/memory:save`, `commands/memory-save.md` has full detail
- **Instructions clear?** Yes -- examples show exact syntax for each category
- **Examples provided?** Yes -- 4 examples covering decision, preference, runbook, constraint
- **Troubleshooting available?** Not needed (straightforward command)
- **Issues**: None significant. Well documented.

#### Scenario 9: Searching for a Specific Memory - PASS
- **Can user find docs?** Yes -- Commands table lists `/memory:search`, `commands/memory-search.md` has detail
- **Instructions clear?** Yes -- scoring system explained, --include-retired flag documented
- **Examples provided?** Yes -- 3 examples in the command file
- **Troubleshooting available?** Yes -- "Memories not being retrieved" covers keyword matching limitations
- **Issues**: None significant. Scoring weights (tag=3, title=2, prefix=1, recency=+1) are clearly documented.

#### Scenario 10: Retiring an Outdated Decision - PASS
- **Can user find docs?** Yes -- Commands table, Memory Lifecycle section, `commands/memory.md` --retire section
- **Instructions clear?** Yes -- retire command documented with confirmation step
- **Examples provided?** Yes -- examples in README Commands section and in memory.md
- **Troubleshooting available?** Lifecycle table explains grace period
- **Issues**: None. The 30-day grace period and GC behavior are clearly documented.

#### Scenario 11: Archiving a Memory for Posterity - PASS
- **Can user find docs?** Yes -- Commands table, Memory Lifecycle section, `commands/memory.md` --archive section
- **Instructions clear?** Yes -- archive command and its difference from retire are documented
- **Examples provided?** Yes -- example in README Commands section
- **Troubleshooting available?** Lifecycle table clearly shows archived = no GC
- **Issues**: None.

#### Scenario 12: Restoring a Retired Memory - PASS
- **Can user find docs?** Yes -- Commands table, Memory Lifecycle section, `commands/memory.md` --restore section
- **Instructions clear?** Yes -- restore command documented with grace period check and staleness warning
- **Examples provided?** Yes -- example in README Commands section
- **Troubleshooting available?** Grace period expiration is addressed ("Memory is eligible for GC and cannot be restored")
- **Issues**: None. The 7-day staleness warning and 30-day grace period are clearly documented in `commands/memory.md`.

---

### Category 4: Configuration and Customization

#### Scenario 13: Checking Current Configuration - PASS
- **Can user find docs?** Yes -- Configuration section in README lists all settings with defaults
- **Instructions clear?** Yes -- file location (`.claude/memory/memory-config.json`) is documented
- **Examples provided?** `/memory` command shows config overview; `assets/memory-config.default.json` is referenced
- **Troubleshooting available?** Not needed
- **Issues**: None.

#### Scenario 14: Reducing Context Injection Noise - PASS
- **Can user find docs?** Yes -- Config table lists `retrieval.max_inject`, `commands/memory-config.md` has example
- **Instructions clear?** Yes -- `/memory:config set max_inject to 3` is an example in the config command file
- **Examples provided?** Yes -- exact command shown
- **Troubleshooting available?** Config table notes "clamped 0-20"
- **Issues**: None. Well-covered.

#### Scenario 15: Disabling Auto-Capture for a Category - PASS
- **Can user find docs?** Yes -- Config table lists `categories.*.auto_capture`, config command file has example
- **Instructions clear?** Yes -- `/memory:config disable runbook auto-capture` is an example
- **Examples provided?** Yes
- **Troubleshooting available?** Config command file notes "Do NOT delete existing memory files when disabling a category"
- **Issues**: None.

#### Scenario 16: Tuning Triage Thresholds - PASS
- **Can user find docs?** Yes -- Config table lists `triage.thresholds.*`, config command has example
- **Instructions clear?** Yes -- `/memory:config raise decision threshold to 0.7` is an example
- **Examples provided?** Yes -- defaults listed: decision=0.4, runbook=0.4, etc.
- **Troubleshooting available?** "Higher values = fewer but higher-confidence captures" is noted
- **Issues**: None. Threshold defaults and their meaning are clearly documented.

#### Scenario 17: Changing Model Assignments for Cost Control - PASS
- **Can user find docs?** Yes -- Config table lists `triage.parallel.category_models`, defaults listed, config command has example
- **Instructions clear?** Yes -- `/memory:config set all category models to haiku` is an example
- **Examples provided?** Yes -- default model assignments per category are listed
- **Troubleshooting available?** Token Cost section discusses cost implications
- **Issues**: None.

#### Scenario 18: Adding a Custom Category - PARTIAL
- **Can user find docs?** Partially -- `commands/memory-config.md` mentions custom categories are NOT supported
- **Instructions clear?** Yes, but negatively -- the docs say custom categories lack validation support
- **Examples provided?** No -- no example of how to create/use a custom category
- **Troubleshooting available?** No
- **Issues**:
  - The config command file says "Custom categories are not currently supported by the validation pipeline" which is clear
  - But there is no guidance on what a user CAN do if they want a custom category (manual JSON files? workaround?)
  - The user scenario expects `/memory:config add category api_docs` but docs don't describe this path
  - This is arguably correct behavior (documenting limitations), but a user with this need has no path forward

---

### Category 5: Trust and Verification

#### Scenario 19: Verifying Memory Accuracy - PARTIAL
- **Can user find docs?** Partially -- `/memory:search` can find the memory, JSON Schema section shows fields
- **Instructions clear?** No -- no guidance on how to verify accuracy of auto-captured content
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No mention that auto-captured memories are LLM-drafted (not verbatim quotes from the session)
  - No explanation of what the `confidence` field means to the user
  - No guidance on "how to inspect a memory for accuracy"
  - The doc-changes-log notes this as a gap: "Could add tip on inspecting JSON to verify memory accuracy"

#### Scenario 20: Correcting an Inaccurate Memory - PARTIAL
- **Can user find docs?** Partially -- SKILL.md "When the User Asks About Memories" covers "Remember that..." but not explicit corrections
- **Instructions clear?** No -- no documented path for "please fix this memory"
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No documented natural-language pattern for requesting corrections
  - The `changes[]` array exists for tracking updates but users don't know how to trigger an update
  - A user would likely just say "update the runbook" and hope Claude understands -- which it probably does via SKILL.md, but this isn't documented from the user perspective

#### Scenario 21: Understanding What Claude "Knows" - PASS
- **Can user find docs?** Yes -- `/memory` command shows status, SKILL.md "When the User Asks About Memories" covers "What do you remember?"
- **Instructions clear?** Yes -- `/memory` shows categories and counts; natural language "What do you remember?" is documented
- **Examples provided?** `/memory` example shows status command
- **Troubleshooting available?** Not needed
- **Issues**: Minor -- the distinction between "what's stored" vs "what's injected per prompt" isn't explicitly stated in user-facing docs (README covers this indirectly via max_inject).

---

### Category 6: Troubleshooting

#### Scenario 22: Memory Not Being Captured - PASS
- **Can user find docs?** Yes -- Troubleshooting section has "Memories not being captured"
- **Instructions clear?** Yes -- lists causes and solutions: check triage.enabled, use trigger keywords, lower thresholds, use /memory:save
- **Examples provided?** Yes -- `/memory:config set decision threshold to 0.3` example
- **Troubleshooting available?** Yes (this IS the troubleshooting entry)
- **Issues**: None. Well-covered.

#### Scenario 23: Memory Not Being Retrieved - PASS
- **Can user find docs?** Yes -- Troubleshooting section has "Memories not being retrieved"
- **Instructions clear?** Yes -- explains exact keyword matching vs semantic, 10-char minimum, stop-word filtering
- **Examples provided?** Yes -- "API throttling" vs "API rate limit" example
- **Troubleshooting available?** Yes
- **Issues**: None. The keyword matching limitation is clearly explained.

#### Scenario 24: Index Out of Sync - PASS
- **Can user find docs?** Yes -- Troubleshooting section + Index Maintenance section
- **Instructions clear?** Yes -- validate then rebuild commands shown
- **Examples provided?** Yes -- full bash commands with --validate and --rebuild
- **Troubleshooting available?** Yes -- notes "after git merges or manual file changes, always rebuild"
- **Issues**: None.

#### Scenario 25: Pydantic Not Installed - PASS
- **Can user find docs?** Yes -- Prerequisites section + Troubleshooting entry
- **Instructions clear?** Yes -- `pip install 'pydantic>=2.0,<3.0'` command provided
- **Examples provided?** Yes
- **Troubleshooting available?** Yes -- mentions venv re-exec fallback
- **Issues**: None.

#### Scenario 26: Quarantined Files - PASS
- **Can user find docs?** Yes -- Troubleshooting section has "Quarantined files"
- **Instructions clear?** Yes -- explains what they are, naming convention, how to handle
- **Examples provided?** Naming convention example: `<filename>.invalid.<unix_timestamp>`
- **Troubleshooting available?** Yes
- **Issues**: None.

#### Scenario 27: Hook Errors During Session - PASS
- **Can user find docs?** Yes -- Troubleshooting section has "Hook errors"
- **Instructions clear?** Yes -- explains fail-open behavior, common warnings are informational
- **Examples provided?** Yes -- example warning: "Config parse error, using defaults"
- **Troubleshooting available?** Yes
- **Issues**: None.

#### Scenario 28: The "Broken Index" Panic - PASS
- **Can user find docs?** Yes -- Index Maintenance section, Troubleshooting "Index out of sync"
- **Instructions clear?** Yes -- rebuild command is clear
- **Examples provided?** Yes -- bash commands for rebuild
- **Troubleshooting available?** Yes -- "index is a derived artifact auto-generated from authoritative JSON files"
- **Issues**: Minor -- the README doesn't explicitly warn "do not manually edit index.md" in a prominent location. The Index Maintenance section says it's "auto-generated from the authoritative JSON files" which implies this, but a more explicit warning would help.

---

### Category 7: Collaboration and Git Workflows

#### Scenario 29: Git Merge Conflicts in index.md - PARTIAL
- **Can user find docs?** Partially -- Index Maintenance mentions "after git merges... always rebuild"
- **Instructions clear?** No -- no explicit merge conflict resolution strategy
- **Examples provided?** No
- **Troubleshooting available?** The rebuild command is available, but no merge-specific guidance
- **Issues**:
  - No guidance on resolving index.md merge conflicts (accept both sides then rebuild)
  - No `.gitattributes` recommendation
  - The doc-changes-log notes: "Could add explicit 'commit .claude/memory to git to share context' guidance"

#### Scenario 30: Cloning a Repo with Existing Memories - PARTIAL
- **Can user find docs?** Partially -- Storage Structure shows memories are per-project in `.claude/memory/`
- **Instructions clear?** No -- no explanation of what happens when you clone a repo that already has memories
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No guidance on team onboarding via shared memories
  - No mention that `.claude/memory/` should be committed to git for team sharing
  - No note about session summaries being less relevant to other team members

#### Scenario 31: Sharing Memories Across Projects - FAIL
- **Can user find docs?** No -- no documentation on cross-project memory sharing
- **Instructions clear?** N/A
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No guidance on copying memories between projects
  - No mention that index must be rebuilt after manual file operations (except in Index Maintenance section, which users would need to find)
  - This is a power-user scenario (Sam) so lower priority, but completely undocumented

---

### Category 8: Privacy and Security

#### Scenario 32: Sensitive Data Accidentally Captured - FAIL
- **Can user find docs?** No -- no privacy/security section in README
- **Instructions clear?** N/A
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No guidance on handling sensitive data in memories
  - No mention of git history scrubbing
  - No recommendation for `.gitignore` patterns for sensitive categories
  - This is a significant gap for any plugin that auto-captures content from conversations

#### Scenario 33: Controlling What Gets Auto-Captured - PASS
- **Can user find docs?** Yes -- Config section lists `triage.enabled`, `categories.*.auto_capture`, examples in config command
- **Instructions clear?** Yes -- `/memory:config disable triage entirely` is an example
- **Examples provided?** Yes
- **Troubleshooting available?** Not needed
- **Issues**: None. The path to disable all auto-capture is documented.

---

### Category 9: Maintenance and Lifecycle

#### Scenario 34: Routine Garbage Collection - PASS
- **Can user find docs?** Yes -- Commands table lists `--gc`, Index Maintenance shows `--gc` command
- **Instructions clear?** Yes -- command documented with grace period reference
- **Examples provided?** Yes -- `/memory --gc` in README examples
- **Troubleshooting available?** Grace period is configurable via `delete.grace_period_days`
- **Issues**: None.

#### Scenario 35: Health Check and Index Validation - PASS
- **Can user find docs?** Yes -- Index Maintenance section has `--health` and `--validate` commands
- **Instructions clear?** Yes -- commands shown with descriptions
- **Examples provided?** Yes -- full bash commands
- **Troubleshooting available?** --validate detects issues, --rebuild fixes them
- **Issues**: Minor -- no explanation of what `--health` output looks like or what "heavily updated" means (times_updated > 5 is in commands/memory.md but not in README).

#### Scenario 36: Session Rolling Window Cleanup - PARTIAL
- **Can user find docs?** Partially -- Config table lists `categories.session_summary.max_retained` with default 5
- **Instructions clear?** No -- the rolling window mechanism is not explained in README
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - Rolling window behavior is only documented in SKILL.md (developer doc), not in README
  - A user wouldn't know that old sessions are auto-retired when new ones are created
  - The config option exists but its behavior isn't explained in user-facing docs

#### Scenario 37: Plugin Upgrade - FAIL
- **Can user find docs?** No -- no upgrade documentation
- **Instructions clear?** N/A
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No upgrade procedure documented
  - No backward compatibility guarantees stated
  - No guidance on what to do after pulling a new version
  - Version number (v5.0.0) is shown but no changelog or migration notes exist

---

### Category 10: Scale and Performance

#### Scenario 38: Memory Store Growing Too Large - PARTIAL
- **Can user find docs?** Partially -- Config table lists `max_memories_per_category`, `max_inject`, `--gc`
- **Instructions clear?** No -- no "scaling guidelines" section
- **Examples provided?** Individual commands exist but no combined maintenance workflow
- **Troubleshooting available?** Partial -- troubleshooting covers retrieval issues
- **Issues**:
  - No guidance on when to retire vs archive
  - No recommended maintenance cadence
  - The user would need to piece together config changes + GC + retirement from multiple sections

#### Scenario 39: Retrieval Adding Too Much Latency - FAIL
- **Can user find docs?** No -- no performance documentation
- **Instructions clear?** N/A
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No explanation of what causes retrieval latency
  - No guidance on temporarily disabling retrieval for performance
  - The auto-retrieval mechanism (keyword matching on index) is documented, but performance characteristics are not

---

### Category 11: Edge Cases and Error Recovery

#### Scenario 40: Zombie Memory (File Deleted but Still in Index) - PASS
- **Can user find docs?** Yes -- Index Maintenance section + Troubleshooting "Index out of sync"
- **Instructions clear?** Yes -- validate to detect, rebuild to fix
- **Examples provided?** Yes -- bash commands
- **Troubleshooting available?** Yes
- **Issues**: Minor -- no explicit "don't delete files directly" warning, but the lifecycle commands (--retire) provide the right path.

#### Scenario 41: Anti-Resurrection Conflict - PARTIAL
- **Can user find docs?** Partially -- SKILL.md documents anti-resurrection in "Write Pipeline Protections"
- **Instructions clear?** Partially -- workarounds are listed in SKILL.md (different slug, wait 24h, restore+update)
- **Examples provided?** No
- **Troubleshooting available?** No user-facing troubleshooting entry
- **Issues**:
  - Anti-resurrection is only documented in SKILL.md (developer/agent doc), not README
  - A user hitting `ANTI_RESURRECTION_ERROR` would not find guidance in user-facing docs
  - Should be in Troubleshooting section

#### Scenario 42: OCC (Optimistic Concurrency Control) Conflict - PARTIAL
- **Can user find docs?** Partially -- README mentions OCC in Shared Index: "MD5 hash check to prevent lost writes"
- **Instructions clear?** No -- just a mention, no explanation of what happens or how to resolve
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - OCC is mentioned but not explained from user perspective
  - No troubleshooting entry for OCC_CONFLICT errors
  - SKILL.md has more detail but it's developer-facing

#### Scenario 43: Dealing with a Corrupted Memory File - PARTIAL
- **Can user find docs?** Partially -- Quarantine troubleshooting entry, index rebuild
- **Instructions clear?** No -- no specific "corrupted file" guidance
- **Examples provided?** No
- **Troubleshooting available?** Partial -- quarantine and rebuild are documented but not connected to this scenario
- **Issues**:
  - No guidance on common causes of corruption (bad merge, manual edit, etc.)
  - No manual repair steps documented
  - A user would need to combine quarantine + validate + rebuild knowledge from multiple sections

---

### Category 12: Natural Language Interactions

#### Scenario 44: "Remember That..." - PASS
- **Can user find docs?** Yes -- SKILL.md "When the User Asks About Memories" lists triggers including "Remember that..."
- **Instructions clear?** Yes -- trigger words listed
- **Examples provided?** No explicit example of usage from user perspective
- **Troubleshooting available?** Not needed
- **Issues**: Minor -- documented in SKILL.md which is loaded by the agent, so it works. But README doesn't mention natural language memory interactions.

#### Scenario 45: "Forget About..." - PASS
- **Can user find docs?** Yes -- SKILL.md covers "Forget..." trigger with confirmation step
- **Instructions clear?** Yes -- triggers listed with behavior
- **Examples provided?** No explicit example
- **Troubleshooting available?** Not needed
- **Issues**: Same as Scenario 44 -- SKILL.md covers it but README doesn't mention this capability.

#### Scenario 46: "What Did We Decide About..." - PASS
- **Can user find docs?** Yes -- SKILL.md covers "What did we decide about X?" trigger
- **Instructions clear?** Yes
- **Examples provided?** No explicit example
- **Troubleshooting available?** Not needed
- **Issues**: Same as Scenarios 44-45. Functional via SKILL.md but not mentioned in README.

---

### Category 13: Runbook Evolution (Active Learning)

#### Scenario 47: Runbook Retrieved and Applied During Error - PARTIAL
- **Can user find docs?** Partially -- Auto-Retrieval section explains keyword matching; Memory Categories table describes runbooks
- **Instructions clear?** No -- no specific guidance on how runbooks are retrieved during errors
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No explanation of the runbook retrieval experience from user perspective
  - The schema fields (trigger, symptoms, steps, verification) are in SKILL.md but not README
  - A user wouldn't know that describing an error triggers runbook retrieval

#### Scenario 48: Runbook Updated After Discovering Better Fix - PARTIAL
- **Can user find docs?** Partially -- Same as Scenario 20 (correcting a memory) -- SKILL.md handles "Remember that..." and update triggers
- **Instructions clear?** No -- no documented pattern for requesting runbook updates
- **Examples provided?** No
- **Troubleshooting available?** No
- **Issues**:
  - No guidance on how to request updates to existing memories
  - The `changes[]` tracking is documented but not connected to user-initiated updates

---

## Recommendations

### High Priority

1. **Add "Getting Started" / "First Session" walkthrough to README** (Scenarios 2, 3, 7)
   - Explain what happens after installation: first session, stop hook firing, what the output means
   - Add minimum session activity guidance for triggering auto-capture
   - Explain what injected context looks like to the user
   - Explain how to browse/inspect saved memories

2. **Add "Sensitive Data" / "Privacy" subsection to README** (Scenario 32)
   - How to handle accidentally captured sensitive data
   - Immediate removal steps (retire + manual delete + rebuild)
   - Git history scrubbing note
   - Recommendation for .gitignore patterns if sensitive categories shouldn't be committed

3. **Add anti-resurrection and OCC to Troubleshooting** (Scenarios 41, 42)
   - User-facing explanation of ANTI_RESURRECTION_ERROR and workarounds
   - User-facing explanation of OCC_CONFLICT and retry guidance
   - These errors can surface to users and currently have no user-facing documentation

4. **Add upgrade procedure to README** (Scenario 37)
   - `git pull` + restart procedure
   - Backward compatibility statement
   - Post-upgrade verification steps (run --validate)

### Medium Priority

5. **Add "Natural Language Interactions" note to README** (Scenarios 44-46)
   - Brief mention that users can say "remember that...", "forget...", "what did we decide about..."
   - Currently only in SKILL.md which users cannot read directly

6. **Add git/collaboration guidance to README** (Scenarios 29, 30)
   - Note that .claude/memory/ should be committed for team sharing
   - Merge conflict strategy: accept both sides, then rebuild index
   - New team member onboarding experience

7. **Document auto-update behavior in README** (Scenario 6)
   - Mention that auto-capture can UPDATE existing memories, not just create new ones
   - Explain duplicate detection briefly

8. **Add session rolling window explanation to README** (Scenario 36)
   - Brief explanation that oldest sessions auto-retire when max_retained is exceeded
   - Currently only in SKILL.md

9. **Add "Correcting a Memory" guidance** (Scenarios 19, 20, 48)
   - How to verify accuracy of auto-captured memories
   - How to request corrections (natural language patterns)
   - What the confidence field means

### Low Priority

10. **Add performance/scaling notes** (Scenarios 38, 39)
    - Brief guidance on retrieval latency and how to mitigate
    - Recommended maintenance cadence for large stores
    - When to retire vs archive

11. **Add cross-project memory sharing guidance** (Scenario 31)
    - How to copy memories between projects
    - Need to rebuild index after manual file operations

12. **Add corrupted file recovery guidance** (Scenario 43)
    - Common causes of corruption
    - Step-by-step recovery process

13. **Warn against manual index.md editing** (Scenario 28)
    - Add explicit "do not manually edit index.md" warning in Index Maintenance section

---

## Hardest-to-Follow Scenarios

The following scenarios had the worst usability from a new user perspective:

1. **Scenario 32 (Sensitive Data)** - FAIL - No documentation at all for a critical safety concern
2. **Scenario 37 (Plugin Upgrade)** - FAIL - No upgrade procedure despite version numbering
3. **Scenario 31 (Cross-Project Sharing)** - FAIL - Power user scenario with zero guidance
4. **Scenario 39 (Retrieval Latency)** - FAIL - Performance concerns undocumented
5. **Scenario 2 (Verifying Installation)** - PARTIAL - First-time users left guessing after install
6. **Scenario 41 (Anti-Resurrection)** - PARTIAL - Error surfaced to users with no user-facing docs
7. **Scenario 6 (Auto-Update Existing)** - PARTIAL - Core feature not explained in user docs

---

## Score Distribution by Category

| Category | Scenarios | PASS | PARTIAL | FAIL |
|----------|-----------|------|---------|------|
| Discovery & Installation | 1-3 | 1 | 2 | 0 |
| Daily Usage | 4-7 | 2 | 2 | 0 |
| Memory Management | 8-12 | 5 | 0 | 0 |
| Configuration | 13-18 | 5 | 1 | 0 |
| Trust & Verification | 19-21 | 1 | 2 | 0 |
| Troubleshooting | 22-28 | 7 | 0 | 0 |
| Collaboration | 29-31 | 0 | 2 | 1 |
| Privacy & Security | 32-33 | 1 | 0 | 1 |
| Maintenance | 34-37 | 2 | 1 | 1 |
| Scale & Performance | 38-39 | 0 | 1 | 1 |
| Edge Cases | 40-43 | 1 | 3 | 0 |
| Natural Language | 44-46 | 3 | 0 | 0 |
| Runbook Evolution | 47-48 | 0 | 2 | 0 |
| **TOTALS** | **48** | **28** | **15** | **5** |

## Key Observations

1. **Core functionality is well-documented.** The Commands section, Configuration section, and Troubleshooting section cover the daily use cases thoroughly. Memory management (scenarios 8-12) scores 5/5 PASS, and Troubleshooting (22-28) scores 7/7 PASS.

2. **First-time user experience has gaps.** Installation is solid (Scenario 1 PASS), but verification and understanding of auto-capture behavior requires some guesswork (Scenarios 2-3 PARTIAL).

3. **Advanced/edge-case scenarios are weakest.** Collaboration, privacy, upgrade, and performance scenarios are mostly undocumented. These are lower-priority but represent real user needs.

4. **SKILL.md carries too much user-relevant info.** Natural language interactions, auto-update behavior, rolling window, anti-resurrection -- these are all documented in SKILL.md but invisible to users reading README. Some key concepts should be surfaced in README even if briefly.

5. **The documentation improvements (45 gaps fixed) were highly effective.** Comparing the scenario coverage matrix (which showed 75% not documented at all) against current state (58% PASS, 31% PARTIAL, 10% FAIL), the doc improvement work moved the needle significantly.
