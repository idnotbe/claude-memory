# Phase 1: Architecture Analysis -- claude-memory Leak Vulnerability Assessment

**Analyst:** arch-analyst
**Date:** 2026-02-20
**Confidence Level:** HIGH (based on complete source code review of all 7 hook scripts, config, and SKILL.md)

---

## 1. Architecture Overview

claude-memory is a structured memory plugin for Claude Code (v5.0.0) that auto-captures session artifacts as JSON files across 6 categories: decisions, runbooks, constraints, tech_debt, preferences, and session_summaries.

### Data Flow

```
User Prompt -> memory_retrieve.py (UserPromptSubmit hook)
  -> reads index.md (flat text), tokenizes prompt, scores entries
  -> reads up to 20 JSON files for recency/retired check
  -> injects max 5 matched entries as XML context into conversation

Session End -> memory_triage.py (Stop hook)
  -> reads last 50 transcript messages (JSONL)
  -> keyword heuristic scoring for 6 categories
  -> if categories trigger: blocks stop, writes context files + triage log
  -> SKILL.md orchestrates: parallel subagent drafting -> verification -> save

Save -> memory_write.py
  -> reads input JSON from .staging/ directory
  -> Pydantic validation + auto-fix
  -> atomic write to category folder
  -> updates index.md (flock-protected)

Lifecycle -> retire/archive/unarchive/restore via memory_write.py
Cleanup -> memory_index.py --gc (MANUAL only)
```

### Key Storage Artifacts

