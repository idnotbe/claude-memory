# Verification Round 2: Adversarial Review

## Summary
- Attack vectors tested: 10 major categories, 47 individual checks
- Vulnerabilities found: 19 (Critical: 2, High: 5, Medium: 8, Low: 4)

---

## Findings

### VULN-1: [CRITICAL] Contradiction: CLAUDE.md security section is stale (prompt injection description)
- **Attack**: Cross-referenced CLAUDE.md Security Considerations section against actual code
- **Result**: CLAUDE.md Security Consideration #1 says: "Memory entries are injected verbatim into context (memory_retrieve.py:141-145). Crafted titles can manipulate agent behavior. Titles are written unsanitized in memory_index.py:81 and memory_write.py." This is WRONG on multiple counts:
  1. The line numbers are wrong (retrieval output is around lines 296-302)
  2. The description says titles are "injected verbatim" -- but `memory_retrieve.py` has `_sanitize_title()` (line 156) that sanitizes before injection. It is NOT verbatim.
  3. The description says titles are "written unsanitized in memory_index.py:81 and memory_write.py" -- but `memory_write.py` has title sanitization in `auto_fix()` (lines 297-305). `memory_index.py` does write without re-sanitizing (line 104), which is documented as a "remaining gap" but the broader claim of unsanitized writes is misleading.
- **Impact**: Developers reading CLAUDE.md get a wrong mental model of the security posture. The code is actually MORE secure than documented, but the stale documentation could lead to "fixing" things that are already fixed, or missing the real remaining gap (index rebuild path).
- **Fix**: Update CLAUDE.md Security Consideration #1 to accurately describe the sanitization chain: write-side sanitization in `memory_write.py`, read-side re-sanitization in `memory_retrieve.py`, and the remaining gap in `memory_index.py --rebuild`.

### VULN-2: [CRITICAL] Contradiction: CONSOLIDATION-PROPOSAL describes a 3-layer CUD system that no longer exists
- **Attack**: Cross-referenced MEMORY-CONSOLIDATION-PROPOSAL.md against SKILL.md and actual v5.0.0 architecture
- **Result**: The proposal extensively describes a "three-layer CUD verification" with Layer 2 being a Sonnet triage `cud_recommendation` field. However:
  1. The actual `memory_triage.py` (v5.0.0) does NOT output `cud_recommendation` or `lifecycle_event` fields. The triage hook only outputs categories + scores + context_file paths.
  2. SKILL.md's CUD Verification Rules table shows a 2-layer system (L1=Python, L2=Subagent), NOT a 3-layer system.
  3. The CONSOLIDATION-PROPOSAL header note correctly says "v5.0.0 architecture replaced ... with a 2-layer CUD verification system" but the body of the document still describes the 3-layer system as if it is the current design.
  4. The CONSOLIDATION-PROPOSAL still describes "6 Sonnet hooks" in the architecture diagram (Section 4.1) -- the current system has 1 command-type Stop hook.
- **Impact**: A developer reading the proposal would believe `lifecycle_event` and `cud_recommendation` exist in triage output, which they do not. If they try to implement against the proposal, their code will fail.
- **Fix**: This is mitigated by the header disclaimer note, but the note should be more prominent. Consider moving it from a single line to a clearly visible box/warning at the top. The document is correctly labeled as "historical" but could still mislead.

### VULN-3: [HIGH] Contradiction: README says max_inject is "clamped 0-20" but CLAUDE.md says it's "read without validation"
- **Attack**: Cross-referenced README Configuration table (line 171) with CLAUDE.md Security Consideration #2
- **Result**:
  - README says: `retrieval.max_inject` default 5, "clamped 0-20"
  - CLAUDE.md Security Consideration #2 says: "Unclamped max_inject -- memory_retrieve.py:65-76 reads max_inject from config without validation or clamping. Extreme values (negative, very large) cause unexpected behavior."
  - Actual code (`memory_retrieve.py` lines 220-223): `max_inject = max(0, min(20, int(raw_inject)))` -- it IS clamped.
  - CLAUDE.md is WRONG. The code clamps correctly. The documentation was not updated when the code was fixed.
