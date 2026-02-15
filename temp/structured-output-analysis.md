# How Claude Code Prompt Hooks Process JSON Responses

## Executive Summary

**Answer: It is BOTH mechanisms -- but with a critical nuance.**

Claude Code v2.1.42 passes `outputFormat: {type: "json_schema", schema: ...}` to the Anthropic
API when executing prompt hooks, requesting server-side constrained decoding. However, it **also**
performs client-side text extraction, JSON parsing (`h1()` function), and Zod schema validation
as a defensive fallback pipeline. The net effect is a **belt-and-suspenders** approach where
structured output is requested but not trusted.

Despite requesting structured output from the API, failures still occur because:
1. Some models (older Haiku snapshots) may not fully support `outputFormat`
2. The API can return empty responses (refusals, token limits, safety filters)
3. The model can still produce text that wraps or prefixes the JSON
4. Claude Code extracts `content[0].text` and re-parses it as plain text regardless

This makes the system **functionally equivalent to mechanism A (plain text generation with
post-hoc parsing)**, even though it technically uses the structured output API parameter.

---

## Source Code Evidence (Definitive)

The following code was extracted from the Claude Code v2.1.42 binary at
`/home/idnotbe/.local/share/claude/versions/2.1.42` using `strings` analysis.

### The Complete Prompt Hook Pipeline

```typescript
// 1. SYSTEM PROMPT -- instructs model to produce JSON (text-level instruction)
systemPrompt: [
  `You are evaluating a hook in Claude Code.
   Your response must be a JSON object matching one of the following schemas:
   1. If the condition is met, return: {"ok": true}
   2. If the condition is not met, return: {"ok": false, "reason": "Reason for why it is not met"}`
],

// 2. API OPTIONS -- passes outputFormat for server-side constrained decoding
options: {
  model: H.model ?? S5(),           // default model function
  querySource: "hook_prompt",
  outputFormat: {                    // <-- STRUCTURED OUTPUT REQUESTED
    type: "json_schema",
    schema: {
      type: "object",
      properties: {
        ok:     { type: "boolean" },
        reason: { type: "string" }
      },
      required: ["ok"],
      additionalProperties: false    // <-- STRICT MODE
    }
  }
}

// 3. TEXT EXTRACTION -- extracts text content, ignoring structured output guarantees
let C = P.message.content
  .filter((T) => T.type === "text")
  .map((T) => T.text)
  .join("");
let _ = C.trim();

// 4. JSON PARSING -- manual parse attempt (h1 function)
let w = h1(_);
if (!w)
  return { outcome: "non_blocking_error", stderr: "JSON validation failed" };

// 5. ZOD VALIDATION -- schema validation AFTER parsing
let q = kbH.safeParse(w);
if (!q.success)
  return { outcome: "non_blocking_error",
           stderr: `Schema validation failed: ${q.error.message}` };
```

### The Zod Schema Definition

```typescript
// kbH is defined as:
kbH = S.object({
  ok:     S.boolean().describe("Whether the condition was met"),
  reason: S.string().describe("Reason, if the condition was not met").optional()
});
```

### Key Observations from the Source

1. **`outputFormat` IS passed** -- Claude Code does request structured output via the API
2. **`additionalProperties: false`** -- strict mode is enabled in the schema
3. **`required: ["ok"]`** -- only `ok` is required; `reason` is optional
4. **Text extraction still happens** -- `content.filter(t => t.type === "text").map(t => t.text)`
5. **Manual JSON parsing** -- `h1(_)` attempts to parse the text as JSON
6. **Zod validation runs separately** -- `kbH.safeParse(w)` validates after parsing
7. **`maxThinkingTokens: 0`** -- thinking/reasoning is disabled for speed

---

## Why Failures Still Occur

Even though `outputFormat` is passed to the API, failures happen for these reasons:

### 1. Empty Responses

Constrained decoding cannot prevent empty responses caused by:
- **Safety refusals** (`stop_reason: "refusal"`) -- the model refuses before generating JSON
- **Token limit reached** (`stop_reason: "max_tokens"`) -- output truncated
- **Model errors** -- API-level failures that return empty content arrays

When the text extraction step produces an empty string, `h1("")` returns null/falsy, triggering
`"JSON validation failed"`.

### 2. Model Compatibility

