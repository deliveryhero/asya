#!/bin/bash
set -euo pipefail

# Check that Chart.lock files don't contain file:// dependencies
# This prevents accidentally committing locks generated from Chart.yaml.local

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

EXIT_CODE=0

echo "[+] Checking Chart.lock files for file:// dependencies..."

# Find all Chart.lock files
while IFS= read -r -d '' lock_file; do
  rel_path="${lock_file#"$REPO_ROOT"/}"

  if grep -q 'file://' "$lock_file"; then
    echo "[-] ERROR: $rel_path contains file:// dependencies"
    echo ""
    echo "    Chart.lock files must use remote repository URLs, not local file:// paths."
    echo "    This usually happens when Chart.lock is generated from Chart.yaml.local."
    echo ""
    echo "    To fix:"
    echo "      1. Ensure Chart.yaml uses remote repositories (https://...)"
    echo "      2. Run: helm dependency update <chart-dir>"
    echo "      3. Verify Chart.lock no longer contains file://"
    echo ""
    echo "    Offending lines:"
    grep -n 'file://' "$lock_file" | sed 's/^/      /'
    echo ""
    EXIT_CODE=1
  else
    echo "[+] OK: $rel_path"
  fi
done < <(find "$REPO_ROOT" -name "Chart.lock" -type f -print0)

if [[ $EXIT_CODE -ne 0 ]]; then
  echo ""
  echo "[-] Chart.lock check FAILED"
  exit 1
fi

echo "[+] All Chart.lock files use remote repositories"
exit 0
