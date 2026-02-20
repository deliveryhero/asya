---
title: Document example flavor EnvironmentConfigs for asya-quickstart
status: open
priority: 2 # medium
type: task
dependencies:
  - misc/1cw3
---

Create example flavor EnvironmentConfigs as documentation and future asya-quickstart chart content.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md (Section 4.5)

Context: The Asya framework does NOT ship default flavors in asya-crossplane. Flavor definitions are the responsibility of platform engineers. A future asya-quickstart Helm chart will provide example flavors as starting points.

Deliverables:
- Directory: examples/flavors/ (example EnvironmentConfigs, not deployed by default)
- Example flavors to document:
  1. gpu-t4 - GPU workload with nodeSelector, tolerations, resources
  2. always-on - minReplicas: 1, conservative scaling
  3. scale-to-zero - minReplicas: 0, standard KEDA defaults
  4. burst - High-throughput: 0-100 replicas, fast polling
  5. flow-router - Envelope mode, python:3.13-slim, lightweight resources
  6. openai-keys - OPENAI_API_KEY from secretKeyRef

Each example must:
- Have label asya.sh/flavor: <name>
- Store data under key matching flavor name (for merge safety, see RFC Section 4.3)
- Use K8s-native syntax (env as list of {name, value/valueFrom})
- Include comments explaining the flavor's purpose and key settings

These examples serve as documentation and templates for platform engineers to adapt.


---
_Migrated from beads `asya-dgnn`_
