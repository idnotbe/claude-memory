# Retrieval System Security Analysis

**Date:** 2026-02-19
**Scope:** memory_retrieve.py, memory_write.py (write-side), memory_index.py (index rebuild)
**Focus:** Security vulnerabilities, edge cases, and defense-in-depth assessment

---

## 1. Prompt Injection via Memory Titles

### 1.1 Retrieval-Side Sanitization (`_sanitize_title` in memory_retrieve.py)

The `_sanitize_title` function (lines 183-195) applies the following transformations in order:

1. Strip ASCII control characters `[\x00-\x1f\x7f]`
2. Strip zero-width, bidirectional override, and Unicode tag characters
   `[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]`
3. Strip index-format injection markers: ` -> ` replaced with ` - `; `#tags:` replaced with empty string
4. Escape XML-sensitive characters: `&`, `<`, `>`, `"` to HTML entities
5. Strip and truncate to 120 characters

This function is called in two places:
- Line 347: sanitizing category descriptions for the `descriptions="..."` XML attribute
- Line 354: sanitizing each entry title before emission

### 1.2 Write-Side Sanitization (`auto_fix` in memory_write.py)

The `auto_fix` function (lines 246-332) sanitizes titles at lines 298-306:

1. Strip ASCII control characters `[\x00-\x1f\x7f]` and `.strip()`
2. Replace ` -> ` with ` - ` and remove `#tags:` substring

**Gaps compared to retrieval-side:**
- **No Unicode bidirectional override stripping** at write time. A title written with bidirectional control characters (e.g., `\u202e`, right-to-left override) passes through `auto_fix` unchallenged, persists in JSON and index.md, and only gets stripped when read by `_sanitize_title` during retrieval. This is defense-in-depth working correctly but the gap is noteworthy.
- **No XML entity escaping** at write time. The JSON title field may contain `<`, `>`, `&`, `"`. These are only escaped during retrieval output assembly (fine, since the XML context only exists at retrieval time).
- **No truncation to 120 chars** at write time in `auto_fix`. Pydantic's `Field(max_length=120)` enforces the limit during validation, but auto_fix itself does not pre-truncate. If validation runs after auto_fix, this is fine. Reviewing the flow: `auto_fix` is called first, then `validate_memory` is called. Pydantic rejects titles over 120 chars. So validation acts as the enforcer, not auto_fix. However, this means auto_fix's whitespace-strip could expose a title that was exactly 120 chars of spaces + content: `stripped = data[field].strip()[:120]` — wait, auto_fix's whitespace strip does NOT truncate; it only strips surrounding whitespace. The 120-char truncation in `_sanitize_title` at line 194 (`title.strip()[:120]`) is retrieval-only. This means a title up to 120 chars on write but not stripped during retrieval until after XML escaping could expand beyond 120 chars due to entity expansion.

**Example:** A title of exactly 120 chars containing 60 `&` characters would expand to `&amp;` (5 chars each), resulting in 120 - 60 + 300 = 360 chars in the output. The truncation on line 194 happens BEFORE XML escaping on line 192, so this does not apply. Let's re-read the order:

```python
def _sanitize_title(title: str) -> str:
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)           # step 1
    title = re.sub(r'[unicode...]', '', title)                 # step 2
    title = title.replace(" -> ", " - ").replace("#tags:", "") # step 3
    title = title.replace("&", "&amp;").replace("<", "&lt;")   # step 4 (XML escape)
    title = title.strip()[:120]                                # step 5 (truncate)
```

Truncation happens AFTER XML escaping. A title with 120 chars (all `&`) becomes 600 chars of `&amp;` entities, then gets truncated to the first 120 chars of that escaped form (`&amp;&amp;&amp;...`). This means the output title may be syntactically incomplete HTML entities: `&amp;&amp;...&amp` (truncated mid-entity). This is cosmetic, not a security issue, but it is a functional bug. The truncation should happen before XML escaping, not after.

