FROM golang:1.25-alpine AS builder
WORKDIR /app/go

COPY go/go.mod go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY go/ .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o /pg-kv ./cmd/pg-kv/

FROM alpine:3.20
RUN apk --no-cache add ca-certificates
COPY --from=builder /pg-kv /pg-kv
ENTRYPOINT ["/pg-kv"]
