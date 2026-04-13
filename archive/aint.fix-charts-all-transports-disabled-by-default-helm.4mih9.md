---
title: "fix(charts): all transports disabled by default in Helm values"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: 00000
tags:
  - worktree:.worktrees/misc/4mih.fix-charts-all-transports-disabled-by-default-helm
  - branch:misc/4mih.fix-charts-all-transports-disabled-by-default-helm
---

## Problem

\`asya-crossplane\` defaults to \`providers.aws.enabled: true\` and \`irsa.enabled: true\`.
With many transports planned (SQS, Pub/Sub, RabbitMQ, NATS, etc.), enabling any transport
by default forces all users to explicitly disable things they don't use — backwards.

The principle should be: nothing is enabled by default, users opt in to exactly the
transport they need.

## Changes

### \`deploy/helm-charts/asya-crossplane/values.yaml\`

\`\`\`yaml
# before
providers:
  aws:
    enabled: true   # → false
  gcp:
    enabled: false  # already correct
irsa:
  enabled: true     # → false  (AWS-specific)
\`\`\`

### \`deploy/helm-charts/asya-crew/values.yaml\`

\`\`\`yaml
# before
dlq-worker:
  enabled: true     # → false  (SQS-specific DLQ worker)
\`\`\`

Note: \`x-sink.enabled\`, \`x-sump.enabled\`, and \`scaling.enabled\` stay \`true\` —
these are not transport-specific, they are always-needed crew actors/behaviors.

## Impact on callers

Any install command currently passing \`--set providers.aws.enabled=false\` or
\`--set irsa.enabled=false\` can drop those flags. The GKE docs (\`docs/install/gcp-gke.md\`)
already does this.

## Files

- \`deploy/helm-charts/asya-crossplane/values.yaml\`
- \`deploy/helm-charts/asya-crew/values.yaml\`
