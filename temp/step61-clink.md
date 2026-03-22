# Step 61 Cross-Model Synthesis: Heredoc Pattern False Positives

## Models Consulted
- **Gemini 3 Pro Preview** (via PAL chat, high thinking mode)
- **Vibe Check** (meta-mentor self-assessment)

## Key Findings

### Approach A vs. B: Strong Divergence

**Vibe Check recommended Approach A** (strip heredoc bodies before Layer 0/0b):
- Smaller change surface in critical security path
- No risk of pattern anchor/context regressions
- Layer 0's short-circuit semantics remain untouched
- Lower blast radius for a false-positive fix

**Gemini 3 Pro strongly recommended Approach B** (move split_commands() before Layer 0/0b):
- Critical insight: Approach A introduces a **Parsing Differential vulnerability** — if the lightweight stripper differs from split_commands() even slightly, an attacker can craft payloads that are stripped by one parser but not the other
- If Approach A must reuse split_commands() logic exactly to avoid this, it's functionally equivalent to running split_commands() anyway — negating the "lightweight" advantage
- Single source of truth for command boundaries eliminates differential risk

### Gemini's Killer Insight: Selective Body Retention

Gemini proposed a refinement to Approach B that solves BOTH plans simultaneously:
- Modify `_consume_heredoc_bodies()` to **capture** body text instead of just advancing the index
- Check the base command against a **DATA_COMMAND_ALLOWLIST** (cat, tee, echo, etc.)
- If data command: discard body (prevents false positives)
- If NOT data command: **append body to sub-command string** so all layers can scan it
- This immediately solves the interpreter-heredoc-bypass gap without needing separate regex patterns

### Data vs. Interpreter: Allowlist vs. Blocklist

Both assessors agreed:
- **Allowlist of data commands is safer** than blocklist of interpreters
- Blocklist misses: awk, sed, jq, mysql, psql, custom binaries, exotic interpreters
- Allowlist: cat, tee, echo, grep, head, tail, wc, patch (and variants)
- Unknown commands default to "retain body" = fail-closed

### Pattern Anchor Risk (Approach B concern)

Gemini noted that existing block patterns already use `(?:^|[;|&...])` prefix patterns, which are already sub-command safe. This mitigates the anchor regression concern raised by the vibe check.

### Performance Concern (Approach B)

Both noted the concern about split_commands() cost before short-circuit. Gemini's mitigation: keep MAX_COMMAND_LENGTH check as a "Layer 00" before split_commands(). Since commands are already length-bounded, split_commands() is O(n) with small n.

## Synthesis: Recommended Approach

**Approach B with selective body retention** (Gemini's refinement):

1. Keep MAX_COMMAND_LENGTH check first (Layer 00)
2. Move split_commands() before Layer 0/0b
3. Modify split_commands() / _consume_heredoc_bodies() to:
   - Capture heredoc body text
   - Check base command against DATA_COMMAND_ALLOWLIST
   - Data command: discard body (no false positives)
   - Non-data command: retain body in sub-command (no false negatives)
4. Layer 0/0b scan per-sub-command instead of raw string
5. This solves BOTH the false-positive and interpreter-heredoc-bypass plans

**Why this wins over Approach A:**
- No parsing differential vulnerability
- Single source of truth for heredoc handling
- Solves both complementary plans simultaneously
- Pattern anchors are already sub-command compatible
- Performance concern mitigated by length check

**Edge cases to address:**
- Command prefixes: env, sudo, command, absolute paths before data commands
- Multiple heredocs per command line
- Quoted vs unquoted delimiters (both need same treatment)
- Per-sub-command scanning for Layer 0/0b (not joined string)