### 1.3 Index Rebuild — Does `memory_index.py` Sanitize Titles?

**No. This is a confirmed gap.**

In `memory_index.py`, `rebuild_index` (lines 89-116) reads titles directly from JSON `data.get("title", json_file.stem)` at line 69 and writes them to `index.md` verbatim:

```python
line = f"- [{m['display']}] {m['title']} -> {m['path']}"
```

No sanitization is applied. If a JSON file has been hand-edited or written via a means bypassing `memory_write.py`, a title containing ` -> ` or `#tags:` will corrupt the index format. A title like `foo -> /etc/passwd #tags:injected` would produce an index line that parses as title=`foo`, path=`/etc/passwd`, tags=`injected`.

The CLAUDE.md documents this: "Remaining gap: memory_index.py rebuilds index from JSON without re-sanitizing (trusts write-side sanitization)." This is a known and accepted gap. It relies entirely on the assumption that all writes flow through `memory_write.py`.

**Attack scenario:** An attacker who can write directly to a JSON file in the memory directory (bypassing `memory_write_guard.py`) could craft a title that, after index rebuild, produces a manipulated index entry pointing to an arbitrary path.

### 1.4 Tag Sanitization in the Retrieval Output

Tags are written to the output at line 356:

```python
tags_str = f" #tags:{','.join(sorted(tags))}" if tags else ""
print(f"- [{entry['category']}] {safe_title} -> {entry['path']}{tags_str}")
```

Tags are **not passed through `_sanitize_title`** before being emitted. Tags come from the parsed index line (via `parse_index_line`, which splits on commas and `.strip().lower()`). While `.lower()` and `.strip()` are applied, tags are not sanitized for:
- Control characters
- Unicode bidirectional overrides
- XML-sensitive characters (`<`, `>`, `&`, `"`)

**Concrete injection risk:** A tag value of `<script>` or `</memory-context>` would appear literally in the output. Tags containing `"` would appear literally in the text line (not in an attribute, so `"` is not an XML-attribute-injection vector here). However, `</memory-context>` in a tag could terminate the output XML block prematurely.

Write-side tag sanitization in `auto_fix` (lines 309-325) does strip control characters and remove `,`, ` -> `, `#tags:`, but it does NOT strip `<`, `>`, `&`, or Unicode bidirectional characters from tags.

**Severity:** Moderate. Tags can contain `</memory-context>` to break out of the data boundary block, or contain LLM-interpretable instructions.

### 1.5 Category Field in Output

At line 357:
```python
print(f"- [{entry['category']}] {safe_title} -> {entry['path']}{tags_str}")
```

The `entry["category"]` comes from the parsed index line (via regex group 1: `[A-Z_]+`). The regex `_INDEX_RE` restricts category to `[A-Z_]+`, so injection through category is not possible. This is correctly constrained.

### 1.6 Path Field in Output

The `entry["path"]` is also emitted without sanitization (line 357). Paths come from the index and are constrained by the `(\S+)` group in `_INDEX_RE` (no whitespace). However, a path containing `</memory-context>` is impossible since it would require whitespace. A path containing XML characters like `<` would need to be a filesystem path containing `<`, which is valid on Linux but unusual. Not a practical concern, but technically unsanitized.

---

## 2. Index Format Fragility

### 2.1 Delimiter Parsing: ` -> ` and `#tags:`

The regex in `memory_retrieve.py` (line 45-48):

```python
_INDEX_RE = re.compile(
    r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)"
    r"(?:\s+#tags:(.+))?$"
)
```

The title group `(.+?)` is lazy and stops at the first ` -> `. This means:
- A title containing ` -> ` (e.g., `foo -> bar`) will be parsed as `title="foo"`, `path="bar"`. The actual intended path would be lost or misassigned.
- This is precisely why write-side sanitization replaces ` -> ` with ` - `. If sanitization is bypassed, the index line is corrupted.

