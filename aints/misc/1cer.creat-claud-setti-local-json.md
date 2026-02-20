---
title: Create .claude/settings.local.json.example template
status: open
priority: 2 # medium
type: task
---

# Create .claude/settings.local.json.example Template

## Goal
Create an example template for `.claude/settings.local.json` that developers and AI agents can copy and customize for their local development setup.

## Implementation Plan

### 1. File Location
Create: `.claude/settings.local.json.example`

### 2. Template Content
```json
{
  "automation": {
    "hookOnToolCall": {
      "bash": [
        "linter check (runs on every bash command)",
        "only non-critical - can suggest fixes"
      ],
      "edit": [
        "formatter check (optional)",
        "warns about potential issues"
      ]
    },
    "onSessionStart": {
      "commands": [
        "bd prime (recover context after compaction)",
        "git status (show current state)"
      ]
    },
    "onSessionEnd": {
      "reminders": [
        "git status (check uncommitted changes)",
        "bd sync --from-main (sync beads from main branch)",
        "git push (push to remote - MANDATORY)"
      ]
    },
    "preferredAgents": {
      "codeReview": "superpowers:code-reviewer",
      "planning": "superpowers:writing-plans",
      "debugging": "superpowers:systematic-debugging",
      "testing": "superpowers:test-driven-development"
    }
  },
  "localPaths": {
    "worktreesDir": "$HOME/.asya-worktrees",
    "coverageDir": "/tmp/asya-coverage",
    "kindClusterName": "asya-e2e-local"
  },
  "testProfiles": {
    "integration": "sqs",
    "e2e": "sqs-s3",
    "defaultHandlerMode": "payload"
  },
  "editor": {
    "beforeSave": "make lint"
  }
}
```

### 3. Key Sections

**automation.hookOnToolCall**: Commands to run on each tool call (linter checks, etc.)

**automation.onSessionStart**: Commands to run at session start (bd prime, git status)

**automation.onSessionEnd**: Reminders for session completion (push to remote!)

**automation.preferredAgents**: Default agents for common tasks

**localPaths**: Where to store worktrees, coverage reports, Kind cluster names

**testProfiles**: Default test transport/storage combinations

**editor**: IDE hooks (e.g., run linter before save)

### 4. Instructions
Add comment at top:
```json
// .claude/settings.local.json.example
// Example settings for local development
// Copy to .claude/settings.local.json and customize for your environment
// DO NOT commit .claude/settings.local.json - it's in .gitignore
```

### 5. Documentation
Create small section in README or CONTRIBUTING.md:
```markdown
## Local Setup

Copy the example settings file:
\`\`\`bash
cp .claude/settings.local.json.example .claude/settings.local.json
\`\`\`

Then customize paths and preferences for your environment.
```

### 6. Acceptance Criteria
✓ `.claude/settings.local.json.example` exists and is valid JSON
✓ All key sections documented with comments
✓ Example values are realistic and helpful
✓ File is NOT in .gitignore (example should be tracked)
✓ .claude/settings.local.json IS in .gitignore (local copy shouldn't be tracked)
✓ Linter passes

## Ready to be done
Marked ready when template is complete and properly formatted.


---
_Migrated from beads `asya-p8i`_
