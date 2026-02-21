# Research: Claude Code Conversation Capture, Logging, and Context Access

**Date:** 2026-02-20
**Sources:** Official Anthropic documentation at docs.anthropic.com / docs.claude.com, Claude Code SDK references, GitHub anthropics/claude-code repository

---

## 1. Can Claude Code Capture/Store All Conversation (stdin/stdout) Into Files?

### Answer: YES -- multiple mechanisms exist

#### 1a. Transcript Files (Automatic, Always-On)

Claude Code **automatically stores every conversation** as JSONL files on disk. The path follows this pattern:

```
~/.claude/projects/<project-hash>/<session-id>.jsonl
```

This is confirmed by the hooks API: every hook receives a `transcript_path` field in its JSON input, e.g.:

```json
{
  "session_id": "abc123",
  "transcript_path": "/home/user/.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
  "cwd": "/home/user/my-project",
  ...
}
```

**Key details:**
- Files are in JSONL (JSON Lines) format -- each line is a complete JSON object representing a message
- Conversations are automatically retained but **auto-deleted after 30 days** (per community reports; no official retention guarantee found)
- Subagent transcripts are stored in a nested `subagents/` folder: `~/.claude/projects/.../<session-id>/subagents/agent-<agent-id>.jsonl`
- The `--no-session-persistence` flag (print mode only) disables session saving to disk

#### 1b. The `/export` Slash Command

Claude Code has a built-in `/export [filename]` command:

```
/export                  # Export to clipboard or default file
/export my-session.md    # Export to a specific file
```

This exports the current conversation to a file or clipboard. It is listed in the official interactive mode documentation as a built-in command.

#### 1c. SDK Headless Mode -- Programmatic Capture

The `--output-format` flag provides structured conversation capture:

| Format | Description |
|--------|-------------|
| `text` | Plain text output (default) |
| `json` | Full structured result with metadata (cost, duration, session_id, etc.) |
| `stream-json` | Real-time streaming of each message as separate JSON objects |

**stream-json** is the most complete capture mechanism. Each conversation begins with an `init` system message, followed by user/assistant messages, and ends with a `result` message containing stats:

```bash
claude -p "Build an application" --output-format stream-json
```

You can also pipe stdin with `--input-format stream-json`:

```bash
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Explain this code"}]}}' \
  | claude -p --output-format=stream-json --input-format=stream-json --verbose
```

This effectively gives you full stdin/stdout capture of the entire conversation in structured JSON.

#### 1d. Third-Party Tools for Transcript Extraction

Several community tools exist to extract/convert the automatic JSONL transcripts:
- `ccexport` (Ruby) -- exports to GitHub-flavored Markdown
- `claude-conversation-extractor` (Python, on PyPI) -- search and export to markdown
- Various custom scripts parsing the `~/.claude/projects/` JSONL files

#### 1e. Verbose Mode

The `--verbose` flag enables detailed logging of tool usage and execution, shown in real-time. This can be toggled interactively with `Ctrl+O`. While not file-based capture per se, it exposes all internal operations.

---

## 2. Does Claude Code Support OpenTelemetry?

### Answer: YES -- First-class, comprehensive OpenTelemetry support

Claude Code has **full native OpenTelemetry (OTel) integration** for metrics and events. This is documented extensively at:
- https://docs.anthropic.com/en/docs/claude-code/monitoring-usage

### Quick Start

```bash
# Enable telemetry
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Choose exporters
export OTEL_METRICS_EXPORTER=otlp       # Options: otlp, prometheus, console
export OTEL_LOGS_EXPORTER=otlp          # Options: otlp, console

# Configure endpoint
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Optional: auth headers
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer your-token"

claude
```

### Available Metrics

| Metric | Description |
|--------|-------------|
| `claude_code.session.count` | Sessions started |
| `claude_code.lines_of_code.count` | Lines modified (added/removed) |
| `claude_code.pull_request.count` | PRs created |
| `claude_code.commit.count` | Git commits created |
| `claude_code.cost.usage` | Session cost in USD |
| `claude_code.token.usage` | Tokens used (input/output/cacheRead/cacheCreation) |
| `claude_code.code_edit_tool.decision` | Accept/reject decisions for edit tools |
| `claude_code.active_time.total` | Active usage time in seconds |

### Available Events (via OTel Logs/Events)

