#!/bin/bash
set -euo pipefail

mkdir -p ~/.claude

cat > ~/.claude/statusline.sh << 'EOF'
#!/bin/bash
input=$(cat)

get_model_name() { echo "$input" | jq -r '.model.display_name'; }
get_current_dir() { echo "$input" | jq -r '.workspace.current_dir'; }
get_cost() { echo "$input" | jq -r '.cost.total_cost_usd | . * 1000 | round / 1000'; }
get_lines_added() { echo "$input" | jq -r '.cost.total_lines_added'; }
get_lines_removed() { echo "$input" | jq -r '.cost.total_lines_removed'; }
get_input_tokens() { echo "$input" | jq -r '.context_window.total_input_tokens'; }
get_output_tokens() { echo "$input" | jq -r '.context_window.total_output_tokens'; }
get_used_percent() { echo "$input" | jq -r '.context_window.used_percentage // 0'; }
get_remaining_percent() { echo "$input" | jq -r '.context_window.remaining_percentage // 100'; }
get_worktree_path() {
    local current_dir
    current_dir=$(get_current_dir)
    local git_dir
    git_dir=$(git -C "$current_dir" rev-parse --show-toplevel 2>/dev/null)
    if [ -n "$git_dir" ]; then
        echo "$git_dir" | sed "s|^$HOME|~|"
    fi
}

echo "[$(get_model_name)] +$(get_lines_added) -$(get_lines_removed) ↑$(get_output_tokens) ↓$(get_input_tokens) | $(get_used_percent)..$(get_remaining_percent)% \$$(get_cost) | $(get_worktree_path)"
EOF
chmod +x ~/.claude/statusline.sh

if [ ! -f ~/.claude/settings.json ]; then
    cat > ~/.claude/settings.json << 'EOF'
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh",
    "padding": 0
  }
}
EOF
fi

echo "[+] claude statusline configured"
