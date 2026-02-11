---
name: memory:search
description: Search memories by keyword across all categories
arguments:
  - name: query
    description: Search terms (e.g., "JWT authentication", "rate limit")
    required: true
---

Search for memories matching the query:

1. Read .claude/memory/index.md for quick title/summary matching
2. If index matches exist, read the matched JSON files for full content
3. If no index matches, use Glob to list all .json files in .claude/memory/*/
   and Grep to search their contents for the query terms
4. Present results grouped by category, showing:
   - Title
   - File path
   - Key content summary (2-3 lines)
   - Last updated date
5. If no results found, say so clearly

Limit to 10 results maximum. Sort by relevance.
