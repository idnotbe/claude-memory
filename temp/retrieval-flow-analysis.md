# Retrieval Flow Analysis: claude-memory Plugin (v5.0.0)

Generated: 2026-02-19
Source: `hooks/scripts/memory_retrieve.py`, `hooks/hooks.json`, `assets/memory-config.default.json`

---

## ASCII Flow Overview

```
USER TYPES PROMPT
       |
       v
  Claude Code Runtime
       |
       |-- fires UserPromptSubmit hook (hooks/hooks.json line 43-54)
       |
       v
  memory_retrieve.py   <-- stdin receives JSON hook payload
       |
       |-- [GUARD 1] Empty / bad JSON? --> exit(0)
       |-- [GUARD 2] Prompt < 10 chars? --> exit(0)
       |
       |-- Resolve: cwd/.claude/memory/index.md
       |
       |-- index.md missing?
       |       |
       |       |-- memory_root dir exists?
       |       |       YES --> spawn memory_index.py --rebuild (subprocess, 10s timeout)
       |       |       NO  --> skip rebuild
       |       |
       |       |-- index.md still missing? --> exit(0)
       |
       |-- Read memory-config.json
       |       |-- retrieval.enabled == false? --> exit(0)
       |       |-- clamp max_inject to [0,20]
       |       |-- max_inject == 0? --> exit(0)
       |       |-- load category descriptions
       |
       |-- Parse index.md --> list[entry]
       |       |-- No entries? --> exit(0)
       |
       |-- Tokenize prompt (stop-word filter, len > 2)
       |       |-- No tokens? --> exit(0)
       |
       |-- Pre-tokenize category descriptions
       |
       |== PASS 1: Score all entries (text matching) ==
       |       |-- score_entry(): title exact (+2), tag exact (+3), prefix (+1)
       |       |-- score_description(): desc exact (+1), prefix (+0.5), capped at 2
       |       |-- discard score == 0
       |       |-- sort: highest score first, then CATEGORY_PRIORITY
       |
       |-- No scored entries? --> exit(0)
       |
       |== PASS 2: Deep check top 20 candidates ==
       |       |-- Read JSON file for each
       |       |-- is_retired? --> skip entry entirely
       |       |-- is_recent (<=30 days)? --> +1 to score
       |       |-- entries ranked 21+ appended as-is (no recency bonus)
       |
       |-- No final entries? --> exit(0)
       |
       |-- Re-sort, take top max_inject
       |
       |-- Sanitize titles (_sanitize_title())
       |
       v
  print <memory-context ...> block to stdout
       |
       v
  Claude Code injects stdout into Claude's context
       |
       v
  Claude receives enriched prompt with relevant memories
```

---

## 1. Trigger Mechanism

### Hook Registration (hooks/hooks.json, lines 43-54)

```json
"UserPromptSubmit": [
  {
    "matcher": "*",
    "hooks": [
      {
        "type": "command",
        "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
        "timeout": 10,
        "statusMessage": "Retrieving relevant memories..."
      }
    ]
  }
]
```

**Key facts:**
- Hook type: `UserPromptSubmit` -- fires before every prompt Claude receives from the user.
- Matcher: `"*"` -- no filtering, fires on every prompt unconditionally.
- Timeout: 10 seconds. If the script does not exit within 10s, Claude Code kills it.
- `$CLAUDE_PLUGIN_ROOT` is set by Claude Code to the plugin's installation directory (e.g., `~/.claude/plugins/claude-memory/`).
- The hook is of type `"command"` -- stdout is injected into Claude's context; stderr is discarded or logged separately.

### Stdin JSON Payload Format

Claude Code sends a JSON object on stdin. The script reads it at lines 200-209:

```python
raw = sys.stdin.read()           # line 201
hook_input = json.loads(raw)     # line 204
user_prompt = hook_input.get("user_prompt", "")   # line 208
cwd = hook_input.get("cwd", os.getcwd())           # line 209
```

