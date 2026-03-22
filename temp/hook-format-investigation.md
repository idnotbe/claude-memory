# Hook Format Investigation: PreToolUse `allow` vs Permission Popups

**Date:** 2026-03-22
**Status:** Root cause identified -- not a format bug, but a Claude Code platform limitation

---

## Summary

The `memory_write_guard.py` hook output format is **correct**. The permission popups persist because Claude Code has a **protected directory check** for `.claude/` paths that runs **independently** of PreToolUse hook decisions. A hook returning `"allow"` does not bypass this protection.

---

## 1. Hook Output Format: CORRECT

The current format used by `memory_write_guard.py` (line 123-128):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
```

This matches the official Claude Code documentation exactly. The format was confirmed via:

- **Official docs** (https://code.claude.com/docs/en/hooks) -- PreToolUse decision control section
- **Plugin dev SKILL.md** (https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md)
- **SDK permissions docs** (https://docs.claude.com/en/docs/claude-code/sdk/sdk-permissions)

The old deprecated format (`{"decision": "approve"}` at top level) is NOT the issue. The current `hookSpecificOutput` format is the correct modern format.

### Valid `permissionDecision` values

| Value   | Effect                                        |
|---------|-----------------------------------------------|
| `allow` | Skip the permission prompt                    |
| `deny`  | Prevent the tool call (shown to Claude)       |
| `ask`   | Show a confirmation prompt to the user        |

### Additional supported fields (not currently used)

- `permissionDecisionReason` -- for `allow`/`ask`: shown to user (not Claude); for `deny`: shown to Claude
- `updatedInput` -- modify tool input before execution
- `additionalContext` -- string added to Claude's context

---

## 2. Root Cause: Protected Directory Check

Claude Code has a **hardcoded protected directory system** that gates writes to certain directories regardless of hook decisions or permission settings. The protected directories are:

- `.git/`
- `.claude/`
- `.vscode/`
- `.idea/`

**Exempted subdirectories** (do NOT prompt):
- `.claude/commands/`
- `.claude/agents/`
- `.claude/skills/`

**NOT exempted** (WILL prompt):
- `.claude/memory/` -- this is where staging files live
- `.claude/settings*.json`
- Any other `.claude/` path

### The critical documentation quote

From https://code.claude.com/docs/en/permissions:

> "Skipping the prompt does not bypass permission rules. Deny and ask rules are still evaluated after a hook returns `"allow"`, so a matching deny rule still blocks the call."

And from the `bypassPermissions` mode documentation:

> "Writes to `.git`, `.claude`, `.vscode`, and `.idea` directories still prompt for confirmation to prevent accidental corruption of repository state and local configuration. Writes to `.claude/commands`, `.claude/agents`, and `.claude/skills` are exempt and do not prompt."

This means:
1. The PreToolUse hook correctly outputs `"allow"`
2. Claude Code acknowledges it and skips the *normal* permission prompt
3. But then a **separate, independent** protected directory check fires for `.claude/memory/.staging/` paths
4. This check is NOT bypassable by hooks, permission rules, or even `--dangerously-skip-permissions`

---

## 3. Known Claude Code Issues Confirming This

Multiple open/recent GitHub issues document this exact behavior:

| Issue | Title | Status |
|-------|-------|--------|
| [#35646](https://github.com/anthropics/claude-code/issues/35646) | Protected directory prompt in bypassPermissions has no override | Closed |
| [#35718](https://github.com/anthropics/claude-code/issues/35718) | `--dangerously-skip-permissions` does not bypass "modify config files" prompt for `~/.claude/` writes | Closed (dup of #35646) |
| [#21242](https://github.com/anthropics/claude-code/issues/21242) | Write permission for skill .md files keeps prompting despite settings.local.json | Open |

Key quote from #35646:

> "There appears to be an undocumented permission category ('modify config files') that gates writes to `~/.claude/` paths. This gate is checked independently of the `--dangerously-skip-permissions` flag."

---

## 4. Settings Analysis

### User settings (`~/.claude/settings.json`)

- Has `skipDangerousModePermissionPrompt: true`
- No Write-specific allow/deny rules
- No `.claude/memory` path rules

### Project settings (`claude-memory/.claude/settings.json`)

- No Write-specific allow/deny rules
- `Bash(python:*)` is allowed (covers memory_write.py execution)
- No `.claude/memory` path rules

### Ops project settings (`ops/.claude/settings.json`)

- Similar structure, no Write path rules

**Conclusion:** No settings-level deny or ask rules are overriding the hook's `allow` decision. The popup comes from the platform-level protected directory check.

---

## 5. Possible Workarounds

### Workaround A: PermissionRequest Hook (RECOMMENDED TO INVESTIGATE)

Claude Code has a `PermissionRequest` hook event that fires when a permission dialog is *about to be shown* to the user. This is a separate event from PreToolUse and runs after all permission checks (including the protected directory check).

Output format:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedInput": {}
    }
  }
}
```

**This could potentially auto-dismiss the protected directory popup.** However, this needs testing -- it is unclear whether the "modify config files" prompt is a standard PermissionRequest or a separate UI-level gate.

Implementation:
1. Add a `PermissionRequest` hook to `hooks/hooks.json` with matcher `Write`
2. Create a new script (e.g., `memory_permission_request.py`) that checks if the path is in `.claude/memory/.staging/` and returns `behavior: "allow"`
3. Apply the same safety gates as `memory_write_guard.py` (extension whitelist, filename pattern, hard link defense)

### Workaround B: Move Staging Outside `.claude/`

Move the staging directory from `.claude/memory/.staging/` to a location that is NOT protected:
- `/tmp/.claude-memory-staging/` (ephemeral, clears on reboot)
- `<project-root>/.memory-staging/` (visible but not protected)

This avoids the protected directory check entirely but requires updating multiple scripts.

### Workaround C: Use Bash for Staging Writes Instead of Write Tool

The protected directory check only applies to the Write tool, not to Bash subprocess writes. However, this directly conflicts with the existing `memory_staging_guard.py` which blocks Bash writes to `.staging/` specifically to prevent Guardian false positives.

The tradeoff: remove the staging guard and accept Guardian false positive risk, or keep it and accept permission popups. Neither is ideal.

### Workaround D: Wait for Upstream Fix

The Claude Code team may add `.claude/memory/` to the exempt list or provide a settings-level override. Issues #35646 and #21242 track this. No timeline is known.

---

## 6. Recommendation

**Short-term:** Investigate Workaround A (PermissionRequest hook). If the "modify config files" prompt fires a PermissionRequest event, this is the cleanest fix -- it preserves all existing safety gates while auto-approving staging writes that pass validation.

**If PermissionRequest doesn't work:** Consider Workaround B (move staging to `/tmp/`). The staging files are ephemeral by design, so `/tmp/` is semantically appropriate. The main cost is updating path references in `memory_write_guard.py`, `memory_staging_guard.py`, `memory_triage.py`, SKILL.md, and related scripts.

**The hook output format itself requires no changes.**
