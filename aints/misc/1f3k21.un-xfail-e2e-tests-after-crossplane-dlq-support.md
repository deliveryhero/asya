---
title: Un-xfail E2E tests after Crossplane DLQ support
status: open
priority: 3 # low
type: task
---


Once Crossplane Composition supports these features, remove skip/xfail markers from these tests:

## DLQ tests (need SQS RedrivePolicy + DLQ creation in Composition):
- tests/test_dlq_e2e.py::test_poison_message_moves_to_dlq_e2e
- tests/test_dlq_e2e.py::test_dlq_preserves_envelope_metadata_e2e

## Timeout tests (need timeout field in XRD + injector passing ASYA_HANDLER_TIMEOUT):
- tests/test_edge_cases_e2e.py::test_timeout_crash_and_pod_restart_e2e

## Operator feature parity xfails:
- tests/test_operator_e2e.py::test_asyncactor_invalid_transport (XRD validation)
- tests/test_operator_e2e.py::test_asyncactor_with_statefulset (StatefulSet support)
- tests/test_operator_e2e.py::test_asyncactor_label_propagation (label propagation)

NOTE: test_asyncactor_status_conditions was previously listed here but now
PASSES after switching to status.phase-based readiness check (commit 961e562).

NOTE: Queue health monitoring tests (4) and KEDA scaling tests (9) are tracked
in asya-zpz2 instead — they relate to XR readiness and Crossplane drift
detection, not to missing Composition features.


---
_Migrated from beads `asya-bija`_
