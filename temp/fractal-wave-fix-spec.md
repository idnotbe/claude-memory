# fractal-wave Fix Specification

## Change Made
File: `/home/idnotbe/projects/fractal-wave/hooks/hooks.json`

### Before
```
Line 9:  "command": "python ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/on_task_modified.py $TOOL_INPUT"
Line 20: "command": "python ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start.py"
```

### After
```
Line 9:  "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/on_task_modified.py $TOOL_INPUT"
Line 20: "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session_start.py"
```

### Reason
WSL/Linux does not have `python` in PATH, only `python3`.
Error was: `/bin/sh: 1: python: not found`

### JSON Validation
PASSED