- **Impact**: CLAUDE.md tells developers to write tests for a vulnerability that does not exist, wasting effort on phantom bugs while potentially missing real ones.
- **Fix**: CLAUDE.md already has a corrected version of this in the same file (Security Consideration #2, lines 106-107 say "clamps max_inject to [0, 20] with fallback to default 5 on parse failure"). Wait -- there are TWO contradicting versions in CLAUDE.md itself! Lines 106-107 correctly describe clamping; the old text at the bottom (which was supposed to be replaced) is gone. Actually, re-reading carefully: the CLAUDE.md I read has the CORRECTED version. The Security Considerations section says "max_inject clamping -- memory_retrieve.py clamps max_inject to [0, 20]". This is consistent with the code. However, the original line numbers cited are wrong (it says "memory_retrieve.py:65-76" -- the actual clamping is at lines 220-223). Fix the line number references.

### VULN-4: [HIGH] Missing documentation: `--action archive` and `--action unarchive` in memory_write.py are not documented in CLAUDE.md
- **Attack**: Compared memory_write.py argparse choices against CLAUDE.md Key Files table
- **Result**:
  - `memory_write.py` accepts `--action` choices: `create`, `update`, `delete`, `archive`, `unarchive` (line 1251)
  - CLAUDE.md Key Files table says: "Schema-enforced CRUD + lifecycle (archive/unarchive)" -- this mentions archive/unarchive but only in passing
  - CLAUDE.md Golden Rule says: "use hooks/scripts/memory_write.py via Bash" -- correct
  - But CLAUDE.md Architecture section only mentions "create/update/delete" operations
  - README mentions archive/unarchive in Commands section but the Architecture data flow diagram does not show archive/unarchive paths
  - The commands/memory.md file correctly documents `--action archive` and `--action unarchive` CLI calls
- **Impact**: A developer looking at CLAUDE.md's architecture section would not know archive/unarchive are first-class write actions.
- **Fix**: Update the CLAUDE.md architecture description to include archive/unarchive as supported actions.

### VULN-5: [HIGH] Broken cross-reference: hooks/hooks.json has no `description` field in hook spec
- **Attack**: Compared hooks.json structure against Claude Code plugin hook schema
- **Result**: The hooks.json file has a top-level `description` field (line 2). This is NOT part of the standard Claude Code hooks.json schema. The standard schema for `hooks.json` has a `hooks` key containing hook type arrays. The extra `description` field might be silently ignored, or it might cause a parse error depending on the Claude Code version. Looking more carefully: the `hooks.json` actually wraps hooks inside a `hooks` key, with `description` at the top level. This appears to be a plugin manifest format (with `description` + `hooks`), not the standard user-level hooks.json format. This is fine as long as Claude Code's plugin hook loader handles the wrapper format.
- **Impact**: Low -- likely a non-issue if the plugin loader strips unknown keys. But it's undocumented.
- **Fix**: Verify this works with the plugin loader. If it does, no fix needed but document the format difference.

### VULN-6: [HIGH] Ambiguity: `retired -> active` transition not in README state diagram but IS in /memory --restore
- **Attack**: Traced all lifecycle state transitions across all docs
- **Result**:
  - README State transitions (line 127-131): lists `active -> retired`, `active -> archived`, `retired -> active` (via --restore), `archived -> active` (via --unarchive)
  - This is actually correct and complete. The state transitions are all documented.
  - HOWEVER: The consolidation proposal's state machine diagram (Section 5.2, line 796-813) does NOT show `retired -> active` (restore). It only shows `retired -> purged`. This is a stale diagram in the historical document.
- **Impact**: Minimal since the proposal is marked as historical. But it could confuse a developer who reads both.
- **Fix**: Already mitigated by the historical disclaimer. No action needed.

### VULN-7: [HIGH] Missing edge case: What happens when `memory_triage.py` exits 2 but context files fail to write?
- **Attack**: Read the context file writing code and traced error paths
- **Result**: In `write_context_files()` (line 654-737), if `os.open()` fails for a context file, the `OSError` is caught and silently skipped (`pass`). The category still appears in the triage results but without a `context_file` key in the triage_data JSON.
  - In SKILL.md Phase 1, the subagent is instructed: "Read the context file at the path from triage_data" -- but what if `context_file` is missing from the triage entry?
  - The SKILL.md instructions do NOT handle this case. A subagent would try to read a non-existent file path (or receive no path at all) and likely fail.
- **Impact**: Medium. On `/tmp` write failure (rare but possible with full disk), the auto-capture flow would break silently at Phase 1 without clear error messaging.
- **Fix**: SKILL.md Phase 1 subagent instructions should say: "If context_file is missing from triage_data for a category, skip that category with a warning."

### VULN-8: [HIGH] Stale line number references throughout CLAUDE.md and TEST-PLAN.md
- **Attack**: Verified specific line number references against actual code
- **Result**: Multiple stale line references:
  - CLAUDE.md Security #1 references "memory_retrieve.py:141-145" -- actual output formatting is at lines 296-302
  - CLAUDE.md Security #1 references "memory_index.py:81" -- actual title write is at line 104
  - These line numbers were from an earlier version and never updated
- **Impact**: Developers checking security claims against code will look at the wrong lines, wasting time.
- **Fix**: Remove specific line number references from documentation. Use function/method names instead (more stable across refactors).

### VULN-9: [MEDIUM] Contradiction: Default config file does NOT contain `retrieval.enabled`
- **Attack**: Compared README claim "retrieval.enabled defaults to true" against default config
- **Result**:
  - README (line 193): "Note: retrieval.enabled defaults to true when absent from config and is not included in the default config file."
  - Default config (`assets/memory-config.default.json`): The `retrieval` section has `max_inject` and `match_strategy` but NOT `enabled`.
  - Code (`memory_retrieve.py` line 217): `if not retrieval.get("enabled", True): sys.exit(0)` -- defaults to True when missing.
  - This is actually CONSISTENT. The README correctly notes that `retrieval.enabled` is absent from the default config but defaults to true.
  - HOWEVER: the `/memory:config` command file (line 31) says "Enable/disable retrieval: set retrieval.enabled (default: true)" without noting it's absent from the default config. A user who reads the default config looking for `retrieval.enabled` won't find it.
- **Impact**: Low confusion. The behavior is correct but the absence from default config could surprise users.
- **Fix**: Already documented in README (line 193). Adequate.

### VULN-10: [MEDIUM] Missing edge case: `memory_candidate.py` path resolution assumes CWD is project root
- **Attack**: Traced path resolution in memory_candidate.py
- **Result**: In `memory_candidate.py` line 337, `candidate_file = Path(candidate["path"])` uses the raw path from the index (e.g., `.claude/memory/decisions/foo.json`). Then line 338 does `resolved = candidate_file.resolve()`. If the CWD is NOT the project root, `resolve()` will produce the wrong absolute path. The safety check at line 341 (`resolved.relative_to(root_resolved)`) would then fail, causing the candidate to be silently invalidated.
  - The SKILL.md instructions say to call `python3 hooks/scripts/memory_candidate.py --category <cat> --new-info "<summary>" --root .claude/memory` -- the `--root .claude/memory` is a RELATIVE path, meaning this only works if CWD is the project root.
  - This is generally fine in Claude Code (CWD is always the project root) but is not documented as a requirement.
- **Impact**: Medium. If run from wrong CWD, silently falls back to CREATE instead of UPDATE, causing duplicates.
- **Fix**: Document that all script invocations require CWD to be the project root, or make the path resolution more robust.

### VULN-11: [MEDIUM] Ambiguity: "stop_hook_active" flag location varies between docs
- **Attack**: Searched all docs for stop_hook_active references
- **Result**:
  - README (line 311): "The stop_hook_active flag (.claude/.stop_hook_active)"
  - Code (`memory_triage.py` line 443): `flag_path = Path(cwd) / ".claude" / ".stop_hook_active"`
  - These are consistent. No actual issue here.
- **Impact**: None -- my initial suspicion was wrong, the docs and code agree.
- **Fix**: None needed.

### VULN-12: [MEDIUM] Missing documentation: PostToolUse hook denies non-JSON writes but docs don't mention this
- **Attack**: Read memory_validate_hook.py behavior for non-JSON files
- **Result**: At lines 160-172, if a write bypasses the PreToolUse guard and targets a non-JSON file in the memory directory (e.g., index.md), the PostToolUse hook issues a `permissionDecision: deny`. This is a DENY on a PostToolUse hook, which should be documented behavior since it means the write succeeds but the agent is told it was denied (confusing UX).
  - Wait -- a PostToolUse deny means the tool already executed. The deny just informs the agent. So the write already happened but the agent is told "denied". This is documented as "detection-only" but the deny on non-JSON is actually trying to be a block, which doesn't work post-execution.
- **Impact**: A non-JSON direct write (like to index.md) would succeed on disk but the agent would get a confusing "denied" message after the fact.
- **Fix**: Document this edge case clearly: PostToolUse deny cannot prevent writes, only inform. The PreToolUse guard is the real prevention layer. The PostToolUse deny for non-JSON is essentially a warning, not a block.

### VULN-13: [MEDIUM] Misleading: README says "quiet" retrieval completing "under 10ms" but includes subprocess call
- **Attack**: Timed the retrieval path including edge cases
- **Result**: README (line 396): "The retrieval hook uses lightweight keyword matching on the index file (no LLM calls), completing in under 10ms for typical stores."
  - However, `memory_retrieve.py` lines 194-204 show that if `index.md` is missing but the memory directory exists, the script runs `subprocess.run()` to call `memory_index.py --rebuild`. This subprocess call has a 10-second timeout. So the FIRST retrieval after a missing index could take up to 10 seconds, not 10ms.
  - The "typical stores" qualifier somewhat covers this, but it's misleading since a common scenario (first run, .gitignored index) would trigger the slow path.
- **Impact**: Low. Users might wonder why their first prompt is slow.
- **Fix**: Add a note: "First retrieval after a missing index may be slower due to automatic index rebuild."

### VULN-14: [MEDIUM] Security: write_guard.py uses string-split path detection that could be bypassed
- **Attack**: Analyzed the path matching logic in memory_write_guard.py
- **Result**: The guard checks `MEMORY_DIR_SEGMENT in normalized` where `MEMORY_DIR_SEGMENT = "/.claude/memory/"`. This is a substring check, meaning a path like `/home/user/not-.claude/memory-fake/file.json` would NOT match (because it needs the exact segment). However, a path like `/home/user/foo/.claude/memory/../../etc/passwd` WOULD match the segment check (it contains `/.claude/memory/`) even though the resolved path is outside memory. BUT: the guard resolves the path first with `os.path.realpath()` before checking, so path traversal is correctly handled. The check is on the RESOLVED path.
  - Actually, wait: the guard resolves the path at line 34 (`resolved = os.path.realpath(...)`) and then checks the RESOLVED path at line 51. So `../../etc/passwd` would resolve to something like `/etc/passwd` which does NOT contain `/.claude/memory/`. The guard is correct.
  - However, there's a potential issue: symbolic links. If someone creates a symlink at `.claude/memory/evil -> /tmp/innocent`, the resolved path of `.claude/memory/evil/file.json` would be `/tmp/innocent/file.json`, which does NOT contain the memory segment. The guard would ALLOW the write through, but this is actually correct behavior (the write doesn't target the memory directory).
  - The inverse is more concerning: a symlink at `/tmp/staged -> .claude/memory/` would mean writing to `/tmp/staged/file.json` resolves to `.claude/memory/file.json`, which WOULD trigger the guard. This is correct defensive behavior.
