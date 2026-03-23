#!/bin/bash
# S2: Cross-Plugin Popup Test
# Runs inside Docker container. Tests memory + Guardian for unexpected dialogs.
set -euo pipefail

EVIDENCE_DIR="/evidence"
RUN_ID="s2-run-$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${EVIDENCE_DIR}/${RUN_ID}"
mkdir -p "${RUN_DIR}"

echo "=== S2 Cross-Plugin Popup Test ==="
echo "Run ID: ${RUN_ID}"
echo "Evidence: ${RUN_DIR}"

# Setup project memory structure
echo "[1/9] Setting up memory directory structure..."
cd /workspace/test-project
mkdir -p .claude/memory/{sessions,decisions,runbooks,constraints,tech-debt,preferences}
cp /config/docker-memory-config.json .claude/memory/memory-config.json

# Fix .claude.json (skip theme onboarding)
echo "[2/9] Restoring Claude config..."
BACKUP=$(ls -t /root/.claude/backups/.claude.json.backup.* 2>/dev/null | head -1)
if [ -n "$BACKUP" ]; then
    cp "$BACKUP" /root/.claude.json
    echo "  Restored from backup"
else
    echo '{"theme":"dark","hasCompletedOnboarding":true}' > /root/.claude.json
    echo "  Created minimal config"
fi

# Create tmux session
echo "[3/9] Starting tmux session..."
tmux new-session -d -s test -x 250 -y 80
tmux pipe-pane -t test -o "cat >> ${RUN_DIR}/claude-raw.log"

# Start Claude
echo "[4/9] Launching Claude with both plugins..."
tmux send-keys -t test 'claude --plugin-dir /plugins/claude-memory --plugin-dir /plugins/claude-code-guardian' Enter

# Navigate through ALL onboarding dialogs
echo "[5/9] Navigating onboarding dialogs (up to 120s)..."
CHAT_READY=0
for i in $(seq 1 120); do
    sleep 1
    PANE=$(tmux capture-pane -t test -p -J 2>/dev/null || true)

    # Dialog: Theme selection ("Choose the text style")
    if echo "$PANE" | grep -q 'Choose the text style'; then
        echo "  [${i}s] Theme dialog → pressing Enter"
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    # Dialog: Workspace trust ("Yes, I trust this folder")
    if echo "$PANE" | grep -q 'Yes, I trust this folder'; then
        echo "  [${i}s] Trust dialog → pressing Enter"
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    # Dialog: Permission mode selection
    if echo "$PANE" | grep -q 'Choose a permission mode'; then
        echo "  [${i}s] Permission mode dialog → pressing Enter (default)"
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    # Dialog: Tips / getting started
    if echo "$PANE" | grep -qE 'Tips:|Getting started|Press Enter to continue'; then
        echo "  [${i}s] Tips dialog → pressing Enter"
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    # Chat input area detected — look for the prompt marker
    # Claude TUI shows ">" or a text input box at the bottom
    if echo "$PANE" | grep -qE '╭─|Type your|❯ .*$|^>|Message Claude'; then
        echo "  [${i}s] Chat input area detected"
        CHAT_READY=1
        sleep 3  # Let it fully settle
        break
    fi

    # Fallback: if we see plugin names, Claude has loaded
    if echo "$PANE" | grep -q 'claude-memory'; then
        echo "  [${i}s] Plugin name visible, likely ready"
        CHAT_READY=1
        sleep 3
        break
    fi

    if [ "$i" -eq 120 ]; then
        echo "  WARNING: Chat not ready after 120s"
        tmux capture-pane -t test -p -J > "${RUN_DIR}/timeout-capture.txt"
    fi
done

# Capture initial state
tmux capture-pane -t test -p -J > "${RUN_DIR}/01-initial-state.txt"
echo "  Initial state captured"

if [ "$CHAT_READY" -eq 0 ]; then
    echo "  ERROR: Claude chat never became ready"
    echo "  Dumping final state and exiting"
    cat "${RUN_DIR}/01-initial-state.txt"
    exit 1
fi

# Popup detection: strict patterns for real Claude Code permission dialogs
POPUP_PATTERN='Allow once|Allow always|Do you want to allow|\[Y/n\]|\[y/N\]|Yes, allow|approve this action|Allow for this session'

# Prompt 1: Memory-triggering content (decision)
echo "[6/9] Sending memory-triggering prompt..."
tmux send-keys -t test "We decided to use PostgreSQL instead of MySQL for the database because it has better JSON support and JSONB indexing. This is an important architectural decision." Enter

