# Phase 4 Context: Regression Prevention Tests

## Goal
P0 regression tests to prevent approval popup issues from recurring.

## Tests Required (from action plan)

### 1. test_no_hook_script_outputs_ask_verdict
- Scan all 3 guard scripts (memory_write_guard.py, memory_staging_guard.py, memory_validate_hook.py)
- Verify none ever output `permissionDecision: "ask"`
- They should only output "allow" or "deny" (never "ask")
- Method: grep/parse source code for `permissionDecision` strings

### 2. test_write_guard_emits_allow_for_staging
- ALREADY EXISTS in tests/test_memory_write_guard.py TestStagingAutoApprove class
- No action needed, just reference

### 3. test_skill_md_commands_no_guardian_conflicts
- Extract all bash commands from SKILL.md
- Test against Guardian block AND ask patterns
- Should detect: `rm .claude/...`, `find -delete`, heredoc+.claude, interpreter deletion with .claude paths

### 4. test_skill_md_rule0_compliance
- Verify Rule 0 from SKILL.md is followed in SKILL.md itself
- No heredoc (<<) + .claude in same command
- No `python3 -c` with inline code referencing .claude paths
- No `find -delete` or `rm` with .claude paths
- No inline JSON with .claude paths on Bash command line

## Guardian Patterns (from guardian.default.json)

### Block Patterns (deny unconditionally)
1. `rm\s+-[rRf]+\s+/(?:\s*$|\*)` — Root deletion
2. `(?i)(?:^\s*|[;|&`({]\s*)(?:rm|rmdir|del|delete|deletion|remove-item)\b\s+.*\.claude(?:\s|/|[;&|)`'"]|$)` — Claude deletion
3. `(?i)find\s+.*\s+-delete` — Find with delete
4. `(?:py|python[23]?|python\d[\d.]*)\s[^|&\n]*(?:os\.remove|os\.unlink|shutil\.rmtree|shutil\.move|os\.rmdir)` — Interpreter deletion
5. `(?:py|python[23]?|python\d[\d.]*)\s[^|&\n]*pathlib\.Path\([^)]*\)\.unlink` — Pathlib unlink

### Ask Patterns (require confirmation)
1. `rm\s+-[rRf]+` — Recursive/force deletion
2. `find\s+.*-exec\s+(?:rm|del|shred)` — Find with exec delete
3. `mv\s+['\"]?(?:\./)?\.claude` — Moving .claude
4. `xargs\s+(?:rm|del|shred)` — xargs with delete

### Interpreter Payload Check (Layer 3/4)
Guardian also extracts payloads from `python3 -c "..."` and checks for:
- `os\.(?:remove|unlink|rmdir)`
- `shutil\.(?:rmtree|move)`
- `pathlib\.Path\([^)]*\)\.unlink`
- `(?<!\.)\\bunlink\\b`

If detected as delete but no paths resolved → F1 safety net: ask verdict.

## CRITICAL FINDING
The SKILL.md Phase 0 cleanup command uses:
```bash
python3 -c "import glob,os
for f in glob.glob('.claude/memory/.staging/intent-*.json'): os.remove(f)
print('ok')"
```

This contains `os.remove` which Guardian's `check_interpreter_payload` would detect.
However, the `[^|&\n]*` in the block pattern regex stops at newlines, so the
block pattern itself won't match (os.remove is on a different line from python3).

BUT `is_delete_command()` calls `check_interpreter_payload()` which extracts the
full payload and finds `os.remove`. This marks it as `is_delete=True`.
Then `extract_paths()` can't find filesystem paths in the Python string literal,
so `sub_paths=[]`, triggering F1 safety net: `("ask", "Detected delete but could not resolve target paths")`.

**This means the python3 -c cleanup command still triggers a Guardian ASK popup.**
The Phase 2 fix avoided the BLOCK but may introduce an ASK.

## File Locations
- Guard scripts: hooks/scripts/memory_write_guard.py, memory_staging_guard.py, memory_validate_hook.py
- SKILL.md: skills/memory-management/SKILL.md
- Guardian config: /home/idnotbe/projects/claude-code-guardian/assets/guardian.default.json
- Guardian utils: /home/idnotbe/projects/claude-code-guardian/hooks/scripts/_guardian_utils.py
- Existing tests: tests/test_memory_write_guard.py, test_memory_staging_guard.py, test_memory_validate_hook.py
