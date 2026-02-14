---
name: memory:search
description: Search memories by keyword across all categories
arguments:
  - name: query
    description: Search terms (e.g., "JWT authentication", "rate limit")
    required: true
  - name: options
    description: "Optional flags: --include-retired to also search retired/archived memories"
    required: false
---

Search for memories matching the query:

1. Read `.claude/memory/index.md` for quick title/tag matching
   - Index entries include `#tags:` suffix for tag-based scoring
   - Retired and archived memories are excluded from the index
2. If index matches exist, read the matched JSON files for full content
3. If no index matches, use Glob to list all .json files in `.claude/memory/*/`
   and Grep to search their contents for the query terms
4. Present results grouped by category, showing:
   - Title
   - File path
   - Key content summary (2-3 lines)
   - Last updated date
   - Record status (if not active)
5. If no results found, say so clearly

**--include-retired**: When this flag is present, also scan `.json` files directly
in all category folders (not just the index) to find retired and archived memories
matching the query. These are marked with their record_status in the output.

Limit to 10 results maximum. Sort by relevance (tag matches score highest at 3 points,
title word matches at 2 points, content matches at 1 point, with a recency bonus
for memories updated within 30 days).
