---
title: "Gateway chart: s3/gcs backend for mesh state proxy, update e2e profiles"
status: working
priority: 2 # medium
assignee: Artem Yushkovskiy
---



Add backend field to stateProxy.mesh in gateway chart (pg-kv|s3|gcs). Switch pubsub-gcs e2e to GCS mesh state proxy, sqs-s3 to S3 mesh state proxy.
