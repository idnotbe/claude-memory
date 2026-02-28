# Phase 0: Agent Hook Stop Experiment Results

## Status: READY TO RUN

Experiment configurations prepared. Requires manual execution in a separate Claude Code session.

### Constraint

Agent hooks fire during Claude Code lifecycle events (Stop = when the main agent finishes responding). They CANNOT be tested from within an agent subthread. Testing requires:
1. Installing the hook config
2. Starting a **new** Claude Code session
3. Having a conversation that triggers Stop
4. Inspecting results afterward

### Quick Start

```bash
# Install the combined experiment
bash temp/run-agent-hook-experiment.sh combined

# Start a new Claude Code session (in a separate terminal)
claude

# After session ends, check results
bash temp/run-agent-hook-experiment.sh results

# Clean up
bash temp/run-agent-hook-experiment.sh cleanup
```

See `temp/run-agent-hook-experiment.sh` for all experiment variants.

---

## Experiment Design

### Combined Experiment (Recommended)

A single agent hook that tests all 4 hypotheses at once. More efficient than running 4 separate sessions.

**Installation**: Use `bash temp/run-agent-hook-experiment.sh combined` or manually add to `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "You are an agent hook experiment probe. Your job is to test what capabilities you have and report them. Follow these steps exactly:\n\n## Step 1: Report Available Tools\nList every tool you have access to (e.g., Read, Write, Edit, Bash, Grep, Glob, WebFetch, etc.).\n\n## Step 2: Test File Read (Experiment B)\nTry to read the file at the path in the cwd field from the hook input below. Read the file: CLAUDE.md\nReport: SUCCESS or FAILURE with details.\n\n## Step 3: Test File Write (Experiment B continued)\nTry to write the text 'AGENT_HOOK_WRITE_TEST' to the file /tmp/agent-hook-exp-write-test.txt\nReport: SUCCESS or FAILURE with details.\n\n## Step 4: Test Bash (Experiment B continued)\nTry to run: echo AGENT_HOOK_BASH_TEST_$(date +%s) > /tmp/agent-hook-exp-bash-test.txt\nReport: SUCCESS or FAILURE with details.\n\n## Step 5: Report Hook Input Data (Experiment D)\nList ALL fields from the hook input JSON below. Specifically report: session_id, transcript_path, cwd, permission_mode, hook_event_name, stop_hook_active, last_assistant_message.\n\n## Step 6: Test Transcript Read (Experiment D continued)\nIf transcript_path was provided, try to read the first 20 lines of that file.\nReport: SUCCESS or FAILURE with details.\n\n## Step 7: Write Results\nWrite a summary of ALL results to /tmp/agent-hook-exp-results.txt with format:\nTOOLS_AVAILABLE: <comma-separated list>\nREAD_TEST: SUCCESS|FAILURE\nWRITE_TEST: SUCCESS|FAILURE\nBASH_TEST: SUCCESS|FAILURE\nHOOK_INPUT_FIELDS: <comma-separated list>\nTRANSCRIPT_READ: SUCCESS|FAILURE\nSTOP_HOOK_ACTIVE: <value>\nLAST_MESSAGE_PRESENT: true|false\n\n## Hook Input Data:\n$ARGUMENTS\n\n## Final Decision\nReturn {\"ok\": true} to allow the session to stop.",
            "timeout": 120,
            "statusMessage": "Running agent hook experiment probe..."
          }
        ]
      }
    ]
  }
}
```

### Experiment A: Isolation Test (Separate)

Tests if agent hook tool calls leak into the main transcript. Run as a second test.

**Installation**: Same `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "Run this Bash command: echo 'ISOLATION_MARKER_7f3a2b1c' > /tmp/agent-hook-isolation-marker.txt. Then return {\"ok\": true}.",
            "timeout": 30,
            "statusMessage": "Running isolation experiment..."
          }
        ]
      }
    ]
  }
}
```

**Verification**: After session ends, search the main transcript for `ISOLATION_MARKER_7f3a2b1c`. If absent from the main transcript but the file exists at `/tmp/`, tool calls are isolated.

### Experiment C: `ok:false` Block Test (Separate)

Tests if returning `ok: false` prevents stopping. **WARNING**: This will create a loop if `stop_hook_active` is not checked.

