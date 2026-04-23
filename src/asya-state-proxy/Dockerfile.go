# Stage 1: pg-kv (CGO disabled — smallest binary, no C runtime needed)
# Named "builder" to preserve compatibility with component tests that use
# `target: builder` to run `go run ./cmd/pg-kv/` in development mode.
FROM golang:1.25-alpine AS builder
ENV GOTOOLCHAIN=local
WORKDIR /app/go

COPY go/go.mod go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY go/ .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o /pg-kv ./cmd/pg-kv/

# Stage 2: pvc-kv (CGO enabled — requires DuckDB via go-duckdb)
# golang:1.25-bookworm pins Debian 12 (glibc 2.36) to match the kind node.
FROM golang:1.25-bookworm AS builder-pvc
ENV GOTOOLCHAIN=local
WORKDIR /app/go

COPY go/go.mod go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY go/ .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=1 GOOS=linux go build -o /pvc-kv ./cmd/pvc-kv/

# Final image: debian-slim provides glibc required by the DuckDB runtime
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder     /pg-kv  /pg-kv
COPY --from=builder-pvc /pvc-kv /pvc-kv
ENTRYPOINT ["/pg-kv"]
