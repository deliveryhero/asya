# Dataset State Proxy — Design Spec

## Problem

ML actors need to read/write datasets (images + metadata) with versioning,
snapshotting, and diffing. No existing tool (DVC, DataChain, LakeFS, Oxen) works
on Asya's state proxy interface — they all require POSIX features we don't have
(SQLite, rename, hardlinks, file locking, inode-based cache).

We need a **dataset state proxy** that:
- Exposes datasets as plain filesystem to actors (`open("/dataset/img-001.png")`)
- Handles versioning/snapshotting transparently (actor doesn't know about versions)
- Stores data on S3 with content-hash deduplication
- Provides diffing between versions (workbench-facing, not actor-facing)
- Scales to 100k+ images per dataset

## Design Principle

Follows [Design Principle 001](../docs/design-principles/001-fs-like-state-proxy-interface.md):
actor handler code uses `open()`, `os.listdir()`, `os.stat()` — zero SDK imports.
Versioning is invisible at the handler level.

## Architecture

```
Actor handler (Python)
  |
  open("/dataset/images/img-001.png", "rb")
  os.listdir("/dataset/images/")
  |
  v
asya-runtime (builtins.open interception)
  |
  GET /keys/images/img-001.png
  |
  v
dataset-proxy sidecar (Rust library + HTTP server)
  |
  resolves manifest for mounted snapshot
  maps path -> content hash
  fetches blob from S3
  |
  v
S3 bucket
```

## Data Layout on S3

```
s3://datasets-bucket/
  _blobs/
    {blake3-hash}                    # content-addressed blobs (write-once)

  _manifests/
    {dataset-name}/
      v001.json                      # snapshot manifest
      v002.json
      latest -> v002                 # pointer to latest version

  {dataset-name}/
    _meta/
      shards/
        0000.jsonl                   # metadata shard (~10k entries each)
        0001.jsonl
      schema.json                    # field schema for metadata entries
    images/
      {uuid}.png                     # working files (mutable between snapshots)
      {uuid}.json                    # per-image metadata (optional, for simple cases)
```

### Manifest Format

```json
{
  "version": "v002",
  "parent": "v001",
  "created_at": "2026-04-14T12:00:00Z",
  "hash_algorithms": ["blake3"],
  "total_files": 50432,
  "total_bytes": 12345678900,
  "shard_count": 6,
  "shards": [
    {
      "path": "_meta/shards/0000.jsonl",
      "entries": 10000,
      "hash": "abc123..."
    }
  ]
}
```

### Metadata Shard Format (JSONL)

Each line is one file entry:

```json
{"path": "images/abc-123.png", "blake3": "deadbeef...", "size": 102400, "labels": ["cat", "outdoor"], "split": "train"}
{"path": "images/abc-124.png", "blake3": "cafebabe...", "size": 98304, "labels": ["dog", "indoor"], "split": "val"}
```

### Why Sharded Metadata

- One JSON per image: `listdir` + N reads = slow at 100k+ files
- One giant JSON: can't diff in git, can't update atomically, OOM risk
- Sharded JSONL (10k entries per shard): fast to scan, diffable, parallelizable,
  fits in memory. Shard boundaries are stable (based on sorted path prefix)

## Transparent Version Mounting

Actor manifest specifies which snapshot to mount:

```yaml
stateProxy:
  - name: dataset
    mount:
      path: /dataset
    connector:
      image: asya/dataset-proxy:latest
      env:
        - name: DATASET_NAME
          value: "imagenet-subset"
        - name: SNAPSHOT
          value: "v002"           # or "latest"
        - name: STATE_BUCKET
          value: "datasets-bucket"
```

The sidecar:
1. On startup: loads manifest for requested snapshot
2. On `read(path)`: resolves path via manifest → fetches blob from `_blobs/{hash}`
3. On `list(prefix)`: returns paths from manifest matching prefix
4. On `stat(path)`: returns size from manifest
5. On `write(path)`: stores blob to `_blobs/{hash}`, updates working state
   (NOT the snapshot — snapshots are immutable once created)
6. Snapshot creation: triggered by explicit command (xattr or control path)

Actor sees:
```python
# read — transparent, version-resolved
img = open("/dataset/images/abc-123.png", "rb").read()
meta = json.load(open("/dataset/images/abc-123.json"))

# read sharded metadata — for bulk operations
for shard in os.listdir("/dataset/_meta/shards/"):
    for line in open(f"/dataset/_meta/shards/{shard}"):
        entry = json.loads(line)
        # process entry...

# write — goes to working state, not snapshot
with open("/dataset/images/new-img.png", "wb") as f:
    f.write(new_image_bytes)
```

## Core Library (Rust)

Separate repo: `asya-dataset` (or `asya-hashfs`). Embedded in the sidecar.

### Interface

```rust
/// Abstract storage backend (S3, local FS, GCS)
trait Store: Send + Sync {
    async fn get(&self, key: &str) -> Result<Vec<u8>>;
    async fn put(&self, key: &str, data: &[u8]) -> Result<()>;
    async fn list(&self, prefix: &str) -> Result<Vec<String>>;
    async fn stat(&self, key: &str) -> Result<Option<u64>>;  // size
    async fn delete(&self, key: &str) -> Result<()>;
}

/// Single file entry in a manifest
struct Entry {
    path: String,
    size: u64,
    hashes: BTreeMap<String, Vec<u8>>,   // algo_name -> hash bytes
    metadata: Option<serde_json::Value>,  // inline metadata (labels, split, etc.)
}

/// Immutable snapshot manifest
struct Manifest {
    version: String,
    parent: Option<String>,
    created_at: DateTime<Utc>,
    entries: Vec<Entry>,    // sorted by path for stable sharding
}

/// Diff between two manifests
struct Diff {
    added: Vec<String>,     // paths in new but not old
    removed: Vec<String>,   // paths in old but not new
    modified: Vec<String>,  // same path, different hash
}

/// Core operations
impl Manifest {
    /// Create snapshot: walk store, hash all files, produce manifest
    async fn snapshot(store: &dyn Store, prefix: &str, hashers: &[Box<dyn Hasher>]) -> Result<Self>;

    /// Diff two manifests
    fn diff(old: &Manifest, new: &Manifest) -> Diff;

    /// Serialize/deserialize
    fn to_json(&self) -> String;
    fn from_json(s: &str) -> Result<Self>;
}
```

### Modular Hashing

```rust
trait Hasher: Send + Sync {
    fn hash(&self, data: &[u8]) -> Vec<u8>;
    fn name(&self) -> &str;   // used as key in Entry.hashes
}

// Content integrity — default, always enabled
struct Blake3Hasher;

// Perceptual — images, optional
struct PHashImageHasher;     // 64-bit perceptual hash
struct DHashImageHasher;     // 64-bit difference hash

// Audio — optional
struct ChromaprintHasher;

// Custom — teams bring their own
// Implement Hasher trait, register at sidecar startup
```

Multiple hashers can run per snapshot. The manifest stores all computed hashes:
```json
{"path": "img.png", "blake3": "abc...", "phash": "0xfe34...", "size": 1024}
```

This enables:
- **Integrity checking**: blake3 (always)
- **Near-duplicate detection**: phash hamming distance < threshold
- **Format-agnostic dedup**: same content in PNG vs JPEG detected by phash

### Performance Considerations

- **blake3**: >1 GB/s on modern CPUs (SIMD), tree-hashable for parallelism
- **Parallel hashing**: snapshot creation fans out across N files using tokio tasks
- **Streaming**: blobs are hashed while being read, not loaded fully into memory
- **Size pre-filter**: only re-hash files whose size changed since last snapshot
- **Shard-level caching**: sidecar caches parsed shards in memory after first load

### Estimated Scope

- Core library (Store, Manifest, Diff, Hasher trait, Blake3): ~600 lines Rust
- Shard I/O (read/write JSONL shards, manifest JSON): ~200 lines
- Perceptual hashing (image_hasher crate wrapper): ~100 lines
- Python bindings (PyO3/maturin): ~200 lines
- HTTP sidecar integration: ~300 lines
- Tests: ~500 lines
- **Total: ~1900 lines**

### Key Crates

- `blake3` — fast content hashing
- `object_store` (Apache Arrow) — S3/GCS/local abstraction, 55M downloads
- `image` + `img_hash` — perceptual hashing
- `serde` + `serde_json` — serialization
- `pyo3` + `maturin` — Python bindings
- `tokio` — async runtime

## Workbench-Facing Operations

The workbench user (Claude Code on VM or local) accesses datasets differently
from actors. They mount S3 via state proxy (or FUSE/Mountpoint) and use the
Python bindings directly:

```python
from asya_dataset import Dataset

ds = Dataset("/datasets/imagenet-subset")

# Create snapshot
ds.snapshot("v003", hashers=["blake3", "phash"])

# Diff
changes = ds.diff("v002", "v003")
print(f"Added: {len(changes.added)}, Modified: {len(changes.modified)}")

# Search by metadata
cats = ds.filter(lambda e: "cat" in e.get("labels", []))

# Find near-duplicates (perceptual hash)
dupes = ds.find_similar("images/abc-123.png", threshold=0.9, hash_algo="phash")
```

## Operations Summary

| Operation | Actor (state proxy) | Workbench (Python lib) |
|---|---|---|
| Read file | `open("/dataset/img.png")` | `open("/dataset/img.png")` |
| Write file | `open("/dataset/img.png", "wb")` | `open("/dataset/img.png", "wb")` |
| List files | `os.listdir("/dataset/images/")` | `os.listdir(...)` or `ds.list()` |
| Create snapshot | N/A (infrastructure) | `ds.snapshot("v003")` |
| Diff versions | N/A | `ds.diff("v002", "v003")` |
| Search metadata | Read shards manually | `ds.filter(...)` |
| Find duplicates | N/A | `ds.find_similar(...)` |

## Open Questions

1. **Snapshot trigger from actors**: Should actors be able to create snapshots?
   Currently only workbench can. If yes, via xattr (`os.setxattr("/dataset/",
   "user.asya.snapshot", "v003")`) or control file
   (`open("/dataset/_control/snapshot", "w").write("v003")`)?

2. **Concurrent writes**: Multiple actors writing to same dataset working state.
   S3 is eventually consistent for overwrites. Do we need CAS for metadata shards?

3. **Garbage collection**: Blobs in `_blobs/` unreferenced by any manifest. Periodic
   GC job, or reference-counted?

4. **Large file streaming**: For multi-GB model checkpoints, the sidecar shouldn't
   buffer the entire blob in memory. Stream-through from S3 to the Unix socket.

5. **Integration with git**: Metadata shards could be committed to git (small JSONL
   files). Manifest pointers (like DVC's `.dvc` files) in git. How to automate this?
