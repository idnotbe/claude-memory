# Verification Round 1: Completeness Check

## Summary
- Original gaps: 42
- Gaps verified fixed: 37
- Gaps NOT fixed: 5
- NEW gaps discovered: 6

---

## Gaps NOT Fixed

### GAP-C4: MEMORY-CONSOLIDATION-PROPOSAL.md -- stale architecture not addressed
- **Status**: Not fixed
- **Details**: The changes log does not mention GAP-C4 at all. MEMORY-CONSOLIDATION-PROPOSAL.md still opens with "TRIAGE (6 Sonnet hooks, parallel, extended outputs)" at line 20 and "6 parallel Sonnet hooks evaluate each Stop event" in Section 4.1. No banner or disclaimer was added to indicate this is a historical document superseded by v5.0.0 architecture.
- **Severity**: Critical (wrong/misleading information in an accessible document)
- **Fix**: Add a prominent banner at the top of MEMORY-CONSOLIDATION-PROPOSAL.md: "NOTE: This is a historical design document for ACE v4.2. The v5.0.0 architecture replaced the 6 prompt-type Stop hooks described here with a single deterministic command-type hook (memory_triage.py). See CLAUDE.md for current architecture."

### GAP-M4: Agent-interpreted vs script-read config -- partially fixed
- **Status**: Partially fixed
- **Details**: CLAUDE.md now has a "Config Architecture" subsection (line 51-55) listing both categories. However, the doc-changes-log says the note was "Moved from README to CLAUDE.md only" per vibe-check feedback. The fix is adequate for developers (CLAUDE.md is the dev guide) but there is no breadcrumb in README pointing users to CLAUDE.md for this classification. This is minor -- the original gap asked for documentation "somewhere" and it's now in CLAUDE.md, so I'll count it as fixed with a minor note.
- **Status revised**: Fixed (in CLAUDE.md as intended)

### GAP-M14: Plugin manifest lacks dependency information
- **Status**: Not fixed (intentionally skipped)
- **Details**: The doc-changes-log says "skipped (JSON file, not documentation-only)". plugin.json still has no dependencies, minimum Python version, or compatibility information. The Claude Code plugin manifest format may or may not support these fields.
- **Severity**: Medium (developer inconvenience)

### GAP-L4: No contributor guidelines
- **Status**: Not fixed (deferred)
- **Details**: The doc-changes-log says "GAP-L4 (contributor guidelines) deferred". No CONTRIBUTING.md exists and no contribution section was added to README or CLAUDE.md.
- **Severity**: Low

### GAP-H12: Version/changelog -- only partially fixed
- **Status**: Partially fixed
- **Details**: Version number "v5.0.0" was added to README title and CLAUDE.md title (GAP-L2 + L3). However, the original GAP-H12 asked for a changelog documenting the v4.2 -> v5.0.0 transition. No CHANGELOG.md was created and no "Version History" section exists in README. The doc-changes-log acknowledges this: "full CHANGELOG.md not created (low priority, would be a new file)."
- **Severity**: Medium (users have no way to understand what changed between versions)

---

## NEW Gaps Discovered

### NEW-1: `retrieval.enabled` is missing from memory-config.default.json
- **Location**: `assets/memory-config.default.json` (retrieval section, line 44-47) vs `hooks/scripts/memory_retrieve.py` (line 217)
- **Missing from**: Default config file
- **Details**: `memory_retrieve.py:217` reads `retrieval.get("enabled", True)`, and README documents `retrieval.enabled` as a config option (line 172). However, `memory-config.default.json` only has `"retrieval": { "max_inject": 5, "match_strategy": "title_tags" }` -- the `enabled` key is absent. This is technically correct (defaults to `true` when absent), but the default config should be the canonical reference for all available options.
- **Severity**: Low (behavior is correct due to default, but config file is incomplete as a reference)
- **Fix**: Add `"enabled": true` to the `retrieval` section in `memory-config.default.json`.

