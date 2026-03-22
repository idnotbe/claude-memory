# Step 61 Analysis: Heredoc Pattern False Positives in Layer 0/0b

## 1. The Exact Problem

In `bash_guardian.py` `main()`, the execution flow is:

```
Line 1423: match_block_patterns(command)    ← RAW command string
Line 1437: match_ask_patterns(command)      ← RAW command string
Line 1442: split_commands(command)          ← heredoc-aware decomposition
Line 1450-1452: Layer 1 scan              ← heredoc-excluded sub-commands
Line 1461+: Layer 3+4 per-sub-command     ← heredoc-excluded sub-commands
```

**Layer 1 was already fixed** (lines 1444-1453) to scan joined sub-commands instead of raw command. But **Layer 0 and Layer 0b still scan the raw command**, which includes heredoc body content.

## 2. False Positive Scenarios

### Scenario A: `rm -rf` in documentation heredoc (BLOCK false positive)

```bash
cat > README.md << 'EOF'
# Danger: never run rm -rf / on your system
EOF
```

Block pattern `rm\s+-[rRf]+\s+/(?:\s*$|\*)` matches `rm -rf /` in the heredoc body.
Result: **DENY** (catastrophic false positive — blocks documentation writing)

### Scenario B: `git push --force` in tutorial heredoc (BLOCK false positive)

```bash
cat > docs/git-guide.md << 'EOF'
Avoid using git push --force as it can overwrite history.
EOF
```

Block pattern `git\s+push\s[^;|&\n]*(?:--force(?!-with-lease)|-f\b)` matches.
Result: **DENY**

### Scenario C: `.git` deletion warning in heredoc (BLOCK false positive)

```bash
cat > CONTRIBUTING.md << 'EOF'
Warning: rm .git/ will destroy your repository
EOF
```

Block pattern `(?:rm|rmdir|del|delete|deletion|remove-item)\b\s+.*\.git` matches.
Result: **DENY**

### Scenario D: `rm -rf` in heredoc body (ASK false positive)

```bash
cat > scripts/cleanup-docs.md << 'EOF'
To clean up: rm -rf build/
EOF
```

Ask pattern `rm\s+-[rRf]+` matches.
Result: **ASK** (unnecessary popup)

### Scenario E: `git reset --hard` in documentation heredoc (ASK false positive)

```bash
cat > troubleshooting.md << 'EOF'
If stuck, try: git reset --hard HEAD~1
EOF
```

Ask pattern `git\s+reset\s+--hard` matches.
Result: **ASK**

### Scenario F: SQL in data heredoc (ASK false positive)

```bash
cat > seed.sql << 'EOF'
DROP TABLE IF EXISTS users;
DELETE FROM sessions;
TRUNCATE TABLE logs;
EOF
```

Ask patterns for `DROP TABLE`, `DELETE FROM`, `TRUNCATE TABLE` all match.
Result: **ASK**

### Scenario G: `find -delete` in notes (BLOCK false positive)

```bash
cat > cleanup.sh << 'EOF'
# To clean tmp files:
find /tmp -name "*.log" -delete
EOF
```

Block pattern `find\s+.*\s+-delete` matches.
Result: **DENY**

### Scenario H: `shred` in security documentation (BLOCK false positive)

```bash
cat > security-guide.md << 'EOF'
Use shred to securely delete sensitive files:
shred -vfz secret.key
EOF
```

Block pattern `shred\s+` matches.
Result: **DENY**

## 3. Which Patterns Are Most Likely to Cause False Positives

### Block patterns (DENY — most impactful):
1. `rm\s+-[rRf]+\s+/(?:\s*$|\*)` — root deletion
2. `(?i)(?:rm|rmdir|...).*\.git` — git deletion
3. `(?i)(?:rm|rmdir|...).*\.claude` — claude config deletion
4. `(?i)find\s+.*\s+-delete` — find with delete
5. `shred\s+` — secure deletion
6. `git\s+push\s[^;|&\n]*(?:--force...)` — force push
7. `git\s+filter-branch` — history rewrite
8. `(?:curl|wget)[^|]*\|\s*(?:bash|sh|...)` — remote script execution
9. Interpreter file deletion patterns (python os.remove, etc.)

### Ask patterns (ASK — annoying but not blocking):
1. `rm\s+-[rRf]+` — recursive/force deletion
2. `git\s+reset\s+--hard` — hard reset
3. `git\s+clean\s+-[fdxX]+` — git clean
4. SQL patterns (DROP, DELETE FROM, TRUNCATE)
5. `find\s+.*-exec\s+(?:rm|del|shred)` — find with exec delete

