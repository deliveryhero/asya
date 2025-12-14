#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
FLOWS_DIR="$REPO_ROOT/src/asya-testing/asya_testing/flows"

echo "[.] Checking flow DSL files for compilation"

has_changes=false

for flow_dir in "$FLOWS_DIR"/*; do
  if [ -d "$flow_dir" ] && [ -f "$flow_dir/flow.py" ]; then
    flow_name=$(basename "$flow_dir")
    compiled_file="$flow_dir/compiled_routers.py"

    echo "[.] Compiling flow: $flow_name"

    temp_dir=$(mktemp -d)
    trap 'rm -rf "$temp_dir"' EXIT

    cd "$REPO_ROOT/src/asya-cli"
    uv run asya flow compile "$flow_dir/flow.py" -o "$temp_dir" > /dev/null 2>&1

    if ! diff -q "$temp_dir/compiled_routers.py" "$compiled_file" > /dev/null 2>&1; then
      echo "[!] Flow '$flow_name' is out of sync with source"
      cp "$temp_dir/compiled_routers.py" "$compiled_file"
      git add "$compiled_file"
      has_changes=true
    else
      echo "[+] Flow '$flow_name' is up to date"
    fi
  fi
done

if [ "$has_changes" = true ]; then
  echo ""
  echo "[!] Flow compilation updated compiled_routers.py files"
  echo "    Updated files have been staged automatically"
  exit 0
fi

echo "[+] All flows are up to date"
