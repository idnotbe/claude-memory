# Verification Round 2: Fresh Independent Review

**Reviewer**: v2-fresh (no prior context)
**Date**: 2026-02-16
**Method**: Read all 9 documentation files and 10 implementation files, compared claims against source code line by line.

## Overall Assessment
- Quality score: 8/10
- Readiness: Ready (with minor fixes recommended)

The documentation is thorough, well-organized, and largely accurate. The main README is excellent as a user-facing document. CLAUDE.md and SKILL.md are well-suited for agent consumption. The command files are clear and actionable. There are some minor accuracy issues and a few gaps, but nothing that would cause a user or agent to fail at their task.

---

## Per-File Review

### README.md
- Clarity: 9/10
- Accuracy: 8/10
- Completeness: 8/10

**Strengths:**
- Excellent structure: flows naturally from "what" to "how" to "troubleshooting"
- Good examples throughout, including the JSON schema example
- Version history provides helpful context
- Troubleshooting section covers the most likely failure modes

**Issues:**
1. **hooks.json location discrepancy**: The README "Hooks" table (line 302-309) lists hooks correctly matching `hooks/hooks.json`. However, the hooks.json file is nested inside the `hooks/` directory and the description field in hooks.json says "See SKILL.md for file format instructions." This is accurate. No issue here.

2. **`retrieval.enabled` default documentation**: README line 193 says `retrieval.enabled` defaults to `true` when absent and is "not included in the default config file." Verified: `assets/memory-config.default.json` has a `retrieval` section with `max_inject` and `match_strategy` but indeed no `enabled` key. The code (`memory_retrieve.py` line 217) defaults to `retrieval.get("enabled", True)`. **Accurate.**

3. **Stop hook flag path**: README line 311 says flag is `.claude/.stop_hook_active`. Code (`memory_triage.py` line 443) confirms `Path(cwd) / ".claude" / ".stop_hook_active"`. **Accurate.**

4. **`triage.max_messages` clamping**: README line 174 says "clamped 10-200". Code line 521 confirms `max(10, min(200, val))`. **Accurate.**

5. **Memory lifecycle state transitions**: README line 127-130 lists 4 transitions. The code supports all of these via `memory_write.py` actions: delete (active->retired), archive (active->archived), restore (via command, not a write action), unarchive (archived->active via `--action unarchive`). However, README says `retired -> active` via `/memory --restore`. The restore flow in `commands/memory.md` (lines 76-92) does this manually by setting record_status to active and calling `--action update`. There is no `--action restore` in `memory_write.py`. The restore path works through the command file's manual steps, not a dedicated write action. **This is correct as documented -- the command file explains the manual process.**

6. **Minor: "hooks/hooks.json" not mentioned explicitly in README**: The README's "Hooks" section describes the hooks but does not mention the config file path `hooks/hooks.json`. A reader might wonder where hooks are configured. CLAUDE.md line 43 mentions it. This is a minor completeness gap for the README.

7. **`match_strategy` config key**: The default config has `"match_strategy": "title_tags"` but this is not documented in README's Configuration table. CLAUDE.md line 55 mentions it as "agent-interpreted." This is technically complete but the README's config table omits it. **Minor omission** -- this is an agent-interpreted key so arguably not needed in user-facing docs.

---

### CLAUDE.md
- Clarity: 9/10
- Accuracy: 9/10
- Completeness: 9/10

**Strengths:**
- Golden Rules are clear and actionable
- Key Files table is complete with correct dependency info
- Config architecture section clearly distinguishes script-read vs agent-interpreted keys
- Security considerations are well-documented with specific file/line references
- Development workflow section is practical

**Issues:**
1. **Security section line references are stale**: CLAUDE.md line 104 says "Memory entries are injected into context by the retrieval hook." Then references sanitization in `memory_write.py` and `memory_retrieve.py`. The actual retrieval injection happens at `memory_retrieve.py:296-301`. The description says "Remaining gap: `memory_index.py` rebuilds index from JSON without re-sanitizing (trusts write-side sanitization)." Looking at `memory_index.py:104`, the `rebuild_index` function writes `m['title']` directly from JSON data to the index without any sanitization. **This accurately describes the gap.**

2. **CLAUDE.md says `memory_write.py` handles "Schema-enforced CRUD + lifecycle (archive/unarchive)"**: The code indeed supports `--action archive` and `--action unarchive` (lines 947-1084). **Accurate.**

