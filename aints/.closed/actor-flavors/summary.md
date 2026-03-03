---
title: Actor Flavors
priority: 2 # medium
---



Implement actor flavors as composable configuration presets using Crossplane EnvironmentConfigs and a custom Composition Function (function-asya-flavors). See RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md

Goal: Allow AsyncActor specs to reference named flavors (spec.flavors: [gpu-t4, openai-keys]) that provide reusable configuration presets. Flavors are partial AsyncActor specs stored as EnvironmentConfigs, merged via strategic merge patch in a custom Composition Function.

Key deliverables:
1. XRD schema change (add spec.flavors field)
2. EnvironmentConfig selector slots in Composition
3. Custom Composition Function (function-asya-flavors) for strategic merge
4. Default flavor EnvironmentConfigs shipped with asya-crossplane chart
5. Go template updates to consume resolved flavor data
6. Unit and integration tests
7. E2E test with flavor-based actor deployment
