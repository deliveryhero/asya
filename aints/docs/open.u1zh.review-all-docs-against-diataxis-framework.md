---
title: Review all docs against Diataxis framework
priority: 2 # medium
---

Audit the full docs/ tree against the Diataxis framework (https://diataxis.fr):

Four quadrants:
- Tutorials: learning-oriented, teach by doing
- How-to guides: task-oriented, practical steps
- Reference: information-oriented, accurate description
- Explanation: understanding-oriented, background context

Goals:
1. Classify every existing doc into one of the four quadrants
2. Identify docs that mix quadrants (most common issue)
3. Identify gaps -- missing quadrants for key features
4. Produce a short remediation plan: rename, split, or rewrite

Scope:
- docs/features/: likely explanations/how-to, check for tutorial leakage
- docs/architecture/: likely reference + explanation
- docs/tutorials/: verify these are actually tutorials (not how-to)
- docs/reference/: verify completeness and accuracy-orientation
- docs/internal/: not user-facing, skip Diataxis but check consistency
- docs/quickstart/: typically tutorial quadrant, verify

Output:
- Classification table (file, quadrant, issues)
- List of files to split/rename
- List of missing docs to create
- No rewrites in this aint -- just the audit and plan