**Validation:**
- `memory_validate_index` in `memory_index.py` uses `line.split(" -> ", 1)[1]` (line 133) — the `, 1` means it splits on the first ` -> ` only, extracting everything after as path+tags. This would yield `bar #tags:something` as the path for a title like `foo -> bar`, and then `path_part = after_arrow.split(" #tags:")[0].strip()` would get `bar`. So validation would believe the path is `bar` while the JSON is at the real path. This would cause a false "stale entry" report.

**Impact:** Title containing ` -> ` causes:
1. In `parse_index_line`: title is truncated, path is wrong
2. In `validate_index`: index appears desynced (false negative)
3. In `rebuild_index`: the corrupted index line is written; this is the real corruption source

### 2.2 `#tags:` in Title

A title containing the literal string `#tags:` (e.g., `"Remember to use #tags: for organization"`) would be handled by write-side sanitization (removes `#tags:`), so under normal write flow this string is stripped. However, the result might be surprising to the user: their title becomes `"Remember to use  for organization"`.

If the index is rebuilt from a hand-edited JSON file containing `#tags:` in the title, the index line becomes:

```
- [DECISION] Remember to use #tags: for organization -> .claude/memory/decisions/foo.json #tags:tag1
```

Parsing this: the `#tags:` group in the regex would match `#tags: for organization -> .claude/memory/decisions/foo.json #tags:tag1` as the tags value, and the path group `(\S+)` would get the text before it. This could cause unpredictable behavior depending on the position of `#tags:` in the title vs. the actual `#tags:` suffix.

### 2.3 Malformed Index Lines Causing Crashes

In `parse_index_line`, the code uses `_INDEX_RE.match(line.strip())` and returns `None` on no match. Lines that don't match are silently skipped. No exceptions are raised.

In `validate_index` and `health_report`, parsing uses simpler string operations:
- `line.split(" -> ", 1)[1]` — would raise `IndexError` if ` -> ` is absent, but the guard `" -> " in line` is checked first (line 131).
- `after_arrow.split(" #tags:")[0]` — safe, returns full string if `#tags:` absent.

**No crash paths identified** in the main parsing code. The regex-based approach in the retrieval script is robust to malformed lines (returns None silently).

### 2.4 Extremely Long Index Lines

No line-length limits are enforced during index parsing. A crafted index entry with a very long title (e.g., 1 MB) would consume memory during parsing. The 120-char title limit enforced by Pydantic limits practical title length during normal write operations, but a hand-edited JSON or bypassed write could introduce long titles. This is a low-severity theoretical denial of service.

---

## 3. Config Manipulation

### 3.1 `max_inject` Clamping

In `memory_retrieve.py` (lines 247-255):

```python
raw_inject = retrieval.get("max_inject", 5)
try:
    max_inject = max(0, min(20, int(raw_inject)))
except (ValueError, TypeError, OverflowError):
    max_inject = 5
```

