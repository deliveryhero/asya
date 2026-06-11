# KEDA external scalers for Asya. Hosts one binary per scaler (currently
# scaler-pubsub); the binary is selected via a command override in the
# asya-crossplane chart (command: ["/scaler-pubsub"]).
FROM golang:1.25 AS builder
WORKDIR /app

# Cache dependency downloads
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o scaler-pubsub .

FROM gcr.io/distroless/static-debian12

COPY --from=builder /app/scaler-pubsub /scaler-pubsub

ENTRYPOINT ["/scaler-pubsub"]
