---
description: Analyze PR comments, implement fixes, and post targeted responses
---

# PR Comment Analyzer & Resolver

Analyze all comments on a GitHub pull request, implement changes, and post targeted responses to each review comment using `gh` CLI.

## Usage

Provide a GitHub PR URL or PR number:

```bash
/fix-pr-review-comments https://github.com/deliveryhero/asya/pull/119
# or
/fix-pr-review-comments 119
```

## Process

1. **Fetch PR Details**
   - Get PR URL, branch name, current files
   - List all comments (review comments and conversations)

2. **Analyze Each Comment**
   - Categorize: bug fix, enhancement, documentation, style/formatting, validation, question
   - Assess: actionable vs informational
   - Extract key requirements

3. **For Actionable Comments**
   - Implement suggested changes
   - Run validation (linting, tests if applicable)
   - Create focused, logical commits
   - Push to PR branch

4. **Post Targeted Responses**
   - Reply directly to each review comment (not general PR comment)
   - Use `gh api` to post reply in the specific conversation thread
   - Keep responses concise and focused on that specific suggestion
   - Use `gh api` to mark conversation as resolved if applicable

5. **No Generic Summaries**
   - Post targeted, context-specific responses only
   - Each suggestion gets a reply in its own thread
   - Skip generic summaries - let the implementation speak

## Response Format

For each review comment:
- Reply directly in the conversation thread (not new PR comment)
- Keep it very short: "✅ Implemented in commit XYZ - [brief description]" is enough
- Mark conversation as resolved if applicable (via `gh` API)

## Implementation Notes

- Work in the existing branch (don't create new branches)
- Preserve existing commits; append new commits
- Use `gh api` to reply to specific review comments (see "Posting Replies" below)
- Run quality gates after each logical change group
- Always preserve original PR intent and author's work

## Working with Review Threads

GitHub review comments are organized into threads. Use GraphQL API to query and resolve threads.

### Get Review Threads for a PR

```bash
PR_NUMBER="124"
OWNER="deliveryhero"
REPO="asya"

# Query all review threads with their IDs and resolution status
gh api graphql -f query='
query {
  repository(owner: "'"$OWNER"'", name: "'"$REPO"'") {
    pullRequest(number: '"$PR_NUMBER"') {
      reviewThreads(first: 20) {
        nodes {
          id
          isResolved
          comments(first: 1) {
            nodes {
              databaseId
              body
              path
              line
            }
          }
        }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | {
  thread_id: .id,
  resolved: .isResolved,
  comment_id: .comments.nodes[0].databaseId,
  file: .comments.nodes[0].path,
  line: .comments.nodes[0].line,
  body_preview: .comments.nodes[0].body[0:80]
}'
```

### Resolve a Review Thread

```bash
THREAD_ID="PRRT_kwDOQPyv8s5sQjKy"  # From query above

# Mark the entire conversation thread as resolved
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "'"$THREAD_ID"'"}) {
    thread {
      id
      isResolved
    }
  }
}' --jq '.data.resolveReviewThread.thread'
```

### Resolve All Threads for a PR

```bash
#!/bin/bash
# Resolve all unresolved review threads

PR_NUMBER="124"
OWNER="deliveryhero"
REPO="asya"

# Get all unresolved thread IDs
THREADS=$(gh api graphql -f query='
query {
  repository(owner: "'"$OWNER"'", name: "'"$REPO"'") {
    pullRequest(number: '"$PR_NUMBER"') {
      reviewThreads(first: 50) {
        nodes {
          id
          isResolved
        }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id' -r)

# Resolve each thread
for THREAD_ID in $THREADS; do
  echo "[.] Resolving thread: $THREAD_ID"
  gh api graphql -f query='
    mutation {
      resolveReviewThread(input: {threadId: "'"$THREAD_ID"'"}) {
        thread {
          id
          isResolved
        }
      }
    }
  ' --jq '.data.resolveReviewThread.thread | {id, isResolved}'
done
```

### Post a Comment on a PR (General Comment)

```bash
PR_NUMBER="124"

# Post a general PR comment (not a review comment on specific lines)
gh pr comment "$PR_NUMBER" --body "✅ All review comments addressed in commit ABC123"
```

### Important Notes

- **Review threads** are groups of comments on specific lines/files
- **Thread IDs** are in format `PRRT_kwDO...` (use GraphQL to get them)
- **Resolving** marks the entire conversation thread as addressed
- Only PR authors, reviewers, or repo collaborators can resolve threads
- **Comment IDs** (numeric) are different from thread IDs (base64 strings)
