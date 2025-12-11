#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPILED_DIR="${SCRIPT_DIR}/compiled"
ASYA_CLI="${ASYA_CLI:-uv run asya}"

mkdir -p "$COMPILED_DIR"

echo "[+] Compiling scene files..."
echo ""

for scene_file in "$SCRIPT_DIR"/*_scene.py; do
    [[ -f "$scene_file" ]] || continue

    basename_with_ext="$(basename "$scene_file")"
    scene_name="${basename_with_ext%.py}"
    scene_dir="${COMPILED_DIR}/${scene_name}"
    output_file="${scene_dir}/compiled.py"

    mkdir -p "$scene_dir"

    echo "[.] Compiling: $basename_with_ext"

    if $ASYA_CLI scene compile "$scene_file" -o "$output_file" -d; then
        echo "[+] Success: $scene_name"
    else
        echo "[-] Failed: $scene_name"
        exit 1
    fi
    echo ""
done

echo "[+] Done. Check ${COMPILED_DIR}/"