### NEW-2: `categories.*.folder` config keys undocumented
- **Location**: `assets/memory-config.default.json` (lines 6, 12, 17, 22, 27, 32) -- each category has a `"folder"` key
- **Missing from**: README config table, CLAUDE.md config architecture section
- **Details**: Every category in the default config has a `"folder"` key (e.g., `"folder": "sessions"`, `"folder": "decisions"`). This key is NOT read by any Python script (scripts use hardcoded CATEGORY_FOLDERS dicts). It's not in the README config table and not categorized in CLAUDE.md's "Agent-interpreted" or "Script-read" lists. It's essentially a config key that exists in the default config but is entirely undocumented.
- **Severity**: Low (the key exists but is unused by scripts and not mentioned in docs)
- **Fix**: Either document it in CLAUDE.md's "Agent-interpreted" list or remove it from the default config if it serves no purpose.

### NEW-3: `triage.parallel.*` config keys missing from CLAUDE.md Config Architecture
- **Location**: CLAUDE.md, "Config Architecture" subsection (lines 53-55)
- **Missing from**: CLAUDE.md "Script-read" list
- **Details**: CLAUDE.md lists script-read keys as: `triage.enabled`, `triage.max_messages`, `triage.thresholds.*`, `triage.parallel.*`, `retrieval.enabled`, `retrieval.max_inject`, `delete.grace_period_days`. Wait -- actually `triage.parallel.*` IS listed via the wildcard. Let me recheck... Yes, confirmed: `triage.parallel.*` is in the "Script-read" list at line 54. This is NOT a gap after all.
- **Status**: WITHDRAWN (false positive on my part)

### NEW-3 (revised): memory_write.py `--action archive` and `--action unarchive` not in CLAUDE.md Key Files table
- **Location**: CLAUDE.md, Key Files table (line 39)
- **Missing from**: CLAUDE.md
- **Details**: The Key Files table describes memory_write.py's role as "Schema-enforced create/update/delete" but it also handles `archive` and `unarchive` actions. The argparse at line 1250-1251 shows `choices=["create", "update", "delete", "archive", "unarchive"]`. The description should say "create/update/delete/archive/unarchive" for completeness.
- **Severity**: Low (actions are documented elsewhere; Key Files table is a summary)
- **Fix**: Update the Role column for memory_write.py to "Schema-enforced CRUD + archive/unarchive"

### NEW-4: README "Hooks" table timeout for Stop hook says 30s but no mention of select() 2s stdin timeout
- **Location**: README.md Hooks table (line 302) vs memory_triage.py `read_stdin(timeout_seconds=2.0)` (line 178)
- **Missing from**: Not a gap per se -- the 30s is the hook-level timeout from hooks.json. The internal 2s stdin read timeout is an implementation detail. However, users troubleshooting slow stops might benefit from knowing the hook timeout is 30s.
- **Severity**: Low (implementation detail, not user-facing)
- **Status**: Not a real gap -- existing documentation is adequate.

### NEW-5: SKILL.md references `categories.<name>.retention_days` but implementation uses `delete.grace_period_days` for GC
- **Location**: SKILL.md Config section (line 254) and default config
- **Missing from**: Clarification of the distinction
- **Details**: SKILL.md lists `categories.<name>.retention_days` as "auto-expire after N days (0 = permanent; 90 for sessions)". The default config has `retention_days: 90` for session_summary. However, NO Python script reads `retention_days`. The GC uses `delete.grace_period_days` (30 days) for retired memories. The relationship between `retention_days` and `grace_period_days` is never explained. Are they different concepts? `retention_days` appears to be an agent-interpreted hint for when to auto-retire, while `grace_period_days` is how long retired files persist before GC deletes them. This distinction is not documented anywhere.
- **Severity**: Medium (config confusion -- users may think retention_days=90 means auto-GC at 90 days)
- **Fix**: Add a clarifying note in SKILL.md or README: "`retention_days` is an agent-interpreted hint for when to consider retiring old entries. `grace_period_days` is the script-enforced delay between retirement and permanent deletion by GC."

