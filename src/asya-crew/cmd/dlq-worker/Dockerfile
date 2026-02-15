FROM golang:1.24 AS builder

WORKDIR /app

# Cache dependency downloads
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o dlq-worker .

FROM gcr.io/distroless/static-debian12

COPY --from=builder /app/dlq-worker /dlq-worker

ENTRYPOINT ["/dlq-worker"]
