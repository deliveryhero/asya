---
title: "Analyze and fix E2E tests: sqs-s3 failure in PR #78 (expr 1.17.7 bump)"
status: done
priority: 2 # medium
type: task
---


## Analysis Summary

**PR #78 Details**: Bump expr from 1.17.0 to 1.17.7 in testing/integration/operator

**Status**: E2E job failed with exit code 1 at final verification step (Check if e2e tests succeeded)

**Key Finding**: All actual test phases PASSED:
- Helm tests: All passed (asya-gateway, asya-operator, test-actors)
- E2E test execution: All passed (operator, non-chaos payload/envelope, chaos payload)
- Final verification: FAILED (exit code 1)

**Failure Type**: Silent failure - tests appear to complete but final verification step detected error

**Root Cause Analysis**:
expr v1.17.7 introduces breaking changes:
1. New 'else if' operator support and 'if' operator behavior changes
2. Stricter nil/undefined variable handling via AsBool()
3. Auto-dereference corrections for maps/slices
4. Unexported struct field access restrictions
5. Error message position changes in multi-line scripts

**Impact**: Likely affects Flow DSL expression parsing in operator integration tests

**Comparison**: PR #91 (similar expr bump) only affects component tests, not integration tests

**Next Steps**: 
1. Check test flow DSL definitions for conditional/nil expression compatibility
2. Review operator expression caching for 1.17.7 incompatibilities
3. Examine nil handling in route condition evaluation
4. Test actor fixture definitions for expr 1.17.7 compatibility



---
## Notes

Previous fix attempt pushed to rfc0 instead of PR branches. Need to redo with correct git worktree branches.


---
**Close reason**: All E2E test failures fixed and verified passing on remote CI


---
_Migrated from beads `asya-bj3`_
