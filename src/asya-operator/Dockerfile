# Build stage
FROM golang:1.23-alpine AS builder

WORKDIR /build

# Copy go mod files
COPY asya-operator/go.mod asya-operator/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# Copy the go source
COPY asya-operator/cmd/ cmd/
COPY asya-operator/api/ api/
COPY asya-operator/internal/ internal/

# Build
ARG TARGETARCH
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH:-amd64} go build -o manager cmd/main.go

# Copy runtime script directly (symlink target is now accessible in build context)
COPY --chown=65532:65532 asya-runtime/asya_runtime.py /tmp/asya_runtime.py

# Runtime stage
FROM gcr.io/distroless/static:nonroot

WORKDIR /
COPY --from=builder /build/manager .
COPY --from=builder --chown=65532:65532 /tmp/asya_runtime.py /runtime/asya_runtime.py

USER 65532:65532

ENTRYPOINT ["/manager"]
