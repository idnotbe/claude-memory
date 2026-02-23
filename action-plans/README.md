# Action Plans

Execution plan management directory.

## Structure
- Root `.md` files = active plans (not-started, active, blocked)
- `_done/` = completed plans
- `_ref/` = reference/historical documents

## Frontmatter Rules
All plan files must have YAML frontmatter at the top:

```yaml
---
status: not-started    # not-started | active | blocked | done
progress: "Not started"  # Current progress (free text)
---
```

## Status Values
- **not-started**: Work has not begun
- **active**: Currently in progress
- **blocked**: Waiting on unresolved dependencies
- **done**: Completed -> **must** move to `_done/`

## Action Plan File Structure
Action plan files must contain ordered actions (phase1, phase2... or step1, step2...).

Each step must have a progress checkmark:
- `[v]` = done
- `[ ]` = not started
- `[/]` = in progress

Example:
```markdown
## Phase 1: Initial Setup
- [v] Configure environment
- [v] Install dependencies

## Phase 2: Implementation
- [/] Develop core feature
- [ ] Write tests
```

When all steps are marked `[v]`, the entire plan is done. Update frontmatter to `status: done` and move the file to `_done/`.

## Lifecycle
1. Create new plan -> add file to root with frontmatter
2. Start work -> `status: active`, update `progress`
3. Complete work -> `status: done`, move to `_done/` (required)
4. Archive as reference -> move to `_ref/`