**Fields consumed from the hook payload:**
| Field | Type | Usage | Default |
|-------|------|-------|---------|
| `user_prompt` | string | The text the user typed | `""` |
| `cwd` | string | Project working directory | `os.getcwd()` |

No other fields are used. The hook payload may contain additional fields (session ID, tool info, etc.) that are simply ignored.

---

## 2. Index Resolution

### Path Construction (lines 216-217)

```python
memory_root = Path(cwd) / ".claude" / "memory"
index_path  = memory_root / "index.md"
```

The index is always anchored to the **project's working directory** (`cwd`), not any global path. This means each project has its own memory store.

### Auto-Rebuild Logic (lines 221-231)

If `index_path` does not exist but `memory_root` IS a directory, the script attempts an on-demand rebuild:

```python
if not index_path.exists() and memory_root.is_dir():
    import subprocess
    index_tool = Path(__file__).parent / "memory_index.py"
    if index_tool.exists():
        try:
            subprocess.run(
                [sys.executable, str(index_tool), "--rebuild", "--root", str(memory_root)],
                capture_output=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass
```

**What memory_index.py --rebuild does** (memory_index.py lines 89-116):
1. Scans all 6 category subfolders (`decisions/`, `runbooks/`, `constraints/`, `tech-debt/`, `preferences/`, `sessions/`)
2. Reads every `.json` file in each folder
3. Skips files where `record_status != "active"` (i.e., skips retired and archived)
4. Extracts `title`, `category`, `tags` from each JSON
5. Computes a relative path from the project root (grandparent of `memory_root`): `json_file.relative_to(root.parent.parent)`
6. Sorts entries alphabetically by display name then title
7. Writes `index.md` with lines in the format:
   ```
   - [DECISION] My decision title -> .claude/memory/decisions/slug.json #tags:tag1,tag2
   ```

**Rebuild conditions summary:**
| Condition | Outcome |
|-----------|---------|
| `index_path` exists | No rebuild attempted |
| `index_path` missing AND `memory_root` is not a dir | No rebuild (exit(0) at line 234) |
| `index_path` missing AND `memory_root` is a dir AND `memory_index.py` exists | Rebuild attempted, 10s timeout |
| Rebuild times out | Silently swallowed (`except subprocess.TimeoutExpired: pass`) |
| After rebuild, index still missing | exit(0) at line 234 |

The `capture_output=True` means neither stdout nor stderr from the rebuild is surfaced to the user.

---

## 3. Configuration Loading (lines 237-265)

Before scoring, the script reads `memory-config.json` from the memory root:

```python
config_path = memory_root / "memory-config.json"
```

This is the **project-local** config, not the plugin default. If the file is missing, the script uses hardcoded defaults:
- `max_inject = 5`
- `category_descriptions = {}` (empty -- no description scoring)

**Config fields consumed:**

| Config Path | Type | Default | Effect |
|-------------|------|---------|--------|
| `retrieval.enabled` | bool | `true` | If `false`, exit(0) immediately (line 246) |
| `retrieval.max_inject` | int | `5` | Max memories to inject; clamped to [0, 20] |
| `categories.<cat>.description` | string | `""` | Used for description-based scoring; truncated at 500 chars |

**max_inject clamping** (lines 248-255):
```python
raw_inject = retrieval.get("max_inject", 5)
try:
    max_inject = max(0, min(20, int(raw_inject)))
except (ValueError, TypeError, OverflowError):
    max_inject = 5
    print(f"[WARN] Invalid max_inject value: {raw_inject!r}; using default 5", file=sys.stderr)
```

Values outside [0, 20] are hard-clamped. Non-integer values fall back to 5 with a stderr warning.

**Category descriptions** (lines 257-263):
Category descriptions are loaded from all keys under `categories` (lowercased). They are stored in `category_descriptions: dict[str, str]` and later converted to token sets for scoring:
```python
for cat_key, cat_val in categories_raw.items():
    desc = cat_val.get("description", "")
    if isinstance(desc, str) and desc:
        category_descriptions[cat_key.lower()] = desc[:500]
```

