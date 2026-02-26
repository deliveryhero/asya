#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "[.] Compiling flow DSL files"

for flow_file in "$REPO_ROOT"/src/asya-testing/asya_testing/flows/*/flow.py \
  "$REPO_ROOT"/examples/flows/*.py \
  "$REPO_ROOT"/docs/img/for-data-scientists-flows/*.py; do
  [ -f "$flow_file" ] || continue

  flow_dir="$(dirname "$flow_file")"

  # Extract flow name and output directory based on file structure
  if [[ "$flow_file" == */flow.py ]]; then
    # Subdirectory structure: nested_if/flow.py -> compile to nested_if/compiled/
    flow_name="$(basename "$flow_dir")"
    output_dir="$flow_dir/compiled"
  else
    # Flat structure: nested_if.py -> compile to examples/flows/compiled/nested_if/
    flow_name="$(basename "$flow_file" .py)"
    [[ "$flow_name" == "__init__" ]] && continue
    output_dir="$flow_dir/compiled/$flow_name"
  fi

  uv run --with-editable src/asya-cli asya flow compile "$flow_file" -o "$output_dir" --plot --overwrite
done

echo "[+] Flow compilation complete"