| Artifact | Location | Growth Pattern |
|----------|----------|----------------|
| Memory JSON files | .claude/memory/{category}/*.json | One per memory, grows with each create |
| Index file | .claude/memory/index.md | One line per active memory |
| Context files | .claude/memory/.staging/context-*.txt | One per triggered category per triage |
| Draft files | .claude/memory/.staging/draft-*.json | One per category per save operation |
| Triage score log | .claude/memory/.staging/.triage-scores.log | Append-only JSONL, never rotated |
| Sentinel file | .claude/memory/.staging/.triage-handled | Touch file, overwritten each time |
| Stop flag | .claude/.stop_hook_active | Touch file, overwritten each time |
| Lock directory | .claude/memory/.index.lockdir | Transient, removed after lock release |

---

## 2. Potential Leak/Bloat Vectors

### Vector 1: Staging Directory Accumulation
**Risk: HIGH**

The `.claude/memory/.staging/` directory accumulates files that are NEVER automatically cleaned up:

- **Context files** (`context-*.txt`): Written by `memory_triage.py` on every triggered triage. Up to 6 files per session end (one per category), each up to 50KB. These are overwritten per category name (e.g., `context-decision.txt`), so only 6 unique files exist. **Revised: MEDIUM** -- the naming convention means at most 6 files (one per category) are ever present, as new triage overwrites old ones.

- **Draft files** (`draft-<category>-<pid>.json`): Written by Phase 1 subagents. These include PID in the filename, so they are NOT overwritten -- they accumulate with every save operation. Each draft is a full memory JSON (typically 1-5KB). Over many sessions, hundreds of draft files can accumulate. **This is a genuine leak.**

- **Triage score log** (`.triage-scores.log`): Append-only JSONL. One JSON line per triage evaluation (every session end, whether or not categories trigger). Each line is ~200-500 bytes. Over 1000 sessions, this grows to ~500KB. Not catastrophic but unbounded. **This is a genuine leak.**

- **Input files** (`_cleanup_input` in memory_write.py deletes the input file after write): These ARE cleaned up. Not a leak.

**Net assessment**: The draft files with PID suffixes are the main staging leak. The triage log is secondary. Context files are self-limiting (max 6 files, overwritten).

### Vector 2: Memory File Count Growth (Unbounded Categories)
**Risk: MEDIUM**

- `max_memories_per_category` is set to 100 in config, but this is **agent-interpreted only** -- no script enforces it. The `memory_write.py` `do_create()` function has NO check against this limit. A category folder can grow to any number of files.

- Session summaries have a rolling window (max_retained=5, enforced by SKILL.md orchestration). This is the only category with enforced limits.

- Other categories (decisions, runbooks, constraints, tech_debt, preferences) grow without bound. Realistically, most projects would accumulate 10-50 memories per category, not 100+. But there's no hard ceiling.

- Each memory JSON file is typically 1-5KB. Even at 100 files per category * 6 categories = 600 files * 5KB = 3MB. Not a disk space concern, but index.md and retrieval performance could degrade.

### Vector 3: Index File Growth
**Risk: LOW-MEDIUM**

- `index.md` has one line per active memory (~100-150 chars per line). At 600 active memories, this is ~90KB. The retrieval hook reads the entire file on every prompt, parses it line by line. This is efficient for hundreds of entries but could become slow at thousands.

- Index is rebuilt from scratch by `memory_index.py --rebuild`, which scans all JSON files. This is O(n) in file count. No incremental rebuild.

- No cap enforcement means the index can grow unboundedly, but practically limited by how fast memories are created.

### Vector 4: Retired Memory Accumulation (No Auto-GC)
**Risk: MEDIUM-HIGH**

- Retired memories (`record_status: "retired"`) stay on disk until `memory_index.py --gc` is manually run. The grace period defaults to 30 days.

- Retired memories are excluded from `index.md` (via `rebuild_index` and `remove_from_index`), so they don't bloat retrieval. But they DO occupy disk space and get scanned during `--rebuild`, `--health`, and `--gc` operations.

- If a user never runs `--gc`, retired memories accumulate forever. Over months of active use, this could be dozens to hundreds of orphaned JSON files.

- **This is the closest parallel to the "claude-mem memory leak" pattern** -- data accumulates silently without user awareness or automatic cleanup.

### Vector 5: Context Window Bloat from Retrieval Injection
**Risk: LOW**

- `max_inject` is clamped to [0, 20] with default 5. Each injected entry is a single line (~100-150 chars) wrapped in `<memory-context>` tags. At max 5 entries, this is ~750 bytes injected per prompt. At max 20, this is ~3000 bytes.

- This is a well-controlled vector. The clamping in `memory_retrieve.py` is robust (handles negative, very large, non-integer values). There's no path to unbounded context injection.

- **However**, the retrieval hook reads the full `index.md` and up to 20 JSON files on EVERY prompt, regardless of whether any matches are found. The I/O cost is O(index_size + 20 * avg_file_size) per prompt.

### Vector 6: Per-Prompt I/O Overhead
**Risk: LOW-MEDIUM**

- `memory_retrieve.py` fires on EVERY `UserPromptSubmit` with a prompt >= 10 chars.
- It reads `index.md` (potentially 90KB+ at scale).
- It reads up to 20 JSON files for `check_recency()` (each 1-5KB = 20-100KB I/O).
- It also reads `memory-config.json` (~1KB).
- Total per-prompt I/O: potentially 100-200KB of file reads.
- Has a 10-second timeout.
- For a typical use case (50-200 memories), this completes in <100ms. At 1000+ memories, could approach timeout.

### Vector 7: Triage Hook Overhead
**Risk: LOW**

- `memory_triage.py` fires on every Stop event.
- Reads transcript (last 50 messages from JSONL), which is bounded by `max_messages`.
- Text processing is pure Python regex matching -- efficient and bounded.
- Context file writing is bounded (50KB cap, max 6 files).
- Stop flag and sentinel are single small files (overwritten, not accumulated).

### Vector 8: Changes Array in Memory Files
**Risk: LOW (MITIGATED)**

- The `changes[]` array in each memory JSON is capped at 50 entries (FIFO overflow). This is enforced in `memory_write.py` for all actions (create, update, retire, archive, unarchive, restore).
- This prevents any single memory file from growing unboundedly.
- Good design -- this is explicitly mitigated.

---

## 3. Mitigations Already In Place

| Mitigation | Protects Against | Strength |
|------------|-----------------|----------|
| max_inject clamping [0, 20] | Context window bloat | Strong |
| changes[] FIFO cap at 50 | Individual file growth | Strong |
| Session rolling window (max_retained) | Session summary accumulation | Strong (script-enforced via SKILL.md) |
| Triage max_messages cap (10-200) | Transcript processing overhead | Strong |
| Context file 50KB cap | Staging file size | Strong |
| Index flock locking | Index corruption | Moderate (timeout fallback proceeds unlocked) |
| Retired entries excluded from index | Retrieval performance | Strong |
| Stop flag TTL (5 minutes) | Stale flag accumulation | Moderate |
| Sentinel TTL for idempotency | Duplicate triage | Moderate |

---

## 4. Gaps and Recommendations

### Gap 1: No Automatic Staging Cleanup (HIGH priority)
**Problem**: Draft files with PID suffixes and the triage score log accumulate forever.
**Recommendation**: Add a cleanup step to `memory_triage.py` or a separate cleanup hook:
- Delete draft-*.json files older than 1 hour in .staging/
- Rotate or truncate .triage-scores.log (e.g., keep last 1000 lines)
- This could be a simple age-based cleanup at the start of each triage run

### Gap 2: No Enforced max_memories_per_category (MEDIUM priority)
**Problem**: `max_memories_per_category=100` is advisory only. The `do_create()` function in memory_write.py doesn't check it.
**Recommendation**: Add a check in `do_create()` that counts existing active files in the target category folder and refuses CREATE if at limit. This would require a category folder scan (cheap, <1ms for 100 files).

### Gap 3: No Automatic Garbage Collection (MEDIUM-HIGH priority)
**Problem**: Retired memories accumulate forever without manual intervention.
**Recommendation**: Options:
1. Run GC automatically as part of the triage hook (simple age check, delete files past grace period)
2. Run GC as a periodic cron-like hook (e.g., once per day on first session start)
3. Add GC to the session summary save flow (natural trigger point)

### Gap 4: No Index Size Monitoring (LOW priority)
**Problem**: No warning when index.md grows beyond a performance-relevant threshold.
**Recommendation**: The `--health` command already reports entry counts. Could add a warning when entries exceed a threshold (e.g., 500).

### Gap 5: Retrieval I/O at Scale (LOW priority)
**Problem**: Reading up to 20 JSON files per prompt is acceptable for <500 memories but could become slow at 1000+.
**Recommendation**: Consider caching recency data in index.md itself (e.g., add updated_at to index lines) to avoid JSON file reads during retrieval. This would be a performance optimization, not a correctness fix.

---

## 5. Comparison with Known claude-mem Issues (Conceptual)

Without access to claude-mem's specific source code, the typical "memory leak" patterns in context-management plugins include:

| Pattern | claude-mem (hypothetical) | claude-memory Status |
|---------|--------------------------|---------------------|
| Unbounded context injection | Every memory injected on every prompt | MITIGATED (max_inject=5, clamped) |
| No memory retirement/deletion | Memories accumulate forever | PARTIALLY MITIGATED (retire exists, but GC is manual) |
| No deduplication | Same information saved repeatedly | MITIGATED (memory_candidate.py ACE checks for existing matches) |
| Index/metadata bloat | Index grows without bounds | PARTIALLY MITIGATED (index only includes active, but no hard cap) |
| Staging/temp file accumulation | Working files never cleaned up | NOT MITIGATED (draft files with PIDs accumulate) |
| Per-prompt overhead | Heavy I/O on every prompt | ACCEPTABLE (bounded reads, but scales with memory count) |
| No lifecycle management | All data is permanent | MITIGATED (retire, archive, restore, GC, rolling window) |

**Key architectural difference**: claude-memory has a fundamentally more disciplined architecture than typical memory plugins. The biggest risks are operational (manual GC, staging cleanup) rather than architectural (unbounded injection, missing dedup).

---

## 6. Risk Summary Matrix

| Vector | Severity | Likelihood | Impact | Status |
|--------|----------|------------|--------|--------|
| Staging draft file accumulation | HIGH | HIGH | Disk bloat over time | Not mitigated |
| Triage score log growth | MEDIUM | HIGH | Disk bloat (slow) | Not mitigated |
| Retired memory accumulation | MEDIUM-HIGH | MEDIUM | Disk bloat, slow rebuilds | Manual GC exists but not automatic |
| Unenforced category file cap | MEDIUM | LOW | Index/retrieval degradation | Advisory only |
| Retrieval I/O at scale | LOW-MEDIUM | LOW | Slow prompt response | Bounded but scales linearly |
| Context window injection bloat | LOW | LOW | Context budget waste | Well-mitigated (max_inject clamp) |
| Individual file size growth | LOW | LOW | Disk usage | Well-mitigated (changes[] cap) |
| Triage processing overhead | LOW | LOW | Slow stop processing | Well-mitigated (max_messages cap) |

---

## 7. Bottom Line

**Does claude-memory have the same memory leak vulnerability as claude-mem?**

**No, not architecturally.** claude-memory has fundamentally better guardrails:
1. Context injection is clamped (max_inject)
2. Deduplication via ACE candidate selection
3. Lifecycle management (retire/archive/restore/GC)
4. Bounded per-file growth (changes[] cap)
5. Session rolling window

**However, it has OPERATIONAL leak vectors** that could cause gradual disk bloat:
1. Staging directory draft files accumulate (HIGH severity)
2. Triage score log grows without rotation (MEDIUM severity)
3. Retired memories require manual GC (MEDIUM-HIGH severity)
4. No enforced per-category file cap (MEDIUM severity)

These are fixable with modest engineering effort and do not represent fundamental architectural flaws. They are more analogous to "missing janitor tasks" than "leaky pipe" issues.
