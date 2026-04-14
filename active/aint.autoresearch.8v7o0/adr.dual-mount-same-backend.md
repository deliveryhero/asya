# ADR: Dual Mount Pattern — Same Backend, Different Abstraction

**Status:** Accepted
**Date:** 2026-04-15

## Context

The memory state proxy stores files on S3. The "dreaming" cron flow needs raw
access to the same files (to rewrite/compact them via LLM). Two options:

1. Dreaming flow uses the memory state proxy (high-level interface with
   index rebuild hooks)
2. Dreaming flow mounts the same S3 prefix via plain S3 state proxy

## Decision

**Dual mount**: same S3 prefix, two different state proxy types.

- Agent actors mount via **memory state proxy** → high-level interface
  (write triggers index rebuild)
- Dreaming flow mounts via **plain S3 state proxy** → raw file access,
  can rewrite/delete anything without triggering hooks

## Rationale

- Dreaming flow IS the curator — it should not trigger index rebuilds on
  every intermediate write (it rebuilds the index explicitly at the end)
- Clean separation: agents write through the managed interface, curators
  operate on the raw data
- No new code: plain S3 state proxy already exists, just mount with the
  memory prefix

## Consequences

- Same S3 prefix must be safely accessible from two state proxy types
  concurrently. S3 eventual consistency is acceptable (dreaming flow runs
  infrequently).
- Dreaming flow must rebuild MEMORY.md explicitly before finishing.
