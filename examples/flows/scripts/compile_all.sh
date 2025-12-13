#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname $(dirname "${BASH_SOURCE[0]}"))" && pwd)"
COMPILED_DIR="${SCRIPT_DIR}/compiled"
ASYA_CLI="${ASYA_CLI:-uv run asya}"

rm -rf "$COMPILED_DIR"
mkdir -p "$COMPILED_DIR"

echo "[+] Compiling flow files..."
echo ""

for flow_file in "$SCRIPT_DIR"/*.py; do
  [[ -f "$flow_file" ]] || continue

  basename_with_ext="$(basename "$flow_file")"
  flow_name="${basename_with_ext%.py}"
  flow_dir="${COMPILED_DIR}/${flow_name}"

  echo "[.] Compiling: $basename_with_ext"

  if $ASYA_CLI flow compile "$flow_file" --output-dir "$flow_dir" --plot; then
    echo "[+] Success: $flow_name"
  else
    echo "[-] Failed: $flow_name"
    exit 1
  fi
  echo ""
done

echo "[+] Done. Check ${COMPILED_DIR}/"