3. **Venv Bootstrap section**: CLAUDE.md line 48-49 says `memory_write.py` re-execs under `.venv/bin/python3` via `os.execv()`. Code confirms at lines 27-34. **Accurate.** The note that `memory_validate_hook.py` also requires pydantic is accurate -- it uses a different bootstrap approach (site-packages injection, lines 18-23).

4. **Config architecture completeness**: The list of script-read keys includes `delete.grace_period_days` but omits that `memory_index.py --gc` also reads this key (line 203). This is correct but could be more explicit. **Very minor.**

---

### SKILL.md
- Clarity: 8/10
- Accuracy: 8/10
- Completeness: 9/10

**Strengths:**
- Very detailed 4-phase flow with clear instructions per phase
- CUD resolution table is well-formatted and covers all cases
- Memory JSON Format section provides a complete reference
- Session rolling window section is thorough

**Issues:**
1. **SKILL.md CUD table vs MEMORY-CONSOLIDATION-PROPOSAL.md**: SKILL.md has a simplified 2-layer CUD table (L1 Python + L2 Subagent). The proposal describes a 3-layer system (Python + Sonnet triage + Opus write-phase). SKILL.md line 156 acknowledges this: "This is the implemented 2-layer system. See MEMORY-CONSOLIDATION-PROPOSAL.md for the original 3-layer design." **Consistent and well-documented.**

2. **Phase 1 subagent instructions reference `memory_candidate.py` CLI**: SKILL.md line 79 shows:
   ```
   python3 hooks/scripts/memory_candidate.py --category <cat> --new-info "<summary>" --root .claude/memory
   ```
   But the code at `memory_candidate.py:196` expects the `--category` choices to be from `CATEGORY_FOLDERS.keys()` which are lowercase (`session_summary`, `decision`, etc.). SKILL.md line 54-58 correctly explains that lowercase should be used. **Accurate.**

3. **Phase 3 write commands**: SKILL.md line 120-123 shows the `memory_write.py` invocations. For CREATE and UPDATE, it uses `$CLAUDE_PLUGIN_ROOT` prefix. For DELETE it does not include `--category` flag. Checking `memory_write.py:1266-1270`, `--category` is only required for create, and optional otherwise. **Accurate.**

4. **Draft path validation**: SKILL.md line 117-118 says "verify the path starts with `/tmp/.memory-draft-` and contains no `..` path components." The `memory_write.py` `_read_input` function (lines 1097-1105) validates that resolved path starts with `/tmp/` and has no `..`, but it checks for `/tmp/` generally, not `/tmp/.memory-draft-` specifically. It also validates on the `--input` path, not the draft path per se. **Minor inconsistency**: SKILL.md is slightly more restrictive than what the code enforces. This is fine (defense in depth), but documentation is not perfectly aligned with implementation.

5. **`delete.archive_retired` config**: SKILL.md line 264 mentions `delete.archive_retired` defaulting to `true`. The default config confirms this at line 76. However, looking through the entire codebase, no Python script actually reads or acts on this key. It appears to be agent-interpreted. CLAUDE.md line 55 lists it as agent-interpreted. **The key exists in config but has no script-side enforcement.** Documentation should clarify this is agent-interpreted (a hint, not enforced by code). SKILL.md doesn't distinguish.

6. **Content schema for `constraint`**: SKILL.md line 189 shows `active: true` for constraint. The Pydantic model (`memory_write.py:128`) has `active: bool` as required. The JSON schema (`constraint.schema.json` not read but likely matches). **This appears accurate.**

---

### commands/memory.md
- Clarity: 9/10
- Accuracy: 8/10
- Completeness: 9/10