Note: `match_strategy` from config (default `"title_tags"`) is **not read or enforced** by `memory_retrieve.py`. It is listed in the config schema but is an agent-interpreted key only -- the script always uses its built-in title+tags+description scoring regardless.

---

## 4. Index Parsing (lines 271-283)

The index file is read line-by-line and parsed using a precompiled regex (lines 45-48):

```python
_INDEX_RE = re.compile(
    r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)"
    r"(?:\s+#tags:(.+))?$"
)
```

**Regex group capture:**
| Group | Content | Example |
|-------|---------|---------|
| `group(1)` | Category display name | `DECISION` |
| `group(2)` | Title (non-greedy, whitespace-trimmed) | `Use pydantic v2 for schema validation` |
| `group(3)` | Relative file path (no whitespace) | `.claude/memory/decisions/use-pydantic-v2.json` |
| `group(4)` | Tags string (optional, after `#tags:`) | `pydantic,validation,schema` |

`parse_index_line()` (lines 69-87) returns a dict:
```python
{
    "category": "DECISION",
    "title": "Use pydantic v2 for schema validation",
    "path": ".claude/memory/decisions/use-pydantic-v2.json",
    "tags": {"pydantic", "validation", "schema"},   # set of lowercase stripped strings
    "raw": "- [DECISION] Use pydantic v2 for schema validation -> .claude/memory/decisions/use-pydantic-v2.json #tags:pydantic,validation,schema"
}
```

Lines that do not match the regex (headers, blank lines, comments) are silently skipped.

---

## 5. Two-Pass Scoring Pipeline

### Tokenization (lines 60-66)

Both the prompt and entry titles/descriptions are tokenized the same way:

```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")

def tokenize(text: str) -> set[str]:
    tokens = set()
    for word in _TOKEN_RE.findall(text.lower()):
        if word not in STOP_WORDS and len(word) > 2:
            tokens.add(word)
    return tokens
```

**Rules:**
- Lowercase everything
- Extract only `[a-z0-9]+` sequences (strips punctuation, hyphens, underscores)
- Remove stop words (32 words defined at lines 21-32, including: `the`, `is`, `how`, `help`, `need`, `want`, `use`, `get`, etc.)
- Remove tokens of length <= 2 (so `db`, `io`, `py` are dropped)
- Returns a `set` (duplicates collapsed)

### Pass 1: Text Matching (lines 295-308)

Executed against ALL parsed index entries.

**`score_entry()` function (lines 90-117):**

| Match Type | Points | Condition |
|------------|--------|-----------|
| Exact title word match | +2 per word | `prompt_words & title_tokens` |
| Exact tag match | +3 per tag | `prompt_words & entry_tags` |
| Prefix match on title or tags | +1 per prompt word | prompt word (len >= 4) is a prefix of ANY title token or tag |

Prefix match logic (lines 112-115):
```python
for pw in prompt_words - already_matched:  # skip already-exact-matched words
    if len(pw) >= 4:
        if any(target.startswith(pw) for target in combined_targets):
            score += 1
```

`already_matched` = union of exact title matches + exact tag matches. This prevents double-counting.

**`score_description()` function (lines 120-144):**

Applied only if the entry's category has a description loaded from config.

| Match Type | Points | Cap |
|------------|--------|-----|
| Exact description word match | +1.0 per word | -- |
| Prefix match on description (4+ char prompt words) | +0.5 per word | -- |
| Total description contribution | min(2, floor(score)) | Capped at 2 |

The cap prevents a verbose description from dominating over title/tag matches.

