# Stage 1: pg-kv (CGO disabled — smallest binary, no C runtime needed)
FROM golang:1.25-alpine AS builder-pg
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
FROM golang:1.25 AS builder-pvc
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
COPY --from=builder-pg  /pg-kv  /pg-kv
COPY --from=builder-pvc /pvc-kv /pvc-kv
ENTRYPOINT ["/pg-kv"]
