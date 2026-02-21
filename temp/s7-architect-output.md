# S7 Architect Output -- memory_judge.py

## What Was Done

Created `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_judge.py` (244 lines) implementing the LLM-as-judge module for memory retrieval verification.

## Pseudocode Fidelity

The implementation follows the pseudocode in `research/rd-08-final-plan.md` lines 573-809 faithfully, with three targeted improvements identified by cross-model code review (Gemini 3.1 Pro + Codex):

### Accepted Improvements (3 changes from spec)

1. **Local RNG instance** (line 152-153): Changed `random.seed(seed); random.shuffle(order)` to `rng = random.Random(seed); rng.shuffle(order)`. Prevents global PRNG state pollution that could affect other modules in the same process. Both external reviewers flagged this as critical/high.

2. **Boolean rejection in `_extract_indices`** (line 201-203): Added `if isinstance(di, bool): continue` before the int check. In Python, `bool` subclasses `int`, so `isinstance(True, int)` is `True`. Without this guard, a hallucinating model outputting `{"keep": [true, false]}` would silently map to indices 1 and 0.

3. **Top-level imports** (lines 19-23): Moved `time` and `deque` imports to module scope instead of lazy imports inside function bodies. These are stdlib modules with no circular dependency risk.

### Noted But Not Changed (spec-faithful decisions)

- **No memory content in judge input**: The pseudocode intentionally uses metadata-only (title, category, tags). The integration layer controls what fields are in candidates. This is a conscious design choice balancing token cost vs. judge accuracy.

- **No read-side `<memory_data>` sanitization**: Write-side sanitization in `memory_write.py` already strips `<`/`>` and control characters. Adding read-side sanitization here would be defense-in-depth but is outside the spec scope for this module.

- **3.0s default timeout**: Kept as specified. It's configurable via the `timeout` parameter on `judge_candidates()`.

- **`n_candidates` parameter in signatures**: Kept even though currently unused in `_extract_indices`. It's in the spec as a future guard rail.

## Module Structure

| Function | Lines | Purpose |
|----------|-------|---------|
| `call_api` | 56-90 | Anthropic Messages API via urllib.request |
| `extract_recent_context` | 93-133 | Parse transcript JSONL (msg["type"] format) |
| `format_judge_input` | 136-168 | Anti-position-bias shuffle via sha256 |
| `parse_response` | 171-192 | JSON extraction with find/rfind fallback |
| `_extract_indices` | 195-209 | Map display->real indices, string coercion |
| `judge_candidates` | 212-244 | Main entry point with timing debug |

## Constants

- `_API_URL`: `https://api.anthropic.com/v1/messages`
- `_API_VERSION`: `2023-06-01`
- `_DEFAULT_MODEL`: `claude-haiku-4-5-20251001`

## Security Features

- `JUDGE_SYSTEM` prompt with anti-injection instructions
- `<memory_data>` tags to delimit untrusted data
- All errors return `None` (graceful fallback, no crash)
- No secrets logged (API key never printed)
- sha256 deterministic shuffle (not `hash()` which varies per process)

## Verification

- `python3 -m py_compile` passes
- Cross-model code review completed (Gemini 3.1 Pro, Codex)
- Vibe-check skill consulted pre-implementation

## External Review Summary

Both Gemini and Codex reviewers converged on the same findings:
- Global RNG mutation: **Fixed**
- Boolean index coercion: **Fixed**
- Lazy imports: **Fixed**
- Missing memory content: **Noted, spec-faithful**
- `<memory_data>` injection: **Noted, write-side sanitization exists**
- Timeout aggressiveness: **Noted, configurable**
