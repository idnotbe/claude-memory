# V2 Adversarial Review: Memory Notification Code

**Date:** 2026-02-28
**Reviewer:** v2-adversarial (Claude Opus 4.6)
**Cross-model:** Gemini 3 Pro Preview (via PAL clink, codereviewer role)
**Files reviewed:**
- `hooks/scripts/memory_retrieve.py` (lines 422-494, 3 notification blocks)
- `skills/memory-management/SKILL.md` (Pre-Phase ~38-54, Phase 0 ~56-59, Post-save ~235-260)
- `tests/test_memory_retrieve.py` (21 new tests across 3 classes)

**Test results:** 116/116 PASS (1.66s)
**V1 bugs fixed:** All 4 (BUG-1 error formatting, BUG-2 atomic write, BUG-3 misleading message, BUG-4 post-save order)

---

## Adversarial Findings

### ADV-1: Heredoc Delimiter Collision (MEDIUM, attacker-requires-LLM-cooperation)

**Location:** `SKILL.md:246-254` (post-save heredoc)
**Vector:** The SKILL.md instructs the LLM to write JSON via `cat > file <<'RESULT_EOF' ... RESULT_EOF`. If a memory title or error message contains the literal string `RESULT_EOF` on its own line, the shell terminates the heredoc early. Remaining content is interpreted as shell commands.
**Attack path:** Attacker creates a project file named `RESULT_EOF` or embeds it in content. The LLM incorporates it into a memory title. When the post-save heredoc fires, the delimiter terminates early and remaining JSON becomes shell input.
**Mitigating factors:**
- `<<'RESULT_EOF'` (single-quoted) prevents variable expansion -- good.
- The LLM generates this content, not the user directly. The LLM would need to literally place `RESULT_EOF` on a line by itself inside the JSON value.
- `memory_write.py` sanitizes titles to max 120 chars, strips control chars, but does NOT filter specific strings like `RESULT_EOF`.
- The heredoc is in a template shown to an LLM as instructions. The LLM replaces `<ISO 8601 UTC>` etc. with actual values. Practical exploitation requires prompt injection into a memory title.
**Severity: MEDIUM** -- requires two-step attack (inject into memory content + LLM cooperation), but the impact is arbitrary command execution if successful.
**Recommendation:** Use a more unique delimiter (e.g., `__CLAUDE_SAVE_RESULT_EOF_7f3a__`) to reduce collision probability. Alternatively, use `printf '%s' '...' > file` instead of heredoc, or use Python to write the file directly.

### ADV-2: Global Result File Cross-Session Theft (MEDIUM, design trade-off)

**Location:** `memory_retrieve.py:425` (reader) + `SKILL.md:244-255` (writer)
**Vector:** `~/.claude/last-save-result.json` is global. If two Claude Code sessions run concurrently in different projects:
1. Session A saves in Project-X, writes result file
2. Session B (Project-Y) fires its retrieval hook first, reads the file, shows "Memories saved in project: Project-X"
3. Session B's `finally` block deletes the file
4. Session A's retrieval hook finds no file -- notification silently lost

**Impact:**
- Session B shows a brief cross-project note (benign information leak: project directory basename only, via `Path.name`)
- Session A silently misses its save confirmation (functional loss)
- `_just_saved` flag is set in Session B, suppressing its Block 2 orphan detection (incorrect state)

**Mitigating factors:**
- This was an intentional design choice (V2 Contrarian Finding 4 chose global path for cross-project visibility)
- Cross-project note only shows `Path.name` (basename), not full path
- The `_just_saved` suppression is only for the orphan message -- no data loss

**Severity: MEDIUM** -- functional notification loss for original session, but no data corruption.
**Recommendation:** Document as known limitation. If concurrent multi-project usage is common, consider per-project scoping (e.g., `last-save-result-<hash>.json`). Current design is acceptable for single-session-at-a-time usage pattern.

### ADV-3: Future Timestamp Bypasses 24h Expiration (LOW)