| Event | Name | Key Details |
|-------|------|-------------|
| User prompt | `claude_code.user_prompt` | Prompt length (content redacted by default; enable with `OTEL_LOG_USER_PROMPTS=1`) |
| Tool result | `claude_code.tool_result` | Tool name, success, duration, error, tool_parameters (including bash commands) |
| API request | `claude_code.api_request` | Model, cost, duration, tokens, cache stats, fast/normal speed |
| API error | `claude_code.api_error` | Model, error, status code, attempt number |
| Tool decision | `claude_code.tool_decision` | Tool name, accept/reject, decision source |

### Event Correlation

All events share a `prompt.id` (UUID v4) that links all activity triggered by a single user prompt. This allows tracing user_prompt -> api_request(s) -> tool_result(s) for any given prompt.

### Privacy Controls

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_LOG_USER_PROMPTS` | disabled | Log actual prompt content (only length by default) |
| `OTEL_LOG_TOOL_DETAILS` | disabled | Log MCP server/tool names and skill names |
| `OTEL_METRICS_INCLUDE_SESSION_ID` | true | Include session.id in metrics |
| `OTEL_METRICS_INCLUDE_ACCOUNT_UUID` | true | Include user.account_uuid |
| `OTEL_METRICS_INCLUDE_VERSION` | false | Include app.version |

### Supported Backends

- **Metrics:** OTLP (gRPC/HTTP), Prometheus, Console
- **Logs/Events:** OTLP (gRPC/HTTP), Console
- **Multiple exporters:** Comma-separated, e.g. `OTEL_METRICS_EXPORTER=console,otlp`
- **Separate endpoints:** Different backends for metrics vs logs via `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` and `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
- **Dynamic auth headers:** Via `otelHeadersHelper` script in settings (auto-refreshed every 29 min)
- **Admin-managed config:** Via managed settings file for org-wide deployment

### Additional Observability

- **Analytics Dashboard:** Available at claude.ai/analytics/claude-code (Teams/Enterprise) and platform.claude.com/claude-code (API customers)
- **Claude Code Analytics API:** Programmatic access to per-user metrics and productivity data
- **ROI Measurement:** GitHub repo with Docker Compose, Prometheus, and OTel setups: https://github.com/anthropics/claude-code-monitoring-guide

---

## 3. Can Hooks Access the Full Conversation Context?

### Answer: YES -- via `transcript_path`, but not directly in the hook input JSON

#### 3a. What Hooks Receive Directly (Common Input Fields)

Every hook receives these fields via stdin JSON:

| Field | Description |
|-------|-------------|
| `session_id` | Current session identifier |
| `transcript_path` | **Path to the full conversation JSONL file** |
| `cwd` | Current working directory |
| `permission_mode` | Current permission mode |
| `hook_event_name` | Name of the event that fired |

The **`transcript_path`** field is the key mechanism for accessing the full conversation. It points to the JSONL file containing the complete conversation history.

#### 3b. Event-Specific Context Available Directly

Different hook events provide additional context beyond the common fields:

| Hook Event | Additional Fields |
|------------|-------------------|
| `UserPromptSubmit` | `prompt` (the submitted user prompt text) |
| `PreToolUse` | `tool_name`, `tool_input` |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response` |
| `Stop` | `stop_hook_active`, `last_assistant_message` |
| `SubagentStop` | `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message` |
| `SessionStart` | `source` (startup/resume/clear/compact), `model`, optional `agent_type` |
| `SessionEnd` | `reason` (clear/logout/prompt_input_exit/other) |
| `PreCompact` | `trigger` (manual/auto), `custom_instructions` |
| `Notification` | `message`, optional `title`, `notification_type` |

#### 3c. How to Access Full Conversation from a Hook

A hook script can read the full transcript by parsing the JSONL file at `transcript_path`:

```python
#!/usr/bin/env python3
import json, sys

input_data = json.load(sys.stdin)
transcript_path = input_data["transcript_path"]

# Read the full conversation
messages = []
with open(transcript_path, 'r') as f:
    for line in f:
        if line.strip():
            messages.append(json.loads(line))