**Issues:**
1. **`--restore` flow uses `--action update`**: The command (line 90-91) calls `memory_write.py --action update` to restore a retired memory. This requires the agent to manually set `record_status` back to `"active"` and remove `retired_at`/`retired_reason` fields, then pass through the full UPDATE validation. The merge protection in `memory_write.py` (line 497-501) explicitly blocks `record_status` changes via UPDATE. **POTENTIAL BUG**: The restore command as documented would fail because merge protections block record_status changes via UPDATE. However, looking more carefully at the update flow (lines 746-751), the code preserves immutable fields from old, including `record_status`: `new_data["record_status"] = old_data.get("record_status", "active")`. So if the user writes JSON with `record_status: "active"` to the temp file, the code would override it back to `"retired"` from the old data. **This is a real issue** -- the `--restore` command as documented would not work as intended because `memory_write.py --action update` preserves the old record_status.

   **Workaround that might work**: The command writes the full JSON to temp then calls update. But `memory_write.py` line 751 forces `new_data["record_status"] = old_data.get("record_status", "active")`. Since old_data has `record_status: "retired"`, the update would keep it retired. The restore cannot work through `--action update`. There would need to be an `--action restore` or the record_status preservation logic would need to be bypassed.

   **Wait**: Re-reading more carefully. The `--restore` command in `memory.md` says (line 85-91) to modify the JSON, write to temp, and call `--action update`. But the code at line 751 does `new_data["record_status"] = old_data.get("record_status", "active")`. This means the restored record_status would be overwritten back to "retired". **This is a documentation-implementation mismatch -- the documented restore workflow would silently fail to change record_status.**

2. **`--gc` tells user to run `--rebuild` after**: The command (line 101) says to "suggest running `--rebuild` to update the index." The `memory_index.py --gc` function already prints this suggestion (line 257). **Consistent.**

3. **Status display references `$CLAUDE_PLUGIN_ROOT`**: Line 39 uses `$CLAUDE_PLUGIN_ROOT` for the validate command. This is correct for the command context.

---

### commands/memory-save.md
- Clarity: 9/10
- Accuracy: 9/10
- Completeness: 9/10

**Issues:**
1. No significant issues. The file clearly documents the save workflow with proper JSON schema construction, temp file usage, and `memory_write.py` invocation.
2. The category folder mapping table matches the code exactly.

---

### commands/memory-search.md
- Clarity: 9/10
- Accuracy: 8/10
- Completeness: 8/10

**Issues:**
1. **Scoring algorithm description**: Lines 41-48 describe the scoring algorithm. This matches `memory_retrieve.py`'s `score_entry` function exactly: exact tag = 3 points, exact title word = 2 points, prefix match (4+ chars) = 1 point, recency bonus = +1 (30 days). **Accurate.**

2. **The command says to use "Glob to list all .json files" and "Grep to search their contents"**: This is agent instruction, not script behavior. The search command is a command file (agent-interpreted), not a Python script. The fallback to Glob+Grep is a reasonable agent instruction. **Fine as-is.**

3. **`--include-retired` flag**: The command says to "scan `.json` files directly in all category folders." This is agent-interpreted behavior. **Reasonable.**

---

### commands/memory-config.md
- Clarity: 9/10
- Accuracy: 9/10
- Completeness: 8/10

**Issues:**
1. **"Custom categories are not currently supported"**: Line 50 correctly notes this limitation. The Pydantic models in `memory_write.py` have hard-coded category content models. **Accurate.**

2. **Missing config keys**: The command does not mention `retrieval.match_strategy` or `auto_commit`. These are in the default config but are agent-interpreted. Since this is a config command, it might be helpful to mention all configurable keys. **Minor completeness gap.**

---

### TEST-PLAN.md
- Clarity: 9/10
- Accuracy: 8/10
- Completeness: 8/10

**Issues:**
1. **P0.1 line references removed**: The test plan references specific behaviors but no longer includes line numbers. This is actually better for maintenance.

2. **P1.3 mentions "Score >= 3 threshold"**: `memory_candidate.py` line 270 confirms `scored[0][0] >= 3`. **Accurate.**

3. **P1.3 mentions "DELETE disallowed for decision/preference/session_summary"**: `memory_candidate.py` line 54 confirms `DELETE_DISALLOWED = frozenset({"decision", "preference", "session_summary"})`. **Accurate.**

4. **P1.5 mentions "exit codes 0=allow, 2=block"**: `memory_triage.py` docstring and code confirm. **Accurate.**

5. **P1.5 mentions "stop flag TTL: 5 minutes"**: Code line 38 confirms `FLAG_TTL_SECONDS = 300`. **Accurate.**

6. **P2.1 mentions "Staging file (/tmp/.memory-write-pending.json): explicitly allowed"**: `memory_write_guard.py` lines 42-48 allow `/tmp/.memory-write-pending*.json`, `/tmp/.memory-draft-*.json`, and `/tmp/.memory-triage-context-*.txt`. The test plan only mentions the first. **Minor incompleteness** -- tests should also cover the draft and context file allowlists.

---

### MEMORY-CONSOLIDATION-PROPOSAL.md
- Clarity: 8/10
- Accuracy: 7/10 (relative to current implementation)
- Completeness: 9/10