### NEW-6: `memory_write.py` supports 5 actions but CLAUDE.md architecture table says "Schema-enforced create/update/delete"
- **Location**: CLAUDE.md, Architecture table (line 19) and Key Files table (line 39)
- **Details**: Both the Architecture Hook Type table (PostToolUse says "schema-validates any memory JSON") and the Key Files table describe memory_write.py as handling "create/update/delete". The script actually handles 5 actions: create, update, delete, archive, unarchive. While archive/unarchive are documented in README and command files, the CLAUDE.md developer guide understates the script's capabilities.
- **Severity**: Low (documented elsewhere, CLAUDE.md is a summary)
- **Fix**: Change "Schema-enforced create/update/delete" to "Schema-enforced CRUD + lifecycle (archive/unarchive)" in the Key Files table.

---

## Config Key Coverage

Every config key from `assets/memory-config.default.json` checked against documentation:

| Config Key | In default config? | Documented? | Where? | Notes |
|---|---|---|---|---|
| `memory_root` | Yes | Yes | CLAUDE.md (agent-interpreted) | |
| `categories.*.enabled` | Yes | Yes | README (line 176), SKILL.md, CLAUDE.md (agent-interpreted) | |
| `categories.*.folder` | Yes | **No** | Not documented anywhere | NEW-2 |
| `categories.*.auto_capture` | Yes | Yes | README (line 177), SKILL.md, CLAUDE.md (agent-interpreted) | |
| `categories.*.retention_days` | Yes | Yes | README (line 178), SKILL.md | Relationship to grace_period unclear (NEW-5) |
| `categories.session_summary.max_retained` | Yes | Yes | README (line 179), SKILL.md | |
| `auto_commit` | Yes | Yes | CLAUDE.md (agent-interpreted) | |
| `max_memories_per_category` | Yes | Yes | README (line 180), SKILL.md, CLAUDE.md (agent-interpreted) | |
| `retrieval.max_inject` | Yes | Yes | README (line 171), SKILL.md, memory-config.md | |
| `retrieval.match_strategy` | Yes | Yes | CLAUDE.md (agent-interpreted) | |
| `retrieval.enabled` | **No** | Yes | README (line 172), memory-config.md | NEW-1: missing from default config |
| `triage.enabled` | Yes | Yes | README (line 173), memory-config.md | |
| `triage.max_messages` | Yes | Yes | README (line 174), memory-config.md | |
| `triage.thresholds.*` | Yes | Yes | README (line 175+189), memory-config.md, SKILL.md | |
| `triage.parallel.enabled` | Yes | Yes | README (line 182), SKILL.md, memory-config.md | |
| `triage.parallel.category_models.*` | Yes | Yes | README (line 183+187), SKILL.md, memory-config.md | |
| `triage.parallel.verification_model` | Yes | Yes | README (line 184), SKILL.md, memory-config.md | |
| `triage.parallel.default_model` | Yes | Yes | README (line 185), SKILL.md, memory-config.md | |
| `delete.grace_period_days` | Yes | Yes | README (line 181), SKILL.md, memory-config.md | |
| `delete.archive_retired` | Yes | Yes | CLAUDE.md (agent-interpreted), SKILL.md | |

**Coverage**: 19/20 config keys documented (95%). 1 key (`categories.*.folder`) undocumented. 1 key (`retrieval.enabled`) documented but missing from default config.

---

## Gap Fix Verification

