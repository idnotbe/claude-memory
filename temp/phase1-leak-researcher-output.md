# Phase 1: claude-mem Memory Leak Research Report

**Researcher:** mem-leak-researcher
**Date:** 2026-02-20
**Confidence Level:** Very High (corroborated across multiple sources, GitHub issues, PRs, changelogs, architecture docs, and cross-model analysis)

---

## 1. What is claude-mem?

**Repository:** [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)
**Current version:** v10.3.1 (latest as of Feb 20, 2026; v10.2.6 is recommended stable)

claude-mem is a Claude Code plugin that automatically captures everything Claude does during coding sessions, compresses it with AI (using Claude's Agent SDK), and injects relevant context back into future sessions. It solves the "context continuity problem" -- each Claude Code session starts fresh with no memory of prior work, and claude-mem provides persistent cross-session memory.

### Architecture (5 process types across 3 runtimes)

| Component | Runtime | Lifecycle | Role |
|-----------|---------|-----------|------|
| Worker Service daemon | Bun/Node | Long-running on port 37777 | Central orchestrator: HTTP API, session management, background processing |
| Hook scripts (x5-6) | Bun | Short-lived per event | SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd |
| MCP Server | Node | Child of worker | Stdio-based MCP protocol server |
| SDK Agent subprocess | Claude CLI | Per-observation | Spawns `claude --resume <session>` to compress observations via Agent SDK |
| chroma-mcp | Python (uvx) | Child of worker (v10.3.0+) | Vector embeddings for semantic search (replaced Node/WASM chroma) |

**Data flow:** Hook (stdin) -> Database (SQLite) -> Worker Service -> SDK Processor (Claude CLI) -> Database -> Next Session Hook

**Storage:** SQLite (`~/.claude-mem/claude-mem.db`) for structured data + ChromaDB (`~/.claude-mem/vector-db`) for vector search

---

## 2. The Memory Leak Issue -- Detailed Technical Explanation

The "memory leak" in claude-mem is not a single bug but a **recurring pattern of 7+ distinct resource leak incidents** spanning 3 months (Dec 2025 - Feb 2026). Each manifests as unbounded process/memory accumulation, but through different pathways.

### Complete Timeline

#### Issue #499 -- SDK Agent Memory Leak (v8.5.2, Dec 2025)
- **Symptom:** Unbounded memory growth in SDK agent lifecycle
- **Root cause:** Resource retention -- AbortController never aborted after SDK agent generator completed naturally, so child processes spawned by Agent SDK remained running indefinitely
- **Fix:** Added explicit subprocess cleanup after SDK query loop using ProcessRegistry (getProcessBySession + ensureProcessExit)
- **Status:** CLOSED, fixed in v8.5.2

#### Issue #572 -- Orphaned Haiku Subagents (v8.5.9, Jan 2026)
- **Symptom:** 89 orphaned Claude Haiku subagent processes consuming 300-500% CPU combined
- **Root cause:** When parent Claude Code sessions ended unexpectedly (crash, force-quit, terminal close), Haiku subagent processes were not terminated. Multiple instances tried to `--resume` the same dead session IDs.
- **Evidence:** 15+ orphaned subagents per dead session, dating back days
- **Fix:** Improved session cleanup
- **Status:** CLOSED

#### Issue #737 -- Zombie Process Accumulation (v9.0.8, Jan 2026)
- **Symptom:** Zombie processes accumulating over time
- **Root cause:** GracefulShutdown not properly wired; stale `onclose` handlers not cleaned up
- **Fix:** Wired into GracefulShutdown for clean teardown; kill-on-failure and stale handler guards
- **Status:** CLOSED, fixed in v9.0.8

#### Issue #789 -- Worker Daemon 50+ GB Memory (v9.0.6, Jan 2026)
- **Symptom:** `worker-service.cjs --daemon` caused 52+ GB memory consumption over ~989 sessions
- **Root cause:** Three compounding factors:
  1. Unbounded child process spawning per hook invocation
  2. Multiple MCP server instances running simultaneously
  3. 832KB bundled script loaded into memory repeatedly per spawn
- **Fix:** Process reuse and cleanup improvements
- **Status:** CLOSED

#### Issue #1145 -- 218 Duplicate Worker Daemons (v10.2.x, Feb 2026)
- **Symptom:** 218 duplicate `worker-service.cjs --daemon` processes, 15GB swap consumed on 8GB MacBook, system freeze requiring hard power-button reset
- **Root cause:** THREE compounding factors:
  1. **Version mismatch restart loop:** `getInstalledPluginVersion()` reads from marketplace git clone, worker reports hardcoded build version. Mismatch triggers shutdown+respawn loop (dozens per minute across 6 sessions)
  2. **No cross-process spawn coordination:** Simultaneous hooks each call `ensureWorkerStarted()`, 1s health check timeout means all conclude worker is down, each spawns a separate detached daemon
  3. **Bun SO_REUSEPORT:** Hook in-process fallback bypasses spawn checks; on macOS, multiple processes bind the same port simultaneously
- **Fix:** PR #1144 addresses all three root causes
- **Status:** CLOSED (but issue itself still marked open)

#### Issue #1168 -- 157 Zombie Observer Processes (v10.2.x, Feb 2026)
- **Symptom:** 157 zombie `claude --resume` processes consuming 8.4 GB RAM while idle
- **Root cause:** FOUR gaps:
  1. No session-end cleanup (Stop hook doesn't force-kill observers)
  2. No timeout mechanism (kill function exists but not invoked for observer lifecycle)
  3. No orphan cleanup (worker daemon doesn't sweep for stale observers)
  4. Empty tracking directory (`observer-sessions/` empty -- tracking system not functioning)
- **Fix (v10.2.6, PR #1175):** Dual-layer fix:
  1. Added `ensureProcessExit()` calls to finally blocks in SessionRoutes.ts and worker-service.ts
  2. Added `reapStaleSessions()` to SessionManager (every 2 min) -- scans stale PID files, kills orphans with SIGKILL
- **Status:** CLOSED, merged Feb 18 2026

#### Issue #1178 -- Duplicate Workers + Zombie Workers (v10.3.1, Feb 2026)
- **Symptom:** Zombie workers persisted after shutdown, reconnected to chroma-mcp, spawning duplicates contending for same data directory. Also: corrupt 147GB HNSW index file caused cascading timeouts.
- **Root cause:** THREE issues:
  1. HTTP shutdown (`POST /api/admin/shutdown`) closed resources but never called `process.exit()`
  2. No guard against concurrent daemon startup (no PID check, no port check before constructor)
  3. Signal handlers registered in constructor prevented exit on EADDRINUSE
- **Fix (v10.3.1):** PID-based guard, port-based guard (before constructor), `process.exit(0)` in try/finally after shutdown
- **Status:** CLOSED

#### Issue #1185 -- chroma-mcp CPU/Memory Leak (v10.3.1, Feb 2026) **[ACTIVE]**
- **Symptom:** `chroma-mcp` Python process spikes to 500-700% CPU within minutes of Claude Code starting, memory reaches 400MB-1GB+
- **Root cause:** v10.3.0 architectural change replaced `npx chroma run` (Node/WASM, in-process) with `chroma-mcp` via `uvx` (Python, out-of-process). The Python subprocess likely enters a busy-wait or tight reconnection loop when the parent dies or disconnects. The daemon respawns killed processes, making it hard to stop.
- **Workaround:** Pin to v10.2.6
- **Status:** **OPEN** as of Feb 20, 2026

---

## 3. Root Cause Analysis: Structural vs Bug?

### Verdict: STRUCTURAL (with bug-level symptoms)

**This is fundamentally an architectural problem, not just a series of bugs.** The individual bugs are real and each fix is technically correct, but the pattern of "fix one leak, another appears within weeks" reveals an underlying structural fragility.

### The Structural Problem

The core issue is **unmanaged, cross-language process orchestration without a unified process supervisor.** claude-mem operates 5+ process types across 3 language runtimes (Bun/Node, Python, Claude CLI) on the user's local machine, treating them as loosely coupled services without the orchestration infrastructure (Kubernetes, systemd, pm2) that such architectures require.

#### Specific architectural gaps:

1. **No unified process supervisor.** The worker daemon acts as both application logic handler AND process supervisor, violating separation of concerns. It cannot reliably manage its own lifecycle AND the lifecycle of its children, especially during failures.

2. **Fire-and-forget spawning pattern.** Hook scripts and the worker daemon spawn processes without bounded concurrency, resource limits, or circuit breakers. Each hook invocation can trigger new spawns without checking if previous ones completed.

3. **No lifecycle coupling ("suicide pact").** Child processes (Claude CLI, chroma-mcp) are not tied to their parent's stdio pipes. When the parent crashes or is killed, children become orphans that run indefinitely. There's no mechanism for children to detect parent death.

4. **Race conditions in singleton enforcement.** Multiple hooks firing simultaneously each call `ensureWorkerStarted()` with a health check timeout. All conclude the worker is down and each spawns a new daemon. PID files are checked non-atomically.

5. **Runtime boundary complexity.** Each runtime (Bun, Node, Python) has its own failure modes, signal handling behavior, and cleanup semantics. Bun's `SO_REUSEPORT` on macOS allows multiple processes to bind the same port -- a feature that becomes a bug in this context.

6. **Architectural changes create new leak surfaces.** The v10.3.0 switch from in-process WASM ChromaDB to out-of-process Python chroma-mcp traded V8 heap pressure for OS-level process management complexity, immediately creating a new leak category (Issue #1185).

### Why "fix one, another appears"

Each fix addresses one specific leak pathway but the architecture has a large surface area for leaks:

```
Leak pathways = (process types) x (lifecycle states) x (failure modes) x (race conditions)
             = 5 x 4 x 3 x 2 = 120 potential leak scenarios
```

Patching individual scenarios is an asymptotic game -- you approach zero leaks but never reach it, because new features (like switching to chroma-mcp) reset the count.

### Cross-Model Consensus

**Gemini 2.5 Pro** (via pal chat) independently reached the same structural conclusion, calling it the **"Local Distributed System Fallacy"** -- treating local processes as if they were independent cloud services without the orchestration layer to manage them. Gemini's key insight: "The shift from WASM (in-process) to Python (out-of-process) for chroma-mcp was the tipping point. It traded V8 heap pressure for OS-level process management complexity."

**Codex 5.3** was unavailable (quota exceeded), but the structural assessment is well-supported by the evidence alone.

---

## 4. Current Fix Status

### Fixed (7 issues closed):
| Issue | Version Fixed | Key Fix |
|-------|--------------|---------|
| #499 | v8.5.2 | SDK subprocess cleanup via ProcessRegistry |
| #572 | ~v8.6.x | Session termination cleanup |
| #737 | v9.0.8 | GracefulShutdown wiring |
| #789 | ~v9.1.x | Process reuse, MCP dedup |
| #1145 | v10.2.x | Version check fix, spawn coordination |
| #1168 | v10.2.6 | ensureProcessExit() + stale session reaper |
| #1178 | v10.3.1 | PID guard, port guard, process.exit(0) |

### Still Open (1 critical):
| Issue | Version | Status |
|-------|---------|--------|
| #1185 | v10.3.0+ | **OPEN** -- chroma-mcp CPU/memory leak, 500-700% CPU |

### Additional Open Issues (related):
- #1161: Windows zombie bun worker blocks Claude Code startup (60s+ hang)
- #1164: Feature request to bound conversation history + lower Chroma embed footprint
- #1179: chroma-mcp sends telemetry to AWS every 1.5s, 529% CPU / 48 threads (closed)

### User-Recommended Stable Version: **v10.2.6**
This version includes the zombie process fixes but uses the older Node/WASM ChromaDB (not the leaky Python chroma-mcp).

---

## 5. Implications for Similar Architectures

### Lessons for any plugin/extension that spawns background processes:

1. **Minimize process types.** Every additional process type multiplies the leak surface area. Prefer in-process libraries over out-of-process CLI spawning. claude-memory (this project) uses stdlib-only Python scripts with no daemons -- zero leak surface.

2. **Lifecycle coupling is mandatory.** If you must spawn child processes, bind their lifecycle to the parent's stdio pipes ("suicide pact" pattern). When stdin closes (parent dies), the child must exit immediately.

3. **Use atomic singleton enforcement.** Port binding is an OS-level atomic mutex. PID files are inherently racy. Use port binding as the primary singleton check, PID files as secondary.

4. **Bounded concurrency.** Never allow unbounded process spawning. Use a fixed-size worker pool or job queue with backpressure.

5. **Process supervisors exist for a reason.** If your architecture requires 3+ long-lived process types, use pm2, systemd, or supervisord. Don't build ad-hoc supervision in application code.

6. **In-process > out-of-process.** The v10.3.0 switch from WASM ChromaDB (in-process) to Python chroma-mcp (out-of-process) immediately introduced a new leak category. In-process code can leak memory but cannot create orphan processes.

7. **Test on constrained hardware.** Many of these issues were first reported on 8GB MacBooks. The architecture was developed on machines with enough RAM to mask leaks.

### Comparison to claude-memory (this project)

claude-memory uses a fundamentally different architecture:
- **No daemons.** All scripts are short-lived, invoked per-hook, exit when done.
- **No subprocess spawning.** Python scripts use stdlib only (except pydantic for write/validate).
- **No cross-language process orchestration.** Everything is Python.
- **Zero leak surface area** from process management. The only pydantic dependency is bootstrapped via venv, not a running service.

This architectural difference is the most significant distinction between the two projects from a reliability standpoint.

---

## 6. Sources

### Primary Sources (GitHub Issues & PRs)
- [Issue #1168: Observer CLI processes never exit](https://github.com/thedotmack/claude-mem/issues/1168) -- 157 zombie processes, 8.4 GB
- [Issue #789: Worker daemon 50+ GB memory](https://github.com/thedotmack/claude-mem/issues/789) -- 52+ GB observed
- [Issue #572: Orphaned Haiku subagents](https://github.com/thedotmack/claude-mem/issues/572) -- 89 orphaned processes
- [Issue #1145: Duplicate worker daemons](https://github.com/thedotmack/claude-mem/issues/1145) -- 218 duplicates, 15GB swap
- [Issue #1185: chroma-mcp CPU/memory leak](https://github.com/thedotmack/claude-mem/issues/1185) -- 500-700% CPU (OPEN)
- [Issue #1178: Duplicate workers + zombie fix](https://github.com/thedotmack/claude-mem/issues/1178) -- PID/port guards
- [PR #1175: Zombie process prevention](https://github.com/thedotmack/claude-mem/issues/1175) -- ensureProcessExit fix

### Secondary Sources
- [claude-mem CHANGELOG.md](https://github.com/thedotmack/claude-mem/blob/main/CHANGELOG.md)
- [claude-mem README / Repository](https://github.com/thedotmack/claude-mem)
- [DeepWiki: thedotmack/claude-mem](https://deepwiki.com/thedotmack/claude-mem)
- [claude-mem Releases](https://github.com/thedotmack/claude-mem/releases)

### Cross-Model Analysis
- **Gemini 2.5 Pro** (via pal chat): Structural assessment confirmed. Coined "Local Distributed System Fallacy" framing. Recommended runtime unification, job queues, and process supervisors.
- **Codex 5.3** (via pal clink): Unavailable (quota exceeded)
- **Gemini 3 Pro Preview** (via pal thinkdeep): Expert analysis confirmed structural root cause. Recommended "suicide pact" pattern for lifecycle coupling and port-based atomic singleton enforcement.

### Methodology Notes
- Web search across GitHub issues, PRs, changelogs, blog posts, and documentation
- Direct GitHub API queries for issue details and PR merge status
- Architecture analysis via DeepWiki and official docs
- Cross-model validation with Gemini 2.5 Pro and Gemini 3 Pro Preview
- Codex 5.3 consultation attempted but blocked by quota limits
- Vibe-check skill not available (no matching skill found), compensated with thinkdeep expert analysis

---

## 7. Confidence Assessment

| Claim | Confidence | Basis |
|-------|-----------|-------|
| claude-mem has had 7+ distinct memory leak issues | **Certain** | Direct GitHub issue evidence |
| The root cause is structural/architectural | **Very High** | Pattern analysis + cross-model consensus + architectural review |
| Issue #1185 (chroma-mcp) is still open | **Certain** | Verified via GitHub API Feb 20, 2026 |
| v10.2.6 is the recommended stable version | **High** | User reports + issue #1185 workaround section |
| claude-memory has zero leak surface from process management | **Very High** | Architecture review: no daemons, no subprocess spawning |
| Fundamental fix requires architectural changes (supervisor, lifecycle coupling) | **High** | Cross-model consensus, but not yet validated by maintainer response |
