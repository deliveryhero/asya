---
title: "E2E rabbitmq-minio: Crossplane Requirements API race blocks flavored actors"
status: open
priority: 2 # medium
---

## Problem

The rabbitmq-minio E2E profile cannot run successfully because Crossplane's
Requirements API has a concurrency limitation when reconciling many XRs in
a single batch on a resource-constrained Kind node.

## Root Cause

function-asya-flavors uses the Requirements API to request EnvironmentConfigs
by name. This requires 2+ reconciliation cycles per XR:
1. Function sets Requirements -> Crossplane fetches EnvironmentConfigs
2. Function receives EnvironmentConfigs -> merges flavors -> emits composed resources

When 40+ actors deploy simultaneously, Crossplane processes them in batches.
Some XRs in the batch get the EnvironmentConfigs populated in their required
map, others don't. The ones that don't are stuck permanently in "Waiting for
flavor EnvironmentConfigs".

## Evidence

CI runs (PR #431):
- https://github.com/deliveryhero/asya/actions/runs/24418802352/job/71335199264
- https://github.com/deliveryhero/asya/actions/runs/24424095943/job/71353809137

Function logs show same-timestamp invocations where some XRs get flavors
applied and others get "Waiting":

    {"msg":"Processing flavors","flavors":["asya-test-actor"]}
    {"msg":"Flavors applied","count":1}         <- XR A succeeds
    {"msg":"Processing flavors","flavors":["asya-test-actor"]}
    {"msg":"Waiting for flavor EnvironmentConfigs"}  <- XR B fails (same second)

Crossplane circuit breaker also trips under this load:

    {"msg":"Circuit breaker is open","controller":"composite/xasyncactors.asya.sh"}

## What was tried (and reverted)

All attempts in PR #431 (commits reverted):
1. Skip stagger annotations for rabbitmq-minio -> circuit breaker still trips from initial deploy
2. Increase max-reconcile-rate 50->100, CPU 500m->1000m -> reduced circuit breaker events (dozens->9) but flavors still fail
3. Wait for function pods to be Ready before deploying actors -> pods were ready, issue persists
4. Remove stagger entirely, replace with kubectl wait for XRs -> same result

## Why sqs-s3 and pubsub-gcs work

Lighter infra pods (LocalStack=1 container vs RabbitMQ+MinIO=2 StatefulSets).
More CPU available for Crossplane reconciliation. Same actors, same flavors,
same compositions -- just more headroom.

## Infra fixes discovered (useful when re-enabling)

These fixes are valid but reverted since the E2E profile is disabled:
- helmfile.yaml.gotmpl: rabbitmq/minio needs must be namespace-qualified (commit 49ffb564)
- research-flow-aggregator.yaml: nil-safe stateProxy connector lookup with dig (commit 06fbdbb5)
- research-flow-aggregator.yaml: treat minio as s3-compatible (commit 416c3c06)
- rabbitmq-minio.yaml: add connector.image override for dev builds (commit dcc08211)
- deploy.sh: build/load state-proxy image for rabbitmq-minio (commit 9866263a)
- deploy.sh: wait for function pods across all namespaces (commit 2d5ab77e)

## Possible fixes

1. Deploy actors in batches (crew first, test-actors second, test-flows third)
2. Reduce total actor count in rabbitmq-minio profile
3. Increase Kind node resources (multi-node cluster)
4. Wait for upstream Crossplane fix for Requirements API batch consistency
5. Add retry/requeue logic in function-asya-flavors for missing EnvironmentConfigs

## Related

- GitHub issue: #432
- PR: #431