# Now you have the complete conversation history
# Process as needed...
```

This is exactly how the `claude-memory` plugin's Stop hook (`memory_triage.py`) works -- it reads the transcript via `transcript_path` to analyze the conversation for memory-worthy content.

**Important caveats:**
- The transcript is a snapshot on disk. Hooks receive the path, not the content inline
- The transcript file format is JSONL (one JSON object per line)
- Subagents have their own transcript files at a separate path (available via `agent_transcript_path` in SubagentStop)
- The `last_assistant_message` field on Stop/SubagentStop hooks provides the final response text without needing to parse the transcript

#### 3d. Additional Context Injection Mechanisms

Hooks can also **add** context to the conversation:

1. **`systemMessage`** (all hooks): Adds a warning/context message shown to the user
2. **`additionalContext`** (SessionStart, Notification): String added to Claude's context
3. **stdout on exit 0** (UserPromptSubmit, SessionStart): stdout text is added as context that Claude can see and act on
4. **`CLAUDE_ENV_FILE`** (SessionStart only): Persist environment variables for the session

#### 3e. What Hooks CANNOT Do

- Hooks cannot modify the transcript directly
- Hooks do not receive the full conversation inline in their stdin JSON -- they must read the file
- The transcript format is not officially documented as a stable API (it is an internal JSONL format)
- Hooks cannot access previous sessions' transcripts (only the current session's `transcript_path`)

---

## Summary Table

| Capability | Supported? | Mechanism |
|------------|-----------|-----------|
| Automatic conversation storage | YES | JSONL files in `~/.claude/projects/` |
| Export conversation to file | YES | `/export [filename]` slash command |
| Programmatic conversation capture | YES | `--output-format stream-json` (SDK/headless mode) |
| Capture stdin/stdout | YES | `stream-json` input/output + piping |
| OpenTelemetry metrics | YES | Native OTel with OTLP, Prometheus, Console exporters |
| OpenTelemetry events/logs | YES | Native OTel logs with prompt, tool, API, and decision events |
| Log user prompt content | YES (opt-in) | `OTEL_LOG_USER_PROMPTS=1` |
| Hooks access full conversation | YES | Via `transcript_path` field (read JSONL file) |
| Hooks access last message | YES | Via `last_assistant_message` (Stop/SubagentStop) |
| Hooks access current prompt | YES | Via `prompt` field (UserPromptSubmit) |
| Hooks receive conversation inline | NO | Must read transcript file; not embedded in hook input |
| Hooks modify conversation | NO | Can add context, but cannot modify existing messages |
| Stable transcript format API | NO | JSONL format is internal, not officially versioned |

---

## Implications for claude-memory Plugin

1. **The Stop hook already has access to the full conversation** via `transcript_path`. The current `memory_triage.py` approach of reading the transcript file is the correct and documented way to access conversation context.

2. **OpenTelemetry could complement the memory system** -- the `claude_code.user_prompt` and `claude_code.tool_result` events provide structured telemetry that could be used for analytics on memory usage patterns, but OTel is designed for observability metrics, not for driving application logic like memory capture.

3. **The `last_assistant_message` field** on Stop hooks provides quick access to Claude's final response without parsing the full transcript, which could be useful for lightweight triage decisions.

4. **SessionStart hooks** could be used to load previously captured memories into context at the beginning of each session (which is already done via the retrieval hook on UserPromptSubmit).

5. **PreCompact hooks** could be leveraged to capture important context before it gets compacted away, which is a potential gap in the current memory architecture.

---

## Source URLs

- Hooks Reference: https://docs.anthropic.com/en/docs/claude-code/hooks
- Hooks Guide: https://docs.anthropic.com/en/docs/claude-code/hooks-guide
- CLI Reference: https://docs.anthropic.com/en/docs/claude-code/cli-reference
- Monitoring (OpenTelemetry): https://docs.anthropic.com/en/docs/claude-code/monitoring-usage
- Analytics: https://docs.anthropic.com/en/docs/claude-code/analytics
- Headless/SDK Mode: https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-headless
- Interactive Mode (slash commands): https://docs.anthropic.com/en/docs/claude-code/interactive-mode (inferred from docs.claude.com)
- TypeScript SDK Hook Types: https://docs.claude.com/en/docs/claude-code/sdk/sdk-typescript#basehookinput
- Python SDK Hook Types: https://docs.claude.com/en/docs/claude-code/sdk/sdk-python#hookcallback
- Agent SDK Hooks Guide: https://platform.claude.com/docs/en/agent-sdk/hooks
- Plugin Hook Development: https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md
