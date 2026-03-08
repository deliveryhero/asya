---
title: K8s Secrets support for AsyncActor (v0)
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/agentic-security/wcnw.k8s-secrets-support-asyncactor-v0
  - branch:agentic-security/wcnw.k8s-secrets-support-asyncactor-v0
dependencies:
  - 1fuy
---


Enable AsyncActor workloads to consume sensitive credentials (AI API tokens, DB passwords) via standard Kubernetes Secrets. This is the minimum viable secret injection story for v0 — no external vault required.

## Problem

Actors using LLM APIs (OpenAI, Anthropic, etc.) need API tokens available at runtime. Without a defined pattern, users resort to hardcoding or unsafe env var injection.

## Scope

### AsyncActor CRD extension
Add `spec.secretRefs` to the AsyncActor XRD:

\`\`\`yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: openai-summarizer
spec:
  handler: my_module.summarize
  secretRefs:
    - secretName: openai-creds
      keys:
        - key: api_key
          envVar: OPENAI_API_KEY
\`\`\`

Actor code reads `os.environ["OPENAI_API_KEY"]` — no secret-fetching logic.

### Injector webhook
When `spec.secretRefs` is present, the asya-injector webhook:
- Adds `envFrom` or `env[].valueFrom.secretKeyRef` entries to the sidecar container spec
- Validates that referenced Secrets exist in the same namespace at admission time (warn-only: block is too strict for PoC)

### Crossplane Composition
Pass `secretRefs` through from XRD claim to the generated Deployment.

### Documentation
- Quick-start example with an OpenAI actor using `secretRefs`
- Note that Secrets in etcd should be encrypted at rest (link to K8s docs)

## Out of Scope (post-v0)
- External secret stores (Vault, AWS Secrets Manager, ESO) — tracked in [1fdf]
- Secret rotation without pod restart
- Audit logging for secret access

## Acceptance Criteria
- AsyncActor with `secretRefs` correctly injects env vars into actor pods
- Actor Python code reads injected env vars transparently
- Unit tests for injector webhook secret injection logic
- Integration test: actor that echoes `os.environ["TEST_SECRET"]` receives correct value
- Quick-start docs updated with AI API token example
