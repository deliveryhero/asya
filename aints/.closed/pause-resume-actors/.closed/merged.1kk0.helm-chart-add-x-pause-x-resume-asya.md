---
title: "Helm chart: add x-pause and x-resume to asya-crew chart"
priority: 2 # medium
tags:
  - pr:221
dependencies:
  - 1kcw
  - 1kr9
---



Add x-pause and x-resume actor definitions to deploy/helm-charts/asya-crew. Configure S3 credentials, handler paths, and environment variables. Both actors use the same image as other crew actors.
