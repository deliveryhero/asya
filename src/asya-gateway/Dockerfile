FROM golang:1.24-alpine AS builder

WORKDIR /build

# Copy go mod files and download dependencies
COPY go.mod go.sum ./
RUN go mod download && go mod verify

# Install build dependencies
RUN apk add --no-cache git

# Copy source
COPY . .

# Build
RUN CGO_ENABLED=0 GOOS=linux go build -o gateway ./cmd/gateway

# Test image
FROM builder AS tester
WORKDIR /build

# Runtime image
FROM alpine:latest

# Install PostgreSQL client for database operations
RUN apk --no-cache add ca-certificates postgresql-client

WORKDIR /app

COPY --from=builder /build/gateway .
COPY db/ /app/db/

# Default port
ENV ASYA_GATEWAY_PORT=8080

EXPOSE 8080

CMD ["./gateway"]
