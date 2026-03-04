---
title: "Crossplane XRD: add timeout field support"
priority: 3 # low
---

The AsyncActor XRD does not support a timeout field yet. This blocks E2E test test_timeout_crash_and_pod_restart_e2e which verifies that timeout causes pod crash and KEDA rescales for retry. See testing/e2e/tests/test_edge_cases_e2e.py.
