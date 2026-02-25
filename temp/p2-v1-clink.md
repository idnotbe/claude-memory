# Plan #2 V1 Review -- External Model Security Opinions

**Date:** 2026-02-25
**Models consulted:** Codex 5.3 (codereviewer), Gemini 3.1 Pro (codereviewer)

---

## Codex 5.3 Assessment

### Findings (by severity)

**MEDIUM: Symlink hardening bypassed on platforms without O_NOFOLLOW**
- Lines: memory_logger.py:35, 154, 274
- `_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)` falls back to 0, meaning symlink protection is silently disabled on affected platforms.
- Fix: Treat missing O_NOFOLLOW as security downgrade; implement lstat/openat-style no-follow checks.

**MEDIUM: TOCTOU symlink race in cleanup_old_logs()**
- Lines: memory_logger.py:129, 136, 143
- `is_symlink()` then later `iterdir()/unlink()` has a race window where an attacker can swap entries.
- Fix: Use dirfd-based traversal (openat, fstatat, unlinkat).

**LOW: .last_cleanup check-then-act without locking**
- Lines: memory_logger.py:115, 150
- Concurrent processes can all run cleanup. Efficiency/consistency issue, not privilege escalation.
- Fix: Advisory lock file or atomic O_CREAT|O_EXCL lock creation.

**LOW: Query tokens logged at info level (not "paths only")**
- Lines: memory_retrieve.py:472 (query_tokens), memory_search_engine.py:501 (fts_query)
- User query material persists in logs at info level. Technically not "paths only."
- Fix: Move to debug level or redact/hash.

### Validated as Safe
1. Path traversal via _sanitize_category(): No practical bypass found. Regex is effective.
2. Secret residue: No memory titles/content logged at info in current call sites.
3. File permissions: 0o600 consistently applied on file creation.
4. Config injection: No code execution/path traversal possible through config.
5. POSIX safety: os.write() + fd closed in finally blocks.

---

## Gemini 3.1 Pro Assessment

### Findings (by severity)

**MEDIUM: Directory permissions over-permissive**
- Lines: memory_logger.py:151, 267
- `os.makedirs(..., exist_ok=True)` defaults to 0o777 (modified by umask). Permissive umask creates readable/writable directories for other users, enabling symlink attacks.
- Fix: Add `mode=0o700` to all `os.makedirs()` calls.

**MEDIUM: TOCTOU symlink race in log cleanup**
- Lines: memory_logger.py:126
- `is_symlink()` check before `iterdir()` has TOCTOU window. Attacker with directory write access could replace category dir with symlink to external directory.
- Fix: Mitigate via directory permissions (0o700) to lock out attackers.

### Validated as Safe (INFO/LOW)
1. Path traversal: "Mathematically impossible" due to aggressive regex substitution.
2. Secret residue: Checked all callers -- no memory titles or file contents leaked at info.
3. Config injection: Strict casting, no eval/dynamic import paths.
4. POSIX safety: Correct os.open() + O_APPEND + os.write() + finally close pattern.

---

## Cross-Model Consensus

| Finding | Codex 5.3 | Gemini 3.1 Pro | Consensus |
|---------|-----------|----------------|-----------|
| O_NOFOLLOW fallback on non-Linux | MEDIUM | Not flagged | Codex-only |
| TOCTOU in cleanup_old_logs | MEDIUM | MEDIUM | Agreed |
| Directory permissions (no mode=0o700) | Not flagged | MEDIUM | Gemini-only |
| .last_cleanup race condition | LOW | Not flagged | Codex-only |
| Query tokens at info level | LOW | Noted but INFO | Near-agreement |
| Path traversal prevention | Safe | Safe | Agreed |
| No title/content at info | Safe | Safe | Agreed |
| File permissions (0o600) | Safe | Safe | Agreed |
| Config injection | Safe | Safe | Agreed |
| POSIX atomic write | Safe | Safe | Agreed |

**Overall:** Both models independently confirm the implementation is sound with no Critical or High severity issues. The main risks cluster around directory-level permission hardening and TOCTOU races in cleanup, which are MEDIUM severity at most given the threat model (local-user-only attack surface, logs directory under .claude/memory/).
