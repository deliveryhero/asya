# Shared State Collaboration (Agent + Asya via State-Proxy)

## Use-Case

A team of developers or researchers, each with their own local AI agent
(Claude Code, Goose, etc.), shares a knowledge base of findings, experiment
results, and decisions. Asya pipelines process team-wide aggregation tasks;
local agents read/write shared state.

Also: an external agent runs a long pipeline on Asya and needs to inspect
intermediate artifacts — model weights, generated reports, cached tool
results — without waiting for the pipeline to complete.

## Why Asya

- **State-proxy abstracts storage**: Actors read/write via standard Python
  `open()`. Backend is S3/GCS/Redis, selected per mount. External agents
  access the same bucket via cloud SDK or presigned URLs.
- **CAS for conflict detection**: `buffered-cas` mode uses ETags (S3) or
  generation numbers (GCS) to detect concurrent modifications. Two agents
  writing to the same key get `FileExistsError` — no silent data loss.
- **Presigned URLs via xattr**: Actors can generate time-limited URLs for
  external access: `os.getxattr("/state/report.pdf", "user.asya.presigned_url")`
- **TTL on Redis**: Cache entries auto-expire via `os.setxattr(..., "user.asya.ttl", b"3600")`
- **No StatefulSets**: Actors remain stateless Deployments. State lives in
  the storage backend, not on local disk.

## Architecture

```
Developer A (Claude Code)              Asya Cluster
+-------------------+                 +-------------------+
| Local agent       |   S3 / GCS     | Actor pods        |
|   reads/writes    | <============> |   read/write via  |
|   shared bucket   |   (same bucket)|   state-proxy     |
+-------------------+                +-------------------+
                                           |
Developer B (Goose)                   State-Proxy Sidecar
+-------------------+                      |
| Local agent       |                 S3 / GCS / Redis
|   reads/writes    | <============>  (shared bucket)
|   shared bucket   |
+-------------------+
```

## Example: Shared Research Knowledge Base

**Asya pipeline** (nightly aggregation):
```python
@flow
async def aggregate_findings(p):
    p = await scan_new_findings(p)    # reads /state/findings/*.json
    p = await cross_reference(p)       # finds contradictions
    p = await generate_summary(p)      # writes /state/summaries/latest.json
    return p
```

**Local agent** (developer's Claude Code):
```bash
# Developer asks Claude Code to check latest research summary
aws s3 cp s3://team-research/summaries/latest.json - | jq .

# Developer saves a finding for the team
echo '{"topic": "...", "finding": "..."}' | \
  aws s3 cp - s3://team-research/findings/2026-03-31-alice.json
```

## Example: Pipeline Artifact Inspection

**During pipeline execution**, an actor stores intermediate results:
```python
async def analysis_actor(payload):
    results = await heavy_computation(payload)

    # Store for external inspection
    with open("/state/artifacts/analysis.json", "w") as f:
        json.dump(results, f)

    # Generate presigned URL for external agents
    url = os.getxattr("/state/artifacts/analysis.json", "user.asya.presigned_url")
    payload["artifact_url"] = url.decode()

    return payload
```

**External agent** reads the artifact via presigned URL without cloud creds.
