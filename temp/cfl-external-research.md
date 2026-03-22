# Closed Feedback Loop: External Research Analysis

Research into autonomous self-improvement patterns from karpathy/autoresearch and snarktank/ralph, plus general concepts applicable to a Claude Code plugin self-testing loop.

---

## 1. karpathy/autoresearch

**Repository:** https://github.com/karpathy/autoresearch
**Created:** 2026-03-06 | **Language:** Python | **License:** MIT

### 1.1 Core Architecture

Autoresearch is a minimalist autonomous research loop where an AI agent iteratively modifies a neural network training script, trains for a fixed 5-minute time budget, evaluates the result, and keeps or discards the change. The entire system consists of three files:

- **`prepare.py`** -- Fixed infrastructure (data loading, tokenizer, evaluation harness). Read-only to the agent.
- **`train.py`** -- The single mutable file. Contains model architecture, optimizer, hyperparameters, training loop. The agent modifies only this.
- **`program.md`** -- The "skill" / instruction file for the agent. Describes setup, experimentation loop, and logging protocol. Edited only by humans.

### 1.2 The Feedback Loop

```
LOOP FOREVER:
  1. Read current git state (what's the baseline?)
  2. Modify train.py with an experimental idea
  3. git commit
  4. Run experiment: uv run train.py > run.log 2>&1
  5. Extract metric: grep "^val_bpb:" run.log
  6. If crashed -> read tail of log, attempt fix or skip
  7. Log result to results.tsv (commit, val_bpb, memory_gb, status, description)
  8. If improved -> keep commit (advance branch)
  9. If equal/worse -> git reset to previous state
```

### 1.3 Key Design Patterns

**Pattern 1: Single Objective Metric**
- val_bpb (validation bits per byte) is the sole success criterion. Lower is better.
- Vocab-size-independent, so architectural changes are fairly compared.
- The metric is evaluated by a FIXED evaluation harness (`evaluate_bpb` in prepare.py) that the agent cannot modify. This is crucial -- the agent cannot cheat the metric.

**Pattern 2: Fixed Time Budget as Equalizer**
- Every experiment gets exactly 5 minutes of wall-clock training time.
- This makes experiments directly comparable regardless of what the agent changes (model size, batch size, architecture).
- Approximately 12 experiments/hour, ~100 overnight.

**Pattern 3: Git as Memory / State Management**
- Each experiment is a git commit on a dedicated branch (`autoresearch/<tag>`).
- Successful experiments advance the branch head.
- Failed experiments are reset via `git reset`.
- The branch history IS the record of successful improvements.
- `results.tsv` (untracked) stores the full experimental log including discarded/crashed runs.

**Pattern 4: Simplicity Criterion**
- "All else being equal, simpler is better."
- A small improvement that adds ugly complexity is not worth keeping.
- Removing code and getting equal/better results is a "simplification win."
- This prevents the codebase from accumulating complexity over iterations.

**Pattern 5: Never Stop Autonomy**
- "NEVER STOP" -- the agent runs indefinitely until manually interrupted.
- No confirmation prompts, no "should I continue?" questions.
- Designed for overnight runs where the human is sleeping.

**Pattern 6: Crash Recovery**
- If a run crashes, the agent uses judgment: simple bug (typo, missing import) -> fix and retry. Fundamentally broken idea -> log as "crash", skip, move on.
- Timeout protection: if a run exceeds 10 minutes (2x budget), kill and treat as failure.

### 1.4 Logging and Evaluation

- **results.tsv**: Tab-separated, 5 columns: `commit | val_bpb | memory_gb | status | description`
- Status values: `keep`, `discard`, `crash`
- **analysis.ipynb**: Post-hoc analysis notebook that generates progress charts, showing val_bpb improvement over time, keep rate statistics, and per-experiment deltas.
- The notebook visualizes the "frontier" -- running minimum of kept experiments.

### 1.5 What Autoresearch Does NOT Have
- No test suite (the metric IS the test)
- No regression detection beyond the single metric
- No persistent inter-session memory beyond git history
- No self-modification of the evaluation harness or instructions

---

## 2. snarktank/ralph

