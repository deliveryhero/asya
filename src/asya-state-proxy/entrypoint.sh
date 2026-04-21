#!/bin/sh
set -e
case "$ASYA_CONNECTOR" in
  *[!a-zA-Z0-9_]* | "")
    echo "[!] ASYA_CONNECTOR must be set to a valid connector name (alphanumeric + underscore)"
    exit 1
    ;;
esac
exec python -m "asya_state_proxy.connectors.${ASYA_CONNECTOR}"