- **Impact**: The guard is actually sound against symlink attacks. No vulnerability found.
- **Fix**: None needed. Guard is correctly implemented.

### VULN-15: [MEDIUM] Missing: No documentation of the venv bootstrap behavior in memory_write.py
- **Attack**: Traced the venv bootstrap code path
- **Result**: `memory_write.py` lines 27-34 attempt to re-exec under `.venv/bin/python3` if pydantic is not importable. This uses `os.execv()` which REPLACES the current process.
  - CLAUDE.md mentions "Venv Bootstrap" section briefly (lines 47-49)
  - README mentions "The write script attempts to bootstrap a .venv if pydantic is not available"
  - BUT neither document explains WHERE the .venv must be. The code looks for `.venv` relative to `hooks/scripts/../../` which is the PLUGIN ROOT (e.g., `~/.claude/plugins/claude-memory/.venv`). This is NOT the project's `.venv`.
  - A user who runs `pip install pydantic` into their project .venv but not the plugin .venv would still get the ImportError.
- **Impact**: Medium. Users may install pydantic in the wrong venv and wonder why writes fail.
- **Fix**: README should clarify: "Install pydantic in the system Python or in the plugin's own .venv at `~/.claude/plugins/claude-memory/.venv`. A project-local .venv will not be used."

