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

# Store PIDs of background processes
pids=()

for flow_file in "$REPO_ROOT"/src/asya-testing/asya_testing/flows/*/flow.py \
  "$REPO_ROOT"/examples/flows/*.py \
  "$REPO_ROOT"/examples/flows/agentic/*.py \
  "$REPO_ROOT"/website/docs/img/flows/*.py; do
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
    [[ "$flow_name" == _asya_utils ]] && continue

    # Flows requiring unsupported syntax (inline with)
    [[ "$flow_name" == with_inline_ctx ]] && continue
    [[ "$flow_name" == adk_llm_auditor ]] && continue
    [[ "$flow_name" == guardrails_sandwich ]] && continue
    output_dir="$flow_dir/compiled/$flow_name"
  fi

  uv run --with-editable src/asya-lab --with pydantic asya compile "$flow_file" -o "$output_dir" --plot &

  # Store the process ID of the background task
  pids+=("$!")
done

# Wait for all background processes
failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=1
done
exit $failed
