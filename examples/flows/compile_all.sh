#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$SCRIPT_DIR/../../src/asya-cli"

echo "[.] Compiling all flow examples..."
echo ""

cd "$CLI_DIR"

echo "[.] Compiling simple_pipeline.py..."
uv run asya flow compile "$SCRIPT_DIR/simple_pipeline.py" -o "$SCRIPT_DIR/simple_pipeline_compiled.py"

echo "[.] Compiling conditional_routing.py..."
uv run asya flow compile "$SCRIPT_DIR/conditional_routing.py" -o "$SCRIPT_DIR/conditional_routing_compiled.py"

echo "[.] Compiling loop_processing.py..."
uv run asya flow compile "$SCRIPT_DIR/loop_processing.py" -o "$SCRIPT_DIR/loop_processing_compiled.py"

echo "[.] Compiling complex_workflow.py..."
uv run asya flow compile "$SCRIPT_DIR/complex_workflow.py" -o "$SCRIPT_DIR/complex_workflow_compiled.py"

echo ""
echo "[+] All examples compiled successfully!"
echo ""
echo "Compiled files:"
ls -lh "$SCRIPT_DIR"/*_compiled.py