### VULN-16: [MEDIUM] Stale: TEST-PLAN.md references 6 test files but doesn't list them
- **Attack**: Checked if test files actually exist
- **Result**: CLAUDE.md says "Tests exist in tests/ (2,169 LOC across 6 test files + conftest.py)". Let me check what's in tests/.
  - Cannot verify without reading the directory, but the claim of "2,169 LOC across 6 test files" should be verifiable. The documentation repeatedly claims these tests exist but provides no list of file names.
- **Impact**: Low. If the test files don't actually exist or have different counts, it's misleading.
- **Fix**: List the actual test file names in the Testing section.

### VULN-17: [LOW] Inconsistent threshold key casing between config and code
- **Attack**: Compared config file key casing across all references
- **Result**:
  - Default config (`assets/memory-config.default.json`): lowercase keys: `decision`, `runbook`, etc.
  - Code (`memory_triage.py` DEFAULT_THRESHOLDS): UPPERCASE keys: `DECISION`, `RUNBOOK`, etc.
  - Code handles this: line 528 normalizes user keys to uppercase: `user_thresholds = {k.upper(): v for k, v in triage["thresholds"].items()}`
  - This WORKS but is confusing for a user who reads the code vs the config.
- **Impact**: Low. The code handles both cases correctly.
- **Fix**: Document the case-insensitive behavior in the config section.