**Location:** `memory_retrieve.py:436-437`
**Vector:** If `saved_at` is a future timestamp (LLM hallucination, clock skew, NTP correction), `_age_secs` becomes negative. Negative values satisfy `< 86400`, so the notification is shown.
**Impact:** A stale result file with a future timestamp will display indefinitely until consumed. This is purely cosmetic -- the file is still deleted (one-shot), so it shows once.
**Severity: LOW** -- one extra benign notification, then the file is gone.
**Recommendation:** Add `0 <= _age_secs < 86400` to reject future timestamps. Minimal effort but very low impact.

### ADV-4: Malformed Pending File Permanent Suppression (LOW, self-recovering)

**Location:** `memory_retrieve.py:486-487` (Block 3)
**Vector:** If `.triage-pending.json` is 0 bytes, a JSON array, or other non-dict JSON, then:
- 0 bytes: `json.loads("")` raises `JSONDecodeError`, caught by `except Exception: pass`
- JSON array: `[1,2].get("categories", [])` raises `AttributeError`, caught by `except Exception: pass`
- Result: Block 3 silently fails, pending file stays on disk, notification never shown

**Impact:** The "pending save" notification is suppressed until the user manually deletes the file or runs `/memory:save` (which cleans staging in Pre-Phase).
**Mitigating factors:**
- The `.triage-pending.json` writer doesn't exist yet (Phase 4 not implemented) -- this is currently dormant code
- Running `/memory:save` cleans it up via Pre-Phase
- Block 2 orphan detection would still fire if triage-data.json is also present and old

**Severity: LOW** -- dormant code path, self-recovering via `/memory:save`.
**Recommendation:** Add `isinstance(_pending_data, dict)` guard after `json.loads` for defense-in-depth. Not urgent since the writer doesn't exist yet.

### ADV-5: Control Characters in `<memory-note>` Output (LOW)

**Location:** `memory_retrieve.py:444-460` (Block 1 output)
**Vector:** `html.escape()` handles `<`, `>`, `&`, `"`, `'` but NOT control characters (null bytes, newlines, ESC, etc.). If a memory title contains `\x00`, `\n`, `\r`, or ANSI escape sequences, these pass through into the `<memory-note>` output.
**Impact:** Could potentially break Claude's XML tag parser or inject terminal escape sequences. In practice, `memory_write.py` sanitizes titles (strips control chars), so this would require a corrupted JSON file.
**Severity: LOW** -- defense-in-depth only; upstream sanitization already handles this.
**Recommendation:** No change needed. Title sanitization in `memory_write.py` is the correct layer for this.

### ADV-6: Path Comparison String Equality (LOW, platform-specific)

**Location:** `memory_retrieve.py:443` (`if _save_project == cwd:`)
**Vector:** Strict string equality fails for:
- Trailing slashes: `/home/user/project` != `/home/user/project/`
- Symlinked paths: `/home/user/link` != `/home/user/actual`
- Case differences (macOS HFS+): `/Users/Bob/Proj` != `/users/bob/proj`

**Impact:** User sees the generic "Memories saved in project: X" instead of the detailed confirmation. Cosmetic only.
**Mitigating factors:**
- Both `cwd` (from Claude Code hook input) and `_save_project` (from SKILL.md writing `cwd`) originate from the same Claude Code session's working directory via consistent mechanisms
- In practice, Claude Code provides consistent `cwd` without trailing slashes
- Linux (the primary target platform) is case-sensitive and doesn't have this issue

**Severity: LOW** -- cosmetic fallback, not functional failure.
**Recommendation:** Could use `Path(x).resolve() == Path(y).resolve()` for robustness, but not necessary given consistent upstream sources.

### ADV-7: Block 2/Block 3 TOCTOU Race (NEGLIGIBLE)

