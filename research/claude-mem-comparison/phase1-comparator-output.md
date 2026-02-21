# claude-mem vs claude-memory: Comprehensive Comparison

## 1. claude-mem Overview

### Features
- **Automatic observation capture** during coding sessions via PostToolUse hooks
- **AI-powered semantic summarization** using Claude Agent SDK for context compression
- **Semantic + keyword hybrid search** via ChromaDB vector embeddings + SQLite FTS5
- **5 MCP tools**: search, timeline, get_observations, save_memory, workflow docs
- **Progressive disclosure**: 3-layer token-efficient retrieval (compact index ~50-100 tokens, timeline, full detail ~500-1000 tokens per result)
- **Privacy controls**: `<private>` tags to exclude sensitive content
- **Web viewer UI**: React interface at localhost:37777
- **mem-search skill**: Natural language query capability
- **"Endless Mode"** (experimental): biomimetic memory for extended sessions

### Architecture
- **Language**: TypeScript, compiled to ESM
- **Runtime**: Node.js 18+ / Bun (auto-installed)
- **Storage**: SQLite3 at `~/.claude-mem/claude-mem.db` + ChromaDB for vector embeddings
- **Worker Service**: Express API on port 37777, Bun-managed background daemon
- **Hooks**: 6 lifecycle hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop/Summary, SessionEnd, Smart Install)
- **Dependencies**: Bun, uv (Python for Chroma), Node.js, ONNX runtime, sqlite3 native module
- **Config**: `~/.claude-mem/settings.json` (auto-created)
- **License**: AGPL-3.0 (main code); PolyForm Noncommercial 1.0.0 (ragtime/ directory)

### Current State (as of Feb 2026)
- **Version**: v10.3.1 (latest release Feb 19, 2026)
- **GitHub stars**: ~29.4k stars, ~2k forks
- **Development activity**: Extremely active -- 10 releases in 3 days (Feb 16-19), indicating intensive bug-fixing/stabilization
- **Commits**: 1,412 on main branch

