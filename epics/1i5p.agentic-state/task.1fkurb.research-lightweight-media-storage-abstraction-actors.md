---
title: "Research: Lightweight media storage abstraction for actors"
status: open
priority: 2 # medium
type: task
---


Design media storage abstraction for Asya actors (images, video, audio).

**Constraints:**
- K8s-native (no non-K8s infrastructure)
- No pip distribution (actors use pre-existing tools)
- AI/agentic focus (large files, streaming, partial reads)
- Lightweight SDK in handlers

**Options to evaluate:**
- fsspec + DirFileSystem (industry standard, lazy loading)
- cloudpathlib (pathlib-like API)
- Direct S3/GCS SDK with helper functions

**Deliverables:**
- Evaluate options against constraints
- Recommend approach
- Document integration pattern for handlers

RFC: docs/rfc/asya-z1o-media-storage.md


---
## Notes

## Session Discussion Takeaways (2026-01-28)

- Artifact references are MANDATORY for media, not optional
- Images/video/audio NEVER sent inline as blobs
- This is a hard architectural decision, not a compression strategy
- Enables message-truth for conversation state while media lives in S3/GCS
- Key constraint: no pip distribution, must use pre-existing K8s-native tools
- fsspec with DirFileSystem is leading candidate (industry standard in ML ecosystem)
- cloudpathlib as alternative (pathlib-like API)


---
_Migrated from beads `asya-z1o`_