**After Pass 1 (lines 303-311):**
- Entries with `text_score == 0` are discarded entirely
- Remaining entries sorted: `(-score, category_priority)` -- highest score first, ties broken by `CATEGORY_PRIORITY`:
  ```python
  CATEGORY_PRIORITY = {
      "DECISION":        1,   # highest priority
      "CONSTRAINT":      2,
      "PREFERENCE":      3,
      "RUNBOOK":         4,
      "TECH_DEBT":       5,
      "SESSION_SUMMARY": 6,  # lowest priority
  }
  ```
  Unknown categories get priority 10 (always last).

### Pass 2: Deep Check (lines 313-333)

Only the top `_DEEP_CHECK_LIMIT = 20` candidates (by Pass 1 score) have their JSON files read.

**Path resolution** (lines 315-318):
```python
project_root = memory_root.parent.parent   # cwd/.claude/memory -> cwd
file_path = project_root / entry["path"]   # cwd / .claude/memory/decisions/foo.json
```

The path stored in the index is relative to the project root (set by `memory_index.py` at line 73 using `json_file.relative_to(root.parent.parent)`), so this reconstruction is consistent.

**`check_recency()` function (lines 147-180):**

Reads the JSON file and checks two things:

1. **Retired check** (lines 160-162):
   ```python
   record_status = data.get("record_status", "active")
   if record_status == "retired":
       return True, False   # is_retired=True, is_recent=False
   ```

2. **Recency check** (lines 164-180):
   - Reads `updated_at` field (ISO 8601 string)
   - Handles both `Z` suffix and `+00:00` offset
   - Ensures timezone-aware comparison (assumes UTC if naive)
   - Returns `is_recent = (age_days <= 30)` where `_RECENCY_DAYS = 30`
   - If `updated_at` is missing or unparseable: returns `(False, False)`

**Per-candidate outcomes:**
| Condition | Action |
|-----------|--------|
| File unreadable or JSON invalid | `check_recency` returns `(False, False)` -- entry included, no recency bonus |
| `record_status == "retired"` | Entry **skipped entirely** (line 323: `continue`) |
| `updated_at` within 30 days | `final_score = text_score + 1` |
| `updated_at` older than 30 days or missing | `final_score = text_score + 0` |

**Entries ranked 21-N** (beyond `_DEEP_CHECK_LIMIT`, lines 329-330):
```python
for text_score, priority, entry in scored[_DEEP_CHECK_LIMIT:]:
    final.append((text_score, priority, entry))
```
These are included without any recency check and without retired filtering. This is a known gap: retired entries ranked below position 20 in Pass 1 can slip through to the output.

**Final re-sort and truncation** (lines 335-337):
```python
final.sort(key=lambda x: (-x[0], x[1]))
top = final[:max_inject]
```

---

## 6. Output Protocol

### Title Sanitization (lines 183-195)

Before output, every title is passed through `_sanitize_title()`:

```python
def _sanitize_title(title: str) -> str:
    # Strip ASCII control characters (null, tab, newline, etc.)
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    # Strip zero-width, BiDi override, Unicode tag characters
    title = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]', '', title)
    # Remove index-format injection sequences
    title = title.replace(" -> ", " - ").replace("#tags:", "")
    # Escape XML-sensitive characters
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
    # Truncate to 120 characters
    title = title.strip()[:120]
    return title
```

This is defense-in-depth: `memory_write.py` sanitizes on write, `memory_retrieve.py` sanitizes again on read. The sanitization prevents:
- Prompt injection via control characters / BiDi overrides
- Breaking the `->` delimiter format if a crafted title contains ` -> `
- XML/HTML tag injection from `<`, `>`, `&`, `"`

### Output Block Construction (lines 342-358)

The output is a `<memory-context>` XML-like block printed to stdout:

```python
print(f"<memory-context source=\".claude/memory/\"{desc_attr}>")
for _, _, entry in top:
    safe_title = _sanitize_title(entry["title"])
    tags = entry.get("tags", set())
    tags_str = f" #tags:{','.join(sorted(tags))}" if tags else ""
    print(f"- [{entry['category']}] {safe_title} -> {entry['path']}{tags_str}")
print("</memory-context>")
```