**Repository:** https://github.com/snarktank/ralph
**Created:** 2026-01-07 | **Language:** TypeScript (flowchart), Bash (core) | **License:** Not specified
**Based on:** [Geoffrey Huntley's Ralph pattern](https://ghuntley.com/ralph/)

### 2.1 Core Architecture

Ralph is a bash-driven autonomous loop that spawns fresh AI coding tool instances (Amp or Claude Code) repeatedly until all items in a Product Requirements Document (PRD) are complete. Each iteration gets a clean context -- no conversation history carries over.

Key files:
- **`ralph.sh`** -- The outer bash loop. Spawns fresh AI instances, checks for completion signal, manages iteration count.
- **`CLAUDE.md` / `prompt.md`** -- Per-tool instruction files. Injected into each fresh AI instance.
- **`prd.json`** -- The task list. JSON with user stories, each having `passes: true/false`.
- **`progress.txt`** -- Append-only learnings file. Persists across iterations.
- **`skills/prd/SKILL.md`** -- Skill for generating PRDs from feature descriptions.
- **`skills/ralph/SKILL.md`** -- Skill for converting PRDs to prd.json format.

### 2.2 The Feedback Loop

```
ralph.sh loop (max N iterations):
  For each iteration:
    1. Spawn fresh AI instance with CLAUDE.md/prompt.md as input
    2. AI reads prd.json -> finds highest priority story where passes=false
    3. AI reads progress.txt -> learns from previous iterations
    4. AI implements the single story
    5. AI runs quality checks (typecheck, lint, tests)
    6. If checks pass -> git commit
    7. AI updates prd.json: set passes=true for completed story
    8. AI appends learnings to progress.txt
    9. AI updates AGENTS.md/CLAUDE.md with discovered patterns
    10. If ALL stories pass -> output "<promise>COMPLETE</promise>" -> loop exits
    11. Otherwise -> iteration ends, ralph.sh spawns next fresh instance
```

### 2.3 Key Design Patterns

**Pattern 1: Fresh Context Per Iteration**
- Each iteration spawns a NEW AI instance with clean context.
- No conversation state carries over.
- This is intentional: prevents context window exhaustion, ensures each iteration starts clean.
- Memory persists only through: git history, progress.txt, prd.json.

**Pattern 2: Structured Task Decomposition (PRD -> Stories)**
- Features are decomposed into small, independent user stories.
- Each story must be completable within a single context window.
- Stories are ordered by dependency (schema -> backend -> UI).
- The PRD skill enforces sizing: "If you cannot describe the change in 2-3 sentences, it is too big."

**Pattern 3: Three-Layer Persistent Memory**
- **prd.json**: Task state (which stories pass/fail). Machine-readable.
- **progress.txt**: Append-only learnings. Two sections:
  - "Codebase Patterns" (top) -- general reusable patterns, consolidated.
  - Per-iteration entries -- what was done, files changed, learnings.
- **AGENTS.md / CLAUDE.md**: Per-directory knowledge files that AI tools automatically read. Updated with patterns, gotchas, conventions.

**Pattern 4: Completion Signal Protocol**
- The AI outputs `<promise>COMPLETE</promise>` when all stories pass.
- ralph.sh greps for this signal in the output.
- This is a clean termination contract between the outer loop and inner agent.

**Pattern 5: Quality Gates as Feedback**
- "Ralph only works if there are feedback loops."
- Typecheck catches type errors.
- Tests verify behavior.
- CI must stay green (broken code compounds across iterations).
- Browser verification for UI stories (via dev-browser skill).

**Pattern 6: Run Archiving**
- Previous runs are archived when starting a new feature (different branchName).
- Archives saved to `archive/YYYY-MM-DD-feature-name/`.
- Preserves prd.json and progress.txt from completed runs.

**Pattern 7: One Story Per Iteration**
- Strict constraint: implement exactly ONE user story per iteration.
- Prevents scope creep within a single context window.
- Each commit is atomic and focused.

### 2.4 Logging and Evaluation

- **progress.txt**: Structured append-only log with per-iteration entries including: what was implemented, files changed, learnings for future iterations.
- **prd.json**: Binary pass/fail per story. No partial completion tracking.
- **Git history**: Each successful iteration produces a commit with message format `feat: [Story ID] - [Story Title]`.
- **Quality checks**: Project-specific (typecheck, lint, test). Must all pass before commit.

### 2.5 What Ralph Does NOT Have
- No metric-based evaluation (pass/fail only, no continuous improvement score)
- No automatic rollback on failure (the iteration just ends)
- No analysis tooling for post-hoc review of iteration efficiency
- No self-modification of the loop or instructions

---

## 3. Comparative Analysis

| Dimension | autoresearch | ralph |
|-----------|-------------|-------|
| **Domain** | ML research (training optimization) | Software development (feature implementation) |
| **Loop granularity** | Single metric optimization per iteration | Single user story per iteration |
| **Success metric** | Continuous (val_bpb, lower is better) | Binary (story passes: true/false) |
| **Rollback mechanism** | git reset on failure | No rollback; iteration ends, next picks up |
| **Memory between iterations** | Git branch history + results.tsv | progress.txt + prd.json + git history + AGENTS.md |
| **Self-modification scope** | Only train.py (the subject of optimization) | Any project file (the subject of development) |
| **Evaluation harness** | Fixed, agent cannot modify (prepare.py) | Project's existing quality checks (tests, typecheck) |
| **Instruction file** | program.md (human-edited) | CLAUDE.md/prompt.md (human-edited, agent appends to AGENTS.md) |
| **Termination** | Never (runs until interrupted) | All stories pass, or max iterations reached |
| **Post-hoc analysis** | analysis.ipynb (charts, statistics) | progress.txt review (manual) |
| **Crash handling** | Explicit: fix simple bugs, skip fundamentally broken | Implicit: iteration ends, next iteration can retry |

### 3.1 Shared Core Pattern: The Autonomous Improvement Cycle

Both systems implement the same fundamental pattern:

```
OBSERVE -> PLAN -> ACT -> EVALUATE -> PERSIST -> REPEAT
```

1. **OBSERVE**: Read current state (git history, metrics, task list, learnings)
2. **PLAN**: Choose what to try next (next experiment / next story)
3. **ACT**: Make the change (modify code, implement feature)
4. **EVALUATE**: Run fixed evaluation (metric check / quality checks)
5. **PERSIST**: Record outcome (results.tsv / prd.json + progress.txt + git commit)
6. **REPEAT**: Loop back with updated state

The critical insight shared by both: **the evaluation mechanism must be outside the agent's control**. In autoresearch, `prepare.py` and `evaluate_bpb` are read-only. In Ralph, quality checks (typecheck, tests) are pre-existing project infrastructure.

---

## 4. General Concepts: Closed-Loop Autonomous Improvement

### 4.1 Core Properties of Effective Closed Loops

From the two repos and general literature, effective closed-loop improvement systems share these properties:

**Invariant Evaluation**: The evaluation function/criteria must not be modifiable by the improving agent. If the agent can change how success is measured, it will optimize the metric rather than the underlying quality. Both autoresearch and Ralph enforce this -- the agent cannot modify the evaluation harness.

**Atomic Iterations**: Each improvement attempt must be a discrete, committable unit. This enables clean rollback, comparison, and analysis. Autoresearch uses single-file modifications with git commits. Ralph uses single-story implementations with git commits.

**Persistent State Across Iterations**: The loop must accumulate knowledge. Git history, metrics logs, learnings files, and pattern documentation all serve this purpose. Without persistent state, the loop has no "ratchet" -- it cannot build on previous gains.

**Bounded Scope Per Iteration**: Constraining what can change in a single iteration reduces the blast radius of failures and makes root cause analysis tractable. Autoresearch limits changes to train.py. Ralph limits to one user story.

**Automatic Regression Detection**: When a change makes things worse, the system must detect it and prevent regression. Autoresearch compares val_bpb and does git reset. Ralph relies on quality checks (tests, typecheck) to catch regressions before commit.

### 4.2 Self-Hosting Testing Patterns (Dogfooding)

For a system that needs to test itself on its own repo, the following patterns emerge:

**Pattern A: Staged Self-Application**
- Run the tool on its own codebase as a test case.
- The tool's own test suite serves as the invariant evaluation harness.
- If the tool modifies its own code, the test suite catches regressions.
- Key constraint: the test suite must be comprehensive enough that passing tests implies correctness.

**Pattern B: Shadow Mode / Dry Run**
- Run the tool in a mode where it proposes changes but does not apply them.
- Compare proposed changes against expected behavior.
- Useful for testing heuristics (e.g., triage classification) without side effects.

**Pattern C: Fixture-Based Regression**
- Maintain a set of known inputs and expected outputs (fixtures).
- Run the tool against fixtures after every change.
- New failures indicate regressions.
- For a memory plugin: fixture conversations that should trigger specific triage categories, fixture queries that should retrieve specific memories.

**Pattern D: Production Log Replay**
- Capture real production inputs (hook invocations, retrieval queries, triage triggers).
- Replay them after code changes and compare outputs.
- Detects behavioral drift without needing explicit fixtures for every case.

### 4.3 Automated Regression Detection from Production Logs

**Structured Logging as the Foundation**
- Both systems log outcomes: autoresearch uses results.tsv, Ralph uses progress.txt + git.
- For a plugin, structured JSONL logging (as claude-memory already has via memory_logger.py) is the prerequisite.
- Every hook invocation should log: input signature, decision made, output produced, timing.

**Regression Detection Approaches:**

1. **Metric Tracking Over Time**
   - Track key metrics per commit/version: triage accuracy, retrieval precision, false positive rate.
   - Flag when a metric degrades beyond a threshold.
   - Analogous to autoresearch's val_bpb tracking.

2. **Behavioral Fingerprinting**
   - Hash the decision outcomes for a fixed set of inputs.
   - If the fingerprint changes after a code modification, investigate.
   - Cheap to compute, catches unintended behavioral changes.

3. **A/B Comparison from Logs**
   - Replay N recent production log entries through both old and new code.
   - Compare outputs. Any difference is either intentional (improvement) or unintentional (regression).
   - This is the log-replay equivalent of autoresearch's keep/discard decision.

4. **Anomaly Detection on Log Patterns**
   - Monitor for sudden changes in: hook execution time, error rate, category distribution, retrieval result counts.
   - Statistical process control (SPC) charts on rolling windows.
   - No need for explicit test cases -- the distribution of real usage is the test.

---

## 5. Transferable Concepts for claude-memory Self-Testing Loop

### 5.1 What claude-memory Already Has

The plugin already has several CFL-compatible components:
- **Structured JSONL logging** (memory_logger.py) -- production log capture
- **pytest test suite** (tests/) -- invariant evaluation harness
- **Schema validation** (pydantic v2 models) -- structural correctness checks
- **Multiple hook scripts** with deterministic behavior -- amenable to fixture testing
- **Action plans and verification workflow** -- manual improvement loop

### 5.2 What's Missing for a Full CFL

**Gap 1: No Automated Metric Extraction**
- The plugin logs events but does not compute aggregate metrics (triage accuracy, retrieval precision, etc.) automatically.
- Need: a `memory_metrics.py` script that processes JSONL logs and emits key metrics.
- Analogous to: autoresearch's `grep "^val_bpb:" run.log` and results.tsv logging.

**Gap 2: No Fixture-Based Regression Suite**
- The existing tests verify code correctness, but there are no "golden" input/output fixtures for the heuristic components (triage keywords, retrieval scoring, candidate matching).
- Need: a set of fixture conversations/queries with expected triage categories and retrieval results.
- Analogous to: autoresearch's fixed evaluation harness (prepare.py's evaluate_bpb).