# Wait for response with popup detection
echo "  Waiting for response (up to 180s)..."
STABLE_COUNT=0
PREV_HASH=""
POPUP_COUNT=0
for i in $(seq 1 180); do
    sleep 1
    PANE=$(tmux capture-pane -t test -p -J 2>/dev/null || true)

    # Check for real permission dialogs (the whole point of S2)
    if echo "$PANE" | grep -qiE "$POPUP_PATTERN"; then
        POPUP_COUNT=$((POPUP_COUNT + 1))
        echo "  >>> POPUP #${POPUP_COUNT} at ${i}s <<<"
        tmux capture-pane -t test -p -J > "${RUN_DIR}/02-popup-${POPUP_COUNT}-at-${i}s.txt"
        # Auto-allow to continue
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    # Screen stability detection
    if [ "$i" -gt 15 ]; then
        CUR_HASH=$(echo "$PANE" | md5sum | cut -d' ' -f1)
        if [ "${PREV_HASH}" = "$CUR_HASH" ]; then
            STABLE_COUNT=$((STABLE_COUNT + 1))
            if [ "$STABLE_COUNT" -ge 5 ]; then
                echo "  Response stabilized at ${i}s"
                break
            fi
        else
            STABLE_COUNT=0
        fi
        PREV_HASH="$CUR_HASH"
    fi

    if [ $((i % 30)) -eq 0 ]; then
        tmux capture-pane -t test -p -J > "${RUN_DIR}/02-progress-${i}s.txt"
        echo "  Progress at ${i}s"
    fi
done

tmux capture-pane -t test -p -J > "${RUN_DIR}/03-after-first-prompt.txt"

# Prompt 2: Write guard trigger
echo "[7/9] Sending write-guard-triggering prompt..."
tmux send-keys -t test "Write a file directly to .claude/memory/decisions/test-popup.json with content {\"test\": true}" Enter

STABLE_COUNT=0
PREV_HASH=""
for i in $(seq 1 120); do
    sleep 1
    PANE=$(tmux capture-pane -t test -p -J 2>/dev/null || true)

    if echo "$PANE" | grep -qiE "$POPUP_PATTERN"; then
        POPUP_COUNT=$((POPUP_COUNT + 1))
        echo "  >>> POPUP #${POPUP_COUNT} at ${i}s <<<"
        tmux capture-pane -t test -p -J > "${RUN_DIR}/04-popup-${POPUP_COUNT}-at-${i}s.txt"
        tmux send-keys -t test Enter
        sleep 2
        continue
    fi

    if [ "$i" -gt 15 ]; then
        CUR_HASH=$(echo "$PANE" | md5sum | cut -d' ' -f1)
        if [ "${PREV_HASH}" = "$CUR_HASH" ]; then
            STABLE_COUNT=$((STABLE_COUNT + 1))
            if [ "$STABLE_COUNT" -ge 5 ]; then
                echo "  Response stabilized at ${i}s"
                break
            fi
        else
            STABLE_COUNT=0
        fi
        PREV_HASH="$CUR_HASH"
    fi

    if [ $((i % 30)) -eq 0 ]; then
        tmux capture-pane -t test -p -J > "${RUN_DIR}/04-progress-${i}s.txt"
        echo "  Progress at ${i}s"
    fi
done

tmux capture-pane -t test -p -J > "${RUN_DIR}/05-after-write-attempt.txt"

# Cleanup
echo "[8/9] Cleaning up..."
tmux send-keys -t test "/exit" Enter
sleep 5
tmux send-keys -t test C-c
sleep 2
tmux capture-pane -t test -p -J > "${RUN_DIR}/06-final-state.txt"
tmux kill-session -t test 2>/dev/null || true

# Analysis
echo ""
echo "[9/9] Analysis"
echo "================================="
echo "Total popup detections: ${POPUP_COUNT}"
echo ""

# Scan all evidence files
EVIDENCE_POPUPS=0
for f in "${RUN_DIR}/"*.txt; do
    fname=$(basename "$f")
    if grep -qiE "$POPUP_PATTERN" "$f" 2>/dev/null; then
        EVIDENCE_POPUPS=$((EVIDENCE_POPUPS + 1))
        echo "POPUP in: ${fname}"
        grep -iE "$POPUP_PATTERN" "$f" | head -3
    fi
done

echo ""
echo "=== S2 RESULT ==="
if [ "$POPUP_COUNT" -eq 0 ] && [ "$EVIDENCE_POPUPS" -eq 0 ]; then
    echo "NO UNEXPECTED POPUPS"
    echo "Both plugins coexisted cleanly."
else
    echo "${POPUP_COUNT} POPUP(S) DETECTED"
    echo "Cross-plugin interaction caused dialog(s)."
fi

echo ""
echo "Evidence: ${RUN_DIR}"
ls -la "${RUN_DIR}/"