### Known Issues
1. **Process zombie accumulation**: Observer Claude CLI processes never exit, accumulating ~5-7 per session, causing 40GB+ RAM consumption over extended usage (Issue #1168)
2. **SQLite initialization failures**: Database not created on fresh install (Issue #818)
3. **ONNX model cache corruption** in embedding pipeline (fixed in v10.2.3)
4. **Hook firing failures**: PostToolUse and Stop hooks stopped firing around Nov 2025 (Issue #504)
5. **Windows compatibility**: Search fails due to ONNX runtime package resolution errors (Issue #1104)
6. **Worker process crashes**: Bun enters CLOSE_WAIT state
7. **Duplicate worker daemons** (fixed in v10.3.1 with PID/port guards)
8. **Chroma collection routing issues** (fixed in v10.2.4)

---

## 2. claude-memory Overview

### Features
- **6 structured memory categories**: session_summary, decision, runbook, constraint, tech_debt, preference
- **Keyword-based retrieval** with weighted scoring (title match: 2pts, tag match: 3pts, prefix match: 1pt, recency bonus: 1pt)
- **Full memory lifecycle**: create, update, retire (soft delete), archive, unarchive, restore
- **Schema-enforced writes** via Pydantic v2 with per-category content models
- **Write guard system**: PreToolUse hook blocks direct writes to memory directory
- **Post-write validation**: PostToolUse hook schema-validates and quarantines invalid files
- **Prompt injection defenses**: multi-layered title sanitization (write-side + retrieval-side + index rebuild)
- **OCC (Optimistic Concurrency Control)**: MD5 hash checking prevents concurrent write conflicts
- **Anti-resurrection protection**: 24-hour cooldown on re-creating retired memories
- **Merge protections**: immutable fields, grow-only tags, append-only changes, FIFO overflow
- **Parallel subagent drafting**: per-category Task subagents with configurable model tiers (haiku/sonnet/opus)
- **Garbage collection**: automated cleanup of retired memories past grace period
- **Health reporting**: index sync detection, heavily-updated memory alerts
- **4 slash commands**: /memory, /memory:config, /memory:search, /memory:save

### Architecture
- **Language**: Python (stdlib + pydantic v2 for write/validation only)
- **Runtime**: Python 3 (no additional runtimes needed)
- **Storage**: JSON files per memory + index.md flat file (derived artifact, auto-rebuilt)
- **Hooks**: 4 hooks -- 1 Stop (command-type triage), 1 UserPromptSubmit (retrieval), 1 PreToolUse:Write (guard), 1 PostToolUse:Write (validation)
- **Dependencies**: Python 3, pydantic v2 (for write/validate scripts only; all others are stdlib-only)
- **Zero external services**: no worker daemon, no database server, no ports
- **Config**: `.claude/memory/memory-config.json` per project
- **License**: MIT

### Current State (as of Feb 2026)
- **Version**: 5.0.0
- **Test coverage**: 6,218 LOC across 10 test files (pytest)
- **Scripts**: 7 Python scripts totaling ~2,800 LOC
- **SKILL.md**: 273-line orchestration document for 4-phase memory consolidation
- **No known process leaks or resource consumption issues**

---

## 3. Detailed Comparison Table

| Dimension | claude-mem | claude-memory | Winner |
|-----------|-----------|---------------|--------|
| **Retrieval Quality** | Semantic + keyword hybrid (ChromaDB vectors + SQLite FTS5) | Keyword-based with weighted scoring + recency bonus | claude-mem |
| **Storage Format** | SQLite + ChromaDB (binary, opaque) | JSON files + index.md (human-readable, git-friendly) | claude-memory |
| **Memory Categories** | Flat observations/summaries | 6 structured categories with typed content schemas | claude-memory |
| **Memory Lifecycle** | Create, search (limited lifecycle) | Create, update, retire, archive, unarchive, restore, GC | claude-memory |
| **Write Safety** | No write guard system documented | PreToolUse guard + PostToolUse validation + Pydantic schemas | claude-memory |
| **Prompt Injection Defense** | `<private>` tag stripping | Multi-layered title sanitization + XML escaping + path containment | claude-memory |
| **Concurrency Control** | SQLite locking | OCC with MD5 hash + mkdir-based portable flock | Tie |
| **Resource Usage** | Heavy (worker daemon, SQLite, ChromaDB, Bun, ONNX runtime) | Lightweight (Python stdlib scripts, no daemons) | claude-memory |
| **Infrastructure** | Express server on port 37777, background daemon | Zero-infrastructure (file I/O only) | claude-memory |
| **Cross-Platform** | Windows issues with ONNX, Chroma | Python stdlib works everywhere | claude-memory |
| **Dependencies** | TypeScript, Bun, Node.js, uv, Python, ONNX, sqlite3 | Python 3, pydantic v2 (optional for most scripts) | claude-memory |
| **Git Friendliness** | SQLite DB not committable | JSON/MD files commit naturally | claude-memory |
| **Per-Project Isolation** | Global database (session-based context switching) | Per-project `.claude/memory/` directory | claude-memory |
| **Configuration** | Global `~/.claude-mem/settings.json` | Per-project `memory-config.json` with defaults fallback | claude-memory |
| **Scalability (1000+ memories)** | Vector DB handles large datasets well | Index.md parsing scales linearly (adequate for typical projects) | claude-mem |
| **Popularity** | 29.4k stars | Small/personal project | claude-mem |
| **Stability** | 10 releases in 3 days (intensive bug-fixing) | Stable; no known runtime issues | claude-memory |
| **Test Coverage** | Unknown (not assessed) | 6,218 LOC across 10 test files | claude-memory |
| **License** | AGPL-3.0 + PolyForm Noncommercial | MIT | claude-memory |
| **Developer Experience** | Install and forget (when it works) | More explicit control via slash commands | Tie (different philosophies) |
| **Schema Validation** | Not documented | Pydantic v2 models per category with 6 content types | claude-memory |
| **Merge Protections** | Not documented | Immutable fields, grow-only tags, append-only changes | claude-memory |
| **Observability** | Web viewer UI at localhost:37777 | Health reports, index validation, triage score logging | Tie |

---

## 4. Unique Advantages of Each

### claude-mem Unique Advantages
1. **Semantic search**: Can find "authentication" when you search for "login" -- handles synonyms and conceptual similarity without exact keyword matching
2. **Automatic observation capture**: PostToolUse hooks capture every tool execution without explicit categorization
3. **Web viewer UI**: Visual interface for browsing memories
4. **Progressive disclosure**: Token-efficient 3-layer retrieval minimizes context window usage
5. **Large community**: 29k stars means more eyeballs on bugs, more contributors
6. **AI-powered compression**: Uses Claude Agent SDK to summarize observations

### claude-memory Unique Advantages
1. **Structured memory types**: 6 distinct categories with typed schemas (decisions, runbooks, constraints, tech debt, preferences, sessions) -- captures semantically richer information than flat observations
2. **Full lifecycle management**: retire/archive/unarchive/restore with grace periods and anti-resurrection -- memories are managed, not just accumulated
3. **Defense in depth**: Write guards, path containment checks, title sanitization, XML escaping -- security-first design
4. **Zero infrastructure**: No daemons, no ports, no databases, no risk of process zombies
5. **Git-native**: Memory travels with the project; teammates get context automatically
6. **Per-project isolation**: Each project has its own memory root -- no cross-contamination
7. **Parallel subagent orchestration**: Uses configurable model tiers (haiku for simple categories, sonnet/opus for complex ones) to draft memories efficiently
8. **Mechanical merge protections**: Immutable fields, OCC, grow-only tags -- prevents data corruption by design
9. **MIT license**: No restrictions on commercial use
10. **Test suite**: 6,200+ LOC of tests including adversarial and security-focused tests

---

## 5. Future Potential Analysis

### What claude-memory can do that claude-mem fundamentally cannot (architectural advantages)

1. **Per-project memory isolation by design**: claude-memory stores memories in `.claude/memory/` within each project. This is an architectural decision that cannot be easily retrofitted into claude-mem's global SQLite database. It means:
   - Memory context switches automatically when you `cd` between projects
   - Team members get shared project context via git
   - No risk of cross-project memory contamination

2. **Structured categorization**: claude-memory's 6-category system with typed Pydantic models captures semantically richer information. A "decision" has rationale, alternatives, and consequences. A "runbook" has triggers, symptoms, and verification steps. claude-mem captures flat observations that lose this structure.

3. **Lifecycle management**: The retire/archive/restore/GC system means old memories are managed, not just accumulated. This prevents context window pollution from stale memories and gives users fine-grained control.

4. **Safety model**: The write guard + validation + sanitization chain is a fundamentally different safety posture. claude-mem has no documented equivalent to preventing prompt injection via crafted memory titles.

5. **Zero-infrastructure reliability**: With no background processes, there is literally nothing that can crash, leak memory, or corrupt a database. This is not a feature that can be added to claude-mem -- it requires removing its core architecture.

### What claude-memory needs to close the gap

1. **Retrieval quality**: The biggest gap. Options to close it without adding infrastructure:
   - **BM25 scoring**: Replace simple keyword counting with BM25 (probabilistic IR algorithm, pure Python, no dependencies)
   - **Query expansion**: Before searching, ask the LLM to generate 3-5 search terms (leverages model intelligence at zero infrastructure cost)
   - **Synonym/alias map**: A lightweight lookup table for common coding synonyms (auth/authentication/login, db/database, etc.)
   - **TF-IDF with n-grams**: Capture phrases like "api key" rather than individual words

2. **Automatic capture breadth**: claude-mem captures every tool use; claude-memory only captures based on keyword-heuristic triage. Could expand triage patterns or add lightweight PostToolUse observation logging.

3. **Community and visibility**: Growth through documentation, examples, and marketing.

### Is continued development justified?

**Yes, strongly.** The architectural advantages (zero-infrastructure, git-native, per-project, structured categories, safety model) are fundamental design decisions that represent a genuinely different philosophy from claude-mem. These are not features that can be added to claude-mem through patches -- they require rethinking the core architecture.

The retrieval quality gap is the only significant disadvantage, and it can be closed incrementally with pure-Python improvements (BM25, query expansion, synonym maps) that maintain the zero-infrastructure advantage.

---

## 6. External Analysis Summary

### Gemini 3 Pro Assessment (via pal chat)
Key takeaways from the external analysis:
- **"Plugin B (claude-memory) is significantly more sustainable"** for a single developer
- **"In a coding project, terminology is usually precise... exact keyword matching is often *better* than semantic search"** -- domain-specific vocabulary reduces the advantage of semantic search
- **"The operational cost of managing a buggy, port-binding background service outweighs the marginal benefit of semantic recall"**
- **"Stick with Plugin B. It aligns better with the Unix Philosophy -- simple, text-based, and focused."**
- Recommended improvements: BM25, TF-IDF with n-grams, small-model re-ranking, synonym expansion

---

## 7. Recommendation

### Continue developing claude-memory. It is the better architecture for its target use case.

**Reasoning:**

1. **Reliability over features**: claude-mem's 10-releases-in-3-days stabilization cycle, process zombie issues, and SQLite initialization failures indicate ongoing reliability challenges inherent to its complex infrastructure. claude-memory's zero-infrastructure approach eliminates entire categories of failure modes.

2. **Right tool for the job**: For a single developer or small team working on multiple projects, per-project file-based memory with git integration is objectively more useful than a global database. The memory should travel with the code.

3. **Safety model matters**: As LLM agent plugins become more common, prompt injection via stored data becomes a real attack vector. claude-memory's multi-layered sanitization approach is ahead of the curve.

4. **The retrieval gap is closable**: BM25 + query expansion + synonym maps can get keyword-based retrieval to ~80-90% of semantic search quality for domain-specific coding content, with zero infrastructure cost.

5. **License advantage**: MIT vs AGPL-3.0 is significant for anyone who might integrate or extend the plugin.

6. **Structured categories are a differentiator**: No other Claude Code memory plugin captures decisions with rationale and alternatives, or runbooks with symptoms and verification steps. This structured data is inherently more valuable than flat observations.

### Confidence Level: **High (8/10)**

The main source of uncertainty is whether claude-mem's community momentum (29k stars) will lead to solving its architectural issues through engineering investment, potentially adding features that close the gap. However, the fundamental architectural differences (global DB vs per-project files, zero-infra vs worker daemon) cannot be changed without a rewrite, so the core advantages of claude-memory are durable.

### Priority Improvements for claude-memory
1. **Implement BM25 scoring** in memory_retrieve.py (highest impact, pure Python)
2. **Add query expansion** in the UserPromptSubmit hook (ask model for search terms before retrieval)
3. **Lightweight synonym map** for common coding terms
4. **PostToolUse observation logging** (optional, to capture broader context)
5. **Documentation and examples** for community growth