| Original Gap ID | Status | Notes |
|---|---|---|
| **CRITICAL** | | |
| GAP-C1 | Fixed | CLAUDE.md security item 2 corrected: max_inject clamped to [0,20] |
| GAP-C2 | Fixed | Stale line-number references removed, behavioral descriptions used |
| GAP-C3 | Fixed | TEST-PLAN.md P3.2 rewritten for command hook architecture |
| GAP-C4 | **NOT FIXED** | MEMORY-CONSOLIDATION-PROPOSAL.md still has stale "6 Sonnet hooks" |
| GAP-C5 | Fixed | README JSON example now includes record_status, changes, times_updated |
| **HIGH** | | |
| GAP-H1 | Fixed | README commands table expanded with all 7 subcommands |
| GAP-H2 | Fixed | README has new Memory Lifecycle section with state transitions |
| GAP-H3 | Fixed | README has Prerequisites section with pydantic v2 |
| GAP-H4 | Fixed | README config table expanded from 9 to 15+ options |
| GAP-H5 | Fixed | memory-config.md fully rewritten with all config sections |
| GAP-H6 | Fixed | README has new Troubleshooting section with 6 entries |
| GAP-H7 | Fixed | TEST-PLAN.md has new P1.5 section with 16 triage test cases |
| GAP-H8 | Fixed | commands/memory.md --gc section rewritten, stale fallback removed |
| GAP-H9 | Fixed | "or custom" removed from memory-save.md; note added to memory-config.md |
| GAP-H10 | Fixed | CLAUDE.md security item 1 updated with multi-layer sanitization chain |
| GAP-H11 | Fixed | README Index Maintenance section now includes --health and --gc |
| GAP-H12 | **Partially fixed** | Version number added but no changelog/version history section |
| GAP-H13 | Fixed | README Phase 2 description corrected: "content quality" not "schema compliance" |
| **MEDIUM** | | |
| GAP-M1 | Fixed | README has new Prerequisites section |
| GAP-M2 | Fixed | CLAUDE.md documents $CLAUDE_PLUGIN_ROOT |
| GAP-M3 | Fixed | memory-search.md scoring clarified: index-based only |
| GAP-M4 | Fixed | CLAUDE.md has Config Architecture section with both categories |
| GAP-M5 | Fixed | CLAUDE.md has new Development Workflow section |
| GAP-M6 | Fixed | README documents stop_hook_active flag with TTL explanation |
| GAP-M7 | Fixed | CLAUDE.md documents venv bootstrap mechanism |
| GAP-M8 | Fixed | SKILL.md has Write Pipeline Protections with anti-resurrection |
| GAP-M9 | Fixed | SKILL.md documents merge protections (immutable fields, grow-only tags, etc.) |
| GAP-M10 | Fixed | SKILL.md Phase 0 now explains keyword heuristic scoring |
| GAP-M11 | Fixed | SKILL.md CUD table has implementation note about 2-layer vs 3-layer |
| GAP-M12 | Fixed | README documents OCC in Shared Index subsection |
| GAP-M13 | Fixed | TEST-PLAN.md P1.4 DELETE corrected to "soft retire" |
| GAP-M14 | **NOT FIXED** | plugin.json dependencies not added (intentionally skipped) |
| GAP-M15 | Fixed | All 4 command files have examples |
| GAP-M16 | Fixed | SKILL.md Phase 1 documents context file format |
| **LOW** | | |
| GAP-L1 | Fixed | README has uninstallation instructions |
| GAP-L2 | Fixed | Covered via GAP-H12 (version number in README title) |
| GAP-L3 | Fixed | CLAUDE.md has explicit v5.0.0 version context |
| GAP-L4 | **NOT FIXED** | Contributor guidelines deferred |
| GAP-L5 | Fixed | README references hooks.json in Hooks subsection |
| GAP-L6 | Fixed | README documents atomic writes |
| GAP-L7 | Fixed | TEST-PLAN.md stale ops/temp/ references updated |
| GAP-L8 | Fixed | README has Typical Workflow section |

---

## Summary of Remaining Work

### Must Fix (before declaring documentation complete)
1. **GAP-C4**: Add historical document banner to MEMORY-CONSOLIDATION-PROPOSAL.md
2. **NEW-5**: Clarify `retention_days` vs `grace_period_days` distinction somewhere in docs

### Should Fix (improves quality)
3. **GAP-H12**: Add a brief Version History section to README (even 3-4 lines)
4. **NEW-1**: Add `"enabled": true` to `retrieval` section in default config
5. **NEW-2**: Document or remove `categories.*.folder` from default config
6. **NEW-6**: Update CLAUDE.md Key Files description for memory_write.py to include archive/unarchive

### Nice to Have (low priority)
7. **GAP-M14**: Add dependency info to plugin.json if format supports it
8. **GAP-L4**: Add contributor guidelines if accepting external contributions
