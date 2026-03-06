---
title: "Crossplane queue health monitoring: operator queue recreation not applicable"
priority: 3 # low
---

All 4 queue health monitoring E2E tests are skipped because Crossplane manages queues via AWS/GCP providers, making operator-level queue health checks not applicable. Tests: test_operator_recreates_deleted_actor_queue_e2e, test_operator_recreates_deleted_system_queue_e2e, test_multiple_queue_deletions_e2e, test_queue_deletion_during_processing_e2e. These tests assumed an operator model. Need to decide: rewrite for Crossplane reconciliation or delete.
