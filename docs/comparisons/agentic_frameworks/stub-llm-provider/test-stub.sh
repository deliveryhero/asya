#!/bin/bash
# Test the stub AI provider endpoints

set -e

BASE_URL="${1:-http://localhost:8100}"

echo "Testing stub AI provider at $BASE_URL"
echo "========================================"

# Health check
echo -n "Health check: "
curl -sf "$BASE_URL/health" && echo "OK" || echo "FAILED"

# OpenAI endpoint
echo -n "OpenAI /v1/chat/completions: "
curl -sf "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer stub-test-key" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}' \
  | head -c 100 && echo "... OK"

# Anthropic endpoint
echo -n "Anthropic /v1/messages: "
curl -sf "$BASE_URL/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: stub-test-key" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-3-5-sonnet-20241022","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}' \
  | head -c 100 && echo "... OK"

# Gemini endpoint
echo -n "Gemini /v1beta/models: "
curl -sf "$BASE_URL/v1beta/models/gemini-2.0-flash:generateContent" \
  -H "Content-Type: application/json" \
  -d '{"contents":[{"parts":[{"text":"Hello"}]}]}' \
  | head -c 100 && echo "... OK"

echo "========================================"
echo "All endpoints responding!"