**Location:** `memory_retrieve.py:472-494`
**Vector:** Block 2 checks `not _triage_pending_path.exists()` and fires orphan warning. If `.triage-pending.json` is created between Block 2's check (line 474) and Block 3's check (line 485), both blocks fire: "Orphaned triage data" AND "Pending memory save" -- contradictory messages.
**Impact:** User sees two contradictory messages in the same prompt. Both are informational only.
**Probability:** Requires another process to create `.triage-pending.json` in the microsecond window between Block 2 and Block 3 execution. Practically impossible with current architecture (no writer for this file exists yet).
**Severity: NEGLIGIBLE** -- theoretical only, no writer exists, both messages are benign.

---

## Race Condition Analysis

| Scenario | Impact | Probability | Verdict |
|----------|--------|------------|---------|
| Two sessions read/write `last-save-result.json` simultaneously | One session steals other's notification | Low (requires concurrent saves) | ACCEPTABLE (ADV-2) |
| Save completes between Block 1 and Block 2 | `_just_saved=False`, new triage-data.json too recent for orphan (< 300s) | Very low | SAFE (age check protects) |
| `triage-data.json` written while Block 2 reads mtime | `.stat().st_mtime` is atomic on POSIX | Very low | SAFE |
| Concurrent unlink of result file | `unlink(missing_ok=True)` is TOCTOU-safe | Low | SAFE |
| Block 2/Block 3 TOCTOU | Contradictory messages | Negligible | SAFE (ADV-7) |

## File System Edge Case Analysis

