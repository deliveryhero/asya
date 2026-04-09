#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Use a pinned graphviz Docker image so PNG output is reproducible across machines.
# Falls back to local 'dot' with a warning if Docker is unavailable.
GRAPHVIZ_IMAGE="asya-graphviz:12.2.0"
DOT_WRAPPER_DIR=""

# shellcheck disable=SC2329
_cleanup() {
  [ -n "$DOT_WRAPPER_DIR" ] && rm -rf "$DOT_WRAPPER_DIR"
}
trap _cleanup EXIT

if command -v docker > /dev/null 2>&1; then
  if ! docker image inspect "$GRAPHVIZ_IMAGE" > /dev/null 2>&1; then
    echo "[.] Building pinned graphviz Docker image ($GRAPHVIZ_IMAGE)..."
    docker build -t "$GRAPHVIZ_IMAGE" \
      -f "$REPO_ROOT/.pre-commit-hooks/Dockerfile.graphviz" \
      "$REPO_ROOT/.pre-commit-hooks/" > /dev/null
    echo "[+] Built $GRAPHVIZ_IMAGE"
  fi
  DOT_WRAPPER_DIR="$(mktemp -d)"
  cat > "$DOT_WRAPPER_DIR/dot" << EOF
#!/usr/bin/env bash
exec docker run --rm -v "$REPO_ROOT:$REPO_ROOT" -w "\$PWD" $GRAPHVIZ_IMAGE "\$@"
EOF
  chmod +x "$DOT_WRAPPER_DIR/dot"
  export PATH="$DOT_WRAPPER_DIR:$PATH"
fi

# Detect flow function name collisions across files
declare -A seen_functions
for flow_file in "$REPO_ROOT"/examples/flows/*.py; do
  [ -f "$flow_file" ] || continue
  fname="$(basename "$flow_file" .py)"
  [[ "$fname" == "__init__" || "$fname" == _asya_utils ]] && continue
  func="$(grep -A1 '^@flow' "$flow_file" 2> /dev/null | grep -oP '(?<=^def |^async def )\w+' | head -1 || true)"
  [ -z "$func" ] && continue
  if [ -n "${seen_functions[$func]:-}" ]; then
    echo "[!] Flow function name collision: '$func' in both ${seen_functions[$func]} and $flow_file" >&2
    exit 1
  fi
  seen_functions[$func]="$flow_file"
done

# Make shared helpers importable (e.g. _asya_utils)
export PYTHONPATH="$REPO_ROOT/examples/flows:${PYTHONPATH:-}"

# Store PIDs of background processes
pids=()

for flow_file in "$REPO_ROOT"/src/asya-testing/asya_testing/flows/*/flow.py \
  "$REPO_ROOT"/examples/flows/*.py \
  "$REPO_ROOT"/docs/website/img/flows/*.py; do
  [ -f "$flow_file" ] || continue

  flow_dir="$(dirname "$flow_file")"

  # Extract flow name
  if [[ "$flow_file" == */flow.py ]]; then
    # Subdirectory structure: nested_if/flow.py
    flow_name="$(basename "$flow_dir")"
  else
    # Flat structure: 01_sequential.py -> compile to examples/flows/compiled/01_sequential/
    flow_name="$(basename "$flow_file" .py)"
    [[ "$flow_name" == "__init__" ]] && continue
    [[ "$flow_name" == _asya_utils ]] && continue
  fi

  uv run --with-editable src/asya-lab asya compile "$flow_name" -f "$flow_file" --plot &

  # Store the process ID of the background task
  pids+=("$!")
done

# Wait for all background processes
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
exit $failed
