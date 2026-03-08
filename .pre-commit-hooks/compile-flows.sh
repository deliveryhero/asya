#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "[.] Compiling flow DSL files in parallel..."

# Store PIDs of background processes
pids=()

for flow_file in "$REPO_ROOT"/src/asya-testing/asya_testing/flows/*/flow.py \
  "$REPO_ROOT"/examples/flows/*.py \
  "$REPO_ROOT"/docs/img/for-data-scientists-flows/*.py; do
  [ -f "$flow_file" ] || continue

  flow_dir="$(dirname "$flow_file")"

  # Extract flow name and output directory
  if [[ "$flow_file" == */flow.py ]]; then
    # Subdirectory structure: nested_if/flow.py -> compile to nested_if/compiled/
    flow_name="$(basename "$flow_dir")"
    output_dir="$flow_dir/compiled"
  else
    # Flat structure: nested_if.py -> compile to examples/flows/compiled/nested_if/
    flow_name="$(basename "$flow_file" .py)"
    [[ "$flow_name" == "__init__" ]] && continue

    # react_* flows require yield/async-generator compiler support (debt/1k38vs)
    [[ "$flow_name" == react_* ]] && continue
    output_dir="$flow_dir/compiled/$flow_name"
  fi

  # Run the command in the background using '&'
  (
    echo "[.] Compiling: $flow_name"
    uv run --with-editable src/asya-cli --with pydantic asya flow compile "$flow_file" -o "$output_dir" --plot --overwrite
  ) &

  # Store the process ID of the background task
  pids+=("$!")
done

# Wait for all background processes to complete
echo "[.] Waiting for all tasks to finish..."
for pid in "${pids[@]}"; do
  wait "$pid"
done

echo "[+] Flow compilation complete"
