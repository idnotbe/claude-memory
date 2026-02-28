# Phase 0: Agent Hook Experiment Configurations

## Experiment A: Isolation Test
Test if agent hook subagent's Bash tool call is visible in main transcript.

```json
{
  "description": "EXPERIMENT A: Agent hook isolation test",
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Run this exact Bash command: echo 'AGENT_HOOK_ISOLATION_TEST_MARKER'. Then return ok: true.",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Measurement:** After session ends, search main transcript for `AGENT_HOOK_ISOLATION_TEST_MARKER`. If absent → isolated.

## Experiment B: File Access Test
Test if agent hook subagent can read project files.

```json
{
  "description": "EXPERIMENT B: Agent hook file access test",
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Read the file at .claude/memory/memory-config.json using the Read tool. Report what you found. Then return ok: true.",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Measurement:** Does the agent succeed in reading the file? Can it access $CLAUDE_PLUGIN_ROOT?

## Experiment C: Block Test
Test if ok:false blocks session exit.

```json
{
  "description": "EXPERIMENT C: Agent hook ok:false block test",
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Return ok: false with reason 'Phase 0 block test'.",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Measurement:** Does the session refuse to exit? How is the reason displayed?

## Experiment D: Data Access Test
Test what data $ARGUMENTS provides to agent hooks.

```json
{
  "description": "EXPERIMENT D: Agent hook data access test",
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Report exactly what arguments and context data you have access to. List all environment variables you can see. Describe the conversation context available to you. $ARGUMENTS",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Measurement:** What data does the agent hook receive? Transcript? Hook input JSON?

---

## Running the Experiments

For each experiment:
1. Replace hooks/hooks.json with the experiment config
2. Start a new Claude Code session in this project
3. Have a brief conversation (e.g., "hello" → response → /stop)
4. Observe the output and check the transcript
5. Restore original hooks.json before next experiment
