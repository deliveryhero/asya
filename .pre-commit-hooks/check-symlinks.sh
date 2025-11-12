#!/bin/bash
set -euo pipefail

# Check that critical files remain as symlinks, not regular files
# This prevents accidentally committing duplicated content that should be symlinked

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Define source files and their required symlinks
declare -A SYMLINK_MAP=(
  ["src/asya-runtime/asya_runtime.py"]="src/asya-operator/internal/controller/runtime_symlink/asya_runtime.py testing/integration/operator/testdata/runtime_symlink/asya_runtime.py"
  ["src/asya-operator/config/crd/asya.sh_asyncactors.yaml"]="deploy/helm-charts/asya-operator/crds/asya.sh_asyncactors.yaml"
)

EXIT_CODE=0

echo "[+] Checking required symlinks..."

for source in "${!SYMLINK_MAP[@]}"; do
  source_path="$REPO_ROOT/$source"

  if [[ ! -f "$source_path" ]]; then
    echo "[-] ERROR: Source file not found: $source"
    EXIT_CODE=1
    continue
  fi

  for symlink in ${SYMLINK_MAP[$source]}; do
    symlink_path="$REPO_ROOT/$symlink"

    if [[ ! -e "$symlink_path" ]]; then
      echo "[-] ERROR: Required symlink missing: $symlink"
      echo "    Should link to: $source"
      EXIT_CODE=1
      continue
    fi

    if [[ ! -L "$symlink_path" ]]; then
      echo "[-] ERROR: File is not a symlink: $symlink"
      echo "    This file MUST be a symlink to: $source"
      echo "    Current type: regular file"
      echo ""
      echo "    To fix, run:"
      echo "      rm $symlink"
      echo "      ln -s \$(realpath --relative-to=\$(dirname $symlink) $source) $symlink"
      EXIT_CODE=1
      continue
    fi

    # Resolve symlink target (handle both relative and absolute paths)
    target=$(readlink "$symlink_path")

    # Convert relative symlink to absolute path for comparison
    if [[ "$target" != /* ]]; then
      symlink_dir=$(dirname "$symlink_path")
      target=$(cd "$symlink_dir" && realpath "$target")
    fi

    source_abs=$(realpath "$source_path")

    if [[ "$target" != "$source_abs" ]]; then
      echo "[-] ERROR: Symlink points to wrong target: $symlink"
      echo "    Expected: $source_abs"
      echo "    Actual:   $target"
      EXIT_CODE=1
      continue
    fi

    echo "[+] OK: $symlink -> $source"
  done
done

if [[ $EXIT_CODE -ne 0 ]]; then
  echo ""
  echo "[-] Symlink check FAILED"
  echo "    Some files are regular files but should be symlinks."
  echo "    This prevents duplicate content and ensures single source of truth."
  exit 1
fi

echo "[+] All required symlinks are valid"
exit 0
