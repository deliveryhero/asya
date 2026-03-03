---
title: "Merge asya-dlq-worker image into asya-crew (multi-stage build, shared image with command override)"
priority: 2 # medium
type: task
---

## Motivation

Reduce the number of published container images from 7 to 6. The dlq-worker Go binary
already lives inside `src/asya-crew/cmd/dlq-worker/` — there's no reason for a separate
Docker image. The binary can be included in the `asya-crew` image via multi-stage build
and run with a `command:` override in the Helm chart.

Failure domain isolation is preserved: the Go binary still uses native AWS SDK, runs as
a standalone K8s Deployment, and shares zero code with the sidecar.

## Changes

1. **`src/asya-crew/Dockerfile`** — add Go builder stage:
   ```dockerfile
   FROM golang:1.24-alpine AS go-builder
   WORKDIR /build
   COPY cmd/dlq-worker/go.mod cmd/dlq-worker/go.sum ./
   RUN go mod download
   COPY cmd/dlq-worker/ .
   RUN CGO_ENABLED=0 go build -o /dlq-worker .
   ```
   Then in the final stage: `COPY --from=go-builder /dlq-worker /usr/local/bin/dlq-worker`

2. **`deploy/helm-charts/asya-crew/templates/dlq-worker.yaml`** — use crew image with
   command override instead of separate dlq-worker image:
   ```yaml
   image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
   command: ["/usr/local/bin/dlq-worker"]
   ```

3. **`deploy/helm-charts/asya-crew/values.yaml`** — remove separate `dlqWorker.image`
   section (dlq-worker uses the same image as crew actors)

4. **`src/build-images.sh`** — remove `asya-dlq-worker` from `ALL_IMAGES` array and
   `get_build_context()` case statement

5. **`.github/workflows/release.yml`** — remove `asya-dlq-worker` from build/tag lists
   (it was already missing from the `:latest` tagging step — that's a pre-existing bug)

6. **Delete** `src/asya-crew/cmd/dlq-worker/Dockerfile` — no longer needed

7. **`testing/e2e/`** — update any Kind image loading to remove dlq-worker

## Verification

- `make build-images` builds 6 images (not 7)
- `asya-crew` image contains `/usr/local/bin/dlq-worker` binary
- Helm template renders dlq-worker Deployment with crew image + command override
- DLQ worker E2E tests pass (currently xfailed, but Helm template should render correctly)
- `make test-unit` passes for both crew (Python) and dlq-worker (Go)
