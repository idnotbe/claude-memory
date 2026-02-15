#!/usr/bin/env bash
input=$(cat)

if [ -z "$input" ]; then
    echo "No input"
    exit 0
fi

model=$(echo "$input" | jq -r '.model.display_name // empty' 2>/dev/null)

context_pct=""
current_tokens=$(echo "$input" | jq -r '
  (.context_window.current_usage.input_tokens // 0) +
  (.context_window.current_usage.cache_creation_input_tokens // 0) +
  (.context_window.current_usage.cache_read_input_tokens // 0)
' 2>/dev/null)
total_size=$(echo "$input" | jq -r '.context_window.context_window_size // 0' 2>/dev/null)

if [ "$total_size" -gt 0 ] 2>/dev/null; then
    percentage=$(awk "BEGIN { printf \"%.1f\", ($current_tokens * 100.0) / $total_size }")
    context_pct="${percentage}%"
fi

branch=""
git_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -n "$git_branch" ]; then
    branch="[${git_branch}]"
fi

parts=()
[ -n "$model" ] && parts+=("$model")
[ -n "$context_pct" ] && parts+=("$context_pct")
[ -n "$branch" ] && parts+=("$branch")

if [ ${#parts[@]} -gt 0 ]; then
    result="${parts[0]}"
    for ((i=1; i<${#parts[@]}; i++)); do
        result="$result | ${parts[$i]}"
    done
    echo "$result"
else
    echo "Ready"
fi