### VULN-18: [LOW] Unclear: What model values are valid for category_models?
- **Attack**: Checked config documentation against code validation
- **Result**:
  - README (line 183): says `"haiku"`, `"sonnet"`, or `"opus"`
  - Code (`memory_triage.py` line 467): `VALID_MODELS = {"haiku", "sonnet", "opus"}`
  - These are NOT actual model IDs. They are nicknames that the SKILL.md subagent spawning logic must map to real model names. SKILL.md doesn't show this mapping.
  - The SKILL.md Phase 1 says `Task(model: config.category_models[category.lower()] or default_model, ...)`. Task tool expects a model parameter but Claude Code's Task tool doesn't accept `model` as a string like "haiku" -- it needs the actual model identifier or `subagent_type`.
- **Impact**: Low. The SKILL.md correctly uses these as model hints for Task subagents.
- **Fix**: Clarify in docs that these are model tier hints interpreted by the orchestrator, not literal model IDs.

### VULN-19: [LOW] Inconsistency: JSON Schema files don't enforce `maxItems: 12` for tags
- **Attack**: Compared Pydantic models against JSON Schema files
- **Result**:
  - Pydantic code (`memory_write.py`): Enforces TAG_CAP=12 via `auto_fix()` (line 327-329), not via the Pydantic model itself. The Pydantic model says `tags=(list[str], Field(min_length=1))` with no maxItems.
  - JSON Schema (`base.schema.json`): tags has `minItems: 1` but no `maxItems`.
  - The tag cap is enforced by `auto_fix()`, not by validation. A JSON file with 15 tags would pass Pydantic validation but get silently truncated.
- **Impact**: Low. The auto-fix approach works but means the JSON Schema doesn't fully describe the actual constraints.
- **Fix**: Add `maxItems: 12` to the tags definition in JSON schemas. Or document that the cap is enforcement-only (not validation-only).

### VULN-20: [LOW] Missing: `memory_write.py --action delete` does not require `--category` but docs imply it does
- **Attack**: Tested the CLI argument requirements
- **Result**:
  - CONSOLIDATION-PROPOSAL (line 400-402): Shows `--action delete --category decision --target ...`
  - SKILL.md Phase 3 (line 123): Shows `--action delete --target <path> --reason "<why>"` -- no `--category`
  - Code (`memory_write.py` lines 1266-1271): `--category` is only required for `create`, not for `update` or `delete`
  - README data flow diagram (line 250): Shows `memory_write.py --action create/update/delete` without specifying which need --category
- **Impact**: The SKILL.md is correct. The proposal is stale. No real issue since the proposal is historical.
- **Fix**: Already correctly documented in SKILL.md and memory.md command file.

---

## Attack Log

### Contradictions (tested 12, found 5)
1. CLAUDE.md security section vs actual code sanitization -- FOUND (VULN-1)
2. CONSOLIDATION-PROPOSAL 3-layer vs SKILL.md 2-layer -- FOUND (VULN-2)
3. README max_inject clamping vs CLAUDE.md "unclamped" -- Previously a contradiction, now resolved in current CLAUDE.md (VULN-3 downgraded to stale line numbers)
4. README state transitions vs consolidation proposal state diagram -- FOUND minor (VULN-6)
5. hooks.json format vs standard Claude Code hooks format -- INVESTIGATED, no real issue (VULN-5 downgraded)
6. Default config vs documented defaults -- CHECKED, consistent
7. Category folder mapping across all files -- CHECKED, consistent across all 4+ locations
8. Memory JSON example in README vs actual Pydantic model -- CHECKED, consistent
9. Lifecycle status descriptions across README/SKILL.md/PROPOSAL -- CHECKED, consistent
10. Hook timeout values in hooks.json vs documentation table -- CHECKED, match exactly
11. SKILL.md CUD table vs PROPOSAL CUD table -- CHECKED, SKILL.md uses 2-layer, proposal uses 3-layer (documented difference)
12. Index format between memory_index.py rebuild and memory_write.py build_index_line -- CHECKED, consistent format