**Gap 3: No Log Replay Mechanism**
- Production logs exist but cannot be replayed through the pipeline.
- Need: a `memory_replay.py` that reads JSONL logs and re-runs triage/retrieval on the recorded inputs, comparing against recorded outputs.
- Analogous to: the general A/B comparison pattern.

**Gap 4: No Automated Improvement Loop Driver**
- The plugin has no equivalent of ralph.sh or autoresearch's program.md that orchestrates repeated self-improvement iterations.
- Need: an outer loop that can: run the test suite, extract metrics, compare against baseline, keep/discard changes.
- This could be a simple bash script or a more sophisticated orchestration.

**Gap 5: No Behavioral Fingerprinting**
- No mechanism to detect unintended behavioral changes after code modifications.
- Need: a deterministic fixture suite whose outputs are hashed and compared.

### 5.3 Proposed CFL Architecture for claude-memory

Drawing from both repos, here is a concrete architecture:

```
Phase 0: Instrument (already partially done)
  - Structured JSONL logging of all hook invocations
  - Input/output capture for triage, retrieval, candidate, draft

Phase 1: Evaluate (new)
  - memory_metrics.py: extract metrics from JSONL logs
    - Triage: category hit rates, threshold distribution, false positive estimate
    - Retrieval: query-result relevance scores, judge agreement rates
    - Performance: hook execution times (p50, p95, p99)
  - Fixture suite: deterministic inputs -> expected outputs
    - Triage fixtures: conversation snippets -> expected categories
    - Retrieval fixtures: queries -> expected memory matches
    - Candidate fixtures: memory titles -> expected match scores

Phase 2: Detect (new)
  - memory_replay.py: replay production logs through current code
  - Behavioral fingerprinting: hash fixture outputs, compare across versions
  - Regression threshold: flag if any metric degrades > X% from baseline

Phase 3: Iterate (new, optional future)
  - Outer loop script (like ralph.sh) that:
    1. Makes a change (e.g., adjusts threshold, adds keyword)
    2. Runs fixture suite + test suite
    3. Extracts metrics
    4. Compares against baseline
    5. Keeps or discards (git commit or git reset)
  - This is the full autoresearch pattern applied to plugin development
```