**Edge cases tested:**
- `max_inject = -1` → clamped to `0`, retrieval exits immediately at line 267 (`if max_inject == 0`)
- `max_inject = 999` → clamped to `20`
- `max_inject = "abc"` → ValueError caught, falls back to `5`
- `max_inject = null` (JSON null → Python None) → `int(None)` raises TypeError, caught, falls back to `5`
- `max_inject = 3.7` → `int(3.7)` = 3, accepted
- `max_inject = 1e308` (very large float) → `int(1e308)` succeeds in Python (arbitrary precision int), then `min(20, ...)` clamps to 20. No overflow.
- `max_inject = "0x10"` → `int("0x10")` raises ValueError (int() without base= doesn't parse hex), caught, falls back to 5.
- `max_inject = true` (JSON boolean → Python True) → `int(True)` = 1, accepted and used. This is an undocumented but harmless edge case.

**The `OverflowError` catch is important:** `int(float("inf"))` raises OverflowError in Python. Without this catch, an `Infinity` value in the JSON config would crash the retrieval hook.

**Assessment:** Clamping is robust. The fallback to default 5 on parse failure is appropriate.

### 3.2 `retrieval.enabled = false`

If the config contains `"retrieval": {"enabled": false}`, the script exits at line 246 with `sys.exit(0)`. This silently disables retrieval entirely. An attacker who can modify `memory-config.json` can suppress all memory injection, effectively blinding the LLM to its stored context. This is a design-level concern: config integrity is not verified.

**Severity:** Low in typical use. High in adversarial scenario where an attacker controls the project directory.

### 3.3 Config Type Confusion

The category `descriptions` are loaded at lines 257-263:

```python
categories_raw = config.get("categories", {})
if isinstance(categories_raw, dict):
    for cat_key, cat_val in categories_raw.items():
        if isinstance(cat_val, dict):
            desc = cat_val.get("description", "")
            if isinstance(desc, str) and desc:
                category_descriptions[cat_key.lower()] = desc[:500]
```

Type guards (`isinstance(categories_raw, dict)`, `isinstance(cat_val, dict)`, `isinstance(desc, str)`) prevent crashes on malformed config. The `desc[:500]` truncation limits description length. This is well-written defensive code.

**Gap:** The category descriptions are passed through `_sanitize_title` before being embedded in the `descriptions="..."` XML attribute (lines 343-350). However, the attribute assembly uses string concatenation:

```python
desc_attr = " descriptions=\"" + "; ".join(desc_parts) + "\""
```

A description containing `"` would be XML-entity-escaped by `_sanitize_title` (to `&quot;`), so attribute injection is prevented. A description containing `; ` (semicolon + space) would be indistinguishable from the separator between categories — but this is a cosmetic parsing ambiguity in how an LLM reads the attribute, not a formal injection.

### 3.4 `grace_period_days` in `memory_index.py`

In `gc_retired` (line 203):

```python
grace_period_days = config.get("delete", {}).get("grace_period_days", 30)
```

No type checking or clamping is applied. If this is set to `0` or a negative number, any retired memory is immediately eligible for GC. If set to a very large number, GC never runs. If set to a non-integer (e.g., `"thirty"`), the comparison `age_days >= grace_period_days` would raise a TypeError at runtime.

**Concrete bug:** `grace_period_days = "30"` (string) → `age_days >= "30"` → TypeError in Python 3 (cannot compare int and str). This would crash `gc_retired` silently (the caller prints to stderr but doesn't propagate the exception). Actually the caller in `main()` does not wrap `gc_retired` in a try/except, so this would propagate as an unhandled exception and exit with a traceback. Low severity since GC is a manual operation.

---

## 4. File System Concerns

### 4.1 Path Traversal

In `memory_retrieve.py` (lines 314-319):

```python
project_root = memory_root.parent.parent
for text_score, priority, entry in scored[:_DEEP_CHECK_LIMIT]:
    file_path = project_root / entry["path"]
    is_retired, is_recent = check_recency(file_path)
```

The `entry["path"]` comes from the parsed index line via the `(\S+)` group. This path is joined directly with `project_root` without validation.

**Traversal test:** An index entry with path `.claude/memory/../../etc/passwd` would survive the `\S+` regex (no whitespace), and `project_root / ".claude/memory/../../etc/passwd"` would resolve to `project_root / "etc/passwd"` — but `project_root` is already 2 levels above the memory root (i.e., the project root), so this would resolve to `<project_root>/etc/passwd`, not `/etc/passwd`.

However: `project_root / "../../../../etc/passwd"` — Python's `Path.__truediv__` does NOT prevent `..` traversal. `Path("/home/user/project") / "../../../../etc/passwd"` resolves to `/etc/passwd` when `.resolve()` is called, but without `.resolve()` it yields `/home/user/project/../../../../etc/passwd` as a logical path object. `open()` on this path will follow the `..` components and access `/etc/passwd`.

**This is a real path traversal vulnerability in `check_recency`.**

If an attacker can write an index entry with a path like `../../../../etc/passwd`, then `check_recency` would attempt to `open()` and `json.load()` that file. The file would likely fail `json.JSONDecodeError` and return `(False, False)` harmlessly. But the read attempt itself is a traversal.

**Practical impact:** The attacker must first control `index.md`. Normally this file is only modified by `memory_write.py` (via the write guard). But if `index.md` is `.gitignored` and rebuilt from JSON files that can be hand-edited, or if the write guard is bypassed, this becomes exploitable. Reading `/etc/passwd` as JSON would fail silently; reading a crafted JSON file outside the memory directory would succeed and its `record_status` / `updated_at` fields would influence retrieval scoring and retired-status filtering. **No file contents are injected into the LLM context** from `check_recency` — only boolean flags are returned — so this is a low-impact traversal (information disclosure limited to boolean leakage).

**Fix recommendation:** Add `path_check = (project_root / entry["path"]).resolve()` and verify it is within `project_root.resolve()` before opening.

### 4.2 Deep-Check Limit Bypass

Entries beyond `_DEEP_CHECK_LIMIT = 20` (line 54) are included without a deep check:

```python
# Also include entries beyond deep-check limit (no recency bonus, assume not retired)
for text_score, priority, entry in scored[_DEEP_CHECK_LIMIT:]:
    final.append((text_score, priority, entry))
```

This means entries ranked 21st or lower by text score bypass retired-status filtering. A retired entry that scores moderately (not in the top 20) could appear in the output. This is an accepted performance tradeoff, but the comment "assume not retired" is a documented false assumption. In practice, retired entries are removed from the index immediately by `memory_write.py` (via `remove_from_index`), so this gap only manifests if the index is stale (e.g., hand-edited or rebuilt with `--include-inactive`).

### 4.3 Race Conditions During Index Read

`memory_retrieve.py` reads `index.md` line by line (lines 272-279) without any locking:

```python
with open(index_path, "r", encoding="utf-8") as f:
    for line in f:
        parsed = parse_index_line(line)
        if parsed:
            entries.append(parsed)
```

If `memory_write.py` is performing an atomic write to `index.md` via `os.rename()` (via `atomic_write_text`) concurrently, the reader could:
- Get a partial/old file if the rename hasn't happened yet (reads old content) — acceptable
- Get an empty/corrupt file if the rename is in progress — the `parse_index_line` regex would just return None for unrecognized lines, and the retrieval would silently return no results for this invocation

The `atomic_write_text` function uses `os.rename()` which is atomic on POSIX systems. The reader opens the file before the rename completes, so it reads the old complete file. This is safe on POSIX. On Windows, `os.rename()` may not be atomic, but the plugin targets Linux/Mac.

**Assessment:** No significant race condition risk on POSIX systems due to atomic rename.

### 4.4 Corrupted JSON Memory Files

In `check_recency` (lines 153-157):

```python
try:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except (OSError, json.JSONDecodeError):
    return False, False
```

Corrupted JSON returns `(False, False)` — treated as "not retired, not recent." This means a corrupted memory file remains in the retrieval results (not filtered as retired). The entry's title still comes from the index, not the JSON file, so no malformed content from the JSON is injected. **Safe.**

In `memory_index.py`'s `scan_memories` (lines 84-85):

```python
except (json.JSONDecodeError, KeyError) as e:
    print(f"WARNING: Could not parse {json_file}: {e}", file=sys.stderr)
```

Corrupted files are skipped during index rebuild with a warning to stderr. **Safe.**

---

## 5. Data Boundary Markers

### 5.1 `<memory-context>` XML Block Structure

The output block is:

```python
print(f"<memory-context source=\".claude/memory/\"{desc_attr}>")
for _, _, entry in top:
    safe_title = _sanitize_title(entry["title"])
    tags = entry.get("tags", set())
    tags_str = f" #tags:{','.join(sorted(tags))}" if tags else ""
    print(f"- [{entry['category']}] {safe_title} -> {entry['path']}{tags_str}")
print("</memory-context>")
```

**Breakout via `safe_title`:** After `_sanitize_title`, `<` and `>` in titles are escaped to `&lt;` and `&gt;`. A title cannot contain the literal `</memory-context>` string — it would become `&lt;/memory-context&gt;`. **Title-based breakout is prevented.**

**Breakout via `tags_str`:** Tags are NOT XML-escaped. A tag value of `</memory-context>` would appear literally in the output:

```
- [DECISION] My title -> path/file.json #tags:</memory-context>
```

This closes the `<memory-context>` block mid-line. Any content emitted after this line (remaining entries) would appear outside the `<memory-context>` block. This is a **real data boundary breakout**.

Write-side tag sanitization removes commas, ` -> `, `#tags:`, and control characters — but does NOT remove `<`, `>`, or `/`. The string `</memory-context>` contains only valid printable ASCII and would pass through `auto_fix` tag sanitization unchanged.

**Severity:** Moderate. An attacker who can store a memory with a tag of `</memory-context>` (which `memory_write.py` allows since it only lowercases and strips the listed characters) can:
1. Break out of the data boundary
2. Cause subsequent retrieval entries to appear as free text in the LLM's context, outside the labeled memory block
3. Potentially inject additional context that appears to come from a different source

**Fix:** Apply XML escaping to tags before emitting them.

### 5.2 `descriptions` Attribute Injection

The `desc_attr` is built as:

```python
desc_attr = " descriptions=\"" + "; ".join(desc_parts) + "\""
```

Where each `desc_part` is `f"{cat_key}={safe_desc}"` and `safe_desc = _sanitize_title(desc)`.

Since `_sanitize_title` escapes `"` to `&quot;`, a description containing `"` cannot break out of the attribute. A description containing `>` becomes `&gt;` and cannot close the opening XML tag. **This is safe.**

However, the `cat_key` values (e.g., `decision`, `constraint`) come from the config dict keys and are not sanitized. They are lowercased but could contain `=` or `"` characters if the config has unusual keys. In practice, the config is application-controlled and uses fixed category names, but this is a theoretical gap.

### 5.3 Unicode Normalization

`_sanitize_title` strips specific Unicode ranges but does not apply Unicode normalization (NFC/NFKC). Visually identical Unicode sequences (e.g., composed vs. decomposed characters) are not normalized. This is unlikely to affect security in a text-matching context but could affect the perceived vs. actual length of a title.

---

## 6. Defense-in-Depth Assessment

### Summary Matrix

| Security Property | Write Side | Index Rebuild | Retrieval Side | Overall |
|---|---|---|---|---|
| Control char stripping (title) | Yes (auto_fix) | No | Yes (_sanitize_title) | Partial gap in rebuild |
| BiDi/Unicode stripping (title) | No | No | Yes (_sanitize_title) | Gap: write + rebuild miss BiDi |
| ` -> ` injection prevention | Yes (auto_fix) | No | Yes (_sanitize_title) | Partial: rebuild trusts write |
| `#tags:` in title prevention | Yes (auto_fix) | No | Yes (_sanitize_title) | Same as above |
| XML escaping (title) | No | No | Yes (_sanitize_title) | Correct: only needed at output |
| XML escaping (tags) | No | No | No | **Gap: tags unsanitized in output** |
| Path traversal check (write) | Yes (containment check) | N/A | No (deep check) | Gap in retrieval |
| Retired entry filtering | N/A | Filters by default | Top-20 only | Gap beyond deep-check limit |
| max_inject clamping | N/A | N/A | Yes, robust | Good |
| Config type safety | N/A | Partial (grace_period) | Yes (descriptions) | Minor gap in gc_retired |
| Race condition protection | Atomic rename | N/A | No lock | Acceptable (POSIX rename atomic) |
| Boundary marker integrity | N/A | N/A | Title safe, tags not | **Gap: tags can break boundary** |

### Confirmed Vulnerabilities

**1. Tag XML Injection / Boundary Breakout (Moderate)**
File: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`, line 356

Tags are emitted without XML escaping. A tag value of `</memory-context>` breaks out of the data boundary block. This is exploitable by anyone who can successfully write a memory entry with such a tag. Write-side tag sanitization (`auto_fix` in `memory_write.py`) removes commas, arrows, and `#tags:` but does NOT strip `<`, `>`, or other XML-significant characters.

**Fix:** Change line 356 in `memory_retrieve.py` to apply HTML entity escaping to individual tag values before emitting them.

**2. Path Traversal in `check_recency` (Low Impact)**
File: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`, lines 317-319

`entry["path"]` from the index is joined with `project_root` without containment validation. A path like `../../../../etc/passwd` would cause a file open attempt outside the memory directory. Practical impact is limited since: (a) failed JSON parse returns `(False, False)` harmlessly, and (b) a successful read only leaks boolean values. No file content is injected into LLM context.

**Fix:** Resolve and validate `file_path.resolve()` is within `project_root.resolve()` before calling `check_recency`.

**3. Index Rebuild Does Not Sanitize Titles (Low, Design-Level Gap)**
File: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py`, line 104

This is a known and documented gap. The security relies on the assumption that all writes go through `memory_write.py`. If that assumption holds, this gap is theoretical.

### Theoretical Concerns (Not Practical Vulnerabilities)

**4. Truncation After XML Escape in `_sanitize_title` (Cosmetic Bug)**
The `title.strip()[:120]` truncation at line 194 of `memory_retrieve.py` occurs after XML entity expansion. A title of 120 characters consisting entirely of `&` characters expands to 600 characters, then gets truncated to 120 characters of `&amp;&amp;...&am` — a broken HTML entity at the end. Not a security issue, but a correctness bug. Fix: truncate BEFORE XML escaping, or truncate the final output to 120 chars post-expansion.

**5. Bidirectional Character Gap on Write Side (Defense-in-Depth Concern)**
Write-side `auto_fix` does not strip BiDi override characters from titles. These characters survive into the JSON and index. `_sanitize_title` catches them on retrieval. The defense-in-depth is present but incomplete at the first layer.

**6. `grace_period_days` Type Confusion in `gc_retired` (Low)**
File: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py`, line 203

No type validation on `grace_period_days` from config. A string value causes a TypeError on comparison. Low severity as `--gc` is a manual operation.

**7. Entries Beyond Deep-Check Limit Bypass Retired Filter (Design Tradeoff)**
File: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`, lines 329-331

Entries ranked 21st+ by text score skip the retired-status check. In normal operation, retired entries are removed from the index immediately, so this gap is only theoretical with a stale index.

### Overall Security Posture Rating

**Posture: ADEQUATE with two specific gaps requiring fixes**

The system demonstrates solid defense-in-depth thinking:
- Multiple sanitization layers (write-side, rebuild-side conceptually, retrieval-side)
- Atomic writes preventing partial reads
- Pydantic schema validation enforcing structural integrity
- Path containment checks on write operations
- `max_inject` clamping with proper overflow/type-error handling
- XML escaping for the main title output

The two gaps that warrant fixing before the system can be called hardened are:
1. Tag values emitted without XML escaping, enabling `</memory-context>` breakout
2. Path traversal in `check_recency` (low impact but cleanable)

The known design gap (index rebuild trusts write-side sanitization) is acceptable given the write guard architecture, but represents a single point of failure for the entire sanitization chain.
