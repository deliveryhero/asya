---
title: "Test: E2E actor deployment with flavors"
status: merged
priority: 2
dependencies:
  - 1fzs
---

Add end-to-end test for deploying actors with flavors in a Kind cluster.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md

Test scenario:
1. Deploy asya-crossplane chart with default flavors
2. Install function-asya-flavors
3. Create an AsyncActor with flavors: [flow-router]
4. Verify Deployment has correct resources, scaling, env vars from the flow-router flavor
5. Create a custom flavor EnvironmentConfig and actor referencing it
6. Verify custom flavor values appear in the Deployment
7. Update the custom flavor and verify the Deployment converges to new values

Test location: testing/e2e/
Extend existing E2E test infrastructure, do not create a new Kind cluster.


_Migrated from beads `asya-3j7r`_