### 5.4 Concrete Actionable Items (Priority Order)

1. **Create a fixture suite for triage classification** -- 20-30 sample conversation snippets with expected triage categories. Run as part of pytest. This is the single highest-value addition because triage is the most heuristic-heavy component and currently has no golden-output tests.

2. **Create a fixture suite for retrieval scoring** -- Sample queries with a small memory corpus, expected top results. Tests that retrieval ranking is stable across code changes.

3. **Build memory_metrics.py** -- Read JSONL logs, emit summary metrics. Can be run ad-hoc or as a CI step. Enables tracking quality over time.

4. **Build memory_replay.py** -- Replay logged triage/retrieval inputs through current code, compare against logged outputs. Catches behavioral drift.

5. **Add behavioral fingerprinting to CI** -- After each commit, run fixtures, hash outputs, compare against stored baseline. Fail CI if fingerprint changes unexpectedly.

6. **(Future) Automated threshold tuning loop** -- An outer loop that adjusts triage thresholds, runs the fixture suite, and keeps the best configuration. This is the full autoresearch pattern applied to threshold calibration.

### 5.5 Key Lessons from Both Repos

**From autoresearch:**
- Keep the evaluation harness immutable and outside the agent's modification scope.
- A single scalar metric enables clear keep/discard decisions.
- Git as the state management backbone works well for any iterative improvement process.
- Fixed resource budgets (time, context window) make experiments comparable.
- The simplicity criterion prevents complexity accumulation.

