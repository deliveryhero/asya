# Build stage
FROM golang:1.24-alpine AS builder

WORKDIR /build

# Copy go mod files and download dependencies
COPY go.mod go.sum ./
RUN go mod download && go mod verify

# Copy source
COPY . .

# Build
ARG TARGETARCH
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH:-amd64} go build -o injector ./cmd/injector

# Runtime stage
FROM gcr.io/distroless/static:nonroot

WORKDIR /

COPY --from=builder /build/injector .

USER 65532:65532

EXPOSE 8443

ENTRYPOINT ["/injector"]
