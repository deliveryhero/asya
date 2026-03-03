---
title: Fix missing charts/ folder on gh-pages branch
priority: 1 # high
tags:
  - type:bug
---





## Problem
  The gh-pages branch exists but has no charts/ folder, causing https://asya.sh/charts/index.yaml to return 404.

  ## Root Cause
  In .github/workflows/release.yml:
  1. Line 149: cp ... || true - silently fails if no .tgz files
  2. Line 158: git commit ... || exit 0 - exits successfully even if nothing to commit

  ## Evidence
  - v0.4.0 release job succeeded in 7s (suspiciously fast)
  - gh-pages branch shows no charts/ folder
  - https://asya.sh/charts/index.yaml returns 404

  ## Fix Required
  1. Remove || true from cp command
  2. Add explicit error checking after helm package step
  3. Consider: should asya-playground be packaged in a separate step after other charts are published?


---
**Close reason**: Fixed in PR #127: https://github.com/deliveryhero/asya/pull/127


---
_Migrated from beads `asya-b0e`_