**From Ralph:**
- Fresh context per iteration prevents state accumulation bugs.
- Append-only learnings (progress.txt) with consolidated patterns (Codebase Patterns section) is an effective two-tier knowledge structure.
- One atomic change per iteration keeps changes reviewable and rollback-safe.
- Quality gates (typecheck, tests) are non-negotiable -- they ARE the feedback loop.
- The PRD decomposition discipline (small stories, dependency-ordered) applies to any iterative development.

**From both:**
- The agent must not be able to modify the criteria by which it is judged.
- Persistent state between iterations is essential (git, logs, structured files).
- Crash/failure handling must be explicit and conservative (log, skip, continue).
- Post-hoc analysis tooling (analysis.ipynb, progress.txt review) is valuable but secondary to the core loop.

---

## 6. Specific Applicability to claude-memory

### 6.1 Triage Threshold Optimization (autoresearch pattern)

The triage system uses keyword heuristics with configurable thresholds. This is directly analogous to autoresearch's hyperparameter tuning:

```
LOOP:
  1. Adjust a threshold or keyword set in memory_triage.py
  2. Run fixture suite (conversation snippets -> expected categories)
  3. Compute accuracy metric (F1 score per category)
  4. If improved -> keep
  5. If worse -> revert
```

The fixture suite serves as the "evaluation harness" and the F1 score serves as the "val_bpb equivalent."

### 6.2 Retrieval Quality Loop (Ralph pattern)

Retrieval quality could use Ralph's PRD-style decomposition:

```
Story 1: Add 10 precision test fixtures (query -> expected top-1 result)
Story 2: Add 10 recall test fixtures (query -> expected result in top-5)
Story 3: Add FTS5 scoring regression tests
Story 4: Add judge agreement rate tests
```

Each story is small, independently testable, and builds on the previous.

### 6.3 Production Log Review Loop

The existing memory_logger.py + log review workflow could be formalized:

```
Weekly/after-each-session:
  1. memory_metrics.py --since "7 days ago" -> dashboard
  2. Flag anomalies (new error types, threshold misses, timing spikes)
  3. If anomaly detected -> create action plan item
  4. Implement fix -> run replay to verify
```

This is a manual version of the autoresearch loop, suitable for a plugin where full automation is premature.

---

## 7. Summary

The two repos represent complementary approaches to autonomous improvement:

- **autoresearch** is a tight, metric-driven optimization loop for a single file against a fixed evaluation harness. Its power comes from the simplicity: one metric, one file, one decision (keep/discard). Directly applicable to threshold tuning, keyword calibration, and any component with a measurable quality metric.

- **Ralph** is a task-driven development loop that decomposes features into atomic stories and executes them sequentially with quality gates. Its power comes from the structured decomposition and persistent learning across iterations. Directly applicable to systematic improvement projects, test suite expansion, and feature development.

For claude-memory's self-testing needs, the recommended approach combines both:
1. Use Ralph-style task decomposition to plan and execute improvement work (fixture creation, metrics tooling, replay infrastructure).
2. Use autoresearch-style metric optimization for heuristic components (triage thresholds, retrieval scoring weights, keyword sets).
3. Build the evaluation infrastructure first (fixtures, metrics, replay) before attempting automated optimization loops.

The single most important principle from both repos: **the evaluation harness must be independent of and immutable to the system being improved.**