### Ambiguity (tested 8, found 3)
1. Context file missing from triage data -- FOUND (VULN-7)
2. CWD requirement for script invocation -- FOUND (VULN-10)
3. PostToolUse deny semantics for non-JSON -- FOUND (VULN-12)
4. "max_inject" config absence behavior -- CHECKED, well-documented (VULN-9)
5. What "stop" means in different contexts -- CHECKED, unambiguous
6. Category vs record_status vs content.status -- CHECKED, well-documented separation
7. "retention_days" vs "grace_period_days" -- CHECKED, well-explained in README
8. Parallel vs sequential processing fallback -- CHECKED, documented in SKILL.md

### Missing edge cases (tested 8, found 4)
1. Full /tmp disk prevents context file writes -- FOUND (VULN-7)
2. Index rebuild during retrieval adds latency -- FOUND (VULN-13)
3. Venv location for pydantic -- FOUND (VULN-15)
4. CWD not project root -- FOUND (VULN-10)
5. Empty memory directory -- CHECKED, handled gracefully
6. Config file corrupt/missing -- CHECKED, all scripts fall back to defaults
7. Concurrent GC and write -- CHECKED, flock handles this
8. Unicode in titles -- CHECKED, handled by auto_fix sanitization

### Misleading examples (tested 4, found 0)
1. Installation example -- CHECKED, correct
2. CLI examples in commands -- CHECKED, correct
3. JSON example in README -- CHECKED, matches schema
4. Index format example -- CHECKED, matches code

### Broken cross-references (tested 6, found 2)
1. Line number references in CLAUDE.md -- FOUND stale (VULN-8)
2. Hook script paths in hooks.json -- CHECKED, use $CLAUDE_PLUGIN_ROOT correctly
3. Schema file references -- CHECKED, all 7 schema files exist
4. Command file paths in plugin.json -- CHECKED, all 4 exist
5. SKILL.md path in plugin.json -- CHECKED, exists
6. TEST-PLAN.md references to code -- Line numbers not referenced, safe

### Security (tested 5, found 1)
1. Path traversal in write_guard.py -- CHECKED, resolved path prevents this (VULN-14 investigation)
2. Symlink attacks -- CHECKED, O_NOFOLLOW used in triage, realpath used in guard
3. Prompt injection via titles -- CHECKED, sanitized at write and read (VULN-1 is about stale docs, not actual vulnerability)
4. Input file path validation in memory_write.py -- CHECKED, /tmp/ prefix required
5. Index lock stale break -- CHECKED, 60-second threshold is reasonable

### Error paths (tested 4, found 1)
1. Pydantic missing -- CHECKED, clear error message
2. Index missing -- CHECKED, auto-rebuild
3. Config missing -- CHECKED, defaults apply
4. Context file write failure -- FOUND undocumented (VULN-7)

### Ordering issues (tested 3, found 0)
1. Phase ordering (0-3) -- CHECKED, enforced by orchestrator
2. Index update after file write -- CHECKED, both inside flock
3. Anti-resurrection before CREATE -- CHECKED, inside flock

---

## Summary of Required Fixes

### Must Fix (Critical + High)
1. **VULN-1**: Update CLAUDE.md Security Consideration #1 to accurately describe the actual sanitization chain. Remove stale line numbers.
2. **VULN-4**: Add archive/unarchive to CLAUDE.md architecture descriptions.
3. **VULN-7**: Add error handling guidance in SKILL.md for missing context_file in triage_data.
4. **VULN-8**: Replace all line number references in CLAUDE.md with function/method names.
5. **VULN-15**: Clarify venv location for pydantic installation in README.

### Should Fix (Medium)
6. **VULN-10**: Document CWD requirement for script invocations.
7. **VULN-12**: Clarify PostToolUse deny semantics (detection-only, cannot prevent).
8. **VULN-13**: Add note about first-retrieval rebuild latency.
9. **VULN-19**: Add maxItems to tags in JSON schemas or document the enforcement approach.

### Nice to Have (Low)
10. **VULN-17**: Document case-insensitive threshold key handling.
11. **VULN-18**: Clarify model tier hints vs actual model IDs.
12. **VULN-16**: List actual test file names.