**`desc_attr` construction** (lines 342-350): If category descriptions were loaded from config, they are included as a `descriptions` attribute on the opening tag:

```python
desc_parts = []
for cat_key, desc in sorted(category_descriptions.items()):
    safe_desc = _sanitize_title(desc)
    desc_parts.append(f"{cat_key}={safe_desc}")
desc_attr = " descriptions=\"" + "; ".join(desc_parts) + "\""
```

**Example output with no descriptions:**
```
<memory-context source=".claude/memory/">
- [DECISION] Use pydantic v2 for schema validation -> .claude/memory/decisions/use-pydantic-v2.json #tags:pydantic,validation
- [CONSTRAINT] Max 20 memories injected per prompt -> .claude/memory/constraints/max-inject.json
</memory-context>
```

**Example output with descriptions:**
```
<memory-context source=".claude/memory/" descriptions="constraint=External limitations, platform restrictions, and hard boundaries that cannot be changed; decision=Architectural and technical choices with rationale -- why X was chosen over Y">
- [DECISION] Use pydantic v2 for schema validation -> .claude/memory/decisions/use-pydantic-v2.json #tags:pydantic,validation
</memory-context>
```

**Note:** Tags in the output come directly from the parsed index line (not re-read from JSON). They are sorted alphabetically for deterministic output. Tags are NOT sanitized in the output line -- only titles are. A crafted tag value containing ` -> ` or `#tags:` could potentially corrupt the output line format.

### How Injection Works

Claude Code captures the hook's stdout. When the script exits with code 0 and has printed content, Claude Code prepends that content to Claude's context for the current turn. Claude reads the `<memory-context>` block and is expected (by the system prompt / SKILL.md instructions) to treat the listed entries as relevant prior memories to consult.

---

## 7. Edge Cases and Early Exits

The following conditions cause `exit(0)` with no output (silence):

| Line(s) | Condition | Reason |
|---------|-----------|--------|
| 202-203 | stdin is empty | No hook payload |
| 205-206 | stdin is not valid JSON | Corrupted hook delivery |
| 212-213 | `user_prompt.strip()` length < 10 | Greetings ("hi", "ok", "yes") don't need retrieval |
| 233-234 | `index_path` does not exist (after attempted rebuild) | No memory index to query |
| 245-246 | `retrieval.enabled == false` in config | Retrieval explicitly disabled |
| 267-268 | `max_inject == 0` (after clamping) | Config says inject nothing |
| 278-279 | `OSError` reading `index.md` | File permissions issue |
| 281-282 | `entries` list is empty | Index exists but has no parseable lines |
| 287-288 | `prompt_words` set is empty after tokenization | Prompt is entirely stop words / short tokens |
| 307-308 | No entries scored > 0 in Pass 1 | No keyword overlap between prompt and memories |
| 332-333 | `final` list is empty after Pass 2 | All Pass 1 candidates were retired entries |

**Additional silent failure:**
- `subprocess.TimeoutExpired` during rebuild (line 230-231): swallowed silently; retrieval proceeds to `exit(0)` at line 234 if index still missing.
- JSON parse errors in config (line 264): `except (json.JSONDecodeError, KeyError, OSError): pass` -- script continues with defaults.
- `check_recency()` file read failure (line 156-157): `return False, False` -- entry is included without recency bonus rather than being dropped.

---

## 8. Configuration Influence Summary

| Config Key | Script Behavior |
|------------|----------------|
| `retrieval.enabled: false` | exit(0) at line 246, nothing injected |
| `retrieval.max_inject: N` | Clamped to [0,20]; controls how many memories appear in output |
| `retrieval.max_inject: 0` | exit(0) at line 268 |
| `retrieval.match_strategy` | NOT READ by script; agent-interpreted key only |
| `categories.<cat>.description` | Loaded as token set; adds up to 2 points to all entries in that category |
| All other config keys | NOT read by memory_retrieve.py |