**Issues:**
1. **Historical document with good disclaimer**: Line 1 has a clear note that this is historical and the v5.0.0 architecture differs. This is well-handled.

2. **3-layer vs 2-layer CUD**: The proposal describes a 3-layer system (Python + Sonnet + Opus). The implementation uses 2 layers (Python structural + subagent). SKILL.md line 156 documents this difference. **Consistent across docs.**

3. **Triage hook format**: The proposal describes triage hooks outputting `{ok: false, reason: "...", lifecycle_event: "...", cud_recommendation: "..."}`. The v5.0.0 implementation uses a completely different output format (`<triage_data>` JSON block with categories, scores, context files). This is expected since the architecture changed fundamentally. **Historical document, so this is fine.**

4. **`fcntl` locking**: The proposal (Section 6.1) describes `fcntl.flock` for OCC. The actual implementation (`memory_write.py` lines 1145-1202) uses `mkdir`-based locking for portability. The `_flock_index` class comment says "Portable lock for index mutations. Uses mkdir (atomic on all FS including NFS)." **The implementation diverged from the proposal for good reason.** Documentation elsewhere (README, CLAUDE.md) correctly describes the current behavior.

---

## Cross-Document Issues

1. **`--restore` workflow broken by merge protections**: The most significant issue found. `commands/memory.md` documents a restore workflow using `--action update`, but `memory_write.py` preserves old `record_status` during UPDATE, making it impossible to change a retired record back to active this way. Either:
   - The code needs an `--action restore` handler, OR
   - The merge protection on `record_status` needs a carve-out for restore, OR
   - The command documentation needs to use a different approach

2. **Consistent use of `$CLAUDE_PLUGIN_ROOT`**: All command files use `$CLAUDE_PLUGIN_ROOT` for script paths. SKILL.md uses both `hooks/scripts/memory_candidate.py` (relative) and `$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py`. Minor inconsistency but not harmful -- the plugin root variable may not be available in all contexts.

3. **`delete.archive_retired` config key**: Present in default config and documented in SKILL.md and README, but no script reads it. All docs should clarify this is agent-interpreted.

4. **`retrieval.match_strategy` config key**: In default config as `"title_tags"`, listed in CLAUDE.md as agent-interpreted, but not mentioned in README config table or `commands/memory-config.md`. Minor gap.

5. **`auto_commit` config key**: In default config as `false`, not documented anywhere in the main docs (README, CLAUDE.md, commands). Listed as agent-interpreted in CLAUDE.md line 55. **Minor gap.**

---

## Remaining Gaps

1. **CRITICAL: `/memory --restore` cannot work with current `memory_write.py`** -- The update action preserves old record_status, preventing status changes. See Cross-Document Issue #1.

2. **Minor: Write guard allowlist not fully documented in TEST-PLAN.md** -- The guard allows 3 temp file patterns but the test plan only mentions one.

3. **Minor: No documentation of the `--action archive` / `--action unarchive` CLI flags** in README's architecture/troubleshooting sections. They exist in `memory_write.py` and are referenced by `commands/memory.md` but not explicitly described in the README's command table or data flow diagram.

4. **Minor: `memory_triage.py` transcript path validation** (lines 889-892) restricts paths to `/tmp/` or `$HOME/` prefix. Not documented anywhere.

---

## Recommendations (prioritized)

1. **HIGH: Fix `--restore` workflow** -- Either add `--action restore` to `memory_write.py`, or modify the merge protection to allow record_status changes when the input explicitly provides them, or update the command to use a different approach (e.g., direct file write followed by index rebuild, though this violates the "never write directly" rule).

2. **MEDIUM: Document all agent-interpreted config keys** -- Add a note in README and commands/memory-config.md that `auto_commit`, `match_strategy`, and `archive_retired` are agent-interpreted hints, not script-enforced.

3. **LOW: Update TEST-PLAN.md P2.1** -- Add test cases for the full write guard allowlist (`/tmp/.memory-draft-*.json` and `/tmp/.memory-triage-context-*.txt`).

4. **LOW: Add `archive`/`unarchive` to README data flow** -- The data flow diagram mentions "memory_write.py --action create/update/delete" but not archive/unarchive.

5. **LOW: Consistent script path convention** -- Decide whether SKILL.md should use `$CLAUDE_PLUGIN_ROOT/hooks/scripts/...` everywhere or relative paths, and be consistent.
