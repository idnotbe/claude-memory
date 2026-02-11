---
name: memory:save
description: Manually save a memory to a specific category
arguments:
  - name: category
    description: Category name (session_summary, decision, runbook, constraint, tech_debt, preference, or custom)
    required: true
  - name: content
    description: What to remember (natural language description)
    required: true
---

Save a memory manually:

1. Read .claude/memory/memory-config.json to validate the category exists
2. If category is invalid, list available categories and ask user to choose
3. Generate a descriptive kebab-case filename from the content
4. Create the JSON file with full schema:
   - schema_version: "1.0"
   - category: the selected category
   - id: kebab-case slug matching the filename (without .json)
   - title: human-readable title (max 120 chars)
   - created_at / updated_at: current ISO 8601 UTC timestamp
   - tags: extracted keywords (minimum 1)
   - content: structured per the category schema
5. Update .claude/memory/index.md with a one-line entry
6. Confirm: show the filename created and a brief summary

The content argument is natural language. Structure it into the appropriate
JSON schema for the category. Ask the user for missing required fields
(e.g., for a decision: what were the alternatives? why was this chosen?).
