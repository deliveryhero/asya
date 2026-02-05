#!/usr/bin/env bash

# Load environment variables from profile-specific .env file
# Usage: source ./load-profile.sh

if [ -z "${PROFILE}" ]; then
  echo "[!] PROFILE is not set, skipping profile env loading"
  exit 1
fi

if [ -z "${PROJECT_ROOT}" ]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2> /dev/null || echo "$(dirname "$0")/../../..")
fi

ENV_FILE="${PROJECT_ROOT}/testing/e2e/profiles/.env.${PROFILE}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "[!] Profile env file not found: ${ENV_FILE}"
  exit 1
fi

echo "[.] Loading environment from: ${ENV_FILE}"

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

echo "[+] Environment loaded for profile: ${PROFILE}"
