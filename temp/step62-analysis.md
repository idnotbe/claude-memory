# Step 6.2 Analysis: Interpreter Path Resolution in bash_guardian.py

## Current Flow (How F1 Triggers Falsely)

**Command**: `python3 -c "import glob,os\nfor f in glob.glob('.claude/memory/.staging/intent-*.json'): os.remove(f)\nprint('ok')"`

### Step-by-step trace:

1. **Layer 0**: `match_block_patterns(command)` -- The block pattern for Python interpreter deletion (`python[23]?\s[^|&\n]*os\.remove`) WOULD match, but `[^|&\n]*` stops at the `\n` in the multiline payload. So block does NOT fire.

2. **Layer 2**: `split_commands(command)` -- The command is a single sub-command (no `;`, `&&`, `||` delimiters outside quotes). Returns `['python3 -c "..."']` as one sub-command.

3. **Layer 3/4**: Per sub-command analysis:
   - `is_write_command(sub_cmd)` -> `False` (no write patterns match)
   - `is_delete_command(sub_cmd)` -> `True` via the **fallback path** at line 1059: `check_interpreter_payload()` extracts the payload via `extract_interpreter_payload()`, then `_DESTRUCTIVE_API_PATTERN` matches `os.remove`.

4. **Layer 3 path extraction**: `extract_paths(sub_cmd, project_dir, allow_nonexistent=True)`
   - `shlex.split()` produces: `['python3', '-c', '<entire payload as one string>']`
   - Parts[1:] iteration:
     - `-c`: starts with `-`, only 2 chars, skipped
     - `<payload>`: contains `\n` chars -> `_is_path_candidate()` returns `False`
   - Result: `paths = []`

5. **Redirection extraction**: `extract_redirection_targets()` -> `[]` (no shell redirections)

6. **F1 safety net** (line 1476): `is_delete=True AND sub_paths=[]` -> triggers `("ask", "Detected delete but could not resolve target paths")`

### Root Cause

`extract_paths()` uses `shlex.split()` which correctly treats the `-c` argument as a single token. But the function then only checks each token against `_is_path_candidate()`, which rejects strings with newlines. Even without newlines, the full payload string (`import glob,os...`) is not a valid filesystem path.

The fundamental disconnect: `extract_paths()` was designed for shell commands where arguments ARE file paths. For interpreter `-c` payloads, the "argument" is source code, not a path. Paths exist **inside** the source code as string literals.

## String Literals in Python -c Payloads

Typical patterns from claude-memory and similar plugins:
- `glob.glob('.claude/memory/.staging/intent-*.json')` -- path in glob pattern
- `os.remove(f)` -- variable, not a literal path
- `open('.claude/memory/.staging/result.json', 'w')` -- path literal
- `os.path.join('.claude', 'memory', '.staging')` -- path components
- `Path('.claude/memory/.staging/')` -- pathlib usage

## Security Implications

### Extracting paths from Python code is inherently risky:
1. **Obfuscation**: `os.remove(chr(46)+chr(101)+chr(110)+chr(118))` -> `.env` -- regex extraction won't catch this
2. **Dynamic construction**: `f".{x}/{y}"` where x='env' -- can't statically resolve
3. **Variable indirection**: `path = get_path(); os.remove(path)` -- the literal path isn't visible
4. **False confidence**: Extracting a path might make the guardian ALLOW when it should ASK, creating a worse security posture than the current false positive

### The F1 safety net exists specifically for this scenario:
- When a destructive operation is detected but targets can't be determined
- The correct security response IS to ask the user
- The problem is not that F1 is wrong -- it's that certain well-known safe patterns should be exempt

## Approaches

### Approach A: Extract Path Literals from Interpreter Payloads
- Parse string literals from the payload using regex
- Feed them through the normal path validation pipeline
- **Pros**: Precise -- checks actual target paths against zeroAccess/noDelete rules
- **Cons**: Complex regex to handle Python/Node/Perl string syntax; easy to bypass via obfuscation; creates false confidence; maintenance burden across languages

### Approach B: Whitelist Safe Interpreter Patterns
- Define patterns for "known safe" interpreter commands
- E.g., cleanup commands targeting `.staging/` directories
- **Pros**: Simple, targeted
- **Cons**: Specific to certain plugins; doesn't generalize; requires updating for new patterns

### Approach C: Enhance F1 with Interpreter-Aware Path Extraction
- When `is_delete=True` and `sub_paths=[]`, and the delete was detected via `check_interpreter_payload()`:
  - Extract the interpreter payload
  - Extract string literals from the payload
  - Validate those extracted paths through the normal path pipeline
  - Only if all paths pass validation, suppress F1 (allow the command)
  - If any path fails validation (zeroAccess, noDelete, etc.), F1 still triggers
  - If no paths can be extracted, F1 still triggers (fail-closed)
- **Pros**: Surgical fix that maintains fail-closed semantics; only runs when F1 would fire anyway; doesn't weaken security for non-interpreter commands
- **Cons**: Still susceptible to obfuscation (but fail-closed means obfuscated paths just trigger F1 as before)

### Approach D: Extract Paths from Payload at the extract_paths() Level
- Modify `extract_paths()` to detect interpreter -c/-e commands and extract paths from the payload
- Uses `extract_interpreter_payload()` already in `_guardian_utils.py`
- **Pros**: Fixes the root cause; paths go through ALL validation layers (zeroAccess, noDelete, readOnly, symlink)
- **Cons**: Changes a core function's behavior

## Trade-off Assessment

**Approach C is the safest** because:
1. It only activates when F1 would already trigger (no weakening of existing allow/deny paths)
2. It maintains fail-closed: if path extraction fails or finds nothing, F1 still fires
3. Extracted paths still go through all validation layers
4. Obfuscated code still triggers F1 (good -- can't bypass by obscuring paths)

**Approach D is more thorough** but riskier because changing `extract_paths()` affects all layers, not just F1.

## Recommendation

**Approach C**: Add an interpreter-aware path extraction step inside the F1 safety net block. This is a precision fix that only activates in the false-positive scenario and maintains all safety guarantees.
