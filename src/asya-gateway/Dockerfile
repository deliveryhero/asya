FROM golang:1.25-alpine AS builder

WORKDIR /build

# Copy go mod files and download dependencies
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# Install build dependencies
RUN apk add --no-cache git

# Copy source
COPY . .

# Build all binaries
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -o gateway ./cmd/gateway && \
    CGO_ENABLED=0 GOOS=linux go build -o mesh-api ./cmd/mesh-api

# Test image
FROM builder AS tester
WORKDIR /build

# Runtime image
FROM alpine:latest

# Install PostgreSQL client for database operations
RUN apk --no-cache add ca-certificates postgresql-client

WORKDIR /app

COPY --from=builder /build/gateway .
COPY --from=builder /build/mesh-api .
COPY db/ /app/db/

# Default port
ENV ASYA_GATEWAY_PORT=8080

EXPOSE 8080

CMD ["./gateway"]
