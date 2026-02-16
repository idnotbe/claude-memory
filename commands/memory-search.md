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

**Examples:**
```
/memory:search JWT authentication      # Find memories about JWT auth
/memory:search rate limit              # Find rate limit related memories
/memory:search --include-retired docker # Include retired/archived in search
```

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

Limit to 10 results maximum. Sort by relevance using index-based scoring:
- Exact tag match: 3 points
- Exact title word match: 2 points
- Prefix match (4+ characters): 1 point
- Recency bonus: +1 for memories updated within 30 days

The scoring algorithm operates on index.md entries (titles and tags) only.
For full content search, the Glob+Grep fallback path (step 3) provides
broader matching without numeric scoring.
