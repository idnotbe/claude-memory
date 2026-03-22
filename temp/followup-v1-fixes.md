# Follow-up V-R1 Fixes Applied

## Fix 1 (HIGH): SKILL.md Phase 3 conditional saved/failed
- Changed command template to use `_ok=1` shell variable + `|| _ok=0` after each save command
- Conditional cleanup: `if [ "$_ok" -eq 1 ]; then cleanup-staging; fi`
- Conditional sentinel state: `if [ "$_ok" -eq 1 ]; then --state saved; else --state failed; fi`
- This ensures partial save failures correctly transition sentinel to "failed" state

## Fix 2 (MEDIUM): update_sentinel_state() staging_dir path containment
- Added same validation as write_save_result(): checks /tmp/.claude-memory-staging-* or legacy .staging path
- Prevents attacker-controlled staging_dir from manipulating sentinel in arbitrary directories