### Critical observation about `re.DOTALL`:
Both `match_block_patterns` and `match_ask_patterns` pass `re.DOTALL` to `safe_regex_search`. This means `.` matches `\n`, so patterns like `[^;|&\n]*` in multiline heredoc commands effectively scan ACROSS lines including heredoc body content. This is the exact amplifier of the false positive problem.

## 4. Ordering Dependency Analysis

The current flow:
```
Layer 0 (block): scan RAW → short-circuit DENY if matched
Layer 0b (ask): scan RAW → accumulate "ask" verdict
Layer 2: split_commands() → heredoc-aware decomposition
Layer 1: scan SPLIT → accumulate verdict
Layer 3+4: per-sub-command → accumulate verdicts
```

**Layer 0 is especially dangerous** because it short-circuits with `sys.exit(0)` on line 1430. Even if later layers would correctly determine the heredoc body is inert data, Layer 0 never lets them run.

## 5. Proposed Restructuring

### Approach: Pre-split heredoc stripping for Layer 0/0b

Instead of moving Layer 0/0b after `split_commands()` (which would change the short-circuit security model), create a lightweight heredoc body stripper that runs BEFORE pattern matching.

```python
def strip_heredoc_bodies(command: str) -> str:
    """Strip heredoc body content from command for pattern matching.

    Returns command with heredoc bodies replaced by empty lines,
    preserving the command structure for regex pattern matching.
    Only strips bodies of DATA heredocs (cat, tee, etc.).
    For INTERPRETER heredocs (bash, python, etc.), the body
    should be preserved for security scanning.
    """
```

Then in main():
```python
# Strip data heredoc bodies before pattern scanning
stripped_command = strip_heredoc_bodies(command)

# Layer 0: Block patterns on stripped command
blocked, reason = match_block_patterns(stripped_command)

# Layer 0b: Ask patterns on stripped command
needs_ask, ask_reason = match_ask_patterns(stripped_command)
```

### Alternative: Reuse split_commands() output

Move `split_commands()` BEFORE Layer 0/0b, then scan joined sub-commands:

```python
sub_commands = split_commands(command)
scan_text = ' '.join(sub for sub in sub_commands if not sub.lstrip().startswith('#'))

blocked, reason = match_block_patterns(scan_text)
needs_ask, ask_reason = match_ask_patterns(scan_text)
```

**Risk**: This changes the scan surface for block patterns — patterns were designed to match against raw command strings. Some patterns use anchors (^) or context assumptions that may break on joined sub-commands.

### Recommended: Hybrid approach

1. Move `split_commands()` up, before Layer 0/0b
2. Layer 0/0b scan joined sub-commands (heredoc bodies excluded)
3. For interpreter heredocs: the interpreter-heredoc-bypass.md plan adds detection at Layer 3/4 level, which runs after split

This way:
- Data heredocs: bodies excluded from ALL layers (no false positives)
- Interpreter heredocs: detected by the new Layer 3/4 check (no false negatives)

## 6. Integration with interpreter-heredoc-bypass.md

The two plans are complementary:

| Problem | This plan | interpreter-heredoc-bypass.md |
|---------|-----------|-------------------------------|
| Data heredoc false positive | FIX: exclude from Layer 0/0b | N/A |
| Interpreter heredoc false negative | N/A | FIX: detect at Layer 3/4 |

**Implementation order matters**: This plan (false positives) should be implemented FIRST because:
1. It moves `split_commands()` before Layer 0/0b, establishing the foundation
2. The interpreter-heredoc-bypass plan then adds detection within the per-sub-command loop
3. Both plans share the same `split_commands()` output

**Shared concern**: Both plans rely on distinguishing "data commands" (cat, tee, echo) from "interpreter commands" (bash, python, perl). The heuristic list must be consistent across both implementations.

## 7. Edge Cases

1. **Pattern anchoring**: Block patterns using `(?:^\\s*|[;|&...])` as prefix — these assume raw command context. Joining sub-commands with spaces changes anchor semantics. Each sub-command should be checked individually, not as a joined string.

2. **Performance**: `split_commands()` is O(n) in command length. Moving it before Layer 0 adds this cost to every command, even those that would have been quickly denied. Acceptable since split_commands is fast and commands have MAX_COMMAND_LENGTH.

3. **Heredoc body with actual commands after it**: `cat << EOF\nbody\nEOF; rm -rf /` — after split, `rm -rf /` is a separate sub-command and is correctly scanned.

4. **Nested heredocs in command substitution**: `$(cat << EOF ...)` — split_commands tracks depth, so heredoc inside $() is not detected at top level. This is correct behavior.

5. **Pattern regression risk**: Some block/ask patterns might rely on seeing the full raw command. Need per-pattern analysis before changing scan surface.
