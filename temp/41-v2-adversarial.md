# V2 Adversarial Attack Report

**Agent:** v2-adversarial
**Date:** 2026-02-22
**Target:** Proposed fixes from V2 deep analysis (`temp/41-solution-synthesis.md`, `temp/41-v1-incorporated.md`)
**External Validation:** Gemini 3.1 Pro (codereviewer), Codex 5.3 (codereviewer)

---

## Attack Results

### Attack 1: Break the raw_bm25 Fallback (Finding #1)

**Overall Verdict: SUCCESS -- Found a genuine design flaw**

#### 1a) Score Inversion -- ranking-label contradiction

**STATUS: SUCCESS (CRITICAL)**

The raw_bm25 fix creates a **ranking-label inversion** where the #1 ranked result can receive a "low" confidence label. Concrete scenario:

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0  (ranked #1 by composite)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5  (ranked #2 by composite)

With raw_bm25 for confidence labeling:
  best_score = max(abs(-1.0), abs(-3.5)) = 3.5
  Entry A ratio = 1.0 / 3.5 = 0.286 -> "low"
  Entry B ratio = 3.5 / 3.5 = 1.0   -> "high"

Result: The #1 ranked entry is labeled "low" while the #2 ranked entry is labeled "high".
```

**Why this matters:** The plan for Action #2 (Tiered Output, `plan-retrieval-confidence-and-output.md:145-260`) explicitly uses confidence labels to determine injection format:
- HIGH -> full `<result>` injection
- MEDIUM -> compact `<memory-compact>` injection
- LOW -> **silence (no output)**

Under tiered mode, Entry A (ranked #1, best overall match including body evidence) would be **silenced** while Entry B (ranked #2, no body relevance) gets full injection. This is a catastrophic user-facing regression.

**External validation:**
- Gemini 3.1 Pro: **"You have broken the contract of the retrieval system."** Recommends rejecting the raw_bm25 fix entirely. Suggests sub-linear body_bonus scaling instead.
- Codex 5.3: **"Entries boosted by strong body evidence can be top-ranked but labeled 'low,' which is misleading."** Recommends keeping confidence on composite score; add separate `title_tag_confidence` attribute if lexical-only signaling is needed.

**Counter-argument considered:** The analysts argue confidence should communicate "BM25 match quality" independently from ranking. This is a valid semantic position, BUT the plan has already committed to using the confidence label as an **action trigger** (tiered injection), not merely an informational signal. Once confidence drives behavior (silence vs. inject), label-ranking inversion becomes a functional bug, not just a semantic preference.

**Resolution options:**
1. **Reject the fix:** Keep composite score for confidence labeling (current code is correct for the tiered injection use case)
2. **Add a separate attribute:** `bm25_confidence` for diagnostic/PoC purposes, keep `confidence` on composite for action decisions
3. **Scale body_bonus sub-linearly:** `body_bonus = log2(1 + body_matches)` instead of `min(3, body_matches)` -- reduces compression without splitting metrics

#### 1b) body_bonus information loss

**STATUS: SUCCESS (subsumed by 1a)**

The scenario in 1a directly demonstrates body_bonus information loss. Three body keyword matches (a strong relevance signal) are completely invisible to the confidence label under the raw_bm25 fix. The current composite score correctly reflects this evidence.

#### 1c) Negative body_bonus

**STATUS: MITIGATED (theoretical, low risk)**

Current code caps body_bonus at `min(3, len(body_matches))` (`memory_retrieve.py:247`), and `body_matches` is a set intersection that can never be negative. The only path to negative body_bonus would require changing the formula.

If the formula were changed to allow negative body_bonus (penalty for body mismatch), the raw_bm25 fix would still "work" in isolation (it ignores body_bonus entirely for labeling). But the composite score used for ranking would also change, potentially creating even larger ranking-label inversions.

**Verdict:** Not a current vulnerability. Future formula changes should re-evaluate the entire scoring pipeline.

#### 1d) raw_bm25 = 0

**STATUS: FAILED (fix is robust here)**

FTS5 BM25 rank is never exactly 0.0 for a matched row. SQLite FTS5 uses a hardcoded minimal IDF to avoid zero-scores. Gemini confirmed: "SQLite FTS5's `bm25()` rank will never be exactly `0.0` for a matched row."

Even if raw_bm25 were 0.0, `confidence_label(0, best_score)` correctly returns "low" because a zero-score genuinely indicates no meaningful match.

---

### Attack 2: Break the Cluster Detection Resolution (Finding #2)

**Overall Verdict: MITIGATED (theoretical risks documented)**

#### 2a) User enables cluster detection

**STATUS: MITIGATED**

If a user sets `cluster_detection_enabled: true` at `max_inject=3`, the plan text at line 68 specifies `cluster_count > max_inject`. As proven in `temp/41-finding2-cluster-logic.md`, this condition is mathematically impossible post-truncation. The feature is silently dead code -- it will never fire.

**Risk:** No crash, no incorrect behavior -- just a feature that does nothing. User expects cluster capping but gets none. This is a **silent misconfiguration**, not a functional break.

**Missing:** There is no config validation warning. The analysts recommend adding a stderr warning when `cluster_detection_enabled=true AND max_inject <= 3`, but this is not in the proposed code changes. It should be added.

#### 2b) Pre-truncation counting future implementation

**STATUS: MITIGATED**

If someone later implements Option B (pre-truncation counting), `apply_threshold()` would need to return the cluster count alongside the filtered results. The current interface returns `list[dict]`, so the implementor would need to either:
1. Add a return value (`list[dict], int`)
2. Mutate a parameter
3. Create a separate function

None of these are blocked by the current fix (which is documentation-only). The interface is extensible. No current code needs to change for future Option B.

---

### Attack 3: Break the --session-id Parameter (Finding #4)

**Overall Verdict: FAILED (fix is robust)**

#### 3a) Unicode / null byte session_id

**STATUS: FAILED**

Gemini confirmed: "Command-line arguments in Unix/Linux are passed to the `execve` system call as arrays of null-terminated C-strings." The shell stops parsing at null bytes and passes an empty string. Python's `subprocess.run` raises `ValueError: embedded null byte` before even invoking the syscall.

Even if a null byte bypassed `sys.argv` (e.g., read from a file), `json.dumps()` safely serializes it as `\u0000`. No JSONL corruption possible.

Unicode strings in `--session-id` are handled natively by Python 3's str type. No injection vector.

#### 3b) Extremely long session_id

**STATUS: FAILED**

argparse accepts the string. `json.dumps()` handles it. The only practical concern is log bloating, but:
1. `emit_event()` writes to a local JSONL log file (not network)
2. A 100KB session_id produces a 100KB+ log line -- unusual but not a crash
3. This is a local tool, not a web service. Malicious long input requires local access, at which point the attacker already has write access to the filesystem

Not a meaningful attack vector.

#### 3c) Concurrent CLI invocations

**STATUS: MITIGATED (theoretical)**

Two CLI processes writing to the same JSONL log simultaneously:

- On Linux, `O_APPEND` guarantees atomic file offset positioning per `write()` system call
- PIPE_BUF (4096 bytes) is the wrong reference -- that applies to pipes/FIFOs, not regular files
- `O_APPEND` + single `os.write()` call is atomic for regular files per POSIX
- But: Python file objects use buffered writes via `stdio`. If `emit_event()` uses Python's `print()` or `file.write()`, a single logical line could be split across multiple `write()` syscalls if it exceeds the buffer size

**Risk:** Low in practice (log lines are typically < 1KB), but the proposed `emit_event()` implementation hasn't been written yet (`memory_logger.py` doesn't exist). This is a design constraint for the future logger implementation, not a current vulnerability.

**Recommendation for logger implementation:** Use `os.write(fd, line_bytes)` with `O_APPEND|O_CREAT|O_WRONLY` for single-call atomic appends. Avoid buffered Python file writes.

---

### Attack 4: Break the Import Hardening (Finding #5)

**Overall Verdict: MITIGATED (one actionable improvement found)**

#### 4a) Malicious memory_logger.py

**STATUS: MITIGATED (pre-existing attack surface)**

If an attacker can place a rogue `memory_logger.py` in `hooks/scripts/`, the `try/except ImportError` successfully imports it. The noop fallback never activates. The imported module runs with full Python privileges.

However, this is NOT a new attack surface introduced by the fix. Any Python `import` statement loads and executes module-level code. The existing `from memory_search_engine import ...` at `memory_retrieve.py:25` has the same vulnerability. The `try/except ImportError` for memory_logger doesn't make this worse -- it just adds another import target alongside existing ones.

**Mitigation context:** Placing a rogue module in the plugin's script directory requires write access to `~/.claude/plugins/claude-memory/hooks/scripts/`, which is the user's own plugin installation. At this privilege level, the attacker could modify any existing script directly.

#### 4b) Transitive dependency ImportError

**STATUS: SUCCESS (actionable improvement)**

This is a genuine gap. If `memory_logger.py` exists but internally imports something that fails with `ImportError` (e.g., `from some_missing_lib import X`), the `except ImportError` block silently swallows it and provides a noop. The operator thinks logging is deployed but it's silently broken.

Same issue applies to the `memory_judge` hardening:
```python
try:
    from memory_judge import judge_candidates
except ImportError:
    judge_candidates = None
```

If `memory_judge.py` exists but `concurrent.futures` has a broken C extension, the `ImportError` is caught and the judge silently degrades.

**Both external models flagged this:**

Gemini recommends scoping the exception:
```python
try:
    from memory_judge import judge_candidates
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_judge':
        raise
    judge_candidates = None
```

Codex recommends at minimum a stderr warning when the file exists but import fails.

**Recommendation:** Adopt Gemini's pattern -- check `e.name` to distinguish "module missing" from "transitive dependency failure". Only swallow `ImportError` when `e.name` matches the target module. Re-raise for transitive failures.

**Note:** The V1 feedback already adds stderr warnings for judge fallback (`temp/41-v1-incorporated.md:59-60`). But the warning fires in ALL fallback cases (module missing OR transitive failure). The `e.name` check would provide distinct behavior: module missing -> warn + fallback; transitive failure -> crash (fail-fast, correct behavior for a broken deployment).

#### 4c) Race condition

**STATUS: FAILED**

Between the `try/except` check and actual logging calls, the module cannot be replaced in a meaningful way. Python caches imported modules in `sys.modules`. Once `from memory_logger import emit_event` succeeds, `emit_event` is bound as a local name reference. Replacing the `.py` file on disk doesn't affect the already-imported function object.

The only way to replace the function would be to modify `sys.modules` from another thread, which requires shared process state -- impossible for separate CLI invocations and irrelevant for the single-threaded hook execution model.

---

### Attack 5: Emergent Issues from Combined Fixes

#### 5a) All fixes simultaneously

**STATUS: MITIGATED (no emergent issues, but Attack 1 is a standalone concern)**

The 5 fixes are largely independent:
- Finding #1 (raw_bm25) modifies `_output_results()` in `memory_retrieve.py`
- Finding #2 (cluster) is documentation-only
- Finding #3 (PoC #5) is plan-text-only
- Finding #4 (--session-id) adds an argparse param to `memory_search_engine.py`
- Finding #5 (imports) adds try/except blocks to `memory_retrieve.py`

No shared mutable state. No conflicting modifications. Findings #4 and #5 both touch `memory_search_engine.py` but in different code regions (CLI argparse vs. module-level imports).

The only cross-fix concern is Finding #1 interacting with the broader Action #2 plan (tiered output), which is captured in Attack 1a above.

#### 5b) Ordering dependency

**STATUS: FAILED (no ordering required)**

Fixes can be applied in any order. Each modifies distinct code regions. There are no intermediate broken states -- each fix is independently valid.

#### 5c) Test coverage gap

**STATUS: MITIGATED**

The least-tested combination is Finding #1 + Finding #5 in the FTS5 path with judge enabled. This path requires:
1. FTS5 available
2. Judge config enabled
3. ANTHROPIC_API_KEY set
4. memory_judge module importable
5. Results returned from FTS5

Existing tests mock the judge path but don't test the raw_bm25 labeling change WITH judge filtering. A result that passes the judge could have a different raw_bm25/composite profile than the original candidates.

**However**, since Attack 1a demonstrates that the raw_bm25 fix itself is flawed, this test coverage gap is moot if the fix is revised.

---

## Newly Discovered Vulnerabilities

### NEW-4: Confidence-Ranking Inversion Enables Silent Result Suppression (HIGH)

**Discovered by:** v2-adversarial, confirmed by Gemini 3.1 Pro and Codex 5.3

**Description:** The proposed raw_bm25 fix for confidence labeling (Finding #1) creates a design flaw where the highest-ranked result (by composite score) can receive the lowest confidence label (by raw_bm25 ratio). When combined with Action #2's tiered output (confidence drives injection format), this becomes a functional bug: the most relevant result can be silenced while less relevant results are fully injected.

**Severity:** HIGH -- affects the correctness of the core retrieval output under tiered mode.

**Scope:** Only manifests when:
1. The raw_bm25 fix is applied, AND
2. An entry has weak title/tag match (low raw_bm25) but strong body match (high body_bonus), AND
3. Tiered output mode is enabled (Action #2)

Under legacy output mode (current default), the inversion affects only the informational `confidence` attribute (cosmetic), not functional behavior. The severity escalates when tiered mode is enabled.

**Root cause:** The fix decouples confidence labels from ranking order. The fundamental semantic question -- "should confidence mean BM25 quality or overall relevance?" -- has different correct answers depending on how the label is consumed. For informational display, BM25 quality is valid. For action triggers (tiered injection), overall relevance alignment with ranking is required.

**Recommendation:** Reject the raw_bm25 fix as proposed. Either:
1. Keep composite score for confidence (current code), or
2. Add a separate `bm25_confidence` attribute for diagnostic/PoC purposes

### NEW-5: ImportError Catch Masks Transitive Dependency Failures (MEDIUM)

**Discovered by:** v2-adversarial, confirmed by Gemini 3.1 Pro and Codex 5.3

**Description:** The proposed `try/except ImportError` for both `memory_logger` and `memory_judge` catches all ImportError subclasses, including those caused by broken transitive dependencies. If `memory_judge.py` exists but `concurrent.futures` has a missing C extension, the import fails with `ImportError(name='_thread')`, which is caught and silently degraded.

**Severity:** MEDIUM -- causes silent feature degradation rather than crash. Difficult to diagnose.

**Fix:** Check `e.name` attribute:
```python
try:
    from memory_judge import judge_candidates
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_judge':
        raise  # Transitive dependency failure -- fail fast
    judge_candidates = None
    print("[WARN] memory_judge module not found; falling back to top-k",
          file=sys.stderr)
```

Apply the same pattern to `memory_logger` imports.

---

## External Validation Summary

| Attack | Gemini 3.1 Pro | Codex 5.3 |
|--------|---------------|-----------|
| 1a (Score inversion) | **CRITICAL** -- "broken the contract" | **HIGH** -- "misleading if interpreted as overall relevance" |
| 1d (raw_bm25=0) | FTS5 never returns 0.0 for matched rows | N/A (not tested) |
| 3a (Null bytes) | Structurally impossible (execve constraint) | N/A |
| 3c (Concurrency) | N/A | PIPE_BUF is wrong reference; use O_APPEND + os.write |
| 4b (Transitive ImportError) | Check `e.name` attribute to scope exception | Warn on stderr; catch only target module |

---

## Vibe-Check

**Self-challenge:** "Am I being too aggressive in calling Attack 1a a break? The analysts made a deliberate semantic choice."

**Assessment after reflection:** The analysts' semantic argument ("confidence should mean BM25 quality") is valid IN ISOLATION. But the plan has already committed confidence labels as action triggers for tiered injection (Action #2: LOW = silence). Once labels drive behavior, they MUST align with ranking or the system contradicts itself. A system that ranks X above Y but silences X while showing Y is objectively broken, regardless of what "confidence" semantically means.

The critical question is: **who consumes the label?** If only humans reading XML output, semantic flexibility is fine. If code that decides what to show/hide, labels must be monotonic with ranking.

**Verdict on my own analysis:** Proportionate. Attack 1a is a genuine functional flaw in the context of the planned tiered output. The other attacks found smaller but actionable issues. I am not over-analyzing.

---

## Overall Verdict: CONCERNS

**Score: 1 SUCCESS (Attack 1a), 1 SUCCESS (Attack 4b), rest MITIGATED or FAILED**

The proposed fixes are mostly sound, but two findings require action:

1. **Finding #1 (raw_bm25 for confidence):** Reject as proposed. The ranking-label inversion is a real functional bug when combined with the planned tiered output mode. Keep composite score for confidence labeling, or add a separate diagnostic attribute for BM25 quality.

2. **Finding #5 (import hardening):** Adopt `e.name` check to distinguish missing modules from broken transitive dependencies. The V1 stderr warnings are good but insufficient alone.

All other fixes (Findings #2, #3, #4) are robust against adversarial attack.
