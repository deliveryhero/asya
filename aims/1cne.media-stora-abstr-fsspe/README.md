---
title: Media Storage Abstraction (fsspec)
status: open
priority: 3
type: epic
---

Asya actors process media files (images, videos) but currently lack a standard way to abstract storage paths like `s3://bucket/session123/`. This epic introduces a storage abstraction layer using `fsspec` with `DirFileSystem`, enabling handlers to work with simple filenames while the session context is extracted from the Asya payload. An alternative approach using `cloudpathlib` with `pathlib`-style syntax is also evaluated.

## RFC: Media Storage Abstraction

For your use case with the **Asya** framework (Delivery Hero's AI-focused actor mesh on Kubernetes), the most effective way to abstract away storage paths like `s3://bucket/session123/` and work with just filenames is to use a **Storage Abstraction Layer** within your Python handlers.

Since Asya encourages "pure Python functions" and is intentionally stateless regarding data storage, you need a slim SDK that can be initialized with a "session context" extracted from the Asya payload.

### The Best "Slim SDK": `fsspec` (with `DirFileSystem`)
`fsspec` (Filesystem Specification) is the industry standard in the Python AI/ML ecosystem (used by Pandas, Dask, and Hugging Face). It is lightweight and has a specific feature for your exact problem: **`DirFileSystem`**.
- **How it works:** You create a filesystem object that is "locked" into a specific S3 prefix.
- **Code Example for Asya Handler:**
```
import fsspec
from fsspec.implementations.dirfs import DirFileSystem

def process(payload: dict) -> dict:
    # 1. Extract session/bucket context from Asya payload
    bucket = payload.get("bucket", "default-bucket")
    session_id = payload.get("session_id")
    base_path = f"s3://{bucket}/{session_id}/"

    # 2. Abstract the path: Everything inside 'fs' is now relative to base_path
    fs = DirFileSystem(base_path)

    # 3. Work with just filenames
    # Worker 1: Write
    with fs.open("video.mp4", "wb") as f:
        f.write(generate_video_content())

    # Worker 2: Read
    # (Another worker receives the same session_id and does the same setup)
    with fs.open("video.mp4", "rb") as f:
        data = f.read()

    return {**payload, "status": "processed"}
```

### 2. Alternative: `cloudpathlib`
If you prefer the Python `pathlib` syntax, `cloudpathlib` is a slim wrapper that makes S3 feel like a local disk.
- **Abstraction:** You define a `S3Path` as your root and use the `/` operator to join filenames.
- **Snippet:**
    ```
    from cloudpathlib import S3Path

    root = S3Path(f"s3://{bucket}/{session_id}")
    video_file = root / "video.mp4" # Still feels like a filename
    video_file.write_bytes(content)
    ```




#### The Power User Trade-off (`fsspec`)

Uses boto3 under the hood.

**fsspec** is essentially the "plumbing" of the Python data world. It is faster because it allows for **lazy loading**.
- **Pros:** If your AI actor only needs to read the metadata of a 2GB video or a specific frame, `fsspec` can fetch just those bytes without downloading the whole file. It is the engine behind `pandas.read_parquet` and `xarray`.
- **Cons:** The API is "file-like" but not always "path-like." You deal with open file handles and buffer objects rather than simple path strings.
- [link nvidia](https://developer.nvidia.com/blog/optimizing-access-to-parquet-data-with-fsspec/)