The debug log message `"Tool search disabled for model 'claude-haiku-4-5-20251001': model does
not support tool_reference blocks"` suggests that some model snapshots may have limited feature
support. If a particular Haiku snapshot does not support the `outputFormat` parameter, the API
may silently ignore it and generate unconstrained text.

### 3. User Prompt Interference

The user's prompt text (injected via `$ARGUMENTS`) can contain instructions that conflict with
the system prompt's JSON format instructions. In plain text mode (if `outputFormat` is ignored),
the model may follow user instructions over system instructions, producing wrong field names
or formats.

### 4. The `additionalProperties: false` Trap

This is what caused the claude-memory plugin's failures. The plugin's Stop hook prompts asked
the model to return extra fields like `lifecycle_event` and `cud_recommendation`:

```json
{"ok": false, "reason": "...", "lifecycle_event": "resolved", "cud_recommendation": "CREATE"}
```

With `additionalProperties: false` in the schema:
- **If structured output IS active**: constrained decoding prevents the model from generating
  extra fields, so the model cannot follow the prompt's instructions to include them
- **If structured output is NOT active**: the model follows the prompt and includes extra fields,
  which then fail Zod validation

Either way, the extra fields cause problems -- they either cannot be generated (structured output)
or are rejected after generation (Zod validation).

---

## Comparison with Other Providers

### Anthropic Structured Outputs API

| Aspect | Prompt Hooks (Internal) | Public API |
|--------|------------------------|------------|
| Parameter | `outputFormat` (internal) | `output_config.format` (GA) |
| Mechanism | Constrained decoding (when supported) | Constrained decoding |
| Models | Haiku, Sonnet (varies by snapshot) | Opus 4.6, Sonnet 4.5, Opus 4.5, Haiku 4.5 |
| Guarantee | Partial (fallback to text parsing) | Schema compliance guaranteed |
| Empty responses | Possible (refusals, errors) | Possible only for refusals/max_tokens |
| Beta header | Not used (internal API) | No longer required (GA) |

### OpenAI Structured Outputs

| Aspect | OpenAI | Claude Code Hooks |
|--------|--------|-------------------|
| Parameter | `response_format: {type: "json_schema"}` | `outputFormat: {type: "json_schema"}` |
| Mechanism | Constrained decoding via `llguidance` | Constrained decoding (Anthropic) |
| Guarantee | 100% schema compliance (claimed) | Best-effort + fallback parsing |
| Empty responses | Not possible (except refusals) | Possible |
| Client-side validation | Optional (SDK `.parse()`) | **Mandatory** (Zod + manual JSON parse) |
| Failure mode | Refusal or max_tokens only | Empty, wrong schema, parse errors |

### Google Gemini Structured Outputs

| Aspect | Gemini | Claude Code Hooks |
|--------|--------|-------------------|
| Parameter | `response_schema` in `generation_config` | `outputFormat` |
| Mechanism | Controlled decoding | Constrained decoding (Anthropic) |
| Guarantee | Schema compliance guaranteed | Best-effort + fallback parsing |
| Key ordering | Preserved (since Nov 2025) | Not relevant (small schemas) |

### Summary of Guarantees

| Provider | Mechanism | Guarantee Level |
|----------|-----------|-----------------|
| OpenAI | `llguidance` constrained decoding | **Deterministic** (100% except refusals) |
| Google Gemini | Controlled decoding | **Deterministic** (schema compliance) |
| Anthropic API | Constrained decoding | **Deterministic** (GA, except refusals/max_tokens) |
| Claude Code Hooks | Structured output + text fallback | **Best-effort** (failures handled gracefully) |

---

## The Architecture: Belt and Suspenders

Claude Code's approach is actually well-engineered for robustness:

```
                        API Call
                           |
                    outputFormat: json_schema
                           |
                 +-------------------+
                 |  Anthropic API    |
                 |  (constrained     |
                 |   decoding)       |
                 +-------------------+
                           |
                    response.content[0].text
                           |
                 +-------------------+
                 |  Text Extraction  |  <-- Extract text from content blocks
                 |  .trim()          |
                 +-------------------+
                           |
                 +-------------------+
                 |  h1() JSON Parse  |  <-- Manual JSON.parse attempt
                 |                   |
                 +---+----------+----+
                     |          |
                  success     failure --> "JSON validation failed"
                     |
                 +-------------------+
                 |  Zod safeParse    |  <-- Schema validation
                 |  kbH.safeParse()  |
                 +---+----------+----+
                     |          |
                  success     failure --> "Schema validation failed"
                     |
                 +-------------------+
                 |  Business Logic   |
                 |  ok? approve :    |
                 |      block        |
                 +-------------------+
```