| Scenario | Behavior | Verdict |
|----------|----------|---------|
| Disk full (can't write result file) | SKILL.md `cat > ... && mv` fails; no result file created. Block 1 sees nothing. Block 2 detects orphan after 5min. | SAFE |
| Permission denied on `~/.claude/` | Block 1 outer `except Exception: pass` catches. No notification, no crash. | SAFE |
| Symlink `last-save-result.json` | `unlink(missing_ok=True)` removes the symlink, not the target. Read follows symlink (potential info read from unexpected location, but content is still validated as JSON with specific schema). | ACCEPTABLE |
| `last-save-result.json` is a directory | `read_text()` raises `IsADirectoryError`, caught by inner try's implicit propagation to outer `except Exception: pass`. `_just_saved=True` but `finally` `unlink` fails on directory (caught by outer). | SAFE |
| NFS/network latency | `.exists()` + `.read_text()` may see stale cache. Worst case: miss a notification or show a stale one. | ACCEPTABLE |
| Zero-byte file from truncated write | Atomic write-then-rename (BUG-2 fix) prevents this. Old race window eliminated. | SAFE |

## Malicious Input Analysis

| Vector | Mitigation | Status |
|--------|-----------|--------|
| Project paths with HTML/XML tags | `html.escape()` + `Path.name` for cross-project | MITIGATED |
| Adversarial category names | `html.escape(str(c))` | MITIGATED |
| Adversarial titles | `html.escape(str(t))` | MITIGATED |
| Adversarial error messages | `isinstance(dict)` check + `html.escape()` | MITIGATED |
| JSON with unexpected types (`categories` as string) | `if _save_categories` guards iteration; `isinstance` check in Block 3 | MITIGATED |
| Prompt injection via `<memory-note>` tag nesting | `html.escape()` escapes `<` and `>` | MITIGATED |
| Control chars in titles | `html.escape` does not strip, but `memory_write.py` sanitizes upstream | ACCEPTABLE |
| RESULT_EOF in heredoc content | See ADV-1 -- partial mitigation via LLM abstraction layer | PARTIALLY MITIGATED |

## SKILL.md Logic Analysis

| Question | Answer |
|----------|--------|
| Pre-Phase guard avoids fresh data deletion? | YES -- guard condition: "Only run when **no** triage tags present." During auto-save, triage tags ARE present, so Pre-Phase is skipped. |
| Atomic write instruction clear for LLM? | YES -- explicit `cat > ... <<'RESULT_EOF' ... mv -f` pattern with explanation. |
| Can RESULT_EOF appear in data? | See ADV-1 -- theoretically yes, practically unlikely with LLM as intermediary. |
| Post-save order correct? | YES -- clean staging first, then write result (BUG-4 fix). Eliminates false orphan window. |

## Cross-Model Validation Summary

### Gemini 3 Pro Preview Findings

| # | Gemini Severity | Finding | My Assessment |
|---|----------------|---------|---------------|
| 1 | Critical | Heredoc RESULT_EOF breakout | **VALID but MEDIUM** -- requires LLM cooperation + prompt injection chain. Not user-direct. See ADV-1. |
| 2 | High | Global state race condition | **VALID, MEDIUM** -- intentional design trade-off. See ADV-2. |
| 3 | Medium | Path comparison string equality | **VALID but LOW** -- consistent upstream sources. See ADV-6. |
| 4 | Medium | Malformed pending JSON permanent suppression | **VALID but LOW** -- dormant code path, self-recovering. See ADV-4. |
| 5 | Low | Cross-talk suppression via `_just_saved` | **VALID** -- corollary of ADV-2 (global file). Same risk profile. |
| 6 | Low | Future timestamp bypass | **VALID** -- See ADV-3. Cosmetic only. |

**Agreement:** All 6 Gemini findings are valid. I adjusted severity ratings based on practical exploitation difficulty and mitigating factors.

**Gemini findings I did NOT independently identify:** None -- full overlap.

**Findings I identified that Gemini missed:**
- ADV-5 (control chars in output) -- Gemini noted `html.escape` as positive but didn't flag the control char gap
- ADV-7 (Block 2/3 TOCTOU) -- Gemini noted mutual exclusivity as positive but didn't analyze the race window

---

## V1 Bug Fix Verification

| V1 Bug | Fix Applied? | Verified? |
|--------|-------------|-----------|
| BUG-1: Error schema mismatch | YES -- `isinstance(dict)` formatting at line 452 | YES -- test updated at line 1198 with dict schema |
| BUG-2: Non-atomic write race | YES -- `cat > .tmp && mv -f` at SKILL.md:246-255 | YES -- heredoc + mv pattern |
| BUG-3: Misleading pending message | YES -- "re-triage and save" at line 492 | YES -- test confirms wording |
| BUG-4: False orphan post-save order | YES -- clean staging first, then write result at SKILL.md:239-255 | YES -- order verified |

---

## Overall Verdict: **PASS**

### Rationale

All V1 bugs have been fixed. The 7 adversarial findings break down as:

| Severity | Count | Actionable? |
|----------|-------|------------|
| MEDIUM | 2 (ADV-1, ADV-2) | ADV-1: consider unique delimiter. ADV-2: document as known limitation. |
| LOW | 4 (ADV-3, ADV-4, ADV-5, ADV-6) | Minor defense-in-depth improvements, none blocking. |
| NEGLIGIBLE | 1 (ADV-7) | Theoretical only. |

**No blocking issues found.** The two MEDIUM findings are:
1. **ADV-1 (heredoc):** Requires a two-step attack chain (prompt injection into memory title + LLM faithfully reproducing the delimiter). The single-quoted delimiter prevents variable expansion. Risk is real but requires attacker to control LLM output, which is already a broader security concern beyond this specific code.
2. **ADV-2 (global file):** Intentional design trade-off for cross-project visibility. Acceptable for the common single-session usage pattern.

The core logic (fail-open, html.escape, one-shot deletion, `_just_saved` flag coordination, Block 2/3 mutual exclusion, atomic write) is architecturally sound. Security sanitization is comprehensive for the XML output context. All 116 tests pass.

### Optional Hardening (non-blocking, ordered by ROI)

1. **ADV-1:** Change `RESULT_EOF` to a more unique delimiter like `__CLAUDE_MEM_SAVE_RESULT_7f3a__` (1 minute, SKILL.md only)
2. **ADV-3:** Add `0 <=` lower bound to age check (1 line change)
3. **ADV-4:** Add `isinstance(_pending_data, dict)` guard in Block 3 (1 line change, future-proofing)
