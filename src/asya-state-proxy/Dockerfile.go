# Combined Go state-proxy image: pg-kv, s3-kv, gcs-kv.
# go-duckdb (used by s3-kv and gcs-kv) bundles a pre-built DuckDB library
# requiring glibc >= 2.38, so we use golang:1.25 (bookworm) + ubuntu:24.04.
FROM golang:1.25 AS builder
ENV GOTOOLCHAIN=local
WORKDIR /app/go

COPY go/go.mod go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY go/ .

# pg-kv: pure Go, no CGO required.
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o /pg-kv ./cmd/pg-kv/

# s3-kv + gcs-kv: require CGO for go-duckdb.
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=1 GOOS=linux go build -o /s3-kv ./cmd/s3-kv/

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=1 GOOS=linux go build -o /gcs-kv ./cmd/gcs-kv/

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /pg-kv /pg-kv
COPY --from=builder /s3-kv /s3-kv
COPY --from=builder /gcs-kv /gcs-kv

USER nobody
# Default entrypoint: pg-kv. Override with command: ["/s3-kv"] or ["/gcs-kv"]
# in the Helm chart when using s3kv or gcskv backends.
ENTRYPOINT ["/pg-kv"]