This means Claude Code **requests** structured output but **does not trust it**. The text
extraction + JSON parsing + Zod validation pipeline handles all failure modes:

1. API returns structured JSON --> text extraction works, JSON parse works, Zod validates
2. API ignores outputFormat --> text may still be valid JSON, pipeline handles it
3. API returns empty --> h1() returns null --> graceful "JSON validation failed" error
4. API returns malformed text --> h1() fails --> graceful error
5. API returns wrong schema --> Zod catches it --> graceful "Schema validation failed" error

---

## Implications for claude-memory Plugin

### Why the Stop Hook Errors Occurred

The plugin's Stop hook prompts instructed the model to return:
```json
{"ok": false, "reason": "...", "lifecycle_event": "...", "cud_recommendation": "..."}
```

With `additionalProperties: false` in the outputFormat schema:
- **Constrained decoding BLOCKS** the extra fields from being generated
- The model can only produce `{"ok": true}` or `{"ok": false, "reason": "..."}`
- The model CANNOT follow the prompt's instructions to include extra fields
- This creates a conflict between the system prompt and the outputFormat constraint

### The Fix (Already Applied)

The fix in commit `b99323e` switched from JSON-instruction prompts to natural-language prompts:
```
Instead of: "Respond with JSON: {\"ok\": true/false, ...}"
Now uses:   "If you would save this, explain what and why. If not, say SKIP."
```

This avoids the conflict entirely by not asking the model to produce structured JSON
with fields that the outputFormat schema forbids.

### Recommendations

1. **Never ask for fields beyond `ok` and `reason`** in prompt hook prompts -- the
   `additionalProperties: false` constraint will block them
2. **Keep prompts simple** -- the model only needs to decide yes/no with an optional reason
3. **Handle errors gracefully** -- empty responses and parse failures will always be possible
4. **Do not rely on `reason` being present** -- it is optional in the schema (`required: ["ok"]`)
5. **Use natural language prompts** -- let the model speak freely within the ok/reason structure

---

## Conclusion

Claude Code uses a **hybrid approach**: it requests structured output via the API's
`outputFormat` parameter (constrained decoding), but implements a full defensive parsing
pipeline (text extraction, JSON parsing, Zod validation) that treats the response as
untrusted text regardless. This is the correct engineering approach -- trust but verify.

The original hypothesis that Claude Code uses "plain text generation" was **partially correct**
in its observable effects (failures do occur, schemas are not guaranteed) but **incorrect about
the mechanism** (the `outputFormat` parameter IS passed to the API). The truth is more nuanced:
Claude Code requests structured output but does not assume it will work, implementing robust
fallbacks for when it does not.

This is fundamentally different from OpenAI and Google's structured outputs, where the client
SDK trusts the server-side guarantee and does not implement mandatory client-side validation.
Claude Code's approach is more defensive and handles more failure modes, at the cost of still
experiencing JSON validation errors that would not occur if the structured output guarantee
were fully trusted.

---

## Sources

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Anthropic Structured Outputs API Docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude Code Bug #11947: Prompt-based Stop hook cannot response correct JSON](https://github.com/anthropics/claude-code/issues/11947)
- [OpenAI Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [OpenAI Introducing Structured Outputs](https://openai.com/index/introducing-structured-outputs-in-the-api/)
- [Google Gemini Structured Output](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini API Structured Outputs Announcement](https://blog.google/technology/developers/gemini-api-structured-outputs/)
- [How Structured Outputs and Constrained Decoding Work](https://www.letsdatascience.com/blog/structured-outputs-making-llms-return-reliable-json)
- [Anthropic Launches Structured Outputs](https://techbytes.app/posts/claude-structured-outputs-json-schema-api/)
- [Claude Code GitHub Repository](https://github.com/anthropics/claude-code)
- Claude Code v2.1.42 binary analysis (`strings` extraction of minified source)
- Gemini 3 Pro analysis (via PAL MCP chat tool)
