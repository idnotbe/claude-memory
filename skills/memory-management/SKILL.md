---
name: memory-management
description: Knowledge about the claude-memory system for managing structured project memories
globs:
  - ".claude/memory/**"
  - ".claude/memory-config.json"
triggers:
  - "remember"
  - "forget"
  - "memory"
  - "memories"
  - "what do you know about"
  - "what did we decide"
  - "previous session"
---

# Memory Management System

You have access to a structured memory system stored in `.claude/memory/`.

## Categories

| Category | Folder | Purpose |
|----------|--------|---------|
| session_summary | sessions/ | Current work resume snapshot |
| decision | decisions/ | Choice + rationale (why X over Y) |
| runbook | runbooks/ | Error fix procedure (symptom -> fix -> verify) |
| constraint | constraints/ | Known limitations/gaps (wall map) |
| tech_debt | tech-debt/ | Deferred work backlog (prioritized) |
| preference | preferences/ | Style/tool conventions (consistency) |

## How It Works

- **Auto-capture**: A Stop hook evaluates each conversation turn and saves relevant
  memories as JSON files in the appropriate category folder.
- **Auto-retrieval**: A UserPromptSubmit hook reads the memory index and injects
  relevant file paths when the user's prompt matches stored memories.
- **Manual commands**: /memory, /memory:config, /memory:search, /memory:save

## Index File

`.claude/memory/index.md` contains one-line summaries of all memories. It is the
primary retrieval mechanism. Format:
`- [CATEGORY] summary -> filepath`

## When the User Asks About Memories

- "What do you remember?" -> Read index.md and summarize
- "Remember that..." -> Use /memory:save logic to create a memory
- "Forget..." -> Read the memory, confirm with user, then delete file and remove from index
- "What did we decide about X?" -> Search decisions/ folder
- "Show me the runbook for X" -> Search runbooks/ folder

## Config

`.claude/memory/memory-config.json` controls which categories are active,
retrieval settings, and custom categories. Use /memory:config to modify.
