---
title: "Research: kubectl-asya via Krew vs custom CLI wrapper"
status: rejected
priority: 3
parent: 00000
tags:
  - type:feature
---

## Research Objective

Evaluate whether `kubectl asya` (via Krew plugin) is a better approach than building a standalone `asya` CLI that wraps kubectl for Kubernetes operations (deploy, logs, status, etc.).

## Core Tension

**Reduce maintenance burden** vs **Data scientist accessibility**

- Kubectl plugins leverage existing kubectl auth, contexts, and patterns
- But data scientists often find kubectl intimidating
- Need to find the right abstraction level

## Current State

`asya-cli` exists with:
- `asya mcp *` - MCP gateway interaction (call tools, stream, status)
- `asya flow *` - Flow DSL compilation

Future needs:
- `asya deploy` - Deploy actors from configs
- `asya logs` - Stream actor logs
- `asya status` - Show actor health, queue depths
- `asya scale` - Manual scaling overrides
- `asya debug` - Attach to actor, inspect envelopes

## Option A: kubectl-asya plugin (via Krew)

**How it works:**
- Distribute via Krew: `kubectl krew install asya`
- Users run: `kubectl asya deploy`, `kubectl asya logs <actor>`
- Plugin is a Go binary that calls kubectl/client-go internally

**Pros:**
- Inherits kubectl auth (kubeconfig, contexts, RBAC)
- Familiar pattern for K8s operators
- Single distribution channel (Krew)
- No "yet another CLI" to install
- Plugin can use client-go directly (no kubectl subprocess)

**Cons:**
- Requires kubectl installed (extra dep for data scientists)
- `kubectl` prefix may intimidate non-K8s users
- Plugin ecosystem less discoverable than standalone CLIs
- Two CLIs to maintain (`asya` for flow/mcp, `kubectl asya` for K8s ops)

## Option B: Standalone asya CLI (wrap kubectl)

**How it works:**
- Single `asya` CLI for everything
- K8s commands shell out to kubectl or use client-go
- Users run: `asya deploy`, `asya logs <actor>`

**Pros:**
- Single CLI, unified UX
- Can hide K8s complexity behind friendly commands
- `asya deploy my-actor.yaml` feels less scary than kubectl
- Full control over output formatting, error messages

**Cons:**
- Must handle kubeconfig, contexts, auth (reinvent kubectl)
- More code to maintain
- Users still need kubectl for debugging anyway
- May create false sense that "no K8s knowledge needed"

## Option C: Hybrid approach

- `asya` CLI for non-K8s operations (flow, mcp, local dev)
- `kubectl asya` plugin for K8s operations
- Clear separation: "use asya locally, kubectl asya on cluster"

**Pros:**
- Each tool does what it's best at
- kubectl plugin gets K8s auth for free
- asya CLI stays lightweight

**Cons:**
- Two tools to learn
- Discoverability: users may not know about the plugin

## Option D: asya CLI with optional K8s mode

- `asya` CLI works standalone for flow/mcp
- `asya deploy` detects kubeconfig and uses client-go
- No kubectl subprocess, but also no plugin distribution

**Pros:**
- Single CLI
- No kubectl wrapper overhead
- Can provide "simplified K8s" UX for data scientists

**Cons:**
- client-go adds significant Go dependency weight
- Still need to handle auth complexity

## Key Research Questions

1. **User research**: Who will use these commands?
   - Platform engineers → comfortable with kubectl
   - Data scientists → want to avoid kubectl
   - ML engineers → somewhere in between

2. **Auth complexity**: How hard is kubeconfig/context handling?
   - client-go makes it easy, but adds ~50MB to binary
   - Shelling to kubectl is simpler but fragile

3. **Krew ecosystem**: Is Krew adoption high enough?
   - Check if target users already have Krew
   - Alternative: distribute as standalone binary + kubectl plugin manifest

4. **Precedent**: How do similar projects handle this?
   - Argo: `argocd` CLI (standalone) + `kubectl argo rollouts` plugin
   - Knative: `kn` CLI (standalone)
   - KEDA: No CLI (kubectl only)
   - Crossplane: `kubectl crossplane` plugin

## Data Scientist UX Considerations

If data scientists are the target:
- Hide K8s concepts where possible
- `asya deploy model.py` instead of `asya deploy asyncactor.yaml`
- `asya logs my-model` instead of `kubectl logs -l app=my-model`
- Provide "escape hatch" to kubectl for power users

Maybe the real question: **Should data scientists interact with K8s at all, or should Asya provide a higher-level abstraction?**

## Research Deliverables

1. **User interview summary** - Who needs what commands?
2. **Prototype both approaches** - Simple deploy/logs commands
3. **Binary size comparison** - With/without client-go
4. **Recommendation** with maintenance cost analysis


---
## Notes

## Initial Thoughts (from creation)

**Maintenance burden is the key driver:**
- Every line of kubectl-wrapping code is a liability
- Auth/context handling is notoriously tricky
- kubectl output parsing breaks across versions
- client-go version must match cluster API version

**The "data scientists fear kubectl" problem:**
- This is real, but may not be solvable at CLI level
- Even `asya deploy` requires understanding pods, logs, scaling
- Maybe the answer is: don't have DS deploy directly
- GitOps (Flux/Argo) + PR-based deploy might be better UX

**Precedent analysis needed:**
- Kubeflow: Has `kfctl` but also kubectl plugins
- MLflow: No K8s CLI, relies on deployment integrations
- Seldon: `seldon` CLI for local, kubectl for cluster
- BentoML: `bentoml deploy` abstracts K8s entirely

**Minimum viable approach:**
- Start with NO K8s commands in asya CLI
- Document kubectl commands in `asya --help` output
- Add K8s commands only when clear pattern emerges
- "Do less, but do it well"

**If we do build K8s commands:**
- kubectl plugin is lower maintenance than wrapper
- Krew distribution is optional (can be standalone binary)
- Any binary named `kubectl-foo` becomes `kubectl foo` automatically


---
_Migrated from beads `asya-tix`_
