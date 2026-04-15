---
title: Memory state proxy with cron dreaming flow
status: open
priority: 1 # high
tags: [autoresearch, state-proxy, memory, agentic]
dependencies: [8v7o0/34yhs, 8v7o0/cy0p1]
---

## Context

Autoresearch orchestrator actors accumulate "reasoning history" across loop
iterations — decisions, observations, what worked/failed. This is the actor
equivalent of Claude Code's auto-memory system.

Two components: a state proxy for storage + a cron flow for curation.

## Part 1: Memory State Proxy

S3-backed (existing S3 connector with dedicated prefix). Mounts at `/memory/`.

Actor sees:
```
/memory/
  MEMORY.md                    # index: one-line summaries
  project.experiment-v3.md     # topic file (YAML frontmatter + body)
  feedback.lr-scheduling.md    # topic file
  raw/
    iteration-005.md           # raw observations (written by actor)
```

File layout follows Claude Code's memory taxonomy:
- YAML frontmatter: `name`, `description`, `type` (project/feedback/reference)
- Types: project (experiment state), feedback (what worked/failed), reference
  (pointers to artifacts on S3)

Actor reads MEMORY.md, decides which topic files to read (simple grep or read
all if few), loads them. No sidecar magic for relevance — handler does it.

Write-triggered index rebuild: when actor writes a file, the sidecar
deterministically rebuilds MEMORY.md index (scan files, read frontmatter
descriptions, write one-line entries). No LLM call — just file scanning.

Same S3 backend can be mounted differently:
- Agent actor: mounts via memory state proxy (with index rebuild hook)
- Dreaming flow: mounts as plain S3 state proxy (raw file access, rewrites)

## Part 2: Dreaming Cron Flow

Scheduled Asya flow (e.g. every hour) that:
1. Mounts memory as plain S3 state proxy (raw access)
2. Reads all topic files + raw observations
3. Calls LLM to: summarize raw observations into topic files, deduplicate,
   prune stale memories, update descriptions
4. Writes back curated topic files, deletes processed raw observations
5. Index is rebuilt automatically on next agent write (or dreaming flow
   can write a dummy file to trigger rebuild)

This mirrors Claude Code's opportunistic memory writing, but as an explicit
pipeline step with LLM-powered curation.

## Testing

- Unit: index rebuild from frontmatter scanning
- Unit: write triggers index rebuild
- Component: actor writes raw observation, reads back via index
- Component: dreaming flow compacts raw observations into topic files
