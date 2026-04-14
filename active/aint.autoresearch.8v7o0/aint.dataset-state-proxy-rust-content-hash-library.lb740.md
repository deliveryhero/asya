---
title: Dataset state proxy (Rust content-hash library)
status: open
priority: 1 # high
tags: [autoresearch, state-proxy, dataset, rust]
---

## Context

ML actors need versioned dataset access. No existing tool (DVC, DataChain,
LakeFS) works on state proxy's flat KV interface. Need a custom Rust library
for content-hash-based snapshots and diffs, embedded in a state proxy sidecar.

Full design spec: `design-dataset-state-proxy.md` in this directory.

## Summary

- Rust library (~1900 lines) in a separate repo (`asya-dataset` or `asya-hashfs`)
- Content-hash store with blake3 (integrity) + optional perceptual hashing (images)
- Sharded JSONL metadata (10k entries/shard, scales to 100k+ files)
- Transparent version mounting: actor sees `/dataset/images/img.png`, sidecar
  resolves via manifest for the mounted snapshot version
- Modular `Hasher` trait: blake3 (default), phash/dhash (images), chromaprint (audio)
- `Store` trait (async get/put/list/stat/delete) backed by `object_store` crate
- PyO3/maturin for Python bindings (workbench use), C FFI for Go sidecar

## Deliverables

1. Rust core library: Store, Manifest, Diff, Hasher trait, Blake3
2. Shard I/O: JSONL read/write, manifest JSON
3. Perceptual hashing: image_hasher crate wrapper
4. Python bindings via PyO3
5. State proxy sidecar integration (HTTP server)
6. Tests (~500 lines)
