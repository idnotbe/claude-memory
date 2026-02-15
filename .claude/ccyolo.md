# ccyolo — Per-Project Claude Code Launcher

`ccyolo` is a bash function that launches Claude Code with `--dangerously-skip-permissions` and automatically loads project-specific plugins.

## How It Works

1. You run `ccyolo` from any directory inside a git repo
2. It finds the repo root via `git rev-parse --show-toplevel`
3. It reads `.claude/plugin-dirs` from that root (if the file exists)
4. Each line becomes a `--plugin-dir` flag passed to `claude`
5. If no config file exists, it runs `claude` with no plugins

```
ccyolo [any claude flags...]
        │
        ├─ finds repo root (git rev-parse --show-toplevel)
        ├─ reads $ROOT/.claude/plugin-dirs
        ├─ expands ~ to $HOME
        ├─ warns on missing dirs (stderr)
        └─ runs: claude --dangerously-skip-permissions --plugin-dir A --plugin-dir B ...
```

## .claude/plugin-dirs Format

```
# Comments start with #
# Blank lines are ignored
# Paths must be absolute or start with ~

~/projects/some-plugin
~/projects/another-plugin

# Commented-out plugins are not loaded:
# ~/projects/disabled-plugin
```

### Rules

| Rule | Detail |
|------|--------|
| Comments | Lines starting with `#` (after whitespace trim) |
| Blank lines | Ignored |
| Path expansion | Only `~` → `$HOME` (no `$VAR`, no `eval`) |
| Relative paths | Not supported — use absolute or `~` paths |
| Missing dirs | Warning printed to stderr, skipped |
| Duplicates | Not de-duped (avoid listing the same path twice) |

## Setup

### 1. Add ccyolo to your shell

The function lives in `~/.bashrc`:

```bash
ccyolo() {
  local plugin_args=()
  local root
  root=$(git rev-parse --show-toplevel 2>/dev/null) || root="$PWD"

  if [ -f "$root/.claude/plugin-dirs" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line%%#*}"
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line%"${line##*[![:space:]]}"}"
      [ -z "$line" ] && continue
      line="${line/#\~/$HOME}"
      if [ -d "$line" ]; then
        plugin_args+=(--plugin-dir "$line")
      else
        echo "ccyolo: warn: plugin dir not found: $line" >&2
      fi
    done < "$root/.claude/plugin-dirs"
  fi

  claude --dangerously-skip-permissions "${plugin_args[@]}" "$@"
}
```

After adding, run `source ~/.bashrc` or open a new terminal.

### 2. Create .claude/plugin-dirs in your project

```bash
cd ~/projects/my-project
mkdir -p .claude
cat > .claude/plugin-dirs << 'EOF'
# Plugins for this project
~/projects/vibe-check
~/projects/claude-code-guardian
EOF
```

### 3. Run

```bash
cd ~/projects/my-project
ccyolo
```

Works from subdirectories too — it finds the git root automatically.

## Current Plugin Assignments

| Repo | Plugins Loaded |
|------|---------------|
| ops | guardian, vibe-check, deepscan, prd-creator |
| claude-memory | vibe-check |
| claude-code-guardian | vibe-check (+ self commented) |
| vibe-check | guardian (+ self commented) |
| deepscan | vibe-check, guardian (+ self commented) |
| prd-creator | vibe-check, guardian (+ self commented) |

## Plugin Development: Self-Loading

Plugin repos include a commented self-load line for dogfood testing:

```
# Uncomment to dogfood-test this plugin in its own repo:
# ~/projects/my-plugin
```

Uncomment when you want to test the plugin against its own codebase. Keep commented by default to avoid surprise side effects.

## Troubleshooting

**No plugins loading?**
- Check you're inside a git repo (`git rev-parse --show-toplevel`)
- Check `.claude/plugin-dirs` exists at the repo root
- Run `ccyolo` — look for warnings on stderr

**Plugin not found warning?**
- Verify the path exists: `ls ~/projects/the-plugin`
- Check for typos in `.claude/plugin-dirs`

**Want to see what gets loaded?**
```bash
# Dry-run: see resolved plugin args without launching claude
bash -i -c '
  root=$(git rev-parse --show-toplevel 2>/dev/null) || root="$PWD"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"; line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}";
    [ -z "$line" ] && continue; line="${line/#\~/$HOME}"
    [ -d "$line" ] && echo "OK: $line" || echo "MISSING: $line"
  done < "$root/.claude/plugin-dirs"
'
```
