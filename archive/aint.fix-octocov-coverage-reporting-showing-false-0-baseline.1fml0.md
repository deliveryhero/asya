---
title: "Fix octocov coverage reporting showing false 0% baseline"
status: merged
priority: 2
tags:
  - type:bug
---

## Investigation Findings

### Observed Issue
Each PR shows coverage raise from 0% baseline (e.g., PR #111 shows 0.0% → 56.6% +56.6%), indicating octocov cannot find previous coverage reports for comparison on main branch.

### Example Evidence
- **PR #111 Coverage Report**: Shows baseline as 0.0%, but actual coverage is 56.6%
  - This suggests octocov has no baseline to compare against
  - All changed files show "+X%" as if they went from 0% to X% coverage

### Root Cause Investigation
The octocov configuration (.octocov.yml) has:
- **Line 62-63**: Diff datastore configured to fetch baseline from artifact datastore
  - `datastores: [artifact://${GITHUB_REPOSITORY}]`
  - `path: report.json`
- **Line 70-74**: Report storage configured to save report.json to artifact datastore on default branch (main)
  - `datastores: [artifact://${GITHUB_REPOSITORY}]`
  - `path: report.json`

### Likely Root Causes
1. **Artifact Retention**: GitHub Actions artifacts have default 90-day retention but are deleted after workflow completion (cannot be restored across workflow runs by octocov)
2. **Report Persistence**: octocov's artifact:// datastore may not persist reports between PR and subsequent commits to main
3. **Timing Issue**: PR runs cannot access main branch's most recent report because:
   - PR runs happen before code is merged
   - Each PR creates its own artifact namespace
   - When PR merges, the artifact is deleted and new main run creates new artifact
   - Next PR runs cannot find previous main's report.json

### Files to Review
- : Coverage configuration and datastore setup (lines 59-74)
- : coverage-report job that runs octocov (lines 400+)
- GitHub Actions secrets/variables: Check if artifact datastore credentials are properly configured

### Next Steps (Implementation)
Need to determine if:
1. octocov artifact datastore supports cross-run persistence
2. Alternative storage needed (GitHub Pages, object storage, database)
3. Report.json should be committed to git instead of artifacts



## Notes

## Work Done (PR #129)

### Changes Made
1. Changed `.octocov.yml` datastore from `artifact://${GITHUB_REPOSITORY}` to `github://${GITHUB_REPOSITORY}@octocov`
2. Updated CI verification step in `.github/workflows/ci.yml` to check octocov branch instead of local file

### How It Should Work
- On main branch CI runs: octocov pushes `report.json` to dedicated `octocov` branch
- On PR CI runs: octocov fetches baseline from `octocov` branch for diff comparison
- The `octocov` branch is NOT served by GitHub Pages (separate from gh-pages)

### Verification After Merge
1. Check if `octocov` branch was created: `git fetch origin octocov`
2. Check if report.json exists: `git ls-tree origin/octocov`
3. Open a new PR and check if coverage diff shows actual baseline (not 0%)

### If Fix Doesn't Work - Things to Check
1. **Branch not created**: octocov may need write permissions - check `contents: write` in CI job
2. **Still showing 0%**: Verify `GITHUB_TOKEN` has push access to create branches
3. **Token permissions**: May need `permissions: contents: write` at workflow level
4. **First run edge case**: First PR after merge will still show 0% (no baseline yet) - this is expected
5. **octocov version**: Ensure octocov-action@v1 supports github:// datastore (v0.74+ does)

### Alternative Approaches If github:// Fails
- Use `s3://` datastore with AWS credentials (more complex infrastructure)
- Use `bq://` datastore with BigQuery (requires GCP)
- Commit report.json to main branch (noisy git history)
- Use a separate private repo for storage


**Close reason**: Fixed in PRs #164, #167, #170, #179. Root causes: (1) artifact:// datastore was ephemeral, switched to github:// datastore on octocov branch (PR #164). (2) fs.Sub(fsys, "") crashed with 'sub : invalid argument', fixed by appending /. to URL (PR #167). (3) diff.path: report.json silently overwrote loaded baseline with empty Report (time.Now() timestamp always newer), fixed by removing it (PR #179). (4) DEBUG logging enabled for future diagnostics (PR #170).


_Migrated from beads `asya-3zy`_
