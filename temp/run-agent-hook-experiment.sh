#!/bin/bash
# Phase 0: Agent Hook Experiment Runner
# Usage: bash temp/run-agent-hook-experiment.sh [combined|isolation|block|cleanup]
#
# This script manages .claude/settings.local.json to install experiment hooks.
# It backs up any existing settings.local.json and restores on cleanup.

set -euo pipefail
PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_SETTINGS="$PROJ_DIR/.claude/settings.local.json"
BACKUP="$LOCAL_SETTINGS.bak"

case "${1:-help}" in
  combined)
    echo "=== Installing Combined Experiment (A+B+D) ==="
    [ -f "$LOCAL_SETTINGS" ] && cp "$LOCAL_SETTINGS" "$BACKUP" && echo "Backed up existing settings.local.json"
    cat > "$LOCAL_SETTINGS" << 'SETTINGS_EOF'
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "You are an agent hook experiment probe. Follow these steps exactly and report results.\n\n## Step 1: Report Available Tools\nList every tool you have access to.\n\n## Step 2: Test File Read\nRead the file CLAUDE.md in the current working directory.\nReport: SUCCESS or FAILURE.\n\n## Step 3: Test File Write\nWrite 'AGENT_HOOK_WRITE_TEST' to /tmp/agent-hook-exp-write-test.txt\nReport: SUCCESS or FAILURE.\n\n## Step 4: Test Bash\nRun: echo AGENT_HOOK_BASH_TEST > /tmp/agent-hook-exp-bash-test.txt\nReport: SUCCESS or FAILURE.\n\n## Step 5: Report Hook Input Fields\nList ALL fields from the hook input JSON. Report values of: session_id, transcript_path, cwd, stop_hook_active, last_assistant_message (first 100 chars).\n\n## Step 6: Test Transcript Read\nIf transcript_path is present, read the first 10 lines.\nReport: SUCCESS or FAILURE.\n\n## Step 7: Write Results Summary\nWrite results to /tmp/agent-hook-exp-results.txt:\nTOOLS_AVAILABLE: <list>\nREAD_TEST: SUCCESS|FAILURE\nWRITE_TEST: SUCCESS|FAILURE\nBASH_TEST: SUCCESS|FAILURE\nHOOK_INPUT_FIELDS: <list>\nTRANSCRIPT_READ: SUCCESS|FAILURE\nSTOP_HOOK_ACTIVE: <value>\nLAST_MESSAGE_PRESENT: true|false\n\nHook input: $ARGUMENTS\n\nReturn {\"ok\": true}.",
            "timeout": 120,
            "statusMessage": "Running agent hook experiment probe..."
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF
    echo "Installed. Now start a new Claude Code session: claude"
    echo "Say 'hello' and let it respond. Watch for the experiment status message."
    echo "After session ends: cat /tmp/agent-hook-exp-results.txt"
    echo "Then run: bash temp/run-agent-hook-experiment.sh cleanup"
    ;;

  isolation)
    echo "=== Installing Isolation Experiment (A) ==="
    [ -f "$LOCAL_SETTINGS" ] && cp "$LOCAL_SETTINGS" "$BACKUP" && echo "Backed up existing settings.local.json"
    cat > "$LOCAL_SETTINGS" << 'SETTINGS_EOF'
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
SETTINGS_EOF
    echo "Installed. Now start a new Claude Code session: claude"
    echo "Say 'hello' and let it respond."
    echo "After session ends, check:"
    echo "  1. cat /tmp/agent-hook-isolation-marker.txt"
    echo "  2. grep ISOLATION_MARKER_7f3a2b1c <transcript_path>"
    echo "Then run: bash temp/run-agent-hook-experiment.sh cleanup"
    ;;

  block)
    echo "=== Installing Block Experiment (C) ==="
    [ -f "$LOCAL_SETTINGS" ] && cp "$LOCAL_SETTINGS" "$BACKUP" && echo "Backed up existing settings.local.json"
    cat > "$LOCAL_SETTINGS" << 'SETTINGS_EOF'
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "Check the stop_hook_active field. If true, return {\"ok\": true}. If false or missing, write 'BLOCK_TEST_FIRED' to /tmp/agent-hook-block-test.txt and return {\"ok\": false, \"reason\": \"Phase 0 block experiment: agent hook blocked stop.\"}. Hook input: $ARGUMENTS",
            "timeout": 30,
            "statusMessage": "Running block test experiment..."
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF
    echo "Installed. Now start a new Claude Code session: claude"
    echo "Say 'hello' and let it respond."
    echo "Watch: Does Claude continue after first stop attempt?"
    echo "After session ends: cat /tmp/agent-hook-block-test.txt"
    echo "Then run: bash temp/run-agent-hook-experiment.sh cleanup"
    ;;

  cleanup)
    echo "=== Cleaning up ==="
    if [ -f "$BACKUP" ]; then
      mv "$BACKUP" "$LOCAL_SETTINGS"
      echo "Restored original settings.local.json from backup"
    elif [ -f "$LOCAL_SETTINGS" ]; then
      rm "$LOCAL_SETTINGS"
      echo "Removed experiment settings.local.json"
    else
      echo "Nothing to clean up"
    fi
    echo ""
    echo "=== Experiment Results ==="
    for f in /tmp/agent-hook-exp-results.txt /tmp/agent-hook-exp-write-test.txt /tmp/agent-hook-exp-bash-test.txt /tmp/agent-hook-isolation-marker.txt /tmp/agent-hook-block-test.txt; do
      if [ -f "$f" ]; then
        echo "--- $(basename "$f") ---"
        cat "$f"
        echo ""
      fi
    done
    ;;

  results)
    echo "=== Experiment Results ==="
    for f in /tmp/agent-hook-exp-results.txt /tmp/agent-hook-exp-write-test.txt /tmp/agent-hook-exp-bash-test.txt /tmp/agent-hook-isolation-marker.txt /tmp/agent-hook-block-test.txt; do
      if [ -f "$f" ]; then
        echo "--- $(basename "$f") ---"
        cat "$f"
        echo ""
      else
        echo "--- $(basename "$f") --- NOT FOUND"
      fi
    done
    ;;

  help|*)
    echo "Phase 0: Agent Hook Experiment Runner"
    echo ""
    echo "Usage: bash temp/run-agent-hook-experiment.sh <command>"
    echo ""
    echo "Commands:"
    echo "  combined   Install combined experiment (tests tools, file access, data access)"
    echo "  isolation  Install isolation experiment (tests if tool calls leak to main transcript)"
    echo "  block      Install block experiment (tests ok:false blocking behavior)"
    echo "  results    Show experiment results from /tmp/"
    echo "  cleanup    Restore settings and show results"
    echo ""
    echo "Workflow:"
    echo "  1. Run: bash temp/run-agent-hook-experiment.sh combined"
    echo "  2. Start a new Claude Code session: claude"
    echo "  3. Say 'hello', let it respond, then exit"
    echo "  4. Run: bash temp/run-agent-hook-experiment.sh results"
    echo "  5. Run: bash temp/run-agent-hook-experiment.sh cleanup"
    ;;
esac
