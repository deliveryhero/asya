---
title: "Helm chart: add x-pause and x-resume to asya-crew chart"
status: merged
priority: 2
dependencies:
  - 1kcww
  - 1kr9s
tags:
  - pr:221
---

Add x-pause and x-resume actor definitions to deploy/helm-charts/asya-crew. Configure S3 credentials, handler paths, and environment variables. Both actors use the same image as other crew actors.