**The `match_strategy` gap:** The config default specifies `"title_tags"` as `match_strategy`, suggesting different strategies might exist. However, `memory_retrieve.py` always uses its full scoring pipeline (title + tags + description). The config value is read only by the LLM agent (via SKILL.md) for documentation/guidance purposes, not enforced programmatically.

---

## 9. Data Flow: Scoring Example

**Prompt:** `"How do I validate JSON schemas with pydantic?"`

**After tokenization (stop words removed, len > 2):**
```
{"validate", "json", "schemas", "pydantic"}
```
(Words removed: "how", "do", "i", "with")

**Index entry:**
```
- [DECISION] Use pydantic v2 for schema validation -> .claude/memory/decisions/use-pydantic-v2.json #tags:pydantic,validation,schema
```

**Pass 1 scoring:**
- Title tokens: `{"use", "pydantic", "v2", "for", "schema", "validation"}` -> after stop-word filter and len>2: `{"pydantic", "schema", "validation"}`
- Exact title matches: `{"pydantic", "schema"}` (note: "schemas" != "schema" -- not exact) -> 2 * 2 = **+4**
- Exact tag matches: `{"pydantic", "validation"}` intersect `{"pydantic", "validation", "schema"}` -> `{"pydantic", "validation"}` -> 2 * 3 = **+6**
- Prefix matches (already matched: `{"pydantic", "validation"}`):
  - Remaining prompt words not already matched: `{"validate", "json", "schemas"}`
  - "validate" (len 8): does "validation" start with "validate"? YES -> **+1**
  - "json" (len 4): no title/tag starts with "json" -> 0
  - "schemas" (len 7): does "schema" start with "schemas"? NO (prefix is reversed) -- "schema".startswith("schemas") = False -> 0
- Description scoring (if DECISION description loaded):
  - Description: "Architectural and technical choices with rationale -- why X was chosen over Y"
  - Desc tokens: `{"architectural", "technical", "choices", "rationale", "why", "chosen", "over"}` (after stop-word filter, len>2)
  - No overlap with `{"validate", "json", "schemas", "pydantic"}` -> **+0**

**Pass 1 total: 4 + 6 + 1 = 11**

**Pass 2 (deep check):**
- `updated_at` is 5 days ago -> is_recent = True -> **+1**
- `record_status = "active"` -> not retired -> included

**Final score: 12**

---

## 10. Known Gaps and Security Notes

1. **Entries ranked 21+ bypass retired filtering** (lines 329-330): If more than 20 entries match a prompt, entries at positions 21+ are included without checking `record_status`. A retired entry that scores highly enough to appear in Pass 1 results but not in the top 20 may be injected.

2. **Tag values are not sanitized in output** (line 357): The output line `- [CAT] title -> path #tags:tag1,tag2` sanitizes the title but not the tags. Tags containing ` -> ` could break the index line format in downstream parsing.

3. **Index rebuild runs without authentication** (lines 222-231): The rebuild subprocess inherits the current Python interpreter and file permissions. A malformed JSON file in the memory directory could cause the rebuild to emit warnings to stderr but will not crash the retrieval script (rebuild errors are silently swallowed).

4. **Config integrity not checked** (lines 240-265): `memory-config.json` is parsed with no checksum or signing. A modified config with `retrieval.enabled: false` or `max_inject: 0` will silently disable retrieval.

5. **`match_strategy` config key is a no-op in the script**: The `"title_tags"` value in the default config suggests future strategies might be implemented but are not currently enforced. All runs use the full title+tags+description pipeline.

6. **`memory_retrieve.py` note on `retrieval.enabled` field**: The config schema does not include `retrieval.enabled` in the default config (`assets/memory-config.default.json`), yet the script checks for it at line 245. The key defaults to `True` via `retrieval.get("enabled", True)` if absent, so this is safe but documents an undocumented config key.