**Installation**:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "Check the stop_hook_active field in the hook input. If stop_hook_active is true, return {\"ok\": true} immediately. Otherwise, write 'BLOCK_TEST_FIRED' to /tmp/agent-hook-block-test.txt and return {\"ok\": false, \"reason\": \"Phase 0 block experiment: agent hook successfully blocked stop.\"}. Hook input: $ARGUMENTS",
            "timeout": 30,
            "statusMessage": "Running block test experiment..."
          }
        ]
      }
    ]
  }
}
```

**Verification**: After the session, check:
1. Does `/tmp/agent-hook-block-test.txt` exist with `BLOCK_TEST_FIRED`?
2. Did the main agent continue after the first stop attempt?
3. Did the main agent receive "Phase 0 block experiment..." as feedback?

---

## Test Protocol

### Running the Combined Experiment

```bash
# 1. Back up existing local settings (if any)
cp .claude/settings.local.json .claude/settings.local.json.bak 2>/dev/null

# 2. Install the combined experiment hook
# (copy the JSON from "Combined Experiment" above into .claude/settings.local.json)

# 3. Start a fresh Claude Code session in this project directory
claude

# 4. In the session, type a simple prompt like:
#    "Say hello and stop."

# 5. When Claude finishes responding, the Stop hook fires.
#    Watch for the status message: "Running agent hook experiment probe..."

# 6. After the session ends, check results:
cat /tmp/agent-hook-exp-results.txt
cat /tmp/agent-hook-exp-write-test.txt
cat /tmp/agent-hook-exp-bash-test.txt

# 7. Restore settings
mv .claude/settings.local.json.bak .claude/settings.local.json 2>/dev/null
```

### Running the Isolation Experiment (A)

```bash
# 1. Install Experiment A hook in .claude/settings.local.json
# 2. Start a new Claude Code session
# 3. Say "hello" and let it respond
# 4. After session ends, find the transcript:
TRANSCRIPT=$(ls -t ~/.claude/projects/*/transcripts/*.jsonl | head -1)
# 5. Search for the isolation marker:
grep -c "ISOLATION_MARKER_7f3a2b1c" "$TRANSCRIPT"
# Result: 0 = isolated, >0 = not isolated
# 6. Check if the marker file was written:
cat /tmp/agent-hook-isolation-marker.txt
```

### Running the Block Experiment (C)

```bash
# 1. Install Experiment C hook in .claude/settings.local.json
# 2. Start a new Claude Code session
# 3. Say "hello" and let it respond
# 4. Observe: Does Claude continue working after the first stop?
# 5. After session ends, check:
cat /tmp/agent-hook-block-test.txt
```

---

## Results Template

Fill in after running experiments:

### Experiment A: Tool Call Isolation
- [ ] Marker found in main transcript? YES / NO
- [ ] Marker file exists at /tmp? YES / NO
- **Conclusion**: Isolated / Not isolated

### Experiment B: File Access
- [ ] Tools available: ___
- [ ] Read test: SUCCESS / FAILURE
- [ ] Write test: SUCCESS / FAILURE
- [ ] Bash test: SUCCESS / FAILURE
- **Conclusion**: ___

### Experiment C: `ok:false` Blocking
- [ ] Block test file created? YES / NO
- [ ] Main agent continued after first stop? YES / NO
- [ ] Reason text received by main agent? YES / NO
- **Conclusion**: Blocking works / does not work

### Experiment D: `$ARGUMENTS` Data Access
- [ ] Hook input fields received: ___
- [ ] transcript_path present? YES / NO
- [ ] Transcript readable? YES / NO
- [ ] stop_hook_active value: ___
- [ ] last_assistant_message present? YES / NO
- **Conclusion**: ___

---

## Implications for claude-memory Plugin

*Fill in after experiments complete*

| Capability | Status | Impact on Architecture |
|-----------|--------|----------------------|
| Read files | ? | Can read existing memories, config, transcript |
| Write files | ? | Can write context files to .staging/ |
| Run Bash | ? | Can invoke memory_write.py |
| Isolated context | ? | Triage noise stays out of main agent |
| ok:false blocking | ? | Can force main agent to process memories |
| $ARGUMENTS data | ? | Can access transcript_path for history |
