#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSPORT="${ASYA_TRANSPORT:-sqs}"
IMAGE="${ASYA_RUNTIME_IMAGE:-localhost/asya-runtime:latest}"
NAMESPACE="${NAMESPACE:-asya-e2e}"

echo "[.] Deploying flow actors for nested_if flow"
echo "    Transport: $TRANSPORT"
echo "    Image: $IMAGE"
echo "    Namespace: $NAMESPACE"

sed -e "s|TRANSPORT_PLACEHOLDER|$TRANSPORT|g" \
  -e "s|IMAGE_PLACEHOLDER|$IMAGE|g" \
  "$SCRIPT_DIR/manifests/actors.yaml" | kubectl apply -f -

echo "[+] Flow actors deployed successfully"

echo "[.] Waiting for actors to be ready..."
kubectl wait --for=condition=Ready \
  --timeout=300s \
  -n "$NAMESPACE" \
  asyncactor/start-test-nested-flow \
  asyncactor/router-test-nested-flow-line-9-if-7 \
  asyncactor/router-test-nested-flow-line-11-if-3 \
  asyncactor/router-test-nested-flow-line-12-seq-1 \
  asyncactor/router-test-nested-flow-line-15-seq-2 \
  asyncactor/router-test-nested-flow-line-19-if-6 \
  asyncactor/router-test-nested-flow-line-20-seq-4 \
  asyncactor/router-test-nested-flow-line-23-seq-5 \
  asyncactor/validate-input \
  asyncactor/route-a-x \
  asyncactor/route-a-y \
  asyncactor/route-b-x \
  asyncactor/route-b-y \
  asyncactor/finalize-result

echo "[+] All flow actors ready"
