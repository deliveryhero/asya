#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "[.] Compiling flow DSL files"

for flow_file in "$REPO_ROOT"/src/asya-testing/asya_testing/flows/*/flow.py \
  "$REPO_ROOT"/examples/flows/*/flow.py; do
  [ -f "$flow_file" ] || continue
  flow_dir="$(dirname "$flow_file")"
  flow_name="$(basename "$flow_dir")"

  echo "[.] Compiling: $flow_name"
  uv run --with-editable src/asya-cli asya flow compile "$flow_file" -o "$flow_dir/compiled" --plot --overwrite
done

echo "[+] Flow compilation complete"
